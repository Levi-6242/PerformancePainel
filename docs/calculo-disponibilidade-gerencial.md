# Cálculo de disponibilidade do Gerencial — do Fracttal ao número

Como a aba **Gerencial → Disponibilidade** (`/gerencial/disponibilidade`) produz o percentual de
disponibilidade por usina e por cliente: quais APIs são acionadas, com que parâmetros, e a conta
que transforma OS do Fracttal em horas perdidas.

Este documento é a referência de **runtime e API**. A metodologia e as decisões de negócio (por que
P75, por que só duas famílias, etc.) estão em [`disponibilidade-por-os.md`](disponibilidade-por-os.md).
O código-fonte da conta é `plataforma/disponibilidade.py`; o disparo e a publicação, `plataforma/app.py`.

---

## 1. O número, em uma frase

> **Disponibilidade da usina = 100 × (1 − horas perdidas ÷ horas solares do período)**

- **Horas solares** = janela **06h–18h** (12 h por dia) × dias do período.
- **Horas perdidas** = tempo em que a usina (ou parte dela) esteve parada, segundo as **OS do
  Fracttal** dos tipos-alvo, **pesado pela fração de potência (kWp)** que a OS derrubou.
- Só entram **usinas Full O&M** (onde a Grid Co. faz a manutenção completa).

Exemplo: uma cabine de 500 kWp de uma usina de 2.000 kWp parada por 4 h solares num mês de 30 dias
perde `(500/2000) × 4 = 1,0` hora-equivalente. Disponibilidade `= 100 × (1 − 1,0 / (12×30)) = 99,72 %`.

---

## 2. Arquitetura: quem calcula e quem serve

O cálculo é **caro** (varre ~140 páginas do Fracttal + SQL do mês). Por isso ele roda **só no worker**,
publica o resultado num arquivo, e o **web só lê** — nunca calcula por requisição.

| Papel | Processo | Função | O que faz |
|---|---|---|---|
| Calcula | `worker.py` | `_frac_disp_loop` (`app.py:19281`) | No boot e a cada **30 min** (`FRAC_DISP_TTL`): varre o Fracttal, calcula os 2 meses, grava `frac_disp_index.json` |
| Publica | worker | `_frac_disp_recalcular` (`app.py:19234`) | Escrita **atômica** (`.tmp` → `os.replace`). Varredura vazia **não** sobrescreve índice bom |
| Serve | `app.py` (web) | `_frac_disp_dados` (`app.py:19265`) | Relê o arquivo quando o `mtime` muda; devolve o payload pronto. **Nunca calcula** |

Arquivo do índice: `plataforma/cache/frac_disp_index.json` (`_FRAC_DISP_FILE`). Estrutura:
`{"ts": <epoch>, "meses": {"2026-09": {payload...}, "2026-08": {payload...}}}`.

Se o worker ainda não publicou (boot recém-feito), a API responde `{"quente": false}` e a tela mostra
o estado frio, sem travar.

---

## 3. Como a API do Fracttal é acionada

Toda a leitura de OS vem da **API REST do Fracttal**.

### 3.1 Autenticação — OAuth2 client_credentials

`get_fracttal_token()` (`app.py:18456`):

```
POST https://app.fracttal.com/oauth/token
  grant_type=client_credentials
  client_id=<FRACTTAL_CLIENT_ID>
  client_secret=<FRACTTAL_CLIENT_SECRET>
→ { "access_token": "...", "expires_in": 3600 }
```

- Credenciais vêm do ambiente: `FRACTTAL_CLIENT_ID`, `FRACTTAL_CLIENT_SECRET`. Se faltarem,
  `FRACTTAL_ON = False` e o cálculo nem roda.
- O token é **cacheado** em memória até `exp − 60 s`; renova sozinho.

### 3.2 Chamada base

`_frac_get(ep, **params)` (`app.py:18472`):

```
GET https://app.fracttal.com/api/<ep>
  Authorization: Bearer <token>
  Accept: application/json
```

- **Base**: `FRACTTAL_BASE` = `https://app.fracttal.com` (env `FRACTTAL_BASE_URL`).
- **Robustez**: até 3 tentativas. `401` → invalida o token e re-autentica; `406` (rate limit,
  **200 req/min**) → dorme o `ratelimit-reset` do header e retenta. Qualquer outra falha → `None`.

### 3.3 A varredura das OS

`_frac_disp_sweep(limite_dt)` (`app.py:19073`). É a **única** chamada de dados da disponibilidade:

```
GET /api/work_orders/?start=<n>&limit=200
```

- Pagina com `start` (incrementado por `len(rows)`) e `limit=200`, na ordem **decrescente por data
  de criação** (padrão do endpoint). Para quando a `creation_date` da última linha fica **antes do
  limite**, ou quando não vêm mais linhas, ou no teto de 40.000 registros.
- **Não filtra por tipo, status nem data na API.** Puxa o fluxo recente inteiro e filtra **localmente**
  (na função `calcular`). Os únicos parâmetros enviados são `start` e `limit`.
- **Limite da varredura**: `menor mês-alvo − 45 dias` (`FRAC_DISP_MARGEM_D`). A margem existe porque
  uma OS **criada** semanas antes pode ter o **evento** dentro do mês. São ~140 páginas para 2 meses.
- De cada work order o sweep guarda só os campos que a conta usa, agrupados por `wo_folio`
  (`_DISP_CAMPOS_TASK`, `app.py`):

  `tasks_log_task_type_main`, `id_status_work_order`, `event_date`, `date_maintenance`,
  `final_date`, `wo_final_date`, `code`, `items_log_description`, `groups_1_description`,
  `description`, `created_by`, `personnel_description`, `user_assigned`.

Resultado: `wos = {folio: [tarefas reduzidas]}`.

---

## 4. As outras duas fontes (não-Fracttal)

| Fonte | Função | Papel | Cache |
|---|---|---|---|
| **BD_Performance, aba Equipamentos** | `_disp_equip_linhas` (`app.py:19036`) | Estrutura e **pesos**: kWp por usina/cabine/inversor, cliente, Full O&M, Nº de inversores, nome supervisório e nome Fracttal | 12 h (`FRAC_CODE_TTL`) |
| **PostgreSQL (banco)** | `_disp_geracao` (`app.py:19095`) | Geração diária por usina, o **juiz** contra parada-fantasma | por recálculo |

A aba Equipamentos é lida de `bases/` (`pd.read_excel(..., sheet_name="Equipamentos", header=2)`) e vira
o **catálogo** de usinas (`montar_catalogo`), com a potência de cada nível hierárquico.

A geração casa o nome do PostgreSQL (`(289) Nome`) com o do BD (`Nome (152)`) tirando o número entre
parênteses; leitura marcada como não-confiável é **descartada**.

---

## 5. Da OS crua ao evento — `consolidar_os` (`disponibilidade.py:292`)

Cada folio do Fracttal passa por um filtro duro antes de contar:

**Tipos que contam** (`tasks_log_task_type_main`):

| Família | Tipos | Constante |
|---|---|---|
| **Queda** | Religamento, Religamento Remoto | `TIPOS_QUEDA` |
| **Equipamento** | Corretiva Emergencial | `TIPOS_EQUIP` |

- Sem nenhum tipo-alvo → a OS **nem é listada** (fora do universo). *Corretiva simples ficou de fora
  de propósito* (decisão do Levi, 29/08 — ver o doc de metodologia).
- Quando a OS tem os dois, a **origem** é `queda` (a usina caiu; a corretiva veio junto).

**Status** (`id_status_work_order`):

- `4` (cancelada) → **excluída**.
- `0, 1, 5, 6` → OS **aberta**.

**Datas** (as regras duras):

- **Início** = `min(event_date | date_maintenance)`, exigindo ano corrente e `≤ agora`.
- **Fim** = `max(final_date)`; só cai no `wo_final_date` (carimbo administrativo da WO) se **não houver
  nenhum** `final_date` — e marca uma flag, porque esse carimbo pode ser tardio.
- Fim **antes** do início: se por `≤ 1 h` (carimbo relâmpago) → duração 0; se por mais → descarta o fim.
- **Sem início válido** → excluída. **Concluída sem fim válido** → excluída.
- **Aberta sem fim** → conta **0 h** no cálculo, mas entra no **cenário das abertas** (§8), que estima
  quanto ela somaria se for parada real.

---

## 6. Escopo — o que a OS derruba — `escopo_os` (`disponibilidade.py:367`)

O escopo é resolvido pelo **ativo** (`code`), nunca por texto solto, e devolve uma lista
`[(usina, nível, chave, kWp)]`:

| Padrão do `code` | Nível | kWp derrubado |
|---|---|---|
| `...-INVR<n>` / `...-DINV<n>` | inversor | kWp daquele inversor (ou média da usina, com flag) |
| `...-{CABN\|SKID\|QGBT\|PECN\|DTRF}<n>` | cabine | kWp da cabine/UG (ou média; ou a usina inteira se não houver cabine no BD) |
| `AAA999`, vazio, ou item ≈ site | usina | kWp da usina inteira |

- O site (`groups_1_description`, "g1") é resolvido para a(s) usina(s) do BD (`resolve_g1`). Site sem
  correspondência → excluída, com o motivo em `flags`/`excl`.
- **Grid Co. / terceiros sem contrato** → excluída.
- Sites **agrupados** ("Aparecida do Taboado 1 e 2"): há réguas para identificar a usina pelo número da
  cabine (quando cada usina tem 1 cabine) ou por pista no texto da descrição; sem pista, atribui à 1ª
  usina e marca "conferir".

---

## 7. O juiz da geração — `_dias_desmentidos` (`disponibilidade.py:526`)

Antes de contar um dia como perdido, a **geração real** pode desmenti-lo. Uma OS longa fechada com
atraso dizia a usina parada enquanto ela gerava (casos Parelhas e Marialva, 30/08).

- **Normal da usina** (`_normal_kwh_kwp`) = **P75** dos dias com dado, em kWh/kWp — só vale se `≥ 4,5`
  (`GER_PLENO_KWH_KWP`, usina praticamente plena); senão não se julga nada.
- **Fatia perdida do dia** = fração de potência afetada × fração do dia solar coberto. Se `< 0,30`
  (`GER_FRAC_MIN`), a geração não tem resolução para julgar — pula.
- Se a usina **produziu mais** que `(1 − fatia) × normal + 15 %` (`GER_TOLERANCIA`), aquele dia é
  **exonerado**: não conta como parada, e a OS ganha a flag e o registro em `dias_exonerados`.
- Dia **sem dado** nunca exonera — ausência de prova não é prova.

---

## 8. A conta — `_varrer` + `calcular` (`disponibilidade.py:482` e `:564`)

1. Cada evento vira `{usina, nível, kWp, ini, fim}`. `_varrer` monta a **linha do tempo por usina**,
   com hierarquia **usina > cabine > inversor** e **teto de 100 %** da usina (dois eventos simultâneos
   não passam de 100 %).
2. Para cada intervalo entre bordas de eventos:
   - **fração afetada** = `kWp afetado ÷ kWp da usina` (ou 100 % se o nível for a usina inteira);
   - **horas solares** do intervalo = interseção de `[ini, fim)` com 06h–18h, dia a dia;
   - `h_eq += fração × horas` (hora-equivalente perdida); `kWh += kWp afetado × horas` (perda à
     **potência nominal**, um teto).
3. **Disponibilidade da usina** = `100 × (1 − Σ h_eq ÷ (12 × n_dias))`.
4. **Decomposição por origem**: a mesma varredura roda 3×: total, só **queda**, só **equipamento**.
   As duas famílias **não somam** o total (o teto de 100 % capa eventos simultâneos).
5. **Por cliente**: ponderado por potência —
   `100 × (1 − Σ(kWp × h_perdidas) ÷ (Σ kWp × 12 × n_dias))`.
6. **Diário** (o mapa usina × dia): por usina, por dia, `h_eq`, `disp`, `kWh` e a decomposição
   queda/equipamento (o card da célula).
7. **Cenário das abertas**: as OS abertas sem fim contam 0 h, mas o payload traz quanto elas somariam
   (`kwh_cenario`, `h_cenario`) se forem parada real até agora — o aviso amarelo da tela.

**Janela e período** (`_disp_meses_alvo`, `app.py:19063`): dois meses — o **corrente** (do dia 1 até
**D-1**, fim exclusivo) e o **anterior** (cheio). No dia 1 o mês corrente vai vazio de propósito
(nenhum dia fechado). `SOL_INI_H = 6`, `SOL_FIM_H = 18` → 12 h/dia.

**Recorte do parque** (`calcular`): entram só usinas com `Full O&M` começando por "S", com potência no
BD, cadastradas no Fracttal, fora de `PARQUE_EXCLUI` (`AP. do Taboado`, linha agregada que duplicaria kWp).

---

## 9. Endpoints da plataforma (o que o front consome)

| Rota | O que devolve |
|---|---|
| `GET /gerencial/disponibilidade` | A página (`disponibilidade.html`). `gerencial_disponibilidade`, `app.py:19292` |
| `GET /api/gerencial/disponibilidade?mes=YYYY-MM&cliente=X` | Payload pronto do mês. `api_gerencial_disponibilidade`, `app.py:19298` |
| `GET /api/gerencial/disponibilidade/export?mes=&cliente=` | Excel do mapa diário usina × dia. `app.py:19322` |

Parâmetros do JSON:

- `mes` — `YYYY-MM`. Ausente → o mês mais recente do índice.
- `cliente` — filtra `usinas`, `diario`, `oss` e `cenario_abertas` por cliente (case-insensitive).
- Sem índice publicado → `{"quente": false, "meses": [...]}`.

Payload (quente):

```
{ "quente": true, "mes": "2026-09", "meses": [...], "atualizado": <epoch>,
  "periodo": {"ini","fim","dias"},
  "usinas":  [ {usina, cliente, pot_kwp, disp, h_perdidas, kwh,
                disp_queda, h_queda, kwh_queda, disp_equip, h_equip, kwh_equip, n_os, ...} ],
  "clientes":[ {cliente, kwp, disp, kwh, disp_queda, disp_equip, n_os, n_usinas, abaixo99} ],
  "diario":  { "<Usina>": { "YYYY-MM-DD": {h_eq, disp, kwh, h_q, h_e} } },
  "oss":     [ {folio, tipos, origem, code, g1, desc, flags, excl, aberta, ini, fim,
                usinas[], escopo[], h_solar, kwh, dias_exonerados} ],
  "cenario_abertas": [...], "lacunas": [...] }
```

---

## 10. Limitações honestas (o que o número NÃO é)

- **kWh perdido é teto**, à potência nominal (não desconta clima nem horário) — serve para ordenar, não
  para faturar.
- **Corretiva simples** não entra: entrariam ~1.933 tarefas e o bucket cairia de 99,5 % para 93,7 %,
  grosso demais (muita coisa é trabalho programado sem parada).
- Sites **agrupados sem pista** na descrição são atribuídos à 1ª usina do grupo, com flag "conferir".
- `wo_final_date` pode ser um **carimbo tardio** — quando é a única data de fim, a OS vem com flag.
- A régua da geração só julga usinas **praticamente plenas** (P75 ≥ 4,5 kWh/kWp) e fatias ≥ 30 % do dia.

---

## 11. Onde está no código

| Coisa | Arquivo |
|---|---|
| A conta (catálogo, escopo, varredura, fórmulas) | `plataforma/disponibilidade.py` |
| Auth + varredura do Fracttal | `plataforma/app.py` → `get_fracttal_token`, `_frac_get`, `_frac_disp_sweep` |
| Geração (juiz) e aba Equipamentos | `plataforma/app.py` → `_disp_geracao`, `_disp_equip_linhas` |
| Worker (loop, recálculo, publicação) | `plataforma/app.py` → `_frac_disp_loop`, `_frac_disp_recalcular`, `_frac_disp_dados` |
| Endpoints web + export Excel | `plataforma/app.py` → `gerencial_disponibilidade`, `api_gerencial_disponibilidade`, `api_gerencial_disp_export` |
| Tela | `plataforma/templates/disponibilidade.html` |
| Metodologia e decisões de negócio | `docs/disponibilidade-por-os.md` |

---

*Referência de runtime da disponibilidade do Gerencial. Constantes citadas: `FRAC_DISP_TTL` 30 min,
`FRAC_DISP_MARGEM_D` 45 dias, rate limit 200 req/min, janela solar 06h–18h, P75 ≥ 4,5 kWh/kWp,
tolerância 15 %, fatia mínima 30 %.*
