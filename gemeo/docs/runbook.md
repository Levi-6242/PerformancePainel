<!-- gemeo/docs/runbook.md -->
# Runbook — Gêmeo Digital

Para quem opera o gêmeo sem ter escrito o código. Tudo que está aqui pode ser feito pela **segunda pessoa** com acesso ao
servidor, ao repositório e ao `SECRETS_DIR` (condição do piloto, spec §10).

## O que roda

| Tarefa | O que faz | Ritmo | Se cair |
|---|---|---|---|
| `Gemeo Ingest` | um laço por fonte (PostgreSQL `powerplants`, API SunOp, API BD_Performance) → `leitura` + `ingest_run` | contínuo | o agendador reinicia em 1 min |
| `Gemeo Modelar` | gate → esperado → decomposição → eventos → cascata dos últimos 3 dias; grava `esperado`, `cascata_dia`, `perda_dia`, `evento` | a cada 15 min, encerra | a próxima execução refaz tudo (idempotente) |
| `Gemeo App` | telas Frota/Usina, API e `/healthz` em `127.0.0.1:5070/gemeo` | contínuo | reinicia em 1 min; a plataforma mostra "fora do ar" (503) enquanto isso |

## Ler o `/healthz`

`problemas: []` e `ok: true` → nada a fazer. Cada linha de `problemas` diz o quê:

- `pg: falha há N min` / `sunop_fino: falha há N min` — a fonte não entregou. Veja `ingest_run.erro` (`SELECT fonte, criado_em, status, erro FROM ingest_run ORDER BY criado_em DESC LIMIT 20`).
  `403` da SunOp = rate limit da borda (CloudFront), o disjuntor já pausa 90 s; se persistir horas, a cota mensal (100 mil/mês, compartilhada com a plataforma) pode ter acabado — `GET https://gridco-api.sunop.net/data/v2/usage/me`.
- `SunOp no teto: 600` — o gêmeo parou de chamar a SunOp por hoje (teto próprio). Volta sozinho à meia-noite UTC. Se acontecer todo dia, revise `config.toml` (`[sunop] teto_dia`) junto com a Performance.
- `modelar há N min` — a tarefa não roda. `Get-ScheduledTaskInfo "Gemeo Modelar"` e `logs\modelar.log`.
- `token SunOp vence em N dias` — troca **humana e anual**: pedir token de API novo à SunOp, colocar em `gemeo.env` (`SUNOP_API_TOKEN`), reiniciar `Gemeo Ingest`.
- `banco: false` — o PostgreSQL onde está o schema não responde. No banco do Thopen (`powerplants`): falar com o DBA; num PostgreSQL próprio: serviço `postgresql-x64-16` no Windows.

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
- `alias` manual e `modelo` são os únicos dados insubstituíveis: estão no backup diário.

## Vitrine: workbook `gemeo_digital` na API da Performance

Ao fim de cada `gemeo modelar`, o gêmeo gera um xlsx com as sete tabelas (cadastro e modelo inteiros; cascata, perdas e eventos
dos últimos 90 dias) e chama `POST /api/workbooks/gemeo_digital/sync-xlsx?replace=true`. É o único caminho da API que grava
cabeçalho (criar aba/linha pela API deixa tudo como "Coluna N"). Precisa do `GRIDCO_SQL_TOKEN`. Falha **não** derruba o
modelo: fica em `estado.publicar.ultimo` e aparece no `/healthz` como `publicar: ...`. Desligar: `[publicar] ativo = false`
no `config.toml`. Não existe DELETE de workbook na API: o nome fica para sempre, então não troque `workbook` à toa.

## Restaurar backup

O dump tem só o schema do gêmeo (`backup.ps1 -Schema`), então restaurar não toca no resto do banco.

```
pg_restore --clean --if-exists --no-owner --dbname=<DSN> D:\Backups\gemeo\gemeo_AAAAMMDD_HHMM.dump
```

## Mudou lote, período, gate ou fusão?

Rode a régua de equivalência sobre um dia real e cole o número no PR:

```
python -m tools.equivalencia tests\fixtures\golden\mro100_2026-08-31.json --b-razao-min 0.25
```
