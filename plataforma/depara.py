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

from datetime import datetime, timedelta, timezone

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
FONTES_INVERSOR = ("semp", "alveslima", "2capi", "greenyellow", "salenergia")

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


def _como_dict(lin) -> dict:
    return dict(zip(CAB, lin)) if isinstance(lin, (list, tuple)) else dict(lin)


def vigente(linhas) -> dict:
    """{"usina": {(fonte, usina_fonte): {"valor", "quando"}}, "inversor": {(fonte, usina_fonte, inversor_fonte): {...}}}
    pela última decisão de cada chave (a mais recente; no empate, a que veio depois). Valor "" fica: é o desfazer."""
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
    estado = {"usina": {}, "inversor": {}}
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
