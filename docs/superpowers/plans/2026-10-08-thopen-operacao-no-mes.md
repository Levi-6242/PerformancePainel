# Operação no Mês (Dashboard Thopen) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No card "Operação no Mês" da aba Diário do 5080, por usina e mês (a partir de 10/2026): strings distintas com saída, trackers distintos parados com a usina comunicando e o nível de zeladoria da última ronda, com a frase da régua.

**Architecture:** A plataforma do servidor acrescenta colunas no FIM das abas do workbook `falhas_performance` (`plant_id`, `dias_comunicou`) e uma aba nova `cobertura`. O 5080 lê esse workbook bruto + as rondas (`campo_nexus · rondas`, `nexus_rondas_checklist · fato_checklist_ronda`) + o de-para do cadastro do Nexus pela mesma API, com cache próprio recarregado em segundo plano, e conta tudo em funções puras. Uma rota nova alimenta o card.

**Tech Stack:** Python 3.14 (Flask, openpyxl), JS puro + Plotly no template, pytest. API de leitura: `https://app.gridco.com.br/db_performace` (`fonte_api._get`).

**Spec:** `docs/superpowers/specs/2026-10-08-thopen-operacao-no-mes-design.md`

## Global Constraints

- Trabalho no worktree `C:\GridcoAuto\wt\thopen-operacao` (branch `feat/thopen-operacao-no-mes`, base `3d8bd7c`). O working tree principal tem trabalho SEM COMMIT de outras sessões (`falhas_job.py`, `app.py`, `relatorio_semanal.py`, `tests/test_falhas_job.py`): não tocar lá.
- **Commit só quando o Levi pedir** (CLAUDE.md da raiz). Os passos "Commit" deste plano viram "conferir `git diff --stat`"; o commit sai no fim, com o OK dele.
- Python: `"C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\python.exe"`; testes a partir da raiz do worktree: `python -m pytest -q <arquivo>`.
- pt-BR em tudo, inclusive comentários (que explicam o POR QUÊ, citando o caso real). Sem emoji na interface.
- Colunas novas SÓ NO FIM das abas existentes; nenhuma coluna existente muda de nome ou de lugar.
- Nada roda no import do `dashboard_thopen` (sem thread, sem rede): a plataforma importa 7 atributos dele.
- Nenhuma rota, assinatura ou formato existente do 5080 muda. As frases da régua moram só no Python.
- Só a partir de **10/2026** (`DESDE = (2026, 10)`).
- O 5080 é público: a resposta só leva agregados (lista branca de chaves), nunca técnico, texto livre ou OS.
- Nunca imprimir segredo (tokens.txt, `.env`).

---

### Task 0: Linha de base

**Files:** nenhum.

- [ ] **Step 1: Rodar a suíte inteira no worktree e guardar o resultado**

Run: `python -m pytest -q -p no:cacheprovider > "%SCRATCH%\base_pytest.txt" 2>&1` (a partir de `C:\GridcoAuto\wt\thopen-operacao`)
Expected: anotar quantos passam e QUAIS falham ANTES de mexer (falha pré-existente não é desta mudança). A memória de 07/10 diz que 4 testes ainda falam com a SunOp/API PV de verdade.

---

### Task 1: plataforma — `dias_comunicou` nos episódios de tracker e a `cobertura` do mês (`falhas_job.montar`)

**Files:**
- Modify: `plataforma/falhas_job.py` (depois de `def yield_dia` ~l.370; dentro de `fecha` ~l.1097–1150; antes do `return {"periodo"` ~l.1298)
- Test (novo): `tests/test_falhas_operacao_cliente.py`

**Interfaces:**
- Produces: cada linha de `pacote["trackers"]["rows"]` ganha `"dias_comunicou": int`; o pacote ganha `pacote["cobertura"] = [{"fonte", "plant_id", "usina", "cliente", "dias_strings", "dias_trackers", "dias_comunicou"}]` (ordenado por usina, fonte, plant_id).

- [ ] **Step 1: Escrever os testes que falham**

```python
# -*- coding: utf-8 -*-
"""Operação no Mês do Dashboard Thopen (Levi, 08/10/2026): o que a aba de falhas publica para o 5080 contar strings e
trackers DISTINTOS por usina, sem zero falso.

- "quando fica parado sem comunicação essa ocorrência é ignorada; se a usina comunicou inversor ou string então aí
  conta" → `dias_comunicou` em cada episódio de tracker (comunicou = a régua de strings leu produção da usina no dia,
  em qualquer fonte e cadastro dela, ou a geração do dia é > 0);
- usina sem linha nos episódios não é "usina sem falha": a aba `cobertura` (mês × fonte × plant_id) diz quem foi medido;
- Brodowski são dois cadastros na API PV com TRK1..52 cada → `plant_id` nas abas de episódio (sem ele, 51 em vez de 103).
"""
from datetime import datetime

import app
import falhas_job
import falhas_publicar as pub
import sol

PID = "18748739"          # Inhapi na API PV (cadastro real, como no test_falhas_job)


def trk(**por_dia):
    """trk(d01=(status, desvio), ...) → o formato do trk_eventos.json, um tracker só."""
    out = {}
    for k, (status, desvio) in por_dia.items():
        evs = [{"tracker": "TRK1", "parada": "08:00", "retorno": None, "desvio": desvio}] if status == "parado" else []
        out[f"2026-09-{k[1:]}"] = {PID: {"nome": "Inhapi", "cobertura": 1.0, "classes": {"TRK1": {"status": status}},
                                          "eventos": evs}}
    return out


def registro(*dias, vivas=24, usina="Inhapi", pid=PID, fonte="pv"):
    """falhas_strings.json: a régua de strings leu a usina nesses dias (com produção quando há vivas)."""
    return {f"2026-09-{d}": {fonte: {pid: {"usina": usina, "ts": 0, "mortas": [],
                                           "vivas": {"Inversor 3.3": vivas} if vivas else {}}}} for d in dias}


def monta(trk_store, mortas=None, geracao=None, fim="2026-09-03"):
    return falhas_job.montar(app, sol, "2026-09-01", fim, geracao=geracao or {}, str_store={}, trk_store=trk_store,
                             book={}, hist_2c=lambda dia: {}, mortas_curva=mortas or {}, log=lambda m: None,
                             agora=datetime(2026, 9, 30, 12, 0))


def test_tracker_parado_com_a_usina_lendo_strings_conta_os_dias_em_que_ela_comunicou():
    (r,) = monta(trk(d01=("parado", 35.0), d02=("parado", 35.0)), mortas=registro("01", "02"))["trackers"]["rows"]
    assert r["dias_comunicou"] == 2


def test_tracker_parado_com_a_usina_muda_tem_zero_dias_de_comunicacao():
    (r,) = monta(trk(d01=("parado", 35.0), d02=("parado", 35.0)))["trackers"]["rows"]
    assert r["dias_comunicou"] == 0


def test_registro_de_madrugada_sem_producao_nao_e_comunicacao():
    (r,) = monta(trk(d01=("parado", 35.0)), mortas=registro("01", vivas=None))["trackers"]["rows"]
    assert r["dias_comunicou"] == 0


def test_geracao_do_dia_tambem_prova_que_a_usina_comunicou():
    u = app._macro_usina_nome("Inhapi") or "Inhapi"
    ger = {u: {"kwp": 1000.0, "dias": {"2026-09-01": 4500.0}}}
    (r,) = monta(trk(d01=("parado", 35.0), d02=("parado", 35.0)), geracao=ger)["trackers"]["rows"]
    assert r["dias_comunicou"] == 1


def test_outro_cadastro_da_mesma_usina_prova_a_comunicacao():
    # Brodowski, out/2026: a metade 297381 não tem registro de strings, a 297378 (mesma usina) tem todo dia
    (r,) = monta(trk(d01=("parado", 35.0)), mortas=registro("01", pid="999", fonte="pvsb"))["trackers"]["rows"]
    assert r["dias_comunicou"] == 1


def test_cobertura_diz_quem_foi_medido_no_mes_mesmo_sem_falha():
    p = monta(trk(d01=("normal", None), d02=("parado", 35.0)), mortas=registro("01", "02", "03"))
    (c,) = [x for x in p["cobertura"] if x["plant_id"] == PID]
    assert (c["fonte"], c["dias_strings"], c["dias_trackers"], c["dias_comunicou"]) == ("pv", 3, 2, 3)
    assert c["usina"] and c["cliente"] == p["trackers"]["rows"][0]["cliente"]


def test_usina_sem_registro_nenhum_nao_aparece_na_cobertura():
    p = monta({}, mortas=registro("01"))
    assert {x["plant_id"] for x in p["cobertura"]} == {PID}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_falhas_operacao_cliente.py`
Expected: FAIL — `KeyError: 'dias_comunicou'` e `KeyError: 'cobertura'`.

- [ ] **Step 3: Implementar em `plataforma/falhas_job.py`**

(a) Logo depois de `def yield_dia(...)` (antes de `# ══ STRINGS`):

```python
    # ── a usina comunicou no dia? (Levi, 08/10/2026, para o Dashboard Thopen: "quando fica parado sem comunicação
    # essa ocorrência é ignorada; se a usina comunicou inversor ou string então aí conta"). Prova = a régua de strings
    # leu PRODUÇÃO da usina nesse dia (qualquer fonte e qualquer cadastro dela — a Brodowski 297381 não tem registro de
    # strings e a 297378, a mesma usina, tem todo dia) ou a geração do dia é > 0. Registro de madrugada sem nada gerando
    # não prova (a mesma régua do "a usina apareceu" das strings). A geração sozinha não serve: ela é D-1, e o dia
    # corrente sairia sempre "sem comunicação".
    com_dia = defaultdict(set)
    for dia_c, fontes_c in mortas_curva.items():
        for usinas_c in (fontes_c or {}).values():
            for pid_c, ent_c in (usinas_c or {}).items():
                if ent_c.get("vivas") or ent_c.get("mortas"):
                    com_dia[nrm(canon(ent_c.get("usina") or pid_c))].add(dia_c)

    def usina_comunicou(usina, dia):
        return dia in com_dia.get(nrm(canon(usina)), ()) or yield_dia(usina, dia) is not None
```

(b) Dentro de `fecha(...)`, logo antes de `chave = chave_trk(fonte, pid, trk, ep["ini_dia"])`:

```python
            dias_com = sum(1 for dd, _x, _y in ep["dias"] if usina_comunicou(usina_c, dd))
```

e no dicionário da linha (o `.append({...})` logo abaixo), depois de `"sem_com_desde": ep.get("sc_fim"),`:

```python
                             "dias_comunicou": dias_com,
```

(c) Antes do `return {"periodo": ...}` do `montar`:

```python
    # ── cobertura do mês (08/10/2026): quem a plataforma MEDIU, com ou sem falha. Sem ela, a usina sem linha nos
    # episódios sairia "0 falhas" no dashboard do cliente — e pode ser usina que a plataforma nem monitora.
    cob = {}

    def _cob(fonte, pid, usina):
        return cob.setdefault((fonte, str(pid)), {"fonte": fonte, "plant_id": str(pid), "usina": canon(usina),
                                                  "s": set(), "t": set()})
    for dia_c in [x for x in sorted(mortas_curva) if ini <= x <= fim]:
        for fonte_c, usinas_c in (mortas_curva[dia_c] or {}).items():
            for pid_c, ent_c in (usinas_c or {}).items():
                if ent_c.get("vivas") or ent_c.get("mortas"):
                    _cob(fonte_c, pid_c, ent_c.get("usina") or pid_c)["s"].add(dia_c)
    for dia_c in [x for x in sorted(str_store) if ini <= x <= fim]:     # o store das quedas também é medição
        for fonte_c, usinas_c in (str_store[dia_c] or {}).items():
            if fonte_c == "owen":
                continue
            for pid_c, ent_c in (usinas_c or {}).items():
                _cob(fonte_c, pid_c, ent_c.get("usina") or pid_c)["s"].add(dia_c)
    for dia_c in dias_t:
        for pid_c, ent_c in (trk_store.get(dia_c) or {}).items():
            if ent_c.get("classes") is not None and (ent_c.get("cobertura") or 0) > 0:
                _cob(fonte_de(pid_c), pid_c, nomes.get(pid_c) or pid_c)["t"].add(dia_c)
    _d0 = datetime.strptime(ini, "%Y-%m-%d")
    todos_dias = [(_d0 + timedelta(days=i)).strftime("%Y-%m-%d")
                  for i in range((datetime.strptime(fim, "%Y-%m-%d") - _d0).days + 1)]
    cobertura = sorted(({"fonte": c["fonte"], "plant_id": c["plant_id"], "usina": c["usina"],
                         "cliente": cliente(c["usina"]), "dias_strings": len(c["s"]), "dias_trackers": len(c["t"]),
                         "dias_comunicou": sum(1 for d_ in todos_dias if usina_comunicou(c["usina"], d_))}
                        for c in cob.values()), key=lambda c: (c["usina"], c["fonte"], c["plant_id"]))
```

e no dicionário do `return`, ao lado de `"strings"`/`"trackers"`: `"cobertura": cobertura,`.

- [ ] **Step 4: Rodar e ver passar (e o resto das falhas intacto)**

Run: `python -m pytest -q tests/test_falhas_operacao_cliente.py tests/test_falhas_job.py`
Expected: PASS em todos.

- [ ] **Step 5: Conferir o diff** — `git diff --stat` mostra só `plataforma/falhas_job.py` e o teste novo.

---

### Task 2: plataforma — colunas novas e a aba `cobertura` no workbook (`falhas_publicar.py`)

**Files:**
- Modify: `plataforma/falhas_publicar.py:26-35` (CABECALHOS) e `:63-93` (tabelas)
- Test: `tests/test_falhas_operacao_cliente.py` (acrescentar)

**Interfaces:**
- Consumes: `pacote["cobertura"]`, `row["plant_id"]`, `row["dias_comunicou"]` (Task 1).
- Produces (contrato com o 5080 — nomes exatos): `strings_episodios` termina em `plant_id`; `trackers_episodios` termina em `plant_id, dias_comunicou`; aba `cobertura` = `mes, fonte, cliente, usina, plant_id, dias_strings, dias_trackers, dias_comunicou`; `atualizacao` termina em `cobertura`. `fonte` sempre pelo `FONTE_ROT` (o mesmo rótulo das outras abas).

- [ ] **Step 1: Escrever os testes que falham** (acrescentar ao arquivo da Task 1)

```python
ANTES = {"strings_episodios": ["mes", "fonte", "cliente", "usina", "inversor", "string", "saiu", "voltou", "situacao",
                               "dias", "horas_sol", "perda_kwh", "perda_inferida_kwh", "kwp_string", "metodo", "avisos"],
         "trackers_episodios": ["mes", "fonte", "cliente", "usina", "tracker", "inversor", "parou", "voltou", "situacao",
                                "horas_sol", "desvio_pico_graus", "fator_perda", "kwp_tracker", "perda_kwh", "cronico",
                                "avisos"],
         "atualizacao": ["mes", "periodo_inicio", "periodo_fim", "atualizado_em", "strings_inversor_dia",
                         "strings_episodios", "trackers_episodios", "regua_strings", "regua_trackers"]}


def _pac():
    return {"mes": "2026-10", "gerado_em": "2026-10-08 10:05", "periodo": ["2026-10-01", "2026-10-08"], "regua": {},
            "strings": {"rows": [], "episodios": [
                {"fonte": "pv", "plant_id": "297378", "cliente": "Thopen", "usina": "Brodowski",
                 "inversor": "Inversor 2.1", "string": "Ipv3", "inicio": "2026-10-02 07:00", "fim": None, "flags": []}]},
            "trackers": {"rows": [
                {"fonte": "pv", "plant_id": "297381", "cliente": "Thopen", "usina": "Brodowski", "tracker": "TRK1",
                 "inicio": "2026-10-01 08:00", "fim": None, "dias_comunicou": 3, "flags": []}]},
            "cobertura": [{"fonte": "pv", "plant_id": "297378", "usina": "Brodowski", "cliente": "Thopen",
                           "dias_strings": 8, "dias_trackers": 8, "dias_comunicou": 8}]}


def _linhas(tabs, aba):
    return [dict(zip(pub.CABECALHOS[aba], lin)) for lin in tabs[aba]]


def test_colunas_novas_entram_so_no_fim_das_abas():
    for aba, cab in ANTES.items():
        assert pub.CABECALHOS[aba][:len(cab)] == cab                  # BI e Nexus leem por posição: nada se mexe
    assert pub.CABECALHOS["strings_episodios"][len(ANTES["strings_episodios"]):] == ["plant_id"]
    assert pub.CABECALHOS["trackers_episodios"][len(ANTES["trackers_episodios"]):] == ["plant_id", "dias_comunicou"]
    assert pub.CABECALHOS["atualizacao"][len(ANTES["atualizacao"]):] == ["cobertura"]
    assert pub.CABECALHOS["cobertura"] == ["mes", "fonte", "cliente", "usina", "plant_id", "dias_strings",
                                           "dias_trackers", "dias_comunicou"]


def test_episodios_levam_o_plant_id_e_o_tracker_os_dias_em_que_a_usina_comunicou():
    tabs = pub.tabelas([_pac()])
    (s,) = _linhas(tabs, "strings_episodios")
    (t,) = _linhas(tabs, "trackers_episodios")
    assert (s["plant_id"], t["plant_id"], t["dias_comunicou"]) == ("297378", "297381", 3)


def test_aba_cobertura_e_a_contagem_na_atualizacao():
    tabs = pub.tabelas([_pac()])
    (c,) = _linhas(tabs, "cobertura")
    assert (c["mes"], c["fonte"], c["usina"], c["plant_id"], c["dias_strings"], c["dias_comunicou"]) == \
        ("2026-10", "Thopen · API PV", "Brodowski", "297378", 8, 8)
    (a,) = _linhas(tabs, "atualizacao")
    assert a["cobertura"] == 1


def test_pacote_antigo_sem_os_campos_novos_sai_com_celula_vazia():
    p = _pac()
    del p["cobertura"]
    p["trackers"]["rows"][0].pop("dias_comunicou")
    tabs = pub.tabelas([p])
    assert _linhas(tabs, "cobertura") == []
    assert _linhas(tabs, "trackers_episodios")[0]["dias_comunicou"] is None
    assert _linhas(tabs, "atualizacao")[0]["cobertura"] == 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_falhas_operacao_cliente.py -k "colunas or plant_id or cobertura or antigo"`
Expected: FAIL (`KeyError: 'cobertura'` / listas diferentes).

- [ ] **Step 3: Implementar em `plataforma/falhas_publicar.py`**

CABECALHOS (as abas existentes só ganham colunas no FIM; `cobertura` entra antes da `atualizacao`):

```python
CABECALHOS = {
    "strings_inversor_dia": ["mes", "dia", "fonte", "cliente", "usina", "inversor", "qtd_strings", "strings",
                             "horas_x_strings", "perda_kwh", "perda_nominal_kwh", "kwp_string", "kwh_kwp_dia", "avisos"],
    # plant_id no FIM (08/10/2026, Dashboard Thopen): sem ele, quem conta string/tracker distinto junta cadastros de
    # mesmo nome — a Brodowski são dois na API PV, com TRK1..52 cada (51 em vez de 103 em setembro)
    "strings_episodios": ["mes", "fonte", "cliente", "usina", "inversor", "string", "saiu", "voltou", "situacao", "dias",
                          "horas_sol", "perda_kwh", "perda_inferida_kwh", "kwp_string", "metodo", "avisos", "plant_id"],
    "trackers_episodios": ["mes", "fonte", "cliente", "usina", "tracker", "inversor", "parou", "voltou", "situacao",
                           "horas_sol", "desvio_pico_graus", "fator_perda", "kwp_tracker", "perda_kwh", "cronico", "avisos",
                           "plant_id", "dias_comunicou"],
    # quem a plataforma mediu no mês, com ou sem falha: separa "0" de "sem monitoramento" no dashboard do cliente
    "cobertura": ["mes", "fonte", "cliente", "usina", "plant_id", "dias_strings", "dias_trackers", "dias_comunicou"],
    "atualizacao": ["mes", "periodo_inicio", "periodo_fim", "atualizado_em", "strings_inversor_dia", "strings_episodios",
                    "trackers_episodios", "regua_strings", "regua_trackers", "cobertura"],
}
```

Em `tabelas`, um helper para o id (texto sempre, para "297378" não virar número em lugar nenhum):

```python
def _pid(x):
    return None if x in (None, "") else str(x)
```

e nas montagens: `strings_episodios` acrescenta `_pid(e.get("plant_id"))` no fim da tupla; `trackers_episodios` acrescenta `_pid(r.get("plant_id")), r.get("dias_comunicou")` no fim; antes da `atualizacao`:

```python
        cs = sorted(p.get("cobertura") or [], key=lambda c: (c["usina"], c["fonte"], str(c["plant_id"])))
        for c in cs:
            out["cobertura"].append([_v(x) for x in (
                mes, FONTE_ROT.get(c["fonte"], c["fonte"]), c.get("cliente"), c["usina"], _pid(c["plant_id"]),
                c.get("dias_strings"), c.get("dias_trackers"), c.get("dias_comunicou"))])
```

e a linha da `atualizacao` acrescenta `len(cs)` no fim. (Atenção: `_v(0)` devolve 0 — só None, "" e lista vazia viram vazio.)

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest -q tests/test_falhas_operacao_cliente.py tests/test_falhas_publicar.py tests/test_falhas_job.py`
Expected: PASS.

- [ ] **Step 5: Conferir o diff** (`git diff --stat`).

---

### Task 3: Nexus — registrar a aba nova no catálogo (governança, regra 10)

**Files:**
- Modify: `C:\Users\Levi Maia\OneDrive - GRID CO\Área de Trabalho\temp\Nexus\nexus\dados\catalogo.py:113-120` (fatos `falha_string`/`falha_tracker` + fato novo `cobertura_falhas`)
- Modify: `...\Nexus\nexus\dados\CLAUDE.md` (contagem de fatos e a linha da tabela "O que existe", se o texto citar números)

- [ ] **Step 1: Ler** `nexus/dados/CLAUDE.md` (regras 1–11) e confirmar no `git status` do Nexus que `nexus/dados/` e `tests/test_dados_camada.py` não têm trabalho de outra sessão.
- [ ] **Step 2: Editar o catálogo**

```python
    Fato("falha_string", "Falha de string", "performance",
         "falhas_performance · strings_episodios, strings_inversor_dia", "1 linha = 1 episódio · inversor × dia",
         _d(data=("cod", "saiu / dia"), usina=("cod", "plant_id da fonte, nos episódios (08/10/2026); usina em nome"),
            cliente=("nome", "cliente"), equipamento=("nome", "inversor, string"))),
    Fato("falha_tracker", "Falha de tracker", "performance", "falhas_performance · trackers_episodios",
         "1 linha = 1 episódio",
         _d(data=("cod", "parou"), usina=("cod", "plant_id da fonte (08/10/2026); usina em nome"),
            cliente=("nome", "cliente"), equipamento=("nome", "tracker, inversor")),
         observacao="dias_comunicou: dias do episódio em que a usina leu string ou gerou (Dashboard Thopen, 08/10/2026)."),
    Fato("cobertura_falhas", "Cobertura do registro de falhas", "performance", "falhas_performance · cobertura",
         "1 linha = mês × fonte × plant_id (dias medidos de strings e de trackers)",
         _d(data=("cod", "mes"), usina=("cod", "plant_id da fonte; usina em nome"), cliente=("nome", "cliente")),
         observacao="Separa 'sem falha' de 'sem monitoramento' no Dashboard Thopen (08/10/2026)."),
```

- [ ] **Step 3: Rodar os testes do Nexus**

Run (na pasta do Nexus): `python -m pytest -q tests/test_dados_camada.py`
Expected: PASS. Se algum teste/página contar "15 fatos", atualizar o número na página (não no teste) e rodar de novo.

- [ ] **Step 4: Conferir o diff do Nexus** — só `nexus/dados/catalogo.py` (e o CLAUDE.md da pasta, se mudou). Commit separado, no repo do Nexus, quando o Levi pedir.

---

### Task 4: 5080 — funções puras da Operação no Mês (`thopen/operacao_mes.py`)

**Files:**
- Create: `thopen/operacao_mes.py`
- Test (novo): `tests/test_thopen_operacao_mes.py`

**Interfaces:**
- Consumes: o dicionário `dados` = `{"strings_episodios", "trackers_episodios", "cobertura", "atualizacao", "rondas_com_os", "rondas_sem_os", "de_para"}` (listas de dicts, colunas do contrato da Task 2; rondas já com `sujidade`/`vegetacao` lidos e sem o texto).
- Produces: `DESDE`, `REGUA`, `CHAVES`, `chave(nome) -> str`, `ler_respostas(texto) -> {"sujidade", "vegetacao"}`, `conferir(dados) -> bool`, `resposta(dados|None, nome, ano, mes, hoje: date) -> dict` com exatamente as chaves de `CHAVES`.

- [ ] **Step 1: Escrever os testes que falham**

```python
# -*- coding: utf-8 -*-
"""Operação no Mês do Dashboard Thopen (08/10/2026): as contas puras do card do Diário.

Cada teste trava um erro previsto antes de ir ao cliente: Brodowski pela metade sem o plant_id, duas linhas iguais que
são dois trackers (Assis), parada com a usina muda, zero que é "sem monitoramento", Ipixuna da 2C na tela da Thopen,
ronda repetida em 3 OS, hora da ronda em UTC, nome que não casa, nível fora da escala, nada antes de 10/2026.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import operacao_mes as om  # noqa: E402

HOJE = dt.date(2026, 10, 8)


def ep_s(usina, pid, inv, st, mes="2026-10", cliente="Thopen", fonte="Thopen · API PV"):
    return {"mes": mes, "fonte": fonte, "cliente": cliente, "usina": usina, "inversor": inv, "string": st, "plant_id": pid}


def ep_t(usina, pid, trk, dias_com=1, mes="2026-10", cliente="Thopen", fonte="Thopen · API PV"):
    return {"mes": mes, "fonte": fonte, "cliente": cliente, "usina": usina, "tracker": trk, "plant_id": pid,
            "dias_comunicou": dias_com}


def cob(usina, pid, s=8, t=8, mes="2026-10", cliente="Thopen"):
    return {"mes": mes, "fonte": "Thopen · API PV", "cliente": cliente, "usina": usina, "plant_id": pid,
            "dias_strings": s, "dias_trackers": t}


def dados(**kw):
    base = {"strings_episodios": [], "trackers_episodios": [], "cobertura": [], "atualizacao": [],
            "rondas_com_os": [], "rondas_sem_os": [], "de_para": []}
    base.update(kw)
    return base


def test_brodowski_conta_os_dois_cadastros_pelo_plant_id():
    t = [ep_t("Brodowski", "297378", f"TRK{i}") for i in range(1, 53)] + \
        [ep_t("Brodowski", "297381", f"TRK{i}") for i in range(1, 52)]
    r = om.resposta(dados(trackers_episodios=t, cobertura=[cob("Brodowski", "297378")]), "Brodowski", 2026, 10, HOJE)
    assert r["trackers"] == 103


def test_duas_linhas_iguais_de_cadastros_diferentes_sao_dois_trackers():
    # Assis, out/2026: TRK15 do 18747549 e do 18747550 chegam iguais tirando o plant_id — deduplicar apagaria um
    t = [ep_t("Assis", "18747549", "TRK15"), ep_t("Assis", "18747550", "TRK15"), ep_t("Assis", "18747550", "TRK15")]
    assert om.resposta(dados(trackers_episodios=t), "Assis", 2026, 10, HOJE)["trackers"] == 2


def test_parada_com_a_usina_muda_nao_conta_e_a_coluna_vazia_conta():
    t = [ep_t("Altair", "1", "TRK1", dias_com=0), ep_t("Altair", "1", "TRK2", dias_com=None),
         ep_t("Altair", "1", "TRK3", dias_com=2)]
    assert om.resposta(dados(trackers_episodios=t), "Altair", 2026, 10, HOJE)["trackers"] == 2


def test_strings_distintas_por_inversor_e_string_com_o_nome_do_inversor_normalizado():
    s = [ep_s("Altair", "1", "Inversor 1.1", "Ipv3"), ep_s("Altair", "1", "inversor 1.1", "Ipv3"),
         ep_s("Altair", "1", "Inversor 1.2", "Ipv3")]
    assert om.resposta(dados(strings_episodios=s), "Altair", 2026, 10, HOJE)["strings"] == 2


def test_medida_sem_falha_e_zero_e_sem_cobertura_e_sem_monitoramento():
    r = om.resposta(dados(cobertura=[cob("Altair", "1", s=8, t=0)]), "Altair", 2026, 10, HOJE)
    assert (r["strings"], r["trackers"]) == (0, None)
    r = om.resposta(dados(), "Lyon", 2026, 10, HOJE)
    assert (r["strings"], r["trackers"], r["disponivel"]) == (None, None, True)


def test_cliente_de_outra_empresa_nunca_entra():
    # Ipixuna do Pará é da 2C (2C-IPX100); Ipixuna 1 e 2 da Polaris são THPN-IPX100 — regra 4 do Kimball
    s = [ep_s("Ipixuna 1", "x", "Inversor 1.1", "Ipv1", cliente="2C")]
    assert om.resposta(dados(strings_episodios=s), "Ipixuna 1", 2026, 10, HOJE)["strings"] is None


def test_nomes_das_falhas_que_nao_sao_os_do_5080():
    s = [ep_s("Primavera 1", "a", "Inversor 1.1", "Ipv1"), ep_s("Primavera 2", "b", "Inversor 1.1", "Ipv1"),
         ep_s("Marajoara I", "c", "Inversor 1.1", "Ipv1"), ep_s("Corrego do Sapucaia", "d", "Inversor 1.1", "Ipv1"),
         ep_s("Santo Antonio do Platina", "e", "Inversor 1.1", "Ipv1")]
    d = dados(strings_episodios=s)
    assert om.resposta(d, "Primavera", 2026, 10, HOJE)["strings"] == 2
    assert om.resposta(d, "Marajoara 1", 2026, 10, HOJE)["strings"] == 1
    assert om.resposta(d, "Córrego do Sapucaia", 2026, 10, HOJE)["strings"] == 1
    assert om.resposta(d, "Santo Antonio da Platina", 2026, 10, HOJE)["strings"] == 1


def test_sem_plant_id_publicado_nao_mostra_numero():
    s = [ep_s("Altair", None, "Inversor 1.1", "Ipv1")]
    r = om.resposta(dados(strings_episodios=s), "Altair", 2026, 10, HOJE)
    assert r["disponivel"] is False and "plant_id" in r["motivo"]


def test_antes_de_outubro_nao_responde_e_sem_dados_esta_carregando():
    assert om.resposta(dados(), "Altair", 2026, 9, HOJE)["motivo"] == "antes de 10/2026"
    r = om.resposta(None, "Altair", 2026, 10, HOJE)
    assert r["disponivel"] is False and r["motivo"] == "carregando"


def test_niveis_do_texto_da_ronda_e_fora_da_escala_e_sem_leitura():
    t = ("Computador: Ligado; Sujidade da vala de drenagem: Limpa; Sujidade dos módulos: 4; "
         "Altura da vegetação: Não se aplica")
    assert om.ler_respostas(t) == {"sujidade": 4, "vegetacao": None}
    assert om.ler_respostas("Sujidade dos módulos: 7; Altura da vegetação: 0") == {"sujidade": None, "vegetacao": None}


def ronda(uid, dia, hi, suj, veg, hf="11:00"):
    return {"usina_id": uid, "dia": dia, "hora_inicio": hi, "hora_fim": hf, "sujidade": suj, "vegetacao": veg}


DP = [{"usina_id": 1, "chave_externa": "Altair"}, {"usina_id": 114, "chave_externa": "Primavera"},
      {"usina_id": 115, "chave_externa": "Primavera"}, {"usina_id": 77, "chave_externa": "Coração 1"},
      {"usina_id": 77, "chave_externa": "Coração 2"}]


def test_zeladoria_e_a_ultima_ronda_do_mes_com_a_frase_da_regua():
    rs = [ronda(1, "2026-10-01", "13:00", 5, 5), ronda(1, "2026-10-02", "12:00", 2, 3),
          ronda(1, "2026-09-30", "13:00", 1, 1)]
    z = om.resposta(dados(rondas_com_os=rs, de_para=DP), "Altair", 2026, 10, HOJE)["zeladoria"]
    assert z == {"data": "02/10", "sujidade": {"nivel": 2, "frase": om.REGUA["sujidade"][2]},
                 "vegetacao": {"nivel": 3, "frase": om.REGUA["vegetacao"][3]}}


def test_hora_da_ronda_e_utc():
    # 01/10 às 00:30 UTC é 30/09 21:30 em Brasília: não é ronda de outubro
    rs = [ronda(1, "2026-10-01", "00:30", 4, 4)]
    assert om.resposta(dados(rondas_com_os=rs, de_para=DP), "Altair", 2026, 10, HOJE)["zeladoria"] is None


def test_ronda_sem_os_entra_e_a_mais_tarde_do_dia_vence():
    rs = [ronda(1, "2026-10-06", "10:00", 2, 2)]
    sem = [{"usina_id": 1, "inicio": "2026-10-06T16:43:50.341Z", "sujidade": 4, "vegetacao": 1}]
    z = om.resposta(dados(rondas_com_os=rs, rondas_sem_os=sem, de_para=DP), "Altair", 2026, 10, HOJE)["zeladoria"]
    assert (z["sujidade"]["nivel"], z["vegetacao"]["nivel"]) == (4, 1)


def test_usina_de_dois_ids_e_id_de_duas_usinas():
    rs = [ronda(115, "2026-10-02", "12:00", 3, 3), ronda(77, "2026-10-01", "12:00", 2, 2)]
    d = dados(rondas_com_os=rs, de_para=DP)
    assert om.resposta(d, "Primavera", 2026, 10, HOJE)["zeladoria"]["data"] == "02/10"
    assert om.resposta(d, "Coração 1", 2026, 10, HOJE)["zeladoria"]["data"] == "01/10"
    assert om.resposta(d, "Coração 2", 2026, 10, HOJE)["zeladoria"]["data"] == "01/10"


def test_usina_sem_ligacao_no_cadastro_nao_chuta_id():
    rs = [ronda(1, "2026-10-02", "12:00", 3, 3)]
    assert om.resposta(dados(rondas_com_os=rs, de_para=DP), "Lyon", 2026, 10, HOJE)["zeladoria"] is None


def test_ronda_repetida_em_varias_os_e_uma_so():
    rs = [ronda(1, "2026-10-02", "12:00", 3, 3)] * 3
    assert len(om.rondas_com_os(rs)) == 1


def test_mes_corrente_diz_ate_quando_e_a_resposta_so_tem_as_chaves_da_lista():
    at = [{"mes": "2026-10", "periodo_fim": "2026-10-08", "atualizado_em": "2026-10-08 10:05",
           "strings_episodios": 0, "trackers_episodios": 0, "cobertura": 0}]
    r = om.resposta(dados(atualizacao=at), "Altair", 2026, 10, HOJE)
    assert (r["parcial_ate"], r["atualizado_em"]) == ("08/10", "2026-10-08 10:05")
    assert tuple(r) == om.CHAVES                                           # lista branca: nada além disto ao cliente


def test_conferencia_da_leitura_com_a_aba_atualizacao():
    at = [{"mes": "2026-10", "strings_episodios": 1, "trackers_episodios": 0, "cobertura": None}]
    assert om.conferir(dados(atualizacao=at, strings_episodios=[ep_s("Altair", "1", "Inversor 1.1", "Ipv1")]))
    assert not om.conferir(dados(atualizacao=at))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_thopen_operacao_mes.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'operacao_mes'`.

- [ ] **Step 3: Implementar `thopen/operacao_mes.py`**

```python
# -*- coding: utf-8 -*-
"""Operação no Mês (Dashboard Thopen, 08/10/2026): strings com saída, trackers parados e a zeladoria da usina.

Pedido do Levi: "quantas strings tiveram saída naquele mês para aquela usina e quantos trackers pararam (trackers
distintos)" + "o nível de zeladoria" das rondas do Nexus. Mockup aprovado em 08/10: card no Diário, só de 10/2026 em
diante, com a frase de cada nível da régua. Tudo aqui é puro (sem rede, sem Flask): a leitura mora em `fonte_operacao`
e a rota em `dashboard_thopen`.
"""
import datetime as dt
import unicodedata

DESDE = (2026, 10)          # Levi, 08/10: "somente a partir de outubro"
FUSO_H = -3                 # Brasília (sem horário de verão desde 2019); as rondas chegam em UTC
CLIENTE = "Thopen"          # as 4 carteiras do 5080 são do cliente Thopen nas falhas; a Ipixuna do Pará é da 2C

# A régua das rondas: 5 níveis e a frase de cada um (cartão "A régua: cinco níveis", Levi, 08/10/2026).
REGUA = {
    "sujidade": {1: "Vidro limpo, escuro e com reflexo",
                 2: "Sujeira leve ou pontual: manchas, escorrido, dejeto",
                 3: "Película visível, mas o módulo ainda aparece escuro",
                 4: "Camada densa e uniforme, módulo fosco e acinzentado",
                 5: "Camada grossa de poeira/terra, cor da célula some"},
    "vegetacao": {1: "Área roçada, grama rente, corredor limpo",
                  2: "Vegetação baixa, com poucos pontos mais altos",
                  3: "Mato médio e uniforme, ainda abaixo da borda dos módulos",
                  4: "Mato alto e denso, encostando na borda inferior dos módulos",
                  5: "Mato na altura ou acima dos módulos, sombreando e fechando o corredor"},
}

# Nome nas falhas (o canônico da plataforma) → nome do 5080 (a coluna Usina do BD_Thopen). Medido em 08/10 contra o
# workbook falhas_performance: só estes não casavam pelo nome sem acento. A Ouro Branco (um nome nas falhas, I a V no
# 5080) fica de fora até haver de-para por plant_id.
ALIAS_FALHAS = {"Marajoara I": "Marajoara 1", "Piracicaba I": "Piracicaba 1",
                "Nova Londrina 1": "Nova Londrina", "Nova Londrina 2": "Nova Londrina",
                "Primavera 1": "Primavera", "Primavera 2": "Primavera",
                "Santo Antonio do Platina": "Santo Antonio da Platina"}

# O que a rota devolve — e NADA além disto (o 5080 é público, sem senha).
CHAVES = ("disponivel", "motivo", "usina", "ano", "mes", "strings", "trackers", "zeladoria", "regua",
          "parcial_ate", "atualizado_em")

_ROT = (("sujidade dos modulos", "sujidade"), ("altura da vegetacao", "vegetacao"))


def chave(nome):
    """Nome para comparar: sem acento, minúsculo, espaços simples ('Córrego' = 'Corrego')."""
    s = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def nivel(v):
    """1 a 5, ou None ("Não se aplica", vazio ou fora da escala nunca vira 0)."""
    n = _int(v)
    return n if n is not None and 1 <= n <= 5 and str(v).strip().replace(".0", "").isdigit() else None


def ler_respostas(texto):
    """{sujidade, vegetacao} do texto de respostas da ronda com OS, como o App escreve: "Sujidade dos módulos: 4;
    Altura da vegetação: 2; ...". O resto do texto (vala, sensores, portaria) não interessa ao card."""
    out = {"sujidade": None, "vegetacao": None}
    for parte in str(texto or "").split(";"):
        rot, sep, val = parte.rpartition(":")
        if not sep:
            continue
        k = next((k for p, k in _ROT if chave(rot).startswith(p)), None)
        if k:
            out[k] = nivel(val.strip())
    return out


def _brt(utc):
    return utc + dt.timedelta(hours=FUSO_H)


def rondas_com_os(linhas):
    """campo_nexus · rondas → [{usina_id, quando (Brasília), sujidade, vegetacao}]. A mesma ronda vem repetida em 2–3
    OS (800 linhas = 598 rondas em 08/10): uma por usina + dia + início + fim. hora_inicio é UTC (conferido em 08/10:
    +180 min contra o Início do App em 594 de 594 rondas)."""
    vistas, out = set(), []
    for r in linhas or []:
        uid, dia, hi = _int(r.get("usina_id")), str(r.get("dia") or "")[:10], str(r.get("hora_inicio") or "")[:5]
        k = (uid, dia, hi, str(r.get("hora_fim") or "")[:5])
        if uid is None or k in vistas:
            continue
        vistas.add(k)
        try:
            utc = dt.datetime.strptime(f"{dia} {hi}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        out.append({"usina_id": uid, "quando": _brt(utc), "sujidade": nivel(r.get("sujidade")),
                    "vegetacao": nivel(r.get("vegetacao"))})
    return out


def rondas_sem_os(linhas):
    """nexus_rondas_checklist · fato_checklist_ronda → o mesmo formato. `inicio` é ISO em UTC ("...Z")."""
    out = []
    for r in linhas or []:
        uid = _int(r.get("usina_id"))
        try:
            utc = dt.datetime.strptime(str(r.get("inicio") or "")[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
        if uid is not None:
            out.append({"usina_id": uid, "quando": _brt(utc), "sujidade": nivel(r.get("sujidade")),
                        "vegetacao": nivel(r.get("vegetacao"))})
    return out


def _nomes(nome):
    """O nome do 5080 e os nomes que viram ele (os aliases), todos como chave."""
    alvo = chave(nome)
    return {alvo} | {chave(a) for a, b in ALIAS_FALHAS.items() if chave(b) == alvo}


def ids_da_usina(de_para, nome):
    """usina_id(s) do nome do 5080 pelo de-para do cadastro do Nexus (sistema "BD_Thopen · Dados Gerais Usinas").
    N:N: Primavera e Nova Londrina têm dois ids; Coração 1 e 2 dividem um. Sem ligação = vazio (nunca chutar ID)."""
    nomes = _nomes(nome)
    return {u for u, ext in ((_int(r.get("usina_id")), r.get("chave_externa")) for r in de_para or [])
            if u is not None and chave(ext) in nomes}


def zeladoria(rondas, ids, ano, mes):
    """A última ronda do mês com nível lido nas usinas dos ids (a mesma régua do Relatório Semanal e do Nexus)."""
    melhor = None
    for r in rondas:
        q = r["quando"]
        if r["usina_id"] not in ids or (q.year, q.month) != (ano, mes):
            continue
        if r["sujidade"] is None and r["vegetacao"] is None:
            continue
        if melhor is None or q > melhor["quando"]:
            melhor = r
    if melhor is None:
        return None

    def item(k):
        n = melhor[k]
        return {"nivel": n, "frase": REGUA[k][n]} if n else None
    return {"data": melhor["quando"].strftime("%d/%m"), "sujidade": item("sujidade"), "vegetacao": item("vegetacao")}


def _da_usina(nome, m):
    nomes = _nomes(nome)

    def f(r):
        u = str(r.get("usina") or "").strip()
        return (str(r.get("mes")) == m and str(r.get("cliente") or "") == CLIENTE
                and chave(ALIAS_FALHAS.get(u, u)) in nomes)
    return f


def contar(dados, nome, ano, mes):
    """Strings e trackers DISTINTOS da usina no mês, ou None quando a plataforma não a mede (sem cobertura e sem
    episódio). Chaves (fonte, plant_id, inversor, string) e (fonte, plant_id, tracker). Tracker só conta com a usina
    comunicando: dias_comunicou == 0 sai; vazio (coluna ainda não publicada) conta."""
    da = _da_usina(nome, f"{ano}-{mes:02d}")
    s = {(r.get("fonte"), str(r.get("plant_id")), chave(r.get("inversor")), str(r.get("string")))
         for r in dados["strings_episodios"] if da(r)}
    t = {(r.get("fonte"), str(r.get("plant_id")), str(r.get("tracker")))
         for r in dados["trackers_episodios"] if da(r) and _int(r.get("dias_comunicou")) != 0}
    cob = [c for c in dados["cobertura"] if da(c)]
    med_s = bool(s) or any((_int(c.get("dias_strings")) or 0) > 0 for c in cob)
    med_t = bool(t) or any((_int(c.get("dias_trackers")) or 0) > 0 for c in cob)
    return {"strings": len(s) if med_s else None, "trackers": len(t) if med_t else None}


def conferir(dados):
    """A leitura bate com a aba `atualizacao`? O sync troca linhas no lugar: lida no meio dele, um episódio pode vir
    duas vezes ou faltar. Diferença = ler de novo — nunca deduplicar (duas linhas iguais podem ser dois trackers de
    cadastros diferentes: Assis, out/2026)."""
    for a in dados["atualizacao"]:
        m = str(a.get("mes"))
        for aba in ("strings_episodios", "trackers_episodios", "cobertura"):
            esperado = _int(a.get(aba))
            if esperado is None:
                continue                      # coluna que ainda não existia quando o mês foi publicado
            if sum(1 for r in dados[aba] if str(r.get("mes")) == m) != esperado:
                return False
    return True


def _mes_info(dados, ano, mes, hoje):
    a = next((x for x in dados["atualizacao"] if str(x.get("mes")) == f"{ano}-{mes:02d}"), None)
    if not a:
        return None, None
    fim = str(a.get("periodo_fim") or "")[:10]
    parcial = f"{fim[8:10]}/{fim[5:7]}" if (hoje.year, hoje.month) == (ano, mes) and len(fim) == 10 else None
    return parcial, a.get("atualizado_em")


def resposta(dados, nome, ano, mes, hoje):
    """A resposta da rota /api/t/operacao — sempre com as chaves de CHAVES, nem uma a mais."""
    r = dict.fromkeys(CHAVES)
    r.update(usina=nome, ano=ano, mes=mes, disponivel=False,
             regua={k: {str(n): f for n, f in v.items()} for k, v in REGUA.items()})
    if (ano, mes) < DESDE:
        r["motivo"] = "antes de 10/2026"
        return r
    if dados is None:
        r["motivo"] = "carregando"
        return r
    m = f"{ano}-{mes:02d}"
    if any(x.get("plant_id") in (None, "") for aba in ("strings_episodios", "trackers_episodios")
           for x in dados[aba] if str(x.get("mes")) == m):
        r["motivo"] = "aguardando a plataforma publicar o plant_id"
        return r
    r.update(contar(dados, nome, ano, mes))
    rondas = rondas_com_os(dados["rondas_com_os"]) + rondas_sem_os(dados["rondas_sem_os"])
    r["zeladoria"] = zeladoria(rondas, ids_da_usina(dados["de_para"], nome), ano, mes)
    r["parcial_ate"], r["atualizado_em"] = _mes_info(dados, ano, mes, hoje)
    r["disponivel"] = True
    return r
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest -q tests/test_thopen_operacao_mes.py`
Expected: PASS (todos).

- [ ] **Step 5: Conferir o diff.**

---

### Task 5: 5080 — leitura própria com cache e recarga em segundo plano (`thopen/fonte_operacao.py`)

**Files:**
- Create: `thopen/fonte_operacao.py`
- Test (novo): `tests/test_thopen_fonte_operacao.py`

**Interfaces:**
- Consumes: `fonte_api._get(caminho, tok)`, `fonte_api._token()`; `operacao_mes.ler_respostas`, `operacao_mes.conferir`.
- Produces: `baixar(tok, get) -> dados`, `dados(agora=None, iniciar=None) -> dados | None` (nunca espera a rede), `estado() -> dict`.

- [ ] **Step 1: Escrever os testes que falham**

```python
# -*- coding: utf-8 -*-
"""Leitura da Operação no Mês (Dashboard Thopen, 08/10/2026): a requisição do cliente nunca espera a rede (a recarga
do BD_Thopen já segura o 1º acesso por ~130 s), só a lista branca entra na memória e leitura que não bate com a aba
`atualizacao` não substitui a última boa."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import fonte_operacao as fo  # noqa: E402

SHEETS = [
    {"id": 1, "workbook_key": "falhas_performance", "sheet_name": "strings_episodios", "row_count": 1},
    {"id": 2, "workbook_key": "falhas_performance", "sheet_name": "trackers_episodios", "row_count": 0},
    {"id": 4, "workbook_key": "falhas_performance", "sheet_name": "atualizacao", "row_count": 1},
    {"id": 5, "workbook_key": "campo_nexus", "sheet_name": "rondas", "row_count": 1},
    {"id": 7, "workbook_key": "cadastro_nexus", "sheet_name": "de_para", "row_count": 2},
]
ROWS = {
    1: [{"headers": ["mes", "usina", "string", "plant_id", "avisos"], "values": ["2026-10", "Altair", "Ipv1", "1", "x"]}],
    4: [{"headers": ["mes", "strings_episodios", "trackers_episodios"], "values": ["2026-10", 1, 0]}],
    5: [{"headers": ["usina_id", "dia", "hora_inicio", "hora_fim", "respostas", "tecnico_cifrado", "pendencias_e_achados"],
         "values": [1, "2026-10-02", "13:00", "13:40", "Sujidade dos módulos: 2; Altura da vegetação: 3", "cf1:x", "texto"]}],
    7: [{"headers": ["usina_id", "sistema", "chave_externa"], "values": [1, "BD_Thopen · Dados Gerais Usinas", "Altair"]},
        {"headers": ["usina_id", "sistema", "chave_externa"], "values": [1, "Fracttal · Classificação 1", "x"]}],
}


def get_falso(caminho, tok):
    if caminho == "/api/sheets":
        return SHEETS
    sid = int(caminho.split("/")[3])
    return {"rows": ROWS.get(sid, [])}


def test_lista_branca_o_texto_da_ronda_e_o_tecnico_nao_entram():
    d = fo.baixar("", get_falso)
    (r,) = d["rondas_com_os"]
    assert r == {"usina_id": 1, "dia": "2026-10-02", "hora_inicio": "13:00", "hora_fim": "13:40",
                 "sujidade": 2, "vegetacao": 3}
    assert "avisos" not in d["strings_episodios"][0]
    assert d["de_para"] == [{"usina_id": 1, "chave_externa": "Altair"}]
    assert d["cobertura"] == []                          # aba ainda não publicada: vazio, não erro


def test_requisicao_nunca_espera_a_rede(monkeypatch, tmp_path):
    monkeypatch.setattr(fo, "CACHE", str(tmp_path / "c.json.gz"))
    monkeypatch.setattr(fo, "_estado", {"dados": None, "ts": 0.0, "erro": None, "carregando": False, "proxima": 0.0,
                                        "disco_lido": False})
    disparos = []
    assert fo.dados(agora=1000.0, iniciar=disparos.append) is None          # nada ainda: dispara e volta na hora
    assert fo.dados(agora=1001.0, iniciar=disparos.append) is None          # já carregando: não dispara de novo
    assert len(disparos) == 1


def test_recarga_boa_vai_para_a_memoria_e_o_disco(monkeypatch, tmp_path):
    monkeypatch.setattr(fo, "CACHE", str(tmp_path / "c.json.gz"))
    monkeypatch.setattr(fo, "_estado", {"dados": None, "ts": 0.0, "erro": None, "carregando": True, "proxima": 0.0,
                                        "disco_lido": True})
    fo._recarrega(get=get_falso, espera=0)
    assert fo._estado["dados"]["strings_episodios"][0]["plant_id"] == "1"
    monkeypatch.setattr(fo, "_estado", {"dados": None, "ts": 0.0, "erro": None, "carregando": False, "proxima": 0.0,
                                        "disco_lido": False})
    assert fo.dados(agora=fo.time.time(), iniciar=lambda f: None)["strings_episodios"]   # sobe pelo disco


def test_leitura_que_nao_bate_com_a_atualizacao_nao_substitui_a_boa(monkeypatch, tmp_path):
    monkeypatch.setattr(fo, "CACHE", str(tmp_path / "c.json.gz"))
    boa = {"strings_episodios": ["boa"]}
    monkeypatch.setattr(fo, "_estado", {"dados": boa, "ts": 1.0, "erro": None, "carregando": True, "proxima": 0.0,
                                        "disco_lido": True})
    ruim = dict(ROWS)
    ruim[4] = [{"headers": ["mes", "strings_episodios", "trackers_episodios"], "values": ["2026-10", 5, 0]}]

    def get_ruim(caminho, tok):
        return SHEETS if caminho == "/api/sheets" else {"rows": ruim.get(int(caminho.split("/")[3]), [])}
    fo._recarrega(get=get_ruim, espera=0)
    assert fo._estado["dados"] is boa and "atualizacao" in fo._estado["erro"]
    assert fo._estado["carregando"] is False and fo._estado["proxima"] > 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_thopen_fonte_operacao.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'fonte_operacao'`.

- [ ] **Step 3: Implementar `thopen/fonte_operacao.py`**

```python
# -*- coding: utf-8 -*-
"""Leitura da Operação no Mês (Dashboard Thopen, 08/10/2026): falhas, rondas e de-para, pela mesma API do BD_Thopen.

Por que um leitor à parte, e não dentro do `fonte_api.workbook()`:
- a recarga do BD_Thopen segura o 1º acesso do cliente depois do TTL por ~130 s (medido em 08/10), DENTRO da
  requisição e sob o `_lock` do `_wb()`. Aqui a requisição NUNCA espera a rede: serve o que tem e recarrega em
  segundo plano (e a 1ª carga depois do boot vem do disco);
- abas de outro workbook no do BD_Thopen poderiam confundir o `_indexa`, que acha aba por assinatura de colunas.
LISTA BRANCA: das rondas só ficam usina_id, dia, horas e os níveis — o texto das respostas, o técnico e as pendências
não entram na memória nem no disco (o 5080 é público, sem senha).
"""
import gzip
import json
import os
import threading
import time

import fonte_api
import operacao_mes

TTL = int(os.environ.get("THOPEN_OPERACAO_TTL", "600"))      # s — o mesmo ritmo do BD_Thopen
COOLDOWN = 60                                                 # s sem tentar de novo depois de uma falha
CACHE = os.environ.get("THOPEN_OPERACAO_CACHE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cache_operacao.json.gz")
SISTEMA_5080 = "BD_Thopen · Dados Gerais Usinas"
# (workbook, aba) → (chave em `dados`, campos que ficam)
ABAS = {
    ("falhas_performance", "strings_episodios"): ("strings_episodios",
                                                  ("mes", "fonte", "cliente", "usina", "inversor", "string", "plant_id")),
    ("falhas_performance", "trackers_episodios"): ("trackers_episodios",
                                                   ("mes", "fonte", "cliente", "usina", "tracker", "plant_id",
                                                    "dias_comunicou")),
    ("falhas_performance", "cobertura"): ("cobertura",
                                          ("mes", "fonte", "cliente", "usina", "plant_id", "dias_strings",
                                           "dias_trackers")),
    ("falhas_performance", "atualizacao"): ("atualizacao",
                                            ("mes", "periodo_fim", "atualizado_em", "strings_episodios",
                                             "trackers_episodios", "cobertura")),
    ("campo_nexus", "rondas"): ("rondas_com_os", ("usina_id", "dia", "hora_inicio", "hora_fim", "respostas")),
    ("nexus_rondas_checklist", "fato_checklist_ronda"): ("rondas_sem_os", ("usina_id", "inicio", "sujidade",
                                                                            "vegetacao")),
    ("cadastro_nexus", "de_para"): ("de_para", ("usina_id", "sistema", "chave_externa")),
}
_lock = threading.Lock()
_estado = {"dados": None, "ts": 0.0, "erro": None, "carregando": False, "proxima": 0.0, "disco_lido": False}


def _linhas(sid, get, tok):
    out, off = [], 0
    while True:
        rows = (get("/api/sheets/%d/rows?offset=%d&limit=1000" % (sid, off), tok) or {}).get("rows") or []
        out.extend(rows)
        if len(rows) < 1000:
            return out
        off += 1000


def baixar(tok="", get=None):
    """Uma leitura completa → dados, com a lista branca aplicada. Levanta se a API falhar."""
    get = get or fonte_api._get
    sheets = {(s["workbook_key"], s["sheet_name"]): s for s in get("/api/sheets", tok)}
    dados = {k: [] for k, _ in ABAS.values()}
    for (wb, aba), (k, campos) in ABAS.items():
        s = sheets.get((wb, aba))
        if not s:
            continue                          # aba ainda não publicada (a cobertura antes do deploy da plataforma)
        for r in _linhas(s["id"], get, tok):
            linha = dict(zip(r.get("headers") or [], r.get("values") or []))
            item = {c: linha.get(c) for c in campos}
            if k == "rondas_com_os":
                item.update(operacao_mes.ler_respostas(item.pop("respostas")))      # o texto não fica
            elif k == "de_para":
                if item.pop("sistema") != SISTEMA_5080:
                    continue
            if item.get("plant_id") not in (None, ""):
                item["plant_id"] = str(item["plant_id"])
            dados[k].append(item)
    return dados


def _grava_cache(dados, ts):
    try:
        tmp = CACHE + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump({"ts": ts, "dados": dados}, f, default=str)
        os.replace(tmp, CACHE)                            # troca atômica: nunca um cache pela metade
    except OSError as e:
        print("[operacao] não gravei o cache (%s)" % e, flush=True)


def _le_cache():
    try:
        with gzip.open(CACHE, "rt", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d.get("dados"), dict) else None
    except (OSError, ValueError, EOFError):
        return None


def _recarrega(get=None, espera=5.0):
    """Roda em segundo plano. Duas tentativas: a leitura tem de bater com a aba `atualizacao`."""
    try:
        tok = fonte_api._token()
        for tentativa in (1, 2):
            dados = baixar(tok, get)
            if operacao_mes.conferir(dados):
                agora = time.time()
                with _lock:
                    _estado.update(dados=dados, ts=agora, erro=None)
                _grava_cache(dados, agora)
                return
            if tentativa == 1:
                time.sleep(espera)
        raise RuntimeError("a leitura não bateu com a aba atualizacao duas vezes (sync em andamento?)")
    except Exception as e:                                # noqa: BLE001 — fica a última leitura boa
        with _lock:
            _estado.update(erro="%s: %s" % (type(e).__name__, e), proxima=time.time() + COOLDOWN)
        print("[operacao] recarga falhou: %s" % _estado["erro"], flush=True)
    finally:
        with _lock:
            _estado["carregando"] = False


def _em_fundo(f):
    threading.Thread(target=f, name="thopen-operacao", daemon=True).start()


def dados(agora=None, iniciar=None):
    """O que houver agora — nunca espera a rede. Vencido ou vazio: dispara a recarga em segundo plano (uma só)."""
    agora = time.time() if agora is None else agora
    with _lock:
        if _estado["dados"] is None and not _estado["disco_lido"]:
            _estado["disco_lido"] = True
            d = _le_cache()
            if d:
                _estado.update(dados=d["dados"], ts=d.get("ts") or 0.0)
        disparar = (agora - _estado["ts"] >= TTL and not _estado["carregando"] and agora >= _estado["proxima"])
        if disparar:
            _estado["carregando"] = True
        atual = _estado["dados"]
    if disparar:
        (iniciar or _em_fundo)(_recarrega)
    return atual


def estado():
    return {"carregado_em": _estado["ts"], "erro": _estado["erro"], "carregando": _estado["carregando"],
            "ttl": TTL, "cache": CACHE if os.path.exists(CACHE) else None}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest -q tests/test_thopen_fonte_operacao.py tests/test_thopen_operacao_mes.py`
Expected: PASS.

- [ ] **Step 5: Conferir o diff.** Acrescentar `thopen/cache_operacao.json.gz` ao `.gitignore` (ao lado do `cache_bd_thopen.json.gz`, se ele estiver lá; conferir com `git check-ignore -v thopen/cache_bd_thopen.json.gz`).

---

### Task 6: 5080 — rota `/api/t/operacao` (`dashboard_thopen.py`)

**Files:**
- Modify: `thopen/dashboard_thopen.py` (imports ~l.44; rota nova antes de `@app.route("/api/t/versao")` ~l.1201)
- Test (novo): `tests/test_thopen_operacao_rota.py`

**Interfaces:**
- Consumes: `fonte_operacao.dados()`, `operacao_mes.resposta(dados, nome, ano, mes, hoje)`, `operacao_mes.CHAVES`.
- Produces: `GET /api/t/operacao?usina=&ano=&mes=` → JSON com as chaves de `CHAVES`; 400 com `{"erro"}` se parâmetro inválido.

- [ ] **Step 1: Escrever os testes que falham**

```python
# -*- coding: utf-8 -*-
"""Rota da Operação no Mês (Dashboard Thopen, 08/10/2026): só agregados, parâmetro validado, chave que desliga, e o
import do dashboard continua sem rede e sem thread (a plataforma importa este módulo a cada deploy do servidor)."""
import os
import subprocess
import sys

import pytest

AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, "..", "thopen"))
import dashboard_thopen as dth  # noqa: E402
import fonte_operacao  # noqa: E402
import operacao_mes  # noqa: E402

D = {"strings_episodios": [{"mes": "2026-10", "fonte": "Thopen · API PV", "cliente": "Thopen", "usina": "Altair",
                            "inversor": "Inversor 1.1", "string": "Ipv1", "plant_id": "1"}],
     "trackers_episodios": [], "cobertura": [], "atualizacao": [], "rondas_com_os": [], "rondas_sem_os": [],
     "de_para": []}


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(fonte_operacao, "dados", lambda *a, **k: D)
    monkeypatch.delenv("THOPEN_OPERACAO", raising=False)
    return dth.app.test_client()


def test_responde_so_as_chaves_da_lista_branca(cli):
    r = cli.get("/api/t/operacao?usina=Altair&ano=2026&mes=10")
    assert r.status_code == 200
    assert tuple(r.get_json()) == tuple(sorted(operacao_mes.CHAVES)) or set(r.get_json()) == set(operacao_mes.CHAVES)
    assert r.get_json()["strings"] == 1


@pytest.mark.parametrize("q", ["usina=Altair&ano=2026&mes=abc", "usina=Altair&ano=2026&mes=13", "ano=2026&mes=10",
                               "usina=Altair&ano=x&mes=10"])
def test_parametro_invalido_e_400_e_nao_500(cli, q):
    r = cli.get("/api/t/operacao?" + q)
    assert r.status_code == 400 and r.get_json()["erro"]


def test_chave_desliga(cli, monkeypatch):
    monkeypatch.setenv("THOPEN_OPERACAO", "0")
    r = cli.get("/api/t/operacao?usina=Altair&ano=2026&mes=10").get_json()
    assert r["disponivel"] is False and r["motivo"] == "desligado"


def test_import_do_dashboard_nao_abre_rede_nem_thread():
    codigo = ("import socket, sys, threading; "
              "socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('rede no import')); "
              "sys.path.insert(0, %r); import dashboard_thopen; "
              "assert not [t for t in threading.enumerate() if t.name == 'thopen-operacao']" % os.path.join(AQUI, "..", "thopen"))
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
```

(Observação para o executor: o Flask devolve o JSON com as chaves ordenadas; por isso o teste aceita a mesma lista em qualquer ordem — o que importa é o CONJUNTO ser exatamente `CHAVES`.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_thopen_operacao_rota.py`
Expected: FAIL — 404 na rota.

- [ ] **Step 3: Implementar em `thopen/dashboard_thopen.py`**

Imports (logo abaixo de `import fonte_api`):

```python
import fonte_operacao        # Operação no Mês (08/10/2026): leitura própria, recarga em segundo plano
import operacao_mes          # ... e as contas puras do card do Diário
```

Rota (antes de `@app.route("/api/t/versao")`):

```python
@app.route("/api/t/operacao")
def api_operacao():
    """Operação no Mês do card do Diário (Levi, 08/10/2026): strings com saída, trackers parados com a usina
    comunicando e a zeladoria da última ronda. Só agregados; a requisição nunca espera a rede (fonte_operacao)."""
    usina = (request.args.get("usina") or "").strip()
    try:
        ano, mes = int(request.args.get("ano", "")), int(request.args.get("mes", ""))
    except ValueError:
        return jsonify({"erro": "ano e mes precisam ser números"}), 400
    if not usina or not 1 <= mes <= 12 or not 2020 <= ano <= 2100:
        return jsonify({"erro": "usina, ano (2020 a 2100) e mes (1 a 12) são obrigatórios"}), 400
    hoje = dt.date.today()
    if os.environ.get("THOPEN_OPERACAO", "1").strip() == "0":
        r = operacao_mes.resposta(None, usina, ano, mes, hoje)
        r["motivo"] = "desligado"
        return jsonify(r)
    return jsonify(operacao_mes.resposta(fonte_operacao.dados(), usina, ano, mes, hoje))
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest -q tests/test_thopen_operacao_rota.py tests/test_thopen_meta_fontes.py tests/test_thopen_corte_historico.py`
Expected: PASS.

- [ ] **Step 5: Conferir o diff.**

---

### Task 7: 5080 — o card na aba Diário (`dashboard_thopen.html`)

**Files:**
- Modify: `thopen/templates/dashboard_thopen.html` (CSS antes de `</style>`; card depois do card "Disponibilidade Usina (%)" ~l.178-180; `loadUsina` ~l.377; `renderDiario` ~l.490-528)
- Test (novo): `tests/test_thopen_operacao_tela.py`

**Interfaces:**
- Consumes: `GET /api/t/operacao` (Task 6): `disponivel, motivo, strings, trackers, zeladoria{data, sujidade{nivel,frase}, vegetacao{nivel,frase}}, regua, parcial_ate`.

- [ ] **Step 1: Escrever os testes que falham**

```python
# -*- coding: utf-8 -*-
"""O card Operação no Mês na tela do 5080 (mockup aprovado pelo Levi em 08/10/2026)."""
import os
import re

T = open(os.path.join(os.path.dirname(__file__), "..", "thopen", "templates", "dashboard_thopen.html"),
         encoding="utf-8").read()


def test_card_fica_na_coluna_da_direita_logo_abaixo_da_disponibilidade():
    i_disp, i_card, i_grid2 = T.index('id="disp"'), T.index('id="opCard"'), T.index('<div class="grid2">')
    assert i_disp < i_card < i_grid2


def test_so_a_partir_de_outubro_e_pela_rota_nova():
    assert "202610" in T and "/api/t/operacao?" in T


def test_frases_da_regua_nao_sao_repetidas_na_tela():
    # moram só no operacao_mes.REGUA (a rota manda): duas cópias divergem
    assert "Vidro limpo" not in T and "Mato na altura" not in T


def test_pdf_espera_o_diario_inteiro():
    # o PDF Carteira fotografa logo depois do loadUsina: o card tem de estar pronto
    assert re.search(r"await renderDiario\(", T)


def test_sem_emoji_no_card():
    card = T[T.index('id="opCard"'):T.index('<div class="grid2">')]
    assert not re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", card)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest -q tests/test_thopen_operacao_tela.py`
Expected: FAIL — `ValueError: substring not found` (`opCard`).

- [ ] **Step 3: Implementar no template**

CSS (antes de `</style>`):

```css
  /* Operação no Mês (Levi, 08/10/2026): strings, trackers e zeladoria; só de 10/2026 em diante */
  .op-card .kpi-row .kpi-big{ font-size:26px; }
  .op-zt{ margin-top:9px; padding-top:8px; border-top:1px solid #eef0f3; text-align:center; font-size:10px;
          color:var(--muted); letter-spacing:1px; text-transform:uppercase; }
  #opZel{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-top:7px; }
  .op-z{ display:flex; flex-direction:column; align-items:center; text-align:center; }
  .zpill{ display:flex; align-items:center; justify-content:center; width:40px; height:38px; border-radius:6px;
          margin-bottom:5px; font-size:22px; font-weight:800; }
  /* régua de 5 níveis (cartão de referência das rondas): 1 limpo … 5 crítico */
  .zpill.z1{ background:#3a8f5c; color:#fff; } .zpill.z2{ background:#8cc63f; color:#1d2b12; }
  .zpill.z3{ background:#e8c547; color:#2b2410; } .zpill.z4{ background:#e8833a; color:#2b1a0e; }
  .zpill.z5{ background:#c8432f; color:#fff; } .zpill.zna{ background:#eef0f3; color:#9aa0a6; font-size:16px; }
  .op-z .zl{ font-size:9.5px; color:var(--muted); letter-spacing:.8px; text-transform:uppercase; }
  .op-z .zd{ font-size:12px; color:#22242a; line-height:1.35; margin-top:1px; }
  .op-z .zd.na{ color:var(--muted); font-style:italic; }
  .op-nota{ margin-top:9px; font-size:10px; color:var(--muted); text-align:center; line-height:1.4; }
```

Card (logo depois do `</div>` que fecha o card "Disponibilidade Usina (%)", dentro de `.col`):

```html
        <div class="card op-card hidden" id="opCard"><h3>Operação no Mês</h3>
          <div class="kpi-row">
            <div><div class="kpi-big" id="opStr">—</div><div class="kpi-lbl">Strings com saída</div></div>
            <div><div class="kpi-big" id="opTrk">—</div><div class="kpi-lbl">Trackers parados</div></div>
          </div>
          <div class="op-zt" id="opZt">Zeladoria</div>
          <div id="opZel"></div>
          <div class="op-nota" id="opNota"></div>
        </div>
```

JS — função nova (antes de `// ---------- página diária ----------`):

```js
// ---------- Operação no Mês (Levi, 08/10/2026) — só de 10/2026 em diante ----------
let _opSeq=0;
async function renderOperacao(usina, ano, mes){
  const seq=++_opSeq, card=$('opCard');
  if(ano*100+mes<202610){ card.classList.add('hidden'); return; }
  let d=null;
  try{ d=await get(`/api/t/operacao?usina=${encodeURIComponent(usina)}&ano=${ano}&mes=${mes}`); }catch(e){ d=null; }
  if(seq!==_opSeq) return;                 // trocou de usina ou de mês no meio: esta resposta não vale mais
  if(!d || d.motivo==='antes de 10/2026' || d.motivo==='desligado'){ card.classList.add('hidden'); return; }
  card.classList.remove('hidden');
  const num=v=>v==null?'—':nf0.format(v), ok=d.disponivel;
  $('opStr').textContent=ok?num(d.strings):'—';
  $('opTrk').textContent=ok?num(d.trackers):'—';
  const z=ok?d.zeladoria:null;
  $('opZt').textContent=z?`Zeladoria · ronda de ${z.data}`:'Zeladoria';
  const escala=k=>Object.entries((d.regua||{})[k]||{}).sort((a,b)=>b[0]-a[0]).map(([n,f])=>`${n} = ${f}`).join('\n');
  const item=(k,rot)=>{ const it=z&&z[k];
    return `<div class="op-z" title="${escala(k)}"><span class="zpill ${it?'z'+it.nivel:'zna'}">${it?it.nivel:'—'}</span>`
      +`<div class="zl">${rot}</div><div class="zd ${it?'':'na'}">${it?it.frase:'sem leitura no mês'}</div></div>`; };
  $('opZel').innerHTML=item('sujidade','Sujidade dos módulos')+item('vegetacao','Altura da vegetação');
  $('opNota').innerHTML=(ok?(d.parcial_ate?`Mês em andamento, até ${d.parcial_ate}. `:''):'Atualizando os dados de operação. ')
    +'Zeladoria: última ronda do mês, de 1 (limpo) a 5 (crítico).<br>'
    +'Strings: 2 h seguidas sem corrente com o inversor gerando · trackers: com a usina comunicando';
  if(!ok && d.motivo==='carregando') setTimeout(()=>{ if(seq===_opSeq) renderOperacao(usina,ano,mes); },5000);
  void document.body.offsetWidth;          // reflow antes de medir: o card muda a altura da coluna
  const c=$('chDiario'); if(c&&c.data&&c.data.length) Plotly.Plots.resize(c);
}
```

Em `renderDiario(ano,mes)`: primeira linha depois de `const usina=$('selUsina').value;`:

```js
  const opP=renderOperacao(usina, ano, mes);   // em paralelo com o diário; o PDF espera os dois
```

e última linha da função (depois do bloco de comentários): `await opP;`

Em `loadUsina`: trocar `renderMensal(+m); renderAnual(+m); renderDiario(+a,+m);` por `renderMensal(+m); renderAnual(+m); await renderDiario(+a,+m);`.

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest -q tests/test_thopen_operacao_tela.py`
Expected: PASS.

- [ ] **Step 5: Conferir o diff.**

---

### Task 8: Prova com dado real (antes de qualquer push)

**Files:** só scratchpad (nada no repo).

- [ ] **Step 1: Suíte inteira** — `python -m pytest -q -p no:cacheprovider`; comparar com a linha de base da Task 0 (as mesmas falhas pré-existentes, nenhuma nova).
- [ ] **Step 2: Plataforma com o dado do PC** — numa CÓPIA dos arquivos de estado (`falhas_strings.json`, `trk_eventos.json`, `perdas_strings.json`, `paradas_book.json` copiados para o scratchpad; nunca gravar no estado real), montar outubro com o `falhas_job.montar` do worktree e conferir: Brodowski 297381 com `dias_comunicou` > 0 nos dias em que a 297378 leu strings; `cobertura` com Altair, Brodowski e Guaratinguetá V; `tabelas()` com as colunas novas no fim. Registrar os números.
- [ ] **Step 3: 5080 de teste na porta 5081 a partir do worktree** (sem tocar no 5080 do cliente):
  `python -c "import sys; sys.path.insert(0, r'C:\GridcoAuto\wt\thopen-operacao\thopen'); import dashboard_thopen as d; d.app.run(host='127.0.0.1', port=5081, threaded=True)"` (em segundo plano). Fotografar as respostas das rotas EXISTENTES no 5080 do cliente (código igual ao da main) e na 5081 com o `_snap_dash.py` (copiar do scratchpad antigo `7c3991ac-.../scratchpad/` para o scratchpad atual) e comparar com `_diff_snap.py`: **0 diferenças**.
- [ ] **Step 4: Rota nova na 5081 com o dado real da API** — antes do deploy da plataforma, a resposta de outubro deve ser `disponivel: false, motivo: "aguardando a plataforma publicar o plant_id"` (prova a barreira). Para ver os números, gerar um `dados` local a partir do pacote do Step 2 (`tabelas()` → linhas como dicts) + rondas reais e chamar `operacao_mes.resposta` para Altair, Guaratinguetá V e Brodowski. Comparar com o mockup (Altair 41/75, GV 43/3 com zeladoria 2/3 em 02/10).
- [ ] **Step 5: Tela e PDF** — com a 5081 servindo `dados` de teste (monkeypatch por variável de ambiente NÃO existe: usar um script que importa o módulo, injeta `fonte_operacao._estado["dados"]` com o `dados` do Step 4 e sobe o app), abrir a aba Diário de 10/2026 no navegador (Edge headless para print + `--print-to-pdf`) e conferir: card igual ao mockup, gráfico sem espaço vazio, Diário cabendo na página 2 do A4 (Ctrl+P) e no PDF Carteira. Mês 09/2026: Diário igual ao de hoje.
- [ ] **Step 6: Mostrar ao Levi** os prints e os números (regra "mostrar antes de seguir") e esperar o OK.

---

### Task 9: Documentação (regra do Levi de 03/10: um .md por área, corrigido e não empilhado)

**Files:**
- Modify: `thopen/CLAUDE.md` — corrigir o que está errado (~1.213 linhas; sem fallback para xlsx, só o cache em disco; a plataforma usa 7 atributos; o cliente roda no clone `C:\GridcoAuto\PerformancePainel` pelo `servir_thopen.py` + túnel, o Railway está fora do ar; a recarga leva ~130 s no 1º acesso) e acrescentar a seção "Operação no Mês (08/10/2026)": fontes, regras, estados, chave `THOPEN_OPERACAO`, cache `cache_operacao.json.gz`, como provar.
- Modify: `plataforma/CLAUDE.md` — seção Falhas: as colunas novas, a aba `cobertura`, `dias_comunicou` e quem consome (o 5080). Conferir no `git diff` que só a seção Falhas mudou (o working tree principal tem outra edição sem commit no mesmo arquivo; a mesclagem é no fim).
- Modify: `CLAUDE.md` da raiz — "Acoplamento": 7 atributos; o `Iniciar Dashboards.bat` não sobe a plataforma (corrigir a frase).

- [ ] **Step 1:** Escrever as três mudanças.
- [ ] **Step 2:** `git diff --stat` — só os arquivos desta mudança.

---

### Task 10: Entrega (só com o OK do Levi)

- [ ] **Step 1:** Pedir o OK para o commit (branch `feat/thopen-operacao-no-mes`) e o do Nexus (catálogo).
- [ ] **Step 2:** Antes do push: trazer para a `main` sem misturar com o trabalho sem commit das outras sessões (`sessoes-paralelas-mesmo-working-tree`): se elas já commitaram, `git rebase main`; senão, `git push origin feat/thopen-operacao-no-mes:main` só depois de conferir que `main` = `origin/main` e que o worktree principal não tem mudança nos MESMOS trechos (conflito → resolver na branch, nunca no working tree delas). Rodar a suíte inteira de novo.
- [ ] **Step 3:** Push = deploy do servidor. Conferir `/versao` com o commit, esperar o worker publicar o workbook (até 1 h + o ciclo) e conferir na API: `trackers_episodios` com `plant_id`/`dias_comunicou`, aba `cobertura`, contagens batendo com a `atualizacao`.
- [ ] **Step 4:** Para o cliente: só depois da correção das Ipv29–32 no ar (sessão paralela) e do OK do Levi — `git pull` no clone `C:\GridcoAuto\PerformancePainel`, reiniciar SÓ o `pythonw servir_thopen.py` (filtro pelo caminho do script, nunca por nome; não tocar no `cloudflared`), conferir `/api/t/fonte`, `/api/t/operacao` de Altair e Guaratinguetá V e o print do Diário.
- [ ] **Step 5:** Bloco final ao Levi: o que foi feito · motivo · resolvido (sim/parcial e o que falta, de quem depende).

---

## Rodada 2 (08/10, tarde) — feedback da Ana + decisões do Levi (ver o spec, "Revisão de 08/10, à tarde")

Estado ao começar: Tasks 1–7 feitas e revisadas no worktree (plataforma 115 testes, 5080 90, Nexus 14). A main já tem
a correção das Ipv29–32 (`0128411`, outra sessão); merge de 3 vias do falhas_job.py simulado: 0 conflitos.
**Nada é commitado** (o Levi está testando). Decisão do orquestrador: tracker em dia "sem prova" (`dias_sem_prova > 0`,
o dia corrente sem geração fechada) CONTA — não é falha de comunicação comprovada.

### Contrato novo no workbook `falhas_performance` (colunas/abas só no FIM; nada existente muda)

- Aba `strings_os` — 1 linha = 1 OS de recomposição de string do Fracttal com DATA DO EVENTO (`event_date`, dia de
  Brasília) no mês: `mes, data_evento, cliente, usina, plant_id, inversor, os, status, strings, qtd, origem`.
  `origem`: `texto` (linha "Strings sem corrente: N (Ipv3, ...)" das observações — contrato com o OS Creator),
  `citadas` (strings citadas no texto, `_falhas_os_citadas`), `estimado` (sem quantidade nem citação, OS com evento
  até 31/10/2026: as strings que a régua da plataforma viu sem corrente naquele inversor no dia do evento — decisão do
  Levi "adapte todas desse mês, do nosso lado, sem tocar no Fracttal"), `sem_quantidade` (depois de outubro, OS sem
  quantidade: `qtd` vazio, nunca 0). Ler o Fracttal SEM chamada nova se der (a varredura da disponibilidade já pagina
  todos os work_orders a cada 30 min); se precisar de chamada, respeitar `_frac_get_paciente` e a cota de 200/min da
  EMPRESA.
- Aba `trackers_dia` — 1 linha = usina-fonte-plant_id × dia com tracker parado: `mes, dia, fonte, cliente, usina,
  plant_id, trackers, qtd, comunicou` (`sim` = a usina comunicou; `sem prova` = dia corrente sem geração fechada).
  Tracker-dia em que a usina NÃO comunicou não entra.
- `atualizacao`: `cobertura` vira VAZIO (não 0) quando o pacote não tem a chave `cobertura` (review do Nexus); ganha
  `strings_os` e `trackers_dia` (contagens) no fim.

### 5080

- Card "Strings com saída" = strings das OS do mês (data do evento): distintas por `(usina, inversor, string)` quando a
  OS lista as strings; senão soma `qtd` (uma vez por OS). OS `sem_quantidade` não soma e vira aviso. Se alguma OS do
  mês for `estimado`, a resposta avisa ("parte estimada pela Grid").
- Card "Trackers parados" = distintos com `dias_comunicou > 0` OU `dias_sem_prova > 0` (lista branca do
  `fonte_operacao` ganha `dias_sem_prova`).
- `/api/t/operacao` ganha `por_dia: [{dia: "DD/MM", strings, trackers}]` (dias com OS de string pelo evento ou tracker
  parado com a usina comunicando) e `avisos: [texto]`; `CHAVES` atualizado.
- Tabela do Diário de 10/2026 em diante = UMA LINHA POR DIA: dias de `por_dia` ∪ dias com comentário (o comentário do
  dia vem do `pontos[].com` do `/api/t/diario`). Colunas Usina | Data | Comentário | Strings | Trackers. Comentário
  igual ao do dia anterior aparece só no 1º dia da sequência (nos seguintes, "continua", em cinza). Antes de 10/2026,
  a tabela fica como hoje. Conferir a impressão (Ctrl+P e PDF Carteira) com um mês cheio de linhas.
- Aba "Metodologia" (mockup v3 aprovado, texto da disponibilidade com "A CONFIRMAR"), FORA do PDF Carteira e do
  Ctrl+P; o texto de strings passa a dizer que vêm das OS do Fracttal (data do evento; quantidade pela linha
  "Strings sem corrente: N" ou pelas strings citadas; em outubro, as OS sem quantidade foram completadas pela Grid a
  partir do monitoramento).
- Conserto do instalador por zip (`thopen/deploy/_package_thopen.py`: ITENS com `fonte_operacao.py` e
  `operacao_mes.py`; "3 arquivos" → 5 no LEIAME, no `railway.toml` e no `render.yaml`; variáveis THOPEN_OPERACAO*).

### Nexus

- Correções da revisão: Brodowski "52 em vez de 103" (não 51); janela escrita como condição; observações curtas (a
  janela com datas fica só no CLAUDE.md); registrar `strings_os` (fato, 1 linha = 1 OS) e `trackers_dia` (1 linha =
  usina × dia) no catálogo.

## Rodada 3 (09/10) — texto por dia, título da Zeladoria, fotos das rondas e dúvida do cliente

Plano próprio: `docs/superpowers/plans/2026-10-09-thopen-rondas-fotos-duvida.md` (spec: seção "Rodada 3" do spec deste plano).
