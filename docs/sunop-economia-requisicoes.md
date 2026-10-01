# Economia de requisições na API da SunOp

Como a plataforma passou a caber (ou tenta caber) na cota da SunOp, o que foi cortado, por quê e o que foi medido
antes e depois. Atualizado em 01/10/2026.

## A cota

- **100.000 requisições por mês** na conta da Athon (plano `settings-default`). Acima disso, **US$ 0,0005 por
  requisição**.
- Para caber, o teto é de **~3.300 por dia** (~140 por hora), somando o servidor e o PC do Levi.
- A Axis é outra conta da SunOp e não gasta esta cota.

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

**Esperado depois do deploy:** a curva de tracker volta ao que o ciclo pede. São ~4 POSTs por volta: no servidor a
cada 10 min (~600 por dia); no PC uma vez por hora (~100 por dia). Cada reinício soma uma carga única de ~370
(92 dias × ~4) até o cache das Ocorrências encher. **Medir no extrato de 02/10 (UTC) e no `/api/sunop/uso` das
duas máquinas.**

### Achado no caminho: um teste gravava no acervo do PC

O `test_os_tres_chamadores_pre_carregam_as_usinas_juntas` (do ee70830) chama o `_sunop_eventos_calc` de verdade, e
essa função salva o acervo.
- Às 09:51 de 01/10, o `trk_eventos.json` do PC (11,7 MB, 93 dias) virou **388 bytes**. O worker regravou o
  arquivo da memória 4 min depois; um reinício nessa janela teria apagado o histórico de trackers do PC.
- Num reinício de 30/09, o worker já tinha carregado as usinas falsas do teste (AAA100 e BBB100, um dia cada).

Desde 01/10 o `conftest.py` isola todos os arquivos de estado que a plataforma grava (`ARQUIVOS_DE_ESTADO`) e
desliga o despejo do contador da SunOp nos testes. `tests/test_isolamento_estado.py` confere a lista contra o
`app.py`.

## O que ainda gasta e os próximos cortes

| Onde | Situação | Corte possível |
|---|---|---|
| **Ronda do WhatsApp com o serviço fora** | Em 01/10, a ronda das 08:25 ficou "aguardando QR". O laço tentou de novo 24 vezes em 2 h, e cada tentativa refaz a ronda com `force` (rebaixa as curvas: ~4 POSTs por vez) | Na retentativa, aproveitar a ronda já calculada, em vez de `force` |
| **Reinícios e deploys** | Cada reinício busca a curva cheia do dia e recarrega as Ocorrências do mês até o cache encher | Guardar o cache das Ocorrências (dias fechados) no snapshot |
| **Gêmeo do servidor vazio** | No servidor a curva nunca vem do acervo do gêmeo (FASE 4): tudo vai à SunOp | Pôr o gêmeo do servidor para ingerir (o do PC foi desligado em 30/09 para o corte) |
| **Strings no servidor** | ~1.500 por dia (`last_values:str` + `analog_values:str`) em 30/09 | Medir depois do corte de 01/10 antes de mexer |

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
