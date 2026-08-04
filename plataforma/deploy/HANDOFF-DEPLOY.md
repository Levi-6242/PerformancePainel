# Plataforma de Performance — o que o deploy precisa saber

Documento de entrega para quem vai subir a aplicação no servidor.
Guia completo de instalação: `plataforma/deploy/README.md` (neste mesmo repositório).

---

## O essencial em 30 segundos

| | |
|---|---|
| Repositório | `https://github.com/Levi-6242/PerformancePainel.git` |
| Pasta da aplicação | `plataforma/` |
| Runtime | Python **3.14** |
| Dependências | `requirements.txt` na **raiz** do repositório (já pinado) |
| Processos | **dois**: `worker.py` e `app.py`, ambos rodando de dentro de `plataforma/` |
| Porta | **5050** (só o `app.py` escuta; o `worker.py` não abre porta) |
| Sub-caminho no proxy | **`/plat-performance`** |
| Verificação de saúde | `GET /healthz` → 200 |

---

## 1. Proxy reverso

A aplicação já está preparada para rodar sob sub-caminho. Basta o proxy encaminhar
com o cabeçalho:

```
X-Forwarded-Prefix: /plat-performance
```

Funciona **das duas formas**, sem configuração extra:

- proxy que encaminha o caminho completo (`/plat-performance/api/data`) — a aplicação
  remove o prefixo sozinha;
- proxy que já remove o prefixo antes de encaminhar — a aplicação só usa o cabeçalho
  para montar as URLs de saída.

**Alternativa sem cabeçalho:** variável de ambiente `APP_PREFIX=/plat-performance`
antes de subir os processos.

Sem nenhuma das duas, a aplicação roda na raiz da porta — que é o comportamento atual
e continua válido para uso local.

O front-end se adapta em tempo de execução: um shim injetado em cada resposta HTML
reescreve os caminhos absolutos (`fetch`, `XMLHttpRequest`, `EventSource`, `<a href>`
e `<form action>`). Trocar o nome do caminho é trocar uma string — não mexe no código.

### Já testado

| Cenário | Resultado |
|---|---|
| Sem proxy (raiz) | 200 — shim não é injetado, nada muda |
| Proxy encaminhando caminho completo | `/plat-performance/api/tokens` → 200 |
| Proxy removendo o prefixo | 200 |
| Redirecionamento de login | `Location: /plat-performance/login?next=...` |

---

## 2. Subir os processos

São **dois** processos do mesmo código, na pasta `plataforma/`:

```
python worker.py     # reconstrói os dados; não escuta porta
python app.py        # servidor web na 5050
```

O `worker.py` faz o trabalho pesado (consulta de APIs, banco, planilhas) e publica um
snapshot; o `app.py` só lê esse snapshot e serve. **Precisa dos dois** — só o `app.py`
sobe a aplicação, mas sem o `worker.py` os dados param de atualizar.

Ordem: `worker.py` primeiro, `app.py` depois.

Recomendado deixá-los sob supervisão (serviço ou tarefa agendada) para religar sozinhos.
Detalhes na seção 4 do `README.md`.

---

## 3. Segredos — não estão no git, e é proposital

O repositório contém **apenas código**. Ficam de fora, por regra do `.gitignore`:

```
.env                    credenciais de banco e integrações
tokens.txt              tokens das APIs (semente)
tokens_runtime.json     tokens renovados automaticamente pela aplicação
cache_snapshot.json     cache de dados
*.json de estado        comentários das usinas, histórico, livro de trackers
*.log
```

Isso garante que um `git pull` **nunca** sobrescreva token vivo nem histórico
operacional.

**Na primeira instalação**, dois arquivos precisam ser colocados à mão, e chegam por
canal seguro (não por e-mail nem por este repositório):

- `.env` → raiz do projeto
- `tokens.txt` → raiz do projeto

Da segunda atualização em diante, é só `git pull`.

---

## 4. Atualizar

```
cd <pasta do projeto>
git pull
pip install -r requirements.txt      # apenas se o requirements mudou
# reiniciar os dois processos
```

### Duas regras para o servidor

**Nunca rodar `git add -A` no servidor.** O servidor é destino, não origem. O estado de
runtime muda o tempo todo; commitá-lo gera conflito no próximo `pull`. Para descartar
alteração local acidental: `git checkout -- <arquivo>`.

**Nunca trocar de branch no servidor.** `git checkout` de branch remove do disco os
arquivos rastreados que não existem na branch de destino. Aconteceu em 03/08/2026 na
máquina de desenvolvimento: a pasta `plataforma/` foi apagada por um checkout, e o
serviço só continuou no ar porque os processos já tinham o código carregado em memória.
No servidor: sempre a mesma branch, sempre `git pull`.

---

## 5. Ponto de atenção antes de subir

A pasta `plataforma/` **ainda não está na branch `main`** — ela vive na branch de
trabalho, e o PR que a leva para a `main` está aberto.

Enquanto esse PR não for mesclado, o servidor precisa apontar para a branch de
trabalho. Depois do merge, a `main` passa a ser a referência e essa ressalva deixa de
existir. Confirmar com o Levi qual usar no momento da instalação.
