# CLAUDE.md — como trabalhar neste projeto

Dashboard de O&M solar da Grid Co. `app.py` (Flask, ~17 mil linhas, porta **5050**) é a
plataforma de performance interna; `dashboard_thopen.py` (porta 5080) é o produto do cliente.
Arquitetura e regras de negócio: `README.md`, `docs/arquitetura.md`, `docs/regras-de-negocio.md`.

## Rodar e reiniciar

Python real desta máquina (NÃO use `python` puro — o alias do WindowsApps sobe um segundo
processo e você fica com dois app.py disputando a 5050):

```
C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\python.exe   # com console/log
C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe  # sem janela (normal)
```

Ritual de restart — sempre nesta ordem:

1. `py -m py_compile app.py` (ou o python real) — **nunca** reinicie sem compilar antes.
2. Matar **por CommandLine**, não por nome: `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*app.py*" }`.
   Confira quantos PIDs voltaram — **é comum aparecerem dois**; mate todos.
3. Esperar ~4 s, subir com `Start-Process pythonw app.py -WindowStyle Hidden`.
4. Confirmar com `GET http://127.0.0.1:5050/healthz` em laço (sobe em 4–10 s).

Para diagnosticar, suba com `python.exe -u` e `-RedirectStandardOutput` num `.log` — o prewarm
imprime o tempo de cada etapa, o que é a forma mais rápida de achar lentidão.

**O que NÃO precisa de restart:** `docs/redesign/Monitoramento (novo design).html` (a página `/`),
`templates/relatorio.html`, `whats_ronda.json` e `plat_token.txt` — todos relidos a cada uso.
Qualquer mudança em `.py` ou nos outros templates precisa.

## Armadilhas que já custaram caro

- **Hooks do Flask parecem código morto.** `@app.before_request`, `@app.after_request` e rotas não
  têm chamador visível num scan estático. **Nunca remova** por "não é usado".
- **Ler `.xlsx` sempre de uma cópia.** O Excel/OneDrive tranca o arquivo (`Errno 13`). Use
  `_bd_readable_path()`, que já copia uma vez por versão do arquivo. Não volte a copiar por chamada.
- **Banco: o schema `dbt` congela.** É um pipeline da Thopen, não nosso. Quando congela, puxe das
  tabelas cruas `public.raw_*` (`raw_inverter`, `raw_tracker`, `raw_weather_station`), que têm o
  mesmo dado em `json_data` e são hypertables indexadas — costuma ser ordens de grandeza mais rápido.
- **Fuso do banco:** `public.raw_*` usa `timestamptz` (UTC); as views `dbt.*` usam timestamp
  ingênuo em hora local. Converta sempre com `AT TIME ZONE 'America/Sao_Paulo'`. Filtro de tempo
  escrito sem isso pode **zerar o resultado silenciosamente**.
- **Janela de tempo muda comportamento.** Ao filtrar "últimas N horas", lembre que usina muda há
  dias precisa continuar aparecendo para acender o alerta de falha de comunicação — senão ela
  some da tela em vez de alertar.
- **Trabalho pesado no processo web trava todo mundo** (GIL). Um rebuild degrada os outros
  usuários em até 1000×. Não coloque `pandas`/`openpyxl`/SQL longo no caminho de uma requisição.

## Convenções

- **Sempre pt-BR**, inclusive comentários de código.
- **Sem emoji na interface** — severidade se comunica por cor. (Exceção herdada: `/painel`.)
- Tema escuro é **navy** (`#090d18` / `#161d30`) + verde Grid. Nunca lilás. O relatório
  (`templates/relatorio.html`) é claro de propósito, imita documento impresso.
- Comentário de código explica **por que**, não o que — de preferência citando o caso real que
  motivou a regra. É o padrão do arquivo; mantenha.
- Ao citar um arquivo numa resposta, dê o caminho clicável.

## Segredos e dados

`.env`, `tokens.txt`, `plat_token.txt`, `pg_password.txt`, `se_credentials.txt` e afins são
segredos — já estão no `.gitignore`. **Nunca imprima `DASH_PASSWORD` nem desligue a autenticação.**
Para validar a interface atrás da senha, faça login por sessão lendo a variável, sem exibi-la.

As 3 planilhas-base moram no OneDrive mas aceitam override por variável de ambiente:
`BD_PERF_PATH`, `BD_THOPEN_PATH`, `TICKETS_PATH`. O servidor dedicado usa um espelho local.

O token da Plataforma (trackers + combiner) é **manual** — tem CAPTCHA e MFA, não auto-renova.
Vence em ~8 h. Status de todos os tokens em `/api/tokens`.

## Verificação

Este projeto trata **confiabilidade de dado como prioridade 1**. Antes de dar algo por pronto:

- Mudou consulta ao banco? Rode a nova **e a antiga** e compare valor a valor.
- Mudou endpoint? Bata nele de verdade (logando por sessão) e confira número e frescor do dado.
- Mudou desempenho? Meça antes e depois, e diga o número.
- Se o teste falhou ou você não conseguiu validar, **diga isso** em vez de afirmar que funcionou.

Commit só quando pedido explicitamente.
