# -*- coding: utf-8 -*-
"""Régua do PADRÃO DE PROPORCIONALIDADE por inversor (10/09/2026) — para as usinas sem visão por string
(String Box com combiner não exposta: Ceilândia 1, Céu Azul, Ouro Branco) e Barretos (sem esperado no cadastro).

A ideia do Levi: "se por padrão aquele inversor opera a 94% do maior, ou 98% em relação aos demais, e cai
10 p.p. ou mais, alerte". O estudo de 30 dias (13 plantas, 132 inversores) mostrou que a razão inversor ÷
mediana da usina é MUITO estável (σ p50 = 1,2 pp, p90 = 4,9 pp), então 10 pp é 2 a 8 desvios acima do ruído.
Os números dos casos abaixo saem desse estudo: Barretos 1 INVERSOR03 a 70 %, Céu Azul II INVERSOR01 a 80 %,
Ceilândia 1.2 SKID 4 INV 5 um dia a 44 %, Barretos 2 INVERSOR19 instável (σ 18 pp)."""
import inv_padrao as ip


def _usina(dias, ratios, base_kwh=500.0, ids=("a", "b", "c", "d", "e")):
    """{dia: {id: kWh}} onde cada inversor gera base_kwh × ratio[id] × fator_do_dia."""
    out = {}
    for i, fator in enumerate(dias):
        d = f"2026-08-{i + 1:02d}"
        out[d] = {k: round(base_kwh * fator * ratios.get(k, 1.0), 1) for k in ids}
    return out


# ── dias válidos ─────────────────────────────────────────────────────────────────────────────────────
def test_dia_de_chuva_forte_nao_entra_no_baseline():
    """Barretos teve 7 dias em 30 com a usina inteira a <25 % do normal: nesses dias a razão vira ruído
    (o INVERSOR20 apareceu a 60 % num dia de 40 kWh) e não pode ensinar nem julgar nada."""
    E = _usina([1.0, 1.0, 0.1, 1.0, 0.2, 1.0], {})
    assert ip.dias_validos(E) == {"2026-08-01", "2026-08-02", "2026-08-04", "2026-08-06"}


def test_dia_sem_nenhuma_leitura_nao_e_valido():
    E = _usina([1.0, 1.0, 1.0], {})
    E["2026-08-04"] = {"a": None, "b": None}
    assert "2026-08-04" not in ip.dias_validos(E)


# ── baseline ─────────────────────────────────────────────────────────────────────────────────────────
def test_baseline_e_a_mediana_da_razao_para_a_mediana_da_usina():
    """Caso Barretos 1 INVERSOR03: 70 % dos pares todos os dias → base 70, σ ~0."""
    E = _usina([1.0] * 10 + [0.6] * 5, {"c": 0.70})
    b = ip.baseline(E)
    assert b["c"]["base"] == 70.0 and b["c"]["sigma"] < 0.5 and b["c"]["n"] == 15
    assert b["a"]["base"] == 100.0


def test_baseline_ignora_dia_de_chuva_e_leitura_faltando():
    E = _usina([1.0] * 8 + [0.1], {"c": 0.70})
    E["2026-08-03"]["c"] = None                       # um dia sem leitura desse inversor
    b = ip.baseline(E)
    assert b["c"]["n"] == 7                           # 9 dias − 1 chuva − 1 sem leitura


def test_baseline_com_poucos_dias_nao_julga():
    """Menos de INV_PADRAO_MIN_DIAS dias válidos → sem base (não inventa padrão com 3 pontos)."""
    E = _usina([1.0] * 3, {"c": 0.70})
    assert ip.baseline(E)["c"]["base"] is None


def test_id_que_nunca_gerou_nao_entra_na_mediana_da_usina():
    """O plant_devices de Barretos lista 31 'INVERTER' para 20 reais (duplicatas, 'xxx', '(old)'). Um id que
    nunca reporta energia não pode puxar a mediana da usina para baixo nem aparecer com base."""
    E = _usina([1.0] * 10, {})
    for d in E:
        E[d]["fantasma"] = None
    b = ip.baseline(E)
    assert "fantasma" not in b
    assert b["a"]["base"] == 100.0


# ── classificação de um dia ───────────────────────────────────────────────────────────────────────────
def test_queda_de_10pp_e_atencao_e_de_20pp_e_critico():
    base = {"a": {"base": 91.0, "sigma": 2.0, "n": 20}, "b": {"base": 100.0, "sigma": 1.0, "n": 20}}
    dia = {"a": 68.0 * 5, "b": 100.0 * 5, "c": 100.0 * 5}     # mediana do dia = 500 → a está a 68 %
    r = ip.classificar_dia(dia, base)
    assert r["a"]["status"] == "critico" and r["a"]["delta"] == -23.0 and r["a"]["razao"] == 68.0
    dia["a"] = 80.0 * 5                                          # 80 % → −11 pp
    assert ip.classificar_dia(dia, base)["a"]["status"] == "atencao"
    dia["a"] = 88.0 * 5                                          # 88 % → −3 pp
    assert ip.classificar_dia(dia, base)["a"]["status"] == "ok"


def test_inversor_instavel_usa_limiar_de_dois_sigma():
    """Barretos 2 INVERSOR19: σ = 18 pp. Com o limiar fixo de 10 pp ele alertaria em 5 dos 30 dias — spam.
    Para ele o limiar é max(10, 2σ) = 36 pp."""
    base = {"a": {"base": 100.0, "sigma": 18.0, "n": 20}, "b": {"base": 100.0, "sigma": 1.0, "n": 20}}
    dia = {"a": 70.0, "b": 100.0, "c": 100.0}
    r = ip.classificar_dia(dia, base)
    assert r["a"]["status"] == "ok" and r["a"]["limiar"] == 36.0
    assert ip.classificar_dia({"a": 60.0, "b": 100.0, "c": 100.0}, base)["a"]["status"] == "atencao"


def test_cronicamente_baixo_e_etiqueta_nao_alerta_todo_dia():
    """Barretos 1 INVERSOR03 a 70 % há 30 dias: é 'cronico', não um alerta novo a cada manhã."""
    base = {"a": {"base": 70.0, "sigma": 2.0, "n": 20}, "b": {"base": 100.0, "sigma": 1.0, "n": 20}}
    r = ip.classificar_dia({"a": 70.0, "b": 100.0, "c": 100.0}, base)
    assert r["a"]["status"] == "ok" and r["a"]["cronico"] is True
    assert r["b"]["cronico"] is False


def test_dia_de_chuva_nao_julga_ninguem():
    base = {"a": {"base": 100.0, "sigma": 1.0, "n": 20}}
    r = ip.classificar_dia({"a": 5.0, "b": 8.0, "c": 6.0}, base, tipico_kwh=500.0)
    assert r["a"]["status"] == "sem_julgamento"


def test_inversor_sem_base_nao_e_julgado():
    base = {"a": {"base": None, "sigma": None, "n": 2}}
    r = ip.classificar_dia({"a": 50.0, "b": 100.0, "c": 100.0}, base)
    assert r["a"]["status"] == "sem_base"


# ── avaliação de um dia contra o histórico ANTERIOR a ele ─────────────────────────────────────────────
def test_avaliar_dia_usa_so_os_30_dias_anteriores():
    """O dia julgado não pode ensinar o próprio baseline (senão uma queda de 10 dias vira 'o novo normal'
    devagar). Caso Céu Azul II INVERSOR01: 80 % por semanas e depois volta a 93 % — a volta é +13 pp."""
    E = _usina([1.0] * 20, {"c": 0.80})
    E["2026-08-21"] = {"a": 500.0, "b": 500.0, "c": 465.0, "d": 500.0, "e": 500.0}   # c volta a 93 %
    r = ip.avaliar_dia(E, "2026-08-21")
    assert r["inversores"]["c"]["base"] == 80.0 and r["inversores"]["c"]["delta"] == 13.0
    assert r["dia"] == "2026-08-21" and r["n_dias_base"] == 20


def test_avaliar_dia_resume_o_pior_da_usina():
    E = _usina([1.0] * 20, {})
    E["2026-08-21"] = {"a": 500.0, "b": 500.0, "c": 340.0, "d": 500.0, "e": 500.0}   # c a 68 % → crítico
    r = ip.avaliar_dia(E, "2026-08-21")
    assert r["status"] == "critico" and r["alertas"] == [{"inv": "c", "status": "critico", "razao": 68.0,
                                                          "base": 100.0, "delta": -32.0}]


# ── prévia intraday (Eday parcial de hoje contra o mesmo baseline) ───────────────────────────────────
def test_previa_de_hoje_so_depois_das_14h():
    base = {"a": {"base": 100.0, "sigma": 1.0, "n": 20}, "b": {"base": 100.0, "sigma": 1.0, "n": 20}}
    hoje = {"a": 100.0, "b": 200.0, "c": 200.0}
    assert ip.previa_hoje(hoje, base, hora=13) is None
    r = ip.previa_hoje(hoje, base, hora=14)
    assert r["a"]["status"] == "critico" and r["a"]["previa"] is True


# ── persistência ─────────────────────────────────────────────────────────────────────────────────────
def test_store_guarda_45_dias_e_descarta_o_resto(tmp_path):
    st = ip.Store(str(tmp_path / "inv_padrao.json"))
    for i in range(60):
        dia = f"2026-06-{i + 1:02d}" if i < 30 else f"2026-07-{(i - 30) + 1:02d}"
        st.gravar_dia("p1", dia, {"a": 1.0})
    st.salvar()
    st2 = ip.Store(str(tmp_path / "inv_padrao.json"))
    dias = sorted(st2.dias("p1"))
    assert len(dias) == ip.INV_PADRAO_RETEM_DIAS and dias[0] == "2026-06-16" and dias[-1] == "2026-07-30"


def test_store_recarrega_o_que_outro_processo_gravou(tmp_path):
    """São dois processos: o worker grava os devices, o web só lê. O web carregou o arquivo no boot, antes do worker
    existir — sem recarregar, os inversores apareceriam pelo id numérico da API até alguém reiniciar."""
    caminho = str(tmp_path / "inv_padrao.json")
    web = ip.Store(caminho)
    worker = ip.Store(caminho)
    worker.gravar_devs("p1", {"1": "INVERSOR01"}, "Barretos 1 (83)")
    worker.salvar()
    assert web.devs("p1") == {}
    web.recarregar()
    assert web.devs("p1") == {"1": "INVERSOR01"}


def test_store_sabe_quais_dias_faltam_na_janela():
    st = ip.Store(None)
    st.gravar_dia("p1", "2026-09-05", {"a": 1.0})
    faltam = st.dias_faltando("p1", ate="2026-09-09", janela=5)
    assert faltam == ["2026-09-06", "2026-09-07", "2026-09-08", "2026-09-09"]


def test_tres_dias_seguidos_em_atencao_viram_critico():
    """Uma queda de 12 pp num dia é atenção; a mesma queda sustentada por 3 dias é problema de verdade (fusível,
    MPPT, string box) e sobe para crítico mesmo sem chegar aos 20 pp."""
    E = _usina([1.0] * 20, {})
    for d in ("2026-08-21", "2026-08-22", "2026-08-23"):
        E[d] = {"a": 500.0, "b": 500.0, "c": 440.0, "d": 500.0, "e": 500.0}        # c a 88 % → −12 pp
    assert ip.avaliar_dia(E, "2026-08-21")["inversores"]["c"]["status"] == "atencao"
    r = ip.avaliar_dia(E, "2026-08-23")
    assert r["inversores"]["c"]["status"] == "critico" and r["inversores"]["c"]["dias_seguidos"] == 3


# ── coleta (custom_query energy) ─────────────────────────────────────────────────────────────────────
def test_coletar_dia_traduz_a_resposta_da_api_pv():
    """POST /custom_query {id, data_type:"energy", period:"YYYY-MM", day:N} → [{idinversor, eday}]. A API PV
    devolve erro como DICT (não lista) — isso vira None, para o chamador saber que o dia NÃO foi coletado
    (e não gravar um dia vazio como se fosse "sem geração")."""
    chamadas = []

    def post(payload):
        chamadas.append(payload)
        return [{"idinversor": 364574, "eday": "812.4"}, {"idinversor": 364575, "eday": None},
                {"idinversor": 364576, "eday": 0}]

    assert ip.coletar_dia(post, 297410, "2026-09-09") == {"364574": 812.4, "364575": None, "364576": 0.0}
    assert chamadas == [{"id": 297410, "data_type": "energy", "period": "2026-09", "day": 9}]
    assert ip.coletar_dia(lambda p: {"error": "Invalid id"}, 297410, "2026-09-09") is None
