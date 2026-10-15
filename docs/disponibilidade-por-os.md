# Disponibilidade por OS — contexto, fontes e réguas

Referência do calculador de disponibilidade da Plataforma de Performance (5050).
Construído em 25–27/08/2026; decisões de régua tomadas pelo Levi e travadas por teste.

## 1. O que é

Cálculo de **disponibilidade mensal por usina e por cliente** a partir das ordens de serviço
do Fracttal, pesado pela estrutura física do BD_Performance. Vive em três lugares:

- **Coluna "Disponibilidade ↗"** na tabela Geração × Meta P50 do `/gerencial` (mês do filtro);
- **Painel `/gerencial/disponibilidade`** — filtros de cliente e mês (corrente + anterior; o ícone
  de atenção acima do mês lista as OS abertas sem data final), KPIs, disponibilidade por cliente
  (abre as usinas do cliente e, na usina, as OS da conta dela), maiores eventos, mapa diário
  usina × dia (célula clicável abre o card da OS) e exportação do mapa em Excel;
- **API** `/api/gerencial/disponibilidade?mes=YYYY-MM[&cliente=X]` e
  `/api/gerencial/disponibilidade/export` (xlsx).

Design aprovado a partir do mockup de 26/08
(https://claude.ai/code/artifact/d027c62d-8456-420e-a4df-91077bbde318).

## 2. Fontes de dados

### 2.1 Fracttal (API oficial) — os eventos

- Autenticação OAuth2 `client_credentials` (`FRACTTAL_CLIENT_ID`/`FRACTTAL_CLIENT_SECRET` no
  `tokens.txt`); endpoint `GET /api/work_orders/` paginado (`start`/`limit=200`, listagem
  decrescente por criação). O limite é 200 req/min para a EMPRESA inteira. No 429, a varredura
  do worker espera o reset informado e repete a página (`_frac_get_paciente`, desde 28/09/2026).
- A varredura cobre **mês corrente + mês anterior + 45 dias de margem** (OS antiga que
  atravessa o mês entra). ~175 páginas por ciclo. Só a varredura inteira vira índice; ver
  `calculo-disponibilidade-gerencial.md` §3.3.
- Cada linha da API é uma **tarefa**; a OS (`wo_folio`, numérico) agrega 1+ tarefas.
- Campos usados por tarefa: `tasks_log_task_type_main` (tipo), `id_status_work_order`
  (0 pendente / 1 em andamento / 2–3 concluída / 4 cancelada / 5–6 aguardando-pausada),
  `event_date`, `date_maintenance`, `final_date`, `wo_final_date`, `code` (ativo),
  `items_log_description`, `groups_1_description` (site), `description`, `created_by`,
  `personnel_description`, `user_assigned`.
- **Fuso:** o Fracttal devolve UTC; tudo é convertido para America/São_Paulo (−3) antes de
  qualquer conta. Errar isso desloca a janela solar.

### 2.2 BD_Performance, aba Equipamentos — a estrutura e os pesos

- Lida do **espelho** `plataforma/bases/BD_Performance.xlsx` (materializado da Gridco
  Performance API pelo `bd_api.py`), via `_bd_readable_path()`, cabeçalho na linha 3.
- Linhas usadas: `UFV` (potência e nº de inversores da usina, cliente, **Usina Fractall** =
  vínculo com o site do Fracttal), `UG NN` (cabines, kWp cada) e `Inversor N.M` (kWp cada).
- **Hierarquia inversor → cabine vem da coluna `Equipamento Parente`** (100% preenchida, aponta
  "UG NN") — é a fonte oficial que a Performance usa. O padrão de nome `Inversor N.M` é só o
  fallback: em Ibirapuã I/II, Inhapi e Tucano 2 o N do nome **não** é a UG.
- Outras derivações quando o cadastro é incompleto (sempre com aviso em "lacunas"): potência da
  UFV vazia → soma das UGs ou dos inversores.
- `Usina Fractall` ↔ `groups_1_description` é o de-para OS→usina (match exato, depois pelo
  "miolo" sem cliente/UF, com romanos normalizados).

### 2.3 Só Full O&M

Desde 30/08 o parque considera **apenas usinas com `Full O&M = Sim`** na aba Equipamentos
(decisão do Levi). Onde a Grid Co. não faz a manutenção completa, a disponibilidade não é
responsabilidade nossa e as OSs do Fracttal não contam a história toda. O filtro vale para o
parque, o resumo por cliente, o diário e a lista de lacunas.

## 3. O que conta como indisponibilidade

1. OS com tipo de tarefa **Religamento**, **Religamento Remoto** ou **Corretiva Emergencial**
   (qualquer tarefa da OS nesses tipos qualifica);
2. **não cancelada** (status ≠ 4 — canceladas são duplicatas/testes e ficam fora, decisão de 26/08);
3. site ≠ **"Grid Co."** (site genérico = usina de terceiros sem contrato, fora do parque);
4. ativo de **geração** (trackers, disjuntor de MT, cabos CC, conversor de mídia ficam fora,
   listados como exclusão);
5. intervalo do evento **toca o mês** (interseção com 1º dia 00:00 → dia D−1 24:00; o dia em
   curso nunca entra).

### 3.1 Duas famílias por origem da falha (metodologia da Performance)

Régua da Ana Patrícia, incorporada em 29/08. A conta é **a mesma** nas duas famílias (potência
do equipamento × tempo de indisponibilidade); o que muda é a **classificação pela origem**:

| Família | Tipos de tarefa | Natureza |
|---|---|---|
| **Por queda** | Religamento, Religamento Remoto | origem externa (rede/concessionária) |
| **Por equipamento** | Corretiva Emergencial | falha física nossa — "tem disponibilidade elétrica, não tem disponibilidade física" |

- O **total** continua sendo o número oficial (e é o que a coluna do `/gerencial` mostra); as
  famílias são a **decomposição** dele, exibida nas colunas "Por queda"/"Por equipamento" da tabela
  e na etiqueta da OS no card do dia. Desde 13/10/2026 não aparece no KPI nem na lista "O que
  derrubou o mês" (Levi: "deixe só o valor principal"; "tem que deixar mais enxuto").
- **As duas famílias não somam o total.** Evento de cada tipo no mesmo horário é capado em 100%
  no total e contado inteiro em cada recorte — a diferença é a sobreposição (medida em 29/08:
  0,06 pp no parque, ou seja, quase uma partição limpa).
- OS que tem tarefas das duas famílias conta como **queda** (a usina caiu; a corretiva veio junto).
- Onde a separação mais muda a leitura (29/08): Ceilândia 1 (92,86% total, **100% na queda**),
  Castelo do Piauí (93,93% / 100%), Altair (95,80% / 100%) — usinas cujo problema é inteiramente
  de manutenção própria, e que num número só pareciam ter problema de rede.

**"Corretiva" simples: fora, por ora** (decisão do Levi, 29/08 — "vamos pensar em algo melhor").
Medido antes de decidir: entrariam 1.933 tarefas e o bucket cairia de 99,5% para 93,7%
(+8.487 MWh). O corte por tipo de tarefa é grosso demais — boa parte dessas corretivas é
trabalho programado sem equipamento parado. O critério melhor provavelmente não é o tipo, e sim
se houve **parada de fato** (candidatos: `real_stop_assets_sec`/`stop_assets` da própria OS, ou
cruzar com a geração do inversor no dia).

**Em aberto com a Ana:** ela citou IPOA ao descrever o peso; se pondera por irradiância, difere
do nosso linear na janela 06–18h.

## 4. Datas do evento — as regras duras

- **Início** = menor `event_date` das tarefas (fallback `date_maintenance`).
- **Fim** = maior `final_date` das tarefas. **`wo_final_date` NÃO é fim de parada** — é carimbo
  administrativo da WO (em 25/08 uma revisão em massa re-carimbou dezenas para o mesmo minuto;
  usá-lo levaria o parque de 97% para 79%). Só entra se não houver `final_date` nenhum, com aviso.
- **Evento depois do fim** (Levi, 15/10/2026): a **data de criação** da OS vira o evento. Se o fim fica antes até da
  criação, a OS conta 0 h e vai para a lista "alinhar". Substituiu as duas réguas de antes (o "relâmpago" de até 1 h =
  duração 0, e o fim descartado quando vinha mais de 1 h antes).
- **OS aberta sem fim CONTA** (Levi, 15/10/2026: "Será considerado OSs fechadas e abertas"): do evento até o fim do
  período — no mês corrente, até ontem —, em todo mês em que seguir aberta. De 26/08 a 15/10 ela valia 0 h, com um
  "cenário" à parte (a prova era Mandaguaçu, OS 11186, e Céu Azul, OS 11832, esquecidas abertas com a usina gerando), e
  sumia no mês seguinte — a 16338, Inversor 2.2 de Ipixuna 2, aberta desde 16/09, não aparecia em outubro. A OS
  esquecida aberta agora aparece na lista "alinhar" da tela, para corrigir no Fracttal.
- Validações: datas com ano fora do período ou no futuro são descartadas (houve fim digitado
  como 2027 e 2025 na fase RDO). Início no ano corrente ou no anterior; fim `≤ agora`, no ano
  corrente **ou, na OS cujo evento é do ano anterior, nele também** (11/10/2026: o índice é
  refeito com o relógio de agora, e em janeiro toda OS concluída em dezembro virava "OS concluída
  sem data final válida" — dezembro/2025 visto em 05/01 com as OS reais: parque 100,0% e 0 OS
  contando, contra 99,907% e 9 OS em 31/12). Fim num ano **antes** do evento segue fora (a
  digitação) e aí vale o `wo_final_date`.

### 4.1 Só o Fracttal — a geração não entra (15/10/2026)

De 30/08 a 15/10/2026 a geração do BD e do banco desmentia a OS em dia em que a usina gerou (o "juiz de
parada-fantasma": a OS 8891 dizia Parelhas parada de 03/07 a 28/08 com 13.111 kWh/dia). **Saiu de vez** (Levi, 15/10:
"Não quero que olhe a geração, precisamos que você foque nos dados do Fracttal (...) não quero que cruze dados de geração
pois são objetivos diferentes"). A OS conta pelas datas dela; o que estiver estranho vai para a lista **"alinhar"**
(`disponibilidade._para_alinhar`), só com o dado do Fracttal:

- OS aberta sem data final (conta até ontem; quantos dias em aberto);
- evento depois do fim (usou a criação) e fim antes até da criação, ou sem a criação (0 h);
- sem `final_date` na tarefa (usou o `wo_final_date`);
- site agrupado sem a usina na descrição;
- Religamento cuja descrição é verificação de comunicação ou inspeção ("houve parada?");
- religamento fechado que durou mais de um dia (a aberta já vai pelos dias em aberto; corretiva longa não: trocar
  inversor leva dias);
- OS fora da conta por dado da própria OS (sem evento, concluída sem fim, site ou ativo que o cadastro não reconhece).

Prova de 15/10/2026 (varredura real × o índice publicado com a regra antiga): outubro da Thopen 88,47% → 80,43%. Das
perdas a mais, ~4,8 GWh eram dias que o juiz exonerava e ~1,5 GWh OS abertas desde setembro que sumiam (Brodowski 12693,
"Verificação de comunicação", aberta desde 02/09; Guatambu 13427, "Inspeção e normalização", desde 10/09). 175 OS de
outubro na lista "alinhar".

### 4.2 Setembro para trás: só a Thopen, pelo BD_Thopen (15/10/2026)

"A disponibilidade será calculada somente pelo Fracttal a partir de outubro; setembro para trás vamos considerar o que
está no BD_Thopen"; fora da Thopen, "só a partir de outubro!" (Levi, 15/10). O mês antes de `DISP_SO_FRACTTAL_DESDE`
(app.py, "2026-10") sai de `disponibilidade.calcular_pelo_bd`: a "Disponibilidade Usina (%)" diária do BD_Thopen (pelo
leitor do 5080, `dashboard_thopen._daily_records`), média dos dias com número, cliente ponderado por kWp, sem OS e sem a
separação queda × equipamento (`fonte` = "BD_Thopen"). O casamento é pelo nome; os de-paras do Gerencial resolvem o resto
(`_DISP_BD_ABAS`: Vargem Grande IB = aba Vargem Grande 1; Nova Londrina 1 e 2 e Primavera 1 e 2 levam o número do
complexo; Ouro Branco = média de I a V). Setembro no PC: Thopen 95,51% (regra antiga) → 95,40% (BD).

## 5. Escopo — o que a OS derruba (pelo ATIVO, não por texto)

| Ativo (`code`) | Escopo | Peso (kWp) |
|---|---|---|
| raiz do site (ex.: `THPN-GTB100`) | usina inteira | kWp da UFV |
| `…-CABN2`, `…-SKID2`, `…-QGBT3`, `…-PECN3`, `…-DTRF3` | cabine N | kWp da UG N (média das UGs se a N não existir, com aviso) |
| `…-INVR1.4`, `…-DINV3.1` | inversor | kWp daquele inversor (média da usina se o número não casar, com aviso) |

**Sites agrupados** (um site Fracttal para 2+ usinas do BD — Santarém 1 e 2, Ipixuna 1 e 2,
Aparecida do Taboado 1 e 2, Rodrigues 1/2, Boa Esperança 1/2):

- **Régua da OS 11461 (Levi, 27/08):** quando cada usina do grupo tem no máximo 1 cabine
  própria, o número da cabine/skid **identifica a usina** e vale como ela inteira
  (`SKID 2` do site Taboado = usina Aparecida do Taboado 2, 100%).
- Guarda: se alguma usina do grupo tem 2+ cabines (Ipixuna 1, Rodrigues 2), o número pode ser
  cabine interna → tenta-se a usina pela **descrição** da OS; sem pista, cai na 1ª usina do
  grupo com flag "conferir". Casos pendentes de decisão: `IPX100-CABN1/2` e `RDR100-SKID2`.
- Evento no nível do site sem pista na descrição vale para o **grupo inteiro** (se o site caiu,
  as duas caíram) — flag registra.

**Sobreposição nunca passa de 100%:** eventos simultâneos na mesma usina são fundidos por
varredura de linha do tempo com hierarquia usina > cabine > inversor (usina inteira ativa
absorve os demais; senão soma capada no kWp da usina).

## 6. Fórmulas

- **Janela solar:** 06:00–18:00, por dia, em horas e minutos (interseção exata do intervalo).
- **Disponibilidade do dia** = 1 − horas-equivalentes indisponíveis ÷ 12 h.
  (horas-equivalentes = Σ fração-de-kWp-afetada × horas)
- **Disponibilidade do mês** = 1 − Σ horas-eq. ÷ (12 h × dias fechados). Mês corrente usa
  apenas dias fechados (01 → D−1).
- **Perda estimada (kWh)** = kWp afetado × horas solares indisponíveis — **à potência
  nominal** (teto teórico; linear na janela, não pondera irradiância nem clima).
- **Cliente/parque** = ponderado por kWp: 1 − Σ(kWp×h-eq) ÷ Σ(kWp×12×dias).
- **Por família** (queda / equipamento) = a mesma conta, rodando a varredura só com os eventos
  daquela origem — por isso cada família é sempre ≥ o total, e a soma das indisponibilidades das
  duas é ≥ a do total.
- **Perda da OS em cada usina** (`kwh_usina`, 13/10/2026, para o drill-down por cliente da tela) =
  a mesma parcela da varredura, separada por usina: soma a perda da OS e a da usina. Repartir a OS
  pela potência erra quando a geração desmente o dia numa usina só (Rodrigues 1 e 2, setembro:
  ~47,9 MWh na usina errada).

## 7. Arquitetura (quem faz o quê)

| Peça | Papel |
|---|---|
| `plataforma/disponibilidade.py` | módulo PURO com todas as réguas (sem Flask/rede/arquivo) |
| `plataforma/app.py`, bloco "Disponibilidade por OS" | varredura (`_frac_disp_sweep`), recálculo e publicação (`_frac_disp_recalcular`), loop de 30 min no worker (`_frac_disp_loop`), leitura no web (`_frac_disp_dados`, por mtime), rotas e export |
| `plataforma/frac_disp_index.json` | índice publicado (payloads prontos do mês corrente + anterior, e `varredura`: até onde leu); escrita atômica; só varredura INTEIRA com os dois meses calculados sobrescreve |
| `plataforma/frac_disp_status.json` | a última tentativa do worker (`ok`, `erro`, `varredura`), que a rota devolve em `ultima_tentativa`; a falha também vai para `plataforma/logs/fracttal.log` |
| `plataforma/templates/disponibilidade.html` | painel (fetch da API; card do dia; export) |
| `plataforma/templates/gerencial.html` | coluna Disponibilidade (match de nome com romanos, SEM herdar valor da usina-mãe quando a granularidade difere — mostra "—") |

O trabalho pesado roda **só no worker** (regra do GIL); o web serve o índice em milissegundos.
Catálogo de equipamentos cacheado por 12 h — mudança na aba Equipamentos vale no próximo ciclo
(ou restart do worker).

## 8. Qualidade — como isso se mantém verdadeiro

- `tests/test_disp_fracttal.py`: cada régua acima é um caso (relâmpago, wo_final_date, aberta
  sem fim, teto de 100%, janela noturna, escopos, sites agrupados, régua da OS 11461,
  criador/escopo no payload, perda por usina) + **regressão com dado real**
  (`tests/fixtures/frac_smp100_os10758.json`: OS 10758 do SMP100, 41,17 h / ~285 MWh).
- `tests/test_disponibilidade_tela_13_10.py`: a tela inteira no node sobre a rota, e o gabarito
  `tests/fixtures/disp_antes_13_10.json` (a saída do módulo antes de 13/10: o de agora tem de
  devolver a mesma).
- Validação de origem: o módulo reproduziu o motor de referência da análise de 26/08 em
  **117 de 120 usinas**; as 3 diferentes eram um bug do motor antigo (a "pista" de site
  agrupado lia o próprio nome do site) que o teste pegou — planilha de 26/08 subestimava
  ~73,5 MWh nos sites agrupados.
- Rodar: `python -m pytest tests/test_disp_fracttal.py -q` a partir da raiz.

## 9. Limitações e avisos honestos

- **Perda é teto teórico** (potência nominal × horas) — não usa irradiância nem P50. Refino
  possível se necessário.
- **Fracttal é a fonte da verdade dos eventos:** parada real sem OS não aparece (foi a decisão
  ao aposentar o RDO). Ocorrências manuais só entram em planilhas avulsas, marcadas — o painel
  nunca as inclui.
- OSs **ainda abertas** contam até ontem enquanto não ganham `final_date` (15/10/2026) — OS esquecida aberta derruba o
  mês até ser fechada; o ícone de atenção acima do mês lista as OS para alinhar no Fracttal.
- **Qualidade do cadastro manda no peso.** Caso real (27/08): a UFV de Ipixuna 1 estava com o
  kWp do site inteiro (3.079 em vez de 1.255,8) e um inversor parado pesava 4,7% em vez de
  11,5%. Suspeitas abertas do scan: Inhapi (inversores sem kWp), Nova Londrina (UFV ≠ Σ
  inversores), Ibaté 1/2 (N de Inversores = 9, reais 12).
- Sites agrupados sem pista → grupo inteiro (pode superestimar a usina irmã); a solução
  estrutural é separar os sites no Fracttal ou detalhar a descrição da OS.

## 10. Cronologia das decisões

- **25/08** — estudo RDO × Fracttal × BD (jul+ago): régua dos 3 tipos, janela solar, escopo
  por ativo; descoberto `wo_folio` numérico e o de-para `groups_1` ↔ Usina Fractall.
- **26/08** — RDO aposentado ("subir o nível"); Fracttal-only; decisões: fim = `final_date`
  da tarefa, canceladas fora, "Grid Co." = terceiros, abertas = 0 h + cenário (tratamento
  definitivo fica para depois). Mockup aprovado.
- **15/10/2026** — só o Fracttal de outubro em diante (sai o juiz da geração), OS aberta conta, evento depois do fim usa a
  criação, lista "alinhar" no lugar do cenário; setembro para trás só a Thopen, pelo BD_Thopen.
- **27/08 (madrugada)** — feature no ar (worker + web); card do dia com criador e conta
  discriminada; export no card do mapa.
- **27/08 (dia)** — régua da OS 11461 (cabine de site agrupado = usina); correção do cadastro
  de Ipixuna 1; planilha avulsa das 23 usinas com 3 ocorrências manuais marcadas.
- **29/08** — reunião com a Ana Patrícia: incorporada a separação por origem da falha (queda ×
  equipamento) em toda a especificação, mantendo a coluna do gerencial como número único; a
  hierarquia passou a sair da coluna `Equipamento Parente`. Dois pontos seguem em aberto com
  ela ("Corretiva" simples e IPOA).
- **13/10** — tela mais enxuta (pedidos do Levi): o aviso das abertas virou ícone de atenção acima
  do mês; KPI só com o valor principal; "O que derrubou o mês" em duas linhas (Usina – Equipamento
  / OS · tipo · evento → fim · h solares, a perda ao lado); disponibilidade por cliente no lugar
  das barras por usina, com as usinas e as OS em drill-down; `kwh_usina` no índice. Números
  iguais aos de antes (provado com OS reais e com o índice real).

## 11. Onde estão as coisas

- Código: `plataforma/disponibilidade.py`, bloco no `plataforma/app.py`,
  `plataforma/templates/disponibilidade.html`, `plataforma/templates/gerencial.html`
- Testes: `tests/test_disp_fracttal.py` + `tests/fixtures/frac_smp100_os10758.json`;
  `tests/test_disponibilidade_tela_13_10.py` + `tests/fixtures/disp_antes_13_10.json`
- Índice publicado: `plataforma/frac_disp_index.json`
- Entregas avulsas (Documentos): `Disponibilidade Fracttal x BD - agosto 2026 (atualizada).xlsx`,
  `Disponibilidade agosto - usinas selecionadas.xlsx` (com as manuais),
  `Disponibilidade e Perda - RDO jul-ago 2026.xlsx` (histórico, metodologia antiga)
- Mockup aprovado: https://claude.ai/code/artifact/d027c62d-8456-420e-a4df-91077bbde318
