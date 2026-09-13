<!-- gemeo/docs/runbook.md -->
# Runbook — Gêmeo Digital

Para quem opera o gêmeo sem ter escrito o código. Tudo que está aqui pode ser feito pela **segunda pessoa** com acesso ao
servidor, ao repositório e ao `SECRETS_DIR` (condição do piloto, spec §10).

## O que roda

| Tarefa | O que faz | Ritmo | Se cair |
|---|---|---|---|
| `Gemeo Ingest` | um laço por fonte (PostgreSQL `powerplants`, API SunOp, API PV Operation pela conta oem@ — Araputanga, Sete Lagoas e Tupi Paulista da 2C —, API BD_Performance) → `leitura` + `ingest_run` | contínuo | o agendador reinicia em 1 min |
| `Gemeo Modelar` | gate → esperado → decomposição → eventos → cascata dos últimos 3 dias; grava `esperado`, `cascata_dia`, `perda_dia`, `evento` | a cada 15 min, encerra | a próxima execução refaz tudo (idempotente) |
| `Gemeo App` | telas Frota/Usina, API e `/healthz` em `127.0.0.1:5075/gemeo` | contínuo | reinicia em 1 min; a plataforma mostra "fora do ar" (503) enquanto isso |

## Ler o `/healthz`

`problemas: []` e `ok: true` → nada a fazer. Cada linha de `problemas` diz o quê:

- `pg: falha há N min` / `sunop_fino: falha há N min` — a fonte não entregou. Veja `ingest_run.erro` (`SELECT fonte, criado_em, status, erro FROM ingest_run ORDER BY criado_em DESC LIMIT 20`).
  `403` da SunOp = rate limit da borda (CloudFront), o disjuntor já pausa 90 s; se persistir horas, a cota mensal (100 mil/mês, compartilhada com a plataforma) pode ter acabado — `GET https://gridco-api.sunop.net/data/v2/usage/me`.
- `SunOp no teto: 600` — o gêmeo parou de chamar a SunOp por hoje (teto próprio). Volta sozinho à meia-noite UTC. Se acontecer todo dia, revise `config.toml` (`[sunop] teto_dia`) junto com a Performance.
- `modelar há N min` — a tarefa não roda. `Get-ScheduledTaskInfo "Gemeo Modelar"` e `logs\modelar.log`.
- `token SunOp vence em N dias` — troca **humana e anual**: pedir token de API novo à SunOp, colocar em `gemeo.env` (`SUNOP_API_TOKEN`), reiniciar `Gemeo Ingest`.
- `banco: false` — o arquivo SQLite não abre (disco cheio, arquivo movido ou preso por outro processo). Ver `[db] caminho` no `config.toml` e `GEMEO_DB_CAMINHO` no `gemeo.env`; `gemeo migrate` imprime onde ele está.

## A usina sumiu da régua

Ela não some: aparece na faixa **"Não modeladas"** com o motivo. `sem ingestão ok nas últimas 24 h` → fonte; `sensor em falha hoje` → a ETM da usina está mentindo (razão POA/GHI fora da faixa) — evento `sensor_em_falha` na tela da usina; `sem cobertura de sensor hoje` → a ETM não entregou 8 h válidas; `sem esperado calculado hoje` → `modelar` não rodou.

## Refazer um dia

```
set SECRETS_DIR=C:\gemeo-secrets
gemeo modelar --ini 2026-08-31 --fim 2026-08-31 --usina MRO100
```

Datas em dia local da usina. Apaga-e-regrava a janela: rodar duas vezes dá o mesmo resultado.

## Calibrar

Depois de ≥ 30 dias limpos (sem evento, cobertura ≥ 0,9, POA estável):

```
gemeo calibrar --usina MRO100 --dias 45
```

Imprime `calibrado: true/false`. Só a versão calibrada vira ativa (tolerância 3 %); antes disso a versão fica gravada em
`modelo` para inspeção e a placa segue no ar, marcada "modelo de placa — não calibrado".

## Cadastro e de-para

- Usinas, inversores (kWp, kW AC), trackers e metas vêm das abas do BD_Performance pela API; o gêmeo relê a cada 30 min
  quando o `updated_at` do workbook muda.
- Tracker → inversor vem do `alias` (`bd_trackers`). Trackers sem inversor aparecem contados na tela da usina
  (`trackers sem inversor no de-para`) e a perda deles vai para a usina, não para um inversor. Corrigir na planilha
  BD_Trackers/Equipamentos é do time de Performance; depois disso, `gemeo ingest` relê.
- `alias` manual e `modelo` são os únicos dados insubstituíveis: estão no backup diário do arquivo.

## Vitrine: workbook `gemeo_digital` na API da Performance

Ao fim de cada `gemeo modelar`, o gêmeo gera um xlsx com as sete tabelas (cadastro e modelo inteiros; cascata, perdas e eventos
dos últimos 90 dias) e chama `POST /api/workbooks/gemeo_digital/sync-xlsx?replace=true`. É o único caminho da API que grava
cabeçalho (criar aba/linha pela API deixa tudo como "Coluna N"). Precisa do `GRIDCO_SQL_TOKEN`. Falha **não** derruba o
modelo: fica em `estado.publicar.ultimo` e aparece no `/healthz` como `publicar: ...`. Desligar: `[publicar] ativo = false`
no `config.toml`. Não existe DELETE de workbook na API: o nome fica para sempre, então não troque `workbook` à toa.

## Restaurar backup

O backup é uma cópia consistente do arquivo (`backup.ps1`, API de backup do SQLite). Restaurar = parar as três tarefas, copiar o `.sqlite` de volta para o caminho configurado, iniciar de novo.

```
Stop-ScheduledTask "Gemeo Ingest"; Stop-ScheduledTask "Gemeo App"; Stop-ScheduledTask "Gemeo Modelar"
# no modo -SemAdmin a acao e um .vbs: parar a tarefa mata so o wscript e o pythonw fica orfao segurando a porta - mate-o tambem:
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -like '*gemeo.cli*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Copy-Item D:\Backups\gemeo\gemeo_AAAAMMDD_HHMM.sqlite <caminho do gemeo.sqlite>
Start-ScheduledTask "Gemeo Ingest"; Start-ScheduledTask "Gemeo App"; Start-ScheduledTask "Gemeo Modelar"
```

## Mudou lote, período, gate ou fusão?

Rode a régua de equivalência sobre um dia real e cole o número no PR:

```
python -m tools.equivalencia tests\fixtures\golden\mro100_2026-08-31.json --b-razao-min 0.25
```

## Token da PV Plataforma venceu (trackers das três da 2C)

Sintoma: `/healthz` ou `ingest_run` com a fonte `plat` em `falha` e o erro "PV Plataforma recusou o token (HTTP 401): renovar
PV_PLAT_TOKEN_OEM no gemeo.env". Os inversores e a estação das três continuam entrando (fonte `apipv`, que tem login por
senha); só o ângulo dos trackers para, e a parcela de tracker volta para o resíduo até o token novo.

O token da PV Plataforma (`apiplataforma.pvoperation.com`, header `x-auth-token-update`) vale **7 dias** e não tem login por
senha na API para a conta oem@: alguém loga em plataforma.pvoperation.com com a conta oem@, copia o token da sessão (o mesmo
que a plataforma de performance usa em `plat_token.txt`) e cola em `gemeo.env`:

```
PV_PLAT_TOKEN_OEM=<token novo>
```

Reinicie só o ingest (`Gemeo Ingest`: matar o `pythonw -m gemeo.cli ingest` e a tarefa sobe de novo em até 5 min, ou
`Start-ScheduledTask 'Gemeo Ingest'`). O primeiro ciclo depois do token novo puxa 3 dias de gráfico por usina; a marca d'água
dos trackers é a dos próprios trackers, então o buraco do período sem token é coberto até o limite da janela — para mais que
isso, `tools/backfill_apipv.py` não serve (é da fonte apipv); rode um ciclo com `reconciliar` ou peça um backfill de trackers.

## Tracker travado ou sem comunicação

Dois eventos novos (13/09/2026), ambos "ângulo congelado o dia inteiro enquanto a frota se mexe":

- `tracker_travado`: o ângulo é um valor fixo diferente de zero (Sete Lagoas TRK51 em 25,8°). O tracker comunica e não mexe —
  OS de campo. O kWh do evento é a perda do dia pelo cosseno, confiável.
- `tracker_sem_comunicacao`: o ângulo é 0,0 fixo (Araputanga TRK5, aComm=1 na PV Plataforma). Não é ângulo, é sensor mudo —
  checar comunicação/controlador antes de mandar alguém ao tracker. O kWh vem marcado `estimativa: incerta`.

Dia de stow (vento/nuvem, frota toda parada no mesmo ângulo) não gera nenhum dos dois: a amplitude da frota é a guarda.
Se um `.sql` novo aparecer em `migrations/`, rode `python -m gemeo.cli migrate` antes da próxima rodada do modelar — as
tarefas agendadas não aplicam migração.
