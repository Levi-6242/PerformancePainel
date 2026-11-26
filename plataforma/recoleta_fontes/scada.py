# -*- coding: utf-8 -*-
"""Recoleta pelo scadaGridco (o supervisório da Automação Grid Co.) para a Coletas do Nexus (17/11/2026).

Levi, 17/11/2026: "quero formas de coletar os dados novamente pelas nossas fontes de dados e gerar uma planilha para
colar nos BDs"; "Sim, todas". Esta é a fonte das usinas que o coletor da noite busca no supervisório e grava no
BD_Performance: GreenYellow (Castelo do Piauí, Demerval Lobão, Irecê 2, Cedro 1 e 2), Apolo (Gravatá II, Iramaia II, Rio
do Peixe I e II), Marialva, PE II e PE III. Nada é gravado aqui: a resposta é o contrato do `comum.py`.

A REGRA é a do coletor que roda toda noite, PORTADA sem mudar: `coleta API PV/src/coletar_greenyellow.py` (13/10/2026,
validado POR VALOR contra o que a equipe digitou; a Apolo, a Marialva e as PE ao centavo). O servidor não tem a pasta da
coleta, por isso a configuração e as contas estão copiadas aqui; `tests/test_recoleta_scada.py` compara as duas com o
arquivo do coletor quando ele está na máquina, para não divergirem em silêncio. Mudou lá, muda aqui no mesmo trabalho.

O de-para é o do COLETOR (`USINAS`), não o `ctx.mapa` da aba Equipamentos: é com ele que o coletor grava o BD, e essas
usinas não têm "Usina/Equipamento Supervisório" no cadastro (plataforma/CLAUDE.md, seção do scadaGridco). O
`scadagridco.FONTES` do tempo real também não serve: na Rio do Peixe ele liga o cadastro (1.1-1.10 e 2.1-2.10), e a
coluna do BD é outra (quatro grupos de cinco, 1.1-1.5 ... 4.1-4.5, a numeração de 10/11/2026). O `ctx.mapa` vai só para o
`comum.montar_resposta` (a conta do dia fora do ar).

A rede é a do cliente da plataforma (`scadagridco.get`): o mesmo `_LOCK` de uma chamada por vez (a regra da Automação: o
mesmo servidor opera as usinas, lendo relés e inversores em tempo real), o `X-API-Key` e o 302 do token recusado.
"""
import datetime as dt
import importlib
import time
import types

from recoleta_fontes import comum

FONTE = "scada"
PAGA = False
TETO = None
# Uma chamada por inversor e dia, na fila de uma por vez que o tempo real também usa: duas plantas de 10 inversores em 7
# dias são 140 chamadas, ~70 s a 0,5 s cada (um inversor-dia da Irecê 2, 06/10/2026); a PE II sozinha (25 inversores)
# são 175. O que passar do ORCAMENTO_S sai em aviso, para pedir de novo aquele trecho.
MAX_PLANTAS = 2

# ── A régua do coletor da noite (coletar_greenyellow.py), igual ─────────────────────────────────────────────────────
COM_OK = 192            # communication_fault da leitura boa (28 = ruim)
HORA_MIN = 5            # antes disso o contador ainda pode trazer a véspera (Irecê 2, 29/09/2026)
HORA_FIM_DIA = 16       # a última leitura boa tem de ser depois disso, senão o dia ficou pela metade
LIMITE = 5000           # registros por página do /api/telemetria
TETO_WH_M2 = 12000      # acima disso é lixo do sensor (a POA da Cedro vem com 1.193.046 no meio do dia)

# ── O que é só da recoleta ─────────────────────────────────────────────────────────────────────────────────────────
HISTORICO_DIAS = 45     # o que o /api/telemetria guarda (scadagridco.py: "histórico só até 45 dias")
# O coletor espera 60 s por chamada porque roda sozinho de noite; aqui há uma pessoa esperando a resposta e o tempo real
# na mesma fila. Um inversor-dia são ~2,5 MB e 0,5 s (Irecê 2, 06/10/2026): 30 s ainda é 60 vezes isso.
TIMEOUT_S = 30
# O pedido vem da Coletas pela internet; acima de ~100 s o proxy na frente da plataforma pode cortar (524 da
# Cloudflare) e a busca INTEIRA se perde, com o supervisório ocupado à toa. Passado o orçamento, a planta-dia seguinte
# não começa: o que faltou sai em aviso, e a planta-dia em curso termina inteira (dia pela metade não sai).
ORCAMENTO_S = 75
# Servidor do supervisório fora ou travado: sem esta trava cada inversor que falta esperaria o TIMEOUT_S (os 25 da PE II
# seriam 12 min presos na fila que o tempo real usa). Três chamadas seguidas com erro param o resto, em aviso. Gateway de
# usina fora (a Rio do Peixe some de madrugada) não conta: a API responde, só que sem registro, e isso é "sem leitura".
FALHAS_SEGUIDAS = 3

# Copiado de coletar_greenyellow.USINAS (aba do BD_Performance -> id do supervisório e {equipamento: coluna do BD}). O
# porquê de cada de-para (conferido por valor, dia a dia) está no docstring de lá; não editar só aqui.
USINAS = {
    "Castelo do Piauí": {"scada": "castelo_do_piaui",
                         "inversores": {**{f"inversor-{i:02d}": f"Inversor 1.{i}" for i in range(1, 9)},
                                        **{f"inversor-{i:02d}-12": f"Inversor 2.{i}" for i in range(1, 9)}}},
    # O supervisório renomeou de "N" para "inversor-NN" (Demerval 04/11/2026, Irecê 05/11): o mesmo conserto do coletor
    # (coletar_greenyellow.USINAS), pela ordem.
    # UG 02 da Demerval (Levi, 17/11/2026: "pode botar agora"): o grupo "inversor-NN-12" apareceu no supervisório em
    # 04/11 (antes não estava; as colunas 2.1-2.8 da aba ficavam vazias), 8 inversores -> Inversor 2.N, PELA ORDEM, como
    # a Cedro 2 (sem histórico anterior para fechar pelo valor).
    "Demerval Lobão": {"scada": "dermeval_lobao",
                       "inversores": {**{f"inversor-{i:02d}": f"Inversor 1.{i}" for i in range(1, 13)},
                                      **{f"inversor-{i:02d}-12": f"Inversor 2.{i}" for i in range(1, 9)}}},
    "Irece 2": {"scada": "irece_2",
                "inversores": {f"inversor-{i:02d}": f"Inversor 1.{i}" for i in range(1, 11)}},
    "Cedro 1": {"scada": "cedro",
                "inversores": {f"inversor-{i:02d}": f"Inversor 1.{i}" for i in range(1, 11)}},
    "Cedro 2": {"scada": "cedro",
                "inversores": {f"inversor-{i:02d}-12": f"Inversor 1.{i}" for i in range(1, 11)}},
    "Gravatá II": {"scada": "gravata_ii_apolo", "so_vazio_ou_maior": True,
                   "inversores": {str(i): f"Inversor 1.{i}" for i in range(1, 11)}},
    "Iramaia II": {"scada": "iramaia_ii_apolo", "so_vazio_ou_maior": True,
                   "inversores": {str(i): f"Inversor 1.{i}" for i in range(1, 11)}},
    "Rio do Peixe I e II": {"scada": "rio_do_peixe_1_2", "so_vazio_ou_maior": True,
                            # 1-20 em sequência desde a renumeração do scadaGridco (coletar_greenyellow, 26/11/2026)
                            "inversores": {str(5 * (g - 1) + n): f"Inversor {g}.{n}"
                                           for g in range(1, 5) for n in range(1, 6)}},
    "Marialva": {"scada": "marialva", "so_vazio_ou_maior": True,
                 "inversores": {str(i): f"Inversor 1.{i}" for i in range(1, 9)}},
    "PEII": {"scada": "pe_ii", "so_vazio_ou_maior": True,
             "inversores": {str(i): f"Inversor 1.{i}" for i in range(1, 26)}},
    "PEIII": {"scada": "pe_iii", "so_vazio_ou_maior": True,
              "inversores": {str(i): f"Inversor 1.{i}" for i in range(1, 11)}},
}

# Copiado de coletar_greenyellow.ETM e .MEDIDOR (25/11/2026, Levi: "só tá puxando ETM de Cedro 1 e 2. E as ETMs
# das demais?"; "Criar a coluna GHI na PEII"; "nessas UFVs da Apolo conseguimos puxar multimedidor"). O porquê de
# cada uma (conferida contra o digitado) está no coletor; não editar só aqui. A Cedro é o maior acumulado do dia; a
# Irecê 2, o contador que não zera à meia-noite; a PE II, só GHI em kWh/m²; a Rio do Peixe, o relé 3 (potência
# exportada integrada). Demerval (estação travada), Castelo (irradiância 0) e as outras não têm ETM aqui.
ETM = {
    "Cedro 1": {"scada": "cedro", "IPOA (kWh/m²)": ("estacao-poa", "irradiation_poa"),
                "GHI (kWh/m²)": ("estacao-ghi", "irradiation_ghi")},
    "Cedro 2": {"scada": "cedro", "IPOA (kWh/m²)": ("estacao-poa", "irradiation_poa"),
                "GHI (kWh/m²)": ("estacao-ghi", "irradiation_ghi")},
    "Irece 2": {"scada": "irece_2", "regra": "contador", "so_vazio": True,
                "IPOA (kWh/m²)": ("estacao", "irradiation_poa"), "GHI (kWh/m²)": ("estacao", "irradiation_ghi")},
    "PEII": {"scada": "pe_ii", "regra": "fim_do_dia_kwh", "so_vazio": True,
             "GHI (kWh/m²)": ("estacao-1", "irradiation_ghi")},
}
MEDIDOR = {
    "Rio do Peixe I e II": {"scada": "rio_do_peixe_1_2", "equip": "3", "coluna": "Multimedidor"},
}
SOL_MAX_W_M2 = 1500     # passo do contador acima de 1.500 W/m² vezes o tempo entre as leituras é lixo
HORA_INI_CONTADOR = 6   # o contador da Irecê 2 tem de estar lendo desde antes do sol, senão o dia ficou sem a manhã
QUEDA_RUIDO_WH = 5      # o contador da Irecê 2 cai 1 Wh/m² de cada vez à noite (o sensor integra irradiância negativa)
BURACO_MAX_S = 900      # buraco maior que 15 min entre 05h e 19h = dia do relé incompleto (perde o sol daquele trecho)
TETO_KWH_M2 = 12.0      # o acumulado da PE II vem em kWh/m²: acima disso é lixo
FIM_KWH_HORA = 17       # o acumulado da PE II já parou de subir: vale a mediana das leituras boas a partir daqui

# Equipamento do supervisório que o coletor deixa de fora DE PROPÓSITO: não é "sem de-para", tem motivo. Vazio desde
# 26/11/2026: o 15 da Rio do Peixe era cópia do 14 (28/10: 315 de 316 minutos com sol iguais) até o scadaGridco
# renumerar a usina para 1-20; hoje o 15 é o Inversor 3.5 (ver coletar_greenyellow).
FORA_DE_PROPOSITO = {}

# O id de cada planta = o id da usina no supervisório, menos onde ele junta duas abas: a "cedro" é a Cedro 1 e a Cedro 2,
# e as duas viram cedro_1/cedro_2, o mesmo id que a descoberta da plataforma dá (`_sg_classifica`).
_ID_PROPRIO = {"Cedro 1": "cedro_1", "Cedro 2": "cedro_2"}
PLANTAS = {_ID_PROPRIO.get(aba, cfg["scada"]): aba for aba, cfg in USINAS.items()}

SEM_LEITURA = "sem leitura boa depois das 05h"
PELA_METADE = "dia pela metade (a última leitura boa é antes das 16h)"
SEM_CONTADOR = "sem contador de energia depois de o inversor ligar"


class _Parou(Exception):
    """O supervisório parou de responder no meio do pedido: o resto não é buscado."""


def _num(v):
    """O `_num` do coletor: texto numérico vale; "-" (ponto sem sensor) e vazio são nulo, nunca zero."""
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _leitura_do_dia(registros):
    """Registros de `/api/telemetria` de UM inversor num dia -> (kWh | None, motivo | None, HH:MM da última boa | None).

    É o `energia_do_dia` do coletor, linha a linha, devolvendo também POR QUE não há valor (o aviso). O MAIOR contador
    a partir da primeira leitura com potência, e não o último: na Cedro o `daily_active_energy` volta a ZERO quando o
    inversor desliga à noite (12/10/2026: 570,6 kWh ao meio-dia, 0,0 às 23:57) e o "último valor" gravou zero nos 10
    inversores de 10 a 12/10. Leitura antes das 05h não conta: o contador da madrugada ainda traz a véspera (Irecê 2,
    29/09/2026). Sem leitura boa depois das 16h a comunicação caiu e o dia ficou pela metade: nulo, nem zero."""
    boas = []
    for x in registros or []:
        if x.get("communication_fault") != COM_OK:
            continue
        hora = str(x.get("data_hora") or "")[11:13]
        if not hora.isdigit() or int(hora) < HORA_MIN:
            continue
        p = x.get("pontos") or {}
        v = _num(p.get("total_daily_energy"))
        if v is None:
            v = _num(p.get("daily_active_energy"))
        boas.append((str(x.get("data_hora")), v, _num(p.get("active_power"))))
    boas = [b for b in boas if b[1] is not None or b[2] is not None]
    if not boas:
        return None, SEM_LEITURA, None
    boas.sort()
    if int(boas[-1][0][11:13]) < HORA_FIM_DIA:
        return None, PELA_METADE, boas[-1][0][11:16]
    acordou = next((i for i, b in enumerate(boas) if (b[2] or 0) > 0), None)
    depois = [b[1] for b in (boas[acordou:] if acordou is not None else boas) if b[1] is not None]
    return (max(depois), None, None) if depois else (None, SEM_CONTADOR, None)


def energia_do_dia(registros):
    """kWh do dia de um inversor, ou None: o mesmo valor que o coletor da noite grava (sem o arredondamento)."""
    return _leitura_do_dia(registros)[0]


def irradiacao_do_dia(registros, campo):
    """O `irradiacao_do_dia` do coletor: registros de `/api/telemetria` de UMA estação num dia -> kWh/m², ou None.

    O maior acumulado PLAUSÍVEL depois das 05h (o acumulado zera de madrugada; lixo acima de TETO_WH_M2 fica fora) e só
    com leitura boa depois das 16h (dia inteiro). Zero o dia todo é sensor sem leitura, não sol zero: None."""
    vals, ultima = [], None
    for x in registros or []:
        if x.get("communication_fault") != COM_OK:
            continue
        hora = str(x.get("data_hora") or "")[11:13]
        if not hora.isdigit() or int(hora) < HORA_MIN:
            continue
        v = _num((x.get("pontos") or {}).get(campo))
        if v is None or v < 0 or v > TETO_WH_M2:
            continue
        vals.append(v)
        ultima = max(ultima or 0, int(hora))
    if not vals or ultima < HORA_FIM_DIA or max(vals) <= 0:
        return None
    return round(max(vals) / 1000.0, 3)


def irradiacao_pelo_contador(registros, campo):
    """Registros de `/api/telemetria` de UMA estação num dia -> kWh/m² do dia, para o acumulado que NÃO zera à meia-noite
    (Irecê 2, 25/11/2026: o `irradiation_poa` de 24/11 vai de 23.412 a 32.968 Wh/m², e no 25/11 segue de onde parou).

    O dia é a soma dos passos POSITIVOS do contador entre leituras boas seguidas: um buraco de comunicação não perde
    nada (o contador seguiu contando na estação), e a queda de 1 Wh/m² da noite fica fora. Fica None (o BD segue vazio):
    - a 1ª leitura boa é depois das 06h (05/11 começou às 11:05, 15/11 às 07:02, 20/11 às 10:02: o dia ficou sem a manhã);
    - o contador reiniciou com a próxima leitura já de dia, depois das 05h (06/11: caiu de 9.171 para 23 num buraco de
      01:12 a 07:15, a manhã até ali se perdeu);
    - a última leitura boa é antes das 16h, ou o total é 0 ou passa do teto.
    Passo maior que 1.500 W/m² vezes o tempo entre as leituras é lixo e fica fora. Puro (tests/test_coletar_greenyellow)."""
    pts = []
    for x in registros or []:
        if x.get("communication_fault") != COM_OK:
            continue
        v = _num((x.get("pontos") or {}).get(campo))
        try:
            t = dt.datetime.fromisoformat(str(x.get("data_hora") or "")[:19])
        except ValueError:
            continue
        if v is not None:
            pts.append((t, v))
    pts.sort()
    if not pts or pts[0][0].hour >= HORA_INI_CONTADOR or pts[-1][0].hour < HORA_FIM_DIA:
        return None
    total = 0.0
    for (ta, va), (tb, vb) in zip(pts, pts[1:]):
        passo = vb - va
        if passo < -QUEDA_RUIDO_WH and tb.hour >= HORA_MIN:
            return None                                       # reiniciou com o sol de pé: a parte de antes se perdeu
        horas = (tb - ta).total_seconds() / 3600
        if 0 < passo <= SOL_MAX_W_M2 * max(horas, 1 / 60):
            total += passo
    if total <= 0 or total > TETO_WH_M2:
        return None
    return round(total / 1000.0, 3)


def irradiacao_fim_do_dia_kwh(registros, campo):
    """PE II (25/11/2026): o acumulado do dia em kWh/m², que zera à meia-noite, com metade das leituras em falha de
    comunicação (`communication_fault` 28) e pico solto no meio do dia (16/11 às 11:25: 1,69 -> 5,16 -> 1,69). O dia é a
    MEDIANA das leituras boas a partir das 17h (o sol já foi e o acumulado não sobe mais: 16/11 = 3,31, a curva dá 3,30).
    Fica None sem leitura boa em pelo menos 8 das 12 horas de 06h a 17h (regra da temperatura da Tucano) ou sem 3
    leituras boas depois das 17h. Puro (tests/test_coletar_greenyellow.py)."""
    horas, fim = set(), []
    for x in registros or []:
        if x.get("communication_fault") != COM_OK:
            continue
        hora = str(x.get("data_hora") or "")[11:13]
        v = _num((x.get("pontos") or {}).get(campo))
        if not hora.isdigit() or v is None:
            continue
        if 6 <= int(hora) < 18:
            horas.add(int(hora))
        if int(hora) >= FIM_KWH_HORA:
            fim.append(v)
    if len(horas & set(range(6, 18))) < 8 or len(fim) < 3:
        return None
    fim.sort()
    v = fim[len(fim) // 2]
    return round(v, 3) if 0 < v <= TETO_KWH_M2 else None


def energia_exportada_do_dia(registros, campo="active_power"):
    """Registros de `/api/telemetria` de UM relé num dia -> kWh exportados no dia, ou None (Rio do Peixe, relé 3).

    A potência ativa (kW, negativa = exportando) integrada no tempo, só o trecho exportado. Fica None se o dia não está
    inteiro: 1ª leitura boa depois das 05h, última antes das 19h, ou buraco de mais de 15 min entre 05h e 19h (o 05/11
    perdeu um trecho e deu 9% a menos que o multimedidor). Puro (tests/test_coletar_greenyellow.py)."""
    pts = []
    for x in registros or []:
        if x.get("communication_fault") != COM_OK:
            continue
        p = _num((x.get("pontos") or {}).get(campo))
        try:
            t = dt.datetime.fromisoformat(str(x.get("data_hora") or "")[:19])
        except ValueError:
            continue
        if p is not None:
            pts.append((t, p))
    pts.sort()
    if not pts or pts[0][0].hour >= HORA_MIN or pts[-1][0].hour < 19:
        return None
    total = 0.0
    for (ta, pa), (tb, pb) in zip(pts, pts[1:]):
        s = (tb - ta).total_seconds()
        if s > BURACO_MAX_S and (HORA_MIN <= tb.hour < 19 or HORA_MIN <= ta.hour < 19):
            return None
        if 0 < s <= BURACO_MAX_S:
            m = (pa + pb) / 2 * s / 3600
            total += -m if m < 0 else 0.0
    return round(total, 2) if total > 0 else None


def _telemetria(get, scada, equip, dia, tipo="inverter"):
    """O `_telemetria` do coletor: UM equipamento por pedido (a usina inteira de uma vez são 19 MB e 22 s; um inversor,
    2,5 MB e 0,5 s — Irecê 2, 06/10/2026), pelo NOME do equipamento (o `indice` voltava vazio na Cedro, 11/10/2026),
    página a página pelo `apos_ts`."""
    regs, apos = [], None
    for _ in range(50):
        p = {"usina": scada, "desde": dia, "ate": dia, "tipo": tipo, "equipamento": equip, "limit": LIMITE}
        if apos:
            p["apos_ts"] = apos
        d = get("/api/telemetria", p) or {}
        regs.extend(r for r in (d.get("registros") or []) if str(r.get("equipamento")) == equip)
        apos = d.get("proximo_apos_ts")
        if not apos:
            break
    return regs


# ── Interface da recoleta (recoleta_fontes/__init__.py) ─────────────────────────────────────────────────────────────
def contexto(app):
    """O cliente do scadaGridco que a plataforma já tem. O `get()` dele segura o `_LOCK` a cada chamada (uma por vez,
    junto com o tempo real); este módulo NÃO pega o lock de novo — o `threading.Lock` não é reentrante e travaria — nem
    o segura o pedido inteiro, que deixaria o tempo real parado por um minuto ou mais. Credenciais: `SCADAGRIDCO_URL` e
    `SCADAGRIDCO_TOKEN` do tokens.txt, que o app põe no ambiente; quem as lê é o próprio `get()`."""
    sg = getattr(app, "_sg", None) or importlib.import_module("scadagridco")
    return types.SimpleNamespace(mapa=app._recoleta_mapa(), get=sg.get, configurado=sg.configurado,
                                 sem_acesso=sg.SemAcesso, hoje=comum.hoje_br, relogio=time.monotonic)


def plantas(ctx):
    return [{"id": pid, "usina": aba, "destino": "BD_Performance"} for pid, aba in PLANTAS.items()]


def custo(*_a, **_k):
    """O scadaGridco é da Automação Grid Co.: sem cota nem consulta paga."""
    return 0


def buscar(ctx, ids, dias, geracao, etm, chuva):
    """Geração por inversor e ETM das plantas x dias (já validados pelo comum). `chuva` não se aplica: o coletor da
    noite não lê pluviômetro pelo supervisório."""
    if not ctx.configurado():
        raise comum.Recusa(503, "scadaGridco sem SCADAGRIDCO_URL/SCADAGRIDCO_TOKEN no tokens.txt")
    inicio, hoje = ctx.relogio(), ctx.hoje()
    seguidas = [0]
    cache = {}

    def get(rota, params):
        """Uma chamada, com o token recusado parando tudo (como no coletor) e o supervisório fora parando o resto."""
        try:
            d = ctx.get(rota, params, timeout=TIMEOUT_S)
        except ctx.sem_acesso as e:
            raise comum.Recusa(502, "%s — pedir troca à Automação" % e)
        except Exception as e:                                   # noqa: BLE001 — conta para o disjuntor abaixo
            seguidas[0] += 1
            if seguidas[0] >= FALHAS_SEGUIDAS:
                raise _Parou("o scadaGridco não respondeu em %d chamadas seguidas (%s)"
                             % (FALHAS_SEGUIDAS, type(e).__name__))
            raise
        seguidas[0] = 0
        return d

    def tele(scada, equip, dia, tipo):
        # a Cedro 1 e a Cedro 2 leem a MESMA estação: uma chamada só por dia
        k = (scada, equip, dia, tipo)
        if k not in cache:
            cache[k] = _telemetria(get, scada, equip, dia, tipo)
        return cache[k]

    ger, esc, avisos = [], [], []
    conferidos, parou, faltou = set(), None, {}
    for pid in ids:
        aba = PLANTAS[pid]
        cfg = USINAS[aba]
        if geracao and cfg.get("so_vazio_ou_maior"):
            avisos.append("%s: no BD esta aba é \"só vazio ou maior\" (Levi: \"COLETA SÓ O QUE FOR A MAIS OU NÃO TEM "
                          "NADA\"): o coletor da noite não baixa nem repete o que a equipe colou; ao colar, não cubra "
                          "valor maior já gravado" % aba)
        if etm and aba not in ETM:
            avisos.append("%s: sem ETM por esta fonte (o coletor da noite lê só as estações da Cedro, da Irecê 2 "
                          "e o GHI da PE II, as conferidas contra o BD)" % aba)
        if etm and ETM.get(aba, {}).get("so_vazio"):
            avisos.append("%s: no BD a ETM desta aba só entra onde está vazio (Levi, 25/11/2026): ao colar, "
                          "não cubra o que a equipe digitou" % aba)
        if geracao and parou is None and cfg["scada"] not in conferidos:
            conferidos.add(cfg["scada"])
            try:
                avisos.extend(_conferir_equipamentos(get, cfg["scada"]))
            except _Parou as e:
                parou = str(e)
            except comum.Recusa:
                raise
            except Exception as e:                               # noqa: BLE001 — a conferência não impede a busca
                avisos.append("%s: não consegui listar os equipamentos no supervisório (%s); a conferência do de-para "
                              "ficou de fora" % (aba, type(e).__name__))
        velhos = []
        for dia in dias:
            iso = dia.isoformat()
            if (hoje - dia).days > HISTORICO_DIAS:
                velhos.append(iso)
                continue
            if parou is None and ctx.relogio() - inicio > ORCAMENTO_S:
                parou = ("o pedido passou de %d s na fila de uma chamada por vez do scadaGridco; peça de novo esse "
                         "trecho" % ORCAMENTO_S)
            if parou is not None:
                faltou.setdefault(aba, []).append(iso)
                continue
            try:
                linhas, escal, avs = _planta_dia(tele, aba, cfg, iso, geracao, etm)
            except _Parou as e:                                  # a planta-dia em curso não sai pela metade
                parou = str(e)
                faltou.setdefault(aba, []).append(iso)
                continue
            ger.extend(linhas)
            esc.extend(escal)
            avisos.extend(avs)
        if velhos:
            avisos.append("%s: %s fora do histórico do scadaGridco (ele guarda %d dias): não buscado(s)"
                          % (aba, ", ".join(velhos), HISTORICO_DIAS))
    for aba, isos in faltou.items():
        avisos.append("%s: %s não buscado(s): %s" % (aba, ", ".join(isos), parou))
    return {"geracao": ger, "escalares": esc, "avisos": avisos}


def _conferir_equipamentos(get, scada):
    """Os inversores que o supervisório tem e o de-para do coletor não liga viram aviso (não somem): é o jeito de ver o
    inversor novo ou renomeado (a Rodrigues 2 virou "INVERSOR01" em ~20/08/2026 e parou de coletar em silêncio). 1
    chamada barata por usina do supervisório (`/api/mqtt/<usina>`, 0,1 s)."""
    d = get("/api/mqtt/%s" % scada, {}) or {}
    tem = [str(e.get("equipamento") or e.get("indice")) for e in (d.get("equipamentos") or [])
           if e.get("tipo") == "inverter"]
    abas = [aba for aba, cfg in USINAS.items() if cfg["scada"] == scada]
    ligados = {e for aba in abas for e in USINAS[aba]["inversores"]}
    fora = FORA_DE_PROPOSITO.get(scada, {})
    nome = " e ".join(abas)
    out = []
    sem = [e for e in tem if e not in ligados and e not in fora]
    if sem:
        out.append("%s: equipamento(s) %s do supervisório sem de-para no coletor da noite: fora da recoleta (ligar no "
                   "coletar_greenyellow.py e aqui, conferido pelo valor)" % (nome, ", ".join(sem)))
    for e in tem:
        if e in fora:
            out.append("%s: o equipamento %s do supervisório fica de fora: %s" % (nome, e, fora[e]))
    return out


def _planta_dia(tele, aba, cfg, iso, geracao, etm):
    """Uma planta num dia -> (linhas de geração, escalares, avisos). Inversor sem o dia inteiro sai com kWh NULO (não 0,
    "sem dado não se inventa", 06/11/2026) e o motivo no aviso; o que mediu zero com comunicação boa sai zero, como em
    toda fonte."""
    linhas, escal, avisos, sem = [], [], [], {}
    if geracao:
        for equip, coluna in cfg["inversores"].items():
            try:
                v, motivo, ate = _leitura_do_dia(tele(cfg["scada"], equip, iso, "inverter"))
            except (_Parou, comum.Recusa):
                raise
            except Exception as e:                               # noqa: BLE001 — um inversor não derruba a usina
                v, motivo, ate = None, "erro na leitura (%s)" % type(e).__name__, None
            linhas.append({"usina": aba, "inversor": coluna, "data": iso,
                           "kwh": None if v is None else round(v, 2)})
            if v is None:
                sem.setdefault(motivo, []).append(coluna + (" (até %s)" % ate if ate else ""))
        if sem:
            partes = "; ".join("%s: %s" % (m, ", ".join(cols)) for m, cols in sem.items())
            avisos.append("%s %s: %d de %d inversores sem valor (fica nulo, não zero) — %s"
                          % (aba, iso, sum(len(c) for c in sem.values()), len(cfg["inversores"]), partes))
    if etm and aba in ETM:
        e = ETM[aba]
        regua = {"contador": irradiacao_pelo_contador,
                 "fim_do_dia_kwh": irradiacao_fim_do_dia_kwh}.get(e.get("regra"), irradiacao_do_dia)
        for coluna, par in e.items():
            if coluna in ("scada", "regra", "so_vazio"):
                continue
            equip, campo = par
            try:
                v = regua(tele(e["scada"], equip, iso, "weather"), campo)
                motivo = "sem a leitura do dia inteiro, ou zero o dia todo (sensor sem leitura)"
            except (_Parou, comum.Recusa):
                raise
            except Exception as ex:                              # noqa: BLE001
                v, motivo = None, "erro na leitura (%s)" % type(ex).__name__
            escal.append({"usina": aba, "data": iso, "coluna": coluna, "valor": v})
            if v is None:
                avisos.append("%s %s %s: %s; fica nulo" % (aba, iso, coluna, motivo))
    if geracao and aba in MEDIDOR:
        m = MEDIDOR[aba]
        try:
            v = energia_exportada_do_dia(tele(m["scada"], m["equip"], iso, "relay"))
            motivo = "o relé não leu o dia inteiro (buraco de mais de 15 min entre 05h e 19h)"
        except (_Parou, comum.Recusa):
            raise
        except Exception as ex:                              # noqa: BLE001
            v, motivo = None, "erro na leitura (%s)" % type(ex).__name__
        escal.append({"usina": aba, "data": iso, "coluna": m["coluna"], "valor": v})
        if v is None:
            avisos.append("%s %s %s: %s; fica nulo" % (aba, iso, m["coluna"], motivo))
    return linhas, escal, avisos
