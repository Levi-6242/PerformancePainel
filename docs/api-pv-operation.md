# API PV Operation — como funciona e como a Grid Co usa

> Documento de referência, atualizado em **23/09/2026** a partir do código (Plataforma de Performance, coletor e
> Gêmeo Digital), das sondagens registradas e dos incidentes reais. Cada medida traz a data em que foi feita.
>
> Substitui a versão de 10/06/2026, que cobria só o script de coleta e ficou defasada em GHI, histórico de
> meteorologia, combiner, v2, trackers e contas (ver [§13](#13-o-que-mudou-desde-a-versão-de-1006)).
>
> **Credenciais nunca aparecem aqui**, só os nomes das variáveis.

## Sumário

1. [Em uma página](#1-em-uma-página)
2. [Acesso: endereço, versões, autenticação e contas](#2-acesso-endereço-versões-autenticação-e-contas)
3. [Endpoints](#3-endpoints)
4. [Identificadores e de-para](#4-identificadores-e-de-para)
5. [Comportamentos medidos](#5-comportamentos-medidos)
6. [Qualidade do dado](#6-qualidade-do-dado)
7. [Como a Grid Co usa](#7-como-a-grid-co-usa)
8. [Operação: credenciais, sintomas e diagnóstico](#8-operação-credenciais-sintomas-e-diagnóstico)
9. [Incidentes e lições](#9-incidentes-e-lições)
10. [Decisões registradas](#10-decisões-registradas)
11. [API PV Operation × PV Plataforma](#11-api-pv-operation--pv-plataforma)
12. [Riscos e pontos abertos](#12-riscos-e-pontos-abertos)
13. [O que mudou desde a versão de 10/06](#13-o-que-mudou-desde-a-versão-de-1006)
14. [Onde está no código](#14-onde-está-no-código)

---

## 1. Em uma página

- **O que é:** a API REST de dados do supervisório **PV Operation**, fornecida pela **Solan**. A documentação
  oficial fica em `solan.group/developers/api-pv-monitoring`, e a coleção `PV-API.postman_collection.json` lista
  todas as rotas.
- **Para que serve aqui:** é a fonte das usinas **Thopen** e, por uma segunda conta, de **SEMP** (Tucano 1 e 2),
  **Alves Lima** (Morada Nova) e de três usinas da **2C** (Araputanga, Sete Lagoas e Tupi Paulista).
- **Endereço:** `https://apipv.pvoperation.com.br/api/v1` (algumas rotas também em `/api/v2`).
- **Autenticação:** usuário e senha geram um JWT, enviado no header `x-access-token`. Não tem CAPTCHA, então é
  automatizável, ao contrário da PV Plataforma ([§11](#11-api-pv-operation--pv-plataforma)).
- **O que entrega:**

  | Dado | Rota | Alcance |
  |---|---|---|
  | Inversores minuto a minuto (correntes por string, potência, temperatura) | `day_inverter` | só hoje |
  | Inversores do dia inteiro, de dia passado | `custom_query` `inverter` | ~8 dias |
  | Energia diária por inversor | `custom_query` `energy` | qualquer dia |
  | Estação meteorológica (POA, GHI, temperatura, vento, chuva) | `day_meteo` / `custom_query` `meteo` | hoje / dias passados |
  | Combiner das String Box | `custom_query` `combiner` (v2) | dia pedido |
  | Trackers (posição, alvo, comunicação) | `trackers` | dia pedido |

- **Quem usa:**
  - a **Plataforma de Performance** (tabelas de strings, drill por inversor, ETM, trackers, PR, padrão por
    inversor, qualidade de dado);
  - o **coletor**, que grava energia diária, IPOA, GHI, chuva e temperatura no BD_Thopen e no BD_Performance;
  - o **Gêmeo Digital**, nas três usinas da 2C.
- **Três cuidados que valem para qualquer uso:**
  1. **Nunca autenticar a cada chamada.** A API bloqueia o `/authenticate` e passa a responder algo que não é JSON.
  2. **Erro vem como objeto (`{"error": ...}`), às vezes com HTTP 200.** Quem espera lista quebra em silêncio.
  3. **O carimbo de hora está em horário de Brasília para todas as usinas**, inclusive as de MT. Quem compara com
     o relógio da máquina precisa rodar em hora de Brasília.

---

## 2. Acesso: endereço, versões, autenticação e contas

### 2.1 Endereço e versões

| | v1 | v2 |
|---|---|---|
| Base | `https://apipv.pvoperation.com.br/api/v1` | `https://apipv.pvoperation.com.br/api/v2` |
| Ordem das leituras | crescente (a primeira é a meia-noite) | a mais recente primeiro |
| Carimbo | formato HTTP (`Wed, 16 Sep 2026 00:02:17 GMT`), com "GMT" falso: é hora de Brasília | ISO, hora local |
| Onde usamos | quase tudo | `custom_query` `combiner` (plataforma) e `custom_query` `inverter` |

As diferenças de ordem e de carimbo foram medidas na combiner, em 16/09. A rota `trackers` existe nas duas versões.

### 2.2 Autenticação

```http
POST /api/v1/authenticate
Content-Type: application/json

{"username": "<usuário>", "password": "<senha>"}
```

A resposta é `{"token": "<JWT>"}`. Todas as chamadas seguintes levam o header:

```http
x-access-token: <JWT>
```

- **Validade:** o JWT traz `exp`. A plataforma e o gêmeo renovam 60 s antes do vencimento e, se não conseguem ler o
  `exp`, assumem 45 min. O coletor não controla validade: renova quando recebe 401, uma vez por chamada.
- **Cache é obrigatório.** A plataforma autenticava a cada chamada e a API passou a limitar o `/authenticate`,
  devolvendo resposta não-JSON (500). Desde então o token fica em memória, com lock.
- **Token da PV Plataforma não serve aqui**, e vice-versa: usar o token da API PV na Plataforma dá HTTP 500.

### 2.3 As duas contas

O **id da usina é global**: as rotas por usina são as mesmas nas duas contas, e o que muda é o token.

| | Conta principal ("gridco") | Conta oem@ |
|---|---|---|
| Usinas em `/plants` | 146 (medido de 31/08 a 22/09) | 155 (22/09), a grande maioria de terceiros |
| Usinas nossas | Thopen. A plataforma publica o recorte Full O&M: 115 usinas em 22/09 | **SEMP:** UFV Tucano 1 (18758732) e Tucano 2 (18768694). **Alves Lima:** MORADA NOVA (18766373, desligada desde 10/09). **2C:** Araputanga (18771898), "Sete Lagoa" (18771901) e Tupi Paulista (18750925) |
| `plant_devices` | liberado | negado: HTTP 200 com `{"message": "Invalid permission"}` (na Tucano, lista vazia) |
| Variáveis | `PV_USERNAME` / `PV_PASSWORD` | `PV_OEM_USERNAME` / `PV_OEM_PASSWORD` |

- **Usina da oem@ consultada com o token principal** responde `Invalid id`:
  - HTTP 401 com `{"error": "Invalid id"}` ou `{"error": "Invalid id, incident will be reported 2"}`;
  - a plataforma escolhe o token por usina em `_pv_token_for(plant_id)`.
- **`Invalid id` também aparece por erro de chamada**, sem ser falta de permissão: por exemplo, id mandado como
  parâmetro de URL em vez de no corpo JSON (401).
- **Ipixuna do Pará (2C) não está na API**: segue pelo e-mail da 2C.
- **Nome do inversor na oem@:** como não há `plant_devices`, o nome é fechado **por valor** (kWh diário contra o BD),
  nunca pela ordem dos ids. Na Morada Nova, a ordem dos ids erraria 6 de 8 inversores.

---

## 3. Endpoints

### 3.1 Resumo

| Rota | Método | Corpo | O que devolve | Alcance | Quem usa |
|---|---|---|---|---|---|
| `/authenticate` | POST | `{username, password}` | `{token}` | — | todos |
| `/plants` | GET | — | `[{id, nome, ...}]` | — | todos |
| `/plant_devices` | POST ou GET com corpo | `{"id": pid}` | dispositivos da usina | — | plataforma, coletor |
| `/day_inverter` | POST | `{"id": pid}` | todos os inversores, ~1 leitura/min | só hoje | plataforma, gêmeo |
| `/day_meteo` | POST | `{"id": pid}` | estação, ~1 leitura/min | só hoje | plataforma, coletor, gêmeo |
| `/custom_query` `energy` | POST | `{id, data_type:"energy", period:"AAAA-MM", day}` | kWh do dia por inversor | qualquer dia | coletor, plataforma |
| `/custom_query` `meteo` | POST | `{id, data_type:"meteo", period:"AAAA-MM", day}` | estação do dia inteiro | dias passados | coletor, gêmeo |
| `/custom_query` `inverter` | POST | `{id, data_type:"inverter", period:"AAAA-MM", day}` | inversores do dia inteiro | ~8 dias | gêmeo |
| `/v2/custom_query` `combiner` | POST | `{id, data_type:"combiner", period:"AAAAMM", day}` | combiners do dia inteiro | dia pedido | plataforma |
| `/trackers` (v1 e v2) | POST | `{"idusina": pid, "date": "DD/MM/AAAA"}` | todos os trackers, ~1 leitura/2,5 min | dia pedido | plataforma |

**Tipos que não existem no `custom_query`:** `irradiance`, `irradiation`, `string`, `strings`, `current`, `mppt` e
`dc`. Respondem 401 "Invalid input" na v1 (10/06) e 400 na v2 (17/09).

**Não mapeado:** leitura do medidor (ele aparece como dispositivo em Barretos 1, Colorado 2 e Aruanã, mas o endpoint
de leitura não foi achado) e PR ao vivo (a API tem, o endpoint não foi registrado, e ele ficou fora das telas por
decisão; ver [§10](#10-decisões-registradas)).

### 3.2 `GET /plants`

```json
[ { "id": 22854, "nome": "Nova Londrina 1 (152)" }, ... ]
```

- O campo é **`nome`**, não `name`. Chutar a chave errada devolve tudo "?" e parece que todas as usinas sumiram.
- Desde ~14/08 o nome vem com sufixo " (NNN)". **Esse número não é o id**: Indaiatuba 1 (131) tem id 21480.
- A API renomeia usina mantendo o id (ex.: "Caicó 1.1 (224)", id 18750804). **Case sempre pelo id.**
- O `/plants` da oem@ traz `latitude`/`longitude` sujos (vírgula decimal, espaço duro: `'-15,479992'`,
  `' -44.203342\xa0 '`) e `capacidade` em kWp. O da principal traz coordenadas em 82 de 146 usinas.

### 3.3 `/plant_devices`

```json
[ { "plant_devices": [
    { "device_id": 46058, "device_name": "INVERSOR01", "device_type": "INVERTER",
      "device_esn": "...", "device_status": 1 }, ... ] } ]
```

- **Método:** o coletor usa POST; a plataforma e os scripts do repositório usam GET com corpo JSON. Os dois
  funcionam. O que dá 401 é mandar o id como parâmetro de URL.
- A resposta aparece em três formatos, e a plataforma trata os três.
- `device_type`: `INVERTER` e `METEO`. Também aparecem "Estação Solarimétrica", "Medidor de Fronteira" e
  "Multimedidor 7KT".
- **Armadilhas:**
  - duplicatas e fantasmas: Barretos lista 31/40 "INVERTER" para 20 inversores reais, com nomes como `xxx` e `(old)`;
    `device_status` 4 = aposentado;
  - nome com espaço no fim (`"INVERSOR 04 "`);
  - `device_esn` pode vir com sufixo `@...`;
  - em alguns inversores `device_id` ≠ `idefinversor` (370258 × 46059). Por isso o de-para passa pelo nome, via
    aba Equipamentos do BD_Performance.

### 3.4 `POST /day_inverter`

Formato da resposta (valores ilustrativos):

```json
[ { "idefinversor": 364574, "tsleitura_new": "2026-09-23 12:57:00",
    "conteudojson": { "Ipv1": 12.7, "Ipv2": 12.9, "Pac": 122.9, "Eday": 546.4, "Temp": 62.9, "Status": 40960 } }, ... ]
```

- **Só o dia corrente.** O parâmetro `date` é ignorado, e a série de "hoje" começa por volta de 23:58 do dia anterior.
- `conteudojson` pode vir como texto JSON ou como objeto.
- Campos:
  - `Ipv1..N` em A;
  - `Upv*`, `Pac` em **kW**, `Eday` em kWh, `Etotal`, `Eac`, `Iac1/2/3`, `Temp`, `Status`;
  - `Imppt1/Pmppt1/Umppt1` nas String Box.
- `'-'` aparece no lugar de número.
- **Armadilhas:**
  - os registros vêm **fora de ordem**;
  - o último ping pode vir só com `Eday`/`Temp`, sem nenhum `Ipv`. Use a última leitura do dia **que tenha `Ipv`**;
  - String Box: às vezes nenhuma chave `Ipv`, às vezes 24 `Ipv` quase todas zero. Conte corrente **real**, não chaves;
  - inversor desligado pode mostrar 0,8–1 A de corrente reversa.
- **Volume:** Saturnino passa de 2 MB por chamada; a Tupi dá ~23 mil registros por dia (7 s); Sto Antônio da Platina
  2, ~13 mil.

### 3.5 `POST /day_meteo`

- Leituras do dia corrente, a cada ~60 s: `tsleitura_new`, `dataleitura_new` e `conteudojson`.
- Campos de sensor que aparecem:
  - **POA:** `piraPOA1`, `IrPOA`, `Ir`, `Ir1`;
  - **GHI:** `piraGHI1`, `IrGHI`, `piraGHI2`, `IrGHITotal`;
  - **POA-RI:** `IrPOA_RI`, `piraPOA_RI1`, `RadPoaRI`;
  - **outros:** `piraAlbedo1`, `PiraGRI`, `Chu`, `chuTotal`, `Umid`, `velVento`, `tempAmb`, `tempMod`,
    `tempCell1/2`, `sn`, `tpLei`, `time_cycle`.
- **Só 83 de 143 usinas têm estação.** Usina sem estação devolve HTTP 200 com zero registros.
- **Virada do dia:** logo depois da meia-noite a rota ainda devolve o acumulado de ontem. Rodar a coleta nessa hora
  grava o dia errado (aconteceu em 17/06).

### 3.6 `POST /custom_query`

Corpo comum: `{"id": pid, "data_type": "<tipo>", "period": "AAAA-MM", "day": N}`. Sem `day`, 401; com `day=0`,
lista vazia. **Não existe consulta do mês inteiro.**

- **`energy`** — o kWh do dia por inversor, de **qualquer dia**:

  ```json
  [ { "dataleitura_new": "2026-06-03 00:00:00", "eday": "1490.51", "idinversor": 46058 }, ... ]
  ```

  - `idinversor` casa com o `device_id` do `plant_devices`;
  - é leve: ~1,5 s por usina-dia; 390 chamadas em 5 min sem erro.
- **`meteo`** — o dia inteiro da estação para dias passados, no formato do `day_meteo` (1,2 a 1,4 mil leituras):
  - backfills de 18 a 25 dias atrás funcionaram (19/06, 25/07 e 21/09);
  - a latência variou muito: ~112 s por usina em junho, com 60% passando de 180 s no pico; 0,5 a 4 s na oem@ em
    setembro;
  - **não paralelizar.**
- **`inverter`** (descoberto em 17/09, na v2) — o dia inteiro dos inversores:
  - de 1 a 8 dias atrás: HTTP 200 com 9,6 a 14,4 mil registros;
  - 10 e 15 dias atrás: HTTP 502 depois de 181 s;
  - 30 dias ou mais: lista vazia em 1 s;
  - ~146 s por usina de 10 inversores.
- **`combiner`** (v2, descoberto em 16/09) — o dia inteiro por combiner:
  - **o `period` vai sem hífen: `AAAAMM`**, ao contrário da v1;
  - devolve `{idcombiner, conteudojson (Ipv1..N, Upv*, Pac, ChaSec, Dps, sn), tsleitura}`, uma leitura a cada
    ~2 min por combiner;
  - o `sn` é "CMB" + o `device_esn` do inversor, o que dá um de-para exato;
  - cobertura parcial: 10 de 20 usinas String Box; na Tanabi 2, 4 de 20 inversores;
  - conferido contra a PV Plataforma: 3 de 4 combiners bateram, diferença de 0,00 A. Custa 9,4 s por usina, contra
    ~25 s **por inversor** na Plataforma.

### 3.7 `POST /trackers` (descoberto em 22/09)

```http
POST /api/v1/trackers
{"idusina": 21480, "date": "23/09/2026"}
```

- Rota própria, fora do `custom_query`. O campo é **`idusina`**, não `id`, e a data vai em **DD/MM/AAAA** (é a única
  rota da API PV com esse formato).
- Devolve o **dia inteiro**: uma entrada a cada ~2,5 min, cada uma com todos os trackers (valores ilustrativos):

  ```json
  [ { "tsleitura": "...", "conteudojson": { "Trackers": [ { "TRK1": { "posAg": 12.3, "posAl": 12.5, "aComm": 0, ... } } ] } } ]
  ```

- Campos que importam: `posAg` (posição), `posAl` (alvo), `aComm` (1 = sem comunicação), `sTrkOK` e `crgBat`. São 38
  campos por tracker.
- A lista é plana: vêm também os trackers que não estão ligados a nenhum inversor.
- **Parâmetros ignorados:** `last`, `limit`, `init/end`, `hora` e `ultima`. As seis variantes devolveram as mesmas 610
  leituras e 13,8 MB. Ou seja, **só existe o dia inteiro**, e a frequência de busca é a única alavanca de custo.
- `tsleitura` já vem em hora de Brasília: **não converter**.
- Os registros vêm fora de ordem.
- **Volume:** 8,85 MB por usina-dia na média de 16 usinas (faixa de 8,8 a 13,8 MB), contra 0,375 MB do instantâneo da
  Plataforma. Buscando a cada 5 min seriam ~8 GB/h nas ~80 usinas; a cada 30 min, ~1,4 GB/h, menos que os ~2,0 GB/h da
  fonte anterior.
- Validação na troca de fonte: 52/52 trackers e 29.551/29.551 pontos da curva idênticos à Plataforma, diferença
  máxima de 0,000°.
- Cobertura: 80 de 146 usinas na principal e 88 de 155 na oem@, nenhuma negada (a oem@ traz os 100 trackers da Tupi).

---

## 4. Identificadores e de-para

- **`plant_id` / `idusina`:** global, o mesmo na API PV e na PV Plataforma.
- **`idefinversor`:** o mesmo `idInversor` da Plataforma, único no sistema inteiro.
- **`device_id` ≠ `idefinversor`** em alguns inversores: o casamento é pelo nome, via aba **Equipamentos** do
  BD_Performance (colunas `Usina Supervisório` e `Equipamento Supervisório`).
- **Cada skid ou cabine é uma usina separada:** Indaiatuba 1–4 (21480–21483), Fernandópolis 1/2/3
  (338980/338984/338983), Nova Londrina 1/2 (22854/22855), Altair 1–5, Ouro Branco 1–5.
- **Nomes mudam mantendo o id.** Casar por nome exato quebra em silêncio (ver [§9](#9-incidentes-e-lições)). O coletor
  normaliza acento, caixa, espaço e sufixo; a plataforma usa `_equip_key` para juntar "INVERSOR01" e "INVERSOR 01".
- **Apelidos:** `PV_NOME_API_ALIAS = {"Sete Lagoa": "Sete Lagoas"}` (a API escreve no singular).
- **Nome de inversor da oem@:** fechado por valor em três lugares: `PV_INV_NOMES` na plataforma, o `config.toml` do
  gêmeo e o de-para fixo em `coletar_semp.py` no coletor.

---

## 5. Comportamentos medidos

### 5.1 Hoje × dias passados

| Dado | Hoje | Dia passado |
|---|---|---|
| Inversores (correntes, potência) | `day_inverter` | `custom_query` `inverter`, até ~8 dias |
| Energia por inversor | `custom_query` `energy` | `custom_query` `energy`, qualquer dia |
| Estação | `day_meteo` | `custom_query` `meteo` |
| Combiner | `custom_query` `combiner` | idem |
| Trackers | `trackers` | idem |

Alcance real do dado: a Morada Nova só tem dado na oem@ a partir de 05/08; a Ceilândia 1 tem irradiância mas zero
geração em 04, 05 e 12/08.

### 5.2 Fuso horário

- `tsleitura_new` vem em **hora de Brasília para todas as usinas**, inclusive Araputanga (MT, UTC−4). Medido pelo
  gêmeo em 11/09; a auditoria de 30/06 já apontava Brasília para API PV, PostgreSQL e 2C.
- O "GMT" ou "Z" nos carimbos é falso.
- **Incidente de 22/09:** o servidor Linux rodava em UTC, e 108 de 115 usinas apareceram "sem comunicação".
  Conserto: `TZ=America/Sao_Paulo` no serviço, mais a trava `_conferir_fuso()`.

### 5.3 Volumes e latências

| Chamada | Volume | Tempo | Quando |
|---|---|---|---|
| `day_inverter` | até ~2 MB (Saturnino); ~23 mil registros/dia (Tupi) | 7 s (Tupi) | 11/09 |
| `custom_query` `energy` | pequeno | ~1,5 s por usina-dia | 10/09 |
| `custom_query` `meteo` | 1,2–1,4 mil leituras | ~112 s por usina (jun); 0,5–4 s (set, oem@) | 14/06; 11/09 |
| `custom_query` `inverter` | 9,6–14,4 mil registros | ~146 s por usina de 10 inversores | 11/09, 17/09 |
| `custom_query` `combiner` | 720 leituras/dia (Tanabi 2) | 9,4 s por usina | 16/09 |
| `trackers` | 8,85 MB médio por usina-dia | 3,3 s por usina-dia | 22/09 |
| Varredura inteira de trackers | ~80 usinas | 897 s | 22/09 |
| Aba "Thopen · API PV" (todas as usinas) | — | ~4 min fria (set) | set |

À noite a API congestiona (timeouts em massa); de manhã responde em ~20 s por chamada (19/06).

### 5.4 Limites e sinais de sobrecarga

- **Nenhuma cota numérica documentada.** O que se observou:
  - bloqueio do `/authenticate` quando chamado seguidamente;
  - o gateway desiste com **502 aos ~181 s** em consultas pesadas;
  - 502 também em dias recentes sob carga (inversores de 08–09/09, pedidos em 11/09, falharam nas três usinas da 2C).
- **No coletor, um 502 aparece como usina com 3 ou mais inversores a menos.**
- **Queda de DNS em 16/07:** o domínio `pvoperation.com.br` inteiro deu SERVFAIL, visto de fora (Google e Cloudflare).
- **Concorrência adotada:** a plataforma faz 3 passadas (8 workers → 4 → sequencial) e limita o aquecimento a 4, 3 e 2
  workers ("com mais, a API PV já nos bloqueou"); o coletor usa 5 threads; o histórico de meteorologia vai em série.

---

## 6. Qualidade do dado

- **GHI:** `IrGHI` vem ~0 em muitas usinas, e em Ouro Branco 1–5 é cópia do POA. O campo bom é **`piraGHI1`**, lido
  primeiro desde 25/07.
- **Nome de campo de irradiância não garante o valor:** na Tupi, `piraPOA1` = 4.921 W/m² e `piraGHI1` = `'-'`; em
  Araputanga e Sete Lagoas, `IrGHI` na casa de 41 milhões. As regras em uso:
  - o coletor descarta |valor| ≥ 2000 W/m² (ex.: −666) e zera negativos;
  - a plataforma escolhe o maior valor plausível até 1.600 W/m²;
  - o gêmeo aceita até −20 W/m² (offset noturno do sensor).
- **Chuva:** `Chu` é constante por leitura (a Fazenda Limão marca 0,2 em todas as 1.433 leituras, somando 286 mm) e
  `chuTotal` tem saltos sem sentido (0 → 715 → 0). **O pluviômetro não é confiável.** O coletor usa o maior menos o
  menor `chuTotal`, limitado a 0–150 mm, e marca em laranja o valor duvidoso.
- **Strings:** há canais `Ipv` fantasmas (hardware não usado), leituras sem nenhum `Ipv` e String Box só com
  `Imppt1/Pmppt1/Umppt1` (Sarandi, Platina). A Tanabi é inconsistente entre inversores.
- **Trackers:** o alvo `posAl` é "furado", porque acompanha o próprio tracker travado. As réguas usam o **desvio da
  mediana da frota**.
- **Conferências que deram certo:** energia da oem@ igual ao e-mail da 2C até o décimo de kWh (IPOA da Araputanga de
  09/09, 2,4% abaixo); defasagem POA × potência de 0 min, correlação de 0,89 a 0,99 (17/09).

---

## 7. Como a Grid Co usa

### 7.1 Plataforma de Performance (porta 5050)

**Fontes da API PV** (seletor do Monitoramento):

| Fonte | Conta | Usinas |
|---|---|---|
| Thopen · API PV (`/api/data`) | principal | recorte Full O&M do cadastro Equipamentos, menos as usinas das outras fontes |
| SEMP (`/api/semp/data`) | oem@ | Tucano 1 e 2 |
| Alves Lima (`/api/alveslima/data`) | oem@ | Morada Nova |
| 2C (`/api/2capi/data`, exibida junto com o e-mail no card "2C") | oem@ | Araputanga, Sete Lagoas, Tupi Paulista |

O recorte está em `PV_FONTES`, e `_pv_token_for(plant_id)` escolhe o token. O `get_plants` junta ao catálogo da
principal as usinas da oem@.

**Funcionalidades e de qual rota dependem:**

| Funcionalidade | Rotas da API PV |
|---|---|
| Tabela de strings (também alimenta a Entrada, o macro/Painel NOC e o sino) | `plants`, `day_inverter` por usina, `combiner` (String Box), `plant_devices` |
| Drill por inversor | `day_inverter`, `plant_devices`, `combiner` (Plataforma de reserva) |
| Curva das strings | hoje: `day_inverter` + `plant_devices`; dia passado: **PV Plataforma** (`trygenerate`) |
| Strings sem corrente, ocorrências (caiu → voltou), Perdas → Strings | `day_inverter` hoje; dia passado pela Plataforma |
| ETM (estação meteorológica) | `day_meteo` (dia passado devolve "sem histórico" na tela) |
| PR por inversor | `day_inverter` + `plant_devices`; String Box, `day_meteo` |
| Trackers (overview, drill, gráfico, parados, frota parada, ronda, eventos, Entrada) | `trackers` (Plataforma de reserva) |
| Padrão por inversor (usinas sem visão por string) | `custom_query` `energy` + `plant_devices` |
| Qualidade de dado (clipping, valor travado), só a 2C | `Pac` do `day_inverter` |
| Diagnóstico v2 | as rotas acima; `temp` e `pac` do inversor só de hoje |
| Histórico e geração por inversor | **não usa a API PV**: lê BD_Thopen e BD_Performance |

**Régua de strings** (`_classifica_strings`, relativa à mediana do próprio inversor):

| Estado | Regra |
|---|---|
| trancada | marcada à mão (MPPT sem string); fora da contagem |
| inativa | mediana do inversor < 0,5 A (noite, nublado); não é falha |
| sem_corrente | ≤ 0,1 A com o inversor produzindo |
| baixa_perf | < 60% da mediana das demais |
| ativa | o resto |

Outras réguas: comunicação a 30 min; temperatura a 65 °C; inversor desligado quando o `Pac` fica abaixo de
max(2 kW, 5% da mediana dos pares), de dia; sem sol (elevação < 8° no estado da usina ou fora de 07–18 h) nada é julgado.

**Cache e cadência.** A plataforma roda em dois processos: o `worker.py` aquece os caches e publica em
`cache_snapshot.json`; o processo web só lê e serve.

| O quê | Cadência | Observação |
|---|---|---|
| Token (principal e oem@) | até `exp` − 60 s | só em memória, cada processo faz seu login |
| Catálogo `/plants` | 5 min | |
| Abas de strings, ETM, PR | ~5 min (`CACHE_TTL`), refeitas no ciclo do worker | a aba principal sai primeiro (etapa 2), o resto em 3 workers |
| PR e parados | 1 ciclo a cada 3 | |
| Trackers (`_pv_trk_loop`) | laço próprio; o dia de cada usina é baixado no máximo a cada 30 min | fora do ciclo desde 22/09: a varredura levava 897 s |
| Padrão por inversor, qualidade | 1×/h | |
| Sino de strings | a cada 30 min, 05:40–18:20 | |
| Combiner | 5 min; em falha mantém a leitura anterior | leitura com mais de 6 h é descartada |
| `plant_devices` | 30 min | |

**Não há pausa noturna para a API PV** (a pausa da noite é só da SunOp). No web, cache vencido é servido como
"stale" sem reconstruir; `force=1` reconstrói na hora.

**Robustez:** token em cache; 3 passadas na busca da aba principal; `_last_known` guarda a última linha boa de cada
usina; trackers vazios não entram no cache. **Não há disjuntor para a API PV**, e o token não é renovado ao receber
401, só por validade.

### 7.2 Coletor (BD_Thopen e BD_Performance)

**Onde mora:** o coletor que roda **não está neste repositório**.

- Código-fonte: `C:\Users\Levi Maia\OneDrive - GRID CO\Área de Trabalho\temp\coleta API PV\src\`. É um repositório git
  próprio, com **um único commit (03/08/2026)**, os módulos da API PV modificados sem commit e vários módulos nunca
  versionados (`coletar_semp.py`, `coleta_2c.py`, `estado_coleta.py`, `fechamento_noturno.py`, `cobertura_aba.py`).
- Instalado: `%LOCALAPPDATA%\Coletor GridCo\` (exe v1.9.14, de 14/09).
- A pasta `coletor/` deste repositório tem só dois scripts avulsos (`collect_energy.py` e `coletar_geracao_hoje.py`),
  que geram um `.xlsx` solto e não gravam em BD nenhum.

**Etapas por dia:**

| Etapa | Conta | O que faz |
|---|---|---|
| 1/5 | principal | energia por inversor (`custom_query` `energy`) e IPOA/GHI integrados no dia (`day_meteo` hoje, `custom_query` `meteo` dia passado). Grava no **BD_Thopen**, na aba da usina e na linha do dia (`Inversor X.Y`, `IPOA (kWh/m²)`, `GHI (kWh/m²)`). O de-para vem da aba Equipamentos do BD_Performance |
| 1b/5 | — | PostgreSQL, para as usinas que sumiram do `/plants` em 27/08 (23 contadas na época; o coletor do PostgreSQL cobre 22) |
| 4b, 4c, 4d | oem@ | Tucano 1 e 2, Morada Nova e a 2C para o **BD_Performance** (IPOA, GHI, temperatura da Tucano, inversores). Na 2C a API manda e o e-mail completa o que faltar |
| 5/5 | ambas | chuva (`Chuva (mm)`) |
| 5b/5 | — | chuva nula vira 0 quando o IPOA/GHI do dia chegou. **Só no fonte, ainda não está no exe** |

**Integração da irradiância:** trapézio no tempo dos W/m², dividido por 1000, dá kWh/m². Cada caminho trata lacuna
de um jeito: a produção não limita lacuna; o script do repositório ignora saltos acima de 1 h; o coletor do
PostgreSQL não integra lacunas acima de 30 min.

**Cadência** (tarefas do Agendador, conferidas em 23/09):

- **"Coletor GridCo - 22h30":** roda o exe. Antes das 22:30 o alvo é ontem; depois, hoje. Coletar um dia em andamento
  grava um parcial com cara de dia inteiro: em 04/08 foram 35.788 kWh gravados em vez de 525.951. Junto do alvo,
  entram até 3 dos últimos 5 dias que não fecharam.
- **"GridCo Fechamento Noturno" (23:30):** refaz D-1 a D-3 (um processo por dia), roda o PostgreSQL, recalcula o
  BD_Thopen no Excel e sobe pelo `sync_gridco_api.py`
  (`POST .../db_performace/api/workbooks/<key>/sync-xlsx?replace=true`). Sobem só valores, nenhuma fórmula. Dia com
  15 ou mais usinas "escuras" volta para a fila.

**Travas:**

| Trava | O que impede | Onde vale |
|---|---|---|
| Dia zerado | em dia fechado, se menos de 50% dos registros vierem acima de zero, não grava (`GRIDCO_ACEITA_ZERO=1` força) | **só no caminho do BD_Thopen** |
| Meteorologia cobre o dia | só aceita a estação se a 1ª leitura for até 07 h e a última depois das 17 h | **só no caminho oem@** |
| `cobertura_aba` | backfill de uma planta só não zera as outras plantas da mesma aba | backfill |
| Planilha aberta | pula a gravação | todos |

**Erros:** login com 5 tentativas (espera de 8 × n s); em 401 reautentica e repete uma vez; **não há retentativa
para 5xx nem para timeout**; o erro de uma usina não derruba a etapa, que por isso sai "OK" mesmo com usina faltando.
O Check pós-coleta compara o dia com os vizinhos, acusa renome pela aba `Sem_Correspondencia` e grava
`logs/ALERTA_COLETA_<dia>.txt`.

### 7.3 Gêmeo Digital (porta 5075)

- **Fonte `apipv`**, conta oem@, só as três usinas da 2C: Araputanga (18771898), Sete Lagoas (18771901) e Tupi
  Paulista (18750925). O de-para `idefinversor` → nome foi conferido valor a valor e fica no `gemeo/config.toml`.
- **Descoberta:** cria a estação `ESTM`, os inversores (código = `idefinversor`) e as strings `<idef>.Ipv<n>`, e
  preenche lat/lon e kWp da usina a partir do `/plants`.
- **Busca:** `day_inverter` e `day_meteo` uma vez por ciclo (cache de 60 s). Dia passado entra pelo `custom_query`
  (`inverter` e `meteo`) só se a janela cobre ao menos 2 h dele.
- **Grava** na tabela `leitura` do SQLite: `p_ac`, `e_dia`, `i_string`, `poa`, `ghi`, `temp_modulo`, `temp_ar` e
  `vento`; inversor a cada 5 min, string a cada 15, estação a cada 1. Upsert com o valor novo vencendo; retenção de 90
  dias; cada ciclo deixa registro em `ingest_run`.
- **Cadência:** ciclo a cada 15 min, com 30 min de sobreposição; o 1º ciclo de uma usina busca 3 dias para trás; às
  03 h UTC (meia-noite de Brasília) refaz as últimas 24 h. Backfill manual:
  `python -m tools.backfill_apipv "<usina>" AAAA-MM-DD AAAA-MM-DD` (fim exclusivo, uma usina por vez, fora de pico).
- **Erros:** em 401 repete uma vez; em 429 ou 5xx abre um disjuntor de 90 s; erro em objeto vira exceção com o texto.
  O `/healthz` acusa depois de 120 min sem ciclo em horário solar. No log de ingestão há 101 "[apipv] ciclo falhou" e
  22 "custom_query: HTTP 502".
- **Trackers dessas três** não vêm da API PV: desde 21/09 o gêmeo os lê da própria Plataforma de Performance.

### 7.4 Dashboard Thopen (porta 5080)

Não chama a API PV. Lê o BD_Thopen já gravado pelo coletor, pela Gridco Performance API.

---

## 8. Operação: credenciais, sintomas e diagnóstico

### 8.1 Onde ficam as credenciais (só os nomes)

| Projeto | Onde | Chaves |
|---|---|---|
| Plataforma | `.env` da raiz, com o `tokens.txt` valendo antes | `PV_USERNAME`, `PV_PASSWORD`, `PV_OEM_USERNAME`, `PV_OEM_PASSWORD` |
| Coletor | variáveis de ambiente, senão `config.ini` ao lado do exe | `[api] usuario, senha, workers`; `[api_oem] usuario, senha`; `[coleta] usinas_fora`; `GRIDCO_ACEITA_ZERO` |
| Gêmeo | `SECRETS_DIR/gemeo.env` | `PV_OEM_USERNAME`, `PV_OEM_PASSWORD` |

O painel `/api/tokens` da plataforma mostra a linha "API PV" como auto-login (nunca alarma) e só o `exp` da conta
principal.

### 8.2 Sintoma → causa provável

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `Invalid id` numa usina | token da conta errada para ela, ou id fora do corpo JSON | conferir `PV_FONTES` / `_pv_token_for` e o formato da chamada |
| login devolve 500 ou algo que não é JSON | autenticação repetida | conferir o cache do token |
| usinas "sem comunicação" em massa | processo fora do fuso de Brasília | `TZ=America/Sao_Paulo` no serviço |
| usina com 3+ inversores a menos no dia | 502 da API sob carga | recoleta direcionada da usina, fora de pico |
| dia inteiro zerado | a API devolveu `eday=0` (caso de 05/09) | a trava recusa; recoletar mais tarde |
| "0 ok / 1101 sem corresp." no coletor | etapa da principal rodando autenticada na oem@ | um processo por dia |
| detalhe sem strings de dia passado | `day_inverter` só tem hoje | dia passado sai da PV Plataforma (`trygenerate`) |
| usina "sumiu" da coleta | renome na API ou saída do `/plants` | casar por `plant_id`; conferir o alerta de `Sem_Correspondencia` |
| IPOA de um dia muito baixo | estação cobrindo só parte do dia | trava de meteorologia que cobre o dia (caminho oem@) |
| payload de ETM inteiro vazio | uma usina devolveu erro em objeto | ver [§12](#12-riscos-e-pontos-abertos) |

---

## 9. Incidentes e lições

| Data (2026) | O que aconteceu | Lição ou trava |
|---|---|---|
| 11/06 | recoleta do dia inteiro de Barretos com a API devolvendo 2 de 40 inversores apagou 38 colunas boas | recoleta direcionada por usina; restaurado do `.bak` |
| 15/06 | o drill de usina parada abria em branco (`day_inverter` só tem hoje) | a tela explica |
| 17/06 | coleta rodada depois da meia-noite gravou o meteo de ontem no dia errado | cuidado com a virada do dia |
| 24/06 | Indaiatuba 1 com 29 strings na linha e 157 no detalhe (leituras sem `Ipv`) | usar a última leitura com `Ipv` |
| 15→27/07 | a API separou Nova Londrina em 22854 e 22855; a cabine 1 foi sobrescrita em silêncio | cadastro por `plant_id` |
| 16/07 | queda de DNS de `pvoperation.com.br` | só a fonte API PV cai; a ronda levou ~6 min tentando |
| 16→22/07 | Nova Iguaçu renomeada e dividida em 2.1 e 2.2; a coleta parou | normalização de nome |
| 25/07 | `IrGHI` zerado ou copiado do POA em 26 usinas | `piraGHI1` primeiro; julho recoletado |
| 16–17/08 | a API passou a escrever "Ceilandia" sem acento; 7 usinas e 70 equipamentos deixaram de casar | chave que ignora acento, caixa, espaço e sufixo |
| 16→26/08 | PR congelado 9,8 dias: usinas da oem@ consultadas com o token principal, e o `Invalid id` em objeto derrubava as 104 | `_pv_token_for` e proteção contra resposta em objeto |
| 19/08 | 22 de 144 usinas do cache com nome divergente (ex.: Caicó 1.1) | casar sempre por `plant_id` |
| 20→26/08 | "INVERSOR 01" renomeado para "INVERSOR01" parou a coleta da Rodrigues 2 por 6 dias | chave normalizada |
| 27→31/08 | 23 usinas sumiram do `/plants`, e a etapa 1/5 seguia dizendo OK | essas usinas passaram para o PostgreSQL (`coletar_pg.py`) |
| 05/09 | recoleta de 03/09 veio com `eday=0` em tudo e apagou 67 usinas (às 23:01 a mesma chamada já trazia os valores) | trava de dia zerado |
| 05/09 | a etapa da oem@ deixou a conta trocada dentro do módulo; os dias seguintes saíram com "0 ok / 1101 sem corresp." | recarregar o módulo no `finally`; um processo por dia |
| 11/09 | Araputanga entrou na API com meteo só a partir das 16:15 (IPOA 1,27 em vez de 8,65) | trava de meteorologia que cobre o dia |
| 11/09 | backfill de uma só usina numa aba compartilhada zerou 101.152 kWh da outra cabine | `cobertura_aba.py` |
| 16/09 | combiner da Plataforma congelada desde 28/05 no INVERSOR02 da Tanabi 2 | API PV primeiro; leitura com mais de 6 h descartada |
| 22/09 | servidor Linux em UTC: 108 de 115 usinas "sem comunicação" | `TZ` no serviço e trava de fuso |
| 22/09 | com trackers desde 00:00, apareceu que a régua v2 não recortava 06–18 h (70 de 1.049 viraram parados) | janela solar na régua |
| 23/09 | Sto Antônio da Platina com 40 de 40 inversores idênticos de 08 para 09/09 (dia clonado na origem) | agrupar a ronda de buracos por dia clonado |

---

## 10. Decisões registradas

| Data (2026) | Decisão |
|---|---|
| 10/06 | curva de strings sai da PV Plataforma e passa para a API PV (`day_inverter`) |
| 11/06 | PR ao vivo da API não entra em tela: gráfico só com dado do banco |
| 22/06 | histórico de strings: hoje por corrente (API PV), dias anteriores por potência (Plataforma) |
| 23/06 | a aba "Thopen · API PV" é a aba piloto; o que for aprovado ali é replicado nas outras fontes |
| 05/08 | "String Box" vira topologia, não motivo para silenciar a régua |
| 19 e 24/08 | uma credencial oem@ atende dois clientes; a fonte é o **cliente**, não a conta |
| 10/09 | Morada Nova desligada; padrão por inversor só nas usinas escolhidas |
| 11/09 | as três da 2C passam do e-mail para a API PV (Ipixuna segue no e-mail); no tempo real, card único "2C" |
| 15/09 | Tucano 2 entra; trackers da SEMP ligados |
| 17/09 | qualidade de dado (pvanalytics) só na 2C; clipping não conta como perda |
| 22/09 | trackers passam para a API PV; o token da PV Plataforma vira reserva |

---

## 11. API PV Operation × PV Plataforma

| | API PV Operation | PV Plataforma |
|---|---|---|
| Endereço | `apipv.pvoperation.com.br/api/v1` e `/v2` | `apiplataforma.pvoperation.com/v2` (portal `plataforma.pvoperation.com`) |
| Autenticação | usuário e senha → JWT em `x-access-token`; renova sozinha | JWT de sessão do navegador em `x-auth-token-update`, com CAPTCHA (Cloudflare Turnstile) e MFA por e-mail |
| Validade | `exp` do JWT, renovado automaticamente | **7 dias**, sem endpoint de refresh; renovação à mão (bookmarklet/userscript que posta em `/api/pv/trackers/token`) |
| Permissão da oem@ | normal (menos `plant_devices`) | com a sessão gridco, usina da oem@ volta HTTP 200 "Usuário não possui permissão…" |
| Papel hoje | fonte principal de strings, inversores, ETM, combiner e trackers | reserva de trackers e combiner; **ainda principal para a potência histórica por string** (`trygenerate`) |
| Proteção na plataforma | nenhum disjuntor | disjuntor que abre no primeiro 401 |

Os ids são os mesmos nas duas. A Plataforma é frágil sob carga: um re-backfill a ~3,4 req/s deixou-a respondendo 502
por mais de 15 min (26/06).

---

## 12. Riscos e pontos abertos

**Coletor**

- **O código que roda está fora do repositório**, com um único commit (03/08) e módulos nunca versionados. Uma perda
  daquela pasta leva o coletor junto.
- **O exe instalado (v1.9.14) está atrás do fonte:** a etapa 5b/5 existe só no código.
- **A trava de dia zerado não cobre o caminho oem@ → BD_Performance:** lá, zeros da API viram 0 vermelho.
- **Possível defeito, por leitura de código:** a trava de dia zerado encerra com `SystemExit`, e o `run()` do
  `coletor.py` só captura `Exception`. Se ela disparar no exe, o processo inteiro para (etapas seguintes, dias
  seguintes, anotação de estado e auto-update).
- Não há retentativa para 5xx e timeout, e a etapa sai "OK" com usina faltando.
- Há três `config.ini` (fonte, `dist` e instalado) e dois arquivos de estado.
- Até 30/07 a senha ia embutida no exe, e até 05/08 no `config.ini.exemplo` do instalador. Vale confirmar que a
  senha foi trocada depois disso.

**Plataforma** (achados por leitura de código, não verificados em execução)

- `_pv_plant_inversores` e `_spv_usina_historico` chamam `get_plants` com o token da usina. O cache do catálogo é um
  só, e o próprio código avisa que a lista da oem@ gravada ali sumiria com as outras.
- Algumas rotas usam o token principal fixo, em vez de `_pv_token_for`: exportação de ETM, correlação,
  eventos de string e PR. Usina da oem@ que esteja no Full O&M receberia `Invalid id` nelas (a SEMP está).
- Os montadores de ETM não se protegem de resposta em objeto: um erro de uma usina derruba o payload inteiro da fonte.
- O cache do dia de trackers não vai no snapshot: no processo web, o primeiro gráfico baixa o dia inteiro dentro da
  requisição (até ~13 MB). Resposta vazia de trackers nunca entra no cache, então usina sem tracker é consultada de
  novo a cada reconstrução.
- A ETM do Alves Lima está fora do snapshot.
- Não há re-login ao receber 401 (só por validade), e há código que nunca roda (`custom_query` `inverter` no
  histórico da curva).

**Gêmeo**

- Uma falha na descoberta (timeout ou 502) derruba o ciclo das três usinas sem registro em `ingest_run`.
- A documentação dele ainda pede `PV_PLAT_TOKEN_OEM`, que não é usado desde 21/09.

**API e decisões pendentes**

- Sem cota documentada; a permissão de `plant_devices` para a oem@ está pedida à Solan.
- Não mapeados: leitura do medidor, PR ao vivo e se o `custom_query` `inverter` alcança 10–15 dias em pedaços menores.
- A validade real do JWT não foi medida.
- Pendente com o Levi: migrar os trackers da 2C do e-mail para a API (chega ~2h45 mais fresca), ligar PR e Perdas na
  SEMP e a proposta de "coleta única" (ainda só desenho).

---

## 13. O que mudou desde a versão de 10/06

| Ponto | Versão de 10/06 | Hoje |
|---|---|---|
| GHI | `IrGHI` primeiro | `piraGHI1` primeiro (desde 25/07) |
| Histórico de meteorologia | "não existe, só o dia corrente" | existe: `custom_query` `meteo` |
| Histórico de inversor | não existia | `custom_query` `inverter`, até ~8 dias (17/09) |
| Combiner | "tipo inexistente" | existe na v2, `period` sem hífen (16/09) |
| Trackers | não citados (eram da PV Plataforma) | rota `trackers` da API PV, fonte principal desde 22/09 |
| Versões | só v1 | v1 e v2 |
| Contas | uma | principal e oem@ |
| Usinas em `/plants` | ~142 | 146 na principal, 155 na oem@ |
| `plant_devices` | POST | POST ou GET com corpo JSON |

---

## 14. Onde está no código

Linhas conferidas em 23/09/2026 (commit `4474d65`); podem andar com o tempo.

**Plataforma** (`plataforma/app.py`, salvo indicação)

| O quê | Onde |
|---|---|
| Base v1 e credenciais | `BASE_URL` (~762), `PV_USERNAME`/`PV_PASSWORD` (~763) |
| Token principal e oem@ | `get_token` (~2095), `get_token_oem` (~2189) |
| Contas e recorte | `PV_FONTES` (~2140), `_pv_token_for` (~2254), `_pv_plantas_da_fonte` (~2222) |
| Catálogo | `get_plants` (~2262) |
| Busca da aba principal | `fetch_all` (~2593), rota `/api/data` (~4035) |
| Drill por inversor | `_pv_plant_inversores` (~2690) |
| Régua de strings | `_classifica_strings` (~2340) |
| ETM | `fetch_etm_plant` (~4099), `_analisa_etm_plant` (~4417) |
| Combiner v2 | `PV_V2_BASE` (~7343), `_pv_comb_parse` (~7376), `_pv_combiner_usina` (~7432) |
| Trackers | `_pv_trk_dia` (~8563), `_pv_trk_loop` (~19468) |
| Padrão por inversor | `coletar_dia` em `plataforma/inv_padrao.py` (~160), `_inv_padrao_loop` (~11901) |
| Qualidade | `plataforma/qualidade.py`, `_qualidade_usina` (~11943), `_qualidade_loop` (~12017) |
| PR | `_pv_pr_collect` (~18162), `_pv_pr_compute` (~18239), rota `/api/pv/pr` (~18319) |
| Curva das strings | rota `/api/spv/usina/<id>` (`api_spv_usina`, ~18766), dia passado em `_spv_usina_historico` (~18728) |
| Aquecimento no worker | `_prewarm_loop` (~19542) |

**Coletor** (`C:\Users\Levi Maia\OneDrive - GRID CO\Área de Trabalho\temp\coleta API PV\src\`)

| O quê | Onde |
|---|---|
| Base e credenciais | `config.py` (61–73) |
| Login, chamadas, integração da irradiância | `coletar_pvoperation.py` |
| Conta oem@ (SEMP, Alves Lima, 2C) | `coletar_semp.py`, `coleta_2c.py` |
| Gravação no BD_Thopen (e trava de dia zerado) | `preencher_bd_thopen.py` (176–196) |
| Gravação no BD_Performance | `preencher_bd_performance.py` |
| Etapas, fechamento e estado | `coletor.py`, `fechamento_noturno.py`, `estado_coleta.py` |
| Subida para o banco | `sync_gridco_api.py` |

**Gêmeo** (pasta `gemeo/` deste repositório)

| O quê | Onde |
|---|---|
| Fonte `apipv` | `gemeo/gemeo/ingest/apipv.py` |
| Configuração e credenciais | `gemeo/gemeo/core/config.py`, `gemeo/config.toml` |
| Backfill manual | `gemeo/tools/backfill_apipv.py` |
