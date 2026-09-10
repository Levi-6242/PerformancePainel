# -*- coding: utf-8 -*-
"""A régua que produz o MOSAICO e os cards do tempo real, que também não tinha teste (varredura de 09/09/2026).

`_macro_dif`, `_macro_status` e `_macro_item` decidem, por usina: o déficit de strings, a cor do bloco e o que
entra no rollup. É de onde saem os números que o Levi confere contra a tabela do Monitoramento — e cada regra
de SILÊNCIO aqui (sem produção, sem comunicação, sem visão) existe porque um dia mentiu na tela.

`_frota_acordou` é o portão que autoriza dizer "parado": sem ele, usina inteira dormindo de madrugada viraria
frota travada.
"""
import app


# ── _macro_dif: o déficit é ativas − esperadas, igual em todas as fontes ────────────────────────────
def test_macro_dif_e_igual_em_todas_as_fontes():
    """Antes preferia 'diferenca_operante' (só inversores produzindo), campo que só API PV/PG calculam — o
    mesmo tracker de régua dava número diferente por fonte. Hoje é sempre ativas − esperadas."""
    assert app._macro_dif({"strings_ativas": 210, "str_esp": 216}) == -6
    assert app._macro_dif({"strings_ativas": 216, "str_esp": 216}) == 0
    assert app._macro_dif({"strings_ativas": 210, "str_esp": 216, "diferenca_operante": 0}) == -6


def test_macro_dif_sem_visao_nao_tem_deficit():
    """String Box sem visão por string não tem `str_esp` — e 'sem esperado' não é 'zero faltando'."""
    assert app._macro_dif({"strings_ativas": 0, "str_esp": None}) is None
    assert app._macro_dif({"strings_ativas": None, "str_esp": 216}) is None
    assert app._macro_dif({}) is None


# ── _macro_status: as três portas de silêncio, na ordem ────────────────────────────────────────────
def test_macro_status_sem_comunicacao_vence_tudo():
    assert app._macro_status({"sem_dados": True, "strings_ativas": 0, "str_esp": 216}) == "sem_comm"
    assert app._macro_status({"falha_comunicacao": True, "inv_off": 5}) == "sem_comm"


def test_macro_status_sem_visao_e_ok_e_nao_critico():
    """Céu Azul / Ouro Branco: a combiner não é exposta, então 0 ativas É o esperado — pintar de crítico
    encheria o painel de alarme falso todo dia."""
    assert app._macro_status({"sem_visao": True, "strings_ativas": 0, "str_esp": 216}) == "ok"


def test_macro_status_deficit_5_e_o_corte_entre_atencao_e_critico():
    base = {"strings_ativas": 0, "str_esp": 0}
    assert app._macro_status(dict(base, strings_ativas=212, str_esp=216)) == "atencao"     # −4
    assert app._macro_status(dict(base, strings_ativas=211, str_esp=216)) == "critico"     # −5
    assert app._macro_status(dict(base, strings_ativas=216, str_esp=216)) == "ok"


# ── _macro_item: o silêncio tem de chegar ao CAMPO que a tela soma ─────────────────────────────────
def _item(**kw):
    r = {"usina": "Teste 1", "plant_id": 1, "strings_ativas": 100, "str_esp": 120,
         "qtd_inversores": 4, "inv_off": 0, "ultima_leitura": "2026-09-09 12:00"}
    r.update(kw)
    return app._macro_item("API PV", r)


def test_macro_item_zera_faltando_quando_a_usina_esta_calada():
    """Regra de ouro do mosaico: usina sem comunicação/sem produção/sem visão NÃO entra no ranking de
    strings faltando — senão a frota inteira aparece 'faltando' toda madrugada. É o campo já silenciado
    que o rollup soma (por isso `_somar_partes_da_usina` soma `strings_faltando`, não Σativas−Σesperadas)."""
    assert _item()["strings_faltando"] == 20
    assert _item(sem_dados=True)["strings_faltando"] == 0
    assert _item(sem_visao=True)["strings_faltando"] == 0
    for it in (_item(sem_dados=True), _item(sem_visao=True)):
        assert it["diferenca"] is not None or it["str_esp"] is None    # a diferença crua continua exposta


def test_macro_item_nunca_devolve_faltando_negativo():
    """Usina com MAIS ativas que esperadas (cadastro desatualizado) não pode virar déficit negativo."""
    it = _item(strings_ativas=130, str_esp=120)
    assert it["strings_faltando"] == 0 and it["diferenca"] == 10


def test_macro_item_preserva_o_que_o_drawer_e_o_tempo_real_leem():
    """Contrato de campos: o drawer, o /tempo-real e o rollup leem estes nomes. Se algum sumir, a tela cala
    sem erro nenhum — foi assim que a Indaiatuba passou meses contando só uma fatia."""
    it = _item()
    for campo in ("fonte", "usina", "plant_id", "status", "sev", "causa", "strings_ativas", "str_esp",
                  "diferenca", "strings_faltando", "inv_off", "qtd_inversores", "ultima_leitura", "sem_visao"):
        assert campo in it, f"o campo {campo} sumiu do item do macro"


# ── _frota_acordou: as duas portas ─────────────────────────────────────────────────────────────────
def test_frota_acordou_pela_mediana():
    """Porta 1: metade da frota girou de verdade (mediana > TRK_ALVO_MOVE_MIN = 30°)."""
    assert app._frota_acordou({f"t{i}": 90.0 for i in range(6)}) is True
    assert app._frota_acordou([0.2, 0.3, 0.1, 0.4]) is False, "frota parada de madrugada não 'acordou'"
    assert app._frota_acordou({}) is False and app._frota_acordou([None, None]) is False


def test_frota_acordou_pela_porta_do_dia_passado():
    """Porta 2: num dia PASSADO com cobertura, frota que nunca girou está TRAVADA, não dormindo. Sem esta
    porta, a usina com a maioria travada (SMP100) mostrava 0 parados enquanto a disponibilidade dizia 3%."""
    amps = [0.2, 0.3, 0.1]
    assert app._frota_acordou(amps, dia_coberto=True, data_ref="2026-01-02") is True
    assert app._frota_acordou(amps, dia_coberto=True, data_ref="02/01/2026") is True, "aceita DD/MM/YYYY"
    assert app._frota_acordou(amps, dia_coberto=False, data_ref="2026-01-02") is False, "sem cobertura não julga"


def test_sem_producao_so_de_dia_e_so_com_telemetria(monkeypatch):
    """'Sem produção' é potência ~0 COM telemetria fresca e COM sol. Sem esse par de guardas, toda usina
    viraria 'parada' à noite e toda usina muda viraria 'parada' de dia."""
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    parada = {"pot_med": 0.0, "qtd_inversores": 8, "strings_ativas": 0}
    assert app._macro_sem_producao(parada) is True
    assert app._macro_sem_producao(dict(parada, sem_dados=True)) is False, "usina muda não é 'parada'"
    assert app._macro_sem_producao(dict(parada, sem_visao=True)) is False, "sem visão não se afirma nada"
    assert app._macro_sem_producao(dict(parada, pot_med=500.0)) is False
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: False)
    assert app._macro_sem_producao(parada) is False, "de noite ninguém produz — não é defeito"


def test_sem_producao_na_fonte_sem_potencia_cai_nas_strings(monkeypatch):
    """A 2C não manda potência ativa: aí o sinal é 0 strings ativas de dia, com inversores cadastrados."""
    monkeypatch.setattr(app, "_macro_eh_dia", lambda r: True)
    assert app._macro_sem_producao({"qtd_inversores": 4, "strings_ativas": 0}) is True
    assert app._macro_sem_producao({"qtd_inversores": 4, "strings_ativas": 12}) is False
    assert app._macro_sem_producao({"qtd_inversores": 0, "strings_ativas": 0}) is False, "sem cadastro não julga"


def test_eh_dia_usa_o_relogio_do_SERVIDOR(monkeypatch):
    """Contrato atual, e limitação conhecida: a janela 07–18h é a do servidor (Brasília), não a da usina —
    uma usina no Mato Grosso (−1 h) é julgada pela hora de Brasília. Se um dia isso virar por fuso da usina,
    é este teste que tem de mudar junto."""
    class _H(app.datetime):
        @classmethod
        def now(cls, tz=None):
            return app.datetime(2026, 9, 9, 6, 59)
    monkeypatch.setattr(app, "datetime", _H)
    assert app._macro_eh_dia({"estado": "MT"}) is False
    class _H2(app.datetime):
        @classmethod
        def now(cls, tz=None):
            return app.datetime(2026, 9, 9, 7, 0)
    monkeypatch.setattr(app, "datetime", _H2)
    assert app._macro_eh_dia({"estado": "MT"}) is True


def test_severidade_do_tracker_ordena_a_frota():
    """A ordem do ranking: sem comunicação e severo empatam no topo (0) — usina muda não pode descer para
    'normal' por não ter número. Sem total = 4 (fica no fim, mas antes de nada)."""
    assert app._trk_severidade({"sem_comunicacao": True, "total": 50}) == 0
    assert app._trk_severidade({"severos": 3, "total": 50}) == 0
    assert app._trk_severidade({"leves": 2, "total": 50}) == 1
    assert app._trk_severidade({"fora_media": 1, "total": 50}) == 2
    assert app._trk_severidade({"total": 50}) == 3
    assert app._trk_severidade({"total": 0}) == 4


def test_frota_acordou_hoje_depende_da_hora(monkeypatch):
    """Hoje, a porta 2 só abre depois de TRK_FROTA_ACORDA_HORA — antes disso pode ser só o dia começando."""
    hoje = app.datetime.now().strftime("%Y-%m-%d")

    class _Cedo(app.datetime):
        @classmethod
        def now(cls, tz=None):
            return app.datetime(2026, 9, 9, app.TRK_FROTA_ACORDA_HORA - 1, 0)

    class _Tarde(app.datetime):
        @classmethod
        def now(cls, tz=None):
            return app.datetime(2026, 9, 9, app.TRK_FROTA_ACORDA_HORA + 1, 0)

    monkeypatch.setattr(app, "datetime", _Cedo)
    assert app._frota_acordou([0.2, 0.1], dia_coberto=True, data_ref=hoje) is False
    monkeypatch.setattr(app, "datetime", _Tarde)
    assert app._frota_acordou([0.2, 0.1], dia_coberto=True, data_ref=hoje) is True
