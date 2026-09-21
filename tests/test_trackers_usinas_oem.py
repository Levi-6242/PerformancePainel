# -*- coding: utf-8 -*-
"""Trackers das usinas da conta OEM pela PV Plataforma (Levi, 15/09/2026).

"SEMP não tá puxando ainda os trackers via PV, já tem os dados lá no sistema da PV."

Até hoje a varredura de trackers (`_build_pv_trk_payload`) excluía TODA usina da conta OEM, porque
a apiplataforma respondia "Usuário não possui permissão" com o PLAT_TOKEN do usuário gridco — era 1
chamada condenada por ciclo. Com o token renovado em 15/09 (usuarioid 8540) a negativa acabou:
conferido ao vivo, Tucano 1 e Tucano 2 devolvem 40 trackers cada, leitura do minuto.

A exclusão deixa de ser "é da conta OEM" e passa a ser "o tracker já vem de OUTRA fonte" — hoje só
as três da 2C, que chegam pelo e-mail (fonte `owen`, rótulo "2C"). Duas fontes para o MESMO tracker
duplicariam a ocorrência no livro (`tracker_watch`) e o "parado" na Entrada."""
import app


def test_tucano_entra_na_varredura_de_trackers():
    # as duas da SEMP têm tracker na PV Plataforma e NENHUMA outra fonte — têm de entrar
    assert app._pv_trk_fora(18758732) is False, "Tucano 1"
    assert app._pv_trk_fora(18768694) is False, "Tucano 2"


def test_2c_fica_fora_porque_ja_vem_pelo_email():
    # Araputanga, Sete Lagoa e Tupi Paulista já têm tracker pela fonte `owen` (e-mail)
    for pid in app.PV_FONTES["2capi"]:
        assert app._pv_trk_fora(pid) is True, f"{pid} duplicaria o tracker do e-mail"
    assert app.PV_TRK_OUTRA_FONTE == set(app.PV_FONTES["2capi"])


def test_varredura_nao_exclui_mais_por_ser_da_conta_oem():
    """A regra velha (`not _pv_is_oem(p["id"])`) tirava a Tucano junto com as da 2C — é
    exatamente o que o Levi viu. Trava para não voltar por engano."""
    import inspect
    src = inspect.getsource(app._build_pv_trk_payload)
    assert "_pv_is_oem" not in src, "a exclusão voltou a ser por conta, não por fonte do tracker"
    assert "_pv_trk_fora" in src


def test_morada_nova_nao_e_excluida_de_proposito():
    """A Morada Nova é da conta OEM e NÃO tem tracker — a API responde 200 com lista vazia.
    Isso é ausência honesta (`tem_trackers` False, a usina não entra nas linhas), não motivo
    para excluí-la na mão: no dia em que ganhar seguidor, ela aparece sozinha."""
    assert app._pv_trk_fora(18766373) is False


def test_rota_da_fonte_semp_existe_e_recorta():
    """No Monitoramento cada fonte pede o SEU endpoint. `/api/pv/trackers` devolve as 83 usinas da
    conta principal — a SEMP precisa da rota própria, senão o chip Trackers da fonte mostraria a
    frota inteira. Sem a rota, `EP.trackers` fica sem a chave `semp` e o chip nem aparece: era o
    que o Levi estava vendo."""
    import pathlib
    APP = (pathlib.Path(app.__file__).resolve().parents[1] / "plataforma" / "app.py").read_text(encoding="utf-8")
    assert '@app.route("/api/semp/trackers")' in APP
    assert "def _pv_trk_payload_da_fonte(" in APP
    MON = (pathlib.Path(app.__file__).resolve().parents[1] / "docs" / "redesign" /
           "Monitoramento (novo design).html").read_text(encoding="utf-8")
    assert "semp:'/api/semp/trackers'" in MON


def test_recorte_da_fonte_filtra_pelas_usinas_dela(monkeypatch):
    """O recorte é por ID da fonte — mesma régua de `_pv_plantas_da_fonte` (não pelo nome).

    16/09: a função passou a CONSTRUIR o payload com as usinas da fonte em vez de recortar o global.
    O motivo está em test_fonte_2capi_etm_trackers: a 2C é excluída da varredura global de propósito,
    então recortar dali devolvia sempre vazio para ela. A intenção travada aqui é a mesma de antes —
    entram só as usinas DA FONTE, e as somas batem —, mas sem depender da ordem, que agora vem de
    `as_completed` (concorrente) e é reordenada por severidade."""
    porta = {18758732: {"plant_id": 18758732, "usina": "Tucano 1", "tem_trackers": True,
                        "total": 40, "severos": 0, "leves": 0},
             18768694: {"plant_id": 18768694, "usina": "Tucano 2", "tem_trackers": True,
                        "total": 40, "severos": 1, "leves": 0}}
    chamadas = []

    def _falso(idusina, nome, **kw):
        chamadas.append(idusina)
        return porta[idusina]

    monkeypatch.setattr(app, "_pv_trackers_analise", _falso)
    app._pv_trk_fonte_cache.pop("semp", None)
    out = app._pv_trk_payload_da_fonte("semp")
    assert sorted(chamadas) == [18758732, 18768694], "só as usinas da fonte são varridas"
    assert {r["plant_id"] for r in out["rows"]} == {18758732, 18768694}
    assert out["summary"]["usinas"] == 2 and out["summary"]["trackers"] == 80
    assert out["summary"]["severos"] == 1


def test_todas_as_rotas_derivadas_do_base_da_fonte_existem():
    """O Monitoramento deriva TRÊS urls do mesmo `EP.trackers[fonte]` — `loadTrk` pede
    `base/<pid>`, `_loadTrkChart` pede `base/<pid>/chart` e o botão "CSV bruto" pede
    `base/<pid>/chart.csv`. Apontar a chave `semp` para `/api/semp/trackers` sem criar as três
    faria a LISTA aparecer e o drill/gráfico/CSV darem 404 — meio caminho, que é pior que nada
    porque parece que funciona. O id é global na API PV, então são delegações."""
    regras = {str(r) for r in app.app.url_map.iter_rules()}
    for rota in ("/api/semp/trackers",
                 "/api/semp/trackers/<int:idusina>",
                 "/api/semp/trackers/<int:idusina>/chart",
                 "/api/semp/trackers/<int:idusina>/chart.csv"):
        assert rota in regras, f"o front deriva {rota} e ela não existe"
