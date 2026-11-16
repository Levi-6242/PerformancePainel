# -*- coding: utf-8 -*-
"""Sala de controle da Performance (`/painel/sala-de-controle`), entrega 3 (16/11/2026): o que a tela precisava e a
plataforma ainda não dizia. Só regra, sem Flask: quem liga às rotas (`/api/sala/*`) é o `app.py`.

1. A IDADE REAL da string parada. Levi: "Tem muitas strings que estão abertas há muito tempo [...] eu nem sei há quanto
   tempo está aberto". O pacote de falhas é do mês: quem já vinha parado no dia 1 aparecia como "desde antes deste mês".
   `idade_real` segue o episódio para trás, de mês em mês, enquanto houver pacote publicado.
2. O VISTO por pessoa. Levi: "ocorrência nova. E aí quando eu clico para ver, já some"; e todos veem quem já viu, para não
   abrir OS em dobro. `Vistos` guarda quem viu o quê e desde quando cada pessoa olha a tela.
3. CONFERIR FONTES: qual usina do SCADA da Grid é a segunda fonte de uma usina do Tempo real (`usinas_do_scada`), e a
   leitura de agora dela, inversor a inversor (`leituras_para_conferir`).
"""
import json
import os
import re
import threading
import unicodedata
from datetime import date, datetime, timedelta

# ── 1. A idade real ───────────────────────────────────────────────────────────────────────────────────────────────

def _chave_str(e) -> str:
    return f"{e.get('usina')}|{e.get('inversor')}|{e.get('string')}"


def idade_real(pacotes) -> dict:
    """`pacotes` = os pacotes de falhas do mais novo (o mês corrente) ao mais antigo, cada um o JSON do mês (`periodo`,
    `strings.episodios`). → {"strings": {"usina|inversor|string": {"d0", "inicio", "antes"}}, "ate": <1º dia olhado>}.

    Só entra o episódio que COMEÇA no 1º dia do mês corrente (os outros o pacote do mês já data certo). Ele é a
    continuação do mês anterior quando lá a mesma string tem um episódio que vai até o ÚLTIMO dia daquele pacote; aí
    vale o começo dele, e a busca segue para trás se ele também começa no dia 1. `antes` = a cadeia chegou ao 1º dia do
    pacote mais antigo publicado: a string já vinha parada de antes dele, e a tela diz "desde antes de <mês>" em vez de
    inventar uma data. Buraco entre os meses (voltou no dia 30, parou de novo no dia 1) NÃO é continuação: são paradas
    diferentes."""
    pacotes = [p for p in (pacotes or []) if isinstance(p, dict) and (p.get("periodo") or [None])[0]]
    if not pacotes:
        return {"strings": {}, "ate": None}
    atual = pacotes[0]
    d1 = atual["periodo"][0]
    fila = {}
    for e in ((atual.get("strings") or {}).get("episodios") or []):
        if e.get("d0") == d1:
            fila[_chave_str(e)] = {"d0": e["d0"], "inicio": e.get("inicio") or e["d0"], "antes": True}
    ate = d1
    vivos = set(fila)
    for p in pacotes[1:]:
        ini, fim = p["periodo"][0], p["periodo"][-1]
        # meses colados: o pacote anterior tem de acabar na véspera do começo do que já foi seguido
        if (date.fromisoformat(ate) - date.fromisoformat(fim)).days != 1:
            break
        ate = ini
        ate_o_fim = {}
        for e in ((p.get("strings") or {}).get("episodios") or []):
            if e.get("d1") == fim:
                ate_o_fim[_chave_str(e)] = e
        seguem = set()
        for k in vivos:
            e = ate_o_fim.get(k)
            if not e:
                fila[k]["antes"] = False            # a parada começou mesmo no dia 1 do mês seguinte
                continue
            fila[k]["d0"], fila[k]["inicio"] = e["d0"], e.get("inicio") or e["d0"]
            if e["d0"] == ini:
                seguem.add(k)                       # também vinha do mês anterior a este
            else:
                fila[k]["antes"] = False
        vivos = seguem
        if not vivos:
            break
    return {"strings": fila, "ate": ate}


# ── 2. O visto por pessoa ─────────────────────────────────────────────────────────────────────────────────────────
CHAVE_MAX, CHAVES_POR_PEDIDO, GUARDA_DIAS = 200, 400, 90
_RX_CHAVE = re.compile(r"^[st]\|[^\x00-\x1f]{3,190}\|\d{4}-\d{2}-\d{2}$")
SEM_IDENTIDADE = "(senha)"          # a senha compartilhada não diz quem é: todos que entram por ela são "uma pessoa"


def chave_valida(k) -> str | None:
    """`s|usina|inversor|string|AAAA-MM-DD` (a string que parou, pelo começo real) ou `t|usina|tracker|AAAA-MM-DD`."""
    k = " ".join(str(k or "").split())
    return k if len(k) <= CHAVE_MAX and _RX_CHAVE.match(k) else None


class Vistos:
    """Quem viu o quê, num arquivo JSON da máquina (como as notas do relatório semanal: só o processo web escreve, com
    trava e troca atômica). {"pessoas": {id: {"nome", "desde"}}, "vistos": {chave: {id: "AAAA-MM-DD HH:MM"}}}.

    `desde` de cada pessoa = a 1ª vez que ela abriu a tela: o que parou ANTES disso não é novidade para ela (a tela não
    acorda com o mês inteiro pulsando). O que parar depois fica "novo" até ela abrir, sem prazo."""

    def __init__(self, caminho, gravar_atomico=None):
        self.caminho = caminho
        self._trava = threading.Lock()
        self._troca = gravar_atomico or os.replace

    def _ler(self) -> dict:
        try:
            with open(self.caminho, encoding="utf-8") as f:
                d = json.load(f)
        except FileNotFoundError:
            d = {}
        if not isinstance(d, dict):
            raise ValueError("arquivo do visto fora do formato")
        d.setdefault("pessoas", {})
        d.setdefault("vistos", {})
        return d

    def _gravar(self, d) -> None:
        os.makedirs(os.path.dirname(self.caminho) or ".", exist_ok=True)
        tmp = self.caminho + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        self._troca(tmp, self.caminho)

    @staticmethod
    def _podar(d, hoje: date) -> None:
        corte = (hoje - timedelta(days=GUARDA_DIAS)).isoformat()
        for k in [k for k in d["vistos"] if k[-10:] < corte]:
            del d["vistos"][k]

    def da_pessoa(self, pid, nome, agora: datetime) -> dict:
        """O que a tela pede ao abrir: {"eu": {"id", "nome", "desde"}, "vistos": {chave: [{"nome", "quando", "eu"}]}}.
        A 1ª abertura da pessoa grava o `desde` dela (agora)."""
        pid = pid or SEM_IDENTIDADE
        with self._trava:
            d = self._ler()
            p = d["pessoas"].get(pid)
            if not p:
                p = d["pessoas"][pid] = {"nome": nome or "", "desde": agora.strftime("%Y-%m-%d %H:%M")}
                self._podar(d, agora.date())
                self._gravar(d)
            elif nome and p.get("nome") != nome:
                p["nome"] = nome
                self._gravar(d)
        nomes = {i: (x.get("nome") or "") for i, x in d["pessoas"].items()}
        vistos = {k: sorted(({"nome": nomes.get(i) or ("alguém pela senha" if i == SEM_IDENTIDADE else "alguém"),
                              "quando": q, "eu": i == pid} for i, q in v.items()), key=lambda x: x["quando"])
                  for k, v in d["vistos"].items()}
        return {"eu": {"id": pid, "nome": p.get("nome") or "", "desde": p["desde"]}, "vistos": vistos}

    def consulta(self, pid):
        """(desde, chaves que a pessoa já viu) SEM criar a pessoa: quem nunca abriu a Sala volta (None, set()). É o que
        o sino do Nexus pergunta; a 1ª abertura da tela é que grava o `desde` (`da_pessoa`)."""
        pid = pid or SEM_IDENTIDADE
        d = self._ler()
        p = d["pessoas"].get(pid)
        if not p:
            return None, set()
        return p.get("desde"), {k for k, v in d["vistos"].items() if pid in v}

    def marcar(self, pid, nome, chaves, agora: datetime) -> int:
        """Marca as chaves como vistas pela pessoa (a 1ª vez de cada uma fica; ver de novo não muda a hora)."""
        pid = pid or SEM_IDENTIDADE
        boas = [k for k in (chave_valida(c) for c in (chaves or [])[:CHAVES_POR_PEDIDO]) if k]
        if not boas:
            return 0
        quando, n = agora.strftime("%Y-%m-%d %H:%M"), 0
        with self._trava:
            d = self._ler()
            d["pessoas"].setdefault(pid, {"nome": nome or "", "desde": quando})
            for k in boas:
                v = d["vistos"].setdefault(k, {})
                if pid not in v:
                    v[pid] = quando
                    n += 1
            if n:
                self._podar(d, agora.date())
                self._gravar(d)
        return n


# ── 3. Conferir fontes: a usina do SCADA da Grid que é a 2ª fonte de uma usina do Tempo real ───────────────────────

def norm(s) -> str:
    t = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


_RX_DUAS = re.compile(r"^(.*\D)\s*(\d+|i{1,3}|iv|v)\s+e\s+(\d+|i{1,3}|iv|v)$")


def nomes_cobertos(nome_scada) -> list:
    """Os nomes (normalizados) das usinas que uma usina do SCADA cobre. "Aparecida do taboado 1 e 2" → as duas; o resto,
    o próprio nome e ele sem a última palavra (o SCADA escreve "Ipixuna do para 2C": o cliente no fim)."""
    b = norm(nome_scada)
    m = _RX_DUAS.match(b)
    if m:
        return [f"{m.group(1).strip()} {m.group(2)}", f"{m.group(1).strip()} {m.group(3)}"]
    partes = b.split(" ")
    return [b] + ([" ".join(partes[:-1])] if len(partes) > 2 else [])


def usina_do_scada(usina, descobertas) -> dict | None:
    """A usina do SCADA (um item do `scadagridco.descobrir()`) que cobre a `usina` do Tempo real, pelo nome; None se
    nenhuma (ou se mais de uma casa: sem palpite). O item volta com `cobre` (os nomes normalizados, na ordem do SCADA)
    e `duas` (a usina do SCADA junta duas do Tempo real)."""
    alvo = norm(usina)
    # o nome inteiro igual vence (a "Rio do Peixe I e II" é UMA usina no Tempo real, com o "e" no nome)
    exatas = [x for x in (descobertas or []) if norm(x.get("nome")) == alvo]
    if exatas:
        return {**exatas[0], "cobre": [alvo], "duas": False} if len(exatas) == 1 else None
    achadas = []
    for x in descobertas or []:
        nomes = nomes_cobertos(x.get("nome"))
        duas = bool(_RX_DUAS.match(norm(x.get("nome"))))
        if alvo in nomes:
            achadas.append({**x, "cobre": nomes if duas else [alvo], "duas": duas})
    return achadas[0] if len(achadas) == 1 else None


def _ordem_natural(s):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", str(s))]


def leituras_para_conferir(leituras) -> list:
    """As leituras do `scadagridco.leitura_mqtt/leitura_modbus` → o que a tela compara, na ordem natural do equipamento
    (inv-01, inv-02...): {eq, ok, kw, kwh, com_corrente (strings com corrente acima de zero), strings, sn}."""
    out = []
    for l in sorted(leituras or [], key=lambda x: _ordem_natural(x.get("equip"))):
        st = l.get("strings") or {}
        vals = [v for v in st.values() if isinstance(v, (int, float))]
        out.append({"eq": str(l.get("equip")), "ok": bool(l.get("ok")),
                    "kw": round(l["pot_kw"], 2) if isinstance(l.get("pot_kw"), (int, float)) else None,
                    "kwh": round(l["eday"], 1) if isinstance(l.get("eday"), (int, float)) else None,
                    "com_corrente": sum(1 for v in vals if v > 0) if l.get("ok") else None, "strings": len(vals),
                    "sn": l.get("serial") or "", "ts": l.get("ts")})
    return out


# ── 4. Exportar Excel (Geração e PR, Potência) ────────────────────────────────────────────────────────────────────
# Levi, 16/11/2026: "tem que ter a opção de exportar. Exportar Excel, aí vem a coluna ali das datas e os inversores
# pivotados [...] E a irradiação pivotada também". A tela manda o que mostra (as datas na 1ª coluna, um inversor por
# coluna, a irradiação noutra aba) e o servidor só formata: .xlsx de verdade, que o Excel abre sem aviso.
EXPORT_ABAS_MAX, EXPORT_COLUNAS_MAX, EXPORT_LINHAS_MAX, EXPORT_CORPO_MAX = 4, 400, 6000, 6 * 1024 * 1024
_RX_ARQUIVO = re.compile(r"[^A-Za-z0-9À-ÿ _.()-]")
_RX_NUMERO = re.compile(r"-?\d+([.,]\d+)?")


class ExportRecusado(ValueError):
    """O corpo do Exportar Excel fora do formato ou dos limites (o motivo vai para a tela)."""


def _celula(v):
    if v is None or (isinstance(v, (int, float)) and not isinstance(v, bool)):
        return v
    s = str(v)[:400]
    # texto que começa como fórmula não vira fórmula no Excel de quem abre
    return "'" + s if s[:1] in ("=", "+", "-", "@") and not _RX_NUMERO.fullmatch(s) else s


def planilha(corpo):
    """{"arquivo": "...", "abas": [{"nome", "cabecalho": [...], "linhas": [[...]]}]} → (Workbook, nome do arquivo .xlsx).
    A 1ª linha de cada aba é o cabeçalho, em negrito e congelado; número segue número."""
    import openpyxl
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    if not isinstance(corpo, dict) or not isinstance(corpo.get("abas"), list) or not corpo["abas"]:
        raise ExportRecusado("mande as abas da planilha")
    if len(corpo["abas"]) > EXPORT_ABAS_MAX:
        raise ExportRecusado(f"até {EXPORT_ABAS_MAX} abas")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    usados = set()
    for a in corpo["abas"]:
        cab, linhas = (a or {}).get("cabecalho"), (a or {}).get("linhas")
        if not isinstance(cab, list) or not cab or not isinstance(linhas, list):
            raise ExportRecusado("cada aba tem um cabeçalho e as linhas")
        if len(cab) > EXPORT_COLUNAS_MAX or len(linhas) > EXPORT_LINHAS_MAX:
            raise ExportRecusado(f"até {EXPORT_COLUNAS_MAX} colunas e {EXPORT_LINHAS_MAX} linhas por aba")
        nome = re.sub(r"[\[\]:*?/\\]", " ", " ".join(str(a.get("nome") or "Dados").split()))[:31] or "Dados"
        while nome in usados:
            nome = nome[:28] + " 2"
        usados.add(nome)
        ws = wb.create_sheet(nome)
        ws.append([_celula(c) for c in cab])
        for c in ws[1]:
            c.font = Font(bold=True)
        for linha in linhas:
            if not isinstance(linha, list) or len(linha) > EXPORT_COLUNAS_MAX:
                raise ExportRecusado("linha fora do formato")
            ws.append([_celula(v) for v in linha])
        ws.freeze_panes = "B2"
        ws.column_dimensions["A"].width = 14
        for i in range(2, len(cab) + 1):
            ws.column_dimensions[get_column_letter(i)].width = max(12, min(28, len(str(cab[i - 1])) + 2))
    arq = _RX_ARQUIVO.sub("", " ".join(str(corpo.get("arquivo") or "sala-de-controle").split()))[:90].strip(" .") or "sala-de-controle"
    return wb, (arq[:-5] if arq.lower().endswith(".xlsx") else arq) + ".xlsx"


# ── 5. O raio-x do SCADA da Grid e a leitura de agora dos trackers e da estação ───────────────────────────────────
# Levi, 16/11/2026: "Quero que faça um raio-x de tudo que tem tracker [...] na nossa API do SCADA Grid e ETM também, e
# fazer aparecer [...] Não pode ter informação na API que a gente não tem aqui no tempo real". O raio-x diz o que cada
# usina do supervisório tem (inversor, tracker, estação); a tela mostra os trackers e a estação de agora de QUALQUER
# usina que o SCADA tenha, mesmo quando a fonte dela no Tempo real não traz (a 2C pela Owen, a Thopen pelo banco).
TIPOS_TRACKER = ("tracker", "tracker_ncu", "tcu", "rsu")
TIPOS_ESTACAO = ("weather",)
MEDIDAS_ESTACAO = (("irradiance_poa", "POA", "W/m²"), ("irradiance_ghi", "GHI", "W/m²"), ("irradiance_poa_rear", "POA traseira", "W/m²"),
                   ("ambient_temperature", "Temperatura ambiente", "°C"), ("module_temperature", "Temperatura do módulo", "°C"),
                   ("wind_speed", "Vento", "m/s"), ("accumulated_rain", "Chuva acumulada", "mm"))


def raiox_scada(todas, mq) -> list:
    """`/api/usinas` e `/api/mqtt` (2 chamadas) → uma linha por usina do supervisório: {id, nome, via, inv_total,
    equipamentos (os inversores, como o `scadagridco.descobrir`), tipos {tipo: quantos}, trackers, estacoes}."""
    por = {u.get("usina"): u for u in ((mq or {}).get("usinas") or []) if u.get("usina")}
    out = []
    for uid, st in sorted((todas or {}).items()):
        u = por.get(uid) or {}
        eqs = u.get("equipamentos") or []
        tipos = {}
        for e in eqs:
            k = str(e.get("tipo") or "?")
            tipos[k] = tipos.get(k, 0) + 1
        out.append({"id": uid, "nome": u.get("nome") or str(uid).replace("_", " "), "via": "mqtt" if eqs else "modbus",
                    "inv_total": (st or {}).get("inv_total"),
                    "equipamentos": [str(e.get("equipamento") or e.get("indice")) for e in eqs if e.get("tipo") == "inverter"],
                    "tipos": tipos, "trackers": sum(v for k, v in tipos.items() if k in TIPOS_TRACKER),
                    "estacoes": sum(v for k, v in tipos.items() if k in TIPOS_ESTACAO)})
    return out


def _n(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def trackers_de_agora(d) -> dict:
    """A resposta do `/api/trackers/<usina>` → {total, fora_do_alvo, sem_comunicacao, com_alarme, lista: [{eq, atual,
    alvo, desvio, fora, sem_com, alarmes}]} na ordem natural. Sem comunicação (ou leitura velha) não tem ângulo de agora."""
    lista = []
    for t in sorted((d or {}).get("trackers") or [], key=lambda x: _ordem_natural(x.get("equipamento") or x.get("indice"))):
        mudo = bool(t.get("sem_comunicacao") or t.get("stale"))
        al = t.get("alarmes")
        lista.append({"eq": str(t.get("equipamento") or t.get("indice")), "atual": None if mudo else _n(t.get("posicao_atual")),
                      "alvo": _n(t.get("posicao_alvo")), "desvio": None if mudo else _n(t.get("desvio")),
                      "fora": bool(t.get("fora_do_alvo")) and not mudo, "sem_com": mudo,
                      "alarmes": len(al) if isinstance(al, list) else int(al or 0)})
    return {"total": len(lista), "fora_do_alvo": sum(1 for x in lista if x["fora"]), "sem_comunicacao": sum(1 for x in lista if x["sem_com"]),
            "com_alarme": sum(1 for x in lista if x["alarmes"]), "lista": lista}


def estacoes_de_agora(mq_usina, com_ok=192) -> list:
    """Os equipamentos `weather` do `/api/mqtt/<usina>` → [{eq, ok, medidas: [{nome, valor, unidade}]}]. Leitura ruim do
    gateway não traz valor (lacuna, não zero); só entram as medidas que a estação manda como número."""
    out = []
    for e in (mq_usina or {}).get("equipamentos") or []:
        if e.get("tipo") not in TIPOS_ESTACAO:
            continue
        m = e.get("measurements") if isinstance(e.get("measurements"), dict) else {}
        ok = e.get("communication_fault") == com_ok and not e.get("stale") and not e.get("falha_comunicacao")
        medidas = [{"nome": nome, "valor": round(_n(m.get(k)), 2), "unidade": un} for k, nome, un in MEDIDAS_ESTACAO if ok and _n(m.get(k)) is not None]
        out.append({"eq": str(e.get("equipamento") or e.get("indice")), "ok": bool(ok), "medidas": medidas, "ts": e.get("ts")})
    return out


# ── 6. O novo por pessoa, agrupado por usina, para o sino do topo do Nexus ─────────────────────────────────────────
# Levi, 16/11/2026: as ocorrências novas chegam no sino agrupadas POR USINA. É a MESMA regra da tela (o `montar` do
# template): novo = parou depois da 1ª vez que a pessoa abriu a Sala, segue parado e ela ainda não abriu. Quem nunca
# abriu a Sala não tem "desde": o sino não mostra nada dela (não acorda ninguém com o mês inteiro).

def novas_por_usina(pacote, idade, desde, vistas, hoje) -> list:
    """`pacote` = o pacote de falhas do mês (strings.rows, strings.episodios, trackers.rows); `idade` = o resultado do
    `idade_real` (a data real de quem já vinha parado no dia 1); `desde` = "AAAA-MM-DD HH:MM" da pessoa; `vistas` = as
    chaves que ela já abriu; `hoje` = "AAAA-MM-DD". → [{usina, strings, inversores, trackers}], a com mais novidade
    primeiro. Sem `desde`, lista vazia."""
    if not desde or not isinstance(pacote, dict):
        return []
    st = pacote.get("strings") or {}
    dias = sorted({r.get("dia") for r in (st.get("rows") or []) if r.get("dia")})
    fechados = [d for d in dias if d < hoje]
    ult, d1mes = (fechados[-1] if fechados else None), (dias[0] if dias else None)
    real = (idade or {}).get("strings") or {}
    por = {}

    def de(usina):
        return por.setdefault(usina, {"usina": usina, "strings": 0, "inv": set(), "trackers": 0})
    for e in st.get("episodios") or []:
        if not ult or (e.get("d1") or "") < ult:
            continue                                     # já voltou: não é novidade
        r = real.get(_chave_str(e)) if e.get("d0") == d1mes else None
        d0, ini = (r["d0"], r.get("inicio") or r["d0"]) if r else (e.get("d0"), e.get("inicio") or e.get("d0"))
        k = f"s|{e.get('usina')}|{e.get('inversor')}|{e.get('string')}|{d0}"
        if str(ini) >= desde and k not in vistas:
            o = de(e.get("usina"))
            o["strings"] += 1
            o["inv"].add(e.get("inversor"))
    for r in (pacote.get("trackers") or {}).get("rows") or []:
        if r.get("fim"):
            continue                                     # o tracker que já voltou não é novidade
        ini = str(r.get("inicio") or "")
        if ini >= desde and f"t|{r.get('usina')}|{r.get('tracker')}|{ini[:10]}" not in vistas:
            de(r.get("usina"))["trackers"] += 1
    out = [{"usina": o["usina"], "strings": o["strings"], "inversores": len(o["inv"]), "trackers": o["trackers"]} for o in por.values()]
    return sorted(out, key=lambda x: (-(x["strings"] + x["trackers"]), str(x["usina"])))
