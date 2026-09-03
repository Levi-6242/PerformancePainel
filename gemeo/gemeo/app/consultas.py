# gemeo/gemeo/app/consultas.py
"""Todo o SQL das telas, em funcoes banco -> dict (JSON-serializavel). O app so renderiza. 'Agora' e
parametro (nunca now()) para as telas serem testaveis sobre um dia congelado — e para 'viajar no tempo'
ao depurar: `/gemeo/?agora=2026-08-31T20:00:00Z`."""
from __future__ import annotations
import base64
import datetime as dt
import json
from zoneinfo import ZoneInfo

FRIO_MIN = 30          # frescor: acima disto a usina fica cinza antes de qualquer outra cor (spec §9)
DEFICIT_GRAVE = 0.08   # faixa 'deficit grave' da regua
H = 0.25
NOMES_PARCELA = {"inv_parado": "inversor parado", "tracker": "trackers fora do alvo",
                 "string": "strings sem corrente", "residuo": "resíduo (não explicado)"}


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
        return "sem ingestão ok nas últimas 24 h"
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


def _usinas(conn, usina_id: int | None = None) -> list[dict]:
    filtro = "AND u.id=%s" if usina_id else ""
    rows = _q(conn, f"""
        SELECT u.id, u.codigo, u.nome, u.fonte, u.tz, coalesce(u.kwp_dc,0), coalesce(u.kw_ac,0), u.cliente,
               (SELECT count(*) FROM equipamento e WHERE e.usina_id=u.id AND e.ativo),
               (SELECT max(r.criado_em) FROM ingest_run r WHERE r.usina_id=u.id AND r.status='ok'),
               (SELECT max(l.ts) FROM leitura l JOIN equipamento e ON e.id=l.equipamento_id WHERE e.usina_id=u.id),
               m.id, m.versao, coalesce(m.tolerancia, 0.08), coalesce(m.calibrado, false)
        FROM usina u LEFT JOIN modelo m ON m.usina_id=u.id AND m.ativo
        WHERE u.ativo {filtro} ORDER BY u.codigo""", (usina_id,) if usina_id else ())
    chaves = ("id", "codigo", "nome", "fonte", "tz", "kwp", "kw_ac", "cliente", "n_equip", "ultimo_ingest_ok", "ultima_leitura",
              "modelo_id", "modelo_versao", "tolerancia", "calibrado")
    return [dict(zip(chaves, r)) for r in rows]


def _ultimo_slot(conn, usina_id: int, modelo_id: int | None, agora: dt.datetime) -> dt.datetime | None:
    if modelo_id is None:
        return None
    r = _q(conn, "SELECT max(x.ts) FROM esperado x JOIN equipamento e ON e.id=x.equipamento_id "
                 "WHERE e.usina_id=%s AND x.modelo_id=%s AND x.p_esperado_kw IS NOT NULL AND x.ts <= %s", (usina_id, modelo_id, agora))
    return r[0][0] if r and r[0][0] else None


def _agora_da_usina(conn, usina_id: int, modelo_id: int, slot: dt.datetime) -> tuple[float | None, float | None, str | None]:
    esp = _q(conn, "SELECT sum(x.p_esperado_kw), min(x.gate) FROM esperado x JOIN equipamento e ON e.id=x.equipamento_id "
                   "WHERE e.usina_id=%s AND x.modelo_id=%s AND x.ts=%s", (usina_id, modelo_id, slot))
    med = _q(conn, "SELECT sum(v) FROM (SELECT avg(l.valor) v FROM leitura l JOIN equipamento e ON e.id=l.equipamento_id "
                   "WHERE e.usina_id=%s AND e.tipo='inversor' AND l.medida='p_ac' AND l.ts >= %s AND l.ts < %s GROUP BY l.equipamento_id) s",
             (usina_id, slot, slot + dt.timedelta(minutes=15)))
    e = float(esp[0][0]) if esp and esp[0][0] is not None else None
    m = float(med[0][0]) if med and med[0][0] is not None else None
    return e, m, (esp[0][1] if esp else None)


def _cascata(conn, usina_id: int, modelo_id: int | None, dia: dt.date) -> dict | None:
    if modelo_id is None:
        return None
    r = _q(conn, "SELECT e_esperado, e_medido, delta, inv_parado, tracker, string, residuo, cobertura_gate, trackers_sem_inversor "
                 "FROM cascata_dia WHERE usina_id=%s AND modelo_id=%s AND dia=%s", (usina_id, modelo_id, dia))
    if not r:
        return None
    ch = ("e_esperado", "e_medido", "delta", "inv_parado", "tracker", "string", "residuo", "cobertura_gate", "trackers_sem_inversor")
    return {k: (float(v) if k != "trackers_sem_inversor" else int(v)) for k, v in zip(ch, r[0])}


def _gate_hoje(conn, usina_id: int, ini: dt.datetime, fim: dt.datetime) -> str:
    r = _q(conn, "SELECT tipo FROM evento WHERE usina_id=%s AND tipo IN ('sensor_em_falha','sem_cobertura') AND ini >= %s AND ini < %s LIMIT 1",
           (usina_id, ini, fim))
    return {"sensor_em_falha": "poa_ghi", "sem_cobertura": "cobertura"}.get(r[0][0], "ok") if r else "ok"


def _preco(conn, usina_id: int, dia: dt.date) -> float | None:
    r = _q(conn, "SELECT preco_mwh FROM meta_mes WHERE usina_id=%s AND ano=%s AND mes=%s", (usina_id, dia.year, dia.month))
    return float(r[0][0]) if r and r[0][0] is not None else None


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
    modeladas = sorted([u for u in usinas if u["motivo"] is None], key=lambda u: -(u["perda_brl"] or u["perda_kwh"]))
    nao = [{"id": u["id"], "codigo": u["codigo"], "fonte": u["fonte"], "motivo": u["motivo"]} for u in usinas if u["motivo"]]
    tot_esp = sum(u["esperado_kw"] for u in modeladas if u["esperado_kw"] is not None)
    tot_med = sum(u["medido_kw"] for u in modeladas if u["medido_kw"] is not None)
    com_preco = [u["perda_brl"] for u in modeladas if u["perda_brl"] is not None]
    confianca = (sum(1 for u in usinas if u["gate_agora"] == "ok" and not u["frio"]) / len(usinas)) if usinas else 0.0
    faixas = {k: sum(1 for u in modeladas if u["faixa"] == k) for k in ("dentro", "moderado", "grave", "sem_dado")}
    tol = min([float(u["tolerancia"]) for u in modeladas], default=0.08)
    return {
        "agora": agora.isoformat(), "ciclo": _ciclo(conn), "usinas": modeladas, "nao_modeladas": nao,
        "totais": {"esperado_kw": tot_esp, "medido_kw": tot_med, "delta": ((tot_med - tot_esp) / tot_esp) if tot_esp else None,
                   "perda_kwh": sum(u["perda_kwh"] for u in modeladas), "perda_brl": sum(com_preco) if com_preco else None,
                   "confianca": confianca, "n_modeladas": len(modeladas), "n_usinas": len(usinas)},
        "regua": {"tolerancia": tol, "faixas": faixas, "calibradas": sum(1 for u in modeladas if u["calibrado"]),
                  "barras": [{"id": u["id"], "codigo": u["codigo"], "faixa": u["faixa"], "frio": u["frio"]} for u in modeladas]},
    }


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
    cabecalho = {"id": usina_id, "codigo": u["codigo"], "nome": u["nome"], "fonte": u["fonte"], "cliente": u["cliente"], "tz": u["tz"],
                 "kwp": u["kwp"], "kw_ac": u["kw_ac"], "n_inversores": int(n_tipo.get("inversor", 0)), "n_trackers": int(n_tipo.get("tracker", 0)),
                 "n_strings": int(n_tipo.get("string", 0)), "modelo_versao": u["modelo_versao"], "calibrado": bool(u["calibrado"]),
                 "tolerancia": float(u["tolerancia"]), "hoje": str(hoje), "slot": slot, "esperado_kw": esp_kw, "medido_kw": med_kw,
                 "delta": delta, "faixa": faixa(delta, float(u["tolerancia"])), "gate_agora": gate_agora,
                 "idade_leitura_min": _min(agora, u["ultima_leitura"]), "idade_esperado_min": _min(agora, slot)}
    cabecalho["frio"] = cabecalho["idade_leitura_min"] is None or cabecalho["idade_leitura_min"] > FRIO_MIN
    # curva do dia: esperado (dia inteiro, o que o modelo ja calculou) x medido (ate agora), na grade de 15 min
    esp_curva = dict(_q(conn, "SELECT x.ts, sum(x.p_esperado_kw) FROM esperado x JOIN equipamento e ON e.id=x.equipamento_id "
                              "WHERE e.usina_id=%s AND x.modelo_id=%s AND x.ts >= %s AND x.ts < %s GROUP BY x.ts", (usina_id, mid, ini, fim))) if mid else {}
    med_curva = dict(_q(conn, "SELECT b, sum(v) FROM (SELECT date_bin('15 minutes', l.ts, TIMESTAMPTZ '2000-01-01') b, l.equipamento_id, avg(l.valor) v "
                              "FROM leitura l JOIN equipamento e ON e.id=l.equipamento_id WHERE e.usina_id=%s AND e.tipo='inversor' AND l.medida='p_ac' "
                              "AND l.ts >= %s AND l.ts < %s GROUP BY 1, 2) s GROUP BY b", (usina_id, ini, min(fim, agora))))
    curva = [{"ts": ts.isoformat(), "hora": ts.astimezone(tz).strftime("%H:%M"),
              "esperado_kw": (float(esp_curva[ts]) if esp_curva.get(ts) is not None else None),
              "medido_kw": (float(med_curva[ts]) if med_curva.get(ts) is not None else None)}
             for ts in sorted(set(esp_curva) | set(med_curva))]
    casc = _cascata(conn, usina_id, mid, hoje)
    preco = _preco(conn, usina_id, hoje)
    eventos = [{"id": r[0], "tipo": r[1], "equipamento_id": r[2], "equipamento": r[3], "ini": r[4].isoformat(), "hora_ini": r[4].astimezone(tz).strftime("%H:%M"),
                "fim": r[5].isoformat() if r[5] else None, "severidade": r[6], "kwh": float(r[7]), "detalhe": r[8] or {}}
               for r in _q(conn, "SELECT ev.id, ev.tipo, ev.equipamento_id, coalesce(e.nome_exibicao, e.codigo_fonte, 'estação'), ev.ini, ev.fim, "
                                 "ev.severidade, ev.kwh, ev.detalhe FROM evento ev LEFT JOIN equipamento e ON e.id=ev.equipamento_id "
                                 "WHERE ev.usina_id=%s AND (ev.ini >= %s OR ev.fim IS NULL) AND ev.ini < %s ORDER BY ev.kwh DESC, ev.ini", (usina_id, ini, fim))]
    perdas: dict[int, dict[str, float]] = {}
    for eid, parcela, kwh in _q(conn, "SELECT p.equipamento_id, p.parcela, p.kwh FROM perda_dia p JOIN equipamento e ON e.id=p.equipamento_id "
                                      "WHERE e.usina_id=%s AND p.modelo_id=%s AND p.dia=%s", (usina_id, mid, hoje)) if mid else []:
        perdas.setdefault(int(eid), {})[parcela] = float(kwh)
    # por inversor: medido e esperado nos MESMOS instantes (a regua do rollup), parcelas do perda_dia, status pelos eventos
    por_inv = {int(r[0]): (float(r[1]), float(r[2])) for r in _q(conn,
        "SELECT s.equipamento_id, sum(s.v)*0.25, sum(x.p_esperado_kw)*0.25 FROM (SELECT date_bin('15 minutes', l.ts, TIMESTAMPTZ '2000-01-01') b, "
        "l.equipamento_id, avg(l.valor) v FROM leitura l JOIN equipamento e ON e.id=l.equipamento_id WHERE e.usina_id=%s AND e.tipo='inversor' "
        "AND l.medida='p_ac' AND l.ts >= %s AND l.ts < %s GROUP BY 1, 2) s JOIN esperado x ON x.equipamento_id=s.equipamento_id AND x.ts=s.b "
        "AND x.modelo_id=%s AND x.p_esperado_kw IS NOT NULL GROUP BY 1", (usina_id, ini, fim, mid))} if mid else {}
    ev_por_eq: dict[int, str] = {}
    for e in eventos:
        if e["equipamento_id"] and e["tipo"] in ("inversor_parado", "inversor_abaixo"):
            ev_por_eq.setdefault(e["equipamento_id"], "parado" if e["tipo"] == "inversor_parado" else "abaixo")
    inversores = []
    for eid, nome, at in _q(conn, "SELECT id, coalesce(nome_exibicao, codigo_fonte), atributos FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND ativo "
                                  "ORDER BY (atributos->>'numero')::int NULLS LAST, codigo_fonte", (usina_id,)):
        med, esp = por_inv.get(int(eid), (None, None))
        razao = (med / esp) if esp else None
        p = perdas.get(int(eid), {})
        status = ev_por_eq.get(int(eid)) or ("sem_dado" if razao is None else "atencao" if razao < 0.9 else "ok")
        inversores.append({"id": int(eid), "nome": nome, "kwp": (at or {}).get("kwp"), "medido_kwh": med, "esperado_kwh": esp, "razao": razao,
                           "inv_parado": p.get("inv_parado", 0.0), "tracker": p.get("tracker", 0.0), "string": p.get("string", 0.0),
                           "residuo": p.get("residuo", 0.0), "status": status})

    def _top(tipo: str, parcela: str, n: int = 15) -> list[dict]:
        rows = _q(conn, "SELECT e.id, coalesce(e.nome_exibicao, e.codigo_fonte), e.pai_id, p.kwh FROM perda_dia p JOIN equipamento e ON e.id=p.equipamento_id "
                        "WHERE e.usina_id=%s AND e.tipo=%s AND p.parcela=%s AND p.modelo_id=%s AND p.dia=%s ORDER BY p.kwh DESC LIMIT %s",
                  (usina_id, tipo, parcela, mid, hoje, n)) if mid else []
        return [{"id": int(r[0]), "nome": r[1], "pai_id": r[2], "kwh": float(r[3])} for r in rows]

    razao_dia = _q(conn, "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY p.valor / g.valor) FROM leitura p JOIN leitura g ON g.equipamento_id=p.equipamento_id "
                         "AND g.ts=p.ts AND g.medida='ghi' JOIN equipamento e ON e.id=p.equipamento_id WHERE e.usina_id=%s AND e.tipo='estacao' AND p.medida='poa' "
                         "AND g.valor > 100 AND p.ts >= %s AND p.ts < %s", (usina_id, ini, fim))
    sensor = {"razao_poa_ghi": (float(razao_dia[0][0]) if razao_dia and razao_dia[0][0] is not None else None),
              "cobertura_gate": (casc["cobertura_gate"] if casc else None), "gate_hoje": _gate_hoje(conn, usina_id, ini, fim),
              "trackers_sem_inversor": (casc["trackers_sem_inversor"] if casc else None)}
    return {"agora": agora.isoformat(), "ciclo": _ciclo(conn), "cabecalho": cabecalho, "curva": curva, "cascata": casc, "preco_mwh": preco,
            "perda_brl": ((max(0.0, casc["delta"]) / 1000.0 * preco) if (casc and preco) else None), "eventos": eventos, "inversores": inversores,
            "trackers": _top("tracker", "tracker"), "strings": _top("string", "string"), "sensor": sensor}


def saude(conn, cfg, agora: dt.datetime) -> dict:
    """/healthz: por fonte o ultimo ciclo (idade, status, cobertura), SunOp hoje / teto, ultimo modelar, banco, e a
    validade do token de API da SunOp (alarme 30 dias antes)."""
    fontes = {}
    try:
        rows = _q(conn, "SELECT DISTINCT ON (fonte) fonte, criado_em, status, cobertura, n_requisicoes FROM ingest_run ORDER BY fonte, criado_em DESC")
        banco = True
    except Exception as e:                  # noqa: BLE001 — sem banco a resposta e o proprio diagnostico
        return {"ok": False, "banco": False, "erro": f"{type(e).__name__}: {e}"[:200], "agora": agora.isoformat()}
    for fonte, em, status, cob, nreq in rows:
        fontes[fonte] = {"ultimo": em.isoformat(), "idade_min": _min(agora, em), "status": status, "cobertura": float(cob)}
    hoje = _q(conn, "SELECT coalesce(sum(n_requisicoes),0) FROM ingest_run WHERE fonte LIKE 'sunop%%' AND (criado_em AT TIME ZONE 'UTC')::date = %s",
              (agora.astimezone(dt.timezone.utc).date(),))
    sunop_hoje = int(hoje[0][0]) if hoje else 0
    ciclo = _ciclo(conn)
    exp = exp_do_jwt(getattr(cfg, "sunop_token", "") or "")
    dias_token = (exp - agora).days if exp else None
    problemas = []
    for f, v in fontes.items():
        if v["status"] != "ok" or (v["idade_min"] or 0) > 120:
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
