# gemeo/tests/test_modelar_eventos.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from golden import G, esperado_de_placa, sem_gate, trk_inv_mro100, veredito  # noqa: E402
from sintetico import grade_sintetica  # noqa: E402
from gemeo.modelar import decomposicao as dc  # noqa: E402
from gemeo.modelar import esperado, eventos, gate  # noqa: E402

P = dc.ParamsDecomp(f_direta_fixa=0.6)
MAPA = {2001: 1001, 2002: 1002}
UNIVERSO = {1001: [3101, 3102, 3103, 3104], 1002: []}   # strings instaladas, como o job traz dos 30 dias
H = 0.25


def _tudo(g):
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    r = sem_gate(g)
    esp = esperado.esperado_por_inversor(g, r, params)
    return r, esp, dc.decompor(g, esp, MAPA, P, instaladas=UNIVERSO)


def _do_tipo(evs, tipo):
    return [e for e in evs if e.tipo == tipo]


def test_severidade_pelo_kwh_sobre_o_esperado():
    assert eventos.severidade(5.0, 1000.0) == "leve" and eventos.severidade(30.0, 1000.0) == "media"
    assert eventos.severidade(60.0, 1000.0) == "grave" and eventos.severidade(0.0, 0.0) == "leve"


def test_sensor_e_cobertura_viram_evento_grave_de_dia_inteiro():
    g = grade_sintetica(); r, esp, d = _tudo(g)
    dia = g.indice[0].tz_convert("America/Belem").date()
    r.motivo_dia = {dia: "poa_ghi"}; r.razao_dia = {dia: 0.12}
    evs = eventos.detectar(g, r, esp, d)
    ev = _do_tipo(evs, "sensor_em_falha")
    assert len(ev) == 1 and ev[0].severidade == "grave" and ev[0].equipamento_id is None and ev[0].ini == g.indice[0]
    assert ev[0].fim == g.indice[-1] + pd.Timedelta(minutes=15) and ev[0].detalhe["razao_poa_ghi"] == 0.12
    r.motivo_dia = {dia: "cobertura"}
    assert len(_do_tipo(eventos.detectar(g, r, esp, d), "sem_cobertura")) == 1


def test_inversor_parado_o_dia_inteiro():
    g = grade_sintetica(); g.inv_p[1001] = 0.0
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "inversor_parado")
    assert [e.equipamento_id for e in ev] == [1001]
    assert ev[0].kwh == pytest.approx(float(d.parado[1001].sum() * H), rel=1e-6) and ev[0].severidade == "grave"
    assert ev[0].ini == g.indice[0] and ev[0].fim == g.indice[-1] + pd.Timedelta(minutes=15)


def test_inversor_parado_de_meia_hora_nao_e_evento_o_de_uma_hora_e():
    """A regra virou CORRIDA de slots (04/09/2026): a CPP100 desligou 8 de 12 inversores por 4 h em 03/09 e a regra
    antiga, de >= 90 % dos slots com sol do dia, nao emitia assinatura nenhuma. Abaixo de 1 h continua sendo ruido."""
    g = grade_sintetica(); g.inv_p.iloc[:2, 0] = 0.0                  # 30 min parado
    r, esp, d = _tudo(g)
    assert not _do_tipo(eventos.detectar(g, r, esp, d), "inversor_parado")
    g = grade_sintetica(); g.inv_p.iloc[2:6, 0] = 0.0                 # 1 h parado no meio do dia
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "inversor_parado")
    assert len(ev) == 1 and ev[0].equipamento_id == 1001
    assert ev[0].ini == g.indice[2] and ev[0].fim == g.indice[5] + pd.Timedelta(minutes=15)   # a janela REAL da parada
    assert ev[0].detalhe["slots"] == 4 and ev[0].detalhe["dia_inteiro"] is False
    assert ev[0].kwh == pytest.approx(float(d.parado[1001].iloc[2:6].sum() * H), rel=1e-6)


def test_duas_paradas_no_mesmo_dia_viram_dois_eventos():
    g = grade_sintetica(); g.inv_p.iloc[0:4, 0] = 0.0; g.inv_p.iloc[5:8, 0] = 0.0   # 1 h, volta 15 min, para de novo
    r, esp, d = _tudo(g)
    ev = sorted(_do_tipo(eventos.detectar(g, r, esp, d), "inversor_parado"), key=lambda e: e.ini)
    assert len(ev) == 1 and ev[0].ini == g.indice[0]        # a 2a corrida tem 3 slots (45 min): fica de fora


def test_inversor_abaixo_dos_pares_por_tres_dias():
    g = grade_sintetica(dias=3); g.inv_p[1002] = 100.0
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "inversor_abaixo")
    assert [e.equipamento_id for e in ev] == [1002] and ev[0].fim is None and ev[0].ini == g.indice[0]
    assert ev[0].kwh == pytest.approx(float((esp[1002] - 100.0).sum() * H), rel=1e-6) and len(ev[0].detalhe["razoes"]) == 3
    g = grade_sintetica(dias=3); g.inv_p.iloc[8:, 1] = 100.0          # so 2 dias abaixo
    r, esp, d = _tudo(g)
    assert not _do_tipo(eventos.detectar(g, r, esp, d), "inversor_abaixo")


def test_tracker_fora_do_alvo_exige_uma_hora_seguida():
    g = grade_sintetica(); g.trk_ang[2002] = [50.0] * 6 + [20.0] * 2
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "tracker_fora_alvo")
    assert [e.equipamento_id for e in ev] == [2002] and ev[0].fim == g.indice[5] + pd.Timedelta(minutes=15)
    assert ev[0].kwh == pytest.approx(float(d.perda_trk[2002].iloc[:6].sum() * H), rel=1e-6) and ev[0].detalhe["excesso_max"] == pytest.approx(30.0, abs=1e-6)
    g = grade_sintetica(); g.trk_ang[2002] = [50.0] * 2 + [20.0] * 6
    r, esp, d = _tudo(g)
    assert not _do_tipo(eventos.detectar(g, r, esp, d), "tracker_fora_alvo")


def test_string_sem_corrente_o_dia_inteiro():
    g = grade_sintetica(); g.str_i[3104] = 0.0
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "string_sem_corrente")
    assert [e.equipamento_id for e in ev] == [3104] and ev[0].detalhe["inversor_id"] == 1001
    assert ev[0].kwh == pytest.approx(float(d.string[1001].sum() * H), rel=1e-6)
    g = grade_sintetica(); g.str_i.iloc[:4, 3] = 0.0                     # metade do dia nao e 'sem corrente'
    r, esp, d = _tudo(g)
    assert not _do_tipo(eventos.detectar(g, r, esp, d), "string_sem_corrente")


@pytest.mark.parametrize("arq", ["mro100_2026-08-26.json", "mro100_2026-08-31.json", "mro100_2026-09-01.json"])
def test_golden_mro100_eventos(arq):
    g, r, esp = esperado_de_placa(G / arq)
    v = veredito(G / arq)
    d = dc.decompor(g, esp, trk_inv_mro100(g), dc.ParamsDecomp())
    evs = eventos.detectar(g, r, esp, d)
    assert {e.equipamento_id for e in _do_tipo(evs, "inversor_parado")} == {1000 + int(n) for n in v["inv_parado"]}
    # 31/08: o tracker 4 ficou o dia inteiro em 15 graus com a frota indo de -55 a +55 — hoje sai como 'tracker_travado', nao
    # como corridas de 'fora do alvo' (13/09/2026); o veredito e "teve evento de tracker", de qualquer um dos tipos
    assert {2000 + t for t in v["trackers"]} <= {e.equipamento_id for e in evs if e.tipo.startswith("tracker_")}
    assert len(_do_tipo(evs, "string_sem_corrente")) == v["strings_sem_corrente"]
    assert not _do_tipo(evs, "sensor_em_falha") and not _do_tipo(evs, "sem_cobertura")


def test_tracker_com_angulo_congelado_o_dia_todo_e_travado_e_nao_fora_do_alvo():
    """Sete Lagoas, 11/09/2026: TRK51 ficou em 25,8 graus das 9h as 17h enquanto a frota foi de -46 a +55 — um tracker
    TRAVADO (comunica, nao mexe), que saia como varias corridas de 'fora do alvo'. Angulo constante o dia inteiro com a frota
    se mexendo e UM evento 'tracker_travado' no dia, com a perda do dia; e nao se repete como fora_alvo."""
    g = grade_sintetica()
    g.trk_ang[2001] = list(np.linspace(-40, 40, 8)); g.trk_ang[2003] = list(np.linspace(-40, 40, 8))
    g.trk_ang[2002] = 25.8
    r, esp, d = _tudo(g)
    evs = eventos.detectar(g, r, esp, d)
    trav = _do_tipo(evs, "tracker_travado")
    assert len(trav) == 1 and trav[0].equipamento_id == 2002 and trav[0].kwh > 0
    assert abs(trav[0].detalhe["angulo"] - 25.8) < 1e-6
    assert not [e for e in _do_tipo(evs, "tracker_fora_alvo") if e.equipamento_id == 2002]
    assert abs(trav[0].kwh - float(d.perda_trk[2002].sum() * eventos.H)) < 1e-6


def test_tracker_congelado_em_zero_e_sem_comunicacao_com_perda_incerta():
    """Araputanga, 11/09/2026: TRK5 veio 0,0 grau fixo o dia inteiro e a PV Plataforma marcava aComm=1 — nao e um angulo, e um
    sensor mudo. Vira 'tracker_sem_comunicacao', e a estimativa de perda fica marcada como incerta."""
    g = grade_sintetica()
    g.trk_ang[2001] = list(np.linspace(-40, 40, 8)); g.trk_ang[2003] = list(np.linspace(-40, 40, 8))
    g.trk_ang[2002] = 0.0
    r, esp, d = _tudo(g)
    evs = eventos.detectar(g, r, esp, d)
    mudo = _do_tipo(evs, "tracker_sem_comunicacao")
    assert len(mudo) == 1 and mudo[0].equipamento_id == 2002 and mudo[0].detalhe.get("estimativa") == "incerta"
    assert not _do_tipo(evs, "tracker_travado") and not [e for e in _do_tipo(evs, "tracker_fora_alvo") if e.equipamento_id == 2002]


def test_frota_toda_em_stow_nao_e_tracker_travado():
    """Dia de vento/nuvem com a frota inteira parada no mesmo angulo: ninguem esta travado — e a amplitude da frota que decide."""
    g = grade_sintetica()                                                # os tres em 20 graus o dia todo
    r, esp, d = _tudo(g)
    evs = eventos.detectar(g, r, esp, d)
    assert not _do_tipo(evs, "tracker_travado") and not _do_tipo(evs, "tracker_sem_comunicacao")


# ── SENSOR CONGELADO (17/09/2026) ──────────────────────────────────────────────────────────────
# A POA medida e a ENTRADA do modelo: piranometro travado nao gera um evento, gera um ESPERADO
# INTEIRO errado. O `sensor_em_falha` que ja existia e outra coisa (razao POA/GHI fora da faixa) e
# nao pega sensor repetindo um valor PLAUSIVEL. Regra: valor repetido com sol, dentro da janela.

def test_sensor_congelado_quando_a_poa_repete_com_sol():
    g = grade_sintetica()
    g.estacao["poa"] = 700.0          # travada o dia inteiro, valor plausivel
    r, esp, d = _tudo(g)
    evs = eventos.detectar(g, r, esp, d)
    achados = _do_tipo(evs, "sensor_congelado")
    assert achados, "POA repetindo com sol tem de virar evento"
    assert achados[0].severidade == "grave"
    assert achados[0].detalhe.get("medida") == "poa"


def test_sensor_congelado_nao_dispara_com_sensor_variando():
    """A grade sintetica nasce com POA e GHI CONSTANTES (700), que o detector — corretamente —
    acusa. Para provar o negativo e preciso variar os dois: sensor que se mexe nao e congelado."""
    import numpy as np
    g = grade_sintetica()
    n = len(g.indice)
    g.estacao["poa"] = 700.0 + np.arange(n) * 3.0
    g.estacao["ghi"] = 600.0 + np.arange(n) * 2.5
    r, esp, d = _tudo(g)
    evs = eventos.detectar(g, r, esp, d)
    assert not _do_tipo(evs, "sensor_congelado")


def test_sensor_congelado_pega_o_GHI_tambem():
    """Nao e so a POA: o GHI entra no gate POA/GHI, entao travado ali tambem corrompe o julgamento."""
    import numpy as np
    g = grade_sintetica()
    g.estacao["poa"] = 700.0 + np.arange(len(g.indice)) * 3.0   # POA saudavel
    r, esp, d = _tudo(g)                                        # GHI segue constante por construcao
    achados = _do_tipo(eventos.detectar(g, r, esp, d), "sensor_congelado")
    assert achados and achados[0].detalhe.get("medida") == "ghi"


def test_sensor_congelado_ignora_zero_a_noite():
    """Sem sol a POA e zero para todo mundo: acusar isso seria alarme todas as madrugadas.

    17/09/2026: a fixture desta prova nao era noite — tinha os dois inversores gerando 180 kW com a
    POA em zero, que e outra coisa (ver o teste seguinte). Noite de verdade e sem geracao."""
    g = grade_sintetica()
    g.estacao["poa"] = 0.0
    g.estacao["ghi"] = 0.0
    g.inv_p = g.inv_p * 0.0                       # noite: ninguem gerando
    r, esp, d = _tudo(g)
    evs = eventos.detectar(g, r, esp, d)
    assert not _do_tipo(evs, "sensor_congelado")


def test_usina_gerando_com_irradiancia_em_zero_e_sensor_morto():
    """O outro lado da mesma moeda: 180 kW saindo dos inversores com POA e GHI em zero nao e noite,
    e piranometro morto — e o esperado do gemeo nasce dessa POA. A regra antiga nunca via este caso
    porque perguntava ao proprio sensor se era dia (a MTS100 tem GHI fixo em 0,0 desde sempre)."""
    g = grade_sintetica()                          # inversores em 180 kW por construcao
    g.estacao["poa"] = 0.0
    g.estacao["ghi"] = 0.0
    r, esp, d = _tudo(g)
    achados = _do_tipo(eventos.detectar(g, r, esp, d), "sensor_congelado")
    assert achados and achados[0].detalhe.get("valor") == 0.0


def test_sensor_congelado_nao_chama_a_madrugada_de_dia_por_causa_do_proprio_sensor():
    """17/09/2026, achado no banco de producao: a Ibate 2 apareceu com POA congelada em 464,04 e GHI
    em 467,24 das 00:00 as 00:00 — 96 slots, o dia inteiro. O congelamento e REAL (287 leituras, UM
    valor distinto), mas a JANELA saiu errada por circularidade: `diurno` vinha de `poa > 50 ou
    ghi > 50`, isto e, do proprio sensor sob suspeita. Travado num valor plausivel, ele declara que
    e dia a noite toda.

    A producao dos inversores nao depende do piranometro: se a usina gera, o sol esta la."""
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2026-08-28T00:00", periods=96, freq="15min", tz="UTC")
    g = grade_sintetica()
    g.indice = idx
    g.estacao = pd.DataFrame({"poa": 464.04, "ghi": 467.24, "temp_modulo": 45.0, "temp_ar": 30.0}, index=idx)
    # inversores so geram das 09:00 as 21:00 UTC (dia em Belem); o resto e noite de verdade
    hora = idx.hour
    gera = np.where((hora >= 9) & (hora < 21), 180.0, 0.0)
    g.inv_p = pd.DataFrame({1001: gera, 1002: gera}, index=idx)
    g.inv_e = pd.DataFrame(index=idx)
    g.trk_ang = pd.DataFrame({2001: 20.0, 2002: 20.0, 2003: 20.0}, index=idx)
    g.trk_alvo = g.trk_ang.copy()
    g.str_i = pd.DataFrame({3101: 8.0, 3102: 8.0, 3103: 8.0, 3104: 8.0}, index=idx)

    r, esp, d = _tudo(g)
    achados = _do_tipo(eventos.detectar(g, r, esp, d), "sensor_congelado")
    assert achados, "a POA congelada continua tendo de ser detectada"
    e = achados[0]
    assert e.ini.hour >= 9 and e.fim.hour <= 21, f"janela invadiu a noite: {e.ini} -> {e.fim}"
    assert e.detalhe["slots"] <= 48, f"{e.detalhe['slots']} slots num dia de 12 h de sol"
