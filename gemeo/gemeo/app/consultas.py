# gemeo/gemeo/app/consultas.py
"""Todo o SQL das telas, em funcoes banco -> dict (JSON-serializavel). O app so renderiza. 'Agora' e parametro (nunca
now()) para as telas serem testaveis sobre um dia congelado — e para 'viajar no tempo' ao depurar:
`/gemeo/?agora=2026-08-31T20:00:00Z`.

Banco e SQLite (03/09/2026): o que o PostgreSQL fazia com date_bin, percentile_cont e AT TIME ZONE aqui e feito em
pandas sobre o DIA (96 slots por inversor cabem na memoria de sobra). Consultas de 'ultimo ts' andam o indice de ts
de tras para frente com LIMIT 1 — max() sobre um join varreria a tabela grande."""
from __future__ import annotations
import base64
import datetime as dt
import json
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from gemeo.core import db, tempo

# Janela de dia da Frota: a mesma 05h-19h da curva do dia. Serve para decidir se existe um "agora" para comparar, e
# olha o RELOGIO, nao o sensor: a POA da Ibate 2 fica congelada em 302 W/m2 a noite inteira, o modelo obedece e
# calculava 1,1 MW esperados as 23h30. Sol abaixo do horizonte nao tem instante a comparar, sensor dizendo o que for.
JANELA_DIA = ("05:00", "19:00")

FRIO_MIN = 30          # frescor: acima disto a usina fica cinza antes de qualquer outra cor (spec §9)
DEFICIT_GRAVE = 0.08   # faixa 'deficit grave' da regua
H = 0.25
NOMES_PARCELA = {"inv_parado": "inversor parado", "tracker": "trackers fora do alvo",
                 "string": "strings sem corrente", "clipping": "clipping (inversor no teto)",
                 "residuo": "resíduo (não explicado)"}


def faixa(delta: float | None, tolerancia: float) -> str:
    """dentro | moderado | grave | sem_dado. delta = (medido - esperado)/esperado; negativo = deficit."""
    if delta is None:
        return "sem_dado"
    if delta >= -tolerancia:
        return "dentro"
    return "moderado" if delta >= -DEFICIT_GRAVE else "grave"


def causa_dominante(c: dict | None) -> str:
    if not c:
        return "sem cascata hoje"
    k = max(NOMES_PARCELA, key=lambda n: c.get(n) or 0.0)
    return NOMES_PARCELA[k] if (c.get(k) or 0.0) > 0 else "dentro da tolerância do modelo"


def motivo_nao_modelada(u: dict, agora: dt.datetime) -> str | None:
    """Por que a usina do cadastro nao esta na regua — None quando esta. E a definicao de 'aparece na
    tela' da spec §6: ativa, com equipamento, ingest ok em 24 h, gate de hoje nao reprovado, esperado."""
    if not u.get("n_equip"):
        return "sem equipamentos no cadastro"
    if u.get("ultimo_ingest_ok") is None or agora - u["ultimo_ingest_ok"] > dt.timedelta(hours=24):
        return "sem ingestão nas últimas 24 h"           # ok OU parcial: dado chegou; cobertura baixa e assunto do /healthz
    if u.get("gate_hoje") in ("poa_ghi", "plausibilidade"):
        return "sensor em falha hoje (POA × GHI)"
    if u.get("gate_hoje") == "cobertura":
        return "sem cobertura de sensor hoje"
    if u.get("esperado_kw") is None:
        return "sem esperado calculado hoje"
    return None


def exp_do_jwt(token: str) -> dt.datetime | None:
    """`exp` do token de API da SunOp (validade ~1 ano): o /healthz alarma 30 dias antes."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload))["exp"]
        return dt.datetime.fromtimestamp(int(exp), dt.timezone.utc)
    except Exception:                       # noqa: BLE001 — token que nao e JWT nao tem validade legivel
        return None


def _dia_utc(dia: dt.date, tz: ZoneInfo) -> tuple[dt.datetime, dt.datetime]:
    ini = dt.datetime.combine(dia, dt.time.min, tzinfo=tz)
    return ini.astimezone(dt.timezone.utc), (ini + dt.timedelta(days=1)).astimezone(dt.timezone.utc)


def _q(conn, sql: str, params: tuple = ()) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _min(agora: dt.datetime, ts: dt.datetime | None) -> int | None:
    return None if ts is None else int((agora - ts).total_seconds() // 60)


def _estado_json(conn, chave: str) -> dict:
    r = _q(conn, "SELECT valor FROM estado WHERE chave=%s", (chave,))
    try:
        return json.loads(r[0][0]) if r else {}
    except Exception:                       # noqa: BLE001
        return {}


def _ciclo(conn) -> dict:
    return _estado_json(conn, "modelar.ultimo")


# A ultima leitura da usina fixando as TRES colunas da PK (equipamento_id, medida, ts). Medido em
# 17/09/2026 contando passos da VM do SQLite (tempo engana: o cache do sistema operacional entrega
# 2 s numa hora e 55 s noutra, com o mesmo codigo):
#
#   ORDER BY l.ts DESC LIMIT 1 sobre `equipamento_id IN (...)`   122.828.000 passos nas 25 usinas
#   max(ts) fixando so o equipamento                              87.583.000  (so 1,4x melhor)
#   max(ts) fixando equipamento E medida                           2.269.000  (54x melhor)
#
# O meio-termo quase me enganou: sem a medida, `max(ts)` ainda varre TODAS as medidas daquele
# equipamento, porque `medida` esta no meio da chave. Com as tres fixas, cada uma vira um seek.
# Conferido valor a valor nas 25 usinas do banco de producao: zero divergencia, inclusive nas que
# estao dois dias sem dado. Era esta consulta, rodada por usina na Frota, que fazia a aba estourar o
# timeout=30 do proxy e virar "Gêmeo Digital fora do ar".
_MEDIDAS_SQL = " UNION ALL ".join(
    ("SELECT '%s' AS v" if i == 0 else "SELECT '%s'") % m for i, m in enumerate(db.MEDIDAS))
SQL_ULTIMA_LEITURA = ('SELECT max(ts) AS "ts [TIMESTAMP]" FROM (SELECT '
                      "(SELECT max(l.ts) FROM leitura l WHERE l.equipamento_id=e.id AND l.medida=m.v) AS ts "
                      f"FROM equipamento e CROSS JOIN ({_MEDIDAS_SQL}) m "
                      "WHERE e.usina_id=%s)")


def _ultima_leitura(conn, usina_id: int) -> dt.datetime | None:
    r = _q(conn, SQL_ULTIMA_LEITURA, (usina_id,))
    return r[0][0] if r and r[0][0] else None


def _usinas(conn, usina_id: int | None = None) -> list[dict]:
    filtro = "AND u.id=%s" if usina_id else ""
    rows = _q(conn, f"""
        SELECT u.id, u.codigo, u.nome, u.fonte, u.fonte_ref, u.tz, coalesce(u.kwp_dc,0), coalesce(u.kw_ac,0), u.cliente,
               u.lat, u.lon,
               (SELECT count(*) FROM equipamento e WHERE e.usina_id=u.id AND e.ativo),
               (SELECT max(r.criado_em) FROM ingest_run r WHERE r.usina_id=u.id AND r.status IN ('ok','parcial')) AS "ultimo_ingest_ok [TIMESTAMP]",
               m.id, m.versao, coalesce(m.tolerancia, 0.08), coalesce(m.calibrado, 0)
        FROM usina u LEFT JOIN modelo m ON m.usina_id=u.id AND m.ativo
        WHERE u.ativo {filtro} ORDER BY u.codigo""", (usina_id,) if usina_id else ())
    # lat/lon entram aqui porque o bloco de clima do dia (ceu claro) depende deles; sem isso o
    # `clima_do_dia` devolvia None e a tela escondia o bloco sem dizer por que (17/09/2026)
    chaves = ("id", "codigo", "nome", "fonte", "fonte_ref", "tz", "kwp", "kw_ac", "cliente", "lat", "lon", "n_equip", "ultimo_ingest_ok",
              "modelo_id", "modelo_versao", "tolerancia", "calibrado")
    out = []
    for r in rows:
        u = dict(zip(chaves, r))
        u["calibrado"] = bool(u["calibrado"])
        u["ultima_leitura"] = _ultima_leitura(conn, u["id"])
        out.append(u)
    return out


def _ultimo_slot(conn, usina_id: int, modelo_id: int | None, agora: dt.datetime) -> dt.datetime | None:
    if modelo_id is None:
        return None
    r = _q(conn, 'SELECT x.ts AS "ts [TIMESTAMP]" FROM esperado x WHERE x.equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s) '
                 "AND x.modelo_id=%s AND x.p_esperado_kw IS NOT NULL AND x.ts <= %s ORDER BY x.ts DESC LIMIT 1", (usina_id, modelo_id, agora))
    return r[0][0] if r else None


def _agora_da_usina(conn, usina_id: int, modelo_id: int, slot: dt.datetime) -> tuple[float | None, float | None, str | None]:
    esp = _q(conn, "SELECT sum(x.p_esperado_kw), min(x.gate) FROM esperado x WHERE x.ts=%s AND x.modelo_id=%s "
                   "AND x.equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s)", (slot, modelo_id, usina_id))
    med = _q(conn, "SELECT sum(v) FROM (SELECT avg(l.valor) v FROM leitura l WHERE l.medida='p_ac' AND l.ts >= %s AND l.ts < %s "
                   "AND l.equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor') GROUP BY l.equipamento_id) s",
             (slot, slot + dt.timedelta(minutes=15), usina_id))
    e = float(esp[0][0]) if esp and esp[0][0] is not None else None
    m = float(med[0][0]) if med and med[0][0] is not None else None
    return e, m, (esp[0][1] if esp else None)


def _cascata(conn, usina_id: int, modelo_id: int | None, dia: dt.date) -> dict | None:
    if modelo_id is None:
        return None
    r = _q(conn, "SELECT e_esperado, e_medido, delta, inv_parado, tracker, string, clipping, residuo, cobertura_gate, trackers_sem_inversor "
                 "FROM cascata_dia WHERE usina_id=%s AND modelo_id=%s AND dia=%s", (usina_id, modelo_id, dia))
    if not r:
        return None
    ch = ("e_esperado", "e_medido", "delta", "inv_parado", "tracker", "string", "clipping", "residuo", "cobertura_gate", "trackers_sem_inversor")
    return {k: (float(v) if k != "trackers_sem_inversor" else int(v)) for k, v in zip(ch, r[0])}


def clima_do_dia(conn, usina_id: int, ini, fim, lat, lon, tz: str) -> dict:
    """Contexto meteorologico do dia: `variabilidade` e `ghi_x_clarosky` (17/09/2026).

    **Variabilidade** = comprimento do caminho da curva medida dividido pelo da curva de ceu claro
    (indice de variabilidade). Perto de 1 = ceu limpo; bem acima = dia instavel. E o que separa
    "deficit porque nublou" de "deficit sem desculpa" — ate aqui essa resposta saia do olho de quem
    analisa.

    **ghi_x_clarosky** = mediana do GHI medido sobre o GHI de ceu claro, so com sol alto. A regua de
    ETM da plataforma so alarma com POA/GHI em ZERO: um piranometro SUJO lendo 700 onde caberia
    1.050 e invisivel. Abaixo de ~0,85 em dia limpo (variabilidade baixa) e sujeira ou desalinho.

    Sem lat/lon nao ha ceu claro — devolve None em vez de inventar. (117 das 157 usinas tem
    coordenada na Info Geral; as outras ficam sem este bloco.)"""
    vazio = {"variabilidade": None, "ghi_x_clarosky": None}
    if lat is None or lon is None:
        return vazio
    rows = _q(conn, 'SELECT l.ts AS "ts [TIMESTAMP]", l.valor FROM leitura l WHERE l.medida=%s AND l.ts >= %s AND l.ts < %s '
                    "AND l.equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s AND tipo='estacao') ORDER BY l.ts",
              ("ghi", ini, fim, usina_id))
    if len(rows) < 12:
        return vazio
    try:
        import numpy as _np
        import pandas as _pd
        import pvlib as _pvlib
        s = _pd.Series([float(v) for _, v in rows], index=_pd.DatetimeIndex([r[0] for r in rows]))
        if s.index.tz is None:
            s.index = s.index.tz_localize("UTC")
        cs = _pvlib.location.Location(float(lat), float(lon), tz="UTC").get_clearsky(s.index)["ghi"]
        alto = cs > 200.0                      # so com sol alto: de madrugada a razao explode
        if int(alto.sum()) < 8:
            return vazio
        razao = float(_np.median((s[alto] / cs[alto]).replace([_np.inf, -_np.inf], _np.nan).dropna()))
        dt_min = float(_np.median(_np.diff(s.index.values).astype("timedelta64[m]").astype(float))) or 1.0
        def _caminho(v):
            d = _np.diff(_np.asarray(v, dtype=float))
            return float(_np.nansum(_np.sqrt(d ** 2 + dt_min ** 2)))
        base = _caminho(cs[alto])
        vi = (_caminho(s[alto]) / base) if base > 0 else None
        return {"variabilidade": (round(vi, 2) if vi is not None else None), "ghi_x_clarosky": round(razao, 3)}
    except Exception:
        return vazio


# Limites do indice de variabilidade, medidos em 18 dias-usina das tres da 2C (17/09/2026): dia limpo
# fica em 1,0 a 1,1 (Araputanga 15 e 16/09, curva de GHI lisa), e o dia de nuvem quebrada da Sete
# Lagoas deu 92,7 — GHI oscilando 1225 -> 372 -> 1202 em minutos, com picos de 1238 W/m2 acima do ceu
# claro (realce de borda de nuvem). O numero cru nao diz nada a quem opera; a palavra diz.
CEU_LIMPO = 2.0
CEU_PARCIAL = 8.0

# Rendimento implicito a partir do qual a irradiancia lida esta abaixo da real. A usina nao produz mais
# do que o sol entrega: medido / (kWp x POA/1000) e a assinatura dela e ficou em 0,76 a 0,81 na
# Araputanga em 4 dias e 0,79 na Tupi num dia limpo (p10-p90 de 0,79 a 0,81). Mediana acima de 1,0 nao
# tem explicacao fisica do lado da usina — sobra o sensor.
RENDIMENTO_IMPOSSIVEL = 1.0


def ceu_do_indice(vi: float | None) -> str | None:
    """Traduz o indice de variabilidade em palavra: limpo, parcial, instavel."""
    if vi is None:
        return None
    return "limpo" if vi <= CEU_LIMPO else ("parcial" if vi <= CEU_PARCIAL else "instável")


def rendimento_do_dia(conn, usina_id: int, ini, fim, kwp: float | None) -> dict:
    """Rendimento implicito do dia: mediana de `medido / (kWp x POA/1000)` com sol alto (17/09/2026).

    Existe porque a regua anterior errava. "GHI abaixo de 85% do ceu claro = piranometro sujo" parece
    certo e NAO e: medi 6 dias das tres usinas 2C e um dia encoberto de verdade da o mesmo numero —
    a Tupi leu 9% do ceu claro o dia inteiro em 14/09 com cobertura cheia, e era nuvem. A
    variabilidade tambem nao separa, porque estrato liso tem VI baixo igual a dia limpo.

    Este criterio a fisica sustenta: a usina nao produz mais do que o sol entrega. Se a mediana passa
    de 1,0, a irradiancia lida esta ABAIXO da real — e ai o problema nao e uma perda, e o `esperado`
    inteiro do gemeo, que nasce da POA medida.

    Usa a MEDIANA de proposito: em dia de nuvem quebrada os instantes soltos estouram (a Sete Lagoas
    chegou a 1,95 num ponto) porque o piranometro e um ponto e a usina e um campo — a mediana
    atravessa isso (ficou em 0,71 a 0,85 nos mesmos dias)."""
    vazio = {"rendimento": None, "sensor_baixo": False}
    if not kwp:
        return vazio
    rows = _q(conn, """SELECT s.poa, t.pac FROM
          (SELECT ts, avg(valor) AS poa FROM leitura WHERE medida='poa' AND ts >= %s AND ts < %s
             AND equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s AND tipo='estacao') GROUP BY ts) s
        JOIN (SELECT ts, sum(valor) AS pac FROM leitura WHERE medida='p_ac' AND ts >= %s AND ts < %s
             AND equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor') GROUP BY ts) t
          ON t.ts = s.ts WHERE s.poa > 300""", (ini, fim, usina_id, ini, fim, usina_id))
    if len(rows) < 20:                       # poucos pares: dia curto ou fonte falhando, nao se opina
        return vazio
    v = [float(pac) / (float(kwp) * float(poa) / 1000.0) for poa, pac in rows if poa and float(poa) > 0]
    if len(v) < 20:
        return vazio
    r = float(np.median(v))
    return {"rendimento": round(r, 2), "sensor_baixo": r > RENDIMENTO_IMPOSSIVEL}


def _gate_hoje(conn, usina_id: int, ini: dt.datetime, fim: dt.datetime) -> str:
    r = _q(conn, "SELECT tipo FROM evento WHERE usina_id=%s AND tipo IN ('sensor_em_falha','sem_cobertura') AND ini >= %s AND ini < %s LIMIT 1",
           (usina_id, ini, fim))
    return {"sensor_em_falha": "poa_ghi", "sem_cobertura": "cobertura"}.get(r[0][0], "ok") if r else "ok"


def _preco(conn, usina_id: int, dia: dt.date) -> float | None:
    r = _q(conn, "SELECT preco_mwh FROM meta_mes WHERE usina_id=%s AND ano=%s AND mes=%s", (usina_id, dia.year, dia.month))
    return float(r[0][0]) if r and r[0][0] is not None else None


def frota(conn, agora: dt.datetime) -> dict:
    usinas = []
    for u in _usinas(conn):
        tz = ZoneInfo(u["tz"]); hoje = agora.astimezone(tz).date(); ini, fim = _dia_utc(hoje, tz)
        slot = _ultimo_slot(conn, u["id"], u["modelo_id"], agora)
        esp_kw = med_kw = gate_agora = None
        if slot:
            esp_kw, med_kw, gate_agora = _agora_da_usina(conn, u["id"], u["modelo_id"], slot)
        casc = _cascata(conn, u["id"], u["modelo_id"], hoje)
        preco = _preco(conn, u["id"], hoje)
        delta = (med_kw - esp_kw) / esp_kw if esp_kw and med_kw is not None else None
        perda_kwh = max(0.0, casc["delta"]) if casc else 0.0
        u.update({
            "hoje": str(hoje), "slot": slot, "esperado_kw": esp_kw, "medido_kw": med_kw, "delta": delta, "gate_agora": gate_agora,
            "gate_hoje": _gate_hoje(conn, u["id"], ini, fim), "cascata": casc, "preco_mwh": preco, "perda_kwh": perda_kwh,
            "perda_brl": (perda_kwh / 1000.0 * preco) if preco else None, "causa": causa_dominante(casc),
            "faixa": faixa(delta, float(u["tolerancia"])), "idade_leitura_min": _min(agora, u["ultima_leitura"]),
            "idade_esperado_min": _min(agora, slot)})
        u["frio"] = u["idade_leitura_min"] is None or u["idade_leitura_min"] > FRIO_MIN
        u["motivo"] = motivo_nao_modelada(u, agora)
        usinas.append(u)
    # Sem sol em nenhuma usina — de noite, ou num dia escolhido que ja fechou — o instante nao diz nada: o esperado
    # das 23h e ~0 e a razao medido/esperado explode (a Frota abriu com "-66,4% agora" em 04/09). A tela inteira
    # passa entao a falar do DIA: energia esperada x medida da cascata, que e o que se quer saber de um dia fechado.
    # A troca e da frota toda, e nao usina a usina, para as colunas nao misturarem MW com MWh na mesma tabela.
    # "agora" exige um instante que exista de verdade: com sol (acima do piso) E recente. Sem a segunda parte, o
    # ultimo slot COM esperado pode ser o do por do sol — a Frota de 04/09 as 23:55 comparava contra as 17h da Ibate 2
    # e mostrava "1,1 MW esperados" no meio da madrugada.
    def _instante_vale(u: dict) -> bool:
        piso = max(20.0, 0.02 * float(u["kw_ac"] or 0.0))
        idade = u["idade_esperado_min"]
        return (tempo.dentro_janela_solar(agora, u["tz"], JANELA_DIA)
                and (u["esperado_kw"] or 0.0) >= piso and idade is not None and idade <= FRIO_MIN)

    base = "agora" if any(_instante_vale(u) for u in usinas) else "dia"
    dia_ref = None
    if base == "dia":
        # Qual dia a tela mostra e decidido POR USINA e pelo relogio dela: antes das 5h o dia local mal comecou e nao
        # tem cascata, entao a referencia e o dia que fechou; das 19h em diante e o proprio dia. Nao se cai para ontem
        # por "falta de cascata" — isso esconderia uma usina que falhou o dia inteiro atras dos numeros bons da vespera.
        # E por usina porque a frota mistura UTC-3 e UTC-4: a meia-noite de Sao Paulo ainda e 23h em Campo Grande.
        datas = []
        for u in usinas:
            tz_u = ZoneInfo(u["tz"]); local = agora.astimezone(tz_u); d_local = local.date()
            if local.hour < 5:
                d_local = d_local - dt.timedelta(days=1)
                i2, f2 = _dia_utc(d_local, tz_u)
                u["cascata"] = _cascata(conn, u["id"], u["modelo_id"], d_local)
                u["gate_hoje"] = _gate_hoje(conn, u["id"], i2, f2)      # a regua de exclusao olha o MESMO dia
                u["causa"] = causa_dominante(u["cascata"])
                u["perda_kwh"] = max(0.0, u["cascata"]["delta"]) if u["cascata"] else 0.0
                u["perda_brl"] = (u["perda_kwh"] / 1000.0 * u["preco_mwh"]) if u["preco_mwh"] else None
            u["dia_ref"] = d_local.isoformat(); datas.append(d_local)
            c = u["cascata"]
            d = ((c["e_medido"] - c["e_esperado"]) / c["e_esperado"]) if (c and c["e_esperado"]) else None
            u.update({"esperado_kw": (c["e_esperado"] if c else None), "medido_kw": (c["e_medido"] if c else None),
                      "delta": d, "faixa": faixa(d, float(u["tolerancia"])), "frio": c is None})
            u["motivo"] = motivo_nao_modelada(u, agora)                 # com o gate e o esperado do dia que a tela mostra
        dia_ref = max(set(datas), key=datas.count) if datas else None   # rotulo da frota: o dia da maioria
    modeladas = sorted([u for u in usinas if u["motivo"] is None], key=lambda u: -(u["perda_brl"] or u["perda_kwh"]))
    nao = [{"id": u["id"], "codigo": u["codigo"], "fonte": u["fonte"], "motivo": u["motivo"]} for u in usinas if u["motivo"]]
    tot_esp = sum(u["esperado_kw"] for u in modeladas if u["esperado_kw"] is not None)
    tot_med = sum(u["medido_kw"] for u in modeladas if u["medido_kw"] is not None)
    com_preco = [u["perda_brl"] for u in modeladas if u["perda_brl"] is not None]
    # de dia, sensor ok no instante; de noite, o gate do dia — senao a confianca cairia a zero toda madrugada
    if base == "agora":
        bons = sum(1 for u in usinas if u["gate_agora"] == "ok" and not u["frio"])
    else:
        bons = sum(1 for u in usinas if u["gate_hoje"] == "ok")
    confianca = (bons / len(usinas)) if usinas else 0.0
    faixas = {k: sum(1 for u in modeladas if u["faixa"] == k) for k in ("dentro", "moderado", "grave", "sem_dado")}
    tol = min([float(u["tolerancia"]) for u in modeladas], default=0.08)
    return {
        "agora": agora.isoformat(), "ciclo": _ciclo(conn), "base": base, "dia_ref": (dia_ref.isoformat() if dia_ref else None),
        "usinas": modeladas, "nao_modeladas": nao,
        "totais": {"esperado_kw": tot_esp, "medido_kw": tot_med, "delta": ((tot_med - tot_esp) / tot_esp) if tot_esp else None,
                   "perda_kwh": sum(u["perda_kwh"] for u in modeladas), "perda_brl": sum(com_preco) if com_preco else None,
                   "confianca": confianca, "n_modeladas": len(modeladas), "n_usinas": len(usinas)},
        "regua": {"tolerancia": tol, "faixas": faixas, "calibradas": sum(1 for u in modeladas if u["calibrado"]),
                  "barras": [{"id": u["id"], "codigo": u["codigo"], "faixa": u["faixa"], "frio": u["frio"]} for u in modeladas]},
    }


def _p_ac_do_dia(conn, usina_id: int, ini: dt.datetime, fim: dt.datetime) -> pd.DataFrame:
    """Potencia AC crua dos inversores no dia, ja na grade de 15 min (media por slot e inversor)."""
    rows = _q(conn, "SELECT l.equipamento_id, l.ts, l.valor FROM leitura l WHERE l.medida='p_ac' AND l.ts >= %s AND l.ts < %s "
                    "AND l.equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor')", (ini, fim, usina_id))
    df = pd.DataFrame(rows, columns=["eq", "ts", "v"])
    if df.empty:
        return pd.DataFrame(columns=["eq", "b", "v"])
    df["b"] = pd.to_datetime(df["ts"], utc=True).dt.floor("15min")
    return df.groupby(["eq", "b"], as_index=False)["v"].mean()


def _esperado_do_dia(conn, usina_id: int, modelo_id: int | None, ini: dt.datetime, fim: dt.datetime) -> pd.DataFrame:
    if modelo_id is None:
        return pd.DataFrame(columns=["eq", "b", "e"])
    rows = _q(conn, "SELECT x.equipamento_id, x.ts, x.p_esperado_kw FROM esperado x WHERE x.modelo_id=%s AND x.ts >= %s AND x.ts < %s "
                    "AND x.p_esperado_kw IS NOT NULL AND x.equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s)",
              (modelo_id, ini, fim, usina_id))
    df = pd.DataFrame(rows, columns=["eq", "b", "e"])
    if not df.empty:
        df["b"] = pd.to_datetime(df["b"], utc=True)
    return df


def usina(conn, usina_id: int, agora: dt.datetime) -> dict | None:
    us = _usinas(conn, usina_id)
    if not us:
        return None
    u = us[0]; tz = ZoneInfo(u["tz"]); hoje = agora.astimezone(tz).date(); ini, fim = _dia_utc(hoje, tz)
    mid = u["modelo_id"]
    n_tipo = dict(_q(conn, "SELECT tipo, count(*) FROM equipamento WHERE usina_id=%s AND ativo GROUP BY tipo", (usina_id,)))
    slot = _ultimo_slot(conn, usina_id, mid, agora)
    esp_kw, med_kw, gate_agora = _agora_da_usina(conn, usina_id, mid, slot) if slot else (None, None, None)
    delta = (med_kw - esp_kw) / esp_kw if esp_kw and med_kw is not None else None
    cabecalho = {"id": usina_id, "codigo": u["codigo"], "nome": u["nome"], "fonte": u["fonte"], "fonte_ref": u["fonte_ref"], "cliente": u["cliente"], "tz": u["tz"],
                 "kwp": u["kwp"], "kw_ac": u["kw_ac"], "n_inversores": int(n_tipo.get("inversor", 0)), "n_trackers": int(n_tipo.get("tracker", 0)),
                 "n_strings": int(n_tipo.get("string", 0)), "modelo_versao": u["modelo_versao"], "calibrado": bool(u["calibrado"]),
                 "tolerancia": float(u["tolerancia"]), "hoje": str(hoje), "slot": slot, "esperado_kw": esp_kw, "medido_kw": med_kw,
                 "delta": delta, "faixa": faixa(delta, float(u["tolerancia"])), "gate_agora": gate_agora, "base": "agora",
                 "idade_leitura_min": _min(agora, u["ultima_leitura"]), "idade_esperado_min": _min(agora, slot)}
    # "Ver dia" congela o agora no fim do dia escolhido, entao ha leitura DEPOIS dele: idade negativa nao e frio,
    # e "ha -531 min" nao quer dizer nada para quem le. Some, e a tela deixa de acusar dado velho que nao existe.
    passado = (cabecalho["idade_leitura_min"] or 0) < 0
    if passado:
        cabecalho["idade_leitura_min"] = None
    cabecalho["frio"] = not passado and (cabecalho["idade_leitura_min"] is None or cabecalho["idade_leitura_min"] > FRIO_MIN)
    # curva do dia: esperado (o que o modelo ja calculou) x medido (ate agora), na grade de 15 min
    pac = _p_ac_do_dia(conn, usina_id, ini, min(fim, agora))
    esp = _esperado_do_dia(conn, usina_id, mid, ini, fim)
    esp_curva = esp.groupby("b")["e"].sum().to_dict() if not esp.empty else {}
    med_curva = pac.groupby("b")["v"].sum().to_dict() if not pac.empty else {}
    curva, slots = [], sorted(set(esp_curva) | set(med_curva))
    for b in slots:
        ts = pd.Timestamp(b).to_pydatetime()
        curva.append({"ts": ts.isoformat(), "hora": ts.astimezone(tz).strftime("%H:%M"),
                      "esperado_kw": (float(esp_curva[b]) if b in esp_curva else None), "medido_kw": (float(med_curva[b]) if b in med_curva else None)})
    casc = _cascata(conn, usina_id, mid, hoje)
    # Sem sol no ultimo slot nao existe instante para comparar: as 23h o esperado e ~0 e a razao medido/esperado
    # explodia — a CPP100 de 03/09 abria com "Dentro 365,1% agora". Nesse caso o selo passa a mostrar o DIA fechado.
    piso = max(20.0, 0.02 * float(u["kw_ac"] or 0.0))
    if casc and (esp_kw is None or esp_kw < piso):
        d_dia = ((casc["e_medido"] - casc["e_esperado"]) / casc["e_esperado"]) if casc["e_esperado"] else None
        cabecalho.update({"delta": d_dia, "faixa": faixa(d_dia, float(u["tolerancia"])), "base": "dia"})
    preco = _preco(conn, usina_id, hoje)
    n_inv_ativos = int(_q(conn, "SELECT count(*) FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND ativo", (usina_id,))[0][0])
    eventos = [{"id": r[0], "tipo": r[1], "equipamento_id": r[2], "equipamento": r[3], "ini": r[4].isoformat(), "hora_ini": r[4].astimezone(tz).strftime("%H:%M"),
                "fim": r[5].isoformat() if r[5] else None, "hora_fim": (r[5].astimezone(tz).strftime("%H:%M") if r[5] else None), "severidade": r[6], "kwh": float(r[7]), "detalhe": r[8] or {}}
               for r in _q(conn, "SELECT ev.id, ev.tipo, ev.equipamento_id, coalesce(e.nome_exibicao, e.codigo_fonte, 'estação'), ev.ini, ev.fim, "
                                 "ev.severidade, ev.kwh, ev.detalhe FROM evento ev LEFT JOIN equipamento e ON e.id=ev.equipamento_id "
                                 "WHERE ev.usina_id=%s AND (ev.ini >= %s OR ev.fim IS NULL) AND ev.ini < %s ORDER BY ev.kwh DESC, ev.ini", (usina_id, ini, fim))]
    perdas: dict[int, dict[str, float]] = {}
    for eid, parcela, kwh in _q(conn, "SELECT p.equipamento_id, p.parcela, p.kwh FROM perda_dia p WHERE p.modelo_id=%s AND p.dia=%s "
                                      "AND p.equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s)", (mid, hoje, usina_id)) if mid else []:
        perdas.setdefault(int(eid), {})[parcela] = float(kwh)
    # por inversor: medido e esperado nos MESMOS instantes (a regua do rollup), parcelas do perda_dia, status pelos eventos
    por_inv: dict[int, tuple[float, float]] = {}
    if not pac.empty and not esp.empty:
        j = pac.merge(esp, on=["eq", "b"], how="inner")
        for eid, g in j.groupby("eq"):
            por_inv[int(eid)] = (float(g["v"].sum() * H), float(g["e"].sum() * H))
    ev_por_eq: dict[int, str] = {}
    for e in eventos:
        if e["equipamento_id"] and e["tipo"] in ("inversor_parado", "inversor_abaixo"):
            ev_por_eq.setdefault(e["equipamento_id"], "parado" if e["tipo"] == "inversor_parado" else "abaixo")
    # curva por inversor nos MESMOS slots da curva da usina (o Raio-X do /painel desenha inversor sobre usina; 06/09):
    # a soma das curvas medidas dos inversores e exatamente a curva medida da usina, porque ela nasce deste mesmo `pac`.
    med_inv = {int(eid): g.groupby("b")["v"].mean().to_dict() for eid, g in pac.groupby("eq")} if not pac.empty else {}
    esp_inv = {int(eid): g.groupby("b")["e"].mean().to_dict() for eid, g in esp.groupby("eq")} if not esp.empty else {}

    def _serie(d: dict) -> list:
        return [(round(float(d[b]), 2) if b in d else None) for b in slots]

    inversores = []
    for eid, nome, at, codigo in _q(conn, "SELECT id, coalesce(nome_exibicao, codigo_fonte), atributos, codigo_fonte FROM equipamento "
                                          "WHERE usina_id=%s AND tipo='inversor' AND ativo "
                                          "ORDER BY CAST(json_extract(atributos, '$.numero') AS INTEGER), codigo_fonte", (usina_id,)):
        med, esp_i = por_inv.get(int(eid), (None, None))
        razao = (med / esp_i) if esp_i else None
        p = perdas.get(int(eid), {})
        status = ev_por_eq.get(int(eid)) or ("sem_dado" if razao is None else "atencao" if razao < 0.9 else "ok")
        inversores.append({"id": int(eid), "nome": nome, "codigo": codigo, "kwp": (at or {}).get("kwp"), "medido_kwh": med, "esperado_kwh": esp_i, "razao": razao,
                           "inv_parado": p.get("inv_parado", 0.0), "tracker": p.get("tracker", 0.0), "string": p.get("string", 0.0),
                           "clipping": p.get("clipping", 0.0),
                           "residuo": p.get("residuo", 0.0), "status": status,
                           "curva_medida_kw": _serie(med_inv.get(int(eid), {})), "curva_esperada_kw": _serie(esp_inv.get(int(eid), {}))})

    def _top(tipo: str, parcela: str, n: int = 15) -> list[dict]:
        rows = _q(conn, "SELECT e.id, coalesce(e.nome_exibicao, e.codigo_fonte), e.pai_id, p.kwh FROM perda_dia p JOIN equipamento e ON e.id=p.equipamento_id "
                        "WHERE e.usina_id=%s AND e.tipo=%s AND p.parcela=%s AND p.modelo_id=%s AND p.dia=%s ORDER BY p.kwh DESC LIMIT %s",
                  (usina_id, tipo, parcela, mid, hoje, n)) if mid else []
        return [{"id": int(r[0]), "nome": r[1], "pai_id": r[2], "kwh": float(r[3])} for r in rows]

    pares = _q(conn, "SELECT p.valor, g.valor FROM leitura p JOIN leitura g ON g.equipamento_id=p.equipamento_id AND g.ts=p.ts AND g.medida='ghi' "
                     "WHERE p.medida='poa' AND g.valor > 100 AND p.ts >= %s AND p.ts < %s "
                     "AND p.equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s AND tipo='estacao')", (ini, fim, usina_id))
    razao_dia = float(np.median([a / b for a, b in pares])) if pares else None
    sensor = {"razao_poa_ghi": razao_dia, "cobertura_gate": (casc["cobertura_gate"] if casc else None), "gate_hoje": _gate_hoje(conn, usina_id, ini, fim),
              "trackers_sem_inversor": (casc["trackers_sem_inversor"] if casc else None),
              "congelado": any(e.get("tipo") == "sensor_congelado" for e in eventos),
              **clima_do_dia(conn, usina_id, ini, fim, u.get("lat"), u.get("lon"), tz),
              **rendimento_do_dia(conn, usina_id, ini, fim, u.get("kwp"))}
    sensor["ceu"] = ceu_do_indice(sensor.get("variabilidade"))
    return {"agora": agora.isoformat(), "ciclo": _ciclo(conn), "cabecalho": cabecalho, "periodo": {"dias": 1, "de": str(hoje), "ate": str(hoje)},
            "dias": [], "curva": curva, "paradas": _paradas(eventos, tz, n_inv_ativos), "cascata": casc, "preco_mwh": preco,
            # clipping fora da conta: e limite de PROJETO, nao falha de operacao (Levi, 17/09/2026)
            "perda_brl": ((max(0.0, casc["delta"] - casc.get("clipping", 0.0)) / 1000.0 * preco)
                          if (casc and preco) else None), "eventos": eventos, "inversores": inversores,
            "trackers": _top("tracker", "tracker"), "strings": _top("string", "string"), "sensor": sensor}


def _paradas(eventos: list[dict], tz: ZoneInfo, n_inversores: int) -> list[dict]:
    """Junta os eventos de inversor parado que se sobrepoem numa janela so: e o desligamento visto pela usina,
    nao pelo equipamento. A curva do dia marca cada janela em vermelho. Quantos inversores caem juntos e o que
    separa a falha de UM equipamento do desligamento (ou corte remoto) que atinge a usina inteira."""
    linhas = sorted(((dt.datetime.fromisoformat(e["ini"]), dt.datetime.fromisoformat(e["fim"]), e)
                     for e in eventos if e["tipo"] == "inversor_parado" and e.get("fim")), key=lambda x: x[0])
    janelas: list[dict] = []
    for ini, fim, e in linhas:
        if janelas and ini <= janelas[-1]["_fim"] + dt.timedelta(minutes=15):
            j = janelas[-1]
            j["_fim"] = max(j["_fim"], fim); j["kwh"] += e["kwh"]; j["equipamentos"].append(e["equipamento"])
        else:
            janelas.append({"_ini": ini, "_fim": fim, "kwh": e["kwh"], "equipamentos": [e["equipamento"]]})
    return [{"ini": j["_ini"].isoformat(), "fim": j["_fim"].isoformat(),
             "hora_ini": j["_ini"].astimezone(tz).strftime("%H:%M"), "hora_fim": j["_fim"].astimezone(tz).strftime("%H:%M"),
             "min": int((j["_fim"] - j["_ini"]).total_seconds() // 60), "n": len(set(j["equipamentos"])), "de": n_inversores,
             "kwh": round(float(j["kwh"]), 1), "equipamentos": sorted(set(j["equipamentos"]))} for j in janelas]


def usina_periodo(conn, usina_id: int, agora: dt.datetime, dias: int) -> dict | None:
    """Diagnostico agregado dos ultimos `dias` (7 ou 30) terminando no dia de `agora`: soma das cascatas diarias, perdas por
    equipamento somadas, eventos do periodo e razao por inversor nos mesmos instantes. Tudo sai das tabelas diarias que o
    job ja grava — nao recalcula o modelo."""
    us = _usinas(conn, usina_id)
    if not us:
        return None
    u = us[0]; tz = ZoneInfo(u["tz"]); mid = u["modelo_id"]
    hoje = agora.astimezone(tz).date(); d0 = hoje - dt.timedelta(days=dias - 1)
    ini, _ = _dia_utc(d0, tz); _, fim = _dia_utc(hoje, tz)
    n_tipo = dict(_q(conn, "SELECT tipo, count(*) FROM equipamento WHERE usina_id=%s AND ativo GROUP BY tipo", (usina_id,)))
    cabecalho = {"id": usina_id, "codigo": u["codigo"], "nome": u["nome"], "fonte": u["fonte"], "fonte_ref": u["fonte_ref"], "cliente": u["cliente"], "tz": u["tz"],
                 "kwp": u["kwp"], "kw_ac": u["kw_ac"], "n_inversores": int(n_tipo.get("inversor", 0)), "n_trackers": int(n_tipo.get("tracker", 0)),
                 "n_strings": int(n_tipo.get("string", 0)), "modelo_versao": u["modelo_versao"], "calibrado": bool(u["calibrado"]),
                 "tolerancia": float(u["tolerancia"]), "hoje": str(hoje), "slot": None, "esperado_kw": None, "medido_kw": None, "delta": None,
                 "faixa": "sem_dado", "gate_agora": None, "idade_leitura_min": _min(agora, u["ultima_leitura"]), "idade_esperado_min": None}
    cabecalho["frio"] = cabecalho["idade_leitura_min"] is None or cabecalho["idade_leitura_min"] > FRIO_MIN
    ch = ("e_esperado", "e_medido", "delta", "inv_parado", "tracker", "string", "clipping", "residuo", "cobertura_gate", "trackers_sem_inversor")
    rows = _q(conn, "SELECT dia, e_esperado, e_medido, delta, inv_parado, tracker, string, clipping, residuo, cobertura_gate, trackers_sem_inversor "
                    "FROM cascata_dia WHERE usina_id=%s AND modelo_id=%s AND dia >= %s AND dia <= %s ORDER BY dia", (usina_id, mid, d0, hoje)) if mid else []
    dias_l = [{"dia": r[0].isoformat(), **{k: (float(v) if k != "trackers_sem_inversor" else int(v)) for k, v in zip(ch, r[1:])}} for r in rows]
    casc = None
    if dias_l:
        casc = {k: float(sum(d[k] for d in dias_l)) for k in ("e_esperado", "e_medido", "delta", "inv_parado", "tracker", "string", "residuo")}
        casc["cobertura_gate"] = float(sum(d["cobertura_gate"] for d in dias_l) / len(dias_l))
        casc["trackers_sem_inversor"] = max(d["trackers_sem_inversor"] for d in dias_l)
        casc["n_dias"] = len(dias_l)
        # delta do periodo sobre o esperado: e a faixa da regua, agora com dias inteiros em vez de um slot
        delta = (casc["e_medido"] - casc["e_esperado"]) / casc["e_esperado"] if casc["e_esperado"] else None
        cabecalho.update({"delta": delta, "faixa": faixa(delta, float(u["tolerancia"])), "esperado_kw": casc["e_esperado"], "medido_kw": casc["e_medido"]})
    preco = _preco(conn, usina_id, hoje)
    eventos = [{"id": r[0], "tipo": r[1], "equipamento_id": r[2], "equipamento": r[3], "ini": r[4].isoformat(), "hora_ini": r[4].astimezone(tz).strftime("%d/%m %H:%M"),
                "fim": r[5].isoformat() if r[5] else None, "severidade": r[6], "kwh": float(r[7]), "detalhe": r[8] or {}}
               for r in _q(conn, "SELECT ev.id, ev.tipo, ev.equipamento_id, coalesce(e.nome_exibicao, e.codigo_fonte, 'estação'), ev.ini, ev.fim, "
                                 "ev.severidade, ev.kwh, ev.detalhe FROM evento ev LEFT JOIN equipamento e ON e.id=ev.equipamento_id "
                                 "WHERE ev.usina_id=%s AND ev.ini >= %s AND ev.ini < %s ORDER BY ev.kwh DESC, ev.ini", (usina_id, ini, fim))]
    perdas: dict[int, dict[str, float]] = {}
    for eid, parcela, kwh in _q(conn, "SELECT p.equipamento_id, p.parcela, sum(p.kwh) FROM perda_dia p WHERE p.modelo_id=%s AND p.dia >= %s AND p.dia <= %s "
                                      "AND p.equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s) GROUP BY 1, 2", (mid, d0, hoje, usina_id)) if mid else []:
        perdas.setdefault(int(eid), {})[parcela] = float(kwh)
    pac = _p_ac_do_dia(conn, usina_id, ini, min(fim, agora))
    esp = _esperado_do_dia(conn, usina_id, mid, ini, fim)
    por_inv: dict[int, tuple[float, float]] = {}
    if not pac.empty and not esp.empty:
        j = pac.merge(esp, on=["eq", "b"], how="inner")
        for eid, g in j.groupby("eq"):
            por_inv[int(eid)] = (float(g["v"].sum() * H), float(g["e"].sum() * H))
    ev_por_eq: dict[int, str] = {}
    for e in eventos:
        if e["equipamento_id"] and e["tipo"] in ("inversor_parado", "inversor_abaixo"):
            ev_por_eq.setdefault(e["equipamento_id"], "parado" if e["tipo"] == "inversor_parado" else "abaixo")
    inversores = []
    for eid, nome, at, codigo in _q(conn, "SELECT id, coalesce(nome_exibicao, codigo_fonte), atributos, codigo_fonte FROM equipamento "
                                          "WHERE usina_id=%s AND tipo='inversor' AND ativo "
                                          "ORDER BY CAST(json_extract(atributos, '$.numero') AS INTEGER), codigo_fonte", (usina_id,)):
        med, esp_i = por_inv.get(int(eid), (None, None))
        razao = (med / esp_i) if esp_i else None
        p = perdas.get(int(eid), {})
        status = ev_por_eq.get(int(eid)) or ("sem_dado" if razao is None else "atencao" if razao < 0.9 else "ok")
        inversores.append({"id": int(eid), "nome": nome, "codigo": codigo, "kwp": (at or {}).get("kwp"), "medido_kwh": med, "esperado_kwh": esp_i, "razao": razao,
                           "inv_parado": p.get("inv_parado", 0.0), "tracker": p.get("tracker", 0.0), "string": p.get("string", 0.0),
                           "residuo": p.get("residuo", 0.0), "status": status})

    def _top(tipo: str, parcela: str, n: int = 15) -> list[dict]:
        rows = _q(conn, "SELECT e.id, coalesce(e.nome_exibicao, e.codigo_fonte), e.pai_id, sum(p.kwh) FROM perda_dia p JOIN equipamento e ON e.id=p.equipamento_id "
                        "WHERE e.usina_id=%s AND e.tipo=%s AND p.parcela=%s AND p.modelo_id=%s AND p.dia >= %s AND p.dia <= %s GROUP BY e.id ORDER BY 4 DESC LIMIT %s",
                  (usina_id, tipo, parcela, mid, d0, hoje, n)) if mid else []
        return [{"id": int(r[0]), "nome": r[1], "pai_id": r[2], "kwh": float(r[3])} for r in rows]

    pares = _q(conn, "SELECT p.valor, g.valor FROM leitura p JOIN leitura g ON g.equipamento_id=p.equipamento_id AND g.ts=p.ts AND g.medida='ghi' "
                     "WHERE p.medida='poa' AND g.valor > 100 AND p.ts >= %s AND p.ts < %s "
                     "AND p.equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s AND tipo='estacao')", (ini, fim, usina_id))
    sensor = {"razao_poa_ghi": (float(np.median([a / b for a, b in pares])) if pares else None), "cobertura_gate": (casc["cobertura_gate"] if casc else None),
              "gate_hoje": _gate_hoje(conn, usina_id, ini, fim), "trackers_sem_inversor": (casc["trackers_sem_inversor"] if casc else None)}
    # a mesma marca vermelha da curva do dia, agora por DIA: cada coluna do grafico de 7/30 dias sabe se houve
    # desligamento e de que tamanho. Sem isso a barra de um dia com 8 inversores fora parece so um dia ruim.
    por_dia: dict[str, list[dict]] = {}
    for e in eventos:
        if e["tipo"] == "inversor_parado" and e.get("fim"):
            por_dia.setdefault(dt.datetime.fromisoformat(e["ini"]).astimezone(tz).date().isoformat(), []).append(e)
    n_inv = int(n_tipo.get("inversor", 0))
    for d in dias_l:
        d["paradas"] = [{k: j[k] for k in ("hora_ini", "hora_fim", "n", "de", "kwh", "min")} for j in _paradas(por_dia.get(d["dia"], []), tz, n_inv)]
    return {"agora": agora.isoformat(), "ciclo": _ciclo(conn), "cabecalho": cabecalho, "periodo": {"dias": dias, "de": d0.isoformat(), "ate": hoje.isoformat()},
            "dias": dias_l, "curva": [], "paradas": [p for d in dias_l for p in d["paradas"]], "cascata": casc, "preco_mwh": preco,
            # clipping fora da conta: e limite de PROJETO, nao falha de operacao (Levi, 17/09/2026)
            "perda_brl": ((max(0.0, casc["delta"] - casc.get("clipping", 0.0)) / 1000.0 * preco)
                          if (casc and preco) else None), "eventos": eventos, "inversores": inversores,
            "trackers": _top("tracker", "tracker"), "strings": _top("string", "string"), "sensor": sensor}


def catalogo(conn) -> list[dict]:
    """Quem esta no gemeo e como a plataforma o encontra: (fonte, fonte_ref) e a chave — 'pg' + plant_id do PostgreSQL,
    'sunop' + nome da planta na SunOp. E o que o Raio-X do /painel usa para saber se a usina tem gemeo (06/09/2026)."""
    return [{"id": u["id"], "codigo": u["codigo"], "nome": u["nome"], "fonte": u["fonte"], "fonte_ref": u["fonte_ref"], "cliente": u["cliente"],
             "kwp": u["kwp"], "n_equip": u["n_equip"], "modelo_versao": u["modelo_versao"], "calibrado": u["calibrado"]} for u in _usinas(conn)]


def saude(conn, cfg, agora: dt.datetime) -> dict:
    """/healthz: por fonte o ultimo ciclo (idade, status, cobertura), SunOp hoje / teto, ultimo modelar, banco, a
    publicacao no workbook e a validade do token de API da SunOp (alarme 30 dias antes)."""
    fontes = {}
    try:
        rows = _q(conn, "SELECT fonte, criado_em, status, cobertura FROM ingest_run WHERE id IN (SELECT max(id) FROM ingest_run GROUP BY fonte)")
        banco = True
    except Exception as e:                  # noqa: BLE001 — sem banco a resposta e o proprio diagnostico
        return {"ok": False, "banco": False, "erro": f"{type(e).__name__}: {e}"[:200], "agora": agora.isoformat()}
    for fonte, em, status, cob in rows:
        fontes[fonte] = {"ultimo": em.isoformat(), "idade_min": _min(agora, em), "status": status, "cobertura": float(cob)}
    dia0 = dt.datetime.combine(agora.astimezone(dt.timezone.utc).date(), dt.time.min, tzinfo=dt.timezone.utc)
    hoje = _q(conn, "SELECT coalesce(sum(n_requisicoes),0) FROM ingest_run WHERE fonte LIKE 'sunop%%' AND criado_em >= %s AND criado_em < %s",
              (dia0, dia0 + dt.timedelta(days=1)))
    sunop_hoje = int(hoje[0][0]) if hoje else 0
    ciclo = _ciclo(conn)
    exp = exp_do_jwt(getattr(cfg, "sunop_token", "") or "")
    dias_token = (exp - agora).days if exp else None
    problemas = []
    # A noite nao ha ciclo SunOp (janela solar): a idade do ultimo ciclo so e problema com alguma usina em janela.
    # 'parcial' e o normal do crepusculo (cobertura ~50% que a reconciliacao das 03h completa) — so 'falha' acusa.
    janela = getattr(cfg, "janela_solar", ("05:40", "18:20"))
    # SO os fusos, direto da tabela `usina`: `_usinas` faria um `_ultima_leitura` por usina e o healthz
    # levava 56 s sobre 17,3 M linhas — o proxy da plataforma (timeout=30) devolvia 503 num gemeo
    # saudavel, que e como esta rota passou a mentir sobre gravidade (17/09/2026)
    fusos = [f for f, in _q(conn, "SELECT tz FROM usina WHERE ativo")]
    dia = any(tempo.dentro_janela_solar(agora, f, janela) for f in fusos)
    for f, v in fontes.items():
        if v["status"] == "falha" or (dia and (v["idade_min"] or 0) > 120):
            problemas.append(f"{f}: {v['status']} há {v['idade_min']} min")
    if ciclo.get("em"):
        idade_ciclo = _min(agora, dt.datetime.fromisoformat(ciclo["em"]))
        if idade_ciclo is not None and idade_ciclo > 45:
            problemas.append(f"modelar há {idade_ciclo} min")
    else:
        problemas.append("modelar nunca rodou")
    if dias_token is not None and dias_token < 30:
        problemas.append(f"token SunOp vence em {dias_token} dias")
    if sunop_hoje >= getattr(cfg, "teto_sunop_dia", 600):
        problemas.append(f"SunOp no teto: {sunop_hoje}")
    pub = _estado_json(conn, "publicar.ultimo")             # vitrine na API da Performance: falha aparece, mas nao derruba o modelar
    if pub and not pub.get("ok"):
        problemas.append(f"publicar: {str(pub.get('erro', 'falhou'))[:80]}")
    return {"ok": not problemas, "banco": banco, "agora": agora.isoformat(), "fontes": fontes,
            "sunop": {"requisicoes_hoje": sunop_hoje, "teto": getattr(cfg, "teto_sunop_dia", 600), "token_exp": exp.isoformat() if exp else None, "token_dias": dias_token},
            "modelar": ciclo, "publicar": pub, "problemas": problemas}
