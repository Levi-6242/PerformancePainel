# gemeo/tests/test_strings_nome_e_drilldown.py
"""Nome do inversor na lista de strings + drill-down da curva (Levi, 21/09/2026).

Dois pedidos do mesmo print:
  1. *"nas strings está aparecendo esse número '400792', creio que seja o ID do inversor, quero o
     nome do inversor"* — a string nasce com `codigo_fonte` = "<idefinversor>.Ipv<n>", que é a
     chave certa no banco e a errada na tela.
  2. *"quando eu clicar nessa linha quero que abra um drill down da curva das strings do inversor
     para aquele dia"* — e a curva é do INVERSOR inteiro de propósito: a pergunta que se faz diante
     de uma string ruim não é "ela caiu?", é "ela caiu SOZINHA?", e só as irmãs respondem.
"""
import datetime as dt
import json
import pathlib
import shutil
import subprocess

import pytest

from gemeo.app import consultas

UTC = dt.timezone.utc
RAIZ = pathlib.Path(consultas.__file__).resolve().parents[2]
JS = (RAIZ / "gemeo" / "app" / "static" / "gemeo.js").read_text(encoding="utf-8")
HTML = (RAIZ / "gemeo" / "app" / "templates" / "usina.html").read_text(encoding="utf-8")
NODE = shutil.which("node")


# ── rótulo ──────────────────────────────────────────────────────────────────────────────────────
def test_o_id_do_inversor_vira_nome():
    """400787.Ipv11 -> ('Inversor 1.4', 'Ipv11'). Era exatamente o que o print mostrava."""
    assert consultas._rotulo_string("400787.Ipv11", "Inversor 1.4", "400787") == ("Inversor 1.4", "Ipv11")


def test_string_sem_pai_mantem_o_rotulo_cru():
    """Esconder a linha por falta de pai seria perder a perda; o código cru é feio mas é verdade."""
    assert consultas._rotulo_string("400787.Ipv11", None, None) == ("", "400787.Ipv11")


def test_prefixo_que_nao_e_do_pai_nao_e_cortado():
    """Só corta o prefixo se ele for MESMO o código do pai — senão mutila o nome de outra fonte."""
    assert consultas._rotulo_string("XYZ.Ipv3", "Inversor 2.1", "400787") == ("Inversor 2.1", "XYZ.Ipv3")


def test_a_chave_do_banco_continua_disponivel():
    """`nome` é o que se lê; `codigo` tem de seguir sendo a chave, senão o drill-down não acha nada."""
    d = consultas._com_pai((7, "400787.Ipv11", 42, 0.3, "Inversor 1.4", "400787"))
    assert d["nome"] == "Inversor 1.4 · Ipv11"
    assert d["codigo"] == "400787.Ipv11" and d["pai_codigo"] == "400787" and d["sufixo"] == "Ipv11"


def test_com_pai_aguenta_linha_curta():
    """Chamada antiga (sem as colunas do pai) não pode levantar — ela ainda existe em snapshot."""
    d = consultas._com_pai((7, "TRK5", 42, 1.5))
    assert d["nome"] == "TRK5" and d["pai"] == ""


# ── mediana, que é a referência contra a qual o olho compara ────────────────────────────────────
@pytest.mark.parametrize("vals,esperado", [([3.0], 3.0), ([1.0, 3.0], 2.0), ([5.0, 1.0, 3.0], 3.0), ([], None)])
def test_mediana(vals, esperado):
    assert consultas._mediana(vals) == esperado


# ── a linha da tabela carrega o que o drill-down precisa ────────────────────────────────────────
def test_a_linha_da_string_e_clicavel_e_leva_os_quatro_dados():
    """Sem qualquer um dos quatro o clique não sabe o que buscar; um `data-` esquecido é uma tela
    que simplesmente não reage, sem erro no console."""
    i = HTML.index('class="str-lin"')
    linha = HTML[i - 60:i + 400]
    for attr in ("data-inv", "data-str", "data-uid", "data-dia"):
        assert attr in linha, f"faltou {attr} na linha da string"
    assert 'tabindex="0"' in linha and 'role="button"' in linha, "clicável só com mouse não serve"


def test_o_prefixo_da_api_vem_do_servidor():
    """O JS monta URL de API. Chutar '/gemeo' quebraria em silêncio se o prefixo mudasse."""
    base = (RAIZ / "gemeo" / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "window.GEMEO_PREFIXO" in base and "GEMEO_PREFIXO" in JS


# ── o desenho, rodando de verdade ───────────────────────────────────────────────────────────────
def _svg(dados, destaque):
    """Roda a função `svg()` do gemeo.js no node, com o MESMO código do arquivo servido."""
    if not NODE:
        pytest.skip("node não instalado")
    def trecho(ini, fim):
        i = JS.index(ini)
        return JS[i:JS.index(fim, i)]

    js = "\n".join([
        trecho("  function hhmm(iso)", "\n"),          # o eixo do tempo usa; sem ele o node levanta
        trecho("  function svg(dados, destaque) {", "\n  function pinta("),
        "process.stdout.write(svg(%s,%s));" % (json.dumps(dados), json.dumps(destaque)),
    ])
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _dia(n, base):
    return [["2026-09-21T%02d:00:00+00:00" % h, base + h * 0.5] for h in range(9, 9 + n)]


def test_desenha_uma_linha_por_string_mais_mediana():
    dados = {"series": {"Ipv1": _dia(8, 1.0), "Ipv2": _dia(8, 1.1), "Ipv3": _dia(8, 0.2)},
             "mediana": _dia(8, 1.0), "n_strings": 3}
    out = _svg(dados, "Ipv3")
    assert out.count("<polyline") == 4, "3 strings + mediana"
    assert "var(--st-risk)" in out, "a string clicada tem de sair em destaque"
    assert "stroke-dasharray" in out, "a mediana tem de sair tracejada"


def test_dia_sem_corrente_por_string_diz_isso_em_vez_de_svg_vazio():
    """SVG em branco parece bug; a frase explica que o dado não existe naquele dia."""
    assert "Sem corrente por string" in _svg({"series": {}, "mediana": []}, "Ipv1")


def test_janela_de_um_ponto_so_nao_quebra_o_desenho():
    """t1 == t0 daria divisão por zero e um SVG com NaN — que o navegador desenha como nada."""
    um = {"series": {"Ipv1": [["2026-09-21T12:00:00+00:00", 4.0]]}, "mediana": []}
    assert "NaN" not in _svg(um, "Ipv1")


def test_corrente_toda_zero_nao_gera_NaN():
    """Divisão por `mx` com mx=0 (noite inteira, ou inversor desligado) é o caso real mais provável."""
    z = {"series": {"Ipv1": _dia(6, 0.0)}, "mediana": _dia(6, 0.0)}
    for v in z["series"]["Ipv1"]:
        v[1] = 0.0
    out = _svg(z, "Ipv1")
    assert "NaN" not in out and "<polyline" in out
