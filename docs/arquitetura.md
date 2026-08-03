# Arquitetura & Operação — Dashboard O&M Grid Co.

> Documento de handover para um dev (ou IA) assumir o projeto do zero.
> Última atualização: 2026-06-10. Escrito em PT-BR (idioma do projeto).
>
> 📚 Documentação relacionada: [Índice](README.md) ·
> [Regras de negócio](regras-de-negocio.md) ·
> [API PV Operation](api-pv-operation.md) ·
> [Coleta SunOp](coleta-sunop.md)

---

## 1. O QUE É

Dashboard web (Flask) de **Operação & Manutenção (O&M) de usinas solares** da Grid Co.
Consolida **strings ativas × esperadas**, **pré-análise ETM** (irradiância POA/GHI),
**geração**, **trackers** e **PR por inversor** de **6 fontes/sistemas diferentes**, cada
uma de um cliente/integrador distinto, numa única tela.

- Roda **localmente** em `http://localhost:5050` (servidor Flask de desenvolvimento).
- Usuário-alvo: analista de O&M (Levi). Uso interno, máquina Windows 11.
- Inicia pelo `Iniciar Dashboard.bat` (instala deps via requirements.txt + `python app.py`).

---

## 2. STACK & ARQUITETURA

- **Backend:** `app.py` (~4.270 linhas, Flask). TUDO num arquivo só (monolito).
- **Frontend:** `templates/index.html` (~2.900 linhas) — HTML + CSS + JS **inline**, sem build.
  Usa **Plotly** (CDN) para gráficos.
- **Sem banco próprio**: o estado fica em **arquivos JSON** na pasta + planilhas Excel + um
  PostgreSQL externo (de uma das fontes).
- **Sem testes automatizados.** Sem framework de front (JS puro).
- `app.run(debug=False, port=5050, threaded=True)` — servidor de DEV (não-produção).
- **Cache:** a maioria dos endpoints cacheia em memória por `CACHE_TTL` (5 min). Botão
  "↻ Atualizar" (`atualizarTudo`) zera os caches e refaz tudo.

### Estrutura de navegação (abas)
Abas **primárias** (cliente / fonte) → cada uma com **subabas** (secundárias):

| Aba primária (label / sub) | `primary` | Subabas disponíveis |
|---|---|---|
| **Thopen / API PV Operation** | `pv` | Strings · ETM · 📊 PR Inversores · 📈 Curva das strings |
| **Thopen / Banco de Dados** | `pg` | Strings · ETM · 📊 Geração · 🛰️ Trackers |
| **Athon / API SunOp** | `sunop` | Strings · ETM · 🛰️ Trackers |
| **RenoGrid / API SolarEdge** | `solaredge` | Strings |
| **2C / (Email)** | `owen` | Strings · ETM · 🛰️ Trackers |

JS de navegação: `switchPrimary()`, `switchSecondary()`, `show()` (chama `_aplicaBarras()`
no início para exibir as subabas certas), `_secsDisponiveis(primary)` lista as subabas.

---

## 3. CAMINHOS ESSENCIAIS (todos)

### Projeto principal (dashboard)
```
C:\Users\Levi Maia\Desktop\Projeto Strings\pv_dashboard\
├── app.py                      # backend Flask (monolito)
├── templates\index.html        # frontend inteiro
├── Iniciar Dashboard.bat        # sobe o servidor (porta 5050)
├── requirements.txt
├── .env                         # credenciais locais (gitignored; modelo em .env.example)
├── docs\                        # documentação (este arquivo + regras + APIs)
├── tracker_watch.py             # módulo do "tracker watch" (issues) — backend pronto, REMOVIDO da UI
├── coletar_geracao_hoje.py      # script auxiliar de coleta (standalone, fora do dashboard)
├── collect_energy.py            # script auxiliar de coleta (standalone)
├── static\                      # (logos opcionais; pv.png/sunop.png/solaredge.png dão 404 se ausentes — cosmético)
└── templates\
```

### Arquivos de ESTADO / dados (na pasta pv_dashboard)
```
owen_accum.json        # acervo do dia da fonte 2C/Email (ETM/Strings/Trackers); ~1 MB; reseta na virada do dia
ufv_state.json         # estado de "Em manutenção" das UFVs (checkbox no ETM) + outros estados de UI
tracker_issues.json    # base do "tracker watch" (issues ativas/histórico) — alimentada por tracker_watch.py
tracker_issues.bak.json# backup
string_notas.json      # motivos de subperformance anotados na "Curva das strings" (chave: "dd/mm/aaaa|idInversor")
spv_stringbox.json     # classificação string-box por usina (cache; {str(idusina): bool})
sunop_etm_accum.json   # (se existir) acumulador de IPOA integrado do SunOp
LEIA-ME.txt
```

### Credenciais / tokens (na pasta pv_dashboard) — todos GITIGNORED
```
.env                   # PRINCIPAL: PV_USERNAME/PV_PASSWORD, SUNOP_TOKEN, PG_*, SE_* (ver .env.example)
pg_password.txt        # senha do PostgreSQL (fallback se PG_PASSWORD não estiver no .env)
tokens_runtime.json    # tokens que o PRÓPRIO APP renova e reescreve (o tokens.txt é semente humana):
                       #   plat      = JWT da API PV Plataforma (x-auth-token-update) — ~7 dias, manual
                       #   sunop/axis= JWT das duas instâncias SunOp (auto-renovadas)
                       #   se_cookie = cookie de sessão SolarEdge (login Cognito)
se_credentials.txt     # credenciais SolarEdge (fallback se SE_USERNAME/SE_PASSWORD não estiverem no .env)
```
> Nenhuma credencial fica no código: `app.py`, `tracker_watch.py` e os scripts auxiliares
> carregam o `.env` na inicialização (python-dotenv). Ainda é texto plano no disco (ver §10).

### Planilhas Excel (SharePoint sincronizado via OneDrive)
```
# Check Diário (cadastro de strings esperadas + mapa de nomes)
C:\Users\Levi Maia\OneDrive - GRID CO\Grid Co_ - 4. O&M\6.Gerencial\4. Gestão à vista\1. Banco de Dados\Check Diário - Geração e ETM.xlsx

# BD_Performance (cadastro MESTRE de equipamentos + potência por inversor + diários Athon/2C/etc.)
C:\Users\Levi Maia\OneDrive - GRID CO\Grid Co_ - 4. O&M\6.Gerencial\4. Gestão à vista\1. Banco de Dados\BD_Performance.xlsx

# BD_Thopen (diário das usinas Thopen: geração/inversor + IPOA + SKID)
C:\Users\Levi Maia\GRID CO\Grid Co. - 17. Acesso Externo Thopen\1. Registro usinas Thopen\BD_Thopen.xlsx
```

### Coletor de e-mail 2C (projeto SEPARADO)
```
C:\Users\Levi Maia\Desktop\Projetos e-mail\
├── 1 - Automatizador\
│   ├── app_gridco.py        # baixador Gmail (Flask manual + modo headless --auto)
│   ├── Iniciar GridCo.bat
│   ├── credentials.json     # OAuth client (Google Cloud)
│   └── token_gmail.json     # token OAuth (expira/revoga periodicamente — ver §9 e §10)
├── ETM\                      # CSVs baixados (irradiância)
├── Strings\                  # CSVs baixados (corrente por string/inversor)
└── Trackers\                 # CSVs baixados (alvo/atual por tracker)
```

### Memória da IA (contexto persistente entre sessões)
```
C:\Users\Levi Maia\.claude\projects\C--Users-Levi-Maia\memory\
├── MEMORY.md                  # índice
├── project-pv-dashboard.md    # ESTE projeto (histórico detalhado de cada feature/fix)
├── project_sunop.md, project_meteorologico.md, project_trackers.md, etc.
```

---

## 4. AS 6 FONTES DE DADOS (auth, endpoints, particularidades)

### 4.1 API PV Operation — `pv` (cliente: Thopen, ~142 usinas)
- **Base:** `https://apipv.pvoperation.com.br/api/v1`
- **Auth:** `POST /authenticate` {username, password} → token; header `x-access-token`.
  Credenciais via `.env` (`PV_USERNAME`/`PV_PASSWORD`).
- **Endpoints:** `/plants`, `POST /day_inverter {id}` (por inversor: `conteudojson` com `Ipv*`
  correntes de string, `Temp`, `Eday`=energia do dia), `GET /plant_devices {id}`,
  `POST /day_meteo {id}` (irradiância intradiária).
- **Filtro Full O&M:** só processa usinas cujo nome está no set `FULL_OM` (vem do Check). ~115.
- **Subaba "📊 PR Inversores":** PR_inv = `Eday / (IPOA × Potência_inv)`. Potência vem do
  Equipamentos (`POWER_INV`); IPOA = integral trapezoidal da curva POA do dia. Só usinas
  **string-box** (inversores com ≤1 string — sem visão real de strings). Endpoints `/api/pv/pr`.
- ⚠️ **Lentidão:** `/api/data` (visão geral) leva **~65 s** na 1ª carga (142 usinas × 3 passadas
  de retry, pois a API dá timeouts intermitentes). Depois cacheia 5 min.
- ⚠️ **Campo de POA inconsistente por usina** — ver §8 (`_pick_irr`).

### 4.2 API PV PLATAFORMA — `pv` subaba "📈 Curva das strings" (Thopen) — FONTE SEPARADA
- **Base:** `https://apiplataforma.pvoperation.com` (≠ apipv!).
- **Auth:** header `x-auth-token-update` = JWT de sessão (~7 dias), na chave `plat` do `tokens_runtime.json`.
  Reautenticar: no portal `plataforma.pvoperation.com`, F12 → copiar header `x-auth-token-update`.
- **🔑 `idusina` é COMPARTILHADO com a apipv** (ex.: Indaiatuba 1 = 21480 nas duas) → catálogo de
  usinas vem do `get_plants()` da apipv.
- **Cadeia:** `GET /v2/relatorios/getlistainversores?idusina=ID` → `.inversores` [{id, nome:"INVERSOR 1.1"}];
  `GET /v2/relatorios/trygenerate?idInversor=ID&data=dd/mm/aaaa&type=9&status=2` →
  `dados_energia_dia`{ST:kWh} + `dados_potencia_string`{ST:[{potencia(W), tsleitura(RFC822 GMT)}]}.
- **Análise:** mediana das energias das strings; string < 90% da mediana = subperformance.
  String-box (≤1 Ipv na `leitura` do getlistainversores) são EXCLUÍDAS da aba.
- Endpoints: `/api/spv/usinas`, `/api/spv/usina/<id>`, `/api/spv/nota` (POST), `/api/spv/pdf`
  (relatório paisagem A4, 4 inversores/página, cards estilo ETM).

### 4.3 Banco PG (PostgreSQL) — `pg` (cliente: Thopen, ~34 usinas)
- **Conexão:** `psycopg2`; host/porta/db/usuário/senha via `.env` (`PG_HOST`, `PG_PORT`, `PG_DB`,
  `PG_USER`, `PG_PASSWORD`; fallback da senha em `pg_password.txt`). Schema principal: **`dbt`** (TimescaleDB).
- **Tabelas-chave:** `dbt.stg_inverter_string_data`, `dbt.stg_inverter_analogic_data`
  (`daily_active_energy`), `dbt.stg_weather_station_analogic_data` (`irradiance_poa/ghi`, 5 min),
  `dbt.int_inverter_power_plant_daily_energy_timeseries` (geração/usina/dia, materializada),
  `dbt.int_tracker_latest_readings` (788 trackers: posat/posal/deviation/status_label),
  `dbt.stg_tracker_analogic_data` (série 5 min de trackers). `public.tb_power_plants`,
  `public.tb_devices`. Medidor `stg_meter_analogic_data` está VAZIO.
- **Subaba "📊 Geração":** IPOA/GHI = **integração TRAPEZOIDAL** pelo tempo real entre leituras
  (`LAG()` em SQL), gaps > 60 min descartados. Mostra **cobertura %** e flag de baixa confiança.
  ⚠️ O banco está com ~50% de cobertura (gaps de ingestão) — ver §10.
- **Subaba "🛰️ Trackers":** overview por usina (instantâneo) + drill-down por curva do dia
  (parado/desvio/atraso). 17 usinas Thopen, 788 trackers.

### 4.4 API SunOp — `sunop` (cliente: Athon, 10 usinas GD)
- **Base:** `https://gridco-api.sunop.net/api` (config) + `/data` (dados).
- **Auth:** header `Authorization: JWT <token>`. Token de sessão (~7 dias) via `.env`
  (`SUNOP_TOKEN`), usado por `app.py` e `tracker_watch.py`. ⚠️ Tokens com `exp` distante mas `sub:Levi`
  são REJEITADOS (401); o que funciona tem `sub:123412`/`is_admin`. Renovar: `gridco.sunop.net`
  → F12 → `localStorage.getItem('token')`.
- **Endpoints:** `/api/plants`, `/data/v2/metadata?plant=`, `POST /data/v2/last_values {pathnames}`,
  `POST /data/v2/analog_values` (HISTÓRICO intradiário, source=Historical — desbloqueado).
- **Pathnames:** strings `{PLANT}.INV_N.MEDIDAS.STR.I_PV{X}`; ETM `{PLANT}.ESTM[_n].{POA|GHI|POA_R}.IRAD`;
  trackers `{PLANT}.TRK_N.MEDIDAS.{POSAL|POSAT|STRD_DEV}`.
- 10 plantas: SMP100, CPP100, TIM100/200, MRO100, MTS100/200, MAB100/200, JCD100.

### 4.5 SolarEdge — `solaredge` (cliente: RenoGrid, 7 UFVs, SÓ strings)
- **Base:** `https://monitoring.solaredge.com`. Auth via **cookie** (chave `se_cookie` do `tokens_runtime.json`) renovado por
  login **Cognito** com `se_credentials.txt`. API interna (não a oficial).
- Só tem visão de **strings** (sem ETM/trackers). Corrente "ativa" = potência > 0.

### 4.6 2C / E-mail (Owen) — `owen` (cliente: 2C, 4 UFVs)
- **UFVs:** `OWEN_UFVS = {ARA: Araputanga, IPX: Ipixuna do Pará, STL: Sete Lagoas 2, TUP: Tupi Paulista}`.
- **Origem:** SCADA envia CSVs por e-mail em 4 janelas/dia (9/12/15/18h). O `app_gridco.py`
  (Gmail OAuth) baixa para `Desktop\Projetos e-mail\{ETM,Strings,Trackers}\`.
- **Acumulador:** como os e-mails são INCREMENTAIS e o baixador sobrescreve, o dashboard mescla
  em `owen_accum.json` (acervo do DIA, dedupe, reseta na virada; `_owen_refresh` filtra só HOJE).
- **OWEN_ROOT** env (default `C:\Users\Levi Maia\Desktop\Projetos e-mail`).
- Endpoints: `/api/owen/{etm/analise, strings/data, trackers}` etc. (reusa helpers das outras fontes).

---

## 5. CADASTRO MESTRE & MAPEAMENTO DE NOMES (crítico)

O grande desafio do projeto: cada API nomeia usinas/inversores diferente. A "cola":

- **Check Diário** (`load_check_spreadsheet`): aba **"Strings"** (esperadas por nome display) +
  aba **"Strings 2"** (mapa **supervisório ↔ display** + Full O&M + nº strings). Preenche as
  globais `ESPERADO_INV`, `EQUIP_NAMES`, `USINA_DISPLAY`, `FULL_OM` — **chaveadas pelo nome
  SUPERVISÓRIO** (o que cada API usa). Recarrega sozinha quando o arquivo muda (mtime).
- **Equipamentos** (`load_equip_power`, aba de **BD_Performance**): **substitui a Strings 2**
  como cadastro mestre (mesmas colunas supervisório + **Potência (kWp) por inversor**).
  Hierarquia UFV → UG NN → Inversor X.Y. Preenche `POWER_INV{usina_sup:{alias_norm:kWp}}`.
  Chave: `Usina Supervisório` = `plant['nome']` da API; `Equipamento Supervisório` = device_name.
- **Regra durável do usuário:** "qualquer relação antes feita na Check Strings 2, usar Equipamentos".
- `nome_usina(plant_id, nome_api)` traduz API→display; `EQUIP_NAMES[sup][equip_sup]` → "Inversor X.Y".

---

## 6. ARMAZENAMENTO — RESUMO

| Tipo | Onde | O quê |
|---|---|---|
| Estado de UI / acervo | JSONs na pasta pv_dashboard | manutenção, notas, acervo 2C, classificação string-box, issues |
| Cadastro / esperadas | Excel (Check, BD_Performance) | nomes, Full O&M, potência por inversor |
| Diário Thopen | Excel BD_Thopen + PostgreSQL | geração/inversor, IPOA, trackers |
| Tempo real | APIs (apipv, plataforma, sunop, solaredge) | leituras instantâneas/curvas |
| 2C | CSVs (e-mail) → owen_accum.json | ETM/strings/trackers |
| Credenciais | .txt em texto plano + hardcoded | senhas/tokens |

---

## 7. PARTICULARIDADES POR CLIENTE

- **Thopen:** tem 3 fontes (apipv tempo real, plataforma curva de strings, PostgreSQL). Usinas
  grandes fatiadas em "Skid"/"(NN)" na apipv (ex.: "Altair 1 (73)".."Altair 5") mas consolidadas
  em "Altair" no Equipamentos. Algumas usinas são **string-box** (1 string fake na apipv) → PR por
  inversor é o substituto. Trackers só no PostgreSQL/SunOp.
- **Athon (SunOp):** única fonte com trackers via API + ETM com POA_R (traseira/bifacial).
- **2C (E-mail):** depende do SCADA enviar CSV por e-mail; sem API. 4 UFVs.
- **RenoGrid (SolarEdge):** só strings, sem ETM/trackers.
- **Nomes duplicados:** 64 usinas têm nome de exibição duplicado na planilha → mantém o
  supervisório nessas (evita ambiguidade).

---

## 8. GOTCHAS TÉCNICOS (já resolvidos — não regredir)

- **`_pick_irr`:** o campo de POA/GHI varia por usina na apipv (`IrPOA` às vezes é energia/ciclo
  ~0,006; `piraPOA1` às vezes vem espúrio ~6393; **`Ir` é o confiável**). Em vez de ordem fixa,
  pega o **maior valor plausível** (descarta None e > 1600 W/m²). `_sensor_status`: erro só se
  v ≤ -50 ou > 1600 (antes marcava saudável > 500 como erro).
- **String ativa:** > 1 A = ativa sempre (regra do usuário). Fora da janela 9-15h, também aceita
  ≥30% da média das produzindo (pega <1 A em luz fraca). `_ipv_ativas`.
- **`.gc-btn-sm { display:none }`** por padrão (só aparece em "barras") → botões em painéis
  próprios precisam de regra CSS (`#panel-spv .gc-btn-sm{display:inline-block}`).
- **cp1252 no Windows:** `print()` com emoji/seta quebra (`UnicodeEncodeError`). Usar ASCII ou
  `sys.stdout.reconfigure(encoding='utf-8')` / `PYTHONUTF8=1`.
- **Template Flask cacheado** (debug=False) → mudar `index.html` exige **reiniciar o servidor**.

---

## 9. AUTOMAÇÕES (Agendador de Tarefas do Windows)

- **"2C - Baixar E-mails GridCo"** — pasta `\Dashboard PV\` no Agendador (⚠️ `-TaskPath '\Dashboard PV\'`
  é obrigatório p/ editar via PowerShell). Roda `pythonw app_gridco.py --auto` às **9/12/15/18h**.
  Configurada (2026-06-10) p/ rodar na bateria, acordar o PC, recuperar horário perdido, limite 30 min.
  O `--auto` coleta o dia e encerra (sem servidor/clique).
- O dashboard em si NÃO é serviço — é iniciado manualmente (`.bat`) ou pela sessão da IA.

---

## 10. PONTOS FRACOS / RISCOS (o que vigiar)

1. **Tokens que expiram (~7 dias) e exigem ação manual:**
   - SunOp (`SUNOP_TOKEN` no `.env`), PV Plataforma (`tokens_runtime.json` → `plat`), Gmail OAuth (`token_gmail.json`).
   - **Gmail:** se o app OAuth está em "Testing", o refresh token expira a cada 7 dias →
     coleta 2C para. **Solução definitiva: publicar o app p/ "Production" no Google Cloud.**
2. **Credenciais em texto plano no disco:** já saíram do código e do repositório (`.env` + `.txt`,
   todos gitignored), mas seguem em texto plano na máquina. Senha do PG fraca + banco com IP
   público continuam pendentes (trocar senha / fechar firewall). Risco de segurança real.
3. **PostgreSQL com ~50% de cobertura** (gaps de ingestão na estação meteorológica, sistêmico há
   semanas) → IPOA/GHI subestimam. Mitigado com trapézio + flag de cobertura, mas a **causa-raiz
   é o pipeline de ingestão do banco** (acima do dashboard) — precisa ser escalado.
4. **/api/data lento (~65 s)** quando a apipv está instável (3 passadas de retry).
5. **Servidor de DEV** (Werkzeug), single-process threaded, atrelado à sessão que o inicia.
   Se a sessão fecha, o dashboard cai. Ideal: rodar via `.bat` em janela própria / serviço.
6. **2C depende do SCADA** enviar CSV do dia. Em 2026-06-10 chegaram relatórios datados de 21/05 e
   25/05 — coleta OK, mas conteúdo do dia ausente. Vigiar a origem.
7. **Monolito:** `app.py` 4.270 linhas, `index.html` 2.900 — difícil de manter; sem testes.
8. **Trackers — critério incompleto (PENDENTE):** o classificador não pega tracker **desalinhado
   do rebanho** (ex.: Sete Lagoas 2 com 16 trackers flat em 0° e alvo=0 enquanto 40 estão a -53°
   → disparidade vs próprio alvo = 0 → "normal"). Proposta: novo critério "desalinhado" =
   |atual − mediana_da_planta| > ~15°. **Ainda não implementado.**
9. **Logos 404** em `static/logos/*.png` (cosmético; há fallback de emoji).

---

## 11. COMO RODAR / OPERAR

- **Subir:** `Iniciar Dashboard.bat` (ou `python app.py` na pasta) → http://localhost:5050.
- **Atualizar dados:** botão "↻ Atualizar" (zera cache, refaz todas as fontes).
- **Trocar token expirado:** o da Plataforma vai pelo bookmarklet (`POST /api/pv/trackers/token`,
  grava no `tokens_runtime.json` e vale na hora); os demais, editar o `tokens.txt`/`.env`
  (`SUNOP_TOKEN`/`AXIS_TOKEN`) e reiniciar.
- **Reautenticar Gmail (2C):** `python "...\app_gridco.py" --auto` num console → abrir a URL
  impressa no navegador → login Google → token salvo.
- **Recarregar planilhas (Check/Equipamentos):** automático no mtime; ou botão Atualizar (force=1).

---

## 12. MÓDULOS/ENDPOINTS PRINCIPAIS (mapa rápido no app.py)

- Auth/helpers PV: `get_token`, `get_plants`, `nome_usina`, `parse_cj`, `_ipv_ativas`, `_pick_irr`.
- Cadastro: `load_check_spreadsheet`, `load_equip_power`, `_pot_inv`.
- Visão geral PV: `/api/data`, `/api/plant/<id>`, `/api/etm`, `/api/etm/analise`.
- SunOp: `/api/sunop/{data, plant/<n>, etm/analise, trackers, trackers/<n>, .../chart}`.
- SolarEdge: `/api/solaredge/data`, `process_site_solaredge`.
- PG: `/api/pg/{data, plant/<id>, etm/analise, geracao, trackers, trackers/<id>, .../chart}`.
- 2C/Owen: `/api/owen/{etm/analise, strings/data, strings/plant/<u>, trackers, .../chart}`.
- PR por inversor: `/api/pv/pr`, `/api/pv/pr/<id>`.
- Curva de strings (plataforma): `/api/spv/{usinas, usina/<id>, nota, pdf}`.
- Tracker watch (backend pronto, sem UI): `/api/tracker-watch*` + `tracker_watch.py`.

---

_Para histórico detalhado de CADA decisão/fix, ver `project-pv-dashboard.md` na memória da IA
(`C:\Users\Levi Maia\.claude\projects\C--Users-Levi-Maia\memory\`)._
