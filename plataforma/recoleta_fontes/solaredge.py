# -*- coding: utf-8 -*-
"""Recoleta da SolarEdge (as 7 usinas da RenoGrid, BD_Performance) no formato do contrato da Coletas (comum.py).

A REGRA DE CÁLCULO é a do coletor que roda toda noite (etapa 3/5 do `coletor.py`):
`coleta API PV/src/coletar_solaredge.py`, lido em 17/11/2026. Portado daqui:
- geração AC do dia por inversor = `se_ac_energy`: generate-chart, métrica `measurement / pv_measurements /
  energy_since_last_telemetry`, nível INVERTER, `alignmentGranularity: DAY`, o dia cortado NO FUSO DA USINA
  (`_day_range`: Cuiabá é UTC−4, então o dia 10/11 vai de 04:00Z a 03:59:59.999Z), soma das linhas em Wh / 1000, 2 casas;
- IPOA = `se_irradiance` + `coletar_ipoa`: render-chart MONTH do 1º inversor, série "Global Irradiance" (W/m², valor
  diário) × 0,25 h / 1000, 2 casas, o dia do ponto pela data UTC do instante; Colider 2 e Xavantina 2 SEMPRE com a
  irradiância da 1 (`IRR_MIRROR`: não têm estação própria);
- tradução = `_collect_site` com o `load_name_mapping` do coletor, que aqui é o `ctx.mapa.inversor_de(usina_sup,
  equip_sup)` (a mesma aba Equipamentos, a mesma chave de nome);
- coluna do IPOA = "IPOA (kWh/m²)", o nome que o `coletar_ipoa` escreve na aba Escalares e que o
  `preencher_bd_performance` grava por NOME EXATO. É o cabeçalho das 7 abas (conferido no espelho do BD_Performance de
  17/11 00:34); a "IPOA (kWh/m²) DEF" do lado é fórmula e não se toca.

O que muda de propósito em relação ao coletor:
- inversor sem valor é NULO, não 0. O coletor grava `round((wh or 0) / 1000, 2)`: inversor que a SolarEdge não devolveu
  vira 0 no BD, igual a inversor parado. Aqui fica `kwh: None` com aviso (Levi, 06/11/2026: "sem dado não se inventa");
  com a linha nula, o `comum.dias_fora` ainda enxerga o dia da usina que a SolarEdge não respondeu;
- uma chamada por vez (o coletor usa 4 em paralelo), e uma recoleta por vez: ver TETO;
- sem o fuso da usina, o dia é cortado no horário de Brasília, com aviso. O coletor caía no horário local da máquina, que
  no PC dele é Brasília; no servidor (UTC) seria 3 h fora.

Nada é gravado: a Coletas monta a planilha e a pessoa cola.
"""
import datetime as dt
import threading
import types

try:
    from zoneinfo import ZoneInfo
except ImportError:                      # pragma: no cover - Python sem zoneinfo
    ZoneInfo = None

from recoleta_fontes import comum

FONTE = "solaredge"
PAGA = False

# Por que 3 plantas por pedido: as chamadas são em série (ver TETO) e cada uma custa ~1,3 s (medido no generate-chart
# da curva das strings, 25/09/2026). Por planta: 1 lista de dispositivos + 1 generate-chart por dia + 1 render-chart do
# mês para o IPOA. Com 3 plantas × 7 dias (o MAX_DIAS do comum) são ~30 chamadas, ~40 s; com as 7 da RenoGrid de uma vez
# seriam ~62, perto dos 100 s em que o Cloudflare corta o pedido (524) no caminho Nexus -> plataforma. A Coletas fatia.
MAX_PLANTAS = 3

# TETO = None, de propósito. A SolarEdge não cobra e este portal (monitoring.solaredge.com/services/...) não tem cota
# por dia: o limite dela é de RITMO. Sob rajada ela responde 200 VAZIO — é o "string AUSENTE da resposta é throttling"
# do CLAUDE.md da plataforma (25/09/2026), o "a SolarEdge sob limite responde 200 vazio" da Potência Ativa (13/10) e o
# motivo do `_retry_solaredge.py` do coletor ("tolerante a throttling: 1 site por vez, com pausas"). Um teto por dia não
# segura rajada nenhuma; o que protege a tabela do tempo real, que usa a MESMA conta (`fetch_all_solaredge`, 4 sites em
# paralelo a cada ciclo), é o ritmo: uma recoleta por vez (`_UMA_POR_VEZ`), uma chamada por vez e o pedido pequeno
# (MAX_PLANTAS × MAX_DIAS). Além disso o `comum.gastar` conta consultas PAGAS e aqui o custo é 0: um teto numérico
# ficaria inerte e a Coletas mostraria um saldo que nunca desce.
TETO = None

COLUNA_IPOA = "IPOA (kWh/m²)"
IRR_MIRROR = {"Colider 2": "Colider 1", "Xavantina 2": "Xavantina 1"}       # o do coletor, com os nomes dele
_ESPELHO = {comum.chave_nome(k): v for k, v in IRR_MIRROR.items()}         # pela chave: "Colíder 2" também casa
LOTE = 50                                                                  # serials por generate-chart, como no coletor
_BRASILIA = dt.timezone(dt.timedelta(hours=-3), "Brasília")                # sem horário de verão desde 2019
_UMA_POR_VEZ = threading.Lock()


def contexto(app):
    """O que a recoleta usa da plataforma, sem import circular: a lista de sites (`se_sites`), os dispositivos
    (`se_devices`, que deixa o motivo da falha em `_se_dev_falha`), o render-chart do mês (`_se_render_month`, o MESMO
    corpo do `se_irradiance` do coletor), a sessão HTTP (`_http`) e os cabeçalhos com o login Cognito automático
    (`_se_headers` -> `_get_se_cookie` -> `_se_login`, credencial do `se_credentials.txt`). Nenhum token colado."""
    return types.SimpleNamespace(mapa=app._recoleta_mapa(), sites=app.se_sites, devices=app.se_devices,
                                 dev_falha=app._se_dev_falha, render_mes=app._se_render_month, http=app._http,
                                 headers=app._se_headers, base=app.SE_BASE)


def _memo(ctx):
    """Guarda, no contexto do pedido, o que já foi lido: a rota chama plantas() e depois buscar() no mesmo ctx, e a
    lista de sites e os dispositivos de uma usina não precisam ir duas vezes à SolarEdge."""
    m = getattr(ctx, "_memo", None)
    if m is None:
        m = ctx._memo = {"devs": {}}
    return m


def _sites(ctx):
    m = _memo(ctx)
    if m.get("sites") is None:
        m["sites"] = list(ctx.sites() or [])
    if not m["sites"]:
        # o `se_sites` devolve [] quando a SolarEdge cai, o login falha ou ela responde vazio por limite: dizer isso,
        # e não "planta que esta fonte não conhece" (o validar recusaria todo id com a lista vazia)
        m["sites"] = None
        raise comum.Recusa(502, "a SolarEdge não devolveu a lista de usinas (fora do ar, login ou limite de consultas);"
                                " tente em alguns minutos")
    return m["sites"]


def _devs(ctx, sid):
    """(dispositivos, motivo da falha ou None). Lista vazia não fica guardada: a próxima usina pode tentar de novo."""
    m = _memo(ctx)["devs"]
    if int(sid) not in m:
        d = ctx.devices(int(sid))
        if not d:
            falha = (ctx.dev_falha or {}).get(int(sid))
            return [], (falha[1] if falha else "a SolarEdge não devolveu os dispositivos da usina")
        m[int(sid)] = list(d)
    return m[int(sid)], None


def plantas(ctx):
    out = []
    for s in _sites(ctx):
        aba = ctx.mapa.usina_de(s.get("nome") or "")
        if aba:                              # site fora da aba Equipamentos: a coleta também não o grava (como na apipv)
            out.append({"id": str(s["id"]), "usina": aba, "destino": "BD_Performance", "planta": s.get("nome")})
    return sorted(out, key=lambda p: p["usina"])


def custo(ids, dias, geracao, etm, chuva):
    return 0                                 # a SolarEdge não cobra: o limite é de ritmo (ver TETO)


def _usina_nome(site):
    """`_usina_nome` do coletor: "UFV Xavantina 2" -> "Xavantina 2" (é a chave do IRR_MIRROR)."""
    return str(site.get("nome", "")).replace("UFV ", "").replace("ufv ", "").strip()


def _agora():
    return dt.datetime.now(dt.timezone.utc)


def _fuso(tzname):
    """(fuso, True) pelo `timeZone` do searchSites; (Brasília, False) sem ele ou com nome que o zoneinfo não conhece."""
    if tzname and ZoneInfo:
        try:
            return ZoneInfo(str(tzname)), True
        except Exception:                    # noqa: BLE001 - nome inválido: cai no de Brasília, com aviso
            pass
    return _BRASILIA, False


def dia_utc(tzname, dia, agora=None):
    """Porte do `_day_range` do coletor: (from, to) em ISO-Z cobrindo o dia `dia` NO FUSO DA USINA, da meia-noite local
    a 23:59:59.999. Se o dia ainda não fechou lá, `to` = agora: o servidor libera "ontem" pelo relógio de Brasília, e à
    00:30 de Brasília ainda são 23:30 em Cuiabá (o coletor fazia o mesmo com o dia de hoje)."""
    if isinstance(dia, str):
        dia = dt.date.fromisoformat(dia)
    tz, _ = _fuso(tzname)
    ini = dt.datetime(dia.year, dia.month, dia.day, tzinfo=tz)
    fim = ini + dt.timedelta(days=1) - dt.timedelta(milliseconds=1)
    agora = agora or _agora()
    if fim > agora:
        fim = agora
    utc = dt.timezone.utc
    return (ini.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            fim.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%S.999Z"))


def energia_ac(ctx, site_id, serials, tzname, dia):
    """Porte do `se_ac_energy` do coletor -> ({serial: kWh ou None}, [motivo de cada lote que não veio]).

    Serial AUSENTE do mapa = a SolarEdge não o devolveu (lote que caiu, ou 200 vazio por limite): é leitura que não veio,
    não inversor parado (a regra do lote falho de 09/09/2026 em `se_string_power`). Serial presente com todas as linhas
    nulas = None. Só número da fonte vira número, inclusive o 0 que ela mandou."""
    frm, to = dia_utc(tzname, dia)
    url = "%s/services/cni/ui-api/pages/site/analysis/custom/site/%s/generate-chart" % (ctx.base, site_id)
    try:
        cab = ctx.headers()
    except Exception as e:                   # noqa: BLE001 - sem login não há leitura: vira aviso, não 500
        return {}, ["login na SolarEdge falhou (%s)" % type(e).__name__]
    kwh, falhas = {}, []
    for i in range(0, len(serials), LOTE):
        lote = serials[i:i + LOTE]
        payload = {"reportPeriod": {"from": frm, "to": to},
                   "datasources": [{"metrics": [
                       {"metricType": "measurement", "metricsCategoryName": "pv_measurements",
                        "uri": "energy_since_last_telemetry"}],
                       "datasourcePopulation": {"populationType": "deviceList", "siteId": int(site_id),
                                                "deviceType": "INVERTER", "deviceSerials": lote},
                       "alignmentGranularity": "DAY"}]}
        try:
            r = ctx.http().post(url, headers=cab, json=payload, timeout=40)
        except Exception as e:               # noqa: BLE001
            falhas.append("%s: %s" % (type(e).__name__, str(e)[:120]))
            continue
        if r.status_code != 200:
            falhas.append("HTTP %s" % r.status_code)
            continue
        try:
            d = r.json()
        except ValueError:
            falhas.append("resposta 200 sem corpo (limite de consultas da SolarEdge)")
            continue
        metas = ((d.get("meta") or {}).get("datasetsMeta") or []) if isinstance(d, dict) else []
        dados = (d.get("data") or []) if isinstance(d, dict) else []
        if not metas:
            falhas.append("resposta 200 vazia (limite de consultas da SolarEdge)")
            continue
        for j, meta in enumerate(metas):
            serial = ((meta or {}).get("reportObject") or {}).get("entityId")
            if serial is None or j >= len(dados):
                continue
            wh = [row[1] for row in (dados[j] or []) if isinstance(row, (list, tuple)) and len(row) > 1
                  and isinstance(row[1], (int, float)) and not isinstance(row[1], bool)]
            kwh[str(serial)] = round(sum(wh) / 1000.0, 2) if wh else None
    return kwh, falhas


def irradiancia(series):
    """Porte do `se_irradiance` do coletor: {date: IPOA kWh/m²} da série "Global Irradiance" do render-chart MONTH.
    IPOA = valor diário (W/m²) × 0,25 h / 1000 (a plataforma conferiu: a soma das 96 amostras de 15 min do DAY é o valor
    diário do MONTH). O dia é a data UTC do instante do ponto, como no coletor. Ponto sem número fica de fora."""
    out = {}
    for s in series or []:
        if "irradian" not in str((s or {}).get("name", "")).lower():
            continue
        for p in s.get("data") or []:
            if (isinstance(p, (list, tuple)) and len(p) >= 2 and isinstance(p[1], (int, float))
                    and not isinstance(p[1], bool)):
                try:
                    dia = dt.datetime.fromtimestamp(p[0] / 1000, tz=dt.timezone.utc).date()
                except (TypeError, ValueError, OverflowError, OSError):
                    continue
                out[dia] = round(p[1] * 0.25 / 1000.0, 2)
    return out


def _ipoa_do_site(ctx, site):
    """({date: IPOA}, motivo ou None) do site que TEM a estação. O render-chart vai com o 1º inversor, como no coletor:
    a irradiância é do site, o inversor só identifica a população do gráfico."""
    devs, motivo = _devs(ctx, site["id"])
    invs = [d for d in devs if d.get("deviceType") == "INVERTER"]
    if not invs:
        return {}, motivo or "a usina não tem inversor na lista de dispositivos"
    series = ctx.render_mes(int(site["id"]), [invs[0]["deviceSerial"]])
    if series is None:
        return {}, "a SolarEdge não respondeu o gráfico do mês (render-chart)"
    if not series:
        return {}, "o gráfico do mês veio vazio (limite de consultas da SolarEdge)"
    serie = irradiancia(series)
    if not serie:
        return {}, "sem a série Global Irradiance no gráfico do mês"
    return serie, None


def _lista(nomes, n=8):
    nomes = list(nomes)
    return ", ".join(nomes[:n]) + (" ..." if len(nomes) > n else "")


def buscar(ctx, ids, dias, geracao, etm, chuva):
    # Duas pessoas na Coletas ao mesmo tempo dobrariam o ritmo na conta do tempo real: a segunda espera (ver TETO).
    if not _UMA_POR_VEZ.acquire(blocking=False):
        raise comum.Recusa(429, "já há uma recoleta da SolarEdge em andamento (uma por vez, para não derrubar a tabela "
                                "do tempo real, que usa a mesma conta); tente em um minuto")
    try:
        return _buscar(ctx, ids, dias, geracao, etm, chuva)
    finally:
        _UMA_POR_VEZ.release()


def _buscar(ctx, ids, dias, geracao, etm, chuva):
    sites = _sites(ctx)
    por_id = {str(s["id"]): s for s in sites}
    por_nome = {comum.chave_nome(_usina_nome(s)): s for s in sites}
    ger, esc, avisos, sem_depara = [], [], [], []
    ipoa = {}                                # id do site com a estação -> ({date: IPOA}, motivo)
    if chuva:
        avisos.append("a SolarEdge não mede chuva nas usinas da RenoGrid: a coluna Chuva fica de fora")
    for sid in ids:
        site = por_id.get(str(sid))
        if site is None:
            avisos.append("site %s: a SolarEdge não o devolveu na lista de usinas" % sid)
            continue
        sup = site.get("nome") or str(sid)
        aba = ctx.mapa.usina_de(sup)
        if geracao:
            _geracao_do_site(ctx, site, sup, aba, dias, ger, avisos, sem_depara)
        if etm:
            _ipoa_do_pedido(ctx, site, sup, aba, dias, por_nome, ipoa, esc, avisos)
    if sem_depara:
        avisos.append("%d equipamento(s) da SolarEdge sem de-para na aba Equipamentos (a coleta também não os grava): %s"
                      % (len(sem_depara), _lista(sem_depara, 12)))
    return {"geracao": ger, "escalares": esc, "avisos": avisos}


def _geracao_do_site(ctx, site, sup, aba, dias, ger, avisos, sem_depara):
    devs, motivo = _devs(ctx, site["id"])
    invs = [d for d in devs if d.get("deviceType") == "INVERTER"]
    if not invs:
        avisos.append("%s: sem a lista de inversores da usina (%s); geração fora deste pedido"
                      % (aba or sup, motivo or "nenhum inversor na lista de dispositivos"))
        return
    alvo = {}                                # serial -> (aba, coluna), na ordem da SolarEdge
    for d in invs:
        serial = str(d.get("deviceSerial"))
        nome = d.get("deviceName") or serial
        t = ctx.mapa.inversor_de(sup, nome)
        if t is None:
            sem_depara.append("%s · %s" % (sup, nome))
        else:
            alvo[serial] = t
    if not alvo:
        return
    tz = site.get("timezone")
    if not _fuso(tz)[1]:
        avisos.append("%s: a SolarEdge não informou um fuso válido da usina (%r); o dia foi cortado no horário de "
                      "Brasília" % (aba or sup, tz))
    for dia in dias:
        kwh, falhas = energia_ac(ctx, site["id"], list(alvo), tz, dia)
        ausentes, nulos = [], []
        for serial, (u, inv) in alvo.items():
            v = kwh.get(serial)
            if serial not in kwh:
                ausentes.append(inv)
            elif v is None:
                nulos.append(inv)
            ger.append({"usina": u, "inversor": inv, "data": dia.isoformat(), "kwh": v})
        rot = "%s %s" % (aba or sup, dia.isoformat())
        if ausentes:
            avisos.append("%s: %d inversor(es) fora da resposta da SolarEdge (%s): ficaram nulos, não 0 — %s"
                          % (rot, len(ausentes), "; ".join(dict.fromkeys(falhas)) or "a fonte não os devolveu",
                             _lista(ausentes)))
        if nulos:
            avisos.append("%s: %d inversor(es) sem nenhuma leitura de energia no dia: ficaram nulos, não 0 — %s"
                          % (rot, len(nulos), _lista(nulos)))


def _ipoa_do_pedido(ctx, site, sup, aba, dias, por_nome, ipoa, esc, avisos):
    if not aba:
        avisos.append("%s: a usina não tem de-para na aba Equipamentos; IPOA fora deste pedido" % sup)
        return
    irma = _ESPELHO.get(comum.chave_nome(_usina_nome(site)))
    fonte = por_nome.get(comum.chave_nome(irma)) if irma else site
    if fonte is None:
        avisos.append("%s: o IPOA vem da %s (sem estação própria) e ela não veio na lista da SolarEdge" % (aba, irma))
        return
    k = str(fonte["id"])
    if k not in ipoa:
        ipoa[k] = _ipoa_do_site(ctx, fonte)
    serie, motivo = ipoa[k]
    faltam = []
    for dia in dias:
        if dia in serie:
            esc.append({"usina": aba, "data": dia.isoformat(), "coluna": COLUNA_IPOA, "valor": serie[dia]})
        else:
            faltam.append(dia.isoformat())
    if faltam:
        de = (" (da %s)" % irma) if irma else ""
        avisos.append("%s: IPOA sem valor%s em %s (%s)"
                      % (aba, de, _lista(faltam), motivo or "o dia não está na série do mês do render-chart"))
