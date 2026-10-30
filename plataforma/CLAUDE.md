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

**Cópia de prova noutra porta (porta única com o Nexus, 09/10/2026).** Para provar mudança sem tocar na 5050 (a ponte do
OS Creator), suba a worktree com `python plataforma/subir_copia_de_prova.py --porta 5150` (o `__main__` do `app.py` fixa a
5050). É o boot do modo WEB, sem `worker.py`: nada de prewarm, coleta, ronda, fechamento nem backfill; nenhum pedido sai
para SunOp ou API PV, e nada que não seja GET/HEAD/OPTIONS sai da máquina (Fracttal, API db_performace, Graph); o estado vai
para uma pasta no TEMP (`GRIDCO_CACHE_DIR`/`GRIDCO_DADOS_DIR`), nunca para o da plataforma de verdade. Com
`--copiar-estado-de "<pasta plataforma/ principal>" --acompanhar` ela mostra os números da principal (copia o snapshot e
o estado, só lendo a origem, e recopia o snapshot quando o worker publica outro). O import ainda LÊ o cadastro da API
db_performace (GET, ~1 min). Credenciais: `.env` e `tokens.txt` da raiz e `plataforma/tokens_runtime.json`, copiados à
mão (gitignorados). Cookie é por host, não por porta: a cópia em 127.0.0.1 divide o `session` com a 5050 e com o Nexus
local, então use um perfil de navegador só da prova. Moldura, cookies e `postMessage` (mesma origem, como no servidor) se
provam pela `ferramentas/porta_local.py` do Nexus, com as duas cópias atrás dela.

**Não precisa de restart:** `docs/redesign/Monitoramento (novo design).html` (a página `/`),
`templates/relatorio.html`, `whats_ronda.json` e `tokens_runtime.json` — todos relidos a cada uso.
Qualquer `.py` ou os demais templates precisam.

**A ronda depende do guardião.** `ronda_guardian.py` roda pela Tarefa Agendada do Windows
"GridCo Ronda Guardian" e sobe o servidor se ele cair, para a ronda das 08:25/13:15 disparar.
A tarefa aponta para o caminho **desta pasta** — se mover o arquivo, atualize a tarefa, senão
a ronda morre em silêncio. **O guardião só reconhece o `app.py`/`worker.py` DESTA pasta** (`_eh_da_plataforma`): pelo
caminho completo dela, ou pelo nome solto com o processo RODANDO nela (a pasta de trabalho vem do psutil; sem ele, o nome
solto conta, na dúvida). Os dois casos que criaram a regra: em 29/09/2026 qualquer python com "app.py" na linha contava (o
Nexus em temp/Nexus/app.py também) e a 5050 ficou fechada 20 min; em 11/10/2026, no reinício do PC, o Nexus subiu pelo nome
solto (`pythonw app.py`, com a pasta dele), o guardião subiu só o worker e a 5050 (a ponte do OS Creator) ficou fechada até
ser subida à mão. Teste: `tests/test_ronda_guardian.py`.

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
  as expõe): os leitores resolvem por aba + assinatura de colunas. Ainda fora da API: o
  Budget/Comentários da Polaris (só o 5080 usa). Os CSVs da 2C (e-mail) saíram do código em 03/10/2026.
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
(o lote do `analog_values` é de 600 pathnames, `SUNOP_LOTE_PATHNAMES`). Dia passado e cache sem `cheio_h` sempre buscam
cheio. Ao mexer nisso, o teste que importa é o de EQUIVALÊNCIA — fusão errada não dá erro, ela deforma a curva, que é o
insumo de "parado por amplitude".

**Cota da SunOp: 100 mil requisições por mês (29/09/2026).** O extrato oficial (`GET {SUNOP_DATA}/v2/usage/me`, com o
token de API; o `/usage/*` não é cobrável e o dia deles é em UTC, consolidado em lotes) deu **323.816 de 01 a 29/09** e
~22 mil/dia desde 24/09, para um teto de ~3.300/dia. Cortes, todos em `tests/test_sunop_cota_cortes.py`:
- **Status em lotes que atravessam usinas** (`_sunop_last_values_multi`, `SUNOP_LV_LOTE = 1000`): a tabela ia em 19 POSTs
  por leitura (500 por usina) e vai em 7; a ETM ia em 10 (1 por usina) e vai em 1. Nova × antiga com a SunOp de verdade:
  7.002 pathnames, nenhum valor diferente com o mesmo carimbo. Lote que falha deixa sem dados só quem estava nele.
- **`check_token` com validade de 15 min** (`SUNOP_TOKEN_VALIDO_S`): `get_sunop_token` validava na rede a cada chamada e
  `ensure_sunop_meta` (no começo de ~20 montadores) montava o cabeçalho antes do teste de cache. A validade cai quando o
  `/plants` recusa o token (as sessões web já foram derrubadas no servidor em 03/09).
- **Contador completo** (`/api/sunop/uso`): conta o serviço de configuração (`cfg:`), separa a Axis (`axis:`, outra
  conta) e soma ao arquivo do processo anterior — antes cada restart regravava o dia por cima. `_total` é a nossa cota.
- **`SUNOP_COLETA=ronda` no PC** (tokens.txt dele; o padrão, `completa`, é o do servidor): o PC fazia a MESMA coleta do
  servidor. Em modo ronda fica só o que a ronda usa — "SunOp trackers" e "SunOp disponibilidade", com a curva refeita de
  hora em hora (`SUNOP_TRK_TTL_RONDA`; a ronda busca o dia inteiro com `force` na hora de sair e o dia anterior vem do
  fechamento das 01:30). Sem tabela, ETM, strings, Axis, backfill da Falhas nem a Athon na Entrada do PC — quem olha é o
  servidor. Os testes rodam em `completa` por padrão (trava no `conftest.py`): o modo vem do tokens.txt da máquina.
- **A Athon do PC vem do servidor** (12/10/2026, Levi: "a maioria das usinas do tempo real estão sem comunicação"):
  em modo ronda a tabela da Athon não era montada desde 29/09, e o tempo real do PC (o que o Nexus local mostra)
  julgava as 10 usinas pela tabela de 29/09 16:10 — 7 "sem comunicação" e 3 "desligadas", com as 10 normais no
  servidor. O worker do PC lê a tabela que o servidor já montou (`_build_sunop_espelho`, tarefa "SunOp espelho" no
  lugar da "SunOp"; `GET /api/sunop/data` com a senha do painel, a mesma nas duas máquinas, por sessão) e a aba
  serve com `espelho` e sem "SunOp pausada". Nenhum pedido à SunOp; falhou, o SWR segura o último espelho bom. Só a
  Athon (a Axis está sem token nos dois). `SUNOP_ESPELHO_URL` (padrão o servidor), `SUNOP_ESPELHO=0` desliga. Teste:
  `tests/test_sunop_espelho_servidor.py`.
- **Curva de tracker das usinas numa baixa só** (`_sunop_trk_curvas_varias`, mesmo método das strings de 02/09:
  cheia junto em 00:00, incrementais na menor janela; regras em `_sunop_trk_janela`/`_sunop_trk_funde`), chamada antes
  do laço no resumo, na disponibilidade e nos parados: 9 POSTs viraram 3. Nova × antiga real: 80.338 pontos, diferença
  só no quarto de hora ainda aberto (a média dele anda entre as buscas).
- **A Entrada conta os parados da Athon pelo resumo do worker** (`_entrada_trk_do_resumo`, resumo de até 30 min): o
  processo web refazia as curvas de tracker a cada 30 min só para contar. Parados iguais nas 9 usinas (97); "com
  ticket" pelo `parados_com`, o da coluna Tickets.
- **O contador diz de quem é a curva**: `analog_values:trk`, `:str`, `:etm` (pelos pathnames do pedido).
- **O gêmeo mora no servidor; o do PC está desligado de propósito desde 30/09/2026** (corte: um banco só; rodando nos
  dois, os bancos divergem e as chamadas às fontes dobram). Medido em 11/10/2026: o do servidor respondeu em 0,5 s, fontes
  com 13–21 min, `modelar` às 02:14 UTC; o único ReadTimeout (proxy de 30 s) foi às 03:11 UTC, na manutenção diária do
  banco dele. No PC o `/gemeo/` dá 503 sempre: a página diz o porquê (`_gemeo_porque`: no Windows, "desligado de propósito";
  no servidor, timeout = manutenção, tente de novo), em navy para quem navega (a moldura do Nexus) e em texto para o resto
  (Levi, 11/10: "EM gêmeo digital não está dando para acessar!" — a moldura mostrava só "fora do ar (ConnectionError)").
- **O QR de pareamento do WhatsApp nas Rondas de Trackers** (Levi, 11/10/2026: "quando o whatsapp ficar fora aparecer o
  QR code para liberar por ele"). A tela mostrava o QR desde 14/07, mas quase nunca dava para escanear: o watchdog (no
  worker) contava "aguardando QR" como travado (o `/health` dá `ok:false` em UNPAIRED) e reiniciava o node a cada ~6,5 min,
  matando o QR; a tela rebaixava a imagem a cada 30 s com o QR trocando a cada ~20 s; e o `/api/ronda/whats/qr` servia o
  qr.png que o node não apaga ao conectar (em 11/10 era de 05/10). Agora: `_whats_quebrado` não conta "aguardando" (o 500
  do "detached Frame" segue reiniciando); o status traz `qr_versao` (hora do arquivo) e a tela troca a imagem só quando ela
  muda, relendo o estado a cada 5 s enquanto não conecta (`svcRapido`); a rota do QR só serve com o serviço dizendo
  `tem_qr` e o PNG inteiro (503 pela metade, a tela tenta de novo); com o QR à vista o botão Reiniciar some (mataria o QR).
  **Só admin do Nexus vê o QR** (`ROTAS_SO_ADMIN`; quem o escaneia liga a PRÓPRIA conta ao serviço da ronda); a sessão da
  senha vê, como antes. O WhatsApp só existe no PC: no servidor a tela diz fora do ar, sem QR.
- **O estado da ronda na tela vem do disco** (11/10/2026): quem envia é o worker, e o web lia `whats_enviados.json`,
  `whats_log.json` e o watchdog uma vez, no boot — a tela dizia "Não enviada" para a ronda que tinha saído e "nenhum
  restart hoje" com reinícios no dia. O watchdog grava `whats_watchdog.json` (o botão Reiniciar também, e o watchdog
  respeita os 5 min a partir de qualquer um dos dois); o log relê o arquivo antes de acrescentar (antes, web e worker
  apagavam as linhas um do outro). Teste: `tests/test_rondas_qr.py`.
- **Os cortes de 29/09 tiraram só ~15%** (oficial de 30/09: 19.477). A curva de tracker era 86% do resto (8.707 no
  servidor, 9.331 no PC em ronda). **Vazamento (01/10):** a SunOp devolve curva vazia para os trackers da MTS100, o
  `_sunop_eventos_calc` grava a usina assim mesmo (`eventos []`, `cobertura 0`, `classes None`), o dia das
  Ocorrências de Perdas ficava "parcial" nos 92 dias desde 01/07 e o `_perdas_ocor_warm_loop` rebaixava, de hora em
  hora, a curva de cada usina da Athon de cada dia, uma por uma. Agora usina com cobertura 0 não deixa o dia parcial
  (`_trk_ev_sem_curva`), quem a curva de reserva classificou conta como visto (o dia fecha e vai para o cache) e a
  reserva vem numa baixa só. O aquecimento em si saiu do worker em 12/10/2026 (ver "Teto de memória do worker"). Régua antiga × nova
  com dado real: 0 ocorrências diferentes nos 23 dias de curva parcial — tirar também a de cobertura parcial (1ª
  versão, no ar por engano às 10:10 de 01/10 no 1302d77 de outra sessão) sumia com 168. Detalhe e medição:
  `docs/sunop-economia-requisicoes.md`.
- **Teste não grava arquivo de estado** (`conftest.ARQUIVOS_DE_ESTADO`, conferido por `tests/test_isolamento_estado.py`):
  um teste da cota chamava o `_sunop_eventos_calc` de verdade e às 09:51 de 01/10 o `trk_eventos.json` do PC (11,7 MB)
  virou 388 bytes, até o worker regravar da memória. Arquivo de estado novo (`_p_dado`/`_p_cache`) entra na lista.
- **Teto de 3.000 por dia e domingo sem SunOp (04/10/2026**, Levi: "domingo não faz requisições"; "só a ronda
  poderá"). `_sunop_pausa()` → `None`/`"domingo"`/`"teto"`; teto por máquina (`SUNOP_TETO_DIA`: 2.700 servidor, 300 PC),
  contando a Axis e o serviço de configuração. Fecha `_sunop_req`, validação do token, `/plants` e o livro de trackers (só
  banco); o prewarm tira as tarefas da SunOp. A ronda abre a janela (`_sunop_libera_ronda`, em `_ronda_coleta_do_slot`) e
  a retentativa do mesmo horário reaproveita a coleta por 10 min. A retenção segura o último dado bom sem prazo e o topo
  da tela diz "SunOp pausada". O `conftest` desliga a pausa (`SUNOP_PAUSA_LIGADA`); `SUNOP_PAUSA=0` desliga em produção.
  **Token web vencido não vai à rede** (`_sunop_web_vencido`): o da Athon (23/07) e o da Axis (17/07) custavam ~2.850
  recusas por dia no servidor. A Axis está sem dado desde julho: falta o `AXIS_API_TOKEN`. Teste:
  `tests/test_sunop_teto_domingo.py`.
- **Para não repetir (cota da SunOp):** dia fechado sem dado na fonte é resultado, não pendência; laço que refaz
  dia passado tem teto de tentativas; curva da SunOp vai em lote, nunca usina por usina num laço de dias; credencial
  vencida não vai à rede; depois de cada mudança que toca a SunOp, medir o `/api/sunop/uso` das duas máquinas por 1 h
  contra o teto de ~140/h.

**Curva da SunOp pelo acervo do gêmeo (FASE 4, `_sunop_analog_history`).** O gêmeo guarda em UTC; a plataforma lê a
SunOp na hora da usina. Desde 28/09 a janela vai ao gêmeo em UTC e o carimbo volta na hora da usina, no texto da SunOp,
pelo fuso de CADA usina (`_sunop_fuso_usina`: estado da Info Geral → `sol.fuso`, reserva Brasília). Antes o drill de dia
passado saía 3 h adiantado, a pré-análise de ETM da Athon parava (TypeError: carimbo com e sem fuso no mesmo diagnóstico,
parada desde as 08:50 de 28/09) e o PR pegava o EPD da véspera (MRO100 21/09: 1.902 kWh por inversor em vez de 1.198).
Dois testes travam os dois lados: `tests/test_fase4_fuso_da_usina.py` (inclui o fuso do `gemeo/config.toml` igual ao da
plataforma) e o contrato em `gemeo/tests/test_app_curva_fase4.py` — a rota devolve UTC; se o gêmeo passar a devolver hora
local, a plataforma converte duas vezes. O acervo tem strings e trackers pela metade (30–43 dos 48 quartos de hora de
06–18 h por dia, marca d'água da ingestão) e strings a 15 min contra 5 da SunOp: dia passado pelo gêmeo pode vir com
buraco. E o gêmeo que serve só PARTE de uma chamada não economiza pedido — a SunOp recebe o POST do mesmo jeito (190 de
5.036 chamadas de 22 a 28/09: pré-análise de ETM e drill de strings).

**Trackers da API PV têm laço próprio (`_pv_trk_loop`, 22/09/2026) — fora do ciclo do prewarm.** A varredura
baixa o dia inteiro de cada usina (8,8–13,8 MB) e levou **897 s** medida sozinha, contra ~3 min de todo o resto
do ciclo. Dentro da ETAPA 3, que só acaba quando a última tarefa acaba, ela fazia o ciclo inteiro durar ~16 min
em vez de 5 — era o "atualizado 17:48 sobre leitura de 16:54" que o Levi via. No boot, a 1ª volta do laço
espera a 1ª aba principal sair (`_ABA_PRINCIPAL_SAIU`, com teto): a **largada do worker é a hora mais
disputada** — ~25 laços começam juntos sob o mesmo GIL, e boot + ETAPA 1 + aba principal, que custam ~3,6 min
sozinhos, levaram **23 min** no servidor (26 aqui) do boot até a publicação. Consequência prática: cada deploy
deixa a tela com dado velho por uns 20+ min. Não recoloque "PV trackers" no `outros` do ciclo.

⚠️ **Armadilha ao mexer no `_prewarm_um_cache`.** Para caches de TTL próprio a margem é o
**período do ciclo**, não 30s fixos, e isso não é preciosismo: com margem fixa, um cache cujo TTL é
MAIOR que o ciclo é pulado numa volta e refeito só na seguinte — o período efetivo vira **2× o
ciclo** (TTL 600 com ciclo de 8,8 min dá 17,7 min, o dobro do que se pediu). A pergunta certa não é
"já venceu?", é "aguenta até eu passar aqui de novo?". Essa regra vale **só** para quem tem `_ttl`:
aplicá-la aos demais os faria reconstruir mais cedo em ciclo curto, ou seja, MAIS requisições.

**API PV fora do ar não pode travar as outras fontes (24/09/2026).** O ciclo é UM só, em série: ETAPA 2 = aba da
API PV, ETAPA 3 = Athon, Axis, SEMP, Alves Lima, 2C, ETMs e banco, ETAPA 4 = as caras (PR e parados da API PV
entre elas). Em 24/09 a API PV parou de responder às 09:10 (às 14:35 o `/authenticate` não respondia em 150 s):
cada chamada esperava o timeout inteiro, as três passadas do `fetch_all` somavam horas, e às 14:42 o banco da
Thopen tinha leitura das 14:40 enquanto a plataforma mostrava a das 13:50 — o Levi viu TODAS as fontes "sem
comunicação". Três travas: (1) **disjuntor da API PV** (`_PvDisjuntor`, montado no `_http()` só para o host
dela): `PV_DISJ_FALHAS` falhas de REDE seguidas → toda chamada falha na hora (`PVForaDoAr`, subclasse de
`ConnectionError`) por `PV_DISJ_ABERTO_S`; resposta HTTP de erro não conta, a API está viva; (2) **teto na
ETAPA 2** (`_prewarm_aba_principal`, `PREWARM_ABA_PRINCIPAL_MAX_S`): passou, a aba segue em fundo; (3) na ETAPA 3
quem depende da API PV vai por último (`PREWARM_DEPENDEM_API_PV` — tarefa nova da API PV entra nesse conjunto;
um teste confere que os nomes existem no laço), e **quem o teto deixou sem começar vai na frente do seu grupo na
volta seguinte** (`_PREWARM_FICARAM`, `_prewarm_ordem_etapa3`, 30/09/2026): com a fila sempre igual, o fim dela nunca
rodava com a API PV lenta — a tabela de strings da 2C parou em 13:46 no servidor e a análise de ETM dela em 12:32,
enquanto SEMP e Alves Lima, antes na fila, eram refeitas às 15:56. Não muda quantas rodam juntas, só quem entra. Não troque o disjuntor por timeout menor: a API LENTA (48 s por
usina às 12h do mesmo dia) responde, e é por isso que a 1ª passada espera 90 s (`PV_TIMEOUT_1A_PASSADA`).

**Teto em TODA etapa, e nada em dobro (24/09/2026, 15:51).** Uma hora depois, o mesmo defeito com o banco da Thopen:
ele passou a comprimir os dados antigos (TimescaleDB) e a consulta da tabela do Banco (`_pg_build_snapshot`, 30 dias
com `DISTINCT ON`) foi de ~3 s para **83 s sozinha**. Com cópias dela no web e no worker, na plataforma local do PC do
Levi e as órfãs que cada restart deixa rodando no banco, nenhuma terminava — e a ETAPA 3, que só acabava com a última
tarefa, segurou a Athon de novo. `_prewarm_paralelo` espera no máximo `PREWARM_ETAPA_MAX_S`; quem passa segue em
fundo e a volta seguinte não começa outra igual (`_PREWARM_EM_VOO`). E o web não reconstrói mais a tabela do Banco
vencida (`_MODO_WEB` em `_pg_get_snapshot`, como o `_swr`). Consulta órfã no banco se vê em `pg_stat_activity`
(`client_addr` do servidor, `query_start` antes do restart) e sai com `pg_cancel_backend` — é leitura, nada muda.
A consulta em si foi trocada no mesmo dia: em vez de ordenar 30 dias de leituras inteiras, cada dispositivo do cadastro
(`tb_devices`) busca a sua mais nova pelo índice `(device_id, timestamp DESC)` com `LIMIT 1` — 7,8 s contra 875 s
da antiga com o banco carregado, e 6.020 linhas iguais na MESMA foto do banco (`REPEATABLE READ`, o jeito de comparar
duas consultas enquanto o dado chega). Não volte ao `DISTINCT ON` em janela longa: o banco comprime o que passa de 7
dias, segmentado por `device_id`.

**Abrir usina da API PV (drill, `_pv_plant_inversores`, 24/09/2026).** Com a API PV lenta, abrir a Santana do Ipanema
(24 inversores) levava 1–2 min: `day_inverter`, lista de usinas e `plant_devices` iam uma depois da outra (18,5 + 10 +
10,6 s), e à noite a combiner de CADA inversor era consultada (24 chamadas, todas 429). Agora as três vão em paralelo,
os dispositivos vêm do cache de 30 min do `_pv_plant_devices` (só guarda resposta boa — o `_pv_dev_names` guarda até a
falha), a combiner só é consultada em usina String Box do cadastro ou inversor gerando (a porta do `build_summary`), e
combiner que falhou espera `PV_COMB_ESPERA_FALHA_S`. Medido na mesma hora: 34,8 → 11,0 s, resultado idêntico.
**Falha no drill não é usina vazia (30/09/2026, Guatambu 2: "fica 'carregando inversores...' (...) do nada o nome
some").** Passados os 90 s da tela com a API PV lenta, o `loadPlant` guardava `[]` calado (e o 504 `{error}` da rota
também), e reabrir não tentava de novo — o `RD.plants` só se esvazia recarregando a página. Agora a falha vai para
`RD.plantErro` com o motivo e "Tentar de novo" e não fica guardada; aos 10 s a linha diz que está esperando
(`RD.plantLento`); vazio de verdade diz "A fonte não devolveu inversores". No servidor, uma busca por usina de cada
vez (`_pv_plant_em_voo`): quem chega no meio espera a que está correndo e leva o memo de 90 s dela, em vez de abrir
uma segunda igual na API que já está lenta; se ela falhou, quem esperou leva a mesma falha (`_pv_plant_falha`) — às
21:48 a Guatambu 4 deu 504 aos 60 s e a abertura que esperava fez outra busca, 504 aos 120 s. Quem chega depois da
falha tenta de novo. Testes: `test_drill_usina_falha_visivel.py`, `test_drill_api_pv_rapido.py`.
**A linha da usina pelo drill (12/10/2026**, Levi: "quando abrisse e o resultado desse que a diferença é menor ou maior
automaticamente atualizaria o número de diferença da UFV"). A linha vem da tabela montada minutos antes; o drill busca na
hora (SMP100 às 17:23: linha −2 da tabela das 17:18, inversores 5.2 −3 e 6.1 −8). Com o drill mais novo que a linha,
`_resumoDrill` troca ativas, esperadas e diferença pelas dos inversores NA CONTA (diferença = soma das faltas, a régua do
`_dif_por_inversor`; desligado, com OS e sem visão ficam fora, como no drill; inversor na conta sem esperadas = fica a
linha), com o ícone e o título dizendo de quando. Tabela mais nova vence. Reabrir a usina depois de 2 min busca os
inversores de novo sem apagar a lista (a releitura que falha mantém a anterior). Só na tela: a Entrada e o Painel NOC
seguem a tabela. Teste: `tests/test_linha_usina_pelo_drill.py`.

**Teto de memória do worker (11/10/2026).** O worker subiu às 00:39 de 11/10 e às 22:52 tinha 5,5 GB (0,3 GB livres de 20
no PC, na hora do fechamento das 23:30; o PC já tinha travado na noite anterior), e cada restart voltava a passar de 3 GB
em 15 min. Medido DENTRO do worker vivo (`sys.remote_exec` do Python 3.14, script só de leitura, com o Levi autorizando —
o processo não para): às 23:45, 4,3 GB privados; o `_pv_trk_dia_cache` (dia cru de trackers da API PV, também o das
plantas da 2C) era 1,8 GB — 86 entradas de hoje com 3,9 milhões de pontos, ontem, e plantas da 2C de 03/07 e 06/07 com
~273 mil pontos cada, trazidas pelo `_perdas_ocor_warm_loop`; o memo da 2C, 96 MB; o `_trk_eventos`, 88 MB; o resto,
miúdo. "Dia fechado nunca expira" tinha virado "nunca SAI": cada dia vivido (~1–1,8 GB) e cada dia antigo que um laço
tocasse ficavam até o restart — e a reciclagem das 03:00 só vale com 12 h no ar. A regra agora (`PV_TRK_DIA_TETO_PONTOS`
= 1,5 milhão de pontos ≈ 330 MB, `PV_TRK_DIA_OCIOSO_S` = 2 h, `_pv_trk_dia_poda`): HOJE fica fora; o PASSADO tem teto,
imposto na hora de guardar e no faxineiro; passou dele, sai primeiro o que foi lido UMA vez (varredura: aquecimentos, o
ontem que virou passado à meia-noite), o mais antigo antes, e o RELIDO fica — é o backfill da hora relendo os mesmos
pares de cobertura baixa (julho a outubro, 2–7 mil pontos cada), que não pode rebaixá-los da API PV, que é paga; nem "o
dia mais antigo primeiro" nem LRU puro serviam. Dia passado ocioso há 2 h sai. Vale também no web desde 22/10/2026 (ver
"Os caches da API PV com prazo e teto também no web"; até ali era só no worker). O
memo da 2C (`_2c_trk_memo_poda`) e a marca de "dia vazio" (`_2C_TRK_VAZIO_S`) só guardam o que ainda servem. Prova:
`tests/test_worker_memoria_teto.py` — inclusive o MESMO backfill com e sem teto, acervo de eventos e curvas idênticos
(o que sai é dia fechado e volta igual; custa uma busca, não um número).
**Aquecimentos da aba Perdas antiga: fora do worker (12/10/2026, Levi: "extirpa essa porcaria que não serve para nada";
a tela de verdade é a Falhas do Diagnóstico).** O `_perdas_ocor_warm_loop`, o `_perdas_pv_warm_dm1_loop` e as
ocorrências que o fechamento das 01:30 montava enchiam o `_PERDAS_OCOR_CACHE` e o `_pv_trk_dia_cache` DO WORKER, que o
web nunca lê (dois processos, duas memórias — sobra do modo SOLO); para isso baixavam da API PV os dias de julho da 2C a
cada boot. A Falhas lê `trk_eventos.json`, `perdas_strings.json` e `paradas_book.json` (`falhas_job.py`), que o laço de
eventos, o backfill da hora e o fechamento seguem enchendo. Não há gêmeo de strings para tirar: o aquecimento "strings
SunOp/Axis" do ciclo também alimenta o sino e o relatório (`_strings_problema_rows`).
**A aba Perdas do Monitoramento saiu inteira (12/10/2026, Levi: "tira a aba Perdas do menu também — destrói essa
porcaria").** Ela vivia no iframe do Tempo real (`/monitor?fonte=…&embed=1`), ao lado de Strings, ETM, Geração, Trackers,
PR e Curva. Saíram a vista, o item do menu e o `?view=perdas` (cai em Strings), as 9 rotas que só ela usava (ocorrências e
parados de tracker, strings zeradas e ocorrências, qualidade do dado, os quatro exports) e o que só elas alcançavam
(cache e classificação das ocorrências, cobertura por curva, `_str_ev_rows_range`). FICAM, porque outras telas leem:
`/api/perdas/<fonte>/trackers/paradas-hist` (painéis de usina e de portfólio), `/api/perdas/fechamento` (status do
fechamento das 01:30) e a curva de reserva `_trk_ocor_curva_list` (rota de depuração `/api/trk/regua/diff`). Prova:
`tests/test_perdas_fora.py`. Ainda aberto: o backfill do mês do PV (`_trk_ev_pv_mes(force=True)`) reenfileira a cada
hora os ~1.263 pares (usina, dia) que nunca classificam (cobertura 0), ~2,4 h por volta — enquanto roda, o
`_trk_ev_hoje_loop` pula.
**Medido de novo em 20/10/2026 (chat de desempenho do Nexus).** O Raio-X do Nexus no servidor (7,1 GB) mostrou a
máquina com 0,2 GB livres e 3,2 GB no swap às 14:17, este worker com 3 GB às 14:45 e 3,3 GB às 16:12, quando o Nexus
inteiro travou esperando o disco (ele com 1,5 GB no swap). Dentro do worker do PC (`sys.remote_exec`, só leitura, Levi
autorizando), às 15:18, 4,4 GB privados: `_pv_trk_dia_cache` 1,6 GB (o dia de HOJE, 88 usinas e 2,6 milhões de pontos
às 15:24, fora do teto de propósito, ~218 B por ponto `{x, y}`; o passado no teto, 1,47 de 1,5 milhão), o
`_2c_str_dia_cache` 518 MB (hoje e ontem), `_pv_comb_cache` 282 MB, `fonte_api._cache` 171 MB, o resto miúdo; e ~1,3 GB
do próprio processo (o que o alocador guarda depois de liberado). Duas correções, sem mudar nenhum dado:
- **As strings da 2C com um datetime por minuto** (`_2c_strings_dia_api`): cada ponto (datetime, A) tinha o seu
  datetime (48 B de ~112) e um `strptime`; agora o minuto é um objeto só para todas as strings do dia. Dia sintético de
  1.056 strings e 824 mil pontos: de 88 para 57 MB, montado em 5,6 s contra 2 a 3 min, igual valor a valor ao cálculo
  antigo. Teste: `test_o_mesmo_minuto_e_um_objeto_so_nas_strings_do_dia` (`tests/test_2c_sem_email.py`).
- **A memória solta volta ao Linux** (`_limita_arenas` no começo do `worker.py`, `_devolve_memoria` depois de cada
  passada do faxineiro): no máximo 2 arenas de malloc (sem limite, as ~30 threads abrem até 8 por núcleo e a sobra fica
  espalhada) e `malloc_trim(0)`. Só no Linux (no PC nada muda); o efeito se mede no servidor, pelo Raio-X do Nexus
  (seção "Quem ocupa a memória da máquina"). Teste: `tests/test_worker_devolve_memoria.py`.
O maior ganho que sobra é o dia de hoje dos trackers em formato compacto (~400–570 MB no fim do dia), que mexe em todos
os leitores da curva e nas respostas das telas: Levi, 20/10, "não mexa nos trackers agora".
**O relatório de memória do worker, que o Raio-X do Nexus mostra (20/10/2026, à noite).** No servidor o worker foi de
3,7 para 5,0 GB (com o swap) entre 16:12 e 16:38 de 20/10, rápido demais para o que se mediu no PC: um backfill que só
roda lá, e a medição de dentro (`sys.remote_exec`) só dava no PC. A cada passada do faxineiro, depois de devolver a
memória, o worker (`_relatorio_memoria_worker`) estima POR AMOSTRA (`_tamanho_estimado`: contêiner com mais de 100 itens
tem 10 medidos e o resto pela média) e com teto de 3 s quanto cada variável dos módulos da plataforma ocupa, e grava em
`/dev/shm/gridco_plataforma_worker.json` (`RELATORIO_MEMORIA_ARQ`; a memória compartilhada da máquina, que o Nexus, outro
usuário, lê sem configuração: por isso 0644) as 12 maiores, a memória do processo e o histórico das últimas 3 h (18
passadas). Gravado com outro nome e trocado de uma vez: o processo morto no meio deixa o relatório anterior inteiro. Só no
Linux; não muda nenhum dado. O Raio-X do Nexus (seção "Dentro do worker da plataforma") mostra cada variável agora × ~1 h
antes e avisa quando o relatório passa de 30 min (o worker parou de anotar). Teste: `tests/test_worker_relatorio_memoria.py`.

**O web também se mede (21/10/2026).** Raio-X do Nexus às 14:55 de 21/10: o processo WEB (este `app.py` no waitress)
foi de 0,8 GB às 14:36 para 3,1 GB e 0,7 GB no swap, 11 a 30 min depois do deploy das 14:25, com a máquina em 0,2 GB
livres e o disco ocupado 71% do tempo; o relatório e a devolução de memória só rodavam no worker. No modo web, o
`__main__` limita o malloc a 2 arenas (`_limita_arenas`, como o worker) antes de subir as vigias e o `_memoria_web_loop`,
que a cada 10 min devolve a memória livre (`_devolve_memoria`) e grava o mesmo relatório em
`/dev/shm/gridco_plataforma_web.json` (`RELATORIO_MEMORIA_ARQ_WEB`); o Raio-X do Nexus mostra "Dentro do web da
plataforma". O web não roda o faxineiro inteiro, só as podas dos dois caches da API PV (abaixo). Teste:
`tests/test_web_relatorio_memoria.py`.

**Os caches da API PV com prazo e teto também no web (22/10/2026).** O relatório do web, às 08:51 de 22/10, mostrou dois
caches da API PV parados desde antes das 07:59, com a máquina em 0,5 GB livres e 3,6 GB no swap: o dia de trackers
(`_pv_trk_dia_cache`, 545 MB em 19 dias de usina abertos no gráfico de trackers) e o dia de strings
(`_spv_hist_recs`, 493 MB em 3 dias; o "~6 MB cada" do código era a usina de 4 inversores, e a de 20 tem ~28,8 mil
registros no dia, ~165 MB). Levi: "resolva esses da API PV que estão atrapalhando". Agora:
- o dia de strings sai quando ninguém o relê há `SPV_HIST_OCIOSO_S` (20 min: o drill e o CSV do mesmo dia vêm em
  minutos), e a soma dos registros tem teto (`SPV_HIST_TETO_REGISTROS`; sai o lido há mais tempo, e o que acabou de
  entrar fica, mesmo sozinho acima dele), além dos 3 dias de antes (`_spv_hist_poda`, na hora de guardar, a cada 10 min no
  web e no faxineiro do worker);
- a poda do dia de trackers (o passado parado há 2 h e o teto de 1,5 milhão de pontos, ver "Teto de memória do worker")
  vale também no web, na hora de guardar e a cada 10 min. Ficava só no worker porque a aba Perdas lia esse cache no web
  sem buscar; a aba saiu em 12/10, e o único leitor que não busca um dia passado é a rota de depuração da régua.
O que sai é dia FECHADO: pedido de novo, volta igual, ao custo de uma busca na API PV (no dia de strings, 1 consulta da
cota histórica da conta). Os combiners da API PV (`_pv_comb_cache`, 159 MB no worker) ficam como estão: é o dia de hoje
de cada usina, trocado a cada leitura, não acumula. Teste: `tests/test_api_pv_caches_no_web.py`.

## Ponte do Nexus: chave só de leitura e sub-caminho (04/10/2026)

O Nexus (`Grid-Co-CODE/nexus`, torre Performance → Tempo real) mostra a Entrada e o Monitoramento desta plataforma por
uma ponte, só leitura (Levi: "tudo da plataforma, só leitura", "em paralelo por enquanto"; a meta é a plataforma morar
100% no Nexus). A ponte manda `X-Nexus-Leitura` (= `NEXUS_LEITURA_TOKEN`, no `.env`/tokens.txt, nunca no git) e
`X-Forwarded-Prefix: /t/performance/plataforma`. Com a chave, o `_auth_gate` deixa passar só o que
`leitura_nexus.permitido` aceita (páginas do tempo real, leituras das fontes e 3 POSTs de consulta); gravação é 403,
mesmo com a plataforma aberta. Toda resposta que o portão deixou passar pela chave leva `X-Nexus-Leitura-Ok: 1`
(`_nexus_confirma_a_chave`; nunca em 401/403 nem em pedido sem a chave): a ponte do Nexus só mostra resposta que o traga,
porque uma plataforma sem `NEXUS_LEITURA_TOKEN` ignora a chave e responderia a tudo, inclusive gravação. **Rota nova numa
página do tempo real precisa entrar na lista** —
`test_a_lista_cobre_as_rotas_das_paginas` quebra se não entrar. O modo sub-caminho passou a pôr o prefixo nos
atributos `src`/`href`/`action` do HTML, nos links criados depois da carga e no `window.open`; a Entrada lê o nível
pelo caminho sem o prefixo (`_partesDoCaminho`). Sem chave e sem prefixo, nada muda.

**A chave também recusa os parâmetros que disparam trabalho** (`PARAMETROS_QUE_DISPARAM`: `force`, `forcar`, `run`, `backfill`) e o `/api/perdas/fechamento`, mesmo em GET; `/static` passa (já é público).

**Pedido do Nexus não fala com a API PV (05/10/2026**, Levi: "por hora não puxa nada da API da thopen, estou tentando
economizar requests e tenho medo que duplique as chamadas"). A API PV (`*.pvoperation.com*`) atende Thopen, SEMP, Alves
Lima e 2C-API. Pelo Nexus vale só o que a plataforma já tem. Três travas, todas em `leitura_nexus.py`:
- `NEGADOS_API_PV`: o drill que abre a usina na API PV na hora é 403 pela chave (rodaria, falharia e poderia guardar a
  falha no cache de todo mundo). Lista espelhada na ponte do Nexus (`nexus/performance/ponte.py`).
- `instalar_trava_api_pv` (chamada logo depois do `_http()`): em pedido do Nexus o `requests` recusa o host da API PV
  com `PVForaDoAr` (não conta no disjuntor), e a marca segue para a thread e para a TAREFA de pool que o pedido abrir —
  o operário do pool é de todo mundo, por isso a marca vai no `submit`, não na thread.
- O pedido do Nexus não monta cache: `_swr` serve o que tem (ou `aquecendo`), a Entrada não dispara o build e a tabela
  do Banco (`_pg_get_snapshot`) não é consultada com o cache frio — era a consulta de até 83 s no banco da Thopen, achada
  pelo mesmo teste na suíte inteira. Montar com a API PV travada guardaria para todo mundo um cache sem ela.
Medido com a rede cortada antes da trava: 10 rotas da chave chamavam a API PV (no pedido, nos operários do pool da SEMP e
da 2C e no build da Entrada); depois, nenhuma. `tests/test_nexus_sem_api_pv.py` chama TODA rota GET que a chave alcança
com a rede cortada e falha se alguma falar com a API PV; rota nova que vá à API PV na hora entra em `NEGADOS_API_PV`.

**O que o calço do sub-caminho NÃO cobre:** atribuição direta de `.src`/`location.href` com caminho absoluto no JavaScript (use `window.__pfx(...)`, como a Entrada faz com a moldura do Monitoramento), `url()` em CSS, `srcset`, `<meta refresh>`, e "Abrir em nova guia"/copiar link de `<a>` criado depois da carga (o clique e o clique do meio são corrigidos na hora).

Testes: `tests/test_leitura_nexus.py`, `tests/test_prefixo_subcaminho.py`.

A ponte FICA no código até a Operação em tempo real (visão "Pelo banco") entrar no Nexus; no menu do Nexus quem abre o
Tempo real passa a ser a moldura da porta única (seção abaixo). A chave `X-Nexus-Leitura` sai na fase 3; a lista dela
(`permitido`) não mudou com o gestor, que tem a sua (`permitido_gestor`).

## Porta única com o Nexus: passe, perfis e modo Nexus (09/10/2026)

Levi, 09/10/2026: "a partir de segunda quero o Nexus como link principal; o Nexus será o centro de tudo, precisamos trazer
o tempo real de performance painel para o Nexus". Desenho aprovado: "uma porta, dois motores"
(`docs/superpowers/specs/2026-10-09-performance-no-nexus-design.md`, no repositório do Nexus). O Nexus é a porta (menu,
login, endereço); a plataforma continua o motor e desenha as próprias telas DENTRO de uma moldura (iframe) do Nexus, na
mesma origem (`app.gridco.com.br/nexus` e a raiz). Código: `porta_nexus.py` (puro: mapa, passe, perfis), o bloco "Porta
única" no `_auth_gate` e logo abaixo dele no `app.py`, `leitura_nexus.permitido_gestor`.

**Inerte sem as variáveis** (a plataforma sobe por push na main; nada pode mudar antes de a T.I. pôr as chaves). Sem
`NEXUS_SSO_CHAVE`: `/painel/nexus/*` é 404 e nenhuma resposta muda (nem modo Nexus, nem CSP, nem perfis).

| Variável (`.env`/`tokens.txt`) | Para quê |
|---|---|
| `NEXUS_SSO_CHAVE` | chave do passe, a MESMA do `.env` do Nexus; 32+ caracteres aleatórios (`secrets.token_urlsafe(32)`); menor = desligada, com aviso no log |
| `PLATAFORMA_ANALISTAS` | e-mails (vírgula) ou `*`: entram como analista (tudo o que a senha faz). Decisão do Levi: começa com `*` |
| `PLATAFORMA_GESTORES` | e-mails ou `*`: gestor, só leitura. O e-mail escrito vence o `*`; escrito nas duas (ou `*` nas duas), vale gestor |
| `NEXUS_PORTA_PRINCIPAL` | **fase 3, desligada vazia**: com `/nexus/` (ou `http://127.0.0.1:5070/` no PC), o `/` leva ao Nexus (logado ou não; nunca dentro de moldura) e o login oferece "Entrar pelo Nexus", com a senha virando reserva. O botão leva à tela do `next` (`<valor sem a barra final>/t/<torre>/<tela>?p=<next>`, `_entrar_pelo_nexus_href`) quando ela é do mapa, e ao Início quando não é (auditoria B6, mais abaixo). Na fase 4 (o Caddy manda o `/` ao Nexus, que mora na raiz) use o endereço completo `https://app.gridco.com.br/`: o `/` sozinho mandaria o `/` ao próprio `/`, em laço, para quem chegasse direto ao waitress |

**O passe (contrato com o Nexus).** A página da tela no Nexus faz um POST (formulário escondido, `target` = a moldura;
sem JavaScript, um botão "Abrir") para `/painel/nexus/entrar` com o campo `passe` = `base64url(json) + "." +
base64url(HMAC-SHA256(json))`, sem `=` (aceito com ou sem). A assinatura é sobre os BYTES do JSON do primeiro segmento.
JSON: `{"v": 1, "email", "nome", "admin": true|false (NEXUS_ADMINS), "destino": "/tela?query", "vence": epoch em s (no
máximo 60 s à frente; mais que 65 s é recusado), "numero": 16 a 128 de [A-Za-z0-9_-]}`. A plataforma confere formato,
assinatura (`compare_digest`), versão, vencimento (número finito: o JSON sem `NaN`/`Infinity`, que deixavam o passe sem
vencer), e-mail, destino (só tela do mapa, caminho local; nada de redirecionamento aberto; nenhum segmento que,
decodificado, seja `.`/`..` ou traga barra: `/gemeo/%2e%2e/tokens` o navegador resolve como `/tokens`) e, por último, o número (uso único; guarda os dos últimos 2 min, em memória: o web é um processo só). Passou:
`session.clear()` e abre a sessão DELA (`auth`, `auth_kind="nexus"`, `user`=e-mail, `nome`, `perfil`, `admin_nexus`,
`nexus_ate` = agora + 12 h, `nexus_chave` = HMAC da chave), não permanente (o cookie some ao fechar o navegador) e 303 para
o destino. Recusa: página "Abra de novo pelo Nexus" com o motivo, 403, sessão nenhuma. Fora das listas: "Sem acesso à
Performance", 403. Nos dois casos a sessão de PASSE que já estivesse aberta no navegador cai junto (a da senha fica):
na cópia de 10/10, depois de um gestor, um login fora das listas via "Sem acesso" e seguia com a sessão do gestor. O passe
e o Sair só valem da MESMA origem (`_de_outra_origem`: `Sec-Fetch-Site` só `same-origin`/`none`; sem ele, `Origin` deste
endereço; `null` não): `same-site` também é recusado, porque no servidor qualquer subdomínio de gridco.com.br é
`same-site` e uma página ali entregaria o passe do atacante (login trocado) ou forçaria o Sair. POST, nunca na URL:
o passe leva o e-mail. O Sair do Nexus faz POST (`target=_top`) em `/painel/nexus/sair` com `volta` = o caminho para onde
seguir (só caminho deste endereço); encerra só a sessão do passe (a da senha fica).

**A cada pedido da sessão do passe** (`_portao_da_sessao_do_passe`): vencida (12 h) ou chave trocada/retirada → sessão
apagada, segue como quem não entrou (spec 8: trocar a chave derruba o passe, não a senha); perfil refeito pelas listas
de hoje; gravação (método fora de GET/HEAD/OPTIONS) só da mesma origem (403 "pedido de outro site": antes, um
`<form enctype=text/plain>` de qualquer site gravava em nome do analista); administração só com `admin_nexus`, em
qualquer perfil (`porta_nexus.ROTAS_SO_ADMIN`: `/tokens`, `/api/tokens*`, `/api/admin/*` (as bases do espelho e os
caminhos do servidor), `/api/ronda/whats/testar`, `/reiniciar`, `/grupos` e `/qr` (o envio pelo chip, a qualquer
número, o serviço do WhatsApp e, desde 11/10, o QR de pareamento); 403 página/JSON. Efeito: o botão "Reiniciar serviço" das Rondas de Trackers é só de admin para
quem entra pelo Nexus; a senha segue como hoje); gestor só passa no
`permitido_gestor` (403 "somente leitura (perfil gestor)") e o pedido dele leva `g.nexus_so_leitura`, que faz o
`pedido_do_nexus()` valer: a API PV fica travada (a mesma trava da ponte) e o pedido não monta cache. Quem grava pelo passe
fica no diário com o e-mail (`_quem_na_sessao`, no lugar de "senha compartilhada").

**O cookie** (`_SessaoDaPlataforma`, só com a chave): `SameSite=Lax`, e `Secure` quando o pedido chegou por https
(o waitress 3 apaga cabeçalho de proxy não confiável: com a chave, o `serve()` confia no 127.0.0.1, o Caddy, só
para o esquema, `_waitress_atras_do_caddy`; o IP e o Host seguem os de sempre). Sem a chave, o
`session=...; HttpOnly; Path=/` e o waitress de sempre. Lax não
atrapalha a moldura (mesma origem) nem o bookmarklet da Plataforma (rota pública, sem cookie). Revisão adversarial de
10/10/2026, com os testes no fim de `tests/test_porta_nexus.py`.

**Gestor** (`leitura_nexus.permitido_gestor`): as páginas de toda tela do mapa, as leituras da ponte mais `_GET_GESTOR`
(as das outras telas), `POSTS_DE_CONSULTA_GESTOR` (os 3 da ponte + `/api/fracttal/os`), sem `force/forcar/run/backfill`,
sem `/api/perdas/fechamento`, sem `NEGADOS_API_PV_GESTOR` (o lado API PV do Diagnóstico: `/api/diagnostico/pv/`,
`/api/painel/correlacao/pv/`, `/api/plant/`, `/api/spv/usina/`...). Para o gestor a tela de uma usina da Thopen abre sem o
que vem da API PV na hora: é o combinado ("sem abrir a API PV na hora"). Rota nova numa tela entra em `_GET_GESTOR`,
`POSTS_DE_CONSULTA_GESTOR` ou `GRAVACOES_GESTOR` — `test_a_lista_do_gestor_cobre_as_rotas_das_telas` lê os templates.

**Modo Nexus.** Página com sessão do passe E `Sec-Fetch-Dest: iframe` sai com `class="modo-nexus"` no `<html>` (posta pelo
servidor, `_porta_do_nexus_na_resposta`), o CSS `html.modo-nexus [data-casca]{display:none}` e um calço que avisa a
moldura `postMessage({tipo: "nexus:rota", caminho}, location.origin)` na carga e a cada `pushState`/`replaceState`/
`popstate`; `caminho` = `pathname + search`, sem o prefixo. Só a página de cima da moldura avisa (o `/monitor?embed=1`
que o Tempo real embute é moldura dentro da moldura). Cada template marca com `data-casca` o que é navegação da
plataforma (a marca, "← Início", "‹ Entrada", "Monitoramento", a barra do Monitoramento); contexto da tela ("←
Portfólio", "Relatório semanal Thopen", "Disponibilidade") fica. `test_toda_pagina_com_link_para_a_entrada_o_marca_como_casca`
quebra se um `<a href="/">` novo ficar sem a marca. `/` na moldura leva a `/tempo-real` (o menu do Nexus faz o papel da
Entrada). Na moldura SEM sessão (venceu), em vez do login por senha dentro do Nexus: "Abra de novo pelo Nexus", 401, com
a senha num link `target=_top` de reserva. Navegador sem `Sec-Fetch-Dest`: a tela com os dois menus, funcionando.

**`Content-Security-Policy: frame-ancestors 'self'`** em toda resposta HTML, só com a chave (spec, fase 1: "desligados
sem a chave"); junta-se a uma CSP que já exista. Investigado em 09/10 antes de ligar: ninguém de fora emoldura a
plataforma. A Entrada embute o `/monitor` na mesma origem; o casco `/os/` do OS Creator Web embute as próprias abas na
mesma origem; a ponte do Nexus busca no servidor e não repassa este cabeçalho; o supervisório da Engenharia emoldurado no
OS Creator é de outro endereço e não é a plataforma; o Thopen (Railway) e o App de Campo não emolduram nada daqui. No PC,
porta diferente é OUTRA origem: a moldura só abre atrás da `ferramentas/porta_local.py` do Nexus (como no servidor).

**O tema do Nexus nas telas (12/10/2026**, Levi: "em Falhas de strings e trackers falta o tema claro"). A aba de Falhas
era sempre navy na moldura; agora o navy vale só com o Nexus no escuro (`html.modo-nexus:not([data-tema="claro"])`), e o
claro usa o claro do Nexus (desde o redesenho de 20/10/2026; antes, as cores da identidade do site). O tema vem do cookie `nexus_tema` (ou do localStorage `nexus.tema`) antes da 1ª
pintura, e o botão do Nexus troca a tela na hora pelo evento `storage` (chega às molduras da mesma origem). Tela nova com
navy próprio no modo Nexus segue a mesma régua. Teste: `tests/test_falhas_tema_nexus.py`. **Sem botão de tema dentro do
Nexus (13/10/2026**, Levi: "tira o botão de tema das telas da plataforma também", depois de o 2º cabeçalho sair): o Painel
NOC (`#darkBtn`, `painelDark`) e a Visão gerencial (`#tema`, `ger.tema`) marcam o botão com `data-casca` e, no modo Nexus,
seguem o tema do Nexus pela mesma régua (cookie, localStorage, `storage`; o NOC remonta o histórico, que pinta com as cores
do tema). Quem diz "no Nexus" é o `window.gcModoNexus` do calço, e não o nome da classe: fora do Nexus a página sai sem
ele (`test_porta_nexus`). Fora do Nexus, cada tela segue com o botão e a escolha dela. Teste:
`tests/test_tema_nexus_noc_gerencial.py`.

**Os responsáveis de cada usina, pela moldura (12/10/2026**, Levi: "Quero um filtro de responsável -> Visão gerencial").
O nome da pessoa só existe decifrado no Nexus (no banco o cadastro guarda as pessoas cifradas, e a plataforma não tem a
chave, de propósito). A Visão gerencial, dentro da moldura, pede `postMessage({tipo: "nexus:pede-responsaveis"},
location.origin)` à janela de cima e recebe `{tipo: "nexus:responsaveis", mapa}` — {chave do nome da usina: {"om":
responsável O&M, "gestor": gestor de contrato}}, `null` sem o cadastro —; aceita só da `window.parent` e da mesma origem.
A chave do nome (`_chaveUsina`) é a MESMA do `chave` do Nexus (`nexus/performance/responsaveis.py`: sem acento,
minúsculo, pontuação vira espaço, romano vira número): mudou num lado, muda no outro no mesmo trabalho. O seletor
"Responsável" (O&M e gestor, com quantas usinas cada um tem) só aparece com o mapa, e recorta junto com o Cliente
(`deriva`, que refaz o portfólio no recorte). Medido em 12/10 contra o Gerencial do PC: 140 de 161 usinas casam; as 21
sem ligação no de-para publicado ficam fora quando um responsável é escolhido (o título do seletor diz quantas). Fora do
Nexus o seletor não aparece. Teste: `tests/test_gerencial_filtro_responsavel.py`.

**O mapa** (`porta_nexus.MAPA`, spec 5.6) é a CÓPIA do mapa do Nexus (o dono): 15 telas, ids do Nexus (Performance
`tempo-real`, `noc`, `diagnostico`, `strings-trackers`, `gerencial`, `disponibilidade`, `gemeo`, `monitor-ronda` =
"Rondas de Trackers"; Relatórios `relatorio`, `relatorio-semanal` e `potencia-ativa`; COS `acompanhamento`; Base
`chaves-fontes`, `fontes-tempo-real` e `de-para-equipamentos`, só admin). Os relatórios foram para a torre Relatórios em
13/10/2026 (Levi: "vai para a central de emissão no Nexus > Relatórios [...] Sai da parte de Performance!"): no Nexus
eles abrem pela Central de emissão, filtrados pelo setor; aqui só muda a torre (o `/t/<torre>/<tela>` do "Entrar pelo
Nexus"). Os dois lados conferem o mesmo texto canônico (`texto_canonico_do_mapa`, uma linha `torre|tela|caminho|tambem|admin`
por tela) pela assinatura `69aca055f5d2c37a` (`test_o_mapa_e_a_copia_do_nexus`): mudou lá, muda aqui. Em 11/10/2026 o Histórico da plataforma
(`/historico-plataforma`, `historico_pv.html`) foi APAGADO, rota e template (Levi: "Pode matar a seção histórico da
plataforma!"); as APIs que ele lia (`/api/pv/trackers` e o gráfico por tracker) ficam, servem a outras telas. Rota de página nova entra no `MAPA` ou no
`FORA_DO_MAPA` com o porquê (`test_toda_rota_de_pagina_tem_lugar_no_mapa`).

**Provado de ponta a ponta no PC (10/10/2026)**, esta cópia de prova com a chave e a cópia do Nexus da branch da porta
única, atrás de um proxy que imita o Caddy nos dois modos (prefixo `/nexus` cortado, o servidor de hoje, também com a
camada de reescrita da T.I. junto; e raiz, a fase 4), Chrome sem janela a 1440 px:
- as 13 telas abrem na moldura com `modo-nexus` e nenhum `data-casca` visível; o número da moldura é o MESMO da tela
  direta no mesmo minuto (Tempo real, Painel NOC, Strings e trackers, Gerencial, Disponibilidade, Monitor da ronda,
  Acompanhamento COS, de 47 a 4.310 números por tela); o `?p=` acompanha o clique dentro da tela (Tempo real -> fonte,
  "investigar" do Painel NOC -> Diagnóstico, "Visão Gerencial" da Disponibilidade -> Gerencial) e o F5 volta ao lugar;
- a sessão `session` desta plataforma e a `nexus_sessao` do Nexus vivem juntas (entrar numa não derruba a outra);
- analista grava (um comentário na `ufv_state.json` da cópia, apagado em seguida; a da pasta principal não mudou); o
  gestor lê as 11 telas e leva 403 ao gravar, no `?force=1`, no `/tokens` e no lado API PV (o gráfico do Histórico da
  plataforma fica vazio para ele: é o combinado); fora das listas, "Sem acesso" e a sessão de passe cai;
- os passes repetido, adulterado (admin, destino ou assinatura), vencido (62 s), com destino fora do mapa, na URL (405) e
  de outro site são recusados, com o motivo, e nenhuma sessão abre; o Sair do Nexus apaga a sessão do passe;
- moldura sem sessão (a de 12 h venceu): "Abra de novo pelo Nexus", 401, e o item do menu reabre com passe novo; outra
  origem (`localhost` emoldurando `127.0.0.1`) é bloqueada pelo `frame-ancestors`, a mesma origem abre;
- sem a chave: `/painel/nexus/*` = 404, nenhuma CSP, nenhum modo Nexus, e o Tempo real do Nexus segue pela ponte;
- fase 3 ligada: o `/` leva ao `/nexus/` (logado ou não), o login oferece "Entrar pelo Nexus" e, na moldura, o `/` vira o
  `/tempo-real`. No Git Bash o valor `/nexus/` vira caminho do Windows (use `MSYS_NO_PATHCONV=1`): a fase 3 fica
  desligada, com o aviso no log;
- abrir pela moldura custa ~100 ms a mais que direto (a página do Nexus, o POST do passe e o 303). O gêmeo deu 503 (não
  está de pé no PC). A `porta_local.py` do Nexus guardava cookies entre clientes até 10/10/2026 (corrigido lá).

**Revisão adversarial, provada de novo no PC (10/10/2026, de madrugada)**, as mesmas cópias e o mesmo proxy, modos
prefixo e raiz:
- o passe e o Sair só da mesma origem: `same-site`, `Origin` de outro host, `Origin: null` e `cross-site` dão 403 sem
  abrir sessão; `same-origin` e `Origin` deste endereço abrem; passe com `"vence": NaN` e com destino
  `/gemeo/%2e%2e/tokens` dão 403;
- com sessão de analista, o POST `text/plain` de outro site (e o `same-site`, e o `Origin` de fora sem
  `Sec-Fetch-Site`) leva 403 "pedido de outro site" e nada é gravado; o da mesma origem grava (na cópia; a pasta
  principal não mudou);
- analista sem admin leva 403 em `/api/admin/bases` e no POST `/api/admin/base/...`; o admin lê (o envio e o
  reinício do WhatsApp só nos testes, para não tocar no serviço real do PC);
- o cookie sai `SameSite=Lax`; atrás de https sai `Secure` também, mas só depois de o `serve()` confiar no Caddy para o
  esquema (`_waitress_atras_do_caddy`): a primeira rodada mostrou que o waitress 3 apagava o `X-Forwarded-Proto`;
- a página do Entrar do Nexus encerra a sessão do passe (`/api/state` 200 -> 401); as 13 telas, o analista que grava,
  o gestor e o Sair seguem como na prova da véspera; sem a chave, 404 em `/painel/nexus/*`, nenhuma CSP e o cookie da
  senha sem `SameSite`, como hoje.

**Antes de alguém depender no servidor:** sondar `POST /painel/nexus/entrar` — tem de responder `Server: waitress` com
`Via: 1.1 Caddy` (404 sem a chave), nunca 502 vazio do Caddy.

**A sessão venceu no meio da tela: número que não veio não vira zero (10/10/2026, auditoria A5).** A sessão do passe
vale 12 h fixas; depois todo `/api/` dá 401 `{"error": "não autenticado"}`, e as telas que releem sozinhas desenhavam o
erro como dado: o Painel NOC (`/api/macro` a cada 60 s) mostrava "Energia perdida 0,0 MWh" numa tela de NOC (provado no
código de antes: 10,0 → 0,0 MWh). Regra, que vale para TODA tela, com e sem a chave (a sessão da senha também vence, em 30
dias): **só resposta 2xx vira número; a leitura que falha não troca nada, fica o último valor com a hora dele, e a faixa
diz por quê.** Peças:
- `aviso_de_sessao.js` (`gcSessaoDaPlataforma`), injetado INLINE logo depois do `<head>` de toda página da plataforma
  (`_aviso_de_sessao_na_resposta`; não no `/login` nem no que é de outro serviço pelo proxy: `/gemeo/`, `/os/`). Não vai
  por `/static/`: com o Nexus na raiz o Caddy manda `/static/*` ao Nexus, menos fonts, logos e notif.js. Embrulha o
  `fetch`: 401 de uma rota `/api/` deste endereço = sessão vencida. Na moldura (o calço do modo Nexus marca
  `window.gcModoNexus`; só a página logo abaixo do topo) mostra "Sessão vencida: abrindo de novo pelo Nexus" e manda
  `postMessage({tipo: 'nexus:sessao-vencida', caminho}, location.origin)` (o caminho sem o prefixo, como o `nexus:rota`),
  no máximo 1 vez a cada 60 s; aos 15 s sem reabrir, acrescenta "clique de novo no item do menu". **Contrato com o
  Nexus**: a moldura, ao receber, pede um passe novo e reabre o mesmo `?p=`, também no máximo 1 vez a cada 60 s, e
  renova sozinha antes das 12 h. Fora do Nexus: "Sessão vencida: entre de novo", com o link do login que volta à tela. O
  `/monitor?embed=1` que o Tempo real embute passa o aviso para a página de cima (quem a moldura conhece) e só se lembra
  dele. `falhou(motivo, quando[, fim])`/`voltou()`: a faixa "Não atualizou (...): os números na tela são de ..." para
  rede/500; `fim` troca o resto da frase na tela que lê uma vez e não tem número velho nem tenta de novo (o Diagnóstico);
- cada tela guarda o último valor: Painel NOC (`_lerOk`; o "carregando" do web recém-subido também não vira 0 usinas;
  sem nenhuma leitura, "—", nunca 0,0 MWh), Tempo real/Entrada (o 401 virava "Fonte desconhecida" no nível 3 e martelava a
  cada 8 s; agora 60 s), Monitoramento (`fetchJSON` dá erro no 401 sempre e, com `exigeOk`, em qualquer não-2xx; sem
  `rows` a tela desenhava os EXEMPLOS do protótipo — 76 usinas, 505 strings — e os cards de exemplo somem com erro na
  tela), Disponibilidade ("Calculando a primeira varredura…"), Monitor da ronda ("DESLIGADA", "FORA DO AR"), Strings e
  trackers e Gerencial (mês apagado; o seletor volta ao mês da tela), Chaves das fontes ("Precisam de você: 0" em verde),
  Acompanhamento COS ("Montando o índice"). O mês com `erro` também não é mês: o `/api/gerencial` com a leitura do PG
  falhando (mês passado, ou o corrente sem snapshot: web que subiu sem ele, plataforma local depois do TTL de 300 s)
  responde **503** `{"erro", "usinas": []}`, nunca 200; com 200 o Painel NOC trocava o mês bom pelo vazio ("Energia
  perdida 0,0 MWh", "0 MWp", "Mês/PG <agora>" como se fosse fresco; revisão adversarial de 10/10/2026, provado com o PG
  simulado fora), e o seletor de usinas do Nexus não dizia que o Gerencial faltou. O Painel NOC (`boot`) e o Gerencial
  (`load`) também recusam corpo com `erro`, venha com o status que vier. Conferidas e já certas:
  Criador de relatório e Relatório semanal (conferem `d.ok`, não releem sozinhos). O Diagnóstico NÃO estava certo (a
  carga do `boot()` desenhava o corpo do erro): ver "Diagnóstico de usina com a fonte fora", logo abaixo.

**Diagnóstico de usina com a fonte fora: não é usina parada (10/10/2026, prova da porta única).** Com a API PV em 504, o
`/painel/usina/<id>` mostrava "Inversores 0 · 0 sem produção", "Strings 0 / 0 ativas", "Hoje 0 kWh · PR mediana 0%" e
"A fonte não devolveu inversores para esta usina": a tela de uma usina parada. Duas causas, as duas corrigidas: a tela
lia `fetch(...).then(r => r.json())` e desenhava o corpo do erro como dado; e várias rotas engoliam a falha da fonte e
respondiam 200 com vazio. Regra: **cada leitura falha por conta própria; a que não veio mostra "—" e o selo "Fonte X não
respondeu (HTTP 504) às HH:MM: sem leitura — não é ...", e o zero DE VERDADE (a fonte respondeu, e é zero: de madrugada,
usina sem tracker, sem OS) continua 0.** A diferença vem do backend:
- rotas que agora dizem que falharam (o corpo segue no formato de sempre, mais `erro`, `fonte` e `fonte_ok: false`, porque a
  tela antiga `?antigo=1` e o Painel NOC leem o JSON sem olhar o status): `/api/plant/<id>` 504 também com o dict de erro
  da API PV (o 429 da cota virava a usina montada pelo cadastro, TODOS os inversores desligados); `/api/diagnostico/pv/<id>`
  504 (era "Sem anomalias — usina dentro do esperado"); `/api/pv/trackers/<id>` (e a 2C pela API PV) 502 e fora do cache
  (era 0 trackers por 5 min); `/api/pv/trackers/<id>/chart` 502 quando a API PV e a reserva não responderam (intervalo com
  dia faltando: 200 com `parcial`); `/api/pg/trackers/<id>` e o `/chart` 503 com o PG fora (a falha fica só
  `_PG_TRK_FALHA_S` = 30 s no cache); `/api/pg/plant/<id>` 503 com o snapshot frio (o pedido do Nexus só lê o que existe);
  `/api/spv/usina/<id>` 502 com o dict de erro (era "Sem dados de inversores"); `/api/solaredge/plant/<id>` 502 quando a
  lista de dispositivos não veio; `/api/fracttal/os` 502 (a 1ª falha encerra a busca, o que chegou antes vai `parcial`; o
  `_frac_wos_raw` não guarda mais a falha como "sem OS" por 10 min, nem o `_frac_ativo_exato` como "ativo não existe" por
  12 h); `/api/os-performance` 502 quando não há índice nenhum porque o Fracttal não respondeu a varredura (a página que
  falha não é mais "fim da lista": o índice anterior fica, nada é gravado, e por `FRAC_OSPERF_FALHA_S` = 60 s não se varre
  de novo); `/api/cascata` segue 200, com `fracttal_ok`/`fracttal_erro` (queda de energia e equipamento) e `trk_ok`/`trk_erro`
  (livro de paradas).
- a régua de "falhou" das funções muito dubladas nos testes NÃO ganha parâmetro novo: o `_pg_trk_plant_curvas` deixa o
  motivo na entrada do cache (`_pg_trk_curvas_erro` lê), o `_pv_trk_grafico` em `_pv_trk_graf_falha` e o `se_devices` em
  `_se_dev_falha` (quem chama confere se a falha é deste pedido, `ts >= início`). As que já tinham lista opcional
  (`falhas=` no `_frac_os_filtradas`/`_frac_wos_raw`/`_frac_ativo`) ficaram assim.
- a tela (`painel_usina_v2.html`): `_dgLer(url, {exige, ms, post})` é a régua do `_lerOk` do Painel NOC — só 2xx com dado;
  401 é da faixa de sessão; corpo com `fonte_ok: false`, ou com `erro` no lugar da lista que a leitura promete, também é
  falha. `FALHA[k]` por leitura (plant, irma, diag, trk, fracttal, osPerf, desde 11/10 eday, plantVelho, pr e invpr — ver
  o parágrafo seguinte — e, no modo histórico, hInv/hDisp/hMen/hDia/hTk);
  `_dgSelo(k, oQue)` escreve o selo; `_dgFaixa()` junta as fontes fora numa linha da faixa do `aviso_de_sessao.js`
  (`falhou(motivo, '', fim)`). Os 5 cartões, as abas Inversores, Trackers (com a releitura que falha num dia já lido: fica a
  última leitura boa DAQUELE dia, com a hora), Curvas (a falha não recua mais para ontem como se fosse "ainda sem curva"),
  Mês (motor de diagnóstico, cascata com o degrau sem leitura em "—", OS, mapa de strings, cards de tracker) e o modo
  histórico (`?hist=1`: "todos no alvo", "ainda não tem quebra por inversor" e "fora do Fracttal" saíam do corpo do 500).
  PR que não respondeu é "PR mediana —" (o `false*100` dava 0%). A planta irmã (Nova Londrina) que não respondeu tira a
  usina inteira dos cartões, com o nome dela no selo.

**A leitura que veio pela metade também não vira zero (11/10/2026, revisão adversarial do conserto acima).** Nove
caminhos em que uma PARTE da leitura falhava e a tela seguia afirmando; regra: **o que depende de uma leitura que faltou
fica sem leitura, mesmo que a rota dele tenha respondido.**
- **OS por inversor dependem da lista de inversores.** O POST do `/api/fracttal/os` leva os nomes que a fonte devolveu;
  com a fonte fora ele ia vazio, a rota respondia 200 só com as OS da usina e o cartão dizia "Fracttal · OS abertas 0" — é
  o print da prova (P_2f). Com `FALHA.plant`/`FALHA.irma` (`_osInvSemLista`) o cartão fica "—" com o selo da fonte que
  faltou, e a lista de OS diz que só tem as do nível da usina, nunca "Nenhuma OS". A irmã que respondeu entra: o
  `completarIrmas` pede as OS de novo com os inversores das duas plantas (antes os da irmã nunca iam), com `_osSeq` para a
  resposta velha não sobrescrever a nova.
- **Energia do dia do PG e da RenoGrid vem do PR do dia** (`_inv_eday_do_pr`), que não tem reserva velha. Com o PG fora e o
  snapshot ainda servido (no web o `_pg_get_snapshot` serve o velho sem limite de idade), todo `eday` vinha None e às 10:00
  a tela dizia "30 sem produção" e "Hoje 0 kWh". O `/api/pg/plant` e o `/api/solaredge/plant` (este pelo
  `_se_eday_falha`, mesma régua do `_se_dev_falha`) mandam `eday_ok: false` + `eday_erro`; a tela liga `FALHA.eday`: "Hoje
  —" com o selo e o `v2Status` deixa de tomar `eday` nulo como prova de inversor parado. O `/api/pg/plant` manda também
  `cache_ts`, `snapshot_idade_s` e `snapshot_velho` (acima de `PG_SNAPSHOT_VELHO_S` = 30 min): os números ficam, com
  "não atualizou (snapshot de N min): números da leitura das HH:MM" (`FALHA.plantVelho`, sem faixa).
- **SunOp sem ler** (pausa de domingo, teto do dia, borda aberta, Axis sem token de API e web vencido): o
  `_sunop_plant_build` devolvia `[]` e o `/api/sunop/plant` respondia 200 com a lista vazia ("Inversores 0", "Hoje 0
  kWh"). O motivo fica em `_so_plant_falha` (`_sunop_motivo_sem_leitura` diz qual: pausa, borda, credencial) e a rota
  responde **502**; com um drill bom guardado, serve o retido com `retido: true`, `erro_releitura` e `cache_ts` = hora da
  leitura (`lido` na entrada do cache, porque o `ts` é renovado para não reconstruir a cada pedido). O
  `/api/sunop/trackers/<usina>` (e Axis) com a usina fora do metadata responde **503** (não pede o metadata: é chamada
  paga); usina no metadata sem tracker segue 200 com `tem_trackers: false`, que é o zero de verdade.
- **De-para do Fracttal sem leitura não é "usina fora do Fracttal".** O `_frac_codebase_index` lia a página que pegou 429
  como fim da lista e gravava o parcial por 12 h; agora levanta, fica o índice anterior, nada é gravado e por
  `FRAC_CB_FALHA_S` = 60 s não se varre de novo (`_frac_cb_falha`). O `_frac_fractall_map` com o xlsx travado no boot frio
  marca `_frac_bd_falha`. `_frac_depara_falha(usina)` diz se a usina sem entrada é falta de leitura; o `/api/fracttal/os` e
  o `/api/os-performance` respondem 502, e a `/api/cascata` põe em `fracttal_ok: false`.
- **PR do mês por inversor (BD_Performance).** O `_bdperf_pr_inv` guardava a falha (planilha travada) 30 min no cache com
  `inversores: {}`; agora não guarda e o `/api/inv/pr-mes` responde **503**. Na tela, `FALHA.invpr`: pílulas "—", selo no
  mapa de strings e a lista de diagnósticos não afirma "Sem anomalias — usina dentro do esperado" (enquanto o PR do mês
  não chega, "Cruzando com o PR do mês…"). Trocar o mês limpa o PR anterior antes de pedir. O PR do mês é pedido em TODA
  saída do mapa de strings (`renderHeat` → `loadInvPR` no `finally`): com o drill fora, String Box ou tudo trancado ele
  nunca era pedido.
- **PR do dia que não respondeu** (`/api/pv/pr/<id>`: `day_inverter` com o dict de erro, ou `day_meteo` fora — era 200 com
  todo PR nulo) responde **502** (`falha`/`falha_ipoa` no dict do `_pv_pr_collect`/`_pv_pr_compute`). Na tela, `FALHA.pr`:
  o cartão Inversores diz "abaixo dos pares: <selo>" em vez de "0 abaixo dos pares" em verde, e a linha que só estaria "ok"
  vira "PR sem leitura" (cinza).
- **Motor de diagnóstico sem os trackers** (`_pv_trackers_analise` com `fonte_ok: false`): o R-09 dizia "sem tracker
  travado associado" e mandava olhar a combiner. Agora o payload leva `trk_ok`/`trk_erro`, o R-09 diz "trackers sem
  leitura: não dá para descartar tracker" (confiança baixa) e os cards de tracker por inversor ficam `sem_leitura`.
- **PDF de strings** (`/api/spv/pdf`): o `api_spv_usina` devolve `(Response, 502)` desde 10/10, e o `.get_json()` da tupla
  derrubava o PDF inteiro com 500. A usina sem leitura sai numa página "Usinas sem leitura neste relatório" (nunca "Todas
  as strings OK"); só usinas sem leitura = 502 com a lista.
- **Monitoramento** (`docs/redesign/Monitoramento (novo design).html`, `loadPlant`): o corpo de falha com `inversores: []`
  passava pelo `!d.inversores` e a linha dizia "A fonte não devolveu inversores desta usina"; erro com a lista vazia, ou
  `fonte_ok: false`, é falha ("Não consegui carregar os inversores", com "Tentar de novo").
Fica de fora, de propósito: o `gerencial.html` e o `_gCarregarOsEv` do Painel NOC, que leem a `/api/cascata` e a
`/api/fracttal/os` sem olhar `fracttal_ok`/status (seguem sem eventos de OS com o Fracttal fora, como antes); e a tela antiga
`painel_usina.html` (`?antigo=1`), que lê o JSON sem olhar o status — os corpos de falha seguem no formato de sempre para ela.
Testes: `tests/test_diagnostico_fonte_fora.py` (cada rota com a fonte dublada fora e o zero de verdade ao lado; a página
inteira no node com a rede dublada, um cenário por cartão e aba, PV, PG e modo histórico) e
`tests/test_diagnostico_leitura_parcial.py` (os nove caminhos de 11/10, com o zero de verdade ao lado; o harness ganhou
`antes=` para relógio fixo e rota que responde conforme o corpo do POST). Rodados contra o código de antes: os de falha
quebram (25 de 63 nos três arquivos, incluído o do Monitoramento), os de zero de verdade passam nos dois.
Prova no navegador (Chromium, 1440 px), app da worktree na 5151 com a rede cortada, dados falsos e sessão de 15 s, atrás
de uma moldura de teste: a moldura recebeu `nexus:sessao-vencida` com `/painel` (e `/tempo-real/athon` quando o 401 veio
do `/monitor` embutido), uma vez só em 60 s; os números ficaram (12,5 MWh) e a faixa apareceu centrada. Essa prova achou
dois erros que o node não via (a faixa com `left:50%` encolhia para metade da tela; a tela embutida, depois de passar o
aviso para cima, cobria a explicação com "Não atualizou"), corrigidos.

**As três pontas da prova (11/10/2026, cópia com navegador).** (1) A faixa de aviso (`aviso_de_sessao.js`) fica
EMBAIXO (`bottom:12px`) e tem "×": no topo, com cinco fontes fora, tinha 77 px e cobria o seletor de dia e o "← Portfólio"
(não dava para trocar o dia). O "×" fecha só aquele aviso: o mesmo texto não volta sozinho, um diferente volta; o "voltou"
zera. A faixa do Diagnóstico cita só as FONTES (`API PV, Fracttal`); o motivo e a hora ficam no selo de cada cartão. (2)
Sem sol não há PR no PG: abaixo de `PR_IPOA_MIN` (0,05 kWh/m² no dia) o PR é `None` ("—") — às 03:00 a estação lia ruído
e a tela dizia "PR mediana −0%"; com sol e geração zero o PR 0% continua (usina parada de verdade), e sai `0.0`, nunca
`-0.0`. (3) `/api/pv/pr/<id>` com a autenticação ou a lista de usinas da API PV fora responde 502 `{erro, fonte, fonte_ok}`
(era 500 em HTML, e a lista que falhava virava 404 "usina não encontrada"); a usina que não existe continua 404. Prova:
`tests/test_diagnostico_pontas_11_10.py`.

**"Entrar pelo Nexus" volta à tela pedida (10/10/2026, auditoria B6).** Abrir uma tela pelo Nexus troca a sessão de
30 dias da senha pela do passe (12 h, que some ao fechar o navegador); no dia seguinte o favorito cai no
`/login?next=/painel` e o botão levava ao Início do Nexus. `_entrar_pelo_nexus_href`: o `next` passa pela régua do
`_login_next` e pelo `destino_permitido` do passe (é o que o Nexus vai pedir com ele) e vira
`<NEXUS_PORTA_PRINCIPAL sem a barra final>/t/<torre>/<tela>?p=` com o caminho como o navegador o escreve; fora do mapa,
o Início. Inerte sem a fase 3. O `next` chega de dois jeitos, e o `?p=` tem de sair igual nos dois: o do portão vem
DECODIFICADO (`/painel/usina/São Bento`, ele monta `quote(caminho)`) e o da faixa "Sessão vencida: entre de novo" vem JÁ
codificado (`encodeURIComponent(location.pathname+search)`). Até a revisão adversarial de 10/10/2026 o botão codificava
de novo o segundo (`S%25C3%25A3o`) e o Diagnóstico abria com o nome `S%C3%A3o%20Bento`: leituras pelo nome vazias, falso
"sem OS/sem meta". Regra: o escape que já existe fica (`%` a salvo; `%` solto, sem dois hexadecimais, vira `%25`), os
sinais que o navegador deixa crus ficam crus (`+` na query é espaço) e só acento, espaço, aspas e `#` são codificados.
Decodificar e codificar de novo não serve: o `%26` de um nome (`A%26B`) viraria `&`.

**O next do login não sai deste endereço (revisão adversarial de 10/10/2026).** Uma régua só,
`_caminho_deste_endereco`, para o `_login_next` (senha), o `oauth_next` e o botão do login Microsoft e o "Entrar pelo
Nexus": começa com uma barra, não com duas, e sem caractere de controle (`\x00-\x1f`, `\x7f`) nem barra invertida. Antes,
com sessão aberta, `/login?next=/%09/mal.exemplo.com/entrar` respondia 302 para `//mal.exemplo.com/entrar`: o navegador
(regra de URL do WHATWG) e o Werkzeug tiram TAB/LF/CR e leem a barra invertida como barra, e sobra o endereço de outro
site. O espaço passa de propósito (o next do portão vem decodificado, e espaço no meio do caminho não muda de endereço).
O `volta` do `/painel/nexus/sair` segue com a régua dele, mais estrita (recusa também o espaço: vem do Nexus, codificado).

**Avisos para quem não é admin (10/10/2026, auditoria B12).** `gcSessaoDaPlataforma.semAdmin` (o app.py marca quem
entrou pelo passe sem `admin_nexus`): a curva das strings com o token da PV Plataforma vencido diz "peça a um
administrador do Nexus" em vez de mandar à tela Tokens (`_curvaMotivoTxt` no Monitoramento, pelo `globalThis`: os testes da curva rodam a função sozinha no node; `tokens(msg)` no Diagnóstico,
que troca o "Renove/Cole um na tela Tokens." do `_SPV_MOTIVO_MSG`). O "Reiniciar serviço" das Rondas de Trackers mostra o
403 na hora ("Só administradores reiniciam o serviço") em vez de girar ~80 s.

Testes: `tests/test_porta_nexus.py` (passe válido, vencido, adulterado, repetido, na URL, de outro site; destino fora do
mapa; fora das listas; analista grava; gestor 403 ao gravar e lê cada tela do mapa; `/tokens` só admin; sem chave, 404 e
nada muda; troca de chave e 12 h derrubam a sessão; frame-ancestors em todo HTML; modo Nexus só com o passe na moldura;
`/` na moldura; fase 3 desligada e ligada), `tests/test_porta_nexus_gestor_sem_api_pv.py` (toda rota GET do gestor com a
rede cortada: nenhuma fala com a API PV; tirando a marca `nexus_so_leitura`, o `/api/entrada/tempo-real` falava),
`tests/test_sessao_vencida_sem_numero_falso.py` (o aviso no node: moldura, 60 s, só `/api/` deste endereço, fora do
Nexus, embutido; a injeção; cada tela com 401/500 rodando o código da própria página; o `/api/gerencial` com o PG fora
dá 503 e o Painel NOC/Gerencial não zeram com `erro`; o link "Entrar" da faixa encadeado pelo `/login` até o `?p=` que
o Nexus lê, igual a `location.pathname+search`) e `tests/test_porta_nexus_destino_e_avisos.py` (o "Entrar pelo Nexus"
com destino, os avisos de B12 e o next com `%09`/`%0a`/`%0d`/`%5C` na senha, no GET com sessão e no login Microsoft).

## Diagnóstico: o que já tem tratamento (fase 1, 27/10/2026)

**Para que serve.** NEXUS > PERFORMANCE > DIAGNÓSTICO é esta tela (`/painel/usina/<id>`, `painel_usina_v2.html`, aberta
pela porta única; o Nexus só põe a moldura e o seletor). Levi, 27/10/2026: cada problema sai com CAUSA PROVÁVEL + PROVA +
AÇÃO, e o que já tem tratamento vai para um grupo "Explicado / em tratamento", deixando na frente só o que ninguém está
olhando. A lista (`renderDiags`) agora tem "Sem tratamento N" na frente (a tabela de sempre) e, embaixo, um `<details>`
recolhido "Explicado / em tratamento N" com inversor/escopo · problema · causa provável · prova (o nº da OS com link
`/os/os/folio/<n>`, o mesmo das Falhas) · desde · ação. Faixa âmbar = em tratamento (OS ou chamado aberto), verde =
explicado (a OS que tirou o ativo já fechou). Um nível de superfície, sem emoji (saíram o `causaIco` da linha e o da frase
"Sem anomalias").

**A regra (fase 1, SEM parâmetro: nenhum limite de dias, nenhum filtro), em `diag_tratamento.py` (puro):**
- **OS de desligamento/religamento no período que cobre o ativo = explicado.** Desligamento/religamento = os tipos da
  Disponibilidade (`disponibilidade.TIPOS_ALVO`: Religamento, Religamento Remoto, Corretiva Emergencial), lidos do índice
  que o worker já monta para o Gerencial (`_frac_disp_dados`, o `frac_disp_index.json`; as `oss` do mês, sem as `excl`).
  Nenhuma chamada nova ao Fracttal. Cobrir = a hierarquia da Disponibilidade: OS da usina inteira cobre todo inversor; a
  da cabine N, os inversores da cabine N (a cabine vem do `inversores` do índice; sem ele, do N de "Inversor N.M"); a do
  inversor, só ele. Período: o problema DE AGORA (motor da fonte R-07..R-10, o básico das strings) só se explica pela OS que
  pega hoje (aberta, ou fechada hoje); o problema DO MÊS (`_per:'mes'`: "Subperformance mensal", "abaixo da meta",
  "Usina abaixo da meta no mês", este só pelas OS da usina inteira) pela que pegou algum dia do mês (o mês do seletor do
  PR). A prova leva as horas de sol que a OS tirou no mês (`h_solar` do índice): a regra não pesa, mas quem lê vê se 2 h
  de religamento "explicam" um mês abaixo da meta.
- **Chamado de garantia aberto para o ativo = em tratamento, "Aguardando fabricante há N dias"** (`verificacao`: "Chamado
  em verificação (aberto há N dias)"). Fonte: o Acompanhamento de chamados do Nexus, NÃO a planilha de tickets (regra de
  12/10/2026): o livro `nexus_chamados · fato_chamado` (situação `aberto`/`verificacao`), lido pelo `cobertura.Decisoes` +
  `depara_fracttal.LivroEmFundo` (cópia de 10 min em `nexus_chamados.json`; o Nexus regrava aos :50). Usina = o site
  (`site_fracttal` = a "Usina Fractall" do cadastro). Ativo = o código, pela régua da Disponibilidade (INVR/DINV N.M =
  inversor; CABN/SKID/QGBT/PECN/DTRF N = cabine; o code-base sozinho = usina). N dias = hoje − `data_id_abertura` (a da nota
  na OS retroativa). Chamado de tracker (ETKR), NCU, RSU, estação e o inversor de almoxarifado (`-PGINVR`) NÃO ligam a
  problema nesta fase (vão em `outros`): o nº do tracker do Fracttal não tem de-para provado com o do supervisório.
- **A OS aberta que a tela já lê do Fracttal** (`OSBYINV`, Corretiva inclusive: o "Acompanhar OS" que já existia) também
  põe o problema em tratamento: alguém está olhando.
- Fase 2 (sujidade, vegetação, rondas) espera os limites do Levi (dias sem limpeza, dias sem ronda): não invente.

**Rota:** `GET /api/diagnostico/tratamento?usina=<nome de exibição>&mes=AAAA-MM` → `{usina, cabines, inversores, outros}`
(cada inversor já com tudo o que o cobre), `os_ok`/`os_erro` (índice frio, mês fora do índice, mês do BD_Thopen) e
`chamados_ok`/`chamados_erro`. A leitura que faltou fica dita: a tela põe tudo na frente com o selo "não cruzei com as OS
de desligamento e os chamados: o que está abaixo pode já ter tratamento", nunca "sem tratamento" afirmado. O gestor do
Nexus alcança pelo prefixo `/api/diagnostico` do `_GET_GESTOR` (só leitura, sem API PV); a ponte não precisa.

**Medida no dado real (27/10/2026 ~15h, só leitura: o índice do servidor pela `/api/gerencial/disponibilidade`, o PR do
mês pela `/api/inv/pr-mes` das 136 usinas e o livro de chamados do banco; os problemas DE AGORA não entraram, porque o
motor lê a API PV na hora):** 68 problemas do mês em 136 usinas; 61 iriam para "Explicado / em tratamento" (25 usinas) e 7
ficariam na frente. Dos 61: 12 com OS aberta, 8 com chamado aberto do inversor, e 41 SÓ por OS já fechada no mês (37 delas
de "Usina abaixo da meta no mês" pela OS da usina inteira) — 20 desses 41 somam menos de 12 h de sol fora. É o ponto a
decidir com o Levi: a regra pedida não pesa a OS contra o tamanho do problema. Dos 247 chamados em aberto, 96 são de
inversor/cabine/usina (os outros 151, tracker e afins, ficam em `outros`); 3 da Nobres não ligam porque a Classificação 1
do Fracttal diz "RenoGrid - Nobres 1 - CE" e o cadastro (e o próprio ativo RNGD-NBS100) "MT" — Levi, 27/10: "Nobres muda
para MT", e depois "não tem como editar, faça uma adaptação": a rota soma aos sites da usina o `g1` (o site como o
Fracttal escreve) das OS que a Disponibilidade já ligou a ela, em qualquer mês do índice — a Disponibilidade casa pelo
miolo, sem a UF. A OS de outra usina não ensina site. A Barretos (Fracttal
1.21–1.40 = cadastro 2.1–2.20) foi resolvida no mesmo dia por `disponibilidade.INV_RENUMERADO`.

**Como provar:** `tests/test_diagnostico_tratamento.py` (os casos reais de Barretos 1 em 27/10: OS 17016 aberta no 1.14,
OS 15510 da cabine 1 fechada em 13/10, OS 16520 da usina de madrugada, chamado 17159 do 1.1 com a Sungrow há 127 dias,
chamado de tracker e de almoxarifado fora; a rota; a página inteira no node). Mutações conferidas: a OS fechada valendo
para hoje, o chamado concluído contando, a cabine sem cobrir, a OS excluída contando, a tela sem o período, a tela sem
separar, o OSBYINV de fora e o N de dias errado quebram os testes.

## Painel NOC (`/painel`, `templates/painel_portfolio.html`)

- **Enxuto (13/10/2026)**, Levi: "Em painel NOC tire o botão de "Ao vivo" e remova o dashboard "Agrupamento"". Saíram a
  pílula "AO VIVO" do topo (só dizia que a visão Tempo real estava ligada; o seletor Tempo real/Histórico já diz) e o card
  "Agrupamento" (a barra de status por carteira, região e estado, com a decomposição recurso × desempenho do mês), com o
  `renderRegion` e o seletor dele. Prova: `tests/test_painel_noc_enxuto.py`.
- **À la Nexus (16/10/2026)**, Levi: "refaça o design de nexus > performance > painel noc, tem que ficar alá Nexus" e,
  sobre a 1ª versão, "tá muito azul pô" (aprovado depois). Só o desenho; dado, rotas e cliques são os mesmos:
  - **tokens do `nexus.css`** (claro em `:root`, escuro no `body.dark`) com os nomes de sempre da tela (`--panel`,
    `--red`...): o JavaScript lê as cores daí (`cssv`), então blocos, linhas e gráficos acompanham. O `#16140e` (texto
    sobre o verde) e o `#c2410c` (sem produção) viraram `--sobre-brand` e `--laranja`. Fontes do Nexus: Poppins no
    texto, Raleway no título; ícones Phosphor (os mesmos do Nexus) no lugar dos emojis das causas;
  - **cabeçalho das telas do Nexus**: "PERFORMANCE", "Painel NOC" e a linha do que a tela responde, com Tempo
    real/Histórico e a hora à direita; a barra da plataforma (logo, Início, Monitoramento, Tema) é `data-casca` e some
    na moldura (o botão de tema também, como pede o `test_tema_nexus_noc_gerencial.py`);
  - **um nível de superfície**: os números do topo na faixa do Nexus (`gc-numeros`); Saúde da frota e Anomalias direto
    no fundo, e os blocos e as anomalias são os cartões (eram três azuis um dentro do outro); a cor fica no estado (a
    faixa lateral do bloco e o número), a linha "gerada · P50" vai neutra, e o que era azul de enfeite vai a cinza;
  - sem o pulso do "Tempo real" e sem o pulinho do bloco (o Windows pede menos movimento).
  Mockup aprovado com o template servido por um proxy só de leitura sobre o 5050, dentro da moldura do Nexus.

## Fontes do tempo real (11/10/2026)

Levi: "Antes o controle do que entra e o que não entra em tempo real estava sendo do Claude, eu passava as instruções e o
claude inseria ao meu gosto. Precisamos de um espaço para administração do que entra no tempo real onde eu possa através da
fonte permitir qual usina entra e qual não entra." Até aqui a lista de cada fonte morava em constantes (`PV_FONTES`,
`scadagridco.FONTES`), no Full O&M do BD_Performance (só a API PV principal) e em "tudo que a conta devolve" (SunOp,
SolarEdge, banco) — e mudar exigia commit e deploy. Regras dele, na mesma conversa: **usina nova espera a liberação, com
notificação**; a escolha vale no **Tempo real, no Monitoramento, no Painel NOC e na ronda**; usina tirada **para de ser
coletada** (os dias fora ficam sem dado).

- **A tela**: `/admin/tempo-real` (`templates/fontes_tempo_real.html`), no Nexus como Base · Fontes do tempo real; só admin
  do Nexus (`so_admin` no mapa; a API mora em `/api/admin/tempo-real/{fontes,decidir,migrar}`). A sessão da senha entra,
  como no `/tokens`. Por fonte: a lista do que ela devolveu, a situação (no tempo real / fora / nova) e os botões Tirar,
  Incluir, Liberar e Manter fora.
- **O dado**: livro `nexus_tempo_real · fato_decisao_cobertura` (registrado no catálogo do Nexus), uma linha por decisão,
  só acrescenta (`cobertura.Decisoes.acrescentar`: relê, grava inteiro, confere a contagem). O vigente é a última decisão
  de cada fonte × chave nativa. Sem pessoa no banco (leitura aberta): quem decidiu vai a `logs/cobertura.log`. PC e
  servidor leem o MESMO livro, com cache de 60 s e a última leitura boa em `cobertura_decisoes.json`.
- **Trava contra apagar o histórico** (20/10/2026, governança do Nexus, ao abrir o `nexus_falhas`; vale para os três livros
  que a `Decisoes` grava: `nexus_tempo_real`, `nexus_depara` e `nexus_falhas`). O "relê, grava inteiro" tinha um buraco: o
  `_ler_banco` devolve [] quando a listagem `/api/sheets` omite a aba por um instante, e o sync com `replace=true` gravava
  só as linhas novas — o livro inteiro trocado pela decisão do momento —, com a conferência passando (ela compara com o
  que acabou de enviar). Agora o `acrescentar` recusa (`GravacaoErro`) pela mesma conta do `livros._conferir_antes` do
  Nexus: (1) a releitura com MENOS linhas do que a última leitura boa desta máquina (memória, ou a cópia em disco no
  processo recém-ligado) não grava — inclusive quando `/api/workbooks` e `/api/sheets` somem juntos e o livro pareceria
  novo (o POST de livro aceita chave que já existe e o replace apagaria tudo); (2) livro que existe e voltou vazio só
  grava se o banco disser que ele não tem aba (`sheet_count` 0: o livro criado cuja 1ª gravação caiu no sync, como a do
  De-para em 11/10 — sem isso ele ficaria travado para sempre); sem o `sheet_count`, ou com aba, é soluço e não grava.
  Livro novo de verdade grava. Teste: `tests/test_decisoes_trava_historico.py` (revisão adversarial de 20/10).
- **Foto de hoje (migração)**: uma fonte só é governada depois das linhas `migracao` (botão "Começar a controlar com a foto
  de hoje"): incluir para o que aparecia pela regra de antes (`_cob_visivel_hoje`: Full O&M na `pv`, a lista fixa nas de ids
  fixos, tudo nas outras), excluir para o resto do inventário. Sem a foto, a fonte segue como antes; a `pv` recusa a foto
  com o Full O&M descarregado (a regra de antes viraria "todas").
- **Onde o filtro mora (a lista de cada fonte, antes da coleta)**: `_cob_filtra` registra o inventário
  (`cobertura_inventario.json`), devolve só as incluídas e avisa a usina nova no sino (tipo `usina_nova`, uma vez por
  usina). API PV: `_pv_plantas_da_fonte` (pv, semp, alveslima, 2capi) e `_pv_monitorada` nos montadores que liam o
  `FULL_OM` (trackers, PR, ocorrências, backfill, curva); o `_pv_trk_plant` é podado na LEITURA (`_pv_trk_itens`: o drill,
  o App e o snapshot também o enchem); `INV_PADRAO_PLANTAS` e `QUALIDADE_PLANTAS`. 2C: plantas em `_2c_strings_dia_api` e
  `_2c_trk_*`, e `_2c_codigos()` (o código sai só quando TODAS as plantas dele saem: tirando só as plantas, os parados
  ligariam o errout). SunOp: o `/plants` em `ensure_sunop_meta` e o meta em `_sunop_meta_monitorada` (os laços perguntam ao
  meta, que também recebe usina pelo drill e pelo snapshot). Banco: depois da consulta, no snapshot, trackers, ETM e PR
  (chave como texto: int nas strings, str nos trackers). SolarEdge: em `fetch_all_solaredge` e `_se_pr_build`, nunca no
  `se_sites` (o drill o usa). scadaGridco: `_sg_build`. **Reserva da exibição**: o `add()` do `_portfolio_rollup`, antes da
  disputa "pior vence" e da soma das fatias. O drill por id não é filtrado (quem abre a usina tirada pelo endereço ainda a vê).
- **O que fica de fora de propósito**: o índice do App de Campo (`_campo_index`, o App é do campo); o `excluir_usinas` do
  `whats_ronda.json` (tira da ronda sem tirar do tempo real, como a Salto Pirapora); o Full O&M como escopo de contrato
  (Gerencial, Disponibilidade, relatório semanal).
- **Armadilhas**: a frota Thopen vem pela `pv` E pela `pg` (o rollup junta pelo nome): para tirar uma usina da Thopen de
  todas as telas, tirar nas duas. Os cards da Entrada guardam o pacote até a próxima montagem (até 30 min). A SunOp retém o
  último payload bom quando nenhuma linha tem dado (`_sunop_guarda_vazio`, até 30 min e sem prazo na pausa de domingo/teto).
  Na SolarEdge, Xavantina 2 e Colider 2 usam a irradiância da 1 (`SE_IRR_MIRROR`): tirar a 1 deixa a 2 sem PR. O livro de
  ocorrências do tracker_watch não fecha as abertas de quem saiu.
- **Estado (11/10/2026)**: foto de hoje gravada às 09:24 pelo servidor em 8 fontes — pv (115 incluídas, 31 fora: as sem
  Full O&M), pg 22, solaredge 7, semp 2, alveslima 1, 2capi 7, greenyellow 2, salenergia 5 (192 linhas no livro). Prova
  valor a valor, antes × depois da recoleta: as 10 tabelas de strings, o Painel NOC (115) e os cards da Entrada com as
  MESMAS usinas (0 diferença). A Athon entrou às 21:02, pela lista do catálogo da API da SunOp (Levi: "puxe pela API
  todas as plantas, aí está sua foto! São todas da Athon"): as 10 da tabela, todas incluídas (202 linhas no livro); servidor e
  PC com as 10 no tempo real e no Painel NOC. A Axis, sem token, segue na regra de antes. Armadilha achada no caminho: com a lista da SunOp em cache (e sempre na pausa) o `ensure_sunop_meta`
  voltava antes do filtro — corrigido (a lista fica inteira como inventário e o filtro vale também na volta antecipada).
- **Desligar**: `TEMPO_REAL_COBERTURA=0` numa máquina (nada é filtrado). Banco ilegível sem cópia em disco: nada é filtrado.
  Os testes rodam com o filtro desligado (`conftest._cobertura_desligada_por_padrao`). Testes: `tests/test_cobertura_tempo_real.py`.

## De-para de equipamentos (11/10/2026)

Levi: "quero que o de-para da equipamentos seja feito na plataforma de forma intuitiva" (e, na mesma noite, "RESOLVA"). O
de-para morava em lugares que ninguém via: a aba Equipamentos do BD_Performance (chave "Usina Supervisório", sincronizada do
Excel pelo coletor), constantes no código (`PV_NOME_POR_ID`, `PV_NOME_API_ALIAS`, `PV_ALIAS_CODIGO`, `PV_INV_NOMES`,
`scadagridco.FONTES`) e a ordem dos ids. No mesmo dia ele quebrou quatro vezes em silêncio (a API renomeou a Ipixuna e a
Morada Nova e as duas ficaram sem esperadas; a União com 6 de 12 inversores e o grupo 2 rotulado como 1).

- **A tela**: `/admin/de-para` (`templates/depara.html`), no Nexus como Base · De-para de equipamentos, só admin (API em
  `/api/admin/de-para`, `/usina`, `/decidir`, `/sugerir`). Desde 20/10/2026 a tela tem duas abas: **Por usina**, a 1ª (a
  tabela do Modo de-para, uma usina por linha: seção "Modo de-para" abaixo), e **Diagnóstico**, com o que segue aqui. O
  diagnóstico (`depara_diag.py`, puro): por fonte e
  usina, como liga ao cadastro (ponte pelo id, do código ou da tela, com o nome que a API escreve; apelido no código; pelo
  nome), as esperadas DO CADASTRO, inversores fonte × cadastro e de onde vem o nome de cada inversor. **Crítico** = SEM
  DE-PARA (a linha não tem esperadas E o nome dela não alcança usina nenhuma do cadastro — `_dp_chaves_da_linha`: apelido,
  chave exata ou nome de exibição; só nas contas da API PV, na Athon e na Axis, onde a ligação é esta — o scadaGridco liga pelo `_sg_cadastro`, e no servidor sem o token dele as 7 da GreenYellow e da Sal Energia viravam falsas; vem com a **sugestão pelo nome**, `depara.parecidas`) ou sem esperadas no cadastro
  (string morta não acusa; com a régua por inversor vigiando, atenção); **atenção** = inversores ≠ cadastro, ou nome pela
  ORDEM (= inversor sem de-para); **informação** = provisório (`PV_INV_PROVISORIOS`, some quando a tela decide a usina).
  Lê as tabelas de strings já montadas (nenhum pedido às fontes); fonte que a máquina não leu aparece "não lida". Caso que
  criou o "sem de-para" (12/10/2026): 5 usinas da Thopen "sem esperadas" eram outra coisa — a API escreve "Itaja 1 (228)"
  e "Pharma 2 (644)", o cadastro tem "Itaja 1 (551)" e "Pharma 2". A sugestão exige o MESMO número ("Itaja 1" nunca
  sugere "Itaja 2") e avisa quando o número entre parênteses é outro (228 × 551: conferir se é a mesma usina).
- **As esperadas são as do cadastro, não as da leitura**: o `str_esp` da linha da API PV já vem descontado (inversor sem
  visão, rampa, desligado, com OS) e a String Box à noite fica com 0 — a 1ª versão deu 20 falsos "sem esperadas". A linha
  da API PV leva `str_esp_cadastro` e `nome_api` (`_pv_cadastro_da_linha`, também na linha sem dados).
- **A lista abre em "Pendentes"** (crítico e atenção); "Todas" mostra as 176. Levi, 12/10/2026: "não deveria aparecer
  usina que já estão ligadas, a não ser que eu tirasse um filtro", "pode aumentar a tela, não precisa ser uma barra lateral
  toda espremida", "em NOVO ao invés de manter tem que alertar que está sem de-para".
- **O editor** ("Ligar" na usina sem de-para, "Editar" nas outras; uma janela grande no centro, usina à esquerda e
  inversores à direita): a **ponte da usina pelo id** nas contas da API PV (pv, semp, alveslima, 2capi) e o **apelido pelo
  nome** nas fontes que mandam o nome como chave (sunop e axis, "CPP100": `depara.FONTES_APELIDO`; antes era editar a
  "Usina Supervisório" no Excel e subir a planilha). A Thopen do banco NÃO: a chave dela é o id da usina no banco (8, 9,
  31…) e o nome da linha já é o de exibição — a 1ª versão a incluía e o editor chamava de "sem de-para" usina ligada. O
  editor acha a ligação pelo nome pelo MESMO caminho do diagnóstico (`_dp_pelo_nome`: chave, exibição, apelido do código). A lista do cadastro ESCONDE as usinas que outra fonte já liga
  (`_dp_cadastro_usinas`, campo `ligada_a`, sem contar a própria usina e sem as cópias dos apelidos, como "Sete Lagoa");
  "Mostrar também as já ligadas" as traz. A sugestão pelo nome vem pré-escolhida só quando não há o que conferir. E o
  **nome de cada inversor**
  onde o código liga pelo id (conta oem@: semp, alveslima, 2capi; scadaGridco: greenyellow, salenergia, apolo), com a origem de
  cada nome (tela, código, ordem do cadastro), "Confirmar como está" e a **sugestão pelo kWh do BD** (conta oem@: o Eday de
  cada id nos 3 últimos dias fechados × as colunas da aba da usina no BD_Performance, um para um, com o erro e a confiança;
  custa até 3 consultas da cota histórica da API PV; coluna vazia no BD não fecha nada e a tela diz). O inversor sem
  de-para (nome pela ordem, ou sem nome) aparece em âmbar com "Sem de-para: escolha o inversor do cadastro" no lugar de
  "manter". **Inversor a inversor na conta principal da API PV (12/10/2026**, Levi: "consigo ligar usinas mas não consigo
  ligar inversor a inversor, precisamos ter essa visualização"): `pv` entrou em `depara.FONTES_INVERSOR`, pelo id do
  inversor (que não muda quando a API renomeia). O editor (`_dp_editor_inv_pv`) lista os inversores que a API mandou hoje
  (o `day_inverter`; sem resposta, os do `plant_devices` com "inv" no nome), com o nome da API, o que vale hoje e a origem:
  "casa pelo nome" (o `_equip_lookup` acha no cadastro da usina), "sem de-para" (não acha: as esperadas dele não entram) ou
  "decidido na tela". Sem a usina no cadastro (a Itaja 1 (228) antes da ponte), pede para ligar a usina primeiro. A decisão
  vale nos DOIS lugares que dão nome ao inversor da conta principal: `_pv_dev_names` e `_pv_plant_devices`, na saída (o
  cache de 30 min guarda a resposta da API; o nome da API fica em `device_name_api`). "Confirmar como está" só manda os
  nomes que são do cadastro. O inversor das outras fontes que mandam o nome (Athon, Axis, banco, RenoGrid) e a usina da
  Thopen do banco e da RenoGrid (a chave é um id e a linha não traz o nome do cadastro) ainda se corrigem no cadastro.
- **O editor abre sem esperar a API PV (13/10/2026)**. Levi: "Gostaria de entender porquê demora tanto para carregar o
  de-para de uma usina [...] Não é aceitável essa demora toda". Não era o banco: cada abertura do editor de uma usina da
  API PV fazia, na hora, o POST `day_inverter` (o dia inteiro de leituras, fonte paga, até 10 s) só para saber QUAIS
  inversores mandaram dado hoje e, com o cache frio, o `plant_devices` (até 20 s). Medido no PC: 0,8 a 4,6 s por
  abertura, a 2ª igual à 1ª; as do scadaGridco, que não vão à API PV, 0,07 s. Agora a linha da tabela de strings
  (`build_summary`, o ciclo do worker de 5 em 5 min, que já faz esse day_inverter) leva `inv_ids_hoje`, e o
  `_dp_ids_hoje_api_pv` lê de lá (`_dp_ids_da_tabela`, tabela de até 30 min); fora dela, a API uma vez, com 4 s de espera
  (era 10: no servidor, logo depois do deploy e com a API PV em ReadTimeout, cada abertura levava 10,3 s), guardada 10 min
  quando responde e 2 min quando falha (`_DP_HOJE_MEMO`). O nome que a API dá a cada inversor vem do que já foi lido (`_dp_nomes_api`: o cache do
  plant_devices de qualquer idade, o do `_pv_dev_names`, a cópia das Falhas em disco), e a API só sem nenhum deles.
  Prova: `tests/test_depara_editor_rapido.py` (o editor com a API PV proibida).
- **Inversor sem de-para à vista no Tempo real (13/10/2026)**. Levi, com Sete Lagoas e Tupi Paulista abertas ("esp —" em
  todos os inversores e a linha com diferença 0): "é preciso eu saber isso sem eu precisar ficar abrindo a usina, e tem
  que abrir um atalho direto para o de-para". O caso: na conta oem@ (2C) o de-para em código chamava os inversores de
  "Inversor 1.x" e o cadastro tinha "INVERSOR01".. (24 e 20 esperadas); a linha fechava pelo total (236 e 400) e o
  diagnóstico dizia "ok", porque só conferia a QUANTIDADE de inversores. Agora a linha da API PV (`build_summary`) leva
  `inv_sem_esp` e os nomes (`_pv_inv_sem_esperadas`): o nome de cada inversor pelo MESMO caminho do drill (plant_devices,
  de-para da oem@ com a tela por cima, ordem do cadastro) e **sem rede** (a API PV é paga): o plant_devices só do cache,
  depois o `_pv_dev_names_cache`, depois a cópia em disco da rotina das Falhas (`falhas_pv_dev.json`, 7 dias); sem nenhum,
  não diz nada (campo ausente). **A cópia cobre a conta principal INTEIRA desde 22/10/2026** (`_falhas_pv_dev`), não só as
  usinas que já tiveram falha de string, e a que ainda não tem nome vai primeiro: as Pharmas 3 e 4 (sem visão de string)
  nunca entravam, chegavam ao Modo de-para como "INV-368373" e a tela mostrava os 6 do cadastro de novo como "sem leitura
  agora" (Levi: "duplicou a quantidade de inversores de pharmas 3 pharmas 4"). A tela não acrescenta linha do cadastro
  quando alguma linha da fonte não casa com a chave (`semLeituraDe`, regra geral desde 26/10/2026: ver "Os inversores sem
  leitura agora" no Modo de-para); a linha que veio só com o número diz "a plataforma ainda não tem o nome
deste inversor (a API PV mandou só o número; chega no próximo ciclo)" — o texto antigo, "sem o nome do inversor na fonte",
fazia parecer que a API PV não tinha o nome (Levi: "como assim sem nome na fonte?"). O diagnóstico acusa em **atenção** ("N de M inversor(es) sem esperadas: o nome que chega
  (...) não casa com o cadastro") e marca `sem_depara = "inversor"`. Na tela: a etiqueta âmbar "sem de-para · N inv." na
  linha da usina, a barra na usina aberta e o título da diferença dizendo que ela é a da usina inteira. O atalho
  (`/admin/de-para?editar=fonte|id`, que abre o editor já na usina) só aparece para quem abre a página dele (`/api/eu`:
  `abre_admin`, que é o passe com admin, a senha ou o Microsoft); para os outros, o aviso diz para pedir a um
  administrador. Prova: `tests/test_depara_inversor_sem_esperadas.py`.
  **O atalho abre uma janela por cima da tela (13/10/2026)**. Levi: "Essa forma taca um bloco minúsculo de ridículo na
  tela abaixo dos cards de KPI e lota de scroll [...] pode aparecer um visual sobrepondo a tela e dando um blur de fundo";
  "Esse scroll lateral não serve para nada!". O atalho era um link comum: dentro da Entrada, ele trocava o iframe do
  Monitoramento pela página do de-para, e o editor (janela fixa) ficava preso no iframe, com rolagem dentro de rolagem.
  Agora o clique chama `gcAbrirDepara`: o Monitoramento embutido pede à Entrada (`postMessage {gc:'depara'}`, mesma
  origem, só `/admin/de-para`) e ela abre `gcDeparaJanela`, um iframe de 1.280 px que cobre a tela inteira com o fundo
  desfocado; fora do embutido, a própria página abre. O de-para com `?janela=1` mostra só o editor; o Fechar e o Esc dele
  mandam `{gc:'depara-fechar'}` à tela de baixo, que fecha (o clique fora também). O href segue no link (botão do meio
  abre numa aba). Provado numa cópia de prova: a janela cobre 1600×950, o Fechar e o clique fora fecham. Prova:
  `tests/test_depara_janela.py`.
  **A mesma janela cria as OS do Tempo real (13/10/2026)**, Levi: "Em performance > tempo real > criar OS ao invés de
  direcionar para o OS Creator aparece a tela de criação de OS sobrepondo toda a tela dando um blur de fundo, assim que a
  pessoa finaliza a OS só aparece a notificação de criação!". O "Criar OS" das strings e o da ETM chamam `gcAbrirOs`
  (antes, `window.open` numa aba nova, ou uma lista de links quando eram várias OS): o embutido pede à Entrada
  (`{gc:'os', links}`), que abre `gcOsJanela`, uma FILA na mesma janela (uma OS por inversor, "Criar OS (2 de 3)") com
  `/os/performance/criar?...&janela=1`. A ponte do OS Creator no Nexus (`_JANELA_OS`) entrega a tela sem o topo e avisa
  `{gc:'os-criada', mensagem, detalhes}` quando o POST da criação deu certo: sai a notificação (`gcAviso`, no pé da tela,
  7 s) e abre a próxima; a última fecha. Fechar no meio avisa quantas foram criadas e quantas ficaram. Só links do OS
  Creator (`/os/...`) entram na fila. Na janela, o "×" fora do canto fecha (a tela do OS Creator não tem Fechar).
- **O dado**: livro `nexus_depara · fato_decisao_depara` (`depara.py`, no catálogo do Nexus), só acrescenta, gravado pela
  mesma `cobertura.Decisoes` (relê, grava inteiro, confere a contagem; cache de 60 s e a última leitura boa em
  `depara_decisoes.json`). O cadastro entra pela chave de negócio (Usina Supervisório, Equipamento Supervisório), que a
  rota confere antes de gravar; vazio = desfaz. Quem decidiu vai a `logs/depara.log`. O apelido usa a mesma linha:
  `usina_fonte` = o nome exatamente como a fonte escreve, `inversor_fonte` vazio (`linha_apelido`); o coletor as ignora
  (só lê semp/alveslima/2capi com ids numéricos).
- **Onde vale**: a decisão VENCE a constante (livro ilegível sem cópia = só o código, como antes). Ponte: `_pv_nome_do_cadastro`
  (no `get_plants`: vale na próxima leitura da lista, até 5 min). Inversor da conta oem@: `_pv_inv_nomes_de` (o
  `_pv_nome_2c` do drill, curvas, CSV e falhas; a qualidade; os ids do dia passado por inversor). scadaGridco:
  `scadagridco.SOBREPOR`, que o `nome_inversor` pergunta antes do mapa e da ordem. Apelido: `_aplica_alias_api_cadastro`
  (o MESMO caminho do `PV_NOME_API_ALIAS`: copia a entrada do cadastro para o nome da fonte, nunca sobrescreve), no fim do
  `load_equipamentos`; o `_dp_estado` relê o cadastro numa thread (`_dp_recarregar_cadastro`) quando a leitura do livro
  traz apelido novo ou desfeito — nesta máquina na hora (o `decidir` chama), na outra em até 60 s. **O coletor segue o mesmo livro**
  (`coletar_semp.com_a_tela`, ver o CLAUDE.md dele): na usina de coluna direta o nome do cadastro vira a coluna do BD pela
  aba Equipamentos; nome que não vira coluna fica de fora, com aviso.
- **Fica no código, de propósito**: os apelidos por nome (`PV_NOME_API_ALIAS`/`PV_ALIAS_CODIGO`: Sete Lagoa e União), que
  o resto do código usa com o nome da API — trocar por ponte mudaria o nome interno dessas usinas. A tela os mostra.
- `DEPARA_TELA=0` desliga numa máquina; os testes rodam desligados (`conftest._depara_desligado_por_padrao`). Testes:
  `tests/test_depara_equipamentos.py`.

## Estrutura do Nexus no lugar da aba Equipamentos (13/10/2026)

Levi, com a tela Base > Equipamentos das usinas pronta no Nexus: "pode fazer todas as fases! vamos pra cima!". O Nexus
publica a visão `nexus_estrutura_usina · aba_equipamentos` (o formato da aba Equipamentos, com os IDs do Nexus no fim) das
chaves que o Levi marcou "no lugar da aba". Aqui (`estrutura_nexus.py`), **toda leitura da aba** passa por
`_equipamentos_df()`: a aba do BD_Performance com as linhas de UFV, UG e inversor dessas chaves trocadas pelas da visão
(chave efetiva = "Usina Supervisório" ou, sem ela, "Usina", o `us` do `load_equipamentos`). São quatro leitores: o
`load_equipamentos` (ESPERADO, ESPERADO_INV, EQUIP_NAMES, USINA_DISPLAY, FULL_OM, STRING_BOX, POWER_* e, desde 20/10/2026,
FRAC_COD_INV, FRAC_COD_INV_DISP, FRAC_COD_CAB e EQUIP_PARENTE), o `_frac_fractall_map`, o `_disp_equip_linhas` e o
cadastro das Falhas (`falhas_job.cadastro_da_aba`, desde 20/10/2026). Até 20/10 este parágrafo dizia "nenhum outro lê a
aba", e estava errado: o `falhas_job.montar` fazia o próprio `pd.read_excel` e as strings e o kWp do Nexus não chegavam
ao kWp da string das Falhas. Agora o `pd.read_excel(... "Equipamentos")` mora só em `_aba_equipamentos_df` (o
`tests/test_modo_depara_backend.py` prende a montagem das Falhas no `_equipamentos_df`).
- Leitura: o mesmo `cobertura.Decisoes` do de-para (cópia de 60 s, a última boa em `estrutura_nexus.json` do cache),
  criado no 1º uso (o `load_equipamentos` roda no import, antes do `cobertura`). Livro que não existe, vazio ou
  ilegível sem cópia = a aba inteira, como antes.
- Recarga: o `maybe_reload_equipamentos` (o vigia do web a cada 60 s e o ciclo do worker) relê o cadastro quando a
  impressão da visão (`estrutura_nexus.marca`) muda, mesmo com o BD parado; a carga zera a cópia de 12 h do mapa do
  "Usina Fractall" e da disponibilidade. O log da carga diz "Nexus: N chave(s) no lugar da aba (M linhas da aba trocadas)".
- `GET /api/estrutura-nexus` (com login): ligado, as chaves (inversores e strings de cada uma), as linhas trocadas, quando
  o cadastro carregou e se a visão mudou desde então.
- **A grafia da chave é a da aba** (`estrutura_nexus.herda_grafia`, 20/10/2026): a troca compara as chaves pelo `texto()`
  (espaços juntados), e a linha da visão HERDA a "Usina Supervisório" e a "Usina" como a aba as escreve quando o texto bate.
  O caso: a aba e a API PV escrevem "Assis Chateaubriand  Skid 1 (79)" (espaço duplo) e o Nexus grava com o `texto()`;
  marcada no lugar da aba, a visão entrava com a grafia do Nexus, o `load_equipamentos` guardava a chave de espaço único e
  o `build_summary` (que procura pela grafia exata da API) deixava a usina sem esperadas, kWp, nome de exibição e Full O&M,
  sem aviso nenhum. Chave que a aba não tem fica como o Nexus escreve. Prova: `tests/test_estrutura_nexus.py`
  (`test_a_chave_com_espaco_duplo_herda_a_grafia_da_aba`, pela chave da API tudo segue preenchido depois de marcada).
- **O "Usina Fractall" também herda a grafia da aba** (`grafias_fracttal`, 2ª revisão final de 21/10/2026), pela MESMA
  chave e quando o `texto()` bate (só os espaços): o `_frac_usina_ent` (e o `_frac_depara_falha`) procura a usina no índice
  de code-base pela description EXATA do Fracttal, e a Belo Jardim ("Thopen - Belo Jardim  1 - PE", espaço duplo na aba,
  no Fracttal e nas Ligações) marcada com o nome de espaços juntados ia de {cb: BJD100, site: 46256021} para None: sem o
  badge de OS abertas, sem as OS no Diagnóstico e no drill, a cascata de queda (h_rede/h_equip) em 0 e sem a estação pelo
  code-base. O Nexus passou a escrever o nome como as Ligações o têm, e o acento diferente ele mesmo acusa (a chave não
  marca). Outras três da aba têm espaço irregular no nome do Fracttal (Matões 2, Timon 1 e 2). Prova:
  `tests/test_estrutura_nexus.py::test_belo_jardim_o_nome_do_fracttal_herda_a_grafia_da_aba_e_segue_no_fracttal`.
- `ESTRUTURA_NEXUS=0` desliga numa máquina; os testes rodam desligados (o conftest põe `ESTRUTURA_NEXUS=0`) e o
  `tests/test_estrutura_nexus.py` liga e dubla a visão. O gêmeo faz o mesmo em `gemeo/gemeo/ingest/cadastro.py`
  (`sobrepor_nexus`, com a mesma herança da grafia, a da chave e a do "Usina Fractall"; a versão do cadastro leva o
  `updated_at` do livro), o coletor no
  `load_name_mapping` (desligado por padrão, ver o CLAUDE.md dele; **a herança da grafia NÃO está lá**: o repositório do
  coletor tem trabalho de outra sessão sem commit, e quem ligar o `load_name_mapping` tem de pôr a mesma regra antes) e o
  Nexus nas Ligações. A regra é a mesma nos quatro.
- **Prova (13/10/2026):** a Altair (6 chaves, 46 linhas na visão) montada no Nexus pelo "Trazer da aba", com a aba real:
  os 13 mapas do cadastro iguais com e sem a visão (só a UFV difere em 5e-12 kWp, fórmula da aba × potência real do
  Registro mestre). No teste, a usina igual à aba não muda nenhum mapa e a esperada acompanha o Nexus quando muda.

## Modo de-para (20/10/2026)

Levi, com o protótipo aprovado: "Boa, é isso mesmo. Implementa no tempo real e adapta na base o de-para para ficar nesse
padrão de tabela e apresentar uma usina por linha". No Tempo real (fontes da API PV, só admin) e na Base · De-para de
equipamentos, a tela liga cada inversor da fonte ao ativo do Fracttal, à cabine (sempre a CABN: "foque em cabine") e à
usina do Registro mestre, com as strings corretas e o kWp pela regra do Levi. **Quem grava é o Nexus** (a estrutura das
usinas, `/t/base/equipamentos/depara/salvar`, que também marca a chave "no lugar da aba"); a ponte da fonte segue no
`POST /api/admin/de-para/decidir` daqui. Esta seção tem o lado de **backend** da plataforma (o que ela lê para a tela e os
leitores do cadastro que passam a seguir o que o Nexus grava) e, no fim, **as telas** (o componente, o Tempo real e a Base).

- **Leitores (fase 0, sem mudar número com a visão vazia)**:
  - as Falhas leem o cadastro pelo `_equipamentos_df` (`falhas_job.cadastro_da_aba`). Prova (20/10, aba real do espelho e
    da cópia de 11:41): CAD_INV 2.183, CAD_UFV 146, CLIENTE_DE 146 e CAD_INV_DISP 2.183 iguais valor a valor, lidos direto
    e pelo caminho novo; o teste refaz a prova com a aba que o `import app` leu;
  - a visão do Nexus ganhou **"Código Fracttal"** no fim (`estrutura_nexus.CAB`; na linha do inversor e na da UG). O
    `load_equipamentos` monta `FRAC_COD_INV {chave: {nrm(equip_sup) e nrm(Equipamento): código}}`, `FRAC_COD_INV_DISP
    {nrm(Usina): {nrm(Equipamento): código}}` (os chamadores do `_frac_inv_code` passam o nome de exibição), `FRAC_COD_CAB
    {chave: {N da UG: código da CABN}}` e `EQUIP_PARENTE {chave: {equip_sup: "UG 02"}}`; a aba não tem a coluna, então
    sem o Nexus os três FRAC_COD ficam vazios. Os quatro passam pelo `_aplica_alias_api_cadastro` como os outros mapas;
  - `_frac_inv_code`: o código **gravado** primeiro (`_frac_cod_gravado`), o derivado do nome depois. O caso: na Pharma
    II o derivado dá THPN-PHS200-INVR1.1 (a "Usina Fractall" da aba é a árvore de antes de 22/09) e o Fracttal de hoje
    tem THPN-PHS100-INVR2.1.
- **Rotas novas (só leitura, só admin: moram debaixo de `/api/admin`)**, a regra pura em `depara_fracttal.py`:
  - `GET /api/admin/de-para/fracttal/usinas` → `{usinas: [{codigo, nome, cliente, usina_id, cabines: [{codigo, nome}],
    fonte}], fonte: "foto", lido_em, foto_em, carregando}`;
  - `GET /api/admin/de-para/fracttal/arvore?codigo=` (aceita o código-base: ITA100 acha THOPEN-ITA100; ambíguo, como o
    IPX100 da 2C e da Thopen, não acha) → `{codigo, nome, cliente, usina_id, cabines: [{codigo, nome, inversores:
    [{codigo, nome, descricao, cabine_por}]}], sem_cabine, fonte: "foto"|"fracttal", lido_em, foto_em, fora_da_foto,
    pendente, aviso?}`;
  - `GET /api/admin/de-para/registro` → `{usinas: [{usina_id, codigo, nome, status, kwp, kwp_de, cliente}], lido_em}`.
  - Sem leitura nenhuma do banco ainda nesta máquina: 503 com `carregando`.
  - `GET /api/admin/de-para/cadastro` (20/10, da memória, nada à rede) → `{chaves: [{chave, exibicao, inversores: [{esup,
    nome, esp, kwp, ug}]}], carregado_em}`: as chaves do cadastro DESTA plataforma (o ESPERADO: a aba com as chaves do
    Nexus por cima), sem os apelidos do nome da API ("Sete Lagoa"). A tela usa para quatro coisas: oferecer a chave da aba
    que o Nexus ainda não tem (a "Coração 2 (112)"), mostrar o inversor da chave que não leu agora, mandar ao Nexus o nome
    do cadastro de cada inversor (e conhecer o que ele vai semear da aba para a conta do kWp) e saber que a chave escolhida
    não está na aba nem no Nexus (pendência: o Nexus a recusa).
  - **`POST /api/admin/de-para/decidir`** (a ponte, que já existia) aceita a chave na grafia do Nexus e grava a do cadastro
    (pelo `texto()`, quando é uma só: "Assis Chateaubriand Skid 1 (79)" → "Assis Chateaubriand  Skid 1 (79)", a que a fonte
    procura) e, com a chave fora do ESPERADO, relê a visão do Nexus AGORA (`_en_leitor().linhas(forcar=True)` +
    `maybe_reload_equipamentos`) antes de recusar (`_dp_alvo_no_cadastro`): a ponte vem segundos depois do salvar do Nexus,
    e a chave que só existe lá dava 400 "não está no cadastro" sempre, até o vigia de 60 s.
  - **`/api/eu`** ganhou `grava_admin` = abre a administração e não é gestor (o perfil do passe). O gestor que é admin do
    Nexus abre (lê) e não grava: no Modo de-para o Nexus gravava a estrutura e a ponte levava 403, gravação pela metade.
- **De onde vem**: a árvore é a dimensão de equipamento do Nexus (`nexus_equipamentos · dim_equipamento`, a FOTO dos
  ativos de 22/09; cópia de 3 h, a última boa em `depara_dim_equipamento.json` do cache); o Registro é o `cadastro_nexus ·
  usinas` (10 min, `depara_registro_usinas.json`), só as colunas que não são sensíveis, e o cliente pelo `clientes`. A
  leitura do banco vai numa thread (`LivroEmFundo`, sobre os `vencida`/`sem_rede` do `cobertura.Decisoes`): com cópia, o
  pedido sai na hora; sem nenhuma, espera a 1ª leitura até 20 s; banco fora e sem cópia, não prende os seguintes por 60 s.
  A indexação da foto (22,5 mil membros, ~0,15 s) é uma vez por leitura.
- **A árvore**: o inversor cai na CABN **subindo pelo `pai_id`** (Itajá: INVR1.1 → QGBT1 → SKID1 → CABN1; na Altair os 40
  inversores caem na CABN1, a cabine é uma só); sem pai até uma cabine, pelo número do código (INVR2.x → a CABN2 da usina,
  se houver uma; `cabine_por: "codigo"`); sem os dois, `sem_cabine` (a Qair Cascavel, INVR → PECN → USINA: 187). O nome
  sai **do código** ("Inversor 2.1", "Cabine 2"), nunca da descrição: 2.380 das 2.477 descrições trazem marca e modelo, e o
  número tirado delas acertaria 39 de 1.743 (o "1" do "H1"). Medido na foto de 20/10: 2.477 inversores, 2.217 pelo pai, 39
  pelo código, 221 sem cabine; 147 usinas (144 da foto + THPN-PHS100, APOL-GVT200 e APOL-RDP100, que só existem pelos
  códigos que o PCM gravou).
- **Fora da foto** (a raiz não está na foto, ou alguma cabine/inversor entrou só pelo código: a Pharmas refeita como
  THPN-PHS100 com CABN2/3/4, a Apolo, a Faro): a rota devolve a árvore da foto **já**, com `pendente: true`, e a
  `BuscaFracttal` lê no próprio Fracttal em fundo (`items/{código}` e `items/?location_code=` de pai em pai, só pelos
  locais; 1 pedido por segundo, uma usina de cada vez, numa thread; a cota de 200/min é da empresa) e guarda 7 dias em
  `depara_fracttal_arvores.json`. O próximo pedido sai com `fonte: "fracttal"`, e a lista de usinas passa a levar a lida
  por cima da foto. Filtro que o Fracttal ignora (devolve o catálogo inteiro, 23 mil) falha alto; árvore de mais de 150
  pedidos também. Sem `FRACTTAL_CLIENT_ID` nesta máquina, nada vai ao Fracttal e a resposta leva o `aviso`.
- **kWp do Registro** (decisão 3 do Levi, alterada em 20/10: "onde não tem potência real, vai usar potência contratual"):
  `potencia_real` × 1.000 (`kwp_de: "real"`); vazia, zero ou ilegível (o "0,,643" da Rodrigues II) → `potencia_contratual`
  × 1.000 (`"contratual"`); sem as duas, `kwp` vazio. No banco de 20/10: 190 real, 68 contratual, 0 sem as duas.
- **`inv_resumo` nas linhas das contas da API PV** (`/api/data`, `/api/semp/data`, `/api/alveslima/data`,
  `/api/2capi/data`): `[{id, nome_api, nome, ativas, total, esp, sem_visao, esup?}]`, montado no `build_summary` com o que o ciclo
  já leu (`_pv_inv_resumo`; o nome pelo mesmo caminho sem rede do `_pv_inv_sem_esperadas`, agora `_pv_nomes_sem_rede`):
  é o que dá ao modo uma linha por inversor de TODAS as usinas da fonte sem abrir o drill de cada uma (pago na hora).
  `ativas` = None no inversor sem visão ou em rampa, 0 no desligado por potência (como o drill); `esp` = as esperadas do
  CADASTRO, sem os descontos da leitura. Tamanho estimado sobre o snapshot de 20/10 (as 120 linhas da `pv` com um resumo
  por inversor, nomes da cópia das Falhas): `/api/data` 83 → 191 KB; com o gzip, que é o que trafega, 7,5 → 14,7 KB.
  **`esup` (26/10/2026), só na conta oem@** (semp, alveslima, 2capi): o Equipamento Supervisório do cadastro, na grafia
  dele, pelo de-para POR ID da plataforma (`_pv_inv_esup_por_id` sobre o `_pv_inv_nomes_de`: o PV_INV_NOMES com as
  decisões da tela De-para por cima), só quando casa com o cadastro da chave; com ele, `nome` e `esp` são os desse
  inversor do cadastro, e o `nome_api` segue o da fonte. Caso: a União (18772125) passou a vir com o nome da fonte
  ("UG1 INVERSOR01".., que vence o de-para por id no `_pv_nomes_sem_rede` porque o nome guardado vem antes), e nenhum
  casava com o "UNI_Inv_1.1".. da chave "UNI" (dado do servidor em 26/10: `inv_sem_esp` 12, `esp` vazio nos 12).
- **Drill da API PV** (`/api/plant/<id>` e o da 2C pela `owen`): por inversor, `nome_fracttal` ("Inversor N.M" do código
  gravado) e `cabine` ("Cabine N"), só quando houver (`_dp_rotulos_fracttal`). O `nome` NÃO muda (decisão 5 do Levi): é a
  chave dos tickets, do padrão de 30 dias, das OS e a coluna do BD. A `cabine` só sai quando a UG do inversor ("Equipamento
  Parente") tem a CABN GRAVADA (`FRAC_COD_CAB`, procurado na chave e no nome de exibição da usina, porque a UG mora na chave
  da UFV): até a revisão de 20/10 ela vinha do "Equipamento Parente" da aba para a frota inteira, sem ninguém usar o modo,
  e onde a UG da aba é o SKID (294 inversores, a Altair entre eles: UG 01 a 05 debaixo de uma CABN1 só) o drill de todo
  mundo passava a dizer "Cabine 3" para um SKID. Sem a CABN gravada, o drill fica como era (a cabine do nome).
- **Quem alcança** (`leitura_nexus.py`): a chave da ponte não alcança nada disto (fora de `permitido`;
  `ADMIN_DAS_PAGINAS` diz ao teste das páginas que é de propósito) e o `decidir` está nas `GRAVACOES`; o gestor admin do
  Nexus lê pelo `_GET_GESTOR` ("/api/admin/de-para") e não grava. Nenhuma das rotas chama a API PV nem a SunOp.
- **Coletor e gêmeo**: o gêmeo lê a visão por nome de coluna e não usa o código (`gemeo/tests/test_ingest_cadastro.py`
  prova que a coluna a mais não muda o cadastro) e herda a grafia da aba na chave, como aqui. O coletor (`load_name_mapping`,
  desligado por padrão) converte a visão para o cabeçalho da aba e descarta a coluna nova; NÃO foi editado (há trabalho de
  outra sessão sem commit naquele repositório) e faltam lá duas coisas antes de ligar o `load_name_mapping`: registrar no
  CLAUDE.md dele a coluna "Código Fracttal" e pôr a herança da grafia da chave (a Assis Skid 1 de espaço duplo).
- Testes: `tests/test_modo_depara_backend.py` (as Falhas pelo `_equipamentos_df` com a aba real, o código gravado vence o
  derivado, a árvore da Itajá pela foto e da Pharmas pelo código e pelo Fracttal dublado, o Registro, o leitor em fundo, o
  `inv_resumo` sem API PV, o drill e a cabine só com a CABN gravada, o `grava_admin` do gestor, a ponte que relê a visão e
  aceita a grafia do Nexus, a rota do cadastro); `tests/test_estrutura_nexus.py` (os quatro mapas novos entram na prova
  "igual à aba"; a Assis Skid 1 de espaço duplo segue com o cadastro inteiro pela chave da API depois de marcada);
  `tests/test_leitura_nexus.py` (a ponte não alcança, o gestor lê).
- **`chave_cadastro` na linha das contas da API PV** (`_pv_chave_da_linha`, no `build_summary`): a chave do cadastro a que
  a linha liga HOJE (o nome por dentro depois da ponte; nos apelidos do código, a chave de verdade: "Sete Lagoa" → "Sete
  Lagoas", "União" → "UNI"). Sem ligação (a Itaja 1 (228)), a linha não leva o campo. É com ela que a tela pede ao Nexus o
  estado e decide se precisa gravar a ponte.

### As telas (20/10/2026)

- **O componente** `static/depara_tabela.js` (`window.DeparaTabela`): a tabela do protótipo aprovado, a MESMA nas duas telas
  (uma linha por inversor agrupada pela usina da fonte; Inversor · Com corrente agora · Strings corretas · Usina no
  Registro mestre · kWp do inversor · Usina no Fracttal · Cabine · Inversor no Fracttal · Situação; tracejado = sugestão,
  cheio = conferido; Conferido e desfazer por linha, "conferir todos os sugeridos", a barra fixa no rodapé com Salvar). A
  regra pura (sugestões, conta do kWp) fica em `DeparaTabela.regras` e os testes a rodam no node. Lê: as linhas da tabela
  da fonte (`inv_resumo` + `chave_cadastro`, nada novo à API PV), `/api/admin/de-para/fracttal/usinas|arvore|registro|cadastro`,
  a "Usina Fractall" da aba (`/api/os-creator/fractall-usinas`), o `/api/eu` e o estado do Nexus.
- **Quem grava** (revisão de 20/10): o `grava_admin` do `/api/eu`. Sem ele (o gestor que é admin do Nexus), a tabela abre só
  de leitura, com o motivo nas fontes e na barra, e o Salvar não sai; no Tempo real o botão nem aparece (`_dpPode` pede
  `RD.gravaAdmin`): o gestor confere na Base.
- **A chave é comparada pela forma normalizada** (`nk` = o `texto()` do Nexus, espaços juntados): a "Assis Chateaubriand
  Skid 1 (79)" da aba (espaço duplo) e a do Nexus (único) são UMA chave na lista, na conta e no "já está no Nexus". Pela
  igualdade exata a tela somava os inversores do Nexus e os da tela como membros diferentes (no ensaio da Itajá, 216,3 kWp no
  lugar de 324,5) e pulava a ponte. Ao Nexus vai a grafia DELE (`chaveParaNexus`); à ponte, a do cadastro da plataforma.
- **As opções de chave** são a de hoje, as do Nexus para a usina do Registro e as do cadastro da plataforma (a rota
  `/cadastro`) com o mesmo nome-base e o mesmo número da planta ("Coração 2" → "Coração 2 (112)", marcada "da aba
  Equipamentos"). A sugestão automática segue a de antes (a de hoje, ou a do Nexus com o mesmo número). **A "Nova chave"
  (o nome que a fonte manda, fora da aba) saiu** (2ª revisão final, 21/10/2026): ela nunca vale no lugar da aba (os leitores
  não a conhecem), o Nexus a gravava como a chave da usina e prendia nela os códigos do Fracttal (na Pharma 3 (851),
  escolhida a "Pharma 3 (851)" e depois a "Pharma 3" da aba, as 6 linhas ficavam "já está no Inversor 1.m (Pharma 3 (851))
  no Nexus" para sempre), e o Nexus agora a recusa. A planta sem opção nenhuma (Itaja 1 e 2 (228/229), Pharma 3 e 4
  (851/852) de hoje, quando o cadastro não tem a chave do número) fica em "falta a chave do cadastro: esta planta não tem
  chave na aba Equipamentos nem no Nexus (ligue a chave na Base > Equipamentos das usinas)"; a chave escolhida que não está
  na aba nem no Nexus é pendência com o porquê.
- **Os inversores sem leitura agora**: o `inv_resumo` só traz quem leu no ciclo; o inversor da chave escolhida que está no
  cadastro (ou no Nexus) e não leu vira uma linha "sem leitura agora", com as strings do cadastro, editáveis. Começa "de
  fora" (o Nexus não mexe nele) quando a sugestão não fecha — na Sapopema, os 2 parados sem strings; com tudo sugerido (o
  INVERSOR04 parado da Coração 2 → COR100-INVR2.4, 20 strings), vai como os outros, a conferir. "incluir" põe de volta.
  Troca de chave refaz essas linhas. Na `pv` de 20/10 (a bancada): 3 linhas, as da Ouro Branco 4 (773), cadastro com 7 e a
  API lendo 4. A linha de fora que o Nexus já tem segue na conta dele e mostra o kWp que ELE vai gravar (os 3 parados da Ouro
  Branco 4, com 17 strings no Nexus, vão de 145,2 a 133,7 junto com os outros), não "o de hoje".
  **Só entram quando TODAS as linhas da fonte casaram** com algum inversor da chave (`casamentoDe`: o cadastro pelo
  `cadDoInv`, o Nexus pelo `invNexus` ou o nome do cadastro da chave de hoje): aí os que sobram são de fato os que não
  leram. Com uma linha sem casar, nenhuma entra (não se sabe qual do cadastro ela é). Os dois casos, com print do Levi: a
  Pharma 3 (851) de 22/10 (a fonte só com o número, "INV-368373": 12 linhas para 6) e a "União 1 e 2" de 26/10 (a fonte com
  nome, "UG1 INVERSOR01", e a chave "UNI" com "UNI_Inv_1.1": 24 linhas para 12, o kWp dividido por 413 strings, 194,4 por
  inversor, e tudo "inversor repetido"). O conserto de 22/10 só cobria o "INV-<id>".
- **A linha solta** (`linhaSolta`, 26/10/2026): a linha da fonte que não casa com a chave **enquanto a chave ainda tem
  inversor sem linha** pode ser o mesmo equipamento com outro nome. Ela é pendência vermelha "o nome da fonte (“X”) não casa
  com o cadastro da chave “Y”: ligue os inversores no editor da ponte", não salva, fica fora da conta do kWp (a semente da
  aba já conta o inversor do cadastro; contada também, a União dividia por 413) e fora do "repetido". Com todos os da chave
  já casados, a linha que sobra é inversor a mais de verdade e vai como novo. Motivo: o salvar do Nexus acha o inversor
  pelo supervisório e, sem ele, pelo NOME; o pedido de 26/10 da União (supervisório "UG1 INVERSOR01", `nome` vazio) achava
  nenhum e ia criar um com o "Inversor N.M" do código, recusado (409) só por coincidir com o nome de um semeado da aba: com
  um código de outro número, nasceria um 2º inversor para o mesmo equipamento.
- **O inversor do cadastro para a linha da fonte** (`cadDoInv`, e o `invNexus` pelo mesmo nome): pelo `esup` do de-para por
  id (a conta oem@, ver `inv_resumo`) e depois pelo nome da fonte; em cada um, pelo Equipamento Supervisório e, sem ele, pelo
  nome do cadastro igual. A Pharma II manda "Inversor 1.1" e a aba e o Nexus têm a "Pharma 2" com INVERSOR01 =
  "Inversor 1.1": só pelo supervisório, a tela contava os 6 duas vezes no kWp (12 membros) e punha os 6 de novo como "sem
  leitura agora". Com o `esup`, a União liga os 12 ao cadastro (401322 = UNI_Inv_1.1, 401313 = UNI_Inv_2.1) e o pedido ao
  Nexus leva o supervisório e o nome do CADASTRO (o Nexus acha o que semeou da aba; nenhum inversor novo).
- **As strings corretas sugeridas**: do Nexus, senão do cadastro da chave, senão da LEITURA de agora. A da leitura é
  pendência "confira as strings: vieram da leitura de agora" até o Conferido DA LINHA (o "conferir todos" não as confere;
  digitar também resolve): 155 inversores da aba não têm Strings Ativas, e uma string parada na hora viraria "não esperada"
  para sempre e entraria na divisão do kWp. A troca de chave passa a sugestão da leitura às strings do cadastro da nova.
- **O nome do inversor no pedido** (`nome`): o do cadastro da chave escolhida para o Equipamento Supervisório (vazio quando
  não há). O inversor que o Nexus cria nasce com o "Equipamento" da aba, a coluna do BD (decisão 5), e não com o
  "Inversor N.M" do código: na Coração 2 a aba diz "Inversor 1.1" e o Fracttal INVR2.1. O inversor do Nexus é achado pela
  chave e pelo Equipamento Supervisório, e sem ele pelo nome do cadastro dentro da usina (o mesmo do salvar do Nexus).
- **O Nexus na mesma origem**: a tela roda dentro da moldura do Nexus (porta única), e o Nexus é a página de CIMA; o prefixo
  dele é o que vem antes do `/t/` no caminho dela (`/nexus/t/performance/tempo-real` → `/nexus`; na raiz, vazio), e o pedido
  leva o cookie `nexus_sessao` (caminho `/nexus`). Estado: `GET <prefixo>/t/base/equipamentos/depara/estado?chaves=A|B&usinas=93`
  (até 50 de cada por pedido). **Fora da moldura não há Nexus**: a tela mostra e sugere, e o Salvar fica desligado dizendo
  "abra pelo Nexus". Na bancada, `window.GC_NEXUS_BASE` força o prefixo.
- **As sugestões** (contrato e `levantamento/cobertura.md`): usina do Fracttal pela "Usina Fractall" da aba, pelo código no
  nome, pelo nome-base com o número e pelas irmãs do mesmo código-base; vence a que casa mais ativos DIFERENTES pelo CÓDIGO
  N.M (o N.M do nome, ou o número da planta com o do inversor; diferentes desde 26/10/2026: a "União 1 e 2" tem o 2 no nome,
  e pelo número da planta os 12 caíam nos 6 INVR2.m, empatando com os 12 do N.M), e no empate a árvore mais nova — a Pharma II casa os 6 na
  THPN-PHS100 de hoje e também na PHS200 da foto, que não existe mais no Fracttal. Planta com rótulo de subusina
  ("Ceilandia 1.2 (90)", "Junco 2.1 (134)"): o número é o N do rótulo e o nome do cadastro vence o empate (lido como planta 2,
  a Ceilandia 1.2 ia para os INVR2.x: 33 erros). Registro: a usina da chave no Nexus, a do Fracttal, o código cheio, o fim do
  código (só se de UMA usina: o IPX100) e a irmã com o número da planta. Chave: a de hoje; senão a da usina do Registro com o
  mesmo número da planta ("Itaja 1 (228)" → "Itaja 1 (551)"); "Nova chave" (o nome da fonte) só por escolha. **Medido em
  20/10** sobre as cópias do banco e as 120 linhas da `pv` do levantamento: **839 de 841** inversores com o ativo que a
  plataforma já liga hoje (a sugestão do protótipo acertava 481); entrar no modo, ~100 ms de conta no node.
- **O kWp mostrado é o que o Nexus vai gravar**, com a conta DELE (`contaKwp`, a mesma regra do salvar do Nexus):
  - o kWp da usina é o do estado do Nexus (`kwp`/`kwp_de` do GET, o Registro com que ele calcula); a cópia do Registro da
    plataforma (`/registro`, 10 min) só vale sem o Nexus e no rótulo da lista. As duas diferentes: a faixa diz "a cópia desta
    tela diz X; o Nexus grava com Y: vale o do Nexus" (no ensaio da Itajá com 2.700 no Nexus e 2.596 na cópia, a tela
    mostrava 324,5 "igual ao de hoje" e o Nexus gravava 337,5);
  - a usina INTEIRA do Registro no Nexus (todas as chaves dela), com as usinas que vão no Salvar por cima e a própria linha;
    a chave que o Nexus ainda não tem entra como ele a vai semear da aba antes do remendo (todos os inversores do cadastro
    dela, com as strings e o kWp da aba): a Coração 2 (112) dá 3.250 ÷ 80 × 20 = 812,5, com "250,0 → 812,5" na linha (o
    Registro de 3.250 é só o da Coração 1, e a regra vale assim: decisão do Levi, "aplica direto");
  - o inversor vivo sem strings corretas fica com o kWp de antes, e ele sai do Registro ANTES de dividir pelos que têm
    strings (a soma da usina continua o Registro: na Sapopema, 3.196 − 2 × 159,8 ÷ 288 strings = 159,8 nos 18; antes, 3.515,6,
    +10%); se os de antes já somam o Registro, a usina fica com a pendência e o Nexus a recusaria;
  - sem potência no Registro (nem real nem contratual), ninguém muda: "fica o de antes" (0 ou vazio NUNCA por cima de dado);
  - **a chave irmã** (2ª revisão final, 21/10/2026): outra planta da tela na MESMA usina do Registro, com uma chave da aba
    que o Nexus ainda não tem, vai no mesmo Salvar ou nenhuma das duas vai (pendência "a chave X (de Y) também é desta usina
    do Registro e ainda não está no Nexus: confira e salve as duas juntas", `irmaFora`, calculada com o que vai no Salvar).
    A Coração 2 salva sozinha dividia os 3.250 do Registro só pelas 80 strings dela (812,5 por inversor) e, com a Coração 1
    (111) seguindo pela aba, a usina somaria 6.500 nos leitores; juntas, 3.250 ÷ 320 × 20 = 203,125. Conta também a irmã
    SEM chave escolhida que tem, entre as opções, uma chave da aba fora do Nexus (revisão do acerto final, 21/10/2026: no
    dado real as duas Coração chegam sem chave, e escolhida só a "Coração 2 (112)" ela ia sozinha; pendência "Coração 1
    também é desta usina do Registro e a chave dela ainda não está no Nexus: escolha a chave de Coração 1..."). O Nexus
    recusa o mesmo caso pelas Ligações (quando a Usina Fractall da irmã está nelas; a da Coração 1 (111) não está);
  - **duas CABN de mesmo número na mesma usina do Registro** (a Ipixuna do Pará, usina 56: a Santa Cecilia 1 na
    IPX100-CABN1 e a 2 na 2C-IPX100-CABN1) caíam na mesma "UG 01" sem pendência, e o Nexus recusava a usina a cada Salvar.
    Agora é pendência nas plantas dela (também quando a UG de mesmo número já tem outro código no Nexus), com o porquê.
    Como nomear a 2ª CABN1 é regra nova, a levar ao Levi; até lá, "deixar de fora" as linhas de uma das plantas;
  - a cabine da faixa é a do Nexus que a CABN vai ocupar (a que tem o código, senão a "UG NN" de mesmo número), com os
    inversores do Nexus que já estão nela. "hoje → novo" quando muda. Sem o Nexus, só a tela (e a faixa diz isso).
- **Salvar**: só as usinas MEXIDAS (mudou algo ou conferiu) e sem pendência; as mexidas com pendência ficam de fora e a barra
  diz quantas. O "já está no X no Nexus" só se isenta quando o X vai no MESMO Salvar (a conta repete até parar de mudar):
  isento por estar em qualquer usina da tela, o código que o Nexus ainda tinha numa usina com pendência passava e o Nexus
  recusava o lote inteiro com 409. Primeiro o Nexus (`POST <prefixo>/t/base/equipamentos/depara/salvar`, lotes de até 50
  chaves, nunca partindo uma usina: o selo é da usina, e o 2º pedido dela daria 409; e as usinas que trocam códigos do
  Fracttal entre si no MESMO pedido, porque o Nexus confere "um código num inversor vivo só" por pedido: a THPN-PHS100 é um
  site só para as Pharmas 2, 3 e 4, e a troca dos blocos entre a 2 e a 3 em dois pedidos era recusada nos dois, sempre. A
  usina lida no Fracttal de hoje NÃO vai mais num pedido só dela: a recusa do código fora da dimensão volta com a culpada e o
  resto vai de novo), depois a ponte (`/api/admin/de-para/decidir`). Cada usina diz o que foi. As regras da resposta:
  - **a recusa 4xx que é de uma usina** traz o `usina_id` (e a `usina_supervisorio`) dela: a tela tira essa usina do lote e
    manda o resto de novo, no máximo 3 vezes; ela diz "o Nexus recusou esta usina (motivo)";
  - **sem resposta, estouro de 180 s, o 500 do Nexus ("leia o estado de novo") e o 502/504**: não se sabe se o Nexus
    gravou. A tela relê as usinas do lote pelo GET, e **espera** (2ª revisão final, 21/10/2026): o pedido abandonado
    continua no Nexus, e a releitura na hora devolvia o selo de antes; a tela dizia "como antes: salve de novo", guardava o
    selo velho, o Nexus gravava segundos depois e o 2º Salvar levava 409 sem a ponte. Agora: o selo que mudou quer dizer que
    gravou (o pedido é um passo só) e segue para a ponte, com a marca relida do estado (a chave que não vale no lugar da
    aba vira aviso); o selo igual só é "como antes: salve de novo" com o Nexus dizendo `gravando: false`; com ele gravando
    (ou sem dizer, um Nexus de antes), relê a cada 15 s até 5 min e meio (o teto do sync do livro é 300 s) e, sem saber até
    lá, diz "não se sabe se o Nexus gravou: recarregue daqui a alguns minutos", sem trocar a base da usina pelo selo relido
    (ela segue pendente). A releitura que falha diz "não se sabe" com as duas falhas. Os tempos são `esperaSelo`/`prazoSelo`
    das opções (os testes usam milissegundos). A recusa 4xx e o 503 em JSON do Nexus (o banco fora antes de gravar) são
    "nada foi gravado";
  - **a resposta que não é JSON** (o `_tela` do Nexus devolve 403 em HTML para quem não é admin e HTML com status 200 sem a
    chave do cadastro) diz quem respondeu, o quê (a página e o título) e o que quer dizer, nunca "HTTP 200 sem JSON";
  - **os avisos do Nexus** vão com a usina: o que cita a chave (“…”) com a usina da fonte dela, o da usina (o nome do
    Registro, "(usina N)") com a 1ª usina dela no pedido, o resto no fim; o "não vale no lugar da aba porque…" em destaque
    (vermelho), na barra e no cabeçalho da usina até o próximo Salvar;
  - **a manchete diz o que não vale no lugar da aba** (2ª revisão final, 21/10/2026): gravar no Nexus já não quer dizer valer
    nos leitores (a usina vale por inteiro ou nada, ver o CLAUDE.md do Nexus), e a manchete dizia em verde "De-para salvo ...
    Vale no tempo real em até 1 min" com toda chave em `nao_marcada`. Ela conta as chaves que não valem pela `marcacao` do
    Nexus (no caminho "respondeu tarde", pelo `substitui_aba` do estado relido) e fica âmbar: "Gravado no Nexus: N usina(s);
    K chave(s) NÃO valem no lugar da aba (...): nelas os leitores seguem com a aba, e o tempo real não muda".
- **A ponte** (depois do Nexus, só onde ele gravou): nenhuma quando a chave é a de hoje (pela forma normalizada) ou quando a
  linha NÃO tem `nome_api` e já se chama como a chave; com `nome_api` (a ponte por id renomeou a planta) e a chave igual a
  ele, a ponte vai VAZIA ("sem ponte": vale o nome da API, que é a chave); senão, a chave como o cadastro da plataforma a
  escreve. A ponte que falha NÃO vira a base da usina: ela fica "ponte pendente" (dito no cabeçalho, na Situação e na
  barra) e o Salvar seguinte manda SÓ o decidir, sem ir ao Nexus de novo, enquanto a chave escolhida for a mesma. **A ponte
  pendente vem do ESTADO** (2ª revisão final, 21/10/2026; `ponteDerivada`), não só da memória da instância: o Tempo real
  cria uma a cada "Modo de-para" e a Base uma por carga, e reaberta a Itaja 1 (228) aparecia "ligada e conferida", com
  "sugestão: a ponte grava ao salvar" e o Salvar desligado. Há ponte pendente quando a chave escolhida não é a de hoje, o
  Nexus já tem essa chave na usina do Registro e todo inversor da fonte que vai está nela com o código do Fracttal e
  Conferido (o rastro do Salvar; os 1.932 do "Ligar pela aba" não têm código). **Usina com pendência (do grupo ou de linha)
  não grava ponte nenhuma**, nem a derivada nem a que ficou pendente nesta instância (revisão do acerto final, 21/10/2026,
  `comPendencia`): a Coração 2 sem ligação recebia a sugestão "Coração 1 (111)", os INVERSOR01..03 dela casavam pelo nome
  com os da Coração 1 gravados e conferidos, e a ponte derivava com a pendência vermelha "a chave também está em Coração 1"
  na tela; um Salvar só da Pharma II mandava junto o decidir Coração 2 → "Coração 1 (111)" (a planta passava a ler o
  cadastro da outra). O "Sair do modo de-para" do Tempo real
  pergunta também pelas pontes pendentes (`pontesPendentes()`), não só pelas usinas mexidas.
- **"Deixar de fora"** (por linha com pendência): a API PV ainda lista o inversor trocado ("INVERSOR 2.1 (old)",
  "INVERSOR03-Cancelado", "INVERSOR02 - Antigo"), que casa o mesmo ativo do novo e prendia a usina inteira no "inversor
  repetido". A linha de fora não vai no pedido (o remendo do Nexus não mexe nela) nem na conta; tudo de fora não salva (a
  chave iria "no lugar da aba" sem inversor). O `inv_resumo` de verdade só traz quem leu hoje, então isto deve ser raro.
- **Desenho**: um `<tbody>` por usina; a mudança redesenha só as usinas que alcança (a mesma usina do Registro, a mesma chave,
  os mesmos códigos). Medido na bancada (`pv` inteira, 990 linhas): a tabela inteira são 2,7 MB de HTML e ~520 ms; um
  Conferido, ~57 ms. Na 2ª rodada (20/10, no node, o mesmo dado): 993 linhas, 2,8 MB, **192 ms** a tabela inteira; o perfil
  mostrou o `kw` criando um `Intl.NumberFormat` a cada chamada (~230 ms por desenho) e o "mexido" da usina calculado em cada
  linha: com os dois guardados, de 843 ms para 192. A sugestão segue acertando 839 de 841. As listas grandes (258 usinas do
  Registro, 147 do Fracttal) só ganham as opções quando a pessoa abre o select (`data-lazy`).
- **Tempo real** (`docs/redesign/Monitoramento (novo design).html`): botão "Modo de-para" ao lado do Criar OS só com
  `RD.abreAdmin` E `RD.gravaAdmin`, na aba Strings, nas contas da API PV (pv, semp, alveslima, 2capi; a 2C da tela é `owen`) e com o
  `inv_resumo` na linha (`_dpPode`/`_dpBtn`); `state.dpMode`; o Criar OS fica desabilitado; os chips de status somem; a barra
  `#gc-dpbar` entra no `_prendeOverlays`; `setSource`/`setView` saem do modo (`_dpSair`); "Sair do modo de-para" com
  mudança não salva pergunta antes. A busca da tela filtra as usinas do modo. **Abre com UMA LINHA POR USINA, recolhida**
  (26/10/2026, Levi: "No modo de-para gostaria de escolher qual usina quero ver o de-para antes, atualmente está expandindo
  tudo!"): o componente vai com `resumo: true` e sem `blocos`, o mesmo resumo da Base (as mesmas colunas) sem o bloco por
  conta, porque a tela já é de uma fonte e já está dentro do cartão "Detalhamento por Usina" (um nível de superfície só); o
  Abrir de cada usina dá a tabela por inversor só dela (só ela é desenhada), dá para abrir várias, e a barra do Salvar
  aparece com usina aberta, mexida ou resultado. No drill, `renderInversor` mostra o
  `nome_fracttal` com o da fonte embaixo ("na fonte Inversor 1.1") e a `cabine` do cadastro no lugar da do nome; o `name`
  segue sendo a chave. A `gcDeparaJanela` e o atalho "sem de-para" (o editor da ponte) ficam.
- **Base · De-para** (`templates/depara.html`): aba **Por usina** (padrão) com um bloco por conta da API PV e UMA USINA POR
  LINHA (Usina na fonte · Chave do cadastro · Usina no Registro mestre · Usina no Fracttal · Inversores ligados/na fonte ·
  Strings corretas · kWp · Situação · Abrir → a tabela por inversor dela); aba **Diagnóstico** com o de antes; o `?editar=` e
  o `?janela=1` abrem o editor da ponte como sempre (na janela, a aba Por usina nem carrega). As outras fontes (banco, Athon,
  Axis, RenoGrid, scadaGridco) seguem só no Diagnóstico: o resumo por inversor é das contas da API PV. Tema: navy aberta direto
  e na janela; na moldura, o do Nexus (`nexus_tema`/`nexus.tema`, o claro em `html.modo-nexus[data-tema="claro"]:not(.janela)`).
- **Armadilhas**: (1) o componente NÃO vem de `/static/`: com o Nexus na raiz o Caddy manda `/static/*` ao Nexus (menos
  fontes, logos e notif.js), e o `/static/depara_tabela.js` dava 404 no servidor (conferido em 21/10/2026, antes do 1º
  push; o botão sumiria calado, porque o `_dpPode` exige `window.DeparaTabela`). Ele sai por `/admin/de-para/tabela.js`
  (`depara_tabela_js`, só admin pelo `so_admin`, no `FORA_DO_MAPA`); a Base o pede no `<script>`, e o Monitoramento só
  para quem grava (`_dpCarrega`, depois do /api/eu; os outros levariam o login em HTML no lugar do script). (2) A foto do Fracttal é de 22/09: usina refeita depois que ainda aparece na aba
  com o nome velho (a PHS200) só sai certa porque a mais nova casa os inversores; com nomes que não casam em nenhuma, vale a da
  aba. (3) O Conferido é da linha: a falta da chave (do grupo) segura só o Salvar.
- Testes: `tests/test_depara_tabela_telas.py` (Itajá e Pharmas, o número do código, a subusina, a conta do kWp, a tabela, o
  Conferido, o repetido, o "deixar de fora", o Salvar e as duas falhas parciais, sem o Nexus, a Base com uma usina por linha, o
  botão só para admin, o molde do Criar OS, o drill e a `chave_cadastro`; e os da 1ª revisão, com os casos reais: a conta da
  Sapopema com os sem strings, o "fica o de antes" sem Registro, a Coração 2 com a chave da aba, o parado e o nome do
  cadastro, a Assis Skid 1 de espaço duplo, a usina recusada que sai do lote, o gestor só leitura, a ponte pendente, o kWp
  do Nexus, as strings da leitura, o código que o Nexus tem numa usina que não vai, a releitura pelo selo, a ponte com
  `nome_api`, os avisos por usina e a resposta que não é JSON; e os da 2ª revisão final de 21/10: a "Nova chave" fora da
  lista e a chave fora da aba e do Nexus como pendência, a ponte pendente que volta ao reabrir, a releitura que espera o
  Nexus (o selo velho no meio da gravação, o `gravando`, o prazo), a troca de códigos entre usinas num pedido só, as duas
  CABN de mesmo número, a manchete com as chaves que não valem, a chave irmã da Coração; e os de 26/10, com o dado do
  servidor da União: sem o de-para por id não duplica nem salva e a conta não conta duas vezes, com ele liga ao cadastro e
  o pedido leva o supervisório do cadastro, o "sem leitura agora" só com todas as linhas casadas, e o Tempo real com uma
  usina por linha). `tests/test_modo_depara_backend.py` tem o `esup` da União pelo id. Mutações
  (`scratchpad .../r2_plat/mutar_plat.py`, as de 21/10 em `scratchpad .../r3/mutar_r3.py` e as de 26/10 em
  `scratchpad .../uniao/mutar.py`): cada regra quebrada de
  propósito faz o teste dela falhar. Bancada: as páginas reais com as leituras dubladas pelas cópias
  do banco e o Nexus imitado em `/nexus` (o script ficou no scratchpad da sessão de 20/10).

## Meta do mês no banco para o Nexus (12/10/2026)

Levi: "Agora temos em um canto só as metas da performance, a disponibilidade, o tanto que o ativo parou, o tempo que o COS
demora para abrir a OS, os chamados, rondas, PTs e APRs (...) construa a visão dos responsáveis da usina!". A Visão do
responsável do Nexus (Campo · App) tira a meta do mês daqui: o worker publica o Gerencial no livro
`nexus_performance · fato_meta_usina_mes` (registrado no catálogo do Nexus antes de existir).

- **Os mesmos números da Visão gerencial**: `gerencial_publicar.linhas` copia o `_ger_cache` (o `_gerencial_payload` do
  mês, refeito a cada 5 min) em linhas `mes_id × usina`, sem refazer conta. Energia em kWh (`prod` e `p50` do Gerencial,
  que são MWh com 1 casa, × 1000): a regra 3 do catálogo do Nexus só aceita `_kwh` no nome da coluna. "—" vira vazio;
  `full_oem` vira 1/0; o `pr_motivo` (texto livre) não vai (a API do banco tem leitura aberta).
- **Quando**: `_ger_publicar_loop` espera 10 min o Gerencial aquecer e tenta a cada 10 min; publica no máximo de hora em
  hora (`GER_PUB_TTL`) e só quando o conteúdo muda (sha1 das linhas novas). Refaz o mês corrente e, até o dia 5, o
  anterior (`_gerencial_payload(ano, mes)`: OS e BD fecham com atraso); os outros meses ficam como estão
  (`gerencial_publicar.mesclar` sobre o livro relido do banco, porque o `replace` troca a aba inteira).
- **Travas**: Gerencial com `erro` ou sem usinas não publica (não apaga o mês que o banco tem); leitura do livro que
  falha não grava nada; depois de gravar, relê e confere a contagem (diferença = tenta na próxima volta). Só o servidor
  (Linux) grava: PC e servidor juntos alternariam os números de cada um. `GER_PUBLICAR=1/0` força numa máquina.
  A última leitura boa do livro fica em `ger_publicado.json` (estado, fora do git).
- **A série diária do Painel NOC** (12/10/2026, para as janelas de Meta e de PR da Visão do responsável: "essa mesma
  visão do PAINEL NOC > HISTÓRICO > PR > PR DIÁRIO EXPANDIDO"): a aba `fato_desempenho_usina_dia` do mesmo livro, com o
  próprio `/api/g/diario` chamado por dentro (`_ger_diario`, como o `_relatorio_build` faz) para cada usina do Gerencial
  (`_ger_series_diarias`): o cliente é o do seletor do Histórico (Thopen para as do banco da Thopen, o cliente para as do
  BD_Performance); o nome que não acha a aba do BD_Thopen tenta o de mesma chave solta (`_usina_chave_solta`). 1 linha =
  usina × dia: geração e meta do dia em kWh, POA e meta de POA, PR e meta de PR em %.
  **A geração e os dias são os do Gerencial** (13/10/2026): os três motores do Gerencial guardam o dia a dia que entra no
  atingimento (`ger_dia` = {dia: kWh}, os MESMOS dias do `dias_cob`, cada um com a régua da sua fonte: PG = dia que a
  fonte reportou; BD_Thopen = `_thopen_dia_coberto`; BD_Performance = linha com número de inversor e sem lixo) e a meta
  do dia sem arredondar (`meta_dia_kwh` = meta do mês ÷ dias do mês); a série usa os dois, e o POA e o PR continuam os do
  PR diário. Por quê: com a geração do PR diário a tabela da Meta do Nexus não fechava em 78 de 131 usinas (a Thopen pula
  o dia com POA até 0,3: Indaiatuba 5 dias e 87% contra 12 e 66%; o BD_Performance escreve 0 no dia em branco: Castelo
  do Piauí 31 dias e 54,9% contra 9 e 189,1%; e a meta arredondada a 0,01 MWh errava 0,2 ponto nas pequenas). Dia que só
  o PR diário tem entra só se tiver PR, com a geração vazia. Prova de 13/10 (o Gerencial de outubro montado com o código
  novo): `ger_dia` fecha no `prod` e no `dias_cob` das 135 usinas que o têm, a tabela fecha no % das 135, e o Gerencial
  segue IGUAL ao do servidor nas 161 (prod, meta, atingimento, dias, PR). Os dois campos não vão na resposta do
  `/api/gerencial` (`api_gerencial` tira). Payload de antes do `ger_dia` (snapshot do disco ao subir): nenhuma série, e o
  mês do banco fica como está. Vai no
  mesmo xlsx da meta (`gerencial_publicar.xlsx_bytes`: as duas abas juntas, porque o `replace` troca o livro), com a
  mesma mescla por mês e a conferência das duas contagens; mês sem série nenhuma não apaga a do banco. A última leitura
  boa da aba fica em `ger_publicado_dia.json`.
- Testes: `tests/test_gerencial_publicar.py` (as linhas sem texto livre, a série diária, o xlsx de duas abas, a mescla
  dos meses, o dia 5, publica e só quando muda, Gerencial que falhou e banco fora não gravam, mês sem série não apaga a
  do banco, desligado não publica; e, de 13/10, a série pela geração do Gerencial, o `ger_dia` do BD_Thopen e do
  BD_Performance, a meta exata, o payload antigo sem série e a resposta sem o dia a dia).

## Valor estourado da Ibirapuã II fora do Gerencial (18/10/2026)

O Gerencial de outubro deu 7.209% na Ibirapuã II (e a meta do mês do Nexus e a Visão do responsável junto): a linha de
13/10 da aba dela no BD_Performance (digitada à mão; nenhuma etapa do coletor grava essa aba) veio com os CONTADORES
ACUMULADOS dos medidores no lugar da geração do dia (multimedidor do SKID 1 = 4.351.190 kWh; 3.127 kWh por kWp num dia),
e estava VALIDADA, então a trava de 14/09 (`_INV_DIA_MAX_KWH`, só dia não validado) deixou passar. Levi: "faça um filtro
que filtre apenas esse valor estourado em Ibirapuã, faça especificamente para essa usina".
- `_ger_dia_estourado` (motor do BD_Performance, `_bdperf_prod_build`): **só nas usinas de `GER_DIA_ESTOURADO_USINAS`
  (hoje só a Ibirapuã II)**, o dia com geração acima da potência × 12 h (`GER_DIA_ESTOURADO_KWH_KWP`, o impossível) vira
  "sem leitura": sai da geração, dos dias da meta, do PR e do `ger_dia`, e vai para `dias_sem_leitura` (dia, kWh, kWh/kWp).
  Quando a linha for corrigida, o valor certo volta a contar sozinho. A tela marca "N dia(s) sem leitura" na célula da
  geração; a série diária (`fato_desempenho_usina_dia`) sai sem geração e sem PR nesse dia.
- **Régua geral não serve** (medido em 18/10 com o outubro real): o PR do dia acima de 150% tirava 13 de 15 dias das
  Aparecida do Taboado 1 e 2 (a irradiação do banco da OEM é errada) e dias de Junco, Fernandópolis, Córrego do Sapucaia,
  Sete Lagoas e Alto Paraná 2, com geração verdadeira. A potência × 12 h em todas as usinas só pegaria a Ibirapuã II, mas
  o Levi pediu o filtro só dela.
- Prova (18/10, o código novo × o servidor): só a Ibirapuã II muda (10.761,6 → 140,7 MWh, 10 → 9 dias); as outras 161
  usinas, produção e dias iguais. O conserto da fonte é da equipe que digita a aba (trocar a linha de 13/10 pela geração
  do dia e preencher 10–12/10).
- Santo Anastácio (217,7%) e Álvares Machado (331,1%), no mesmo dia: a produção está normal; a META de outubro na aba
  "Dados Mensais 2026" do BD_Thopen é que está baixa (~1,3 e ~0,9 kWh/kWp/dia). Não é da plataforma.
- Teste: `tests/test_gerencial_valor_estourado.py`.

## Número anômalo sinalizado no Gerencial (18/10/2026)

Levi: "sobre as demais quero que apenas sinalize que o número está anômalo e o dado pode estar errado, temos que
sinalizar pela plataforma e não ficar travando a construção!". **Só sinaliza: o número fica como está.**
- `_ger_anomalia` (no fim do `_gerencial_payload`, em toda usina) → `anomalia` = CÓDIGOS de uma lista fechada,
  separados por vírgula, e `anomalia_txt` = a frase de cada um (só para a tela daqui):
  - `meta_baixa` / `meta_alta`: a meta do mês por kWp por dia (`meta_dia_kwh` ÷ kWp; sem ela, a meta prorrateada ÷ os
    dias da meta) fora de `GER_META_KWH_KWP_DIA` = 2 a 8. Régua escolhida pelo Levi entre quatro medidas no outubro real
    (PR do mês acima de 130%, geração do mês acima de 8 kWh/kWp/dia e atingimento acima de 200% ficaram de fora). Em
    outubro pega Álvares Machado (0,9) e Santo Anastácio (1,3); o portfólio fica de 4 a 6.
  - `geracao_impossivel`: a usina tem dia "sem leitura" (o filtro da Ibirapuã II, seção acima); sem limiar novo.
  - É o domínio `dominios.ANOMALIA_META` do catálogo do Nexus (os três, registrado lá em 18/10, 2b489cb); código novo =
    domínio novo lá antes da 1ª gravação.
  - Código e não frase porque a regra 8 do catálogo do Nexus não aceita texto livre no fato (o mesmo motivo de o
    `pr_motivo` ficar de fora); quem mostra traduz. Código novo só com régua aprovada pelo Levi, e avisando o Nexus.
- A tela marca "dado anômalo" (âmbar) ao lado do atingimento, com a frase no título. O `fato_meta_usina_mes` leva a
  coluna `anomalia` no FIM (depois de `meta_fonte`), vazia quando normal; a Visão do responsável do Nexus a lê pelo nome.
  Coluna nova = registro no catálogo do Nexus antes da 1ª gravação (regra 10).
- Teste: `tests/test_gerencial_anomalia.py`.

## Disponibilidade por OS (`/gerencial/disponibilidade`)

A conta mora em `disponibilidade.py` (puro; réguas e decisões em `docs/disponibilidade-por-os.md`, o caminho de runtime
em `docs/calculo-disponibilidade-gerencial.md`): o worker varre o Fracttal e publica `frac_disp_index.json` a cada 30 min,
e o web só serve (`/api/gerencial/disponibilidade`).

**A regra desde 15/10/2026: só o Fracttal de outubro em diante.**
Levi, 15/10/2026, a partir da OS 16338 (Corretiva Emergencial do Inversor 2.2 de Ipixuna 2, aberta desde 16/09, que valia
0 h em setembro e sumia de outubro): "A disponibilidade será calculada somente pelo Fracttal a partir de outubro;
setembro para trás vamos considerar o que está no BD_Thopen. Será considerado OSs fechadas e abertas; OSs com diferenças
negativas (evento depois do fim) — a data de criação como data do evento"; fora da Thopen, "só a partir de outubro!"; e
"não quero que olhe a geração (...) pode até apontar possíveis erros em criação de OS". Regras em
`docs/disponibilidade-por-os.md` (§4, 4.1, 4.2) e o runtime em `docs/calculo-disponibilidade-gerencial.md`.

- **De `DISP_SO_FRACTTAL_DESDE` ("2026-10") em diante** (`_frac_disp_recalcular` → `disponibilidade.calcular`): OS aberta
  conta até o fim do período em todo mês em que seguir aberta; evento depois do fim usa a criação (fim antes até da
  criação = 0 h); **o juiz da geração saiu** e a disponibilidade é **isolada da geração** (Levi: "a geração não deve
  afetar a disponibilidade (...) disponibilidade é full Fracttal, isolada da geração"): o laço não lê geração nenhuma
  (até 15/10 ele a buscava para a aba Falhas antes de publicar, e o banco lento atrasava o índice; a aba Falhas busca a
  dela, `_falhas_geracao`). Geração e disponibilidade lado a lado numa tela (Gerencial, Relatório Semanal) tudo bem; uma
  mexer na outra, não. Teste: `test_o_laco_da_disponibilidade_publica_sem_nunca_ler_a_geracao`.
- **A "Disponibilidade UFV" da cascata do Gerencial (`_cascata_usina`) e do Criador de Relatório (`_relatorio_build`)**
  divide as horas de OS pelos dias FECHADOS do período, não pelos dias com geração na série (até 15/10/2026 um dia sem a
  geração no BD tirava 12 h do divisor e derrubava a disponibilidade; achado da auditoria de 15/10). Sem dia fechado,
  "—". As perdas em energia das duas seguem pelos dias da série (são da geração). As duas ainda usam a régua do BI antigo
  (só OS de usina inteira, evento no período), não o índice da tela Disponibilidade: o número pode diferir dele.
  Teste: `tests/test_disp_cascata_relatorio_sem_geracao.py`.
- **Antes** (`calcular_pelo_bd` + `_disp_dias_bd_thopen`): só as usinas da Thopen, pela "Disponibilidade Usina (%)" do
  BD_Thopen (o leitor do 5080), sem OS e sem queda × equipamento; de-paras em `_DISP_BD_ABAS` (os do Gerencial).
- **A Thopen pelas normalizações do COS (29/10/2026)**, Levi: "calcule a disponibilidade por lá [Nexus > COS >
  Normalizações] usando o de-para como referência [...] o que for falha de comunicação tem a coluna Geração Parou, se sim
  então deve contar na disponibilidade e entrar nos comentários. Nos comentários tem que vir as proteções atuadas";
  decisões dele: **só a Thopen** e **só o que está na Ronda COS** (as normalizações e, desde 30/10/2026, as ocorrências
  ainda abertas, abaixo). O Nexus grava o fato (`nexus_cos_normalizacoes · fato_normalizacao`, de hora em hora); o worker o lê
  (`_disp_normalizacoes`, conferido com a contagem da `atualizacao`) e o `disponibilidade.calcular(..., normalizacoes,
  usinas_por_id)` põe as usinas da Thopen (cliente da aba Equipamentos) pela normalização: **início = a falha, fim = a
  volta registrada pelo COS**, não o fechamento da OS no Fracttal; a OS do Fracttal só da Thopen sai da lista. Conta:
  todo `DESLIGAMENTO_*` (usina, cabine, SKID, QGBT, inversor), a `FALHA_COMUNICACAO` com `geracao_parou` = 1 e, pela
  decisão do mesmo dia, a atuação de proteção, o inversor offline e a falha da concessionária (`COS_TIPOS_PARADA`; a
  concessionária é a usina inteira); a de comunicação sem resposta vai ao "alinhar" ("COS sem resposta"); desfeita, sem
  hora real e os outros tipos (falha de string, manutenção programada, ventilador, tracker) ficam fora, "COS: ...".
  Exceções do Levi pelo registro ou pela OS (`COS_EXCECOES`, à vista no "alinhar"): na Brodowski a OS 12693 sai ("a
  geração não parou") e a normalização sem OS de 02/07 a 28/10 vale só a cabine 1. A usina: o usina_id do Nexus → as usinas da aba pelo de-para (`depara_fracttal.usinas_por_id`: a chave
  externa casa com o nome da usina OU com o site do Fracttal dela; o cadastro "Ipixuna 1 e 2" é as duas da aba). O
  escopo: desligamento de usina = a usina inteira (o relé citado não muda); com código, a cabine e o inversor lidos NA
  usina da normalização (o relé, RELE, é a usina inteira e o QGBT N é a cabine N, Levi 30/10/2026;
  `_escopo_na_usina`: o site dividido não manda a cabine para a vizinha; até 30/10/2026 as
  cabines da Rodrigues 2 iam para a Rodrigues 1 e caíam na potência média), o `escopo_os` só no cadastro de duas usinas;
  código que não é de geração vale pelo tipo, com a potência média, e vai ao "alinhar"; normalização de mais de 24 h
  também vai ("conferir a falha e a volta na Ronda COS"). As proteções vão na OS (`protecoes`) e na aba
  `disponibilidade_os_dia` (`fonte` cos). **A única fonte da Thopen é a normalização + as adaptações** (30/10/2026,
  Levi: "garanta que a única fonte seja a de normalizações + adaptações sem puxar OS de fractall"): a OS do Fracttal só
  da Thopen sai, a de site misto perde a parte da Thopen, e sem o livro, com a leitura pela metade ou sem o de-para o
  worker NÃO publica (fica o índice anterior; nunca cai para o Fracttal; teste
  `test_sem_as_normalizacoes_o_worker_nao_publica_e_a_thopen_nao_cai_no_fracttal`). A conta de antes, só para o
  cliente (`meses_fracttal` e as abas `_fracttal`), existiu de 29 a 30/10/2026 e saiu com a liberação. Fora do
  índice, a cascata do Gerencial, o Criador de Relatório e o % disp do Diagnóstico ainda usam as OS do Fracttal
  (`_frac_os_filtradas`, a régua do BI antigo). Ensaio de 29/10/2026 (outubro até o dia 28, 555
  normalizações da Thopen, 444 contando): Thopen ponderada 88,85% (Fracttal) → 94,16% (COS); Brodowski 95,49% → 46,75%
  (a cabine 1 o mês todo), Colorado 2 78,43% → 61,60%.
  **Conferência com as barras do Diário (30/10/2026**, Levi: "se o COS marcou como desligamento então tudo ok, você pode
  checar com o gráfico de barras do dashboard thopen para bater e me retornar o que não faz sentido, mas o que fizer manda
  para frente!"): cada OS do COS de outubro contra a geração do dia (a esperada = a geração por irradiação dos dias sem
  perda da usina × a irradiação do dia; a parada pesada pela energia do horário, seno de 06 a 18 h). Das 432: 314
  pequenas (menos de 20% da energia de um dia), 68 batem, 16 em parte (seguem contando), 3 sem geração e 31 em que a
  barra não caiu, que foram a ele; ele respondeu na planilha, e as respostas viraram exceções (`COS_EXCECOES`: "fora",
  "volta" por usina com `fim_por_usina`, "periodo"). No mesmo dia o COS corrigiu os registros na Ronda COS (SCADA, PV
  Operation e relato dos técnicos) e, onde discordou da planilha (Boa Esperança do Sul 2, Canarana 1, Fazenda Limão,
  Ipixuna 2, o inversor 1.4 da Ipixuna 1, Matão 2 e Nova Londrina em 29/10), o Levi decidiu "Vale o COS": **as exceções
  da planilha saíram, e a fonte é a Ronda COS corrigida**. Ficam a OS 15632 (São Bento 5, falha de comunicação sem
  resposta: "considera desligamento", `desligamento`) e o `ESCOPO_COS` da 16498 (só a AP2) e da 17447 (só a BES2: o
  registro é do cadastro "Boa Esperança do Sul 1 e 2", sem a cabine; sai quando o COS acertar lá). Os mecanismos das
  exceções ficam no código para a próxima conferência. A conta não lê geração: exceção é decisão escrita do Levi, nunca
  um juiz automático; o certo é o COS corrigir na Ronda COS.
  **A usina da Thopen que a Ronda COS monitora entra na conta** mesmo com "Full O&M: Não" ou sem a Usina Fractall na aba
  (30/10/2026: Aruanã, Sapopema e Segredo, com desligamentos registrados pelo COS, e a Coração 2 ficavam fora do parque;
  Levi: "Passam para o COS"): a que tem normalização ligada pelo de-para e potência no catálogo. Thopen de outubro (01 a
  29): 95,22%, 91 usinas.
  **A parada que segue aberta conta** (30/10/2026, Levi: "para as em aberto contar na disponibilidade precisamos puxar
  os dados dessa fonte"; até ali só contava quando o COS normalizava, e a OS 16958 de Santarém, inversor parado desde
  12/07 aguardando peça, não contava nada): o Nexus grava na mesma volta o retrato das abertas da Thopen
  (`fato_ocorrencia_aberta`, da fotografia do Andamento, `GET /api/nexus/Thopen`); o worker o lê junto, confere com o
  `abertas_qtd` da `atualizacao` (pela metade = nada publicado; a gravação de antes, sem a coluna, só tem as
  normalizações) e o `abertas_como_normalizacao` as põe na régua sem a volta, tirando a que já está normalizada (a
  mesma chave, o registro: conta uma vez, pela volta do COS). O `consolidar_normalizacao` conta a aberta **do início até
  agora** (o período corta em D-1), como a OS aberta do Fracttal contava (Levi, 15/10/2026), com o mesmo escopo e os
  mesmos tipos; sai "em aberto" no comentário do Dashboard (`aberta`, `fim` vazio), e a de mais de um dia vai ao
  "alinhar" com a etapa ("aguardando peça"). A falha de comunicação aberta fica fora até o COS normalizar: a resposta
  "a geração parou?" vem na normalização, e aí o trecho inteiro conta; não vai ao "alinhar". A OS com uma parte
  normalizada e outra aberta segue aberta.
  Prova: `tests/test_disp_normalizacoes_cos.py`.
- **Falta de comunicação NÃO é parada** (Levi, 19/10/2026: "a falta de comunicação não deve entrar no cálculo de
  disponibilidade"). A OS cuja descrição (ou o ativo) diz "comunicação" (`disponibilidade.eh_falta_de_comunicacao`; no
  Fracttal ela vem como "Verificação de comunicação do ...", tipo Religamento ou Corretiva Emergencial) fica fora da
  conta (`EXCL_COMUNICACAO`), com a usina, e aparece no "alinhar" como "fora da conta: falta de comunicação". Vale também
  no % disp do Diagnóstico (`_dispDia`), na cascata do Gerencial e no Criador de Relatório, e o Relatório Semanal não a
  conta como desligamento. Em outubro (até 18/10) eram 113 OS e 27,8% da energia perdida: Thopen 81,47% → ~86,2%,
  Athon 85,06% → ~92,5%, Renogrid 82,18% → ~90,5%; Brodowski 0% → 100% (OS 12693). O Tempo real não muda: a OS aberta
  de Religamento na usina inteira segue marcando "usina desligada" (`_religamentos_abertos_usina`).
- **A de comunicação que foi parada conta** (Levi, 26/10/2026: "agora sabemos tudo o que estava sem subtarefa porém foi
  religamento em outubro, bote na conta e a partir de agora veja as últimas OSs criadas sobre comunicação que foi
  confirmado na subtarefa que foi religamento"). O worker lê as subtarefas de toda OS de comunicação da varredura
  (`_frac_com_vereditos`, guardadas em `frac_com_subtarefas.json`: a concluída uma vez, a aberta a cada volta; o Fracttal
  fora não segura o índice) e o `disponibilidade.veredito_subtarefas` decide pelo **Diagnóstico**: "Desligado" = parada,
  conta; "Só sem comunicação (segue gerando)" = fora; o formulário do religamento ("Foi necessário religamento?" = Sim)
  também conta; em branco ou sem subtarefa, fora. A Ação não decide: das 162 OS de comunicação de outubro, as 18 com "Só
  sem comunicação" e "Religamento local" eram roteador, smartlogger e internet. O **retorno do COS** de outubro
  (`RETORNO_COS`, planilha de 26/10/2026) vence a subtarefa: põe na conta três sem subtarefa que foram parada (16640,
  15678, 16515) e tira quatro que eram só comunicação (16653, com a subtarefa "Desligado" e a usina gerando; 14997, 15025
  e 15314, abertas como Religamento ou inspeção). Os vereditos vão no índice (`comunicacao`), e a cascata, o Criador de
  Relatório e o % disp do Diagnóstico (`comunicacao_fora` em cada OS do `_frac_os_filtradas`) decidem igual
  (`_disp_comunicacao_fora`). Em outubro: 52 OS entram (689 h solares) e 3 saem. As datas são as do Fracttal (o fim da
  ATIVIDADE, `final_date`; o fim da OS só sem nenhum); data errada se corrige lá, e o religamento de mais de um dia vai
  para o "alinhar". **Fim corrigido à mão** só onde a OS não pode mais ser editada (`disponibilidade.CORRECOES_FIM`; Levi,
  26/10/2026: "15192 infelizmente não temos mais como editar então faça essa peculiaridade manual"): São Bento do Una, OS
  15192, termina às 10:40 de 02/10 (o COS) e não em 05/10 22:30 (a atividade). Vale na conta e no drill
  (`_frac_os_filtradas`) e fica no "alinhar" com o fim do Fracttal. A Metodologia da tela da disponibilidade (a mesma de
  Performance → Disponibilidade no Nexus) explica a regra da comunicação e a correção.
  **Escopo pelo COS** (`ESCOPO_COS`, Levi, 26/10/2026: OS 16498 "Só na AP2"): a OS no site de duas usinas que o COS
  diz ser de uma só conta só nela — na conta, na cascata, no relatório e no drill (`escopo_cos_exclui`). **O que a
  subtarefa diz e a geração desmente fica como o Fracttal diz** (Levi, 26/10/2026, "Deixar como o Fracttal diz"): Pharma
  II 15066 e Pharma IV 15777 ("Desligado" com a usina gerando como a Pharma III), São Bento do Una 15855 (09/10) e Inhapi
  16059 (11 e 12/10); quem corrige é o COS, no Fracttal. Medido na 1ª publicação (15:48 de 26/10): 52 OS entraram, 44
  usinas mudaram; Ceilândia 1 76,88% → 94,54% e Sítio dos Nogueiras 76,66% → 94,02% (as que o COS tirou).
- **As Pharma II, III e IV** (Levi, 22/10/2026: "Pharmas mudou o nome no fracttal, esse mês vai pegar as OSs no nome
  antigo e no novo. No novo se diferencia por cabine, nos antigo é nome mesmo"). Até 22/10 as três ficavam fora da conta e
  "—" no Dashboard Thopen, por dois motivos:
  - **Sem potência na aba Equipamentos** (as 24 linhas delas vazias): toda OS saía com "nenhuma usina do site ... tem
    potência no BD". Agora a usina SEM potência nenhuma na aba usa o kWp do Registro mestre do Nexus (`pot_reserva` do
    `calcular`, montado por `_disp_pot_reserva` com `depara_fracttal.kwp_por_nome`: o nome da aba casa com UMA usina do
    Registro pelo de-para do Nexus ou pelo nome; a real × 1.000, sem ela a contratual — a regra do kWp de 20/10/2026). As
    Pharma: 990 kWp cada; o inversor, 990 ÷ 6 = 165. O que a aba tiver vence, e a reserva vira lacuna. Em 22/10 mais três
    usinas estavam sem potência e sem reserva única (Sol Maior 2 - TO, Taguaí 1 e 2): seguem fora.
  - **O site novo:** o Fracttal refez as Pharmas depois de 22/09 em UM site, "Thopen - Pharmas - PR" (THPN-PHS100), com a
    CABN2/3/4 e os inversores INVR2.x/3.x/4.x. `disponibilidade.SITES_POR_CABINE`: a cabine N é a Pharma N inteira, o
    inversor N.M é o 1.M da Pharma N no BD, a raiz vale para as três e o resto (estação, infraestrutura) fica fora como
    não-geração. O nome antigo ("Thopen - Pharmas N - PR") segue pela "Usina Fractall" da aba.
  - Prova (22/10): as 12 OS válidas das Pharma de outubro (todas fora da conta antes) entram, cada uma na usina certa (10
    na usina inteira, 990 kWp; a THPN-PHS300-INVR1.1 e a THPN-PHS400-INVR1.6 no inversor, 165 kWp);
    `tests/test_disp_pharmas.py`.
  - **Numeração própria do Fracttal (Barretos, 27/10/2026, Levi: "arrume o de-para de barretos"):** lá os inversores
    são INVR1.1 a INVR1.40 numa fila só; no cadastro, 1.1–1.20 (UG 1) e 2.1–2.20 (UG 2). Conferido ativo por ativo no
    Fracttal: 1.1–1.20 no SKID 1 / QGBT 1, 1.21–1.40 no SKID 2 / QGBT 2, INVR2.x inexistente. `disponibilidade.
    INV_RENUMERADO` ({code-base: {nº Fracttal: nº cadastro}}) vale nos DOIS sentidos e em todo lugar que traduz um no
    outro: o índice (`escopo_os`, com flag), os chamados do Diagnóstico (`diag_tratamento.ativo_do_codigo`), o código
    derivado do ativo (`_frac_inv_code` e o Investigar ativo: o 2.5 vira BRS100-INVR1.25) e as OS de strings
    (`_falhas_os_*`, que guardam o nº do cadastro). O código GRAVADO pelo Modo de-para continua vencendo. Antes, a OS
    17428 (religamento do INVR1.21) caía num "Inversor 1.21" que não existe, com a potência média. Usina nova com o
    mesmo defeito entra na tabela depois de conferida no Fracttal. Prova: `tests/test_barretos_renumerado.py`.
- **`alinhar`** no lugar do `cenario_abertas` (que saiu do payload): as OS que pedem um olho no Fracttal, só pelo dado
  dele (aberta contando, evento depois do fim, `wo_final_date`, site agrupado sem a usina, Religamento com descrição de
  inspeção, religamento de mais de um dia, OS fora da conta — a de falta de comunicação inclusive). A tela
  Disponibilidade mostra a lista no balão do ícone de atenção e, no mês do BD, o aviso da fonte.
- **Prova (15/10, varredura real × índice publicado com a regra antiga):** outubro Thopen 88,47% → 80,43% (~4,8 GWh dos
  dias que o juiz exonerava, ~1,5 GWh de OS abertas desde setembro: Brodowski 12693 e Guatambu 13427); Ipixuna 2 91,1% →
  76,7% (a 16338 com 168 h); 175 OS de outubro em "alinhar"; setembro Thopen 95,51% → 95,40%.
- Testes: `tests/test_disp_fracttal.py`, `tests/test_disp_varredura_completa.py` (o corte por mês),
  `tests/test_painel_v2_disp_dia.py` e `tests/test_disponibilidade_tela_13_10.py` (o gabarito de 13/10 virou a régua do
  que a regra nova pode mudar: só a OS que a geração "desmentia" e a aberta sem data final).

A tela desde 13/10/2026 (pedidos 3 a 6 do Levi):

- **Atenção é ícone, não faixa** ("deixe como um informação de atenção em um ícone de exclamação acima do filtro do mês,
  ao clicar no ícone aparece a mensagem!"): desde 15/10/2026 o ícone lista as OS para alinhar no Fracttal (o `alinhar`;
  até 15/10 eram as abertas sem data final, que valiam 0 h) e, no mês do BD_Thopen, diz a fonte; ícone âmbar ACIMA do
  seletor do mês, fora do corpo, só quando há o que avisar — o
  `ph-warning-circle` do Phosphor desenhado em SVG, porque a tela não carrega a fonte de ícones. O clique abre a MESMA
  mensagem de antes num balão (`aria-expanded`; Esc e clique fora fecham, o Esc devolve o foco ao ícone). Mês que sai do
  índice (`quente: false`) esconde o ícone junto.
- **KPI só com o valor principal** ("tire a informação de disponibilidade por queda e por equipamento"). A divisão segue
  no módulo e só aparece nas colunas da tabela "Detalhe por usina" e no card do dia: `origem` da OS = queda (Religamento,
  Religamento Remoto: origem externa, rede/concessionária) ou equipamento (Corretiva Emergencial: falha física nossa), a
  OS com os dois tipos conta como queda; cada família é a mesma varredura só com as OS dela, por isso as duas não somam o
  total (metodologia da Ana Patrícia, 29/08).
- **"O que derrubou o mês" em duas linhas** ("muita informação (...) Tem que deixar mais enxuto"): em cima `Usina –
  Equipamento`, embaixo `OS · tipo · evento → fim · N h solares`, a perda ao lado (as 6 maiores, como antes). O equipamento
  é o nome que o cadastro do Fracttal dá ao sufixo do código do ativo (`equipamento()` na tela; os nomes vêm do
  `items_log_description` de 39 mil tarefas): CABN → Cabine, SKID → Skid, QGBT, PECN → Ponto de Entrega, DTRF → Disjuntor
  do Transformador, INVR → Inversor, DINV → Disjuntor do Inversor; sem sufixo = Usina. As horas são o `h_solar` da OS
  no mês ("no mês" quando ela passa da borda); OS ainda aberta no Fracttal diz "em aberto". (De 13 a 15/10 a linha dizia
  também os dias que a geração desmentia; saiu com o juiz.)
- **Disponibilidade por cliente** no lugar das barras por usina ("ao clicar na linha vai expandir as usinas daquele
  cliente! ao clicar na usina aparecerá as OSs"): cliente → usinas → OS, cada linha um `<button>` com `aria-expanded`. O
  cliente é o `cliente` da usina no payload (coluna Cliente da aba Equipamentos, o mesmo do filtro) e pondera as usinas
  dele pela MESMA conta do total (`dispPonderada`: 1 − Σ(kWp × horas perdidas) ÷ (Σ kWp × 12 h × dias)): os clientes fecham
  com o total e batem com o `clientes[].disp` do módulo. O que está aberto continua aberto na releitura de 5 min
  (`ABERTOS`). O drill-down lista as OS da conta da usina (as com evento nela, o "OSs" da tabela; desde 15/10 a aberta
  sem fim também, porque conta), da maior perda para a menor, com a perda da OS NAQUELA usina.
- **`kwh_usina`** (novo no índice, por OS: {usina: kWh}) é a mesma parcela do `det_os` separada por usina na varredura
  (`_varrer`): soma a perda da OS e a da usina, e as chaves são as usinas onde a OS tem evento. Repartir pela potência
  erra quando o teto de 100% pega uma usina e não a outra (e, até 15/10, quando a geração desmentia o dia numa só): no índice de 13/10 a
  Rodrigues 1 e 2 trocavam ~47,9 MWh de setembro, e a Boa Esperança do Sul 1 e 2 ~2,5 MWh de outubro. O
  `disponibilidade_os` do workbook de falhas (Nexus) usa o mesmo campo desde 13/10 (seção "Falhas de strings e
  trackers" › `disponibilidade_os`).
  Índice de antes do deploy (sem o campo, até a 1ª varredura do worker): a OS de 2+ usinas mostra a perda somada e diz
  isso.
- **Prova (13/10/2026)**: o módulo de antes × o de agora sobre 39 mil tarefas reais (`frac_mtta_linhas.json`) e a aba
  Equipamentos real, setembro e outubro, sem geração e com geração plena forçando o juiz: saída idêntica, e o `kwh_usina`
  fecha com cada OS, cada usina e o `n_os`. A tela de antes × a de agora no node, sobre o índice real (2 meses × parque e
  11 clientes, 520 linhas de usina): mesmo total (outubro 92,02%, setembro 94,51%) e mesmas usinas; os clientes fecham com
  o total (diferença 0).
- Testes: `tests/test_disponibilidade_tela_13_10.py` (a página inteira no node sobre a rota de verdade; o gabarito
  `tests/fixtures/disp_antes_13_10.json` é a saída do módulo de antes), `tests/test_disp_fracttal.py` (o `kwh_usina`) e
  `tests/test_disponibilidade_mapa_8.py` (o mapa diário e a rolagem da lista por cliente).

## Padrão por inversor (usinas sem visão por string)

Ceilândia 1, Céu Azul e Ouro Branco (String Box com combiner não exposta) e Barretos (sem esperado no
cadastro) não têm régua de strings — ficavam "ok" para sempre. Desde 10/09/2026 vale a régua de **padrão
de proporcionalidade**: `inv_padrao.py` (puro, com teste) aprende nos 30 dias válidos anteriores quanto
cada inversor gera em relação à mediana da usina e alerta a −10 pp (atenção) / −20 pp ou 3 dias seguidos
(crítico). O dado é o `custom_query energy` da API PV (kWh por inversor de qualquer dia), guardado em
`inv_padrao.json`; o worker (`_inv_padrao_loop`, 1×/h) julga o D-1, faz a prévia de hoje após as 14h e
publica via snapshot. Só as plantas de `INV_PADRAO_PLANTAS` — para incluir outra, basta o `plant_id`.
Armadilhas: o dia julgado **não** ensina o próprio baseline; dia com a usina a <25 % do típico não conta
(chuva forte vira ruído); Barretos lista 31/40 "INVERTER" para 20 reais no `plant_devices` — a régua
trabalha por id que reportou energia e traduz pelo cadastro.


## Curva das strings da RenoGrid (SolarEdge, 25/09/2026)

Até 25/09 a RenoGrid não tinha curva: o drill nem pedia ("solaredge: sem curva") e dizia "a usina pode não ter
reportado"; a aba "Curva das strings" dava a fonte por indisponível. O caminho que o Levi mostrou (Análise > gráfico
personalizado do portal) é o `generate-chart` — o MESMO que a tabela já chamava em `se_string_power`, com o login
automático daqui (Cognito, `se_credentials.txt`); nenhum token colado. A tabela fica com o último ponto de cada string;
`se_string_series` guarda o dia. `GET /api/solaredge/curva/<site>?data=&inv=<serial>` devolve o formato da Athon
(`_se_strings_curva`: inversor com o nome do cadastro, string com o nome do chip do drill), em **W**: a SolarEdge dá
potência por string, não corrente (corrente só por otimizador). Um inversor = 1 pedido (~1,3 s medido); a usina
inteira, 1 a cada 50 strings. Dia passado vale (o intervalo é o dia NO FUSO DA USINA — Cuiabá é UTC−4). Conferido em
25/09: o último ponto de cada curva bate com o valor da tabela nas 39 strings testadas, em 6 usinas. **O quarto de
hora em andamento chega parcial** (o das 12:00, recém-aberto, com 0,6–2,7 kW em strings de 13,6 kW; 20 min depois o
das 11:45 subiu de 10,5–13,5 para 13,3–14,9 kW) e sai da curva de hoje. **A tabela também** (`se_string_power`, desde
a tarde de 25/09): o parcial não zerava string nenhuma (0 inativas falsas em 1.017), mas a régua de inversor desligado
(potência < 5% da mediana) caía nele — às 14:48, 3 min depois de abrir o quarto, 21 inversores "desligados" na Colíder
1 e 8 na Colíder 2, contra 0 e 0 com o quarto fechado. A última leitura da RenoGrid fica ~15 min atrás, e é de propósito.
Na tela, `curvaSVG(..., unit)` recebe 'W' na RenoGrid e 'A' nas outras.

## GreenYellow, Sal Energia e Apolo pelo scadaGridco (06/10/2026; Apolo 29/10/2026)

Levi: "OS para tempo real e histórico das UFVs da Green Yellow", "separe green yellow e sal energia", tempo real "igual
às outras fontes", histórico "só até 45 dias" (é o que a API guarda). A fonte é o supervisório da Automação Grid Co.
(`https://app.gridco.com.br/supervisorio`, documento "API do scadaGridco — como puxar os dados"): só GET, cabeçalho
`X-API-Key`, token em `SCADAGRIDCO_URL`/`SCADAGRIDCO_TOKEN` no tokens.txt (nunca no código nem em print; vazou, pedir
troca à Automação). Sem token ou com token errado a API responde **302 para o login**. Tudo da API mora em
`scadagridco.py` (puro, menos o `get()`); o `app.py` tem a linha, o drill e a curva no bloco "scadaGridco".

- **Duas fontes, dois cards na Entrada** (`greenyellow`, `salenergia`; cliente da Info Geral "Greenyellow" e "Sal
  Energia"). Tabela, drill, Curva das strings (hoje e até 45 dias), CSV, rollup do macro e a aba de Falhas. Sem ETM nem
  trackers (as usinas não mandam), sem sino e sem Ocorrências (como a RenoGrid). A Apolo (abaixo) é a 3ª, com a NCU.
- **GreenYellow = gateway MQTT**: tabela/drill por `/api/mqtt/<usina>` (1 pedido, 0,1 s); curva por `/api/telemetria`
  **um inversor por pedido** (`indice=N`: 2,5 MB e 0,5 s; a usina inteira de uma vez são 19 MB e 22 s), 1 ponto por
  minuto. A de hoje vem aos pedaços (`apos_ts`, `CurvasDoDia`), a de dia passado fica 6 h. O histórico é pedido pelo
  NOME do equipamento (`equipamento=`): o `indice` só filtra quem tem nome numérico ("1"), e a Cedro ("inversor-01")
  voltava vazia; na Demerval e na Irecê os dois dão o mesmo.
- **As usinas são descobertas na API** (11/10/2026, Levi: "Na API que está puxando as UFVs da GreenYellow não está
  aparecendo todas as UFVs"): a lista fixa tinha só a Demerval Lobão e a Irecê 2, e o supervisório já lia a Castelo do
  Piauí (16 inversores) e a "Cedro 1 e 2" (20). O worker lê `/api/usinas` e `/api/mqtt` de hora em hora
  (`_sg_descobre_se_preciso`), classifica pelo CLIENTE do Info Geral (outro cliente fica de fora: Santo Inácio XII é
  Thopen, Crateús é RenoGrid, Boa Esperança do Sul é de outro) e grava `sg_usinas_descobertas.json` (o web relê pelo
  mtime, `_sg.ATUALIZAR`). "X 1 e 2" que o cadastro tem como duas usinas vira duas, cada uma com o seu grupo de
  equipamentos: a Cedro 1 e a 2 são `cedro_1`/`cedro_2`, com `scada: "cedro"` (o id da URL). O nome dos inversores vem do
  NOME do equipamento (`inversor-03-12` = 2º grupo, nº 3 → Inversor 2.3; nas Cedro, Inversor 1.3 de cada uma),
  PROVISÓRIO (o histórico delas no supervisório começa em 11/10 e o BD vai até 06/10: sem dia em comum para fechar pelo
  valor) — a tela De-para mostra o aviso e decide. A usina descoberta entra na fonte e espera a liberação nas Fontes do
  tempo real. Balsas 1, Icó 2 e Macaíba 1 ainda não estão no supervisório.
- **Sal Energia = Modbus**: `/api/inversores/<usina>` e `/api/dados/string` (5 min). Em 06/10/2026 as cinco estavam com
  `read_error: TimeoutError` e 0 kW desde pelo menos 17/09 (o supervisório não lê os inversores; o BD_Performance tem
  geração delas): na tela, **sem comunicação**, que é o que elas estão para a fonte. Campos Modbus conferidos na Boa
  Esperança do Sul (`string_NN_i`, `active_power_w`, `daily_energy_kwh`).
- **De-para dos inversores POR VALOR** (`scadagridco.FONTES`): energia do dia do scadaGridco × kWh diário da aba do
  BD_Performance, 27 a 30/09. **Irecê 2: ordem natural desde 01/10** (1 a 10 = 1.1 a 1.10, 10/10 em 01, 05 e 09/10; o de-para de 27 a 30/09, 4 = 1.8 e 7 = 1.4, só batia em setembro). A
  Demerval Lobão tem só a UG 01 (12 de 20, 1 a 12 = 1.1 a 1.12): a linha conta as esperadas dos 12, não as 280. **Sal
  Energia vai pela ORDEM do cadastro, provisório** — fechar por valor quando o supervisório voltar a ler.
- **Esperadas pelo nome de exibição** (`ESPERADO_INV_DISP`, no `load_equipamentos`): essas usinas não têm "Equipamento
  Supervisório" no cadastro, e o `ESPERADO_INV` é por ele. 14 strings por inversor nas duas da GreenYellow; o Huawei manda
  28 entradas, e string acima das esperadas só entra se tiver corrente.
- Regras da Automação que o código segura: **uma chamada por vez** (`scadagridco._LOCK`: o mesmo servidor opera as
  usinas), busca incremental, `communication_fault` 192 = leitura boa (lacuna é sem comunicação, nulo não é zero).
  `data_hora` é hora local (UTC−3), `ts` é epoch. O contador `total_daily_energy` pode amanhecer com o valor da véspera.
- **Aba de Falhas**: `_falhas_sg_varre` (dentro do `_falhas_loop`, de 07h a 18:30 e uma depois) registra a régua nova
  sobre a curva de hoje de cada inversor; usina sem leitura não é perguntada.
- Inversor lendo e sem string ativa (noite) é "desligado" no drill, sem diferença — como na RenoGrid e na Athon.
- **Apolo = 3ª fonte (`apolo`, card "Apolo", 29/10/2026)**. Levi: "As API que tem as mesmas UFVs da GreenYellow também
  soltou Rio do Peixe 1 e 2 que é da Apolo, traga para o tempo real". O mesmo gateway MQTT da GreenYellow; igual a ela em
  tudo (card, tabela, drill, Curva das strings, CSV, rollup, aba de Falhas, relatório Potência ativa, De-para de
  equipamentos, Fontes do tempo real, ponte do Nexus). Cliente "Apolo" na Info Geral → `apolo` (`_SG_FONTE_DO_CLIENTE`):
  usina nova da Apolo que aparecer no supervisório (Ibipeba, Gravatá II e Iramaia II estão no cadastro e ainda não no
  supervisório) entra pela descoberta. Fonte nova nas Fontes do tempo real nasce **não governada** (sem a foto de
  migração): a Rio do Peixe entra direto; para controlar pela tela, tirar a "foto de hoje" da fonte.
- **Rio do Peixe I e II (`rio_do_peixe_1_2`)**: 21 equipamentos `inverter` ("1" a "21", 28 entradas `string_N_current`,
  `active_power` em kW, `daily_active_energy`, temperatura em `temperature_internal`), 3 `relay` (proteção/disjuntor) e
  1 `tracker_ncu`. **Sem estação** (sem POA/GHI). O cadastro (aba Equipamentos, sem "Usina Supervisório", liga pelo nome
  de exibição) tem **20** inversores: 1.1–1.10 (UG 01) e 2.1–2.10 (UG 02), com 20/20/20/18/18/18/18/20/20/20 strings
  (384). O **15 é cópia do 14** (28/10: 315 de 316 minutos com sol iguais em potência e em cada string; 14 × 16, 0). Por
  isso ela fica na **lista fixa** do `scadagridco.FONTES["apolo"]` com o de-para (1–10 = 1.1–1.10, 11–14 = 2.1–2.4, 16–21
  = 2.5–2.10, o 15 de fora): pela ordem do cadastro o 15 virava o 2.5, o 18 (18 strings) o 2.8 (20 esperadas, −2 falso) e
  o 21 ficava sem inversor. **PROVISÓRIO pelo padrão das strings** (nº de entradas com corrente às 13h de 28/10): o
  histórico do supervisório começa em 28/10 11:52 e o BD vai até 21/10, sem dia em comum para fechar pelo valor — fechar
  quando houver. O aviso vai no diagnóstico e no editor do De-para (`provisorio` na usina); o decidido na tela vence. As
  entradas vivas ficam espalhadas pelas 28 (no inversor 1: 2–4, 6–12, 16–18, 21–23, 25–28): as mortas aparecem no drill
  como sem corrente até alguém trancá-las; a conta da linha fecha (ativas × esperadas). O gateway fica **fora de madrugada**
  (29/10 01:10: `online` false, todos `stale` desde 21:48): a linha sai "sem comunicação" à noite.
- **A NCU como tracker** (29/10/2026, Levi: "traga a NCU como tracker também e nomeie como NCU"): `trackers: {"1": "NCU"}`
  na usina; a aba Trackers da Apolo (`/api/apolo/trackers`, o drill `/<pid>` e o gráfico `/<pid>/chart`, montada pelo
  worker, `_apo_trk_cache`) mostra UM tracker "NCU" com o ângulo (`posat`) e o alvo (`posal`) da telemetria
  (`tipo=tracker_ncu`, 1 ponto por minuto, `_sg_trk_curvas`). Régua = a da 2C (`_trk_analise_curvas`, o corpo antigo do
  `_owen_trackers_analise`): parado pela amplitude do dia, depois a freeze-based e o alvo pela mediana capada em ±55°.
  Com um tracker só, a mediana da usina é ele mesmo: **desvio e atraso relativos nunca acendem**; vale o parado e a
  disparidade contra o alvo. As **falhas da NCU** (flh_com, flh_leve, flh_zigbee, out_of_range, bot_emerg, manu_on,
  bat_*) vão no tracker como estão (`alarmes` = as em 1, `falhas_ncu` = todas; no título do chip): a régua é pelo ângulo
  e não tem regra para bandeira — nenhuma foi inventada. Em 28/10 o `flh_com` ficou em 1 o dia todo, com a NCU girando
  (amplitude 66°). NCU sem leitura no dia = sem comunicação (não verde). A Entrada conta os parados SÓ do pacote do worker
  (`_sg_parados_rows`), e só onde há o token. Fora da subaba Parados/Ocorrências (`_TRK_SUB_FONTES`, como SEMP e 2C-API)
  e do registro de ocorrências (`trk_eventos`, `FONTES_TRK`). **Relés e ETM não entram.**
- O **Modo de-para do Tempo real** (`_DP_FONTES`, `depara_tabela.js`) não cobre nenhuma fonte do scadaGridco (lê o
  `inv_resumo` das linhas da API PV); o de-para dos inversores delas é o da Base · De-para de equipamentos
  (`/admin/de-para`, `_DP_SG`), onde a Apolo está.
- Testes: `tests/test_scadagridco.py`, `tests/test_fonte_greenyellow_sal.py`, `tests/test_scadagridco_descoberta.py`.

## Visão Geração no drill-down do Monitoramento

Desde 13/09/2026 a usina expandida na aba Strings tem o seletor **Strings | Geração** (`state.invView`, vale de
usina em usina). Geração = barras de kWh por inversor no período (fichas Ontem / 7 dias / Mês ou de/até, só dias
**fechados**, até 62 dias), desvio contra a **mediana da usina** (por kWh/kWp quando a base traz `pot_kwp`; kWh
puro quando não), participação × esperado e o padrão 30d onde existe. A fonte é `/api/<fonte>/inversores/
historico/<pid>?usina=&mes=` (BD_Thopen p/ cliente Thopen, BD_Performance p/ o resto) — nunca a API ao vivo. A
conta (`_gerAgrega`, `_gerFaixa`) roda no node em `tests/test_monitoramento_geracao_logica.py` com o código
extraído do HTML: mudou a régua, mude o teste. Régua: até −5 % normal, −10 observar, −20 crítico.

## Strings: inversor desligado e OS atribuída — o padrão Athon em todas as abas (24/09/2026)

Inversor **desligado de dia** sai da conta **inteiro — ativas e esperadas** — em toda fonte que tem potência por
inversor: Athon/Axis (desde 22/09), API PV (`build_summary`: Thopen, SEMP, Alves Lima, 2C-API) e Banco
(`_pg_build_snapshot`), desde 24/09 ("quero todos no padrão Athon"). Régua única: `_inv_desligados_por_potencia`
(potência < max(piso, 5 % da mediana dos pares), com sol, com a usina gerando, com leitura). O piso (2 kW) fica limitado a
25 % da mediana quando ela passa dele (`_macro_prod`, 29/09/2026): com céu fechado, o inversor a 1,98 kW com os vizinhos a
3,5–4 kW contava como desligado (Guatambu 4); com sol normal nada muda. A linha leva
`inv_desligados` / `strings_fora` / `inv_desligados_nomes` (a tela mostra "N inv. desligado · M strings fora da
conta" na célula das esperadas e o status "Inversor desligado"; os tickets leem os nomes). No drill, o inversor
continua listado, marcado `desligado` e `fora_da_conta`, com `diferenca` None. Usina inteira parada NÃO tira
ninguém (é "Usina desligada"). De 11/09 a 24/09 a API PV e o Banco faziam o contrário (todas as strings do
desligado contavam como faltantes). **OS atribuída** (`os_atribuidas`, chave `plant_id|idefinversor`) e OS aberta
no Fracttal em inversor desligado continuam tirando o inversor da conta pela OS (`inv_com_os`/`strings_com_os`),
sem virar o aviso de desligado (11/09: "se está desligado e tem OS então está tudo OK"). **Só o desligado, desde
29/09/2026** (Levi: "String PV10 em vermelho ... diferença -1 no inversor e mesmo assim não acusou na linha principal da
usina! É INADMISSÍVEL"): a OS 12093, de recomposição, atribuída ao INVERSOR02 da Rodrigues 2.1 em 25/08, tirava da
linha o inversor INTEIRO, gerando, e a Ipv10 parada nele sumia (43/43, "Normal"; o drill dizia −1). A OS não diz quais
strings cobre: o inversor que gera fica na conta, e a OS vai na linha (`os_na_conta`, no título da diferença). E a
**diferença da usina é a soma das FALTAS de cada inversor** (`_dif_por_inversor`, nas cinco fontes com esperadas por
inversor no cadastro): a sobra de um inversor (cadastro que conta a menos) não paga a falta de outro; esperada que
nenhum inversor na conta explica segue como falta; sem as esperadas de cada um, vale a conta pelo total. A sobra vai
em `strings_acima_cadastro`. Teste: `tests/test_diferenca_por_inversor.py`. **O macro e a Entrada usam o mesmo número**
(29/09 à tarde): `_macro_dif` lê a `diferenca` da linha (ativas − esperadas só sem ela) — a Poconé 1 tinha −6 na tabela e
"ok" no macro —, e a Entrada lê o `strings_faltando` já silenciado do macro, não a diferença crua, que contava a usina em
pouca luz ou sem sol (medido no PC às 12:38: 580 strings "faltando" no card da API PV contra 177). As duas fontes SEM
potência por inversor usam a medida das strings dele, somada: RenoGrid/SolarEdge (`_se_fora_da_conta`: potência DC
= soma dos W das strings). A 2C do e-mail fazia o mesmo pela soma das correntes até 03/10/2026; hoje a 2C é API PV.

**Inversor SEM LEITURA HOJE também é desligado (25/09/2026)**, com os outros da usina gerando e com sol — Levi: "o
inversor 1.3 de Colorado 2 está desligado, a plataforma não conta como desligado". O 3º portão da régua ("sem leitura
não é desligado") tem uma exceção, o `sem_leitura` de `_inv_desligados_por_potencia`, e cada fonte diz o que é "nada
hoje": API PV = inversor do cadastro fora do `day_inverter`, só se a conta fecha pelo nome (`build_summary`); SunOp =
nenhuma corrente numérica, ou só de outro dia, e a potência de outro dia não vale (`_sunop_regua_hoje`, a mesma na linha
e no drill); Banco = última leitura de outro dia (a tabela guarda 30 dias); SolarEdge = todas as strings dele
**devolvidas sem potência** — string AUSENTE da resposta é throttling (200 vazio) ou lote falho e não vale; a 2C do e-mail
(até 03/10/2026) usava o inversor do cadastro fora do e-mail do dia. Usina inteira sem leitura continua
sendo "sem comunicação" da usina (TIM100 em 25/09: os 50 com a última leitura de 24/09 06:23 — ninguém vira desligado).
Medido em 25/09 com os mesmos dados, antiga × nova: RenoGrid mudou 3 de 7 (Crateus 75/362 −287 → 75/75, 40 desligados
das cabines 1 a 4; Xavantina 2 −13 → +3, porque o cadastro diz 6 e 7 esperadas nos inversores 3.4 e 3.5, que têm 8
strings ativas; Elias Fausto −6 → 0), Banco 0 de 22, 2C do e-mail 0 de 4, Athon 0 de 10. O drill do Banco
recalculava a diferença de todo inversor e devolvia "−4" ao que estava fora da conta — agora fica None.

**Colunas da tabela de strings (25/09/2026, pedidos do Levi).** Abre pelo **Status**, antes da Usina ("quero a coluna
de STATUS antes do nome da USINA"), e **não tem mais a Disponib.** ("pode tirar a coluna de disponibilidade das strings
em tempo real"): era ativas ÷ esperadas em %, a Diferença dita de outro jeito, e passava de 100% com o cadastro errado.
É um componente só para as 11 fontes; as linhas de largura toda têm 9 colunas. Teste:
`tests/test_strings_sem_coluna_disponibilidade.py`. A Disponibilidade da tabela de TRACKERS é outra (por tempo) e fica.

**Colunas de strings são sempre strings.** As 13 usinas da régua de padrão (`inv_padrao`) punham "18/20 inv.",
"padrão 30d", "no padrão" e "2 crônicos" nas colunas; desde 24/09 ativas/esperadas/diferença
saem em '—' sem visão por string, e a proporcionalidade vai para o aviso da célula das esperadas
(`_strNotaPadrao`, roda no node). Com visão (Ouro Branco), valem as strings, e o padrão de ontem só vira status
quando as strings de agora não têm nada a dizer. O `gerencial.html` é tema escuro por padrão só por tokens
(`:root[data-theme="dark"]`); é Jinja — mudança nele exige restart do web.

## Usina calada: desligada ou sem comunicação, e o relógio do registrador (28/09/2026)

**A API não diz se a usina está desligada**, e calada é calada: a Ceilândia 1.1 gerava 1,4 MW às 08:10 de 28/09 e o
dado parou ali. A usina calada (sem dado, `falha_comunicacao` ou leitura com mais de 2 h) só vira **"Usina
desligada"** com MOTIVO, nesta ordem (`_usina_desligada_de`):

1. a **marcação do analista**, com a observação (drill da usina → "Marcar como desligada"; estado
   `usinas_desligadas`, chave = plant_id, rotas `/api/state/usina-desligada` e `/usina-religada`). Some sozinha quando
   a usina volta a gerar (`_usina_gerando`) — marca velha faria a próxima queda de comunicação parecer desligamento;
2. **OS de Religamento aberta na usina inteira** no índice de disponibilidade (`_religamentos_abertos_usina`, casa pelo
   `_macro_usina_nome`). De cabine ou inversor não desliga a usina; e só vale para quem está calado — a Ceilândia 2
   tinha a #14710 aberta e gerava;
3. **estação comunicando com os inversores calados há mais de 2 h** (`_etm_leitura_por_pid`, das análises de ETM em
   cache). Menos que isso pode ser o barramento dos inversores.

Sem motivo, segue "sem comunicação". Aplicado na saída das 11 tabelas de strings (`_com_usina_desligada`, dentro do
`_servir_tabela_strings`) e no rollup (`_portfolio_rollup` → status `desligada`), então a Entrada conta
`usinas_desligadas` à parte e tira as strings delas da conta. A tela mostra a observação embaixo do nome, como o aviso
do inversor desligado.

**Relógio do registrador em outro fuso.** A API devolve o carimbo do REGISTRADOR (`dataleitura` é só a data). O da
Diamantino 1 e 2 está no horário de Cuiabá: dado minuto a minuto sempre 62–63 min "atrás", e a régua dos 30 min dizia
"sem comunicação" o dia inteiro — as únicas 2 das 153 (medido em 28/09). O fuso é do registrador, não do estado (a
Canarana, também no MT, manda em horário de Brasília), então `_pv_relogio_corrige` **aprende** por usina: defasagem de
horas cheias (± 12 min) repetida com o carimbo ANDANDO = relógio; usina parada não anda e não confirma; até 15 min de
defasagem zera. O confirmado persiste em `pv_relogio.json` (estado, `_p_dado`). Vale para a linha (`build_summary`) e
para a série da estação (`_analisa_etm_plant`). As curvas do drill ainda saem no horário do registrador.

Testes: `tests/test_usina_desligada_e_relogio.py`.

**Pouca luz não é usina desligada (29/09/2026**, Levi: "0 strings ativas, usina desligada!"). A régua de dado fresco
("nenhuma string com corrente" = desligada, de 23/09) chamava de desligada a usina que gera pouco: às 08:42, Diamantino 1 e
2 com a estação a 3,5–16 W/m² e os inversores a 0,4–0,9 kW; Guatambu 2, 3 e 4 a 2–4,4 kW por inversor, strings a
0,2–0,49 A. A régua de string põe o inversor com mediana abaixo de 0,5 A como "inativo" ("noite/nublado"), e a rampa (corrente
real, baixa) só existia para String Box. Agora `_pouca_luz_de`: nenhuma string ativa **e** uma prova de que a usina gera —
a mediana dos inversores ≥ 2 kW (`potencia`) ou a estação da usina, fresca (90 min, carimbo cru), abaixo de 100 W/m²
(`estacao`, de `_poa_atual_por_pid`, das tabelas de ETM em cache) — marca `rampa` e `pouca_luz` ({por, texto}) na saída
(`_com_pouca_luz`, dentro do `_servir_tabela_strings`, tirando a linha do card "Sem geração") e no rollup, antes da
macro. Sem prova continua "Usina desligada": inversor desligado pode mostrar 0,3 kW com 0,9 A de ruído, então potência
baixa sozinha não prova. Na tela: "Baixa irradiância" com a prova embaixo do nome, colunas neutras, sem pulsar; com um
inversor desligado de verdade, "Inversor desligado" com o aviso (a macro diz crítico). A macro não chama a linha de
`sem_producao`. No drill da API PV, com a usina em pouca luz, o inversor só é desligado pela régua da linha e os outros
ficam neutros (antes os 10 da Diamantino saíam desligados). A SunOp leva `pot_inv_med` (o `pot_med` dela é o total).
SolarEdge não tem potência na linha e fica como estava (a 2C do e-mail também não tinha; saiu em 03/10/2026). Teste: `tests/test_pouca_luz_nao_e_desligada.py`.

## Tickets de strings na tabela (23/09/2026)

A tabela de strings tem a coluna **Tickets**: strings com ticket ABERTO na aba **"Strings indisp"** (sheet 128) da
planilha de tickets, a mesma que a tela de Tickets do OS Creator lê e grava, contra as que faltam agora. No drill, o
inversor ganha a etiqueta azul "ticket", a vermelha "N sem ticket" ou a verde "voltou", e o chip da string ganha um
ícone. `load_tickets_strings` → `TICKETS_STR`, anexado na saída das 11 rotas por `_com_tickets_str`, dentro de
`_servir_tabela_strings`. A aba é diferente da de trackers, e cada regra vem disso:
- **uma linha por ticket de INVERSOR, com a quantidade**. QUAL string só aparece nos comentários ("Ipv11 e Ipv12 com
  corrente nula", texto do ticket que nasce de OS). Em 23/09, 19 dos 82 abertos diziam quais. Ticket que não diz a
  string só marca as zeradas do inversor como cobertas quando a quantidade dele alcança todas.
- a coluna Usina mistura nome e **código** (ALT100). O de-para é a própria planilha, aba "Base de dados - Usinas".
- "X 1 e 2" vai para a parte certa pelo 1º número do inversor. Um ticket sem inversor ("Todos") é da usina inteira e,
  em cada parte, conta até as esperadas dela (Brodowski: um ticket de 209 em duas linhas).
- a posição da linha no espelho `bases/` **é** o `row_number` da API (o `bd_api` grava cada linha na posição
  original; conferido em 82 de 82). É esse número que o "Finalizar ticket" usa.

**Finalizar pela tela (23/09/2026).** Ao abrir o inversor, cada ticket dele vira um card (o da usina inteira e o de
inversor que a fonte não mostra ficam no alto da usina) com "Finalizar ticket", que grava o Fim na base de tickets.
Quem grava é a **plataforma**, pelo relay (`tickets_relay.encaminhar`: token daqui, abas liberadas, log), com as regras
do Salvar do OS Creator web em `tickets_str_fechar.py` (puro, com teste): relê a linha na API, confere usina + inversor
+ início, manda a LINHA INTEIRA no PUT e registra o retrato no **diário v3** (sheet 399) — é o diário que segura o
ticket fechado se alguém subir o Excel, e é onde moram a OS e o Status do ticket. O contrato do diário é do oem; o
teste `test_contrato_do_diario_bate_com_o_oem` compara os dois onde o clone existe. O leitor aplica o diário por cima
(mesma régua do OS Creator), e a coluna mostra **"N para fechar"** quando a linha tem todas as esperadas produzindo e
ainda há ticket aberto (`normalizado`, em `_com_tickets_str`). Duas armadilhas que só o dado real mostrou:
- a aba do diário chega ao espelho **sem cabeçalho** (a API devolve o 1º registro com row_number 1, a linha do
  cabeçalho, e o `bd_api` só escreve cabeçalho em linha livre): ler por posição com `_tkf.COLUNAS`;
- coluna de data do espelho é data de verdade, e a célula vazia chega como **NaT** — `str(NaT)` é "NaT", que o `_tk_s`
  não trata como vazio. Use `_tk_vazio`. Sem isso o leitor deu os 82 abertos por fechados.

**Causa, status e a OS de recomposição no card (23/09/2026, pedidos do Levi).** Causa raiz e Status do ticket são
escolhas de lista (`tickets_str_fechar.CAUSAS`/`STATUS`, as mesmas `TK_CAUSAS`/`TK_STATUS` da tela; o gravador recusa
outro valor, menos o que a linha já tem) e há **Salvar** sem fechar. **Nunca finaliza sem causa raiz** (tela trava,
servidor recusa). Finalizar grava o status "Concluído". Status do ticket não tem coluna: salvar só ele vai só ao
diário. O bloco **Observação** mostra a última OS de recomposição do inversor (`GET /api/strings/tickets/<linha>/os`
→ `_tk_str_ultima_recomposicao`: descrição com "recomposi"/"string", sem cancelada, conclusão = maior `final_date`
das tarefas em hora local, relato = `note` quando difere da `task_note`), e o Fim já vem sugerido por ela — só se a
OS não for anterior ao ticket. O inversor se acha no Fracttal pelo **código** da usina (`t["cod"]`): o que a planilha
escreveu (MTS200) ou, quando ela escreveu o nome ("Boa Esperança do Sul 1 e 2"), o da aba "Base de dados - Usinas".

**Quantidade e o card enxuto (23/09/2026, pedidos do Levi).** A quantidade de strings afetadas é um contador no card
(mínimo 1, teto 999, os mesmos do OS Creator). O nome real da coluna é **"Quantidade de strings no afetadas"**, com o
"no" que sobrou (`tickets_str_fechar.QTD`). Ela vai **só para a planilha**: o diário do OS Creator não tem esse campo,
então um sync do Excel pode desfazê-la. A coluna vale sobre o texto (`_tk_str_qtd`); as strings citadas só contam
com ela vazia. Até 23/09 valia o maior dos dois, e o card não conseguiria baixar a quantidade. O contador edita o
TOTAL do ticket (`qtd`), nunca a parte da usina (`qtd_na_linha`). O card não tem borda lateral colorida nem linha de
aviso: o porquê do Finalizar travado é dica no mouse, e o "como grava" fica no "?" do canto.

**Cadeado de string (23/09/2026).** Para a string trancada o servidor manda status "trancada" (`_classifica_strings`)
e o status real some do payload. Por isso **destrancar recalcula na tela** com a mesma régua (`_strReclassifica`:
mediana das que produzem, 0,1 A, 60%, inversor parado abaixo de 0,5 A, e "desligado" se a linha do inversor está
desligada) e busca a curva de novo (`_curvaRecarrega`), porque o servidor serve a curva sem as trancadas. Os limites
estão repetidos na página e travados contra o `app.py` em `tests/test_strings_destrancar_tela.py` (paridade Python ×
JS nas mesmas correntes). Trancar não precisa de conta: "trancada" vale qualquer que seja o status.

**Todas as fontes (24/09/2026, "implemente para os demais").** Coluna, card, OS de recomposição, quantidade e cadeado
já são o mesmo código nas 9 fontes: medido nas que tinham ticket (Thopen API PV, Thopen Banco, Athon, RenoGrid), todo
ticket de inversor casou com um inversor do drill e a OS se achou no Fracttal. O que faltava era casar a USINA: o
ticket que nenhuma linha acha pelo nome vai pelo **código** (`_tk_str_achados` + `TICKETS_STR_COD`), só para a linha
cujo código é **único** na tabela — Altair 1 a 5 dividem ALT100 e ali vale o nome + o 1º número do inversor. O código
da linha vem do de-para mestre, a aba "Info Geral" do BD_Performance (`USINA_COD`), que estava **vazio desde 30/07**:
uma linha inserida acima do cabeçalho, e o `load_usina_codigos` lia a 1ª linha e saía calado. Agora ele acha o
cabeçalho (142 códigos). Antiga × nova em 24/09: só Canarana 1 (+2, CNN100) e Araçoiaba da Serra 1 (+1, ADS100)
mudaram; as OS da planilha por usina não mudaram em nenhuma; a análise da ronda do WhatsApp volta a reconhecer usina
por código e descrição (142 → +332 nomes). Fora, e por quê: Castelo do Piauí (GreenYellow, sem fonte de strings),
Petrolina 2 (nome que não está no Info Geral nem na aba de usinas; a Axis chama de PEII/PEIII) e o TESTE100.

**Thopen API PV: Fracttal flexível e julgamento pela geração (24/09/2026, respostas do Levi à lista de dificuldades).**
- O code do inversor no Fracttal às vezes leva o prefixo do cliente e às vezes não: ALT100-INVR1.8, CTS100-INVR1.1 e
  MTS100-INVR6.2 existem sem; THPN-CNN100-INVR1.1, THPN-APR100-INVR1.10 e THPN-EBG100-INVR2.2 só com (conferido lá).
  `_frac_ativo` tenta o code como veio e, se não existir, com o prefixo da usina (`USINA_PREFIXO_FRAC`, da aba de
  usinas da planilha de tickets) e o da Thopen; o achado fica no cache do code sem prefixo. Vale para todo mundo que
  resolve ativo (card do ticket, OS no drill, ETM). A PV Operation divide por cabine usinas que no Fracttal são uma
  só (Embu Guaçu 1 e 2 = EBG100, "Inversor 2.2" = inversor 2 da cabine 2; Altair também).
- Inversor **sem visão por string** (a usina toda ou só ele) tem o ticket julgado pela **geração**: a linha da API PV
  (`build_summary`) leva `inv_sem_visao` e `ger_inv` = potência por string esperada ÷ mediana dos pares
  (`_pv_ger_relativa`), e `_tk_str_pela_geracao` decide: com N de S strings paradas ele geraria ~(S−N)/S; voltou é
  passar do meio. Perda < 6% (1 em 17+) não dá para ver, e a régua diz isso. O card mostra "Geração normal agora ·
  99% dos pares" / "abaixo dos pares · 84% (com 2 de 12 paradas seria ~83%)". Antes, o ticket de um inversor sem
  visão numa usina com as outras normais era dado por fechado pela conta das outras. Em 24/09 eram 10 linhas inteiras
  sem visão e nenhuma com ticket. A Altair é String Box e TEM visão de dia; o "sem visão" dela era da madrugada.
- Usina inteira **fecha por parte** (Levi: "Brodowski fecha por parte"): cada linha julga pelas strings dela, e o
  ticket leva `outras_partes` para o card avisar a parte que ainda não está — finalizar fecha a linha única da planilha.
- Código de **várias** linhas (as partes: Cipó-Guaçu 1/2/3 = CGU100 no Info Geral) manda o órfão para a parte do 1º
  número do inversor (`_tk_str_parte`; "Ceilandia 1.2" não diz a parte e não recebe nada). O ticket 315 (CGU100 ·
  Inversor 1.1) é da Cipó-Guaçu 1 — o Levi achou que era a Cidade Gaúcha (CGH100); o Info Geral e o ativo da OS diziam
  Cipó Guaçu, e ele confirmou. A Cipó-Guaçu não tem nome de inversor no cadastro (o drill mostra "INV-368336").
- **API PV lenta congela a tabela**: com a API a ~48 s por usina (24/09) a 1ª passada do `fetch_all` desistia em 45 s e
  tudo caía na 3ª, sequencial — ciclo de ~2 h. `PV_TIMEOUT_1A_PASSADA = 90`.

**Thopen Banco de Dados (24/09/2026, itens 2 e 3 do Levi).** A aba lê do banco e o drill responde na hora; os 9 tickets
acharam o inversor e 8 a OS. Duas regras novas no card, que valem em toda aba:
- **OS concluída com a string ainda morta não sugere o Fim** (estado 'morta'): na Santarém 1 a OS 9420 foi concluída
  em 14/07 e a string 1 segue sem corrente — o card punha 14/07 no Fim. Agora fica a hora atual, e o bloco da OS diz
  "mas a string não voltou" (ou "a geração", no inversor sem visão).
- **"usar N · zeradas agora"** ao lado do contador (`_tkQtdSug`): quantidade do ticket + as zeradas do inversor que
  nenhum ticket cobre (o `tkSemN` do drill). Só em ticket que não diz as strings. Armadilha de CSS que a foto pegou:
  a regra dos botões − e + tem de ser `.gc-tkc-qt .cx button` — sem o `.cx`, ela dava 30 px ao "usar N" e o texto
  centralizado ficava por cima de "string".
Os tickets repetidos da Santarém 1 (166/171, 213/214, 168/170) a equipe fecha na planilha.

## ETM: o que alarma

Régua do Levi (10/09/2026): **só IPOA (POA) e GHI medidos em zero com sol alarmam** — hoje (`_diagnostico_etm`,
janela 9–15h) ou no mês (`_etm_problemas_build`, BD_Performance). POA-RI é aviso (`info`), sensor que não
reportou nada é nota cinza (`nota`, não severidade — as AIML da Athon não têm GHI), sem comunicação é violeta.
Cada flag leva `sensor` (POA/GHI/POARI/COM) e o diagnóstico devolve `sensores` por estação. O item do mês tem
`alarme`/`alarmes`/`avisos` (+ `problemas` = tudo, compat); a Entrada conta só alarmes em `etm_problema` e os
avisos em `etm_atencao`. Na tela o card tem UMA cor (borda esquerda + ponto do veredito): nada de anel, sombra
ou brilho com outro significado — OS aberta é chip laranja no rodapé. Gotcha: a análise de ETM da SunOp é tarefa
de CURVA e fica pausada à noite; mudança de régua só aparece nos cards da Athon/Axis no ciclo da manhã (a tela
tem fallback para linhas do snapshot antigo sem `sensor`/`sensores`).

## Histórico por inversor: base por CLIENTE e drill-down do dia

Desde 11/09/2026 a base do histórico/energia por inversor (`/api/<fonte>/inversores/historico` e `energia-mes`)
é escolhida pelo **cliente**, não pela fonte: usina Thopen (fonte `pg`, carteira do 5080 ou cliente 'Thopen' na
Info Geral — `_inv_usina_thopen`) lê a aba diária do **BD_Thopen** primeiro, BD_Performance de reserva; as
demais só BD_Performance (`_inv_dias_por_base`). Colorado 2, Barretos, Ceilândia, Ouro Branco… são API PV e
caíam no BD_Performance, que não tem aba por inversor para elas. Sub-usina sem aba própria cai na da usina
**física** filtrada pelo bloco (`Barretos 2` → aba `Barretos`, só os `Inversor 2.x`). No Diagnóstico v2 a linha
do dia do "Histórico do mês" abre um drill-down com a curva daquele dia (mesmos endpoints da aba Curvas; ETM da
fonte para POA/GHI/POA-RI; `temp`/`pac` do inversor só na API PV e só HOJE — `_spv_analise_inversor`), séries
ligáveis por chip; a coluna **% disp** refaz no front a régua do Gerencial (`disponibilidade.py`: só Religamento,
Religamento Remoto e Corretiva Emergencial, janela solar 06–18h, OS aberta conta até agora, evento depois do fim usa a
`criada_ts`; dia antes de outubro sai "—", porque setembro para trás é a disponibilidade da USINA no BD_Thopen; cabine fica
só no Gerencial) com as OS já carregadas do Fracttal (`OSALL`/`OSSITE`). Teste no node: `tests/test_painel_v2_disp_dia.py`. Gotcha: a API PV só
entrega ETM intradiária do dia atual (dia passado → `sem_historico`) — o drill-down diz isso em vez de esconder.
Na aba Curvas, de madrugada o card recua UMA vez para ontem quando hoje ainda não tem curva (`_icRecuou`).

## Seletor do Histórico PR (Painel NOC, 28/09/2026)

Ana: "córrego de sapucaia não aparece na parte do painel - histórico". O seletor do Thopen mostrava só Full O&M, casando o
nome da carteira do banco com o do cadastro pelo `_nrm` (não tira acento): 38 das 116 sumiam sem aviso, 6 delas Full O&M
por grafia (Córrego × Corrego, Marajoara 1 × Marajoara I, Piracicaba 1 × I, Santo Antonio da × do Platina, Primavera e
Nova Londrina = as partes 1 e 2). Agora `_usina_chave_solta` (sem acento, romano como número, sem da/do/de/e) e
`_g_th_usinas_grupos` devolvem (Full O&M, outras com o motivo); `/api/g/usinas?grupos=1` alimenta dois `<optgroup>` — "Full
O&M" e "Sem Full O&M no cadastro", o motivo no título —, e a lista simples, sem `grupos`, traz todas. Usina dividida no
cadastro só é Full O&M se todas as partes forem, e parte se acha pelo nome de EXIBIÇÃO (a chave do supervisório traz o
id: "Primavera 1 (115)"). Cliente de fora do banco: as da Info Geral sem aba no BD_Performance entram como "Sem aba no
BD_Performance". **Gráfico vazio diz o porquê** (`motivo` do `/api/g/mensal`, em âmbar no subtítulo): 16 das 116 não têm
PR — 15 sem um dia no BD_Thopen (Delmiro Gouvea 1 a 4…) e a Guatambu, com geração desde julho e IPOA 0,0 em todos os dias.
Lyon e Pharma II a IV têm meta de PR 0 em setembro (cadastro vazio gravado como zero). Teste:
`tests/test_hist_seletor_e_uniao.py`.

## Alves Lima (Morada Nova) no tempo real (19/10/2026)

Levi: "inclua a usina morada nova cliente Alves Lima no tempo real!". A fonte `alveslima` (conta oem@, `PV_FONTES`
18766373) tinha a aba no Monitoramento desde 19/08, mas saiu dos cards da Entrada em 25/09 e **nunca esteve no
`_portfolio_rollup`** — por isso, mesmo com o card na lista, ele nasceria vazio, e o Painel NOC não a via. Agora, como a
SEMP: card ("Alves Lima", "Alves Lima", "alveslima") logo depois da SEMP em `_ENTRADA_GRUPOS`; `add("Alves Lima", r)` no
rollup lendo SÓ o `_alveslima_cache`; "Alves Lima" → "alveslima" no `_ROLLUP_COB_FONTE` (a decisão vigente nas Fontes do
tempo real é "incluir" desde a foto de 11/10); `'Alves Lima':'pv'` no `FMAP` do Painel NOC, para o drill. O cliente do
card sai da Info Geral (Morada Nova = "Alves Lima", Ceará). **Acoplamento:** o `FONTE_DO_DIAGNOSTICO` de
`nexus/static/porta.js` é cópia do `FMAP` — mudou um, muda o outro (sem a entrada, a Morada Nova some do seletor do
Diagnóstico do Nexus). O `KEYPFX` do Painel NOC ganhou "SEMP" → "semp" e "Alves Lima" → "al" (o prefixo da aba no
Monitoramento): sem ele o comentário publicado no drawer saía calado. **O Diagnóstico das usinas da oem@ pede o PR do dia
com o token da conta que as enxerga** (`_pv_token_for` em `/api/pv/pr/<id>` e na correlação `pv`): até aqui ia o da
principal e, no servidor às 23h de 19/10, Tucano e Araputanga voltavam "Invalid id" (502, "PR do dia não respondeu").
Sem tracker na usina, o quadro de Trackers do card diz "sem leitura", como na RenoGrid. Teste:
`tests/test_alveslima_tempo_real.py` e `tests/test_entrada_so_os_cards_escolhidos.py`.

## Fonte `2capi`: as três usinas da 2C pela API PV

Desde 11/09/2026 Araputanga (18771898), "Sete Lagoa" (18771901 — singular na API, "Sete Lagoas" no cadastro) e Tupi
Paulista (18750925) entram pela conta oem@ da API PV como fonte `2capi` ("2C · API PV"): strings ao vivo, ETM
completa, curva, Diagnóstico v2. É o padrão SEMP/Alves Lima (`PV_FONTES` + bloco da fonte), com três coisas próprias:
fonte explícita filtra por **id**, não pelo `FULL_OM` (`_pv_plantas_da_fonte` — o FULL_OM é por nome de supervisório
e "Sete Lagoa" não está lá); `PV_NOME_API_ALIAS` traduz o nome da API para o do cadastro em `nome_usina`; e
`PV_INV_NOMES` dá o nome do inversor (a conta oem@ não devolve nome e as abas da 2C não têm linha no Equipamentos) —
de-para fechado **por valor** contra o kWh diário do BD, nunca pela ordem dos ids. **A API renomeia planta** (a Tucano em
26/08; em 11/10/2026 "Santa Cecilia 1/2/3" viraram "Ipixuna do Pará 1/2/3" e "MORADA NOVA" virou "Morada Nova", e as
duas usinas ficaram SEM esperadas — string morta não acusava — e a Ipixuna deixou de juntar as três UGs): o
`get_plants` passa a lista por `_pv_nome_do_cadastro`, que põe o nome do cadastro pelo ID (`PV_NOME_POR_ID`) e guarda o
da API em `nome_api`. A Morada Nova ganhou o de-para por valor do coletor no `PV_INV_NOMES` (a ordem errava 6 de 8) e o
id novo do INVERSOR08 (388164 → 402513). A tela De-para de equipamentos (seção acima) mostra e decide cada ponte; a
decisão dela vence a constante.

**O e-mail saiu do Tempo Real (29/09/2026, à noite**, Levi: "Ipixuna do Pará passar a puxar da API PV matando de vez o
e-mail no tempo real!"). A Ipixuna do Pará entrou na conta oem@ como **três plantas, uma por UG** — Santa Cecilia 1
(18771915, UG 01, 8 inversores), 2 (18771929) e 3 (18771930), 6 cada, 6.918 kWp somadas, o total do cadastro. O
Equipamentos já as liga à "Ipixuna do Pará" pela Usina Supervisório (nomes "INVERSOR0 1.1"… na UG 01, "INVERSOR01"… nas
outras), e o `USINA_GRUPO` as junta no macro como fatias somadas. De-para dos 20 inversores **por valor**: Eday × coluna
do BD em 26, 27 e 28/09, ao centésimo de kWh; a UG 01 pula os ids 400841 e 400842 (o coletor, em outra sessão, fechou o
mesmo em 6 dias). A estação é UMA, repetida nas três plantas: POA em −1 (o piranômetro inclinado não mede, como no
e-mail) e GHI no `piraGHI1`. Tabela de strings, ETM, aba de trackers, macro e sino da 2C leem **só a API**
(`_2c_linhas_api`); sem o cache da API a aba fica vazia, sem reserva do e-mail. O sino lia as duas portas e avisava
ARA/STL/TUP em dobro. Teste: `tests/test_2c_tempo_real_unificado.py` (inclui um que confere o de-para contra a grafia
do cadastro — se o Equipamentos mudar "INVERSOR0 1.1", o inversor perde nome e esperada sem erro nenhum).

**Trackers da 2C pela API com o nome do e-mail (30/09/2026).** O e-mail, os tickets e o registro (`trk_eventos`,
chaveado por ARA/STL/TUP/IPX) chamam o tracker de "Tracker 2.10"; a API, de "TRK10" da planta da UG. O de-para foi
fechado **pela curva** em 28/09 (posição de cada tracker do e-mail × cada um da API, minuto a minuto): os 340 pares da
regra `_2C_TRK_FAIXAS` com diferença média ≤ 0,5° e os PARADOS no mesmo ângulo, a prova que falta a eles (curva reta casa
com qualquer reta — os cinco da Ipixuna caíam todos no TRK24). O prefixo não é a UG: na Ipixuna o grupo 2 atravessa a UG
02 e a UG 03. `_owen_trackers_build` passa a montar o dia pela API (`_2c_trk_build_api`, com o alvo da 2C, `com_alvo` do
`_pv_trk_parse_dia` — o alvo dela é o do e-mail; o da Thopen é furado e não é guardado), e tudo que lia o e-mail segue
com as mesmas chaves: aba (a Ipixuna é UMA usina, 122 trackers), parados da Entrada e da ronda, frota parada,
ocorrências, disponibilidade, App de Campo e a curva que o gêmeo lê. Dia anterior a `_2C_TRK_API_DESDE` (30/09) segue o
histórico do e-mail. A União não está no e-mail nem no de-para: segue pela API com os nomes dela. Equivalência com as
duas fontes na mesma análise, 28/09 cortado às 12:00: os mesmos parados nas quatro usinas; o dia inteiro dá 61 × 6 na
Ipixuna porque o e-mail repete o último valor de 17:19 a 17:59 e a API para às 17:17 — os 6 são os travados em 0° nas
duas. Os parados passaram a levar o `ticket_status` (antes a linha ia com `na_planilha=False`), e a API fora de dia vira
`errout` (a Entrada mostra "de tal hora"), não zero parados. **Desde 03/10/2026 o e-mail saiu do código** (Levi: "agora
está tudo via API do PV Operation"): a aba de falhas, a correlação e a curva por código leem a API PV
pelo `_2c_strings_dia_api`, com as chaves do antigo acervo (código, inversor "U.N", string k = Ipvk) — o que já foi
gravado com elas continua casando; API fora levanta erro (dia com buraco não é guardado). Saíram o `_owen_loop`, o
acumulador (`owen_accum.json`), o `_hist_build`, a página Histórico 2C e as rotas `/api/2c/*`; os trackers de dia
anterior a 30/09 também vêm da API. Em 04/10 saiu o resto: a tarefa do Gmail no PC ("2C - Baixar E-mails
GridCo") foi desligada e o coletor de geração (`coleta API PV`) não usa mais o e-mail nem de reserva.
**Conferido com o e-mail em 04/10**: em 02/10, as mesmas strings mortas e vivas nas 4 usinas (régua
da aba de falhas: 0 × 0 mortas, vivas por inversor 60 de 60); o valor do e-mail é a média dos 5 min anteriores da API
(erro mediano 0,7% Araputanga, 1,2% Tupi, 1,7% Sete Lagoa; Ipixuna 4,2%, o e-mail dela carimba 3 min depois, :03/:08).
As 208 séries "só no e-mail" eram trancadas (o leitor da API já as tira; as da Ipixuna estão só com a chave IPX| e a
régua tira depois). Em 22/09 o e-mail dava 17 strings do inversor 2.2 da Tupi mortas das 08:20 às 10:20 — 0,0 A cravado
no inversor inteiro, buraco do SCADA; a API tem 1–3 A subindo com a manhã. **A Tupi Paulista vai por inversor no dia
passado**: o `custom_query` da usina inteira (20 inversores) responde `400 "Resposta grande demais"`, e o
`_spv_day_records_por_inversor` pede um por vez (ids do `PV_INV_NOMES`, `idefinversor` carimbado: o registro por inversor
vem sem ele). Custa ~25 consultas da cota histórica por dia passado da 2C, por isso o achado de cada dia fechado da aba de
falhas fica em disco (`_FALHAS_2C_PATH`, `falhas_job._cache_2c_*`, marca das travas por sha1 — o `hash()` muda a cada
processo): antes vivia na memória do worker e cada deploy pediria o mês inteiro de novo. Teste:
`tests/test_2c_dia_passado_custo.py`. **O dia fica quente no worker** (`_2c_trk_loop`, de 6 h às 19 h): frio, os parados da 2C levam 51 s (o dia
inteiro de 6 plantas, 8 a 64 MB cada) e quente 5 s, e a Entrada dá 30 s por fonte — o dia vence de 30 em 30 min, no passo
dela, e logo depois do deploy o card saiu "de tal hora". O laço renova 2 min antes de vencer, sem apagar o dia
(`_2c_trk_vence`: se a busca falha, fica o de antes), e dia ainda vazio espera 5 min antes de pedir de novo. **A aba de
trackers da 2C é montada no worker** (`_build_2c_trk_payload` → `_2c_trk_cache`, no snapshot como `2c_trk`, com o drill de
cada usina em `por_codigo`): às 14:42 de 30/09 a Entrada abriu a aba e a tela desistiu aos 90 s — no web o dia estava frio
e a União montava as 7 plantas da `2capi` para usar uma (agora só ela, `_pv_trackers_analise`). A disponibilidade da aba
é recalculada no máximo a cada 30 min (`_2C_DISP_A_CADA_S`): recalcular refaz as ocorrências e grava o `trk_eventos.json`
inteiro (26 MB, no OneDrive). **No web a aba nunca é montada** (`api_owen_trackers`): sem pacote responde `carregando`
(a tela repete em 6 s) e o Atualizar serve o último pacote — às 15:07 de 30/09, antes do 1º pacote do worker, o web
montou sozinho em 104 s e publicou ARA, IPX, STL e TUP com 0 trackers; dia vazio da API também não entra mais no memo
do `_2c_trk_build_api`. **Os parados da 2C sem `force` saem do pacote** (`_2c_trk_analises_publicadas`: o `por_codigo`
de hoje, com até 30 min): a régua de parado sobre o dia inteiro da API leva de 25 a 45 s (39,5 s e 44,6 s seguidas no
servidor) e o card da 2C na Entrada ficou "de 14:48" a tarde inteira. Conferido valor a valor com dado real: os mesmos
9 parados, campo a campo, em 0,01 s contra 58,6 s. A ronda (`force`) refaz com a leitura de agora. **A Curva das
strings da 2C é a da API PV** quando o id é numérico (`_ehApiPv` no `loadCurvaView`, e o CSV em `_strings_curva_longo`):
a rota do e-mail só conhece ARA/STL/TUP/IPX e dava "Sem curva de strings" nas 7 usinas; a SEMP nem tinha ramo.
A tabela de strings da 2C diz a hora e a validade do **pacote da `2capi`** (`cache_ts`, `stale`), não a da
requisição: às 16:20 de 30/09 o servidor mostrava as leituras de 13:40 como se fossem de agora. A trava de ocorrência em dobro está em `PV_TRK_OUTRA_FONTE`, e desde 29/09 o `_pv_parados_rows` também
pula essas usinas (quando a aba de trackers da 2C tinha sido aberta no web, o mesmo tracker entrava duas vezes). A conta principal responde "Invalid id" para
as usinas da 2C: qualquer chamada delas tem de ir por `_pv_token_for`. Teste: `tests/test_fonte_2capi.py`.

**Gráfico de trackers da 2C: só a planta da usina, dias em paralelo (06/10/2026**, Levi: "As curvas de trackers na 2C
estão demorando muito — carrega carrega e no final dá erro", Sete Lagoas de 01 a 05/10). O gráfico pelo código (STL, o
que a aba usa) baixava, para cada dia, o dia inteiro das SEIS plantas da 2C pelo `_2c_trk_build_api` (8 a 64 MB cada),
e os dias iam em série — no servidor, UM dia passou de 600 s; pelo id da API PV, 41 s. Agora `codigos=` busca só as
plantas da usina (o pedaço não entra no memo do dia inteiro, que a aba, os parados e a ronda leem), e os dias do
intervalo vão em paralelo (`TRK_CHART_PARALELO`, também no gráfico da API PV). Medido: 5 dias da Sete Lagoas em 44,6 s
frio e 15,3 s quente. Fonte que não respondeu a tempo não é mais "Sem curva (...) não reportou ângulos": a tela diz que
a busca demorou e oferece "Tentar de novo" (`retryTrkChart`). Teste: `tests/test_2c_trk_grafico_rapido.py`.

**A União entrou em 25/09/2026** ("adicione a usina União em 2C!"): conta oem@, id 18772125, "União " na API (com
espaço), 2.162 kWp, instalada em 22/09 — 6 inversores com 28 Ipv (18 com corrente). No cadastro é "União 1 e 2" (Info
Geral: cliente 2C, Piauí, 12 inversores, 4,46 MWp — a API tem metade, por ora), e o `PV_NOME_API_ALIAS` faz a ponte;
sem ela o card da 2C da Entrada a descartava por falta de cliente. Os trackers dela seguem o caminho das outras três
(aba 2C, pela API). Teste: `tests/test_2c_uniao.py`.

**Cadastro da União (28/09/2026**, Levi: "já está na aba equipamentos porém não apareceu na plataforma"). O Equipamentos
a preencheu sob o supervisório **"UNI"** (UNI_Inv_1.1 a 2.6, 12 inversores de 18 strings), não sob "União 1 e 2" —
`PV_ALIAS_CODIGO` faz a cópia do alias procurar também o código. **Desde 11/10/2026 a API tem os 12** (401313–401318 e
401322–401327; até ali só 6, e o `PV_ALIAS_PARCIAL` copiava só esses): a ponte copia o cadastro inteiro (216
esperadas). **401313–401318 são o GRUPO 2** (`UNI_Inv_2.x`): o coletor fechou assim em 28/09 pela razão entre os trios
(1,17, a mesma do BD 2.1–2.3 × 2.4–2.6) e conferiu com o FusionSolar; a plataforma tinha posto "1.x" pela ordem e
rotulou o grupo 2 como grupo 1 até 11/10/2026. Os 6 novos (401322–401327) são o grupo 1 PELA ORDEM, provisório (as
colunas 1.x do BD estão vazias desde 05/10, sem valor para fechar). Na potência o filtro compara pelo `_nrm` do
supervisório e do nome de exibição, que é como o `POWER_INV` é chaveado.
Drill, curva do dia, curva de dia passado e CSV nomeiam pelo mesmo `_pv_nome_2c`, que vem **antes** da ordem do cadastro:
a ordem é de texto ("1.10" antes de "1.2") e rotularia errado a usina de 10+ inversores que ganhasse cadastro. Até 28/09
a curva de hoje das três da 2C saía "INV-400771" e o drill desenhava a do 1º inversor em todos.

## Sol por estado (macro e sino)

**O pôr do sol não é falha.** Medido em 10/09/2026 às 17:52: 89 de 102 usinas "críticas" no `/api/macro` e
300 eventos "string zerou" numa leitura só do sino — era o anoitecer de setembro (~17:50 em SP) dentro de
janelas fixas ("dia" até 18h; sino até 18:20). Agora `sol.py` calcula a elevação do sol pela capital do
**estado** da usina (Info Geral; não há lat/lon no cadastro) e `_macro_sol_baixo(r)` / `_notif_filtra_novos`
descartam o julgamento ao vivo com o sol abaixo de `SOL_BAIXO_GRAUS` (8°). O D-1 da régua de padrão por
inversor continua valendo à noite. O sino ainda tem uma segunda peneira: mais de `_NOTIF_MAX_NOVOS_LEITURA`
(100) quedas novas numa leitura é evento ambiente, nada é avisado individualmente. **Usina sem estado no
cadastro cai na janela fixa antiga** — cadastrar o estado é o que liga a régua para ela. Teste que usa
`_macro_status`/`_notif_ciclo` com usina real precisa de `freeze_now` em horário de sol, senão passa de dia
e falha à noite.

**A tabela de strings do Tempo Real também (22/09/2026).** Antes ela não tinha noção de noite: às 22h a Athon
inteira aparecia "Sem geração" em vermelho, cobrando todas as esperadas. Agora `_servir_com_sol` marca
`sol_baixo` em cada linha **na saída** das 11 rotas de strings, com a mesma `_macro_sol_baixo`, e tira do card
"Sem geração" quem está sem sol, pelo critério de cada fonte (`_sem_geracao_*`). Na tela (`_strStatus`), sem
sol a linha diz "Sem sol", com esperadas e diferença em "—". Comunicação e o D-1 do padrão por
inversor continuam valendo. A marca é feita na saída e não no build porque o ciclo do worker chega a 15 min, e o
payload em cache é do worker (só se mexe em cópia). **Rota de strings nova precisa passar por
`_servir_com_sol`**: o teste lê o mapa `strings:{...}` do HTML e falha se faltar uma.

## Trackers: curva curta não é parado, e o dia anterior (28–29/09/2026)

**Piso de cobertura** (`_trk_curva_curta` + `_trk_piso_cobertura`, na SAÍDA dos dois dispatchers, curso e perdas, nas
duas réguas, antes do `_trk_promove_semcom`): o "parado" de quem tem curva curta vira "normal". Curta = tem leitura na
janela, cobre menos que `TRK_COBERTURA_MIN_H` (4 h), a frota não girou mais que `TRK_ALVO_MOVE_MIN` no intervalo DELE
e ele não emudeceu (última leitura contra a MEDIANA da frota). Caso real: a Guaratinguetá V às 15:44 de 28/09 tinha 48
"parados" com 40 min de curva — a v2 chama de parado quem tem amplitude < 10° sem perguntar quanto a curva cobre, e a
guarda de 4 h só existia na pré-classificação dos motores, que o `_trk_status_from_curva` sobrescreve.

**Regra do dia anterior** (`_trk_parados_antes`, argumento `manter` dos dispatchers): de manhã toda curva é curta, e o
piso sozinho adiava para ~10 h as paradas de frota travada havia dias — a ronda das 08:25 deixaria de citá-las. Quem
estava parado no último dia CLASSIFICADO do registro (até `TRK_MANTER_DIAS` atrás) não é rebaixado. Todos os pontos que
classificam passam a usina: motores da SunOp, Banco e 2C, refino da API PV, os 4 gráficos, o registro do dia e a
reserva das Ocorrências. O web carrega o `trk_eventos.json` (26 MB) só no boot, então o worker grava junto, no
`_trk_ev_save`, um índice pequeno do fim de cada dia (`trk_parados_fim_dia.json`) que o web relê pelo mtime.
Medido às 08:36 de 29/09, nas mesmas curvas (régua de produção sem piso / só o piso / piso + dia anterior): API PV 451 /
146 / 363 (Brodowski, Guatambu 4 e Primavera voltam inteiros; Córrego do Sapucaia 26 / 0 / 0 e São Bento do Una 52 / 0 /
11 — os falsos da manhã continuam fora); Banco 284 / 94 / 161 (Aparecida 3 66 / 17 / 64); Athon 72 nas três.
Testes: `tests/test_trackers_cobertura_curva.py` e `tests/test_trackers_piso_dia_anterior.py` (as duas réguas).

## Tokens

**Dois arquivos, dois donos.** O `tokens.txt` (raiz) é **semente**, formato `CHAVE=VALOR`, editado
por gente e carregado no ambiente no boot. O `plataforma/tokens_runtime.json` é **estado**: o app
escreve nele (chaves `plat`, `sunop`, `axis`, `se_cookie`) toda vez que renova um token. Não junte
os dois — o app reescrevendo o `tokens.txt` apagaria comentários e arriscaria as outras ~20 chaves
numa corrida com quem estivesse editando à mão. Gravação é atômica (`.tmp` + `os.replace`) sob lock,
porque várias threads renovam tokens diferentes ao mesmo tempo e agora todos moram no mesmo arquivo.
Os antigos `*_token.txt`/`se_cookie.txt` foram migrados sozinhos e renomeados para `.migrado` — não
adianta colar token neles.

O token da Plataforma é **manual**: tem CAPTCHA e MFA, não auto-renova. Vale **7 dias** (medido no
`exp` do próprio JWT). **Hoje ele é só reserva de tudo:** trackers e combiner vêm da API PV desde
22/09/2026, e a curva de strings dos DIAS ANTERIORES vem em **corrente pela API PV** desde 28/09
(`_spv_day_records_hist` → `custom_query` v2 com `period`+`day`: a usina inteira, um registro por minuto,
~5 s — 1 consulta da cota histórica, com a mesma reserva da combiner). Ele só entra, em **potência**
(`/v2/relatorios/trygenerate`), no inversor ou na usina que a API PV não tiver em corrente (Levi: "se
tiver histórico de corrente, deixa corrente, se não tiver pega potência"). O histórico de corrente foi
dado por impossível em 15/06 por um teste feito na Matão 1, que parara de reportar em 12/06 — não
provava nada. No mesmo 28/09 a tela deixou de culpar a fonte: a rota diz o `motivo` do vazio (e
`faltando`, por inversor; `motivo_api` quando a API PV não trouxe a corrente) e a unidade de cada
inversor (`unidade`: A ou W — antes a potência saía com eixo de corrente). Só `sem_curva_na_fonte`
diz que a fonte não tem. `/api/tokens` mostra este token como reserva, alarmando só nesta tela.
Quando ele vence, o combiner de reserva recebe `HTTP 401`; um disjuntor abre no primeiro 401.

**Como renovar:** colar em `/tokens`, ou o userscript do Tampermonkey (`plat_token_autocapture.user.js`), que posta
em `POST /api/pv/trackers/token` com `{"token": "..."}` **e a chave no cabeçalho `X-Gridco-Chave`**. A rota passa pelo
portão (o userscript roda na origem da PV, sem a sessão daqui) e, até 10/10/2026, gravava qualquer coisa com cara de
JWT: a revisão adversarial da "porta única" mostrou que qualquer um na internet trocava o token (um forjado com `exp`
em 2099 vence o verdadeiro pela regra da validade maior e a tela /tokens passa a dizer "ok") e zerava o cache de
trackers a cada pedido. Agora, com `DASH_PASSWORD` (servidor), sem a chave é 401 e nada muda. A chave é gerada por
`_plat_chave()` na 1ª visita logada a /tokens ("Mostrar chave"), mora no `tokens_runtime.json` (`plat_chave`) e não muda
sozinha; vazou, apague essa entrada e a próxima visita gera outra. Pedido de fora nunca gera chave, e chave não gerada
recusa tudo. Sem `DASH_PASSWORD` (dev local) a rota segue aberta, como o resto do app. Não dá para validar o JWT na fonte
em vez disso: a Plataforma é frágil (502 por 15 min a ~3,4 req/s em 26/06) e cada POST de fora viraria um pedido nela.
Teste: `tests/test_plat_token_chave.py`. O `tokens_runtime.json` é relido a cada uso, então vale na hora, sem reiniciar. `_plat_token()` escolhe
entre o `PLAT_TOKEN` do ambiente e o arquivo **pela validade maior** — o ambiente é só semente de
boot. Não inverta essa ordem: com "ambiente primeiro", uma semente velha no `tokens.txt` sequestra
a renovação e colar token novo não muda nada (aconteceu em 25/07).

Os demais (SunOp, Axis, SolarEdge, API PV) se renovam sozinhos.

**O `GRIDCO_SQL_TOKEN` também grava em nome do OS Creator** (desde 07/09/2026). O app de desktop
não carrega o token: manda a alteração para `/api/tickets/...` com o JWT do login do Fracttal, a
plataforma confere quem é (`tickets_relay.identificar`) e grava com o token daqui — só nas abas
de `tickets_relay.ABAS`, carimbando o nome verificado no diário e deixando rastro em
`logs/tickets_relay.log`. Essas rotas passam pelo `_auth_gate` por isenção explícita (gate
próprio no handler, como `/api/campo/`). E como o túnel troca de endereço a cada subida, o
`_tunnel_url_loop` publica a URL atual no banco (`os_creator/plataforma`) — é de lá que o app a
lê. Sem essa publicação o app fica só-leitura, então **restart da plataforma = URL republicada**.

## OS Creator na web — proxy `/os/*` (12/09/2026)

O card "Criar OS" da Entrada abre o OS Creator dentro da plataforma. O serviço NÃO mora aqui: é `os_creator/os_web`
no repositório Grid-Co-CODE/oem (clone em `C:\GridcoBuild\oem`), waitress em 127.0.0.1:5090, lançado por
`deploy/os_web.cmd|.vbs`. O `app.py` só faz o proxy (`os_web_proxy`, `OS_WEB_URL` no tokens.txt), no molde do
`/gemeo/*`, com uma diferença: repassa o cookie `os_sessao` (Path=/os) nos dois sentidos — a sessão do Fracttal é de
cada pessoa, não há senha compartilhada. O `_auth_gate` cobre `/os/*`: primeiro o login da plataforma, depois o do
Fracttal. Serviço fora do ar → 503 com texto. Testes: `tests/test_os_web_proxy.py`. Detalhes: `docs/os-creator-web.md`
no repositório oem.

### Última OS no drill do inversor (25/09/2026; recolhida e com a observação desde 28/09)

Bloco "Última OS" no inversor aberto, com três abas pelas marcas que o Fracttal já dá: **Performance** (etiqueta
PERFORMANCE), **Religamento** (tipo Religamento/Religamento Remoto, a mais nova entre a do inversor e a da usina) e
**Chamado** (etiqueta CHAMADOS); cancelada nunca conta (`_frac_ultimas_os`, rota `GET /api/fracttal/ultima-os`). A
linha **"Observação da OS"** é o `note` do REST — o mesmo campo que o card do ticket de strings lê. O bloco nasce
**recolhido** (Levi: "vir recolhida como padrão e abre caso eu clique") e só pergunta ao Fracttal quando abre
(`toggleUltOs`): antes todo inversor aberto fazia a pergunta, e a cota é de 200/min para a empresa inteira. Testes:
`tests/test_ultima_os_inversor.py`.

### OS de tracker criada direto da plataforma (25/09/2026)

Botão **Criar OS** no cabeçalho da aba Trackers (toda fonte com drill de trackers). No modo OS o clique no chip
**marca** o tracker (fora dele, segue ocultando no gráfico); o drill oferece "Marcar os N parados sem ticket". A janela
pede responsável, programada (padrão: **agora + 1 dia**, como a Tradicional do OS Creator), observação e "Gerar
ticket", e cria **pela API do OS Creator** via proxy (`POST /os/api/performance/criar`, o mesmo corpo do `perf.js`),
com a sessão do Fracttal de quem clicou — a OS sai no nome dessa pessoa. Plano "Verificação de Tracker Parado" (o da
Estrutura Trackers, `linkar=false`), uma OS por tracker. Regras que o código segura:

- **Incidente = "parado desde"** da plataforma: `GET /api/trackers/parado-desde?fonte=&plant_id=&trackers=`, a mesma
  varredura da curva da lista de parados (`_trk_parado_desde_hist`), com o livro do tracker_watch como reserva só na
  API PV. A rota devolve a **origem** de cada hora: "livro" é a hora da DETECÇÃO e a janela avisa "confira" — numa
  máquina sem a curva, a Embu Guaçu 2 deu "desde 23:28" de hoje para trackers parados havia dias.
- **Ativo do Fracttal pelo de-para** (`Code Fracttal` de `trackers_depara.xlsx`) casado contra
  `/os/api/performance/alvos`; a usina, contra `/os/api/performance/usinas` (o OS Creator exige o nome EXATO). Sem par,
  a pessoa escolhe na lista. De-para não "casado" (ou trocado à mão) põe "(supervisório: TRKnn)" na observação.
- **Tracker com ticket aberto** (ou ticket da usina inteira) recebe a OS **sem** ticket novo — senão a planilha teria a
  mesma parada duas vezes. Como a caixa do OS Creator é uma por pedido, os pedidos saem por usina × hora da parada ×
  ticket, com no máximo 5 OS cada (o proxy desiste em 180 s).
- Resposta ilegível (tempo esgotado, proxy fora) = **pode ter criado**: os trackers saem da seleção e a janela manda
  conferir no Histórico antes de tentar de novo. Sem sessão do Fracttal (401) a janela oferece o login e segue sozinha.

Testes: `tests/test_trackers_os_plataforma.py` (rota + regras puras no node).

### Investigar ativo: botão direito no inversor do drill (26/10/2026)

Levi: "Gostaria de poder clicar com botão direito do mouse em cima do inversor e ter a opção 'Investigar ativo'. Vai
aproveitar o pré carregamento de histórico de OS do OS Creator filtrando esse ativo, deve mostrar o período filtrado e eu
devo conseguir fazer novos filtros e pesquisas pela visão. Vai abrir uma sub janela sobrepondo a tela dando um blur de
fundo que nem quando vamos criar OS."

- **O menu** (Monitoramento, `gcMenuAtivo`): o botão direito na linha do inversor do drill (o `.gc-chip` com
  `data-inv-usina`, posto só no inversor de verdade com a usina da linha) abre "Investigar ativo", no tema da tela, sem
  emoji, em **toda fonte** com drill de inversor, não só nas do Criar OS. A marca do chip é o único portão: fora do
  inversor (e no protótipo, que não tem a marca) o botão direito é o do navegador; no inversor, o nosso cancela o nativo.
  O nome da usina vem da **linha que abriu o drill** (`buildInversores(pid, r.usina)`); o `RD.pv` achado pelo `plant_id`
  ficou só de reserva. Caso que corrigiu a regra (26/10/2026): o portão era o `_OS_FONTES`, e a Colider 2 é da RenoGrid
  (SolarEdge, sem Criar OS); o Levi clicou no "Inversor 1.6" e veio o menu do navegador, embora o chip estivesse marcado
  e a rota achasse `CLD200-INVR1.6` pelo nome. Onde o ativo não for achado (o inversor desligado chega com o serial,
  `7E05ABED`), o menu aparece igual e a janela abre com a usina inteira e o aviso do OS Creator. Quem não abre o OS
  Creator para no portão do Nexus dentro da janela, como no Criar OS. Fecha com Esc, clique fora, rolagem ou outra janela.
- **O ativo** (`GET /api/fracttal/ativo-do-inversor?usina=<nome da linha>&inv=<nome da fonte>` → `{codigo, origem,
  usina_fracttal}`): o código GRAVADO no cadastro (`_frac_cod_gravado`, Modo de-para) e, sem ele, o derivado do nome
  (`{CODE-BASE}-INVR{N.M}`, a régua do `_frac_inv_code`) com o code-base do índice que JÁ existe em memória ou no disco
  (`_frac_codebase_sem_varrer`: um clique não dispara a varredura de ~150 páginas do `_frac_codebase_index` frio). A
  usina vai com o nome do Fracttal (`_fractall_da_usina`, a régua do `/api/os-creator/fractall-usinas`, que passou a
  usá-la). Nada vai ao Fracttal nem à API PV; está no `_GET` do `leitura_nexus` (ponte e gestor leem). Sem código (índice
  frio, usina sem de-para, a leitura que falhou), a janela abre igual: o OS Creator acha pelo número do inversor na usina.
- **A janela:** `/os/historico/ativo?codigo=&usina=&nome=&rotulo=` + `janela=1`, a do OS Creator no Nexus
  (`nexus/torres/oscreator/README.md`, "Investigar ativo"), no MESMO `gcDeparaJanela` do Criar OS e do de-para. No
  embutido quem abre é a Entrada (`{gc:'investigar', href}`, aceito só da mesma origem e só para `/os/historico/ativo?`).
  O histórico é a lista da Visão COS (30 dias, "Todos"), sem busca a mais no Fracttal; o código é conferido lá, no
  catálogo de ativos do disco (o derivado errado, a Pharma II, vira aviso e a procura pelo nome).
- **No PC aberto direto** (sem o Nexus), o `/os/*` da plataforma vai ao 5090 do oem, que só ganha a tela quando o Levi
  mandar sincronizar: até lá, 404 na janela.

Testes: `tests/test_investigar_ativo.py` (a rota com o gravado, o derivado pela memória e pelo disco, sem índice, sem
parâmetro, sem ir ao Fracttal; a classificação; o menu e a Entrada; o clique rodado no node, com e sem o código, solto e
embutido; o caso da Colider 2 com a linha e o drill que o servidor serviu: o drill da RenoGrid marca o inversor com a
usina da linha, e o botão direito no node abre o nosso menu, barra o nativo, deixa o nativo fora do chip e abre a janela).
Prova no navegador: uma bancada que serve o Monitoramento e responde as rotas com os JSON gravados do servidor (sem rede
para fora), clique direito de verdade no chip, solto e dentro de uma moldura.

## Qualidade de dado: clipping e valor travado (pvanalytics, 17/09/2026)

`qualidade.py` (módulo PURO, com teste) embrulha duas réguas do **pvanalytics**; `_qualidade_loop`
roda 1×/h **no worker** e publica no snapshot; `/api/qualidade` só lê. É pandas — nunca chamar no
caminho de uma requisição.

- **Clipping** (`features.clipping.geometric`, sobre o Pac do `day_inverter`). **Tem PISO
  obrigatório** (`FRACAO_MINIMA = 0.10`): o detector marca o topo da curva de sino como platô mesmo
  SEM teto nenhum. Medido: sino liso sem teto = 0,053; com ruído de 2% já cai a 0,000; clipping real
  vai de 0,193 a 0,649. Sem o piso, usina de céu limpo acusaria clipping todo meio-dia.
- **Valor travado** (`quality.gaps.stale_values_diff`), só em valor **NÃO-ZERO** — zero é assunto da
  régua de inversor desligado, e zero repetido de madrugada é a noite de todo mundo.

**DUAS ARMADILHAS que só o teste de campo pegou:**
1. O `stale_values_diff` marca VÁRIAS sequências no mesmo dia (a madrugada em zero E o platô de
   clipping). Tratar `marcados[0]`/`marcados[-1]` como uma sequência só produziu *"250 kW travado
   desde 23:58 por 9,8 h"* na Sorocaba — 10 falsos positivos. A régua agrupa em blocos **contíguos**
   e reporta o mais longo; não desfaça isso.
2. O `day_inverter` traz leituras a partir de ~23:58 do dia ANTERIOR, então a série de "hoje" começa
   no dia -1. O parâmetro `date` dele é **ignorado** (só existe o dia corrente).

Achados reais na 1ª varredura: Coração 1 (9 inversores em clipping, o pior a 60% do dia),
Coração 2 (3), Altair 1 (1), Tupi Paulista (8 de 20, cravados em 250,24 kW desde 08:15).

**Decisões de 17/09 (tarde):** **clipping NÃO conta como perda** (é de projeto, não de operação —
`QUALIDADE_CLIPPING_E_PERDA=False` e `regua.clipping_e_perda` no payload; não somar às perdas
evitáveis nem valorar em R$) e o recorte é **só a 2C** (`QUALIDADE_PLANTAS = PV_FONTES["2capi"]`;
desde 29/09/2026 inclui a Ipixuna, pelas Santa Cecilia). Ciclo caiu de 80 s para ~11 s. O nome do inversor vem do
`PV_INV_NOMES` porque a conta oem@ não pode chamar `/plant_devices`.

## Falhas de strings e trackers (aba do Diagnóstico, 24/09/2026)

**A tela redesenhada do zero (20/10/2026**, Levi: "mantenha os pilares mas quero que fique mais fácil de entender e o
design mais cara do Nexus"; o foco é o `/t/performance/strings-trackers` do Nexus, que é esta mesma página na moldura).
Mockup com o dado real de outubro aprovado no mesmo dia. O que mudou em
`templates/falhas.html`, sem mudar o pacote nem a régua:
- **Ordem = a pergunta do plantão primeiro.** Cabeçalho do Nexus ("Performance" / "Strings e trackers" / a pergunta),
  com o Mês e o frescor à direita (o Mês vale também na Qualidade, onde antes sumia). Abas com a pílula "N parados
  agora" (o recorte de cliente, busca e confiáveis, sem a usina da outra aba). Faixa de números: **Parados agora** (clicável:
  liga "Só parados agora"; num mês fechado vira "no fim do mês"), Perda no mês (com quanto dela tem estimativa), Pararam
  no mês (não depende do "Só parados agora"), Usinas afetadas — com "Só parados agora" ligado, perda e usinas passam a
  dizer "dos parados". A faixa soma as PARADAS de string (com o filtro, só as que seguem paradas) e a lista soma as
  OCORRÊNCIAS inteiras, com as strings delas que já voltaram: no pacote de 20/10 13:45, 79,4 MWh na faixa × 88,5 MWh nas 66
  ocorrências. Com o filtro de String (ou a busca que acha uma string) é igual: a faixa fica com a string, a lista com a
  ocorrência que a contém. A regra é do Levi e fica; o total da lista leva a dica (title) do que soma (`dicaConta`); sem
  nenhum dos dois, as somas são a mesma (partição). Depois os **cartões por usina** do que segue parado (inclui os crônicos,
  como o card "Parados em aberto" de antes, agora também nas strings), cada um com quantas linhas da lista a usina tem no
  mês — "N ocorrências no mês" nas strings, "N paradas no mês" nos trackers, o recorte da lista sem o "Só parados agora" e
  sem a usina escolhida —, e a lista com os filtros em cima. **Saíram "Onde mais se perdeu no mês" e "Por cliente"** (21/10/2026,
  Levi: "nos cards de strings já mostra também a quantidade de ocorrências nessas usinas e mata os gráficos de Onde mais se
  perdeu no mês e Por cliente"; nos trackers, "mata de uma vez"). A lista fica no **cartão do Nexus** (`.cartao-tab`, o
  `.cn-tab` do campo.css: a superfície com borda e canto de 10 px, o cabeçalho no 2º tom; Levi: "quero a tabela de
  strings e trackers no estilo Nexus, está transparente"); o drill aberto segue na mesma superfície. A perda com
  estimativa leva o ≈ e a dica, sem o sublinhado tracejado (21/10: "tira esse underline traçado de perda").
- **Avisos**: estimativa vai para o ≈ da perda (a dica diz qual), contexto vai para a coluna dele ("vinha parado desde",
  "voltou e parou de novo", "voltou a girar com desvio severo"), o resto vira etiqueta cinza. Antes eram etiquetas âmbar
  iguais em quase toda linha. A Qualidade traduz os contadores (`DIZ`, o nome de dentro fica no title) e junta os avisos
  sem a data (eram 410 caixas em outubro, viram 26).
- **Tirar da conta** = o desconsiderar de antes (mesma rota, mesma caixa: marcar tira, desmarcar devolve), com as tiradas
  numa gaveta lateral (a mensagem sai dentro dela, o foco vai e volta; a perda é a do pacote do mês, o resumo da hora fica
  de reserva); o 403 do gestor diz o motivo (`j.error`) e põe a tela em só leitura (ver Vincular OS). **Nas strings a coluna
  saiu em 21/10/2026** (Levi: "tire a coluna tirar da conta em strings"): fica só nos trackers; as tiradas de string de antes
  seguem fora dos totais e na gaveta, onde dá para voltar. O que vem abaixo sobre a caixa das strings vale para quando ela
  voltar (o código e os testes do lote ficaram). Nas strings a caixa da
  linha tirava TODAS as paradas de string da ocorrência num pedido só (`chaves` + `resumos`; a Inhapi 3.3 são 4, em outubro
  uma chegou a 33) e a linha fica riscada na hora (as tiradas nesta visita formam uma ocorrência à parte, `fora`, que volta
  a juntar ao desmarcar). A chave é por DIA (`fonte|cadastro|inversor|string|dia`; a do tracker, `fonte|cadastro|tracker|
  dia`): duas ocorrências do mesmo equipamento que começam no mesmo dia dividem as chaves e a caixa de uma tira a outra
  (Xavantina 2 · 2.3, 18/10: a das 08:45 leva a das 13:45; nos trackers, 442 chaves repetidas no pacote das 13:45). A regra
  é a de sempre (o worker tira pela chave); a mensagem diz quem saiu ou voltou junto (`juntasTxt`), e a caixa de tracker
  acha a linha pelo id (chave + hora do início), não pela chave (pegava a primeira, com a hora da outra). O recado de erro
  não repete o prefixo: as rotas mandam "não gravou — ..." e a tela dizia "Não gravou: não gravou — ..." (`naoGravou`).
- **Strings = uma tabela só, por OCORRÊNCIA DO INVERSOR (20/10/2026, tarde**; Levi: "Por inversor e dia como tabela
  principal e única", com quantidade de strings, parada, retorno, download, Vincular OS e drill de mais de um dia; saiu o
  segmentado "Por string / Por inversor e dia"). Montada na TELA (`ocorrencias()`), dos episódios que ela já baixa — o
  pacote e o workbook não mudam: as paradas de string do mesmo `fonte|plant_id|usina|inversor`, em ordem de início; a que
  começa ATÉ o fim da ocorrência aberta entra nela (junção inclusiva: o fim é o maior fim, e uma parada em aberto a deixa
  aberta). Sem tolerância. Pacote de 20/10 13:45: 1.456 paradas → **344 ocorrências** (66 paradas agora, 116 com 2+ dias);
  no das 11:03, 337. A estrita ("antes do fim") dava 349/342 — os 5 a mais são Castelo do Piauí: uma string volta às 11:20
  e outra cai às 11:20, na mesma leitura. "Só linhas confiáveis" tira a PARADA com aviso da régua antes de juntar.
  - Colunas: Usina | Inversor | Strings (as distintas; embaixo a lista INTEIRA, "máx. N juntas" quando difere — Guaratinguetá
    V 1.3, 07 a 14/10: 10 distintas, 6 juntas — e "N paradas agora" quando parte já voltou; 21/10/2026, Levi: "aumenta o
    tamanho da coluna de strings prioriza mais isso que avisos": `col-str` com 260 px no mínimo e a lista sem o "+N",
    `col-av` encolhida com as etiquetas quebrando em linhas) | Parou | Voltou | Duração
    (relógio; "N dias" embaixo) | Perda | OS | Avisos | Tirar da conta. Parado agora = alguma string `em aberto` (a régua
    de sempre das strings; a do `dcf725a` é só dos trackers).
  - **Volta sem hora inventada:** "voltou de madrugada" (43% das ocorrências de outubro) mostra só o dia + "de madrugada"
    (o `fim` é o nascer do dia seguinte, não uma leitura) e a duração leva ≈ (conta a noite); "entre duas leituras" = "até
    dd/mm". Trackers seguem com "hora não registrada".
  - **≈ pelo DIA:** a perda estimada da ocorrência é a soma das linhas do dia (`strings.rows`) dela que têm estimativa —
    Inhapi 3.3: 1.114,8 de 8.024,8 kWh (4 dias); em outubro, 84 MWh pelos dias contra 161 MWh marcando a parada inteira.
    Sem as linhas do dia (pacote antigo), a flag das paradas, como antes.
  - **Drill (`cn-linha`/`cn-detalhe` do Nexus) só com 2+ dias:** o acompanhamento diário pelas linhas do dia do inversor
    — Dia | Strings paradas | Das–às | Duração no dia | Perda —, casadas por fonte + `plant_id` + inversor (`indexaDias`).
    A linha que soma dois cadastros com o mesmo nome de inversor no dia (`plant_id` null + `cadastros`, o formato do
    `falhas_job`) entra ITEM A ITEM, pelo plant_id de cada cadastro, e a soma não entra em ocorrência nenhuma; a reserva por
    fonte + usina + inversor é só da linha SEM o campo `plant_id` (o pacote de antes, setembro) e vale dia a dia. Até a
    revisão de 20/10 a tela escolhia um mapa inteiro (o do plant_id OU o da usina) e ignorava o `cadastros`: na Itajá
    (18749574 × 18749576, pacote do worker novo) o drill de um cadastro levava a perda do outro — 14 ocorrências com o drill
    longe da perda em mais de 1 kWh, agora 2 (Santana do Ipanema, 1 kWh de arredondamento). O ≈ pelo dia e as colunas "Dia
    a dia" e "Perda estimada" do Excel saem do mesmo casamento. O dia dividido entre duas ocorrências (Xavantina 2 · 2.3 e
    Xavantina 1 · 1.4, 18/10) leva a dica, e a perda dele é a da ocorrência menos a dos outros dias. O detalhe NÃO ganha
    outro tom de fundo (16/10, um nível de superfície): recuo, fio à esquerda e letra menor. O aberto mora em `S.abre` (o
    `desenha()` refaz a tabela); trocar de aba ou mês zera.
  - Números do topo, cartões e pílulas seguem nas PARADAS de string (os episódios do mesmo recorte); a contagem "no mês"
    do cartão é de ocorrências.
- **Trackers:** 1 linha = 1 parada, como sempre (juntar "voltou e parou de novo" é decisão do Levi; o print da Sete Lagoas
  segue com 56 paradas), + coluna OS e o drill da parada de 2+ dias (do dia do início ao `visto_ate`: 1.460 em outubro)
  pelo `dias` da linha (dia, das, às, horas, perda, comunicação). O drill lista TODOS os dias do cabeçalho "N dias com
  parada" (`diasDaParada`): o dia em que o tracker não mandou leitura não vem no `dias` (a parada atravessa, sem perda) e
  aparece como "sem leitura do tracker no dia", sem horas nem perda — Aparecida 3 · Tracker 24, 13 a 18/10: 6 dias, 3 com
  leitura; no pacote do worker novo eram 272 das 1.612 paradas de 2+ dias com menos linhas que o cabeçalho, agora 0. A aba
  "Dia a dia" do Excel segue os mesmos dias (fecha com a coluna Dias). Pacote sem `dias` (setembro): os dias do
  `trackers_dia` ("parado neste dia", os outros "sem leitura") e a frase "Detalhe por hora a partir de outubro".
- **Vincular OS na tela (1.5 e 1.7):** o vínculo gravado aparece SEM clique (chips "OS n" → `/os/os/folio/n`, lidos no
  `carrega()` de `GET /api/painel/falhas/vinculos` — o livro do Nexus, não o Fracttal). A leitura NÃO segura a 1ª pintura:
  a tela desenha com as tiradas (o arquivo local, como antes) e os vínculos entram num 2º desenho quando chegam, com teto
  de 10 s (`leVinculos`, AbortController); até lá o cabeçalho da coluna OS diz "lendo…" e, com erro ou teto, "incompleta"
  com o motivo na dica (`thOS`). Antes era um `Promise.all` com as tiradas: o banco do Nexus lento deixava a tela em branco.
  A leitura mais nova vale (`VINC_SEQ`: outro mês, ou a lista que volta de uma gravação). A busca `GET /api/painel/falhas/os`
  mora SÓ no `ouvinteOS` (o clique em "Vincular OS"): abrir, filtrar, ordenar, abrir o drill e baixar o Excel fazem zero
  pedido de OS. O painel abre logo abaixo da linha (ou no topo do drill); 502 = erro dito como erro, com "Tentar de novo",
  nunca "nenhuma OS"; a reserva da varredura (`fonte_ok: false` + `reserva`) diz "O Fracttal não respondeu; estas são as
  OS da varredura das HH:MM (pode faltar a mais nova)" e vincula igual. **Forçar vínculo** (22/10/2026, Levi: "ao vincular
  OS e não achar nada, pode ter um 'forçar vínculo' eu digito a OS e fica registrado uma OS, mesmo que não seja daquele
  ativo específico"): no fim do painel (com a lista, sem nada achado ou com o Fracttal fora), um campo para o número da
  OS (só dígitos, até 9; Enter vale o botão) grava o vínculo com `origem: "forcado"` — o livro aceita `tela` e `forcado`
  (`falhas_vinculos.ORIGENS`), os vigentes devolvem a origem, o chip mostra "à mão" (com a dica "pode não ser deste
  ativo") e o Excel escreve "12097 (à mão)". Não pergunta nada ao Fracttal. O vínculo cola na linha do mesmo equipamento cujo
  intervalo de dias contém o `dia_inicio` (no dia de duas linhas, a que começou nele). Desvincular confirma na própria
  linha, sem `confirm()`. O link da OS (chip e painel) sai do número conferido (só dígitos → `/os/os/folio/<n>`), nunca do
  `link` que veio na resposta; fora do formato, sem link e sem "Vincular". Depois de cada ação (abrir e fechar a busca,
  vincular, desvincular, confirmar, a caixa "Tirar da conta") o `desenha()` refaz a tabela e o foco volta ao controle
  equivalente da mesma linha (`devolveFoco`; o "Cancelar" ao pedir para desvincular, o "×" ao cancelar), sem roubar o de
  quem já está em outro lugar. **Só leitura (gestor):** a tela só descobre o perfil pela recusa — o gestor vê os controles
  até o 1º 403 (de qualquer gravação: tirar da conta ou vincular); depois dele somem o "Vincular OS", o "×", a coluna
  "Tirar da conta" inteira e o "voltar para a conta" da gaveta (`ficaSoLeitura`; escondidos, não desabilitados).
- **Baixar Excel (1.4):** a tela monta as abas com TODAS as linhas filtradas da aba (o filtro e a ordem da tabela, sem o
  corte de 60; as tiradas da conta ficam fora) e manda à `POST /api/painel/falhas/exportar`, que só formata; por fetch →
  blob → `<a download>` (com `location.href`, um erro em JSON navegaria a moldura do Nexus); erro na própria tela
  (`baixa-msg`). Strings: "Ocorrências" + "Dia a dia" (ocorrência × dia); trackers: "Paradas" + "Dia a dia" (só com
  `dias`). A volta sem hora vai como DATA em "Voltou" e o "de madrugada"/"não registrada" em "Hora da volta".
- **Sem o filtro de Fonte** (Levi, 20/10/2026: "Tire o filtro de fonte"): nenhuma usina aparece em duas fontes (49 nas
  strings, 63 nos trackers, em setembro e em outubro). Ficam o `id="fonte"` (é o FRESCOR do cabeçalho, que o teste de
  sessão vencida lê), o mapa `FONTE` e a fonte na chave e no rótulo "cliente · fonte".
- **Tracker parado agora** (Levi, 20/10/2026: "Se a usina inteira ficou sem dado então sai da conta, se for só aquele
  tracker é bem possível que esteja parado então segue"): `trkAberto` = sem fim, menos quando o episódio tem o aviso "sem
  dado da usina desde dd/mm" (o Voltou diz "usina sem dado desde", e o tempo parado vai até esse dia, com ≈). O tracker
  que perdeu a comunicação sozinho (`sem_com_desde`) passou a contar: "parado agora" com "sem comunicação desde" embaixo,
  tempo até agora. Leitura incompleta da usina segue contando. No pacote de 20/10 11:03: 925 → 898 (saem 63 — Mandaguaçu
  40, Salto Pirapora 3 16, Boa Esperança do Sul 1 5, Marajoara I 2; entram 36 — Barretos 9, Mandaguaçu 9, Aparecida 3 8,
  TIM100 8). Só a tela: a perda e o pacote não mudam. Teste: `tests/test_falhas_parado_agora.py`.
- **Tema**: tokens do `nexus.css`; aberta direto e no Nexus claro, o claro do Nexus; no Nexus escuro, o navy. `--paper`,
  `--mist` e `--green` guardam os nomes de antes porque o `test_porta_nexus` os confere. Sem `zoom` (era 1.2): a escala é
  a do Nexus, como o Painel NOC. Sem o `#prop` vazio no hash.
- **Prova**: os números do print do Levi (Trackers · 2C · Sete Lagoas, crônicos escondidos: 13,6 MWh, 56 paradas, 27
  trackers, 4 parados agora) saem iguais; a 390 px a página não rola de lado. Os testes de tela (`test_falhas_*`,
  `test_porta_nexus`, `test_sessao_vencida_sem_numero_falso`, `test_telas_sem_funcao_fantasma`) prendem os ids `f-mes`,
  `f-inv`, `f-str`, `frio`, `fonte` (o frescor), `t-vaz`, `t-trv` e `t-sc` pelo texto, e o `filtra()` (que serve à
  ocorrência e aos episódios dos números do topo). Os testes de node NÃO prendiam id nenhum: o DOM de mentira cria
  qualquer id que se peça, e o mutante sem `b-xls`, `baixa-msg` e `lista-msg` passava em tudo (revisão de 20/10). Quem
  prende é `test_todo_id_que_o_script_pede_existe_na_pagina`: todo `$('x')`, `getElementById('x')` e `querySelector('#x')`
  do script tem `id="x"` na página (o varredor acha os três do mutante). `tests/test_falhas_ocorrencias.py` roda a página
  INTEIRA no node (DOM de mentira, fetch dublado) com os casos reais (Inhapi 3.3, Guatambu 2.5, Guaratinguetá V 1.3, Itajá,
  Xavantina 2, Aparecida 3): a junção, a perda = soma das paradas, o ≈ pelo dia, o parado agora parcial, a dica do total,
  o drill que segue aberto depois de redesenhar, o casamento por cadastro (o formato exato do `cadastros`), os dias sem
  leitura do tracker, a busca de OS só no ouvinte (estático e pelos pedidos), os vínculos que não seguram a tela (e o teto),
  o vínculo, o 502, a reserva, o link pelo número, o foco, o só leitura, a chave do dia, o "Não gravou" e o Excel.

`/painel/falhas` (debaixo do `/painel` por causa do Caddy): cada string sem corrente e cada tracker parado do mês,
de quando saiu a quando voltou, com a perda em kWh. Link no card "Diagnóstico de performance" da Entrada.
`falhas.py` (régua, pura, `tests/test_falhas_strings.py`) + `falhas_job.py` (montagem do mês, a mesma do estudo de
24/09, `tests/test_falhas_job.py`); o worker (`_falhas_loop`, 30 min) publica `falhas_AAAA-MM.json` já no formato da
resposta e a rota `/api/painel/falhas?mes=` só devolve os bytes. De `FALHAS_INI` (01/09) para frente.
- **Régua de strings (Levi):** 06–18h, **2 h seguidas** sem corrente com o inversor gerando (mediana das strings
  VIVAS >= 0,5 A e >= 12% do pico do dia). Sem corrente = <= 0,1 A, sem leitura, ou < 10% da mediana das outras
  vivas (string morta que lê ruído — Athon, 24/09: 43 a mais que a régua antiga). Somar o dia não serve (sombra do
  amanhecer + do fim da tarde); mediana de todas não serve (metade das strings mortas zera a mediana).
- Roda sobre a MESMA curva que as ocorrências baixam (`_falhas_registra` em `_pv_strings_eventos` e
  `_sunop_strings_eventos`), sem chamada nova à API; o worker persiste em `falhas_strings.json`. Curva do passado
  da 2C vem da API PV (`_2c_hist_api`; até 03/10/2026, o 2C_historico do e-mail); API PV e Athon usam as quedas
  gravadas (`perdas_strings.json`) antes de 24/09.
- Sem notícia depois, o episódio segue **em aberto** (pedido do Levi). Trava de string vale para o mês todo; a da
  API PV precisa do de-para nome → idefinversor (`falhas_pv_dev.json`, `plant_devices`, 7 dias).
- Trackers: régua de parado da plataforma; parado que vira severo/médio/leve sai; desvio < 2° o episódio todo não é
  falha; kWp do tracker = inversor ÷ trackers dele, ou o típico medido no cadastro (dividir a UFV pelos trackers
  "vistos no store" inflava ~10×: o store só lista tracker com anomalia).
- Geração (`_falhas_geracao`): a do mês com o banco da Thopen, que uma thread da própria aba busca de 30 em 30 min,
  um mês por vez (`_falhas_ger_buscar` → `_ger_diaria_mes`; vale até 3 h), ou, sem ela, BD_Thopen + BD_Performance na
  hora (`com_pg=False`). A volta não espera o banco. Até 15/10/2026 quem buscava era o laço da Disponibilidade (antes
  de publicar o índice dela); saiu de lá porque a disponibilidade é só do Fracttal e isolada da geração.
- **Workbook `falhas_performance` (Gridco API, id 39, criado em 25/09):** oito abas, nesta ordem —
  `strings_inversor_dia`, `strings_episodios`, `trackers_episodios`, `cobertura`, `strings_os`, `trackers_dia`,
  `disponibilidade_dia` e `atualizacao` (`falhas_publicar.py`, o caminho do gêmeo: xlsx + `sync-xlsx?replace=true`; as
  quatro do meio desde 11/10/2026, ver "11/10/2026 — as quatro abas do catálogo do Nexus", no fim desta seção). O worker
  sobe de hora em hora e só quando o dado muda (`_falhas_publicar_workbook`) — a
  API guarda histórico por linha, por isso as linhas vão pela data de início e o "gerado em" mora na `atualizacao`.
  De 25 a 27/09 só gravava com `FALHAS_WORKBOOK=1` (em nenhuma): o registro do SERVIDOR só tinha 22/09 em diante e,
  ligado, ele trocou a carga completa pela parcial em 25/09 00:45. Desde 27/09 o servidor grava sozinho, com a trava de
  cobertura (ver abaixo). A API não apaga workbook nem aba.
- **Fim de episódio de tracker sem hora (Levi, 25/09):** o registro de trackers só guarda a CLASSE do dia. Tracker que
  some das classes num dia em que a usina leu, ou que vira severo/médio/leve, voltou NESSE dia — `fim` = só a data
  ("hora não registrada" na tela), nunca o fim do último dia parado. MAB200 Tracker 103: a tela dizia "voltou 08/09
  17:38"; na curva, voltou em 09/09 entre 16:45 e 17:00. Usina sem leitura depois = segue em aberto.
- **Nome de inversor sempre pelo `_nrm`** ao casar trava: Indaiatuba 21480|378276|Ipv18 escapava porque o
  plant_devices diz "INVERSOR 1.10" e a queda "Inversor 1.10". Episódio aberto HOJE termina em "agora", não às 18:00.

**27/09/2026 — o cruzamento com as OS do Fracttal e as correções que saíram dele** (`docs/mockups/falhas-strings-x-os-2026-09-27.html`):
- **Entrada vazia não é falha.** Ipv29–Ipv32 eram 41% dos episódios e 55% do kWh de setembro: entradas sem string ligada
  (0 A cravado o dia inteiro), nunca citadas em OS. `falhas.avaliar_dia` devolve, além das mortas, `vivas` por inversor
  (gerando ≥ 50% das vizinhas com o inversor a 30% do pico) e `sempre_zero` em cada morta; `_falhas_registra` guarda os
  dois. Na montagem, entrada vazia = nenhuma volta de verdade no histórico gravado (retorno em massa não conta; "queda no
  meio do dia" também não: aparece em 172 entradas vazias por buraco de captura) + zero em toda curva + o inversor já
  com as vivas do cadastro. Sai do mês inteiro e vai para `strings.entradas_vazias`. **Não corte pelo número de strings
  do cadastro**: SMP100 5.2 tem 17 no cadastro e ST19–25 são reais (OS 13297).
- **Inversor com o mesmo nome em todo lugar**: id (`INV-367159`, quando o plant_devices falha — Santana do Ipanema, 27/09
  23:41), nome do plant_devices ("INVERSOR 3.3") e o da queda ("Inversor 3.3") viram o do cadastro (`inv_canon` +
  `inv_cadastro` no falhas_job). Sem isso a entrada vazia não casava com o cadastro.
- **Fontes novas**: String Box pela curva da combiner (`_pv_comb_curvas`, a MESMA resposta do custom_query, que já traz o
  dia inteiro; chave "pvsb", porque a API PV registra a mesma usina pelo Ipv≈0 e um apagaria o outro); RenoGrid pela
  série que o generate-chart da tabela já devolve (`_se_serie_ultima`, em W, grade de 15 min — a assinatura de
  `se_string_power` não mudou porque os testes da tabela a trocam por uma função de 3 argumentos); Banco da Thopen por
  `_falhas_pg_varre` (1 consulta por usina, de 2 em 2 h e uma depois das 18:30, sem o 2º passe da mediana; consulta vazia
  não registra). A trava vale pelo `ids` que a curva registra (pvsb e pg).
- **Volta falsa da manhã**: volta que morre de novo antes do meio-dia é o mesmo episódio — antes das 9h com até 2h30 viva
  (pouca luz) ou a qualquer hora com até 1 h viva (pisca: a ST15 voltou 08:20–09:10 e 09:40–10:00). Só junta episódio que
  JÁ tem 2 h seguidas: somar pedaços curtos é a régua recusada. SMP100 5.2 ST15 (um defeito, OS 13297) ia de 11 episódios
  para 3; os que sobram são volta de 2h40 ou dia sem dado. Na régua nova usa `ini_producao` da morta.
- **Trava com OS aberta**: `_falhas_os_abertas` (4 consultas por status ao Fracttal — a API não aceita lista —, a cada 6 h,
  só "recomposi"), `/api/strings/trava-aviso` (o Monitoramento pergunta antes de trancar, `_travaOk`) e
  `strings.travas_com_os` na aba. Casa pela chave da trava com o nome de inversor de HOJE: a Guatambu tem a Ipv18 trancada
  na Guatambu 1 INVERSOR03 e a OS 11016 aberta no INVR3.2 (Guatambu 3), mas em julho/agosto a Guatambu 1 gravava quedas
  no "Inversor 3.2" — o nome mudou no caminho e a ligação não está provada.
- **Histórico do PC no servidor**: `POST /api/painel/falhas/historico` (login) guarda a carga; o worker junta só o
  dia-fonte vazio ou ausente, antes de hoje (`_falhas_importa_historico`). Não há acesso ao disco do servidor e o backup
  `plataforma_series` só restaura quando o arquivo some — e PC e servidor sobrescrevem o mesmo backup.
- **Workbook**: grava sozinho só no Linux (o servidor); `FALHAS_WORKBOOK=1/0` força. E só sobe mês cujo registro de strings
  começa até o 4º dia e que já tem um dia de curva avaliada com as vivas (`_falhas_cobertura_ok`; `strings.dias_registrados`,
  `strings.dias_com_vivas`) — logo depois do deploy o servidor ainda não separou as entradas vazias.
- **Virada de mês**: `_falhas_meses_a_montar` (o anterior é refeito até o dia 2); quem estava em aberto no fim do mês e
  amanhece igual no dia 1 leva `desde` e o aviso "vem do mês anterior" (`abertos_antes`).

**28/09/2026 — volta só com prova, filtros e os trackers em aberto contra o tempo real:**
- **String "voltou de madrugada" sem ter voltado** (MAB100 3.9 ST03/ST04, sem corrente desde 04/09, partida em 25/09
  06:38): a queda do dia seguinte que começa depois das 07:30 continua o episódio se a string está morta desde que o
  inversor começou a gerar (`ini_producao` + 20 min) ou, sem essa hora, se caiu até as 10:30; e registro de madrugada sem
  nada gerando não conta como "a usina apareceu" (Assis 5.1). 262 voltas falsas no mesmo dia em setembro → 28.
  E a volta de até 1 h que morre de novo no mesmo dia junta a QUALQUER hora (antes, só até o meio-dia): MTS100 3.7 ST11
  passou o 23/09 sem uma leitura acima de 0,5 A na curva, e as quedas "voltavam" 30 min às 12:40 e às 14:30. O que
  sobra desse tipo em setembro é 1 caso (MTS100 4.2 ST13, 23/09): a régua das quedas só marcou a queda às 12:30 —
  sem a curva daquele dia gravada, não há como provar; a curva da SunOp de dia passado existe e resolveria.
- **Filtro por inversor e por string/tracker** na aba (`f-inv`, `f-str`; ordem natural, 3.1 ≠ 3.10; na ocorrência do
  inversor vale a string da lista: a ocorrência entra se a contém). Rótulo e seletor ficam no mesmo `.fpar` para quebrarem
  de linha juntos.
- **Trackers em aberto × tempo real** (Levi: "batem com o tempo real?"): às 15:44 batiam 359 dos 738 parados. Três causas,
  todas no `falhas_job`: (1) o descarte "no alvo (desvio < 2°)" usa o desvio do registro, medido contra a MEDIANA DA
  FROTA — com metade ou mais da frota parada (`FRAC_FROTA_PARADA`, frota = cadastro ou a vista no mês) ele dá ~0 e sumia
  justo com a usina inteira parada: 1.671 dos 1.692 descartes de setembro (Brodowski 52/52 a 0,6° desde 24/09,
  Santa Bárbara I 52/52 em 0,0° desde pelo menos 19/09 — a mesma que motivou a regra em 24/09, lida errado). Dia assim não
  descarta e o desvio dele não entra na perda (sem outro, fator 25%), com o aviso "maioria da frota parada"; (2) dia que o
  registro leu mas não classificou (`classes` None: cobertura < 0,5 — MAB100 0,43, CPP100 0,34) fechava tudo "voltou
  (hora não registrada)": agora atravessa, e o em aberto leva "leitura incompleta da usina desde"; (3) dia de classe
  "parado" com o último evento "voltando" (leitura que teleporta, Barretos 2: 172° e 8·10¹¹°) fechava "voltou a girar":
  a classe do dia vence. Medido na mesma foto: 334 → 619 dos 622 do tempo real. O que sobra na aba e não no tempo real é
  usina sem dado ou sem classificação hoje (com aviso) e o atraso do registro (30 min) + pacote (30 min).
- **Backfill da curva da SunOp** (`_falhas_backfill_sunop_loop`, no worker, 15 min depois da largada e de 6 em 6 h):
  cada usina-dia da Athon e da Axis, de `FALHAS_INI` a ontem, sem registro da régua nova, com registro pela metade
  (avaliado antes das 18h: a plataforma caiu, deploy) ou de antes das vivas ganha a curva de strings direto na API da
  SunOp, na hora da usina — um lote por vez, um dia por minuto (rajada derruba a conta na borda). Dia baixado fica em
  `falhas_backfill_sunop.json`; lote que falha para a passada sem gravar o dia pela metade; usina sem leitura no dia
  não ganha registro (vazio apagaria as quedas gravadas dela). Equivalência em 27/09: 14 de 14 strings mortas iguais,
  mesma hora, mesmas vivas nas 10 usinas da Athon. ~13 POSTs por dia, US$ 0,0005 cada acima da cota. **Não pelo acervo
  do gêmeo**: até 28/09 ele vinha em UTC lido como hora da usina (corrigido, ver "Curva da SunOp pelo acervo do gêmeo"),
  e continua direto na API porque o acervo tem strings pela metade — o backfill precisa do dia inteiro.
- **O tempo real também erra**: Guaratinguetá V às 15:44 tinha 48 "parados" com 40 min de curva (15:10–15:50, os trackers
  indo de 46° a 55°) — a v2 não tem piso de cobertura e o `dia_coberto` (4 h) só vale na pré-classificação. A aba não o
  pegou porque o registro não classifica dia com cobertura < 0,5.

**29/09/2026 — sombra não é falha** (Levi, com print da aba: MAB100 4.2 ST07 em 02/09 e 5.1 ST07 em 12/09, "funcionando
normalmente" no Fusion):
- A string sai de 50% das vizinhas e desce em **rampa** — uns 4 pontos a cada 10 min, com o inversor a 95–100% do pico —
  até ficar abaixo de 10%: sombra crescendo. String que abre cai num degrau. `falhas.avaliar_dia` põe o trecho que entra
  ou sai por uma rampa de `QUEDA_GRADUAL_MIN` (40 min) ou mais em `sombras`, fora das `mortas`. Rampa: em toda célula
  entre a última leitura a ≥ 50% das vizinhas (com qualquer luz: no nublado a sombra some) e o trecho, o inversor forte
  (≥ 30% do pico) e a razão num sentido só (`RAMPA_FOLGA`, 0,05).
- **Não meça só o relógio** desde a última leitura boa (a 1ª versão, que não subiu): chamava de sombra 23 trechos em 9
  inversor-dias sem rampa nenhuma — buraco de dado no meio (MTS100 3.7 ST11–13 em 22/09, SMP100 6.1 em 18/09:
  amanheceram mortas), dia no patamar de 20% do pico (CPP100 4.1, 14/09) e string piscando (SMP100 3.1 ST03). Dos 28
  episódios de entrada lenta na varredura de setembro (curva do 1º dia de 632 episódios de curva), só 3 são rampa: os
  dois da MAB100 e a MTS200 2.15 ST04 (19/09).
- Na montagem, `strings.sombras` lista o que saiu, para conferir. Sombra que termina o dia morta e amanhece morta volta a
  ser falha, com o aviso "começou devagar" (`sombra_amanheceu`).
- O registro guarda a versão da régua (`regua` = `FALHAS_REGUA_VER`) e o backfill da SunOp refaz o dia avaliado com a
  anterior (~13 POSTs por dia do mês). Banco e RenoGrid não têm backfill: dia passado fica como foi avaliado (a API PV
  tem, ver abaixo, mas não refaz a régua anterior).

**29/09/2026 — a queda gravada da API PV de dia passado não vale** (Levi, com print da Rodrigues 2.1 Inversor 1.1: "As
strings citadas estão trancadas"). Não eram trava — as trancadas eram as Ipv4/5/9/10/14/15/19/20/24:
- O motor de ocorrências grava o dia que passou pela POTÊNCIA por string da PV Plataforma (trygenerate;
  `_perdas_str_backfill`, depois da meia-noite). Na corrente da API PV do mesmo dia (custom_query v2) ela errava a
  string: Rodrigues 2.1, 10/09, Ipv13/16/17/18/21/22/23 "zeradas" nos 8 inversores e gerando 9–14 A ao meio-dia; Ouro
  Branco, 15/09, 432 acusadas e nenhuma morta; Ipv29–32 num inversor de 28 entradas (Sorocaba, Guatambu 4). Das 1.151
  quedas gravadas da API PV na aba em 29/09 (107 MWh), ~95% eram string gerando.
- `falhas_job.FONTE_POTENCIA_DEPOIS_DO_DIA`: a queda da API PV gravada depois do fim do dia (ts ≥ meia-noite de
  Brasília) sai do store antes de tudo — nem episódio, nem dia visto, nem "voltou"; `strings.pv_potencia_fora` conta as
  usinas-dia. A gravada no próprio dia (corrente de hoje) segue valendo onde a usina-dia não tem a régua sobre a curva.
- A corrente de hoje também inventa string no detector antigo: a Tanabi 2 só reporta uma corrente por inversor (Ipv1) e
  ele acusava Ipv2 a Ipv24 (460 episódios em 24/09). A régua sobre a curva exige duas strings vivas e não acusa.
- **Backfill da curva da API PV** (`_falhas_backfill_pv_loop`, só no servidor; `FALHAS_BF_PV=1/0` força): a usina-dia
  sem a régua sobre a curva ganha a corrente do dia pela API PV — primeiro a que tinha queda gravada, do dia mais recente
  para trás. 1 consulta histórica por usina-dia, da cota da CONTA (800/dia e 200/h, a mesma da combiner e da coleta da
  noite): para com a cota do dia abaixo de `FALHAS_BF_PV_RESERVA_DIA` (450) ou da hora abaixo de 60, 30 s entre pedidos,
  120 por passada (de hora em hora). Não refaz a régua anterior. `falhas_backfill_pv.json` guarda a usina-dia pedida:
  sem leitura na API, não volta a pedir.

**30/09–01/10/2026 — desconsiderar, volta com prova e a entrada que o inversor não manda** (pedidos do Levi com print):
- **Desconsiderar ocorrência** (MAB200, 22/09 07:10–09:40: strings abaixo de 1 A com os trackers parados): checkbox na
  linha do episódio e do tracker; `POST /api/painel/falhas/desconsiderar` grava em `falhas_desconsideradas.json` (estado,
  com quem e quando), o worker lê na montagem (`desconsideradas=`) e a chave é `falhas_job.chave_str`/`chave_trk`. Sai dos
  episódios, da visão por inversor × dia e dos totais; o laço do worker acorda ~1 min depois da gravação (mtime do
  arquivo). **O checkbox marca E desmarca** (05/10, "o CheckBox só marca e não desmarca"): marcada na visita, a linha
  fica na tabela apagada (`DESC_VIS`, `tr.desc-on`) e fora das contas, e desmarcar devolve; a tela muda na hora e volta
  atrás se o servidor não gravar — a caixa não trava esperando a resposta (Inhapi TRK13/TRK52 gravaram às 12:15 e as
  caixas ficaram marcadas e cinzas). Na visita seguinte a desconsiderada some da tabela e fica em "desconsideradas
  (N)", de onde volta. Teste: `tests/test_falhas_desconsiderar.py`.
- **Duração no dia** (05/10, na visão por inversor e dia; desde 20/10/2026 no acompanhamento diário da ocorrência, que
  substituiu essa visão): o `h_sol` da linha SOMA as strings (20 strings × 10,9 h = 218 h na
  Guaratinguetá V 1.4); `dur_h`/`dur_min_h` são a maior e a menor duração de uma string no dia e `janela` o
  "HH:MM–HH:MM" (no título). É de RELÓGIO entre 06 e 18 h (`dur_relogio`): string fora o dia todo = **12 h**, o
  período solar (Levi: "pode colocar duração 12 hrs, que é o período solar (6 as 18)"); amanheceu morta (desde a
  partida do inversor, ou caiu até 07:30 sem essa hora) conta das 06:00, sem volta vai até as 18:00 (hoje, até agora).
  A perda segue pesada pelo sol. Outubro no PC: 390 de 539 linhas com 12 h. Pacote montado antes da coluna (setembro,
  que não remonta mais) mostra "—" (a média por string em horas de sol, o "≈" de antes, não é duração de relógio).
- **A volta do fim da tarde precisa de prova** (MTS100 6.3 ST06, 13/09 16:50): a string morta lê 0,1–0,35 A de fuga, passa
  dos 10% das vizinhas que também caíram e "voltava" — o episódio de 11 a 15/09 virou dois. A volta do ÚLTIMO trecho do
  dia só vale com sol forte ou a string a ≥ 50% das vizinhas (`falhas.avaliar_dia`); régua `2026-09-30-volta-com-prova`.
- **Entrada que o inversor não manda** (Fazenda Limão: "pra mim fazenda limão não aparece essas strings 29 a 32"). Em
  30/09 o INVERSOR06 mandou 1.437 registros com Ipv1 a Ipv28 e UM, às 09:00, com 92 campos (Ipv29 a Ipv32 = 0, Upv29,
  Pac1–3, Ri). A régua lê célula sem leitura como sem corrente: a fantasma "morria" o dia inteiro. No servidor, em 30/09,
  Ipv29+ eram 328 dos 433 episódios da API PV e 43 dos 82 MWh (Fazenda Limão, Guatambu, Nova Londrina 2, Poconé 1,
  Colorado 1, Belo Jardim, Canarana 1, São Bento do Una — todos inversores de 28 entradas). A prova da entrada vazia não
  pegava porque pede zero em TODO dia de curva, e no dia sem o registro solto a fantasma nem está na curva (conta como
  dia em que ela gerou). Duas travas: (1) `_pv_curvas_strings_de` tira a entrada que vem em menos de
  `PV_ENTRADA_MIN_FRAC` (25%) dos registros do inversor — vale para ocorrências, régua, drill e CSV; (2) o registro do dia
  AO VIVO guarda `entradas` (maior IpvN regular, contando a trancada, só do inversor que gerou) e o `falhas_job` tira do
  mês inteiro a string acima do maior número visto (`entradas_inexistentes`, "entrada que o inversor não manda: fora").
  Backfill não ensina (a curva do custom_query não é o pacote do inversor). Antiga × nova no dia real: só as 4 séries
  fantasmas mudam (1 ponto cada), 232.398 pontos iguais. Testes: `tests/test_falhas_entrada_fantasma.py` e os de
  `test_falhas_job.py`. **Só limpa o mês depois que a usina tem um dia ao vivo registrado com o código novo** — e o mês
  anterior só é remontado até o dia 2.
- **A fantasma que vem em MAIS de 25% dos registros** (08/10, Levi: "está puxando strings que não existem no PV
  Operation"). De 02 a 05/10 cinco inversores da Fazenda Limão 1 mandaram Ipv29–32 = 0 em boa parte dos registros (o
  registro do dia diz 32) e nos outros dias não mandaram (28). O "maior número visto" (32) desfazia a inexistente, e a
  vazia não fechava porque o dia sem a entrada no pacote — e os de antes do `entradas`, 28–30/09 — contavam como dias
  em que ela gerou. Prova pelo dia (`INEXIST_DIA` no `falhas_job`): num dia ao vivo em que o inversor gerou, a entrada
  veio em menos de 25% dos registros (o número do dia fica abaixo dela), e em TODO dia ao vivo em que ela veio ficou
  zerada; sem volta no histórico, número acima das strings do cadastro e o inversor com as vivas do cadastro **nos dias
  com o número** — dia sem o número (antes de 01/10, backfill) não decide nem conta nas vivas: a revisão adversarial
  mostrou a string real que gerou num dia desses, morreu de madrugada e sumiria com um dia de pacote degenerado (a
  Ceilândia 2 grava 1 e 24). Vai para `entradas_inexistentes` com o número que mais se repete ("o inversor manda 28
  entradas"). Antiga × nova no dado do PC: outubro 44 linhas a menos (Fazenda Limão 21; São Bento do Una, Primavera 1 e
  2, Córrego do Sapucaia 23; ~8,5 MWh), só Ipv29–32, nada entra, trackers iguais. **Setembro ficou com as fantasmas da
  Fazenda Limão no pacote fechado em 02/10** (444 strings-dia, ~18 MWh no PC): ele só remonta se o arquivo sumir, e
  remontar hoje traria também a deriva do dado desde 02/10 — decisão à parte.
- **Tracker sem comunicação não entra** ("alguns trackers estão como 'parados' porém ficaram sem comunicação, não quero
  esses trackers no relatório"). Desde 08/09 o tempo real conta como parado o sem comunicação travado num ângulo
  (`_trk_promove_semcom`) e o registro só guardava "parado". O registro do dia passa a guardar `sem_comunicacao` (lista,
  `_trk_semcom_set` — a etiqueta roxa) nos 4 pontos que gravam o `_trk_eventos`; no `falhas_job` o dia sem comunicação
  atravessa (não é parado nem volta), não entra na conta da frota parada e vai para `trackers.sem_comunicacao`. O parado
  de verdade que perde a comunicação fica sem fim e com `sem_com_desde` + `visto_ate` (o último dia em que o viram
  parado): a perda é só dos dias em que comunicava, e ele sai de toda conta de "em aberto" (`trkAberto` na aba, `_fim_ef`
  no semanal) — não se sabe se voltou; na coluna Voltou, "sem comunicação desde dd/mm". **Antes de 01/10 a marca vem das
  fotos da ronda** (`trackers_parados_hist.jsonl`, `_falhas_trk_semcom_hist`): vale a última foto do dia que listou o
  tracker; rótulo repetido (a ronda junta Guatambu 1 a 4 como "Guatambu", com um TRK1 em cada) só vale com todos sem
  comunicação; e o dia SEM FOTO nenhuma (ronda que não rodou), até `TRK_SEMCOM_LACUNA_MAX_DIAS` (4) seguidos, é sem
  comunicação se o tracker estava assim na foto de antes e na de depois (Santa Bárbara I Tracker 48: sem comunicação em
  toda foto de 15 a 30/09 e "parado" em 20 e 26/09, sem ronda). O servidor não faz a ronda: a do PC vai por
  `POST /api/painel/falhas/trk-semcom` (login; `scratchpad/envia_trk_semcom_servidor.py`). Setembro no PC: 5.597
  tracker-dias de 559 trackers saíram, 1.065 → 738 MWh. Teste: `tests/test_falhas_trk_semcom.py`.
- **"Trackers que pararam"** (card da aba de trackers): os trackers diferentes do recorte, quantos começaram no período,
  quantos já vinham parados (`cronico` ou `desde`) e quantos seguem parados agora; com "Esconder crônicos" ligado, o card
  diz que os de antes estão escondidos. **No relatório semanal** (bloco 04, `relatorio_semanal.trackers_pararam`): os
  DISTINTOS (id da usina na fonte + tracker; sem o id, fonte + nome + tracker — desde 11/10 sem a fonte quando há id, ver
  "Fonte do tracker pelo cadastro") parados em algum momento da semana, por quantidade — total, quantos
  começaram na semana, quantos seguiam parados no fim e as usinas com mais trackers (Levi: "distintos viu, por
  quantidade"). 21–27/09 no PC: 770 (301 começaram, 500 seguiam parados; Barretos 106, Brodowski 102).

**11/10/2026 — as quatro abas do catálogo do Nexus** (Levi: "Dê seguimento a todas essas que não foram criadas, faça
funcionar"). O catálogo do Nexus (`nexus/dados/catalogo.py`, fatos `falha_tracker_dia`, `cobertura_falhas`, `os_string`
e `disponibilidade_dia`; seção "Falhas da plataforma com `plant_id`" do `nexus/dados/CLAUDE.md`) registrou em 08 e
09/10 abas que a plataforma nunca publicou: o desenho delas nasceu da Operação no Mês do Dashboard Thopen (5080; o
leitor do 5080, `thopen/fonte_operacao.py`, e o spec, `docs/superpowers/specs/2026-10-08-thopen-operacao-no-mes-design.md`,
ainda não estavam na main em 11/10). Aqui só a publicação. **Colunas novas só no FIM e abas novas antes da `atualizacao`**: nada que existia mudou de nome ou de lugar
(o BI e o Nexus leem por posição). Tudo sai do que o worker JÁ monta — nenhuma chamada nova a fonte paga nem ao Fracttal.
- **`plant_id`** no fim de `strings_episodios` e `trackers_episodios` (sempre texto: "297378" e 297378 viram células
  diferentes). É a chave dos episódios no catálogo: pelo nome, a Brodowski junta os dois cadastros dela na API PV (52
  trackers em vez de 103). O pacote do mês já o trazia nos episódios; desde 20/10/2026 as linhas inversor × dia do
  pacote (`strings.rows`) também o levam (ver "Strings e trackers: tabela única, Vincular OS e download"), mas a
  `strings_inversor_dia` segue agregando usina × inversor × dia e sem a coluna (colunas explícitas no `falhas_publicar`).
- **`dias_comunicou` e `dias_sem_prova`** no fim de `trackers_episodios` (Levi, 08/10: "quando fica parado sem
  comunicação essa ocorrência é ignorada; se a usina comunicou inversor ou string então aí conta"). Comunicou no dia = a
  régua de strings leu PRODUÇÃO da USINA (nome canônico, qualquer fonte e cadastro — a Brodowski 297381 não tem
  registro de strings e a 297378 tem todo dia; `vivas` ou `mortas` no registro, ou a curva da 2C) ou a geração do dia
  passa de 0. Registro de madrugada sem nada gerando não prova; a geração sozinha não serve (é D-1: o dia corrente sairia
  sempre "sem comunicação"). `dias_sem_prova` = dia que a GERAÇÃO ainda não cobre, sem prova nenhuma: Barretos, Céu
  Azul, Ceilândia 1 e Cidade Gaúcha não têm string lida e só provam pela geração, que o BD_Thopen grava 0 até o
  fechamento das 23:30 (às 15:00 de 08/10, 72 episódios do dia saíam com 0 dia de comunicação). **Fechado é pela geração,
  não pelo relógio** (revisão adversarial de 11/10): o dia fecha quando a geração do mês chega até ele (`GER_ATE` no
  `falhas_job`, o maior dia em que alguma usina gerou; sem geração nenhuma no pacote, vale o relógio). Pelo relógio, às
  00:05 a geração em uso era a que a Disponibilidade buscou às 23:50 (cortada no D-1 dela: até anteontem) e o dia de
  ontem saía "não comunicou" — o tracker parado só nele sumia do card do 5080. Nos stores reais de 11/10, às 00:05 com a
  geração até 09/10: o `trackers_dia` de 10/10 ia de 58 linhas ("sim") para 64 (+6 "sem prova": Barretos, Ceilândia 1,
  Céu Azul e Sete Lagoas, 23 trackers), os outros dias iguais. Volta a 0 quando a geração do dia chega. Limite: a
  `GER_ATE` é da frota — com o banco da Thopen já fresco e o fechamento do BD_Thopen atrasado, a usina do BD_Thopen sem
  string lida ainda sai "não comunicou" no dia que o banco já cobre (o kWh do pacote não diz de qual base veio).
- **`cobertura`** (1 linha = mês × SISTEMA × `plant_id`; `dias_strings`, `dias_trackers`, `dias_comunicou`): quem a
  plataforma MEDIU no mês, com ou sem falha — sem ela, a usina sem linha nos episódios sairia "0 falhas" no cliente, e
  pode ser usina que a plataforma nem monitora. Dia de strings = registro com `vivas`/`mortas`, queda gravada no store
  (fora a 2C) ou curva da 2C; dia de trackers = registro classificado com cobertura > 0. **`0` = a régua registrou o
  cadastro e não houve leitura** (Céu Azul e Ceilândia 1 nas strings: registradas sem produção; MTS100 nos trackers: a
  SunOp devolve curva vazia); **vazio = a régua nem registrou o cadastro no mês** (não medido: a de trackers na usina sem
  tracker monitorado, a de strings na que só tem tracker — Brodowski 297381, Tucano 1 e 2). A **String Box sai na linha
  da API PV** (`falhas_job.FONTE_SISTEMA`: é a mesma usina, o mesmo `plant_id`, guardada em "pvsb" só para um registro
  não apagar o outro) e o tracker vai pela fonte do cadastro (abaixo). Até a revisão adversarial de 11/10, outubro tinha
  32 `plant_id` em duas linhas, cada uma com um 0 falso (21480: Banco com 0 dia de strings e 3 de trackers, API PV com
  10 e 0; Brodowski 297378: String Box 11 e 0, API PV 0 e 11). O `dias_comunicou` é da USINA, repetido em cada
  `plant_id` dela: não somar entre linhas. Vai pelo 1º dia medido, para o cadastro que aparece no meio do mês entrar no
  fim.
- **Fonte do tracker pelo cadastro, não pelo tamanho do id** (revisão adversarial de 11/10; `falhas_job.fonte_de`). O
  registro de trackers (`trk_eventos.json`) é um store só das quatro fontes, chaveado pelo `plant_id`, e não dizia de qual
  fonte cada usina era: a montagem chutava pelo tamanho do id (até 5 dígitos = Banco, `fonte_pelo_id`). A API PV tem 29
  cadastros de 5 dígitos (Indaiatuba 1 a 4 = 21480–21483, Embu Guaçu, Nova Londrina, Altair, Ceilândia II e 1, Céu Azul,
  Tanabi, Mandaguaçu, Canarana), que saíam "Thopen · Banco" (o Banco vai de 1 a 34) — e o Nexus, que liga o `plant_id`
  pelo de-para do sistema, procuraria o 21480 no Banco. Vale, nesta ordem: a `fonte` que o registro grava (os quatro
  gravadores do app, `_sunop_eventos_calc`, `_trk_ev_backfill`, `_owen_eventos_calc` e `_pg_eventos_calc`, desde
  11/10; ver o comentário do `_TRK_EV_PATH`); o de-para da API PV (`falhas_pv_dev.json`) e o registro de strings (o mesmo
  `plant_id` em pv/pvsb é da API PV, em pg é do Banco), quando dizem uma fonte só; e, sem nada disso, o tamanho do id.
  - **A chave da ocorrência (`chave_trk`) continua pelo tamanho do id**: é o que o analista desconsidera e a tela devolve
    ("pg|21480|..."); mudar a chave junto com a fonte devolveria à aba as ocorrências que ele já tirou. É identificador,
    não fonte.
  - O **"desde"** do mês anterior (`abertos_antes`) casa pelo `plant_id` e o tracker, sem a fonte, e o relatório semanal
    conta os trackers distintos do mesmo jeito (`relatorio_semanal.trackers_pararam`): setembro, montado em 02/10 e não
    mais remontado, tem o 21480 como Banco, e na semana da virada o mesmo tracker viria com as duas fontes.
  - Nos stores reais de 11/10 (cópia de 22:35), o `falhas_job` de `1d0cae7` × o corrigido: strings iguais (841
    episódios, 1.198 linhas); `trackers_episodios` as mesmas 3.010 linhas (mesma chave) e só a fonte muda, Banco → API
    PV, em 741, todas dos 29; `trackers_dia` as mesmas 583 linhas e a fonte muda em 126; `cobertura` 192 → 159 linhas,
    159 `plant_id`, 0 em duas linhas, e cada régua de cada `plant_id` dá o maior valor que as linhas de antes davam (158
    de 159; a 22841, Ceilândia II, juntou 1 dia da API PV e 10 da String Box: 11).
- **`trackers_dia`** (1 linha = fonte × `plant_id` × dia com tracker parado; `trackers` em lista, `qtd`, `comunicou` =
  "sim" ou "sem prova"): só os episódios que ficam na aba (nem descartados nem desconsiderados), só no dia em que a usina
  comunicou ou no que a geração ainda não cobre, sem outra prova. Trackers distintos no mês saem da LISTA, nunca da soma
  da `qtd`. A fonte é a do cadastro (acima).
- **`strings_os`** ("Strings é OS", Levi, 08/10: o cliente vê as strings das OS do Fracttal, não a régua de 2 h). **1
  linha = OS de recomposição de string × INVERSOR** com a **data do evento** no mês (`mes, data_evento, cliente, usina,
  plant_id, inversor, os, status, strings, qtd, origem`): a OS 13585 da Altair tem seis tarefas, uma por inversor, e
  sai em seis linhas, cada uma com as strings da sua `task_note`. **A chave é (`mes`, `os`, `inversor`)** e não repete
  (`test_strings_os_e_uma_linha_por_os_e_inversor_e_essa_e_a_chave`). O catálogo do Nexus (só na pasta principal, sem
  commit em 11/10) diz (`mes`, `os`) e "1 linha = 1 OS": a frente do Nexus corrige o fato `os_string` para chave (`mes`,
  `os`, `inversor`) e grão "1 linha = 1 OS de recomposição de string × inversor, com a data do evento no mês" — **antes
  do push e do deploy deste trabalho** (regra 10: aba que o catálogo do servidor não conhece cai no radar como nova).
  - Da varredura que a Disponibilidade já faz (`_frac_disp_recalcular`, 30 min): ela guarda `note`, `task_note` e
    `creation_date` da MESMA resposta (`_DISP_CAMPOS_TASK`), o `_falhas_os_string(wos)` grava o índice **`os_string` no
    `frac_disp_index.json`** e o worker das falhas o lê (`_falhas_os_string_indice` → `falhas_job.montar(os_string=)`).
    Erro nesse índice não segura a Disponibilidade: sem a chave, o mês sai sem a aba (vazio, "não publicado").
  - Entra a OS viva cuja descrição tem "recomposi" E "string" (só "recomposi" pegava a OS 15308, alimentação da ETM da
    Inhapi); cancelada fora. Evento = `event_date`, ou a criação, no dia de Brasília — **até 11/10 a varredura não
    guardava a criação** e a OS sem `event_date` ficava fora de todo mês. A nota da OS só vale para OS de um inversor.
    Texto livre não vai ao índice (a nota tem nome de técnico): só o que foi lido dele.
  - Usina pelo código do ativo + prefixo do cliente (`PREFIXO_CLIENTE`: a Ipixuna é IPX100 na Thopen e 2C-IPX100 na 2C);
    na dúvida, sem usina — nunca a de outro cliente.
  - `origem`: `texto` (a linha `Strings sem corrente: N (Ipv3, Ipv7)` que o OS Creator escreve, `_RX_OS_STR_QTD`; o N é a
    quantidade), `citadas` (`_falhas_os_citadas`), `estimado` (evento até `OS_STRING_ESTIMA_ATE` = 31/10/2026, sem linha
    nem citação: as strings que a régua viu sem corrente naquele inversor no dia do evento — Levi, "adapte todas desse
    mês, do nosso lado, sem tocar no Fracttal") e `sem_quantidade` (`qtd` vazio, **nunca 0**: a OS existe, a quantidade
    é que não se sabe). O 0 escrito na OS fica 0.
- **`disponibilidade_dia`** (Levi, 09/10: a Disp (%) "calculada pelo Fracttal, da mesma forma que calculamos pelo
  gerencial da plataforma"). 1 linha = usina do catálogo do Gerencial × dia FECHADO do mês (`mes, dia, cliente, usina,
  usina_fracttal, pot_kwp, disp, h_perdidas`), do mesmo `frac_disp_index.json` da aba Gerencial › Disponibilidade
  (`_falhas_disp_mes`): TODA usina × todo dia, inclusive o 100,0 com 0 h do dia sem OS — sem a linha, ninguém separa
  "100%" de "não medido". `h_perdidas` vai junto porque o `disp` de 1 casa, arredondado, desvia a média do mês. Liga
  pelo nome do Gerencial antes do Fracttal: um site do Fracttal pode ser de duas usinas (Aparecida do Taboado 1 e 2).
  - **Setembro para trás é o BD_Thopen** (15/10/2026, a regra da seção "Disponibilidade do Gerencial: só o Fracttal de
    outubro em diante"): o índice traz o mês anterior a `DISP_SO_FRACTTAL_DESDE` com `fonte: "BD_Thopen"`, só as usinas
    da Thopen e a "Disponibilidade Usina (%)" de cada dia. A `disponibilidade_dia` desse mês sai dela (as outras usinas
    saem do mês); `disponibilidade_os` e `disponibilidade_os_dia` saem VAZIAS (não publicadas: o `_falhas_disp_mes` manda
    `oss: None` e o dia vai sem a chave `os`), nunca "nenhuma OS". No 1º deploy, setembro (que segue o índice do dia 3
    em diante) troca as linhas do Fracttal pelas do BD.
  - O índice tem o mês corrente e o anterior. O mês remontado ganha a dele na volta; **o mês que a volta não remonta e o
    índice ainda tem (o anterior, do dia 3 em diante) segue o índice** (`_falhas_disp_fora_da_volta`, só quando muda):
    setembro foi montado em 02/10, antes da aba, e ficaria sem linha nenhuma, e o Gerencial segue recalculando o mês
    anterior o mês todo (OS fechada com atraso). O mês que sai do índice fica com a última que recebeu.
  - **Janeiro** (revisão adversarial de 11/10): o fim da OS só valia no ano de agora (`disponibilidade.consolidar_os`),
    e o índice é refeito com o relógio de agora — de 01/01 em diante o dezembro perdia toda OS concluída nele e,
    seguindo o índice, saía 100% em todos os dias. Agora vale também o fim no ano do evento (o fim num ano antes do
    evento segue fora). Com as OS reais (`frac_mtta_linhas.json`): setembro e outubro de 2026 iguais, valor a valor, na
    antiga e na nova; dezembro/2025 visto em 05/01/2026 ia de 99,907% (9 usinas abaixo de 100, 9 OS) para 100,0% (0 OS)
    na antiga, e a nova dá o mesmo de 31/12.
- **`disponibilidade_os`** (12/10/2026, Levi, para a janela de Disponibilidade da Visão do responsável do Nexus: "Quero
  também que apareça todas as OSs listadas que formaram aquele valor (...) a OS, que tipo de religamento foi, quanto
  tempo demorou, qual foi o total de perda de energia"). 1 linha = OS da conta × usina do escopo dela (`mes, os, usina,
  usina_fracttal, tipo, origem, codigo_ativo, escopo, kwp, inicio, fim, aberta, duracao_sol_min, perda_kwh`), das `oss`
  do mesmo índice (`_falhas_disp_mes` leva a lista enxuta, sem as excluídas): `tipo` = o tipo da tarefa, `origem` = queda
  ou equipamento, `escopo` = usina inteira, cabine N ou inversor N.M, `duracao_sol_min` = as horas de sol (06–18 h) da OS
  no mês, `perda_kwh` = a perda da OS NAQUELA usina pela régua do Gerencial (kWp afetado × horas, sem irradiação): o
  `kwh_usina` do índice (ver "Disponibilidade por OS"), que o `_falhas_disp_mes` leva e o `_disp_os_linhas` usa — as
  linhas de uma usina somam a perda dela. Sem a descrição nem quem criou (o banco tem leitura aberta). Pela data de início
  (a nova no fim).
  - **A OS de duas usinas leva a perda de cada uma, não a repartição pela potência** (13/10/2026): repartir erra quando o
    teto de 100% pega uma usina e não a outra (e, até 15/10/2026, quando a geração desmentia o dia numa só). A usina do
    escopo fora do `kwh_usina` (nenhuma hora de sol nela) fica com a linha, em 0 — a linha não some (a API guarda
    histórico por linha). O índice de antes
    do campo (`kwh_usina` ausente, até a 1ª varredura do worker com o código de 13/10; o worker do PC ainda o publicava
    às 21:29 de 13/10) segue a repartição pela potência — a única conta possível sem ele. A observação do fato
    `disponibilidade_os` no catálogo do Nexus (`nexus/dados/catalogo.py`) ainda dizia "repartida pela potência" em 13/10.
  - **Prova (13/10/2026)**, sobre a cópia do `frac_disp_index.json` do PC de 21:29 (sem o campo): o código de antes × o
    novo dão `disponibilidade_dia`, `disponibilidade_os` e `atualizacao` iguais célula a célula (setembro e outubro; 910
    e 495 linhas de OS). Com o `kwh_usina` reconstruído pela varredura do módulo (`_varrer`) sobre os eventos do mesmo
    índice — a de uma usina leva o `kwh` dela, como no módulo; a de 2+ usinas reproduz o `kwh` da OS em 35 de 38 (±1 kWh
    nas outras: o índice guarda o kWp com 1 casa) —, mudam só 8 células, todas `perda_kwh` de OS de duas usinas:
    setembro, OS 14351 Rodrigues 1 66.065 → 113.958 e Rodrigues 2 54.627 → 6.734 kWh (47.893 kWh na usina errada);
    outubro, Boa Esperança do Sul OS 16109 (2.093) e 16117 (372) e Rodrigues OS 16114 (5.166: a Rodrigues 2 teve o dia 12
    desmentido e vai a 0). A soma das linhas de cada usina fecha com a perda dela em ±5 kWh (o arredondamento por OS,
    igual antes); antes errava 47.895 kWh na Rodrigues 2 em setembro e 5.166 em outubro.
- **`disponibilidade_os_dia`** (14/10/2026, Dashboard Thopen, Levi: "A partir de outubro quero os comentários 100% OS
  Fracttal. Comentários e disponibilidade! Antes deixe como estava!"). 1 linha = OS × usina × DIA em que ela tirou
  disponibilidade (`mes, dia, usina, usina_fracttal, os, tipo, origem, escopo, kwp, inicio, fim, aberta, trechos,
  h_perdidas`): `h_perdidas` = as horas equivalentes que a OS tirou da usina no dia e `trechos` = os horários das 06–18 h em
  que ela foi dona da perda (`"06:00-08:06; 10:55-12:05"`). Sai da MESMA varredura da `disponibilidade_dia`: o `_varrer`
  ganhou o `det_os_dia` (a parcela de cada dono em cada segmento, `frac_af × kWp ÷ ΣkWp dos donos × horas`) e o
  `calcular` põe a lista em `diario[u][dia]["os"]` (`_os_do_dia`); o `_falhas_disp_mes` leva e o `_disp_os_dia_linhas`
  publica. **As linhas de uma usina num dia somam o `h_perdidas` dela** (por construção); a OS de cabine coberta por uma
  de usina inteira só tem os trechos fora dela (até 15/10/2026 o dia que a geração desmentia também não tinha linha).
  - **Por que existe:** o 5080 escrevia o comentário do dia refazendo a conta com as OS do mês (`disponibilidade_os`,
    início e fim) e errava: a Canarana 1 de 08 a 12/10 aparecia com "usina parada o dia todo" ao lado de 87,5% (a geração
    desmentiu a OS de usina inteira e só o inversor 1.8 contou). Refeita fora daqui, a conta não pega a exclusão nem a
    hierarquia (nem, até 15/10/2026, a geração); a parcela tem de vir da varredura.
  - **Prova (14/10/2026)**, sobre a cópia do `frac_disp_index.json` do PC de 14:14 (sem a parcela): os eventos refeitos
    das `oss` do índice (escopo, `dias_exonerados`, sem as excluídas) e o `_varrer` novo reproduzem o `h_eq` de TODOS os
    1.203 dias-usina com perda (810 de setembro, 393 de outubro) e a soma das parcelas fecha com ele em todos; nenhum dia
    com perda sem OS. No 5080 de ensaio com as duas abas desse índice: 250 dias abaixo de 100% em outubro, todos com OS
    (315 linhas), nenhum dia de 100% com OS.
  - Índice de antes do código (sem a chave `os` nos dias, até a 1ª varredura do worker depois do deploy): a aba sai vazia
    e a `atualizacao` conta VAZIO — o 5080 diz "ainda não publicado", nunca "sem OS". Testes:
    `tests/test_disp_os_do_dia.py` (a parcela e a hierarquia), `tests/test_falhas_publicar.py` (a aba e a contagem) e o
    gabarito de `tests/test_disponibilidade_tela_13_10.py` (a saída de antes + a parcela somando o dia).
- **`atualizacao`** ganha no fim `cobertura`, `strings_os`, `trackers_dia`, `disponibilidade_dia`, `disponibilidade_os`
  e `disponibilidade_os_dia` (as linhas de cada aba no mês; a das OS conta vazio no pacote de antes de 12/10/2026, e a
  parcela do dia no índice de antes de 14/10/2026). **Aba que o pacote não montou conta VAZIO, não 0** (0 diria "nenhuma OS" / "nenhuma usina medida" onde só não
  houve publicação); a montada e vazia conta 0.
- **Janela (é condição, não data):** o worker remonta só o mês corrente (e o anterior até o dia 2). Mês montado antes do
  deploy fica sem `dias_comunicou`/`dias_sem_prova` e sem linhas em `cobertura`, `strings_os` e `trackers_dia`
  (contagens vazias) até ser remontado — setembro para sempre; outubro na 1ª volta depois do deploy. A `strings_os` só
  ganha linhas depois da 1ª varredura da Disponibilidade com este código (até 30 min).
- Exceções ao "nada muda a cada volta": os `dias_*` da `cobertura` sobem a cada dia (e o vazio de uma régua vira número
  no dia em que ela registra o cadastro), o `dias_sem_prova` volta a 0, o status da OS muda quando ela fecha, a
  estimativa de outubro cresce durante o dia do evento, o "sem prova" vira "sim" (ou sai) quando a geração do dia chega
  e a disponibilidade do mês anterior acompanha o Gerencial. Uma vez, no deploy: a fonte dos 29 cadastros da API PV de
  5 dígitos passa de Banco a API PV no mês corrente (setembro fica como foi montado). Outra, no deploy de 13/10/2026: a
  `perda_kwh` das OS de duas usinas passa da repartição pela potência à perda de cada usina — também em setembro, que o
  `_falhas_disp_fora_da_volta` regrava porque a disponibilidade do índice mudou (no índice de 13/10, 8 linhas: Rodrigues
  e Boa Esperança do Sul).
- **Ensaio com o dado real do PC (11/10, 21:26; rede cortada, nada gravado; geração vazia, então `dias_comunicou` só
  pela leitura de strings):** o `falhas_job` de antes e o novo sobre os MESMOS stores dão o MESMO pacote em tudo o que
  já existia (só entram `cobertura` e `trackers_dia`); o workbook de setembro + outubro tem 1,19 MB — `trackers_dia` 589
  (575 "sim", 14 "sem prova"), `disponibilidade_dia` 5.200 (130 usinas × 30 + 10 dias), `strings_os` 0 (o índice do PC
  ainda não tem `os_string`); 0 chave repetida (as do catálogo; na `strings_os`, mês + OS + inversor) e 0 `plant_id`
  vazio; a soma das horas do dia dá o mês do Gerencial nas 130 usinas dos dois meses. A `cobertura` desse ensaio (192
  linhas) ainda tinha as linhas partidas; com a revisão adversarial são 159 (ver "Fonte do tracker pelo cadastro").
- Governança (regra 10 do Nexus): aba ou coluna nova aqui = registro no catálogo do Nexus no mesmo trabalho. **Em 11/10
  os quatro fatos (`falha_tracker_dia`, `cobertura_falhas`, `os_string`, `disponibilidade_dia`) só existem SEM commit na
  pasta principal do Nexus** — nem no origin/main nem no worktree `nexus-acessos`: o push/deploy deste trabalho espera a
  frente do Nexus commitá-los, com a chave da `os_string` em (`mes`, `os`, `inversor`), a observação da
  `cobertura_falhas` dizendo que a fonte é o sistema (a String Box na linha da API PV) e que vazio é "a régua não
  registrou o cadastro", e a do `falha_tracker` com "volta a 0 quando a geração do dia chega".
- Testes: `tests/test_falhas_workbook_abas.py` (o caminho do worker de ponta a ponta com o Fracttal e a API do banco
  dublados: varredura → índice → volta das falhas → um POST com as 8 abas; zero medido × vazio; o "gerado em" não sobe
  o workbook; o mês não remontado segue o índice; o erro do índice das OS não segura a Disponibilidade),
  `tests/test_falhas_operacao_cliente.py` (a montagem: comunicou, sem prova — também o dia que a geração ainda não
  cobre —, cobertura por sistema com o vazio da régua que não registrou, a fonte do tracker pelo cadastro com a chave e o
  "desde" de antes, os quatro gravadores com a `fonte`, OS de string e a origem da quantidade, trackers por dia, colunas
  só no fim, contagem vazia × 0; e, de 13/10, o índice de verdade → `_falhas_disp_mes` → aba: a soma das OS de cada
  usina fecha com a perda dela, e o índice sem `kwh_usina` volta a repartir pela potência), `tests/test_falhas_publicar.py`
  (a perda de cada usina pelo `kwh_usina`, a usina sem perda em 0), `tests/test_disp_fracttal.py` (o dezembro em
  janeiro; o fim digitado num ano antes do evento) e `tests/test_relatorio_semanal.py` (a semana da virada).

### Strings e trackers: tabela única, Vincular OS e download (20/10/2026) — o backend

Pedido do Levi (20/10): nas strings, uma tabela só, por inversor (a OCORRÊNCIA: as paradas de string do inversor que se
encostam no tempo), com quantidade de strings, parada, retorno, drill diário para mais de um dia, download e "1.5 Opção de
vincular OS, eu clico no botão e buscas as OSs de recomposição de string desse inversor (...) 1.7 A OS só carrega se eu
clicar em vincular, caso eu não clique não deve carregar nem fazer requisição alguma do fractal"; "1.8 faça algo parecido
com os trackers!"; sem o filtro de fonte. A ocorrência é montada na TELA a partir do pacote; aqui fica o que a tela pede
ao servidor. Nenhuma régua, filtro ou limiar novo: tudo reaproveita a régua que existia.

- **Pacote** (`falhas_job.montar`; o workbook não muda — o `falhas_publicar` escreve colunas explícitas):
  - `trackers.rows[].dias` = `[[dia, de "HH:MM", até "HH:MM", horas, kWh, comunicou], ...]`: o que a conta da perda JÁ
    fazia por dia e jogava fora, para o drill da parada de mais de um dia. Horas e kWh repartidos pelas somas acumuladas
    arredondadas (`_reparte`): os dias somam o `h_sol` e o `perda_kwh` da linha, sem sobra. O dia em que o TRACKER
    ficou sem comunicação não entra (atravessa, como na perda); `comunicou` é da USINA no dia, a régua do
    `dias_comunicou`: "sim", "sem comunicação" (dia fechado sem prova) ou "sem prova" (a geração ainda não cobre).
    Pacote de antes (setembro) não tem `dias`. Medido sobre o registro de trackers do PC de 20/10 (outubro, 4.826
    paradas, 9.354 tracker-dias = 1,94 por parada): +0,55 a 0,68 MB no JSON cru, +51 a 54 KB no gzip que o Flask-Compress
    manda (a parte dos trackers: 119 → 170–173 KB); 0 das 4.826 paradas com a soma dos dias diferente da linha.
  - `strings.rows[].plant_id`: o cadastro da linha inversor × dia. O drill casa o dia com a ocorrência por fonte +
    `plant_id` + inversor, e cinco usinas têm mais de um cadastro (Altair 4, Guatambu 3, Indaiatuba 2, Mandaguaçu 2,
    Santo Antonio do Platina 2). A linha segue no grão de sempre (usina × inversor × dia: é a chave da
    `falha_string_inversor_dia` no catálogo do Nexus e o `n` do `por_cliente`); quando dois cadastros têm o MESMO nome de
    inversor no dia, ela leva `plant_id` None e a linha de cada um em `cadastros` (mesmos campos, com o `plant_id`). A tela
    casa cada item de `cadastros` pelo plant_id DELE (a linha somada não entra em ocorrência nenhuma) e só usa a reserva por
    fonte + usina + inversor na linha SEM o campo `plant_id` (pacote de antes), dia a dia — até a revisão de 20/10 ela
    ignorava o `cadastros` (ver "Drill" acima; teste com o formato exato em `tests/test_falhas_ocorrencias.py`). Nos
    stores do PC de 20/10 é a Itajá (18749574 e 18749576, INVERSOR01 a 04, 24 linhas; no pacote do servidor, nenhuma) — e
    ela parece o MESMO inversor cadastrado duas vezes: as mesmas 11 strings e a mesma perda nos dois, e a linha de sempre
    soma os dois (1.570,9 kWh no dia, `dur_h` 24 h). Antiga × nova sobre os stores do PC (outubro, mesmo "agora", sem
    geração): 8.744 linhas iguais sem o `plant_id`/`cadastros`, 4.826 paradas de tracker iguais sem os `dias`, o resto
    do pacote igual e o workbook igual célula a célula.
- **Busca de OS** — `GET /api/painel/falhas/os?tipo=strings|trackers&fonte=&plant_id=&usina=&inversor=&tracker=&desde=`,
  a ÚNICA chamada da tela ao Fracttal, só no clique: 2 a 4 pedidos com o cache frio (code → ativo, guardado 12 h;
  ativo → OS, 10 min), 0 no mesmo ativo dentro do cache. Resposta `{ok: true, ativo: {code, nome} | null, motivo?, os: [{folio,
  status, tipo, criada, evento, concluida, descricao (≤160), strings (só nas strings), anterior, link "/os/os/folio/<n>"}],
  buscado_em}`, a mais nova primeiro; datas "AAAA-MM-DD HH:MM" no relógio daqui (`_frac_dt_local`); `concluida` = a
  MAIOR `final_date` das tarefas (como o card do ticket), só com a OS concluída; `anterior` = evento antes de `desde`.
  - **Strings**: ativo `{código}-INVR{N.M}` com o código da Info Geral (`_tk_str_cod_bruto_da_linha`), **nunca o
    `_frac_codebase`**: com o índice de ativos vencido (o do PC era de 13/10) ele varre ~150 páginas de `items/` dentro do
    clique. Código de dois clientes (IPX100: "IPX100" é a Ipixuna da Thopen, "2CIPX100" a do Pará da 2C): só o ativo do
    cliente da usina (2C-IPX100-INVR1.1 para a 2C; o sem prefixo e o THPN para a Thopen) — nunca o do outro cliente.
    Filtro = a régua do `strings_os` ("recomposi" E "string", sem acento, cancelada fora), agora numa função só
    (`_falhas_os_vivas_de_string`), que o `_falhas_os_string` também usa. Casos: Guatambu 1.2 (01 a 20/10) → OS 16561, em
    andamento, evento 01/10 (no índice: THPN-GTB100-INVR1.2, Ipv18); Mandaguaçu 4.4 (01 a 15/10) → só a 9915, de 23/07,
    que vem `anterior`. As strings citadas leem descrição, instrução e nota de cada tarefa do ativo (`_falhas_os_citadas`;
    na OS de vários inversores a nota pode citar string de outro — a 16561 tem seis).
  - **Trackers**: o "Code Fracttal" do de-para dos trackers (`trackers_depara.xlsx`, o mesmo do "Criar OS" de tracker),
    casado pelo nome do CADASTRO do `plant_id` (`_falhas_trk_nome_cadastro`, do registro `_trk_eventos`: é o nome do drill
    do Monitoramento, "Altair 3 (75)") e pelo número do tracker. A linha da aba traz a usina canônica ("Altair" = 1 a 5) e
    o número se repete entre as sub-usinas: em outubro, pelo canônico, 365 dos 1.335 trackers ficavam ambíguos; pelo
    `plant_id`, 1.061 com code e nenhum ambíguo (133 em usina fora do de-para, 141 sem Code Fracttal). Número repetido com
    codes diferentes só vale pelo nome exato; sem o cadastro do `plant_id`, a canônica de várias sub-usinas não chuta.
    OS = todas as não canceladas do ativo (a OS de tracker é uma por tracker). Sem code (a 2C/owen, fora do de-para — a
    Sete Lagoas Tracker 1.49 tem a 15481 no SLG200-ETKR49.200, e a regra "Tracker 1.N = ETKR N.200" não está combinada —
    ou o tracker "sem par") → `ativo: null` com o motivo, sem pedido ao Fracttal.
  - **Fracttal sem resposta** (429 da cota, rede, 5xx, token): **502** `{ok: false, fonte_ok: false, motivo: "o Fracttal
    não respondeu (...)"}` — nunca "sem OS" (o card do ticket chama sem `falhas=` e mostra o 429 como "inversor não
    achado"). Nas STRINGS, com OS do mesmo inversor (código + N.M, o cliente pelo prefixo) no índice `os_string` da
    varredura de 30 min da Disponibilidade, a reserva responde 200 `{ok: true, fonte_ok: false, reserva: "varredura",
    varrido_em, motivo, ativo, os}` (sem tipo, criação, conclusão e descrição: o índice não guarda texto livre). Sem
    credencial do Fracttal: 503.
- **O vínculo gravado** (`falhas_vinculos.py`, a regra pura; a leitura e a gravação são a `cobertura.Decisoes` do
  `_FV_DECISOES`, no molde do `_DP_DECISOES`: cache de 60 s, a última leitura boa em `falhas_vinculos.json` do cache,
  `GRIDCO_SQL_TOKEN` para gravar; PC e servidor leem o MESMO livro). Livro `nexus_falhas · fato_decisao_vinculo_os`,
  REGISTRADO no catálogo do Nexus pela frente do Nexus antes da 1ª gravação (regra 10); aqui só se grava. CAB
  `decidida_em, data_id, tipo, fonte, plant_id, equipamento, data_id_inicio, os, decisao, origem`: o dia do início vai
  como PAPEL em AAAAMMDD (regra 7) e a API da tela segue com `dia_inicio` "AAAA-MM-DD" (a conversão mora no módulo).
  Só acrescenta; vigente = a última decisão de cada (tipo, fonte, `plant_id`, equipamento, `data_id_inicio`, os).
  Sem pessoa nem texto (regra 8): quem vinculou vai a `logs/falhas_vinculos.log` (`_quem_na_sessao`). Só a FORMA de
  id e de equipamento passa (revisão de 20/10: o livro é de leitura aberta, nunca se apaga, e aceitava "Fulano da
  Silva" no `plant_id` e telefone com quebra de linha no equipamento, que ainda forjava linha no log): `plant_id`
  `[A-Za-z0-9_.:-]{1,40}`, equipamento `[\w .,#/()+-]{1,40}` com um número (medido nos pacotes de set. e out.: todos
  passam, o maior tem 13 caracteres), OS de 1 a 10⁹.
  - `GET /api/painel/falhas/vinculos` → `{ok, vinculos: [{tipo, fonte, plant_id, equipamento, dia_inicio, os,
    decidida_em}], lido_em, erro?}` (só os `vincular`); banco fora = a última leitura boa + `erro`; nenhuma = `ok: false`.
  - `POST` `{tipo, fonte, plant_id, equipamento, dia_inicio, os, decisao: vincular|desvincular}` → confere tudo (400 com
    o motivo), acrescenta (relê, grava, confere; e a trava contra apagar o histórico, em "Fontes do tempo real") →
    `{ok, vinculos}`; não gravou → 500 com o motivo. **Fonte = as do pacote da aba** (`pv, pvsb, pg, sunop, axis, owen,
    solaredge, greenyellow, salenergia, apolo`, o `FONTE_ROT` do workbook), não as da `cobertura.FONTES`, onde a 2C é `2capi`:
    a 2C dos trackers (owen) e a String Box (pvsb) seriam recusadas. Em `GRAVACOES_GESTOR`: o gestor leva 403.
- **Tirar da conta em lote**: o `POST /api/painel/falhas/desconsiderar` aceita `chaves: [...]` (até 60, cada uma
  conferida como a `chave`, numa gravação só, tudo ou nada) e `resumos: {chave: resumo}` (sem ele, o `resumo` vale para
  todas). A caixa da ocorrência tira as chaves de todos os episódios dela (a Inhapi 3.3 são 4; uma linha de outubro
  chegou a 33). `chave` sozinha segue valendo (trackers).
- **Exportar Excel** — `POST /api/painel/falhas/exportar`, corpo `{nome, abas: [{nome, colunas: [{titulo, tipo:
  texto|inteiro|numero|data|datahora}], linhas: [[...]]}]}`: a TELA manda as linhas que mostra e o servidor só formata
  (não refaz o filtro nem abre o pacote no web). Número e data viram célula de número e de data de verdade (`#,##0.0`,
  `0`, `dd/mm/yyyy`, `dd/mm/yyyy hh:mm`); a datahora só com o dia (o tracker que voltou em hora não registrada) vira data,
  sem 00:00 inventado; texto que começa com "=" fica texto, inclusive no título da coluna (revisão de 20/10: o título
  "=HYPERLINK(...)" saía como fórmula), e caractere de controle (\x01, \x0b) dá 400 com o motivo, não 500. Até 600 mil
  células somando as abas (o mês de trackers do PC tem ~190 mil e leva ~9 s; 30 mil × 40 levavam ~62 s com uma thread
  do waitress presa, pelo escritor XML do openpyxl sem lxml). Cabeçalho navy das exportações, painel congelado, autofiltro e
  largura; write-only (30 mil linhas não montam célula a célula na memória do web). Limites, 400 com o motivo: até 4
  abas, nome de aba de 1 a 31 caracteres sem `[ ] : * ? / \` (e sem repetir), até 40 colunas, até 30.000 linhas somando
  as abas, texto até 500 caracteres; corpo acima de 16 MB, ou sem tamanho declarado, 413 (o Flask desta plataforma não tem
  `MAX_CONTENT_LENGTH`). Nome do arquivo sem acento + `.xlsx`. Consulta, não gravação: em `POSTS_DE_CONSULTA_GESTOR`
  (o gestor também baixa). Prova (20/10): amostra com as linhas reais de outubro (Inhapi 3.3, Guaratinguetá V 1.3,
  Guatambu 1.2, Mandaguaçu 4.4; Sete Lagoas e Altair nos trackers) aberta no Excel pelo COM, só leitura: as três abas, a
  data como data ("01/10/2026 06:30", série 46296,27), o número como número ("8.024,8", a soma da coluna igual à do JSON),
  a volta sem hora como data ("17/10/2026").
- **O gestor** (porta única): a busca e a leitura dos vínculos passam pelo prefixo `/api/painel/falhas` do
  `_GET_GESTOR` (um clique dele chama o Fracttal, como já chama na `/api/fracttal/os`); o POST dos vínculos é gravação.
  A ponte (`X-Nexus-Leitura`) segue sem a aba.
- Testes: `tests/test_falhas_vincular_os.py` (a busca com o `_frac_get` dublado e o `_frac_ativo`/`_frac_wos_raw` de
  verdade por cima, o índice de ativos proibido; o código de dois clientes; o 502, a reserva e o 503; trackers com e sem
  code; os vínculos com o banco de mentira; o gestor), `tests/test_falhas_exportar.py`, `tests/test_falhas_dias_e_plant_id.py`
  (os dias somam a linha, o dia sem comunicação do tracker, o `plant_id` por cadastro, o workbook igual),
  `tests/test_decisoes_trava_historico.py` e os de lote em `tests/test_falhas_desconsiderar.py`. O `conftest.py` aponta o
  `_FV_DECISOES` para um endereço que recusa na hora e o log para o `tmp_path` (`_vinculos_das_falhas_sem_banco_por_padrao`).

## Relatório Semanal Thopen (`/relatorio/semanal`, 29/09/2026)

Relatório para o CLIENTE Thopen, toda segunda até as 12h (Ana Patrícia e Levi, reunião de 28/09; spec em
`docs/superpowers/specs/2026-09-29-relatorio-semanal-thopen-design.md`). As contas moram em `relatorio_semanal.py`
(puro, sem rede: `tests/test_relatorio_semanal*.py`); o `app.py` só junta os leitores (`_RelSemLeitores`: BD_Thopen,
índice de disponibilidade, OS do worker, aba de falhas, rondas). Os campos do analista (leitura, responsável, causa,
ação, previsão) gravam em `relatorio_semanal.json`; "Emitir PDF" registra a versão (R00, R01…) com o que foi ao cliente.

**Considerações do Levi em 05/10/2026** (`tests/test_relatorio_semanal_verificacao.py`):
- **Usina sem IPOA medido entra no PR, com asterisco, em tudo** (resumo, bloco 05, curva de evolução): no dia com
  geração e IPOA vazio ou zero, o PR usa a irradiação de referência do cliente (meta de IPOA do mês ÷ dias do mês)
  **corrigida pelo sol do dia** (`fator_sol`: a MEDIANA de IPOA medida ÷ referência das usinas que mediram — mediana
  porque uma ETM ruim puxaria o dia de todos). IPOA medido abaixo de 0,3 kWh/m² segue fora, como no Histórico PR.
  28/09–04/10: 18 usinas; PR do portfólio 78,1% só medido → 72,9% com a referência pura (semana a 81% da referência)
  → **75,5% com a correção** (decisão do Levi).
- **Bloco 06 "Pontos em verificação pela Grid"** no fim, em texto para o cliente (sem nome de planilha): geração ×
  disponibilidade incoerente, ETM medindo alto ou baixo e as usinas pela referência (numa linha só). O dia que a coleta
  ainda não gravou para a maioria das usinas fica fora (`COLETA_MIN_FRAC`): a coleta das 22:30 grava o dia ANTERIOR, e na
  segunda de manhã o domingo não está no BD_Thopen — em 28/09–04/10 eram 51 dos 65 avisos.
- **Card de geração, 2ª linha**: "Atingimento de geração pela meta do IPOA" = geração dos dias com IPOA medido ÷ (meta
  de geração desses dias × IPOA real ÷ IPOA de referência).
- **Causa principal pega a ETM**: em 30 dias, geração ≥ 100% da meta e IPOA medida 10 pontos ou mais acima da geração →
  "Irradiância acima do esperado (sensor)". A Vertentes gerou 107% da meta com a IPOA a 132% e o bloco 05 dizia
  "Trackers parados". PR acima de 130% em 3+ dias dos últimos 30 = ETM medindo baixo, só no bloco 06.
- **Campos editáveis** com `contenteditable="true"` (não "plaintext-only", que navegador antigo não conhece) e colar
  como texto puro. A edição é na página, antes de emitir: o PDF não é editável.

## Relatório Potência Ativa dos Inversores (`/relatorio/potencia-ativa`, 13/10/2026)

Levi: "Teria como ter um novo relatório de performance pegando a potência ativa de cada inversor e sobrepondo por dia.
Cada inversor terá uma cor diferente. Se chamará relatório Potência Ativa dos Inversores!". Fonte e usina (as da tabela
do Tempo real, lidas da memória: nada é montado), período de 1 a 7 dias → um gráfico por dia, uma linha por inversor
(kW, média de 5 min; mais de 15 min sem leitura quebra a linha), legenda com o nome do cadastro, tabela por dia,
Imprimir/PDF (A4 deitado, sempre claro). Contas em `potencia_ativa.py` (puro); leitores e rotas no bloco "RELATÓRIO
POTÊNCIA ATIVA" do `app.py` (`/api/relatorio/potencia-ativa?fonte&usina&ini&fim` e `/usinas`); tela
`templates/potencia_ativa.html`, que pede UM dia por vez.
- **De onde vem a potência** (nenhuma leitura nova a fonte paga; cada leitor é a leitura que outra tela já fazia):
  API PV (Thopen API PV, 2C, SEMP, Alves Lima) = o `Pac` das MESMAS leituras da Curva das strings (`_spv_day_records`:
  hoje o day_inverter; dia passado o `_spv_day_records_hist`, 1 consulta da cota histórica por usina e dia, 20 na Tupi
  Paulista), nome do inversor pelo caminho do drill; Banco da Thopen = o `active_power` do `raw_inverter`, a consulta da
  correlação do drill (`_pg_series_inversores`) para qualquer dia, com 45 s de teto; GreenYellow = o `pot` que a telemetria
  MQTT já traz na curva da aba Curva (`_sg_curvas`, 45 dias); RenoGrid = **potência CC**, a soma das strings de cada
  inversor de 15 em 15 min, pela curva das strings do drill (`_se_strings_curva`; site e dispositivos guardados 30 min em
  `_PA_SE_ESTRUTURA`). A SolarEdge não entrega a potência ativa (CA) do inversor: a fonte tem `grandeza` "Potência CC", o
  rótulo diz "(potência CC)" e a página escreve a grandeza no cabeçalho (Levi, 13/10/2026: "Quero sim"). Lote de strings
  que falhou e resposta sem nenhuma string (a SolarEdge sob limite responde 200 vazio) são falha, não "sem dado".
  **Sem histórico, e a tela diz o porquê**: Sal Energia (Modbus: histórico só por string). **Athon e Axis saíram** (Levi,
  13/10/2026: "Não, por hora pode tirar Axis e Athon"): o histórico de `P` seria pedido novo à SunOp, fonte paga de cota
  estourada, ~1 por usina e dia; voltam se ele pedir.
- **Teto de 7 dias** (`MAX_DIAS`): a cota histórica da API PV é da conta (800/dia, 200/h, dividida com a combiner e a
  coleta da noite), o scadaGridco atende um pedido por vez (um por inversor e dia) e 7 gráficos são uma semana. O relatório
  não gasta a cota abaixo de 450 no dia ou 40 na hora (`PA_COTA_RESERVA_*`, a régua do backfill das falhas); o dia que o
  drill já baixou cru (`_spv_hist_recs`) não gasta nada; id de usina que a plataforma não conhece é 400 antes da API PV.
- **Cache no web** (`_PA_CACHE`, 40 dias): dia que já acabou e veio com leitura fica até reiniciar; dia sem leitura na
  fonte, 6 h; hoje, 5 min; **falha não fica guardada** e aparece como "a fonte não respondeu (motivo) — não é usina
  parada", com "Tentar de novo"; "sem dado" é a fonte respondendo vazio. Inversor que a fonte listou sem potência, ou que
  faltou num dia, é dito embaixo do gráfico, nunca uma linha em zero.
- **Cores** (skill dataviz): as 8 da paleta categórica em ordem fixa, degraus próprios no claro e no navy, validadas pelo
  validador da skill contra `#ffffff` e `#161d30` (no claro, aqua, amarelo e magenta abaixo de 3:1: o alívio é a tabela
  do dia). Mais de 8 inversores = cor × traço (6 traços, até 48 por gráfico; passou, o dia vira dois gráficos), nunca uma
  9ª cor; a cor segue o inversor pela ordem natural da união dos dias. Sem rótulo na ponta da linha: as curvas convergem
  no amanhecer e no pôr do sol; a legenda (passar o mouse destaca, clicar esconde) e a dica com todos os inversores fazem
  esse papel. A régua de ordem natural é a mesma no Python e no JS (há teste).
- **Nexus**: a página já sai pronta para a moldura (`data-casca` na marca, na navegação e no botão de tema; no modo Nexus
  segue o tema do Nexus pelo `window.gcModoNexus`, como o Painel NOC). No mapa desde 13/10/2026 como
  `relatorios|potencia-ativa|/relatorio/potencia-ativa||`: no Nexus abre por Relatórios → Central de emissão, com os
  outros relatórios, filtrada pelo setor. As APIs já estão no `_GET_GESTOR`
  (`/api/relatorio`); para o gestor a API PV fica de fora e só o dia que um analista já leu aparece.
- Prova: `tests/test_relatorio_potencia_ativa.py` (a rota com 2 inversores × 2 dias, o teto, sem dado × falhou, a cota,
  o gestor, os três leitores com a fonte dublada, a lista de usinas e o JS da página no node). A tela foi conferida num
  Chrome sem janela abrindo o template como arquivo, com o `fetch` dublado e a rede cortada (proxy morto): escuro, claro,
  390 px dentro de iframe (o Chrome sem janela não desce de ~500 px de largura) e o PDF.

### No Tempo real: ··· → Potência + POA e GHI (27/10/2026)

Levi: "Em relatórios > performance temos a Potência Ativa dos Inversores. Quero que vá para os três pontos no tempo real
e seja Potência Ativa dos Inversores + POA e GHI / E POTÊNCIA ATIVA DA USINA + POA E GHI!". São duas abas do Monitoramento
embutido (`potinv` e `potusina`), abertas pelo ··· da Entrada (`/tempo-real/<fonte>?view=potinv`): uma usina (a lista da
aba Strings, em ordem alfabética) e um dia (hoje por padrão) por vez.
- **Só onde há histórico**: o ··· mostra as duas só nas fontes do relatório (`POT_FONTES` da Entrada; Athon, Axis e Sal
  Energia não têm, e um teste amarra a lista ao `potencia_ativa.FONTES`). Na 2C só entram as usinas da API PV (id
  numérico, fonte `2capi`); as da Owen não têm potência por inversor. RenoGrid é "Potência CC"; RenoGrid e GreenYellow
  não expõem a estação por usina, então o rótulo delas não promete o POA/GHI. O "Perdas" saiu do ··· no mesmo dia (Levi:
  "Pode tirar perdas"): a aba acabou no 03fa176 e o item não abria nada.
- **De onde vem**: a potência é a rota do relatório (`/api/relatorio/potencia-ativa`, ini = fim = o dia: o mesmo cache,
  a mesma reserva da cota histórica da API PV); o POA/GHI é a rota do gráfico do ETM (`_etmChartUrl`). A API PV só
  entrega a curva da estação do dia de HOJE (`day_meteo`): dia passado mostra a potência e diz que não há POA/GHI. Nada é
  lido antes de escolher a usina; hoje fica 5 min na tela (o "Atualizar" relê na hora), dia passado lido não é relido,
  falha nunca fica guardada.
- **Um gráfico, dois eixos** (Levi, 27/10/2026, no print da Araputanga: "quero que o IPOA e GHI fique junto do gráfico
  da geração/potência ativa"; antes eram dois gráficos empilhados): kW à esquerda, W/m² à direita (`_potSvg(..., dir)`).
  `_potTicksPar` dá à direita o MESMO número de intervalos e o zero na mesma linha, com o passo 1-2-2,5-5 × 10ⁿ que cobre
  o maior POA/GHI: cada linha de grade é marca dos dois eixos. O POA/GHI é desenhado por baixo da potência; a legenda diz
  "POA (W/m²)". Sem a potência, o POA/GHI ocupa o gráfico sozinho. O balão segue com a potência do passo de 5 min e o
  POA/GHI mais perto dele. Inversores com a paleta do relatório (8 cores × traço); POA e GHI em tinta neutra.
- **A usina = a soma dos inversores, só nos passos em que todos os que leram no dia leram**: no passo em que um ficou sem
  leitura a linha falha (somar só os que leram desenharia uma queda que não houve), e a tela conta esses passos.
  Inversor sem leitura o dia inteiro fica fora da soma e é dito; inversor que não veio da fonte também, com o aviso de
  que a usina gerou mais que a linha.
- **Pelo Nexus**: a rota da potência entrou na lista da ponte (`leitura_nexus._GET`; o gestor já a tinha em
  `/api/relatorio`). Pedido do Nexus não abre a API PV: o dia vem "falhou" com o motivo do perfil (só o que um analista já
  leu aparece) e o `/api/etm/chart` segue negado, então pelo Nexus a API PV fica sem POA/GHI; o banco mostra os dois.
- **Banco da Thopen lento (27/10/2026)**: na produção a consulta da potência estourou o teto de 45 s para a Aparecida do
  Taboado 1 (hoje e 26/10); daqui do PC a mesma consulta levou 119 s para 14 linhas, com o plano no índice
  (power_plant_id, timestamp) de cada chunk. A aba (e o relatório) diz "o banco da Thopen não respondeu"; o POA/GHI do
  banco veio.
- Prova: `tests/test_tempo_real_potencia.py` (a lista do ··· × relatório, nada lido sem usina, as rotas por fonte, a
  Owen fora, cache e falha, a soma que só fecha com todos, as mensagens e o nome escapado, rodando o bloco da tela no
  node). Tela conferida numa bancada (Entrada e Monitoramento do worktree; linhas e POA/GHI reais do banco pela produção,
  potência sintética porque o banco estourava) em 1280 px: mira alinhada nos dois gráficos, balão, modo usina e as falhas.
