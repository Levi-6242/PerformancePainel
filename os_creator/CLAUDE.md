# OS Creator

App de **desktop** (PyQt6) que cria e acompanha Ordens de Serviço no **Fracttal**. É o único
projeto do repositório que não é web e que já era autocontido: tem `app.py`, `main.py` e
`requirements.txt` próprios. Ver o `CLAUDE.md` da raiz para as convenções gerais.

**Atenção ao nome:** o `app.py` desta pasta é o do OS Creator, **não** o da plataforma
(que fica em `plataforma/app.py`). O `from app import MainWindow` em `main.py` aponta para cá.

| Arquivo | Papel |
|---|---|
| `main.py` | Ponto de entrada (login + janela principal) |
| `app.py` | `MainWindow`, tema escuro (`DARK_QSS`), `LoginDialog` |
| `api.py` | Cliente do Fracttal (REST + RPC) |
| `cos_spec.py` | Regras do COS: tipos de OS e categorias |
| `steps/` | Uma tela por fluxo (performance, chamados, OS pai, detalhe, histórico) |
| `workers.py` | Threads de API — ver o cuidado abaixo |

Para escrever uma tela nova, leia também `steps/CLAUDE.md`.

## Cuidados

- **PyQt6 + threads derruba o app se feito errado.** Uma `QThread` sem referência viva é coletada
  pelo garbage collector e mata o processo. Use o padrão que já existe (`ApiWorker` + slot seguro);
  não crie thread solta.
- **Login é multiusuário**: cada pessoa entra com a própria conta (RPC `rpc/login_new`, senha em
  MD5 duplo). O REST e o RPC do Fracttal são autenticados de formas diferentes — não misture.
- `fracttal_login.txt` é credencial: não commite nem imprima.
- **Buildar fora do OneDrive** (o sync corrompe o PyInstaller). Use uma pasta local como
  `C:\GridcoBuild`, e distribua pelo instalador, não pelo `.exe` solto.
- Paginação da API do Fracttal corta em ~100 itens — sempre pagine.
- **`sys.path.append`, nunca `insert(0)`.** O pacote `chamado_garantia` mora na raiz do
  repositório, então a raiz entra no `sys.path` (`api.py`). Mas a raiz também tem um `app.py` —
  o da **plataforma**. Com `insert(0)`, um `import app` posterior resolvia para o dela e chegava a
  **executar o boot da plataforma** dentro do processo do OS Creator. Medido, não teórico.

## Verificação — a régua que importa

O erro barato é o que quebra: o app não abre e alguém percebe em minutos. O erro caro é o que
**não** quebra — a OS é criada, ninguém estranha, e está errada dentro do sistema do cliente.
Nenhum teste automático pega isso hoje. Só o hábito abaixo pega.

**Antes de dar qualquer mudança de criação de OS por pronta:**

1. Crie uma OS de verdade na usina **`TESTE - PA`** — ela existe no Fracttal exatamente para isso.
2. Abra a OS no Fracttal (web) e confira **campo a campo** contra o que você quis criar:
   título, ativo, responsável, classificações, etiquetas, data do evento, data programada,
   observação da OS, observação de cada tarefa, OS pai.
3. Confirme também o que a tela **diz** que fez: o número que aparece no app é o mesmo que abriu
   no Fracttal.
4. Cancele a OS de teste ao terminar.

Se não deu para validar ao vivo, **diga isso** em vez de afirmar que funciona. A regra do
`CLAUDE.md` da raiz — "confiabilidade de dado é prioridade 1" — vale aqui em dobro, porque aqui
o dado é gravado no sistema do cliente e não dá para desfazer sozinho.

**Antes de qualquer release:** abra o `.exe` buildado. Não a tela isolada — a **janela principal**.
A v135 saiu com um `KeyError` no `MainWindow.__init__` e o app não abria; como o atualizador só
rodava depois dele, quem instalou ficou preso na versão quebrada, sem conseguir atualizar.

## Armadilhas da API do Fracttal

Aprendidas na marra, cada uma custou tempo. Nenhuma está documentada pelo fornecedor.

**Respostas**

- **`success: false` chega com HTTP 200.** Nunca confie no código de status: leia o corpo.
- **Filtro desconhecido devolve o banco inteiro**, silenciosamente e nos dois protocolos
  (26.868 registros no REST, 10.272 no RPC). Se você errar o nome de um filtro, o resultado
  parece um sucesso enorme. **Sempre confira o `total`** antes de acreditar.
- Paginação corta em ~100 itens.

**Criação de OS — dois caminhos, não misture**

- `create_planned_os(to_work_order=True)`: 1 chamada, já nasce numerada como OS.
  É o caminho de Performance, ETM e Inspeção.
- `create_os_rpc(to_work_order=False)` + `tasks_todo_list_kanban` + `work_order_insert`:
  duas fases. É o caminho de Criar OS, COS, Chamados, PCM e Clonar.

**O que sobrevive à conversão kanban → OS** (medido, não suposto)

- Sobrevive: `task_note`, `description`, `id_task_type`, `id_task_type_2`, `id_priorities`,
  `id_item`, `id_task_type_main`.
- **Não sobrevive:** `id_parent`, `initial_date`, `final_date`. Se precisar de OS pai ou de datas,
  mande no `work_order_insert`, que aceita `id_parent` e `note`.

**O que o Fracttal ignora calado**

- `date_maintenance` — ele usa o `initial_date` como data programada.
- O `description` da OS no insert.
- `id_parent_wo` no `work_orders_update` — devolve `ACTION_DONE` e grava `None`.

**Campos que parecem iguais e não são**

- `note` é a observação **da OS**; `task_note` é a observação **da tarefa**. São campos
  diferentes, e é o que torna possível ter uma observação geral e uma por ativo.

**Limites conhecidos**

- **OAuth/REST não cria OS** (devolve 401). Criação é só pelo RPC.
- REST não tem filtro por faixa de datas.
- **Data de fim de tarefa não pode ser retroativa** — o Fracttal carimba a hora da chamada e
  ignora o que você mandar. Por isso o campo de data de fim foi removido da tela de conclusão:
  campo que o servidor ignora é pior que campo nenhum.
- Ao ler uma OS pelo RPC para clonar, as classificações podem voltar **`NULL`**. Resolva os IDs
  pelo nome (`_classif_ids`) em vez de copiar o que veio.

## Onde o erro se esconde

`@slot_seguro` **engole a exceção** para não derrubar o app. O rastro vai para
`%TEMP%\criaros_erros.log` — é o primeiro lugar a olhar quando "não aconteceu nada".

## Deep link

A plataforma abre este app já preenchido via `gridos://` (ativo, OS pai e responsável). Se mudar
o formato do link, o lado da plataforma (`plataforma/app.py`) precisa acompanhar.
