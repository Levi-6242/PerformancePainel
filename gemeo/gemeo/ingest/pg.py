# gemeo/gemeo/ingest/pg.py
"""Fonte PostgreSQL `powerplants` (Thopen): raw_weather_station, raw_inverter, raw_tracker.
So leitura. Timestamps ja sao timestamptz (UTC) — nenhuma conversao na gravacao."""
from __future__ import annotations
import datetime as dt
import re

from gemeo.core.modelos import UsinaRef
from gemeo.ingest.base import Busca, Ingestor

MEDIDAS = {
    "raw_weather_station": {"irradiance_poa": "poa", "irradiance_ghi": "ghi", "module_temperature": "temp_modulo",
                            "air_temperature": "temp_ar", "wind_speed": "vento"},
    "raw_inverter": {"active_power": "p_ac", "daily_active_energy": "e_dia", "state_simplified": "estado"},
    "raw_tracker": {"posat": "angulo", "posal": "angulo_alvo"},
}
TIPO = {"raw_weather_station": "estacao", "raw_inverter": "inversor", "raw_tracker": "tracker"}
_STR = re.compile(r"^string_(\d+)_current$")


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def linhas_de(json_data: dict, tabela: str, device_id: str, ts: dt.datetime, mapa_eq: dict) -> list[tuple]:
    """(equipamento_id, medida, ts, valor) para um registro cru. Valor nao numerico e descartado."""
    out = []
    eid = mapa_eq.get((TIPO[tabela], str(device_id)))
    if eid is not None:
        for chave, medida in MEDIDAS[tabela].items():
            v = _num(json_data.get(chave))
            if v is not None:
                out.append((eid, medida, ts, v))
    if tabela == "raw_inverter":
        for chave, val in json_data.items():
            m = _STR.match(chave)
            if not m:
                continue
            sid = mapa_eq.get(("string", f"{device_id}.string_{m.group(1)}"))
            v = _num(val)
            if sid is not None and v is not None:
                out.append((sid, "i_string", ts, v))
    return out


class IngestorPG(Ingestor):
    fonte = "pg"

    def __init__(self, cfg, conn, usinas: list[UsinaRef], conn_fonte):
        super().__init__(cfg, conn, usinas)
        self.fonte_conn = conn_fonte

    def _mapa(self, usina: UsinaRef) -> dict:
        with self.conn.cursor() as cur:
            cur.execute("SELECT tipo, codigo_fonte, id FROM equipamento WHERE usina_id=%s AND ativo", (usina.id,))
            return {(t, c): i for t, c, i in cur.fetchall()}

    def descobrir(self, usina: UsinaRef) -> None:
        """Equipamento novo na fonte vira linha em `equipamento` com atributos.numero; o cadastro
        enriquece depois. Strings nascem das chaves string_N_current do ultimo registro do inversor."""
        pid = int(usina.fonte_ref)
        with self.fonte_conn.cursor() as src, self.conn.cursor() as cur:
            for tabela, tipo in TIPO.items():
                src.execute(f"SELECT DISTINCT device_id FROM public.{tabela} WHERE power_plant_id=%s AND timestamp >= now() - interval '7 days'", (pid,))
                for (dev,) in src.fetchall():
                    cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, atributos) VALUES (%s,%s,%s,%s) "
                                "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING RETURNING id",
                                (usina.id, tipo, str(dev), '{"numero": %d}' % int(dev)))
                    if tabela != "raw_inverter":
                        continue
                    src.execute("SELECT json_data FROM public.raw_inverter WHERE power_plant_id=%s AND device_id=%s ORDER BY timestamp DESC LIMIT 1", (pid, dev))
                    r = src.fetchone()
                    cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte=%s", (usina.id, str(dev)))
                    inv_id = cur.fetchone()[0]
                    for chave in (r[0] if r else {}):
                        m = _STR.match(chave)
                        if m:
                            cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, pai_id, atributos) VALUES (%s,'string',%s,%s,%s) "
                                        "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING",
                                        (usina.id, f"{dev}.string_{m.group(1)}", inv_id, '{"numero": %d}' % int(m.group(1))))
        self.conn.commit()

    def buscar(self, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime) -> Busca:
        mapa = self._mapa(usina)
        pid = int(usina.fonte_ref)
        leituras: list[tuple] = []
        with self.fonte_conn.cursor() as src:
            for tabela in MEDIDAS:
                src.execute(f"SELECT timestamp, device_id, json_data FROM public.{tabela} "
                            "WHERE power_plant_id=%s AND timestamp > %s AND timestamp <= %s", (pid, ini, fim))
                for ts, dev, jd in src.fetchall():
                    leituras.extend(linhas_de(jd or {}, tabela, str(dev), ts, mapa))
        n_series = len(mapa)
        esperadas = int(n_series * max(1, (fim - ini).total_seconds() / 300))   # 5 min por serie
        return Busca(leituras=leituras, n_requisicoes=len(MEDIDAS), esperadas=esperadas)
