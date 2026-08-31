# Dashboard O&M — Grid Co. (handover técnico / deploy)

> Documento para **dev/TI**. Não é tutorial passo-a-passo — assume Windows + Python.
> Para arquitetura/decisões em profundidade, ver `docs/arquitetura.md` e `docs/regras-de-negocio.md`.

## O que é
Dashboard web (Flask, monolito) de **Operação & Manutenção de usinas solares fotovoltaicas** da Grid Co. Consolida numa única tela **strings ativas × esperadas, pré-análise ETM (irradiância POA/GHI), geração, trackers e PR por inversor** de **8 fontes/integrações diferentes** (cada uma de um cliente/integrador). Uso **interno** do time de O&M; serve dados a partir de APIs externas, um PostgreSQL externo, e planilhas Excel sincronizadas via OneDrive. Sobe com um único `python app.py`.

## Stack
- **Python: 3.14.6** (versão exata em produção na máquina de origem). Roda também em 3.11–3.13, mas os pins do `requirements.txt` foram verificados no 3.14.6.
- **Servidor web de produção: `waitress` 3.0.2** (WSGI puro-Python, Windows). `python app.py` já sobe via waitress em `0.0.0.0:5050` com `threads=16`. **Comando recomendado: `python app.py`** (não `waitress-serve` — ver "Como rodar").
- **Servidor de dev:** se o `waitress` não estiver instalado, o `app.py` cai no servidor embutido do Flask (`app.run(port=5050, threaded=True)`). É só fallback.
- **`gunicorn` 23.0.0 está no requirements mas NÃO roda no Windows** (usa o módulo `fcntl`, que é POSIX-only). Está ali apenas para o deploy Linux/Railway via `Procfile`. **Em Windows, use waitress.**
- **Dependências de SO: NENHUMA além do Python.** Tudo instala por wheel:
  - `psycopg2-binary` → **libpq embutido** no wheel (não precisa instalar PostgreSQL client/libpq no SO).
  - `numpy`, `pandas`, `matplotlib` → wheels compilados (sem libs de sistema). `matplotlib` usa backend headless (Agg) para gerar PDFs/cards no servidor — não precisa de display.
  - `openpyxl`, `flask`, `flask-compress`, `requests`, `pycognito`, `python-dotenv`, `waitress` → puro-Python.
- **Rede (relevante p/ firewall/security-group):**
  - **Inbound:** TCP **5050** (a porta do dashboard).
  - **Outbound 443 (HTTPS):** `apipv.pvoperation.com.br`, `apiplataforma.pvoperation.com`, `gridco-api.sunop.net`, `axis.sunop.net`, `monitoring.solaredge.com`, `cognito-idp.eu-central-1.amazonaws.com`, `app.fracttal.com`.
  - **Outbound 5432 (TCP):** o PostgreSQL AWS RDS (`PG_HOST`). **O IP do servidor precisa estar no security group do RDS**, senão a aba "Banco de Dados" não conecta.

## Estrutura de pastas
```
app.py                      → Flask principal (monolito, ~7.140 linhas, 84 rotas) — TODO o backend
tracker_watch.py            → módulo importado pelo app.py (issues de trackers; rotas /api/tracker-watch*)
templates/
  index.html                → frontend do dashboard (HTML+CSS+JS inline, Plotly via CDN)
  painel_portfolio.html     → Painel NOC — Monitoramento de Portfólio (rota /painel, consome /api/macro+/api/gerencial)
  painel_usina.html         → Painel NOC — Diagnóstico de Usina (rota /painel/usina/<id>)
static/                     → fonts/ e logos/ (logos cosméticos; 404 com fallback de emoji)
docs/                       → documentação técnica (arquitetura, regras de negócio, APIs)
requirements.txt            → deps de runtime (pins verificados no 3.14.6)
.env.example                → modelo com TODAS as chaves (sem valores) — copiar p/ .env
Iniciar Dashboard.bat        → atalho: instala deps + python app.py
BD_Performance.xlsx         → cadastro mestre (cópia local = fallback auto-suficiente; ver "coleta diária")
ufv_state.json              → estado por UFV ("em manutenção", flags de UI) — config, NÃO regenerável

# Gerados na 1ª execução — NÃO vêm no pacote (o app cria sozinho):
#   cache_snapshot.json (SWR), owen_accum.json (2C), spv_stringbox.json,
#   string_notas.json, sunop_etm_accum.json, tracker_issues.json
# Tokens/segredos — NÃO vêm no pacote (preencher via .env / ver "Variáveis de ambiente"):
#   .env, tokens_runtime.json (tokens que o app renova sozinho),
#   se_credentials.txt, pg_password.txt
# Deliberadamente FORA deste pacote (NÃO usados pelo app.py — entregar à parte se precisar):
#   dashboard_thopen.py / dashboard_geracao.py (apps Flask SEPARADOS, portas próprias 5080/etc),
#   collect_energy.py / coletar_geracao_hoje.py (coletores standalone, não importados),
#   tests/ + conftest.py + pytest.ini + requirements-dev.txt (testes; rodar do repo, não do pacote),
#   Procfile + railway.toml (deploy Linux/Railway), os_creator/ (MIGRADO 28/08 -> Grid-Co-CODE/oem)
```

## Variáveis de ambiente (.env)
Copie `.env.example` → `.env` e preencha. **Tudo é opcional**: cada integração sem credencial só fica "indisponível"; o app sobe igual. Os tokens de sessão são persistidos em `.txt` (auto-renovados quando há semente válida).

| Nome | Função | Sensível | Como obter | Validade/rotação |
|---|---|---|---|---|
| `DASH_PASSWORD` | Senha única do gate de login. Vazio = app aberto (só dev). | Sim | Definida pela equipe | Estática |
| `SECRET_KEY` | Assina o cookie de sessão Flask. | Sim | Gerar aleatória (`secrets.token_hex`) | Estática |
| `PV_USERNAME` / `PV_PASSWORD` | Login da API PV Operation (Thopen). | Sim | Conta apipv | Estática |
| `SUNOP_TOKEN` | Semente JWT SunOp Athon (gridco). Renova sozinho → `tokens_runtime.json` (`sunop`). | Sim | `gridco.sunop.net` → F12 → `localStorage.getItem('token')` | ~7 dias (auto-renova) |
| `AXIS_TOKEN` | Semente JWT SunOp Axis (2ª instância). Renova → `tokens_runtime.json` (`axis`). | Sim | `axis.sunop.net` → F12 → localStorage `token` | ~24 h (auto-renova) |
| `PLAT_TOKEN` | JWT da API PV Plataforma (curva strings/trackers). Ou em `tokens_runtime.json` (`plat`). | Sim | `plataforma.pvoperation.com` → F12 → header `x-auth-token-update` | ~7 dias (**manual**) |
| `PG_HOST` / `PG_PORT` / `PG_DB` / `PG_USER` / `PG_PASSWORD` | PostgreSQL AWS RDS (Thopen). Defaults: PORT 5432, DB `powerplants`. Senha tb aceita em `pg_password.txt`. | Sim (host/user/pass) | Infra Grid Co. | Estática |
| `SE_USERNAME` / `SE_PASSWORD` | Login SolarEdge (Cognito). Ou em `se_credentials.txt`. | Sim | Conta SolarEdge | Estática |
| `SE_COGNITO_CLIENT` / `SE_COGNITO_POOL` | IDs do pool Cognito do SolarEdge. **Têm default no código** (só sobrescrever se mudarem). | Não | SolarEdge | Raro |
| `FRACTTAL_CLIENT_ID` / `FRACTTAL_CLIENT_SECRET` | OAuth2 client_credentials do Fracttal (CMMS / OS). | Sim | Painel Fracttal | Estática |
| `SUNOP_SAMPLE_INTERVAL` | (opcional) intervalo do amostrador ETM SunOp (s). Default 300. | Não | — | — |
| `BD_PERF_PATH` / `BD_THOPEN_PATH` / `TICKETS_PATH` / `OWEN_ROOT` | (opcional) overrides de caminho local p/ as planilhas e a raiz dos CSVs 2C. | Não | — | — |
| `FRACTTAL_BASE_URL` / `FRACTTAL_ID_*` / `FRACTTAL_TOKEN` / `FRACTTAL_LOGIN_JWT` | (opcional) overrides do Fracttal; têm default no código. | Parcial | — | — |

## Como rodar (resumo)
```bash
# 1. venv + deps
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

# 2. configurar
copy .env.example .env   # e preencher

# 3. subir (Windows, produção): isto JÁ usa waitress (0.0.0.0:5050, threads=16)
python app.py
```
- **Use `python app.py`** (não `waitress-serve app:app` nem `gunicorn app:app`). Motivo crítico: as **4 threads de background** (Owen, keep-alive SunOp, prewarm, persist) e o `_cache_load()` só são iniciados no bloco `if __name__ == "__main__"`. Servir via `waitress-serve`/`gunicorn` importa o `app` **sem** rodar esse bloco → o dashboard sobe, mas **sem reaquecimento de cache, sem renovação de token e sem persistência** (toda carga vira fria/lenta e os tokens expiram sem renovar).
- **Por que NÃO gunicorn:** `gunicorn` depende de `fcntl` (POSIX). No Windows ele instala mas **não executa**. Só serve no deploy Linux/Railway (`Procfile`). Em Windows o servidor de produção é o **waitress** (já embutido no `app.py`).
- **Porta:** `5050` está **hardcoded** no `app.py`. Para mudar: editar a chamada `serve(...)` no fim do `app.py` (não há env `PORT` no caminho Windows).
- **Como serviço:** rodar `python app.py` via NSSM/Tarefa Agendada/serviço do Windows apontando para o python do venv. O processo é single-instance e fica em foreground (loga em stdout).

## Integrações externas
| Integração | Base / host | Auth | Observações |
|---|---|---|---|
| **PV Operation** (Thopen, ~142 usinas) | `https://apipv.pvoperation.com.br/api/v1` | `POST /authenticate` {user,pass} → header `x-access-token` | `/api/data` ~65 s na 1ª carga (retries; API instável) |
| **PV Plataforma** (curva strings/trackers) | `https://apiplataforma.pvoperation.com` | header `x-auth-token-update` (JWT manual ~7d) | `idusina` compartilhado com a apipv |
| **PostgreSQL** (Thopen, AWS RDS) | `PG_HOST:5432`, db `powerplants` | usuário/senha (psycopg2) | schema **`dbt`** (TimescaleDB); cobertura ~50% (gaps de ingestão a montante) |
| **SunOp Athon** (gridco, 10 GD) | `https://gridco-api.sunop.net/api` + `/data` | `Authorization: JWT <token>` | token funcional tem claim `sub` numérico + `is_admin` (sub="Levi" é rejeitado/401) |
| **SunOp Axis** (2ª instância: PE III, Ponto Belo) | `https://axis.sunop.net` | `Authorization: JWT <token>` (~24h) | mesma API do Athon, conta separada |
| **SolarEdge** (RenoGrid, 7 UFVs) | `https://monitoring.solaredge.com` | **AWS Cognito** (pool `eu-central-1_fVUTz39em`) → cookie em `tokens_runtime.json` (`se_cookie`) | API interna (não a oficial); só strings |
| **2C / Email** (Owen, 4 UFVs) | — (sem API) | — | lê CSVs de `OWEN_ROOT` (baixados por projeto Gmail separado) → `owen_accum.json` |
| **Fracttal** (CMMS / OS) | `https://app.fracttal.com` | **OAuth2 client_credentials** (`FRACTTAL_CLIENT_ID/SECRET`) | leitura REST de work_orders; rate limit ~200/min (cacheado) |

> **NÃO há integração Microsoft Graph / SharePoint API.** As planilhas Excel (`BD_Performance.xlsx`, `Check Diário`, `BD_Thopen.xlsx`) chegam por **sincronização de arquivo do OneDrive/SharePoint** (cliente desktop), não por API. O app só lê os arquivos do disco.

## Threads / jobs background
Iniciadas no `__main__` (só com `python app.py`). Todas são **falha-silenciosa** (try/except + `continue`; logam em stdout, nunca derrubam o servidor):
| Thread | O que faz | Frequência |
|---|---|---|
| `_owen_loop` | Mescla os CSVs 2C no acervo do dia (`owen_accum.json`) antes do próximo e-mail sobrescrever | **10 min** |
| `_sunop_keepalive_loop` | Renova os tokens SunOp gridco/axis (`/refresh_token`) — nunca precisa colar token manual com o server de pé | **6 h** |
| `_prewarm_loop` | Reaquece `/api/data` + todos os caches por fonte antes de expirarem (rede de segurança do SWR) | **~4,5 min** (`CACHE_TTL`−30) |
| `_persist_loop` | Salva `cache_snapshot.json` quando algo mudou (dirty flag) | **1 min** |

Obs.: existe `_sunop_accum_loop` (amostrador ETM → `sunop_etm_accum.json`, intervalo `SUNOP_SAMPLE_INTERVAL`=300 s) **definido mas não iniciado no boot** (acionado sob demanda pela aba ETM SunOp).

## Estado persistido em disco
| Arquivo | Guarda | Se apagar |
|---|---|---|
| `cache_snapshot.json` | Snapshot dos caches (SWR) | OK — reconstrói em ~5 min (1ª carga fica fria/lenta) |
| `owen_accum.json` | Acervo do dia 2C/Email | OK na prática — reseta na virada do dia de qualquer forma |
| `ufv_state.json` | Estado por UFV ("em manutenção", flags de UI) | **PERDE config manual** — não regenerável |
| `string_notas.json` | Notas de subperformance (curva strings) | **PERDE anotações** — não regenerável |
| `spv_stringbox.json` | Classificação string-box por usina | OK — recalcula sob demanda |
| `sunop_etm_accum.json` | IPOA integrado do SunOp (acumulador do dia) | OK — reacumula no dia |
| `tokens_runtime.json` | Tokens/cookies de sessão renovados pelo app (`sunop`, `axis`, `plat`, `se_cookie`) | OK — recriados do `.env`/`tokens.txt` (Plataforma exige colar token manual) |

> **Não vêm no ZIP** (segredos): `.env`, `se_credentials.txt`, `pg_password.txt` e o `tokens_runtime.json` acima. O app os recria a partir do `.env` (exceto PV Plataforma, que é token manual). Ver "Pegadinhas".

## Portas e endpoints
- **Porta:** `5050` (hardcoded no `app.py`).
- **Healthcheck:** `GET /healthz` → 200 (liberado, sem login) — use no monitor/load-balancer.
- `GET /login` → tela de login (liberada). `GET /` → dashboard (exige sessão se `DASH_PASSWORD` setada).
- Demais ~84 rotas sob `/api/...` por fonte (ver `docs/arquitetura.md` §12).

## Pegadinhas conhecidas
- **Servir SÓ com `python app.py`** — `waitress-serve`/`gunicorn` não disparam as threads/persistência (ver "Como rodar"). É o erro nº 1 de deploy aqui.
- **gunicorn não roda no Windows** (`fcntl`). Use waitress.
- **Python 3.14.6** é o alvo; os pins têm wheel cp314. Não há motivo p/ subir de versão; se baixar, revalidar wheels.
- **`psycopg2-binary` pin 2.9.12** — não dar bump sem testar (libpq embutido).
- **PostgreSQL:** o **IP do servidor precisa estar no security group do RDS** (porta 5432), senão a aba "Banco de Dados" fica indisponível. O banco está com **~50% de cobertura** (gaps de ingestão a montante — não é bug do dashboard).
- **Fuso horário:** o app assume horário **local BR (UTC−3)** para "hoje"/janelas do dia. Rodar o servidor com TZ diferente desloca os recortes de dia. Manter o SO em America/Sao_Paulo.
- **Console cp1252 (Windows):** `print()` com emoji/acento pode dar `UnicodeEncodeError` em console legado. Rodar com `PYTHONUTF8=1` (ou `chcp 65001`) evita.
- **Template Flask cacheado** (debug=False): mudar `index.html` exige **reiniciar** o servidor.
- **Tokens que expiram:** PV Plataforma (chave `plat` do `tokens_runtime.json`, ~7d, **manual**) e o token do Gmail do coletor 2C (projeto separado, expira ~7d se o app OAuth estiver em "Testing") param a respectiva fonte — as demais auto-renovam.
- **Permissão de escrita:** o processo precisa de **escrita na pasta do app** (grava os `.json`/`.txt` de estado e tokens ali, ao lado do `app.py`).
- **Logos 404** em `static/logos/*.png` — cosmético (há fallback de emoji).

## Comandos úteis de operação
- **Forçar atualização de tudo:** botão "↻ Atualizar" na UI, ou `GET /api/data?force=1` (zera caches e refaz as fontes).
- **Recarregar planilhas (Check/Equipamentos):** automático no `mtime`; ou o force acima.
- **Trocar token expirado:** o da Plataforma vai pelo bookmarklet (`POST /api/pv/trackers/token`, vale na hora); os demais, editar `tokens.txt`/`.env` (`SUNOP_TOKEN`/`AXIS_TOKEN`) e reiniciar.
- **Limpar cache em disco:** parar o app, apagar `cache_snapshot.json`, subir (reconstrói; use se o snapshot ficar corrompido). **Não** apague `ufv_state.json`/`string_notas.json` (não regeneráveis).
- **Healthcheck/monitor:** `curl http://localhost:5050/healthz`.
- **Testes:** `run_tests.bat` (ou `pytest`).

## Sobre a coleta diária das UFVs (BD_Thopen e BD_Performance)
Este dashboard **apenas lê** as planilhas `BD_Performance.xlsx` (cadastro mestre + diários Athon/2C) e `BD_Thopen.xlsx` (diário das usinas Thopen). **Quem as preenche é um conjunto SEPARADO de coletores** (projeto "coleta API PV": `coletar_pvoperation`/`rodar_sunop`/`rodar_solaredge` → escrevem geração+IPOA+GHI+chuva por UFV, com a regra "dado nulo → 0 + amarelo/vermelho"), rodados manualmente ou por Tarefa Agendada do Windows. **Esses coletores NÃO fazem parte deste ZIP** — são entrega à parte.

**Resolução do caminho do `BD_Performance.xlsx`** (`_bd_perf_path()`): tenta nesta ordem → (1) env `BD_PERF_PATH`; (2) caminho do OneDrive sincronizado; (3) **cópia local ao lado do `app.py`** (a que vem neste ZIP) como último recurso. Ou seja, **o ZIP é auto-suficiente**: no servidor do TI (sem aquele OneDrive) o app cai automaticamente na cópia local empacotada — mas ela é um *snapshot* do dia do empacotamento. Para o dashboard refletir a coleta diária, aponte `BD_PERF_PATH` (e, no `dashboard_thopen.py`, `BD_THOPEN_PATH`) para uma cópia mantida atualizada pelos coletores, ou deixe o OneDrive sincronizar a pasta `1. Banco de Dados`.
