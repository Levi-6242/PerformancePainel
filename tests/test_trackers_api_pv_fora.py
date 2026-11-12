# -*- coding: utf-8 -*-
"""A usina cuja leitura de tracker a API PV não devolveu continua na aba com a última linha boa (12/11/2026).

Levi: "Acho que a API da PV tá estranha (não tá localizando os trackers de coração e tinha bugado tracker SEMP)". A API PV
respondia em 10 a 60 s por pedido; a leitura falhava e a montagem DESCARTAVA a usina (o `except: pass`): a aba ficou com
10 usinas, sem a Coração 1 e 2. Agora a falha (fonte_ok=False ou exceção) mantém a linha anterior, com a hora real dela e
`api_fora`; a usina que respondeu sem tracker segue fora; e a mantida não entra no livro de ocorrências.
"""
import app


def _plantas():
    return [{"id": 1, "nome": "Coração 1"}, {"id": 2, "nome": "Tanabi 2"}, {"id": 3, "nome": "Sem tracker"},
            {"id": 4, "nome": "Caiu de vez"}]


def _analise(idusina, nome, **kw):
    base = {"plant_id": idusina, "usina": nome, "total": 0, "severos": 0, "leves": 0, "trackers": [], "tem_trackers": False}
    if idusina == 1:
        return dict(base, fonte_ok=False, erro="API PV: ReadTimeout")
    if idusina == 2:
        return dict(base, total=70, parados=4, tem_trackers=True, ultima_leitura="2026-11-12 14:22:00")
    if idusina == 4:
        raise TimeoutError("sem resposta")
    return base                                         # respondeu: não tem tracker


def test_a_falha_da_api_mantem_a_linha_anterior(monkeypatch):
    monkeypatch.setattr(app, "get_plants", lambda tok, force=False: _plantas())
    monkeypatch.setattr(app, "get_token", lambda: "x")
    monkeypatch.setattr(app, "_pv_monitorada", lambda p: True)
    monkeypatch.setattr(app, "_pv_trk_fora", lambda pid: False)
    monkeypatch.setattr(app, "_pv_trackers_analise", _analise)
    monkeypatch.setattr(app, "_TRACKER_WATCH_OK", True)
    sincronizados = []
    monkeypatch.setattr(app._tw, "sync_api_pv", lambda parados, plants_cobertas: sincronizados.append(set(plants_cobertas)),
                        raising=False)
    monkeypatch.setattr(app, "_trk_eventos_disp_by_id", lambda *a, **k: {}, raising=False)
    anterior = {"rows": [{"plant_id": 1, "usina": "Coração 1", "total": 23, "parados": 1, "severos": 1, "leves": 0,
                          "ultima_leitura": "2026-11-12 11:40:00"},
                         {"plant_id": 3, "usina": "Sem tracker", "total": 5, "parados": 0, "severos": 0, "leves": 0,
                          "ultima_leitura": "2026-11-11 10:00:00"},
                         {"plant_id": 4, "usina": "Caiu de vez", "total": 9, "parados": 0, "severos": 0, "leves": 0,
                          "ultima_leitura": "2026-11-12 12:00:00"}]}
    monkeypatch.setitem(app._pv_trk_cache, "payload", anterior)
    rows = {r["plant_id"]: r for r in app._build_pv_trk_payload()["rows"]}
    assert rows[1]["api_fora"] and rows[1]["ultima_leitura"] == "2026-11-12 11:40:00" and rows[1]["total"] == 23
    assert "ReadTimeout" in rows[1]["erro"]
    assert rows[4]["api_fora"] and "TimeoutError" in rows[4]["erro"]       # a exceção também mantém
    assert 3 not in rows                                                   # respondeu sem tracker: fora, como antes
    assert not rows[2].get("api_fora") and rows[2]["total"] == 70
    assert all(1 not in c and 4 not in c for c in sincronizados)          # a mantida não mexe nas ocorrências
