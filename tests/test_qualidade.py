# -*- coding: utf-8 -*-
"""Réguas de qualidade de dado sobre o pvanalytics (Levi, 17/09/2026: "pode seguir").

Duas primeiras do estudo, escolhidas por não dependerem de coordenada — valem para a frota inteira:

**Dado congelado.** A régua geral do caso que achei em 16/09: o combiner do INVERSOR02 da Tanabi 2
repetindo 13 zeros desde 28/05 enquanto o inversor gerava 92 kW. A guarda que pus lá olha a IDADE
do carimbo; esta olha o VALOR, então pega o sensor que repete a mesma leitura com carimbo novo — a
falha mais traiçoeira, porque parece saudável.

**Clipping.** Patamar achatado na curva de potência. Não tínhamos nada, e ele derruba PR sem ser
defeito: hoje um inversor no teto o dia inteiro é lido como perda.

O ajuste de domínio que o pvanalytics não faz: **à noite tudo é zero e toda série parece congelada**.
Por isso zero repetido só acusa DENTRO da janela solar; valor não-zero repetido acusa a qualquer
hora (um sensor travado em 5,2 A às 3h continua travado)."""
import pandas as pd
import pytest

qualidade = pytest.importorskip("qualidade")


def _serie(valores, ini="2026-09-17 06:00", freq="15min"):
    return pd.Series(valores, index=pd.date_range(ini, periods=len(valores), freq=freq))


class TestCongelado:
    def test_serie_que_varia_nao_acusa(self):
        s = _serie([1.0, 2.0, 3.1, 4.7, 5.2, 6.0, 7.1, 8.3])
        assert qualidade.congelado(s, janela=3)["congelado"] is False

    def test_valor_repetido_acusa_com_desde_e_valor(self):
        s = _serie([1.0, 2.0, 5.2, 5.2, 5.2, 5.2, 5.2, 9.0])
        r = qualidade.congelado(s, janela=3)
        assert r["congelado"] is True
        assert r["valor"] == 5.2
        assert r["n"] >= 4                      # a sequência inteira, não só a cauda
        assert str(r["desde"]).startswith("2026-09-17 06:30")   # 3ª leitura = 1º 5.2

    def test_zero_repetido_A_NOITE_nao_acusa(self):
        """Sem isto, TODA usina é acusada todas as madrugadas."""
        s = _serie([0.0] * 8, ini="2026-09-17 01:00")
        noite = pd.Series(False, index=s.index)
        assert qualidade.congelado(s, janela=3, mascara_dia=noite)["congelado"] is False

    def test_zero_repetido_DE_DIA_acusa(self):
        """O caso Tanabi 2: 13 zeros com sol e o inversor gerando."""
        s = _serie([0.0] * 8, ini="2026-09-17 11:00")
        dia = pd.Series(True, index=s.index)
        r = qualidade.congelado(s, janela=3, mascara_dia=dia)
        assert r["congelado"] is True and r["valor"] == 0.0

    def test_sem_mascara_o_zero_repetido_acusa(self):
        """Sem máscara a régua é conservadora do lado de acusar — quem chama é que sabe do sol."""
        assert qualidade.congelado(_serie([0.0] * 8), janela=3)["congelado"] is True

    def test_serie_curta_demais_nao_acusa(self):
        assert qualidade.congelado(_serie([2.0, 2.0]), janela=6)["congelado"] is False

    def test_serie_vazia_ou_toda_nula_nao_quebra(self):
        assert qualidade.congelado(pd.Series(dtype=float))["congelado"] is False
        assert qualidade.congelado(_serie([None] * 6))["congelado"] is False

    def test_horas_congeladas_sai_do_indice(self):
        s = _serie([3.0] * 9)                    # 9 leituras de 15 min = 2 h de ponta a ponta
        r = qualidade.congelado(s, janela=3)
        assert r["horas"] == pytest.approx(2.0, abs=0.01)

    def test_duas_sequencias_separadas_nao_viram_uma_so(self):
        """BUG REAL pego no campo (17/09, Sorocaba INVERSOR10). A série de um dia tem DUAS
        sequências constantes: a madrugada em 0 e o platô de clipping em 250. Pegando o primeiro
        marcado e o último, a régua relatava "250 kW travado desde 23:58 por 9,8 h" — o início de
        uma com o valor da outra, cobrindo a série inteira. Tem de reportar UMA sequência contígua,
        a mais longa."""
        s = _serie([0.0] * 10 + [5.0, 60.0, 130.0] + [250.0] * 6 + [130.0, 60.0])
        r = qualidade.congelado(s, janela=4)
        assert r["congelado"] is True
        assert r["valor"] == 0.0, "a mais longa é a madrugada (10 pontos), não o platô (6)"
        assert r["n"] == 10, f"pegou {r['n']} pontos — misturou as duas sequências"

    def test_reporta_a_sequencia_mais_longa(self):
        s = _serie([7.0] * 4 + [1.0, 2.0, 3.0] + [9.0] * 9 + [1.0])
        r = qualidade.congelado(s, janela=4)
        assert r["valor"] == 9.0 and r["n"] == 9

    def test_tolerancia_relativa_ignora_ruido_minusculo(self):
        """Sensor com ruído de 1e-9 continua congelado — é a diferença entre rtol e igualdade crua."""
        s = _serie([4.0, 4.000000001, 4.000000002, 4.000000001, 4.0, 4.000000002])
        assert qualidade.congelado(s, janela=3)["congelado"] is True


def _sino(teto=None, amp=130, freq="15min"):
    import numpy as np
    idx = pd.date_range("2026-09-17 05:00", "2026-09-17 19:00", freq=freq)
    s = pd.Series(np.cos(np.linspace(-1.5, 1.5, len(idx))) * amp, index=idx).clip(lower=0)
    return s.clip(upper=teto) if teto else s


class TestClipping:
    def test_curva_sem_teto_nao_acusa(self):
        """O detector marca o topo do sino mesmo SEM teto — medido: 0,053 na curva perfeita. Sem o
        piso, toda usina de céu limpo acusaria clipping ao meio-dia."""
        r = qualidade.clipping_dia(_sino())
        assert r["clipping"] is False
        assert r["fracao"] < qualidade.FRACAO_MINIMA     # o bruto fica visível para inspeção

    def test_platô_acusa_e_diz_a_janela(self):
        r = qualidade.clipping_dia(_sino(teto=110))
        assert r["clipping"] is True
        assert r["fracao"] > 0.15
        assert r["inicio"] is not None and r["inicio"] < r["fim"]
        assert r["teto"] == pytest.approx(110, abs=1)

    def test_quanto_mais_baixo_o_teto_maior_a_fracao(self):
        """Monotonicidade: a régua tem de responder à severidade, não só ao sim/não."""
        leve = qualidade.clipping_dia(_sino(teto=125))["fracao"]
        forte = qualidade.clipping_dia(_sino(teto=90))["fracao"]
        severo = qualidade.clipping_dia(_sino(teto=70))["fracao"]
        assert leve < forte < severo

    def test_serie_curta_nao_quebra(self):
        assert qualidade.clipping_dia(_serie([1.0, 2.0]))["clipping"] is False

    def test_serie_vazia_nao_quebra(self):
        assert qualidade.clipping_dia(pd.Series(dtype=float))["fracao"] == 0.0


def test_modulo_degrada_sem_a_biblioteca(monkeypatch):
    """O worker não pode morrer se o pvanalytics sumir do ambiente (máquina nova, deploy da T.I.).
    Sem a biblioteca as réguas devolvem "não sei", nunca levantam."""
    monkeypatch.setattr(qualidade, "_PVA", False)
    assert qualidade.congelado(_serie([3.0] * 8))["congelado"] is False
    assert qualidade.clipping_dia(_serie([3.0] * 8))["clipping"] is False
    assert qualidade.congelado(_serie([3.0] * 8))["indisponivel"] is True


def test_laco_e_rota_ligados_no_app():
    """Trava a fiação: a régua só serve se o worker a roda e o snapshot a carrega. Sem isto ela
    fica sendo um módulo bonito que ninguém chama."""
    import pathlib
    APP = (pathlib.Path(__file__).resolve().parents[1] / "plataforma" / "app.py").read_text(encoding="utf-8")
    assert "def _qualidade_loop():" in APP
    assert "_qualidade_loop,  " in APP.replace("\n", " ")          # registrado nos laços de fundo
    assert '@app.route("/api/qualidade")' in APP
    assert '"qualidade":    {"ts": _qualidade_cache' in APP        # escreve no snapshot
    assert '("qualidade", _qualidade_cache, "data")' in APP        # e relê dele
    # o Pac travado só conta em valor NÃO-zero: zero é a régua de inversor desligado
    assert 'if g["congelado"] and g["valor"]:' in APP


def test_recorte_2c_e_clipping_nao_e_perda():
    """Decisões do Levi (17/09, sobre o mockup do gêmeo):
    (1) "Clipping não conta como perda" — é perda de PROJETO, não de operação: ninguém vai
        consertar um inversor que está no limite do que foi dimensionado. Some junto com string
        morta e tracker travado e a usina parece mal operada estando apenas no teto. O payload
        precisa dizer isso de forma explícita, para ninguém somar por engano.
    (2) "Vamos focar apenas nas usinas 2C por ora" — a varredura deixa de percorrer 40 usinas da
        FULL_OM e passa a olhar só as três da 2C que estão na API PV."""
    import app
    assert app.QUALIDADE_PLANTAS == set(app.PV_FONTES["2capi"]), "o recorte é a fonte 2capi"
    assert len(app.QUALIDADE_PLANTAS) == 4          # as três de 17/09 + a União (25/09/2026)
    import pathlib
    APP = (pathlib.Path(__file__).resolve().parents[1] / "plataforma" / "app.py").read_text(encoding="utf-8")
    assert '"clipping_e_perda": False' in APP, "o payload tem de dizer que clipping não é perda"
    assert "QUALIDADE_PLANTAS" in APP.split("def _qualidade_ciclo")[1][:600], "o ciclo usa o recorte"


def test_nome_do_inversor_usa_o_de_para_da_conta_oem():
    """As três da 2C são da conta oem@, que NÃO pode chamar /plant_devices — sem o de-para a tela
    listaria "inv 367511" em vez de "Inversor 1.1". O `PV_INV_NOMES` já existe e foi fechado por
    VALOR contra o kWh do BD; aqui só garanto que a régua o consulta."""
    import pathlib
    APP = (pathlib.Path(__file__).resolve().parents[1] / "plataforma" / "app.py").read_text(encoding="utf-8")
    bloco = APP.split("def _qualidade_usina")[1][:1800]
    assert "PV_INV_NOMES.get(pid)" in bloco
    assert "nomes.setdefault" in bloco, "o nome da API, quando existe, tem precedência"
