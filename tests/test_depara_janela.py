"""O de-para do Tempo real numa janela POR CIMA da tela, com o fundo desfocado (13/10/2026). Levi: "Essa forma taca um
bloco minúsculo de ridículo na tela abaixo dos cards de KPI e lota de scroll [...] ao clicar em "de-para" no ao vivo pode
aparecer um visual sobrepondo a tela e dando um blur de fundo"; "Esse scroll lateral não serve para nada!". O atalho era
um link comum: dentro da Entrada, ele trocava o iframe do Monitoramento pela página do de-para, e o editor ficava preso
naquele iframe. Provado no navegador numa cópia de prova: a janela cobre a tela, o Fechar e o clique fora fecham."""
import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[1]
ENT = (RAIZ / "docs" / "redesign" / "Entrada.html").read_text(encoding="utf-8")
MON = (RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html").read_text(encoding="utf-8")
DEP = (RAIZ / "plataforma" / "templates" / "depara.html").read_text(encoding="utf-8")


def test_a_entrada_abre_a_janela_quando_o_monitoramento_embutido_pede():
    assert "function gcDeparaJanela(href)" in ENT and "function gcDeparaFechar()" in ENT
    assert "backdrop-filter:blur(6px)" in ENT and "position:fixed;inset:0" in ENT
    # só aceita o pedido da mesma origem e só para a página do de-para
    assert "if(ev.origin!==location.origin) return;" in ENT
    assert "d.gc==='depara'&&typeof d.href==='string'&&d.href.indexOf('/admin/de-para')>=0" in ENT
    assert "+'janela=1'" in ENT


def test_o_monitoramento_embutido_pede_a_entrada_e_sozinho_abre_a_propria():
    i = MON.index("function gcAbrirDepara(")
    f = MON[i:MON.index("\n}\n", i)]
    assert "parent.postMessage({gc:'depara',href:href},location.origin)" in f and "if(EMBED)" in f
    assert "gcDeparaJanela(href)" in f and "ev.preventDefault()" in f


def test_o_de_para_em_janela_mostra_so_o_editor_e_o_fechar_avisa_a_tela_de_baixo():
    assert re.search(r"\.janela \.topo,\.janela \.wrap,\.janela \.veu\{display:none!important\}", DEP)
    assert "get('janela')==='1') document.documentElement.classList.add('janela')" in DEP
    i = DEP.index("function fechar(){")
    f = DEP[i:DEP.index("\n  }\n", i)]
    assert "parent.postMessage({gc:'depara-fechar'}, location.origin)" in f
