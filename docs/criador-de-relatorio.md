# Criador de Relatório — como funciona, onde fica e como incluir um tipo novo

> Atualizado em **28/09/2026**, a partir do código da Plataforma de Performance. As medidas trazem a data em que foram
> feitas. Credenciais nunca aparecem aqui.

O Criador de Relatório é a página **`/relatorio`** da Plataforma de Performance (porta 5050). Escolhe-se a usina e o
período; o servidor monta os números e o navegador desenha um documento claro, no estilo do PDF de performance entregue
ao cliente, que sai em PDF pela impressão do navegador. Este documento segue o dado do banco até o PDF, diz onde mora
cada peça e o que muda para incluir um tipo novo de relatório — o semanal, por exemplo.

## Sumário

1. [Em uma página](#1-em-uma-página)
2. [Onde fica](#2-onde-fica)
3. [Como o relatório é montado](#3-como-o-relatório-é-montado)
4. [As seções do documento](#4-as-seções-do-documento)
5. [Do navegador ao PDF](#5-do-navegador-ao-pdf)
6. [O estado hoje](#6-o-estado-hoje-medido-em-28092026)
7. [Pontos de atenção](#7-pontos-de-atenção)
8. [Como incluir um tipo novo de relatório](#8-como-incluir-um-tipo-novo-de-relatório)
9. [Os outros relatórios da plataforma](#9-os-outros-relatórios-da-plataforma)

---

## 1. Em uma página

- **Para que serve:** gerar o relatório de performance de **uma usina** num período qualquer (o "personalizado" do
  PDF). Foi construído em 23/07/2026 reproduzindo o PDF de Tupi Paulista de junho/2026.
- **Como se usa:** Entrada → card *Diagnóstico de performance* → **Criador de Relatório** (ou o menu do
  Monitoramento). Escolher a usina, **De** e **Até** (abre no mês corrente), **Gerar**, e **Salvar como PDF**.
- **Três peças:** a página (`plataforma/templates/relatorio.html`), o motor (`_relatorio_build`, em
  `plataforma/app.py`, servido por `/api/relatorio`) e a lista de usinas (`/api/relatorio/usinas`, do cadastro Info
  Geral).
- **A régua é a da cascata do Diagnóstico**, com duas diferenças de propósito: a meta de PR é a do **1º ano**, sem
  degradação (régua do relatório entregue ao cliente, decisão do Levi), e todo número leva **cobertura, fonte e
  alertas** (a camada de confiabilidade).
- **O PDF é a impressão do navegador** (`window.print()` com CSS de impressão A4). O servidor não gera arquivo.
- **Uma usina por vez, sob demanda.** Não há relatório agendado, por carteira nem enviado por e-mail.

---

## 2. Onde fica

| Peça | Onde | O que faz |
|---|---|---|
| Página | `plataforma/templates/relatorio.html` | Barra (usina, De, Até, Gerar, Salvar como PDF), chama a API e desenha as seções em JavaScript (`render(d)`). |
| Rota da página | `GET /relatorio` → `page_relatorio()` | Só entrega o HTML. |
| Motor | `GET /api/relatorio?usina=&ini=AAAA-MM-DD&fim=AAAA-MM-DD` → `api_relatorio()` → `_relatorio_build(usina, ini, fim)` | Monta o JSON do relatório. Recusa de negócio volta `{"ok": false, "motivo": ...}` com HTTP 200; exceção volta 500 com o motivo. |
| Lista de usinas | `GET /api/relatorio/usinas` → `api_relatorio_usinas()` | Usinas da **Info Geral** (nome de exibição, cliente, MWp), sem repetição. 156 em 28/09/2026. |
| Auxiliares | `_rel_meses`, `_rel_parse_ts`, `_pr_meta_1ano` | Meses que o período toca, data das OS, meta de PR do 1º ano. |
| Links de entrada | `docs/redesign/Entrada.html` (card *Diagnóstico de performance*) e o menu de `docs/redesign/Monitoramento (novo design).html` | Os dois caminhos até `/relatorio`. |

No `app.py`, o bloco começa no comentário **`═══ CRIADOR DE RELATÓRIO ═══`** — busque por ele; o arquivo passa de 27
mil linhas. Página e API ficam atrás do login (`_auth_gate`), como o resto da plataforma.

**O que precisa de restart:** mudança no motor (`app.py`) precisa reiniciar o web. Mudança só no `relatorio.html` não:
o Flask relê os templates a cada acesso (`TEMPLATES_AUTO_RELOAD`).

---

## 3. Como o relatório é montado

`_relatorio_build(usina, ini, fim)` roda **no processo web, na hora do pedido**, em seis passos. Cada passo reaproveita
uma peça que a plataforma já tem, em vez de recalcular por conta própria — as rotas internas são chamadas por dentro,
com `app.test_request_context(...)`.

### 3.1 Série diária, P50 e meta de PR

- Para cada mês que o período toca, chama a rota diária do Histórico PR (`api_g_diario`). A base é escolhida pelo
  **cliente** da usina na Info Geral: **Thopen** → BD_Thopen (pelas carteiras do banco, `thopen/dashboard_thopen.py`);
  os demais → aba diária do BD_Performance.
- Ficam os dias com geração dentro de [início, fim]. No Thopen, a rota diária também descarta o dia **sem IPOA**
  (≤ 0,3 kWh/m²) — sem irradiação não há PR.
- **P50** e **IPOA previsto**: a meta mensal ÷ dias do mês, somada nos dias que entraram.
- **Meta de PR:** o *PR Previsto do 1º ano* da Info Mensal (`pr_previsto_1ano`), em média nos dias do período. Sem
  ela, ou sem a potência da usina, o relatório **não sai**: *"faltam potência ou meta de PR (1º ano) no cadastro"*.

As contas de base:

| Grandeza | Conta |
|---|---|
| Possível com o sol que veio | `IPOA × Pot × meta de PR` |
| Perda por baixo IPOA (externa) | `max(0, IPOA previsto × Pot × meta − possível)` |
| PR realizado | `geração ÷ (IPOA × Pot)` |

### 3.2 Trackers

- A fonte da usina (`_fonte_da_usina`: `pv`, `pg`, `sunop`, `axis` ou `owen`) e o **book de paradas** do período
  (`_trk_paradas_hist`): as corridas de dias em que o tracker foi classificado "parado", reconstruídas do
  `trk_eventos.json` — inclusive as que já voltaram. Não precisa de coleta nova.
- `perda de tracker = possível × horas solares paradas ÷ (12 × dias × frota) × 20%`. Os 20% são o ganho do
  rastreamento sobre a estrutura fixa (`TRK_GANHO_RASTREIO`, premissa calibrável).
- A frota vem de `_trk_frota_total(fonte, usina, sel)`: por usina da fonte, o `total` do overview de trackers que o
  worker publica (o da tabela de Trackers; na 2C do e-mail, o acervo do dia); a usina que a fonte não lista hoje vem do
  cadastro (aba BD_Trackers); e nunca menos que os trackers que pararam nela. Só lê o publicado — no processo web,
  reconstruir o overview seria a varredura de até 15 min da API PV. Até 29/09/2026 ela devolvia 0 fora do Banco e o
  motor dividia pelos trackers que PARARAM (ver os [pontos de atenção](#7-pontos-de-atenção)).

### 3.3 PR por inversor

A rota `api_g_inversores` já recorta o período. Cada inversor sai com PR e desvio em pontos contra a meta.

### 3.4 Desligamentos (OS do Fracttal)

OS com **data do evento** dentro do período, em dois níveis:

- **Usina inteira** (o *site* no Fracttal): a energia perdida é real, pelas horas solares paradas (`possível ÷ (12 ×
  dias)` por hora). Religamento vira *Queda de energia*; o resto, *Equipamento*. Só essas horas derrubam a
  **Disponibilidade UFV**.
- **Inversor:** a OS **não vira energia**. A perda do inversor é o **déficit medido** — `(PR mediano dos pares − PR do
  inversor) × IPOA × Pot do inversor` — e só conta como *Equipamento* o déficit do inversor que tem OS no período. Sem
  OS, o déficit fica no *não explicado*, como manda a régua da Ana.

Por que déficit medido, e não horas de OS: com horas de OS, uma OS "aberta há 43 h" virava perda fantasma e o não
explicado ficava negativo (decisão do Levi, 23/07/2026). OS sem data de fim: em período passado vale só o dia do evento;
em período corrente, até agora — e o relatório avisa.

### 3.5 Ofensores em aberto

- **Trackers:** as paradas do book ainda abertas no fim do período.
- **Strings:** o retrato de **agora** (`_strings_problema_rows`), até 12. Em período passado, o histórico intradiário de
  string não existe, e o relatório avisa que a lista é limitada.

### 3.6 Fechamento e confiabilidade

- `O&M = tracker + desligamentos` (queda de energia + equipamento).
- `não explicado = max(0, possível − geração − O&M)`. Quando as perdas mapeadas passam do desvio (`om_excede`), a meta
  de PR provavelmente está baixa demais, e o relatório diz isso (caso Tupi: meta de planilha 79,4%).
- **Cobertura** de geração e de IPOA = dias com dado ÷ dias do calendário.
- **Alertas:** cobertura abaixo de 90%, PR acima de 130% (IPOA subestimada), não explicado acima de 5% do possível,
  strings limitadas, OS sem data de fim, `om_excede`.
- **Nível:** *alta* sem alerta nenhum; *média* com alerta, mas cobertura de geração ≥ 90% e de IPOA ≥ 80%; *baixa* no
  resto.

### 3.7 O que o motor devolve

Um JSON com, entre outros: `usina`, `cliente`, `ini`, `fim`, `dias`, `pot`, `pr_meta`, `pr_real`, `p50`, `poa`,
`poa_prev`, `possivel`, `geracao`, `serie` (dia a dia: `data`, `geracao`, `poa`), `perda_ipoa`, `perda_trk`,
`perda_rede`, `perda_equip`, `perda_deslig`, `nao_explicado`, `om`, `om_excede`, `disponibilidade_ufv`,
`perda_inv_medida`, `trk` (paradas, trackers, frota, horas solares, ganho), `os` (quantidade, lista), `inversores`
(PR, desvio, déficit), `equip_disp` (indisponibilidade por inversor), `abertos` e `confiabilidade` (nível, coberturas,
fontes, alertas). É esse contrato que a página desenha — mudar um nome de campo quebra a página em silêncio.

---

## 4. As seções do documento

A função `render(d)` do `relatorio.html` monta as seções; cada uma vira uma página na impressão.

| Nº | Seção | O que mostra |
|---|---|---|
| — | Capa e resumo | Usina, MWp, cliente, período, selo, os quatro números (geração × P50, PR × meta, disponibilidade, perda evitável), a leitura em texto e os pontos de atenção. |
| 02 | Recurso Solar | IPOA real × previsto e o aproveitamento. |
| 03 | Qualidade da Performance & Equipamentos | PR, disponibilidade, perda de inversor medida e a tabela por inversor (PR, desvio, déficit, desligamentos, indisponibilidade). |
| 04 | Contabilidade de Energia | Cascata em MWh: P50 → −baixo IPOA → possível → −tracker → −queda de energia → −equipamento → −não explicado → real. |
| 05 | Contabilidade de PR | A mesma cascata em pontos de PR, com a linha da meta. |
| 06 | Comportamento Diário | Tabela dia a dia (geração e IPOA) e o total. |
| 07 | *(Comportamento Anual)* | **Não existe.** Previsto em julho (mês a mês, precisa do mensal do Gerencial); a numeração pula de 06 para 08. |
| 08 | Registros do Período | As OS de desligamento (nível, classe, início, fim, horas solares) e os ofensores em aberto. |
| 09 | Metodologia & Confiabilidade | As fórmulas em texto e o selo de confiabilidade (nível, coberturas, não explicado, alertas). |

O selo da capa segue a **geração contra o P50**, não o PR: *ÓTIMO* a partir de 98%, *BOM* a partir de 90%, *ABAIXO DO
ESPERADO* abaixo disso. As cascatas são SVG desenhado no próprio navegador (`wf()`, adaptado do Diagnóstico para fundo
claro), então saem vetoriais no PDF.

---

## 5. Do navegador ao PDF

- **Salvar como PDF** chama `window.print()`. O CSS `@media print` esconde a barra, usa A4 com 14 mm de margem e quebra
  a página em cada seção.
- O **nome do arquivo** sai do título da página ("Criador de Relatório — Grid Co."): o navegador não sabe a usina nem o
  período. O relatório da carteira do 5080 troca o `document.title` antes de imprimir; o Criador ainda não.
- O documento é **claro de propósito** (estilo do PDF entregue), não o tema navy da plataforma.

---

## 6. O estado hoje (medido em 28/09/2026)

Rodei o motor para as **156 usinas do seletor** na semana **21 a 27/09/2026**, com o Fracttal e as strings ao vivo
desligados (para não gastar a cota de 200 chamadas por minuto, que é da empresa inteira). O resto é o motor real, com o
dado de hoje.

**96 geram, 60 não.** Fora do Thopen, geram 47 de 52 — as 5 que não geram (Lajedo 1, Nova Venécia 1 e 2 da Axis;
Balsas 1 e Icó 2 da Greenyellow) não têm aba no BD_Performance. **No Thopen, geram 49 de 104.** As 55 que não geram:

| Causa | Usinas | Quantas |
|---|---|---|
| Meta de PR do 1º ano ausente na Info Mensal | Alto Paraná 1, Alvares Machado, Aruanã, Caicó, Cambé, Cipó Guaçu, Colorado 1, Itajá, Jucurutu, Matão 2, Rodrigues 1 e 2, Santana do Ipanema, Santo Anastacio, Sapopema, Saturnino 1, Sorocaba, Taguaí | 18 |
| Meta de PR do 1º ano **zero** | Lyon, Parelhas, Pharma II, III e IV | 5 |
| Nome diferente entre Info Geral e BD_Thopen — grafia | Corrego do Sapucaia (lá, Córrego), Marajoara I (Marajoara 1), Piracicaba I (Piracicaba 1), Vargem Grande IB (Vargem Grande 1) | 4 |
| Nome diferente — a usina está partida de outro jeito | Boa Esperança do Sul 1 e 2 (lá, 1 e 2 separadas), Diamantino 1 (Diamantino), Nova Londrina 1 e 2 (Nova Londrina), Ouro Branco (I a V), Primavera 1 e 2 (Primavera), Santarém 1 e 2 (1 e 2 separadas) | 8 |
| Não está no BD_Thopen | Pacaembu | 1 |
| Geração na semana, mas **nenhum dia com IPOA** | Alto Paraná 2, Assis, Bernardino de Campos, Brodowski, Colorado 2, Céu Azul, Guatambu, Indaiatuba, Ipixuna 1 e 2, Monte Aprazível, Paranavaí | 12 |
| Nenhum dia na semana | Caroá, Delmiro Gouvea 1 a 4, Ribeirão Cascalheiras, Urupês 1 | 7 |

Sobre o IPOA, contando por semana desde 31/08: em cinco usinas ele **parou em setembro** — Brodowski depois da semana
de 31/08, Colorado 2 e Monte Aprazível na de 07/09, Alto Paraná 2 e Assis na de 14/09; em Céu Azul, Guatambu, Indaiatuba
e Ipixuna 1 e 2 ele não aparece em nenhuma das quatro semanas; Bernardino de Campos e Paranavaí tiveram um dia só. Isso
derruba o PR dessas usinas em toda a plataforma, não só no relatório.

**Confiabilidade dos 96 que geraram:** 7 *alta*, 20 *média*, 69 *baixa*. Em período passado, toda usina das fontes
`pv`, `owen`, `sunop` e `axis` recebe o alerta de "strings limitadas", e com qualquer alerta o nível já não é *alta*.
Além disso, os dias 26 e 27/09 estavam incompletos no dado que a plataforma lê quando medi (28/09, 23h): 69 e 65 usinas
do Thopen com geração, contra 96–97 no começo da semana. Isso derruba a cobertura.

**Tempo:** sem o Fracttal, o primeiro relatório levou 31,8 s (carga do BD_Thopen) e os seguintes, 0,03 s na mediana.
Com o Fracttal, não medi — ele faz consultas por usina e por inversor, por mês do período.

---

## 7. Pontos de atenção

1. **Horas de tracker parado fora do período (em aberto).** No relatório de período PASSADO, a parada aberta no fim do
   período conta horas até agora (`_trk_paradas_hist`): um agosto gerado em 29/09 tinha de 28% (API PV) a 43% (Athon)
   das horas vindas de setembro. Na cascata do Diagnóstico (`_cascata_usina`) é pior: ela soma no mês o book inteiro,
   desde 01/07 — em setembro, 582 mil h contra 181 mil h do período (3,2×). Há uma tarefa sugerida para cada um.
   A FROTA (o denominador) foi corrigida em 29/09/2026: `_trk_frota_total` chamava `_pv_trackers_overview`, nome que
   nunca existiu, e devolvia 0 fora do Banco. Medido antes × depois no relatório de setembro: 27 de 52 usinas mudaram,
   perda de tracker 1.226,4 → 546,5 MWh (MAB100 111,1 → 9,6).
2. **Roda no processo web, na hora do pedido.** Um relatório por vez funciona. Gerar em lote (todas as usinas, toda
   segunda) no processo web travaria os outros usuários — é a regra do `plataforma/CLAUDE.md`: trabalho pesado vai
   para o worker.
3. **Consulta o Fracttal por usina e por inversor, por mês do período.** A cota é de 200 chamadas por minuto para a
   empresa inteira (App de Campo e OS Creator usam a mesma).
4. **A meta é só a do 1º ano, sem reserva.** O Histórico PR usa a meta do BD_Thopen quando a Info Mensal não tem; o
   relatório não, e 23 usinas do Thopen não saem por isso.
5. **O nome da Info Geral precisa bater, exato, com o do BD_Thopen.** É o mesmo problema que escondia a Córrego do
   Sapucaia do seletor do Histórico, corrigido no seletor em 28/09 — o relatório ainda não tem a correção, e a usina
   partida de outro jeito nos dois cadastros (Primavera 1 e 2 × Primavera) não se resolve só com a grafia.
6. **A URL interna é montada sem codificar** (`f"/api/g/diario?cliente={cli}&usina={usina}..."`). Nenhum nome de hoje
   tem `&` ou `#`, mas um que tiver quebra a consulta.
7. **Data padrão pelo relógio UTC.** A barra usa `toISOString()`: depois das 21h o *Até* vem com a data de amanhã, e o
   "Emitido em" também. O painel já corrigiu o mesmo defeito com uma data local (`_gIso`).
8. **Strings só no retrato de agora**, e a seção 07 não existe.
9. **Não há teste automatizado** do motor nem da página.

---

## 8. Como incluir um tipo novo de relatório

### 8.1 Antes de codificar: o que o semanal é

As respostas mudam o caminho inteiro:

| Pergunta | Por que importa |
|---|---|
| Para quem? Cliente ou equipe interna? | Define a régua (meta do 1º ano × meta degradada), o tom e o que pode aparecer (OS, tickets). |
| De uma usina, de uma carteira ou do portfólio? | Uma usina reaproveita o motor; carteira/portfólio pede um motor que agregue — e roda no worker. |
| Que semana? Seg–dom fechada? | O dado do Thopen é D-1 e fecha à noite (23:30). A semana de segunda só está completa na terça. |
| Que conteúdo? | As mesmas seções em 7 dias, ou um relatório operacional diferente (paradas, OS, strings, trackers)? |
| Como chega? Na tela, em PDF, automático? | Na tela é só página. Automático precisa de agendamento, de PDF gerado no servidor e de canal de envio. |

### 8.2 Caminho curto: a semana como período do relatório de hoje

O motor já aceita qualquer [início, fim], inclusive uma semana que atravessa dois meses (`_rel_meses`). Um botão
**Semana passada** (seg–dom) na barra do `relatorio.html` preenche *De* e *Até* e chama `gerar()` — são poucas linhas,
sem restart. Vale saber: o P50 e o IPOA previsto da semana saem da meta mensal dividida por dia, e o selo compara com o
P50 desses 7 dias.

### 8.3 Caminho completo: um tipo novo

1. **Motor.** Uma função nova (`_relatorio_semanal_build`) ao lado de `_relatorio_build` — ou, melhor, um módulo puro
   novo, `plataforma/relatorio_semanal.py`, no padrão de `disponibilidade.py`, `falhas.py` e `inv_padrao.py` (conta sem
   rede, fácil de testar). Reaproveitar `_relatorio_build` por usina onde servir, em vez de recalcular.
2. **Rota.** `GET /api/relatorio/semanal?...` no bloco do Criador. O login vale sozinho (`_auth_gate`).
3. **Página.** Um seletor de *tipo* na barra do `relatorio.html` (Período livre | Semanal), cada tipo com o seu
   `render`, ou um template próprio com rota própria. Manter o CSS de impressão (`.sec`, `@page A4`) e trocar o
   `document.title` para o PDF sair com nome útil.
4. **Links.** O card da Entrada e o menu do Monitoramento, se o semanal tiver entrada própria.
5. **Testes.** O motor com dado de fixture (troca-se `api_g_diario` e companhia por stubs, no padrão dos testes da
   pasta `tests/`), e as contas da página rodadas no node, extraídas do HTML (padrão de
   `tests/test_monitoramento_geracao_logica.py`).
6. **Conferência.** O semanal de uma usina tem de fechar com o Criador de hoje para o mesmo [início, fim], número a
   número — é a régua de confiabilidade do projeto.

### 8.4 Se o semanal for automático

- **Onde roda:** um laço novo no worker, registrado em `_iniciar_loops_de_fundo` (`app.py`), no molde do
  `_fecha_dia_loop`: acorda de tempos em tempos, vê se a semana-alvo já foi feita e, se não, faz. O resultado vai para
  um arquivo que o web só lê — como a aba de Falhas faz com `falhas_AAAA-MM.json`.
- **PDF no servidor:** o único PDF gerado no servidor hoje é o de curvas de strings, em matplotlib
  (`_curva_pdf_response`). O Criador e o 5080 imprimem pelo navegador. Um PDF automático no layout do Criador pede
  matplotlib ou um navegador sem janela — decisão a tomar, com o custo de cada um.
- **Envio:** a plataforma não manda e-mail nem mensagem no Teams hoje. O único envio automático é o WhatsApp da ronda,
  pelo serviço Node local (`C:\GridcoWhats\wa_service.js`), que só pode rodar num processo.

---

## 9. Os outros relatórios da plataforma

| Relatório | Onde | Como sai |
|---|---|---|
| **PDF de curvas de strings do dia** | Monitoramento → usina → *Curva das strings* → botão **PDF**. Rotas `/api/spv/pdf` (API PV), `/api/sunop/pdf` (Athon/SunOp) e `/api/pg/pdf` (Banco), no `app.py`. | Gerado **no servidor** em matplotlib: por usina, os cards dos inversores com as curvas, as strings abaixo e o motivo anotado. |
| **Relatório da carteira (5080, cliente)** | `thopen/templates/dashboard_thopen.html`, `printRelatorioCarteira()`. | Pelo navegador: capa, visão geral e mensal/diário de cada usina da carteira; `FORA_DO_RELATORIO` (em `thopen/dashboard_thopen.py`) tira usinas dele. |
| **Exportações** | `.../export`, `.xlsx`, `.csv` de trackers, geração, ETM e disponibilidade. | Dado bruto em planilha — não são relatórios. |

Documentos relacionados: [Cálculo de disponibilidade do Gerencial](calculo-disponibilidade-gerencial.md),
[Disponibilidade por OS](disponibilidade-por-os.md), [Regras de negócio](regras-de-negocio.md) e
[Perdas: particularidades por fonte](perdas-particularidades-por-fonte.md).
