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
(potência < max(piso, 5 % da mediana dos pares), com sol, com a usina gerando, com leitura). A linha leva
`inv_desligados` / `strings_fora` / `inv_desligados_nomes` (a tela mostra "N inv. desligado · M strings fora da
conta" na célula das esperadas e o status "Inversor desligado"; os tickets leem os nomes). No drill, o inversor
continua listado, marcado `desligado` e `fora_da_conta`, com `diferenca` None. Usina inteira parada NÃO tira
ninguém (é "Usina desligada"). De 11/09 a 24/09 a API PV e o Banco faziam o contrário (todas as strings do
desligado contavam como faltantes). **OS atribuída** (`os_atribuidas`, chave `plant_id|idefinversor`) e OS aberta
no Fracttal em inversor desligado continuam tirando o inversor da conta pela OS (`inv_com_os`/`strings_com_os`),
sem virar o aviso de desligado (11/09: "se está desligado e tem OS então está tudo OK"). As duas fontes SEM
potência por inversor usam a medida das strings dele, somada: RenoGrid/SolarEdge (`_se_fora_da_conta`: potência DC
= soma dos W das strings) e a 2C do e-mail (`_owen_fora_da_conta`: soma das correntes, que zera quando ele desliga).

**Colunas de strings são sempre strings.** As 13 usinas da régua de padrão (`inv_padrao`) punham "18/20 inv.",
"padrão 30d", "no padrão" e "2 crônicos" nas colunas; desde 24/09 ativas/esperadas/diferença/disponibilidade
saem em '—' sem visão por string, e a proporcionalidade vai para o aviso da célula das esperadas
(`_strNotaPadrao`, roda no node). Com visão (Ouro Branco), valem as strings, e o padrão de ontem só vira status
quando as strings de agora não têm nada a dizer. O `gerencial.html` é tema escuro por padrão só por tokens
(`:root[data-theme="dark"]`); é Jinja — mudança nele exige restart do web.

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

## Fonte `2capi`: as três usinas da 2C pela API PV

Desde 11/09/2026 Araputanga (18771898), "Sete Lagoa" (18771901 — singular na API, "Sete Lagoas" no cadastro) e Tupi
Paulista (18750925) entram pela conta oem@ da API PV como fonte `2capi` ("2C · API PV"): strings ao vivo, ETM
completa, curva, Diagnóstico v2. É o padrão SEMP/Alves Lima (`PV_FONTES` + bloco da fonte), com três coisas próprias:
fonte explícita filtra por **id**, não pelo `FULL_OM` (`_pv_plantas_da_fonte` — o FULL_OM é por nome de supervisório
e "Sete Lagoa" não está lá); `PV_NOME_API_ALIAS` traduz o nome da API para o do cadastro em `nome_usina`; e
`PV_INV_NOMES` dá o nome do inversor (a conta oem@ não devolve nome e as abas da 2C não têm linha no Equipamentos) —
de-para fechado **por valor** contra o kWh diário do BD, nunca pela ordem dos ids. No rollup do macro a fonte entra
**antes** do e-mail (`owen`): em empate de severidade fica quem entrou primeiro, e um estado pior no e-mail continua
vencendo. **Trackers seguem pelo e-mail** (fonte `owen`), junto com a Ipixuna do Pará, que não está na API. Não é mais
por falta de permissão: desde 15/09/2026 a PV Plataforma devolve as três (ARA 59, STL 59, TUP 100, iguais ao
BD_Trackers) — é para não ter a MESMA ocorrência em duas fontes. Quem decide migrar é o Levi; a API é ~2h45
mais fresca. A trava está em `PV_TRK_OUTRA_FONTE` (ver "Trackers das usinas da conta OEM" abaixo). A conta principal responde "Invalid id" para as três:
qualquer chamada delas tem de ir por `_pv_token_for`. Teste: `tests/test_fonte_2capi.py`.

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
sol a linha diz "Sem sol", com esperadas, diferença e disponibilidade em "—". Comunicação e o D-1 do padrão por
inversor continuam valendo. A marca é feita na saída e não no build porque o ciclo do worker chega a 15 min, e o
payload em cache é do worker (só se mexe em cópia). **Rota de strings nova precisa passar por
`_servir_com_sol`**: o teste lê o mapa `strings:{...}` do HTML e falha se faltar uma.

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
a Ipixuna fica fora por não estar na API). Ciclo caiu de 80 s para ~11 s. O nome do inversor vem do
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
  **Só o servidor grava** (Linux; `FALHAS_WORKBOOK=1/0` força): a ponte local do OS Creator, se rodar este código,
  deixaria o workbook trocando de versão a cada hora. A API não apaga workbook nem aba.
