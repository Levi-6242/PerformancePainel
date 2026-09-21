# -*- coding: utf-8 -*-
"""Dois pedidos do Levi (14/09/2026):
1) Diagnóstico de performance: a OS aberta para o "Inversor 1.10" era reconhecida também no "Inversor 1.1" — o
   casamento por prefixo (startsWith) confundia 1.1 com 1.10. Agora casa por número EXATO (_invnum).
2) Painel de portfólio: um botão para filtrar a frota por cliente."""
import pathlib

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
V2 = (RAIZ / "plataforma" / "templates" / "painel_usina_v2.html").read_text(encoding="utf-8")
PORT = (RAIZ / "plataforma" / "templates" / "painel_portfolio.html").read_text(encoding="utf-8")


def test_os_por_inversor_casa_por_numero_exato_nao_por_prefixo():
    # o helper que extrai "bloco.numero" ("Inversor 1.10" -> "1.10")
    assert "const _invnum=s=>{const m=String(s==null?'':s).match(/(\\d+(?:\\.\\d+)?)/);return m?m[1]:null;};" in V2
    # v2OsInv agora casa por numero exato
    assert "if(ni!=null && _invnum(o.sub)===ni)" in V2
    # e o casamento por prefixo (o bug) sumiu
    assert "v2nrm(o.sub||'').startsWith(k)" not in V2


def test_portfolio_tem_filtro_de_cliente():
    assert 'id="wallCli"' in PORT and 'onchange="wallSetCli(this.value)"' in PORT
    assert "function wallSetCli(v){ wallCli=v; renderWall(); }" in PORT
    assert "function fillWallCli(){" in PORT               # popula os clientes distintos do MAP
    assert "fillWallCli(); renderWall();" in PORT          # chamado no boot antes de desenhar a frota
    assert "if(wallCli && (p.cliente||'—')!==wallCli) return false;" in PORT   # o filtro em renderWall
