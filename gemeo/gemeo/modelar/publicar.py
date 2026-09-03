# gemeo/gemeo/modelar/publicar.py
"""Publica o resultado do modelo no workbook `gemeo_digital` da API SQL da Performance, ao fim de cada `gemeo modelar`.
Caminho que grava cabecalho na API (aprendido em 03/09/2026): gerar um xlsx (linha 1 = cabecalho, celula vazia = None,
nunca "") e POST /api/workbooks/{key}/sync-xlsx?replace=true — criar aba/linha pela API deixa tudo como 'Coluna N'.
Nunca derruba o modelar: falha vira `estado.publicar.ultimo` com ok=false e aparece no /healthz."""
from __future__ import annotations
import datetime as dt
import io
import json
import time
from zoneinfo import ZoneInfo

import requests
from openpyxl import Workbook

from gemeo.core import db

ROTULO_EVENTO = {"inversor_parado": "Inversor parado", "inversor_abaixo": "Inversor abaixo dos pares",
                 "tracker_fora_alvo": "Tracker fora do alvo", "string_sem_corrente": "String sem corrente",
                 "sensor_em_falha": "Sensor em falha (POA x GHI)", "sem_cobertura": "Sem cobertura de sensor"}
CABECALHOS = {
    "usina": ["codigo", "fonte", "tz", "kwp_dc", "kw_ac", "n_inversores", "lat", "lon"],
    "equipamento": ["usina", "tipo", "codigo", "pai", "numero", "kwp", "kw_ac"],
    "alias": ["usina", "equipamento", "sistema", "valor", "confianca", "origem"],
    "modelo": ["usina", "versao", "parametros", "tolerancia", "calibrado", "ativo", "calibrado_em", "metrica"],
    "cascata_dia": ["usina", "dia", "modelo", "e_esperado_kwh", "e_medido_kwh", "delta_kwh", "inv_parado_kwh", "tracker_kwh",
                    "string_kwh", "residuo_kwh", "cobertura_gate", "trackers_sem_inversor"],
    "perda_dia": ["usina", "dia", "equipamento", "tipo", "parcela", "kwh", "modelo"],
    "evento": ["usina", "assinatura", "equipamento", "inicio_local", "fim_local", "kwh", "severidade", "detalhe"],
}
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _num(v):
    """Atributos do cadastro chegam como texto do jsonb; numero vira numero, o resto fica como esta."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _celula(v):
    """O parser do sync rejeita texto vazio ('Celula D2 e inlineStr sem elemento <is>'); datas viram texto para
    aparecer igual em qualquer leitor; json e booleano viram texto legivel."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return "sim" if v else "nao"
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return v


def tabelas(conn, dias: int = 90) -> dict[str, list[list]]:
    """As sete tabelas do workbook, lidas do banco; as diarias limitadas aos ultimos `dias` (o replace apaga o resto)."""
    desde = dt.date.today() - dt.timedelta(days=dias)
    desde_ts = dt.datetime.combine(desde, dt.time.min, tzinfo=dt.timezone.utc)
    q: dict[str, list[list]] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT codigo, fonte, tz, kwp_dc, kw_ac, n_inversores, lat, lon FROM usina WHERE ativo ORDER BY codigo")
        q["usina"] = [list(r) for r in cur.fetchall()]
        cur.execute("SELECT u.codigo, e.tipo, coalesce(e.nome_exibicao, e.codigo_fonte), coalesce(p.nome_exibicao, p.codigo_fonte), "
                    "json_extract(e.atributos, '$.numero'), json_extract(e.atributos, '$.kwp'), json_extract(e.atributos, '$.kw_ac') FROM equipamento e JOIN usina u ON u.id=e.usina_id "
                    "LEFT JOIN equipamento p ON p.id=e.pai_id WHERE e.ativo ORDER BY u.codigo, e.tipo, e.codigo_fonte")
        q["equipamento"] = [[r[0], r[1], r[2], r[3], _num(r[4]), _num(r[5]), _num(r[6])] for r in cur.fetchall()]
        cur.execute("SELECT coalesce(u.codigo, u2.codigo), coalesce(e.nome_exibicao, e.codigo_fonte), a.sistema, a.valor, a.confianca, a.origem "
                    "FROM alias a LEFT JOIN equipamento e ON e.id=a.equipamento_id LEFT JOIN usina u ON u.id=e.usina_id "
                    "LEFT JOIN usina u2 ON u2.id=a.usina_id ORDER BY 1, 3, 2")
        q["alias"] = [list(r) for r in cur.fetchall()]
        cur.execute("SELECT u.codigo, m.versao, m.parametros, m.tolerancia, m.calibrado, m.ativo, m.calibrado_em, m.metrica FROM modelo m "
                    "JOIN usina u ON u.id=m.usina_id ORDER BY u.codigo, m.criado_em")
        q["modelo"] = [list(r) for r in cur.fetchall()]
        cur.execute("SELECT u.codigo, c.dia, m.versao, c.e_esperado, c.e_medido, c.delta, c.inv_parado, c.tracker, c.string, c.residuo, "
                    "c.cobertura_gate, c.trackers_sem_inversor FROM cascata_dia c JOIN usina u ON u.id=c.usina_id "
                    "JOIN modelo m ON m.id=c.modelo_id WHERE c.dia >= %s ORDER BY c.dia DESC, u.codigo", (desde,))
        q["cascata_dia"] = [list(r) for r in cur.fetchall()]
        cur.execute("SELECT u.codigo, p.dia, coalesce(e.nome_exibicao, e.codigo_fonte), e.tipo, p.parcela, p.kwh, m.versao FROM perda_dia p "
                    "JOIN equipamento e ON e.id=p.equipamento_id JOIN usina u ON u.id=e.usina_id JOIN modelo m ON m.id=p.modelo_id "
                    "WHERE p.dia >= %s ORDER BY p.dia DESC, u.codigo, p.kwh DESC", (desde,))
        q["perda_dia"] = [list(r) for r in cur.fetchall()]
        cur.execute("SELECT u.codigo, ev.tipo, coalesce(e.nome_exibicao, e.codigo_fonte, 'usina'), ev.ini, ev.fim, "
                    "ev.kwh, ev.severidade, ev.detalhe, u.tz FROM evento ev JOIN usina u ON u.id=ev.usina_id "
                    "LEFT JOIN equipamento e ON e.id=ev.equipamento_id WHERE ev.ini >= %s ORDER BY ev.ini DESC, ev.kwh DESC", (desde_ts,))
        # hora local em Python: SQLite nao tem AT TIME ZONE
        q["evento"] = [[r[0], ROTULO_EVENTO.get(r[1], r[1]), r[2], r[3].astimezone(ZoneInfo(r[8])).replace(tzinfo=None),
                        r[4].astimezone(ZoneInfo(r[8])).replace(tzinfo=None) if r[4] else "aberto", r[5], r[6], r[7]] for r in cur.fetchall()]
    return q


def xlsx_bytes(tabs: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for nome, cab in CABECALHOS.items():
        ws = wb.create_sheet(nome)
        ws.append(cab)
        for lin in tabs.get(nome, []):
            ws.append([_celula(v) for v in lin])
        ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def sincronizar(cfg, conteudo: bytes, sessao=None) -> dict:
    """Garante o workbook (cria se faltar — nao ha DELETE na API, entao so cria uma vez) e sincroniza com
    replace=true. Devolve o JSON da API: {sheets, inserted, updated, deleted}."""
    s = sessao or requests
    base = cfg.bd_api_base.rstrip("/")
    h = {"Authorization": f"Bearer {cfg.bd_api_token}"}
    key = cfg.publicar_workbook
    r = s.get(f"{base}/api/workbooks", headers=h, timeout=60)
    r.raise_for_status()
    if key not in {w.get("key") for w in r.json()}:
        rc = s.post(f"{base}/api/workbooks", headers=h, json={"key": key, "display_name": "Gêmeo Digital"}, timeout=60)
        rc.raise_for_status()
    r = s.post(f"{base}/api/workbooks/{key}/sync-xlsx", headers=h, params={"replace": "true"},
               files={"file": (f"{key}.xlsx", conteudo, MIME_XLSX)}, timeout=300)
    r.raise_for_status()
    return r.json()


def publicar(conn, cfg, agora: dt.datetime | None = None) -> dict:
    """Le, gera, sincroniza e registra em estado.publicar.ultimo. Nunca levanta excecao: o modelar nao pode cair
    por causa da vitrine — a falha fica registrada e o /healthz mostra."""
    agora = agora or dt.datetime.now(dt.timezone.utc)
    t0 = time.time()
    try:
        tabs = tabelas(conn, cfg.publicar_dias)
        res = sincronizar(cfg, xlsx_bytes(tabs))
        out = {"ok": True, "em": agora.isoformat(), "workbook": cfg.publicar_workbook, "linhas": {k: len(v) for k, v in tabs.items()},
               "api": res, "duracao_s": round(time.time() - t0, 1)}
    except Exception as e:                                   # noqa: BLE001 — registra e segue
        try:
            conn.rollback()
        except Exception:                                    # noqa: BLE001
            pass
        out = {"ok": False, "em": agora.isoformat(), "workbook": cfg.publicar_workbook,
               "erro": f"{type(e).__name__}: {e}"[:300], "duracao_s": round(time.time() - t0, 1)}
    try:
        db.gravar_estado(conn, "publicar.ultimo", json.dumps(out, ensure_ascii=False, default=str))
    except Exception:                                        # noqa: BLE001
        pass
    return out
