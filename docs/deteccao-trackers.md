# Detecção de trackers — spec (rascunho)

> Fonte única das **regras** de classificação de trackers. Os casos rotulados em
> `tests/fixtures/trackers/` são a **verdade de campo** que a detecção tem que reproduzir
> (projeto *Confiabilidade da Plataforma*). Rascunho — a fechar no kickoff.

## Esquema NOVO — por CURSO (Levi 09/07)

Trocamos o critério antigo ("desvio da mediana da frota", frágil) por **quanto do curso ±limite o
tracker cumpriu no dia**. É físico e auto-calibrável.

| Estado | Cor | Regra |
|---|---|---|
| **parado** | 🔴 | Amplitude do dia `< TRK_PARADO_AMP` (15°) — não se moveu (inclui travado num ângulo fixo ≠ 0°). |
| **desvio_severo** | 🟠 | Mexeu, mas **não bateu em nenhum extremo** — curso mecânico limitado, longe do ±limite. |
| **desvio_leve** | 🟡 | Bateu em **UM** extremo (±limite de um lado só). Curso quase completo. |
| **normal** | 🟢 | Bateu nos **DOIS** extremos (curso completo). |

**O ±limite é DERIVADO DA FROTA:** o maior ângulo positivo e o menor negativo que os *melhores*
trackers da usina alcançaram no dia (com piso `TRK_CURSO_LIM_FLOOR` = 45° e margem `TRK_CURSO_TOL` = 8°).
Assim auto-calibra por usina, sem cadastrar o ângulo de projeto. **Limitação conhecida:** se a usina
INTEIRA estiver degradada (nenhum tracker alcança o limite real), o limite derivado fica baixo e pode
mascarar — caso a resolver com o ângulo de projeto por estrutura, se/quando houver a fonte.

Implementação: **`_trk_classifica_curso(g)`** em app.py — função pura sobre a curva do trackerschart.
(**Ainda NÃO ligada em produção**; validada nos fixtures.)

## Camada 2 — flags técnicos (separados da classificação)

Alguns sinais **não mudam** a classe (parado/severo/leve/normal), mas viram **alerta técnico à parte**
(alimentam a aba de Ocorrências / equipe de telemetria):

- **Possível falha de comunicação** — 1 a 3 leituras isoladas com desvio abrupto (>15° da frota ou do
  próprio padrão) que **retornam ao normal no registro seguinte**, sem persistência. Ruído / RSSI fraco /
  interferência no rádio ou cabo — o tracker físico pode estar saudável. Ex. (Céu Azul 1): TRK9 leitura
  isolada de 54,6° às 08:37 (frota em −38,6°); TRK3 (parado) com picos de 1 leitura a ±55°.
- **Ocorrências de travamento** — episódios em que o tracker congela (≥20 min, ou soma de congelamentos),
  caindo atrás da referência e recuperando. Um tracker pode ter ocorrências e ainda ser *leve*/*normal*.

> Importante: esses picos de 1 leitura são **filtrados** da classificação (amplitude robusta p02–p98),
> senão fingem curso cheio num tracker parado (foi o erro que o caso Céu Azul 1 pegou).

## Janela e referências

- **Janela diurna:** 07:00–18:00 (pontos fora ignorados).
- **Amplitude** por tracker = max − min do ângulo na janela.
- **Extremos da frota** = max(+) e min(−) entre todos os trackers da usina no dia.

## Em aberto — a decidir

- **Ligar em produção:** hoje `_pv_trk_refina_curva` (overview/drill/ronda) usa o esquema ANTIGO
  (parado/desvio/normal por mediana). Trocar por `_trk_classifica_curso` → mexe em contadores, cores do
  front (4 estados) e na ronda.
- **Ronda:** manda só `parado`, ou também `desvio_severo`?
- **Outras fontes** (SunOp/Athon, PG, 2C): estendem o esquema por curso? (têm curva de ângulo.)
- **±limite:** derivado-da-frota (atual) vs cadastro de projeto por usina/estrutura.

## Como um caso vira teste

1. **Foto:** `python tests/capturar_caso.py trackers apipv <idusina> <dd/mm/aaaa> <slug>`.
2. **Gabarito:** `apipv__<slug>__<aaaa-mm-dd>.gab.json` — `esperado` por tracker + `agregado_esperado`.
3. **Roda:** `pytest tests/test_regressao_trackers.py` (pega o par sozinho; usa `_trk_classifica_curso`).

## Casos ancorados

- **Primavera 1 · 06–09/07/2026 · dia perfeito** (idusina `18746926`): 22 trackers, todos **normais**
  (curso completo) nos 4 dias. O *"dia bom"* que pega falso positivo.
- **Altair 5 · 09/07/2026 · problemático** (idusina `22862`): 11 **parados** (10 em 0.00° + TRK90
  travado em −30°), 9 **desvio_severo** (não chegaram a nenhum extremo), 4 **desvio_leve** (chegaram a
  um ±55°), 0 normal. Reproduz 100% os rótulos do Levi.
