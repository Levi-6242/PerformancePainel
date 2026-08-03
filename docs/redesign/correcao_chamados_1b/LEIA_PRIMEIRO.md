# Leia primeiro — por que o porte fica "quase certo" e como fechar

Este pacote corrige o porte PyQt6 do design **Chamados 1B**. Ele tem duas partes:

- **§1–§2**: a regra que estava faltando e o arquivo novo que a implementa (`chamado_pecas.py`).
- **§3**: os defeitos encontrados no código enviado, cada um com causa medida e o patch.

Tudo aqui foi lido contra `codigo/chamados.py`, `codigo/chamado_detalhe.py` e os dois renders
(`render/board_atual.png`, `render/detalhe_atual.png`).

Antes de mais nada: **o porte está bom.** A estrutura, os grupos, o gutter da timeline, a
descoberta do rgba-em-pai-transparente e a trava de release são trabalho sério e certo. O que
falta não é esforço, é **uma regra que ninguém tinha escrito** — está no §1.

---

## 1. A regra que faltava

> **Caixa se estiliza com QSS. Marca se pinta com QPainter.**

**Caixa** = card, botão, input, painel. Tem fundo, borda, raio, padding. QSS faz bem.
**Marca** = ponto, régua de 1px, barrinha de tempo, trilho, glow. Não tem conteúdo, é um
desenho. QSS faz mal, e falha de três jeitos que já aconteceram neste porte:

| Sintoma no render | Causa real |
|---|---|
| Todo ponto saiu **quadrado**, nas duas telas | `border-radius: 3.5px` — **o parser de QSS do Qt recusa comprimento fracionário e descarta a declaração inteira**. `_Ponto` gera o raio com `{tam/2:.1f}`, então 7px→"3.5px", 9px→"4.5px": todos caem. |
| Trilho e divisórias invisíveis | `rgba()` herdado da folha não compõe sobre pai transparente (você mediu — está certo) |
| Sem glow nos pontos | `box-shadow` não existe em QSS |

Os três somem de uma vez quando a marca é pintada: o `QPainter` compõe sobre qualquer pai,
aceita float sem reclamar, e o glow é um `QRadialGradient` de três linhas.

Isso responde sua **pergunta 1**: o glow tem solução, sim, e não é
`QGraphicsDropShadowEffect` (que é caro e borra o widget inteiro). É gradiente radial dentro
do `paintEvent` do próprio ponto. Está pronto em `chamado_pecas.Ponto`.

### O corolário: pare de escrever `background:transparent` em todo QLabel

A folha abre com `QWidget { background: #07090F; }`. Como `QLabel` é um `QWidget`, **todo
rótulo carimba um retângulo opaco** — você achou isso no número da OS (defeito #9 das suas
notas) e o consertou rótulo a rótulo. Não é um bug de rótulo, é a primeira linha da folha.

Corrigido no `chamados.qss` deste pacote:

```css
/* ANTES — a origem do problema */
QWidget { background: #07090F; color: #E7EAF2; font-family: "Inter", ...; }

/* DEPOIS — herança de cor/fonte sem carimbar fundo */
QWidget { color: #E7EAF2; font-family: "Inter", "Segoe UI", sans-serif; }
QWidget#chPage, QDialog { background: #07090F; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
```

Depois disso dá para apagar quase todos os `background:transparent` espalhados pelos dois
arquivos. Não é cosmético: cada um deles é um lugar onde o próximo rótulo vai errar de novo.

---

## 2. O arquivo novo

`chamado_pecas.py` — quatro marcas pintadas, sem dependência além de PyQt6:

| Peça | Substitui |
|---|---|
| `Ponto(cor, tam, glow=True)` | as **duas** classes `_Ponto` (uma em cada arquivo — divergiram, e é por isso que o bug apareceu em dobro) |
| `Regua(cor, alpha, esmaece=)` | `_divisor()` e `_regua()`, incluindo o fade-to-transparent |
| `Trilho(cor, alpha)` | a `linha` do `_Entrada` |
| `BarraTempo(cor)` | `_Barra` |

Um detalhe de uso: o box do `Ponto` cresce `Ponto.BLEED` (4px) de cada lado para caber o
halo. O **centro óptico não se move**, só a caixa. Onde o espaçamento importa, desconte:
`ch.setSpacing(9 - Ponto.BLEED)`. Os patches do §3 já fazem isso.

---

## 3. Defeitos encontrados e os patches

### 3.1 · Pontos quadrados — **as duas telas**

Apague `class _Ponto` de `chamados.py` **e** de `chamado_detalhe.py`. Em ambos:

```python
from chamado_pecas import Ponto, Regua, Trilho, BarraTempo
```

Em `chamados.py`, cabeçalho da coluna:
```python
# ANTES
ch = QHBoxLayout(); ch.setSpacing(9)
ch.addWidget(_Ponto(cor, T.DOT["idle"]))
# DEPOIS
ch = QHBoxLayout(); ch.setSpacing(9 - Ponto.BLEED)
ch.addWidget(Ponto(cor, T.DOT["idle"]))
```

Em `chamado_detalhe.py`, linha de estado do header:
```python
# ANTES
l1 = QHBoxLayout(); l1.setSpacing(10)
self.pt = _Ponto(cor0, T.DOT["idle"]); l1.addWidget(self.pt)
# DEPOIS
l1 = QHBoxLayout(); l1.setSpacing(10 - Ponto.BLEED)
self.pt = Ponto(cor0, T.DOT["idle"]); l1.addWidget(self.pt)
```

E em `_render` — **aqui o 3.5 está digitado à mão**, é o mesmo bug:
```python
# ANTES
self.pt.setStyleSheet(f"background:{cor};border-radius:3.5px;")
# DEPOIS
self.pt.setCor(cor)
```

Na timeline (`_Entrada`), troque `_Ponto(cor, tam)` por `Ponto(cor, tam, glow=(cor != T.DOT_IDLE))`
— o ponto cinza do histórico não acende — e a `linha` por `Trilho()`.

### 3.2 · A borda do card segue o STATUS, deveria seguir o GRUPO

No render, a coluna **EM ANDAMENTO** (azul) tem dois cards de borda **verde** (8903, 8904) e um
neutro (8273). Três cores dentro de uma coluna que já se declarou azul.

`_ChamadoCard` faz `cor = _status_cor(st)` e usa essa cor para **tudo**: a borda
(`setProperty("group", …)`), o gradiente do topo (`card_gradient(cor)`) e o texto do status.

O README §5.1 separa os dois eixos, e a separação é o que faz o board funcionar:

- **cor do GRUPO** → borda do card + gradiente do topo. Diz *em que coluna estou*.
- **cor do STATUS** → só o texto do status, no canto. Diz *em que etapa estou*.

Sem isso o olho não consegue ler a coluna como um bloco. Patch:

```python
# _ChamadoCard.__init__ — receber o grupo de quem cria o card
def __init__(self, d, on_click, cor_grupo=None):
    ...
    cor = _status_cor(st) if st else _STATUS_COR.get(d.get("status"), T.TEXT_MUTED)
    feito = _encerrado(st, d.get("status"))
    grupo = cor_grupo or cor          # cor da COLUNA — manda na moldura

    self.setProperty("group", _TOM.get(grupo, "blue"))
    if not feito:
        self.setStyleSheet("QFrame#card{background:%s;}" % T.card_gradient(grupo))
    ...
    ls.setProperty("tone", "green" if feito else _TOM.get(cor, "blue"))   # texto = STATUS
```

```python
# _render_board — passar a cor da coluna
for d in dados:
    c["lista"].addWidget(_ChamadoCard(d, self._abrir_os, _cor_grupo(nome)))
```

`_cor_grupo()` já existe no arquivo e não estava sendo usada.

### 3.3 · "atualizado hoje" sai cinza; deveria ser verde

```python
# ANTES
urg = (T.TEXT_FAINT if feito else
       (T.RED_TEXT if dias > 30 else (T.AMBER_TEXT if dias > 15 else T.TEXT_MUTED)))
# DEPOIS
if feito:      urg = T.TEXT_FAINT
elif dias > 30: urg = T.RED_TEXT
elif dias > 15: urg = T.AMBER_TEXT
elif dias == 0: urg = T.GREEN        # "atualizado hoje" é notícia boa e o card diz isso
else:          urg = T.TEXT_MUTED
```

### 3.4 · A faixa de filtros está pesada demais

No render ela é a segunda coisa que o olho pega, depois do título — dois campos de 190×40px com
"todos" escrito em ambos, ou seja, dois blocos grandes que **não informam nada** no estado
padrão. O board é para ler chamado, não para operar filtro.

Filtro é **cromo**: discreto quando inativo, aceso quando filtrando.

```python
# ANTES
l1 = QLabel("Fabricante"); l1.setObjectName("secondary"); fbl.addWidget(l1)
self.cb_fabf = QComboBox(); self.cb_fabf.addItem("todos", None)
...
self.cb_fabf.setFixedWidth(190); fbl.addWidget(self.cb_fabf)

# DEPOIS
self.cb_fabf = QComboBox(); self.cb_fabf.setObjectName("filtro")
self.cb_fabf.addItem("Fabricante: todos", None)          # o rótulo vive DENTRO do campo
for f in cspec.TODOS_FABRICANTES:
    self.cb_fabf.addItem("Fabricante: " + f, f)
self.cb_fabf.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
```

Idem para `cb_espf` com `"Aguardando: …"`. A folha nova traz `QComboBox#filtro` (11px,
padding 5/10, raio 8) e acende a borda em verde quando há filtro:

```python
def _pintar_filtro(cb):
    cb.setProperty("ativo", "true" if cb.currentData() else "false")
    cb.style().unpolish(cb); cb.style().polish(cb)
```
Chame nos dois `currentIndexChanged`, junto do `_render_board`.

Os combos também estavam **sem seta** no render — `::drop-down { border:none }` apaga o frame e
o tema escuro fica sem imagem de seta. A folha nova desenha o chevron com o truque de bordas.

### 3.5 · Cards com buraco vertical (coluna 3 do render)

8903 e 8904 têm ~30px de vazio entre a usina e o rodapé, e o título de 8273 sai cortado em vez
de quebrar. É o mesmo defeito: `QLabel` com `setWordWrap(True)` e política horizontal
`Preferred` **exige a largura do texto inteiro**; a coluna não dá, o `heightForWidth` é
calculado contra a largura errada e sobra altura.

```python
# chamados.py — aplicar em tit e loc; chamado_detalhe.py — em at, lc, tx e no valor de _par
def _texto_flex(lb):
    """QLabel que quebra de verdade dentro da coluna.
    'Ignored' na horizontal = 'não peça largura, use a que sobrar' — sem isso o
    heightForWidth é medido contra a largura do texto inteiro e o card cresce à toa."""
    lb.setWordWrap(True)
    sp = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.MinimumExpanding)
    sp.setHeightForWidth(True)
    lb.setSizePolicy(sp)
    lb.setMinimumWidth(1)
    return lb
```

### 3.6 · `_chip()` ainda existe com fundo preenchido

`chamados.py` linha ~250: `_chip(..., forte=True)` pinta `background: rgba(cor,0.15)` +
borda. É exatamente o que a §3.2 do README proíbe e o que estourava as colunas no design antigo.
Hoje está morto no board, mas é o primeiro helper que alguém reusa. **Apague a função** — o
status é texto colorido com ponto, e o chip de fabricante é `QLabel#chip`, contorno puro.

### 3.7 · Hexes fora dos tokens

`from steps.ui import ... GREEN, MUTED, TEXT, INPUT, BORDER` e o literal `#2A3550` dentro de
`_chip`. Some com o `_chip`; e `_status_cor` termina em
`return _STATUS_COR.get(st, MUTED)` → troque por `T.TEXT_MUTED`.

Enquanto isso: `_status_cor` devolve `T.BLUE` para "teste". "Testes adicionais solicitados" é
o fabricante que pediu — a bola está com ele, é **âmbar**. Mova `"teste"` para o ramo do âmbar.

### 3.8 · O "Fechar" no rodapé

O design não tem barra de rodapé; ações de janela moram no header, junto de "Salvar situação" e
"Abrir a OS no app". O rodapé de hoje é uma faixa de 30px que só existe para um botão. Mova o
"Fechar" para a coluna `acoes` do header e mantenha só o `self.hint` embaixo — ou melhor,
mova o hint para junto do "Salvar situação", que é a ação que ele comenta, e apague o rodapé.

### 3.9 · Painel não centralizado

`env.addWidget(painel)` com `setMaximumWidth` deixa o painel colado à esquerda em monitor
grande. `env.addWidget(painel, 0, Qt.AlignmentFlag.AlignHCenter)`.

---

## 4. Suas perguntas abertas

**1 · O glow.** Tem solução — está no `Ponto`. Não use `QGraphicsDropShadowEffect`.

**2 · `#8A93A8` vs `TEXT_MUTED`.** Confirmado: `TEXT_MUTED`. O `#8A93A8` do HTML era ruído
meu; o token é a verdade.

**3 · Trilho contínuo ou interrompido.** Você seguiu o HTML e o HTML estava errado. **Contínuo.**
A timeline é uma linha só — o corte a cada 14px transforma o fio em três traços soltos e a
leitura vertical se perde. Em Qt: `box_log.setSpacing(0)` e o respiro de 14px vai para a
margem inferior do corpo da entrada, dentro do `_Entrada`, para o `Trilho` correr de ponta a
ponta. A última entrada não desenha trilho abaixo do ponto (`Trilho(fim=True)` no pacote).

**4 · `BOARD_MAX_WIDTH = 1280`.** Intencional — a três colunas, passar disso dá cards de 500px
que ninguém varre. Só **centralize** (§3.9): a faixa vazia dos dois lados é margem, a de um lado
só é bug.

---

## 5. Checklist da revisão

Ordem de impacto visual, do maior para o menor:

- [ ] Nenhum ponto quadrado em nenhuma das duas telas
- [ ] Pontos com halo, exceto o cinza do histórico
- [ ] Borda e gradiente do card = cor da **coluna**; só o texto do status usa a cor do status
- [ ] Faixa de filtros discreta, rótulo dentro do campo, chevron visível, borda verde quando ativo
- [ ] Nenhum card com vazio entre a usina e o rodapé; título longo quebra, não corta
- [ ] "atualizado hoje" em verde
- [ ] Trilho da timeline **contínuo** do primeiro ao último ponto
- [ ] Nenhum rodapé; "Fechar" no header
- [ ] Painel centralizado
- [ ] `grep -n "#[0-9A-Fa-f]\{6\}" chamados.py chamado_detalhe.py` → nenhum resultado
- [ ] `grep -n "border-radius:[0-9]*\.[0-9]"` → nenhum resultado (raio fracionário é sempre bug)
- [ ] `_chip` apagada
