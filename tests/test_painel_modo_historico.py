# -*- coding: utf-8 -*-
"""Modo histórico do painel (Levi, 14/09/2026): usinas SEM fonte ao vivo entram na parede e ganham
um diagnóstico histórico. Trava os marcadores das duas telas + o endpoint de tickets. A régua da
disponibilidade por inversor (cascata da cabine) tem teste próprio em test_disp_por_inversor.py."""
import pathlib

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
PORT = (RAIZ / "plataforma" / "templates" / "painel_portfolio.html").read_text(encoding="utf-8")
V2 = (RAIZ / "plataforma" / "templates" / "painel_usina_v2.html").read_text(encoding="utf-8")
APP = (RAIZ / "plataforma" / "app.py").read_text(encoding="utf-8")
DISP = (RAIZ / "plataforma" / "disponibilidade.py").read_text(encoding="utf-8")


def test_portfolio_entra_usina_so_gerencial_na_parede():
    # merge() adiciona as usinas só do gerencial (sem macro) marcadas _soHist
    assert "const gUsado=new Set();" in PORT
    assert "_soHist:true" in PORT
    # o clique abre o diagnóstico histórico e o tile mostra o selo "hist"
    assert "function openHist(k){" in PORT
    assert "class=\"thist\"" in PORT
    # drillUrl roteia para o modo histórico
    assert "?hist=1&cliente=" in PORT
    assert "return p._soHist?true:!!FMAP[p.fonte];" in PORT  # hasDrill libera o histórico
    # a visão Strings exclui as só-histórico (não têm string ao vivo)
    assert "if(wallView==='str' && p._soHist) return false;" in PORT


def test_v2_tem_modo_historico():
    assert "const HIST=Q.get('hist')==='1';" in V2
    assert "if(HIST){ return bootHist(); }" in V2
    assert "async function bootHist(){" in V2
    # o v2Boot (loaders ao vivo + o laço tick de v2Render) NÃO pode rodar no modo histórico,
    # senão reescreve a tela do bootHist com "Carregando…" (bug do 14/09, usina União 1 e 2)
    assert "async function v2Boot(){\n  if(HIST) return;" in V2
    # troca as fontes ao vivo pelas históricas
    assert "/api/g/inversores?" in V2
    assert "/api/gerencial/disponibilidade?mes=" in V2
    assert "/api/g/tickets-trackers?usina=" in V2
    # a tabela por inversor tem a coluna % disp e a cabine
    assert "% disp" in V2 and "Cabine " in V2
    # Trackers só com ticket; acumulado do mês POR INVERSOR
    assert "tk && tk.tem_ticket" in V2
    assert "Acumulado do mês por inversor" in V2


def test_v2_historico_empilha_sem_abas():
    """Levi, 15/09: no modo histórico não há abas — Inversores, Mês · gerencial e Trackers vêm
    empilhados. Clicar em aba chamava o render AO VIVO e travava a tela em "Carregando" (loop)."""
    # o render ao vivo não roda no histórico (era a causa do loop infinito)
    assert "function v2Render(){ if(HIST) return;" in V2
    # a barra de abas some e os painéis são empilhados na ordem Inversores → Mês → Trackers
    assert "const _tabs=document.querySelector('.v2-tabs'); if(_tabs) _tabs.style.display='none';" in V2
    assert "insertBefore(pMes, pInv.nextSibling)" in V2
    assert "insertBefore(pTrk, pMes.nextSibling)" in V2
    # o filtro "todos / só com problema" passa a redesenhar a tabela histórica
    assert "window.v2FInv=v=>{ V2.fInv=v;" in V2
    assert "const rs2=(V2 && V2.fInv==='prob') ? rs.filter(_prob) : rs;" in V2


def test_v2_historico_gerado_x_esperado_e_os_no_tooltip():
    """Levi, 15/09: trazer gerado x esperado (no dia e no acumulado do mês) e, no tooltip da
    disponibilidade, o detalhe da OS."""
    assert "/api/g/diario?" in V2                      # fonte do gerado x esperado POR DIA
    assert "Gerado x esperado por dia" in V2
    assert "card('Geração do mês'" in V2               # acumulado do mês no KPI
    # dia sem dado no BD não entra na conta do mês (senão o esperado infla)
    assert "const _hTemDia=p=>" in V2
    # OS no tooltip: texto montado e aplicado na célula de % disp e nos cards de disponibilidade
    assert "function _histOsTip(oss){" in V2
    assert "HISTOS=_histOsTip(" in V2
    assert "h perdidas em horas solares" in V2


def test_gerado_x_esperado_na_tabela_de_inversores():
    """Levi, 15/09: a relação gerado x esperado tem que estar NA TABELA de inversores, por inversor.
    Esperado = Σ IPOA do período × potência do inversor × alvo de PR (o que o alvo daria com a
    irradiância que veio). Conferido ao vivo: Cedro 1 soma 71,7 MWh gerados, igual ao Gerencial."""
    APP_ = (RAIZ / "plataforma" / "app.py").read_text(encoding="utf-8")
    # a rota devolve gerado e esperado POR INVERSOR (os dois ramos: BD_Performance e BD_Thopen)
    assert '"ger_mwh": round(_ger, 2)' in APP_
    assert 'r["esp_mwh"] = round(_d * alvo, 2)' in APP_
    assert '"ger_mwh": round(max(ger, 0.0) / 1000.0, 2)' in APP_     # ramo BD_Thopen
    # usina do BD_Thopen tira a meta de PR do próprio BD_Thopen quando a Info Mensal não a tem
    assert 'alvo = ((THOPEN_META.get(_nrm(u)) or {}).get(d0.month) or {}).get("pr_meta")' in APP_
    # colunas na tabela + recorte do MÊS (sem ini/fim a rota soma o histórico inteiro)
    assert ">Gerado</th>" in V2 and ">Esperado</th>" in V2 and ">do esperado</th>" in V2
    assert "const qim=`${qi}&ini=${_d1}&fim=${_d2}`;" in V2


def test_v2_ao_vivo_coluna_agora_so_status():
    """Levi, 15/09: a coluna "Agora" da v2 AO VIVO mostra só o status — o kW embaixo do selo
    dobrava a altura de todas as linhas. O valor foi para o title do selo."""
    assert 'title="${nf(i.active_power)} kW agora"' in V2
    assert 'margin-top:3px">${nf(i.active_power)} kW</div>' not in V2


def test_endpoint_tickets_trackers_existe():
    assert '@app.route("/api/g/tickets-trackers")' in APP
    assert "def api_g_tickets_trackers():" in APP
    assert '"tem_ticket": bool(nums) or bool(tu)' in APP


def test_disponibilidade_emite_por_inversor():
    assert "def _disp_por_inversor(" in DISP
    assert "\"inversores\": disp_inv.get(u, [])" in DISP
