# -*- coding: utf-8 -*-
"""A trava de string tem de valer no processo que CONSTRÓI os números (varredura de 09/09/2026).

O achado: `_trancadas` era lido uma única vez, no import (`set(_load_state()...)`), e só reatribuído
dentro da rota POST — que roda no processo WEB. Quem monta o mosaico, o /monitoramento, o card do
tempo real e o sino é o WORKER, outro processo: ele nunca reliaa o arquivo. Resultado para o analista:
tranca a string, a tela pisca certo (resposta do próprio web) e volta atrás no ciclo seguinte, com a
string contando como faltando até o worker reciclar às 03:00.

Estes testes fixam o contrato do conserto: existe uma recarga guardada por mtime, ela é barata quando
nada mudou, ela reconstrói o índice tolerante ao plant_id e ela está ligada nos DOIS processos.
"""
import inspect
import json
import pathlib

import app

APP_PY = pathlib.Path(app.__file__)


def _estado(tmp_path, trancadas):
    p = tmp_path / "ufv_state.json"
    p.write_text(json.dumps({"strings_trancadas": trancadas}), encoding="utf-8")
    return str(p)


def _isola(monkeypatch, caminho):
    """Aponta o estado para um arquivo de teste e devolve os globais ao fim (o módulo é compartilhado)."""
    monkeypatch.setattr(app, "STATE_PATH", caminho)
    monkeypatch.setattr(app, "_trancadas", set(app._trancadas), raising=False)
    monkeypatch.setattr(app, "_TRANC_INV", set(app._TRANC_INV), raising=False)
    monkeypatch.setattr(app, "_TRANC_MARCA", None, raising=False)


def test_recarga_ve_a_trava_gravada_por_outro_processo(tmp_path, monkeypatch):
    """O caso do analista: o web gravou o arquivo, o worker tem de enxergar sem reiniciar."""
    caminho = _estado(tmp_path, ["22854|9911|Ipv3"])
    _isola(monkeypatch, caminho)
    assert app._trancadas_recarrega() is True, "a 1ª leitura do arquivo tem de valer como mudança"
    assert "22854|9911|Ipv3" in app._trancadas
    assert app._str_trancada("22854", "9911", "Ipv3") is True


def test_recarga_reconstroi_o_indice_tolerante_ao_plant_id(tmp_path, monkeypatch):
    """`_TRANC_INV` é o que faz a trava valer quando a mesma usina aparece com plant_id diferente
    (Fernandópolis, 3 registros). Recarregar sem reconstruir o índice devolveria metade da regra."""
    caminho = _estado(tmp_path, ["22854|9911|Ipv3"])
    _isola(monkeypatch, caminho)
    app._trancadas_recarrega()
    assert ("9911", "Ipv3") in app._TRANC_INV
    assert app._str_trancada("OUTRO_ID", "9911", "Ipv3") is True


def test_recarga_e_barata_quando_o_arquivo_nao_mudou(tmp_path, monkeypatch):
    """Roda a cada 20 s nos dois processos: sem o guard de mtime, seria um json.load + invalidação de
    cache de minuto em minuto, de graça."""
    caminho = _estado(tmp_path, ["22854|9911|Ipv3"])
    _isola(monkeypatch, caminho)
    assert app._trancadas_recarrega() is True
    assert app._trancadas_recarrega() is False, "arquivo intacto não pode contar como mudança"


def test_recarga_enxerga_a_DEStrava(tmp_path, monkeypatch):
    """Destrancar é o caminho de volta: a string tem de voltar a contar como faltando."""
    caminho = _estado(tmp_path, ["22854|9911|Ipv3"])
    _isola(monkeypatch, caminho)
    app._trancadas_recarrega()
    pathlib.Path(caminho).write_text(json.dumps({"strings_trancadas": []}), encoding="utf-8")
    assert app._trancadas_recarrega() is True
    assert app._trancadas == set() and app._TRANC_INV == set()
    assert app._str_trancada("22854", "9911", "Ipv3") is False


def test_arquivo_sumido_nao_apaga_as_travas_da_memoria(tmp_path, monkeypatch):
    """OneDrive/antivírus segurando o arquivo por um instante não pode destrancar a frota inteira —
    sem estado legível, o que já está na memória continua valendo."""
    caminho = _estado(tmp_path, ["22854|9911|Ipv3"])
    _isola(monkeypatch, caminho)
    app._trancadas_recarrega()
    pathlib.Path(caminho).unlink()
    assert app._trancadas_recarrega() is False
    assert "22854|9911|Ipv3" in app._trancadas, "sumiço do arquivo destrancou a string"


def test_a_recarga_esta_ligada_nos_DOIS_processos():
    """De nada adianta a função existir: quem constrói os números é o worker (loops de fundo) e quem
    responde ao usuário é o web (que também roda um watch). Se sair de um dos dois, o bug volta."""
    assert "_tranc_watch_loop" in inspect.getsource(app._iniciar_loops_de_fundo), \
        "o worker voltou a não reler o ufv_state.json"
    src = APP_PY.read_text(encoding="utf-8")
    web = src[src.index("_MODO_WEB = True"):]
    assert "_tranc_watch_loop" in web[:800], "o processo web não observa mais o estado das travas"


def test_o_post_marca_o_arquivo_como_lido():
    """O próprio POST grava o arquivo; sem carimbar a marca, o watch do mesmo processo acordaria em
    seguida e limparia os caches de novo, à toa."""
    src = inspect.getsource(app.api_state_string_trancada)
    assert "_tranc_marca_lido()" in src, "o POST deixou de carimbar o mtime que ele mesmo produziu"
