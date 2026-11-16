# Sala de controle da Performance

O desenho foi aprovado pelo Levi em 16/11/2026 ("o desenho está tudo ok"), depois de 17 rodadas num mockup com dado real:
`docs/mockups/sala-de-controle/index.html` (a referência de tudo o que está abaixo; `lateral.html` guarda os três desenhos
da lateral que ele comparou). Este documento é o que a tela TEM de ser. A regra dele: **tudo o que o Tempo real faz hoje
tem de estar aqui, transformado na visão nova.**

## Para que serve

Uma tela só para a Performance responder: o que está em falha agora, o que ninguém está acompanhando e o que apareceu de
novo. Ele pediu a partir do "Control room" de um portal de fora, sem o mapa, o diagrama e a ficha do sistema.

## A tela

- **Lateral: um cartão por fonte do tempo real**, com o nome por extenso ("Thopen · Banco de dados"). Em cada cartão,
  três números: strings SEM acompanhamento, trackers SEM OS e estações com alarme, com o total embaixo ("de 52"). O que
  pede ação vem na frente e pintado. Clicar abre as usinas dentro do cartão, por criticidade: sem comunicação (roxo),
  crítica (vermelho), atenção (laranja), [desligada], normal (verde). Busca no padrão do Nexus (lupa, sem sugestão do
  navegador). O frescor à vista ("a cada 5 min · 11:01"). "Todas as fontes" é o primeiro cartão.
- **Quatro cartões de número no alto** (fundo e canto, SEM borda colorida, os números na mesma linha): strings sem
  acompanhamento, trackers sem OS, estações com alarme sem OS, inversores abaixo sem parada que explique. Clicáveis.
- **Visão geral em abas** (todas as fontes ou uma fonte), cabendo na primeira tela, a tabela rolando por dentro:
  - **Strings**: "O que olhar primeiro" (Novo, Crítico agora, Ver agora, Acompanhar), "Há quanto tempo as strings estão
    paradas" (faixas clicáveis, com e sem OS) e a tabela por usina.
  - **Trackers**: por usina (parados, sem OS, perda) e os Insights recolhidos (o que apareceu de novo, em falha por dia).
  - **ETM**: as estações, alarme na frente.
  - **Geração**: os inversores abaixo dos demais (os 10 piores, os sem explicação por usina, os EXPLICADOS com o que explica).
- **A usina** (clicar na lateral ou numa linha):
  - **Strings**: a curva por string EM CIMA dos cartões (clicar num inversor troca o gráfico); os inversores POR CABINE,
    cada cabine recolhe; a string colorida (gerando, corrente baixa, sem corrente, trancada, inversor desligado); a
    quantidade em acompanhamento DIGITÁVEL (por usina, sem setas); a OS de performance como ícone de ferramenta no cartão
    do inversor; os comentários embaixo dos cartões.
  - **Trackers**: o MESMO gráfico do Tempo real (`_trkChartInline` do Monitoramento: De/Até até 5 dias, visão reduzida,
    Ruins/Bons/Todos, a legenda que filtra, o Alvo, os cartões que entram e saem, CSV, Expandir); depois "Agora" e
    "Quando parou", os dois RECOLHIDOS, nessa ordem; clicar no "Quando parou" abre o gráfico no dia.
  - **ETM**, **Abaixo dos demais** (a linha abre os dias; o dia abre a curva por string dele), **Geração e PR** (um botão
    alterna; clicar no inversor abre "o que aconteceu": o dia a dia contra a mediana, a DISPONIBILIDADE do inversor e da
    usina, as paradas que o cobrem, as strings que caíram, as OS), **Potência** (por usina | por inversor, com POA e GHI),
    **Conferir fontes** (a fonte × o SCADA da Grid, inversor a inversor) e **De-para** (a tabela do Modo de-para).
- **Gráficos**: período solar (06 às 18h) por padrão, "Dia inteiro" à mão; passar o mouse mostra TODOS os valores do
  instante; o rótulo do eixo acima da área e o "18h" inteiro; Exportar Excel em Geração/PR e Potência (datas na 1ª
  coluna, inversores pivotados, e a irradiação).

## Regras que ele deu

- **Trancar/destrancar string**: pede confirmação antes de gravar, e só o setor Performance pode.
- **Criar OS pela tela**: marcar um ou vários inversores → UMA OS para todos, com o texto pronto e a data do evento =
  quando aconteceu (a 1ª parada). Antes de criar, avisar se o inversor já teve OS de recomposição de string nos últimos
  **60 dias** e mostrar qual ("o técnico faz, fecha e não resolve"); a mais antiga aparece à parte. A consulta ao Fracttal
  é SÓ no clique de Criar OS e só dos inversores marcados (em 16/11, 22 consultas seguidas bateram o teto de 200/min).
- **Ocorrência nova**: o que parou desde a última vez da PESSOA ganha a marca "nova" e PULSA (vermelho, só a borda, sem
  sombra nem zoom); o pulso do cartão para no clique; a marca some ao abrir o inversor. O cartão mostra a todos quem já
  viu e que já tem OS (evitar OS duplicada). No sino do Nexus, as novas chegam agrupadas POR USINA.
- **Acompanhamento** segue por usina (o `tracking` de hoje).
- **Disponibilidade por inversor**: a régua da Disponibilidade por OS (janela 06-18h, dia a dia, usina > cabine >
  inversor, união dos trechos); tem de sair do cálculo oficial, não de uma conta à parte.
- Movimento que informa (o pulso) roda mesmo com as animações do Windows desligadas.

## De onde vem o dado (o que já existe)

| O quê | Onde |
|---|---|
| Lateral e os números | `/api/entrada/tempo-real` (`grupos[].usinas[]`: `strings_faltando`, `strings_acomp`, `strings_nao_rec`, `trk_parados`, `trk_com_os`, `etm_alarmes`, `etm_os`) |
| Novo, em falha por dia, há quanto tempo, perda | `/api/painel/falhas?mes=` (`strings.episodios`, `strings.rows`, `trackers.rows`, `strings_os`) |
| Inversores e strings, trackers, ETM, curvas | as rotas de cada fonte que o Monitoramento já usa (`/api/pg/plant/<id>`, `/api/pg/trackers/<id>`, `.../chart?ini=&fim=`, `/api/pg/curva/<id>?data=`, e as equivalentes da API PV, SunOp, SolarEdge e scadaGridco) |
| Trancadas, acompanhamento, comentários, OS atribuída | `/api/state` e as rotas `/api/state/*` |
| OS de performance | `/api/os-performance?usina=` |
| OS de recomposição do inversor | `/api/painel/falhas/os?tipo=strings&usina=&inversor=&desde=` |
| Geração e PR, Potência | `/api/<fonte>/inversores/historico/<id>`, `/api/<fonte>/pr/<id>`, `/api/relatorio/potencia-ativa` |
| De-para | `/api/admin/de-para/usina?fonte=&id=` |
| Paradas do COS/Fracttal | livro `falhas_performance · disponibilidade_os_dia` no banco |

O que nasceu na entrega 3: `/api/sala/idade` (a idade além do mês), `/api/sala/visto` (o visto por pessoa),
`/api/sala/conferir` (o SCADA de agora), `/api/sala/exportar` (o Excel) e, no Nexus, a leitura do "abaixo dos demais"
(`/t/performance/sala-de-controle/abaixo`; a conta segue no `mural.py` do Conversor, que é o dono).

O que ainda NÃO existe: a novidade no sino DO NEXUS (o do topo, fora da tela); a conferência com o SCADA para usinas que
ele não tem, ou tem com outro nome (falta a lista do COS e o de-para com o SCADA); o atalho para o prontuário da usina
(o Comando > Usinas abre pelo id do cadastro do Nexus, que a plataforma não conhece).

## Entregas

1. **Leitura** (`/painel/sala-de-controle`): a lateral, os números, a visão geral em abas e a usina com Strings, Trackers
   e ETM, lendo as rotas que já existem. Não grava nada.
2. **Ações** (feita em 16/11/2026): trancar com confirmação e só a Performance, acompanhamento, comentários, criar OS
   com o aviso. Gravam pelas rotas do Tempo real; a OS nasce na tela do OS Creator, aberta por cima, com todos os
   inversores marcados numa OS só. Detalhe em `plataforma/CLAUDE.md`.
3. **O que é novo** (feita em 16/11/2026): o "abaixo dos demais" (lido do Nexus, o dono da conta), Geração e PR,
   Potência e o Excel, o que aconteceu com o inversor pelo cálculo oficial da Disponibilidade, as ocorrências novas por
   pessoa com o pulso e o sino da tela por usina, a idade real das strings, a conferência com o SCADA e o de-para dentro
   da usina. Detalhe em `plataforma/CLAUDE.md`.

## Retornos depois de usar (16/11/2026)

As strings aparecem assim que a usina responde (os trackers e a estação chegam depois); a seta da fonte só abre e
recolhe; trancar várias strings com uma confirmação só; o botão do prontuário (Nexus > Comando > Usinas); e o que o SCADA
da Grid tem de tracker e de estação aparece na usina mesmo quando a fonte dela não traz, com o raio-x na visão geral.
Detalhe e medições em `plataforma/CLAUDE.md`.

## Em aberto com o Levi

- O corte do "Ver agora" (no mockup, 8 dias ou mais sem OS; agora com a idade real).
- A 1ª leitura da Geração do mês de uma usina leva até uns 3 min no servidor (a rota do histórico por inversor, que o
  Tempo real também usa): vale olhar o porquê.
- Buscar a OS do Fracttal por inversor parado sem depender do vínculo manual (custo: uma consulta por inversor).
- Onde entram "desligada" e "sem produção" na ordem de criticidade.
- A lista de usinas do Monitoramento do COS (ele diz que Altair, Linhares e Barretos estão lá; nenhuma está nas 21 do
  SCADA que a plataforma lê).
