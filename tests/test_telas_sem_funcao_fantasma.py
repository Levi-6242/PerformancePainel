# -*- coding: utf-8 -*-
"""Nenhuma tela pode chamar função que não existe (Levi, 22/09/2026).

O caso: *"trackers está carregando porém ETM não carrega"* — a aba ETM do tempo real ficava para
sempre em "Coletando dados…", em TODAS as fontes. No console: `ReferenceError: _etmSensTile is not
defined`. A função que desenha os blocos de sensor (POA, GHI, POA-RI) do card tinha sido apagada no
commit 2c75fb8, junto com o `_etmMesCurto`, quando a linha do "mês BD" saiu da tela a pedido dele —
os dois moravam colados, e o bloco inteiro foi embora. As duas chamadas ficaram.

Por que passou: o teste daquela mudança exercitava a régua do alarme (`_etmEstado`), não o desenho
do card; e o `node --check` só pega erro de SINTAXE — chamada a função inexistente é sintaxe
perfeitamente válida e só explode no navegador, na hora de desenhar. Uma única chamada órfã cala a
tela inteira, porque a exceção interrompe o laço que monta todos os cards.

Este arquivo trava a classe do erro, não só o caso: toda função auxiliar (a convenção da casa é o
`_` na frente) chamada numa tela tem de estar definida na mesma tela.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import app

RAIZ = pathlib.Path(app.__file__).resolve().parents[1]
TELAS = [RAIZ / "docs" / "redesign" / "Monitoramento (novo design).html",
         RAIZ / "docs" / "redesign" / "Entrada.html"]
NODE = shutil.which("node")

_ID = r"_[A-Za-z][A-Za-z0-9_]*"


def _scripts(html: str) -> str:
    return "\n".join(re.findall(r"<script[^>]*>(.*?)</script>", html, re.S))


def _sem_comentarios(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    return re.sub(r"(?m)(^|[^:\\])//[^\n]*", r"\1", js)      # preserva o "//" de http://


def funcoes_fantasma(js: str) -> list:
    """Chamadas a `_algo(` sem nenhuma definição de `_algo` no mesmo código."""
    js = _sem_comentarios(js)
    chamadas = set(re.findall(r"(?<![.\w$])(" + _ID + r")\s*\(", js))
    defs = set(re.findall(r"function\s+(" + _ID + r")\s*\(", js))
    defs |= set(re.findall(r"(?:const|let|var)\s+(" + _ID + r")\s*=", js))
    defs |= set(re.findall(r"(?<![.\w$])(" + _ID + r")\s*=(?!=)", js))
    defs |= set(re.findall(r"window\.(" + _ID + r")\s*=", js))
    defs |= set(re.findall(r"[,(]\s*(" + _ID + r")\s*[,)=]", js))       # parâmetro
    return sorted(chamadas - defs)


@pytest.mark.parametrize("tela", TELAS, ids=lambda p: p.name)
def test_nenhuma_chamada_a_funcao_que_nao_existe(tela):
    fantasmas = funcoes_fantasma(_scripts(tela.read_text(encoding="utf-8")))
    assert not fantasmas, f"{tela.name} chama funções que não estão definidas: {fantasmas}"


def test_o_varredor_ACHA_o_caso_real():
    """Prova de que o detector funciona: o trecho exato que quebrou a ETM tem de ser acusado."""
    js = "const sensHtml=_etmSensTile('POA',sens&&sens.poa); function _etmEstado(r){return r}"
    assert funcoes_fantasma(js) == ["_etmSensTile"]


def test_o_varredor_nao_acusa_o_que_esta_definido():
    js = ("function _a(x){return x} const _b=()=>1; let _c=function(){}; window._d=()=>0;"
          "_a(1);_b();_c();_d(); [1].map((_e)=>_e); obj._naoConta(); // _comentado()\n/* _bloco() */")
    assert funcoes_fantasma(js) == []


# ── o bloco de sensor em si ───────────────────────────────────────────────────

def _roda(expr):
    if not NODE:
        pytest.skip("node não instalado")
    mon = TELAS[0].read_text(encoding="utf-8")
    i = mon.index("function _etmSensTile(")
    j = mon.index("\n", mon.index("W/m² pico", i))
    js = mon[i:j] + "\nprocess.stdout.write(JSON.stringify(" + expr + "));"
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_sensor_sem_leitura_e_cinza_e_diz_sem_leitura():
    h = _roda("_etmSensTile('POA-RI', {pico:null, status:'sem_leitura'}, true)")
    assert "sem leitura" in h and 'class="gc-etm-sn x"' in h


def test_sensor_nulo_nao_quebra():
    """Estação sem dado nenhum manda `sens` nulo — o bloco tem de sair cinza, não derrubar o card."""
    assert "sem leitura" in _roda("_etmSensTile('GHI', null)")


def test_GHI_zerado_e_vermelho_POA_RI_zerado_e_so_aviso():
    """A régua de 10/09: só IPOA/GHI medidos em zero alarmam; POA-RI zerado é aviso (azul)."""
    assert "zerado" in _roda("_etmSensTile('GHI', {pico:0, status:'zerado'})")
    h = _roda("_etmSensTile('POA-RI', {pico:0, status:'zerado'}, true)")
    assert "aviso" in h and "zerado" not in h.split("W/m²")[1]


def test_sensor_ok_mostra_o_pico_formatado():
    assert "1.099" in _roda("_etmSensTile('POA', {pico:1098.8, status:'ok'})")
