"""PR e IPOA da API PV — _ipoa_from_meteo (integração trapezoidal) e _pv_pr_compute.

_ipoa_from_meteo é puro. _pv_pr_compute busca o meteo por _http(); o teste injeta um
_http() falso (sem rede) que devolve uma curva controlada, para validar a fórmula
PR = geração / (IPOA × potência), a mediana e a classificação severo/leve/ok.
"""
import app


def _rec(hora, poa):
    """Registro de meteo no formato day_meteo: conteudojson + tsleitura_new."""
    cj = {} if poa is None else {"Ir": poa}
    return {"conteudojson": cj, "tsleitura_new": f"2026-06-14 {hora}:00"}


class _FakeHTTP:
    """Sessão falsa: .post()/.get() devolvem sempre o mesmo .json()."""
    def __init__(self, data):
        self._data = data

    def _resp(self):
        data = self._data

        class _R:
            def json(self_inner):
                return data
        return _R()

    def post(self, *a, **k):
        return self._resp()

    def get(self, *a, **k):
        return self._resp()


# ── _ipoa_from_meteo: integração trapezoidal ──────────────────────────────────

def test_ipoa_curva_constante():
    # 800 W/m² constante das 12:00 às 13:00 em passos de 15 min:
    # 4 intervalos × 800 × 0,25 h = 800 Wh/m² = 0,8 kWh/m².
    meteo = [_rec("12:00", 800), _rec("12:15", 800), _rec("12:30", 800),
             _rec("12:45", 800), _rec("13:00", 800)]
    assert app._ipoa_from_meteo(meteo) == 0.8


def test_ipoa_descarta_gap():
    # Um ponto isolado 2 h depois cria um intervalo > 30 min, que é descartado:
    # o IPOA não muda em relação à curva contínua.
    meteo = [_rec("12:00", 800), _rec("12:15", 800), _rec("12:30", 800),
             _rec("12:45", 800), _rec("13:00", 800), _rec("15:00", 800)]
    assert app._ipoa_from_meteo(meteo) == 0.8


def test_ipoa_clampa_negativos():
    # Valor negativo (sensor com erro) vira 0 antes de integrar:
    # (800+0)/2×0,25 + (0+800)/2×0,25 = 200 Wh/m² = 0,2 kWh/m².
    meteo = [_rec("12:00", 800), _rec("12:15", -100), _rec("12:30", 800)]
    assert app._ipoa_from_meteo(meteo) == 0.2


def test_ipoa_ignora_pontos_invalidos():
    # POA ausente e ts vazio são pulados; sobra a curva válida.
    meteo = [_rec("12:00", 800), _rec("12:15", None),
             {"conteudojson": {"Ir": 800}, "tsleitura_new": ""},
             _rec("12:15", 800), _rec("12:30", 800), _rec("12:45", 800),
             _rec("13:00", 800)]
    assert app._ipoa_from_meteo(meteo) == 0.8


def test_ipoa_sem_pontos():
    assert app._ipoa_from_meteo([]) is None
    assert app._ipoa_from_meteo([_rec("12:00", None)]) is None


# ── _pv_pr_compute: PR = geração / (IPOA × potência) ──────────────────────────

def test_pv_pr_compute_formula_mediana_e_status(monkeypatch):
    meteo = [_rec("12:00", 800), _rec("12:15", 800), _rec("12:30", 800),
             _rec("12:45", 800), _rec("13:00", 800)]                   # IPOA = 0,8
    monkeypatch.setattr(app, "_http", lambda: _FakeHTTP(meteo))

    raw = {
        "plant_id": 1,
        "ts_max": "2026-06-14 13:00:00",
        "inversores": [
            {"id": "INV01", "eday": 560.0, "pot_kwp": 1000.0},  # PR 0,70
            {"id": "INV02", "eday": 552.0, "pot_kwp": 1000.0},  # PR 0,69 (mediana)
            {"id": "INV03", "eday": 480.0, "pot_kwp": 1000.0},  # PR 0,60 -> severo
        ],
    }
    res = app._pv_pr_compute(raw, token="tok")

    assert res["ipoa"] == 0.8
    prs = [i["pr"] for i in res["inversores"]]
    assert prs == [0.7, 0.69, 0.6]
    assert res["pr_mediana"] == 0.69

    status = {i["id"]: i["status"] for i in res["inversores"]}
    assert status == {"INV01": "ok", "INV02": "ok", "INV03": "severo"}
    assert res["abaixo"] == 1
    assert res["sem_pot"] == 0

    # PR da usina = geração total / (IPOA × potência total)
    # 1592 / (0,8 × 3000) = 0,6633...
    assert res["geracao_kwh"] == 1592.0
    assert res["pot_kwp"] == 3000.0
    assert res["pr"] == 0.663


def test_pv_pr_compute_sem_ipoa_status_sem_dados(monkeypatch):
    # Sem meteo -> IPOA None -> PR None por inversor -> status "sem_dados".
    monkeypatch.setattr(app, "_http", lambda: _FakeHTTP([]))
    raw = {
        "plant_id": 2,
        "ts_max": None,
        "inversores": [{"id": "INV01", "eday": 500.0, "pot_kwp": 1000.0}],
    }
    res = app._pv_pr_compute(raw, token="tok")
    assert res["ipoa"] is None
    assert res["inversores"][0]["pr"] is None
    assert res["inversores"][0]["status"] == "sem_dados"
    assert res["pr"] is None


def test_pv_pr_compute_conta_sem_pot(monkeypatch):
    meteo = [_rec("12:00", 800), _rec("12:15", 800), _rec("12:30", 800),
             _rec("12:45", 800), _rec("13:00", 800)]
    monkeypatch.setattr(app, "_http", lambda: _FakeHTTP(meteo))
    raw = {
        "plant_id": 3,
        "ts_max": "2026-06-14 13:00:00",
        "inversores": [
            {"id": "INV01", "eday": 560.0, "pot_kwp": 1000.0},  # PR 0,70
            {"id": "INV02", "eday": 560.0, "pot_kwp": None},    # sem potência
        ],
    }
    res = app._pv_pr_compute(raw, token="tok")
    assert res["sem_pot"] == 1
    assert res["inversores"][1]["pr"] is None
    assert res["inversores"][1]["status"] == "sem_dados"
