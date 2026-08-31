# Plataforma de Performance + ronda de trackers

Flask na porta **5050**, uso interno (3 a 6 analistas). `app.py` tem ~19,5 mil linhas — **nunca
peça para lê-lo inteiro**; trabalhe por busca ou por trecho. Ver o `CLAUDE.md` da raiz para as
convenções gerais e a regra `_AQUI` × `_RAIZ`.

## Rodar e reiniciar

Python real desta máquina (NÃO use `python` puro — o alias do WindowsApps sobe um segundo
processo e você fica com dois `app.py` disputando a 5050):

```
C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\python.exe   # com log
C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe  # sem janela (normal)
```

Ritual, sempre nesta ordem:

1. `py -m py_compile app.py` — **nunca** reinicie sem compilar antes.
2. Matar **por CommandLine**, não por nome:
   `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*app.py*" }`.
   Confira quantos PIDs voltaram — **é comum aparecerem dois**; mate todos.
3. Esperar ~4 s e subir a partir desta pasta: `Start-Process pythonw app.py -WindowStyle Hidden`.
4. Confirmar com `GET http://127.0.0.1:5050/healthz` em laço (sobe em 4–10 s).

Para diagnosticar, suba com `python.exe -u` e `-RedirectStandardOutput` num `.log`: o prewarm
imprime o tempo de cada etapa, que é a forma mais rápida de achar lentidão.

**Não precisa de restart:** `docs/redesign/Monitoramento (novo design).html` (a página `/`),
`templates/relatorio.html`, `whats_ronda.json` e `tokens_runtime.json` — todos relidos a cada uso.
Qualquer `.py` ou os demais templates precisam.

**A ronda depende do guardião.** `ronda_guardian.py` roda pela Tarefa Agendada do Windows
"GridCo Ronda Guardian" e sobe o servidor se ele cair, para a ronda das 08:25/13:15 disparar.
A tarefa aponta para o caminho **desta pasta** — se mover o arquivo, atualize a tarefa, senão
a ronda morre em silêncio.

## Armadilhas que já custaram caro

- **Hooks do Flask parecem código morto.** `@app.before_request`, `@app.after_request` e rotas não
  têm chamador visível num scan estático. **Nunca remova** por "não é usado".
- **Ler `.xlsx` sempre de uma cópia.** O Excel/OneDrive tranca o arquivo (`Errno 13`). Use
  `_bd_readable_path()`, que copia uma vez por versão do arquivo. Não volte a copiar por chamada:
  o caminho temporário fixo permitia uma thread truncar o arquivo enquanto outra lia.
- **As planilhas são 100% API desde 25/08** (decisão do Levi). BD_Performance, BD_Thopen e Tickets
  vêm da Gridco Performance API (`app.gridco.com.br/db_performace`), materializadas em
  `plataforma/bases/` pelo `bd_api.py` (laço no worker, 30 min). **Os caminhos do OneDrive foram
  removidos dos resolvedores de propósito** — não os recoloque "por garantia": as duas fontes
  divergem de formas silenciosas (cache de fórmula, lock, sync sobrescrevendo). Emergência = env
  `BD_PERF_PATH`/`TICKETS_PATH`/`BD_THOPEN_PATH`. O espelho NÃO tem tabelas nomeadas (a API não
  as expõe): os leitores resolvem por aba + assinatura de colunas. Ainda fora da API: os CSVs do
  2C (e-mail) e o Budget/Comentários da Polaris (só o 5080 usa).
- **O schema `dbt` do banco congela.** É um pipeline da Thopen, não nosso. Quando congela, puxe das
  tabelas cruas `public.raw_*` (`raw_inverter`, `raw_tracker`, `raw_weather_station`): mesmo dado em
  `json_data`, hypertable indexada, ordens de grandeza mais rápido. Já foi feito para trackers, ETM,
  geração, PR e potência.
- **Fuso do banco:** `public.raw_*` é `timestamptz` (UTC); as views `dbt.*` são timestamp ingênuo em
  hora local. Converta sempre com `AT TIME ZONE 'America/Sao_Paulo'`. Filtro escrito sem isso pode
  **zerar o resultado silenciosamente** (aconteceu: "últimas 2 horas" caiu no futuro e voltou vazio).
- **Janela de tempo muda comportamento.** Ao filtrar "últimas N horas", lembre que usina muda há dias
  precisa continuar aparecendo para acender o alerta de falha de comunicação — senão ela some da
  tela em vez de alertar.
- **Trabalho pesado no processo web trava todos** (GIL). Um rebuild degrada os outros usuários em até
  1000×. Não coloque `pandas`/`openpyxl`/SQL longo no caminho de uma requisição.

## Arquitetura de cache (importante para desempenho)

Os dados vivem em cache na memória e são servidos em 2–4 ms. **São dois processos:** o `worker.py`
roda o `_prewarm_loop` e PUBLICA em `cache_snapshot.json`; o `app.py` só LÊ e serve. No web,
`_swr` com cache vencido devolve `stale` e **não reconstrói** — era justamente a reconstrução no
caminho da requisição que travava todo mundo pelo GIL. (Isto resolveu o gargalo antigo; o
`GRIDCO_SOLO=1` volta ao modo de um processo só.)

**TTL por cache.** O padrão é `CACHE_TTL` (300s). Um cache pode ter validade própria pela chave
`"_ttl"` — é o caso do SunOp/Axis, em `SUNOP_TTL` (600s, pedido do Levi: status de trackers e
inversores a cada 10 min). O `_` no nome mantém a chave **fora do snapshot**: é configuração, não
estado, e o `_cache_load` faz `update` sem apagá-la.

**Pausa noturna da SunOp.** Fora de 05:40–18:20 (`_sunop_janela_curva`), o `_prewarm_filtra_noturno`
tira do ciclo as 6 tarefas que dependem de CURVA da SunOp/Axis e mantém as 3 baratas (last_values) —
é o `ts_max` delas que acende falha de comunicação, então a madrugada não fica cega. ~7.3 mil
requisições a menos por noite. **O portão vale só para o reaquecimento de HOJE:** a primitiva
`_sunop_analog_history` fica aberta porque o `_fecha_dia_loop` (01:30) e os backfills horários
trabalham dias PASSADOS de madrugada, e `force=1`/drill é ação do usuário. Nunca mover o portão
para dentro da busca — há teste travando isso.

**Curva de tracker é INCREMENTAL no dia corrente** (`_sunop_trk_curvas`): busca a partir do último
ponto menos 30 min e funde por timestamp (valor novo vence), com uma busca CHEIA por hora para
reconciliar correção que a SunOp faça atrás. ~76% menos payload; a contagem de requisições NÃO muda
(o lote é de 40 pathnames). Dia passado e cache sem `cheio_h` sempre buscam cheio. Ao mexer nisso,
o teste que importa é o de EQUIVALÊNCIA — fusão errada não dá erro, ela deforma a curva, que é o
insumo de "parado por amplitude".

⚠️ **Armadilha ao mexer no `_prewarm_um_cache`.** Para caches de TTL próprio a margem é o
**período do ciclo**, não 30s fixos, e isso não é preciosismo: com margem fixa, um cache cujo TTL é
MAIOR que o ciclo é pulado numa volta e refeito só na seguinte — o período efetivo vira **2× o
ciclo** (TTL 600 com ciclo de 8,8 min dá 17,7 min, o dobro do que se pediu). A pergunta certa não é
"já venceu?", é "aguenta até eu passar aqui de novo?". Essa regra vale **só** para quem tem `_ttl`:
aplicá-la aos demais os faria reconstruir mais cedo em ciclo curto, ou seja, MAIS requisições.

## Tokens

**Dois arquivos, dois donos.** O `tokens.txt` (raiz) é **semente**, formato `CHAVE=VALOR`, editado
por gente e carregado no ambiente no boot. O `plataforma/tokens_runtime.json` é **estado**: o app
escreve nele (chaves `plat`, `sunop`, `axis`, `se_cookie`) toda vez que renova um token. Não junte
os dois — o app reescrevendo o `tokens.txt` apagaria comentários e arriscaria as outras ~20 chaves
numa corrida com quem estivesse editando à mão. Gravação é atômica (`.tmp` + `os.replace`) sob lock,
porque várias threads renovam tokens diferentes ao mesmo tempo e agora todos moram no mesmo arquivo.
Os antigos `*_token.txt`/`se_cookie.txt` foram migrados sozinhos e renomeados para `.migrado` — não
adianta colar token neles.

O token da Plataforma (trackers + combiner box) é **manual**: tem CAPTCHA e MFA, não auto-renova.
Vale **7 dias** (medido no `exp` do próprio JWT — o mesmo token serve trackers e combiner).
Quando vence, o combiner recebe `HTTP 401`; existe um disjuntor que abre no primeiro 401 e para
de tentar, em vez de repetir ~280 chamadas condenadas por ciclo. Status em `/api/tokens`.

**Como renovar:** bookmarklet de 1 clique, ou `POST /api/pv/trackers/token` com `{"token": "..."}`.
O `tokens_runtime.json` é relido a cada uso, então vale na hora, sem reiniciar. `_plat_token()` escolhe
entre o `PLAT_TOKEN` do ambiente e o arquivo **pela validade maior** — o ambiente é só semente de
boot. Não inverta essa ordem: com "ambiente primeiro", uma semente velha no `tokens.txt` sequestra
a renovação e colar token novo não muda nada (aconteceu em 25/07).

Os demais (SunOp, Axis, SolarEdge, API PV) se renovam sozinhos.
