# Testes — Fase 1 (funções puras de `app.py`)

Testes direcionados à **lógica de negócio** do dashboard. As APIs ao vivo (API PV,
SunOp, Plataforma, PostgreSQL) são mockadas ou evitadas — aqui só entram funções
puras e regras determinísticas.

## Como rodar

```bat
pip install -r requirements-dev.txt
run_tests.bat            REM ou: python -m pytest
run_tests.bat -v         REM verboso, lista cada teste
```

## O que está coberto

| Arquivo | Funções | Foco |
|---|---|---|
| `test_strings.py` | `_classifica_strings`, `_str_ativas`, `_ipv_ativas`, `_str_key`, `_na_janela_sol` | Régua de strings (trancada/sem_corrente/baixa_perf/ativa/inativa) |
| `test_severidade.py` | `severidade` | Ordenação das usinas (0=pior … 5=normal) e prioridade entre condições |
| `test_diagnostico_etm.py` | `_diagnostico_etm` | Flags da curva de irradiância (sem comunicação, POA zerado, GHI>POA, dropouts) |
| `test_trackers.py` | `_trk_accum_feed`, `_trk_accum_desvio`, `_trk_accum_parados` | Acumulador diário de trackers; detecção de tracker travado |
| `test_pr_ipoa.py` | `_ipoa_from_meteo`, `_pv_pr_compute` | Integração trapezoidal do IPOA; PR = geração ÷ (IPOA × potência) |
| `test_misc.py` | `_spv_stnum`, `_pv_trk_num`, `_nrm`, `_num`, `_pot_inv` | Utilitários de extração/normalização e potência por inversor |

## Decisões de teste (gotchas)

- **Relógio congelado** — funções que leem `datetime.now()` (curva ETM, janela de
  sol, acumulador de trackers) usam o fixture `freeze_now`, que troca `app.datetime`
  por uma subclasse com `now()` fixo (strptime/strftime continuam reais).
- **Globais isolados** — `app._trancadas` e `app._trk_accum` são mutáveis a nível de
  módulo; os fixtures `set_trancadas` / `trk_accum` usam `monkeypatch` e revertem ao
  fim de cada teste, então a ordem não importa.
- **Fonte paga é recusada (10/10/2026)** — o `conftest.py` da raiz recusa com `ConnectionError` todo pedido
  `requests`/`urllib` a host com `sunop.net` ou `pvoperation.com` (API PV, PV Plataforma, SunOp) e **quebra o teste
  que tentou**, listando método e URL (sem a query); o fim da rodada imprime `fonte paga (SunOp/PV Operation): N
  chamada(s)` — tem de ser 0. Motivo: em 10/10 cada rodada fazia 9 chamadas reais (a SunOp estourou a cota em
  setembro, a API PV é paga) e os testes passavam, porque o código engole a falha de rede. Teste novo que passa por
  essas fontes **dubla a função** (`_pv_dev_names`, `get_token`, `_sunop_trk_curvas`…), nunca a trava. Exceção:
  `@pytest.mark.rede_cortada_pelo_teste`, para quem conta tentativas cortando o `socket.getaddrinfo`
  (`test_nexus_sem_api_pv.py`, `test_porta_nexus_gestor_sem_api_pv.py`) — só vale enquanto a resolução estiver
  trocada. A trava se prova em
  `test_trava_fontes_pagas.py`.
- **`import app` não é limpo** — no topo do módulo ele roda
  `load_equipamentos()` / `load_metas()` / `load_tickets_trackers()`, que leem
  `BD_Performance.xlsx`. **Local funciona** (o xlsx está na raiz). Para rodar em
  **CI no GitHub Actions** será preciso esconder essas cargas atrás de função (lazy)
  ou commitar um xlsx-fixture pequeno. Decidir na Fase 2.

## Regressão contra casos REAIS rotulados (Confiabilidade da Plataforma)

Além dos testes de função pura acima, há uma **rede de regressão** que roda a detecção sobre
**dados reais capturados** e compara com a **verdade de campo** narrada pelo especialista. É o que
impede o "conserta um, quebra outro". Ver `docs/deteccao-trackers.md`.

- **Fixtures:** `tests/fixtures/<equip>/` — pares `<caso>.raw.json` (a foto do dado cru da fonte,
  reamostrada a 5 min) + `<caso>.gab.json` (o gabarito: `agregado_esperado` + `esperado` por peça).
- **Captura:** `python tests/capturar_caso.py trackers apipv <idusina> <dd/mm/aaaa> <slug>`.
- **Runner:** `tests/test_regressao_trackers.py` — parametrizado, descobre todo par sozinho.
  **Adicionar um caso = soltar 2 JSON**, sem código novo. Roda a lógica de PRODUÇÃO
  (`_pv_trk_refina_curva`) via priming do cache da curva (sem rede).
- **1º caso ancorado:** Primavera 1 · 06–09/07/2026 · *dia perfeito* (o "dia bom" que pega falso positivo).

## Próximas fases (ver memória `testes-automatizados-plano`)

- **Fase 2** — contrato dos endpoints com `app.app.test_client()` + `monkeypatch` em
  `app._http()` e `app._pg_conn()` (sem rede), garantindo o shape do JSON.
- **Fase 3** — smoke Playwright atrás da `DASH_PASSWORD` (só se o frontend continuar
  quebrando).
