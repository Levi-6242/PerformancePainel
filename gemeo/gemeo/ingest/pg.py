# gemeo/gemeo/ingest/pg.py
"""Fonte PostgreSQL `powerplants` (Thopen): raw_weather_station, raw_inverter, raw_tracker.
So leitura. Timestamps ja sao timestamptz (UTC) — nenhuma conversao na gravacao."""
from __future__ import annotations
import datetime as dt
import re

from gemeo.core.modelos import UsinaRef
from gemeo.ingest.base import Busca, Ingestor, valor_valido

MEDIDAS = {
    "raw_weather_station": {"irradiance_poa": "poa", "irradiance_ghi": "ghi", "module_temperature": "temp_modulo",
                            "air_temperature": "temp_ar", "wind_speed": "vento"},
    "raw_inverter": {"active_power": "p_ac", "daily_active_energy": "e_dia", "state_simplified": "estado"},
    "raw_tracker": {"posat": "angulo", "posal": "angulo_alvo"},
}
TIPO = {"raw_weather_station": "estacao", "raw_inverter": "inversor", "raw_tracker": "tracker"}
_STR = re.compile(r"^string_(\d+)_current$")
# Medidas que NAO precisam da cadencia de 5 min da fonte: o modelo pergunta a elas se o tracker esta no alvo e se a
# string esta zerada, e uma amostra por bloco de 15 min (a mesma grade do modelo) responde as duas. Guardar tudo
# custaria 17 GB em 90 dias com as 18 usinas do Thopen, e 72% seriam corrente de string (medido em 04/09/2026).
# Potencia do inversor e a estacao continuam na cadencia da fonte: sao a fisica, e a media do bloco fica melhor.
GROSSAS = ("angulo", "angulo_alvo", "i_string")
BLOCO_MIN = 15


def _bloco(ts: dt.datetime) -> dt.datetime:
    return ts.replace(minute=(ts.minute // BLOCO_MIN) * BLOCO_MIN, second=0, microsecond=0)


def _repetida(vistos: set | None, eid: int, medida: str, ts: dt.datetime) -> bool:
    """True quando a medida e GROSSA e o bloco de 15 min dela ja foi gravado nesta busca."""
    if vistos is None or medida not in GROSSAS:
        return False
    chave = (eid, medida, _bloco(ts))
    if chave in vistos:
        return True
    vistos.add(chave)
    return False


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def linhas_de(json_data: dict, tabela: str, device_id: str, ts: dt.datetime, mapa_eq: dict, vistos: set | None = None) -> list[tuple]:
    """(equipamento_id, medida, ts, valor) para um registro cru. Valor nao numerico e descartado.
    `vistos` (opcional) carrega os blocos de 15 min ja gravados das medidas GROSSAS, para ficar so a primeira
    amostra de cada bloco. Sem ele, nada e descartado — e o que os testes de contrato usam."""
    out = []
    eid = mapa_eq.get((TIPO[tabela], str(device_id)))
    if eid is not None:
        for chave, medida in MEDIDAS[tabela].items():
            v = _num(json_data.get(chave))
            if valor_valido(medida, v) and not _repetida(vistos, eid, medida, ts):
                out.append((eid, medida, ts, v))
    if tabela == "raw_inverter":
        for chave, val in json_data.items():
            m = _STR.match(chave)
            if not m:
                continue
            sid = mapa_eq.get(("string", f"{device_id}.string_{m.group(1)}"))
            v = _num(val)
            if sid is not None and v is not None and not _repetida(vistos, sid, "i_string", ts):
                out.append((sid, "i_string", ts, v))
    return out


class IngestorPG(Ingestor):
    fonte = "pg"

    def __init__(self, cfg, conn, usinas: list[UsinaRef], conn_fonte):
        super().__init__(cfg, conn, usinas)
        # `conn_fonte` é uma FÁBRICA de conexão (o `rodar`) ou a conexão já aberta (testes) — ver `fonte_conn`
        self._fabrica_fonte = conn_fonte if callable(conn_fonte) else None
        self._fonte = None if self._fabrica_fonte else conn_fonte

    @property
    def fonte_conn(self):
        """A conexão com o PostgreSQL do Thopen, viva. De 27/09 13:50 UTC até 28/09 a coleta das 18 usinas do banco
        morreu em `connection already closed`: a conexão nascia uma vez na partida, nunca fechava a transação (a
        sessão ficava "ociosa em transação" por dias, segurando a limpeza do banco do Thopen) e, quando o servidor a
        derrubou, ninguém abriu outra. Agora abre quando precisa, em autocommit — é só leitura, nenhuma transação
        atravessa um ciclo — e reabre se estiver fechada (`closed` 1 = fechada, 2 = quebrou no meio de uma consulta)."""
        c = self._fonte
        if self._fabrica_fonte is not None and (c is None or getattr(c, "closed", 0)):
            c = self._fabrica_fonte()
            c.autocommit = True
            self._fonte = c
        return c

    @fonte_conn.setter
    def fonte_conn(self, c):
        self._fonte = c

    def _mapa(self, usina: UsinaRef) -> dict:
        with self.conn.cursor() as cur:
            cur.execute("SELECT tipo, codigo_fonte, id FROM equipamento WHERE usina_id=%s AND ativo", (usina.id,))
            return {(t, c): i for t, c, i in cur.fetchall()}

    def _cadastro_da_usina(self, usina: UsinaRef) -> None:
        """placa e coordenadas de tb_power_plants. As usinas do Thopen nao estao na aba Info Geral do BD_Performance
        (de onde as da SunOp tiram o kWp), mas o proprio PostgreSQL tem `capacity` e lat/lon — e sem kWp o modelo nao
        tem esperado nenhum, sem lat/lon a posicao do sol sai errada. So preenche o que ainda esta vazio: o cadastro
        do time de Performance, quando existir, continua mandando."""
        with self.fonte_conn.cursor() as src:
            src.execute("SELECT capacity, location_lat, location_long FROM public.tb_power_plants WHERE id=%s", (int(usina.fonte_ref),))
            r = src.fetchone()
        if not r:
            return
        kwp, lat, lon = (float(x) if x is not None else None for x in r)

        def _grava():
            with self.conn.cursor() as cur:
                cur.execute("UPDATE usina SET kwp_dc=coalesce(kwp_dc, %s), lat=coalesce(lat, %s), lon=coalesce(lon, %s) WHERE id=%s",
                            (kwp, lat, lon, usina.id))
            self.conn.commit()
        self._db.com_retentativa_de_lock(self.conn, _grava)

    def descobrir(self, usina: UsinaRef) -> None:
        """Equipamento novo na fonte vira linha em `equipamento` com atributos.numero; o cadastro
        enriquece depois. Strings nascem das chaves string_N_current do ultimo registro do inversor.

        O Postgres responde TUDO antes do primeiro INSERT. Ate 29/09/2026 o INSERT do primeiro equipamento abria a
        escrita do SQLite (transacao implicita do sqlite3) e o laco seguia consultando o Postgres ate o commit do fim;
        com o banco do Thopen lento, a sessao do gemeo passou 21+ min em `SELECT DISTINCT device_id FROM public.raw_tracker`
        segurando o arquivo, e sunop, apipv, plat, cadastro e modelar morreram em 'database is locked' (251 no log)."""
        self._cadastro_da_usina(usina)
        pid = int(usina.fonte_ref)
        devs: dict[str, list] = {}
        ultimo: dict = {}                       # device_id do inversor -> json_data do ultimo registro dele
        with self.fonte_conn.cursor() as src:
            for tabela in TIPO:
                src.execute(f"SELECT DISTINCT device_id FROM public.{tabela} WHERE power_plant_id=%s AND timestamp >= now() - interval '7 days'", (pid,))
                devs[tabela] = [dev for (dev,) in src.fetchall()]
            for dev in devs["raw_inverter"]:
                src.execute("SELECT json_data FROM public.raw_inverter WHERE power_plant_id=%s AND device_id=%s ORDER BY timestamp DESC LIMIT 1", (pid, dev))
                r = src.fetchone()
                ultimo[dev] = r[0] if r else {}

        def _grava():
            with self.conn.cursor() as cur:
                for tabela, tipo in TIPO.items():
                    for dev in devs[tabela]:
                        cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, atributos) VALUES (%s,%s,%s,%s) "
                                    "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING RETURNING id",
                                    (usina.id, tipo, str(dev), '{"numero": %d}' % int(dev)))
                        if tabela != "raw_inverter":
                            continue
                        cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte=%s", (usina.id, str(dev)))
                        inv_id = cur.fetchone()[0]
                        for chave in ultimo[dev]:
                            m = _STR.match(chave)
                            if m:
                                cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, pai_id, atributos) VALUES (%s,'string',%s,%s,%s) "
                                            "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING",
                                            (usina.id, f"{dev}.string_{m.group(1)}", inv_id, '{"numero": %d}' % int(m.group(1))))
            self.conn.commit()
        # a retentativa refaz so o SQLite: voltar ao Postgres custaria outros 20 min num dia como o 29/09
        self._db.com_retentativa_de_lock(self.conn, _grava)
        self._nomes_legiveis(usina, [int(dev) for tabela in TIPO for dev in devs[tabela]])

    def _nomes_legiveis(self, usina: UsinaRef, devs: list[int]) -> None:
        """tb_devices.device_name ('Inversor 1.1') vira nome_exibicao. Sem isto o gemeo mostrava os inversores do Thopen
        como 83, 84... (Santo Inacio XII, 06/09) e o Raio-X do /painel nao conseguia casar com a plataforma pelo nome.
        So preenche o que esta vazio e nunca derruba a descoberta: falha aqui e aviso, nao erro."""
        if not devs:
            return
        try:
            with self.fonte_conn.cursor() as src:
                src.execute("SELECT id, device_name FROM public.tb_devices WHERE id = ANY(%s)", (devs,))
                nomes = [(str(nome).strip(), str(dev)) for dev, nome in src.fetchall() if nome and str(nome).strip()]

            def _grava():
                with self.conn.cursor() as cur:
                    for nome, dev in nomes:
                        cur.execute("UPDATE equipamento SET nome_exibicao=%s WHERE usina_id=%s AND codigo_fonte=%s "
                                    "AND (nome_exibicao IS NULL OR nome_exibicao='')", (nome, usina.id, dev))
                self.conn.commit()
            self._db.com_retentativa_de_lock(self.conn, _grava)
        except Exception as e:                                   # noqa: BLE001 — nome bonito nao pode parar o ingest
            self.conn.rollback()
            print(f"[pg] nomes de equipamento nao vieram ({e}); sigo com codigo_fonte")

    def buscar(self, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime) -> Busca:
        mapa = self._mapa(usina)
        pid = int(usina.fonte_ref)
        leituras: list[tuple] = []
        vistos: set = set()
        with self.fonte_conn.cursor() as src:
            for tabela in MEDIDAS:
                src.execute(f"SELECT timestamp, device_id, json_data FROM public.{tabela} "
                            "WHERE power_plant_id=%s AND timestamp > %s AND timestamp <= %s ORDER BY timestamp", (pid, ini, fim))
                for ts, dev, jd in src.fetchall():
                    leituras.extend(linhas_de(jd or {}, tabela, str(dev), ts, mapa, vistos))
        # `esperadas` saiu em 21/09/2026: supunha 5 min por serie, de madrugada inclusive, e punha
        # 480 de 480 ciclos em "parcial" com a fonte sa. Quem decide o status agora e o frescor.
        return Busca(leituras=leituras, n_requisicoes=len(MEDIDAS))
