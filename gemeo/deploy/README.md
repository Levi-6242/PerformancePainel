<!-- gemeo/deploy/README.md -->
# Deploy do Gêmeo Digital (servidor Windows da T.I.)

O gêmeo é um serviço separado da plataforma: pasta própria, banco próprio, três tarefas agendadas, porta **5070**
em `127.0.0.1`. Quem usa chega por **`/gemeo/` na plataforma** (proxy no `app.py` dela, mesmo túnel e mesmo login).

## 1. Pré-requisitos

- Python 3.12+ (caminho real do `pythonw.exe`, não o alias da Microsoft Store).
- **PostgreSQL 16** local: banco `gemeo`, usuário `gemeo` com `CREATE` no banco (o gêmeo cria o schema `gemeo`).
- Acesso de rede: `44.214.183.214:5432` (PostgreSQL `powerplants` do Thopen), `gridco-api.sunop.net` e
  `axis-api.sunop.net` (API SunOp), `app.gridco.com.br` (API BD_Performance).
- Pasta de segredos **fora de qualquer pasta sincronizada** (OneDrive), por exemplo `C:\gemeo-secrets`.

## 2. Instalar

```
git clone <repositório> C:\gemeo        # ou copiar a pasta gemeo/ deste repositório
cd C:\gemeo
python -m pip install -e ".[dev]"
```

`C:\gemeo-secrets\gemeo.env` (uma chave por linha, sem aspas):

```
GEMEO_DB_DSN=postgresql://gemeo:<senha>@127.0.0.1:5432/gemeo
POWERPLANTS_DSN=postgresql://<usuario>:<senha>@44.214.183.214:5432/powerplants
SUNOP_API_TOKEN=<token de API da SunOp — o de /data, validade ~1 ano; NÃO o token web de 7 dias>
GRIDCO_SQL_TOKEN=<mesmo do tokens.txt da plataforma>
GEMEO_SENHA=<senha compartilhada das telas — a MESMA vai no tokens.txt da plataforma>
```

`config.toml` (versionado): usinas do piloto, ritmos, teto da SunOp (600/dia), porta.

## 3. Primeira carga

```
set SECRETS_DIR=C:\gemeo-secrets
gemeo migrate                       # cria o schema gemeo
gemeo inspecionar-cadastro          # imprime os headers das abas do BD_Performance (Info Geral / Info Mensal / BD_Trackers)
gemeo importar-alias ..\docs\de-para-trackers-supervisorio-fracttal.xlsx
gemeo ingest                        # deixa rodando alguns minutos e encerre com Ctrl+C: cadastro + primeiras leituras
gemeo modelar                       # últimos 3 dias; imprime um JSON por usina
gemeo app                           # http://127.0.0.1:5070/gemeo/  (login = GEMEO_SENHA)
```

Se `inspecionar-cadastro` mostrar headers diferentes dos esperados pelo `ingest/cadastro.py`, ajuste o de-para de
colunas lá antes de seguir (pendência conhecida: Info Geral / Info Mensal / BD_Trackers ainda não foram lidas ao vivo).

## 4. Tarefas agendadas e backup

PowerShell **como administrador**:

```
cd C:\gemeo\deploy
.\instalar_tarefas.ps1 -Raiz "C:\gemeo" -Python "C:\Python312\pythonw.exe" -SecretsDir "C:\gemeo-secrets"
Start-ScheduledTask "Gemeo Ingest"; Start-ScheduledTask "Gemeo App"; Start-ScheduledTask "Gemeo Modelar"
```

Logs em `C:\gemeo\logs\{ingest,modelar,app}.log`. Backup diário (agende às 02:00 na mesma máquina):

```
$env:GEMEO_DB_DSN = "<mesmo DSN do gemeo.env>"; .\backup.ps1 -Destino "D:\Backups\gemeo" -PgDump "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe"
```

## 5. Ligar na plataforma

No `tokens.txt` da plataforma acrescente `GEMEO_SENHA=<a mesma do gemeo.env>` (e `GEMEO_URL=http://127.0.0.1:5070` se
mudar a porta). **Reinicie a plataforma** — o proxy `/gemeo/*` só existe no processo novo. A entrada "Gêmeo Digital"
do menu aparece sozinha quando `/gemeo/healthz` passa a responder.

## 6. Saúde

`GET http://127.0.0.1:5070/gemeo/healthz` (ou `/gemeo/healthz` pela plataforma): 200 = tudo ok; 503 = há problema, e o
JSON diz qual (fonte parada, `modelar` atrasado, SunOp no teto, token da SunOp vencendo em < 30 dias, banco fora).
Aponte o monitor externo (Teams) para essa URL.

## 7. Atualizar

`git pull` → `gemeo migrate` → reiniciar as três tarefas (`Stop-ScheduledTask`/`Start-ScheduledTask`). Zip da pasta só
como emergência. Ver `docs/runbook.md` para o resto.
