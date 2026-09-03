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
| A1 | **PostgreSQL 16** para o banco `gemeo` | Instalar no servidor da T.I. (ou instância Azure): banco `gemeo`, usuário `gemeo` com `CREATE` no banco. Sem isso nada roda. |
| A2 | ~~Testes de banco nunca rodaram~~ **Resolvido em 03/09**: a CI do PR #20 rodou os 11 testes de banco (migrações, upsert, job, calibrar, consultas) — 102 passed | Manter a CI verde a cada PR; localmente basta definir `GEMEO_TEST_DSN`. |
| A3 | Segredos `SECRETS_DIR/gemeo.env` | `GEMEO_DB_DSN`, `POWERPLANTS_DSN`, `SUNOP_API_TOKEN`, `GRIDCO_SQL_TOKEN`, `GEMEO_SENHA` (gerar uma senha nova). Pasta fora do OneDrive. Modelo em `deploy/README.md`. |
| A4 | **Token de API da SunOp** (o de `/data`, validade ~1 ano) | Pedir à SunOp. A plataforma usa o token web de 7 dias, que não serve para um serviço contínuo. O `/healthz` alarma 30 dias antes de vencer; a troca é humana e anual. |
| A5 | Rede do servidor | Saída para `44.214.183.214:5432` (PostgreSQL `powerplants`), `gridco-api.sunop.net`, `axis-api.sunop.net`, `app.gridco.com.br`. |
| A6 | Tarefas agendadas, backup e monitor | `deploy/instalar_tarefas.ps1` (3 tarefas), `deploy/backup.ps1` agendado (pg_dump diário, 14 dias), monitor externo apontando para `/gemeo/healthz` (Teams). |
| A7 | **Reinício da plataforma** para o proxy `/gemeo/*` existir | O `app.py` já tem a rota, mas o processo no ar não foi reiniciado (de propósito). No `tokens.txt`: `GEMEO_SENHA=<mesma do gemeo.env>`; reiniciar no próximo horário da T.I. Até lá a entrada "Gêmeo Digital" do menu fica escondida (só aparece quando `/gemeo/healthz` responde). |
| A8 | Repositório `Grid-Co-CODE/gemeo` | Criar (Levi/T.I.). O pacote `gemeo/` é autocontido; levar junto `.github/workflows/gemeo-ci.yml` (hoje na raiz deste repositório). |
| A9 | ~~Merge do PR #20~~ **Resolvido em 03/09**: mesclado na `main` (commit `0c588cf`, 22 commits, CI verde) | Nada a fazer. A `main` é a referência para o deploy: `git pull` no servidor traz o gêmeo e o proxy. |
| A10 | Segunda pessoa com acesso | Repositório, servidor e `SECRETS_DIR`, treinada em `docs/runbook.md` — condição do piloto (spec §10). |

## B. Dado e cadastro (Performance)

| # | Pendência | O que é preciso |
|---|---|---|
| B1 | Abas **Info Geral, Info Mensal e BD_Trackers** nunca foram lidas ao vivo pelo gêmeo | Rodar `gemeo inspecionar-cadastro` no servidor e ajustar o de-para de colunas em `ingest/cadastro.py` se os headers diferirem. Só a aba Equipamentos foi validada nos spikes. Sem isso: sem `meta_mes`, sem lat/lon, sem `alias` de trackers pelo cadastro. |
| B2 | De-para tracker → inversor incompleto na MRO100 (62 de 120 sem inversor: BD_Trackers e Equipamentos discordam no skid 2) | Corrigir nas planilhas (time de Performance). No gêmeo isso aparece como `trackers sem inversor no de-para` na tela da usina; a perda desses trackers vai para a usina, não para um inversor. |
| B3 | Latitude/longitude por usina | Vem da Info Geral (B1). Sem coordenadas a fração direta da irradiância usa 0,6 fixo, e a perda por tracker fica mais grosseira. |
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
| C7 | Volume de `esperado` (3 dias × 96 slots × inversores a cada 15 min) | Ok para o piloto; acima de ~10 usinas, `leitura` e `esperado` viram hypertable TimescaleDB (spec §6). |

## D. SunOp

| # | Pendência | O que é preciso |
|---|---|---|
| D1 | Cota mensal compartilhada (100 mil req) — a plataforma sozinha projeta ~120 mil | Gêmeo com teto próprio de 600/dia (~18 mil/mês). A **Fase 4** (plataforma ler curvas do banco do gêmeo e cortar as ~4.000/dia dela) não está feita — é o próximo projeto. |
| D2 | `/v2/metadata` das 10 usinas num processo novo derruba a borda (403) | O ingestor guarda o metadata em disco (`cache/`); na primeira subida, se der 403, rodar uma usina de cada vez. |
| D3 | Consumo real do gêmeo nunca medido ao vivo | `ingest_run.n_requisicoes` e `/healthz` (`sunop.requisicoes_hoje`) tornam isso auditável desde o primeiro dia. |

## E. Plataforma (efeitos colaterais, todos controlados)

| # | Pendência | O que é preciso |
|---|---|---|
| E1 | `plataforma/app.py` ganhou a rota `gemeo_proxy` (após `logout`) — o processo no ar não a tem | Reinício pela T.I. (A7). Hoje `/gemeo/healthz` na 5050 devolve 302 (login) / 404. |
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

## O que foi verificado de fato

- `cd gemeo && python -m pytest -q` → 91 passed, 11 skipped (banco).
- `python -m tools.equivalencia tests/fixtures/golden/mro100_2026-08-31.json` → `"equivalente": true`.
- `python -m pytest tests/test_gemeo_proxy.py -q` (raiz) → 4 passed.
- CI do PR #20 (`gemeo-ci`, PostgreSQL 16 em container) → **102 passed** (run 33752954156).
- Telas Frota e Usina renderizadas com dados fixos e conferidas no navegador (identidade tokens_grid R00).
- Depois de tudo: `5050 /healthz → 200`, `5080 → 200`, dois `cloudflared` vivos, `tunnel_url.txt` inalterado.
- **Não verificado:** as três tarefas agendadas e o backup em um Windows real; o proxy no processo da plataforma (só no cliente de teste); o cadastro ao vivo (B1).
