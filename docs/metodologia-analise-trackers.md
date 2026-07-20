# Metodologia de análise de trackers (a régua definitiva)

Spec da classificação de trackers, gerada pelo Sonnet 5 a partir do caso **MAB200 16/07/2026** (150 trackers)
e adotada pelo Levi como a régua a implementar. Objetivo: classificação **auditável e reprodutível** →
vira teste de regressão contra as fixtures (`tests/fixtures/trackers/*.raw.json` + `.gab.json`).

## Categorias (por tracker, por dia)
- **Parado** — (a) *comunicação morta*: ângulo = 0,00° nas 24h (madrugada inclusa), flat 100% → offline;
  (b) *travado desde antes da meia-noite*: variação total do dia < 2° (travado num ângulo real = falha mecânica).
- **Desvio Severo** — tem ocorrência real ≥ 30 min.
- **Desvio Leve** — tem ocorrência real de 15 a 29 min.
- **Normal** — completou o ciclo dentro do esperado (inclui os batentes legítimos compartilhados).

## Regras (tradução direta pra código)

**3.1 Normalização** — dados vêm em formato longo (tracker/hora/ângulo) ou largo (1 coluna/tracker); normalizar
pra longo, nº do tracker via regex. (Na plataforma já vem `grafico = {tracker:[{x,y}]}`.)

**3.2 Janela de geração** — status e ocorrências restritos a **06:00–18:00**. Fora disso (madrugada) só serve
pra checar se já estava travado antes da meia-noite (caso crônico), nunca pra classificar o dia.

**3.3 Casos triviais (usando o DIA INTEIRO, sem filtro de horário)** — antes de qualquer série temporal:
- min == max == 0,00° → **Parado** (comunicação morta).
- variação total (máx − mín) < 2° → **Parado** (travado desde antes da meia-noite).

**3.4 Congelamento por tolerância (banda 2,0°)** — igualdade exata falha (ruído ±0,1–0,5°); agrupa leituras
consecutivas dentro da banda:
```
i = 0
enquanto i < n:
  j = i
  enquanto |valor[j+1] - valor[i]| <= tolerancia:  j += 1
  duracao = tempo[j] - tempo[i]
  se duracao >= 30 min:  registrar janela (inicio=tempo[i], fim=tempo[j], valor=valor[i])
  i = j + 1
```

**3.5 Congelamento real × batente compartilhado legítimo (O PASSO MAIS IMPORTANTE)** — trackers de eixo único
param legitimamente em ≥3 momentos (stow ao amanhecer, batente matinal ~−50 a −55°, batente da tarde ~+50 a
+55°). Horários **variam por latitude/estação/pitch → achar EMPIRICAMENTE do próprio dado, nunca fixo**. Valida
cada janela candidata contra o **movimento da mediana da frota** no mesmo intervalo:
```
para cada janela candidata (tracker travado de T1 a T2):
  se |mediana_frota(T2) - mediana_frota(T1)| <= tolerancia:  -> batente compartilhado legítimo (DESCARTA)
  senao:                                                     -> ocorrência real (a frota se moveu, o tracker não)
```
Sem isso → dezenas de falsos-positivos/dia (foi o erro mais recorrente no desenvolvimento).

**3.6 Fechamento da ocorrência** — travou e não recuperou até 18:00 → fecha às **18:00** com nota
`[NÃO RETOMOU ATÉ 18:00]`. **Exceção:** se o próprio arquivo termina antes das 18:00 (dado parcial) → fica
**em aberto por dado insuficiente** (fechar seria presumir resultado não observado).

**3.7 Classificação final**
```
se travado (3.3) o dia todo        -> PARADO
senão se ocorrência real >= 30 min -> DESVIO SEVERO
senão se ocorrência real 15–29 min -> DESVIO LEVE
senão                              -> NORMAL
```

**3.8 Agrupamento por causa raiz** — depois de listar as ocorrências individuais, agrupa por **horário de início
+ valor de congelamento**. Muitos trackers travando no mesmo minuto e mesmo ângulo = **1 causa compartilhada**
(zona/string/controlador), não N falhas independentes. É o que transforma a lista em ação (priorizar por causa).
Ex. MAB200 16/07: Cluster D = 28 trackers travaram 14:34–14:48 @ 34,8–38,4° → destravaram 17:58–17:59 (janela de
1 min entre si). Cluster E = 7 trackers (TRK_54–60) travaram 16:48 @ ~33°, recorrente (também no dia anterior).

## Uso na plataforma (plano)
1. `_trk_analise_dia(grafico)` traduz 3.3→3.8 → por tracker `{classe, ocorrencias[], travado_em, causa_grupo}`.
2. Validar contra as fixtures (`sunop__mab200__*`, etc.) — o `.gab.json` é o gabarito.
3. Fundir sub-abas **Ocorrências + Parados** numa só, coluna **FONTE = Parado / Severo / Desvio**.
4. **Histórico persistido por dia** (padrão "persiste+lê").
5. Piloto na fonte do caso; replicar. Quando validado, vira a fonte do overview (mata o "todos parados" falso).
