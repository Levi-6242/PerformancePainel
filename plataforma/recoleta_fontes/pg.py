# -*- coding: utf-8 -*-
"""Recoleta pelo banco da Thopen (PostgreSQL, public.raw_*), no formato do contrato da Coletas (comum.py).

POR QUE AS RÉGUAS SÃO AS DO COLETOR, E NÃO OUTRAS
-------------------------------------------------
O coletor da noite (`coleta API PV/src/coletar_pg.py`) roda as 22 usinas que perderam a apipv em 27/08/2026 e teve as
duas réguas validadas valor a valor contra o BD_Thopen (31/08, 14/09 e 17/09/2026: o mesmo número em 650 de 695
dias-usina, e os 45 que mudaram eram todos de usina com defeito PROVADO na série crua). "Régua errada não dá erro,
deforma": por isso aqui não há régua nova, só o PORTE das de lá, com o mesmo nome e os mesmos casos nos comentários.

- ENERGIA = soma dos INCREMENTOS de `daily_active_energy` no dia local, com a base atravessando a meia-noite, o reset
  do contador entrando inteiro, o zero fantasma fora e o contador travado SEM resposta (`energia_por_dia` do coletor).
  O coletor faz a conta toda em SQL; aqui o SQL só tira a leitura repetida (o `dedup` de lá) e a conta, linha a linha
  a mesma do CASE de lá, roda em Python (`energia_da_serie`). Motivo: ela fica provável por teste sem banco — a bateria
  do coletor (tests/test_coletar_pg_energia.py) só roda com o PG de verdade, e esta pasta não conecta no banco em
  teste. A aritmética é em Decimal porque o `::numeric` do PG é exato e o float não: com float, a soma dos incrementos
  podia virar a casa do arredondamento em relação ao que a coleta da noite gravou.
- IPOA/GHI = integral trapezoidal de `irradiance_poa`/`irradiance_ghi` com o delta REAL entre leituras e buraco maior
  que MAX_GAP_MIN fora (`irradiacao_por_dia` do coletor, já em Python lá; veio igual).

O DE-PARA
---------
O coletor traduz pelo `load_name_mapping` (aba Equipamentos, "Usina Supervisório"/"Equipamento Supervisório"); aqui é o
`ctx.mapa` (comum.Mapa), que é o mesmo de-para com a mesma chave de nome. Por cima dele, como no coletor: a troca do
1.4 com o 1.5 da Ipixuna 1 (TROCA_DISPOSITIVO), o inversor do banco que não está no cadastro indo pela coluna com o
nome dele (avisado, não some) e o nome da aba do BD quando o cadastro escreve diferente (mapeamento.RENOMES).

Fuso: `raw_*` é timestamptz em UTC; o dia é o de Brasília, pelo carimbo de DENTRO do json com `AT TIME ZONE
'America/Sao_Paulo'` (plataforma/CLAUDE.md, "Fuso do banco": filtro sem isso já zerou resultado em silêncio).
"""
import re
import time
import types
from decimal import Decimal

from recoleta_fontes import comum

FONTE = "pg"
PAGA = False                  # o banco é nosso acesso direto: não há cota nem custo por consulta
TETO = None
MAX_PLANTAS = 8               # o mesmo tamanho de pedido da apipv; 8 usinas x 7 dias cabem num pedido de ~1 min

# coletar_pg.MAX_GAP_MIN: leitura mais espaçada que isto não é integrada, é buraco, não curva.
MAX_GAP_MIN = 30

# coletar_pg.USINAS_PG: as 22 usinas que perderam a apipv em 27/08/2026 e cujo dado vive no PG. Chave = nome exato de
# `public.tb_power_plants.name`, que é TAMBÉM o "Usina Supervisório" da aba Equipamentos. Mudou lá, muda aqui.
USINAS_PG = [
    "(289) Boa Esperança do Sul 1", "(290) Boa Esperança do Sul 2", "(292) Caxambu",
    "(295) Goytacazes 1", "(296) Ipixuna 2", "(298) Aparecida 3",
    "(299) Araçoiaba da Serra 1", "(300) Araçoiaba da Serra 2", "(305) Guaratinguetá V",
    "(306) Ibaté 1", "(307) Ibaté 2", "(308) Ipixuna 1", "(309) Piracicaba I",
    "(310) Salto Pirapora III", "(311) Santa Bárbara I", "(312) São Bento V",
    "(317) Santarém 1", "(318) Santarém 2", "(321) Marajoara I",
    "(323) Aparecida do Taboado 1", "(324) Aparecida do taboado 2", "(327) Santo Inácio XII",
]

# coletar_pg.ETM_ERRADA: estações cuja irradiação no PG está ERRADA — nulo é melhor que errado. Aparecida do Taboado 1
# e 2, 13/10/2026: o datalogger da estação (CSV do Levi, minuto a minuto) deu POA 7,4 a 9,1 kWh/m² de 24 a 30/09 e o PG
# gravava 0,5 a 1,1; a GHI também divergia (28/09: 3,03 x 6,91). Sai daqui quando sair de lá.
ETM_ERRADA = {"(323) Aparecida do Taboado 1", "(324) Aparecida do taboado 2"}

# coletar_pg.TROCA_DISPOSITIVO: dispositivos com o NOME TROCADO no supervisório da OEM (o PG repete o nome de lá; a aba
# Equipamentos é 1 para 1). Ipixuna 1, 11/11/2026 (Levi: "trocar o 1.5 pelo 1.4 e vice versa pois a coleta que está
# errada!"): o COS tinha o 1.4 parado (OS 16174 e 16726) e no BD quem zerava era a coluna 1.5. Sem a troca, a recoleta
# desfazia no BD a correção que o Levi fez à mão no histórico de 18/07 a 10/11.
TROCA_DISPOSITIVO = {"(308) Ipixuna 1": {"Inversor 1.4": "Inversor 1.5", "Inversor 1.5": "Inversor 1.4"}}

# mapeamento.RENOMES do coletor, só as linhas que caem nas 22 do PG: a aba Equipamentos traduz para "Piracicaba I" e
# "Marajoara I" (romano) e as abas do BD_Thopen são "Piracicaba 1" e "Marajoara 1" (arábico). Achado em 31/08/2026 ao
# ligar a coleta pelo PG: sem isto a rota aponta para aba inexistente e o dia inteiro das duas some. A Coletas procura a
# aba pelo nome EXATO, então aqui sai o nome da aba. Usina nova no USINAS_PG: confira a linha dela no RENOMES de lá.
_ABA_DO_BD = {"Piracicaba I": "Piracicaba 1", "Marajoara I": "Marajoara 1"}

# coletar_pg.FRACAO_RESET: queda para MENOS DA METADE do valor anterior = o contador zerou. Acima disso é oscilação, que
# NÃO pode virar reset: sem o piso, um vai-e-vem 100,2 -> 100,1 contava 100,1 kWh como trecho novo e dobrava o dia (o
# 1º rascunho da régua do coletor deu 14.048 kWh onde o certo eram 7.032). Decimal porque a conta de lá é numeric.
FRACAO_RESET = Decimal("0.5")

# coletar_pg.GAP_RESET_MIN: buraco maior que meia hora atravessando a virada = o valor que volta já é o acumulado do dia
# novo (o contador é DIÁRIO), não um delta. O mesmo número da irradiação, pela mesma razão.
GAP_RESET_MIN = MAX_GAP_MIN

# Teto por consulta, o mesmo do `_pa_ler_pg` do app: o banco é dividido com o pipeline da Thopen e já levou 83 s numa
# consulta com os dias comprimidos (24/09/2026). A recoleta pede dia passado, que é justamente o comprimido.
TETO_CONSULTA_MS = 45000
# Prazo do pedido inteiro: passou disso, as usinas que faltam ficam para o próximo pedido, AVISADAS. Sem ele, 8 usinas
# com o banco lento seguravam a requisição (e uma conexão do pool) por até 8 x 2 x 45 s.
PRAZO_PEDIDO_S = 150

# coletar_pg._NUM: cast defensivo. O json da estação usa "-" para leitura ausente, e um `::numeric` cru derruba a
# consulta inteira com "invalid input syntax for type numeric".
_NUM = ("CASE WHEN {j}->>'{c}' ~ '^-?[0-9]+(\\.[0-9]+)?$' "
        "THEN ({j}->>'{c}')::numeric END")


def _num(campo, j="json_data"):
    return _NUM.format(j=j, c=campo)


# As leituras de energia da usina, já sem o timestamp repetido: é o `l` + `dedup` do coletar_pg.energia_por_dia, igual
# (MAX de numeric ignora o nulo, e o HAVING tira o instante que só tinha nulo, como o WHERE kwh IS NOT NULL de lá).
# Bound pela coluna "timestamp" (índice do hypertable, poda chunks) com 1 dia de folga antes — a base da meia-noite é a
# ÚLTIMA leitura da véspera — e 2 depois — o zero fantasma da última leitura do dia é julgado pela SEGUINTE. O recorte do
# dia é pelo carimbo de dentro do json, convertido para Brasília.
_SQL_ENERGIA = """
    SELECT r.device_id, d.device_name,
           ((r.json_data->>'timestamp')::timestamptz AT TIME ZONE 'America/Sao_Paulo') AS ts_local,
           MAX({kwh}) AS kwh
      FROM public.raw_inverter r
      JOIN public.tb_devices d ON d.id = r.device_id
     WHERE r.power_plant_id = %(pid)s
       AND r."timestamp" >= %(ini)s::date - interval '1 day'
       AND r."timestamp" <  %(fim)s::date + interval '2 days'
     GROUP BY 1, 2, 3
    HAVING MAX({kwh}) IS NOT NULL
""".format(kwh=_num("daily_active_energy", "r.json_data"))

# coletar_pg.irradiacao_por_dia, a consulta igual.
_SQL_IRRADIACAO = """
    SELECT ((json_data->>'timestamp')::timestamptz
              AT TIME ZONE 'America/Sao_Paulo') AS ts_local,
           {poa} AS poa, {ghi} AS ghi
      FROM public.raw_weather_station
     WHERE power_plant_id = %(pid)s
       AND "timestamp" >= %(ini)s::date - interval '1 day'
       AND "timestamp" <  %(fim)s::date + interval '2 days'
     ORDER BY 1
""".format(poa=_num("irradiance_poa"), ghi=_num("irradiance_ghi"))

_SQL_CATALOGO = "SELECT name, id FROM public.tb_power_plants WHERE name = ANY(%s)"


def coluna_trocada(nome_pg, equip_bd):
    """coletar_pg.coluna_trocada: a coluna do BD depois da troca de nome do supervisório; sem troca, a mesma."""
    return TROCA_DISPOSITIVO.get(nome_pg, {}).get(equip_bd, equip_bd)


def aba_do_bd(usina):
    return _ABA_DO_BD.get(usina, usina)


class _MapaPelaAba:
    """O Mapa do comum com o `inv_por_usina` também pelo nome da ABA. A trava do dia zerado do comum (`dias_fora`) conta
    os inversores do cadastro pela usina das linhas, e aqui a linha sai com a aba ("Piracicaba 1") enquanto o cadastro
    diz "Piracicaba I": sem isto o total caía para o número de inversores que vieram e a trava nunca disparava nas
    duas. O resto (usina_de, inversor_de) é o Mapa, sem cópia."""

    def __init__(self, mapa):
        self._mapa = mapa
        por = {u: set(s) for u, s in (getattr(mapa, "inv_por_usina", None) or {}).items()}
        for u, s in list(por.items()):
            if aba_do_bd(u) != u:
                por.setdefault(aba_do_bd(u), set()).update(s)
        self.inv_por_usina = por

    def __getattr__(self, nome):
        if nome == "_mapa":                                  # ainda sem o __init__ (cópia): não entra em laço
            raise AttributeError(nome)
        return getattr(self._mapa, nome)


def contexto(app):
    """O de-para da aba Equipamentos (com o Nexus por cima) e o pool do PG do app. A conexão sai de `app._pg_conn()` e
    volta com `.close()`, que no pool DEVOLVE (rollback + putconn, `_PGConnEmprestada`) e fora dele fecha — o mesmo
    padrão dos outros pontos de uso do app."""
    return types.SimpleNamespace(mapa=_MapaPelaAba(app._recoleta_mapa()), conectar=app._pg_conn, catalogo=None)


def _conectar(ctx):
    try:
        return ctx.conectar()
    except Exception as e:                                   # noqa: BLE001 — banco fora é recusa, não 500
        raise comum.Recusa(502, "o banco da Thopen não respondeu (%s: %s)" % (type(e).__name__, str(e)[:160]))


def _teto(cur, ms=TETO_CONSULTA_MS):
    # SET LOCAL vale só até o fim da transação: o rollback do `.close()` do pool o desfaz, e a conexão volta limpa.
    cur.execute("SET LOCAL statement_timeout = %d" % int(ms))


def _catalogo(ctx):
    """{id do PG (texto): nome} das USINAS_PG, guardado no ctx (a rota chama plantas() e buscar() no mesmo pedido).
    coletar_pg._catalogo: usina que sumiu do tb_power_plants não entra, e isso sai no log do servidor em voz alta."""
    if ctx.catalogo is not None:
        return ctx.catalogo
    conn = _conectar(ctx)
    try:
        cur = conn.cursor()
        try:
            _teto(cur)
            cur.execute(_SQL_CATALOGO, (list(USINAS_PG),))
            achadas = {str(n): str(i) for n, i in cur.fetchall()}
        finally:
            cur.close()
    except comum.Recusa:
        raise
    except Exception as e:                                   # noqa: BLE001
        raise comum.Recusa(502, "o banco da Thopen não respondeu (%s: %s)" % (type(e).__name__, str(e)[:160]))
    finally:
        conn.close()
    faltam = [n for n in USINAS_PG if n not in achadas]
    if faltam:
        print("[recoleta/pg] usina(s) do USINAS_PG que NÃO existem em tb_power_plants, fora da lista: %s"
              % ", ".join(faltam))
    ctx.catalogo = {i: n for n, i in achadas.items()}
    return ctx.catalogo


def plantas(ctx):
    """As usinas do PG que têm de-para na aba Equipamentos, na ordem do USINAS_PG. Sem de-para não entra: a coleta da
    noite também não a grava (sem a usina do BD não há aba de destino)."""
    ordem = {n: k for k, n in enumerate(USINAS_PG)}
    out = []
    for pid, nome in sorted(_catalogo(ctx).items(), key=lambda kv: ordem.get(kv[1], 99)):
        u = ctx.mapa.usina_de(nome)
        if u:
            out.append({"id": pid, "usina": aba_do_bd(u), "destino": "BD_Thopen", "planta": nome})
    return out


def custo(ids, dias, geracao, etm, chuva):
    return 0                                                 # o banco não tem cota


def _dec(v):
    return v if isinstance(v, Decimal) else Decimal(str(v))


def energia_da_serie(leituras, ini, fim):
    """{dia: kWh} de UM dispositivo: a SOMA DOS INCREMENTOS de daily_active_energy no dia local.

    Porte, CASE a CASE, do SQL de coletar_pg.energia_por_dia (régua de 17/09/2026). `leituras` = [(ts local ingênuo,
    kWh)], em qualquer ordem e com repetição; vem com folga antes de `ini` (a base) e depois de `fim` (a seguinte).
    Os modos de falha, todos com caso real na série crua:
      a) o contador zera DEPOIS da meia-noite e a manhã carrega a véspera (Aparecida do Taboado 1 zera ~06:00: o
         MAX gravou 421,4 do dia 31/08 no lugar dos 67,1 de 01/09) -> a sobra plana não gera incremento;
      b) o contador NÃO zera na meia-noite (Santo Inácio XII zera às 13:00) -> conta só o que subiu no dia, e o reset
         no meio do dia soma os dois trechos;
      c) zero fantasma (Ipixuna 1, 0,0 às 22:15 de 01/09 entre dois 748,3) -> sai antes da conta, senão o dia dobrava;
      d) buraco atravessando a virada (Guaratinguetá V em 26/08, nada até 18:10 e 687,6 de volta) -> o valor que volta
         é o acumulado do dia; MENOS quando é o mesmo de antes do buraco (Ibaté 1 travado em 1107,66 de 31/08 até as
         11:00 de 01/09): contador congelado não gerou nada.
    E a trava do coletor: dia sem nenhum incremento só tem resposta se o contador ficou em 0 (a usina não gerou). Fora
    disso a telemetria congelou, e a única resposta honesta é NÃO RESPONDER — devolver 0 apagaria um dia bom (Marajoara
    I, 02/09: 72 leituras com 0 e 213,62 e nenhum incremento; 2,2 MWh por inversor que o BD já tinha)."""
    por_ts = {}
    for ts, kwh in leituras:                                 # dedup: timestamp repetido na origem (49 leituras/hora)
        if ts is None or kwh is None:
            continue
        v = _dec(kwh)
        if ts not in por_ts or v > por_ts[ts]:
            por_ts[ts] = v
    pts = sorted(por_ts.items())
    limpo = []
    for k, (ts, v) in enumerate(pts):
        # `limpo` do coletor: a leitura que despenca e VOLTA na seguinte é leitura ruim; os vizinhos são os do dedup.
        if 0 < k < len(pts) - 1:
            ant, prox = pts[k - 1][1], pts[k + 1][1]
            if v <= ant * FRACAO_RESET and prox > ant * FRACAO_RESET:
                continue
        limpo.append((ts, v))
    soma, maximo = {}, {}
    for k, (ts, v) in enumerate(limpo):
        if k == 0:
            inc = v                                          # 1ª leitura da série
        else:
            t0, ant = limpo[k - 1]
            gap_min = (ts - t0).total_seconds() / 60.0
            if t0.date() != ts.date() and gap_min > GAP_RESET_MIN:
                inc = Decimal(0) if v == ant else v          # volta de buraco na virada; igual = congelado
            elif v >= ant:
                inc = v - ant                                # subida normal
            elif v <= ant * FRACAO_RESET:
                inc = v                                      # reset: o trecho novo entra inteiro
            else:
                inc = Decimal(0)                             # oscilação: ignora
        dia = ts.date()
        if ini <= dia <= fim:
            soma[dia] = soma.get(dia, Decimal(0)) + inc
            maximo[dia] = max(maximo.get(dia, v), v)
    # HAVING do coletor: SUM > 0 OR MAX(kwh) = 0
    return {d: float(s) for d, s in soma.items() if s > 0 or maximo[d] == 0}


def energia_por_dia(cur, pid, ini, fim):
    """{(dia, device_id, device_name): kWh} da usina. Por device_id, como a PARTITION BY do coletor; o nome vai junto
    para o de-para (nunca deduza pela ordem dos device_id: o coletar_semp conta que isso trocaria 6 dos 8 inversores da
    Morada Nova sem sintoma nenhum)."""
    cur.execute(_SQL_ENERGIA, {"pid": int(pid), "ini": ini.isoformat(), "fim": fim.isoformat()})
    series, nomes = {}, {}
    for dev_id, dev_nome, ts, kwh in cur.fetchall():
        series.setdefault(dev_id, []).append((ts, kwh))
        nomes[dev_id] = str(dev_nome or "").strip()
    out = {}
    for dev_id, serie in series.items():
        for dia, kwh in energia_da_serie(serie, ini, fim).items():
            out[(dia, dev_id, nomes[dev_id])] = kwh
    return out


def irradiacao_da_serie(linhas, ini, fim):
    """{dia: (poa kWh/m², ghi kWh/m²)} por trapézio — coletar_pg.irradiacao_por_dia, a conta igual. Os acumuladores
    irradiation_* do json vieram SEMPRE nulos; intervalo fixo de 5 min errava quando a estação falhava leitura (20/08:
    8,07 contra 7,27 do BD); buraco maior que MAX_GAP_MIN não é interpolado (atravessar uma queda de 3 h inventaria
    irradiância que ninguém mediu). Integral 0 sai nula, como lá."""
    por_dia = {}
    for ts, poa, ghi in sorted(linhas, key=lambda x: x[0]):
        por_dia.setdefault(ts.date(), []).append((ts, poa, ghi))
    fora = {}
    for dia, serie in por_dia.items():
        if not (ini <= dia <= fim):
            continue
        acc = {"poa": 0.0, "ghi": 0.0}
        for k in range(1, len(serie)):
            t0, p0, g0 = serie[k - 1]
            t1, p1, g1 = serie[k]
            dt_h = (t1 - t0).total_seconds() / 3600.0
            if dt_h <= 0 or dt_h > MAX_GAP_MIN / 60.0:
                continue                                     # buraco: não inventa curva por cima
            for chave, a, b in (("poa", p0, p1), ("ghi", g0, g1)):
                if a is None or b is None:
                    continue
                acc[chave] += (float(a) + float(b)) / 2.0 * dt_h / 1000.0
        fora[dia] = (round(acc["poa"], 3) or None, round(acc["ghi"], 3) or None)
    return fora


def irradiacao_por_dia(cur, pid, ini, fim):
    cur.execute(_SQL_IRRADIACAO, {"pid": int(pid), "ini": ini.isoformat(), "fim": fim.isoformat()})
    return irradiacao_da_serie(cur.fetchall(), ini, fim)


def _lista(itens, n=12):
    itens = sorted(itens)
    return ", ".join(itens[:n]) + (" ..." if len(itens) > n else "")


def buscar(ctx, ids, dias, geracao, etm, chuva):
    """Geração por inversor e IPOA/GHI das usinas pedidas. `chuva` não se aplica: o banco da Thopen não tem
    pluviômetro na coleta."""
    ini, fim = min(dias), max(dias)
    dias_ok = {d.isoformat() for d in dias}
    cat = _catalogo(ctx)
    avisos, escalares = [], []
    cand = {}                       # (aba, coluna, dia) -> [(0 cadastro | 1 nome do banco, kWh, "planta · equipamento")]
    sem_depara, conflito, fora_do_prazo = set(), set(), []
    lidas = []                      # plantas cuja geração o banco respondeu: os inversores delas sem leitura saem nulos
    t0 = time.monotonic()
    conn = _conectar(ctx)
    try:
        cur = conn.cursor()
        try:
            for pid in ids:
                nome = cat.get(str(pid))
                if not nome:
                    avisos.append("planta %s não é do banco da Thopen (fora do USINAS_PG ou do tb_power_plants)" % pid)
                    continue
                if time.monotonic() - t0 > PRAZO_PEDIDO_S:
                    fora_do_prazo.append(nome)
                    continue
                usina = ctx.mapa.usina_de(nome)
                if not usina:
                    avisos.append("%s: sem de-para na aba Equipamentos; nada dela vai para o BD" % nome)
                    continue
                try:
                    _teto(cur)
                    if geracao:
                        for (dia, _dev_id, dev), kwh in sorted(energia_por_dia(cur, pid, ini, fim).items(),
                                                               key=lambda kv: (kv[0][0], kv[0][2], str(kv[0][1]))):
                            alvo = ctx.mapa.inversor_de(nome, dev)
                            prio = 0
                            if not alvo:
                                # coletar_pg.coletar: o inversor que existe no banco e na planilha mas não no cadastro
                                # vai pela coluna com o nome do banco, avisado. Caso real: Ipixuna 2 / Inversor 2.13
                                # (31/08/2026) — sem isto a geração dele sumia, o erro que a coleta do PG veio corrigir.
                                # A caixa é a da coluna do BD (Ibaté 1 traz "inversor 10" minúsculo no tb_devices).
                                sem_depara.add("%s · %s" % (nome, dev))
                                alvo = (usina, re.sub(r"^inversor", "Inversor", dev, flags=re.I))
                                prio = 1
                            u_bd, col = alvo
                            col = coluna_trocada(nome, col)
                            cand.setdefault((aba_do_bd(u_bd), col, dia.isoformat()), []).append(
                                (prio, kwh, "%s · %s" % (nome, dev)))
                        lidas.append(nome)
                    if etm and nome in ETM_ERRADA:
                        avisos.append("%s: a irradiação da estação no banco está errada (desde 24/09/2026, conferida "
                                      "contra o datalogger em 13/10); IPOA e GHI não vão, como na coleta da noite" % nome)
                    elif etm:
                        aba = aba_do_bd(usina)
                        for dia, (poa, ghi) in sorted(irradiacao_por_dia(cur, pid, ini, fim).items()):
                            for coluna, valor in (("IPOA", poa), ("GHI", ghi)):
                                if valor is not None and dia.isoformat() in dias_ok:     # nulo é nulo, não vira linha
                                    escalares.append({"usina": aba, "data": dia.isoformat(), "coluna": coluna,
                                                      "valor": valor})
                except Exception as e:                       # noqa: BLE001 — uma usina que falha não derruba o pedido
                    avisos.append("%s: o banco não respondeu (%s: %s); peça de novo esta usina"
                                  % (nome, type(e).__name__, str(e)[:160]))
                finally:
                    # fecha a transação a cada usina: solta o snapshot e, depois de erro, destrava a conexão
                    # ("current transaction is aborted") para a usina seguinte
                    try:
                        conn.rollback()
                    except Exception:                        # noqa: BLE001
                        pass
        finally:
            cur.close()
    finally:
        conn.close()

    geracao_out = []
    for (aba, col, dia), lst in sorted(cand.items()):
        if dia not in dias_ok:
            continue
        lst.sort(key=lambda x: x[0])
        melhores = [x for x in lst if x[0] == lst[0][0]]
        if len(melhores) > 1:
            # dois dispositivos no mesmo destino (nome repetido no tb_devices, ou cadastro apontando dois para a mesma
            # coluna): não se adivinha qual vale nem se soma — fica de fora, avisado
            conflito.add("%s · %s em %s (%s)" % (aba, col, dia, " e ".join(x[2] for x in melhores)))
            continue
        geracao_out.append({"usina": aba, "inversor": col, "data": dia, "kwh": round(melhores[0][1], 2)})
        for x in lst[1:]:
            conflito.add("%s · %s em %s: ficou o do cadastro, %s fora" % (aba, col, dia, x[2]))
    # O inversor do cadastro que o banco não trouxe no dia sai NULO (nunca 0): é assim que a régua do dia fora do
    # comum (as linhas que a fonte devolveu, a trava do coletor) enxerga a usina que só mandou 1 de 3 inversores.
    tem = {(r["usina"], r["inversor"], r["data"]) for r in geracao_out}
    from recoleta_fontes.comum import chave_nome
    for nome in dict.fromkeys(lidas):
        cp = chave_nome(nome)
        for (k_pl, _k_eq), (u_bd, col) in getattr(ctx.mapa, "inv", {}).items():
            if k_pl != cp:
                continue
            aba, col = aba_do_bd(u_bd), coluna_trocada(nome, col)
            for d in sorted(dias_ok):
                if (aba, col, d) not in tem:
                    tem.add((aba, col, d))
                    geracao_out.append({"usina": aba, "inversor": col, "data": d, "kwh": None})
    if sem_depara:
        avisos.append("%d equipamento(s) do banco sem de-para na aba Equipamentos, mandados pela coluna com o nome do "
                      "banco (como na coleta da noite; confira o cadastro): %s" % (len(sem_depara), _lista(sem_depara)))
    if conflito:
        avisos.append("%d valor(es) com dois dispositivos no mesmo destino, fora da planilha: %s"
                      % (len(conflito), _lista(conflito, 8)))
    if fora_do_prazo:
        avisos.append("o banco está lento: passou de %d s e %d usina(s) ficaram para o próximo pedido: %s"
                      % (PRAZO_PEDIDO_S, len(fora_do_prazo), ", ".join(fora_do_prazo)))
    return {"geracao": geracao_out, "escalares": escalares, "avisos": avisos}
