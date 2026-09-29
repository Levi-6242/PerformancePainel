# Tempo real — como funciona, onde fica e o que vigiar

> Atualizado em **29/09/2026**, a partir do código da Plataforma de Performance (commit `c03bdb3`) e de medidas feitas
> no servidor (`app.gridco.com.br`) às 11:39 do mesmo dia. Onde o texto diz **medido**, houve medida, com hora; onde diz
> **pelo código**, a regra foi lida e não observada rodando. Credenciais nunca aparecem aqui.

O tempo real é o **Monitoramento** da Plataforma de Performance (porta 5050): as visões **Strings**, **ETM** e
**Trackers** de nove fontes de dado, mais a **Entrada** e o **macro** (NOC), que resumem tudo por usina, e os alertas
(sino e ronda do WhatsApp). Este documento segue o dado do supervisório até a pílula de status da tela, diz onde mora
cada regra e por que ela existe, mostra o estado medido hoje e lista o que está quebrado ou frágil.

É a referência para mexer no tempo real. Os documentos antigos que tratavam do assunto estão defasados — a lista está
na [seção 16](#16-documentos-que-esta-referência-substitui).

## Sumário

1. [Em uma página](#1-em-uma-página)
2. [Onde fica](#2-onde-fica)
3. [Como o dado anda: worker, snapshot e web](#3-como-o-dado-anda-worker-snapshot-e-web)
4. [As nove fontes](#4-as-nove-fontes)
5. [Strings: a régua da tabela](#5-strings-a-régua-da-tabela)
6. [O status da usina na tela](#6-o-status-da-usina-na-tela)
7. [Usina calada, relógio e sol](#7-usina-calada-relógio-e-sol)
8. [Tickets de strings na tabela](#8-tickets-de-strings-na-tabela)
9. [ETM](#9-etm)
10. [Trackers](#10-trackers)
11. [O drill-down de uma usina](#11-o-drill-down-de-uma-usina)
12. [Entrada e macro (NOC)](#12-entrada-e-macro-noc)
13. [Alertas: sino e ronda do WhatsApp](#13-alertas-sino-e-ronda-do-whatsapp)
14. [O estado hoje](#14-o-estado-hoje-medido-em-29092026-às-1139)
15. [Pontos de atenção](#15-pontos-de-atenção)
16. [Documentos que esta referência substitui](#16-documentos-que-esta-referência-substitui)
17. [Testes que prendem as regras](#17-testes-que-prendem-as-regras)
18. [Como mexer sem quebrar](#18-como-mexer-sem-quebrar)

---

## 1. Em uma página

- **Dois processos.** O `worker.py` coleta as fontes, monta tudo e publica o `cache_snapshot.json`; o `app.py` (web) só
  lê esse arquivo e serve. No web, cache vencido volta marcado `stale` e **não é reconstruído** — reconstruir dentro da
  requisição é o que travava um usuário por causa de outro.
- **Frescor.** O worker dá uma volta a cada ~5 min (`CACHE_TTL` = 300 s; SunOp e Axis, 600 s). A página do Monitoramento
  **não se atualiza sozinha**: carrega ao abrir, ao trocar de fonte ou de aba e no botão **Atualizar**. A Entrada relê a
  cada 60 s.
- **Nove fontes, oito chips:** Thopen pela API PV e pelo Banco, Athon, Axis, RenoGrid, 2C (e-mail e API PV juntos),
  SEMP e Alves Lima. A chave `2capi` existe só por trás do chip 2C.
- **Régua de string instantânea e relativa:** cada string é comparada com a mediana das strings do **próprio inversor**
  naquele instante (≤ 0,1 A = sem corrente; < 60% da mediana = baixa performance). Inversor com mediana < 0,5 A não está
  gerando, e suas strings não são falha.
- **Inversor desligado é decidido pela potência**, com três portões: sol no estado da usina, a usina gerando e o
  inversor com leitura. Ele sai da conta de ativas e de esperadas e vira o aviso "N inv. desligado(s)".
- **A diferença da usina é a soma das faltas de cada inversor.** A sobra de um inversor não paga a falta de outro
  (29/09/2026, caso Rodrigues 2.1).
- **Precedência do status:** Usina desligada → Usina sem comunicação → Baixa irradiância → Sem visão de strings → Sem sol
  → Usina desligada (0 ativas) → Falha de string → Inversor desligado → padrão do inversor → Temp elevada → Sem dados →
  Normal. A [seção 6](#6-o-status-da-usina-na-tela) traz a tabela completa.
- **Trackers:** régua v2 (ligada no servidor e no local), janela 06–18 h. Os trackers da API PV têm laço próprio,
  fora do ciclo, porque a varredura sozinha levava 897 s.
- **Ronda do WhatsApp:** 08:25 e 13:00, só no PC local. **Hoje (29/09) a das 08:25 não saiu** — a sessão do WhatsApp
  caiu e pede um QR novo (ver [seção 13.3](#133-ronda-do-whatsapp)).

---

## 2. Onde fica

| Peça | Onde | O que faz |
|---|---|---|
| Tela do Monitoramento | `docs/redesign/Monitoramento (novo design).html`, servida em `/monitor` | Tabelas de Strings, ETM e Trackers, drill-down, gráficos, cadeados, tickets. Relida quando o arquivo muda, **sem restart**. |
| Entrada | `docs/redesign/Entrada.html`, servida em `/`, `/tempo-real` e `/tempo-real/<fonte>` | Cards por cliente e fonte; no 3º nível embute o Monitoramento num iframe (`/monitor?fonte=…&embed=1`). |
| Backend | `plataforma/app.py` (28,5 mil linhas) | Coleta, réguas, caches, rotas. Busque pelo nome da função; as linhas andam. |
| Worker | `plataforma/worker.py` | Importa o `app.py`, carrega o estado e sobe os laços de `_iniciar_loops_de_fundo`. Recicla sozinho depois de 12 h, às 03:00. |
| Régua de trackers v2 | `plataforma/trk_regua_v2.py` | Classificação do tracker no dia (parado, severo, leve, normal). |
| Sol | `plataforma/sol.py` | Elevação solar (NOAA) pela capital da UF. |
| Padrão por inversor | `plataforma/inv_padrao.py` | Queda contra o próprio histórico de 30 dias (13 usinas). |
| Qualidade de dado | `plataforma/qualidade.py` | Clipping e valor travado (só 2C pela API PV; sem tela). |
| Tickets de strings | `plataforma/tickets_str_fechar.py`, `plataforma/tickets_relay.py` | Salvar e finalizar ticket da aba "Strings indisp". |
| Sino | `plataforma/static/notif.js` | Alertas de string que zerou. |
| Estado compartilhado | `plataforma/ufv_state.json` | Trancadas, OS atribuídas, usinas marcadas desligadas, acompanhamento, comentários, sino. |
| Snapshot | `plataforma/cache_snapshot.json` | O que o worker publica e o web serve. |
| Registro de trackers | `trk_eventos.json`, `paradas_book.json`, `trk_parados_fim_dia.json`, `tracker_issues.json` (em `plataforma/`) | Classes por dia, paradas, "parado desde". |
| Relógio do registrador | `plataforma/pv_relogio.json` | Atraso aprendido por usina (Diamantino 1 e 2 hoje). |
| Ronda | `plataforma/whats_ronda.json`, `whats_enviados.json`; serviço `C:\GridcoWhats\wa_service.js` | Horários, grupos, envios do dia; o serviço Node fala com o WhatsApp. |
| Cadastro | espelho em `plataforma/bases/` (BD_Performance, BD_Thopen, Tickets) | Esperadas, String Box, nomes, cliente, estado, região. |

**O que precisa de restart:** mudança só no HTML, não. Mudança no `app.py` precisa reiniciar **os dois** processos: a
régua roda no worker, e a saída das rotas (sol, pouca luz, usina desligada, tickets) roda no web. No servidor, o push na
`main` faz o deploy sozinho (~4 min; confira em `/versao`) e o worker leva de 10 a 20 min para republicar tudo.

---

## 3. Como o dado anda: worker, snapshot e web

### 3.1 Dois processos

| | worker (`python worker.py`) | web (`python app.py`) |
|---|---|---|
| Faz | todos os laços de fundo (coleta, réguas, ronda) | só serve HTTP (waitress, 16 threads) |
| `_MODO_WEB` | falso | verdadeiro |
| `cache_snapshot.json` | **único escritor** (`_persist_loop`, a cada 60 s se houve mudança) | só lê (`_snapshot_watch_loop`, a cada 20 s, por data e tamanho) |
| Vigias próprios | — | `_snapshot_watch_loop`, `_tranc_watch_loop` (20 s), `_cadastro_watch_loop` (60 s) |

Por que dois (25/07/2026): com o rebuild no mesmo processo, "endpoints que respondem em 2–7 ms passavam de 2.900 ms", e
o ciclo completo já era mais longo que o TTL do cache. `GRIDCO_SOLO=1` volta ao processo único; nesse modo o worker se
recusa a subir. **Nunca rode dois workers:** a ronda sairia duplicada.

Do worker à tela, o atraso máximo de publicação é de ~80 s (60 s para gravar + 20 s para o web reler), fora o tempo do
próprio ciclo.

### 3.2 O snapshot

- `_cache_save` grava num `.tmp` e troca atômica; chaves que começam com `_` (lock, TTL) ficam fora.
- `_cache_load` só aplica um cache se o salvo for **mais novo** que o da memória — em 31/07 um snapshot vazio das 09:34
  engoliu o dado bom das 09:35.
- `_persist_registry` lista **21 caches**: strings de pv, sunop, axis, solaredge (`se`), semp, alveslima, 2capi; ETM e
  análise de ETM de pv, sunop, semp, 2capi e pg; trackers de pv, sunop e pg; PR da API PV. O snapshot do Banco (`pg`)
  vai à parte, no nível de cima. Mais extras: `macro`, `ger`, `etm_prob`, `inv_padrao`, `qualidade`, `pv_trk_plant` e
  outros.
- **Fora do snapshot:** ETM e análise da Alves Lima; ETM, análise e trackers da Axis; trackers da SEMP e da 2C pela API
  (`_pv_trk_fonte_cache`); o cache da Entrada. No web, esses são montados na primeira requisição e depois ficam `stale`
  — **medido** hoje: a aba Trackers da 2C levou 36,7 s e a da SEMP 11,5 s para responder.
- O web carrega `trk_eventos.json`, `paradas_book.json` e `perdas_strings.json` **só no boot**. O que atravessa depois é o
  snapshot e o índice `trk_parados_fim_dia.json` (por data do arquivo).

### 3.3 O ciclo do worker (`_prewarm_loop`)

Antes de cada volta: `maybe_reload_equipamentos()`, `maybe_reload_tickets()` e `_expira_por_token_novo()` — o worker não
recebe requisição, então sem isso nunca relia o cadastro (19/08: "98 contra 89 publicadas").

| Etapa | O que roda | Paralelismo e teto |
|---|---|---|
| 1 | Disponibilidade de trackers de hoje: Banco, Athon, Axis, 2C | 4 em paralelo, teto 300 s |
| 2 | A tabela da API PV Thopen (`/api/data`), **sozinha** | teto 300 s (`PREWARM_ABA_PRINCIPAL_MAX_S`); passou disso, segue em fundo |
| 3 | As leves: tabelas de Banco, Athon, Axis, SEMP, Alves Lima e 2C API; ETMs e análises; trackers de Banco e Athon; Geração pivô, Gerencial, ETM do mês | 3 em paralelo, teto 300 s por etapa; **as que dependem da API PV vão por último** |
| 4 | Só 1 volta em 3: PR da API PV, **RenoGrid** (tabela), análise de ETM da Athon, eventos de string da Athon e da Axis, parados da API PV e do Banco | 2 em paralelo, teto 300 s |

- **Período:** `max(gasto + 30 s, 270 s)`. Não medi o de hoje; os registros no código falam em 116 s para a etapa 2
  (22/09) e ~3 min para o resto.
- **Por quê de cada regra:** a etapa 2 sozinha porque em paralelo a `/api/data` foi de 129 s para 484 s (25/07); o teto
  por etapa porque, em 24/09, a consulta do Banco foi de ~3 s para 83 s e a etapa só acabava quando a última tarefa
  acabava; a API PV por último porque ocupava as 3 vagas e deixava Athon, Axis e Banco na fila.
- **Pausa noturna da SunOp (Athon e Axis):** fora de 05:40–18:20 saem do ciclo as seis tarefas de curva
  (`_SUNOP_TAREFAS_CURVA`); ficam as baratas (`last_values`), que mantêm a "sem comunicação" viva de madrugada.
  Decisão do Levi em 26/08. O portão vale só para o reaquecimento de hoje — **nunca movê-lo para dentro da busca**,
  senão o fechamento do dia e os backfills param.
- **Trackers da API PV têm laço próprio** (`_pv_trk_loop`, a cada 60 s), fora do ciclo: a varredura levou 897 s
  (22/09) e levava o ciclo a ~16 min. Não recoloque "PV trackers" na etapa 3.

### 3.4 TTL e `_swr`

- `CACHE_TTL = 300` s em quase tudo; `SUNOP_TTL = 600` s nos caches da Athon e da Axis (Levi, 26/08: "status dos
  trackers e inversores a cada 10 min"; mais que isso abre o disjuntor da borda da SunOp).
- `_prewarm_um_cache` pula o cache que "aguenta até eu passar aqui de novo": sem TTL próprio, idade < 270 s; com TTL
  próprio, `idade + período ≤ TTL`. A margem fixa antiga fazia a SunOp atualizar a cada 17,6 min.
- `_swr` no web: cache fresco → serve; vencido → serve com `stale=True`, **sem reconstruir**; vazio ou `force=1` →
  constrói na hora. A `/api/data?force=1` responde na hora e reconstrói em fundo.
- Na tela, se a resposta vem `stale`, `_pollFresco` tenta de novo até 10 vezes, de 8 em 8 s. O "atualizado HH:MM" é o
  `cache_ts` do payload.

### 3.5 Laços de fundo que tocam o tempo real

| Laço | Cadência | O que faz |
|---|---|---|
| `_prewarm_loop` | ~5 min | o ciclo acima |
| `_pv_trk_loop` | 60 s | trackers da API PV (refaz com idade ≥ 270 s; o dia de cada usina, a cada 30 min) |
| `_trk_parada_loop` | 60 s | "desde quando todos parados" (API PV) |
| `_trk_ev_hoje_loop` | 30 min | eventos de tracker de ontem e hoje (API PV) |
| `_paradas_book_loop` | 1 h | book de paradas das 5 fontes de tracker |
| `_macro_prewarm_loop` | 120 s | o rollup do macro (Entrada, NOC) |
| `_notif_strings_loop` | 30 min, 05:40–18:20 | o sino |
| `_inv_padrao_loop` | 1 h | padrão por inversor |
| `_qualidade_loop` | 1 h | clipping e valor travado |
| `_tranc_watch_loop` | 20 s | relê as strings trancadas |
| `_owen_loop` | 10 min | junta os CSVs da 2C no acervo do dia |
| `_bd_api_loop` | 30 min | espelho das planilhas (cadastro, tickets) |
| `_frac_disp_loop` | 30 min | índice de OS do Fracttal (religamento, OS em inversor) |
| `_sunop_keepalive_loop` | 6 h | renova os tokens web da SunOp |
| `_ronda_whats_loop` | 30 s | dispara a ronda nos horários |
| `_whats_watchdog_loop` | 180 s | reergue o serviço do WhatsApp travado |

### 3.5.1 Cota da SunOp

A conta tem **100 mil requisições por mês** (US$ 0,0005 por requisição acima disso). Em 01–29/09 foram 323.816 (extrato
oficial, `/data/v2/usage/me`), ~22 mil/dia desde 24/09, para um teto de ~3.300/dia. Desde 29/09: status e ETM em lotes
que atravessam usinas (29 POSTs por leitura viraram 8), curva de tracker das usinas numa baixa só (9 viraram 3), a
Entrada contando os parados pelo resumo do worker, `check_token` com validade de 15 min, contador completo em
`/api/sunop/uso` (separa tracker, string e ETM) e o PC em `SUNOP_COLETA=ronda` (só as curvas de tracker que a ronda
usa, de hora em hora). No servidor o gêmeo está vazio, então a curva nunca vem do acervo dele. Detalhe e
testes no `plataforma/CLAUDE.md` ("Cota da SunOp"). **Olhar a tela não gasta nada** — o web serve o que o worker
coletou; gastam o botão Atualizar (busca sem cache), o drill de uma usina da Athon (cache de 5 min por usina,
compartilhado) e a curva de um inversor (10 min, com o gêmeo respondendo primeiro).

### 3.6 Amortecedores

- **Disjuntor da API PV** (`_PvDisjuntor`): 6 falhas **de rede** seguidas abrem o disjuntor por 120 s; nesse tempo toda
  chamada falha na hora (`PVForaDoAr`). Resposta HTTP de erro não conta ("a API está viva"). Por quê: em 24/09 a API
  parou e cada chamada esperava o timeout inteiro — "o Levi viu TODAS as fontes 'sem comunicação'".
- **`fetch_all` em três passadas:** 8 em paralelo com timeout de 90 s; as que falharam, 4 em paralelo com 45 s; o resto
  em sequência com 60 s. O 90 é de 24/09, quando a API respondia em ~48 s por usina.
- **Linha histórica:** usina da família API PV que volta sem dado é trocada pela última linha boa (`_last_known`),
  marcada `dado_historico` e com `falha_comunicacao` forçada. Fica na tela, sai das somas.
- **SunOp:** o primeiro 403 da borda pausa todas as chamadas por 90 s; lote de pathnames que falha vira `sem_dados` (a
  foto está incompleta, e "um pathname que não voltou é desconhecido, não é zero"); um payload todo vazio não apaga o
  anterior (retém até 30 min).

### 3.7 A saída das rotas de strings

As nove rotas de tabela passam por `_servir_tabela_strings`, que trabalha sobre **cópias** (o payload é do worker), nesta
ordem:

1. **`_servir_com_sol`** marca `sol_baixo` e tira a usina sem sol da conta de alertas (ver [7.4](#74-sol)).
2. **`_com_pouca_luz`** marca `rampa` e `pouca_luz` na usina com 0 strings ativas que prova estar gerando.
3. **`_com_usina_desligada`** marca `desligada` na usina calada que tem motivo.
4. **`_com_tickets_str`** anexa os tickets de strings e o "para fechar".

O argumento `conta` diz o que é "sem geração" em cada fonte: `_sem_geracao_api_pv` (pv, semp, alveslima, 2capi),
`_sem_geracao_padrao` (sunop, axis, pg, solaredge) e `_sem_geracao_2c_email` (owen). **Toda rota nova de strings tem de
passar por essa cadeia** — o teste `test_strings_sem_sol_a_noite.py` lê o mapa de rotas da tela e falha se faltar uma.

---

## 4. As nove fontes

| Chave | Chip | Cliente e origem | Linha da usina | Sem comunicação (backend) | Potência por inversor | ETM | Trackers |
|---|---|---|---|---|---|---|---|
| `pv` | Thopen · API PV | Thopen, API PV (conta principal) | `build_summary` | > 30 min da última leitura (relógio corrigido) | `Pac` (kW) | `day_meteo` | API PV `/trackers` |
| `pg` | Thopen · Banco | Thopen, PostgreSQL (`public.raw_*`) | `_pg_build_snapshot` | > 30 min | `active_power` (analógica de 6 h) | `raw_weather_station` | `raw_tracker` |
| `sunop` | Athon | Athon, SunOp `gridco` | `process_plant_sunop` | > 30 min do carimbo das correntes | `P` do inversor; `pot_med` é o **total** da usina | `last_values` / curva | curva POSAT/POSAL de 15 min |
| `axis` | Axis | Axis, SunOp `axis` | idem | idem | idem | idem, fora do ciclo | idem, fora do ciclo |
| `solaredge` | RenoGrid | RenoGrid, portal SolarEdge (`generate-chart`) | `process_site_solaredge` | **nenhuma** | soma dos W das strings | não tem | não tem |
| `owen` | 2C | 2C, CSV por e-mail + API PV | `_owen_strings_rows` + `_2c_unifica_rows` | **nenhuma** | soma das correntes (A) | e-mail (+ API nas da API) | e-mail (+ API) |
| `semp` | SEMP | SEMP, API PV (conta oem@) | `build_summary` | como `pv` | `Pac` | `day_meteo` | API PV, sob demanda |
| `alveslima` | Alves Lima | Alves Lima, API PV (oem@) | `build_summary` | como `pv` | `Pac` | `day_meteo`, fora do snapshot | não tem seguidor |
| `2capi` | (dentro do 2C) | 2C, API PV (oem@) | `build_summary` | como `pv` | `Pac` | `day_meteo` | API PV, sob demanda |

Na tela, qualquer linha com a última leitura há mais de **120 min** também vira "Usina sem comunicação" — é a única régua
de comunicação da RenoGrid e da 2C e-mail na tabela.

**Particularidades que já custaram caro:**

- **`pv`** — o recorte é o `FULL_OM` do cadastro **por nome**, menos as usinas das outras contas (`PV_FONTES`, por
  **id**, porque a API renomeia usina e mantém o id: "Sete Lagoa" × "Sete Lagoas"). A leitura é o `day_inverter` do dia.
  **String Box/combiner:** a corrente real vem de `custom_query` v2 (`data_type=combiner`), casada ao inversor pelo número
  de série (`CMB` + `device_esn`); leitura com mais de 6 h é descartada (a Tanabi 2 tinha um inversor congelado desde
  28/05); a combiner vale 1 h de dia e 12 h à noite, e para quando a cota da conta (800 consultas por dia, 200 por hora)
  chega à reserva de 300 e 20 — o PC e o servidor gastam a mesma cota.
- **`pg`** — o schema `dbt` da Thopen congela; tudo vem das tabelas cruas `public.raw_*`. A linha pega a leitura mais
  nova de cada dispositivo **em 30 dias** (usina parada há dias precisa continuar aparecendo); potência de outro dia
  não vale e vira "sem leitura hoje".
- **`sunop`/`axis`** — `last_values` em lotes de 1.000 pathnames que atravessam usinas (desde 29/09; eram 500 por usina);
  o `pot_med` da linha é o total da usina, então a prova de
  pouca luz usa a mediana por inversor (`pot_inv_med`). Não usa o `InvsFalhaComunicacao` do supervisório: falha parcial
  de inversor é déficit, não usina sem comunicação (CPP100, 05/07). Cota da SunOp: 100 mil requisições por mês. **A Axis
  está com 0 linhas**: não há token de API da Axis gerado.
- **`solaredge`** — só existe potência por string, nunca corrente; string ativa = potência > 0. O **quarto de hora em
  andamento é descartado**, então a última leitura fica ~15 min atrás de propósito (25/09: com o quarto aberto, a
  Colíder 1 mostrava 21 inversores "desligados"). String que não voltou na resposta é limitação da API, não string morta.
  O carimbo vem em UTC (`…Z`).
- **`owen`** — o SCADA da 2C manda CSV por e-mail em janelas de ~3 h; um baixador externo grava as pastas e o
  `_owen_loop` junta no acervo do dia. A tabela é **unificada**: Araputanga, Sete Lagoas, Tupi Paulista e União vêm da
  API PV; Ipixuna do Pará, do e-mail. Os parados, as ocorrências e o livro de trackers seguem pelo e-mail.
- **`semp`, `alveslima`, `2capi`** — conta oem@ da API PV, escolhida por `_pv_token_for`. A oem@ nega o `plant_devices`,
  então não há nome de inversor pela API: a 2C usa o de-para `PV_INV_NOMES`, fechado **pelo kWh diário** (nunca pela
  ordem dos ids), com uma exceção provisória, a União, que está pela ordem; SEMP e Alves Lima nomeiam por posição.

**Cadastro.** A aba **Equipamentos** do BD_Performance (cabeçalho na linha 3), chave "Usina Supervisório":
`ESPERADO_INV[usina][inversor]` = strings esperadas, `ESPERADO[usina]` = inversores e strings, `STRING_BOX`, nomes de
exibição. Pontes de nome em `_aplica_alias_api_cadastro` ("Sete Lagoa", "União"; a API da União só tem a UG 01). A
**Info Geral** dá cliente, estado e região. As planilhas chegam pelo espelho da API de planilhas a cada 30 min
(`bd_api`); aba sem cabeçalho "precisa falhar alto" — em 25–26/08 o cadastro vazio deixou as esperadas em branco em
todas as fontes.

**Tokens.** A API PV (as duas contas), a SolarEdge e o token web da SunOp renovam sozinhos. São manuais: o token de API
da SunOp (6 a 12 meses) e o da **PV Plataforma** (7 dias, com CAPTCHA). Hoje a PV Plataforma é só reserva: trackers,
combiner e a curva de dia passado vêm da API PV desde 22 e 28/09. Sementes em `tokens.txt`, estado em
`tokens_runtime.json`; vale o de maior validade.

---

## 5. Strings: a régua da tabela

### 5.1 Classificação de cada string (`_classifica_strings`)

A primeira regra que casar vence:

| Status | Regra | Constante |
|---|---|---|
| `trancada` | cadeado do analista (chave `usina\|inversor\|Ipv`) | — |
| `inativa` | o inversor não gera: mediana das strings livres com corrente > 0,1 A abaixo de 0,5 A | `STRING_INV_MIN_MED_A = 0.5` |
| `sem_corrente` | corrente ≤ 0,1 A (falha tipo 1) | `STRING_SEM_CORRENTE_A = 0.1` |
| `baixa_perf` | corrente < 60% da mediana do inversor (falha tipo 2) | `STRING_BAIXA_PERF_FRAC = 0.60` |
| `ativa` | o resto | — |

- **Ativas** = `ativa` + `baixa_perf`. Corrente ausente vale 0. A mediana é a "superior" (em contagem par, o elemento de
  cima, não a média dos dois centrais) — o JavaScript do destrancar faz igual.
- Usam esta régua: API PV (e SEMP, Alves Lima, 2C API), Athon, Axis, Banco e 2C e-mail. **A RenoGrid não:** ali ativa é
  potência > 0 W, e o drill nunca mostra "sem corrente" nem "baixa performance".
- A régua de janela 09–15 h (`_ipv_ativas`, `STRING_JANELA_*`, `STRING_ATIVA_FRAC`) **não é a da tabela**: ela serve
  só à "Curva das strings". Os documentos antigos a descrevem como régua da tabela.

### 5.2 Esperadas e descontos

`str_esp` sai do cadastro (`ESPERADO`). Na família API PV, antes da diferença, saem da conta, nesta ordem:

1. **Neutros** — inversor sem visão por string ou em rampa de String Box ([5.4](#54-sem-visão-string-box-e-pouca-luz)).
   Sai o esperado **exato** do inversor, casado pelo nome (`_equip_lookup`, que tolera "INVERSOR01" × "INVERSOR 01" e
   nunca casa por pedaço: "2.1" ≠ "2.18"). Sem nome, sai a média. Por quê: a Tanabi 1 (07/08) cravava −2 com todos os
   inversores em diferença 0.
2. **Desligados** — ativas e esperadas do inversor saem ([5.3](#53-inversor-desligado)).
3. **Desligado com OS** — sai pela OS, sem virar aviso ([5.5](#55-os-atribuída-e-os-do-fracttal)).
4. **Sem leitura hoje** — inversor do cadastro que não apareceu no `day_inverter` de hoje, com sol e a usina gerando,
   quando a conta de quantos faltam fecha. Vira inversor desligado (caso Colorado 2, 25/09).

Nas outras fontes, só desligados e sem leitura saem da conta; não há neutros nem desconto por OS.

**A diferença** (`_dif_por_inversor`, 29/09/2026) é a **soma das faltas de cada inversor**, mais a esperada que nenhum
inversor em conta explica. A sobra vai para `strings_acima_cadastro` e aparece só no título da célula. Vale quando todo
inversor em conta tem esperada no cadastro; senão, cai na conta antiga `ativas − esperadas`. Está em todas as fontes com
esperada por inversor (API PV e família, Athon/Axis, Banco, RenoGrid, 2C e-mail). Por quê: na Rodrigues 2.1 a string PV10
de um inversor estava morta e a sobra de outro zerava a linha — "É INADMISSÍVEL". Regra do comentário: "sobra é cadastro
que conta a menos, falta é string parada — uma não paga a outra".

### 5.3 Inversor desligado

`_macro_prod` decide quem produz; `_inv_desligados_por_potencia` aplica os portões.

| Mediana de potência dos inversores | Abaixo disso, o inversor não produz |
|---|---|
| < 2 kW | 2,0 kW |
| 2 a 8 kW | 25% da mediana |
| 8 a 40 kW | 2,0 kW |
| ≥ 40 kW | 5% da mediana |

- Constantes: `MACRO_POT_INV_MIN = 2.0`, `MACRO_POT_INV_MIN_FRAC = 0.25` (29/09: Guatambu 4 às 08:50, mediana ~3,5 kW, um
  inversor a 1,98 kW contava como parado), `DIAG_TRIP_FRAC = 0.05`.
- **Portões:** (1) sol — `_macro_eh_dia`, 07–18 h e sol ≥ 8° no estado; (2) a usina gerando — algum inversor
  produzindo; "usina parada é outra ocorrência"; (3) leitura — potência ausente não é desligado, salvo "sem leitura
  hoje". O sinal é a potência, não o `Workstate` da SunOp ("Falha na ventilação" em 217 de 329 inversores gerando, 22/09).
- **Sem leitura hoje, por fonte:** API PV — fora do `day_inverter`; Athon/Axis — corrente ou potência de outro dia não é
  de hoje; Banco — última leitura de outro dia; RenoGrid — todas as strings devolvidas sem potência; 2C e-mail — fora do
  e-mail do dia. Usina **inteira** sem leitura não vira inversor desligado: segue sem comunicação.
- Campos da linha: `inv_desligados`, `strings_fora`, `inv_desligados_nomes`.

### 5.4 Sem visão, String Box e pouca luz

- **Sem visão** (API PV): usina String Box no cadastro, ou inversor gerando (≥ 2 kW) com no máximo uma corrente real →
  consulta a combiner. Sem combiner, o inversor fica **sem visão** e neutro — desde 25/09 só se a esperada dele for maior
  que 1 (Cambé, Assis, Tanabi e Ouro Branco 4 liam "1 de 11" e davam −191; usina de 1 string por inversor segue
  contando). Com combiner ou String Box, 0 ativas e ≥ 2 kW: alguma corrente > 0,1 A = **rampa**; tudo ≈ 0 = sem visão.
- **Pouca luz** (29/09/2026): usina com 0 strings ativas que prova estar gerando vira **Baixa irradiância**, não "Usina
  desligada". Provas (`_pouca_luz_de`): mediana dos inversores ≥ 2 kW, ou estação com leitura de até 90 min e POA abaixo
  de 100 W/m² (`POUCA_LUZ_POA_WM2`, `POUCA_LUZ_POA_IDADE_MAX_MIN` — o 90 é pelo carimbo cru, porque o registrador da
  Diamantino anda 1 h atrás). Potência baixa sozinha não prova nada: inversor desligado mostra 0,3 kW com 0,9 A de ruído.
  Caso: Diamantino 1 e 2 e Guatambu 2, 3 e 4 às 08:42 — "0 strings ativas, usina desligada!". Só funciona onde há
  potência por inversor ou estação no cache (fora: RenoGrid e 2C e-mail).

### 5.5 OS atribuída e OS do Fracttal

- **Regra desde 29/09:** a OS só desculpa inversor **desligado**. O desligado com OS atribuída (botão "Atribuir OS") ou
  com OS aberta no Fracttal no ativo sai da conta sem virar aviso (`inv_com_os`, `strings_com_os`). O inversor **que gera**
  com OS atribuída fica na conta, e a OS aparece no título da Diferença: "a falta segue na conta até a string voltar"
  (`os_na_conta`). Antes, a OS 12093 no INVERSOR02 da Rodrigues 2.1 fazia a linha dar "43/43, Normal".
- As OS do Fracttal vêm do índice de disponibilidade (`frac_disp_index.json`, recalculado a cada 30 min pelo worker),
  OS abertas com escopo de inversor. Só a família API PV tem desconto por OS.

### 5.6 Strings trancadas (cadeado)

- A chave `usina|inversor|Ipv` vai para `strings_trancadas` no `ufv_state.json` (`POST /api/state/string-trancada`). A
  string trancada fica fora da mediana e das ativas, com chip azul. O worker relê a cada 20 s (até 09/09 lia uma vez
  só, no import).
- Ao trancar, a tela pergunta `/api/strings/trava-aviso`: se há OS de recomposição aberta ou ticket para aquelas strings,
  abre "Trancar mesmo assim". Se a pergunta falha, deixa trancar ("o aviso é ajuda, não porteiro").
- Ao destrancar, `_strReclassifica` recalcula na hora, na tela, com os mesmos limites do servidor (Levi, 23/09: "não
  destranca imediatamente"). A paridade Python × JavaScript está presa em teste.

---

## 6. O status da usina na tela

### 6.1 Precedência (`_strStatus`)

| # | Condição | Texto | Cor |
|---|---|---|---|
| 1 | `desligada` (com motivo) | Usina desligada | vermelho |
| 2 | última leitura > 120 min ou `falha_comunicacao` | Usina sem comunicação | violeta |
| 3 | `rampa` (pouca luz ou String Box em rampa) | "Inversor desligado" se há inversor desligado; senão "Baixa irradiância" | âmbar |
| 4 | `sem_visao` com padrão crítico / atenção | Inversor fora do padrão / abaixo do padrão | vermelho / âmbar |
| 5 | `sem_visao` | Sem visão de strings | neutro |
| 6 | `sol_baixo` | "Sem sol" (ou "Sem dados") | neutro |
| 7 | dado fresco e 0 strings ativas | Usina desligada | vermelho |
| 8 | `diferenca < 0` | Falha de string | vermelho |
| 9 | `inv_desligados > 0` | Inversor desligado | âmbar |
| 10 | padrão crítico / atenção | Inversor fora do padrão / abaixo do padrão | vermelho / âmbar |
| 11 | temperatura média ≥ 65 °C | Temp elevada | âmbar |
| 12 | `sem_dados` | Sem dados | neutro |
| 13 | — | Normal | verde |

- Comunicação vem antes de tudo porque o CPP100 (23/09) mostrava −248 e 0,0% em vermelho estando só sem leitura. A linha
  7 é o antigo "Sem geração", renomeado em 23/09. A linha 9 é do MRO100 (22/09): o −85 inteiro estava em 5 inversores
  parados e a usina viraria "Normal".
- **Cores dos chips de filtro** (`_stCor`) não batem com as pílulas em três casos: Inversor desligado, fora do padrão e
  abaixo do padrão têm pílula colorida e chip cinza.

### 6.2 Colunas

| Coluna | Mostra |
|---|---|
| Status | a pílula |
| Usina | nome, nota embaixo (`deslNote`: motivo da usina desligada ou a prova de pouca luz), selos de OS de performance e de comentários |
| Inv. | inversores lidos / esperados |
| Ativas | `strings_ativas`; "—" em rampa, sem visão ou sem comunicação |
| Esperadas | `str_esp`; "—" em rampa, sem visão ou sem sol. Nota: "N inv. desligado(s) · M strings fora da conta" |
| Diferença | a soma das faltas; "—" em rampa, sem visão, sem sol ou sem comunicação. Azul se bate com o Acomp., vermelha se < 0. O título explica sobra no cadastro e OS atribuída |
| Acomp. | quantas strings da falta já estão acompanhadas (grava em `/api/state/tracking`) |
| Tickets | ver [seção 8](#8-tickets-de-strings-na-tabela) |
| Última leitura | carimbo; violeta e negrito se passou de 120 min |

A coluna "Disponib." saiu em 25/09.

### 6.3 Ordem, destaque e cards

- **Ordem:** primeiro o déficit **não acompanhado** (a linha pulsa em vermelho), depois o déficit igual ao acompanhado,
  depois sem déficit, por fim quem não tem diferença (sem sol, sem comunicação, desligada, rampa). Dentro de cada grupo,
  a maior falta primeiro. Com movimento reduzido no Windows fica só a faixa lateral, sem animação.
- **Cards do topo:** Usinas, Strings ativas, Usinas desligadas, Temp ≥ 65 °C e Usinas sem comunicação. Os de desligadas
  e sem comunicação contam as pílulas da tabela (depois do filtro de nome, antes do filtro de status).
- **Chips de status:** um por status presente, com contagem; clicar filtra; trocar de fonte limpa.

---

## 7. Usina calada, relógio e sol

### 7.1 Desligada × sem comunicação

A API não diz se a usina está desligada: "calada é calada" (28/09). A usina **calada** (sem dado, com falha de
comunicação ou com leitura de mais de 120 min) vira **Usina desligada** só com motivo, nesta ordem
(`_usina_desligada_de`):

1. **Marcação do analista** — botão "Marcar como desligada" no drill, com observação obrigatória. Some sozinha quando a
   usina volta a gerar.
2. **OS de Religamento aberta na usina inteira** — do índice de disponibilidade do Fracttal. Casos: Ceilândia 1
   (#14711), Assis (#14715), Brodowski (#12693).
3. **Estação comunicando e inversores calados** — estação com leitura de até 30 min e inversores sem leitura há 120 min
   ou mais (Canarana 1: estação às 09:48, inversores desde 23/09). **Hoje só funciona na família API PV** (ver
   [15.1](#151-defeitos-confirmados)).

Sem motivo, fica **Usina sem comunicação**. O drill mostra o motivo numa barra vermelha; sem motivo, uma barra violeta
com o botão de marcar.

### 7.2 Comunicação: duas réguas

- **Backend:** `COMM_ALERT_MINUTES = 30` (família API PV, Banco, Athon/Axis). RenoGrid e 2C e-mail não têm.
- **Tela:** `COMM_STALE_MIN = 120` min (régua do Levi de 22/07: 2 h). Qualquer uma das duas pinta "Usina sem
  comunicação"; só a de 120 min pinta a última leitura de violeta.

### 7.3 Relógio do registrador

A API PV entrega o carimbo do **registrador**. O da Diamantino 1 e 2 anda em horário de Cuiabá: dado minuto a minuto,
sempre 62–63 min "atrás", e a régua dos 30 min dava "sem comunicação" o dia inteiro (28/09). `_pv_relogio_corrige`
**aprende** o atraso por usina — horas cheias, ±12 min, confirmado em duas leituras com o carimbo andando, no máximo 3 h;
zera se a defasagem cai abaixo de 15 min ou se o corrigido cai no futuro. Não segue tabela por estado: a Canarana,
também no MT, manda em Brasília. Vale para a linha da usina e para a série da estação. **O drill não corrige.**

### 7.4 Sol

- **`_macro_sol_baixo`:** fora de 07–18 h, sem sol; dentro, sol abaixo de 8° (`SOL_BAIXO_GRAUS`) na **capital da UF** da
  usina (Info Geral). UF desconhecida vale a janela fixa. Por quê: em 10/09, às 17:52, 89 de 102 usinas estavam
  "críticas" porque o sol de setembro já tinha se posto e a janela fixa dizia "dia".
- É marcado **na saída**, não no build, porque o worker leva minutos por volta.
- Outras janelas vivas, para não confundir: a **Entrada** usa a hora do navegador (noite = antes das 5 h ou a partir das
  19 h); o **sino** usa só a elevação no estado; a **SunOp** pausa a curva fora de 05:40–18:20.

### 7.5 Fuso do processo

Todas as réguas comparam a hora local ingênua. O processo precisa rodar em UTC−3: em 22/09 um servidor em UTC mostrou
108 de 115 usinas da API PV "sem comunicação". `/healthz` avisa se o fuso estiver errado.

---

## 8. Tickets de strings na tabela

- **De onde:** aba "Strings indisp" da planilha de Tickets (espelho da API), só tickets com "Fim da ocorrência" vazio,
  com o diário do app por cima. A usina casa pelo nome ou pelo código; "X 1 e 2" é dividido pelo 1º número do inversor.
- **Na linha** (`_com_tickets_str`): cada ticket leva a parte que cabe à linha; ticket da usina inteira conta até as
  esperadas da linha e "fecha por parte" (Brodowski: 209 strings em duas linhas).
- **"N para fechar":** 0 strings faltando e ticket aberto (Levi, 23/09: "Se tem 0 strings inativas e tem 1 ticket aberto,
  então sei que devo fechar"). Como a diferença é a soma das faltas por inversor, "para fechar" exige nenhuma falta em
  nenhum inversor.
- **Não julga** com sem sol, usina desligada, sem comunicação ou irradiância baixa — mostra "N aberto(s)" com o motivo.
  Inversor sem visão é julgado pela geração contra os pares (perda menor que 6% não dá para dizer).
- **Coluna:** "—" sem ticket e sem falta; "N para fechar" em verde; com falta, a barra "tickets/falta", vermelha se sobra
  falta sem ticket.
- **Card e Finalizar:** causa raiz, status, quantidade, OS vinculada. Finalizar relê a linha, confere usina, inversor e
  início, recusa conflito com outra pessoa (409), grava a linha **inteira** (a API troca a linha toda), grava o diário (que
  impede o sync do Excel de reabrir o ticket) e só confirma com o valor lido de volta.

---

## 9. ETM

### 9.1 A régua ao vivo (`_diagnostico_etm`)

| Aviso | Tipo | Quando |
|---|---|---|
| Sem comunicação | crítico | última leitura há mais de 30 min |
| Possível falta de dados | atenção | de dia, leitura entre 15 e 30 min, ou buraco de mais de 30 min na série |
| POA zerado | crítico | a partir das 10 h, pico de POA entre 9 e 15 h abaixo de 20 W/m² |
| GHI zerado | crítico | a partir das 10 h, com POA > 50 W/m², o GHI reporta e o pico fica abaixo de 20 |
| Sem leitura de GHI | nota | GHI não reporta (as estações AIML não têm GHI) |
| POA-RI zerado ou sem leitura | informação | nunca alarma (decisão do Levi, 27/08) |
| GHI > POA; quedas de POA | atenção | padrões suspeitos na curva |

- Regra do Levi de 10/09: **alarmar só GHI e IPOA zerados**. Severidade: 0 com crítico, 1 com atenção, 3 normal.
- A leitura do sensor pega o **maior valor plausível** entre os campos (até 1.600 W/m²: já veio `piraPOA1 = 6393`).

### 9.2 Abas e cards

- Uma aba por fonte (a RenoGrid não tem ETM). Na família API PV, um card por UFV, com o melhor skid.
- **Cor única** por veredito (Levi, 10/09: "essa hierarquia de cores… está confusa, deixe no padrão"): vermelho alarme,
  âmbar atenção, violeta sem comunicação, verde OK, cinza sem dado. **Pulsa só alarme sem OS.**
- **Chip laranja "OS nº · ETM":** OS aberta no Fracttal cujo **ativo** é de estação (meteorológica, piranômetro,
  datalogger…), nunca pela descrição. Sem OS e com alarme, botão "Abrir OS · ETM".
- O botão "Alarmes · N" nasce desmarcado (Levi, 21/09). O diagnóstico do **mês** não pinta mais o card (21/09: três
  usinas da 2C estavam vermelhas com o sensor lendo 1.267, 1.160 e 898 W/m²).

### 9.3 O diagnóstico do mês (`_etm_problemas_build`)

Alimenta o card ETM da Entrada e o `/painel`: IPOA e GHI das abas por usina do BD_Performance nos dias fechados do mês
(IPOA zerado ou ausente = alarme; valor constante por 3 dias = aviso "sensor travado?") e, no Banco, IPOA ausente com a
usina gerando. Cache de 15 min.

---

## 10. Trackers

### 10.1 A régua

- **Qual roda:** a **v2** (`trk_regua_v2.py`), ligada por `TRK_REGUA_V2=1` — **medido** hoje: ligada no servidor e no
  local (`/api/trk/regua/diff` → `flag_v2_ligado`). A legada fica de reserva, se a v2 der erro. O mesmo classificador
  serve tabela, drill, gráfico, registro e ronda ("régua única": em 04/08 a Coração 2 tinha 22 parados na tabela, 0 no
  detalhe e 1 no gráfico).
- **Janela:** 06:00–18:00. Madrugada fora (22/09: 19 pontos de madrugada bastavam para trackers da Brodowski virarem
  "normal"; em 40 usinas, 70 de 1.049 trackers mudaram, todos no sentido de parado).
- **Parado (v2):** sem ponto; ≥ 98% das leituras em ±0,1° (comunicação morta); amplitude robusta (p02–p98) abaixo de
  10° (travado); leitura repetida em ≥ 75% do dia com ≥ 20% fora de ±55° (glitch); ou congelado ≥ 90 min sem retomar.
- **Severo e leve:** ocorrência de congelamento (banda de 2°, ≥ 15 min) em que o tracker fica ≥ 13° longe da mediana da
  frota (15° no batente), ou em que a frota anda ≥ 13° enquanto ele está parado; ≥ 30 min = severo, 15–29 min = leve.
  Platô compartilhado no batente e saída atrasada de estacionamento não contam.
- **Médio:** severo cujo desvio fica abaixo do teto (15°; 15,5° na Thopen) e cabe inteiro em 07:30–10:00 ou 14:30–17:00;
  ou, para quem estava normal ou leve, congelamento de ≥ 30 min dentro de uma dessas janelas com desvio de 8° até o teto.
- **O alvo do supervisório não classifica** ("o alvo da API PV é furado": acompanha o tracker travado). O alvo exibido é
  a mediana do alvo de quem gira, limitada a ±55°.
- **Correções depois da régua:**
  - *Em cima do alvo:* parado a até 12° do alvo volta a normal (TIM100, 30/07), a menos que tenha ficado imóvel o dia
    todo (amplitude < 3°) ou que, na última hora e meia, a frota tenha andado e ele não (Ibaté 2, 05/08: "três telas,
    dois veredictos").
  - *Curva curta* (28/09): tracker com menos de 4 h de dado na janela, com a frota quase parada, não é parado
    (Guaratinguetá V, 48 "parados" às 15:44) — **salvo** se já estava parado no último dia classificado ("de manhã toda
    curva é curta"; sem isso a ronda das 08:25 deixaria de citar 218 paradas).
  - *Sem comunicação* (roxo): leituras ≈ 0° ou mudo há mais de 45 min contra o mais recente da frota; conta como parado
    (08/09).
- **Frota parada:** todos os trackers da usina parados há 2 h ou mais vira o status "Frota parada há X" (21/09).

### 10.2 Fontes e cadência

| Fonte | De onde | Cadência |
|---|---|---|
| API PV | `POST /trackers` com o dia inteiro (8,8 a 13,8 MB por usina) | laço de 60 s; tabela refeita com idade ≥ 270 s; o dia de cada usina, a cada 30 min — a frequência é a única alavanca de custo |
| Athon | curva POSAT/POSAL de 15 min, **incremental** (último ponto − 30 min) e cheia uma vez por hora; primeiro o acervo do gêmeo, depois a SunOp | ciclo do worker, TTL 600 s, pausa fora de 05:40–18:20 |
| Axis | idem | **só sob demanda** (fora do ciclo e do snapshot) |
| Banco | `public.raw_tracker` | ciclo do worker, 300 s |
| 2C | e-mail para Ipixuna do Pará; API PV para Araputanga, Sete Lagoas, Tupi e União | e-mail a cada 10 min; API sob demanda |
| SEMP | API PV (conta oem@) | sob demanda |

As usinas da 2C pela API ficam **fora** da varredura geral da API PV (`PV_TRK_OUTRA_FONTE`) para a mesma ocorrência não
abrir duas vezes no livro. A PV Plataforma é só reserva.

### 10.3 Registro

- **`trk_eventos.json`** (26,7 MB, desde 01/06): por dia e usina, as classes que não são normais, com a versão da régua
  (mudou a régua, o histórico é refeito; sem o carimbo, "toda mudança de régua era inócua no histórico").
- **"Parado desde":** varre os dias para trás até o primeiro em que o tracker girou; o livro `tracker_watch` é reserva.
- **Book de paradas** (`paradas_book.json`, a cada hora): dias seguidos em "parado" = uma parada, aberta se chega a hoje.
- **Disponibilidade da tabela é por contagem:** parado pesa 1, severo 0,5; médio e leve não entram (régua do Levi,
  22/07 — a conta antiga dava 100% com a frota inteira parada).

### 10.4 Tickets, de-para e OS

- **Tickets:** aba "Trackers" da planilha. Só ocorrência **aberta** conta. "Novos" = anômalos sem ticket;
  "Acompanhados" = com ticket; "Normaliz." = ticket aberto e tracker normal (candidato a fechar). Ticket de status
  "Parado" aberto tira o tracker da ronda.
- **De-para supervisório ↔ Fracttal:** `plataforma/trackers_depara.xlsx` (casado, a confirmar, sem par) — o elo no chip.
- **OS de tracker pela plataforma** (25/09): uma OS por tracker, em lotes de até 5, ativo pelo código do Fracttal no
  de-para, programada para o dia seguinte; resposta ilegível conta como "pode ter criado" e manda conferir o histórico.

### 10.5 A tela

- Colunas: Usina, Trackers, Parado, Severo, Médio, Leve, Disponibilidade, Tickets, Normaliz., Desvio médio, Última
  leitura, Status. Status: "Sem dado há XhMM", "Sem comunicação", "Frota parada há X", "Todos parados", "Atenção" (algum
  parado) ou "OK". Severo, médio e leve sozinhos não geram "Atenção".
- Drill: chips por tracker com o desvio; cor por classe (parado vermelho, severo laranja, médio âmbar, leve amarelo, sem
  comunicação roxo, normal verde); o drill é rebuscado a cada abertura (Brodowski, 07/08: chips congelados).
- Gráfico de até 5 dias, 06–18 h por padrão; o status de cada linha é o dos cards (o TIM100 dizia 76 parados no gráfico
  contra 8 nos cards).

---

## 11. O drill-down de uma usina

- **Sequência:** clicar na usina carrega os inversores (`/api/plant/<id>` na família API PV; `/api/pg/plant/<id>`,
  `/api/sunop|axis/plant/<nome>`, `/api/solaredge/plant/<id>`, `/api/owen/strings/plant/<id>`); clicar no inversor
  carrega a curva do dia. Uma usina e um inversor abertos por vez. O drill da API PV guarda 90 s e faz as três chamadas
  em paralelo (24/09: de 34,8 para 11,0 s).
- **Linha do inversor:** ativas/total, esperadas, diferença. Fundo vermelho com 0 ativas (`semGer`), âmbar com baixa
  performance. Inversor desligado: strings cinza e diferença "—" se está fora da conta. Sem visão: mostra o padrão de 30
  dias no lugar das strings. Rampa: "Pouca luz". Etiqueta "N sem ticket" em vermelho.
- **Chips de string:** sem corrente vermelho, baixa performance âmbar, trancada azul, ativa verde, inativa e desligado
  cinza; laranja quando a curva marcou a string abaixo das irmãs. Cadeado no chip.
- **Curva do dia:** hoje, pelo `day_inverter` (corrente). Dia passado na API PV: `custom_query` v2 em **corrente**
  (28/09); o inversor sem corrente cai em **potência** pela PV Plataforma (`unidade` = corrente, potência ou misto). Se a
  curva não vem, a resposta diz por quê (`motivo`: token vencido, sem token, sem curva na fonte, erro), para a tela não
  culpar a fonte quando o problema é o token. Em dia passado, só o gráfico é da data; chips e ativas são de hoje.
- **CSV da usina:** `/api/<fonte>/strings/curva.csv` (sem Alves Lima).
- **Última OS:** performance, religamento e chamado do Fracttal, recolhido por padrão — só pergunta ao Fracttal ao abrir
  (a cota é de 200 por minuto para a empresa inteira).
- **Atribuir OS:** escolhe entre as OS abertas da usina; a atribuição some quando a OS fecha.
- **Visão Geração:** kWh por inversor até ontem (ontem, 7 dias, mês ou intervalo), desvio contra a mediana da usina
  (−5% normal, −5 a −10 observar, −10 a −20 atenção, ≤ −20 crítico), da base do cliente (BD_Thopen ou BD_Performance),
  nunca da API ao vivo.

---

## 12. Entrada e macro (NOC)

### 12.1 A Entrada

| Nível | URL | Conteúdo |
|---|---|---|
| 1 | `/` | cinco cards sem número; cada um abre numa aba ao lado (29/09) |
| 2 | `/tempo-real` | um card por cliente × fonte, nesta ordem: Thopen/API PV, Thopen/Banco, Athon, Axis, RenoGrid, 2C, SEMP ("apenas o que eu quero que apareça", 25/09) |
| 3 | `/tempo-real/<fonte>` | Sem comunicação, Strings faltando, ETM, Trackers parados, e o Monitoramento no iframe |

- **Um endpoint só:** `/api/entrada/tempo-real`. O cache vale 30 min (Levi, 06/09: 2 min "custava cota da SunOp sem o
  plantão precisar"; urgência é o botão Atualizar, que exige 60 s desde a última construção). A parte de **strings** é
  recalculada a cada leitura, do rollup (memória de 15 s) — em 08/09 o card da Athon dizia "65/153" com a tabela em 28.
- **Trackers parados:** as cinco fontes em paralelo, 30 s de prazo cada; quem estoura reaproveita a última contagem boa
  (até 3 h) e marca atraso. Esse cache é montado **no processo web**.
- "Strings faltando" soma o `strings_faltando` do macro, o campo já silenciado: usina sem comunicação, desligada, parada,
  sem visão, em pouca luz ou sem sol não entra — as mesmas que a tabela mostra com a Diferença em "—". Até 29/09 a conta
  lia a diferença crua e contava a pouca luz e o fim de tarde (medido no PC às 12:38: 580 contra 177 na API PV).

### 12.2 O rollup (`_portfolio_rollup`) e o status do macro

- Junta as fontes (Banco, API PV, Athon, Axis, 2C, RenoGrid, SEMP), uma entrada por usina de exibição (sub-usinas da
  mesma fonte somadas: Altair 1 a 5 viram "Altair"). Na disputa da usina, **vence a pior** (menor severidade).
- **A 2C entra com a linha da tabela** (`_2c_unifica_rows`): a da API onde ela vê, a do e-mail no resto (29/09).
- **O déficit é o da tabela:** `_macro_dif` lê a `diferenca` da linha (a soma das faltas por inversor); ativas −
  esperadas só vale sem ela (29/09).
- **Severidade de quem a régua de strings cala** (sem visão, pouca luz, sem sol): não vem das strings, que dizem "sem
  geração" com 0 ativas; vale o degrau do status (29/09 — antes a fatia sem visão vencia a disputa e escondia a fatia
  com problema).
- **Telemetria parada:** com a frota lendo fresco (< 1 h), usina com leitura de mais de 2 h vira sem comunicação.
- **`_macro_status`**, a primeira que casar: desligada → sem comunicação → sem sol → rampa (crítico se há inversor
  desligado) → sem produção (mediana < 2 kW de dia) → padrão → sem visão (ok) → inversor desligado (crítico) → falta
  de strings (≤ −5 crítico, senão atenção) → ok.
- Laço a cada 120 s no worker; `/api/macro` no web só serve o publicado.

---

## 13. Alertas: sino e ronda do WhatsApp

### 13.1 Sino (backend)

- A cada 30 min, de 05:40 a 18:20, compara a lista de strings sem corrente com a leitura anterior; só o que é **novo**
  vira aviso ("string N zerou"). A primeira leitura do dia só firma a base; leitura anterior com mais de 3 h (PC dormiu)
  refaz a base sem avisar; string que zerou com o sol baixo é descartada; **mais de 100 quedas numa leitura = nenhuma é
  avisada** (inundação: "nenhuma frota perde 100+ strings de defeito ao mesmo tempo").
- **A régua de "sem corrente" do sino muda por fonte:**

| Fonte | Entra no sino |
|---|---|
| API PV, SEMP, Alves Lima, 2C API | string zerada durante **toda** a janela de geração do inversor (≥ 30 min); **quem gerou e caiu no meio do dia não entra** |
| Athon, Axis | ocorrência aberta hoje: caiu, não voltou, inversor gerando, ≥ 30 min |
| Banco | foto instantânea |
| 2C e-mail | último valor do e-mail |

- O padrão por inversor também gera aviso (uma vez por inversor por dia).

### 13.2 Sino (tela)

Consulta a cada 60 s, agrupa por usina e inversor, abre `/tempo-real/<fonte>?view=strings&usina=…`. O "visto" fica no
navegador de cada pessoa. Toasts sem som, de propósito.

### 13.3 Ronda do WhatsApp

- **Onde roda:** só no worker do **PC local** (`whats_ronda.json` ligado; no servidor está desligada), com o serviço Node
  `C:\GridcoWhats\wa_service.js` na porta 5099. Horários **08:25 e 13:00** (o `plataforma/CLAUDE.md` ainda diz 13:15).
  Tolerância de 120 min para disparos atrasados; os grupos saem com intervalo aleatório de ~1 min (a conta foi restringida
  por "spam" em 14/07); o envio fica gravado por região na hora (era a causa da ronda dobrada).
- **Conteúdo:** trackers parados por região (Centro-Oeste, Nordeste, Norte, Sudeste, Sul), das cinco fontes, pelo mesmo
  critério do tempo real. Saem: usinas excluídas no JSON (hoje Salto Pirapora); parado a até 10° do alvo; parado com
  ticket "Parado" aberto (vai para "EM ACOMPANHAMENTO DA PERFORMANCE"); em garantia vai para seção própria.
- **Estado hoje (medido, 29/09 ~11:55):** a ronda das 08:25 **falhou nas cinco regiões** com "sessão não conectada:
  aguardando_qr" (Norte 9, Nordeste 19, Centro-Oeste 78, Sudeste 239, Sul 108 trackers). O último envio gravado em
  `whats_enviados.json` é de 23/09, 13:00. O vigia reinicia o serviço a cada ~6 min, e cada reinício gera um QR novo em
  `C:\GridcoWhats\qr.png`. **Para voltar:** no celular do chip da ronda, WhatsApp → Aparelhos conectados → escanear o
  QR mais recente.

---

## 14. O estado hoje (medido em 29/09/2026 às 11:39)

Servidor `app.gridco.com.br`, versão `c03bdb3` (no ar desde 11:03). Login por sessão; nada foi escrito.

**Strings**

| Aba | Usinas | Strings esperadas | Payload de | Com diferença < 0 | Com inversor desligado | Caladas |
|---|---|---|---|---|---|---|
| Thopen · API PV | 115 | 12.665 | 11:31 | 24 | 8 | 6: Alto Paraná 2, Canarana 1 e Paranavaí (linha histórica); Assis Skid 1, Brodowski Skid 1 e Ribeirão Cascalheiras (sem dado) |
| Thopen · Banco | 22 | 3.836 | 11:37 | 8 | 1 | 3: Ipixuna 1 e 2 (desde 17/09), Piracicaba I (desde 24/09) |
| Athon | 10 | 4.310 | 11:31 | 4 | 4 | 2: SMP100 (desde 28/09 19:48), TIM100 (desde 07:58) |
| Axis | 0 | — | — | — | — | — |
| RenoGrid | 7 | 1.001 | 11:33 | 4 | 3 (Crateús com 41 inversores desligados) | — |
| 2C | 5 | 980 | 11:37 | 1 | — | Ipixuna do Pará (sem dado) |
| SEMP | 2 | 160 | 11:31 | — | — | — |
| Alves Lima | 1 | — | 11:31 | — | — | Morada Nova (sem dado) |

Das seis caladas da API PV, duas têm motivo e aparecem como **Usina desligada**: a Canarana 1, pela estação (comunica e
os inversores não), e a Brodowski Skid 1, pela OS de religamento 12693. As rotas que vêm do snapshot responderam em menos
de 0,1 s.

**ETM:** API PV 110 estações (11 críticas, 21 em atenção, 19 sem dados); Banco 19 (2, 3); Athon 19 (4, 7, 3 sem dados);
2C 5; SEMP 2; Alves Lima 1 (sem dados); Axis 0.

**Trackers:** API PV 118 usinas, 3.382 trackers, 475 parados, 78 severos, 20 leves, 0 médios (ver [15.1](#151-defeitos-confirmados));
Banco 15 usinas, 704 trackers, 153 parados, 24 severos, 11 médios; Athon 9 usinas, 1.005 trackers, 81 parados, 17
severos, 5 médios; 2C 294 trackers, 3 parados; SEMP 80 trackers, 0 parados; Axis 0.

**Macro:** 106 usinas — 60 ok, 14 em atenção, 13 críticas, 12 sem comunicação, 5 sem produção, 2 desligadas; 298 strings
faltando.

**Entrada (cache das 11:34, antes do conserto da [15.0](#150-corrigidos-em-29092026-à-tarde))**

| Card | Sem comunicação | Desligadas | Críticas | Strings faltando (não reconhecidas) | ETM (alarmes do mês) | Trackers parados (com ticket) |
|---|---|---|---|---|---|---|
| Thopen · API PV | 3 | 2 | 9 | 341 (292) | 0 | 475 (111) |
| Thopen · Banco | 3 | 0 | 2 | 54 (47) | 2 | 153 (0) |
| Athon | 2 | 0 | 2 | 7 (0) | 1 | 81 (71) |
| Axis | 0 | 0 | 0 | 0 | 0 | 0 |
| RenoGrid | 0 | 0 | 1 | 27 (23) | 0 | sem fonte |
| 2C | **4** | 0 | 0 | 0 | 2 | 0 |
| SEMP | 0 | 0 | 0 | 0 | 0 | sem fonte |

**Ronda:** a das 08:25 não saiu (ver [13.3](#133-ronda-do-whatsapp)).

---

## 15. Pontos de atenção

### 15.0 Corrigidos em 29/09/2026, à tarde

Achados na primeira versão deste documento e corrigidos no mesmo dia, com teste (`tests/test_macro_segue_a_tabela.py`)
e replay no dado real do PC às 12:38 (mesmo snapshot pelas duas regras: 13 de 106 usinas mudam, todas explicadas):

- **O macro e a Entrada contavam `ativas − esperadas`**, sem a diferença por inversor: a Poconé 1 tinha 202/202 e −6 na
  tabela e "ok · Normal" no macro. Agora `_macro_dif` lê a `diferenca` (Assis 8 → 9, Guatambu 26 → 28).
- **A 2C do rollup disputava e somava e-mail e API.** No servidor, a linha do e-mail sem dado vencia e a Entrada dizia "4
  sem comunicação" com Araputanga, Sete Lagoas e Tupi Paulista lendo às 11:29 pela API; no PC, as duas se somavam
  (Araputanga 472 ativas de 236, Tupi Paulista 800 de 400). Agora entra a linha da tabela.
- **A Entrada contava as strings de quem a tabela deixa neutro** (pouca luz, sem sol): 580 "faltando" no card da API PV
  contra 177 (Poconé 1 e Diamantino, céu fechado no MT).
- **A fatia sem visão vencia a disputa da usina física** (severidade "sem geração" por ter 0 ativas): a Ceilândia 1
  estava "ok · Sem visão" com o Inversor 2.6 a 0% do padrão ontem; a Céu Azul, "ok" com a III crítica; e 8 das 10
  primeiras do NOC eram usinas "ok". Agora as duas são críticas e o topo do NOC só tem problema.
- **Usina fatiada com uma fatia calada** dizia "204 string(s) abaixo do esperado" com o status "ok" (Diamantino).

### 15.1 Defeitos confirmados

Em aberto. Cada um foi conferido no código e, quando dá, no dado do servidor de hoje.

1. **O motivo "estação comunicando, inversores calados" não funciona no Banco, na Athon nem na Axis.**
   `_etm_leitura_por_pid` procura `_pg_etm_analise_cache`, `_sunop_etm_analise_cache` e `_axis_etm_analise_cache`, que
   não existem (os nomes certos não têm o `_etm`), e pula essas fontes em silêncio. O teste troca a função inteira, por
   isso não pegou.
2. **A coluna Médio da aba Thopen · API PV é sempre 0.** A análise por usina conta os médios, mas a montagem da tabela
   (`_build_pv_trk_payload`) não copia o campo `medios`. Esses trackers não aparecem em nenhuma coluna da tabela, só no
   drill. Medido: 0 médios na API PV contra 11 no Banco e 5 na Athon.
3. **O "com OS" do card ETM da Entrada é sempre 0.** A conta procura `ticket` nos itens do cache do mês, mas esse campo
   só é anexado à cópia que a rota `/api/etm/problemas` devolve — e ele guarda o comentário do analista, não uma OS.
4. **ETM > Tabela:** as colunas POA, GHI, POA-RI (kWh/m²) e Pluviômetro ficam sempre "—": a tela lê campos
   (`poa_kwh`, `ghi_kwh`, `poari_kwh`, `chuva`) que nenhuma rota devolve.
5. **"Novos" e "Acompanhados" zerados nas abas Trackers do Banco e da 2C:** o resumo dessas fontes não traz os dois
   campos, e a tela mostra 0.
6. **Caches fora do snapshot são montados na requisição do web** — medido: Trackers da 2C em 36,7 s, da SEMP em 11,5 s,
   ETM da Alves Lima em 7,4 s. Depois ficam `stale` até alguém forçar.
7. **A ronda não avisa quando cai.** A sessão do WhatsApp caiu e nada na plataforma chamou atenção: o vigia só reinicia
   o serviço (e gera outro QR). Usina sem região na Info Geral também nunca sai na ronda.
8. **O Monitor da Ronda não vê os envios do worker.** `/api/ronda/whats/status` é servida pelo web, que lê
   `whats_enviados.json` e o log só no boot; quem envia (e relê o arquivo) é o laço do worker. Medido em 29/09: a das
   13:00 saiu nas cinco regiões (gravada às 13:08) e o status continuava dizendo que nada tinha saído hoje.

### 15.2 Riscos lidos no código, a conferir

- **Teto do Médio da Thopen (15,5°) não chega ao status ao vivo:** `_lst_usina` procura o nome da usina nos trackers, e
  eles não levam esse campo; ao vivo vale 15°. O registro histórico usa 15,5°.
- **RenoGrid e a idade da leitura:** `_usina_idade_min` lê o carimbo com "Z" (UTC) como hora local e dá idade negativa;
  a usina da RenoGrid nunca fica "calada" pela idade no backend, e o motivo de OS de religamento não a alcança.
- **Inversor desligado em manhã escura:** com a mediana abaixo de 2 kW, o limite é 2 kW; se um inversor passar disso, os
  que ainda estão abaixo viram "desligados". Nenhum teste cobre o caso misto.
- **POA sem valor na janela vira "POA zerado"**, sem a guarda que o GHI tem ("só acusa se o sensor reporta").
- **OS abertas:** o índice usado no chip de ETM e no "Atribuir OS" só considera o status 1 do Fracttal; o resto da
  plataforma trata 0, 1, 5 e 6 como abertas.
- **OS atribuída não confere se a OS ainda está aberta** na conta das strings; a limpeza só acontece quando alguém abre a
  lista de OS de performance. Havia 12 atribuições, a mais antiga de 29/06.
- **Drill em cache no navegador:** os inversores de uma usina ficam na memória da página até recarregar; o Atualizar só
  renova a tabela.
- **O web não relê** `trk_eventos.json`, `paradas_book.json` e `perdas_strings.json` depois do boot.
- **Trackers parados da 2C podem entrar duas vezes na Entrada** se a aba de trackers da 2C foi aberta no web (linhas da
  API PV e do e-mail somadas).
- **Estado gravado pelos dois processos:** `ufv_state.json` tem trava só dentro de cada processo.

### 15.3 Textos defasados no código e nos documentos

- `plataforma/CLAUDE.md`: ronda "08:25/13:15" (é 13:00); lote da SunOp "40 pathnames" (é 600); tamanho do `app.py`; "os
  trackers da 2C seguem pelo e-mail" (a tabela já usa a API nas três).
- Comentários do `app.py`: "Tupi Paulista fica fora" do `PV_FONTES`; "os 8 pares" da Entrada (são 7); "a 2C fica de
  fora" do sino (está dentro); `dbt.*` nos trackers do Banco (é `raw_tracker`); "8–10°" e janelas do Médio (valem as
  constantes); "15 min por varredura" do `_pv_trk_loop`.
- `docs/api-pv-operation.md` §7.1: "não há disjuntor para a API PV" (há, desde 24/09); combiner a cada 5 min (é 1 h de
  dia); três usinas da 2C pela API (são quatro).

---

## 16. Documentos que esta referência substitui

| Documento | O que está defasado |
|---|---|
| `docs/regras-de-negocio.md` §5–7 | régua de string ativa (descreve a de janela, que não é a da tabela), ETM e trackers de junho |
| `docs/arquitetura.md` | "6 fontes", Banco por `dbt.*`, sem worker nem snapshot |
| `docs/dashboard-tempo-real.md` | é o blueprint do PR ao vivo (junho), não o Monitoramento |
| `docs/metodologia-analise-trackers.md`, `docs/deteccao-trackers.md` | especificações de julho, superadas pela v2 |
| `docs/regua-trackers-resultado-workflow.md` | histórico da v2; cita funções que não existem mais |
| `docs/handoff-integracao-trackers/parametros-trackers-parados.md` | apresenta a régua legada como definitiva |

Continuam valendo, como aprofundamento: [API PV Operation](api-pv-operation.md) (menos o §7.1), [API SunOp](coleta-sunop.md),
[Metodologia de strings](metodologia-analise-strings.md) (gabaritos da curva), [Criador de Relatório](criador-de-relatorio.md)
e o `plataforma/CLAUDE.md`, que é o diário de desenvolvimento.

---

## 17. Testes que prendem as regras

`python -m pytest -q` a partir da raiz.

| Tema | Arquivos em `tests/` |
|---|---|
| Régua de string e tela | `test_strings.py`, `test_strings_destrancar_tela.py`, `test_strings_sem_sol_a_noite.py`, `test_strings_sem_coluna_disponibilidade.py`, `test_strings_problema_trancada.py` |
| Diferença, desligado, sem leitura | `test_diferenca_por_inversor.py`, `test_inversor_desligado_conta_strings.py`, `test_inversor_desligado_fora_das_esperadas.py`, `test_inversor_sem_leitura_desligado.py`, `test_inversor_sem_leitura_todas_as_abas.py`, `test_padrao_athon_todas_as_abas.py` |
| Usina calada, pouca luz, sol | `test_usina_desligada_e_relogio.py`, `test_usina_sem_comunicacao_ou_desligada.py`, `test_pouca_luz_nao_e_desligada.py`, `test_sol.py`, `test_sol_macro_sino.py` |
| Tickets de strings | `test_tickets_strings.py`, `test_tickets_str_fechar.py`, `test_tickets_str_pela_geracao.py`, `test_tickets_str_por_codigo.py` |
| Fontes | `test_api_pv_fora_nao_trava_as_outras_fontes.py`, `test_combiner_apipv.py`, `test_combiner_cota_e_sem_visao.py`, `test_sunop_*.py`, `test_solaredge_*.py`, `test_fonte_2capi*.py`, `test_2c_tempo_real_unificado.py`, `test_2c_uniao.py` |
| ETM | `test_etm_regua_alarme.py`, `test_etm_alarme_e_do_agora.py`, `test_etm_coluna_ipoa.py`, `test_etm_os_fracttal.py` |
| Trackers | `test_trk_regua_nucleo.py`, `test_regressao_trackers.py`, `test_trackers_cobertura_curva.py`, `test_trackers_piso_dia_anterior.py`, `test_trackers_semcom_parado.py`, `test_trackers_chart_status.py`, `test_frota_de_trackers_parada.py`, `test_trackers_pela_api_fixa.py`, `test_trackers_tickets.py`, `test_trackers_depara.py`, `test_trackers_os_plataforma.py`, `test_ciclo_nao_espera_trackers.py` |
| Entrada e macro | `test_entrada_tempo_real.py`, `test_entrada_trk_sobrevive_restart.py`, `test_entrada_so_os_cards_escolhidos.py`, `test_entrada_cards_abrem_ao_lado.py`, `test_macro_regua_usina.py` |
| Alertas, padrão, qualidade | `test_notificacoes.py`, `test_inv_padrao.py`, `test_inv_padrao_app.py`, `test_qualidade.py` |
| Tela e rotas | `test_monitoramento_*.py`, `test_drill_api_pv_rapido.py`, `test_curva_strings_*.py` |

---

## 18. Como mexer sem quebrar

- **Regra nova de status vale em todo lugar que decide status:** a linha da fonte (build), o drill, a saída
  (`_servir_tabela_strings`), o macro (`_macro_status`, `_macro_item`, `_macro_dif`), a Entrada
  (`_entrada_tr_strings_de`) e o sino. Os defeitos corrigidos em 29/09 ([15.0](#150-corrigidos-em-29092026-à-tarde)) eram exatamente uma
  regra que chegou à tabela e não chegou ao macro. E vale **em todas as abas**, não só na da API PV.
- **Trabalho pesado vai para o worker.** O web não reconstrói cache; se precisar de dado novo, é um laço ou uma tarefa
  do ciclo — e o cache novo entra no `_persist_registry`, senão o web nunca o recebe.
- **Não recolocar** os trackers da API PV no ciclo, **não mover** o portão noturno da SunOp para dentro da busca, **não
  subir** dois workers.
- **Medir antes e depois:** tempo do ciclo, tempo da rota, e o número da tela contra o da fonte. Regra nova de réguas
  precisa de replay contra o dado real (várias usinas, várias horas do dia) antes de ir ao ar.
- **Conferência rápida no servidor:** `/versao` (commit no ar), `/healthz` (fuso), `/api/macro` (rollup),
  `/api/entrada/tempo-real` (cards), `/api/trk/regua/diff?fonte=pg&max=1` (régua de trackers ligada) e
  `/api/ronda/whats/status` (ronda; só no PC local).
