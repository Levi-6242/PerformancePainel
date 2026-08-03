# Cole isto no Claude Code

Chegou uma revisão de design do porte da aba Chamados. A pasta `correcao_chamados_1b/`
está no repositório.

Faça nesta ordem:

1. Leia `correcao_chamados_1b/LEIA_PRIMEIRO.md` inteiro. A §1 tem a regra que faltava
   e explica por que todo ponto das duas telas saiu quadrado.
2. Copie `chamado_pecas.py` para junto de `chamados.py`.
3. Substitua `assets/chamados.qss` pela versão desta pasta. Repare na primeira regra —
   ela mudou, e isso deixa de exigir `background:transparent` em cada QLabel.
4. Aplique os patches da §3, um por vez, na ordem em que estão. São nove.
5. Rode o checklist da §5 item por item e me devolva o resultado de cada um.
   Rode também os dois `grep` do checklist e cole a saída.

Regras:

- Apague as duas classes `_Ponto` (uma em cada arquivo). Elas divergiram e é por isso
  que o mesmo bug apareceu em dobro. Marca é uma só, e mora em `chamado_pecas.py`.
- **Raio fracionário em QSS é sempre bug.** O parser do Qt descarta a declaração inteira.
  Se você escrever `border-radius: 3.5px` de novo, o ponto volta a ser quadrado.
- Não invente valor: tudo vem de `chamado_tokens`. O grep tem que sair vazio.
- Nada de `QGraphicsDropShadowEffect` para o glow — é `QRadialGradient` no `paintEvent`,
  já pronto em `Ponto`.
- Se um patch conflitar com o padrão do codebase, pergunte antes de decidir.

Três respostas às perguntas que você deixou abertas: o glow tem solução (§4.1); a data
antiga é `TEXT_MUTED`, confirmado (§4.2); o trilho da timeline é **contínuo**, o HTML
estava errado (§4.3); e o painel fica capado em 1280 mas **centralizado** (§4.4).
