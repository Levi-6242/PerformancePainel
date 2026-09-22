# -*- coding: utf-8 -*-
"""A contagem de trackers parados sobrevive ao restart do deploy (Levi, 22/09/2026).

O caso: *"os trackers não está contando os trackers parados"* — no tempo real da Athon, o card
dizia "fonte não respondeu" logo depois de um deploy. A rota respondia (200, 33 KB, 5,5 s); quem
falhava era a montagem do tempo real, que dá 30 s por fonte e, se estoura, reaproveita a contagem da
montagem ANTERIOR. Só que "anterior" morava na memória do processo, e o servidor reinicia a cada
push — hoje foram quatro. Na primeira montagem depois do restart não havia anterior nenhuma e o
card ficava sem número por 5 a 10 minutos, até a fonte esquentar. Medido: às 15:23 Athon, API PV e
Thopen pendentes; às 15:29, com as fontes quentes, Athon 93, API PV 250, SEMP 1.

Agora a última leitura BOA de cada fonte fica num arquivo pequeno em `plataforma/`, e o reaproveitamento
cai nele quando a memória está vazia. A regra de 21/09 continua: dado velho só com rótulo — o card diz
"da leitura das HH:MM", não finge que é de agora. E há teto: contagem de mais de 3 h não é reaproveitada,
porque aí o traço volta a ser o honesto.
"""
import json
import time

import pytest

import app


@pytest.fixture
def arquivo(tmp_path, monkeypatch):
    p = tmp_path / "entrada_trk_ultimo.json"
    monkeypatch.setattr(app, "_ENTRADA_TRK_ULTIMO", str(p))
    return p


def _grupo(cliente="Athon", fonte="Athon", parados=93, com_os=4, ok=True, atrasado=None, lido="15:29"):
    g = {"cliente": cliente, "fonte": fonte, "trk_fonte_ok": ok, "trk_parados": parados, "trk_com_os": com_os,
         "trk_lido_em": lido, "usinas": [{"usina": "MTS100", "trk_parados": 60, "trk_com_os": 4},
                                         {"usina": "TIM100", "trk_parados": 33, "trk_com_os": 0}]}
    if atrasado:
        g["trk_atrasado"] = True
    return g


def test_a_leitura_boa_vai_para_o_disco_e_volta(arquivo):
    app._entrada_trk_ultimo_gravar([_grupo()])
    ant = app._entrada_trk_anterior({}, "Athon", "Athon")          # memória vazia = processo recém-reiniciado
    assert ant and ant["trk_fonte_ok"] and ant["trk_parados"] == 93 and ant["trk_com_os"] == 4
    assert ant["trk_lido_em"] == "15:29", "sem o horário o card não consegue dizer DE QUANDO é o número"
    assert {u["usina"]: u["trk_parados"] for u in ant["usinas"]} == {"MTS100": 60, "TIM100": 33}


def test_a_memoria_vence_o_disco(arquivo):
    """Com a montagem anterior na memória (processo sem restart), ela é a mais nova — o disco é só
    para quando ela não existe."""
    app._entrada_trk_ultimo_gravar([_grupo(parados=10, lido="14:00")])
    mem = {("Athon", "Athon"): _grupo(parados=93, lido="15:29")}
    assert app._entrada_trk_anterior(mem, "Athon", "Athon")["trk_parados"] == 93


def test_contagem_REAPROVEITADA_nao_regrava_o_disco(arquivo):
    """Senão o horário da leitura velha seria renovado a cada montagem e ela nunca passaria do teto:
    o card mostraria para sempre um número de ontem com cara de recente."""
    app._entrada_trk_ultimo_gravar([_grupo(parados=93, lido="15:29")])
    app._entrada_trk_ultimo_gravar([_grupo(parados=1, atrasado=True, lido="15:29")])
    assert app._entrada_trk_anterior({}, "Athon", "Athon")["trk_parados"] == 93


def test_fonte_que_nao_respondeu_nao_vai_para_o_disco(arquivo):
    app._entrada_trk_ultimo_gravar([_grupo(ok=False, parados=0)])
    assert app._entrada_trk_anterior({}, "Athon", "Athon") is None


def test_contagem_de_mais_de_tres_horas_nao_e_reaproveitada(arquivo, monkeypatch):
    app._entrada_trk_ultimo_gravar([_grupo()])
    real = time.time
    monkeypatch.setattr(app.time, "time", lambda: real() + app._ENTRADA_TRK_ULTIMO_MAX_S + 60)
    assert app._entrada_trk_anterior({}, "Athon", "Athon") is None, "número velho demais tem de voltar a ser traço"


def test_gravar_uma_fonte_nao_apaga_as_outras(arquivo):
    """Numa montagem a Athon responde e a API PV estoura; na seguinte, o contrário. As duas leituras
    boas têm de conviver no arquivo."""
    app._entrada_trk_ultimo_gravar([_grupo("Athon", "Athon", parados=93)])
    app._entrada_trk_ultimo_gravar([_grupo("Thopen", "API PV", parados=250)])
    assert app._entrada_trk_anterior({}, "Athon", "Athon")["trk_parados"] == 93
    assert app._entrada_trk_anterior({}, "Thopen", "API PV")["trk_parados"] == 250


def test_arquivo_corrompido_nao_derruba_a_montagem(arquivo):
    arquivo.write_text("{isto não é json", encoding="utf-8")
    assert app._entrada_trk_anterior({}, "Athon", "Athon") is None
    app._entrada_trk_ultimo_gravar([_grupo()])                     # e a próxima gravação conserta
    assert json.loads(arquivo.read_text(encoding="utf-8"))


def test_o_arquivo_fica_fora_do_git():
    """Estado de runtime: não pode ser commitado nem brigar com o `git pull` do deploy."""
    import pathlib
    import subprocess
    raiz = pathlib.Path(app.__file__).resolve().parents[1]
    r = subprocess.run(["git", "check-ignore", "-q", "plataforma/entrada_trk_ultimo.json"], cwd=str(raiz))
    assert r.returncode == 0, "entrada_trk_ultimo.json não está no .gitignore"


def test_o_card_diz_DE_QUANDO_e_o_numero():
    import pathlib
    raiz = pathlib.Path(app.__file__).resolve().parents[1]
    s = (raiz / "docs" / "redesign" / "Entrada.html").read_text(encoding="utf-8")
    # os DOIS lugares que rotulam a contagem reaproveitada (card do grupo e card da fonte) usam o horário
    assert s.count('g.trk_lido_em ? "das " + g.trk_lido_em') == 2, "algum rótulo ainda diz só 'anterior'"
