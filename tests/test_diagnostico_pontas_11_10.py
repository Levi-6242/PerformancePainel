# -*- coding: utf-8 -*-
"""As três pontas que a prova do Diagnóstico com a fonte fora achou (11/10/2026).

1. A faixa de aviso (aviso_de_sessao.js) ficava no TOPO: com cinco fontes fora tinha 77 px e cobria o seletor de dia e o
   "← Portfólio" — não dava para trocar o dia. Agora fica embaixo, com "×" para fechar (o mesmo aviso não volta sozinho).
2. "PR mediana −0%" às 03:00: a estação lia ruído de irradiância e o PR do PG saía −0.0. Sem sol, não há PR.
3. /api/pv/pr/<id> com a autenticação da API PV fora devolvia 500 em HTML (o get_token fora do try), e a lista de
   usinas que falhava virava 404 "usina não encontrada". Os dois são "a fonte não respondeu": 502 com erro/fonte.
"""
import app
from test_sessao_vencida_sem_numero_falso import _aviso


# ── 1. a faixa embaixo, com o "×" ──────────────────────────────────────────────────────────────────────────────────
_ROTEIRO = """
  const S = window.gcSessaoDaPlataforma;
  S.falhou("API PV, Fracttal", "", "o que depende dessas leituras está com —.");
  const f = criados.find(e => e.id === "gc-sessao-faixa");
  const css = f.style.cssText, html = f.innerHTML, antes = f.hidden;
  f.onclick({ target: { getAttribute: k => (k === "data-fechar" ? "" : null) } });
  const fechou = f.hidden;
  S.falhou("API PV, Fracttal", "", "o que depende dessas leituras está com —.");
  const mesmoTextoSegueFechado = f.hidden;
  S.falhou("API PV", "", "o que depende dessas leituras está com —.");
  const outroTextoVolta = !f.hidden;
  f.onclick({ target: { getAttribute: k => null } });
  const cliqueForaDoXNaoFecha = !f.hidden;
  out({ css, html, antes, fechou, mesmoTextoSegueFechado, outroTextoVolta, cliqueForaDoXNaoFecha });
"""


def test_a_faixa_fica_embaixo_e_nao_cobre_o_seletor_de_dia(tmp_path):
    r = _aviso({}, _ROTEIRO, tmp_path)
    assert "bottom:12px" in r["css"] and "top:" not in r["css"], r["css"]
    assert 'data-fechar' in r["html"] and "Fechar o aviso" in r["html"]
    assert r["antes"] is False


def test_o_x_fecha_e_o_mesmo_aviso_nao_volta_sozinho_mas_outro_volta(tmp_path):
    r = _aviso({}, _ROTEIRO, tmp_path)
    assert r["fechou"] and r["mesmoTextoSegueFechado"]
    assert r["outroTextoVolta"], "um aviso diferente (outra fonte) tem de aparecer"
    assert r["cliqueForaDoXNaoFecha"]


def test_a_faixa_do_diagnostico_cita_so_as_fontes():
    import pathlib
    html = (pathlib.Path(app.__file__).parent / "templates" / "painel_usina_v2.html").read_text(encoding="utf-8")
    assert "fs.map(f=>f.fonte.replace(/^Fonte /,''))" in html
    assert "+': '+f.motivo+' às '+f.hora" not in html, "o motivo e a hora ficam no selo de cada cartão"


# ── 2. sem sol, sem PR ─────────────────────────────────────────────────────────────────────────────────────────────
class _Cursor:
    def __init__(self, linhas): self.linhas = linhas
    def execute(self, *a, **k): pass
    def fetchall(self): return self.linhas


class _Conn:
    def __init__(self, linhas): self.c = _Cursor(linhas)
    def cursor(self): return self.c
    def close(self): pass


def _pr_pg(monkeypatch, ipoa, ger):
    linhas = [("Usina X", 7, 1, "INV 1", ger, ipoa, 288, 0), ("Usina X", 7, 2, "INV 2", ger, ipoa, 288, 0)]
    monkeypatch.setattr(app, "_pg_conn", lambda: _Conn(linhas))
    monkeypatch.setattr(app, "_pot_inv", lambda *a, **k: 100.0)
    _, detail = app._pg_pr_build("2026-10-11")
    return [i["pr"] for i in detail[7]["inversores"]] if isinstance(detail.get(7), dict) else [i["pr"] for i in detail[7]]


def test_de_noite_o_pr_e_none_e_nao_menos_zero(monkeypatch):
    prs = _pr_pg(monkeypatch, ipoa=0.004, ger=-0.0)
    assert prs == [None, None], prs


def test_com_sol_e_geracao_zero_o_pr_zero_continua(monkeypatch):
    prs = _pr_pg(monkeypatch, ipoa=4.2, ger=-0.0)
    assert prs == [0.0, 0.0] and all(str(p) == "0.0" for p in prs), prs   # 0.0, não -0.0


def test_com_sol_o_pr_segue_a_conta_de_sempre(monkeypatch):
    prs = _pr_pg(monkeypatch, ipoa=5.0, ger=400.0)
    assert prs == [0.8, 0.8], prs


# ── 3. /api/pv/pr com a fonte fora ────────────────────────────────────────────────────────────────────────────────
def _cli(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")          # sem senha: app aberto (dev), o portão não interfere
    monkeypatch.setitem(app.app.config, "PROPAGATE_EXCEPTIONS", False)
    app._pv_pr_cache["detail"].pop(424242, None)
    return app.app.test_client()


def test_autenticacao_da_api_pv_fora_da_502_em_json(monkeypatch):
    def cai(): raise ConnectionError("sem rede")
    monkeypatch.setattr(app, "get_token", cai)
    r = _cli(monkeypatch).get("/api/pv/pr/424242")
    assert r.status_code == 502 and r.is_json, (r.status_code, r.get_data(as_text=True)[:200])
    assert r.get_json()["fonte"] == "API PV" and r.get_json()["fonte_ok"] is False


def test_lista_de_usinas_fora_nao_vira_usina_nao_encontrada(monkeypatch):
    monkeypatch.setattr(app, "get_token", lambda: "t")
    def cai(token): raise TimeoutError("lenta")
    monkeypatch.setattr(app, "get_plants", cai)
    r = _cli(monkeypatch).get("/api/pv/pr/424242")
    assert r.status_code == 502 and "não encontrada" not in r.get_data(as_text=True)


def test_usina_que_nao_existe_continua_404(monkeypatch):
    monkeypatch.setattr(app, "get_token", lambda: "t")
    monkeypatch.setattr(app, "get_plants", lambda token: [{"id": 1, "name": "Outra"}])
    r = _cli(monkeypatch).get("/api/pv/pr/424242")
    assert r.status_code == 404
