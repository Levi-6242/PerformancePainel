<!-- gemeo/deploy/README.md -->
# Deploy do Gêmeo Digital (servidor Windows da T.I.)

O gêmeo é um serviço separado da plataforma: pasta própria, **banco próprio em um arquivo SQLite** (sem servidor,
sem DBA), três tarefas agendadas, porta **5075** em `127.0.0.1`. Quem usa chega por **`/gemeo/` na plataforma**
(proxy no `app.py` dela, mesmo túnel e mesmo login).

## 1. Pré-requisitos

- Python 3.12+ (caminho real do `pythonw.exe`, não o alias da Microsoft Store).
- Acesso de rede: `gridco-api.sunop.net` e `axis-api.sunop.net` (API SunOp), `app.gridco.com.br` (API BD_Performance);
  `44.214.183.214:5432` (PostgreSQL `powerplants` do Thopen) só se houver usina de fonte `pg` no piloto.
- Pasta de segredos **fora de qualquer pasta sincronizada** (OneDrive), por exemplo `C:\gemeo-secrets`.
- **Banco:** nada a instalar. O SQLite vem com o Python. O arquivo nasce no primeiro `gemeo migrate`, em
  `%LOCALAPPDATA%\GridCo\gemeo\gemeo.sqlite` (padrão) ou no caminho de `[db] caminho` do `config.toml` /
  `GEMEO_DB_CAMINHO` do `gemeo.env`. **Nunca dentro do OneDrive**: sincronização + SQLite = lock preso e arquivo pela
  metade. Na pasta do repositório só se ela não for sincronizada.

## 2. Instalar

```
git clone <repositório> C:\gemeo        # ou copiar a pasta gemeo/ deste repositório
cd C:\gemeo
python -m pip install -e ".[dev]"
```

`C:\gemeo-secrets\gemeo.env` (uma chave por linha, sem aspas):

```
SUNOP_API_TOKEN=<token de API da SunOp — o de /data, validade ~1 ano; NÃO o token web de 7 dias>
GRIDCO_SQL_TOKEN=<mesmo do tokens.txt da plataforma>
GEMEO_SENHA=<senha compartilhada das telas — a MESMA vai no tokens.txt da plataforma>
GEMEO_DB_CAMINHO=D:\gemeo-dados\gemeo.sqlite      # opcional; sem esta linha vale o padrão em %LOCALAPPDATA%
POWERPLANTS_DSN=host=44.214.183.214 port=5432 dbname=powerplants user=... password=...   # só com usina de fonte pg
```

`config.toml` (versionado): usinas do piloto (só as com relação tracker × inversor), ritmos, teto da SunOp (600/dia),
porta, `[db] caminho`, `[publicar]`.

## 3. Primeira carga

```
set SECRETS_DIR=C:\gemeo-secrets
gemeo migrate                       # cria o arquivo e as tabelas; imprime onde ficou
gemeo inspecionar-cadastro          # imprime os headers das abas do BD_Performance (Info Geral / Info Mensal / BD_Trackers)
gemeo importar-alias ..\docs\de-para-trackers-supervisorio-fracttal.xlsx
gemeo ingest                        # deixa rodando alguns minutos e encerre com Ctrl+C: cadastro + primeiras leituras
gemeo modelar                       # últimos 3 dias; imprime um JSON por usina e, ao fim, sincroniza o workbook
                                    # gemeo_digital da API da Performance ([publicar] no config.toml; usa o GRIDCO_SQL_TOKEN)
gemeo app                           # http://127.0.0.1:5075/gemeo/  (login = GEMEO_SENHA)
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

Num **PC de uso, sem administrador** (o caso do PC do Levi em 03/09/2026): acrescente `-SemAdmin`. As tarefas sobem no
logon do usuário e um gatilho de 5 min faz de guardião (se já está rodando, o Windows ignora; se morreu, sobe de novo) —
é o que sobrevive a um logoff, que mata tudo que foi iniciado à mão. A ação passa por um `.vbs` para não piscar console,
e os wrappers usam o caminho 8.3 da pasta quando ela tem acento (`Área de Trabalho` vira `READET~1`): `.cmd` é ASCII.

```
.\instalar_tarefas.ps1 -Python "<pythonw.exe real>" -SecretsDir "C:\Users\<voce>\gemeo-secrets" -SemAdmin
```

Para remover: `Unregister-ScheduledTask "Gemeo Ingest","Gemeo App","Gemeo Modelar" -Confirm:$false`.

**Armadilha real (03/09/2026, PC do Levi): `%LOCALAPPDATA%` não é o mesmo arquivo para todo mundo.** O app Claude
(desktop) é um pacote MSIX e o Windows *virtualiza* `AppData\Local` para tudo que nasce dentro dele — inclusive os
shells do Claude Code. O `gemeo.sqlite` gravado o dia inteiro por processos subidos dali foi parar em
`AppData\Local\Packages\Claude_<id>\LocalCache\Local\GridCo\gemeo\`, enquanto as tarefas agendadas (fora do pacote)
abriam um arquivo VAZIO no caminho "real" — `no such table: usina` com o banco de 29 MB intacto do outro lado. O mesmo
vale para o `py` da Microsoft Store (pacote PythonManager, com o seu próprio cache). Regra: **num PC assim, `-Banco` e
`GEMEO_DB_CAMINHO` apontam para fora de `AppData`** (aqui: `C:\GridcoAuto\gemeo\gemeo.sqlite`); no servidor da T.I.,
sem app empacotado, o padrão em `%LOCALAPPDATA%` serve.

Logs em `C:\gemeo\logs\{ingest,modelar,app}.log`. Backup diário (agende às 02:00 na mesma máquina) — cópia consistente
do arquivo pela API de backup do próprio SQLite, 14 dias de retenção:

```
.\backup.ps1 -Destino "D:\Backups\gemeo" -Banco "<caminho do gemeo.sqlite>" -Python "C:\Python312\python.exe"
```

## 5. Ligar na plataforma

No `tokens.txt` da plataforma acrescente `GEMEO_SENHA=<a mesma do gemeo.env>` e `GEMEO_URL=http://127.0.0.1:5075`.
**Reinicie a plataforma** — o proxy `/gemeo/*` só existe no processo novo. A entrada "Gêmeo Digital" do menu aparece
sozinha quando `/gemeo/healthz` passa a responder.

## 6. Saúde

`GET http://127.0.0.1:5075/gemeo/healthz` (ou `/gemeo/healthz` pela plataforma): 200 = tudo ok; 503 = há problema, e o
JSON diz qual (fonte parada, `modelar` atrasado, SunOp no teto, token da SunOp vencendo em < 30 dias, banco fora,
publicação no workbook da Performance falhando). Aponte o monitor externo (Teams) para essa URL.

## 7. Atualizar

`git pull` → `gemeo migrate` → reiniciar as três tarefas (`Stop-ScheduledTask`/`Start-ScheduledTask`). Zip da pasta só
como emergência. Ver `docs/runbook.md` para o resto.
