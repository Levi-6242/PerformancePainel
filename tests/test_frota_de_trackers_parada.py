# -*- coding: utf-8 -*-
"""Alarme de FROTA de trackers parada (Levi, 21/09/2026).

Pedido: *"temos que ter um alarme específico para quando todos os trackers ficam parados por + de
2 horas"*. É outra ocorrência, não um agravamento: um tracker parado é manutenção de equipamento;
a frota inteira parada é o sistema de rastreamento fora — controlador, comunicação ou alimentação —
e a usina passa a gerar como se fosse fixa. Hoje a tabela pinta "20 de 52" e "52 de 52" com a mesma
cor de aviso.

As três decisões da régua estão testadas aqui porque cada uma muda o resultado:
  1. o relógio é o do tracker que caiu por ÚLTIMO (mínimo das horas);
  2. duração desconhecida não vira alarme;
  3. de noite a régua não existe — tracker estacionado está parado por definição.
"""
import pytest

import app


def _linhas(usina, horas, n=None, plant_id="86"):
    """n linhas de tracker parado nessa usina; `horas` pode ser lista (uma por tracker) ou número."""
    hs = horas if isinstance(horas, list) else [horas] * (n or 1)
    return [{"usina": usina, "plant_id": plant_id, "tracker": f"TRK{i+1}", "horas_parado": h}
            for i, h in enumerate(hs)]


def test_frota_inteira_parada_ha_mais_de_duas_horas_alarma():
    r = app.frota_parada({"Brodowski - Skid 2": 3}, _linhas("Brodowski - Skid 2", [3.1, 4.0, 2.5]))
    assert len(r) == 1 and r[0]["alarme"] is True
    assert r[0]["trackers"] == 3 and r[0]["horas"] == 2.5


def test_o_relogio_e_o_do_ultimo_a_cair():
    """Dois parados há 5 h e um há 10 min: a FROTA não está parada há 5 h, está há 10 min.
    Usar o máximo diria "5 h" e abriria OS urgente para algo que começou agora."""
    r = app.frota_parada({"X": 3}, _linhas("X", [5.0, 5.0, 0.17]))
    assert r[0]["horas"] == 0.17 and r[0]["alarme"] is False


def test_um_tracker_de_pe_derruba_o_alarme():
    """52 de 52 é o alarme; 51 de 52 é a régua antiga, de tracker individual."""
    assert app.frota_parada({"X": 52}, _linhas("X", 9.0, n=51)) == []


def test_usina_sem_total_conhecido_nao_alarma():
    """Sem o total não dá para afirmar "todos" — e tratar o nº de parados como total faria QUALQUER
    usina com um tracker parado virar frota parada."""
    assert app.frota_parada({}, _linhas("X", 9.0, n=5)) == []


def test_duracao_desconhecida_nao_vira_alarme_mas_aparece():
    """Sem `parado_desde` não dá para dizer "mais de 2 h". Afirmar o que não se mediu é o que faz
    um alarme virar ruído — mas sumir com o caso esconde a frota caída."""
    r = app.frota_parada({"X": 2}, [{"usina": "X", "horas_parado": None},
                                    {"usina": "X", "horas_parado": None}])
    assert len(r) == 1 and r[0]["alarme"] is False and r[0]["duracao_desconhecida"] is True


def test_um_sem_hora_no_meio_tambem_e_desconhecida():
    """Se um dos parados não tem hora, o mínimo do resto pode ser maior que a verdade."""
    r = app.frota_parada({"X": 3}, [{"usina": "X", "horas_parado": 9.0},
                                    {"usina": "X", "horas_parado": 8.0},
                                    {"usina": "X", "horas_parado": None}])
    assert r[0]["duracao_desconhecida"] is True and r[0]["alarme"] is False


def test_exatamente_no_corte_alarma():
    assert app.frota_parada({"X": 1}, _linhas("X", 2.0))[0]["alarme"] is True


def test_corte_configuravel():
    assert app.frota_parada({"X": 1}, _linhas("X", 3.0), horas=4.0)[0]["alarme"] is False
    assert app.frota_parada({"X": 1}, _linhas("X", 3.0), horas=1.0)[0]["alarme"] is True


def test_de_noite_a_regra_nao_existe():
    """Tracker estacionado à noite está parado por definição — é o mesmo portão do sol que o macro
    e o sino já usam, e sem ele a frota inteira "alarmaria" todo fim de tarde, em toda usina."""
    assert app.frota_parada({"X": 2}, _linhas("X", 9.0, n=2),
                            de_dia_por_usina=lambda u: False) == []
    assert len(app.frota_parada({"X": 2}, _linhas("X", 9.0, n=2),
                                de_dia_por_usina=lambda u: True)) == 1


def test_alarmes_vem_antes_e_o_mais_antigo_primeiro():
    """Quem lê a lista age de cima para baixo: alarme antes de não-alarme, e dentro do alarme o que
    está parado há mais tempo."""
    rows = _linhas("A", 3.0, n=1) + _linhas("B", 9.0, n=1, plant_id="87") + _linhas("C", 0.5, n=1, plant_id="88")
    r = app.frota_parada({"A": 1, "B": 1, "C": 1}, rows)
    assert [x["usina"] for x in r] == ["B", "A", "C"]


def test_linha_sem_usina_nao_quebra():
    assert app.frota_parada({"X": 1}, [{"horas_parado": 9.0}]) == []


def test_o_corte_padrao_e_de_duas_horas():
    """O número que o Levi pediu não pode mudar por acidente de refactor."""
    assert app.FROTA_PARADA_HORAS == 2.0


@pytest.mark.parametrize("fonte", ["pv", "pg", "sunop", "axis", "owen"])
def test_a_rota_e_EXPLICITA_por_fonte(fonte):
    """As cinco fontes precisam da rota — se uma ficasse de fora, a usina dela nunca alarmaria e
    ninguém perceberia até o dia do incidente.

    E precisa ser explícita, não `/api/<fonte>/...`: com o curinga, `/api/pg/trackers/<plant_id>`
    vence no Werkzeug e "frota-parada" chega como id de usina — devolvia análise vazia com HTTP 200,
    que é a pior falha possível: parece funcionar."""
    rotas = {str(r) for r in app.app.url_map.iter_rules()}
    assert f"/api/{fonte}/trackers/frota-parada" in rotas
    assert "/api/<fonte>/trackers/frota-parada" not in rotas
    assert fonte in app._TRK_FONTES
