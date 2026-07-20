# Migração do Dashboard Thopen — Dossiê Técnico para T.I.

> **Objetivo:** subsidiar a decisão de onde hospedar a aplicação (hoje no Railway).
> **Preparado por:** Grid Co — Performance · **Data:** 06/07/2026
> **Repositório:** `Levi-6242/PerformancePainel` (privado, GitHub)
> **URL atual:** https://web-production-014f9.up.railway.app/

---

> ⚠️ **PREMISSA A CORRIGIR (importante):** a aplicação **não** se conecta ao OneDrive por API
> (Graph / MSAL / Azure AD). Ela apenas **lê arquivos `.xlsx`** — do disco (OneDrive sincronizado,
> quando roda no PC) ou de um **snapshot versionado no próprio repositório** (quando roda na nuvem).
> **Não existe App Registration, client_id, client_secret nem token.** Isso elimina toda a
> complexidade de credenciais que normalmente se pressupõe numa integração OneDrive.

---

## 1. Arquitetura da aplicação

| Item | Valor |
|---|---|
| **Framework** | **Flask 3.1.3** (WSGI puro) |
| **Versão do Python** | Sem pin no repo. Roda em **3.11–3.14** (dev local = 3.14.6). Recomendado fixar 3.12 via `runtime.txt` |
| **Entrypoint** | `dashboard_thopen.py`, objeto WSGI `app` |
| **Comando (produção)** | `gunicorn dashboard_thopen:app --bind 0.0.0.0:$PORT --workers 2 --timeout 180` |
| **Comando (dev)** | `python dashboard_thopen.py` → `app.run(port=5080, threaded=True)` |
| **SPA ou multi-rota?** | **Híbrido:** 1 página HTML (`/`) que consome **5 rotas de API** via `fetch`. Não é framework SPA (sem React/Vue); é HTML + JS puro + Plotly.js (via CDN) |
| **WebSockets?** | **Não.** 100% HTTP request/response. (Usa `threading` apenas para lock de cache em memória, não para conexões persistentes) |

**Rotas expostas:** `/` (HTML) · `/api/t/usinas` · `/api/t/overview` · `/api/t/diario` · `/api/t/geral` · `/api/t/reload`

---

## 2. Estrutura do projeto

> **Importante:** o repositório `PerformancePainel` contém **várias aplicações** (o dashboard interno
> `app.py`, coletores, o `os_creator`, etc.). O que roda no Railway é **exclusivamente o
> `dashboard_thopen.py`**. Os arquivos abaixo são os únicos relevantes para este deploy.

```
PerformancePainel/            (repo privado no GitHub: Levi-6242/PerformancePainel)
├── dashboard_thopen.py        ← ENTRYPOINT (908 linhas)
├── templates/
│   └── dashboard_thopen.html  ← frontend (637 linhas, Plotly.js via CDN)
├── data/                      ← SNAPSHOT dos dados (lido na nuvem) ~4,9 MB
│   ├── BD_Thopen.xlsx                       3,5 MB
│   ├── Matrix/Geração Matrix.xlsx           128 KB
│   ├── Copel/Geração Copel.xlsx             96 KB
│   └── Polaris/
│       ├── Budget_2025_UFVs_Raizen…xlsx     1,1 MB
│       └── Comentários Polaris.xlsx         48 KB
├── requirements.txt
├── Procfile
├── railway.toml
├── atualizar_nuvem.ps1 / "Atualizar Nuvem.bat"   ← script que atualiza o snapshot
└── (app.py, dashboard_geracao.py, os_creator/, coletores… = NÃO usados por este app)
```

**`requirements.txt`** (é compartilhado com o `app.py` — o dashboard_thopen só precisa de 3 destas):

```
flask==3.1.3          ← usado
openpyxl==3.1.5       ← usado
gunicorn==23.0.0      ← usado (servidor WSGI Linux)
# --- as abaixo são do app.py, NÃO do dashboard_thopen: ---
flask-compress, requests, pandas, numpy, matplotlib,
psycopg2-binary, pycognito, python-dotenv, waitress
```

> **Recomendação:** criar um `requirements` enxuto só com `flask`, `openpyxl`, `gunicorn`
> → build muito mais rápido e leve.

**`Procfile`:**

```
web: gunicorn dashboard_thopen:app --bind 0.0.0.0:$PORT --workers 2 --timeout 180
```

**`railway.toml`:**

```toml
[build]
builder = "NIXPACKS"
[deploy]
startCommand = "gunicorn dashboard_thopen:app --bind 0.0.0.0:$PORT --workers 2 --timeout 180"
healthcheckPath = "/"
restartPolicyType = "ON_FAILURE"
```

**`Dockerfile`:** N/A (não existe — o Railway usa Nixpacks). Se a TI preferir Docker, é trivial montar
(imagem `python:3.12-slim` + `pip install` + `gunicorn`). Posso fornecer sob demanda.

---

## 3. Integração com OneDrive

**Não há integração via API.** Detalhamento:

| Item | Resposta |
|---|---|
| **Método de autenticação** | **Nenhum.** Leitura de arquivo `.xlsx` com `openpyxl` |
| **Microsoft Graph / MSAL / SDK?** | **N/A** — não usado |
| **Tipo de credencial** | **N/A** — não há credencial |
| **Client ID / Tenant ID** | **N/A** |
| **Como as planilhas são localizadas** | Por **caminho**. Duas fontes, escolhidas em runtime: **(1)** no PC → caminhos absolutos do OneDrive sincronizado (`C:\Users\...\OneDrive\...`); **(2)** na nuvem → pasta `data/` do repo (ativada por env `THOPEN_DATA_DIR` ou auto-detecção de qualquer env `RAILWAY_*`) |
| **Frequência de leitura** | **Cache em memória**, invalidado pela data de modificação do arquivo (`mtime`). Lê do disco só na 1ª requisição e quando o arquivo muda. Copia para arquivo temporário antes de abrir (evita lock do Excel/OneDrive) |
| **Tamanho / quantidade** | **5 planilhas, ~4,9 MB** no total (ver árvore acima) |

**Consequência prática para a TI:** hoje, "atualizar os dados na nuvem" = **atualizar o snapshot `data/`
e fazer deploy**. Existe um script de 1 clique que faz isso (`Atualizar Nuvem.bat`). A alternativa
"dados ao vivo" exigiria **desenvolvimento novo** para ler do SharePoint via Graph API (ver seção 10).

---

## 4. Variáveis de ambiente

O app **não exige nenhuma variável** para funcionar (tem fallback para tudo). As que ele *lê*
(todas opcionais, **nenhum segredo**):

| Nome | Função | Injetada hoje no Railway? |
|---|---|---|
| `THOPEN_DATA_DIR` | Aponta a pasta do snapshot (ex.: `data`) | Não (usa auto-detecção) |
| `BD_THOPEN_PATH` | Caminho alternativo do BD_Thopen.xlsx | Não |
| `PORT` | Porta HTTP (padrão do host) | **Sim** (injetada automaticamente pelo Railway) |
| `RAILWAY_*` | Diversas, automáticas do Railway | **Sim** (o app só checa a *existência* para saber que está na nuvem) |

**Não há** `AZURE_CLIENT_ID`, `CLIENT_SECRET`, `ONEDRIVE_FOLDER_ID`, chave de banco, nem qualquer credencial.

---

## 5. Recursos e escala

| Item | Resposta |
|---|---|
| **Usuários/dia** | *A confirmar pelo dono do produto.* Pela natureza (relatório O&M interno + poucos clientes), estimativa **baixa — dezenas, não milhares** |
| **CPU** | Baixa. Picos curtos ao ler os `.xlsx`; ocioso o resto do tempo |
| **RAM** | Estimativa **~150–400 MB** (mantém os workbooks em memória). Valor real disponível em Railway → **Metrics/Usage** |
| **Cold start** | **Tolerável, mas existe:** ~10–30 s no 1º acesso após ficar parado (subir o processo + ler os Excel). Não precisa estar "warm" o tempo todo, mas cliente externo sente a 1ª abertura lenta |
| **Armazenamento persistente** | **Não precisa.** Sem SQLite, sem cache em disco, sem uploads. Estado é efêmero em memória; dados vêm do snapshot no repo. Filesystem pode ser **read-only** |

---

## 6. Autenticação de usuários

| Item | Resposta |
|---|---|
| **É público?** | **Sim — hoje não tem login nenhum.** Qualquer pessoa com a URL vê tudo |
| **Sistema de login** | N/A (inexistente) |
| **Quem pode acessar** | Intenção: **colaboradores Grid + clientes externos** (Thopen). Mas, sem auth, é qualquer um com o link |

> 🔴 **Ponto de atenção:** os dados são comerciais de clientes (geração, disponibilidade, metas,
> ocorrências operacionais de UFVs de Thopen/Copel/Polaris-Raízen/Matrix). Expor **público, sem login**,
> é a maior fragilidade atual. Antes de divulgar amplamente, recomenda-se **pelo menos** uma senha
> compartilhada, ou **Cloudflare Access / Azure AD** na frente.

---

## 7. Domínio

| Item | Resposta |
|---|---|
| **URL atual** | https://web-production-014f9.up.railway.app/ |
| **Domínio custom** | **Não configurado.** Subdomínio automático do Railway |
| **Quem controla o DNS** | O da URL atual é do **Railway**. Um domínio próprio (ex.: `thopen.gridco.com.br`) seria controlado **pela TI da Grid** — é aí que entra o CNAME/registro para qualquer opção escolhida |

---

## 8. Código-fonte (mapa dos módulos)

Tudo num único arquivo `dashboard_thopen.py` (908 linhas). Blocos principais:

- **Localização/leitura dos dados** (linhas ~35–130): `_DATA_DIR`, `_bd_path()`, `_open_wb()`
  (copia p/ temp e abre com openpyxl `data_only`), `_wb()` (cache por `mtime`).
- **Fontes por carteira:** `_polaris_records()` (Budget Polaris), `_sheet_records()` (Matrix/Copel),
  `_daily_bd()` (BD_Thopen) + `_daily_records()` (roteador com a regra de corte 01/06).
- **Métricas/relatório:** `_meta2026()`, `_produzida_*()`, `_resumo_usina()`.
- **6 rotas Flask** (JSON) + `/` que faz `render_template`.
- **Renderização de gráficos:** é **client-side** — o `templates/dashboard_thopen.html` monta os
  gráficos com **Plotly.js** (CDN) a partir do JSON das APIs. O servidor **não** gera imagem.

*(O fonte completo — `dashboard_thopen.py` + `.html`, 1.545 linhas — está no repositório e pode ser
anexado à parte se a TI precisar revisar linha a linha.)*

---

## 9. Restrições e requisitos operacionais

| Item | Resposta |
|---|---|
| **Grid precisa atualizar o app?** | **Sim, duas coisas distintas:** (1) **dados** — hoje via `Atualizar Nuvem.bat` (recopia planilhas + `git push` → re-deploy). (2) **código** — via `git push` no repo. Se hospedado com leitura ao vivo do SharePoint, o item (1) desaparece |
| **Log / auditoria de acesso** | **Não existe** hoje (só o log de request do servidor). Se for requisito, precisa ser adicionado (ou resolvido pela camada de proxy/Access) |
| **LGPD / sensibilidade** | **Sem dados pessoais** (não há CPF, e-mail, nome de pessoa física). **Mas há dados comerciais sensíveis**: nomes de clientes/UFVs, energia gerada, disponibilidade, metas, ocorrências. Confidencial por contrato — **não deveria ser público** |
| **Tolerância a indisponibilidade** | Cliente externo tolera mal ficar fora do ar. Isso **penaliza a opção (a)** se a máquina Windows depender de energia/rede de um escritório e do OneDrive estar sincronizado |

---

## 10. Recomendação técnica

**O verdadeiro eixo da decisão não é "qual host", é "como os dados chegam ao servidor".**
Hoje são um snapshot manual. Isso influencia as 3 opções:

### (a) Cloudflare Tunnel + máquina Windows da Grid
- ✅ **Único cenário com dados AO VIVO sem código novo** — a máquina tem o OneDrive sincronizado, o app lê direto.
- ✅ Custo quase zero; controle total.
- ❌ **Uptime frágil:** depende da máquina ligada 24/7, energia, reboots do Windows e do OneDrive estar sincronizado. Ruim para cliente externo.
- ❌ **Usar *named tunnel*, nunca o *quick tunnel*.** O quick tunnel dá problema (URL muda, cai, sofre rate-limit). O named tunnel (com domínio no Cloudflare) resolve, mas exige setup + o domínio.
- ❌ Manutenção manual (quem reinicia se travar?).

### (b) Cloud gerenciada (Fly.io / DigitalOcean / **Azure App Service**)
- ✅ **Melhor uptime e HTTPS/domínio**; ideal para cliente externo.
- ✅ **Azure App Service** é o encaixe natural: a Grid já é ecossistema Microsoft, e abre caminho
  para, **no futuro**, ler os dados **ao vivo do SharePoint via Graph API** (hoje feito por snapshot)
  — resolvendo a limitação de dados congelados.
- ⚠️ Precisa decidir a fonte de dados: **snapshot** (como hoje, atualizado por deploy/CI) **ou**
  desenvolver a leitura via Graph (App Registration com `Sites.Read.All` — trabalho novo).
- ❌ Custo mensal (baixo — é um app minúsculo; qualquer tier básico sobra).

### (c) Manter no Railway
- ✅ Já funciona; deploy automático por `git push`; zero setup.
- ❌ **Trial acaba** (~US$ 5/mês depois — barato, mas é fornecedor terceiro com dados de cliente).
- ❌ Mantém o **snapshot congelado** (atualização por deploy).

### 🎯 Recomendação
- **Para "entregar a cliente externo com estabilidade": opção (b), Azure App Service** — encaixa no
  ecossistema Microsoft da Grid, uptime alto, domínio `*.gridco.com.br` fácil. Começar com o
  **snapshot** que já existe e evoluir para **Graph API ao vivo** quando fizer sentido.
- **Para "uso interno rápido e barato": opção (a) com named tunnel** — assumindo o risco de uptime.
- **Independente da escolha, dois pré-requisitos antes de expor a cliente:**
  1. **Colocar autenticação** na frente (Access / Azure AD / senha).
  2. Resolver a **estratégia de dados** (snapshot automatizado *vs.* Graph ao vivo).

---

## Lacunas a preencher (dono do produto / TI)
1. **Usuários/dia reais** (seção 5).
2. **CPU / RAM / custo reais** — em Railway → aba **Metrics/Usage**.
