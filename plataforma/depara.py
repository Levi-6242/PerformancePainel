# -*- coding: utf-8 -*-
"""De-para de equipamentos decidido na tela (Levi, 11/10/2026: "quero que o de-para da equipamentos seja feito na plataforma
de forma intuitiva"; depois: "RESOLVA"). A regra pura; a leitura e a gravação no banco são as da `cobertura.Decisoes`.

Até aqui o de-para que o código aplica morava em constantes: a ponte pelo id da usina que a API renomeou (`PV_NOME_POR_ID`),
o nome de cada inversor da conta oem@, que não manda nome (`PV_INV_NOMES`), e o dos inversores do scadaGridco
(`scadagridco.FONTES`). Mudar exigia o Claude, um commit e um deploy, e no mesmo dia 11/10 o de-para quebrou quatro vezes
em silêncio. Agora a decisão da tela VENCE a constante, que vira a reserva (livro ilegível = vale o código, como antes).

O dado (governança do Nexus, `nexus/dados/CLAUDE.md`): livro `nexus_depara`, aba `fato_decisao_depara`, no catálogo do
Nexus. Grão: 1 linha = 1 decisão de ligar 1 usina (o id dela na fonte) ou 1 inversor (o id dele na fonte) ao cadastro (a aba
Equipamentos do BD_Performance). Tipo: sem medida. Só acrescenta: o vigente é a última decisão de cada fonte × usina ×
inversor. O cadastro entra pela CHAVE DE NEGÓCIO dele (Usina Supervisório, Equipamento Supervisório), nunca texto livre: a
rota só aceita o que o cadastro tem. Valor vazio = desfaz (volta ao nome da API, ou ao de-para do código).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

LIVRO = "nexus_depara"
NOME_LIVRO = "Nexus · De-para de equipamentos"
ABA = "fato_decisao_depara"
CAB = ["decidida_em", "data_id", "fonte", "usina_fonte", "inversor_fonte", "usina_supervisorio",
       "equipamento_supervisorio", "origem"]
ORIGENS = ("tela",)

# Onde o código liga pelo ID (é ali que a tela decide): a usina pela ponte do id nas contas da API PV; o inversor pelo id
# na conta oem@ (SEMP, Alves Lima, 2C) e pelo número do equipamento no scadaGridco. A Thopen da conta principal e as outras
# fontes ligam pelo nome que a fonte manda: corrige-se no cadastro.
FONTES_USINA = ("pv", "semp", "alveslima", "2capi")
# 12/10/2026 (Levi: "eu consigo ligar usinas mas não consigo ligar inversor a inversor"): a conta principal da API PV (pv)
# entra aqui. O nome do inversor dela vem do plant_devices e só casava com o cadastro se a grafia batesse; agora o id do
# inversor (que não muda quando a API renomeia) liga ao Equipamento Supervisório, como na conta oem@.
FONTES_INVERSOR = ("pv", "semp", "alveslima", "2capi", "greenyellow", "salenergia", "apolo")
# As fontes que mandam a usina só pelo NOME (a Athon e a Axis, pela SunOp: a chave delas é o próprio nome, "CPP100").
# Até 12/10/2026 o conserto de um nome que não casava era editar a "Usina Supervisório" no Equipamentos do BD_Performance
# e subir a planilha (Levi: "precisamos trazer para o Nexus e deixar mais dinâmico com a plataforma"). Agora a tela grava
# um APELIDO (o nome que a fonte escreve → a usina do cadastro) e a plataforma o aplica como o PV_NOME_API_ALIAS do código.
# Ficam de fora a Thopen do banco (a chave é o id da usina no banco, 8, 9, 31…, e o nome da linha já é o de exibição) e
# a RenoGrid (a chave é o id do site): a 1ª versão incluía o banco e o editor chamava de "sem de-para" usina ligada.
FONTES_APELIDO = ("sunop", "axis")

_BRT = timezone(timedelta(hours=-3))


def agora_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dia(quando: str) -> int:
    d = datetime.strptime(quando, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone(_BRT)
    return int(d.strftime("%Y%m%d"))


def _txt(v) -> str:
    return "" if v is None else str(v).strip()


def linha_usina(fonte: str, usina_fonte, usina_supervisorio, quando: str | None = None) -> list:
    """Liga a usina (id na fonte) à Usina Supervisório do cadastro; vazio = sem ponte (vale o nome que a API escreve)."""
    if fonte not in FONTES_USINA:
        raise ValueError(f"a usina da fonte {fonte!r} liga pelo nome: corrija no cadastro")
    uf = _txt(usina_fonte)
    if not uf:
        raise ValueError("usina sem id")
    quando = quando or agora_utc()
    return [quando, _dia(quando), fonte, uf, "", _txt(usina_supervisorio), "", "tela"]


def linha_inversor(fonte: str, usina_fonte, inversor_fonte, equipamento_supervisorio, quando: str | None = None) -> list:
    """Liga o inversor (id na fonte) ao Equipamento Supervisório do cadastro; vazio = volta ao de-para do código."""
    if fonte not in FONTES_INVERSOR:
        raise ValueError(f"o inversor da fonte {fonte!r} liga pelo nome que ela manda: corrija no cadastro")
    uf, inv = _txt(usina_fonte), _txt(inversor_fonte)
    if not uf or not inv:
        raise ValueError("inversor sem id")
    quando = quando or agora_utc()
    return [quando, _dia(quando), fonte, uf, inv, "", _txt(equipamento_supervisorio), "tela"]


def linha_apelido(fonte: str, nome_na_fonte, usina_supervisorio, quando: str | None = None) -> list:
    """Liga a usina que a fonte manda PELO NOME à Usina Supervisório do cadastro; vazio = desfaz (vale o nome que ela
    manda, como antes). `usina_fonte` guarda o nome exatamente como a fonte escreve."""
    if fonte not in FONTES_APELIDO:
        raise ValueError(f"a usina da fonte {fonte!r} não liga por apelido: corrija no cadastro")
    nome = _txt(nome_na_fonte)
    if not nome:
        raise ValueError("usina sem nome")
    quando = quando or agora_utc()
    return [quando, _dia(quando), fonte, nome, "", _txt(usina_supervisorio), "", "tela"]


def _como_dict(lin) -> dict:
    return dict(zip(CAB, lin)) if isinstance(lin, (list, tuple)) else dict(lin)


def vigente(linhas) -> dict:
    """{"usina": {(fonte, usina_fonte): {"valor", "quando"}}, "inversor": {(fonte, usina_fonte, inversor_fonte): {...}},
    "apelido": {(fonte, nome na fonte): {...}}} pela última decisão de cada chave (a mais recente; no empate, a que veio
    depois). Valor "" fica: é o desfazer."""
    marcadas = []
    for i, lin in enumerate(linhas or []):
        d = _como_dict(lin)
        f, uf, inv = _txt(d.get("fonte")), _txt(d.get("usina_fonte")), _txt(d.get("inversor_fonte"))
        if d.get("origem") not in ORIGENS or not uf:
            continue
        if inv:
            if f in FONTES_INVERSOR:
                marcadas.append((_txt(d.get("decidida_em")), i, "inversor", (f, uf, inv), _txt(d.get("equipamento_supervisorio"))))
        elif f in FONTES_USINA:
            marcadas.append((_txt(d.get("decidida_em")), i, "usina", (f, uf), _txt(d.get("usina_supervisorio"))))
        elif f in FONTES_APELIDO:
            marcadas.append((_txt(d.get("decidida_em")), i, "apelido", (f, uf), _txt(d.get("usina_supervisorio"))))
    estado = {"usina": {}, "inversor": {}, "apelido": {}}
    for q, _i, tipo, chave, valor in sorted(marcadas):
        estado[tipo][chave] = {"valor": valor, "quando": q}
    return estado


def pontes(estado) -> dict:
    """{id da usina (int): Usina Supervisório, ou "" para "sem ponte"} das contas da API PV (o id é o mesmo nas quatro)."""
    out = {}
    for (f, uf), v in ((estado or {}).get("usina") or {}).items():
        try:
            out[int(uf)] = v["valor"]
        except (TypeError, ValueError):
            continue
    return out


def apelidos(estado) -> dict:
    """{nome que a fonte escreve: Usina Supervisório} das fontes que ligam pelo nome. Só os ligados: o vazio desfaz."""
    return {nome: v["valor"] for (_f, nome), v in ((estado or {}).get("apelido") or {}).items() if v.get("valor")}


def inversores(estado, fontes, usina_fonte) -> dict:
    """{id do inversor (texto): Equipamento Supervisório, ou "" para "volta ao código"} de uma usina nas `fontes`."""
    uf = _txt(usina_fonte)
    return {inv: v["valor"] for (f, u, inv), v in ((estado or {}).get("inversor") or {}).items() if f in fontes and u == uf}


def aplica_inversores(codigo: dict, decididos: dict, chave=int) -> dict:
    """O de-para do código com as decisões da tela por cima: valor decidido troca, vazio tira (o inversor volta a não ter
    nome no código). `chave` converte o id do inversor (int na API PV, texto no scadaGridco)."""
    out = dict(codigo or {})
    for inv, nome in (decididos or {}).items():
        try:
            k = chave(inv)
        except (TypeError, ValueError):
            continue
        if nome:
            out[k] = nome
        else:
            out.pop(k, None)
    return out


# ── sugestão pelo valor: o jeito que fechou a Morada Nova, a Ipixuna e a 2C (o kWh de cada id × a coluna do BD) ──────
def sugerir_por_valor(fonte_kwh: dict, bd_kwh: dict, minimo_dias: int = 2) -> dict:
    """`fonte_kwh` {id: {dia: kWh}} (o Eday de cada inversor na fonte), `bd_kwh` {coluna: {dia: kWh}} (a aba da usina no
    BD). Casa cada id com a coluna de menor erro relativo nos dias que os dois têm, um para um (o par mais certo primeiro).
    → {"pares": {id: {"coluna", "erro_pct", "segunda_pct", "dias", "confianca"}}, "sem_par": [ids], "colunas_vazias": [...]}.
    Confiança: "certa" (erro ≤ 1% e a 2ª opção 3× pior), "provável" (≤ 5%), "fraca" (o resto: conferir antes)."""
    fonte_kwh = {str(k): v or {} for k, v in (fonte_kwh or {}).items()}
    colunas_vazias = sorted(c for c, s in (bd_kwh or {}).items() if not any((v or 0) > 0 for v in (s or {}).values()))
    cands = []
    custos = {}
    for i, sf in fonte_kwh.items():
        for c, sb in (bd_kwh or {}).items():
            if c in colunas_vazias:
                continue
            dias = sorted(d for d in sf if d in sb and isinstance(sf[d], (int, float)) and isinstance(sb[d], (int, float)))
            if len(dias) < minimo_dias:
                continue
            soma_b = sum(abs(sb[d]) for d in dias)
            if soma_b <= 0:
                continue
            erro = sum(abs(sf[d] - sb[d]) for d in dias) / soma_b * 100
            custos.setdefault(i, []).append((erro, c, len(dias)))
            cands.append((erro, i, c, len(dias)))
    pares, usados_i, usados_c = {}, set(), set()
    for erro, i, c, n in sorted(cands):
        if i in usados_i or c in usados_c:
            continue
        outros = sorted(e for e, cc, _n in custos.get(i, []) if cc != c)
        segunda = outros[0] if outros else None
        if erro <= 1 and (segunda is None or segunda >= 3 * max(erro, 0.01)):
            conf = "certa"
        elif erro <= 5:
            conf = "provável"
        else:
            conf = "fraca"
        pares[i] = {"coluna": c, "erro_pct": round(erro, 2), "segunda_pct": None if segunda is None else round(segunda, 2),
                    "dias": n, "confianca": conf}
        usados_i.add(i)
        usados_c.add(c)
    sem_par = sorted(i for i in fonte_kwh if i not in pares)
    return {"pares": pares, "sem_par": sem_par, "colunas_vazias": colunas_vazias}


# ── sugestão pelo NOME: a usina que a fonte manda e não casa com o cadastro ────────────────────────────────────────────
# Caso que criou (12/10/2026): a API escreve "Itaja 1 (228)" e "Pharma 2 (644)"; o cadastro tem "Itaja 1 (551)" e
# "Pharma 2". O número tem de bater ("Itaja 1" nunca sugere "Itaja 2") e o que está entre parênteses só avisa.
_ROMANOS = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}


def base_do_nome(nome) -> str:
    """O nome para comparar: sem acento, minúsculo, sem o que está entre parênteses, sem "UFV", romano vira número."""
    s = unicodedata.normalize("NFKD", _txt(nome)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(_ROMANOS.get(t, t) for t in s.split() if t not in ("ufv", "usina"))


def _parenteses(nome) -> list:
    return [p.strip() for p in re.findall(r"\(([^)]*)\)", _txt(nome)) if p.strip()]


def parecidas(nome, candidatos, limite: int = 3) -> list:
    """As usinas do cadastro (`candidatos`: [{"chave", "nome"}]) com nome parecido com o que a fonte escreve, da mais
    parecida para a menos: [{"chave", "nota", "confere"}]. Os números do nome têm de ser os mesmos; `confere` diz o que
    olhar antes de ligar (o número entre parênteses diferente)."""
    b = base_do_nome(nome)
    if not b:
        return []
    txt_b = " ".join(t for t in b.split() if not t.isdigit())
    num_b = [t for t in b.split() if t.isdigit()]
    par_b = _parenteses(nome)
    out = []
    for c in candidatos or []:
        nomes = [x for x in dict.fromkeys((c.get("chave"), c.get("nome"))) if x]
        melhor = 0.0
        for n in nomes:
            bn = base_do_nome(n)
            if not bn or [t for t in bn.split() if t.isdigit()] != num_b:
                continue
            txt_n = " ".join(t for t in bn.split() if not t.isdigit())
            melhor = max(melhor, 1.0 if txt_n == txt_b else SequenceMatcher(None, txt_b, txt_n).ratio())
        if melhor < 0.8:
            continue
        par_c = [p for n in nomes for p in _parenteses(n)]
        confere = (f"o número entre parênteses é outro ({', '.join(par_b)} na fonte, {', '.join(dict.fromkeys(par_c))} "
                   f"no cadastro): confira se é a mesma usina") if par_b and par_c and not set(par_b) & set(par_c) else None
        out.append({"chave": c["chave"], "nota": round(melhor, 2), "confere": confere})
    out.sort(key=lambda x: (-x["nota"], str(x["chave"]).lower()))
    return out[:limite]
