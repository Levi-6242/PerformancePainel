# -*- coding: utf-8 -*-
"""O vermelho do card da ETM descreve AGORA, nunca o histórico do mês (Levi, 21/09/2026).

O caso que motivou: na tela `/tempo-real/2c`, Araputanga, Sete Lagoas e Tupi Paulista apareciam
vermelhas, pulsando e com botão "Abrir OS · ETM" por causa da frase "IPOA zerada/nula em 3 de 20
dias" — vinda do BD_Performance — enquanto o piranômetro das três lia 1.267, 1.160 e 898 W/m²
naquele minuto. O único alarme real da fonte (Ipixuna do Pará, pico 0 W/m² hoje) ficava
indistinguível dos três saudáveis, e o filtro "Alarmes" contava 4.

A régua roda no navegador; aqui ela roda no node com o MESMO código extraído do HTML — mesmo
arranjo de `test_monitoramento_geracao_logica.py`. Antes de 21/09 a regra estava solta dentro do
`.map()` dos cards e duplicada na tabela; foi assim que Cards e Tabela passaram a contar coisas
diferentes sem ninguém ver.
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

# Alarme do mês como o backend o devolve: foi ele que pintava o card indevidamente até 21/09.
MES_ALARME = {"alarme": True,
              "alarmes": ["IPOA zerada/nula em 3 de 20 dias"],
              "avisos": ["IPOA constante em 0.0 por 3 dias seguidos (sensor travado?)"]}


def _trecho(ini, fim):
    i = MON.index(ini)
    return MON[i:MON.index(fim, i) + len(fim)]


def _estado(r, prob_mes=None, fonte=MON):
    """Roda `_etmEstado` no node com a estação `r` e o diagnóstico do mês `prob_mes`."""
    if not NODE:
        pytest.skip("node não instalado")
    i = fonte.index("function _etmEstado(")
    js = "\n".join([
        fonte[i:fonte.index("/* fim _etmEstado */", i)],
        "process.stdout.write(JSON.stringify(_etmEstado(%s,%s)));" % (json.dumps(r), json.dumps(prob_mes)),
    ])
    p = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _lendo(**kw):
    """Estação reportando normalmente agora: sem flag crítica nenhuma."""
    return dict({"usina": "Araputanga", "sem_dados": False, "flags": []}, **kw)


def test_mes_zerado_nao_pinta_card_de_estacao_que_esta_lendo():
    """O caso do print: 3 de 20 dias zerados no BD, mas o sensor lê 1.267 W/m² AGORA."""
    e = _estado(_lendo(), MES_ALARME)
    assert e["estado"] == "ok", f"histórico do mês voltou a pintar o card: {e}"
    assert e["prob"] is False, "estação saudável entrando na contagem de Alarmes"
    assert e["vd"] == "Estação OK"


def test_a_funcao_resiste_a_receber_o_mes():
    """Desde 21/09 ninguém passa o mês para `_etmEstado` — a tela inteira deixou de buscá-lo.

    O parâmetro fica, e este teste com ele: se alguém voltar a alimentá-lo, a função tem de
    reconhecer o alarme do mês (`alMes`) e mesmo assim NÃO pintar o card. É a garantia de que a
    correção está na régua, e não só no fato de a chamada ter sumido."""
    e = _estado(_lendo(), MES_ALARME)
    assert e["alMes"] is True and e["estado"] == "ok" and e["prob"] is False


def test_ipoa_zerada_hoje_alarma():
    """Ipixuna do Pará, pico 0 W/m² hoje — este é o alarme que tem de sobrar sozinho."""
    e = _estado(_lendo(usina="Ipixuna do Pará",
                       flags=[{"tipo": "crit", "sensor": "POA", "t": "IPOA zerado", "info": "pico 0 W/m²"}]))
    assert e["estado"] == "al" and e["prob"] is True
    assert e["vd"] == "IPOA zerada hoje" and e["vdSub"] == "pico 0 W/m²"


def test_ghi_zerado_hoje_alarma_com_o_nome_do_sensor_certo():
    e = _estado(_lendo(flags=[{"tipo": "crit", "sensor": "GHI", "t": "GHI zerado", "info": ""}]))
    assert e["estado"] == "al" and e["vd"] == "GHI zerado hoje"


def test_sem_dados_hoje_com_alarme_no_mes_fica_cinza_nao_vermelho():
    """Sem leitura não há medição em zero — e a régua do Levi (10/09) é 'IPOA/GHI MEDIDOS em zero'.
    Estação muda é assunto do card 'Sem comunicação', não da cor de alarme da ETM."""
    e = _estado(_lendo(sem_dados=True), MES_ALARME)
    assert e["estado"] == "sd" and e["prob"] is False
    assert e["vd"] == "Sem dados hoje"


def test_sem_comunicacao_e_atencao_nao_viram_alarme():
    assert _estado(_lendo(flags=[{"tipo": "crit", "sensor": "COM", "t": "sem comunicação"}]))["estado"] == "cm"
    at = _estado(_lendo(flags=[{"tipo": "warn", "t": "POA-RI sem leitura", "info": ""}]))
    assert at["estado"] == "at" and at["prob"] is False


def test_tabela_e_cards_usam_a_MESMA_funcao():
    """Regressão da causa-raiz: eram duas cópias da regra, e só uma foi corrigida em 10/09."""
    linha = _trecho("const prob=_etmEstado(r,null).prob;", "\n")
    assert "_etmEstado(" in linha, "a tabela voltou a ter régua própria"
    assert MON.count("function _etmEstado(") == 1


def _so_codigo():
    """O HTML sem comentários (`//` e `/* */`): eles citam de propósito os nomes do que foi removido."""
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", MON, flags=re.S))


def test_o_mes_do_BD_nao_aparece_mais_na_tela():
    """Levi, 21/09: "tire essa informação de mês BD, se eu quiser saber do BD eu vejo em outro canto".

    O que ele viu no print: card com veredito verde "Estação OK" e, logo abaixo, "IPOA zerada/nula em
    3 de 20 dias" em VERMELHO — texto do BD_Performance com cor de risco embaixo de estação sadia."""
    codigo = _so_codigo()
    for morto in ("mesHtml", "mesTit", "gc-etm-mes", "_etmProbMes", "RD.etmMes", "etmProbMesN"):
        assert morto not in codigo, f"o mês voltou para a tela: {morto}"


def test_a_varredura_do_mes_nao_e_mais_buscada():
    """Sem leitor, `_ensureEtmMes` seguiria varrendo o BD_Performance uma vez por sessão para nada."""
    assert "_ensureEtmMes" not in _so_codigo()


def test_o_filtro_alarmes_nasce_desmarcado():
    """Levi, 21/09: "está marcando o botão Alarme como padrão, quero que deixe desmarcado".

    O `?etmprob=1` vinha da Entrada quando o card dela contava alarme do MÊS — contagem que nem
    governa mais esta tela. A tela abria filtrada sem ninguém ter pedido."""
    assert "etmProb:false" in MON
    assert "etmprob" not in _so_codigo(), "ainda há quem ligue o filtro pela URL"


def test_a_regra_antiga_falharia_este_teste():
    """Prova que o teste pega o bug: roda os MESMOS casos contra a régua de antes de 21/09.

    Sem isto, um teste escrito depois da correção só atesta que o código de hoje concorda consigo
    mesmo. A régua antiga está reproduzida aqui porque o arquivo original já foi alterado."""
    antiga = """function _etmEstado(r,probMes){
      const fl=r.flags||[];
      const critSens=fl.filter(f=>f.tipo==='crit'&&(f.sensor==='POA'||f.sensor==='GHI'));
      const semCom=fl.find(f=>f.tipo==='crit'&&f.sensor==='COM');
      const warns=fl.filter(f=>f.tipo==='warn');
      const alHoje=critSens.length>0, alMes=!!(probMes&&probMes.alarme);
      const estado=r.sem_dados?(alMes?'al':'sd'):((alHoje||alMes)?'al':(semCom?'cm':(warns.length?'at':'ok')));
      return {estado,vd:'',vdSub:'',prob:estado==='al',alHoje,alMes};
    }
    /* fim _etmEstado */"""
    e = _estado(_lendo(), MES_ALARME, fonte=antiga)
    assert e["estado"] == "al" and e["prob"] is True, (
        "a régua antiga deveria acusar o falso alarme — se não acusa, este teste não prova nada")
