# -*- coding: utf-8 -*-
"""Recoleta da SunOp (as 10 GD da Athon) para a Coletas do Nexus, no contrato do comum.py, com destino o BD_Performance.

A REGRA é a do coletor que roda toda noite, portada daqui (17/11/2026):
`coleta API PV/src/coletar_sunop.py` (a régua) e `coleta API PV/src/sunop_client.py` (as chamadas e o lote que falha).
- Geração do dia por inversor = o MAIOR valor do EPD (energia produzida no dia, um contador que zera à meia-noite da
  usina). Inversor sem leitura no dia é nulo, nunca 0.
- POA e GHI = integral trapezoidal da curva (W/m²) em kWh/m², com o intervalo real entre os carimbos e cada ponto
  limitado a 0..1600 W/m² (`POA_TETO`: acima disso é erro de sensor).
- A coluna sai com o nome do BD_Performance (`_build_escalares`/`_COL_UNICA` do coletor): "IPOA (kWh/m²) ETM" e
  "GHI (kWh/m²)". A TIM100 tem uma coluna por estação; usina com mais de uma estação (MAB100) fica com a de dado válido
  (o maior valor > 0); a TIM200 sem POA válido usa a POA-RI (traseira), o "fallback temporário" do coletor.
- O de-para é a aba Equipamentos: o `load_name_mapping` do coletor é o `ctx.mapa` aqui, (MRO100, INV_1) ->
  ("Athon - Mãe do Rio 1 - PA", "Inversor 1.1"). Inversor sem de-para vira aviso: a coleta da noite também não o grava
  (vai para a aba Sem_Correspondencia).
- Lote que falha deixa a usina SEM VALOR no dia, não com o que veio (sunop_client, 06/08/2026: com um lote faltando o
  máximo do EPD é o parcial do último instante que respondeu, e a coleta gravou 5.457 kWh no MRO100, o certo era 36.813,
  6.555 no TIM200 e ZERO no CPP100, dizendo "SunOp: OK").
- O dia é o da usina: a SunOp guarda em UTC, e o `use_plant_timezone=true` faz a janela e os carimbos virem na hora dela
  (é o que o coletor e a plataforma pedem). Ponto de outro dia fica de fora (o drill do gêmeo saía 3 h adiantado até
  28/09 e o PR pegava o EPD da véspera: MRO100 21/09, 1.902 kWh por inversor em vez de 1.198).

Custo: a SunOp é PAGA, 100 mil requisições por mês para a conta (10 usinas x 10.000), e a cota já estourou uma vez
(323.816 de 01 a 29/09/2026). A plataforma limita a 3.000 por dia somando as máquinas (`SUNOP_TETO_DIA`: 2.700 no
servidor, 300 no PC) e domingo só a ronda busca (`_sunop_pausa`, Levi 04/10/2026). Esta recoleta:
- pede pela própria `_sunop_req` da plataforma, que conta cada POST no contador do dia (`_sunop_uso_conta`) e respeita a
  pausa, o disjuntor da borda e a credencial vencida: nenhuma requisição fura a contagem;
- pede em LOTE que atravessa usinas (`SUNOP_LOTE_PATHNAMES`, 600 pathnames por POST; misturar usinas no mesmo POST foi
  medido em 02/09/2026), um POST por lote por DIA, nunca usina por usina num laço de dias (plataforma/CLAUDE.md, "Para
  não repetir"). As 10 usinas inteiras cabem em ~1 POST por dia;
- não tenta de novo: `custo()` promete n requisições e `permite()`/`gastar()` autorizam n; uma tentativa a mais gastaria
  fora do que foi autorizado. O lote que falhou volta como aviso e a pessoa pede de novo;
- não passa pelo acervo do gêmeo (o `_sunop_analog_history` passa): o lote que falha lá vira [] em silêncio, que é o
  defeito de 06/08, e o acervo tem buraco em dia passado (30–43 dos 48 quartos de hora). O coletor da noite também vai
  direto à SunOp.
- `TETO` próprio: 150 requisições por dia para a recoleta (`RECOLETA_SUNOP_TETO_DIA`, em memória no comum: o restart
  zera), dentro do teto do dia da máquina.
"""
import datetime as dt
import os
import re
import types
from concurrent.futures import ThreadPoolExecutor

FONTE = "sunop"
PAGA = True
MAX_PLANTAS = 10                 # as 10 GD da Athon num pedido só, como o coletor da noite
DESTINO = "BD_Performance"       # o coletar_sunop.py é consumido pelo preencher_bd_performance.py
INST = "gridco"                  # a conta da Athon; a Axis é outra conta e está sem token de API desde julho

LOTE_PADRAO = 600                # o SUNOP_LOTE_PATHNAMES do app.py; o contexto() copia o valor de lá
TRABALHADORES = 2                # 2, não mais: rajada é o que abre a borda do CloudFront (5 em paralelo abria, 03/08)
TIMEOUT_S = 120                  # o mesmo do _sunop_analog_history_api: estourar o tempo apagaria meio lote


def _teto_do_ambiente(valor, padrao=150):
    """O teto do dia da recoleta. Zero ou negativo vale o padrão: no `comum.gastar` teto 0 é "fonte sem cota", ou
    seja, sem limite nenhum, o contrário do que quem escreveu 0 quis."""
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        return padrao
    return n if n > 0 else padrao


TETO = _teto_do_ambiente(os.environ.get("RECOLETA_SUNOP_TETO_DIA"))

# --- a régua do coletor (coletar_sunop.py), portada sem mudar a conta --------------------------------------------------
POA_TETO = 1600.0                # W/m² (clamp de erro de sensor)

# Único caso com 2 colunas separadas no BD: TIM100 (uma coluna por estação).
_TIM100_COL = {
    ("ESTM_1", "poa"): "IPOA (kWh/m²) ETM 1", ("ESTM_1", "ghi"): "GHI ETM 1 (kWh/m²)",
    ("ESTM_2", "poa"): "IPOA (kWh/m²) ETM 2", ("ESTM_2", "ghi"): "GHI ETM 2 (kWh/m²)",
}
# Demais plantas: 1 coluna só, independente do nome da estação (ESTM, ESTM_1...).
_COL_UNICA = {"poa": "IPOA (kWh/m²) ETM", "ghi": "GHI (kWh/m²)"}

# Os mesmos parâmetros do coletor e da plataforma: sem `period` vale o padrão da API (média de 5 min), que é o que a
# régua do EPD máximo e da integral sempre leu.
_PARAMS = {"fill_missing": "false", "source": "Historical", "use_plant_timezone": "true"}

# O que o plantas() viu de cada usina, para o custo() contar sem o ctx (o contrato não o passa): {planta: (EPD, POA/GHI)}.
# O `_recoleta_por_fonte` chama plantas() antes do custo() no mesmo pedido, então a conta é a do metadado de agora.
_ANOTADO = {"lote": LOTE_PADRAO, "caminhos": {}}


def _build_escalares(planta, station_vals):
    """{(estacao, medida): valor} -> {coluna_BD: valor}, o `_build_escalares` do coletor.

    Uma diferença, de propósito: na TIM100 o coletor guarda o 0 (só testa `is not None`); aqui 0 é nulo como nas outras
    usinas. A integral só dá 0 com a estação lendo zero o dia inteiro, que é sensor parado, não sol nenhum, e a recoleta
    existe para colar no BD: 0 nunca vai por cima de dado (Levi, 20/10/2026) e sem dado não se inventa (06/11/2026)."""
    out = {}
    if planta == "TIM100":
        for (est, med), v in station_vals.items():
            col = _TIM100_COL.get((est, med))
            if col and v is not None and v > 0:
                out[col] = v
    else:
        for med, col in _COL_UNICA.items():
            validos = [v for (e, m), v in station_vals.items() if m == med and v is not None and v > 0]
            if validos:
                out[col] = max(validos)
            elif planta == "TIM200" and med == "poa":
                # Fallback TEMPORÁRIO do coletor: TIM200 sem POA válido -> usa POA-RI (traseira)
                ri = [v for (e, m), v in station_vals.items() if m == "poari" and v is not None and v > 0]
                if ri:
                    out[col] = max(ri)
    return out


def _colunas_esperadas(planta, irr):
    """As colunas que a usina TEM no BD pelas estações do metadado: as que a fonte não preencheu saem nulas, para a
    Coletas ver que a SunOp foi consultada e não tinha o valor (nulo é nulo; coluna que a usina não mede nem aparece)."""
    if planta == "TIM100":
        return [col for k, col in _TIM100_COL.items() if k in irr]
    meds = {m for (_e, m) in irr}
    out = []
    if "poa" in meds or (planta == "TIM200" and "poari" in meds):
        out.append(_COL_UNICA["poa"])
    if "ghi" in meds:
        out.append(_COL_UNICA["ghi"])
    return out


def _integral(serie):
    """Integral trapezoidal da curva (W/m²) -> kWh/m², o `_integral` do coletor. Δt real entre os carimbos (aqui já
    convertidos em datetime na hora da usina, ver `_na_hora_da_usina`)."""
    if not serie or len(serie) < 2:
        return None
    tot = 0.0
    for (t0, v0), (t1, v1) in zip(serie, serie[1:]):
        dt_h = (t1 - t0).total_seconds() / 3600.0
        a = min(max(v0 or 0, 0), POA_TETO)
        b = min(max(v1 or 0, 0), POA_TETO)
        tot += (a + b) / 2.0 * dt_h / 1000.0
    return round(tot, 3)


def _epd_do_dia(serie):
    """O máximo do EPD no dia (kWh), arredondado como o coletor. Sem ponto nenhum é nulo; zero medido segue zero."""
    vals = [v for _t, v in (serie or ()) if v is not None]
    return round(max(vals), 2) if vals else None


# --- o metadado da plataforma lido como o coletor lê --------------------------------------------------------------------
def _invnum(x):
    """Ordem do inversor pelo número do id ('INV_2' antes de 'INV_10'), a do `_sunop_invnum` do app.py."""
    nums = re.findall(r"\d+", str(x))
    return tuple(int(n) for n in nums) if nums else (999,)


def _caminhos(meta, planta):
    """(EPD {inversor: pathname}, irradiância {(estação, medida): pathname}) pela regra do coletor.

    O metadado é o da plataforma (`_load_sunop_plant_meta`), que guarda mais do que o do coletor: a "AIML" (a POA da
    previsão, sem sensor) fica nas usinas de estação única, e o `_build_escalares` pegaria o maior valor entre ela e a
    estação de verdade. Aqui só entra estação "ESTM*" e, havendo numeradas, a "ESTM" solta sai — como no sunop_client.
    A POA-RI só serve à TIM200 (o fallback), então só ela a pede: mesma conta, menos pathname no lote."""
    meta = meta or {}
    epd = {inv: o["EPD"] for inv, o in (meta.get("inv_other") or {}).items()
           if str(inv).startswith("INV_") and isinstance(o, dict) and o.get("EPD")}
    est = {s: d for s, d in (meta.get("etm_stations") or {}).items() if str(s).startswith("ESTM") and isinstance(d, dict)}
    numeradas = [s for s in est if s != "ESTM"]
    if numeradas:
        est = {s: est[s] for s in numeradas}
    medidas = ("poa", "ghi", "poari") if planta == "TIM200" else ("poa", "ghi")
    irr = {(s, k): p for s, d in est.items() for k, p in d.items() if k in medidas and p}
    return epd, irr


def _aba_da_planta(mapa, planta, epd):
    """A aba do BD da usina: a da linha da usina na aba Equipamentos e, sem ela, a única aba para onde vão os inversores
    (no recorte do Nexus a linha UFV da Athon vem sem "Usina Supervisório", só as dos inversores a têm)."""
    aba = mapa.usina_de(planta)
    if aba:
        return aba
    abas = {alvo[0] for alvo in (mapa.inversor_de(planta, inv) for inv in epd) if alvo}
    return next(iter(abas)) if len(abas) == 1 else None


# --- o contrato ---------------------------------------------------------------------------------------------------------
def contexto(app):
    """O que a recoleta usa do app.py. `get_sunop_token` vai junto mas NÃO é chamado: o serviço de dados usa o token de
    API, que a `_sunop_req` põe sozinha (`_sunop_data_headers`); chamá-lo validaria o token web na rede
    (`cfg:check_token`), uma requisição a mais na conta. O gasto do dia é o `_sunop_gasto_hoje` (este processo + o
    anterior + o outro processo da máquina), o mesmo da pausa: o `_sunop_uso_hoje` sozinho é só o processo web, e quem
    gasta a SunOp é o worker."""
    S = app._si(INST)
    lote = int(getattr(app, "SUNOP_LOTE_PATHNAMES", LOTE_PADRAO) or LOTE_PADRAO)
    _ANOTADO["lote"] = lote
    return types.SimpleNamespace(
        mapa=app._recoleta_mapa(),
        inst=INST,
        data_url=S["data"],
        meta=S["meta"],                               # o dicionário vivo: o ensure_sunop_meta completa nele
        ensure_meta=lambda: app.ensure_sunop_meta(INST),
        get_sunop_token=app.get_sunop_token,
        sunop_req=app._sunop_req,
        pausa=app._sunop_pausa,
        teto_dia=int(app.SUNOP_TETO_DIA),
        gasto_hoje=app._sunop_gasto_hoje,
        edge_aberto=app._sunop_edge_aberto,
        sem_rede=lambda: app._sunop_sem_rede(INST),
        fuso=app._sunop_fuso_usina,
        lote=lote,
    )


def plantas(ctx):
    """As usinas da Athon com pathname de EPD ou de irradiância e com aba no BD. O metadado é o cache da plataforma
    (o mesmo da tabela da Athon): já carregado, nenhuma chamada; a frio, o `ensure_sunop_meta` busca pela `_sunop_req`
    (contada) e na pausa não vai à rede. Usina sem aba fica de fora, como na fonte apipv: a coleta também não a grava."""
    ctx.ensure_meta()
    out = []
    for planta in sorted(ctx.meta):
        epd, irr = _caminhos(ctx.meta.get(planta), planta)
        if not epd and not irr:
            continue
        aba = _aba_da_planta(ctx.mapa, planta, epd)
        if not aba:
            continue
        _ANOTADO["caminhos"][planta] = (len(epd), len(irr))
        out.append({"id": planta, "usina": aba, "destino": DESTINO})
    return out


def custo(ids, dias, geracao, etm, chuva):
    """Os POSTs ao /v2/analog_values que a busca faz: por dia, os pathnames das usinas pedidas em lotes de
    `SUNOP_LOTE_PATHNAMES`. Usina que o plantas() não anotou conta um lote só dela por dia (para mais, nunca para menos).
    Chuva não custa: a SunOp não a mede no coletor."""
    if not dias or not (geracao or etm):
        return 0
    lote = max(1, int(_ANOTADO["lote"] or LOTE_PADRAO))
    n_caminhos, sem_conta = 0, 0
    for i in dict.fromkeys(str(x) for x in ids):
        c = _ANOTADO["caminhos"].get(i)
        if c is None:
            sem_conta += 1
            continue
        n_caminhos += (c[0] if geracao else 0) + (c[1] if etm else 0)
    return len(dias) * (-(-n_caminhos // lote) + sem_conta)


def permite(ctx, n):
    """None ou o motivo da recusa. A pausa vem sem a janela da ronda (`considera_ronda=False`): a ronda abre a SunOp por
    até 15 min no domingo e depois do teto, e a recoleta não é a ronda."""
    if n <= 0:
        return None                               # nenhuma requisição: nada a pausar
    motivo = ctx.pausa(considera_ronda=False)
    if motivo == "domingo":
        return ("SunOp pausada: domingo só a ronda do WhatsApp busca (Levi, 04/10/2026); recolete a partir de segunda")
    if motivo == "teto":
        return ("SunOp pausada: o teto do dia desta máquina (%d requisições) já foi atingido e só a ronda busca até a "
                "meia-noite; recolete amanhã" % ctx.teto_dia)
    if motivo:
        return "SunOp pausada (%s)" % motivo
    gasto = int(ctx.gasto_hoje() or 0)
    if gasto + n > ctx.teto_dia:
        return ("esta recoleta gastaria %d requisição(ões) da SunOp e passaria do teto do dia desta máquina (%d de %d "
                "usadas hoje; a cota é de 100 mil por mês); peça menos dias ou recolete amanhã"
                % (n, gasto, ctx.teto_dia))
    if ctx.edge_aberto():
        return "a borda da SunOp (CloudFront) está bloqueando agora; tente em alguns minutos"
    sem = ctx.sem_rede()
    if sem:
        return "a SunOp não pode ser chamada agora (%s)" % sem
    return None


def _na_hora_da_usina(ts, fuso):
    """O carimbo como datetime na hora da usina, sem fuso. Com `use_plant_timezone=true` a SunOp já devolve a hora da
    usina sem fuso no texto; carimbo com fuso (o "+00:00" que o acervo do gêmeo deixava passar até 28/09) é convertido."""
    try:
        d = dt.datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d.astimezone(fuso).replace(tzinfo=None) if d.tzinfo else d


def _fuso(ctx, planta):
    try:
        return ctx.fuso(planta)
    except Exception:                             # noqa: BLE001 — sem cadastro ou sem base de fusos: Brasília
        return dt.timezone(dt.timedelta(hours=-3))


def _post(ctx, dia, pathnames):
    """(lista de registros, None) ou (None, motivo). A conferência do formato é a do sunop_client (08 a 11/09/2026: a
    etapa da SunOp morreu quatro noites com "string indices must be integers" porque o 200 não era lista)."""
    iso = dia.isoformat()
    params = dict(_PARAMS, start_time="%sT00:00:00" % iso, end_time="%sT23:59:59" % iso)
    try:
        r = ctx.sunop_req("POST", "%s/v2/analog_values" % ctx.data_url, ctx.inst,
                          params=params, json={"pathnames": list(pathnames)}, timeout=TIMEOUT_S)
    except Exception as e:                        # noqa: BLE001 — falha de um lote não derruba os outros
        return None, "%s: %s" % (type(e).__name__, e)
    if r is None:
        return None, "sem resposta: pausa, borda bloqueada, credencial ou rede"
    if r.status_code != 200:
        return None, "HTTP %s" % r.status_code
    try:
        corpo = r.json()
    except Exception:                             # noqa: BLE001 — 200 com corpo ilegível é lote falho
        return None, "HTTP 200 com corpo que não é JSON"
    if corpo is None:
        corpo = []
    if not isinstance(corpo, list):
        return None, "HTTP 200 devolveu %s, esperava lista" % type(corpo).__name__
    if any(not isinstance(x, dict) for x in corpo):
        return None, "HTTP 200 com item fora do formato"
    return corpo, None


def buscar(ctx, ids, dias, geracao, etm, chuva):
    avisos = []
    if chuva:
        avisos.append("a SunOp não tem chuva no coletor da noite (só geração e POA/GHI); a chuva vem pela fonte chuva")
    if not (geracao or etm):
        return {"geracao": [], "escalares": [], "avisos": avisos}

    plano = {}                                    # planta -> (EPD pedidos, irradiância pedida, aba)
    for planta in dict.fromkeys(str(i) for i in ids):
        meta = ctx.meta.get(planta)
        epd, irr = _caminhos(meta, planta)
        if not epd and not irr:
            avisos.append("%s: sem a lista de pontos da SunOp agora (o metadado não carregou); nada buscado" % planta)
            continue
        plano[planta] = (epd if geracao else {}, irr if etm else {}, _aba_da_planta(ctx.mapa, planta, epd))

    # Um POST por lote por dia, com as usinas juntas na mesma ordem em que o custo() as contou.
    dono, caminhos = {}, []
    for planta, (epd, irr, _aba) in plano.items():
        for p in list(epd.values()) + list(irr.values()):
            if p not in dono:
                dono[p] = planta
                caminhos.append(p)
    lote = max(1, int(ctx.lote or LOTE_PADRAO))
    tarefas = [(dia, caminhos[i:i + lote]) for dia in dias for i in range(0, len(caminhos), lote)]
    resultados = []
    if tarefas:
        with ThreadPoolExecutor(max_workers=min(TRABALHADORES, len(tarefas))) as ex:
            resultados = list(ex.map(lambda t: _post(ctx, t[0], t[1]), tarefas))

    fusos = {planta: _fuso(ctx, planta) for planta in plano}
    series, falhas = {}, {}                       # (dia, pathname) -> [(datetime, valor)]; (planta, dia) -> motivo
    for (dia, pedidos), (corpo, motivo) in zip(tarefas, resultados):
        if motivo:
            for p in pedidos:
                falhas.setdefault((dono[p], dia), motivo)
            continue
        for rec in corpo:
            p, v = rec.get("pathname"), rec.get("value")
            if p not in dono or isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            t = _na_hora_da_usina(rec.get("timestamp"), fusos[dono[p]])
            if t is None or t.date() != dia:
                continue                          # ponto de outro dia (ou carimbo ilegível) não entra na conta do dia
            series.setdefault((dia, p), []).append((t, v))
    for s in series.values():
        s.sort()

    geracao_out, escalares, sem_depara, sem_aba = [], [], {}, set()
    for planta, (epd, irr, aba) in plano.items():
        for dia in dias:
            iso, falhou = dia.isoformat(), (planta, dia) in falhas
            for inv in sorted(epd, key=_invnum):
                alvo = ctx.mapa.inversor_de(planta, inv)
                if alvo is None:
                    sem_depara.setdefault(planta, set()).add(inv)
                    continue
                kwh = None if falhou else _epd_do_dia(series.get((dia, epd[inv])))
                geracao_out.append({"usina": alvo[0], "inversor": alvo[1], "data": iso, "kwh": kwh})
            if not irr:
                continue
            if not aba:
                sem_aba.add(planta)
                continue
            vals = {} if falhou else {k: _integral(series.get((dia, p))) for k, p in irr.items()}
            cols = _build_escalares(planta, vals)
            for col in _colunas_esperadas(planta, irr):
                escalares.append({"usina": aba, "data": iso, "coluna": col, "valor": cols.get(col)})

    por_falha = {}
    for (planta, dia), motivo in sorted(falhas.items(), key=lambda x: (x[0][1], x[0][0])):
        por_falha.setdefault((dia, motivo), []).append(planta)
    for (dia, motivo), pls in por_falha.items():
        avisos.append("%s: a SunOp não devolveu o lote de %s (%s). O dia fica SEM valor nessas usinas: com um lote a "
                      "menos o total sairia menor que o real (06/08/2026: 5.457 kWh no MRO100 em vez de 36.813). Peça "
                      "de novo." % (dia.isoformat(), ", ".join(pls), motivo))
    for planta, invs in sorted(sem_depara.items()):
        lista = sorted(invs, key=_invnum)
        avisos.append("%s: %d inversor(es) da SunOp sem de-para na aba Equipamentos (a coleta da noite também não os "
                      "grava): %s" % (planta, len(lista), ", ".join(lista[:12]) + (" ..." if len(lista) > 12 else "")))
    for planta in sorted(sem_aba):
        avisos.append("%s: sem a aba do BD na aba Equipamentos; o POA/GHI fica fora da planilha" % planta)
    return {"geracao": geracao_out, "escalares": escalares, "avisos": avisos}
