# -*- coding: utf-8 -*-
"""Inversor desligado sai das strings esperadas — começando pela Athon (Levi, 22/09/2026).

O pedido: *"não gostaria que contasse na coluna de strings esperadas na parte de usinas quando o
inversor estiver desligado, com potência ativa = 0 ou alguma flag de inversor desligado"*.

O sinal escolhido foi a POTÊNCIA ATIVA, não o estado de operação — e a escolha foi medida. A SunOp
entrega, por inversor, `MEDIDAS.P` (kW) e `MEDIDAS.Workstate`, com um dicionário de códigos no
cadastro (1 = Normal, 16 = Stand-by, 512 = "Falha na ventilação"…). Só que o dicionário vale para UM
modelo de inversor: na MTS100/MTS200 o normal é o código 1; nas outras oito usinas da Athon o
inversor gerando normal manda 512. Em 22/09, 217 dos 329 inversores estavam com o código de "falha"
gerando em média 18 kW. Usar o estado marcaria como problema inversor que está produzindo.

Régua: desligado = potência abaixo de `max(piso, 5% da mediana dos vizinhos)`, COM SOL no estado da
usina, e COM A USINA GERANDO (pelo menos um vizinho produzindo). Os três portões importam:
  - sem sol, todo inversor está a zero — é a noite, não falha;
  - usina inteira a zero de dia é outra ocorrência (usina parada); tirar todas as strings da conta
    esconderia a usina morta atrás de "0 strings faltando";
  - sem leitura de potência é "sem comunicação", outro alarme — nunca "desligado".

Isto INVERTE, para a Athon, o tratamento de 11/09 da API PV e do banco (inversor desligado contava
todas as strings como faltando). O inversor não some: a linha leva `inv_desligados`/`strings_fora` e a
tela mostra o aviso na célula das esperadas.
"""
import pathlib

import pytest

import app


# ── a régua, pura ─────────────────────────────────────────────────────────────

def test_inversor_parado_com_os_vizinhos_gerando_e_desligado():
    assert app._inv_desligados_por_potencia([50.0, 48.0, 0.0, 51.0], com_sol=True) == [False, False, True, False]


def test_sem_sol_ninguem_e_desligado():
    """É a noite. Sem este portão, às 18h toda a Athon sairia das esperadas."""
    assert app._inv_desligados_por_potencia([0.0, 0.0, 0.0], com_sol=False) == [False, False, False]


def test_usina_inteira_parada_nao_tira_ninguem_da_conta():
    """Usina morta de dia é ocorrência de USINA. Tirar todas as strings da conta faria a tela dizer
    '0 strings faltando' justamente na usina que não está gerando nada."""
    assert app._inv_desligados_por_potencia([0.0, 0.1, 0.0], com_sol=True) == [False, False, False]


def test_sem_leitura_de_potencia_nao_e_desligado():
    """Leitura que não veio é 'sem comunicação', não 'desligado'."""
    assert app._inv_desligados_por_potencia([50.0, None, 49.0], com_sol=True) == [False, False, False]


def test_inversor_produzindo_pouco_nao_e_desligado():
    """Nuvem sobre um bloco, derating, limitação: gera menos, mas gera. Só o ~zero sai da conta."""
    assert app._inv_desligados_por_potencia([50.0, 15.0, 49.0], com_sol=True) == [False, False, False]


# ── a linha da usina da Athon ─────────────────────────────────────────────────

@pytest.fixture
def usina_athon(monkeypatch):
    """TST100 com 3 inversores de 4 strings: INV_1 e INV_2 gerando; INV_3 parado, só com o ruído de
    corrente reversa nas strings (0,9 A) — o caso que a régua por string não pega sozinha."""
    nome = "TST100"
    meta = {"inv_strings": {f"INV_{i}": [f"{nome}.INV_{i}.MEDIDAS.STR.I_PV{s}" for s in range(1, 5)] for i in (1, 2, 3)},
            "inv_other": {f"INV_{i}": {"P": f"{nome}.INV_{i}.MEDIDAS.P"} for i in (1, 2, 3)},
            "plant_paths": {}}
    corrente = {1: 8.0, 2: 7.9, 3: 0.9}
    potencia = {1: 52.0, 2: 50.5, 3: 0.0}
    valores = []
    for i in (1, 2, 3):
        valores += [{"pathname": p, "value": corrente[i], "timestamp": app.datetime.now().isoformat(timespec="seconds")}
                    for p in meta["inv_strings"][f"INV_{i}"]]
        valores.append({"pathname": f"{nome}.INV_{i}.MEDIDAS.P", "value": potencia[i],
                        "timestamp": app.datetime.now().isoformat(timespec="seconds")})

    class _R:
        status_code = 200

        def json(self):
            return valores
    monkeypatch.setitem(app._si("gridco")["meta"], nome, meta)
    monkeypatch.setitem(app.ESPERADO_INV, nome, {"INV_1": 4, "INV_2": 4, "INV_3": 4})
    monkeypatch.setattr(app, "_sunop_req", lambda *a, **k: _R())
    # O detalhe chama ensure_sunop_meta() antes de tudo, e ele pede token e lista de usinas à SunOp
    # DE VERDADE — na 1ª versão deste teste a suíte travou esperando a rede e gastando cota.
    monkeypatch.setattr(app, "ensure_sunop_meta", lambda *a, **k: None)
    return nome


def test_de_dia_o_inversor_desligado_sai_das_esperadas(usina_athon, monkeypatch):
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    r = app.process_plant_sunop(usina_athon, "gridco")
    assert r["str_esp"] == 8, "as 4 strings do inversor parado não podem contar nas esperadas"
    assert r["strings_ativas"] == 8 and r["diferenca"] == 0
    assert r["inv_desligados"] == 1 and r["strings_fora"] == 4
    assert r["inv_desligados_nomes"], "o aviso precisa dizer QUAL inversor"


def test_de_noite_nada_muda(usina_athon, monkeypatch):
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: False)
    r = app.process_plant_sunop(usina_athon, "gridco")
    assert r["str_esp"] == 12 and r["inv_desligados"] == 0 and r["strings_fora"] == 0


# ── o detalhe da usina ────────────────────────────────────────────────────────

def test_no_detalhe_o_inversor_continua_listado_marcado_desligado(usina_athon, monkeypatch):
    """O inversor não pode sumir do detalhe: continua lá, marcado, com as strings em 'desligado' e
    fora da conta de diferença."""
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    invs = app._sunop_plant_build(usina_athon, "gridco")
    por = {i["id"]: i for i in invs}
    assert set(por) == {"INV_1", "INV_2", "INV_3"}
    assert por["INV_3"]["desligado"] is True and por["INV_3"]["fora_da_conta"] is True
    assert por["INV_3"]["diferenca"] is None
    assert all(s["status"] == "desligado" and s["ativa"] is False for s in por["INV_3"]["strings"])
    assert por["INV_1"]["desligado"] is False and not por["INV_1"].get("fora_da_conta")


# ── a tela ────────────────────────────────────────────────────────────────────

def test_a_tabela_mostra_o_aviso_na_celula_das_esperadas():
    raiz = pathlib.Path(app.__file__).resolve().parents[1]
    s = (raiz / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
    assert "inv_desligados" in s and "strings fora da conta" in s


def test_usina_sem_deficit_mas_com_inversor_desligado_NAO_e_normal():
    """O caso real de 22/09: a MRO100 tinha todo o seu -85 em 5 inversores desligados. Tirados da conta,
    o déficit zera — e sem um status próprio a usina viraria "Normal" perdendo 20% da geração."""
    raiz = pathlib.Path(app.__file__).resolve().parents[1]
    s = (raiz / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
    i_falha = s.index("stt='Falha de string'")
    i_desl = s.index("stt='Inversor desligado'")
    i_normal = s.index("stt='Normal'", i_falha)
    assert i_falha < i_desl < i_normal, "Inversor desligado tem de vir depois de Falha de string e antes de Normal"
