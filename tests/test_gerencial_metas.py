# -*- coding: utf-8 -*-
"""Metas do Gerencial (07/09/2026) — três regras que o Levi pediu depois de ver usina com meta aparecendo
"sem meta" no mosaico da Frota:

  1. o BD_Thopen é lido SÓ pelo PostgreSQL (Gridco Performance API). Sem banco, mantém o que já está
     carregado e diz por quê — nunca cai no .xlsx do OneDrive, que é onde a coleta ESCREVE e pode estar horas
     atrás do banco;
  2. usina sem geração no mês ainda assim usa a meta do BD_Thopen (Tanabi, Guaratinguetá V): "sem meta" e
     "tem meta, falta a geração" são problemas diferentes e de gente diferente;
  3. os GRUPOS (Nova Londrina 1+2, Primavera 1+2, Ouro Branco I..V, Santo Antonio do/da Platina) viajam no
     payload e na rota própria — é a relação que o mosaico usa para somar os dois lados.
"""
import io

import pytest

import app


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(app, "DASH_PASSWORD", "")
    return app.app.test_client()


def test_bd_thopen_so_pelo_postgresql(monkeypatch, capsys):
    """API muda → relê; API fora → mantém a meta anterior e NÃO abre o Excel."""
    chamou_disco = []
    monkeypatch.setattr(app, "_bd_thopen_path", lambda: chamou_disco.append(1) or "nao_deveria.xlsx")
    monkeypatch.setattr(app, "_bd_readable", lambda *a, **k: chamou_disco.append(1) or None)
    antes = {"guatambu": {9: {"meta_mwh": 748.35}}}
    monkeypatch.setattr(app, "THOPEN_META", dict(antes))

    import bd_api
    monkeypatch.setattr(bd_api, "carregar", lambda *a, **k: None)      # banco fora do ar
    app.load_thopen_meta()
    assert app.THOPEN_META == antes, "perdeu a meta já carregada quando o banco não respondeu"
    assert not chamou_disco, "leu (ou tentou ler) o arquivo — a regra é PostgreSQL e ponto"
    assert "Excel NÃO é lido" in capsys.readouterr().out

    def _explode(*a, **k):
        raise RuntimeError("timeout no banco")
    monkeypatch.setattr(bd_api, "carregar", _explode)
    app.load_thopen_meta()
    assert app.THOPEN_META == antes and not chamou_disco   # exceção também não libera o arquivo


def test_sem_geracao_ainda_usa_a_meta_do_bd_thopen():
    """O ramo 'cadastro' (sem geração no mês) passou a consultar THOPEN_META, como os outros três ramos."""
    import inspect
    src = inspect.getsource(app._gerencial_payload)
    ini = src.index('p50_mes, p50_src = None, "cadastro"')
    fim = src.index('"src": "cadastro"', ini)
    trecho = src[ini:fim]
    assert "_meta_mes(" in trecho, "o caminho sem geração voltou a ignorar a meta do BD_Thopen"
    # a ordem importa: BD_Thopen primeiro, depois Info Mensal (mês exato → mesmo mês), por fim P50 anual/12
    assert trecho.index("_meta_mes(") < trecho.index("prm_all") < trecho.index("p50_mwh\"] / 12.0")
    # e a procedência é registrada: dá para ver na tela de onde saiu a meta de cada usina
    assert '"thopen"' in trecho and '"anual_12"' in trecho and '"mes_exato"' in trecho
    assert '"p50_src": p50_src' in src, "o payload voltou a fixar p50_src='cadastro' e esconde a procedência"


def test_grupos_do_mosaico(cliente):
    """A relação vive no backend (uma fonte só) e chega na tela pelo payload e pela rota."""
    nomes = {g["nome"] for g in app._GER_GRUPOS}
    assert {"Nova Londrina", "Primavera", "Ouro Branco", "Santo Antonio da Platina"} <= nomes
    por = {g["nome"]: g for g in app._GER_GRUPOS}
    # a base junta o que a API PV separa
    assert por["Nova Londrina"]["vivo"] == ["Nova Londrina 1", "Nova Londrina 2"]
    assert por["Nova Londrina"]["ger"] == ["Nova Londrina"]
    # ...e separa o que ela junta
    assert por["Ouro Branco"]["vivo"] == ["Ouro Branco"] and len(por["Ouro Branco"]["ger"]) == 5
    # grafia divergente: "do Platina" ao vivo, "da Platina" na base
    assert por["Santo Antonio da Platina"]["vivo"] == ["Santo Antonio do Platina"]
    d = cliente.get("/api/gerencial/grupos").get_json()
    assert {g["nome"] for g in d["grupos"]} == nomes
    for g in app._GER_GRUPOS:                       # sem grupo vazio dos dois lados
        assert g["vivo"] and g["ger"]


def test_producao_do_mes_nao_pula_polaris_em_bloco():
    """Polaris com ABA PRÓPRIA (Guaratinguetá V) entra na produção; quem vem do PG é descartado depois,
    pelo `pg_keys` do gerencial — pular todas aqui cegava as que não estão no banco do OEM."""
    import inspect
    src = inspect.getsource(app._thopen_prod_build)
    assert '== "Polaris"' not in src, "voltou a pular a carteira Polaris em bloco"
    logs = [l.strip() for l in src.splitlines() if l.strip().startswith("print(") and "usinas" in l]
    assert len(logs) == 1 and "(PostgreSQL)" in logs[0] and "xlsx" not in logs[0], \
        f"o log voltou a dizer que a fonte é o Excel: {logs}"
    assert "if k in pg_keys" in inspect.getsource(app._gerencial_payload)   # a de-duplicação continua existindo


def test_chave_tolerante_casa_as_duas_grafias():
    """A aba do BD_Thopen escreve 'Piracicaba 1' o que o PG chama 'Piracicaba I'. Sem esta chave a usina entrava
    DUAS vezes no gerencial (dobrando o rollup) e a meta ficava na cópia que a tela não mostra."""
    f = app._ger_fold
    assert f("Piracicaba I") == f("Piracicaba 1") == "piracicaba1"   # colado, como o _nrm dos cadastros
    assert f("Marajoara I") == f("Marajoara 1")
    assert f("Santo Antonio do Platina") == f("Santo Antônio da Platina") == "santoantonioplatina"
    assert f("Córrego do Sapucaia") == f("Corrego Sapucaia") == "corregosapucaia"
    assert f("Altair 1 (73)") == "altair1"                     # código entre parênteses não é nome
    # ...e continua separando o que é diferente de verdade
    assert f("Ouro Branco I") != f("Ouro Branco II")
    assert f("Nova Londrina 1") != f("Nova Londrina")
    assert f("Aparecida do Taboado 1") != f("Aparecida do Taboado 1 e 2")
    assert f(None) == "" and f("") == ""


def test_dedup_do_gerencial_usa_a_chave_tolerante():
    import inspect
    src = inspect.getsource(app._gerencial_payload)
    assert "pg_folds" in src, "a de-duplicação voltou a olhar só a chave exata"
    assert "_ger_fold(tp.get(\"usina\") or k) in pg_folds" in src
    assert "_meta_mes(" in src and src.count("_meta_mes(") >= 4   # os 3 ramos + a definição


def test_sem_colisao_entre_usinas_distintas():
    """A chave tolerante não pode juntar usinas diferentes: se juntar, uma soma vira de duas."""
    import collections
    for reg, rot in ((app.INFO_GERAL, "Info Geral"), (app.THOPEN_META, "BD_Thopen")):
        c = collections.Counter(app._ger_fold(k) for k in reg)
        dup = {f: [k for k in reg if app._ger_fold(k) == f] for f, n in c.items() if n > 1}
        assert not dup, f"{rot}: nomes distintos caíram na mesma chave -> {dup}"
