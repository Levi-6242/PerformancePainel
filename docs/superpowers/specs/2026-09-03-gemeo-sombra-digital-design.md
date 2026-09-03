# Gêmeo Digital — Sombra Digital (Níveis 1–3): desenho

**Data:** 03/09/2026 · **Status:** desenho aprovado seção a seção, aguardando revisão do texto · **Autor:** Levi (com Claude) · **Origem:** handover do Fillipe (Gestão O&M) de 23/08/2026 — `LEIA-ME.md`, documento conceitual R00, plano de migração R00, sondagem Fracttal R00, mockups.

---

## 1. Objetivo

Transformar a Plataforma Performance de dashboard (explica o agora) em gêmeo digital (prevê e prescreve), por degraus. **Esta spec cobre os três primeiros degraus — a Sombra Digital:**

1. **Estrutural** — a usina descrita como dado: hierarquia, atributos, de-para entre sistemas.
2. **Comportamental** — a geração esperada por inversor, calculada por modelo físico (`pvlib`) sobre a irradiância **medida**, gravada ao lado da medida.
3. **Econômico** — o delta esperado × medido decomposto em perdas com nome (inversor parado, tracker fora do alvo, string sem corrente, resíduo), em kWh e, quando houver preço de contrato, em R$.

Com duas telas: **Frota** e **Usina**.

## 2. O que dois spikes provaram (02–03/09/2026)

O desenho não parte de hipótese. Dois testes descartáveis rodaram antes dele:

| | Santarém 1 (fonte PostgreSQL) | MRO100 (fonte SunOp) |
|---|---|---|
| Dado | 14 dias, 5 min, 10 inversores, 450 strings | 14 dias, 898 séries (ETM, 25 inversores, 120 trackers, 450 strings) |
| Modelo | PVWatts genérico, cadastro de placa, zero calibração | idem |
| Resultado | inversores sãos a 0,91–0,97 do esperado; razão diária 0,841 ± 0,036 | inversores sãos a **0,96–1,00**; delta 6,0 % em 10 dias, **71 % com nome**, resíduo **1,8 % do esperado** |
| O que o gêmeo achou sozinho | inversor 106 parado 13 dias; inversor 104 a 0,81 | INV_14 parado 20–27/08, INV_22 parado 28/08–02/09 (a SunOp reportou `InvsParados = 0`); INV_15 a 0,92 |
| O que confirmou a plataforma | — | Trackers 4 e 17, nos mesmos dias; strings sãs nos dois julgamentos |

Seis regras saíram deles e entram aqui como **requisito**, não como opção:

1. O gate de sensor tem **duas portas**: plausibilidade POA × GHI e cobertura. Uma checagem por faixa não pega sensor em falha (Santarém, 02/09: POA leu 0,12 do GHI com os inversores normais — teria acusado excedente de 5,6×).
2. Dia de **calibração** é dia de irradiância estável: em dia de nuvem esparsa o sensor pontual infla contra a área (Santarém 22–24/08, razão 0,75 sem falha).
3. O delta é **horário** e **por inversor** — em 5 min é ruído; no total da usina, falha e calibração se confundem.
4. A referência de tracker fora do alvo é o **ângulo mediano da frota**, não o próprio alvo (Tracker 17: a 0,9° do alvo dele, a 35° da frota — o alvo estava errado).
5. O esperado **tem de ser físico**: os modelos da própria SunOp (`POT.ESP`, `AIML.P`), aprendidos da saída, igualam o medido a 0,99 e não enxergam perda.
6. Foto vazia **nunca sobrescreve** leitura anterior (a lição do `pg_trk` congelado 33 h e do `_sunop_str_med_ent`).

## 3. Decisões

| # | Decisão | Motivo |
|---|---|---|
| D1 | **Projeto separado**, lendo das mesmas fontes | Fonte-agnóstico não se sustenta dentro do `app.py` de 19 mil linhas; os spikes rodaram sem tocar na plataforma |
| D2 | **O gêmeo cria o banco da Fase 4** — conectores próprios, schema próprio | É o "banco no centro" do plano de migração; nasce pelo gêmeo e a plataforma migra para ele por fonte (estrangulador) |
| D3 | O banco é **nosso** — não é o `powerplants` | O usuário `levi.maia` não tem CREATE lá (verificado 03/09); é o servidor da Thopen, 7,4 GB, nove usuários nomeados. `powerplants` é fonte de leitura |
| D4 | **Telas próprias**: os quatro mockups; esta spec entrega Frota e Usina | O produto é o gêmeo; a plataforma lê o banco do gêmeo quando quiser |
| D5 | Arquitetura **B empacotada como A**: um pacote, três pontos de entrada (`ingest`, `modelar`, `app`), que só se falam pelo banco | Isolamento por fonte (o disjuntor da SunOp não trava o modelo), modelo rerodável sobre o histórico, fonte nova = ingestor novo |
| D6 | Modelo físico = **`pvlib`**, PVWatts sobre POA medida, sem transposição | Decidido no conceito; os spikes confirmaram que a POA medida no plano dos módulos dispensa geometria no Nível 2 |
| D7 | **Usinas do piloto**: Santarém 1 e MRO100 (uma por fonte, provadas nos spikes) + as que o time escolher | Decisão 1 da reunião do time ainda aberta; o desenho parametriza |
| D8 | Identidade visual **tokens_grid R00** (navy `#191528`, lime `#A9DB21`) | Já decidido; os mockups seguem |

## 4. Recorte

**Dentro:** Níveis 1–3; telas Frota e Usina; fontes PostgreSQL `powerplants` (Thopen/PG), API SunOp (instância `gridco`; Axis é a mesma classe) e API BD_Performance (cadastro e metas); calibração como job; `/healthz`; CI.

**Fora, cada um com sua spec futura:** Preditivo (Open-Meteo, projeção de contrato — exige um trimestre de calibração), Prescritivo (exige granularidade de causa no Fracttal, que a sondagem mostrou não existir, e preço por contrato), escrita de OS no Fracttal, rota do App Campo, notas de analista, SSO (é a borda Cloudflare Access da Fase 2 do plano), fontes API PV / SolarEdge / 2C (entram como ingestores novos quando as usinas delas forem escolhidas).

## 5. Arquitetura

```
                 ┌────────────────────────── gemeo/ ──────────────────────────┐
fontes           │  ingest (processo longo, 3 laços)      modelar (job 15 min)│      app (waitress)
PostgreSQL ────► │  ┌ pg ──────┐                          ┌──────────────┐    │   ┌──────────────┐
powerplants      │  │ sunop ───┼──► leitura, ingest_run ──► gate         │    │   │ Frota        │
API SunOp ─────► │  │ cadastro ┘    usina, equipamento,    │ esperado     │    │   │ Usina        │
API BD_Perf ───► │  └──────────     alias, meta_mes        │ decomposição │    │   │ /api/frota   │
                 │                                         │ eventos      │    │   │ /api/usina   │
                 │                    PostgreSQL gemeo ◄───┴──────────────┘ ◄──┼───┤ /healthz     │
                 └──────────────────────────────────────────────────────────────┘   └──────────────┘
                 as três peças não se falam; só o banco fala. ingest_run é o contrato.
```

`core/` (schema, config, alias, utilidades de tempo) é o único código compartilhado. `ingest` não importa `modelar`; `modelar` não importa `ingest`; `app` importa apenas `core`.

## 6. Banco — schema `gemeo`

PostgreSQL 16 (instalador oficial), banco `gemeo`. Migrações em SQL puro, versionadas (`migrations/0001_*.sql`), aplicadas por `gemeo migrate`.

**Convenções:** todo `ts` é `timestamptz` em UTC; o fuso da usina fica em `usina.tz` e a conversão é feita na consulta, nunca na gravação. Toda escrita é upsert pela chave natural. Um ciclo que volta vazio grava `ingest_run` com falha e **nenhuma** leitura. Nenhum upsert grava NULL sobre valor existente.

### Cadastro (Nível 1)

```sql
usina        (id, codigo, nome, fonte, fonte_ref, cliente, lat, lon, tz, kwp_dc, kw_ac,
              n_inversores, full_om bool, ativo bool, criado_em)
              -- fonte ∈ {pg, sunop, axis, apipv, solaredge, owen}; fonte_ref = pid/nome na fonte
equipamento  (id, usina_id, tipo, codigo_fonte, nome_exibicao, pai_id, atributos jsonb,
              descoberto_em, ativo bool)
              -- tipo ∈ {inversor, tracker, string, estacao, cabine}
              -- atributos: kwp, kw_ac, n_strings_esperadas, modelo_modulo, gamma, tilt, azimute...
alias        (id, usina_id, equipamento_id, sistema, valor, confianca, origem, criado_em)
              -- sistema ∈ {fracttal, bd_performance, bd_trackers, sunop, apipv, pg}
              -- confianca ∈ {direto, contagem, ordem, limite_skid, manual}
              -- UNIQUE (sistema, valor): um nome num sistema aponta para UM equipamento
```

### Leituras (o estado)

```sql
leitura      (equipamento_id, medida, ts, valor double)  PRIMARY KEY (equipamento_id, medida, ts)
              -- medida ∈ {poa, ghi, temp_modulo, temp_ar, vento, p_ac, e_dia, i_string,
              --           angulo, angulo_alvo, estado}
              -- particionada por mês; índice (equipamento_id, medida, ts desc)
ingest_run   (id, fonte, usina_id, ini, fim, status, n_linhas, n_requisicoes, duracao_s,
              cobertura numeric, erro text, criado_em)
              -- status ∈ {ok, parcial, falha}; cobertura = linhas obtidas / esperadas na janela
```

### Modelo (Níveis 2 e 3)

```sql
modelo       (id, usina_id, versao, parametros jsonb, tolerancia numeric, calibrado bool,
              calibrado_em, metrica jsonb, ativo bool, criado_em)
              -- parametros: pac0_kw, gamma, perdas_fixas, eta_inv, gate{...}; metrica: razao_media, desvio, n_dias
esperado     (equipamento_id, ts, p_esperado_kw, poa_usada, temp_usada, gate, modelo_id)
              PRIMARY KEY (equipamento_id, ts, modelo_id)
              -- gate ∈ {ok, poa_ghi, cobertura, plausibilidade}
cascata_dia  (usina_id, dia, modelo_id, e_esperado, e_medido, delta, inv_parado, tracker,
              string, residuo, cobertura_gate, trackers_sem_inversor int)
              PRIMARY KEY (usina_id, dia, modelo_id)
perda_dia    (equipamento_id, dia, modelo_id, parcela, kwh)
              PRIMARY KEY (equipamento_id, dia, modelo_id, parcela)
              -- parcela ∈ {inv_parado, tracker, string, residuo}
              -- (inversor ABAIXO dos pares não é parcela: é evento; a perda dele fica no resíduo)
evento       (id, usina_id, equipamento_id, tipo, ini, fim, severidade, kwh, detalhe jsonb, modelo_id)
              -- tipo ∈ {inversor_parado, inversor_abaixo, tracker_fora_alvo, string_sem_corrente,
              --         sensor_em_falha, sem_cobertura}
              -- severidade ∈ {leve, media, grave} pelo kWh do evento sobre o esperado do dia da
              -- usina: < 1 % leve, 1–5 % media, > 5 % grave; sensor_em_falha e sem_cobertura são
              -- sempre 'grave' (um dia inteiro sem modelo)
meta_mes     (usina_id, ano, mes, pr_previsto, ipoa_previsto, p50_mwh, disp_alvo, preco_mwh)
              PRIMARY KEY (usina_id, ano, mes)   -- preco_mwh NULL até o contrato chegar
```

**"A usina aparece na tela"** tem definição: existe em `usina` com `ativo`, tem `equipamento` e tem ao menos um `ingest_run` ok nas últimas 24 h. Não é efeito colateral de cache.

**Volume e crescimento.** No formato longo, MRO100 gera ~100 mil linhas/dia. Para as usinas do piloto, PostgreSQL puro. Acima de ~10 usinas, `leitura` vira hypertable TimescaleDB com compressão e retenção — bruto por 90 dias; `cascata_dia`, `perda_dia`, `evento` e `modelo` para sempre. Mesma consulta, outra conexão.

## 7. Conectores (`gemeo ingest`)

Um laço por fonte em thread própria, com disjuntor, ritmo e orçamento próprios. Entregam apenas `leitura` + `ingest_run`. **Não importam código da plataforma** — reaproveitam o conhecimento (pathnames, chaves do `json_data`, parser de metadata), reescrito nos spikes.

| Ingestor | Descobre equipamentos por | Traz | Ritmo |
|---|---|---|---|
| `pg` | `device_id` em `raw_inverter`, `raw_tracker`, `raw_weather_station` (`tb_power_plants` para a usina) | POA, GHI, temperaturas, P por inversor (`active_power`), E do dia, corrente por string (`string_N_current`), ângulos | 15 min, dia e noite |
| `sunop` | `/v2/metadata`, uma vez por dia, guardado em disco (é a chamada mais pesada e a que derruba a borda) | ETM (`POA.IRAD`, `GHI.IRAD`, `PNL.TEMP`, `AR.TEMP`), `INV_n.MEDIDAS.P/EPD/Workstate`, `TRK_n.MEDIDAS.POSAT/POSAL`, `STATUS.WORKSTATE`, `INV_n.MEDIDAS.STR.I_PVk` | ETM + inversores a 15 min; trackers + strings a 60 min com `period=15m` |
| `cadastro` | abas Equipamentos, Info Geral, Info Mensal, BD_Trackers via `/api/sheets/{id}/rows` | `usina`, `equipamento.atributos`, `alias` (bd_performance, bd_trackers), `meta_mes` | 30 min e sob demanda; só rebaixa se `updated_at` do workbook mudou |

**Incremental por marca d'água:** cada ciclo parte de `max(ts)` gravado por (usina, medida) menos 30 min de sobreposição; uma vez por dia rebaixa as 24 h anteriores inteiras (reconciliação). Fusão por timestamp com o valor novo vencendo.

**Cota da SunOp (limite duro):** 100 mil requisições/mês, compartilhadas com a plataforma (que sozinha projeta ~120 mil). Lote de 600 pathnames atravessando usinas (medido equivalente e sem vazamento em 03/09); pausa fora de 05:40–18:20; **teto diário próprio de 600 requisições** que abre o disjuntor. `ingest_run.n_requisicoes` torna o consumo auditável. Estimativa para 9 usinas Athon: ~270 POSTs/dia.

**Regras:** o ingestor não julga — grava cru (o gate é do `modelar`), descartando e contando só valor não numérico. Falha é dado: ciclo vazio → `ingest_run` falha, cobertura 0, nenhuma leitura. 403 da borda SunOp → pausa 90 s e escalada, sem tocar nos outros laços. Equipamento novo na fonte → `equipamento` com `descoberto_em`; `cadastro` enriquece depois.

**Fracttal:** não é ingestor nesta spec. Os `alias` do Fracttal entram pela importação da planilha `docs/de-para-trackers-supervisorio-fracttal.xlsx` (a coluna "Como casou" vira `confianca`) e por edição manual.

## 8. Modelo (`gemeo modelar`)

`modelar(usina, janela, modelo) → esperado, cascata_dia, perda_dia, evento` — função pura do banco, idempotente por (equipamento, ts, modelo). Roda a cada 15 min sobre as últimas 3 h de hoje; roda igual sobre qualquer intervalo.

1. **Grade de 15 min.** Tudo reamostrado nela (a ETM da SunOp vem a ~6 min; trackers e strings a 15).
2. **Gate.** *Plausibilidade:* POA e GHI em [0, 1400]; razão POA/GHI em [0,3; 3] com GHI > 100; no dia, mediana da razão dentro de ±30 % da referência móvel de 30 dias da usina. *Cobertura:* instante exige POA; dia exige ≥ 8 h de instantes válidos. Resultado gravado em `esperado.gate`. Reprovação por sensor → `evento sensor_em_falha`; por cobertura → `evento sem_cobertura`.
3. **Esperado por inversor.** `pvlib.pvsystem.pvwatts_dc(poa, temp_celula, kwp, gamma) × (1 − perdas_fixas)` → `pvlib.inverter.pvwatts(pdc, pac0, eta_inv)`. Temperatura de célula = temperatura de módulo medida; sem ela, temperatura do ar + 0,03·POA. `kwp` e `pac0` de `equipamento.atributos`; `pac0` ausente → inferido do máximo observado em 30 dias e marcado `inferido` em `modelo.parametros`. Versão inicial "placa": γ −0,35 %/°C, perdas 14 %, η 0,96.
4. **Decomposição por inversor e instante.** *Parado:* medido < 1 kW e esperado > 20 kW → delta inteiro em `inv_parado`. Senão: *tracker* = esperado × média, nos trackers do inversor, de `f_direta × (1 − cos(excesso))`, com `excesso = |ângulo − mediana da frota|` só acima de 5°, e `f_direta` de Erbs (`pvlib.irradiance.erbs`) sobre o GHI com a posição solar (lat/lon/tz da usina); ângulo de tracker mudo = último conhecido por até 6 h; *string* = (esperado − tracker) × zeradas ÷ instaladas, instalada = canal com > 1 A nos últimos 30 dias, zerada = < 0,1 A com a mediana do inversor > 0,5 A; *resíduo* = o resto. Tracker sem inversor no `alias` → perda atribuída à usina e contada em `cascata_dia.trackers_sem_inversor`.
5. **Eventos.** `inversor_parado` (≥ 90 % dos instantes diurnos), `inversor_abaixo` (razão < 0,90 da mediana dos pares por 3 dias consecutivos), `tracker_fora_alvo` (excesso > 10° por ≥ 1 h), `string_sem_corrente` (zerada durante toda a janela produtiva do inversor — a régua da plataforma), `sensor_em_falha`, `sem_cobertura`. Severidade pelo kWh; R$ = kWh × `meta_mes.preco_mwh` quando existir.

**Calibração (`gemeo calibrar`).** Seleciona dias limpos — sem `evento` de equipamento, `cobertura_gate` ≥ 0,9, irradiância estável (coeficiente de variação da POA entre 10 h e 14 h abaixo de 0,25 — valor inicial, parâmetro do `config.toml`; os dias 22–24/08 de Santarém, que inflaram o sensor, ficam de fora com ele) — e ajusta `perdas_fixas` até a mediana da razão medido/esperado dos inversores sãos ser 1,0. Grava **versão nova** de `modelo` com `metrica`. `calibrado = true` exige ≥ 30 dias limpos e desvio < 0,03. Até lá: faixa "modelo de placa — não calibrado", `tolerancia` = 0,08; calibrado, `tolerancia` = 0,03 (o valor do mockup). O delta antes da calibração informa; não alarma.

## 9. Telas (`gemeo app`)

Flask + waitress, só leitura, HTML servido pelo servidor com Jinja, sem build. CSS base extraído dos mockups (tokens_grid R00). Biblioteca de gráfico vendorizada em `static/` (sem CDN). Login por senha compartilhada no piloto; SSO na borda (Cloudflare Access), fora do app. Convenções do repositório: pt-BR, cor carrega severidade, contraste antes de paleta, sem emoji (os glifos ● ▲ ✕ dos mockups são símbolos e ficam).

**Frota — "A frota contra a física".** Cinco números: esperado agora, medido agora (último slot completo, só usinas modeladas), Δ da frota, perda de hoje (Σ `perda_dia`; R$ se houver preço), confiança do ciclo (fração das usinas com `esperado.gate = ok` e `ingest_run` fresco). Régua em três faixas: **dentro** (Δ ≤ `tolerancia`), **déficit moderado** (`tolerancia` < Δ ≤ 8 %) e **déficit grave** (Δ > 8 %). Com o modelo calibrado, `tolerancia` = 3 % e as faixas são as do mockup (3–8 %, > 8 %); antes de calibrar, `tolerancia` = 8 % e a faixa moderada fica vazia de propósito — só o déficit grave aparece, porque é o único que o modelo de placa sustenta. Tabela dos maiores déficits ordenada por perda: usina, fonte, esperado, medido, Δ, causa dominante (maior parcela do dia), perda de hoje, status; clique → Usina. **Faixa "não modeladas"** com o motivo de cada usina do cadastro que não está na régua (sem sensor, sem cobertura hoje, sem cadastro).

**Usina — diagnóstico.** Cabeçalho (kWp, inversores, trackers, fonte, versão do modelo, calibrado ou não). Curva do dia esperado × medido a 15 min, **até agora**. Cascata do dia: esperado → inversor parado → trackers → strings → resíduo → medido, kWh e R$. Assinaturas detectadas: `evento` abertos com início e kWh. Tabela por inversor (razão do dia, parcelas, status); trackers e strings expansíveis pelas maiores perdas; estado do sensor do dia (razão POA/GHI, cobertura); `trackers_sem_inversor` visível.

**Frescor:** toda tela mostra a hora do ciclo e, por usina, a idade da última leitura e do último esperado; > 30 min → cinza antes de qualquer outra cor.

**API:** `/api/frota`, `/api/usina/<id>` (JSON das telas), `/healthz`. São a porta pela qual a plataforma passa a ler o gêmeo (estrangulador).

**Acessível pela plataforma (decisão do Levi, 03/09/2026).** O gêmeo continua projeto separado, mas quem usa encontra tudo num lugar só: a plataforma ganha uma entrada de menu **"Gêmeo Digital"** e um proxy `/gemeo/*` → `127.0.0.1:5075` no próprio `app.py` da plataforma, para que as telas do gêmeo saiam pelo mesmo túnel e pelo mesmo login. O gêmeo é servido sob o prefixo `/gemeo` (todas as rotas e assets relativos ao prefixo) e não sabe que está atrás do proxy.

## 10. Operação

- **Repositório:** `Grid-Co-CODE/gemeo`, pacote `gemeo/` com `core/`, `ingest/`, `modelar/`, `app/`, `migrations/`, `tools/`, `tests/`. Nasce fora do OneDrive.
- **Configuração:** `config.toml` (ritmos, tolerâncias, usinas do piloto, teto da SunOp); segredos em `SECRETS_DIR` fora de pasta sincronizada (credenciais do `powerplants`, do banco `gemeo`, token da API SunOp, `GRIDCO_SQL_TOKEN`). Nenhum caminho fixo no código.
- **Servidor:** o mesmo Windows da T.I. que hospeda a plataforma; porta própria (`5075`); PostgreSQL 16 local, banco `gemeo`.
- **Três tarefas agendadas:** `gemeo ingest` (longo, reinício automático), `gemeo modelar` (a cada 15 min, encerra), `gemeo app` (longo). `pythonw` pelo caminho real; scripts `.ps1` em ASCII.
- **Saúde:** `/healthz` por fonte (último ciclo, idade, cobertura, requisições SunOp hoje ÷ teto), último `modelar` e duração, banco alcançável. Monitor externo → Teams. O gêmeo usa o token de **API** da SunOp (o de `/data`, validade de ~1 ano), não o token web de 7 dias; `/healthz` expõe o `exp` do JWT e alarma com 30 dias de antecedência — a troca do segredo é ação humana anual, não renovação automática.
- **Backup:** `pg_dump` diário para a pasta que a T.I. já copia. Insubstituíveis: `modelo` (calibrações) e `alias` manual; o resto se reconstrói das fontes.
- **Deploy:** `git pull` + `gemeo migrate` + reiniciar as três tarefas. Zip como emergência.
- **Gente:** uma segunda pessoa com acesso ao repositório, ao servidor e ao `SECRETS_DIR`, treinada no runbook (`docs/runbook.md` no repositório do gêmeo) — condição do piloto.

## 11. Testes e CI

1. **Modelo** — unitários com dado sintético sobre as invariantes: parcelas somam o delta; parado exclui tracker e string; tracker sem alias vai para a usina; NaN nunca é zero; gate reprova faixa, razão e cobertura.
2. **Golden tests** — recortes reais dos spikes congelados no repositório: Santarém 1 → inversor 106 parado; MRO100 → INV_14/INV_22 parados nos dias certos, trackers 4 e 17, strings zero, resíduo < 3 %. Mudança que altera veredito validado falha.
3. **Ingestores** — fixtures gravadas (metadata e `analog_values` da SunOp; linhas do PG); marca d'água, sobreposição, disjuntor, teto, "vazio grava falha e nada mais". Um teste ao vivo por fonte, marcado, rodado à mão antes de cada release.
4. **Banco** — migrações em schema temporário; upsert-sem-NULL como propriedade.
5. **App** — endpoints sobre banco semeado; render de cada tela.

CI: GitHub Actions com PostgreSQL em container, `pytest -q` a cada PR. **Regra de mudança:** lote, período, gate ou fusão alterados → equivalência com tolerância 1e-6 sobre um dia real (`tools/equivalencia.py`), número no PR. Igualdade exata de float é proibida.

## 12. Critérios de pronto

| Dimensão | Pronto quando |
|---|---|
| Funcional | usinas do piloto modeladas; Frota e Usina no ar; `ingest_run.cobertura` ≥ 0,9 por 7 dias; SunOp abaixo do teto todos os dias |
| Dado | gate ativo; sensor em falha gera `evento`, não delta falso; vereditos dos spikes reproduzidos a partir do banco vivo |
| Honestidade | "modelo de placa — não calibrado" até uma versão calibrada (≥ 30 dias limpos, desvio < 0,03); tolerância 8 % → 3 % só então |
| Operação | as três tarefas sobrevivem a reboot; `pg_dump` diário; `/healthz` monitorado; segunda pessoa com acesso; runbook |
| Aceite | dono técnico do modelo valida o esperado em 5 dias; Fillipe aceita as telas contra os mockups |

Não é critério: R$ (depende do preço por contrato), Preditivo, Prescritivo.

## 13. Riscos e pendências

| Risco / pendência | Mitigação ou dono |
|---|---|
| Cota da SunOp compartilhada — a plataforma já projeta ~120 mil/mês | teto diário do gêmeo; a plataforma passa a ler as curvas do banco do gêmeo (Fase 4), cortando as ~4.000/dia dela |
| PostgreSQL 16 no servidor da T.I. (instalação, porta, backup) | pedido à T.I. junto com o deploy da plataforma; alternativa: instância gerenciada Azure desde o início |
| De-para tracker → inversor incompleto (MRO100: abas BD_Trackers e Equipamentos discordam no skid 2; 62 de 120 sem inversor) | `alias` com `confianca`; `trackers_sem_inversor` visível na tela; correção nas planilhas é do time de Performance |
| ETM sem dado por dias (MRO100, 21–24/08) | `sem_cobertura` como evento; a usina sai da régua com motivo, não desaparece |
| Perda por tracker é aproximação (cosseno sobre fração direta de Erbs, sem geometria) | serve para ordenar e detectar, não para valorar; geometria entra pelo Nível 1 |
| Decisões da reunião do time ainda abertas: usinas do piloto, datasheets/as-builts, preço por contrato, dono técnico do modelo, granularidade do Fracttal | D7 parametriza as usinas; preço e datasheets são colunas nulas até chegarem; dono técnico é critério de aceite |
| Cadastro físico real (Nível 1) inexistente | versão "placa" do modelo é explícita e visível; o Nível 1 melhora a versão, não bloqueia o piloto |

---

*Próximo passo, após revisão deste texto: plano de implementação (`writing-plans`) no repositório `gemeo`.*
