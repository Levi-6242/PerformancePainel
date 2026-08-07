# API de campo — ronda de trackers por usina

> **Status: CONSTRUÍDO e LIGADO (05/08) na instância de produção.** `CAMPO_API_KEY` configurada,
> web reiniciado, endpoint verificado (`200` ao vivo com ronda real). O comportamento fail-closed
> continua valendo (sem a chave → `401`); a seção **"Como ligar"** fica como referência.

## Objetivo
O técnico escolhe a usina no app de campo → **1 chamada** → a ronda de trackers daquela usina
(os **parados** / sem comunicação). Automático, sem o técnico saber de qual fonte (SunOp/API PV/PG/2C)
a usina vem. A régua e os **tokens das fontes ficam na plataforma**; o app de campo autentica só
com uma `x-api-key`.

## Endpoints
```
GET /api/campo/ronda?usina=<nome>      Header: x-api-key: <chave>
GET /api/campo/usinas                  Header: x-api-key: <chave>   (lista os nomes válidos)
```
- **`usina`** aceita vários formatos do mesmo nome: o do **catálogo Fracttal**
  (`Thopen - Ibaté 1 - SP`), o **display** (`Mandaguaçu 4 (143)`) ou o **nome da fonte**
  (`TIM100`, `(306) Ibaté 1`). O resolvedor casa sozinho. Use `/api/campo/usinas` para popular o
  seletor do app com os nomes que resolvem.
- **Sub-usinas (grupos):** um nome de catálogo que cobre VÁRIAS sub-usinas no supervisório
  (ex.: `Thopen - Ceilândia 2 - DF` = 4 sub-usinas; Altair 1-5; `Santarém 1 e 2`) **não resolve**
  — devolve `400` com o array `subusinas` listando os nomes. É de propósito: devolver a 1ª
  sub-usina silenciosamente seria uma resposta parcial com cara de completa. Consulte **cada
  sub-usina pelo próprio nome** e some no seu lado. A resposta de `/api/campo/usinas` traz o
  campo `grupos` (`[{nome, subusinas}]`) pronto para esse mapeamento — hoje são 19 grupos.
- **`x-api-key`** = chave única do app de campo (NÃO é token de fonte).
- Filtros: **padrão = parados + sem comunicação** (o que o técnico age). `?desvios=1` inclui também
  os que estão **fora do alvo agora** (desvio/atraso). `?tudo=1` devolve todos os trackers.

## Resposta `200`
```json
{
  "usina": "TIM100",
  "fonte": "Athon",
  "atualizado": "2026-08-05T09:14:00",
  "total_trackers": 150,
  "ronda": [
    {"tracker": 5,  "status": "parado",          "atual": 0.69, "alvo": -29.11, "disparidade": 29.8,  "sem_comunicacao": false, "desde": null},
    {"tracker": 3,  "status": "sem_comunicacao",  "atual": 0.0,  "alvo": -29.11, "disparidade": 29.11, "sem_comunicacao": true,  "desde": null}
  ]
}
```
| Campo | Significado |
|---|---|
| `tracker` | número do tracker **no supervisório** (sem Fracttal por enquanto) |
| `status` | `parado` \| `sem_comunicacao` \| `desvio` \| `atraso` \| `normal` (os 2 últimos só com `?desvios=1`/`?tudo=1`) |
| `atual` | ângulo medido (°) — `null`/`0.0` quando sem comunicação |
| `alvo` | ângulo alvo (°) — `null` se a usina não tem alvo |
| `disparidade` | \|atual − alvo\| (°) |
| `sem_comunicacao` | `true` = curva morta/defasada |
| `desde` | início do parado (ISO) quando disponível; senão `null` |

- **Sem Fracttal por enquanto:** `tracker` é o número do supervisório. Quando a relação
  tracker↔ativo Fracttal fechar, entra um campo novo (ex.: `ativo_fracttal`) **sem quebrar o contrato**.

## Erros
| Código | Significado |
|---|---|
| `401` | `x-api-key` ausente/errada — **ou o endpoint ainda não foi ligado** (`CAMPO_API_KEY` vazia) |
| `400` | nome não bate → `sugestoes` (nomes próximos); **ou** nome de grupo → `subusinas` (consulte cada uma) |
| `502` | falha ao buscar na fonte (token vencido/fonte fora) |
| `200` | ronda entregue |

## Segurança
Os tokens das fontes (SunOp / API PV / PG / 2C) **não vão para o app de campo** — ficam na
plataforma. O app usa só a `x-api-key`. Token de fonte vencendo/rotacionando é problema nosso,
transparente para o campo. A chave é comparada em tempo constante (`hmac.compare_digest`).

## Régua
Classificação idêntica à da plataforma (parado / sem comunicação / desvio / atraso / on-alvo) —
ver `parametros-trackers-parados.md` / `parametros-trackers.json`.

## Como ligar
1. Gere uma **chave forte** (você/T.I. — ex.: 32+ chars aleatórios).
2. Ponha no `tokens.txt` da raiz: `CAMPO_API_KEY=<a chave>` (é carregado no ambiente no boot).
3. Reinicie o **web** da plataforma (o worker/ronda não precisa).
4. O app de campo chama com o header `x-api-key: <a chave>`.

Enquanto o passo 2 não for feito, o endpoint fica **fail-closed** (401) — seguro por padrão.
