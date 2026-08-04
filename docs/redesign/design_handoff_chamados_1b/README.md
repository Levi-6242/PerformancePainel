# Handoff: aba Chamados — direção 1B (board respirado)

> **Leia isto inteiro antes de escrever uma linha de código.** Este documento existe porque
> tentativas anteriores de "recriar o design" produziram uma versão genérica. Os números
> abaixo não são sugestões: são a especificação.

---

## 1. O que é este pacote

| Arquivo | O que é |
|---|---|
| `chamados_1b_standalone.html` | **A referência visual.** Abra no navegador. É o alvo. |
| `Chamados 1B.dc.html` | Fonte do mesmo design (mesmo markup, estilos inline). Use para ler valores exatos. |
| `tokens.py` | Todos os valores do design como constantes Python. **Importe, não redigite.** |
| `chamados.qss` | Folha de estilo Qt já escrita a partir dos tokens. Ponto de partida. |
| `PROMPT.md` | O que colar no Claude Code para iniciar a tarefa. |

Os HTMLs são **referência de design**, não código de produção. A tarefa é **reproduzir esse
resultado visual no app Qt existente** (PySide/PyQt + QSS), respeitando os padrões do
codebase — não portar HTML.

**Fidelidade: alta (hi-fi).** Cores, tipografia, espaçamento e hierarquia são finais.
Reproduza fielmente. Onde o Qt não alcançar, use a seção "Degradações permitidas" (§8) —
não improvise.

---

## 2. A ideia do design em uma frase

Um board de três colunas agrupado por **quem está travando o chamado** (não por status),
onde o **número da OS** é a âncora visual de cada card e o **tempo parado** é a informação
que grita. Fundo escuro dessaturado, cor usada como sinal — nunca como decoração.

Se a sua implementação não deixar claro em 1 segundo *qual OS* e *em que estado ela está*,
ela está errada, mesmo que os pixels batam.

---

## 3. Regras não negociáveis

1. **Verde `#A6E22E` só em ação e marca.** Botões são *outline* (borda 1px + texto verde,
   fundo transparente). Nunca botão verde preenchido. Nunca verde em texto corrido, header
   de tabela, borda de card ou fundo de seção.
2. **Sem chips de status com fundo colorido e largura fixa.** Status é **texto colorido**
   (peso 600) precedido por um ponto de 7px. Foi exatamente isso que resolveu o estouro de
   coluna do layout antigo.
3. **Número da OS em fonte mono, peso 700, `letter-spacing` negativo.** É o único elemento
   com essa tipografia no card. Não use mono em mais nada além de OS, serial, ticket, datas
   e contadores.
4. **Máximo 2 cores de fundo no app.** `#0C111C` (ground) e `#131928` (card). Todo o resto
   é a mesma cor com transparência.
5. **Nada de sombra pesada, nada de gradiente chamativo.** Profundidade = borda 1px clara
   + um leve gradiente vertical de 11% de opacidade no topo do card. Só.
6. **Hierarquia é tamanho e espaço, não peso.** Não engorde títulos para dar destaque.
7. **Sem emoji, sem ícone decorativo, sem ilustração.** O único "ícone" é o ponto de status.
8. **Vazio é resultado, não bug.** Coluna sem chamados mostra uma linha de texto discreta,
   não um card placeholder.

---

## 4. Design tokens

Todos em `tokens.py`. Reproduzidos aqui para conferência.

### Cores — fundo e superfície
| Token | Hex | Uso |
|---|---|---|
| `BG` | `#07090F` | fundo da janela |
| `SURFACE` | `#0C111C` | painel principal (base do gradiente) |
| `SURFACE_TOP` | `#111624` | topo do gradiente do painel |
| `CARD` | `#131928` | fundo do card |
| `CARD_MUTED` | `#111726` | card de chamado concluído |
| `BORDER` | `rgba(255,255,255,.07)` | borda de painel |
| `BORDER_STRONG` | `rgba(255,255,255,.12)` | borda de input / chip |
| `DIVIDER` | `rgba(255,255,255,.10)` | linha divisória, trilho da timeline |

### Cores — texto
| Token | Hex | Uso |
|---|---|---|
| `TEXT` | `#E7EAF2` | texto principal |
| `TEXT_BRIGHT` | `#FFFFFF` | número da OS ativa |
| `TEXT_DIM` | `#C9CFDE` | texto de item concluído |
| `TEXT_MUTED` | `#7A85A0` | linha secundária (cliente · usina) |
| `TEXT_FAINT` | `#5B6479` | metadados (pai 9102, placeholder) |
| `TEXT_LABEL` | `#4E576D` | rótulos uppercase de seção |
| `TEXT_CHIP` | `#96A0B8` | texto do chip de fabricante |

### Cores — semáforo (estado do chamado)
| Token | Hex | Significa |
|---|---|---|
| `RED` | `#F5766B` | ação nossa / a abrir / atraso crítico |
| `AMBER` | `#F5A623` | aguardando fabricante ou cliente |
| `BLUE` | `#4A9EF5` | em andamento / garantia aprovada |
| `GREEN` | `#48D07A` | concluído / atualizado hoje |
| `ACCENT` | `#A6E22E` | verde Grid — ação e marca |
| `ACCENT_HOVER` | `#C4F154` | hover do verde |

Variantes claras para **texto** sobre fundo escuro (quando o hex puro fica saturado demais):
`RED_TEXT #F79B92` · `AMBER_TEXT #F5C46A` · `BLUE_TEXT #8AC0FA` · `GREEN_TEXT #7FDCA2`

Fundos tingidos (topo do card, header de coluna): a mesma cor a **11%** (`.11`) no card e
**22–28%** na borda/linha de coluna.

### Tipografia
Famílias: **Inter** (UI) e **JetBrains Mono** (números). Ambas são OFL — podem ser
embarcadas no instalador. Baixe em rsms.me/inter e jetbrains.com/lp/mono, coloque os
`.ttf` em `assets/fonts/` e registre no boot com `QFontDatabase.addApplicationFont`.
Fallback `Segoe UI` / `Consolas` — aceitável em dev, **não** para release: a Segoe UI não
reproduz o peso 500 nem o tracking negativo da OS.

`letter-spacing` não existe no QSS. Aplique por código:
```python
f = QFont("JetBrains Mono", 19, QFont.Bold)
f.setLetterSpacing(QFont.AbsoluteSpacing, -1.1)
```

| Papel | Fonte | px | Peso | Letter-spacing |
|---|---|---|---|---|
| Número da OS (card) | Mono | **19** | 700 | −1.1 |
| Número da OS (detalhe) | Mono | **24** | 700 | −1.3 |
| Título do painel | Inter | 20 | 500 | −0.3 |
| Título do chamado | Inter | 13.5 | 600 | 0 |
| Título no detalhe | Inter | 15 | 600 | 0 |
| Linha secundária | Inter | 11.5 | 400 | 0 |
| Status (texto colorido) | Inter | 11 | 600 | 0 |
| Header de coluna | Inter | 11.5 | 700 | +0.9, UPPERCASE |
| Rótulo de seção | Inter | 10.5 | 600 | +1.0, UPPERCASE |
| Chip de fabricante | Inter | 10.5 | 600 | 0 |
| Metadado (pai 9180) | Inter | 10.5 | 400 | 0 |
| Data na timeline | Mono | 12 | 700 | 0 |
| Ano na timeline | Inter | 10 | 400 | 0 |
| Corpo da atualização | Inter | 12.5 | 400 | line-height 1.55 |
| Botão | Inter | 12.5 | 600 (primário) / 400 | 0 |

> Se o app roda em DPI escalado, converta com o `devicePixelRatio` — não arredonde valores
> para "números redondos". 13.5px é 13.5px.

### Espaçamento e forma
| Token | Valor |
|---|---|
| Raio do painel | 16 |
| Raio do card | 14 |
| Raio de input/botão | 9–10 |
| Raio do chip | pill — no Qt use `altura/2` (≈11 numa pill de 22px), nunca 9 |
| Padding do painel | 22 topo / 24 laterais / 26 base |
| Padding do card | 16 / 16 / 14 |
| Gap entre cards da coluna | 12 |
| Gap entre colunas | 16 |
| Gap interno do card | 11 |
| Largura do board | fluido, max 1280 |

---

## 5. Estrutura das telas

### 5.1 Painel — board

```
QFrame#panel  (radius 16, borda 1px BORDER, fundo gradiente SURFACE_TOP→SURFACE)
└── QVBoxLayout (margens 24,22,24,26 · spacing 20)
    ├── header: QHBoxLayout
    │   ├── QVBoxLayout: "Chamados" (20px/500) + resumo (12px MUTED,
    │   │   com "7 a abrir" em RED peso 600)
    │   ├── stretch
    │   ├── toggle Board|Lista  (QFrame radius 10, dois QPushButton checkable;
    │   │                        ativo = fundo ACCENT + texto #0B1020)
    │   └── botão "Atualizar" (outline verde)
    └── board: QHBoxLayout (spacing 16, alinhado ao topo)
        ├── coluna "AÇÃO NOSSA"      (RED)
        ├── coluna "COM O FABRICANTE"(AMBER)
        └── coluna "EM ANDAMENTO"    (BLUE)
```

**Coluna** = `QVBoxLayout` (spacing 12) com:
- **header**: ponto 7px da cor da coluna · rótulo UPPERCASE 11.5/700 na cor da coluna ·
  stretch · contador mono 11.5/700 em `TEXT_MUTED` com **dois dígitos** (`02`, não `2`).
  Abaixo, borda inferior 1px na cor da coluna a 28% e 9px de respiro.
- **cards** empilhados, altura livre (nunca fixa).
- **stretch no fim** — os cards sobem, não se distribuem.

**Card** (`QFrame`, radius 14, borda 1px na cor do grupo a 22%):
```
QVBoxLayout (margens 16,16,16,14 · spacing 11)
├── linha 1: OS mono 19/700 · "pai 9180" 10.5 FAINT · stretch · status 11/600 colorido
├── divisória 1px (DIVIDER, esmaecendo à direita)
├── bloco: título 13.5/600 (line-height 1.35) + "Cliente · Usina — UF" 11.5 MUTED
└── rodapé: chip de fabricante (pill outline) · stretch ·
            tempo parado (mono 11/700 na cor de urgência, precedido de barra 26×3px)
```
Fundo do card: gradiente vertical da cor do grupo a **11%** no topo → `CARD` a partir de 46%.

**Card concluído**: fundo `CARD_MUTED`, borda neutra, opacidade 72% (no Qt:
`QGraphicsOpacityEffect(0.72)` ou simplesmente use os tons `TEXT_DIM`), volta a 100% no hover.

**Regra de agrupamento** (é o coração da direção 1B):
| Coluna | Entram os chamados cujo "aguardando" é… |
|---|---|
| Ação nossa | Grid / Pré-Operação / vazio, **e** os "A abrir" |
| Com o fabricante | Fabricante ou Cliente |
| Em andamento | garantia aprovada, em trânsito, e concluídos recentes |

### 5.2 Tela do chamado

```
QFrame#panel
├── header  (fundo: gradiente da cor do estado a 10% → transparente; borda inferior 1px)
│   ├── esquerda: linha de estado (ponto + STATUS UPPERCASE colorido + "· aguardando X ·
│   │             41 dias" com o número em RED) / OS mono 24 + título 15/600 /
│   │             "Cliente · Usina — UF · OS pai 9102 · Em Processo" 12.5 MUTED
│   └── direita: "Salvar situação" (outline verde) + "Abrir a OS no app" (outline neutro)
└── corpo: QHBoxLayout
    ├── coluna esquerda 300px fixos (borda direita 1px)
    │   ├── "DADOS": 4 linhas rótulo↔valor (rótulo 12 MUTED à esquerda,
    │   │   valor 12.5 à direita; mono nos códigos; "—" em FAINT quando vazio)
    │   ├── divisória
    │   ├── QComboBox "Status do chamado"
    │   ├── QComboBox "Aguardando"
    │   └── "Marcar como aberto" (outline neutro)
    └── coluna direita (stretch)
        ├── "ATUALIZAÇÕES" + contador mono "05"
        ├── composer: QTextEdit placeholder "O que aconteceu? (a data entra sozinha)"
        │   (min-height 58, radius 10) + botão "Adicionar" alinhado à base
        └── timeline
```

**Timeline** (o detalhe que define a tela):
- Cada entrada é `QHBoxLayout` (spacing 14): gutter **52px** alinhado à direita com
  data mono 12/700 + ano 10, depois o corpo.
- O corpo tem **borda esquerda 1px** `DIVIDER` (o trilho contínuo) e **padding-left 16**.
- Sobre o trilho, um **ponto** posicionado em `left:-4px`.
- **As datas e os pontos são coloridos por natureza do evento** — é isso que dá vida:
  - entrada mais recente / ação nossa → `ACCENT` (ponto 9px, data verde) **e** o corpo
    ganha um cartão `rgba(166,226,46,.06)` com borda `rgba(166,226,46,.18)`, radius 10;
  - mudança de status → `AMBER` (ponto 8px, data âmbar), sem cartão;
  - histórico / importado de planilha → ponto `#3B435C` 7px, data `TEXT_MUTED`.
- Autor em 10.5 `TEXT_FAINT`; origem importada em 10 itálico `TEXT_LABEL` ("planilha").

---

## 6. Estados e interação

| Elemento | Normal | Hover | Pressed | Focus |
|---|---|---|---|---|
| Botão primário | borda `rgba(166,226,46,.5)`, texto `ACCENT`, fundo transparente | fundo `rgba(166,226,46,.12)`, borda `ACCENT` | fundo `rgba(166,226,46,.18)` | borda `ACCENT` sólida |
| Botão neutro | borda `rgba(255,255,255,.14)`, texto `TEXT_DIM` | borda `rgba(166,226,46,.5)`, texto `#FFF` | idem + fundo `rgba(255,255,255,.04)` | idem |
| Card | borda da cor do grupo a 22% | **borda a 55%** (única mudança) | — | borda `ACCENT` |
| Combo / input | borda `BORDER_STRONG` | borda `rgba(166,226,46,.45)` | — | idem |
| Card concluído | opacidade 72% | 100% | — | — |

- Card inteiro é clicável → abre a tela do chamado.
- Nenhuma animação obrigatória. Se houver transição, 120–160ms, só em cor de borda.
- Todo controle precisa de `:focus-visible` visível — nunca o anel azul padrão do sistema.
- Cursor `PointingHandCursor` em card e botão.

---

## 7. Conteúdo e cópia

Use exatamente estes textos onde forem rótulos fixos:
"Chamados" · "Atualizar" · "Board" / "Lista" · "AÇÃO NOSSA" / "COM O FABRICANTE" /
"EM ANDAMENTO" · "Salvar situação" · "Abrir a OS no app" · "Marcar como aberto" ·
"Adicionar" · "DADOS" · "ATUALIZAÇÕES" · placeholder "O que aconteceu? (a data entra sozinha)".

Formatos: OS sem prefixo (`9587`), OS pai como `pai 9102`, local como
`Cliente · Usina — UF`, tempo como `41 dias parado` / `3 dias parado` / `sem histórico` /
`atualizado hoje`, data como `25/07` + ano em linha separada, contador com dois dígitos.

Tom: telegráfico, minúsculas nos textos de apoio, sem ponto final em rótulo.

---

## 8. Degradações permitidas no Qt

O QSS não tem flexbox, gap, `box-shadow` nem opacidade por elemento. Faça assim:

| No HTML | No Qt |
|---|---|
| flex + gap | `QVBoxLayout/QHBoxLayout` + `setSpacing()` + `setContentsMargins()` |
| `box-shadow` de glow no ponto | **omita** (ou `QGraphicsDropShadowEffect` com blur 10, sem offset) |
| gradiente do card | `qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(...,28), stop:0.46 #131928)` |
| barra de tempo 26×3px | `QFrame` `setFixedSize(26,3)` com `border-radius:2px` |
| divisória esmaecida | `QFrame` 1px com `qlineargradient` horizontal para transparente |
| ponto colorido 7px | `QLabel` `setFixedSize(7,7)` + `border-radius:3px` (ou 4px em 8px) |
| `opacity: .72` no card | `QGraphicsOpacityEffect` **ou** trocar as cores de texto por `TEXT_DIM`/`TEXT_FAINT` (preferível — mais barato) |
| `white-space: nowrap` | `setWordWrap(False)` + `setSizePolicy(Fixed, …)` no botão |
| altura de card livre | **nunca** `setFixedHeight` — `QSizePolicy.Minimum` no vertical |
| `outline` de foco | Qt ignora `outline` no QSS — foco é `border-color: #A6E22E` |
| `letter-spacing` | **não existe em QSS.** Use `QFont.setLetterSpacing(QFont.AbsoluteSpacing, -1.1)` — sem isso o número da OS perde o caráter |
| raio pill (999) | `border-radius: altura/2` — meça a altura real do QLabel |

O que **não** pode degradar: os hexes, os tamanhos de fonte, os pesos, os raios, o
espaçamento e a regra do botão outline.

---

## 9. Checklist de aceite

Passe por esta lista antes de dizer que terminou. Compare lado a lado com
`chamados_1b_standalone.html` aberto no navegador.

- [ ] Nenhum botão com fundo verde sólido (exceto a aba "Board" ativa do toggle)
- [ ] Nenhum chip de status com fundo colorido
- [ ] Número da OS em mono 19px, peso 700, mais claro que tudo ao redor no card
- [ ] Três colunas com header colorido, contador de dois dígitos e borda inferior tingida
- [ ] Cards com altura variável — nenhum `setFixedHeight`
- [ ] Gradiente sutil no topo do card, na cor do grupo
- [ ] Hover do card muda **só** a borda
- [ ] Chip de fabricante é pill outline, não preenchido
- [ ] Tempo parado com barrinha + número mono colorido por urgência
- [ ] Timeline com trilho contínuo, pontos alinhados sobre ele e datas coloridas
- [ ] Entrada mais recente da timeline em cartão verde translúcido
- [ ] Coluna de dados com 300px fixos e borda direita
- [ ] `:focus-visible` verde em todo controle; nada de anel azul do sistema
- [ ] Fundo geral `#0C111C`, sem preto puro e sem branco puro fora do número da OS
- [ ] Nada de emoji, ícone decorativo ou ilustração
- [ ] Inter e JetBrains Mono registradas via `addApplicationFont` (não fallback)
- [ ] `setLetterSpacing` aplicado no número da OS (−1.1 no card, −1.3 no detalhe)

## 10. Arquivos de referência no repo

`docs/redesign/chamados_aba.html` — a réplica do layout **antigo** (o ponto de partida,
para diferença). Este pacote é o **alvo**.
