# CLAUDE.md — mapa do repositório

Projetos independentes da Grid Co, um repositório. **O OS Creator saiu deste repositório em 28/08/2026** e vive em [Grid-Co-CODE/oem](https://github.com/Grid-Co-CODE/oem), junto com o pacote `chamado_garantia`, que só ele usava. **Cada pasta tem seu próprio CLAUDE.md**
com o que é específico dela — leia o da pasta em que estiver trabalhando.

| Pasta | Projeto | O que é |
|---|---|---|
| `plataforma/` | Plataforma de Performance + ronda de trackers | Flask na porta **5050**, uso interno. É o maior (`app.py`, ~17 mil linhas) |
| `coletor/` | Coletor automatizado de dados | Scripts **antigos**. O coletor que roda de verdade (22:30, fechamento das 23:30, Painel e widget) mora em `C:\Users\Levi Maia\OneDrive - GRID CO\Área de Trabalho\temp\coleta API PV`. **Antes de mexer em coleta, no BD_Thopen, no BD_Performance ou no fechamento, leia o `CLAUDE.md` de lá** e acrescente nele cada regra nova que aprender |
| ~~`os_creator/`~~ | OS Creator | **Migrado em 28/08/2026** para [Grid-Co-CODE/oem](https://github.com/Grid-Co-CODE/oem) — ver `os_creator/MOVIDO.md` |
| `thopen/` | Dashboard BD_Thopen | Flask na porta **5080**, produto para o **cliente**. Servido deste PC (clone `C:\GridcoAuto\PerformancePainel` + túnel trycloudflare); o Railway está fora do ar (404 em 08/10/2026) |
| `gemeo/` | Gêmeo Digital (sombra digital das usinas) | Serviço separado da plataforma: porta **5075** em `127.0.0.1`, banco SQLite próprio fora do OneDrive; quem usa chega por `/gemeo/` na plataforma (proxy do `app.py`). Ainda sem CLAUDE.md: leia `gemeo/README.md`, `gemeo/deploy/README.md` e `gemeo/docs/runbook.md` |

Documentação de arquitetura e regras de negócio: `README.md` e `docs/`.

**REGRA (Levi, 03/10/2026): um `.md` por área, sempre em dia.** Toda alteração em qualquer área atualiza o
`CLAUDE.md` da pasta dela no mesmo trabalho; área sem um ganha um. O Claude lê esse `.md` antes de mexer, em vez de
varrer o código. Escreva o que o código não diz (para que serve, de onde vem o dado, a regra e o caso que a criou, como
provar); regra que mudou se **corrige**, não se empilha. Vale também para o coletor e para o Nexus.

## O que fica na raiz, e por quê

Só o que **não pertence a um projeto sozinho**: `CLAUDE.md`, `README.md`, `requirements*.txt`,
`pytest.ini`, `conftest.py`, `run_tests.bat`, `docs/`, `tests/`, `.env` (a coleta também lê) e
`tokens.txt` (arquivo único que a T.I. edita). Mais `railway.toml` e `render.yaml`, o deploy de nuvem do
Thopen, na raiz porque o Railway só lê a configuração dali (ver `thopen/CLAUDE.md`).

O `Iniciar Dashboards.bat` também está na raiz, mas **não sobe a plataforma, e nem o Thopen**: ele mata o processo
que escuta na 5080 e roda `dashboard_thopen.py` a partir da raiz, onde o script não existe (mora em `thopen/`). Neste
PC a 5080 é o Dashboard do **cliente** (`servir_thopen.py`): rodar o `.bat` derruba o cliente até o vigia religar, em
até 3 min. Não use.

Todo o resto mora na pasta do dono — inclusive **estado de runtime e credenciais**: caches,
histórico de trackers, notas dos analistas, tokens auto-renovados e logs estão em `plataforma/`.

Consequência prática: dentro de `plataforma/app.py` existem duas constantes, e a escolha entre elas
importa —

- **`_AQUI`** = pasta do próprio arquivo → o normal: templates, static, estado, tokens, logs
- **`_RAIZ`** = raiz do repositório → a exceção: `.env`, `tokens.txt`, `docs/` e o `sys.path`
  do `thopen/` — só o que é de fato compartilhado

Ao criar um caminho novo, o padrão é `_AQUI`. Use `_RAIZ` apenas se outro projeto também consome
aquele arquivo.

## Acoplamento conhecido: plataforma → thopen

`plataforma/app.py` importa `dashboard_thopen` e usa **7 atributos** dele para ler o BD_Thopen (hoje o
PostgreSQL, pelo `fonte_api` do próprio `thopen/`): `_CARTEIRA_DE`, `_registro()`, `_daily_records()`,
`_daily_inversores()` (histórico por inversor), `_meta2026()` (metas do relatório semanal), `_wb()` e
`_state["daily"]` (o índice das abas diárias). É resolvido por um `sys.path.insert` no topo do `app.py` apontando para
`thopen/`. Consequência: **nada no `dashboard_thopen` (nem nos módulos que ele importa) pode rodar no import** — sem
thread, sem rede.

Não é acidente: o BD_Thopen é genuinamente compartilhado. Extrair um módulo comum arrastaria junto
`fonte_api`, `_wb`/`_indexa`, `_daily_bd` e `CARTEIRAS` — metade do `dashboard_thopen.py` — por um ganho
que, num repositório único, não se paga. **Se um dia os projetos virarem repositórios separados,
essa extração passa a ser obrigatória.**

## Acoplamento conhecido: Nexus → plataforma, gêmeo e coletor (estrutura das usinas, 13/10/2026)

A tela Base > Equipamentos das usinas do Nexus publica a visão `nexus_estrutura_usina · aba_equipamentos` (o formato da
aba Equipamentos do BD_Performance) das chaves marcadas "no lugar da aba", e cada leitor da aba troca as linhas dessas
chaves por ela, pela mesma regra: a plataforma (`plataforma/estrutura_nexus.py`), o gêmeo (`gemeo/gemeo/ingest/
cadastro.py`), o coletor (`load_name_mapping`, desligado por padrão) e as Ligações do Nexus. Mudou a regra ou o formato
num, muda nos outros no mesmo trabalho. Detalhe em `plataforma/CLAUDE.md` e em `nexus/cadastro/CLAUDE.md` (Nexus).

Desde o Modo de-para (21/10/2026, Nexus 6454293 + plataforma d21dc35): a visão ganhou a coluna **"Código Fracttal"** no
fim, e o `sobrepor` da plataforma, do gêmeo e do Nexus faz a linha da visão **herdar a grafia da aba** (a chave e a Usina
Fractall) quando só os espaços diferem — a "Assis Chateaubriand  Skid 1 (79)", de espaço duplo, sumia dos leitores. O
**coletor ainda não tem as duas regras** (o repositório dele tinha trabalho de outra sessão sem commit): quem ligar o
`load_name_mapping` põe as duas antes.

## Acoplamento conhecido: Nexus → plataforma (chamados no Diagnóstico, 27/10/2026)

O Diagnóstico da usina (`/painel/usina/<id>`, NEXUS > PERFORMANCE > DIAGNÓSTICO) lê o livro que o Nexus publica,
`nexus_chamados · fato_chamado` (o Acompanhamento de chamados), para pôr o problema com chamado aberto em "Explicado / em
tratamento". O cabeçalho está COPIADO em `plataforma/diag_tratamento.py` (o dono é `nexus/dados/fato_chamado.py`); a leitura
é por nome de coluna: coluna nova lá não quebra, renomear quebra. Detalhe em `plataforma/CLAUDE.md`, seção "Diagnóstico: o
que já tem tratamento".

## Acoplamento conhecido: Nexus → plataforma (porta única, 09/10/2026)

O Nexus (outro repositório, `Grid-Co-CODE/nexus`) abre as telas da plataforma numa moldura com um passe assinado
(`NEXUS_SSO_CHAVE`, a mesma nos dois). O contrato mora em `plataforma/porta_nexus.py`: o **mapa das telas** é CÓPIA do
mapa do Nexus (o dono), e os dois lados conferem a mesma assinatura do texto canônico; o formato do passe e o Sair por
`/painel/nexus/sair`. Mudou o mapa ou o passe num lado, muda no outro no mesmo trabalho (o teste cruzado do Nexus roda
contra esta pasta com `PLATAFORMA_REPO`). Tudo fica inerte sem a chave. Regras, variáveis e prova: `plataforma/CLAUDE.md`,
seção "Porta única com o Nexus".

## Convenções (valem para os quatro)

- **Sempre pt-BR**, inclusive comentários de código.
- **Sem emoji na interface** — severidade se comunica por cor. (Exceção herdada: `/painel`.)
- Tema escuro é **navy** (`#090d18` / `#161d30`) + verde Grid. Nunca lilás.
- Comentário de código explica **por que**, de preferência citando o caso real que motivou a regra.
  É o padrão dos arquivos; mantenha.
- Ao citar um arquivo numa resposta, dê o caminho clicável.
- Commit só quando pedido explicitamente.

## Segredos

`.env`, `tokens.txt`, `tokens_runtime.json`, `pg_password.txt`, `se_credentials.txt` e afins são
segredos, já cobertos pelo `.gitignore`. **Nunca imprima `DASH_PASSWORD` nem desligue a
autenticação.** Para validar interface atrás da senha, faça login por sessão lendo a variável,
sem exibi-la.

## Verificação

Este projeto trata **confiabilidade de dado como prioridade 1**. Antes de dar algo por pronto:

- Mudou consulta ao banco? Rode a nova **e a antiga** e compare valor a valor.
- Mudou endpoint? Bata nele de verdade e confira número e frescor do dado.
- Mudou desempenho? Meça antes e depois, e diga o número.
- Se o teste falhou ou você não conseguiu validar, **diga isso** em vez de afirmar que funcionou.

Testes: `python -m pytest -q` a partir da raiz (o `conftest.py` põe `plataforma/` no path). O `conftest.py` também
**recusa toda chamada à SunOp e à PV Operation** (fontes pagas) e quebra o teste que tentou; a rodada termina com
`fonte paga (SunOp/PV Operation): 0 chamada(s)`. Teste que passa por elas dubla a função — ver `tests/README.md`.
