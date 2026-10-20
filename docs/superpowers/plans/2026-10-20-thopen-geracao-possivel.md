# Geração possível pelo IPOA (Visão Geral e linha do Diário) — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a Visão Geral e a linha preta do Diário do Dashboard Thopen com a regra de geração possível do Levi, de 10/2026 em diante.

**Architecture:** um módulo puro novo (`thopen/geracao_possivel.py`, sem rede e sem Flask) faz toda a conta; o
`dashboard_thopen.py` lê o GHI num leitor próprio, chama o módulo no `_resumo_usina`, no `/api/t/geral` (linha Total) e
no `/api/t/diario` (linha do dia), sempre só de 10/2026 em diante; o HTML só desenha.

**Tech Stack:** Python 3 (Flask), Plotly no navegador, pytest (`--noconftest` com `PYTHONPATH=thopen`).

**Spec:** `docs/superpowers/specs/2026-10-20-thopen-geracao-possivel-design.md`

## Global Constraints

- Só de 10/2026 em diante: `operacao_mes.DESDE` (`_so_os_fracttal(ano, mes)`); antes, as rotas e a tela respondem
  exatamente como antes de 20/10/2026 (a Visão Geral de 10 colunas, o Diário com a linha da irradiação em kWh/m²).
- IPOA_MIN = 0,3 kWh/m²; GHI_MIN = 1,0 kWh/m²; IPOA_MAX = 12 kWh/m²; GHI_MAX = 10 kWh/m²; COBERTURA_MIN = 0,5.
- Nada no import (a plataforma importa o `dashboard_thopen`); `_daily_records` não muda de formato.
- pt-BR, sem emoji; comentário diz o porquê com o caso real.
- A conta kWp × IPOA × PR (`_base_esperada`, `_esperada_ipoa`, `pontos[].esperada`, `esperada_base`) sai inteira.

## Review Focus

1. Mês corrente com as linhas pré-criadas (0 kWh, sem IPOA) depois do último dia coletado: não entram e não viram furo.
2. Usina sem GHI na fonte (Polaris, Copel, Matrix): só a ETM conta; sem ela, "sem ETM", nunca erro.
3. Leitura de operação carregando (`fonte_operacao.dados()` vazio): sem expurgo ("—"), o resto da linha sai.
4. Usina sem meta de IPOA no mês (`metairr` nulo ou 0): sem possível, com o motivo; não divide por zero.
5. Setembro: `/api/t/geral` e `/api/t/diario` com a mesma resposta de antes.

---

### Task 1: o módulo puro da regra

**Files:**
- Create: `thopen/geracao_possivel.py`
- Test: `tests/test_thopen_geracao_possivel.py`

**Interfaces:**
- Produces:
  - `ipoa_do_dia(ipoa: float|None, ghi: float|None) -> tuple[float|None, str|None]` — `(valor, "ETM"|"GHI"|None)`.
  - `periodo(registros: list[dict], ghi: dict[date, float], meta_mes: float|None, meta_ipoa_mes: float|None,
    dias_mes: int, disp: dict[int, float]|None) -> dict` — `registros` = `{data: date, ger, ipoa}` do mês até o corte;
    `disp` = `{dia_do_mês: %}` (o `operacao_mes.disp_por_dia`) ou None. Devolve as chaves `dias, furos (list[date]),
    meta, meta_ipoa, real, dias_medidos, cobertura, ipoa_ajustado, dif_ipoa, possivel, disp_efetiva (0–1),
    possivel_exp, dif_possivel, dif_possivel_exp, sem_etm (bool), motivo (None|"sem_meta_ipoa"|"cobertura")`.
  - `possivel_do_dia(meta_mes, meta_ipoa_mes, ipoa_medido) -> float|None` = meta_mes × ipoa_medido ÷ meta_ipoa_mes.
  - `portfolio(linhas: list[dict]) -> dict` — cada linha tem `pot_kwp, meta, produzida` e as chaves do `periodo`;
    devolve `meta, produzida, dif_prod, ipoa_ajustado, meta_ipoa, dif_ipoa, possivel, real_etm, dif_possivel,
    possivel_exp, real_exp, dif_possivel_exp`.

- [ ] **Step 1: testes com os números à mão** (mês de 30 dias, meta_mes 30.000 kWh, meta_ipoa_mes 150 kWh/m²):
  registros d1 (ger 900, ipoa 6,0), d2 (800, ipoa 0,1, GHI 5,5), d3 (ger None), d4 (0, sem IPOA nem GHI),
  d5 (700, ipoa None, GHI 0,5), d6 (0, sem IPOA, depois do último coletado); disp {1: 100, 2: 80, 5: 90}.
  - `test_dia_que_entra_e_furo`: dias == 3 (d1, d2, d5); furos == [d3, d4]; d6 não é furo.
  - `test_meta_e_ipoa_do_periodo`: meta == 3000; meta_ipoa == 15; dias_medidos == 2; cobertura == 2/3;
    ipoa_ajustado == approx(17,25); dif_ipoa == approx(0,15); possivel == approx(3450); real == 2400;
    dif_possivel == approx(-0,304348, abs=1e-6).
  - `test_expurgo_ponderado_pelo_ipoa`: disp_efetiva == approx(1490/16,5/100); possivel_exp == approx(3450 × 0,903030);
    dif_possivel_exp == approx(-0,229636, abs=1e-6) e igual a (1 + (2400/disp_efetiva)/3000 − 1)/(1 + 0,15) − 1.
  - `test_ipoa_etm_ghi_e_teto`: ipoa_do_dia(6,0, 9) == (6,0, "ETM"); (0,2, 5,5) == (5,5, "GHI"); (0,2, 0,9) == (None,
    None); (12,5, 7,0) == (7,0, "GHI"); (None, 25,7) == (None, None); (11,6, None) == (11,6, "ETM").
  - `test_cobertura_minima`: 2 dias com 1 medido → sem_etm False; 3 dias com 1 medido → sem_etm True, motivo
    "cobertura", possivel None, dif_ipoa None.
  - `test_sem_meta_de_ipoa`: meta_ipoa_mes None → sem_etm True, motivo "sem_meta_ipoa", possivel None.
  - `test_sem_disp`: disp None → disp_efetiva None, possivel_exp None, dif_possivel_exp None; possivel continua.
  - `test_possivel_do_dia`: possivel_do_dia(30000, 150, 6,0) == 1200; ipoa None → None; meta_ipoa 0 → None.
  - `test_portfolio`: A (pot 1000, a linha acima, meta 3000, produzida 2400), B (pot 3000, sem_etm, meta 5000,
    produzida 4000), C (pot 500, meta None, produzida 100, sem_etm): meta 8000; produzida 6400; dif_prod −0,2;
    possivel 3450; real_etm 2400; ipoa_ajustado 17,25 e meta_ipoa 15 (ponderados pela potência só de A).
- [ ] **Step 2:** `PYTHONPATH=thopen python -m pytest -q --noconftest tests/test_thopen_geracao_possivel.py` → falha
  (módulo não existe).
- [ ] **Step 3:** escrever o módulo. Regras não óbvias: dia entra se `ger > 0` ou (`ger == 0` e `ipoa_do_dia` com
  valor); furo = dia que não entra e vem antes do último dia que entrou; pesos da disponibilidade = IPOA medido do dia
  ou `meta_ipoa_mes / dias_mes`; dia sem disp publicada fica fora da média; `portfolio` soma meta e produzida das
  linhas com `meta`, possível e real das linhas sem `sem_etm`, possível_exp e real_exp das que têm `possivel_exp`.
- [ ] **Step 4:** a mesma linha de teste passa.

### Task 2: o GHI e a Visão Geral no servidor

**Files:**
- Modify: `thopen/dashboard_thopen.py` (`_ghi_por_dia` novo perto do `_daily_bd`; `_resumo_usina`; `geral`)
- Test: `tests/test_thopen_geracao_possivel_rotas.py`

**Interfaces:**
- Consumes: `geracao_possivel.periodo`, `geracao_possivel.portfolio`.
- Produces: `_ghi_por_dia(usina) -> dict[date, float]` (coluna "GHI" da aba diária do BD_Thopen; `{}` sem a aba ou
  sem a coluna; guardado em `_state["df"][("ghi", usina)]`). De 10/2026 em diante cada linha do `/api/t/geral` ganha
  `meta, irr_esp, irr_med, dif_prod, dif_irr` do período e `possivel, dif_possivel, possivel_exp, dif_possivel_exp,
  sem_etm, motivo, cobertura, dias, dias_medidos, furos ["dd/mm"]`; a resposta ganha `total` (o `portfolio`, com
  `disp` = a média simples de hoje) e `regra: "possivel"`. Antes de outubro, a resposta de antes, sem `total` nem
  `regra`.

- [ ] **Step 1: testes** (dados falsos com `monkeypatch` em `_daily_records`, `_ghi_por_dia`, `_meta2026`, `_registro`,
  `fonte_operacao.dados` e `operacao_mes.disp_por_dia`):
  - `test_geral_de_outubro_pela_regra`: linha da usina com meta/irr_esp/irr_med/possivel iguais ao `periodo` dos mesmos
    dados; `total` presente; `regra == "possivel"`.
  - `test_geral_de_setembro_igual_ao_de_antes`: setembro sem `total`, sem `regra` e com `meta` == a meta do mês inteiro.
  - `test_operacao_carregando_sem_expurgo`: `fonte_operacao.dados` → None → `possivel_exp` None e `possivel` presente.
  - `test_ghi_le_a_coluna_da_aba`: uma aba falsa com "GHI (kWh/m²)" vira `{date: valor}`; sem a coluna, `{}`.
- [ ] **Step 2:** rodar → falha.
- [ ] **Step 3:** implementar; o `_resumo_usina` de outubro em diante passa `disp_por_dia` só quando
  `THOPEN_OPERACAO` não é "0" e `fonte_operacao.dados()` veio.
- [ ] **Step 4:** passa, e `tests/test_thopen_operacao_rota.py` (que testa a Visão Geral de outubro) continua verde.

### Task 3: a Visão Geral na tela e na folha

**Files:**
- Modify: `thopen/templates/dashboard_thopen.html` (`renderGeral`, o cabeçalho da `#tblGeral`, CSS `table.geral` na
  impressão)
- Test: `tests/test_thopen_geracao_possivel_rotas.py` (testes de texto do HTML)

**Interfaces:**
- Consumes: a resposta do `/api/t/geral` da Task 2.

- [ ] **Step 1: testes**: `renderGeral` monta 14 colunas quando `d.regra === 'possivel'` (cabeçalhos "Geração Possível
  (kWh)", "Dif. Possível (%)", "Possível c/ Expurgos (kWh)", "Dif. c/ Expurgos (%)") e a linha Total vem de `d.total`;
  sem `d.regra`, o cabeçalho e o Total de antes; o texto "sem ETM" e "dias sem dado" existem no `renderGeral`.
- [ ] **Step 2:** rodar → falha.
- [ ] **Step 3:** implementar. "sem ETM" nas colunas de IPOA e de possível, com o título "medição em X de Y dias" (ou
  "sem meta de irradiação no mês"); a marca "N dias sem dado" na célula da usina com os dias no título; as usinas
  "fora" (abaixo do Total) com as mesmas 14 colunas; na folha, a fonte da tabela encolhe só com a regra nova até caber
  na largura A4.
- [ ] **Step 4:** passa.

### Task 4: a linha do Diário

**Files:**
- Modify: `thopen/dashboard_thopen.py` (`diario`; remover `_base_esperada` e `_esperada_ipoa`),
  `thopen/templates/dashboard_thopen.html` (`renderDiario`, `#grafTit`, a nota sob o gráfico, Metodologia)
- Delete: `tests/test_thopen_esperada_ipoa.py`; Modify: `tests/test_thopen_operacao_tela.py` (contagem dos mouses)
- Test: `tests/test_thopen_geracao_possivel_rotas.py`

**Interfaces:**
- Consumes: `geracao_possivel.ipoa_do_dia`, `possivel_do_dia`, `periodo` (para a cobertura do mês).
- Produces: de 10/2026 em diante `pontos[].possivel` e `pontos[].fonte_ipoa` ("ETM"|"GHI"|None) e `possivel_info`
  `{sem_etm, motivo, dias, dias_medidos}`; antes, a resposta de antes de 20/10 (sem essas chaves e sem `esperada`).

- [ ] **Step 1: testes**: outubro → `pontos[0].possivel == possivel_do_dia(meta, meta_ipoa, ipoa)` e `fonte_ipoa`;
  mês com cobertura < 50% → `possivel` nulo em todos e `possivel_info.sem_etm`; setembro → sem `possivel`, sem
  `esperada`; o HTML desenha "Possível pelo IPOA" no eixo da energia quando há `d.possivel_info` sem `sem_etm`, a nota
  "medição de irradiação em" quando `sem_etm`, e "Irradiação (kWh/m²)" com `yaxis2` antes de outubro; a Metodologia
  tem "Geração possível pelo IPOA" e não tem mais "PR da meta".
- [ ] **Step 2:** rodar → falha.
- [ ] **Step 3:** implementar; o mouse mostra "Possível pelo IPOA 22.900 kWh · IPOA 4,65 kWh/m² (ETM)".
- [ ] **Step 4:** passa, com a suíte do `thopen/` inteira.

### Task 5: prova e documentação

**Files:**
- Modify: `thopen/CLAUDE.md` (a seção da linha preta e a da Visão Geral: a regra, os estados, a prova)

- [ ] **Step 1:** dado real (cópia do cache do BD): Altair e Guaratinguetá V de outubro conferidas à mão contra o
  `periodo`; o `/api/t/geral` e o `/api/t/diario` de setembro idênticos aos do `origin/main` (as duas versões lado a
  lado, mesmo cache, comparação do JSON).
- [ ] **Step 2:** tela no navegador: Visão Geral e Diário de outubro, e a Visão Geral na folha (Ctrl+P) cabendo na
  largura.
- [ ] **Step 3:** suíte inteira da plataforma (`python -m pytest -q`) verde.
- [ ] **Step 4:** pedir ao Levi o OK para subir (commit e push na `main` só com a autorização dele).
