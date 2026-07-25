# CLAUDE.md — mapa do repositório

Quatro projetos independentes da Grid Co, um repositório. **Cada pasta tem seu próprio CLAUDE.md**
com o que é específico dela — leia o da pasta em que estiver trabalhando.

| Pasta | Projeto | O que é |
|---|---|---|
| `plataforma/` | Plataforma de Performance + ronda de trackers | Flask na porta **5050**, uso interno. É o maior (`app.py`, ~17 mil linhas) |
| `coletor/` | Coletor automatizado de dados | Scripts de coleta que alimentam as planilhas |
| `os_creator/` | OS Creator | App de desktop (PyQt6) que cria OS no Fracttal |
| `thopen/` | Dashboard BD_Thopen | Flask na porta **5080**, produto para o **cliente**, publicado no Railway |

Documentação de arquitetura e regras de negócio: `README.md` e `docs/`.

## O que fica na raiz, e por quê

`.env`, tokens, arquivos de estado (`*.json`), `docs/`, `tests/` e as planilhas ficam **na raiz**,
não dentro das pastas. São ~26 arquivos — incluindo 8 MB de histórico de trackers, caches e notas
dos analistas. O código desceu para as pastas; o estado ficou parado, o que tornou a separação
segura (nada de estado foi movido, então nada podia se perder no caminho).

Consequência prática: dentro de `plataforma/app.py` existem duas constantes, e a escolha entre elas
importa —

- **`_AQUI`** = pasta do próprio arquivo → `templates/` e `static/`, que viajaram com o código
- **`_RAIZ`** = raiz do repositório → `.env`, tokens, estado, `docs/`, planilhas

Ao criar um caminho novo, pergunte: isso é recurso colado no código (`_AQUI`) ou estado
compartilhado (`_RAIZ`)?

## Acoplamento conhecido: plataforma → thopen

`plataforma/app.py` importa `dashboard_thopen` para usar **três** leitores do `BD_Thopen.xlsx`:
`_CARTEIRA_DE`, `_registro()` e `_daily_records()`. É resolvido por um `sys.path.insert` no topo
do `app.py` apontando para `thopen/`.

Não é acidente: a planilha é genuinamente compartilhada. Extrair um módulo comum arrastaria junto
`_bd_path`, `_open_wb`, `_daily_bd` e `CARTEIRAS` — metade do `dashboard_thopen.py` — por um ganho
que, num repositório único, não se paga. **Se um dia os projetos virarem repositórios separados,
essa extração passa a ser obrigatória.**

## Convenções (valem para os quatro)

- **Sempre pt-BR**, inclusive comentários de código.
- **Sem emoji na interface** — severidade se comunica por cor. (Exceção herdada: `/painel`.)
- Tema escuro é **navy** (`#090d18` / `#161d30`) + verde Grid. Nunca lilás.
- Comentário de código explica **por que**, de preferência citando o caso real que motivou a regra.
  É o padrão dos arquivos; mantenha.
- Ao citar um arquivo numa resposta, dê o caminho clicável.
- Commit só quando pedido explicitamente.

## Segredos

`.env`, `tokens.txt`, `plat_token.txt`, `pg_password.txt`, `se_credentials.txt` e afins são
segredos, já cobertos pelo `.gitignore`. **Nunca imprima `DASH_PASSWORD` nem desligue a
autenticação.** Para validar interface atrás da senha, faça login por sessão lendo a variável,
sem exibi-la.

## Verificação

Este projeto trata **confiabilidade de dado como prioridade 1**. Antes de dar algo por pronto:

- Mudou consulta ao banco? Rode a nova **e a antiga** e compare valor a valor.
- Mudou endpoint? Bata nele de verdade e confira número e frescor do dado.
- Mudou desempenho? Meça antes e depois, e diga o número.
- Se o teste falhou ou você não conseguiu validar, **diga isso** em vez de afirmar que funcionou.

Testes: `python -m pytest -q` a partir da raiz (o `conftest.py` põe `plataforma/` no path).
