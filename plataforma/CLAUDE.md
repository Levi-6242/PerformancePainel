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
a ronda morre em silêncio. **O guardião só reconhece o `app.py`/`worker.py` DESTA pasta** (`_eh_da_plataforma`, 29/09/2026):
antes, qualquer python com "app.py" na linha de comando contava — o do Nexus (temp/Nexus/app.py) também —, e depois do
reinício das 17:43 a 5050 ficou fechada 20 min com o guardião rodando de 5 em 5. Teste: `tests/test_ronda_guardian.py`.

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
- **Curva de tracker das usinas numa baixa só** (`_sunop_trk_curvas_varias`, mesmo método das strings de 02/09:
  cheia junto em 00:00, incrementais na menor janela; regras em `_sunop_trk_janela`/`_sunop_trk_funde`), chamada antes
  do laço no resumo, na disponibilidade e nos parados: 9 POSTs viraram 3. Nova × antiga real: 80.338 pontos, diferença
  só no quarto de hora ainda aberto (a média dele anda entre as buscas).
- **A Entrada conta os parados da Athon pelo resumo do worker** (`_entrada_trk_do_resumo`, resumo de até 30 min): o
  processo web refazia as curvas de tracker a cada 30 min só para contar. Parados iguais nas 9 usinas (97); "com
  ticket" pelo `parados_com`, o da coluna Tickets.
- **O contador diz de quem é a curva**: `analog_values:trk`, `:str`, `:etm` (pelos pathnames do pedido).
- **O gêmeo do servidor está vazio** (29/09: `/gemeo/healthz` 503 "modelar nunca rodou", 0 usinas): no servidor a
  curva nunca vem do acervo e vai toda à SunOp. O gêmeo com dado é o do PC.

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
um teste confere que os nomes existem no laço). Não troque o disjuntor por timeout menor: a API LENTA (48 s por
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
= soma dos W das strings) e a 2C do e-mail (`_owen_fora_da_conta`: soma das correntes, que zera quando ele desliga).

**Inversor SEM LEITURA HOJE também é desligado (25/09/2026)**, com os outros da usina gerando e com sol — Levi: "o
inversor 1.3 de Colorado 2 está desligado, a plataforma não conta como desligado". O 3º portão da régua ("sem leitura
não é desligado") tem uma exceção, o `sem_leitura` de `_inv_desligados_por_potencia`, e cada fonte diz o que é "nada
hoje": API PV = inversor do cadastro fora do `day_inverter`, só se a conta fecha pelo nome (`build_summary`); SunOp =
nenhuma corrente numérica, ou só de outro dia, e a potência de outro dia não vale (`_sunop_regua_hoje`, a mesma na linha
e no drill); Banco = última leitura de outro dia (a tabela guarda 30 dias); SolarEdge = todas as strings dele
**devolvidas sem potência** — string AUSENTE da resposta é throttling (200 vazio) ou lote falho e não vale; 2C do e-mail
= inversor do cadastro fora do e-mail do dia, só se a conta fecha (`_owen_ausentes`). Usina inteira sem leitura continua
sendo "sem comunicação" da usina (TIM100 em 25/09: os 50 com a última leitura de 24/09 06:23 — ninguém vira desligado).
Medido em 25/09 com os mesmos dados, antiga × nova: RenoGrid mudou 3 de 7 (Crateus 75/362 −287 → 75/75, 40 desligados
das cabines 1 a 4; Xavantina 2 −13 → +3, porque o cadastro diz 6 e 7 esperadas nos inversores 3.4 e 3.5, que têm 8
strings ativas; Elias Fausto −6 → 0), Banco 0 de 22, 2C do e-mail 0 de 4, Athon 0 de 10. O drill do Banco
recalculava a diferença de todo inversor e devolvia "−4" ao que estava fora da conta — agora fica None.

**Colunas da tabela de strings (25/09/2026, pedidos do Levi).** Abre pelo **Status**, antes da Usina ("quero a coluna
de STATUS antes do nome da USINA"), e **não tem mais a Disponib.** ("pode tirar a coluna de disponibilidade das strings
em tempo real"): era ativas ÷ esperadas em %, a Diferença dita de outro jeito, e passava de 100% com o cadastro errado.
É um componente só para as 9 fontes; as linhas de largura toda têm 9 colunas. Teste:
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

Sem motivo, segue "sem comunicação". Aplicado na saída das 9 tabelas de strings (`_com_usina_desligada`, dentro do
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
SolarEdge e 2C do e-mail não têm potência na linha e ficam como estavam. Teste: `tests/test_pouca_luz_nao_e_desligada.py`.

## Tickets de strings na tabela (23/09/2026)

A tabela de strings tem a coluna **Tickets**: strings com ticket ABERTO na aba **"Strings indisp"** (sheet 128) da
planilha de tickets, a mesma que a tela de Tickets do OS Creator lê e grava, contra as que faltam agora. No drill, o
inversor ganha a etiqueta azul "ticket", a vermelha "N sem ticket" ou a verde "voltou", e o chip da string ganha um
ícone. `load_tickets_strings` → `TICKETS_STR`, anexado na saída das 9 rotas por `_com_tickets_str`, dentro de
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
Religamento Remoto e Corretiva Emergencial, janela solar 06–18h, OS aberta sem fim = 0 h; cabine e conferência
pela geração ficam só no Gerencial) com as OS já carregadas do Fracttal (`OSALL`/`OSSITE`). Gotcha: a API PV só
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

## Fonte `2capi`: as três usinas da 2C pela API PV

Desde 11/09/2026 Araputanga (18771898), "Sete Lagoa" (18771901 — singular na API, "Sete Lagoas" no cadastro) e Tupi
Paulista (18750925) entram pela conta oem@ da API PV como fonte `2capi` ("2C · API PV"): strings ao vivo, ETM
completa, curva, Diagnóstico v2. É o padrão SEMP/Alves Lima (`PV_FONTES` + bloco da fonte), com três coisas próprias:
fonte explícita filtra por **id**, não pelo `FULL_OM` (`_pv_plantas_da_fonte` — o FULL_OM é por nome de supervisório
e "Sete Lagoa" não está lá); `PV_NOME_API_ALIAS` traduz o nome da API para o do cadastro em `nome_usina`; e
`PV_INV_NOMES` dá o nome do inversor (a conta oem@ não devolve nome e as abas da 2C não têm linha no Equipamentos) —
de-para fechado **por valor** contra o kWh diário do BD, nunca pela ordem dos ids.

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
`errout` (a Entrada mostra "de tal hora"), não zero parados. Pelo acervo do e-mail ficam só Perdas e relatório de strings
e a correlação. **O dia fica quente no worker** (`_2c_trk_loop`, de 6 h às 19 h): frio, os parados da 2C levam 51 s (o dia
inteiro de 6 plantas, 8 a 64 MB cada) e quente 5 s, e a Entrada dá 30 s por fonte — o dia vence de 30 em 30 min, no passo
dela, e logo depois do deploy o card saiu "de tal hora". O laço renova 2 min antes de vencer, sem apagar o dia
(`_2c_trk_vence`: se a busca falha, fica o de antes), e dia ainda vazio espera 5 min antes de pedir de novo. **A aba de
trackers da 2C é montada no worker** (`_build_2c_trk_payload` → `_2c_trk_cache`, no snapshot como `2c_trk`, com o drill de
cada usina em `por_codigo`): às 14:42 de 30/09 a Entrada abriu a aba e a tela desistiu aos 90 s — no web o dia estava frio
e a União montava as 7 plantas da `2capi` para usar uma (agora só ela, `_pv_trackers_analise`). A disponibilidade da aba
é recalculada no máximo a cada 30 min (`_2C_DISP_A_CADA_S`): recalcular refaz as ocorrências e grava o `trk_eventos.json`
inteiro (26 MB, no OneDrive). A trava de ocorrência em dobro está em `PV_TRK_OUTRA_FONTE`, e desde 29/09 o `_pv_parados_rows` também
pula essas usinas (quando a aba de trackers da 2C tinha sido aberta no web, o mesmo tracker entrava duas vezes). A conta principal responde "Invalid id" para
as usinas da 2C: qualquer chamada delas tem de ir por `_pv_token_for`. Teste: `tests/test_fonte_2capi.py`.

**A União entrou em 25/09/2026** ("adicione a usina União em 2C!"): conta oem@, id 18772125, "União " na API (com
espaço), 2.162 kWp, instalada em 22/09 — 6 inversores com 28 Ipv (18 com corrente). No cadastro é "União 1 e 2" (Info
Geral: cliente 2C, Piauí, 12 inversores, 4,46 MWp — a API tem metade, por ora), e o `PV_NOME_API_ALIAS` faz a ponte;
sem ela o card da 2C da Entrada a descartava por falta de cliente. Os trackers dela seguem o caminho das outras três
(aba 2C, pela API). Teste: `tests/test_2c_uniao.py`.

**Cadastro da União (28/09/2026**, Levi: "já está na aba equipamentos porém não apareceu na plataforma"). O Equipamentos
a preencheu sob o supervisório **"UNI"** (UNI_Inv_1.1 a 2.6, 12 inversores de 18 strings), não sob "União 1 e 2" —
`PV_ALIAS_CODIGO` faz a cópia do alias procurar também o código. E a API tem só a **UG 01**: `PV_ALIAS_PARCIAL` copia os
inversores 1.1 a 1.6 (6 × 360,36 kWp = os 2.162 kWp da API — é a conferência que fecha), com o esperado da usina somado
deles: 108, não 216, que seriam 108 strings "faltando" que não existem. Na potência o filtro compara pelo `_nrm` do
supervisório e do nome de exibição, que é como o `POWER_INV` é chaveado. Os nomes vêm de `PV_INV_NOMES` **pela ordem dos
ids** (401313 → UNI_Inv_1.1 … 401318 → 1.6) — provisório, a única exceção à regra do valor: a conta oem@ não lista
dispositivos, o e-mail da 2C não manda a União e o ativo do Fracttal não tem nº de série. Confirmar na PV Plataforma.
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
`sol_baixo` em cada linha **na saída** das 9 rotas de strings, com a mesma `_macro_sol_baixo`, e tira do card
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

**Como renovar:** bookmarklet de 1 clique, ou `POST /api/pv/trackers/token` com `{"token": "..."}`.
O `tokens_runtime.json` é relido a cada uso, então vale na hora, sem reiniciar. `_plat_token()` escolhe
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
  só existe no 2C (2C_historico); API PV e Athon usam as quedas gravadas (`perdas_strings.json`) antes de 24/09.
- Sem notícia depois, o episódio segue **em aberto** (pedido do Levi). Trava de string vale para o mês todo; a da
  API PV precisa do de-para nome → idefinversor (`falhas_pv_dev.json`, `plant_devices`, 7 dias).
- Trackers: régua de parado da plataforma; parado que vira severo/médio/leve sai; desvio < 2° o episódio todo não é
  falha; kWp do tracker = inversor ÷ trackers dele, ou o típico medido no cadastro (dividir a UFV pelos trackers
  "vistos no store" inflava ~10×: o store só lista tracker com anomalia).
- Geração: a que a Disponibilidade acabou de buscar (`_DISP_GER_ULTIMA`) ou `_disp_geracao(..., com_pg=False)` —
  nunca uma 2ª consulta do mês ao banco da Thopen.
- **Workbook `falhas_performance` (Gridco API, id 39, criado em 25/09):** abas `strings_inversor_dia`,
  `strings_episodios`, `trackers_episodios` e `atualizacao` (`falhas_publicar.py`, o caminho do gêmeo: xlsx +
  `sync-xlsx?replace=true`). O worker sobe de hora em hora e só quando o dado muda (`_falhas_publicar_workbook`) — a
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
- **Filtro por inversor e por string/tracker** na aba (`f-inv`, `f-str`; ordem natural, 3.1 ≠ 3.10; na visão por inversor
  e dia vale a string da lista). Rótulo e seletor ficam no mesmo `.fpar` para quebrarem de linha juntos.
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
