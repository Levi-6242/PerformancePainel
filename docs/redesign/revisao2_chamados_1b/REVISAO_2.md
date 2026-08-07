# Revisão 2 — o que ficou

Os nove itens da revisão anterior estão aplicados e conferem no render. Bolinhas redondas com
halo, borda do card pela cor da coluna, "atualizado hoje" em verde, filtros compactos com o
rótulo dentro, painel centralizado, Fechar no header, trilho contínuo. Bom trabalho.

Sobraram três. As duas primeiras são de dez minutos; a terceira é a que importa.

---

## 1. A faixa clara dentro do cartão verde da timeline

No render `2_detalhe_chamado.png`, dentro do cartão da entrada de 05/07, há uma banda mais
clara atrás da linha de texto, indo até quase a borda direita.

**É a armadilha que você já documentou** — a mesma do `QFrame#chLado`, num lugar novo:

```python
# chamado_detalhe.py, _Entrada.__init__
corpo.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:10px;}"
                    % (T.rgba(T.ACCENT, 0.06), T.rgba(T.ACCENT, 0.18)))
```

Seletor `QFrame` puro. **QLabel herda de QFrame**, então o `tx` lá dentro recebe a mesma tinta
de novo — o verde a 6% é aplicado duas vezes na altura exata de uma linha de texto. A banda é
o segundo passe.

```python
# DEPOIS
corpo.setObjectName("chCorpo")
corpo.setStyleSheet("QFrame#chCorpo{background:%s;border:1px solid %s;border-radius:10px;}"
                    % (T.rgba(T.ACCENT, 0.06), T.rgba(T.ACCENT, 0.18)))
```

O ramo `else` logo abaixo tem o mesmo seletor solto (`QFrame{background:transparent;...}`).
Hoje é inofensivo, mas é a mesma bomba armada — troque para `QFrame#chCorpo` também.

**Regra geral, vale escrever no README:** nunca use `QFrame`, `QLabel` ou `QWidget` como
seletor sem `#id` num stylesheet de widget. Em Qt o seletor pega os filhos, e metade da
hierarquia herda de QFrame.

## 2. A seta do combo sai como um traço cinza

O truque de bordas não funciona em `::down-arrow`: o Qt trata a subcontrol como caixa com
tamanho mínimo e desenha um retângulo. Aparece nos dois filtros do board e nos dois combos do
detalhe.

Vale a regra da §1 da revisão anterior: **seta é marca, marca se pinta.** Adicionei
`Combo` em `chamado_pecas.py` — um `QComboBox` que desenha o chevron no `paintEvent`.

```python
from chamado_pecas import Combo
self.cb_fabf = Combo()          # no lugar de QComboBox()
```

E na folha, some com o truque:
```css
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: none; width: 0; height: 0; }
```

Enquanto isso: a barra de rolagem da timeline aparece com nada para rolar e o punho sai claro
demais. `rolo.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)` e baixe o
punho para `rgba(255,255,255,0.09)` com `width: 8px`.

## 3. A tela "Abrir chamado" continua no tema antigo — e é a mais usada

`3_abrir_chamado_TEMA_ANTIGO.png`: cards azul-marinho, círculos verdes numerados, campos com
fundo preenchido, botão desabilitado cinza-claro. Nada disso é do 1B.

E essa é **a tela que o supervisor abre**, todo dia, para cada chamado. As outras duas são da
equipe de chamados, que é um punhado de pessoas. Se só uma tela puder ser portada agora, é
esta — não as que já estão prontas.

O que muda, na ordem:

**Numeração das seções.** Círculo verde preenchido com número dentro é do tema antigo e queima
o verde de ação em decoração. No 1B a seção é o rótulo `sectionLabel` (10.5/600, tracking +1,
maiúsculas, `TEXT_LABEL`) com uma `Regua` embaixo — igual a "DADOS" e "ATUALIZAÇÕES" no
detalhe. Sem número: a ordem vertical já é a ordem.

**Os cards de seção.** Hoje são `QFrame` azul-marinho com raio grande. Devem ser a mesma
superfície do resto: nenhuma. As quatro seções são blocos empilhados num `QFrame#panel`
único, separados por `Regua`, com 26px de respiro. Uma moldura por seção fragmenta a tela em
quatro caixas que competem entre si.

**A grade de fabricantes.** Nove botões iguais numa grade 5×2 é o pedaço mais importante da
tela e o mais engessado. Vira uma linha de pílulas de contorno que quebram, mesmas do chip do
card: `QPushButton` checkable, borda `rgba(255,255,255,.12)`, texto `TEXT_CHIP`; o
selecionado ganha borda `rgba(166,226,46,.5)` e texto `ACCENT`. Largura pelo conteúdo, nunca
fixa. Isso encolhe o bloco de duas fileiras de 70px para uma faixa de ~40px, e libera a tela
para o que interessa — a seção 3, que hoje é uma linha de texto cinza.

**Os campos.** `QLineEdit`/`QComboBox` da folha 1B: fundo `rgba(255,255,255,.04)`, borda 1px,
raio 9. Nada de campo com fundo mais claro que o card.

**O rodapé.** "Abrir chamado" é `QPushButton#primary` (contorno verde). Desabilitado usa a
regra `:disabled` da folha, não um cinza próprio. E o `hint` ("Escolha o fabricante.") fica
colado à esquerda do botão, não na outra ponta da tela — o aviso tem que estar onde o olho já
está.

**Herança da folha.** O diálogo faz `setStyleSheet(QSS_FORM + _folha())`. `QSS_FORM` é o
tema antigo e vem primeiro, mas ele estiliza classes que a folha 1B não menciona
(`Card`, `campo()`) — por isso o azul-marinho sobrevive. A saída não é ordem de folha: é
parar de usar `Card` e `campo()` do `steps.ui` nesta tela e montar com as peças do 1B,
como `chamado_detalhe.py` já faz.

---

## Checklist

- [ ] Nenhum stylesheet de widget com seletor `QFrame`/`QLabel`/`QWidget` sem `#id`
      (`grep -n 'setStyleSheet("QFrame{\|setStyleSheet("QLabel{'`)
- [ ] Cartão verde da timeline sem banda clara atrás do texto
- [ ] Chevron triangular nos quatro combos
- [ ] Barra de rolagem só quando há o que rolar
- [ ] "Abrir chamado" sem círculos numerados e sem cards azul-marinho
- [ ] Fabricantes como pílulas de contorno numa faixa, não grade de botões
- [ ] Nenhum `Card`/`campo` de `steps.ui` em `abrir_chamado.py`
