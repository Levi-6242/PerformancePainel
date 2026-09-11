# -*- coding: utf-8 -*-
"""O pôr do sol não é falha (10/09/2026). Medido às 17:52: 89 de 102 usinas 'críticas' no /api/macro ("N inversores
parados · N strings abaixo") e 300 eventos 'string zerou' numa leitura só do sino às 17:43 — todas as plantas API PV
com pot_med < 2 kW às 18:15. A régua do macro considerava 'dia' até 18h e não olhava o sol; a janela do sino ia até
18:20. Agora o macro e o sino perguntam ao sol.py a elevação solar no ESTADO da usina (Info Geral)."""
import app


def _junco(**extra):
    # Junco (Piauí): pôr do sol ~17:55 de Brasília em setembro
    r = {"usina": "Junco 2.1 (134)", "plant_id": 60560, "qtd_inversores": 4, "inv_off": 4, "strings_ativas": 0,
         "str_esp": 82, "pot_med": 0.0, "ultima_leitura": "2026-09-10 18:12:00", "sem_visao": False}
    r.update(extra)
    return r


def test_estado_da_usina_vem_da_info_geral_pelo_nome_canonico():
    assert app._estado_da_usina("Junco 2.1 (134)") == "Piaui"
    assert app._estado_da_usina("Barretos 2 (83)") == "Sao Paulo"
    assert app._estado_da_usina("Usina Que Nao Existe") is None


def test_macro_ao_anoitecer_nao_e_falha(freeze_now):
    freeze_now("2026-09-10 18:10:00")
    r = _junco()
    assert app._macro_status(r) == "ok"
    assert "sol" in app._macro_causa(r, "ok").lower()
    item = app._macro_item("API PV", r)
    assert item["status"] == "ok" and item["strings_faltando"] == 0


def test_macro_deficit_de_strings_ao_anoitecer_tambem_nao_e_falha(freeze_now):
    """Sem inversor parado, só as strings zerando (dif −82): antes virava 'critico' pela régua de déficit."""
    freeze_now("2026-09-10 18:10:00")
    r = _junco(inv_off=0, pot_med=0.5)
    assert app._macro_status(r) == "ok"


def test_macro_de_dia_a_mesma_usina_continua_sem_producao(freeze_now):
    freeze_now("2026-09-10 14:00:00")
    assert app._macro_status(_junco()) == "sem_producao"
    assert app._macro_status(_junco(inv_off=0, pot_med=50.0)) == "critico"      # 82 strings abaixo com sol alto


def test_sem_comunicacao_continua_valendo_de_noite(freeze_now):
    freeze_now("2026-09-10 18:10:00")
    assert app._macro_status(_junco(falha_comunicacao=True)) == "sem_comm"


def test_usina_sem_estado_cai_na_regua_antiga(freeze_now):
    """Sem estado na Info Geral não dá para perguntar ao sol: vale a janela fixa 07–18h de sempre."""
    freeze_now("2026-09-10 17:30:00")
    r = _junco(usina="Usina Sem Cadastro")
    assert app._macro_status(r) == "sem_producao"


def test_de_noite_nada_se_julga_ao_vivo_mesmo_sem_estado(freeze_now):
    """Visto às 22:40 de 10/09: Santo Antonio do Platina, Corrego do Sapucaia, Alvares Machado e Santo Anastacio
    (estado em BRANCO na Info Geral) seguiam 'críticas' por '357 strings abaixo' — a régua de déficit não tinha
    portão de hora. Fora da janela 07–18h ninguém é julgado ao vivo, com ou sem estado."""
    freeze_now("2026-09-10 22:40:00")
    r = _junco(usina="Usina Sem Cadastro", inv_off=0, pot_med=0.0)
    assert app._macro_status(r) == "ok"
    assert "sol" in app._macro_causa(r, "ok").lower()


def test_causa_de_noite_fica_so_com_o_padrao_do_inversor(freeze_now):
    """Barretos às 22:40: 'Inversor 2.7 a 88 % … · 40 inversor(es) parado(s)' — os 40 parados são a noite."""
    freeze_now("2026-09-10 22:40:00")
    r = _junco(usina="Barretos 2 (83)", inv_off=20, qtd_inversores=20, str_esp=None,
               inv_padrao={"status": "atencao", "dia": "2026-09-09", "cronicos": [],
                           "alertas": [{"inv": "Inversor 2.7", "status": "atencao", "razao": 88.0, "base": 98.8, "delta": -10.8}]})
    assert app._macro_status(r) == "atencao"
    causa = app._macro_causa(r, "atencao")
    assert "Inversor 2.7" in causa and "parado" not in causa


# ── sino ─────────────────────────────────────────────────────────────────────────────────────────────
def _ev(usina, n, quando="2026-09-10T17:43:31"):
    return [{"usina": usina, "plant_id": 1, "inversor": "Inversor 1.1", "string": str(i), "fonte": "pv",
             "rotulo": "Thopen · API PV", "quando": quando, "tipo": "string_zerou"} for i in range(n)]


def test_sino_descarta_string_que_zerou_com_o_sol_baixo_na_usina(freeze_now):
    freeze_now("2026-09-10 17:43:31")
    mt = next(v["usina"] for v in app.INFO_GERAL.values() if v.get("estado") == "Mato Grosso")
    novos = _ev("Barretos 2 (83)", 4) + _ev("Junco 2.1 (134)", 3) + _ev(mt, 2)
    mantidos, descartes = app._notif_filtra_novos(novos, app.datetime.now())
    assert [e["usina"] for e in mantidos] == [mt, mt]               # em MT ainda são 16:43 solares
    assert descartes == {"sol_baixo": 7, "inundacao": 0}


def test_sino_trata_inundacao_como_evento_ambiente(freeze_now):
    """Mais de _NOTIF_MAX_NOVOS_LEITURA quedas numa leitura só (300 em 10/09) não é 300 strings com defeito ao mesmo
    tempo — é nuvem, anoitecer ou telemetria. Nenhum aviso individual; fica registrado quantos foram."""
    freeze_now("2026-09-10 14:00:00")
    mt = next(v["usina"] for v in app.INFO_GERAL.values() if v.get("estado") == "Mato Grosso")
    muitos = _ev(mt, app._NOTIF_MAX_NOVOS_LEITURA + 1, quando="2026-09-10T14:00:00")
    mantidos, descartes = app._notif_filtra_novos(muitos, app.datetime.now())
    assert mantidos == [] and descartes["inundacao"] == app._NOTIF_MAX_NOVOS_LEITURA + 1
    poucos = _ev(mt, 5, quando="2026-09-10T14:00:00")
    assert app._notif_filtra_novos(poucos, app.datetime.now())[0] == poucos
