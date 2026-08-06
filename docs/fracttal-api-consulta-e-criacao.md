# API do Fracttal — consultar e criar OS

Referência de bolso das duas APIs do Fracttal: qual usar para quê, o que cada uma entrega e onde
elas mordem. Tudo aqui foi **medido ao vivo na conta 4987 em 06/08/2026**, não transcrito de
documentação — os números são reais e os campos foram conferidos na resposta.

Motivo do documento: reproduzir a **visão COS do Histórico** fora do OS Creator (Power BI, script,
outro app) e saber se dá para criar OS por fora.

---

## 1. As duas APIs, em uma tabela

| | **REST (OAuth)** | **RPC (JWT de sessão)** |
|---|---|---|
| Endpoint | `https://app.fracttal.com/api/...` | `POST https://app.fracttal.com/rpc/proxy` |
| Autentica | `client_credentials` da EMPRESA | e-mail + senha da PESSOA |
| Validade | 1 h (renovável sem ninguém) | ~12 h, pessoal |
| É documentada? | Sim | Não — é a API interna do web app |
| **Consultar OS** | Sim, e melhor (§3) | Sim, mas em 2 chamadas (§4) |
| **Criar OS** | **NÃO** — 401 `UNAUTHORIZED_ENDPOINT` | Sim (§5) |
| Estabilidade | Alta | Muda sem aviso |

**Regra prática:** consulta → REST. Criação → RPC, não tem escolha.

---

## 2. Autenticação

### REST / OAuth (consulta)

```bash
curl -X POST https://app.fracttal.com/oauth/token \
  -d "grant_type=client_credentials&client_id=SEU_ID&client_secret=SEU_SECRET"
```

Devolve `access_token` (1 h). Depois: `Authorization: Bearer <token>`.

É credencial de **aplicação**, não de pessoa — roda em script agendado sem ninguém logar. As do
OS Creator estão no `.env` dele; para outra ferramenta, peça um par próprio ao Fracttal.

### RPC / JWT (criação)

```
POST https://app.fracttal.com/rpc/login_new
{"email": "...", "password": "<MD5 duplo>", "id_company": 4987,
 "id_server": "AMERICAN", "platform": "Fracttal/5.7.02 web"}
```

A senha vai transformada igual ao web app (achado no bundle deles). **MD5 simples é recusado**
com `USER_OR_INVALID_KEY`:

```
inner = MD5(email + ":" + senha)
final = MD5(email + ":" + inner)
```

Toda chamada vai para `/rpc/proxy`, corpo JSON-RPC **dentro de uma lista**:

```json
[{"id": "<uuid4>", "jsonrpc": "2.0", "method": "<método>", "params": { ... }}]
```

Headers obrigatórios — os três, e os dois últimos **não são decorativos**; sem eles o proxy recusa:

```
Authorization: Bearer <jwt>
Origin: https://app.fracttal.com
x-version: Fracttal/5.7.02 web
```

---

## 3. Consultar OS pelo REST — o caminho recomendado

Uma linha do `work_orders/` traz **as 11 colunas da visão COS de uma vez**. É a vantagem decisiva
sobre o RPC, que precisa de uma segunda consulta para tipo de tarefa, início e gatilho.

| Coluna COS | Campo REST |
|---|---|
| Data da programação | `date_maintenance` |
| Tipo de tarefa | `tasks_log_task_type_main` |
| Usina | `groups_1_description` |
| Descrição | `description` |
| Equipe | `personnel_description` |
| Data Início da OS | `initial_date` |
| Data Fim da OS | `final_date` |
| Descrição gatilho | `trigger_description` |
| Descrição EQP | `items_log_description` |
| Nº da OS | `wo_folio` |
| Criado por | `created_by` |

Cliente sai do `{ CODE }` dentro de `items_log_description` cruzado com o catálogo, ou do
`parent_description`.

### Filtros (query param, casamento EXATO)

```
work_orders/?limit=100&start=0&creation_date=2026-07-15
work_orders/?limit=100&id_status_work_order=3
work_orders/?limit=100&tasks_log_task_type_main=Religamento
work_orders/?limit=100&created_by=Levi Maia
work_orders/?wo_folio=10697
```

Medidos: `Religamento` → 3.059 · `created_by=Levi Maia` → 397 · sem filtro → 26.868.

### Três armadilhas medidas

1. **Não existe intervalo de data.** `creation_date` é **dia exato**. Testei `__gte`, `__gt`,
   `_gte`, `_from`, `_min`, `start_date/end_date` e dois parâmetros — todas ignoradas. E ignorar
   aqui significa **devolver as 26.868**. Período = laço dia a dia.
2. **`limit` corta em 100**, mesmo pedindo 500. Pagine com `start`.
3. **`search` é ignorado** — devolve o catálogo inteiro.

> Em todas as três, filtro desconhecido **não dá erro: dá tudo**. Confira sempre o `total` contra
> o esperado antes de confiar no resultado.

### Custo medido

**7 dias = 734 linhas em 5,7 s.** Um mês fica em ~25 s.

### Esqueleto

```python
import requests, datetime as dt

tok = requests.post("https://app.fracttal.com/oauth/token",
                    data={"grant_type": "client_credentials",
                          "client_id": ID, "client_secret": SECRET}).json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}
TIPOS_COS = {"Corretiva", "Corretiva Emergencial", "Religamento", "Religamento Remoto"}

linhas, d = [], dt.date(2026, 7, 1)
while d <= dt.date(2026, 7, 31):
    start = 0
    while True:
        r = requests.get("https://app.fracttal.com/api/work_orders/", headers=H,
                         params={"limit": 100, "start": start,
                                 "creation_date": d.isoformat()}).json()
        pag = r.get("data") or []
        linhas += [x for x in pag if x.get("tasks_log_task_type_main") in TIPOS_COS]
        if len(pag) < 100:
            break
        start += 100
    d += dt.timedelta(days=1)
```

### Gatilho vem em código

`NO_SCHEDULE_TASK`, `DATE$EVERY$30$DAYS`. A tradução é a mesma do Power Query que já existia:

```
NO_SCHEDULE_TASK       → Tarefa não agendada
EVENT$                 → (remove)
DATE$EVERY$            → A cada
$DAYS / $MONTHS / $YEARS → dias / meses / anos
```

---

## 4. Consultar OS pelo RPC — o que o OS Creator faz

Duas chamadas, porque quatro colunas não existem no nível da OS.

**Chamada 1 — a lista:** `tasks.work_orders_list_react`

```json
{"page": 1, "limit": 60, "start": 0, "append": true,
 "sort": [{"property": "id", "direction": "desc"}],
 "filter": [{"operator": "=",  "property": "id_created_by", "value": 52},
            {"operator": ">=", "property": "creation_date", "value": "2026-07-01"},
            {"operator": "<=", "property": "creation_date", "value": "2026-07-31T23:59:59"},
            {"operator": "in", "property": "id_status_work_order", "value": [1,2,3]}]}
```

Filtros que funcionam: `id_created_by`, `id_assigned_user`, `id_item`, `id_label`,
`id_status_work_order`, `id_parent_wo`, `creation_date`, `wo_folio`. **Usina não dá** — `like` em
campo do item é ignorado.

**Chamada 2 — o nível TAREFA:** `tasks.work_orders_tasks_new_list`, em lotes de ~130 ids

```json
{"page": 1, "limit": 2000, "start": 0,
 "filter": [{"operator": "in", "property": "id_work_order", "value": [<ids>]}]}
```

De lá saem `tasks_types_main_description`, `initial_date`, `trigger_description`, `final_date`.

### Armadilhas do RPC

- **Compõe filtros com OU, não E.** Mandar busca junto de "criado por" devolvia a união: 138 OS
  viravam 243, com 62 de outros criadores. E **não dá para agrupar** — as duas formas de aninhar
  condições que testei foram ignoradas.
- **Filtro como parâmetro solto** (fora do `filter`) é ignorado silenciosamente.
- **Não use `first_date_task` como início.** Ele é igual à data programada; só **33 de 1.306**
  tarefas medidas têm início real.

### Custo medido

Página de 60 → **0,7 s**. O enriquecimento das mesmas 60 → **3,5 s** (5× mais). Por isso o app
renderiza primeiro e busca a meta depois, assíncrono.

---

## 5. Criar OS — só pelo RPC

> **`POST /api/work_orders/` e `POST /api/work_requests/` respondem HTTP 401
> `UNAUTHORIZED_ENDPOINT`** com as credenciais OAuth atuais. Testado em 06/08. Para criar por
> fora, seria preciso pedir ao Fracttal a liberação de escrita nessas credenciais.

Um método faz o trabalho: **`tasks.tasks_noscheduled_react_insert`**. Ele cria a OS **com as
subtarefas dentro** — não precisa de plano cadastrado. O campo `to_work_order` bifurca o fluxo.

### Caminho A — `to_work_order: true` (1 chamada)

A OS já nasce **numerada**, com responsável. Usado por: Performance, ETM, Inspeção de chamados.

Campos essenciais: `id_item`, `items_description`, `id_type_item`, `id_group_task`, `path_node`
(`"{id_parent}.{id_item}"`), `description`, `id_task_type_main`, `id_priorities`, `subtasks`,
`id_assigned_user`, `event_date`, `initial_date`.

### Caminho B — `to_work_order: false` (3 chamadas)

Cria tarefa **pendente** e depois junta N tarefas numa OS só. Usado por: Criar OS tradicional,
COS, Chamados, PCM, Clonar.

```
1. tasks.tasks_noscheduled_react_insert   (1× por ativo)  → id_task
2. tasks.tasks_todo_list_kanban           → registro COMPLETO de cada tarefa
3. tasks.work_order_insert                → 1 OS numerada com todas + responsável
```

O passo 2 existe porque o `work_order_insert` exige o registro inteiro e o insert só devolve o id.
Precisa de retry: a tarefa leva 1–2 s para aparecer no kanban.

**Sem responsável o fluxo para no passo 1** — ficam tarefas pendentes, sem número de OS.

### Depois da criação

| O quê | Como |
|---|---|
| Etiqueta | `tasks.work_order_labels_sync` — chamada separada, com `id_work_order`. Falhar aqui **não deve** derrubar a OS |
| Classificação | No payload da criação (`id_task_type` / `id_task_type_2`), resolvida pelo **nome** em `tasks.tasks_types_list` e `tasks.tasks_types_2_list` — a lista é editável no Fracttal, id fixo quebra |
| Anexo | `s3_object_post` |

### Quatro armadilhas da escrita

1. **O Fracttal ignora o `date_maintenance` que você manda** e usa o **`initial_date`** como data
   de programação. Medido na OS 10402: mandei 11:00Z, ele gravou 10:40Z. Mande os três iguais.
2. **`success: false` chega com HTTP 200.** Cheque o campo, não o status.
3. **`id_task` e `id_task_reference` precisam ser `null`** quando você manda subtarefas próprias.
   Preenchidos, ele descarta as suas e usa as do plano.
4. **O registro do kanban não tem `initial_date` nem `final_date`** — então toda OS criada pelo
   Caminho B nasce **sem data de início/fim na tarefa**, e o `concluir_os` não preenche depois.
   Testado na OS 10567: nula antes, nula depois. É a origem do aviso de "OS sem data de fim".

---

## 6. Tipos de subtarefa (form items)

Sondado ao vivo varrendo os form items de 70 OS. **A documentação REST está errada para esta
conta** — ela diz `3=Data`, `5=Dropdown`, `7=Foto`. Não é o que o servidor devolve, e **não
existe tipo Data**: data se pede como Texto.

| id | Tipo |
|---|---|
| 1 | Texto |
| 2 | Sim/Não |
| 3 | Número |
| 4 | Verificação (`1`/`2`/`3` → Aprovado/Alerta/Falhou) |
| 7 | Lista (usa `dropdown_options`) |

---

## 7. Ver também

- [`chamado-os-inspecao-api.md`](chamado-os-inspecao-api.md) — a receita completa de criação, com
  o payload literal capturado do código e o formato de cada subtarefa.
- [`chamado-os-inspecao.md`](chamado-os-inspecao.md) — a regra de negócio do chamado de garantia.
