# Criar a OS de inspeção no Fracttal — receita para o app de campo

Complemento de [`chamado-os-inspecao.md`](chamado-os-inspecao.md), que descreve **o quê** criar.
Este documento descreve **como** — a chamada exata que o OS Creator faz.

Tudo aqui foi extraído do código que está em produção (`os_creator/api.py`), não transcrito de
memória. O payload da §3 é uma captura literal: interceptei o POST do OS Creator com o RPC real,
sem deixar a requisição sair, para o corpo vir do próprio código.

---

## 1. O pacote `chamado_garantia/`

Vai junto no zip. É Python puro — importa só `re` e `unicodedata`, nada de PyQt nem `requests`,
justamente para poder ser importado pelo middleware sem arrastar dependência.

| Arquivo | Papel |
|---|---|
| `spec.py` | As subtarefas: `BASE`, `POR_TIPO`, `POR_FABRICANTE`, `ALIAS_TIPO`, `so_para`, `derivados` |
| `regras.py` | `montar()`, `pode_abrir()`, `descobrir_marca()` + as constantes de tipo/classificação/etiqueta |
| `__init__.py` | Reexporta a superfície pública |
| `README.md` | Como usar |

**Importar, não copiar.** As tabelas do §10 da spec são geradas do código; transcrevê-las cria uma
segunda fonte da verdade que envelhece sozinha e faz as duas OS divergirem. O OS Creator faz
exatamente isso — seu `chamado_insp_spec.py` é uma ponte de 6 linhas que reexporta o pacote.

As funções recebem o **ativo inteiro** (dict), não o tipo em string — porque `descobrir_marca` e
`titulo` precisam da descrição, e `so_para` precisa do tipo. Basta um dict com `code`,
`description` e `tipo`:

```python
import chamado_garantia as cg

ativo = {"code": "TESTE100-INVR1.1", "description": "Inversor 1.1 Huawei", "tipo": "Inversor"}

cg.pode_abrir(ativo, "Religamento")   # → True   (o botão aparece?)
cg.pode_abrir(ativo, "Preventiva")    # → False
cg.descobrir_marca(ativo, irmaos)     # → "Huawei"  ('' se não deu, aí pergunte)

cg.montar(ativo, "Huawei")
# → {'tipo_tarefa': 'Inspeção', 'classif_1': 'Programada', 'classif_2': 'Elétrica',
#    'etiqueta': 'Aguardando Garantia',
#    'titulo': '[Inversor 1.1 Huawei] - Inspeção para chamado Huawei',
#    'fabricante': 'Huawei', 'subtarefas': [...8 dicts...],
#    'resumo': '8 subtarefas · 6 obrigatórias · 2 com anexo obrigatório'}
```

`montar()` é o contrato inteiro num dicionário só — inclusive o `resumo` pronto para a tela de
confirmação. O que **não** vem dele é o que é do contexto de quem chama: ativo, data do incidente,
responsável e OS pai; no app de campo os quatro saem da OS que o técnico já está preenchendo.

`pode_abrir` checa duas coisas: o ativo tem modelo de subtarefa **e** a OS é de origem válida
(corretiva, corretiva emergencial, religamento ou religamento remoto). Passar `tipo_tarefa_os=None`
pula a segunda checagem.

Tudo em `chamado_garantia` roda **sem rede**: a decisão de mostrar o botão, a descoberta da marca e
a montagem das subtarefas são locais. Só o POST da §3 precisa de internet — ver a §7.

---

## 2. Autenticação

O RPC é a API interna do web app do Fracttal, **não** o REST OAuth. São autenticações diferentes e
não se misturam.

```
POST https://app.fracttal.com/rpc/proxy
Authorization: Bearer <JWT>
Content-Type: application/json
Accept: application/json, text/plain, */*
Origin: https://app.fracttal.com
x-version: Fracttal/5.7.02 web
```

O `Origin` e o `x-version` **não são decorativos** — o proxy recusa sem eles.

O JWT é por usuário, obtido em `rpc/login_new` (senha em MD5). É o mesmo token que o app de campo já
usa para fechar OS, então a OS nasce no nome do técnico, que é o que se quer: quem apertou o botão
fica registrado como autor.

Corpo de qualquer chamada (JSON-RPC 2.0, **sempre dentro de uma lista**):

```json
[{"id": "<uuid4>", "jsonrpc": "2.0", "method": "<método>", "params": { ... }}]
```

---

## 3. A criação — `tasks.tasks_noscheduled_react_insert`

Um único POST cria a OS **com as subtarefas dentro**. Não existe plano cadastrado no Fracttal para
o chamado de garantia, e não precisa: este método aceita a lista de subtarefas no próprio payload.

Captura literal (inversor Huawei, incidente 03/08 09:15Z, programada 04/08 08:00Z):

```json
{
  "event_date":            "2026-08-03T09:15:00.000Z",
  "cal_date_maintenance":  "2026-08-04T08:00:00.000Z",
  "date_maintenance":      "2026-08-04T08:00:00.000Z",
  "initial_date":          "2026-08-04T08:00:00.000Z",
  "final_date":            "2026-08-04T08:15:00.000Z",
  "assigment_date":        "2026-08-03T09:15:00.000Z",

  "id_item":            43128271,
  "items_description":  "Inversor 1.1 Huawei     { TESTE100-INVR1.1 }",
  "id_type_item":       2,
  "id_group_task":      350524,
  "path_node":          "43128214.43128271",

  "description":  "[Inversor 1.1 Huawei] - Inspeção para chamado Huawei",
  "note":         "[CHAMADO] ...",
  "task_note":    "",
  "requested_by": "Levi Maia",
  "name":         "Levi Maia",

  "tasks_types_main_description": "Inspeção",
  "id_task_type_main":            43889,
  "id_task_type":                 56098,   "tasks_types_description":   "Programada",
  "id_task_type_2":               66713,   "tasks_types_2_description": "Elétrica",

  "id_assigned_user": 1414413,
  "id_parent":        null,
  "id_priorities":    2,
  "duration":         900,   "real_duration": 0,

  "type_user": "HUMAN_RESOURCES",
  "to_work_order": true, "to_in_review": false, "work_done": false, "edit_mode": false,
  "failure_asset": false, "stop_assets": false,
  "id_failure_severity": 0, "id_damage_type": 1,
  "id_task_reference": null, "id_task": null,
  "id_request": null, "available": null,
  "initial_date_out_of_service": null, "date_asset_out_of_service": null,
  "id_work_order_task_related": null,
  "msg_availability": "ASSET_OUT_OF_SERVICE",
  "array_resources": [],

  "subtasks": [ ... ver §4 ... ]
}
```

### O que vem de onde

| Campo | Origem |
|---|---|
| `id_item`, `items_description`, `id_type_item`, `id_group_task`, `path_node` | O registro do ativo. `path_node` = `"{id_parent}.{id}"`, ou só `"{id}"` se não tiver pai |
| `event_date`, `assigment_date` | Data do **incidente** — clonada da OS corretiva |
| `cal_date_maintenance`, `date_maintenance`, `initial_date` | Data **programada**. Os três iguais, ver o alerta abaixo |
| `final_date` | `initial_date + duration` segundos |
| `id_task_type_main` | `43889` = Inspeção (`TIPO_TAREFA` do pacote) |
| `id_task_type` / `id_task_type_2` | Resolvidos **pelo nome** — ver §5 |
| `id_assigned_user` | `id_personnel` do responsável |
| `id_parent` | `id` da OS corretiva (não é o número dela — ver §6) |
| `description` | `chamado_garantia` monta: `[Ativo] - Inspeção para chamado {marca}` |
| `note` | O bloco `[CHAMADO]` + a observação livre |

**`id_task_reference` e `id_task` são `null` de propósito.** É o que diz "OS avulsa, com as
subtarefas copiadas" em vez de "OS ligada a um plano cadastrado". Preencher esses dois faz o
Fracttal ignorar as subtarefas que você mandou e usar as do plano.

> **O Fracttal ignora o `date_maintenance` que você manda.** Medido na OS 10402: mandei 11:00Z e ele
> gravou 10:40Z, que era o `initial_date`. Ele usa o **`initial_date`** como data de programação.
> Por isso os três vão iguais. Se mandar `initial_date` diferente, a OS nasce programada na hora
> errada e ninguém percebe até o técnico chegar na usina no dia errado.

### Resposta

```json
{"success": true, "message": "ACTION_DONE",
 "data": {"id_task": ..., "id_work_order": ..., "wo_folio": "10559", ...}}
```

O `wo_folio` é o **número da OS** que o técnico vê. Ele só existe depois que o servidor aceita —
é o nó da questão do offline (§7).

Cuidados no parse, todos já mordidos em produção: a resposta vem numa **lista**; o `result` pode ser
lista **ou** dict; e um `{"success": false}` chega com **HTTP 200** — checar o campo, não o status.

---

## 4. Formato de cada subtarefa

`montar()` devolve dicts com `description`, `id_task_form_item_type`, `is_required` e
`attachments_required`. O RPC precisa de mais quatro campos de controle:

```json
{
  "id": "a1ee6895-4914-4f3c-aa52-eea88ab17165",
  "order_number": 1,
  "description": "Descrição do problema: sintoma observado em campo",
  "id_task_form_item_type": 1,
  "task_form_item_type_description": "Texto",
  "id_task_form_item_group": null,
  "task_form_item_group_description": null,
  "is_required": true,
  "attachments_required": false,
  "dropdown_options": null,
  "is_new": false,
  "phantom": true,
  "num_attachments": 0
}
```

- `id` = UUID4 novo por subtarefa; `order_number` = 1..N na ordem da lista.
- `phantom: true` e `is_new: false` são o que o web manda. Não inventei — copiei da captura.
- `dropdown_options` só na Lista (tipo 7); nos outros, `null`.

Tipos, **sondados ao vivo na conta 4987** varrendo os form items de 70 OS:

| id | Tipo |
|---|---|
| 1 | Texto |
| 2 | Sim/Não |
| 3 | Número |
| 4 | Verificação (`1`/`2`/`3` → Aprovado/Alerta/Falhou) |
| 7 | Lista (usa `dropdown_options`) |

> **A doc REST do Fracttal está errada para esta conta.** Ela diz `3=Data`, `5=Dropdown`, `7=Foto`.
> Não é o que o servidor devolve. E **não existe tipo Data** — data se pede como Texto.

---

## 5. Resolver as classificações pelo nome

`id_task_type` (56098 = Programada) e `id_task_type_2` (66713 = Elétrica) **não devem ser fixados no
código**: a lista é editável dentro do Fracttal e um id fixo quebra na primeira edição de alguém.
Resolva pelo nome, no catálogo:

- Classificação 1 → `tasks.tasks_types_list` *(no OS Creator: `get_classif1()`)*
- Classificação 2 → `tasks.tasks_types_2_list` *(`get_classif2()`)*

Case-insensitive, e nome que não existir simplesmente não entra — OS sem classificação é menos ruim
que OS com a classificação errada.

---

## 6. Etiqueta: uma segunda chamada, depois da OS

A etiqueta **não vai no payload de criação**. É um POST separado, com o `id_work_order` que a
criação devolveu:

```
method: tasks.work_order_labels_sync
params: {"id_work_order": <id>, "id_labels": [2036],
         "append": true, "page": 1, "limit": 200, "start": 0}
```

`2036` = **Aguardando Garantia** (`ETIQUETA` do pacote). Resolva pelo nome em
`tasks.work_order_labels_list` (`{"only_enabled": true, "page":1, "limit":200, "start":0,
"id_work_order":0, "is_tree":false, "node":null, "sort":[{"property":"description","direction":"asc"}]}`).

**Falhar aqui não deve derrubar a OS.** O OS Creator cria, tenta etiquetar e, se a etiqueta falhar,
devolve a OS criada com um aviso. Uma OS sem etiqueta você conserta em 10 segundos no Fracttal web;
uma OS que não foi criada porque a etiqueta falhou o técnico perde a viagem.

### `id_parent` — é o `id`, não o número

O `id_parent` é o **`id` interno** da OS corretiva, não o folio que aparece na tela. Se o app só
tiver o número, resolva com `tasks.work_orders_parents_list` e case pelo folio exato. No OS Creator
isso é o `buscar_os_pai()`, e OS pai é opcional: não achou, cria sem vínculo em vez de falhar.

---

## 7. Offline — a pergunta que ficou em aberto

A spec foi escrita para o OS Creator, que é desktop e online. O app de campo é offline-first, e essa
diferença é real: o técnico aperta o botão numa usina sem sinal.

**Recomendo a fila**, pelo mesmo motivo do resto do app. O que pesa a favor:

- Tudo que decide *o que* criar já roda offline — `pode_abrir`, `descobrir_marca` e `montar` são
  Python puro sem rede. Só o POST precisa de internet.
- Bloquear o botão significa perder a informação no momento em que ela é mais fresca: o técnico está
  na frente do equipamento, com a placa na mão. Uma hora depois ele não lembra o número de série.

O que a fila custa, e precisa aparecer na tela: **o técnico não recebe o número da OS na hora.** O
`wo_folio` só existe depois que o servidor aceita. A confirmação teria de dizer "chamado registrado,
a OS é criada quando o celular reconectar" em vez de mostrar o número — e o app precisa avisar
depois, quando o número chegar.

Dois detalhes que a fila obriga a tratar, e que valem decidir agora e não no primeiro bug:

1. **Data do incidente é a do incidente, não a do envio.** O `event_date` tem de ser gravado no
   momento em que o técnico aperta o botão. Se o payload for montado só na hora do envio, toda OS
   enfileirada nasce com a data errada.
2. **Reenvio não pode duplicar.** Rede ruim gera resposta perdida com OS criada do outro lado. Vale
   guardar a chave (OS pai + ativo + data do incidente) e checar antes de reenviar.

Essa é a decisão que o Levi precisa bater — as duas saídas são defensáveis, mas mudam o que o
técnico vê ao apertar o botão.

---

## 8. Resumo da sequência

```
1. (offline)  pode_abrir(tipo_os) ................... mostra o botão?
2. (offline)  descobrir_marca(ativo, irmãos) ........ achou? senão pergunta
3. (offline)  montar(tipo_ativo, marca) ............. as N subtarefas
4. (rede)     tasks.work_orders_parents_list ........ folio da OS pai → id_parent   [opcional]
5. (rede)     tasks_types_list / _2_list ............ nomes → id_task_type / _2
6. (rede)     tasks.tasks_noscheduled_react_insert .. cria a OS  → wo_folio
7. (rede)     tasks.work_order_labels_sync .......... etiqueta Aguardando Garantia  [não fatal]
```

Os passos 4, 5 e 7 são cacheáveis e tolerantes a falha. O passo 6 é o único que precisa dar certo.
