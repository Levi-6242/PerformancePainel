# gemeo/gemeo/modelar/calibrar.py
"""`gemeo calibrar`: dias limpos -> ajusta perdas_fixas ate a mediana medido/esperado dos inversores saos
ser 1,0 -> versao NOVA de `modelo` com metrica. So vira ativa (e tolerancia 0,03) com >= 30 dias limpos e
desvio < 0,03; antes disso fica gravada, inativa, para inspecao — o modelo de placa continua no ar e o
delta informa sem alarmar."""
from __future__ import annotations
import datetime as dt
import json
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from gemeo.core.modelos import UsinaRef
from gemeo.modelar import esperado as esp_mod
from gemeo.modelar import gate as gate_mod
from gemeo.modelar import job
from gemeo.modelar.grade import Grade, carregar_grade

H = 0.25


@dataclass(frozen=True)
class ParamsCalib:
    cv_max: float = 0.25            # CV da POA entre 10 h e 14 h: acima disso o dia e instavel (22-24/08 de Santarem)
    cobertura_min: float = 0.90
    dias_min_calibrado: int = 30
    desvio_max: float = 0.03
    tolerancia_calibrado: float = 0.03
    tolerancia_placa: float = 0.08
    razao_sao_min: float = 0.5      # inversor com razao abaixo disto no dia esta parado/abaixo: nao calibra ninguem
    iteracoes: int = 4


def cv_poa_dia(poa: pd.Series, tz: str, h_ini: int = 10, h_fim: int = 14) -> dict[dt.date, float]:
    local = poa.index.tz_convert(ZoneInfo(tz))
    meio = poa[(local.hour >= h_ini) & (local.hour < h_fim)]
    dia = pd.Series(meio.index.tz_convert(ZoneInfo(tz)).date, index=meio.index)
    g = meio.groupby(dia)
    cv = g.std() / g.mean().replace(0, np.nan)
    return {d: (float(v) if pd.notna(v) else float("nan")) for d, v in cv.items()}


# Tipos que tornam o MEDIDO nao representativo do dia: o inversor parou, a string zerou, o sensor
# mentiu. Tracker fica de fora desta lista de proposito — ver `dias_limpos`.
TIPOS_GRAVES = ("inversor_parado", "inversor_abaixo", "string_sem_corrente",
                "sensor_em_falha", "sensor_congelado", "sem_cobertura")
FRACAO_TRACKER_MAX = 0.01      # tracker que custou <=1% do esperado do dia nao invalida a calibracao


def dias_limpos(cobertura: dict[dt.date, float], dias_com_evento: set[dt.date], cv: dict[dt.date, float],
                p: ParamsCalib, perda_por_dia: dict[dt.date, dict] | None = None) -> list[dt.date]:
    """Cobertura do gate >= 0,9, POA estavel e nada que torne o medido nao representativo.

    21/09/2026 — o piloto nas tres usinas da 2C devolveu 1, 1 e ZERO dias limpos em 12, 10 e 10 dias
    de cascata. Nao era falta de dado: a regra vetava o dia por QUALQUER evento de equipamento, e na
    2C isso e tracker o tempo todo (`tracker_travado` matou 8 dos 10 dias de Sete Lagoas). E a
    parcela `tracker` da cascata desses MESMOS dias e **zero kWh** nas tres — a regua vetava o dia
    por um evento que ela propria valorou em nada.

    Com `perda_por_dia` o criterio passa a ser auto-validante: veta o que CUSTOU energia, nao o que
    apenas apareceu. Tracker que derrubou geracao de verdade entra na parcela e continua vetando.
    Sem o argumento, mantem o comportamento antigo — para nao mudar em silencio quem chama de fora."""
    def ok(d):
        if cobertura[d] < p.cobertura_min:
            return False
        if d not in cv or pd.isna(cv[d]) or cv[d] >= p.cv_max:
            return False
        if perda_por_dia is None:
            return d not in dias_com_evento
        if d in dias_com_evento:                       # graves vetam sempre
            return False
        parc = perda_por_dia.get(d) or {}
        esp = float(parc.get("esperado") or 0.0)
        trk = float(parc.get("tracker") or 0.0)
        return esp <= 0 or (trk / esp) <= FRACAO_TRACKER_MAX
    return sorted(d for d in cobertura if ok(d))


def razoes_por_dia(grade: Grade, r: gate_mod.Resultado, params: dict[int, esp_mod.ParamsModelo]) -> pd.DataFrame:
    """medido/esperado por (dia local, inversor) nos MESMOS instantes — a mesma regua do rollup."""
    esp = esp_mod.esperado_por_inversor(grade, r, params)
    med = grade.inv_p.reindex(columns=esp.columns)
    ok = esp.notna() & med.notna()
    dia = pd.Series(grade.indice.tz_convert(ZoneInfo(grade.usina.tz)).date, index=grade.indice)
    return ((med.where(ok) * H).groupby(dia).sum(min_count=1)) / ((esp.where(ok) * H).groupby(dia).sum(min_count=1))


def ajustar_perdas(grade: Grade, r: gate_mod.Resultado, params: dict[int, esp_mod.ParamsModelo], dias: list[dt.date], p: ParamsCalib) -> tuple[float, dict]:
    """Itera perdas_fixas ate a mediana das razoes dos saos, nos dias limpos, ser 1,0. O DC do PVWatts e
    linear em (1 - perdas), entao cada passo e quase exato; o clipping AC e o que pede mais de um."""
    if not dias:
        raise ValueError("sem dias limpos para calibrar")
    perdas = next(iter(params.values())).perdas_fixas

    def avalia(perdas_: float) -> pd.Series:
        pr = {e: esp_mod.ParamsModelo(q.kwp, q.pac0_kw, q.gamma, perdas_, q.eta_inv, q.pac0_inferido) for e, q in params.items()}
        raz = razoes_por_dia(grade, r, pr).reindex(dias)
        return raz.where(raz >= p.razao_sao_min).median(axis=1)

    for _ in range(p.iteracoes):
        med_dia = avalia(perdas)
        R = float(np.nanmedian(med_dia.values)) if med_dia.notna().any() else float("nan")
        if not np.isfinite(R) or R <= 0:
            raise ValueError("razoes invalidas nos dias limpos")
        if abs(R - 1.0) < 1e-4:
            break
        # perdas fora de [0, 0,5] nao e calibracao, e sensor ou cadastro errado: trava e a metrica denuncia
        perdas = float(min(0.5, max(0.0, 1.0 - (1.0 - perdas) * R)))
    med_dia = avalia(perdas)
    R = float(np.nanmedian(med_dia.values))
    metrica = {"razao_mediana": round(R, 4), "desvio": round(float(np.nanstd(med_dia.values)), 4),
               "n_dias": int(med_dia.notna().sum()), "dias": [str(d) for d in dias], "perdas_fixas": round(perdas, 4)}
    return perdas, metrica


def calibrar(conn, usina: UsinaRef, dias: int = 45, p: ParamsCalib = ParamsCalib(), agora: dt.datetime | None = None) -> dict:
    agora = agora or dt.datetime.now(dt.timezone.utc)
    tz = ZoneInfo(usina.tz)
    mod = job.modelo_ativo(conn, usina.id)
    ini, fim = job.janela_padrao(agora, usina.tz, dias)
    with conn.cursor() as cur:
        cur.execute("SELECT dia, cobertura_gate, tracker, e_esperado FROM cascata_dia "
                    "WHERE usina_id=%s AND modelo_id=%s AND dia >= %s",
                    (usina.id, mod.id, ini.astimezone(tz).date()))
        cobertura, perda_por_dia = {}, {}
        for d, c, trk, esp in cur.fetchall():
            cobertura[d] = float(c)
            perda_por_dia[d] = {"tracker": float(trk or 0.0), "esperado": float(esp or 0.0)}
        # So os tipos GRAVES vetam o dia por si; tracker e julgado pelo que custou (ver dias_limpos)
        marc = ",".join("%s" for _ in TIPOS_GRAVES)
        cur.execute(f"SELECT ini FROM evento WHERE usina_id=%s AND equipamento_id IS NOT NULL "
                    f"AND ini >= %s AND tipo IN ({marc})", (usina.id, ini, *TIPOS_GRAVES))
        com_evento = {r[0].astimezone(tz).date() for r in cur.fetchall()}     # fuso em Python: SQLite nao tem AT TIME ZONE
    grade = carregar_grade(conn, usina, ini, fim)
    r = gate_mod.avaliar(grade.estacao, job.referencia_razao(conn, usina.id, fim, usina.tz),
                         gate_mod.ParamsGate(**(mod.parametros.get("gate") or {})), usina.tz)
    limpos = dias_limpos(cobertura, com_evento, cv_poa_dia(grade.estacao["poa"], usina.tz), p,
                         perda_por_dia=perda_por_dia)
    if not limpos:
        return {"usina": usina.codigo, "erro": "sem dias limpos", "dias_cascata": len(cobertura), "com_evento": len(com_evento)}
    params = job.params_por_inversor(grade, mod, job.p_ac_30d(conn, usina.id, fim))
    perdas, metrica = ajustar_perdas(grade, r, params, limpos, p)
    calibrado = metrica["n_dias"] >= p.dias_min_calibrado and metrica["desvio"] < p.desvio_max
    versao = f"cal-{agora.astimezone(tz).date()}"
    parametros = {**mod.parametros, "perdas_fixas": perdas, "base": mod.versao}
    with conn.cursor() as cur:
        if calibrado:
            cur.execute("UPDATE modelo SET ativo=false WHERE usina_id=%s AND ativo", (usina.id,))
        cur.execute("INSERT INTO modelo (usina_id, versao, parametros, tolerancia, calibrado, calibrado_em, metrica, ativo) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (usina_id, versao) DO UPDATE SET parametros=EXCLUDED.parametros, "
                    "tolerancia=EXCLUDED.tolerancia, calibrado=EXCLUDED.calibrado, calibrado_em=EXCLUDED.calibrado_em, "
                    "metrica=EXCLUDED.metrica, ativo=EXCLUDED.ativo RETURNING id",
                    (usina.id, versao, json.dumps(parametros), p.tolerancia_calibrado if calibrado else p.tolerancia_placa,
                     calibrado, agora if calibrado else None, json.dumps(metrica), calibrado))
        mid = cur.fetchone()[0]
    conn.commit()
    return {"usina": usina.codigo, "versao": versao, "modelo_id": int(mid), "calibrado": calibrado, "ativo": calibrado, **metrica}


def rodar_cli(usina: str, dias: int) -> int:
    from gemeo.core import db
    from gemeo.core.config import carregar
    from gemeo.ingest.runner import usinas_do_piloto
    cfg = carregar(); conn = db.conectar(cfg.db_caminho)
    usinas = usinas_do_piloto(conn, (usina,))
    if not usinas:
        print(f"usina {usina!r} nao esta no banco", flush=True)
        return 1
    res = calibrar(conn, usinas[0], dias)
    print(json.dumps(res, ensure_ascii=False, default=str), flush=True)
    return 0 if "erro" not in res else 1
