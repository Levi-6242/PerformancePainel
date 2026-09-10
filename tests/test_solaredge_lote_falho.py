# -*- coding: utf-8 -*-
"""Lote que falhou NÃO é string zerada — a lição de 31/07 do SunOp, que faltava no SolarEdge.

Achado crítico da varredura de 09/09/2026 (3 céticos, 3 a favor): `se_string_power` lê as strings em
lotes de 50 e, quando um lote falha (não-200 ou exceção), simplesmente segue (`continue`). Os uuids
daquele lote somem do mapa — e quem consome conta `power.get(u) is not None` como prova de vida. Uma
falha de rede vira "string inativa" para 50 strings de uma vez, com `sem_dados=False` jurando que a
leitura está boa.

O irmão SunOp já tinha o conserto, com o incidente escrito no comentário: "LOTE FALHO = FOTO
INCOMPLETA... a usina aparecia com temperatura e energia normais e '0 de 248 strings ativas' — 248
alarmes falsos". Aqui é a mesma régua: pathname que não voltou é DESCONHECIDO, não é zero.
"""
import app


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._p = payload or {}

    def json(self):
        return self._p


def _devs(n=60):
    """n strings (mais de um lote de 50) + 1 inversor."""
    return ([{"deviceType": "STRING", "deviceSerial": f"S{i}", "deviceName": f"String 1.{i}"}
             for i in range(n)]
            + [{"deviceType": "INVERTER", "deviceSerial": "INV1", "deviceName": "Inverter 1"}])


def _http_falso(monkeypatch, respostas):
    """respostas: lista de _Resp, uma por lote, na ordem."""
    fila = list(respostas)

    class _H:
        def post(self, *a, **k):
            return fila.pop(0) if fila else _Resp(500)

    monkeypatch.setattr(app, "_http", lambda: _H())
    monkeypatch.setattr(app, "_se_headers", lambda: {})


def _ok(uuids):
    """Resposta boa: todas as strings do lote com potência acima do mínimo."""
    return _Resp(200, {"meta": {"datasetsMeta": [{"reportObject": {"entityId": u}} for u in uuids]},
                       # row = [ts, energia_Wh, potencia_W] — o ts vem ISO (string), como na API real
                       "data": [[["2026-09-09T12:00:00Z", 10.0, 500.0]] for _ in uuids]})


def test_lote_que_falha_nao_vira_string_inativa(monkeypatch):
    """Lote 1 responde, lote 2 cai: a usina inteira vira SEM DADOS, não 10 strings mortas."""
    monkeypatch.setattr(app, "se_devices", lambda sid: _devs(60))
    _http_falso(monkeypatch, [_ok([f"S{i}" for i in range(50)]), _Resp(500)])
    r = app.process_site_solaredge({"id": 1, "nome": "Usina SE", "inv": 1, "timezone": "America/Sao_Paulo"})
    assert r["sem_dados"] is True, "meia leitura virou número: 10 strings falsas mortas"
    assert r["strings_ativas"] is None and r["diferenca"] is None


def test_leitura_completa_continua_contando(monkeypatch):
    """Régua intacta no caminho feliz: os dois lotes voltam e a usina conta normalmente."""
    monkeypatch.setattr(app, "se_devices", lambda sid: _devs(60))
    _http_falso(monkeypatch, [_ok([f"S{i}" for i in range(50)]), _ok([f"S{i}" for i in range(50, 60)])])
    r = app.process_site_solaredge({"id": 1, "nome": "Usina SE", "inv": 1, "timezone": "America/Sao_Paulo"})
    assert r["sem_dados"] is False and r["strings_ativas"] == 60


def test_se_string_power_devolve_quantos_lotes_falharam(monkeypatch):
    """O contador é o que permite ao consumidor decidir — sem ele, o silêncio volta."""
    _http_falso(monkeypatch, [_ok([f"S{i}" for i in range(50)]), _Resp(500)])
    power, _ts, falhos = app.se_string_power(1, [f"S{i}" for i in range(60)], "America/Sao_Paulo")
    assert falhos == 1 and len(power) == 50
