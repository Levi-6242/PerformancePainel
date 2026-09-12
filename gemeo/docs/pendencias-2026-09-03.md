# Pendências do Gêmeo Digital — fechamento da execução do plano (03/09/2026)

As 21 tarefas do plano (`docs/superpowers/plans/2026-09-03-gemeo-sombra-digital.md`) foram executadas nesta
sessão, na pasta `gemeo/` deste repositório, com um commit por tarefa no branch `feat/sunop-bases-api-gemeo-spec`
(PR #20; o #19, da spec, foi mesclado). Suíte do gêmeo: **91 passando e 11 pulados nesta máquina** (sem PostgreSQL) e
**102 passando na CI do PR #20**, com PostgreSQL 16 em container — a CI achou, e a sessão corrigiu, dois defeitos que só o
banco revela (`df.eq` em `grade.py`, que colidia com o método do DataFrame, e `NaN` dentro de JSON de evento). Nada do que está no ar (plataforma 5050, worker, Thopen 5080, `cloudflared`, tarefas agendadas)
foi reiniciado ou reconfigurado.

Cada item abaixo diz **o que falta** e **o que é preciso** para resolver.

## A. O que bloqueia o piloto subir (infra e acessos — T.I. / Levi)

| # | Pendência | O que é preciso |
|---|---|---|
| A1 | ~~Schema no PostgreSQL existente~~ **Resolvido em 03/09 (tarde)**: a pedido do Levi (\"para não termos que depender dele\"), o gêmeo passou a usar **SQLite embutido** — um arquivo fora do OneDrive (`%LOCALAPPDATA%\GridCo\gemeo\gemeo.sqlite` ou `[db] caminho`). Sem servidor, sem schema, sem DBA. Os 13 testes de banco que só rodavam na CI passaram a rodar em qualquer máquina | Nada a pedir ao DBA; o pedido do schema `digital_twins` pode ser cancelado. `psycopg2` continua só para LER o `powerplants` do Thopen quando houver usina de fonte `pg`. |
| A2 | ~~Testes de banco nunca rodaram~~ **Resolvido em 03/09**: a CI do PR #20 rodou os 11 testes de banco (migrações, upsert, job, calibrar, consultas) — 102 passed | Manter a CI verde a cada PR; localmente basta definir `GEMEO_TEST_DSN`. |
| A3 | Segredos `SECRETS_DIR/gemeo.env` | Obrigatórios: `SUNOP_API_TOKEN`, `GRIDCO_SQL_TOKEN`, `GEMEO_SENHA`. Opcionais: `GEMEO_DB_CAMINHO` (caminho do SQLite) e `POWERPLANTS_DSN` (só com usina de fonte pg). Já criado nesta máquina em `C:\Users\Levi Maia\gemeo-secrets\gemeo.env`. Modelo em `deploy/README.md`. |
| A4 | **Token de API da SunOp** (o de `/data`, validade ~1 ano) | Pedir à SunOp. A plataforma usa o token web de 7 dias, que não serve para um serviço contínuo. O `/healthz` alarma 30 dias antes de vencer; a troca é humana e anual. |
| A5 | Rede do servidor | Saída para `44.214.183.214:5432` (PostgreSQL `powerplants`), `gridco-api.sunop.net`, `axis-api.sunop.net`, `app.gridco.com.br`. |
| A6 | Tarefas agendadas, backup e monitor | `deploy/instalar_tarefas.ps1` (3 tarefas), `deploy/backup.ps1` agendado (cópia consistente do arquivo SQLite, diária, 14 dias), monitor externo apontando para `/gemeo/healthz` (Teams). |
| A7 | ~~Reinício da plataforma~~ **Resolvido em 03/09 (tarde)**: plataforma reiniciada duas vezes pelo ritual (12:43 e 16:55), com `GEMEO_SENHA` e `GEMEO_URL=http://127.0.0.1:5075` no `tokens.txt`; `/gemeo/*` chega ao gêmeo pela plataforma (mesmo login e túnel) | Nada a fazer aqui. No servidor da T.I. vale o mesmo: `tokens.txt` + reinício. |
| A8 | Repositório `Grid-Co-CODE/gemeo` | Criar (Levi/T.I.). O pacote `gemeo/` é autocontido; levar junto `.github/workflows/gemeo-ci.yml` (hoje na raiz deste repositório). |
| A9 | ~~Merge do PR #20~~ **Resolvido em 03/09**: mesclado na `main` (commit `0c588cf`, 22 commits, CI verde) | Nada a fazer. A `main` é a referência para o deploy: `git pull` no servidor traz o gêmeo e o proxy. |
| A10 | Segunda pessoa com acesso | Repositório, servidor e `SECRETS_DIR`, treinada em `docs/runbook.md` — condição do piloto (spec §10). |

## B. Dado e cadastro (Performance)

| # | Pendência | O que é preciso |
|---|---|---|
| B1 | ~~Abas nunca lidas ao vivo~~ **Parcial**: o cadastro lê ao vivo **Equipamentos, Info Geral (kWp total, inversores, trackers, cliente) e BD_Trackers (tracker → inversor)**. Falta **Info Mensal** (metas: PR, IPOA, P50 por mês) | Implementar `separar_info_mensal` no `ingest/cadastro.py` com os headers da aba (`gemeo inspecionar-cadastro`) para preencher `meta_mes`. |
| B2 | ~~De-para tracker → inversor incompleto~~ **Quase resolvido**: pela BD_Trackers, CPP100 63/63, MAB100 150/150, MRO100 119/120 (271 casam direto, 61 pela ordem "Inversor c.n → INV_n"). Só o "Inversor 2.28" da MRO100 não existe | **MTS100: 0/52** — a planilha nomeia os trackers `SKC_n` e sem inversor; a SunOp tem `TRK_1..52`. Corrigir a aba BD_Trackers da MTS100 (Performance). |
| B3 | Latitude/longitude por usina | A Info Geral **não tem** lat/lon (só Estado e Região). Sem coordenadas a fração direta usa 0,6 fixo. Colocar lat/lon na Info Geral ou no `[usinas.detalhe]` do `config.toml`. |
| B4 | kW AC por inversor | Vem da aba Equipamentos; se faltar, o gêmeo infere `pac0` do máximo observado em 30 dias e marca (`inferidos` no JSON do `modelar`). |
| B5 | Preço por contrato (`meta_mes.preco_mwh`) | Nulo até o contrato chegar: as telas mostram perda em MWh, sem R$. |
| B6 | De-para trackers supervisório ↔ Fracttal com 8 usinas pendentes (planilha `docs/de-para-trackers-supervisorio-fracttal.xlsx`) | Completar a planilha; `gemeo importar-alias` grava como `alias` com `confianca`. |

## C. Modelo (honestidade do número)

| # | Pendência | O que é preciso |
|---|---|---|
| C1 | Modelo **de placa, não calibrado** (γ −0,35 %/°C, perdas 14 %, η 0,96; tolerância 8 %) | ≥ 30 dias limpos por usina e desvio < 0,03 → `gemeo calibrar --usina X` grava versão calibrada e a tolerância vai a 3 %. Até lá a faixa "moderado" da régua fica vazia de propósito. |
| C2 | Vereditos golden ajustados durante a execução (documentados no campo `nota` das fixtures) | 26/08 da MRO100: sem trackers (o spike registrou 0,1 kWh) e resíduo < 5 % (spike: 3,76 %); Santarém: razão dos sãos ≥ 0,85, porque o spike limitava o AC em 0,96 × placa (corrigido na Tarefa 13). Vale revisar com o dono técnico do modelo. |
| C3 | `inversor_abaixo` é recomputado dos últimos 3 dias; o evento aberto anterior é apagado a cada rodada | Não há histórico de fechamento desse evento. Se fizer falta, gravar o fechamento em vez de apagar (job.persistir). |
| C4 | Perda por tracker é aproximação (cosseno × fração direta de Erbs, sem geometria) | Serve para ordenar e detectar, não para valorar. Geometria entra pelo Nível 1 (cadastro físico), fora do piloto. |
| C5 | Tracker mudo há mais de 6 h vira dado ausente (não perda) | Regra da spec; conferir com a Performance se 6 h é o limite certo. |
| C6 | Universo de strings instaladas vem dos últimos 30 dias de leitura | Nos primeiros 30 dias de uma usina nova o universo é só a janela carregada (string morta o tempo todo não aparece). |
| C7 | Volume: `leitura` tem ~70 mil linhas/dia por usina como a MRO100 (a MTS100, com 522 trackers, mais que isso), agora em SQLite | Ok para as 4 usinas do piloto com retenção de 90 dias (alguns GB). Acima de ~10 usinas, medir; a saída é particionar por mês em arquivos ou voltar a um servidor. |

## D. SunOp

| # | Pendência | O que é preciso |
|---|---|---|
| D1 | Cota mensal compartilhada (100 mil req) — a plataforma sozinha projeta ~120 mil | Gêmeo com teto próprio de 600/dia (~18 mil/mês). A **Fase 4** (plataforma ler curvas do banco do gêmeo e cortar as ~4.000/dia dela) não está feita — é o próximo projeto. |
| D2 | `/v2/metadata` das 10 usinas num processo novo derruba a borda (403) | O ingestor guarda o metadata em disco (`cache/`); na primeira subida, se der 403, rodar uma usina de cada vez. |
| D3 | Consumo real do gêmeo nunca medido ao vivo | `ingest_run.n_requisicoes` e `/healthz` (`sunop.requisicoes_hoje`) tornam isso auditável desde o primeiro dia. |

## E. Plataforma (efeitos colaterais, todos controlados)

| # | Pendência | O que é preciso |
|---|---|---|
| E1 | ~~Processo no ar sem a rota~~ **Resolvido em 03/09 (tarde)**: reiniciado; `/gemeo/healthz`, `/gemeo/` e `/gemeo/api/frota` respondem pela plataforma (logado) | A entrada "Gêmeo Digital" do menu aparece sozinha (o `fetch` acha o `/gemeo/healthz`). |
| E2 | `docs/redesign/Monitoramento (novo design).html` (relido a cada requisição) ganhou o link escondido e um `fetch('/gemeo/healthz')` por carga de página | Inofensivo até o proxy existir (404 = fica escondido). Foi o único arquivo "ao vivo" tocado. |
| E3 | Links do gêmeo são absolutos (`/gemeo/...`) | Se a plataforma rodar atrás de prefixo (`_prefixo()`), os links quebram — tratar quando/se houver prefixo. |
| E4 | Só `tests/test_gemeo_proxy.py` (4 testes) foi rodado da suíte da raiz nesta rodada | Rodar `python -m pytest -q` na raiz antes do merge. |
| E5 | `plataforma/deploy/README.md` ganhou a seção 12 (Gêmeo) | Nada a fazer; é documentação para a T.I. |

## F. Herdado da sessão (fora do gêmeo)

| # | Pendência | O que é preciso |
|---|---|---|
| F1 | `PLAT_TOKEN` (API PV Operation) vence a cada 7 dias | Renovação manual (`POST /api/pv/trackers/token`); `GET /api/tokens` mostra os dias. |
| F2 | Workbooks `zz_teste_claude_apagar`, `plataforma_estado`, `plataforma_series` na API BD_Performance | Apagar (Levi). |
| F3 | `plataforma/deploy/oem-app.zip` contém `tokens.txt` | Entregar à T.I. por canal seguro; nunca por e-mail aberto. |
| F4 | Fixtures golden no repositório (~3,3 MB em 4 arquivos) | Aceitável; se pesar, mover para Git LFS quando o repo `gemeo` nascer. |

## G. Publicação na API SQL da Performance (03/09, tarde)

| # | Pendência | O que é preciso |
|---|---|---|
| G1 | ~~O `modelar` não publica sozinho~~ **Resolvido em 03/09**: `gemeo/modelar/publicar.py` roda ao fim de cada `gemeo modelar` (gera o xlsx, cria o workbook se faltar, `sync-xlsx?replace=true`; falha vai para `estado.publicar.ultimo` e para o `/healthz`, sem derrubar o modelo) | Configurar `[publicar]` no `config.toml` (ativo, workbook, dias); precisa do `GRIDCO_SQL_TOKEN`. O workbook `gemeo_digital` (id 36) hoje tem a carga manual de 01/09; a primeira rodada real substitui tudo (replace). |
| G2 | A API ganhou `/api/raw/*` (customers, power-plants, device-types, devices e ingestão por tipo de equipamento, com fila e "latest") — mesma estrutura das tabelas `raw_*` do Thopen; tudo vazio em 03/09 | É a Fase 4 nascendo do lado da T.I. Decidir com eles quem alimenta: a coleta da plataforma, o gêmeo (que já unifica as três fontes) ou os dois. Sem consulta por período, não substitui o schema do gêmeo. |
| G3 | A API **não tem DELETE de workbook** | Os workbooks `zz_teste_claude_apagar` (id 4), `plataforma_estado` (33) e `plataforma_series` (35) só saem pela T.I. |

| G4 | **Piloto redefinido (03/09, tarde):** só usinas com relação tracker × inversor no BD_Trackers → `MRO100`, `MAB100`, `MTS100`, `CPP100` (Athon/SunOp). TIM100, TIM200, JCD100 e SMP100 têm trackers sem inversor na aba; as usinas do PostgreSQL do Thopen (Ibaté, Santa Bárbara, Aparecida 3, Araçoiaba, Santarém 1 e 2, ...) têm trackers vivos no `raw_tracker` mas nenhuma linha no BD_Trackers. Santarém 1 saiu do piloto | Se quiser Thopen no gêmeo: preencher o BD_Trackers para essas usinas, ou usar a coluna `cabin` do `tb_devices` (tracker → cabine → inversores da cabine), que é um ajuste no modelo. Volume SunOp estimado para as 4 usinas: ~260 requisições/dia, abaixo do teto de 600. |

| G5 | **Porta do gêmeo mudou de 5070 para 5075.** Na máquina do Levi a 5070 é do Painel de Integridade do Coletor (`Painel GridCo.exe`); o proxy da plataforma encaminhava para lá e devolvia o 404 do Painel | Já trocado em `config.toml`, `GEMEO_URL` do `tokens.txt`, padrão do `app.py` e docs. A plataforma no ar (reiniciada às 12:43) ainda tem `GEMEO_URL` 5070 em memória: precisa de mais um reinício quando o gêmeo subir. |

## H. Primeira subida real nesta máquina (03/09, tarde)

O gêmeo está **rodando nesta máquina** com dado real: `gemeo ingest` (SunOp das 4 usinas + cadastro pela API) e `gemeo app` na 5075, processos destacados (não são tarefas agendadas: morrem se a máquina reiniciar). Banco em `%LOCALAPPDATA%\GridCo\gemeo\gemeo.sqlite`. `gemeo modelar` rodado à mão; ainda **não está agendado a cada 15 min** (tarefa agendada só no servidor, via `deploy/instalar_tarefas.ps1`).

| # | Achado | O que é preciso |
|---|---|---|
| H1 | **MTS100 tem GHI sempre 0** (sensor ou tag morta); POA normal (máx. 1.095 W/m²) | O gate não consegue validar POA × GHI nessa usina (roda só com plausibilidade e cobertura). Cobertura passou a usar POA quando o GHI está morto. Ver com a Athon/SunOp o tag `MTS100.ESTM.GHI.IRAD`. |
| H2 | **CPP100 mede 17 % acima do esperado** (01–02/09: 24,9 MWh medidos vs 20,5 esperados) | Ou o kWp da Info Geral (4.910) está baixo, ou a POA lê baixo. Conferir placa e sensor com a Performance antes de confiar na régua dessa usina. |
| H3 | Cobertura dos ciclos SunOp ~50 % (`parcial`) | Os primeiros ciclos (janela de 3 dias num lote só) deram timeout; corrigido (pedaços de 24 h), mas os buracos do passado só entram na reconciliação diária (24 h). Daqui para a frente os ciclos de 15 min cobrem. |
| H4 | Trackers da MTS100 sem leitura de ângulo | Os pathnames existem na SunOp (`MTS100.TRK_n.MEDIDAS.POSAT`); o grupo lento começou hoje. Acompanhar no próximo ciclo; se seguir vazio, olhar o `classificar` para os tags `POSAT_MOT_n`. |
| H5 | Consumo SunOp do gêmeo hoje: 30 requisições até 17:00 (teto 600) | Medido no `/healthz` (`sunop.requisicoes_hoje`). Dentro da estimativa. |
| H6 | O "agora" da Frota perto do pôr do sol dá Δ positivo alto (MRO100 +38 % às 16:58) | Com POA baixa o esperado é pequeno e a razão explode; a régua diária (cascata) é a que vale. Avaliar suavizar o "agora" para a média da última hora. |
| H7 | Reinícios da plataforma (12:43 e 16:55) e do gêmeo por mim | O `.bat` da raiz só sobe o Thopen; app.py e worker.py sobem à mão pelo ritual da memória. Nada do túnel foi tocado. |

## O que foi verificado de fato

- `cd gemeo && python -m pytest -q` → 91 passed, 11 skipped (banco).
- `python -m tools.equivalencia tests/fixtures/golden/mro100_2026-08-31.json` → `"equivalente": true`.
- `python -m pytest tests/test_gemeo_proxy.py -q` (raiz) → 4 passed.
- CI do PR #20 (`gemeo-ci`, PostgreSQL 16 em container) → **102 passed** (run 33752954156).
- Telas Frota e Usina renderizadas com dados fixos e conferidas no navegador (identidade tokens_grid R00).
- Depois de tudo: `5050 /healthz → 200`, `5080 → 200`, dois `cloudflared` vivos, `tunnel_url.txt` inalterado.
- **Não verificado:** as três tarefas agendadas e o backup em um Windows real; o proxy no processo da plataforma (só no cliente de teste); o cadastro ao vivo (B1).

## I. Noite de 03/09 → 04/09: o gêmeo sumiu, o banco "vazio" e as tarefas agendadas

O que aconteceu, em ordem, com a causa de cada coisa:

1. **Ingest, modelar e app morreram entre 22:36 e 23:18** junto com a plataforma (o guardião do túnel registrou "porta
   5050 fechada" às 23:18; o `ronda_guardian.py` religou worker/app às 23:23). Eram processos soltos, subidos à mão —
   **um logoff mata tudo isso**. Resolvido: as três tarefas agendadas do `deploy/instalar_tarefas.ps1` agora existem
   neste PC, no modo novo `-SemAdmin` (sem elevação, sobem no logon, gatilho de 5 min faz de guardião, ação via `.vbs`
   para não piscar console). Ver `deploy/README.md`.
2. **Caminho com acento**: `Set-Content -Encoding Ascii` gravou `?rea de Trabalho` no `.cmd` e a tarefa nem achava a
   pasta. O instalador passou a usar o nome curto 8.3 (`READET~1`) quando o caminho tem algo fora do ASCII.
3. **O banco "sem tabelas"**: as tarefas abriam `%LOCALAPPDATA%\GridCo\gemeo\gemeo.sqlite` e viam um arquivo de 4 KB sem
   schema, enquanto o de 29 MB seguia intacto. Causa: o app Claude é um pacote **MSIX** e o Windows virtualiza
   `AppData\Local` para tudo que nasce dentro dele (os shells do Claude Code inclusive) — o gêmeo escreveu o dia inteiro
   em `AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\GridCo\gemeo\`. O `py` da Store (PythonManager)
   tem outro cache e via um terceiro estado. Resolvido: banco resgatado pela API de backup do SQLite (248.225 leituras,
   integrity ok) para **`C:\GridcoAuto\gemeo\gemeo.sqlite`**, fora de AppData; `GEMEO_DB_CAMINHO` no `gemeo.env` e
   `-Banco` no instalador apontam para lá; conferido que os dois contextos enxergam o mesmo arquivo.
4. **Noite marcada como falha**: fora da janela solar o ingest registrava `ingest_run` 'falha' com "fora da janela solar"
   a cada ciclo e o `/healthz` passava a noite em 503. Resolvido: sem registro fora da janela; a saúde só cobra idade do
   ciclo quando alguma usina está em janela e 'parcial' deixou de ser problema (só 'falha' acusa).

Pendente / a saber:

- **Sobras a apagar quando quiser**: o `gemeo.sqlite` de 4 KB no `%LOCALAPPDATA%\GridCo\gemeo` *real* (só se vê de fora
  do app Claude) e a cópia de 29 MB em `Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\GridCo\gemeo\` (serve de backup
  de 03/09 até lá).
- **Parar o gêmeo no modo -SemAdmin** exige matar o `pythonw` além de `Stop-ScheduledTask` (o .vbs morre, o Python fica
  órfão segurando a porta). Está no runbook.
- **`logs/*.log` crescem sem rotação** (o wrapper faz `>>`). Aceitável por semanas; não por meses.
- **Regra geral para este PC**: qualquer coisa subida pelo Claude Code que grave em `AppData\Local`/`Roaming` grava no
  cache do pacote, não no lugar que uma tarefa agendada ou o usuário veem. Vale para tudo, não só para o gêmeo.

## J. As 18 usinas do Thopen (PostgreSQL) entraram no piloto — 04/09/2026, à noite

A pedido do Levi. O piloto foi de 4 para 22 usinas. Das 33 do banco `powerplants`, 18 tinham o que o modelo precisa
(inversor + estação com POA + leitura fresca); Ipixuna 1 e 2 têm inversor mas nenhuma estação, e as outras 13 não têm
leitura nenhuma. Elas trazem **placa e coordenadas do próprio `tb_power_plants`**, que as quatro da SunOp ainda não têm
(lá a fração direta cai no valor fixo de 0,6).

Primeira rodada, 3 dias, sem calibração: **11 usinas dentro de 10%** entre esperado e medido (São Bento V em 0,1%,
Santa Bárbara I em 0,5%, Araçoiaba da Serra 2 em 0,6%), 5 entre 10 e 30%, nenhuma fora.

Pendências que nasceram daqui:

- **Santarém 1 e 2 não modelam: o piranômetro de POA está morto**, manda `-999` o dia inteiro (o GHI está bom, 900 a
  1100 W/m²). Ou o sensor é trocado em campo, ou o gêmeo aprende a transpor GHI para o plano dos módulos (o pvlib faz;
  é a mesma conta que a fração direta já usa). Enquanto isso o gate reprova o dia, e está certo em reprovar.
- **Sentinela de sensor virou regra** (`ingest/base.valor_valido`): irradiância abaixo de -20 W/m² é código de erro, não
  medida. Vale para as duas fontes — o Thopen usa `-999`, a SunOp usa `-666` (o GHI da ESTM 1 da MAB100, que a
  plataforma já pinta como erro na aba ETM). Antes disso o -999 entrava como irradiância e a razão POA/GHI da Santarém
  saía -0,46, o que reprovava o dia inteiro por "sensor em falha".
- **Cinco usinas com desvio de 10 a 30%**, para revisar placa ou POA: Aparecida 3 com -26,7%, Santo Inácio XII com
  +21,2%, Aparecida do Taboado 1 com +19,8% e a 2 com +11,9%, Ibaté 1 com -12,0%. A placa vem do campo `capacity` do
  PostgreSQL; vale conferir contra a Info Geral do BD_Performance.
- **Tracker sem inversor**: nenhuma usina do Thopen tem essa relação no BD_Trackers, então a parcela de tracker não é
  atribuída a inversor nenhum. O evento `tracker_fora_alvo` continua saindo, porque só precisa do ângulo e do alvo.
- **Volume**: tracker e corrente de string passaram a ser gravados uma vez a cada 15 min (`GROSSAS` em `ingest/pg.py`),
  a mesma grade do modelo. Sem isso as 18 usinas custariam 17 GB em 90 dias, e 72% disso seria corrente de string a
  cada 5 min. Com a amostragem são cerca de 82 MB por dia, algo como 7 GB no regime de 90 dias. Potência do inversor e
  estação continuam na cadência da fonte: é delas que sai a média de cada bloco.

## 11/09/2026 — fonte `apipv`: as três da 2C pela conta oem@ da API PV Operation

Pedido do Levi depois da visão do Gêmeo ("Comportamento": quanto a usina deveria gerar AGORA e a cascata de perdas em
tempo real): "comece com as usinas da 2C que estão na API PV". Araputanga, Sete Lagoas e Tupi Paulista entraram no piloto
com `gemeo/ingest/apipv.py` (day_inverter/day_meteo de hoje a cada 15 min; dia passado por `custom_query` só quando a
janela cobre o dia). Carimbos da API são horário de Brasília para todas (medido), a estação mente por chave (POA/GHI com a
ordem de campos do coletor e teto de 2000 W/m²), inversor a 5 min, string a 15 min, estação a 1 min. O cadastro passou a
aceitar "Usina Supervisório" vazio (cai para "Usina") e a casar inversor pelo nome de exibição — as 2C só têm
`INVERSOR01..20` no BD_Performance e a API só dá o idefinversor.

Pendências que nasceram daqui:

- **O "agora" do Comportamento ainda não existe**: o gêmeo calcula esperado em blocos de 15 min a cada rodada do
  `modelar`; falta um endpoint/card com esperado × medido do instante (e a cascata do dia até agora) para a plataforma.
- **Trackers das três não entram**: a API PV (apiplataforma) nega trackers para a conta oem@/token gridco; sem eles a
  parcela de tracker vai para o resíduo. Precisa de PLAT_TOKEN da conta oem@ ou de outra fonte.
- **Calibração**: modelo "placa" até haver ≥ 30 dias limpos (a API guarda histórico, mas o `custom_query` de inversor leva
  ~146 s por usina/dia — backfill só fora de pico e em lote pequeno).
- **Ipixuna do Pará** (2C) segue fora: só existe no e-mail.
- **Sete Lagoas** tem nome triplo: "Sete Lagoas" no cadastro (código do gêmeo), "Sete Lagoas 2" no Fracttal e "Sete Lagoa"
  na API — o de-para é por id/código, nunca por nome.
