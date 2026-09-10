# -*- coding: utf-8 -*-
"""O NÚCLEO da régua de tracker, que decidia número na tela sem um teste sequer (varredura de 09/09/2026).

São quatro funções pequenas de que TUDO depende — overview, cards, gráfico, disponibilidade, ronda e o book de
perdas passam por elas — e nenhuma tinha teste:

  _amp_robusta          amplitude do dia aparada (p02–p98): é ela que separa "linha reta" de "girou"
  _trk_marca_mov_recente prova de movimento recente do tracker × da frota
  _trk_exonera_onalvo   rebaixa parado→normal quem está EM CIMA DO ALVO e provou que se move
  _trk_daykey/_g_ultimo_dia  isola o ÚLTIMO dia num gráfico multi-dia antes de classificar

Os casos abaixo são os que a própria casa documentou nos comentários (SMP100 Tracker 82, TIM100 trk 7/21,
Sete Lagoas 1.38, Santo Inácio XII trk 22/40) — se algum dia a régua mudar sem querer, é aqui que estoura.
"""
import app


# ── _amp_robusta ────────────────────────────────────────────────────────────────────────────────────
def test_amp_robusta_apara_glitch_de_telemetria():
    """Caso SMP100 Tracker 82 (07/07): reto o dia todo, com meia dúzia de leituras podres. A amplitude CRUA
    passava de TRK_PARADO_AMP e o tracker escapava de 'parado'; a aparada p02–p98 devolve a linha reta."""
    reto = [-15.5] * 100
    assert app._amp_robusta(reto) == 0.0
    sujo = reto[:] + [-31.6, -0.2, 40.0, -44.0]                 # 4 glitches em 104 leituras
    assert (max(sujo) - min(sujo)) > app.TRK_PARADO_AMP, "o caso perdeu a graça: a amplitude crua tem de ser grande"
    assert app._amp_robusta(sujo) < app.TRK_PARADO_AMP2, "glitch inflou a amplitude e o travado escaparia de parado"


def test_amp_robusta_serie_curta_usa_o_range_cru():
    """Menos de 20 pontos não tem o que aparar — e aparar destruiria o sinal."""
    assert app._amp_robusta([-50.0, 0.0, 50.0]) == 100.0
    assert app._amp_robusta([1.0]) is None and app._amp_robusta([]) is None
    assert app._amp_robusta([None, 3.0, None, 7.0]) == 4.0        # None não conta


def test_amp_robusta_nao_estoura_indice_no_limite_dos_20():
    """v[int(len*0.98)] é o topo da faixa: com exatamente 20 e com 21 pontos o índice tem de existir."""
    for n in (20, 21, 49, 50, 51):
        assert app._amp_robusta([float(i) for i in range(n)]) is not None, f"quebrou com {n} pontos"


# ── _trk_marca_mov_recente ──────────────────────────────────────────────────────────────────────────
def _pts(ini, fim, y0, y1, passo=10):
    n = max(1, (fim - ini) // passo)
    return [{"x": f"2026-09-09T{(ini + k * passo) // 60:02d}:{(ini + k * passo) % 60:02d}:00",
             "y": round(y0 + (y1 - y0) * k / n, 2)} for k in range(n + 1)]


def test_marca_mov_recente_separa_quem_gira_de_quem_congelou():
    """A frota gira na última janela; um tracker acompanha e o outro está parado no mesmo ângulo."""
    g = {f"Tracker {i}": _pts(6 * 60, 18 * 60, -50, 50) for i in range(1, 6)}
    # sobe até 16h20 e congela em 30° — a janela recente (90 min antes do último ponto) fica toda plana
    g["Tracker 9"] = _pts(6 * 60, 16 * 60 + 20, -50, 30) + _pts(16 * 60 + 30, 18 * 60, 30, 30)
    lst = [{"id": n} for n in g]
    app._trk_marca_mov_recente(lst, g)
    por = {t["id"]: t for t in lst}
    assert por["Tracker 1"]["_mov_rec"] > 0, "quem girou na janela tem de acusar movimento"
    assert por["Tracker 9"]["_mov_rec"] == 0.0, "quem congelou não pode acusar movimento recente"
    assert por["Tracker 1"]["_mov_frota"] == por["Tracker 9"]["_mov_frota"], "a frota é a MESMA para todos"
    # amplitude do dia na janela 06–18h: ~100°, e não exatamente 100 porque o p02–p98 apara as pontas —
    # é justamente a aparação que faz o glitch não inflar a amplitude do travado
    assert 90.0 < por["Tracker 1"]["_amp_dia"] < 100.0


def test_marca_mov_recente_sem_curva_nao_anota_nada():
    """Sem gráfico a exoneração tem de se comportar como antes — nada de campo pela metade."""
    lst = [{"id": "Tracker 1"}]
    app._trk_marca_mov_recente(lst, {})
    assert lst == [{"id": "Tracker 1"}]


# ── _trk_exonera_onalvo ─────────────────────────────────────────────────────────────────────────────
def _trk(nome, status="parado", disp=0.0, amp=None, mov=None, frota=None, mudo=False):
    t = {"id": nome, "status": status, "disparidade": disp, "sem_comunicacao": mudo}
    if amp is not None:
        t["_amp_dia"] = amp
    if mov is not None:
        t["_mov_rec"], t["_mov_frota"] = mov, frota
    return t


def test_exonera_quem_travou_de_manha_e_voltou_ao_alvo():
    """Caso TIM100 trk 7/21 (30/07): percorreu o dia (amplitude grande), está em cima do alvo agora e a frota
    também parou de girar — não é ação de campo."""
    lst = [_trk("Tracker 7", disp=2.0, amp=90.0, mov=0.0, frota=1.0)]
    assert app._trk_exonera_onalvo(lst) == 1
    assert lst[0]["status"] == "normal"


def test_nao_exonera_quem_nunca_girou_mesmo_em_cima_do_alvo():
    """Caso Santo Inácio XII (05/08): a frota estacionou no stow e os travados caíam dentro dos 12° — mas
    amplitude ~0 no dia inteiro é congelamento, não 'voltou'. O lugar onde ele parou não é prova."""
    lst = [_trk("Tracker 22", disp=1.5, amp=0.4, mov=0.0, frota=1.0)]
    assert app._trk_exonera_onalvo(lst) == 0
    assert lst[0]["status"] == "parado"


def test_nao_exonera_congelado_com_a_frota_girando():
    """A frota gira agora e ele não: está congelado num ângulo pelo qual a frota está passando."""
    lst = [_trk("Tracker 5", disp=3.0, amp=80.0, mov=0.5, frota=40.0)]     # 0,5 < 25% de 40
    assert app._trk_exonera_onalvo(lst) == 0
    assert lst[0]["status"] == "parado"


def test_nao_exonera_longe_do_alvo_nem_sem_comunicacao():
    lst = [_trk("Tracker 1", disp=24.0, amp=90.0, mov=0.0, frota=1.0),      # fora dos 12°
           _trk("Tracker 2", disp=1.0, amp=90.0, mov=0.0, frota=1.0, mudo=True),
           _trk("Tracker 3", disp=None, amp=90.0, mov=0.0, frota=1.0)]      # sem alvo confiável
    assert app._trk_exonera_onalvo(lst) == 0
    assert [t["status"] for t in lst] == ["parado", "parado", "parado"]


def test_exoneracao_marca_a_provisoriedade_para_o_alvo_mediana_desfazer():
    """A exoneração aqui usa o alvo CRU do supervisório; o _trk_alvo_mediana a desfaz e reavalia com o alvo
    bom. A marca `_parado_curva` é o que torna isso possível — sem ela a usina com alvo furado ficava normal."""
    lst = [_trk("Tracker 7", disp=2.0, amp=90.0, mov=0.0, frota=1.0)]
    app._trk_exonera_onalvo(lst)
    assert lst[0].get("_parado_curva") is True


# ── _trk_daykey / _trk_g_ultimo_dia ─────────────────────────────────────────────────────────────────
def test_daykey_le_iso_e_rfc():
    assert app._trk_daykey("2026-09-09T07:15:00") == "20260909"
    assert app._trk_daykey("Wed, 09 Sep 2026 07:15:00 GMT") == "20260909"
    assert app._trk_daykey("9 Sep 2026") == "20260909", "dia sem zero à esquerda tem de casar"
    assert app._trk_daykey("07:15") == ""


def test_g_ultimo_dia_isola_o_dia_mais_recente():
    """O classificador é minute-of-day: com dois dias concatenados ele mistura a manhã de um com a tarde do
    outro. O gráfico multi-dia (De/Até até 5 dias) depende disto para colorir o dia certo."""
    g = {"Tracker 1": [{"x": "2026-09-08T09:00:00", "y": -10.0}, {"x": "2026-09-09T09:00:00", "y": 10.0}],
         "Tracker 2": [{"x": "2026-09-08T09:00:00", "y": -12.0}]}
    ult = app._trk_g_ultimo_dia(g)
    assert [p["y"] for p in ult["Tracker 1"]] == [10.0]
    assert ult["Tracker 2"] == [], "tracker sem leitura no último dia fica VAZIO, não some"
    um_dia = {"Tracker 1": [{"x": "2026-09-09T09:00:00", "y": 1.0}]}
    assert app._trk_g_ultimo_dia(um_dia) is um_dia, "um dia só volta o próprio objeto (sem cópia à toa)"
