# -*- coding: utf-8 -*-
"""Usina sem comunicação ou desligada tem nome próprio na tabela de strings (Levi, 23/09/2026).

O pedido, sobre o print da aba Athon: *"Usinas sem comunicação ou desligadas tem que aparecer como 'Usina Desligada'
ou 'Usina sem comunicação'"*. O caso do print: CPP100 com a última leitura na véspera, 18:26, e a linha dizendo
"0 ativas · 248 esperadas · −248 · 0,0% · Tickets 0/248", tudo em vermelho e pulsando como déficit de strings. Com o
dado parado, esses números são um retrato velho. O que dá para afirmar é só que a usina não está comunicando.

  - USINA SEM COMUNICAÇÃO: a leitura mais nova da usina passou de 30 min (`falha_comunicacao`, calculada pelo backend
    sobre o carimbo mais novo da usina) ou de 2 h (`velho`, régua da tela de 22/07). Vem antes de tudo, e ativas,
    diferença e disponibilidade não são julgadas;
  - USINA DESLIGADA: dado fresco, de dia, nenhuma string com corrente. Era o "Sem geração".
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _trecho(ini, fim):
    i = MON.index(ini)
    return MON[i:MON.index(fim, i) + len(fim)]


def _status(r, velho=False):
    if not NODE:
        pytest.skip("node não instalado")
    js = "\n".join([
        _trecho("const pill=(bg,fg)=>", "\n"), _trecho("const pillOk=", "\n"), _trecho("const pillRed=", "\n"),
        _trecho("const pillAmber=", "\n"), _trecho("const semGer=", "\n"),
        _trecho("function _strStatus(", "/* fim _strStatus */"),
        "process.stdout.write(JSON.stringify(_strStatus(%s,%s)[0]));" % (json.dumps(r), json.dumps(velho)),
    ])
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _cpp100(**kw):
    """O print: 14 inversores, 0 de 248 strings, leitura da véspera."""
    return dict({"usina": "CPP100", "qtd_inversores": 14, "strings_ativas": 0, "str_esp": 248, "diferenca": -248,
                 "sem_dados": False, "falha_comunicacao": True, "ultima_leitura": "2026-09-22 18:26:00"}, **kw)


def test_dado_parado_ha_mais_de_2h_e_usina_sem_comunicacao():
    assert _status(_cpp100(), velho=True) == "Usina sem comunicação"


def test_leitura_mais_nova_passou_de_30_min_tambem():
    """falha_comunicacao do backend = o carimbo MAIS NOVO da usina passou de 30 min: a usina inteira parou de mandar.
    Antes ele ficava no fim da lista e perdia para 'Falha de string', julgada sobre o dado parado."""
    assert _status(_cpp100(strings_ativas=200, diferenca=-48)) == "Usina sem comunicação"


def test_sem_comunicacao_vale_de_dia_e_de_noite():
    assert _status(_cpp100(sol_baixo=True)) == "Usina sem comunicação"


def test_usina_com_dado_fresco_e_nenhuma_string_de_dia_e_usina_desligada():
    assert _status(_cpp100(falha_comunicacao=False, ultima_leitura="agora")) == "Usina desligada"


def test_a_noite_usina_zerada_continua_sem_sol_e_nao_desligada():
    assert _status(_cpp100(falha_comunicacao=False, sol_baixo=True)) == "Sem sol"


def test_os_nomes_antigos_sairam_da_tela():
    s = MON[MON.index("function _strStatus("):MON.index("/* fim _strStatus */")]
    assert "stt='Falha comunicação'" not in s and "stt='Sem geração'" not in s


def test_sem_comunicacao_nao_julga_as_colunas():
    """Diferença, ativas e disponibilidade saem em '—' e a linha não pulsa: o déficit (`dif`) é anulado na origem,
    como na noite."""
    m = MON[MON.index("usinas=pv.rows.filter("):]
    m = m[:m.index("}).sort(")]
    assert re.search(r"semCom=_velho\|\|!!r\.falha_comunicacao", m)
    assert re.search(r"dif=\(semSol\|\|semCom\)\?null:r\.diferenca", m)
    assert re.search(r"active:_ip\?[^\n]*semCom", m) and re.search(r"avail:_ip\?[^\n]*semCom", m)
    assert re.search(r"_tkStrCel\(r,[^)]*semCom", m), "a coluna Tickets também não julga déficit sem comunicação"


def test_os_cards_contam_o_que_a_tabela_mostra():
    real = MON[MON.index("pvReal=true"):]
    assert "label:'Usinas desligadas'" in real and "label:'Usinas sem comunicação'" in real
    assert "_stCount['Usina desligada']" in real and "_stCount['Usina sem comunicação']" in real
