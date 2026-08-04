# Prompt inicial para o Claude Code

Cole isto na primeira mensagem, com a pasta `design_handoff_chamados_1b/` no repositório.

---

Você vai reimplementar a aba **Chamados** do app seguindo um design já aprovado.

Leia, nesta ordem, antes de qualquer coisa:
1. `design_handoff_chamados_1b/README.md` — a especificação. É normativa.
2. `design_handoff_chamados_1b/chamados_1b_standalone.html` — abra no navegador. É o alvo visual.
3. `design_handoff_chamados_1b/tokens.py` e `chamados.qss` — os valores já prontos.

Regras de trabalho:

- **Não invente valores.** Toda cor, tamanho de fonte, peso, raio e espaçamento vem de
  `tokens.py`. Se você digitou um hex que não está lá, está errado.
- **Não simplifique.** "Aproximado" não serve: o gradiente de 11% no topo do card, o
  letter-spacing de −1.1 na OS, o contador de dois dígitos e as datas coloridas da timeline
  são parte do design, não enfeite.
- Antes de codar, **descreva em 10 linhas** a árvore de widgets que você vai montar para o
  board e para a tela do chamado, e espere meu OK.
- Implemente **uma tela por vez**: primeiro o board, mostre, depois a tela do chamado.
- Ao terminar cada tela, rode o **checklist da §9 do README** item por item e me diga o
  resultado de cada um. Não afirme que terminou sem isso.
- Use os padrões que já existem no codebase para layout, sinais e nomes de arquivo. Se
  houver conflito entre o padrão do codebase e o README, pergunte — não decida sozinho.

Por que as tentativas anteriores falharam: o resultado ficou genérico — botão preenchido,
chip colorido, card de altura fixa, tipografia toda no mesmo tamanho. O que dá caráter a
este design é a **hierarquia extrema** (OS enorme em mono, apoio minúsculo em cinza) e a
**cor usada como sinal, não como decoração**. Se a sua tela parecer "um dashboard bonitinho
qualquer", você errou.
