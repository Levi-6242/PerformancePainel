# -*- coding: utf-8 -*-
"""`/monitoramento` sem parâmetro leva ao Tempo real; COM parâmetro, não (Levi, 21/09/2026).

O pedido foi "poderia excluir do nosso código essa visão de monitoramento?" — e a premissa estava
errada de um jeito perigoso: o atalho do cabeçalho do /painel leva à MESMA tela do redesign, a que
estávamos editando naquele instante. Não há segunda tela; há um pouso ruim.

**Por que apagar a rota seria um estrago:** `/tempo-real/<fonte>` É esta rota dentro de um iframe
(`/monitoramento?fonte=…&embed=1`), e o /painel tem dois deep links por usina. A rota é estrutural.

O que estes testes seguram é justamente a fronteira: o redirecionamento vale SÓ para o caso nu.
Se um dia alguém generalizar, o Tempo real volta a carregar um iframe que se redireciona — a tela
dentro da tela — e o /painel perde os links por usina.
"""
import pytest

import app as appmod


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(appmod, "DASH_PASSWORD", "", raising=False)   # sem senha, o gate libera
    appmod.app.config["TESTING"] = True
    with appmod.app.test_client() as c:
        yield c


def test_sem_parametro_vai_para_o_tempo_real(cliente):
    r = cliente.get("/monitoramento")
    assert r.status_code in (301, 302, 308)
    assert r.headers["Location"].endswith("/tempo-real")


def test_com_fonte_serve_a_tela_e_nao_redireciona(cliente):
    """O deep link do /painel ("Monitoramento desta usina") passa por aqui."""
    r = cliente.get("/monitoramento?fonte=thopen-db&usina=7&view=trackers")
    assert r.status_code == 200 and b"<html" in r.data.lower()


def test_o_iframe_do_tempo_real_continua_servido(cliente):
    """É o caso crítico: `/tempo-real/<fonte>` embute esta URL. Se ela redirecionar, a Entrada
    passa a mostrar a Entrada dentro da Entrada."""
    r = cliente.get("/monitoramento?fonte=2C&embed=1&view=etm")
    assert r.status_code == 200 and b"<html" in r.data.lower()


def test_embed_sozinho_tambem_e_respeitado(cliente):
    """`embed=1` sem `fonte` existe no código da Entrada em transições de aba; redirecionar aí
    quebraria a troca de aba sem ninguém ligar as duas coisas."""
    assert cliente.get("/monitoramento?embed=1").status_code == 200


def test_a_rota_nao_foi_apagada():
    """Regressão do pedido original. A tela é a do redesign — a mesma de /tempo-real."""
    rotas = {str(r) for r in appmod.app.url_map.iter_rules()}
    assert "/monitoramento" in rotas
    assert "/tempo-real/<fonte_id>" in rotas, "o destino do redirecionamento tem de existir"


def test_a_entrada_ainda_aponta_o_iframe_para_ca():
    """Se a Entrada deixar de montar esta URL, o redirecionamento acima vira letra morta e alguém
    vai 'limpar' a rota achando que ninguém usa."""
    import pathlib
    raiz = pathlib.Path(appmod.__file__).resolve().parents[1]
    entrada = (raiz / "docs" / "redesign" / "Entrada.html").read_text(encoding="utf-8")
    assert "/monitoramento?fonte=" in entrada and "embed=1" in entrada
