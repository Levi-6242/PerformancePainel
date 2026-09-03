# gemeo/gemeo/modelar/job.py
"""`gemeo modelar`: para cada usina do piloto, carrega os ultimos 3 dias locais (o 'abaixo dos pares' pede
3 dias, e o dia de hoje e recomputado a cada 15 min), roda gate -> esperado -> decomposicao -> eventos ->
cascata e persiste por chave natural. Idempotente: rodar duas vezes deixa o banco igual."""
from __future__ import annotations
import datetime as dt
import json
import time
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import psycopg2.extras

from gemeo.core.modelos import UsinaRef
from gemeo.modelar import decomposicao as dc
from gemeo.modelar import esperado as esp_mod
from gemeo.modelar import eventos as ev_mod
from gemeo.modelar import gate as gate_mod
from gemeo.modelar import rollup
from gemeo.modelar.grade import Grade, carregar_grade

PLACA = {"gamma": -0.0035, "perdas_fixas": 0.14, "eta_inv": 0.96, "gate": {}}
DIAS_CONTEXTO = 3


def _json_limpo(obj):
    """NaN/inf viram null e numeros do numpy viram nativos: o tipo json do PostgreSQL rejeita 'NaN' — a primeira CI
    com banco real caiu exatamente nisso, num detalhe de evento."""
    if isinstance(obj, dict):
        return {k: _json_limpo(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_limpo(v) for v in obj]
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj


@dataclass(frozen=True)
class Modelo:
    id: int
    versao: str
    parametros: dict
    tolerancia: float
    calibrado: bool


def modelo_ativo(conn, usina_id: int) -> Modelo:
    """A versao ativa; sem nenhuma, nasce a 'placa' (gamma -0,35 %/C, perdas 14 %, eta 0,96, tolerancia 0,08,
    calibrado=false) — e a faixa 'modelo de placa — nao calibrado' das telas vem daqui."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, versao, parametros, tolerancia, calibrado FROM modelo WHERE usina_id=%s AND ativo", (usina_id,))
        r = cur.fetchone()
        if r is None:
            cur.execute("INSERT INTO modelo (usina_id, versao, parametros, tolerancia, calibrado, ativo) VALUES (%s,'placa',%s,0.08,false,true) "
                        "ON CONFLICT (usina_id, versao) DO UPDATE SET ativo=true RETURNING id, versao, parametros, tolerancia, calibrado",
                        (usina_id, json.dumps(PLACA)))
            r = cur.fetchone()
    conn.commit()
    return Modelo(int(r[0]), r[1], r[2] if isinstance(r[2], dict) else json.loads(r[2]), float(r[3]), bool(r[4]))


def params_por_inversor(grade: Grade, mod: Modelo, p_ac_hist: dict[int, pd.Series] | None = None) -> dict[int, esp_mod.ParamsModelo]:
    """kwp e kw_ac do proprio inversor (equipamento.atributos, vindos do cadastro); sem kwp, a placa da usina
    dividida pelos inversores; sem kw_ac, infere do maximo observado (30 dias se o job trouxe, senao a
    janela) e marca `pac0_inferido` — a tela mostra."""
    invs = [e for e, t in grade.tipo.items() if t == "inversor"]
    pr = mod.parametros
    out = {}
    for eid in invs:
        at = grade.atributos.get(eid, {})
        kwp = float(at.get("kwp") or (grade.usina.kwp / max(1, len(invs))))
        serie = (p_ac_hist or {}).get(eid)
        if serie is None:
            serie = grade.inv_p[eid] if eid in grade.inv_p.columns else pd.Series(dtype=float)
        pac0, inferido = esp_mod.inferir_pac0(serie, at.get("kw_ac"), kwp)
        out[eid] = esp_mod.ParamsModelo(kwp=kwp, pac0_kw=pac0, gamma=float(pr.get("gamma", PLACA["gamma"])),
                                        perdas_fixas=float(pr.get("perdas_fixas", PLACA["perdas_fixas"])),
                                        eta_inv=float(pr.get("eta_inv", PLACA["eta_inv"])), pac0_inferido=inferido)
    return out


def instaladas_30d(conn, usina_id: int, ate: dt.datetime, dias: int = 30) -> dict[int, list[int]]:
    """Universo de strings: canal com > 1 A em algum momento dos ultimos 30 dias, agrupado pelo inversor pai."""
    with conn.cursor() as cur:
        cur.execute("SELECT e.pai_id, e.id FROM leitura l JOIN equipamento e ON e.id=l.equipamento_id "
                    "WHERE e.usina_id=%s AND e.tipo='string' AND l.medida='i_string' AND l.ts >= %s AND l.ts < %s "
                    "GROUP BY e.pai_id, e.id HAVING max(l.valor) > 1.0 ORDER BY e.pai_id, e.id",
                    (usina_id, ate - dt.timedelta(days=dias), ate))
        out: dict[int, list[int]] = {}
        for pai, sid in cur.fetchall():
            out.setdefault(pai, []).append(sid)
    return out


def p_ac_30d(conn, usina_id: int, ate: dt.datetime, dias: int = 30) -> dict[int, pd.Series]:
    """Quantil 0,999 da potencia AC por inversor nos ultimos 30 dias, calculado no banco — e o que
    `inferir_pac0` precisa quando o cadastro nao traz kw_ac."""
    with conn.cursor() as cur:
        cur.execute("SELECT e.id, percentile_cont(0.999) WITHIN GROUP (ORDER BY l.valor) FROM leitura l "
                    "JOIN equipamento e ON e.id=l.equipamento_id WHERE e.usina_id=%s AND e.tipo='inversor' AND l.medida='p_ac' "
                    "AND l.ts >= %s AND l.ts < %s AND l.valor > 0 GROUP BY e.id", (usina_id, ate - dt.timedelta(days=dias), ate))
        return {int(eid): pd.Series([float(q)]) for eid, q in cur.fetchall() if q is not None}


def referencia_razao(conn, usina_id: int, ate: dt.datetime, tz: str = "UTC", dias: int = 30) -> float | None:
    """Referencia movel do gate: mediana, em 30 dias, da mediana diaria de POA/GHI (GHI > 100). Com menos
    de 3 dias devolve None e o gate usa a propria janela."""
    with conn.cursor() as cur:
        cur.execute("SELECT (p.ts AT TIME ZONE %s)::date, percentile_cont(0.5) WITHIN GROUP (ORDER BY p.valor / g.valor) "
                    "FROM leitura p JOIN leitura g ON g.equipamento_id=p.equipamento_id AND g.ts=p.ts AND g.medida='ghi' "
                    "JOIN equipamento e ON e.id=p.equipamento_id "
                    "WHERE e.usina_id=%s AND e.tipo='estacao' AND p.medida='poa' AND g.valor > 100 AND p.ts >= %s AND p.ts < %s "
                    "GROUP BY 1", (tz, usina_id, ate - dt.timedelta(days=dias), ate))
        vals = [float(v) for _, v in cur.fetchall() if v is not None]
    return float(np.median(vals)) if len(vals) >= 3 else None


def janela_padrao(agora: dt.datetime, tz: str, dias: int = DIAS_CONTEXTO) -> tuple[dt.datetime, dt.datetime]:
    local = agora.astimezone(ZoneInfo(tz))
    ini = (local - dt.timedelta(days=dias - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return ini.astimezone(dt.timezone.utc), agora


def persistir(conn, usina: UsinaRef, mod: Modelo, grade: Grade, r: gate_mod.Resultado, esp: pd.DataFrame,
              evs: list[ev_mod.Evento], casc: rollup.Cascata) -> None:
    est = grade.estacao
    tcel = esp_mod.temp_celula(est["temp_modulo"], est["temp_ar"], est["poa"])
    linhas = []
    for eid in esp.columns:
        col = esp[eid]
        for ts, g in r.gate.items():
            poa = est["poa"].get(ts)
            if poa is None or pd.isna(poa):      # sem POA nao ha o que dizer: a ausencia e o evento de cobertura
                continue
            v = col.get(ts); t = tcel.get(ts)
            linhas.append((int(eid), ts.to_pydatetime(), mod.id, None if pd.isna(v) else float(v), float(poa),
                           None if pd.isna(t) else float(t), str(g)))
    dias = [d for d in casc.por_dia.index]
    ini_g, fim_g = grade.indice[0].to_pydatetime(), (grade.indice[-1] + pd.Timedelta(minutes=15)).to_pydatetime()
    with conn.cursor() as cur:
        if linhas:
            psycopg2.extras.execute_values(
                cur, "INSERT INTO esperado (equipamento_id, ts, modelo_id, p_esperado_kw, poa_usada, temp_usada, gate) VALUES %s "
                     "ON CONFLICT (equipamento_id, ts, modelo_id) DO UPDATE SET p_esperado_kw=EXCLUDED.p_esperado_kw, "
                     "poa_usada=EXCLUDED.poa_usada, temp_usada=EXCLUDED.temp_usada, gate=EXCLUDED.gate", linhas, page_size=5000)
        # apaga-e-regrava a janela: e o que torna o job idempotente sem chave para 'evento sem equipamento'
        cur.execute("DELETE FROM cascata_dia WHERE usina_id=%s AND modelo_id=%s AND dia = ANY(%s)", (usina.id, mod.id, dias))
        cur.execute("DELETE FROM perda_dia WHERE modelo_id=%s AND dia = ANY(%s) AND equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s)",
                    (mod.id, dias, usina.id))
        cur.execute("DELETE FROM evento WHERE usina_id=%s AND modelo_id=%s AND ini >= %s AND ini < %s", (usina.id, mod.id, ini_g, fim_g))
        # 'abaixo dos pares' e sempre recomputado dos ultimos 3 dias: o aberto de ontem sai, o de hoje entra
        cur.execute("DELETE FROM evento WHERE usina_id=%s AND modelo_id=%s AND tipo='inversor_abaixo' AND fim IS NULL", (usina.id, mod.id))
        casc_rows = [(usina.id, dd, mod.id, float(x.e_esperado), float(x.e_medido), float(x.delta), float(x.inv_parado), float(x.tracker),
                      float(x.string), float(x.residuo), float(x.cobertura_gate), int(x.trackers_sem_inversor))
                     for dd, x in casc.por_dia.iterrows() if x.e_esperado > 0]
        if casc_rows:
            psycopg2.extras.execute_values(cur, "INSERT INTO cascata_dia (usina_id, dia, modelo_id, e_esperado, e_medido, delta, inv_parado, "
                                                "tracker, string, residuo, cobertura_gate, trackers_sem_inversor) VALUES %s", casc_rows)
        perda_rows = [(int(x.equipamento_id), x.dia, mod.id, x.parcela, float(x.kwh)) for x in casc.perda_dia.itertuples()]
        if perda_rows:
            psycopg2.extras.execute_values(cur, "INSERT INTO perda_dia (equipamento_id, dia, modelo_id, parcela, kwh) VALUES %s", perda_rows)
        ev_rows = [(usina.id, e.equipamento_id, mod.id, e.tipo, e.ini.to_pydatetime(), e.fim.to_pydatetime() if e.fim is not None else None,
                    e.severidade, float(e.kwh), json.dumps(_json_limpo(e.detalhe), default=str)) for e in evs]
        if ev_rows:
            psycopg2.extras.execute_values(cur, "INSERT INTO evento (usina_id, equipamento_id, modelo_id, tipo, ini, fim, severidade, kwh, detalhe) VALUES %s "
                                                "ON CONFLICT (usina_id, equipamento_id, tipo, ini) DO UPDATE SET fim=EXCLUDED.fim, "
                                                "severidade=EXCLUDED.severidade, kwh=EXCLUDED.kwh, detalhe=EXCLUDED.detalhe, modelo_id=EXCLUDED.modelo_id", ev_rows)
    conn.commit()


def modelar(conn, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime, mod: Modelo | None = None) -> dict:
    t0 = time.time()
    mod = mod or modelo_ativo(conn, usina.id)
    grade = carregar_grade(conn, usina, ini, fim)
    pg = gate_mod.ParamsGate(**(mod.parametros.get("gate") or {}))
    r = gate_mod.avaliar(grade.estacao, referencia_razao(conn, usina.id, fim, usina.tz), pg, usina.tz)
    params = params_por_inversor(grade, mod, p_ac_30d(conn, usina.id, fim))
    esp = esp_mod.esperado_por_inversor(grade, r, params)
    d = dc.decompor(grade, esp, dc.trk_inv_da_grade(grade), dc.ParamsDecomp(), instaladas=instaladas_30d(conn, usina.id, fim))
    evs = ev_mod.detectar(grade, r, esp, d)
    casc = rollup.cascata(grade, r, esp, d)
    persistir(conn, usina, mod, grade, r, esp, evs, casc)
    return {"usina": usina.codigo, "modelo": mod.versao, "dias": int(len(casc.por_dia)), "eventos": len(evs),
            "e_esperado": round(float(casc.por_dia.e_esperado.sum()), 1), "e_medido": round(float(casc.por_dia.e_medido.sum()), 1),
            "inferidos": sum(1 for p in params.values() if p.pac0_inferido), "duracao_s": round(time.time() - t0, 1)}


def rodar_cli(ini: str | None, fim: str | None, usina: str | None) -> int:
    """`gemeo modelar [--ini AAAA-MM-DD] [--fim AAAA-MM-DD] [--usina CODIGO]` — datas em dia LOCAL da usina;
    sem datas, os ultimos 3 dias ate agora. Grava `estado.modelar.ultimo` para o /healthz."""
    from gemeo.core import db
    from gemeo.core.config import carregar
    from gemeo.ingest.runner import usinas_do_piloto
    cfg = carregar(); conn = db.conectar(cfg.db_dsn, cfg.db_schema)
    usinas = usinas_do_piloto(conn, (usina,) if usina else cfg.usinas_piloto)
    if not usinas:
        print("nenhuma usina do piloto no banco — rode `gemeo ingest` (cadastro) primeiro", flush=True)
        return 1
    agora = dt.datetime.now(dt.timezone.utc); t0 = time.time(); resumos = []
    for u in usinas:
        if ini:
            i0 = pd.Timestamp(ini).tz_localize(u.tz).tz_convert("UTC").to_pydatetime()
            f0 = (pd.Timestamp(fim or ini) + pd.Timedelta(days=1)).tz_localize(u.tz).tz_convert("UTC").to_pydatetime()
        else:
            i0, f0 = janela_padrao(agora, u.tz)
        try:
            res = modelar(conn, u, i0, f0)
        except Exception as e:                                   # noqa: BLE001 — uma usina nao derruba as outras
            conn.rollback()
            res = {"usina": u.codigo, "erro": f"{type(e).__name__}: {e}"[:300]}
        resumos.append(res); print(json.dumps(res, ensure_ascii=False), flush=True)
    db.gravar_estado(conn, "modelar.ultimo", json.dumps(_json_limpo({"em": agora.isoformat(), "duracao_s": round(time.time() - t0, 1), "usinas": resumos}),
                                                         ensure_ascii=False, default=str))
    return 0 if all("erro" not in r for r in resumos) else 1
