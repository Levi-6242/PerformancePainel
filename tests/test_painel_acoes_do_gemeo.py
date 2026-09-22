# -*- coding: utf-8 -*-
"""As "Ações propostas" do gêmeo dentro do Diagnóstico do painel (Levi, 21/09/2026).

Pedido: "gostei das ações propostas, conseguimos fazer isso aparecer na parte de diagnóstico no
painel? sempre bom explicar o motivo das ações propostas". O bloco lê `V2.gemeo.acoes` — que a tela
JÁ busca para os KPIs — então não custou requisição nova.

O que estes testes seguram, e por quê:
  - o **porquê** tem de aparecer. É o pedido explícito, e é o que separa "abrir OS no Inversor 2.8"
    de "abrir OS porque ele produziu 383 kWh abaixo dos irmãos desde 00:00". Um render que mostrasse
    só a ação passaria despercebido em revisão e esvaziaria o bloco.
  - a visão de PERÍODO não traz `acoes` (só a do dia). Sem guarda, `V2.gemeo.acoes` seria
    `undefined` e o bloco quebraria o ciclo de render inteiro — foi exatamente o que aconteceu no
    template do gêmeo em 21/09 (`d.acoes` virando Undefined no Jinja).
  - usina fora do gêmeo: `V2.gemeo === false`. O bloco some, não mostra vazio nem erro.

A função roda no node com o MESMO código extraído do HTML, como `test_monitoramento_geracao_logica.py`.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
PAINEL = (RAIZ / "plataforma" / "templates" / "painel_usina_v2.html").read_text(encoding="utf-8")
NODE = shutil.which("node")

# Carga real do gêmeo (MAB100, 21/09/2026): sensor no topo por prioridade, custo em kWh sem preço
# de contrato, e um resíduo que vira "investigar" em vez de OS.
ACOES = [
    {"tipo": "sensor_congelado", "prioridade": 1, "equipamento": "ESTM", "kwh": 0.0, "brl": None,
     "acao": "Verificar o sensor da estação solarimétrica",
     "porque": "POA travado em -1 desde 06:30. A POA medida é a ENTRADA do modelo.",
     "compromete_diagnostico": True},
    {"tipo": "inversor_abaixo", "prioridade": 2, "equipamento": "Inversor 2.8", "kwh": 383.0, "brl": 114.9,
     "acao": "Comparar com os pares em campo — Inversor 2.8",
     "porque": "Produzindo abaixo dos inversores irmãos desde 00:00 (383 kWh).",
     "compromete_diagnostico": False},
    {"tipo": "residuo_sem_causa", "prioridade": 3, "equipamento": None, "kwh": 860.0, "brl": None,
     "acao": "Investigar a usina — perda sem causa atribuída",
     "porque": "860 kWh (3% do esperado) sobraram depois de descontar inversor parado, trackers e strings.",
     "compromete_diagnostico": False},
]


def _trecho(ini, fim):
    i = PAINEL.index(ini)
    return PAINEL[i:PAINEL.index(fim, i) + len(fim)]


def _render(gemeo):
    """Roda `renderAcoes()` no node com um DOM mínimo e devolve o que foi para a tela."""
    if not NODE:
        pytest.skip("node não instalado")
    js = "\n".join([
        # DOM de mentira: só o que a função toca. Serve de contrato — se ela passar a mexer em
        # outro elemento, o teste quebra e alguém olha, em vez de descobrir na tela.
        "const _els = {acoesCard:{style:{}}, acoesQuando:{}, acoesBody:{}};",
        "global.document = {getElementById: id => _els[id] || null};",
        _trecho("const nf=(v,d=0)=>", "\n"),
        _trecho("const v2esc=s=>", "\n"),
        "const V2 = {gemeo: " + json.dumps(gemeo) + "};",
        _trecho("function renderAcoes(){", "\n}\n"),
        "renderAcoes();",
        "process.stdout.write(JSON.stringify({display:_els.acoesCard.style.display,"
        "quando:_els.acoesQuando.textContent||'', html:_els.acoesBody.innerHTML||''}));",
    ])
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_mostra_a_acao_e_o_porque_de_cada_uma():
    """O pedido era o motivo; uma lista só de ações não serve."""
    out = _render({"acoes": ACOES, "periodo": {"de": "2026-09-21"}})
    assert out["display"] == ""
    for a in ACOES:
        assert a["acao"] in out["html"], f"sumiu a ação: {a['acao']}"
        assert a["porque"][:40] in out["html"], f"sumiu o PORQUÊ de: {a['acao']}"


def test_sensor_comprometido_avisa_que_o_numero_nao_vale():
    """Sem esse aviso, alguém lê o déficit da usina como verdade estando o sensor travado."""
    out = _render({"acoes": ACOES, "periodo": {"de": "2026-09-21"}})
    assert "não é confiável até resolver" in out["html"]


def test_custo_sai_em_reais_com_centavos_e_em_kwh_quando_nao_ha_preco():
    out = _render({"acoes": ACOES, "periodo": {"de": "2026-09-21"}})
    assert "R$ 114,90" in out["html"], "preço do contrato arredondado para inteiro"
    assert "860 kWh" in out["html"], "sem preço, o custo tem de sair em energia"


def test_dia_da_carga_aparece():
    assert _render({"acoes": ACOES, "periodo": {"de": "2026-09-21"}})["quando"] == "dia 2026-09-21"


def test_sem_acoes_o_bloco_some():
    assert _render({"acoes": [], "periodo": {"de": "2026-09-21"}})["display"] == "none"


def test_visao_de_periodo_nao_traz_acoes_e_isso_nao_pode_quebrar():
    """A visão de mês não carrega `acoes`. Sem guarda o ciclo de render inteiro morria."""
    assert _render({"periodo": {"de": "2026-09-01"}})["display"] == "none"


def test_usina_fora_do_gemeo_nao_mostra_nada():
    """`V2.gemeo === false` é como a tela marca 'esta usina não está no gêmeo'."""
    assert _render(False)["display"] == "none"


def test_o_bloco_fica_entre_a_cascata_e_os_diagnosticos():
    """Ordem pensada: para onde foi o desvio → o que fazer → por quê. Se alguém mover, que apareça."""
    assert PAINEL.index('id="cascCard"') < PAINEL.index('id="acoesCard"') < PAINEL.index('class="diags" id="diags"')
