# Fontes de tracker e autenticação

Handoff de integração. Como cada fonte entrega a **curva de ângulo dos trackers** e como
autenticar. A régua de classificação é a mesma para todas (ver
`parametros-trackers-parados.md`).

> **Segredos:** este documento NÃO contém valores de token/senha — só o **local** de onde
> sair cada um. Os valores vivos ficam em `plataforma/tokens_runtime.json` (estado, escrito
> pelo app) e as sementes em `tokens.txt` / `.env` (raiz). Ver §Tokens no fim.

As 5 fontes de tracker (rótulo interno → nome): `pv → API PV`, `pg → Thopen`,
`sunop → Athon`, `axis → Axis`, `owen → 2C`.

---

## 1. API PV / Plataforma (fonte `pv`)

Duas APIs distintas do mesmo fornecedor (pvoperation):

### 1a. Curva de TRACKERS (o que importa aqui)
- **Base:** `https://apiplataforma.pvoperation.com`
- **Header:** `x-auth-token-update: <TOKEN_PLATAFORMA>`
- **Endpoints:**
  - `GET /v2/usinas/trackers` — estado atual dos trackers por usina
  - `GET /v2/usinas/trackerschart?...` — curva (POSAT) do dia
  - `GET /v2/inversores/view` — inversores (contexto)
- **Token:** chave `plat`. **Manual** (tem CAPTCHA + MFA, **não** auto-renova). Vale **~7 dias**
  (medido no `exp` do próprio JWT). O mesmo token serve trackers e combiner box.
  - Renovar: bookmarklet de 1 clique **ou** `POST /api/pv/trackers/token` com `{"token":"..."}`
    (relido na hora, sem reiniciar). Origem do token: `plataforma.pvoperation.com` → F12 →
    header `x-auth-token-update`.
  - Quando vence: combiner recebe `HTTP 401`; há disjuntor que abre no 1º 401.

### 1b. API PV Operation (strings / inversores / ETM — contexto)
- **Base:** `https://apipv.pvoperation.com.br` (constante `BASE_URL`)
- **Header:** `x-access-token: <TOKEN_APIPV>` (token **por conta/planta**, `_pv_token_for(pid)`)
- **Endpoints:** `GET /plants`, `POST /day_inverter`, `GET /plant_devices`, `POST /day_meteo`
- Curva de string por `Ipv`; trackers vêm da API 1a (Plataforma), não daqui.

---

## 2. SunOp / Athon (fonte `sunop`, instância `gridco`)

- **API de configuração:** `https://gridco-api.sunop.net/api`
- **Serviço de dados:** `https://gridco-api.sunop.net/data`
- **Dois tipos de token:**
  | Tipo | Header | Chave runtime | Validade | Uso |
  |---|---|---|---|---|
  | WEB (login) | `Authorization: JWT <tok>` | `sunop` | ~7 dias, **auto-renova** | `/api` (config, metadata via /api) |
  | API | `Authorization: Bearer API <tok>` | `sunop_api` | ~6–12 meses | `/data` (analog_values, /v2/metadata) — preferido |
  - O serviço `/data` prefere o token de **API**; sem ele, cai no header WEB.
  - O token WEB funcional tem claim `sub` **numérico** + `is_admin`; tokens com `sub` textual
    (ex. "Levi") são **rejeitados** no WEB (mas valem como token de API).
- **Renovação (WEB):** `GET /api/refresh_token` (exige o token atual **ainda válido**) →
  novo token; validação por `GET /api/check_token`. Keep-alive a cada 6 h. Semente: `SUNOP_TOKEN`.
- **Trackers:** `analog_values` traz `POSAT` (ângulo atual) e `POSAL` (alvo) por tracker;
  metadata da planta em `/data/v2/metadata`. Nome da planta ≈ code-base (ex. TIM100).

---

## 3. Axis SunOp (fonte `axis`, instância `axis`)

Mesma API/lógica do SunOp, outra instância:
- **Config:** `https://axis-api.sunop.net/api` — **Dados:** `https://axis-api.sunop.net/data`
- **Tokens:** chaves `axis` (WEB, ~24 h, auto-renova) e `axis_api` (API). Semente `AXIS_TOKEN`.
- Poucas usinas (ex.: PE III, Ponto Belo). Enquanto não gerarem token de API lá, usa o header WEB.

---

## 4. Thopen / PostgreSQL (fonte `pg`)

- **Banco:** PostgreSQL (AWS RDS), `PG_DB = powerplants`.
- **Conexão (env):** `PG_HOST`, `PG_PORT=5432`, `PG_DB`, `PG_USER`, `PG_PASSWORD`.
- **Trackers:** ler da tabela **crua** `public.raw_tracker` (campo `json_data`) — hypertable
  indexada, ordens de grandeza mais rápida que as views `dbt.*` (que congelam).
- **Fuso (armadilha):** `public.raw_*` é `timestamptz` (UTC). Converter **sempre** com
  `AT TIME ZONE 'America/Sao_Paulo'`, senão o filtro de janela pode zerar silenciosamente.

---

## 5. 2C / Owen (fonte `owen`)

- **Sem API/token.** Os dados chegam por **e-mail** (Excel diário) e são gravados num banco
  local por dia: `2C_historico/AAAA-MM-DD`.
- **Trackers:** curva de ângulo lida do Excel 2C; alinhada à régua do SunOp.

---

## Tokens — arquivos, precedência e renovação

**Dois arquivos, dois donos:**
- `tokens.txt` (raiz) — **semente**, formato `CHAVE=VALOR`, editado por gente, carregado no
  ambiente no boot. Chaves relevantes: `SUNOP_TOKEN`, `AXIS_TOKEN`, `PLAT_TOKEN`,
  `PG_HOST/PG_PORT/PG_DB/PG_USER/PG_PASSWORD`, `PV_USERNAME/PV_PASSWORD`.
- `plataforma/tokens_runtime.json` — **estado**, escrito pelo app ao renovar. Chaves:
  `plat`, `sunop`, `sunop_api`, `axis`, `axis_api`, `se_cookie` (+ `_atualizado`).
  Relido a cada uso.

**Precedência:** o app escolhe entre a semente (`.env`/`tokens.txt`) e o runtime **pela
maior validade** (`exp` do JWT) — `_sunop_token_inicial` / `_plat_token`. A semente é só
boot; não inverta (semente velha "sequestrando" a renovação já causou incidente).

**Renovação:**
- SunOp / Axis / SolarEdge: **automática**.
- API PV / Plataforma (`plat`): **manual** (CAPTCHA/MFA) — `POST /api/pv/trackers/token` ou bookmarklet.
- Colar pela tela (qualquer um): `POST /api/tokens/<fonte>` com `fonte ∈ {plat, sunop, axis}`
  (atrás do gate de senha). Recusa token vencido.
- **Status de todos:** `GET /api/tokens`.

**Nota de robustez (04/08):** `get_sunop_token` agora **relê o `tokens_runtime.json`** quando
o token em memória venceu e o refresh falha — assim um token colado pela tela passa a valer
sem reiniciar o processo (antes só valia após restart).

---

## Como o outro app deve pegar os VALORES dos tokens

Os valores vivos estão em `plataforma/tokens_runtime.json` (JSON, chaves acima). Opções:
1. Ler esse arquivo direto (se o outro app roda na mesma máquina/servidor).
2. Consumir `GET /api/tokens` da plataforma (status/validade; atrás do gate de senha).
3. Pedir que eu **escreva um arquivo de config** no formato que o outro app espera, com os
   valores reais preenchidos, num caminho que você indicar (fora do git). — sob demanda.
