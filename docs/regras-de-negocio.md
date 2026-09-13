# Regras de Negócio & Detalhes Funcionais — Dashboard O&M
> Detalhamento das regras de análise (string ativa, ETM, trackers), planilha Check e estado
> compartilhado. Última atualização: 2026-06-08.
>
> ℹ️ A visão geral mais recente da arquitetura (incluindo a 6ª fonte, **PV Plataforma /
> Curva das strings**) está em [arquitetura.md](arquitetura.md).
>
> 📚 Documentação relacionada: [Índice](README.md) · [Arquitetura](arquitetura.md) ·
> [API PV Operation](api-pv-operation.md) · [Coleta SunOp](coleta-sunop.md)

---

## 1. O QUE É
Dashboard web (Flask) de monitoramento de O&M solar que reúne, num só lugar, **strings
(ativas × esperadas)**, **ETM (estações meteorológicas — curva POA/GHI/POA-RI)**,
**geração diária** e **trackers** de **5 fontes**:

| Aba (fonte) | Marca/Plataforma | Strings | ETM | Geração | Trackers |
|---|---|---|---|---|---|
| **API PV** | PV Operation | ✅ | ✅ curva (day_meteo, só hoje) | — | — |
| **Banco PG** | PostgreSQL (warehouse dbt) | ✅ | ✅ curva (banco) | ✅ período (export Excel) | — |
| **API SunOp** | Automa/DNV | ✅ | ✅ curva (analog_values) | — | ✅ alvo/atual + curva |
| **API SolarEdge** | RenoGrid | ✅ | ❌ | — | ❌ |
| **2C (Email)** | CSV SCADA via Gmail | ✅ | ✅ curva | — | ✅ |

Roda em **http://localhost:5050**. Ordem das abas: **API PV → Banco PG → API SunOp →
API SolarEdge → 2C**.

---

## 2. ONDE ESTÁ / COMO RODAR
Pasta: **`C:\Users\Levi Maia\Desktop\Projeto Strings\pv_dashboard\`**
- **Rodar:** `Iniciar Dashboard.bat` (ou `python app.py`). Python 3 + `requirements.txt`.
- **Parar:** fechar o terminal ou matar a porta 5050.
- Backend: **`app.py`** (~3200 linhas, tudo aqui). Frontend: **`templates/index.html`**
  (1 arquivo, HTML+CSS+JS inline, fonte Inter).
- **Caminhos relativos** (portátil), exceto o Check (online) e os CSVs do 2C (caminhos fixos).

### Arquivos
```
app.py                          backend Flask (todas as 5 fontes + endpoints)
templates/index.html            frontend completo
Check Diário ... .xlsx          cópia local (fallback) — a MASTER é a online (ver §4)
pg_password.txt                 senha PostgreSQL [gitignored]
se_credentials.txt / tokens_runtime.json  SolarEdge (Cognito) [gitignored]
ufv_state.json                  check/comentário/acompanhamento/MANUTENÇÃO (estado da equipe)
owen_accum.json                 acervo do dia da fonte 2C/Email (acumulador, reseta diário)
docs/regras-de-negocio.md       este doc
docs/coleta-sunop.md            recipe da coleta SunOp (EPD + POA/GHI/POA-RI)
collect_energy.py / coletar_geracao_hoje.py  scripts standalone (API PV)
```

---

## 3. AS 5 FONTES (endpoints, auth, quirks)

### 3.1 API PV Operation
- Base `https://apipv.pvoperation.com.br/api/v1`. Auth `POST /authenticate` → header `x-access-token`.
- `GET /plants` · `POST /plant_devices {id}` (nomes inversor) · `POST /day_inverter {id}`
  (strings `Ipv1..N`) · `POST /day_meteo {id}` (ETM intradiário do dia, POA=`IrPOA/Ir/Ir1`,
  GHI=`IrGHI`) · `POST /custom_query {id,data_type:"energy",...}` (energia, com histórico).
- `fetch_all()` = 3 passadas (8 workers → retry 4 → sequencial) contra throttling.
- **Gotcha:** `device_name` às vezes vem com **espaço no fim** (`'INVERSOR 04 '`) → `.strip()` em `dev_names`.
  Inversores "...OLD" filtrados por `_EXCLUIR_CONTEM`.
- **Agrupar ETM por UFV:** SKIDs da mesma UFV (mesmo "(NNN)" no nome) viram 1 card (melhor skid).

### 3.2 Banco PG (PostgreSQL "powerplants")
- Conexão via `.env` (`PG_HOST`, `PG_USER`, `PG_PASSWORD`...). ⚠️ **Host com IP público +
  senha fraca** (risco grave — ver §10).
- Schema `dbt`: `stg_inverter_string_data` (corrente/string), `stg_inverter_analogic_data`
  (`daily_active_energy`=kWh acum/dia/inversor), `stg_weather_station_analogic_data`
  (`irradiance_poa/ghi`, 5min), `int_inverter_power_plant_daily_energy_timeseries`
  (geração total/usina/dia, histórico desde 10/12/2025). `public.tb_power_plants` (id→name).
  Medidor `stg_meter_analogic_data` VAZIO.
- Snapshot único (resumo + drill = mesma query) → total da usina = soma dos inversores.
- **Aba "📊 Geração":** período selecionável → geração (MÁX EPD por inversor, somado) + IPOA/GHI
  (`SUM(GREATEST(irr,0))/12000` = integração 5min). Export Excel. Endpoints `/api/pg/geracao[/export]`.

### 3.3 API SunOp (Automa/DNV)
- Config `https://gridco-api.sunop.net/api` · Dados `.../data`. Header `Authorization: JWT <token>`.
- ⚠️ **TOKEN EXPIRA ~7 dias** e o refresh automático NÃO renova (a API exige token válido p/ renovar).
  Quando o SunOp parar de trazer dados: pegar um **cURL fresco** no portal (DevTools→Rede) e
  trocar `SUNOP_TOKEN` no `.env`. Blindado: se
  expirar, `ensure_sunop_meta` não crasha mais (degrada gracioso).
- `GET /api/plants` (10 plantas GD) · `GET /data/v2/metadata?plant=&size=6000` (paths) ·
  `POST /data/v2/last_values {pathnames}` (só último valor, lotes 500).
- **🔑 HISTÓRICO (curva do dia):** `POST /data/v2/analog_values` (descoberto via DevTools) —
  query `?source=Historical&start_time=&end_time=&use_plant_timezone=true&fill_missing=false`,
  corpo `{pathnames:[...]}`. Serve curva de QUALQUER medida (POA/GHI/POA-RI, tracker POSAL/POSAT,
  EPD…), inclusive dias passados. Helper `_sunop_analog_history()`.
- Paths: strings `PLANT.INV_N.MEDIDAS.STR.I_PVx`; ETM `PLANT.ESTM[_n].{POA|GHI|POA_R}.IRAD`;
  tracker `PLANT.TRK_N.MEDIDAS.{POSAL=alvo|POSAT=atual|STRD_DEV}` + `STATUS.WORKSTATE`;
  energia inversor `PLANT.INV_N.MEDIDAS.EPD`.
- ETM agora tem **curva real** (sparkline + checks). POA-RI (POA_R) na mini-curva (~3/12 estações têm).
- O "API token" (`Authorization: API`) que o usuário testou NÃO serve (459/401 em tudo) — usa o JWT de sessão.

### 3.4 API SolarEdge (RenoGrid)
- Plataforma SolarEdge (`monitoring.solaredge.com/one`). 7 UFVs (Xavantina 1/2, Colider 1/2,
  Crateús, Nobres, Elias Fausto). **Auth automática AWS Cognito SRP** (`pycognito`), cookie
  `se_monitoring_auth` renovado sozinho (~24h). API interna: `searchSites`, `.../devices`,
  `.../generate-chart`. String ativa = potência > 0 W. **Sem ETM, sem trackers.**

### 3.5 2C (Email) — CSV SCADA via Gmail  [a mais nova]
- 4 UFVs: **ARA** (Araputanga), **IPX** (Ipixuna do Pará), **STL** (Sete Lagoas; "Sete Lagoas 2" só no Fracttal), **TUP** (Tupi Paulista).
- Baixador externo `Desktop\Projetos e-mail\1-Automatizador\app_gridco.py` (Gmail OAuth) salva CSVs em
  `Desktop\Projetos e-mail\{ETM,Strings,Trackers}\`.
- **E-mails INCREMENTAIS** (4/dia): 9h traz 06→09, 12h traz 09→12, 15h traz 12→15, 18h traz 15→18.
  O baixador SOBRESCREVE o arquivo → por isso há **acumulador persistente** (`owen_accum.json`):
  `_owen_refresh()` mescla os CSVs no acervo do DIA (dedupe ponto+timestamp), thread background a
  cada 10 min (captura cada janela antes do overwrite), reset na virada do dia. ⚠️ servidor
  precisa estar de pé quando cada janela chega.
- CSV formato LONGO latin-1: `Point name,Time,Value,Rendered,Annotation`. Point name codifica
  UFV+dispositivo+medida. ETM `<UFV>_ETM_A - ..._GHI/POA`; Strings `..._Inv_<N.M>_STR_Corrente PV<XX>`;
  Tracker `..._TRK_<N.M>_MED_Ângulo Alvo|Posição Atual`.
- Endpoints `/api/owen/{etm/analise, etm/chart, strings/data, strings/plant/<u>, trackers, trackers/<u>, trackers/<u>/chart}`.
- Esperado das strings vem do **Check** pela chave SUPERVISÓRIO (Usina Sup=código "ARA",
  Equip Sup=tag "ARA_Inv_1.1"), igual API PV/SunOp — SEM fallback físico (None se não cadastrado).
  Nome da Usina vem de `USINA_DISPLAY` (Check), com fallback fixo. Internamente a fonte se chama "owen".

---

## 4. PLANILHA "Check Diário" — agora ONLINE
- **MASTER (online, a que o dashboard usa):**
  `C:\Users\Levi Maia\OneDrive - GRID CO\Grid Co_ - 4. O&M\6.Gerencial\4. Gestão à vista\1. Banco de Dados\Check Diário - Geração e ETM.xlsx`
- `STRINGS_PATH` aponta pra online (env `CHECK_PATH`); **fallback** pra cópia local se OneDrive offline.
- **Hot-reload:** `maybe_reload_check()` compara `mtime` e recarrega sozinho — o botão **↻ Atualizar**
  chama `/api/check/reload` antes de re-buscar; também recarrega em qualquer `force=1` (before_request).
  NÃO precisa reiniciar o servidor ao editar a planilha.
- Abas usadas: **"Strings 2"** (fonte do esperado: coluna "Número de Strings ativas", + mapa
  Usina/Equip Supervisório ↔ display + Full O&M) e **"Strings"** (fallback do esperado por display).
- Globais: `ESPERADO_INV[usina_sup][equip_sup]`, `EQUIP_NAMES`, `USINA_DISPLAY`, `ESP_BY_DISPLAY`,
  `FULL_OM`. Hoje: ~1597 inversores, 128 usinas c/ esperada, 115 Full O&M. ARA/IPX/STL/TUP já
  cadastradas (ex.: `ESPERADO_INV['IPX']['IPX_Inv_1.1']`=17 — note: esperado ≠ nº físico de strings).

---

## 5. REGRA DE "STRING ATIVA" (API PV + SunOp + 2C)
Helper `_ipv_ativas(correntes, em_janela)`:
- **DENTRO de 09:00–15:00** (sol forte): ativa se `corrente > 1 A` (`STRING_JANELA_MIN_A`).
- **FORA da janela**: ativa se `corrente > 0 E >= 30% da média das strings produzindo` (`STRING_ATIVA_FRAC`).
- Valor 0 sempre inativo. (Evolução: 0,5A fixo → média−4A → bimodal quebrou → 30% → janela 9-15.)
- PG = 0,5 A fixo; SolarEdge = >0 W (não usam essa regra).

---

## 6. ETM (pré-análise, cards)
- `_diagnostico_etm(series)` compartilhado (PV/PG/SunOp/2C): flags **Sem comunicação** (>30min),
  **POA zerado** (pico<20 em 9-15h), **GHI>POA** (>60% do tempo), **Quedas de POA**. Sparkline + severidade.
- Cards: clique abre gráfico do dia (Plotly). API PV ordenado: Sem comunicação → Grave → Atenção → Normal.
- **Manutenção:** cada card tem "🔧 Em manutenção" (borda azul, salvo em `ufv_state.json`, compartilhado).

---

## 7. TRACKERS (SunOp + 2C) — análise por CURVA do dia
Drill-down por usina (`_sunop_trackers_plant_curva` / `_owen_trackers_analise`):
- **PARADO** (🔴 vermelho, grave): amplitude do ângulo no dia < 15° enquanto a mediana dos vizinhos
  se moveu > 30° (peer-based → funciona até sem alvo, ex.: MAB100 que não tem POSAL).
- **DESVIO** (🟠 laranja): disparidade ATUAL − mediana da planta > 5° (fora do ângulo agora).
- **ATRASO** (🟡 amarelo): disparidade MÁX do dia − mediana > 10° (saiu muito mas voltou; relativo
  à mediana p/ descontar o ruído estrutural ~11°).
- **Curva do dia INLINE** (botão "📈 Curva do dia"): expande gráfico entre a usina e os chips;
  chips são FILTRO (clica liga/desliga a curva); botões Bons/Ruins/Todos. Linhas coloridas por
  status; alvo preto tracejado. Painel de trackers COMPARTILHADO SunOp/2C (`_trkBase()` por aba).
- UFV sem alvo (POSAL) → card mostra "planta sem ângulo alvo".

---

## 8. ESTADO COMPARTILHADO (`ufv_state.json`)
Salvo no servidor, compartilhado pela equipe: `verified` (check), `comments`, `tracking`
(strings em acompanhamento), `manutencao` (ETM em manutenção). Endpoints `/api/state[...]`.

---

## 9. GOTCHAS / ARMADILHAS (importante)
- **SunOp token expira ~7 dias** → trocar o JWT (não trava mais, mas para de trazer dados).
- **Windows cp1252:** `print()` com char fora do cp1252 (ex.: seta "→") crasha — usar ASCII em prints.
- **`.gc-btn-sm` tem `display:none`** por padrão (só some em barra) → botão em célula de tabela
  precisa de `style="display:inline-block"` senão fica invisível.
- **Nomes com espaço** da API (ex.: "INVERSOR 04 ") quebram match → `.strip()`.
- **Esperado SEMPRE do Check** (chave supervisório), nunca contagem física — senão mascara falha.
- **Flask template cache:** com debug off, mudou index.html → REINICIAR o servidor (e Ctrl+F5 no browser).

---

## 10. SEGURANÇA
1. 🔴 PostgreSQL com IP público + senha fraca → trocar senha + fechar firewall. MAIS URGENTE (pendente).
2. ✅ Credenciais migradas do código para o `.env` (gitignored) — PV_*, SE_*, PG_*, SUNOP_TOKEN,
   OWEN_ROOT, CHECK_PATH. Seguem em texto plano no disco; ver `.env.example` para o modelo.

---

## 11. STACK
Python 3 · Flask · pandas/openpyxl · psycopg2 (PG) · pycognito (SolarEdge SRP) · requests ·
Plotly.js (gráficos) · estado/acumuladores em JSON. Frontend: 1 HTML (CSS+JS inline).

---

## 12. PRÓXIMOS PASSOS SUGERIDOS
1. 🔴 Segurança do PostgreSQL (§10).
2. Cadastrar/conferir as 4 UFVs do 2C no Check (esperado por inversor) — já parcialmente lá.
3. Auto-refresh do token SunOp (capturar via login, se viável) ou alerta quando expirar.
4. Coleta agendada (Agendador do Windows) p/ manter o dashboard de pé o dia todo (acumulador 2C).
5. Histórico de ETM/geração acumulado por dia (hoje a maioria é só o dia corrente).
