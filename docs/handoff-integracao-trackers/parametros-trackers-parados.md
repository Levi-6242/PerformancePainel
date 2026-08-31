# Régua de detecção de trackers parados — parâmetros e lógica

Handoff de integração. Este documento descreve **todos os parâmetros e a lógica** que a
Plataforma de Performance usa para classificar o estado de um tracker (parado / desvio /
atraso / sem comunicação / normal). A régua é **igual para todas as fontes** — muda só a
forma de obter a curva (ver `fontes-autenticacao.md`).

Fonte da verdade: `plataforma/app.py`. Os valores abaixo são as constantes do código
(seção `TRK_*`, ~linhas 3742–6420). O JSON `parametros-trackers.json` traz os mesmos
valores em formato consumível por máquina.

---

## 1. Insumo: a curva do dia

- Para cada tracker, a fonte entrega uma **curva de ângulo** ao longo do dia:
  `POSAT` = ângulo **atual** (medido) por timestamp; `POSAL` = ângulo **alvo** (setpoint),
  quando a fonte fornece (nem toda usina tem POSAL).
- **Janela diurna solar: 06:00–18:00** (minuto-do-dia 360–1080). O reposicionamento
  noturno é descartado (inflava a amplitude de tracker travado).
- A classificação é **minuto-do-dia**; ao concatenar dias, isolar o ÚLTIMO dia antes de
  classificar (`_trk_daykey`).
- Amplitude usada é **robusta**: range p02–p98 (`_amp_robusta`), para matar spike isolado.

---

## 2. Classificação definitiva (freeze-based) — `_trk_classifica_curso`

Régua canônica (Levi 10/07). Aplicada por `_trk_status_from_curva(lst, g)` para
SunOp/Athon, Axis, Thopen/PG e 2C; e por `_pv_trk_refina_curva` para a API PV. Saída por
tracker: `parado | severo | medio | leve | normal`.

### PARADO (vermelho) — dois gatilhos
| Gatilho | Regra | Constante |
|---|---|---|
| Nunca rastreou | amplitude robusta do ângulo no dia **< 3,0°** | `TRK_PARADO_AMP2 = 3.0` |
| Sensor morto (comm) | **> 90%** das leituras da janela ≈ 0,00° (`\|v\| < 0,05`) | (limiar 0,9 / 0,05) |

> Existe também um limiar mais frouxo herdado do overview instantâneo,
> `TRK_PARADO_AMP = 15.0°`, usado na passada rápida (peer-based) antes da régua definitiva
> sobrescrever o status. A régua definitiva é a `TRK_PARADO_AMP2 = 3.0°`.

### FREEZE (congelou no meio do dia) → severo/leve
Trecho plano da curva enquanto a **frota se move**:
| Parâmetro | Valor | Significado |
|---|---|---|
| `TRK_FREEZE_STEP` | 1,5° | passo entre leituras 5-min abaixo disto = trecho **plano** |
| `TRK_FREEZE_MIN` | 15 min | trecho plano ≥ isto = freeze (piso) |
| `TRK_FREEZE_SEV` | 30 min | freeze ≥ isto = **severo** (15–30 min = leve) |
| `TRK_FLEET_MOVE` | 8,0° | a frota tem de ter se movido isto no trecho (senão é dwell, não freeze) |
| `TRK_FREEZE_DEV` | 8,0° | o freeze tem de ter **caído** isto da frota (senão é seção lenta/dwell) |
| `TRK_JUMP` | 8,0° | passo abrupto que **encerra** um trecho plano (salto de recuperação) |
| `TRK_EOD_TAIL_MIN` | 75 min | minutos finais da janela p/ testar "congelou e ficou" (parado por persistência) |

### Batente / fora do curso físico (não é freeze)
| Parâmetro | Valor | Significado |
|---|---|---|
| `TRK_BATENTE` | 53° | `\|ângulo\| >` isto = batente mecânico → dwell legítimo |
| `TRK_FORA_FISICO` | 56° | `\|ângulo\| >` isto = fora do curso físico (glitch/calibração) |
| `TRK_FORA_FRAC` | 0,15 | fração de pontos fora-do-físico que caracteriza "parado por garbage" |
| `TRK_CURSO_TOL` | 8,0° | margem p/ "bateu no extremo" (perto do limite alcançado pela frota) |
| `TRK_CURSO_LIM_FLOOR` | 45° | piso do limite: 'normal' bidirecional chega a ~±45° no mínimo |

---

## 3. Exoneração "em cima do alvo" — `_trk_exonera_onalvo`

Rebaixa **parado → normal** um tracker que travou de manhã mas **voltou ao alvo** (está
posicionado certo agora, não precisa reset). Vale para todas as fontes.

- Condição: `status == "parado"` **E** `não sem_comunicacao` **E**
  `disparidade ATUAL ≤ TRK_ONALVO_MAX (12,0°)`.
- **Cuidado documentado:** só dispara quando há `disparidade` (exige POSAL/alvo por tracker
  ou disparidade derivada). Em usina **sem POSAL** a `disparidade` sai `None` e a exoneração
  **não** age — de propósito, para não liberar tracker travado no batente leste (−55°) que
  de manhã coincide com o alvo. O sinal confiável nesse caso é a **amplitude** (§2), não a
  proximidade do alvo.

| Parâmetro | Valor | Significado |
|---|---|---|
| `TRK_ONALVO_MAX` | 12,0° | disparidade atual abaixo disto = "em cima do alvo" (posicionado certo) |

---

## 4. Sem comunicação — `_trk_semcom_set`

Marca **rótulo** (não muda status nem contagem): um parado que é, na verdade, falta de
comunicação. Dois casos:

| Caso | Regra | Constante |
|---|---|---|
| Sensor morto | > 90% das leituras ≈ 0,00° (`\|v\| < 0,05`) | (0,9 / 0,05) |
| Curva defasada | parou de reportar há **> 45 min** enquanto a **frota segue** (compara o último minuto do tracker com `frota_ult` = o mais recente da frota ≈ agora) | `TRK_STALE_MIN = 45.0` |

Efeito: a ronda mostra "(sem comunicação)" em vez de um ângulo defasado que não é o de agora.

---

## 5. Desvio / atraso (instantâneo, overview)

Relativo à **mediana da planta** (o alvo do supervisório é ruidoso; a mediana da frota é a
referência robusta).

| Estado | Regra | Constante |
|---|---|---|
| Desvio (laranja) | disparidade ATUAL − mediana da planta **>** limiar | `TRK_DESVIO_MIN = 5.0` |
| Atraso (amarelo) | disparidade MÁX do dia − mediana **>** limiar (saiu por pouco e voltou) | `TRK_ATRASO_DELTA = 10.0` |
| Alerta leve/severo (vs alvo) | disparidade alvo×atual | `TRK_DISP_LEVE = 5.0` / `TRK_DISP_SEVERO = 10.0` |
| Fora da média da usina | desvio do ângulo atual vs média | `TRK_FORA_MEDIA = 3.0` |

Específico da API PV (desvio vs mediana da frota, instantâneo e curva):
| Parâmetro | Valor |
|---|---|
| `TRK_PV_DESVIO_FROTA` | 10,0° (anômalo) |
| `TRK_PV_SEV_DEV` | 20,0° (severo; 10–20° = leve) |
| `TRK_DEV_SEVERO` | 10,0° (confirma frota saudável) |

---

## 6. Guardas de horário e de frota

Evitam falso-positivo de manhã cedo (dia jovem = todo mundo mexeu pouco) e permitem julgar
uma planta inteira parada.

| Parâmetro | Valor | Significado |
|---|---|---|
| `TRK_COBERTURA_MIN_H` | 4,0 h | span mínimo da curva p/ julgar "parado" de forma ABSOLUTA (independe dos vizinhos) |
| `TRK_FROTA_ACORDA_HORA` | 11 h | frota que **nunca** girou até esta hora = referência de que "não acordou" |
| `TRK_PARADA_GLOBAL_HORA` | 12 h | passada esta hora, planta que mal girou (mediana baixa) = TODOS parados |
| `TRK_ALVO_MOVE_MIN` | 30° | (régua relativa) referência de movimento dos vizinhos |
| `TRK_ACCUM_MIN_CONF` | 20 amostras | baldes ~5 min p/ CONFIAR num "todos parados" com frota parada (~100 min de dia) |
| `TRK_DIA_INI` / `TRK_DIA_FIM` | 9 / 15 h | janela do "desvio do dia" (acumulador) |

Função `_frota_acordou(amps, dia_coberto)` decide se a frota já se moveu o suficiente para o
gatilho de "parado por amplitude" valer.

Notificação de parada global (tela):
| Parâmetro | Valor |
|---|---|
| `TRK_PARADA_NOTIF_HORAS` | 2,0 h (todos parados por mais que isto → notifica) |
| `TRK_PARADA_NOTIF_HORA_INI` | 9 h (só a partir daqui, sem ruído de madrugada) |

---

## 7. Alvo exibido — `_trk_alvo_mediana`

- Alvo de todos os trackers = **mediana** do alvo da UFV (dos que estão girando), **capada**
  em ±`TRK_ALVO_MAX (55,0°)` — limite físico da TCU. O supervisório às vezes manda ~±60° no
  backtracking (irreal → capado).
- Se a usina inteira estiver parada / sem leitura → alvo = `None` (UI/ronda mostram "—").
- Só mexe no **alvo/disparidade exibidos**; NÃO altera os status (que já vêm da curva).

---

## 8. Disponibilidade e histórico de ocorrências (`TRK_EV_*`)

Motor de eventos (linha do tempo de travamentos; base do "disponibilidade por tempo" e do
histórico de recorrência).

| Parâmetro | Valor | Significado |
|---|---|---|
| `TRK_EV_DATA_INI` | "2026-06-01" | início do histórico |
| `TRK_EV_STEP` | 10 min | resolução da grade de detecção |
| `TRK_EV_WIN_INI` / `TRK_EV_WIN_FIM` | 06:00 / 18:00 | janela (início efetivo é dinâmico pelo despertar) |
| `TRK_EV_WAKE` | 5,0° | afastou isto do amanhecer = "acordou" (saiu do stow) |
| `TRK_EV_LOOKBACK` | 3 células (30 min) | janela deslizante p/ medir movimento |
| `TRK_EV_FLEET_RANGE` | 3,0° | frota mexeu isto na janela → dá p/ julgar "travado" |
| `TRK_EV_STUCK_RANGE` | 1,5° | tracker mexeu ≤ isto → travado |
| `TRK_EV_RESUME` | 3,0° | voltou a mexer isto do patamar travado → retorno |
| `TRK_EV_MIN_MIN` | 30 min | duração mínima do travamento p/ virar ocorrência |
| `TRK_EV_COBERTURA` | 0,5 | fração mínima de dados (senão = falha de comunicação no período) |
| `TRK_EV_DESVIO` | 12,0° | `\|ângulo − mediana da frota\| >` isto = fora do alvo (conta como indisponível no tempo) |
| `TRK_EV_STOW_ANG` | −55,0° | ângulo aproximado do **stow leste** |
| `TRK_EV_STOW_TOL` | 10,0° | tolerância (−65° a −45° conta como stow) |
| `TRK_EV_STOW_INI` / `TRK_EV_STOW_FIM_MAX` | 07:30 / 10:30 | janela onde o stow é esperado / limite p/ sair sem virar ocorrência |
| `_TRK_PARADO_MANHA` | 09:00 | parada até aqui = travou de manhã (não voltou do despertar) |
| `_TRK_PARADO_ANOITE` | 16:30 | retorno ≥ isto (ou nunca) = não voltou de verdade, só anoiteceu |

---

## 9. Flags e outros

| Parâmetro | Valor | Significado |
|---|---|---|
| `TRK_REGUA_V2` | env `TRK_REGUA_V2=1` | liga a régua v2 (`_regua_v2`) na classificação de perdas |
| `TRK_CHART_MAX_DIAS` | 5 | janela máxima do gráfico De/Até |

---

## 10. Funções-chave (para replicar)

| Função | Papel |
|---|---|
| `_trk_classifica_curso(g, usina)` | classificador freeze-based definitivo (status por tracker) |
| `_trk_status_from_curva(lst, g)` | aplica classificação + `_trk_semcom_set` + `_trk_exonera_onalvo` (SunOp/PG/2C) |
| `_pv_trk_refina_curva(...)` | mesma régua para a API PV |
| `_trk_semcom_set(g)` | conjunto dos trackers "sem comunicação" (sensor morto / curva defasada) |
| `_trk_exonera_onalvo(lst)` | rebaixa parado→normal em cima do alvo |
| `_trk_alvo_mediana(base)` | alvo/disparidade exibidos = mediana capada da frota |
| `_amp_robusta(vals)` | amplitude robusta p02–p98 |
| `_frota_acordou(amps, dia_coberto)` | guarda de despertar da frota |
| `_sunop_trackers_plant_curva(planta, inst)` | monta curva + classifica uma usina SunOp/Athon/Axis |
| `_sunop_parados_rows(inst)` | linhas de parados de uma instância (alimenta a ronda) |

> Semântica de saída por tracker: `status ∈ {parado, severo, medio, leve, normal}`,
> `sem_comunicacao: bool`, `atual` (ângulo °), `alvo` (° ou None), `disparidade` (° ou None),
> `amplitude` (°). Um tracker "parado + sem_comunicacao=false" é travado mecânico; "parado +
> sem_comunicacao=true" é falta de comunicação.
