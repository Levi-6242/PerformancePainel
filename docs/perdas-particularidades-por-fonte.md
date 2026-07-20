# Base de Perdas — particularidades por fonte

Referência viva pra não ficar re-descobrindo como cada fonte se comporta na base de perdas
(trackers/strings, ocorrências/paradas, horas solares → energia). Atualizar quando mudar.

## Matriz rápida

| Capacidade | API PV (Thopen) | PG (Thopen BD) | 2C (Owen) | SunOp (Athon) | Axis | SolarEdge (RenoGrid) |
|---|---|---|---|---|---|---|
| Curva de tracker (ângulo) | Sim (trackerschart, ~90s) | Sim (backend) | Sim (5min) | Sim | Sim | Não |
| Status severo/leve do tracker | Sim (classificador) | Sim | Sim | Sim | Sim | — |
| Curva de string intradiária | Hoje: **corrente**; passado: **potência** | **Não (snapshot 1×/dia)** | Sim (5min) | Sim (I_PV) | Sim | Não |
| Ocorrência string caiu→voltou | Sim (hoje corrente / passado potência) | **Não (snapshot)** | Sim | Sim | Sim | Não |
| "Desde quando" multi-dia | Sim (store desde 01/07) | Parcial (só foto) | Sim | Sim | Sim | Não |
| Irradiância/POA confiável | Parcial (day_meteo) | **Furado (IPOA)** | Ignorada | Lento (custom_query) | Lento | render-chart |
| Fuso | Local | Local | Local | **UTC** (forçar plant tz) | **UTC** | — |

## Detalhe por fonte

### API PV (Thopen) — piloto
- **Trackers**: ângulo via `trackerschart` (pesado ~90s, cacheado). `±55°` (ou o limite de curso) **é parada aceitável** quando o ALVO é ±55° (backtracking no sol baixo / fim de curso) — só conta como perda o `|ângulo − alvo|` fora do limiar. Multi-dia via `trk_eventos.json`.
- **Strings**: HOJE = **corrente (A)** via `day_inverter`/Ipv; DIA PASSADO = **potência (W)** via `trygenerate` (unidade e limiares diferentes — `_str_eventos_calc` recebe `zero_thr`/`inv_min` próprios). A **curva** de string (drill) só do dia atual; as **ocorrências** caiu→voltou funcionam em dia passado (via potência). Store de eventos começa **01/07**. **Sem Riso** ao vivo.
- **Skids**: uma usina pode ser vários `plant_id` (Fernandópolis 1/2/3 = 338980/984/983; Indaiatuba 1–4). Trancada é por `plant_id` → usar match **tolerante por inv_id** (`_str_trancada`, idefinversor é único global).
- **Meteo**: `day_meteo` tem POA/GHI/chuva/umidade/vento/temp; POA histórico via `custom_query` (lento sob carga, rodar fora de pico).

### PG (Thopen — banco de dados)
- **String é SNAPSHOT** (`stg_inverter_string_data`, 1 leitura/dia): **não** dá ocorrência caiu→voltou nem "desde"; só "zerada" da foto. (Régua reaplicada na leitura — não precisa filtrar trancada em cache.)
- **Trackers**: telemetria analógica por inversor (Riso/temp/estado); curvas ok no backend.
- **IPOA/irradiância furado** → PR/decomposição de clima **bloqueada** por aqui.
- É a fonte da **base de geração** (ver abaixo).

### 2C (Owen)
- **Banco-por-dia** (`2C_historico/AAAA-MM-DD`), curvas 5min. E-mails Owen chegam em **janelas ~3h** → latência/granularidade grossa. "Geração e Irradiação" **ignorada**. Token Gmail vence **~7 dias** (pode parar a coleta). Strings alinhadas à régua do SunOp.

### SunOp (Athon) e Axis
- `last_values` em **UTC** → passar `use_plant_timezone=true`. Token **auto-renova**. `custom_query` meteo **lento** fora de pico. Strings = curva `I_PV` por inversor (**trancadas já filtradas** na origem). Axis = 2ª instância (`axis.sunop.net`), mesma API, 2 usinas (PE III, Ponto Belo).

### SolarEdge (RenoGrid)
- **Throttling** (não martelar o `.exe`); telemetria que **não fechou** dá valor uniforme baixo (falso — não confundir com perda). Irradiância via `render-chart`. RenoGrid dá só **PR por inversor**. **Sem** ETM/Trackers/curva de string na v2 → fora da base de perdas por enquanto.

## Fonte de reconciliação (fechar a conta — passo 2)
Não usar medidor de fronteira. Existe **base de geração para todas as UFVs** (BD_Performance / BD_Thopen `Historico_2026`): energia diária por inversor + `gerada ÷ P50`. É contra ela que a soma das fatias da cascata tem que fechar.

## Regras transversais da base de perdas
- **Horas solares 06–18h = 12h/dia**, linear no tempo (ainda **não** ponderado por irradiância — isso é o passo tempo→energia).
- Base retroativa **01/07** (antes → clampa 01/07 06:00). Mínimo 30min. Trancadas fora.
- **Ocorrência** = caiu e voltou; **parada** = caiu e não voltou (aberta).
- **Severo/leve de tracker = status REAL da plataforma** (não banda de duração): pegar os trackers com status de desvio no(s) dia(s) e extrair os episódios que os classificaram.
- **D-1**: parados e ocorrências da base de perdas em dia FECHADO (D-1 pra trás); só os gráficos de monitoramento ficam ao vivo.
- **Gap de coleta**: se um dia do meio ficou sem dados e depois normalizou, fechar o evento às **18:00 do último dia com dado**.
- **Sem dupla contagem**: tracker que está em "parados" (aberto) num período não aparece também em "ocorrências" no mesmo período.
- **Strings baixa performance** (abaixo dos pares, não zeradas): **fora** da conta por ora (complexidade alta).
