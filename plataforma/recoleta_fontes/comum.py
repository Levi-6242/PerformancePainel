# -*- coding: utf-8 -*-
"""O contrato comum da recoleta por fonte (o que a Coletas do Nexus lê) e as regras que valem para todas.

Resposta de POST /api/recoleta/<fonte>:
    {"geracao":  [{"usina", "inversor", "data", "kwh"}],          usina = aba do BD; inversor = coluna do BD
     "escalares": [{"usina", "data", "coluna", "valor"}],          coluna = o cabeçalho do BD quando a fonte sabe
                                                                    ("IPOA (kWh/m²) ETM" da Athon) ou o apelido
                                                                    "IPOA" | "GHI" | "Chuva" (AbaBD.col do Conversor
                                                                    casa os dois)
     "avisos":   [texto], "dias_fora": [{"usina", "data"}],
     "consultas": n, "cota_restante": n | None, "teto": n | None}
É o formato das abas Geracao_Inversor e Escalares que os coletores do PC já geram (coleta API PV/src), com os nomes já
traduzidos pela aba Equipamentos do BD_Performance — o mesmo de-para da coleta.

Regras (as da coleta e as do Levi):
- nulo é nulo, nunca 0 (06/11: "sem dado não se inventa");
- dia em que menos da metade dos inversores da usina veio com valor > 0 é FONTE FORA DO AR, não geração zero (a trava do
  dia zerado do preencher_bd_thopen, 05/09/2026: a apipv devolveu eday=0 para todos os inversores de um dia fechado e o
  gravador apagou 67 usinas): vai em `dias_fora` e em avisos, e a Coletas não sugere esse dia;
- equipamento da fonte sem de-para na aba Equipamentos vira aviso, não some;
- só dia fechado no fuso de Brasília; no máximo MAX_DIAS por pedido (a Coletas fatia).
"""
import datetime as dt
import re
import threading
import unicodedata

MAX_DIAS = 7
_CONTA = {}                      # (conta, dia) -> consultas gastas hoje
# Fontes que gastam a MESMA conta dividem o teto: a chuva é a consulta meteo da conta principal da API PV.
CONTA_DE = {"chuva": "apipv"}
_LOCK = threading.Lock()


class Recusa(Exception):
    def __init__(self, status, texto):
        super().__init__(texto)
        self.status = status


def hoje_br(agora_utc=None):
    """O servidor roda em UTC: às 22h de Brasília já é amanhã lá."""
    agora_utc = agora_utc or dt.datetime.now(dt.timezone.utc)
    return (agora_utc - dt.timedelta(hours=3)).date()


def chave_nome(nome):
    """A chave de nome do coletor (`coletar_pvoperation.chave_nome`): sem o " (NNN)" do supervisório, sem acento, sem
    espaço, sem caixa. A API escreve "Ceilandia 1.1 (89)" e o cadastro "Ceilândia 1.1 (89)"; a Rodrigues 2 virou
    "INVERSOR01" em ~20/08/2026 e parou de coletar em silêncio."""
    s = re.sub(r"\s*\(\d+\)\s*$", "", str(nome or "")).strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"\s+", "", s).lower()


class Mapa:
    """O de-para da aba Equipamentos: (usina do supervisório, equipamento do supervisório) -> (aba do BD, coluna).
    Duas grafias diferentes que caem na mesma chave e apontam para destinos diferentes não casam (o MapaNomes do
    coletor faz igual): não se adivinha."""

    def __init__(self, linhas):
        """linhas: dicts com "Usina Supervisório", "Equipamento Supervisório", "Usina", "Equipamento"."""
        self.inv, self.usina, self._amb = {}, {}, set()
        self.inv_por_usina = {}
        for r in linhas:
            us, u = str(r.get("Usina Supervisório") or "").strip(), str(r.get("Usina") or "").strip()
            if not us or not u or us.lower() == "nan" or u.lower() == "nan":
                continue
            self._pos(self.usina, chave_nome(us), u)
            es, e = str(r.get("Equipamento Supervisório") or "").strip(), str(r.get("Equipamento") or "").strip()
            if es and e and es.lower() != "nan" and e.lower() != "nan":
                e = re.sub(r"(\d),(\d)", r"\1.\2", e)          # "Inversor 6,2" (Cascavel) = "Inversor 6.2"
                self._pos(self.inv, (chave_nome(us), chave_nome(es)), (u, e))
                self.inv_por_usina.setdefault(u, set()).add(e)

    def _pos(self, d, k, v):
        if k in self._amb:
            return
        if k in d and d[k] != v:
            del d[k]
            self._amb.add(k)
            return
        d[k] = v

    def usina_de(self, usina_sup):
        return self.usina.get(chave_nome(usina_sup))

    def inversor_de(self, usina_sup, equip_sup):
        return self.inv.get((chave_nome(usina_sup), chave_nome(equip_sup)))


# A aba do BD quando o cadastro escreve diferente: cópia do `mapeamento.RENOMES`/`rotear` do coletor (coleta API PV/src),
# cada linha com o caso que a criou lá. Mudou lá, muda aqui.
RENOMES = {
    "Rondonópolis": "Rondonopolis", "Nova Londrina": "Nova Londrina 1", "Poconé 1": "Poconé",
    "São Bento do Una": "Bento da Una", "Bernardino de Campos": "Bernardino",
    "Primavera 1": "Primavera", "Primavera 2": "Primavera", "Santana do Ipanema": "Santana", "Saturnino 1": "Saturnino",
    "Cipó-Guaçu 1": "Cipó", "Cipó-Guaçu 2": "Cipó", "Cipó-Guaçu 3": "Cipó",
    "Corrego Sapucaia 1": "Córrego", "Corrego Sapucaia 2": "Córrego", "Corrego do Sapucaia": "Córrego",
    "Piracicaba I": "Piracicaba 1", "Marajoara I": "Marajoara 1",       # romano no cadastro, arábico na aba (31/08)
    "Santo Anastacio": "Santo Anastácio",                                # sem acento no cadastro (11/09)
    "Nova Londrina 2": "Nova Londrina 1",                                # a cabine 2 mora na aba da 1 (11/09)
}


def rotear(usina, inversor):
    """(aba, coluna) no BD_Thopen, como o coletor grava. Ouro Branco: o prefixo do inversor é a aba ("Inversor 2.3" ->
    aba "Ouro Branco 2", coluna "Inversor 1.3")."""
    usina, inversor = str(usina or "").strip(), str(inversor or "").strip()
    if usina == "Ouro Branco":
        m = re.match(r"Inversor\s+(\d+)\.(\d+)", inversor)
        return ("Ouro Branco %s" % m.group(1), "Inversor 1.%s" % m.group(2)) if m else None
    return RENOMES.get(usina, usina), inversor


def abas_de(usina, mapa):
    """As abas do BD_Thopen de uma usina do cadastro (a Ouro Branco vira duas)."""
    if usina == "Ouro Branco":
        return sorted({r[0] for r in (rotear(usina, i) for i in mapa.inv_por_usina.get(usina, ())) if r})
    return [RENOMES.get(usina, usina)]


def mapa_do_df(df):
    """Mapa a partir do DataFrame da aba (o `_equipamentos_df` do app.py, com o Nexus por cima)."""
    cols = ["Usina Supervisório", "Equipamento Supervisório", "Usina", "Equipamento"]
    return Mapa(dict(zip(cols, (r.get(c) for c in cols))) for r in df.to_dict("records"))


def validar(corpo, ids_validos, max_plantas, hoje=None):
    """(ids, dias, geracao, etm, chuva, simular) ou Recusa(400)."""
    hoje = hoje or hoje_br()
    try:
        ids = [str(x) for x in (corpo.get("ids") or [])]
        ini = dt.date.fromisoformat(str(corpo.get("ini")))
        fim = dt.date.fromisoformat(str(corpo.get("fim")))
    except (TypeError, ValueError):
        raise Recusa(400, "pedido inválido: ids, ini e fim (AAAA-MM-DD)")
    geracao, etm, chuva = bool(corpo.get("geracao")), bool(corpo.get("etm")), bool(corpo.get("chuva"))
    if not ids or not (geracao or etm or chuva):
        raise Recusa(400, "escolha a usina e pelo menos Geração, ETM ou Chuva")
    ids = list(dict.fromkeys(ids))
    if len(ids) > max_plantas:
        raise Recusa(400, "no máximo %d plantas por pedido" % max_plantas)
    fora = sorted(set(ids) - {str(i) for i in ids_validos})
    if fora:
        raise Recusa(400, "planta(s) que esta fonte não conhece: %s" % ", ".join(fora))
    if fim < ini:
        raise Recusa(400, "período ao contrário")
    if fim >= hoje:
        raise Recusa(400, "só dia fechado: o período vai até ontem (%s)" % (hoje - dt.timedelta(days=1)).isoformat())
    n = (fim - ini).days + 1
    if n > MAX_DIAS:
        raise Recusa(400, "no máximo %d dias por pedido (a Coletas fatia o período)" % MAX_DIAS)
    dias = [ini + dt.timedelta(days=k) for k in range(n)]
    return ids, dias, geracao, etm, chuva, bool(corpo.get("simular"))


def gastar(fonte, n, teto, hoje=None):
    """Reserva n consultas do teto do dia da fonte (somando todos os pedidos); Recusa(429) se não couber. Devolve o
    que resta. Teto None = fonte sem cota."""
    fonte = CONTA_DE.get(fonte, fonte)
    if not teto or not n:
        return None if not teto else teto - _CONTA.get((fonte, hoje or hoje_br()), 0)
    hoje = hoje or hoje_br()
    with _LOCK:
        usado = _CONTA.get((fonte, hoje), 0)
        if usado + n > teto:
            raise Recusa(429, "teto de %d consultas por dia da recoleta por %s atingido (%d usadas hoje); tente amanhã"
                         % (teto, fonte, usado))
        _CONTA[(fonte, hoje)] = usado + n
        return teto - usado - n


def restante(fonte, teto, hoje=None):
    return None if not teto else teto - _CONTA.get((CONTA_DE.get(fonte, fonte), hoje or hoje_br()), 0)


def dias_fora(geracao, mapa=None):
    """[(usina, data)] em que menos da metade dos inversores DEVOLVIDOS pela fonte veio com valor > 0 (as fontes devolvem
    o inversor sem leitura como nulo). É a régua da trava do coletor (`com_valor < 0.5 * len(ger)`, sobre o que a coleta
    trouxe), por usina × dia; contar pelo cadastro marcaria como fora o pedido de PARTE de uma aba (uma UG das três da
    Ipixuna). Usina com a maioria parada de verdade (Crateus, 40 de 50 em 11/2026) também cai aqui: a Coletas mostra o
    aviso e a pessoa decide."""
    vistos, com = {}, {}
    for r in geracao:
        k = (r["usina"], r["data"])
        vistos.setdefault(k, set()).add(r["inversor"])
        if isinstance(r.get("kwh"), (int, float)) and r["kwh"] > 0:
            com.setdefault(k, set()).add(r["inversor"])
    return [k for k in sorted(vistos) if len(com.get(k, ())) < 0.5 * len(vistos[k])]


def montar_resposta(res, mapa, consultas, cota_restante, teto):
    geracao = res.get("geracao") or []
    fora = dias_fora(geracao, mapa) if geracao else []        # o nulo conta como "sem valor" na régua do dia
    avisos = list(res.get("avisos") or [])
    # Nulo não vai na resposta: a Coletas cola o que vem, e linha vazia por cima de dado seria apagar (0 nunca cobre
    # dado; sem dado não se inventa). Todas as fontes saem iguais; a contagem fica no aviso.
    n_nulos = sum(1 for r in geracao if not isinstance(r.get("kwh"), (int, float)))
    esc = res.get("escalares") or []
    n_nulos += sum(1 for r in esc if not isinstance(r.get("valor"), (int, float)))
    geracao = [r for r in geracao if isinstance(r.get("kwh"), (int, float))]
    res = dict(res, escalares=[r for r in esc if isinstance(r.get("valor"), (int, float))])
    if n_nulos:
        avisos.append("%d valor(es) sem leitura na fonte ficaram de fora (nulo, não 0)" % n_nulos)
    for u, d in fora:
        avisos.append("%s %s: fonte fora do ar no dia (menos da metade dos inversores com valor); não sugerir"
                      % (u, d))
    return {"geracao": geracao, "escalares": res.get("escalares") or [], "avisos": avisos,
            "dias_fora": [{"usina": u, "data": d} for u, d in fora],
            "consultas": consultas, "cota_restante": cota_restante, "teto": teto}
