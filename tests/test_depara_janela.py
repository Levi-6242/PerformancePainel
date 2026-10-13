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
    assert "function gcDeparaJanela(href,rotulo)" in ENT and "function gcDeparaFechar(trocando)" in ENT
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


# ── a criação de OS na mesma janela (13/10/2026) ─────────────────────────────────────────────────────────────────────
def test_o_criar_os_do_tempo_real_abre_na_janela_e_nao_em_outra_aba():
    """Levi: "Em performance > tempo real > criar OS ao invés de direcionar para o OS Creator aparece a tela de criação de
    OS sobrepondo toda a tela dando um blur de fundo, assim que a pessoa finaliza a OS só aparece a notificação"."""
    assert "window.open(" not in MON                                      # nem as strings nem a ETM abrem outra aba
    i = MON.index("function gcAbrirOs(")
    f = MON[i:MON.index("\n}\n", i)]
    assert "parent.postMessage({gc:'os',links:links},location.origin)" in f and "gcOsJanela(links)" in f
    assert "gcAbrirOs(links); osClear();" in MON and "gcAbrirOs([OS_WEB_CRIAR+'?'" in MON
    for pagina in (ENT, MON):
        assert "d.gc==='os'&&Array.isArray(d.links)" in pagina and "d.gc==='os-criada'" in pagina


def test_a_fila_de_os_abre_uma_depois_da_outra_e_avisa_cada_criada():
    import json
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node não instalado")
    ini = ENT.index("var _gcOsFila=[]")
    fim = ENT.index("document.addEventListener('keydown'", ini)
    codigo = ENT[ini:fim]
    dom = r"""
    const registro = {}; const ouvintes = {};
    function el(tag){ return {tag, style:{}, attrs:{}, filhos:[], hidden:false, setAttribute(k,v){this.attrs[k]=v;},
      appendChild(c){ this.filhos.push(c); if(c.id) registro[c.id]=c; return c; },
      addEventListener(){}, remove(){ delete registro[this.id]; }, focus(){},
      set id(v){ this._id=v; }, get id(){ return this._id; }}; }
    globalThis.document = {createElement: el, body: {appendChild(c){ registro[c.id]=c; return c; }},
      getElementById: id => registro[id] || null, documentElement: {style:{}}, addEventListener(){}};
    globalThis.window = {addEventListener(){}}; globalThis.location = {origin: 'https://app.gridco.com.br'};
    """
    roteiro = r"""
    const passos = [];
    const janela = () => registro['gc-depara-janela'];
    const iframe = () => janela().filhos[0].filhos[0];
    const aviso = () => (registro['gc-aviso-janela'] || {}).textContent || '';
    gcOsJanela(['/os/performance/criar?usina=A', 'https://outro.site/x', '/os/performance/criar?usina=B', '/os/performance/criar?usina=C']);
    passos.push([iframe().src, janela().attrs['aria-label']]);
    function criada(m){ _gcOsCriadas++; gcAviso(m, true); _gcOsProxima(); }
    criada('1 OS criada: 15100');
    passos.push([iframe().src, janela().attrs['aria-label'], aviso()]);
    gcDeparaFechar();                                          // fechou antes da última
    passos.push([!!janela(), aviso(), document.documentElement.style.overflow]);
    gcOsJanela(['/os/performance/criar?usina=Z']);
    criada('1 OS criada: 15200');
    passos.push([!!janela(), aviso()]);
    process.stdout.write(JSON.stringify(passos));
    """
    p = subprocess.run([node, "-e", dom + codigo + roteiro], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    passos = json.loads(p.stdout)
    # o link de fora do OS Creator nem entra na fila; a 1ª abre em janela com o rótulo da contagem
    assert passos[0] == ["/os/performance/criar?usina=A&janela=1", "Criar OS (1 de 3)"]
    assert passos[1] == ["/os/performance/criar?usina=B&janela=1", "Criar OS (2 de 3)", "1 OS criada: 15100"]
    assert passos[2] == [False, "1 OS criada; 1 ficou sem criar.", ""]
    assert passos[3] == [False, "1 OS criada: 15200"]                    # a única da fila: criou e fechou
