# Dashboard Thopen — Geração possível pelo IPOA (Visão Geral e linha do Diário)

Data: 20/10/2026. Pedido do Levi, que trocou a conta da linha preta do Diário (a de 20/10 de manhã, kWp × IPOA × PR da
meta, `a32a688`) por uma regra completa de "geração possível", e escolheu onde ela entra: **Visão Geral + linha do
Diário**, com a linha **pelo IPOA, sem expurgos**, **de 10/2026 em diante** (antes, como era), e a disponibilidade
do expurgo **como está** (a do Fracttal, isolada da geração).

## Por quê

Hoje a Visão Geral compara a produção do mês **até o corte** com a meta do **mês inteiro**, e a irradiação medida até o
corte com a esperada do mês inteiro: no meio do mês toda usina aparece "abaixo da meta". Também não diz quanto a usina
deveria ter gerado com o sol que de fato fez, nem quanto dessa diferença é indisponibilidade. A regra nova responde as
três coisas, com a mesma conta usina a usina e no total do portfólio.

## A regra (como o Levi escreveu, adaptada às fontes do painel)

**Vale de 10/2026 em diante** (`operacao_mes.DESDE`, como o resto do painel novo). Antes de outubro, a Visão Geral e
o Diário ficam como eram até 20/10/2026 (a Visão Geral com a meta e a irradiação do mês inteiro; o Diário com a linha
da irradiação em kWh/m²): o PDF de setembro sai igual. A conta kWp × IPOA × PR (`a32a688`) sai de todos os meses.

**1. Período e meta proporcional.** O período é o da tela (Visão Geral: o mês escolhido até o corte; Diário: o mês).
Só entram os **dias do período com geração** no BD_Thopen (`ger` não nulo; 0 é dado). Dia sem geração fica de fora e é
contado como **furo de coleta**.
- Meta de geração do período = Σ (meta mensal de geração ÷ dias do mês), nos dias que entram.
- Meta de IPOA do período = Σ (meta mensal de IPOA ÷ dias do mês), nos mesmos dias.
A meta mensal é a de hoje (`_meta2026`: `meta` e `metairr`).

**2. IPOA medido.** IPOA do dia = o IPOA da ETM (coluna "IPOA (kWh/m²)") se ≥ 0,3 kWh/m²; senão o GHI (coluna "GHI
(kWh/m²)") se ≥ 1,0; senão o dia fica **sem medição**.
- Cobertura = dias com medição ÷ dias que entram.
- Cobertura < 50%: a usina fica **sem ETM** — sem Dif. IPOA e sem geração possível.
- IPOA medido ajustado = Σ IPOA medido ÷ cobertura.

**3. Geração possível pelo IPOA.** Dif. IPOA = IPOA medido ajustado ÷ meta de IPOA do período − 1. Geração possível =
meta de geração do período × (1 + Dif. IPOA) — a meta corrigida pela irradiação que ocorreu, com o PR que a meta já
embute.

**4. Com expurgos.** Disponibilidade do dia = a das OS de religamento do Fracttal, a mesma que o painel já lê
(`falhas_performance · disponibilidade_dia`, `operacao_mes.disp_por_dia`: horas perdidas entre 06h e 18h no ativo da OS,
pela potência). **Como está**: isolada da geração, a regra de 15/10/2026; a OS em que o ativo gerou normalmente
continua contando (Levi, 20/10/2026, escolheu assim no lugar do desconto do item 4 da regra). Disponibilidade efetiva = média das disponibilidades dos dias que entram, ponderada pelo IPOA do dia (o
medido; sem medição, a meta de IPOA do dia). Geração possível com expurgos = geração possível × disponibilidade efetiva.

**5. Comparação.** Dif. geração possível = geração real ÷ geração possível − 1. Dif. com expurgos = geração real ÷
geração possível com expurgos − 1. Geração real = Σ geração dos dias que entram.

**6. Portfólio (linha Total da Visão Geral).** Geração possível (com e sem expurgos): soma das usinas **com ETM
válida**, comparada com a soma da geração real **dessas mesmas usinas**. Meta e geração do portfólio: soma das usinas
**com meta** (usina sem meta fica fora da comparação com a meta). IPOA do portfólio: média ponderada pela potência (MWp)
das usinas com ETM, não soma.

## O que muda na tela

**Visão Geral** (`/api/t/geral` + `renderGeral`; a tabela que vai no PDF Carteira):
- Meta (kWh) e Irradiação Esperada passam a ser **as do período** (item 1). Irradiação Medida passa a ser o **IPOA
  medido ajustado** (item 2). Dif. Produção e Dif. Irradiação usam esses valores.
- Colunas novas, depois de Dif. Irradiação: **Geração possível (kWh)**, **Dif. possível (%)**, **Possível c/ expurgos
  (kWh)**, **Dif. c/ expurgos (%)**. Disponibilidade e FC ficam como estão.
- Usina sem ETM (cobertura < 50%): nas colunas de IPOA e de possível, "sem ETM" com a cobertura no título da célula
  ("medição em 9 de 20 dias"). Usina com furo: na célula da usina, uma marca "N dias sem dado" com os dias no título.
- Linha **Total** calculada no servidor pelo item 6 (hoje é somada no navegador): meta e produzida das usinas com meta;
  possível e real das usinas com ETM; IPOA ponderado pela potência; a Disponibilidade do Total segue a média simples
  de hoje.
- As usinas "fora" (abaixo do Total, como Piancó) ganham as mesmas colunas e não entram no Total.

**Diário** (`/api/t/diario` + `renderDiario`): a linha preta vira a **geração possível do dia** = meta do dia × (IPOA
medido do dia ÷ meta de IPOA do dia) = meta mensal × IPOA medido do dia ÷ meta mensal de IPOA. Mesma regra de IPOA (ETM
≥ 0,3, senão GHI ≥ 1,0); dia sem medição, sem ponto. Mês com cobertura < 50%: sem a linha, e uma nota sob o gráfico
("Sem a geração possível: medição de irradiação em 9 de 20 dias; o mínimo é metade"). O mouse mostra "Possível pelo
IPOA 22.900 kWh · IPOA 4,65 kWh/m² (ETM)" (ou "(GHI)"). Título "Energia (kWh) × Geração possível pelo IPOA (kWh)".
Os cards do Diário (Energia acumulada, Irradiação no mês, Disponibilidade) **não mudam**.

**Metodologia**: as fórmulas acima, no lugar da "Geração esperada pelo IPOA" de 20/10.

## Metas, não-metas e o que seria falha

- Meta: a Visão Geral e a linha do Diário com a regra do Levi, usina a usina e no portfólio, provadas com número.
- Não-meta: cards do Diário, Mensal, Capa, contestação, a disponibilidade das outras telas.
- Falha mesmo funcionando: número pela metade sem aviso (furo ou cobertura escondidos); a meta do mês inteiro de volta
  no meio do mês; o Total somando usina sem ETM na geração possível; setembro mudando sem o Levi saber.

## Decisões minhas (o Levi pode trocar)

1. "Dia com geração" = `ger` > 0, **ou** `ger` = 0 com irradiação medida (a usina parada com sol: é dado ruim de
   verdade e tem de pesar). O 0 sem medição é a linha que o BD cria de antemão para o mês inteiro (medido em 20/10:
   hoje e ontem com 0 kWh e sem IPOA em 93 e 92 de 98 usinas): não entra. Só é **furo** o dia assim **antes** do
   último dia coletado da usina; depois dele é "ainda não coletado" e não aparece como furo.
2. Cobertura conta sobre os dias que entram (os com geração), não sobre os dias corridos.
3. O GHI só vale quando o IPOA da ETM falta ou é < 0,3; ele entra no lugar, sem conversão para o plano dos módulos.
4. **Teto físico**: IPOA acima de 12 kWh/m² ou GHI acima de 10 kWh/m² no dia é leitura fora da faixa e não conta como
   medição daquela fonte (o IPOA fora da faixa cai para o GHI; o GHI fora da faixa, para "sem medição"). Medido em
   20/10: uma usina com GHI de 10 a 25,7 "kWh/m²" em 45 de 47 dias (parece MJ/m²) e 41 dias de outubro com IPOA entre
   10 e 11,6 (plausível em usina com tracker, por isso o teto do IPOA é 12). Nada é convertido: unidade suspeita vira
   aviso, não número.
5. A disponibilidade efetiva ignora o dia sem valor publicado (o dia de hoje, ainda não fechado).
6. As colunas Meta, Irradiação Esperada e Irradiação Medida mudam de significado (período e ajustada) em vez de ganhar
   colunas novas: a tabela já tem 10 colunas e vai para a folha A4. Antes de 10/2026 a tabela é a de hoje (10
   colunas); de outubro em diante, 14.
7. A Disponibilidade da tabela (e a do Total) segue como hoje; a efetiva só aparece dentro da conta com expurgos.
8. Usina sem meta de IPOA no mês: sem Dif. IPOA e sem possível (como "sem ETM", com o motivo no título).
9. A conta mora num módulo puro novo (`thopen/geracao_possivel.py`, sem rede e sem Flask), usado pela Visão Geral e
   pelo Diário; o GHI entra nos registros diários (`_daily_bd` e as fontes da Polaris/Copel/Matrix quando tiverem).

## Respostas do Levi (20/10/2026)

- Onde: Visão Geral + linha do Diário; a linha é a possível **pelo IPOA, sem expurgos**.
- Desde quando: **de 10/2026 em diante**; antes, como era.
- OS com o ativo gerando normalmente: **conta, como hoje** (a disponibilidade do Fracttal isolada da geração).

## Como provar

- Testes do módulo puro com números à mão: meta proporcional com furo, ETM/GHI/sem medição, cobertura 49% e 50%,
  ajuste pela cobertura, disponibilidade efetiva ponderada, com e sem expurgos, portfólio só com ETM e IPOA ponderado.
- Rotas: `/api/t/geral` com a linha Total do servidor e os estados ("sem ETM", furo); `/api/t/diario` com a linha
  possível e a nota de cobertura.
- Dado real: Altair e Guaratinguetá V de outubro conferidas à mão contra o BD_Thopen; a Visão Geral e o Diário de
  setembro idênticos aos de antes (a mesma resposta das rotas).
- Tela: Visão Geral e Diário no navegador e na folha A4 (Ctrl+P e PDF Carteira, a tabela cabendo na largura).
