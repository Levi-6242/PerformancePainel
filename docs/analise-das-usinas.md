# Análise das usinas — o desenho da tela real (25/11/2026)

**O que é.** A tela da Performance que substitui o **Painel NOC**, o **Histórico de PR** e a **Disponibilidade**, e traz os
expurgos. Duas visões: a **inicial** (as usinas em cards, por cliente) e o **diagnóstico da usina** (clique no card).
Nome no Nexus: **Performance › Análise das usinas**.

**De onde veio.** Levi, 24 e 25/11/2026, em 10 rodadas de mockup com dado real da Santarém 2 (novembro, 01 a 22/11):
`docs/mockups/analise-da-usina/analise-das-usinas-r3.html` (local, **não sobe**: tem dado de cliente), gerado do modelo
e do gerador da sessão. O desenho foi aprovado em 25/11 ("começa a construir a tela real"). Cada regra abaixo cita o
pedido dele.

## Onde mora

Na **plataforma** (5050), como a Sala de controle: `/painel/analise-das-usinas`, `templates/analise_usinas.html`, e as
regras puras num módulo novo `analise_usinas.py` (sem Flask, testável). O Nexus abre a tela na moldura pela **porta
única** (o mapa das telas nos dois lados, `plataforma/porta_nexus.py` e o mapa do Nexus, no mesmo trabalho). Motivo:
todo o dado que a tela usa já está na plataforma (o Gerencial, a cascata, o Histórico de PR, a régua do COS, o índice do
Fracttal, as curvas do banco e a porta para o gêmeo); levar para o Nexus seria refazer leitores.

**Em paralelo.** O Painel NOC, o Histórico de PR e a Disponibilidade continuam no ar até o Levi aprovar a troca; aí o
menu passa a levar à Análise e as telas antigas viram redirecionamento.

## Visão inicial (aprovada: "ficou bem melhor")

- **Um card por usina, agrupado por cliente**, card de tamanho fixo (204 px), o cliente sempre até a borda direita;
  fundo do cliente transparente com borda clara. Cabeçalho do cliente: nome, nº de usinas, geração × P50, PR × meta,
  disponibilidade e as bolinhas vermelho/amarelo/verde/sem dado. Clicar no cabeçalho recolhe.
- **Card**: geração × P50 em destaque (com a barra e o traço do 100%), PR e meta, disponibilidade, ocorrências do mês.
  A cor da borda = o pior dos três sinais (≥ 95% verde, 85–95% amarelo, < 85% vermelho; disponibilidade ≥ 98 / 95–98 /
  < 95).
- **Ordem**: "Por cliente" (o cliente com mais usinas vermelhas primeiro) ou "Mais urgentes" (todas juntas: vermelhas,
  amarelas, verdes, sem dado; dentro da cor, a menor geração × P50).
- **Filtros no molde do Histórico de OS do OS Creator**: busca (lupa, 36 px), botão "Filtros" com o nº, pílulas com ×,
  painel suspenso com Aplicar, × e Esc: mês, cliente (vários), situação, PR de/até, PR abaixo da meta em p.p., geração ×
  P50 abaixo de, disponibilidade abaixo de, usinas sem dado (mostrar / só elas / esconder). **Todo seletor no estilo do
  Nexus** (busca digitável, caixas de marcar, limite no pé); nenhum `<select>` nem `<datalist>` do navegador.
- **Ocultar usina** (a que nem está mobilizada): passar o mouse no card (botão no canto) ou botão direito; o botão
  "Ocultas N" mostra de novo. **Decisão pendente: vale para a equipe ou por pessoa.**
- **Lista**: no botão Cards | Lista (a lista "a gente faz depois").
- **Sem** os KPIs gerais no topo ("não serve muito não").
- **Exportar relatório (PDF)**: uma página por cliente.

## Diagnóstico da usina

1. **Cabeçalho**: nome, cliente, local, kWp, nº de inversores/strings/trackers, **mobilizada em** (o cadastro do Nexus);
   seletores de usina e mês (estilo Nexus); "Exportar relatório (PDF)". Sempre o mês atual; o mês a mês só no botão.
2. **Parecer** numa linha e **5 números**: geração × P50, PR × meta, disponibilidade (ocorrências do COS), perda nas
   ocorrências (e quanto geraria sem elas), ocorrências do COS (nº, abertas, quedas).
3. **Ofensores** (recolhível): inversor parado, tracker parado, string sem corrente e **vegetação alta**; cada um com
   **o que já o cobre** e o próximo passo; e **Observações** à parte (a meta de PR que mudou, a conta dos expurgos que
   estourou, a última ronda, os dias sem explicação). Regra da cobertura (Levi, 25/11): **desligamento** (inversor,
   cabine, usina) = a ocorrência do COS; **string** = a OS de recomposição ou verificação de string do Fracttal naquele
   inversor; **tracker** = o chamado de tracker da usina. A mesma regra decide o "já tem" das sugestões do gêmeo.
   **Vegetação** (Levi, 26/11/2026: "incluir a vegetação também [...] essa informação tem nas rondas, a última ronda
   feita"): o nível da última ronda (a Zeladoria que o Nexus publica, `nexus_zeladoria · zeladoria_semana`) acima de 3 é
   ofensor, coberto quando a supressão está programada ou feita; a última ronda (vegetação, sujidade, a OS, a última
   supressão e limpeza) vai sempre nas observações. Na tela real os ofensores de tracker e de string saem do **pacote
   da Falhas do mês** (a régua da plataforma), não do gêmeo; o inversor que zerou num dia **sem** ocorrência do COS
   entra descoberto.
4. **Para onde foi a energia**: a cascata do mês (P50 → sol → queda de rede → equipamento → trackers → não explicado →
   gerado), com expurgos × operação × não explicado ao lado e a conferência pelas ocorrências do COS; "Mês a mês" no
   botão (as perdas empilhadas de jan a hoje, com os números).
5. **Dia a dia**: um gráfico só (geração em barras, PR, POA; a legenda liga e desliga). Em cima da barra, **amarelo** =
   o que o inversor parado tirou, **laranja** = o que as quedas tiraram (só nos dias com queda); a conta no topo
   ("gerado X · sem as ocorrências geraria Y (+Z): inversor parado · quedas"). Faixa de disponibilidade (régua do COS) e
   linha das ocorrências. Mouse: os números do dia, cada um explicado, e cada ocorrência com a bolinha da cor dela.
   Clique abre a faixa do dia: os números numa linha, a curva do gêmeo + as sugestões do gêmeo do dia, e as **ocorrências
   do COS do dia em tabela larga** (OS, tipo, equipamento, janela, horas, proteção, geraria, gerou, perda, como).
   **Comparar inversores** (um botão): até 4 inversores e até 3 dias (calendário), sobrepostos, "Potência e POA" ou
   "Strings e POA", o mouse com os valores do instante.
   **Dias sem explicação** (Levi, 25/11/2026: "ser apontado os dias que não tem explicação [...] teve baixa performance,
   porém não tem nenhuma explicação [...] de queda de ocorrência de COS, ou qualquer outro expurgo"): o dia em que,
   devolvidas as perdas já explicadas (as ocorrências do COS e os expurgos mapeados), o PR ainda fica abaixo do limite
   ganha a marca na linha das ocorrências. **A régua (Levi, 25/11/2026: "85% tá ok")**: o PR do dia, somadas as perdas
   das ocorrências, abaixo de 85% da meta. No clique, a faixa do dia mostra a **curva da usina** (potência × POA) e, no
   lugar da curva do gêmeo, a **curva dos inversores** (a potência de cada um sobre a POA), para achar o que caiu.
6. **PR e inversores**: o PR do mês × meta ("Ver o PR mês a mês" no botão), as sugestões do gêmeo do mês, e a tabela dos
   inversores em % (PR com o traço do alvo, × alvo em p.p., outubro, o dia a dia contra os outros, disponibilidade, OS e
   a **observação editável**). Sem strings sem corrente e sem gráfico de curva aqui.
7. **De onde vem cada número** (recolhido).

## As contas (o módulo `analise_usinas.py`)

- **Disponibilidade**: a régua do COS que a plataforma já grava (`falhas_performance · disponibilidade_dia` e
  `disponibilidade_os_dia`, fonte `cos`); o mês = a média dos dias.
- **Perda de uma queda** (usina ou cabine): a razão potência ÷ POA da hora antes e da hora depois, vezes a POA de cada 5
  min da janela, menos o que a usina gerou nela. **Sem curva no banco**: a geração do dia × a fatia da janela num dia
  típico (marcada "estimativa").
- **Perda de inversor parado**: a geração mediana dos outros inversores no dia (BD), menos a dele.
- **PR do portfólio e do cliente**: Σ geração dos dias com POA ÷ Σ (POA × potência), a conta do Gerencial; a meta pelo
  mesmo peso.
- **Cobertura dos ofensores**: string pelo índice de OS de string que a varredura da Disponibilidade publica a cada 30
  min (o mesmo do Vincular OS quando o Fracttal não responde): a tela **não** chama o Fracttal ao abrir. Tracker pelos
  chamados dos Tickets (`tickets_performance`: as paradas sem o fim e a aba Tracker).

## Rotas novas (só leitura, exceto as duas de gravar)

- `GET /api/analise/usinas?mes=` — a visão inicial: o Gerencial do mês + a disponibilidade e as ocorrências do COS por
  usina + mobilização + ocultas.
- `GET /api/analise/usina?usina=&mes=` — o diagnóstico: cascata do mês e dos meses do ano, dia a dia (BD + COS + perdas),
  inversores (PR, alvo, outubro, a matriz contra os outros, disponibilidade, OS, observação), ofensores e observações.
- As curvas do comparar e da faixa do dia: as rotas que a Sala de controle já usa (`/api/pg/curva`,
  `/api/relatorio/potencia-ativa`, `/api/pg/etm/chart`), só quando se pede; o gêmeo pela porta que já existe.
- `POST /api/analise/observacao` (a observação do inversor) e `POST /api/analise/ocultas` — pelo `gcEu.grava`, só quem
  grava (o gestor só lê), com o autor da sessão no log.

## Entregas

Situação em 26/11/2026: 1 no ar (d8ee8c9 + Nexus e98dda37); **2 e 3 no código** (o diagnóstico, as curvas no clique, o
gêmeo na faixa do dia, a observação e o PDF), provadas na bancada com o dado do servidor; a troca das telas antigas (a
segunda metade da 4) espera o OK do Levi depois de ele usar o diagnóstico.

1. **Visão inicial** completa (cards, filtros, ocultar, lista simples, PDF da visão) + `/api/analise/usinas` + testes.
2. **Diagnóstico**: cabeçalho, 5 números, ofensores, para onde foi a energia (+ mês a mês), dia a dia com as perdas e a
   faixa do dia, PR e inversores + `/api/analise/usina` + `analise_usinas.py` com testes das contas (a Santarém 2 de
   novembro como caso: quedas 0,83 (estimativa), 0,19 e 0,19 MWh; o 2.7 43,0 MWh).
3. **Comparar inversores**, o gêmeo na faixa do dia e o **PDF** no molde do Criador de relatório (seções numeradas,
   inversores em barras na horizontal).
4. **Nexus**: a tela no mapa da porta única e no menu da Performance; depois do OK do Levi, o NOC, o Histórico de PR e a
   Disponibilidade passam a levar à Análise.

Cada entrega sobe fora do período solar, em lote (a regra do deploy), com a prova no servidor.

## Decisões do Levi (25/11/2026)

- **Ocultar usina vale para a equipe**: quem oculta esconde para todos da Performance; "Ocultas" mostra de volta e diz
  quem ocultou e quando.
- **A régua dos números do topo é o Gerencial nas duas visões** (geração × P50, PR e meta: os mesmos números do NOC); a
  cascata fica só para decompor a perda (para onde foi a energia). Na Santarém 2 a cascata dava PR 66,9% e o Gerencial
  69,8%: a tela mostra o do Gerencial.
- **A cascata será corrigida numa entrega à parte**, depois da tela (achado de 24/11: ela conta cada hora de OS que não é
  religamento como a usina inteira parada, setembro 361 MWh de "equipamento", e as paradas de tracker entram sem filtro
  de mês): o degrau de equipamento pelas perdas das ocorrências do COS e o de trackers filtrado pelo mês. Muda também o
  Gerencial e o Criador de relatório. Até lá a tela avisa nos meses em que a conta estoura.
- **O plano das 4 entregas está aprovado**; as telas antigas seguem em paralelo até o OK dele.

## Como ficou na tela real (26/11/2026)

- `GET /api/analise/usina?usina=&mes=`: o diagnóstico inteiro numa chamada (10 min de cópia); a cascata e o mês a mês à
  parte em `GET /api/analise/usina/energia` (a do mês corrente leva uns 24 s na 1ª vez, medido no servidor); as curvas
  (`/api/analise/curvas`) e o gêmeo (`/api/analise/gemeo`) só no clique, sob `/api/analise` (o gestor lê).
- As curvas só de fonte gratuita (o banco da Thopen e o scadaGridco): a usina que só tem curva na API PV ou na SunOp
  mostra o motivo no lugar do gráfico.
- A perda da queda sem curva no banco usa a POA dos outros dias de queda do mês; sem nenhuma, o dia de céu limpo (o seno
  das 06 às 18 h), marcada "estimativa".
- O mês a mês do PR é o do BD (`/api/g/mensal`); o PR do topo é o do Gerencial.

## Velocidade (26/11/2026)

Medido no servidor: o diagnóstico refeito leva de 1,5 a 7 s; a 1ª abertura com as cópias frias chegou a 46,6 s (Santarém
2). Os expurgos (a cascata) levam de 0,1 a 1,8 s, mas a MRO100 fria levou 95,7 s: a cascata é a do Gerencial e consulta
ao vivo o Fracttal, o livro de paradas de tracker e, nas usinas da Athon e da API PV, a lista de strings abertas (que
pode baixar curva da SunOp ou da API PV). A Análise deixou de pedir a lista; o resto se decide pelos `tempos` que a
cascata e o diagnóstico passaram a devolver.

Depois do deploy (c682c7f, 14:29, servidor frio): MRO100 31,3 s (a lista 0,0 s; a série do BD_Performance da Athon 26 s),
Santarém 2 68,3 s (o BD_Thopen inteiro carregando, 66 s), CPP100 0,8 s e Piracicaba I 0,2 s logo depois, porque a série
do cliente já estava na memória. O que pesa agora é o 1º acesso por cliente depois de cada reinício do servidor.

## Achados de dado no caminho (para conferir)

- A Piracicaba I e a Marajoara I têm outro nome no BD_Thopen ('Piracicaba 1', 'Marajoara 1'): o diagnóstico vinha sem dia
  a dia e sem cascata. Corrigido pelo nome da aba (`_au_nome_bd`, 26/11/2026). A Vargem Grande 1 não tem dia nenhum no
  BD_Thopen em novembro.

- A Santarém 2 foi mobilizada em **20/10/2025** em todas as fontes (o Levi achava junho).
- O gêmeo acusa a "string 5" do 2.10 e a "string 15" do 2.5, mas o banco lista só 20 strings por inversor e não tem
  ST 05/ST 15: conferir o de-para das strings (a numeração do gêmeo pode ser outra).
- kWp 3.510 no cadastro e 3.256 no BD (a base do P50).
- O banco da Thopen não tem leitura da Santarém 2 de 01 a 04/11.
