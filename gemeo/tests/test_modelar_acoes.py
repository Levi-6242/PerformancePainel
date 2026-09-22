# -*- coding: utf-8 -*-
"""Ações propostas (21/09/2026, Levi: "faça o gêmeo reportar e propor").

**De onde vem a ideia.** O relatório IEA-PVPS T13-34 classifica em três níveis: *Digital Model*,
*Digital Shadow* (fluxo automático só físico→digital) e *Digital Twin* (automático nos DOIS
sentidos). Pela taxonomia somos Sombra Digital — correto, e é como o plano nos chama. O passo que
falta está descrito quase como se nos conhecesse: o gestor abre a tela, vê os alarmes **e uma lista
de ações propostas**, e aprova. Nós já temos deep link do OS Creator e escrita na API do Fracttal:
o que falta não é integração, é o gêmeo PROPOR.

**A regra que governa tudo aqui: propor não é executar.** A ação nasce com o veredito, o porquê e o
quanto; quem abre a OS é uma pessoa. Nada nesta camada escreve em sistema externo.
"""
from gemeo.modelar import acoes


def _ev(tipo, equip="Inversor 2.3", kwh=0.0, sev="grave", eid=7, detalhe=None):
    return {"tipo": tipo, "equipamento": equip, "equipamento_id": eid, "kwh": kwh,
            "severidade": sev, "hora_ini": "08:15", "hora_fim": "17:30", "detalhe": detalhe or {}}


def test_inversor_parado_vira_corretiva_com_a_perda_no_texto():
    """O que move alguém não é 'inversor parado', é 'inversor parado custando 412 kWh'."""
    a = acoes.propor([_ev("inversor_parado", kwh=412.0)], cascata={}, preco_mwh=None)
    assert len(a) == 1
    assert a[0]["equipamento"] == "Inversor 2.3" and a[0]["prioridade"] == 1
    assert "412" in a[0]["porque"] and a[0]["kwh"] == 412.0
    assert a[0]["acao"].lower().startswith("abrir os")


def test_ordena_pelo_que_custa_mais():
    a = acoes.propor([_ev("tracker_fora_alvo", equip="TRK 12", kwh=15.0, sev="leve"),
                      _ev("inversor_parado", equip="Inversor 1.1", kwh=300.0),
                      _ev("string_sem_corrente", equip="String 4", kwh=48.0)],
                     cascata={}, preco_mwh=None)
    assert [x["equipamento"] for x in a] == ["Inversor 1.1", "String 4", "TRK 12"]


def test_sensor_congelado_avisa_que_o_NUMERO_esta_comprometido():
    """A POA é a ENTRADA do modelo: sensor travado não gera uma perda, gera um esperado inteiro
    errado. A ação tem de dizer isso, senão alguém sai caçando inversor por um déficit que não
    existe. É o caso da Ibaté 2 (287 leituras no dia, UM valor distinto, por três dias)."""
    a = acoes.propor([_ev("sensor_congelado", equip="estação", kwh=0.0,
                          detalhe={"medida": "poa", "valor": 464.04, "slots": 30})],
                     cascata={}, preco_mwh=None)
    assert len(a) == 1 and a[0]["prioridade"] == 1        # kWh zero e ainda assim é o mais urgente
    assert a[0]["compromete_diagnostico"] is True
    assert "464" in a[0]["porque"]


def test_clipping_nao_vira_acao():
    """Decisão do Levi em 17/09: clipping é limite de projeto, não falha de operação. Propor
    'investigar o clipping' seria mandar gente a campo por um projeto funcionando como desenhado."""
    assert acoes.propor([], cascata={"clipping": 900.0, "delta": 900.0}, preco_mwh=None) == []


def test_residuo_grande_sem_causa_vira_investigacao_e_nao_OS():
    """Resíduo é o que a cascata NÃO explicou. Mandar abrir OS sobre o não-explicado é pedir para o
    time procurar no escuro; a ação certa é investigar a usina, não trocar peça."""
    a = acoes.propor([], cascata={"residuo": 2200.0, "delta": 2500.0, "e_esperado": 20000.0}, preco_mwh=None)
    assert len(a) == 1 and a[0]["tipo"] == "residuo_sem_causa"
    assert "investigar" in a[0]["acao"].lower() and a[0]["equipamento"] is None


def test_com_preco_a_acao_fala_em_reais():
    a = acoes.propor([_ev("inversor_parado", kwh=1000.0)], cascata={}, preco_mwh=320.0)
    assert a[0]["brl"] == 320.0 and "R$" in a[0]["porque"]


def test_a_acao_nunca_executa_nada():
    """Trava de desenho: o módulo é PURO. Se um dia alguém puser chamada de rede aqui, este teste
    não pega — mas o texto fica, e a revisão pega."""
    import inspect
    fonte = inspect.getsource(acoes)
    for proibido in ("requests", "urlopen", "http", "psycopg", "sqlite3", "conn."):
        assert proibido not in fonte, f"a camada de proposta não pode falar com {proibido}"


def test_sensor_em_falha_diz_o_que_e_em_vez_de_SENSOR_generico():
    """21/09, visto ao vivo em Sete Lagoas e Tupi: o texto saía "SENSOR das 00:00 às 11:00" porque o
    `sensor_em_falha` (tipo antigo, do gate POA×GHI) não carrega `medida` no detalhe, ao contrário do
    `sensor_congelado`. Rótulo genérico não diz a ninguém o que ir verificar."""
    a = acoes.propor([_ev("sensor_em_falha", equip="estação", kwh=0.0, detalhe={})],
                     cascata={}, preco_mwh=None)
    assert "SENSOR" not in a[0]["porque"]
    assert "POA" in a[0]["porque"] and "GHI" in a[0]["porque"]
