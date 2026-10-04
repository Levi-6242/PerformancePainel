# Economia de requisições na API da SunOp

Como a plataforma passou a caber (ou tenta caber) na cota da SunOp, o que foi cortado, por quê e o que foi medido
antes e depois. Atualizado em 04/10/2026.

## A cota

- **100.000 requisições por mês** na conta da Athon (plano `settings-default`). Acima disso, **US$ 0,0005 por
  requisição**.
- Para caber, o teto é de **~3.300 por dia** (~140 por hora), somando o servidor e o PC do Levi.
- A Axis é outra conta da SunOp e não gasta esta cota. Mas, por decisão do Levi (04/10), ela entra no teto de
  3.000 por dia da plataforma (ver abaixo).

### Onde medir

| O quê | Como | Observação |
|---|---|---|
| **Extrato oficial** | `GET {SUNOP_DATA}/v2/usage/me?start=AAAA-MM-DD&end=AAAA-MM-DD`, com o token de API da plataforma | Não é cobrável. O dia é em **UTC** (começa às 21:00 de Brasília) e consolida em lotes: não serve para janela curta |
| **Contador da plataforma** | `GET /api/sunop/uso` em cada máquina (servidor e PC) | Por dia (horário de Brasília), por serviço e por tipo: `analog_values:trk` (curva de tracker), `:str` (corrente de string), `:etm` (estação), `last_values:*`, `cfg:*` (serviço de configuração), `axis:*` (outra conta). `_total` é a nossa cota |

O contador soma os dois processos de cada máquina (`logs/sunop_uso_web.json` e `logs/sunop_uso_worker.json`) e
não zera no reinício desde 29/09.

## Antes dos cortes (extrato oficial)

De 01 a 29/09: **323.816 requisições**, 3,2× a cota, com **US$ 111,91** de excedente. Por dia (UTC):

| 20/09 | 21/09 | 22/09 | 23/09 | 24/09 | 25/09 | 26/09 | 27/09 | 28/09 | 29/09 |
|---|---|---|---|---|---|---|---|---|---|
| 2.377 | 7.794 | 8.781 | 12.730 | 20.744 | 26.215 | 14.754 | 23.448 | 24.650 | 25.746 |

## Cortes de 29/09 (commits 722cd73 e ee70830)

Cada corte tem teste em `tests/test_sunop_cota_cortes.py`.

1. **Status em lotes que atravessam usinas** (`_sunop_last_values_multi`, `SUNOP_LV_LOTE = 1000`). A tabela pedia o
   `last_values` em lotes de 500 **por usina**: 19 POSTs por leitura. Agora são 7. A ETM fazia 10 POSTs (1 por
   usina) e agora faz 1. Conferido contra a SunOp real: 7.002 pathnames, nenhum valor diferente.
2. **`check_token` com validade de 15 min** (`SUNOP_TOKEN_VALIDO_S`). Antes, o token era validado na rede a cada
   chamada, e `ensure_sunop_meta` (que abre ~20 montadores) montava o cabeçalho antes de olhar o cache.
3. **Contador completo e cumulativo** (`/api/sunop/uso`). Passou a contar o serviço de configuração (`cfg:`),
   separar a Axis (`axis:`) e o tipo de curva, e somar ao processo anterior em vez de regravar o dia a cada
   reinício.
4. **PC em `SUNOP_COLETA=ronda`** (no `tokens.txt` do PC). O PC fazia a mesma coleta inteira do servidor. Agora
   busca só a curva de tracker da Athon que a ronda do WhatsApp usa, de hora em hora.
5. **Curva de tracker das usinas numa baixa só** (`_sunop_trk_curvas_varias`). Antes eram 9 POSTs, um por usina;
   agora são 3. Conferido: 80.338 pontos iguais.
6. **A Entrada conta os parados da Athon pelo resumo do worker** (`_entrada_trk_do_resumo`), em vez de refazer as
   curvas no processo web a cada 30 min.

### Resultado medido: insuficiente

| | Requisições |
|---|---|
| 30/09, oficial (UTC), 1º dia inteiro depois dos cortes | **19.477** (média de 24 a 29/09: ~22.600) |
| 30/09, contador do servidor | 11.103, das quais **8.707 de curva de tracker** |
| 30/09, contador do PC (em modo ronda) | 9.997, das quais **9.331 de curva de tracker** |

Os cortes tiraram ~15%. A curva de tracker sozinha era ~86% do que sobrou, e o PC em modo ronda deveria pedir
~100 por dia, não 9 mil. Daí a investigação abaixo.

## O vazamento de 01/10: Perdas → Ocorrências rebaixava o mês inteiro toda hora

**Causa:**
1. A SunOp devolve curva **vazia** para os 52 trackers da **MTS100**: o cadastro tem os pathnames, mas não vem
   série nenhuma.
2. `_sunop_eventos_calc` grava a usina no acervo de eventos (`trk_eventos.json`) assim mesmo, com `eventos: []`,
   `cobertura: 0` e `classes: None`. O mesmo acontece com usina de cobertura abaixo de 50% no dia (CPP100, SMP100,
   TIM100 e outras, alguns dias).
3. O teste de "dia completo" das Ocorrências (`_perdas_trk_ocor_cached`) exige que todas as usinas no acervo
   tenham classificação. Com a MTS100 sem classificação, **os 92 dias de 01/07 a 30/09** ficavam "parciais" e
   nenhum entrava no cache.
4. O `_perdas_ocor_warm_loop` (1×/h, de 01/07 até ontem) recalculava todos os dias parciais. Para isso, baixava
   **a curva de cada usina da Athon, uma por uma, de cada dia**. Isso rodava no servidor e no PC; o modo ronda não
   desligava esse laço.

**Correção (01/10, `tests/test_sunop_cota_cortes.py`, seção 5):**
- Usina **sem curva nenhuma no dia** (cobertura 0, o caso da MTS100) não deixa o dia parcial (`_trk_ev_sem_curva`).
- Usina de **curva parcial** (com pontos, mas abaixo de 50%) segue pela curva de reserva, como antes. A diferença é
  que o que a curva classificou passa a contar como visto, então o dia fecha e vai para o cache em vez de voltar
  toda hora.
- A curva de reserva vem **numa baixa só** por dia (≈4 POSTs em vez de ≈10).
- O PC em modo ronda **não aquece** as Ocorrências da Athon e da Axis (`_perdas_ocor_warm_fontes`). Quem abre a
  aba Perdas é o servidor.

**Conferência com dado real (acervo do PC, régua antiga × nova):**
- Nos 23 dias com usina de curva parcial, **0 ocorrências diferentes**.
- Nos demais dias, só a MTS100 ficava sem classificação. A SunOp não tem curva dela (0 pontos em 01/07, 01/08,
  01/09, 15/09 e 30/09), então a curva de reserva não acrescentava nada.
- A primeira versão desta correção tirava também as usinas de curva parcial e **sumia com 168 ocorrências** de
  01/07 a 30/09 (TIM100 em 31/07: 38). Ela entrou no ar por engano às 10:10 de 01/10, num commit de outra sessão
  (1302d77). Foi trocada por esta antes de qualquer decisão sobre o que a aba mostra.

**Medido depois do deploy (2a492b1, no ar 10:41 de 01/10, contador da plataforma):**

| | Curva de tracker, 30/09 | Curva de tracker, 10:41–12:02 | Nossa cota, 12:03–12:18 |
|---|---|---|---|
| Servidor | ~363/h | 62/h (~24/h depois da 1ª passada do aquecimento) | **156/h** |
| PC (ronda) | ~389/h | 7/h | **48/h** (10:41–12:02) |

Juntos dão ~4,9 mil por dia nesse ritmo, contra ~22,6 mil antes (−78%). Ainda fica acima do teto de ~3,3 mil.
Falta confirmar no extrato oficial de 02/10 (UTC).

O que sobra no servidor (12:03–12:18, por hora):

| Tipo | Por hora |
|---|---|
| Curva de string (`analog_values:str`) | 96 |
| Status de string (`last_values:str`) | 28 |
| Curva de tracker | 16 |
| Configuração (`cfg:*`) | 12 |
| ETM (`last_values:etm`) | 4 |

A Axis (outra conta) gastou mais 144/h, quase tudo renovando o token: `refresh_token` e `check_token` 48/h cada.
O `/plants` da Axis responde "Invalid credentials".

### Achado no caminho: um teste gravava no acervo do PC

O `test_os_tres_chamadores_pre_carregam_as_usinas_juntas` (do ee70830) chama o `_sunop_eventos_calc` de verdade, e
essa função salva o acervo.
- Às 09:51 de 01/10, o `trk_eventos.json` do PC (11,7 MB, 93 dias) virou **388 bytes**. O worker regravou o
  arquivo da memória 4 min depois; um reinício nessa janela teria apagado o histórico de trackers do PC.
- Num reinício de 30/09, o worker já tinha carregado as usinas falsas do teste (AAA100 e BBB100, um dia cada).

Desde 01/10 o `conftest.py` isola todos os arquivos de estado que a plataforma grava (`ARQUIVOS_DE_ESTADO`) e
desliga o despejo do contador da SunOp nos testes. `tests/test_isolamento_estado.py` confere a lista contra o
`app.py`.

## Teto de 3.000 por dia e domingo sem SunOp (04/10/2026)

Levi: "temos como limitar em 3000 requisições por dia e domingo não faz requisições?". Respostas dele: domingo, só a
ronda busca; a Axis entra no teto; passou do teto, só a ronda.

- **Domingo**: nenhuma requisição à SunOp, Athon e Axis. A ronda do WhatsApp (08:25 e 13:00) busca.
- **Teto do dia, por máquina**: 2.700 no servidor e 300 no PC (`SUNOP_TETO_DIA`; o padrão sai do `SUNOP_COLETA`).
  Cada máquina só enxerga o próprio contador, então a divisão é fixa. O dia é o de Brasília. O extrato oficial conta em
  UTC (o dia começa às 21:00), então um dia deles não bate exato com o nosso.
- **Passou do teto**: só a ronda busca até a meia-noite.
- **O que conta**: tudo o que o `/api/sunop/uso` conta na máquina (os dois processos e o processo anterior ao último
  reinício), com a Axis e o serviço de configuração.
- **Como a pausa age**: `_sunop_pausa()` diz `None`, `"domingo"` ou `"teto"`. Ela fecha o `_sunop_req` (todo o serviço
  de dados), a validação do token, o `/plants` e o livro de trackers (que vai só pelo banco). O prewarm nem monta as
  abas da SunOp. A ronda abre uma janela (`_sunop_libera_ronda`) enquanto coleta, e a retentativa do mesmo horário
  reaproveita a coleta por 10 min.
- **A pausa não apaga dado**: a tela segura o último dado bom sem prazo (`_sunop_guarda_vazio`), e o topo do
  Monitoramento troca o "ao vivo" por "SunOp pausada · domingo · dado de HH:MM". A Entrada fica com a última contagem.
- **Desligar**: `SUNOP_PAUSA=0` no ambiente. Trocar o teto: `SUNOP_TETO_DIA`.
- **Consequência conhecida**: o registro de trackers de domingo da Athon só tem o que a ronda viu. Os backfills da aba
  de falhas pegam o domingo na segunda.

### Token vencido fora da rede

Medido no `/api/sunop/uso` de 03/10, o servidor gastou 3.011 da Athon e 2.315 da Axis. Da Axis, tudo era recusa:

| Chave (servidor, 03/10) | Requisições | Por quê |
|---|---|---|
| `axis:cfg:check_token` + `axis:cfg:refresh_token` | 1.545 | Token web da Axis vencido desde 17/07 |
| `axis:cfg:plants` + `axis:metadata` | 770 | `/plants` e o catálogo recusados, a cada chamada |
| `cfg:check_token` + `cfg:refresh_token` + `cfg:plants` (Athon) | 542 | Token web da Athon vencido desde 23/07 |

Com o `exp` no passado, o check, o refresh e o `/plants` recusam sempre. Agora `get_sunop_token` não vai à rede: só
adota um token colado pela tela. O `/plants` vai direto à lista do serviço de dados (em disco, 24 h). E a Axis, sem
token de API e com o web vencido, não chama o serviço de dados.

O token de 24 h da Axis renovava a cada chamada, porque "vence em menos de 2 dias" era sempre verdade. Agora ele
renova na metade da vida. Isso só vale quando alguém colar um token novo da Axis.

**A Axis não traz dado desde julho.** Ela não tem token de API e o web venceu. Para voltar, é preciso gerar o token
de API na interface da Axis e guardar como `AXIS_API_TOKEN` no `tokens.txt` (a tela `/tokens` diz o mesmo).

## Para não repetir

1. **Dia fechado sem dado na fonte é resultado, não pendência.** Usina sem curva num dia passado não pode deixar o
   dia "incompleto". Dia incompleto volta a ser buscado, e o que não existe na fonte nunca chega. Foi o caso da MTS100.
2. **Laço que refaz dia passado tem teto.** Toda volta que reprocessa dias antigos precisa de um limite de tentativas
   por dia e de um registro do que pulou. Tentar de novo na próxima hora, para sempre, é vazamento.
3. **Curva da SunOp vai em lote, nunca usina por usina dentro de um laço de dias.** Usar `_sunop_trk_curvas_varias`
   (trackers) e `_sunop_str_hist_varias` (strings).
4. **Medir depois de cada mudança que toca a SunOp.** Olhar o `/api/sunop/uso` das duas máquinas por 1 h, contra o
   teto de ~140/h. Em 29/09 o corte foi dado por bom pela estimativa, e o extrato de 30/09 mostrou que não era.
5. **Teste não grava arquivo de estado.** O `conftest.py` isola todos (`ARQUIVOS_DE_ESTADO`).
6. **Credencial vencida não vai à rede.** Token com `exp` no passado é recusa certa. Bater nele a cada ciclo
   custou ~2.850 requisições por dia de 17/07 a 04/10 sem trazer nada.

## O que ainda gasta e os próximos cortes

| Onde | Situação | Corte possível |
|---|---|---|
| **Ronda do WhatsApp com o serviço fora** | Feito em 04/10: a retentativa do mesmo horário reaproveita a coleta por 10 min | — |
| **Reinícios e deploys** | Cada reinício busca a curva cheia do dia e recarrega as Ocorrências do mês até o cache encher | Guardar o cache das Ocorrências (dias fechados) no snapshot |
| **Gêmeo do servidor vazio** | No servidor a curva nunca vem do acervo do gêmeo (FASE 4): tudo vai à SunOp | Pôr o gêmeo do servidor para ingerir (o do PC foi desligado em 30/09 para o corte) |
| **Curva de string no servidor** | 96/h (~2,3 mil por dia) em 01/10 12:03–12:18, o maior item que sobrou | Achar quem pede (strings da tabela, curva do dia, backfill da Falhas) e juntar ou espaçar |
| **Token da Axis** | Feito em 04/10: token vencido fora da rede. A Axis está sem dado desde julho | Gerar o token de API da Axis |

## Como conferir

```python
# extrato oficial por dia (UTC) — usa o token da plataforma, nunca impresso
import app, requests
H = app._sunop_data_headers("gridco")
d = requests.get(app.SUNOP_DATA + "/v2/usage/me", headers=H,
                 params={"start": "2026-09-20", "end": "2026-10-02"}, timeout=60).json()
for dia in d["daily"]:
    print(dia["usage_date"], dia["counters"]["request_count"])
```

E o `/api/sunop/uso` de cada máquina, comparando o `_total` e o `analog_values:trk` antes e depois de cada mudança.
