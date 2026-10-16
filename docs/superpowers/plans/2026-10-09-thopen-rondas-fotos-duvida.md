# Rodada 3 do Dashboard Thopen — texto por dia, Zeladoria, fotos das rondas e dúvida do cliente

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** No card "Operação no Mês" do Diário (5080): a tabela de comentários em frases, o título "Zeladoria" como título, um ícone que abre as rondas do mês com as fotos (checklist sem nome) e um campo de dúvida do cliente que avisa a Grid Co. no Teams.

**Architecture:** O `fonte_operacao` passa a guardar, das rondas com OS, o número da OS, a unidade, o nº de fotos, os itens do checklist e só os ACHADOS (o texto livre é descartado na leitura). Um módulo puro (`rondas_cliente`) monta a lista do mês e o detalhe de uma ronda; um módulo de E/S (`fotos_ronda`) lê os anexos da OS no Fracttal e entrega fotos e miniaturas; outro (`duvida`) valida, limita e manda o cartão para o fluxo do Teams. Quatro rotas novas no `dashboard_thopen`; a tela ganha o ícone, a janela e o formulário.

**Tech Stack:** Python 3.14 (Flask, urllib, Pillow opcional), JS puro no template, pytest (+ node para as funções JS puras).

**Spec:** `docs/superpowers/specs/2026-10-08-thopen-operacao-no-mes-design.md`, seção "Rodada 3 (09/10/2026)".

## Global Constraints

- Worktree `C:\GridcoAuto\wt\thopen-operacao`. **Sem commit** ("não commita nada disso ainda, estou testando e validando", Levi 08/10): cada "Commit" vira conferir `git diff --stat`.
- Python: `"C:\Users\Levi Maia\AppData\Local\Python\pythoncore-3.14-64\python.exe"`; testes da raiz do worktree: `python -m pytest -q <arquivo>`.
- pt-BR em tudo; comentário explica o POR QUÊ com o caso real. Sem emoji na interface. Tema do 5080 (claro + navy `#1F2E6E`).
- Nada roda no import do `dashboard_thopen` (sem thread, sem rede): a plataforma importa 7 atributos dele.
- O 5080 é público: das rondas, NUNCA técnico, observação escrita, PENDÊNCIAS, qualidade, GPS; foto e dúvida só de OS de ronda de usina do de-para do 5080 e de 10/2026 em diante.
- Fracttal: 200 pedidos/min por EMPRESA, dividido com tudo — 1 pedido por OS aberta, guardado 20 min.
- Segredo (FRACTTAL_*, THOPEN_DUVIDA_TEAMS) nunca impresso, nunca no código.
- Nenhuma rota, chave de resposta ou formato existente do 5080 muda (o `/api/t/operacao` fica igual).

---

### Task 1: `fonte_api.segredo` + `rondas_cliente` (puro)

**Files:**
- Modify: `thopen/fonte_api.py` (função nova depois de `_token`)
- Create: `thopen/rondas_cliente.py`
- Test: `tests/test_thopen_rondas_cliente.py`

**Interfaces:**
- Produces: `fonte_api.segredo(nome) -> str`; `rondas_cliente.campos(respostas, pendencias, usina) -> {"itens": [[item, resposta]], "achados": {chave: valor}, "unidade": str}`; `rondas_cliente.do_mes(dados, nome, ano, mes) -> [cabecalho]`; `rondas_cliente.da_os(dados, os_) -> linha | None`; `rondas_cliente.cabecalho(linha) -> {"os","dia","inicio","fim","unidade"}`; `rondas_cliente.detalhe(linha, descricoes) -> {cabecalho..., "itens","pragas","ocorrencias","outras","fotos"}`.

- [ ] **Step 1: testes**

```python
# tests/test_thopen_rondas_cliente.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import fonte_api  # noqa: E402
import rondas_cliente as rc  # noqa: E402

RESP = ("Computador: Ligado; Sujidade da vala de drenagem: Parcial; Sujidade dos módulos: 2; Altura da vegetação: 3; "
        "As luvas isolantes estão disponíveis?: Sim")
PEND = ("PENDÊNCIAS — ronda longa pendente; levantamento por zonas pendente: sujidade | ACHADOS — trincado: 1 ponto; "
        "praga: Pontual; sombreamento: Pontual")


def test_campos_guarda_checklist_e_achados_e_descarta_texto_livre():
    c = rc.campos(RESP, PEND, "Thopen - Guaratingueta 5 - SP")
    assert c["itens"][0] == ["Computador", "Ligado"] and ["As luvas isolantes estão disponíveis?", "Sim"] in c["itens"]
    assert c["achados"] == {"trincado": "1 ponto", "praga": "Pontual", "sombreamento": "Pontual"}
    assert c["unidade"] == "Guaratingueta 5"
    # Caicó 02/10: o campo traz texto livre do técnico — não pode passar
    livre = rc.campos("", "Sujeira nos módulos, falta de água para banheiro", "Thopen - Caicó - RN")
    assert livre["achados"] == {} and "banheiro" not in str(livre)


def _dados(*linhas, ids=(86,)):
    return {"rondas_com_os": list(linhas), "de_para": [{"usina_id": i, "chave_externa": "Guaratinguetá V"} for i in ids]}


def _r(os_, dia="2026-10-02", hi="10:13", hf="11:07", n=19, uid=86):
    return {"os": str(os_), "usina_id": uid, "dia": dia, "hora_inicio": hi, "hora_fim": hf, "n_fotos": n,
            "unidade": "Guaratingueta 5", "itens": [["Sujidade dos módulos", "2"]], "achados": {}}


def test_do_mes_em_brasilia_e_uma_os_por_ronda():
    d = _dados(_r(15176, n=19), _r(15177, n=21), _r(15300, dia="2026-10-01", hi="02:30", hf="03:00"),
               _r(14000, dia="2026-09-30", hi="12:00"))
    out = rc.do_mes(d, "Guaratinguetá V", 2026, 10)
    # 02:30 UTC de 01/10 = 23:30 de 30/09 em Brasília: fica fora de outubro; a ronda em duas OS fica na de mais fotos
    assert [(x["os"], x["dia"], x["inicio"], x["fim"]) for x in out] == [("15177", "2026-10-02", "07:13", "08:07")]


def test_da_os_so_de_usina_do_5080_e_de_outubro_em_diante():
    d = _dados(_r(15176), _r(14000, dia="2026-09-20"), _r(15999, uid=999))
    assert rc.da_os(d, 15176)["os"] == "15176" and rc.da_os(d, "15176") is not None
    assert rc.da_os(d, 14000) is None          # setembro: antes do card
    assert rc.da_os(d, 15999) is None          # usina fora do de-para do 5080 (outro cliente)
    assert rc.da_os(d, 1) is None and rc.da_os(None, 15176) is None


def test_detalhe_casa_foto_com_item_e_esconde_descricao_solta():
    r = dict(_r(15176), itens=rc.campos(RESP, PEND, "x")["itens"], achados={"trincado": "1 ponto", "praga": "Pontual"})
    descs = ["Sujidade dos módulos — 2", "Ronda 2026-10-02 — Thopen - Guaratingueta 5 - SP · qualidade 95%",
             "Módulo trincado — tr 09 · antes", "Pragas — pontual", "Zona valetas critica", "Sujidade dos módulos — 2"]
    d = rc.detalhe(r, descs)
    suj = next(i for i in d["itens"] if i["item"] == "Sujidade dos módulos")
    assert suj["nivel"] == 2 and suj["frase"].startswith("Sujeira leve") and suj["fotos"] == [0, 5]
    assert next(i for i in d["itens"] if i["item"] == "Computador")["nivel"] is None
    assert [(p["item"], p["resposta"], p["fotos"]) for p in d["pragas"]] == [
        ("Pragas", "Pontual", [3]), ("Dejeto de pássaro nos módulos", "Nenhum", []),
        ("Sombreamento por vegetação", "Nenhum", [])]
    assert [(o["item"], o["resposta"], o["fotos"]) for o in d["ocorrencias"]] == [("Módulo trincado", "1 ponto", [2])]
    assert d["outras"] == [1, 4]
    # a capa leva a qualidade da ronda e a descrição solta pode ser texto do técnico: nenhuma das duas sai
    assert d["fotos"][1] == {"i": 1, "item": "Capa da ronda", "resposta": ""}
    assert d["fotos"][4] == {"i": 4, "item": "Foto da ronda", "resposta": ""}
    assert "qualidade" not in str(d) and "valetas" not in str(d)
    assert (d["os"], d["inicio"]) == ("15176", "07:13")


def test_segredo_ambiente_primeiro_depois_env_da_raiz(monkeypatch, tmp_path):
    monkeypatch.setattr(fonte_api, "_AQUI", str(tmp_path / "thopen"))
    (tmp_path / ".env").write_text('X_TESTE="do-arquivo"\nOUTRA=1\n', encoding="utf-8")
    monkeypatch.delenv("X_TESTE", raising=False)
    assert fonte_api.segredo("X_TESTE") == "do-arquivo" and fonte_api.segredo("NAO_TEM") == ""
    monkeypatch.setenv("X_TESTE", "do-ambiente")
    assert fonte_api.segredo("X_TESTE") == "do-ambiente"
```

- [ ] **Step 2: rodar e ver falhar** — `python -m pytest -q tests/test_thopen_rondas_cliente.py` → `ModuleNotFoundError: rondas_cliente`.

- [ ] **Step 3: `fonte_api.segredo`** (depois de `_token`)

```python
def segredo(nome):
    """Um segredo de configuração (FRACTTAL_CLIENT_ID, THOPEN_DUVIDA_TEAMS...): o ambiente do processo e, sem ele, o
    `.env` e o `tokens.txt` da raiz do repositório (linhas NOME=valor). O clone do cliente
    (C:\\GridcoAuto\\PerformancePainel) não tem .env: quem instala põe lá as linhas que o README do pacote lista.
    Vazio = não configurado. Nunca imprime o valor."""
    v = os.environ.get(nome)
    if v and v.strip():
        return v.strip()
    padrao = re.compile(r"\s*%s\s*=\s*(.*)$" % re.escape(nome))
    for arq in (".env", "tokens.txt"):
        try:
            for linha in io.open(os.path.join(_AQUI, "..", arq), encoding="utf-8", errors="surrogateescape"):
                m = padrao.match(linha)
                if m:
                    return m.group(1).strip().strip('"').strip("'")
        except OSError:
            continue
    return ""
```

- [ ] **Step 4: `thopen/rondas_cliente.py`**

```python
# -*- coding: utf-8 -*-
"""Rondas do mês para o cliente (Dashboard Thopen, rodada 3 — Levi, 09/10/2026: "um ícone de imagem ... carregando a
imagem das rondas em uma estrutura parecida com" o detalhe de ronda do painel do App).

O QUE VAI AO CLIENTE (Levi, 09/10: "Checklist + fotos, sem nome"): os itens do checklist com a resposta, os níveis de
sujidade e vegetação com a frase da régua, os ACHADOS estruturados do App (praga, dejeto, sombreamento, módulo
trincado), as fotos, o número da OS e o horário. NUNCA: o técnico; a observação escrita — o `pendencias_e_achados`
mistura os achados com texto livre ("Sujeira nos módulos, falta de água para banheiro, falta de um cadeado", Caicó
02/10); as PENDÊNCIAS (marcas internas: "ronda longa pendente"); a qualidade da ronda (nota interna do App, que também
vai na capa da foto); o GPS. Foto que não casa com item do checklist sai como "Foto da ronda": a descrição dela pode ser
texto do técnico ("Zona valetas critica"). O 5080 é público, sem senha. Nada aqui faz rede.
"""
import datetime as dt
import re

import operacao_mes as om

# chave do App → (seção da janela, nome na tela). Pragas, dejeto e sombreamento aparecem sempre ("Nenhum" quando o App
# não achou); trincado só quando achou — como no detalhe de ronda do painel do App
ACHADOS = (("praga", "pragas", "Pragas"), ("dejeto", "pragas", "Dejeto de pássaro nos módulos"),
           ("sombreamento", "pragas", "Sombreamento por vegetação"), ("trincado", "ocorrencias", "Módulo trincado"))
_ACHADOS_RE = re.compile(r"ACHADOS\s*\W+\s*([^|]+)")
_NIVEL = (("sujidade dos modulos", "sujidade"), ("altura da vegetacao", "vegetacao"))
VALOR_MAX = 40                    # o valor de um achado é curto ("Pontual", "1 ponto", "Até 5"); mais que isso é texto


def campos(respostas, pendencias, usina):
    """Da linha do `campo_nexus · rondas`, só o que pode ir ao cliente — roda na LEITURA (fonte_operacao), antes da
    memória e do disco: o texto livre nunca fica guardado."""
    itens = []
    for parte in str(respostas or "").split(";"):
        item, sep, resp = parte.rpartition(":")
        if sep and item.strip() and resp.strip():
            itens.append([item.strip(), resp.strip()])
    achados = {}
    m = _ACHADOS_RE.search(str(pendencias or ""))
    for parte in (m.group(1).split(";") if m else []):
        k, sep, v = parte.partition(":")
        k, v = om.chave(k), v.strip()
        if sep and v and len(v) <= VALOR_MAX and k in {a for a, _s, _n in ACHADOS}:
            achados[k] = v
    partes = [p.strip() for p in str(usina or "").split(" - ")]
    # "Thopen - Guaratingueta 5 - SP" → "Guaratingueta 5"; "Thopen - Itajá 1 e 2 - RN" → "Itajá 1 e 2"
    unidade = " - ".join(partes[1:-1]) if len(partes) >= 3 else partes[-1]
    return {"itens": itens, "achados": achados, "unidade": unidade}


def _quando(r, campo="hora_inicio"):
    """A hora do livro é UTC (conferido em 08/10: +180 min contra o App em 594 de 594 rondas) → Brasília."""
    try:
        utc = dt.datetime.strptime("%s %s" % (str(r.get("dia") or "")[:10], str(r.get(campo) or "")[:5]),
                                   "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return om._brt(utc)


def cabecalho(r):
    q, f = _quando(r), _quando(r, "hora_fim")
    return {"os": str(om._int(r.get("os"))), "dia": q.strftime("%Y-%m-%d"), "inicio": q.strftime("%H:%M"),
            "fim": f.strftime("%H:%M") if f else "", "unidade": r.get("unidade") or ""}


def do_mes(dados, nome, ano, mes):
    """As rondas com OS da usina do 5080 no mês (o dia em Brasília), da mais recente para a mais antiga. A mesma ronda
    vem em 2–3 OS (188 de 598 rondas em 09/10, cada OS com as suas fotos): fica a de mais fotos, e no empate a de menor
    número."""
    ids = om.ids_da_usina((dados or {}).get("de_para"), nome)
    grupos = {}
    for r in (dados or {}).get("rondas_com_os") or []:
        uid, q = om._int(r.get("usina_id")), _quando(r)
        if uid not in ids or q is None or (q.year, q.month) != (ano, mes) or om._int(r.get("os")) is None:
            continue
        grupos.setdefault((uid, str(r.get("dia"))[:10], str(r.get("hora_inicio"))[:5], str(r.get("hora_fim"))[:5]),
                          []).append(r)
    out = [cabecalho(min(rs, key=lambda x: (-(om._int(x.get("n_fotos")) or 0), om._int(x.get("os")))))
           for rs in grupos.values()]
    return sorted(out, key=lambda x: (x["dia"], x["inicio"]), reverse=True)


def da_os(dados, os_):
    """A linha da OS de ronda — só se for de usina ligada no de-para do 5080 e de 10/2026 em diante. É a trava das rotas
    de foto e de dúvida: o 5080 é público, e sem ela qualquer número de OS do Fracttal (de qualquer cliente) viraria
    foto na tela."""
    alvo = om._int(os_)
    if alvo is None or not dados:
        return None
    ids = {om._int(x.get("usina_id")) for x in dados.get("de_para") or []}
    for r in dados.get("rondas_com_os") or []:
        if om._int(r.get("os")) == alvo and om._int(r.get("usina_id")) in ids:
            q = _quando(r)
            if q is not None and (q.year, q.month) >= om.DESDE:
                return r
    return None


def _foto(i, desc):
    d = str(desc or "").strip()
    if om.chave(d).startswith("ronda "):
        return {"i": i, "item": "Capa da ronda", "resposta": "", "chave": None}
    item, sep, resp = d.partition(" — ")
    return {"i": i, "item": item.strip(), "resposta": resp.strip() if sep else "", "chave": om.chave(item)}


def detalhe(r, descricoes):
    """A ronda montada para a janela: `descricoes` são as descrições dos anexos de imagem da OS, na ordem do Fracttal (o
    índice é o da rota de foto). Cada foto vai para o item do checklist ou o achado que ela mostra; a que sobra vai para
    "outras", com nome genérico."""
    fotos = [_foto(i, d) for i, d in enumerate(descricoes or [])]
    livres = {}
    for f in fotos:
        if f["chave"]:
            livres.setdefault(f["chave"], []).append(f["i"])

    def pega(*rotulos):
        for rot in rotulos:
            achou = livres.pop(om.chave(rot), None)
            if achou:
                return achou
        return []

    itens = []
    for item, resp in r.get("itens") or []:
        k = next((k for p, k in _NIVEL if om.chave(item).startswith(p)), None)
        n = om.nivel(resp) if k else None
        itens.append({"item": item, "resposta": resp, "nivel": n, "frase": om.REGUA[k][n] if n else None,
                      "fotos": pega(item)})
    ach, secoes = r.get("achados") or {}, {"pragas": [], "ocorrencias": []}
    for k, sec, rot in ACHADOS:
        v = ach.get(k)
        if sec == "pragas" or v:
            secoes[sec].append({"item": rot, "resposta": v or "Nenhum", "nivel": None, "frase": None,
                                "fotos": pega(rot, rot.split()[0])})
    outras = sorted(i for v in livres.values() for i in v) + [f["i"] for f in fotos if f["chave"] is None]
    for i in outras:
        if fotos[i]["chave"] is not None:
            fotos[i].update(item="Foto da ronda", resposta="")
    out = cabecalho(r)
    out.update(itens=itens, pragas=secoes["pragas"], ocorrencias=secoes["ocorrencias"], outras=sorted(outras),
               fotos=[{"i": f["i"], "item": f["item"], "resposta": f["resposta"]} for f in fotos])
    return out
```

- [ ] **Step 5: rodar** → 5 passaram.
- [ ] **Step 6: `git diff --stat`** (sem commit).

### Task 2: lista branca das rondas no `fonte_operacao` + versão do cache

**Files:**
- Modify: `thopen/fonte_operacao.py` (ABAS, `baixar`, `_grava_cache`, `_le_cache`, docstring)
- Test: `tests/test_thopen_fonte_operacao.py`

**Interfaces:**
- Consumes: `rondas_cliente.campos`.
- Produces: `dados["rondas_com_os"]` com `{"usina_id","dia","hora_inicio","hora_fim","os","n_fotos","sujidade","vegetacao","itens","achados","unidade"}`; `fonte_operacao.VERSAO_CACHE = 3`.

- [ ] **Step 1: testes** — no `test_lista_branca_o_texto_da_ronda_e_o_tecnico_nao_entram`, as linhas falsas do `campo_nexus · rondas` ganham `os`, `usina`, `n_fotos`, `pendencias_e_achados` (com PENDÊNCIAS e texto livre) e `tecnico_cifrado`; o assert passa a ser:

```python
    (r,) = d["rondas_com_os"]
    assert r == {"usina_id": 1, "dia": "2026-10-02", "hora_inicio": "13:00", "hora_fim": "13:40", "os": "15176",
                 "n_fotos": 19, "sujidade": 2, "vegetacao": 3, "unidade": "Altair 1",
                 "itens": [["Sujidade dos módulos", "2"], ["Altura da vegetação", "3"]], "achados": {"praga": "Pontual"}}
    assert "ronda longa" not in str(d) and "Fulano" not in str(d) and "cf1:" not in str(d)
```

e um teste novo:

```python
def test_cache_em_disco_sem_a_versao_da_rodada_3_nao_sobe(monkeypatch, tmp_path):
    # o cache da rodada 2 tem todas as abas, mas as rondas sem OS, itens e achados: a janela abriria vazia até a recarga
    arq = tmp_path / "c.json.gz"
    with gzip.open(arq, "wt", encoding="utf-8") as f:
        json.dump({"ts": 1.0, "dados": {k: [] for k, _ in fo.ABAS.values()}}, f)
    monkeypatch.setattr(fo, "CACHE", str(arq))
    monkeypatch.setattr(fo, "_estado", {"dados": None, "ts": 0.0, "erro": None, "carregando": False, "proxima": 0.0,
                                        "disco_lido": False})
    assert fo.dados(agora=1000.0, iniciar=lambda f: None) is None
    fo._grava_cache({k: [] for k, _ in fo.ABAS.values()}, 5.0)
    assert fo._le_cache()["ts"] == 5.0
```

- [ ] **Step 2: ver falhar.**
- [ ] **Step 3: implementar**

```python
# ABAS
    ("campo_nexus", "rondas"): ("rondas_com_os", ("usina_id", "dia", "hora_inicio", "hora_fim", "os", "usina",
                                                  "n_fotos", "respostas", "pendencias_e_achados")),
# baixar(), no lugar do update antigo:
            if k == "rondas_com_os":
                item.update(operacao_mes.ler_respostas(item["respostas"]))
                # rodada 3: o checklist e só os ACHADOS; o texto livre e as PENDÊNCIAS morrem aqui
                item.update(rondas_cliente.campos(item.pop("respostas"), item.pop("pendencias_e_achados"),
                                                  item.pop("usina")))
                item["n_fotos"] = operacao_mes._int(item.get("n_fotos")) or 0
# cache
VERSAO_CACHE = 3        # rodada 3 (09/10): as rondas ganharam os, itens e achados — o cache da rodada 2 não serve
#   _grava_cache: json.dump({"versao": VERSAO_CACHE, "ts": ts, "dados": dados}, ...)
#   _le_cache:    if d.get("versao") != VERSAO_CACHE: return None   (antes da checagem das chaves)
```

- [ ] **Step 4: rodar `tests/test_thopen_fonte_operacao.py`** → todos passam.

### Task 3: `fotos_ronda` (Fracttal + miniaturas)

**Files:**
- Create: `thopen/fotos_ronda.py`
- Test: `tests/test_thopen_fotos_ronda.py`

**Interfaces:**
- Consumes: `fonte_api.segredo`.
- Produces: `fotos_ronda.anexos(os_) -> [{"desc","url","mime"}]`, `foto(os_, i) -> (bytes, mime)`, `miniatura(os_, i) -> (bytes, mime)`; exceções `SemCredencial`, `Ocupado`, `SemFoto`; ponto de injeção `_abrir(req, timeout)`.

- [ ] **Step 1: testes** (Fracttal falso por `_abrir`; nada de rede)

```python
import io, json, os, sys, urllib.error
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import fotos_ronda as fr  # noqa: E402


class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


@pytest.fixture
def fracttal(monkeypatch):
    pedidos = []
    monkeypatch.setattr(fr, "_tok", {"v": "", "exp": 0.0})
    monkeypatch.setattr(fr, "_listas", {}); monkeypatch.setattr(fr, "_fotos", fr.OrderedDict())
    monkeypatch.setattr(fr, "_minis", fr.OrderedDict())
    monkeypatch.setattr(fr.fonte_api, "segredo", lambda n: "x" if n.startswith("FRACTTAL_CLIENT") else "")

    def abrir(req, timeout=None):
        url = req.full_url
        pedidos.append(url)
        if url.endswith("/oauth/token"):
            return Resp(json.dumps({"access_token": "t", "expires_in": 3600}).encode())
        if "/api/work_orders_attachments" in url:
            return Resp(json.dumps({"data": [
                {"description": "Sujidade dos módulos — 2", "value": "https://s3/a.jpg?sig=1"},
                {"description": "planilha", "value": "https://s3/b.xlsx?sig=1"},
                {"description": "Pragas — pontual", "value": "https://s3/c.png?sig=1"}]}).encode())
        return Resp(b"\xff\xd8 foto")
    monkeypatch.setattr(fr, "_abrir", abrir)
    return pedidos


def test_lista_so_imagens_e_guarda_20_min(fracttal):
    a = fr.anexos(15176)
    assert [(x["desc"], x["mime"]) for x in a] == [("Sujidade dos módulos — 2", "image/jpeg"), ("Pragas — pontual", "image/png")]
    fr.anexos("15176")
    assert sum("/api/work_orders_attachments" in p for p in fracttal) == 1     # o 2º veio da memória
    assert "folio=15176" in [p for p in fracttal if "attachments" in p][0]


def test_foto_baixa_pelo_link_e_indice_fora_e_semfoto(fracttal):
    corpo, mime = fr.foto(15176, 1)
    assert corpo == b"\xff\xd8 foto" and mime == "image/png"
    with pytest.raises(fr.SemFoto):
        fr.foto(15176, 9)


def test_sem_credencial_avisa_sem_pedir(monkeypatch, fracttal):
    monkeypatch.setattr(fr.fonte_api, "segredo", lambda n: "")
    with pytest.raises(fr.SemCredencial):
        fr.anexos(15176)
    assert fracttal == []


def test_cota_do_fracttal_vira_ocupado(monkeypatch, fracttal):
    def abrir(req, timeout=None):
        if req.full_url.endswith("/oauth/token"):
            return Resp(json.dumps({"access_token": "t"}).encode())
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
    monkeypatch.setattr(fr, "_abrir", abrir)
    with pytest.raises(fr.Ocupado):
        fr.anexos(15176)


def test_miniatura_reduz_e_sem_pillow_vai_a_inteira(monkeypatch, fracttal):
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (1280, 1700), "white").save(b, "JPEG")
    monkeypatch.setattr(fr, "_baixar", lambda url: b.getvalue())
    corpo, mime = fr.miniatura(15176, 0)
    assert mime == "image/jpeg" and max(Image.open(io.BytesIO(corpo)).size) == fr.MINI_PX
```

- [ ] **Step 2: ver falhar.**
- [ ] **Step 3: implementar `thopen/fotos_ronda.py`**

```python
# -*- coding: utf-8 -*-
"""Fotos da ronda para o cliente (rodada 3, 09/10/2026): os anexos da OS de ronda no Fracttal. O App sobe cada foto
com a descrição "<item do checklist> — <resposta>" ("Sujidade dos módulos — 2"); a 1ª vira a capa ("Ronda <dia> —
<usina> · qualidade N%"). O mesmo caminho do Nexus (nexus/campo/ronda_fotos.py, 06/10): a LISTA vem da API REST, 1
pedido por OS guardado 20 min (o link vem assinado e vale 24 h); o ARQUIVO vem do S3 pelo link — não é pedido à API. O
link nunca sai para o navegador: o 5080 baixa e entrega.

Cota: o Fracttal limita 200 pedidos/min por EMPRESA, somando App de Campo, PCM, OS Creator e as duas plataformas, e
vive no limite — aqui é 1 pedido por OS aberta. Recusa por cota vira `Ocupado` na hora (esperar prenderia uma linha do
waitress). Credencial: FRACTTAL_CLIENT_ID / FRACTTAL_CLIENT_SECRET, a da plataforma (fonte_api.segredo). Sem ela, a
janela mostra a ronda e diz que as fotos não estão disponíveis. Nada roda no import.
"""
import io
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict

import fonte_api

BASE = (os.environ.get("FRACTTAL_BASE_URL") or "https://app.fracttal.com").rstrip("/")
LISTA_S = 1200               # a lista de anexos de uma OS, 20 min sem pedir de novo
LISTAS_MAX = 500
FOTOS_EM_MEMORIA = 40        # as últimas fotos inteiras (182 a 690 kB cada, medido em 06/10)
MINIS_EM_MEMORIA = 600       # as últimas miniaturas (7 a 14 kB)
FOTO_MAX = 10 * 1024 * 1024
MINI_PX = 240
PAGINA = 100
TIMEOUT = 30
MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


class SemCredencial(RuntimeError):
    """FRACTTAL_CLIENT_ID/SECRET não configurados neste servidor."""


class Ocupado(RuntimeError):
    """O Fracttal recusou por cota (429; 406 era o limite antigo, por IP)."""


class SemFoto(LookupError):
    """O índice pedido não está nos anexos de imagem da OS."""


_trava = threading.Lock()
_tok = {"v": "", "exp": 0.0}
_listas = {}
_fotos = OrderedDict()
_minis = OrderedDict()


def _abrir(req, timeout=TIMEOUT):
    return urllib.request.urlopen(req, timeout=timeout)


def _token():
    with _trava:
        if _tok["v"] and time.time() < _tok["exp"]:
            return _tok["v"]
    cid, sec = fonte_api.segredo("FRACTTAL_CLIENT_ID"), fonte_api.segredo("FRACTTAL_CLIENT_SECRET")
    if not (cid and sec):
        raise SemCredencial("FRACTTAL_CLIENT_ID/FRACTTAL_CLIENT_SECRET não configurados")
    corpo = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid,
                                    "client_secret": sec}).encode()
    with _abrir(urllib.request.Request(BASE + "/oauth/token", data=corpo, method="POST")) as r:
        d = json.loads(r.read().decode("utf-8"))
    with _trava:
        _tok.update(v=d["access_token"], exp=time.time() + int(d.get("expires_in", 3600)) - 60)
        return _tok["v"]


def _get(ep, params):
    url = "%s/api/%s?%s" % (BASE, ep, urllib.parse.urlencode(params))
    for tentativa in (1, 2):
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + _token(),
                                                   "Accept": "application/json"})
        try:
            with _abrir(req) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401 and tentativa == 1:
                with _trava:
                    _tok["v"] = ""                     # token venceu: pede outro uma vez
                continue
            if e.code in (406, 429):
                raise Ocupado("Fracttal recusou por cota (%d)" % e.code) from None
            raise


def anexos(os_):
    """As imagens anexadas na OS, na ordem do Fracttal: [{desc, url, mime}]. O índice desta lista é o da rota."""
    chave = str(int(os_))
    with _trava:
        g = _listas.get(chave)
        if g and time.time() - g[0] < LISTA_S:
            return g[1]
    brutos, ini = [], 0
    while True:
        d = _get("work_orders_attachments", {"folio": chave, "limit": PAGINA, "start": ini})
        linhas = (d.get("data") if isinstance(d, dict) else d) or []
        brutos += linhas
        if len(linhas) < PAGINA:
            break
        ini += PAGINA
    out = []
    for a in brutos:
        url = str(a.get("value") or "")
        mime = MIME.get(url.split("?", 1)[0].rsplit(".", 1)[-1].lower())
        if url and mime:
            out.append({"desc": str(a.get("description") or "").strip(), "url": url, "mime": mime})
    with _trava:
        if len(_listas) >= LISTAS_MAX:
            _listas.clear()
        _listas[chave] = (time.time(), out)
    return out


def _baixar(url):
    with _abrir(urllib.request.Request(url)) as r:
        corpo = r.read(FOTO_MAX + 1)
    if len(corpo) > FOTO_MAX:
        raise SemFoto("a foto no Fracttal é grande demais")
    return corpo


def _guardado(cache, limite, chave, fazer):
    with _trava:
        if chave in cache:
            cache.move_to_end(chave)
            return cache[chave]
    item = fazer()
    with _trava:
        cache[chave] = item
        while len(cache) > limite:
            cache.popitem(last=False)
    return item


def foto(os_, i):
    def fazer():
        lista = anexos(os_)
        if not 0 <= int(i) < len(lista):
            raise SemFoto("a OS %s não tem a foto %s" % (os_, i))
        return _baixar(lista[int(i)]["url"]), lista[int(i)]["mime"]
    return _guardado(_fotos, FOTOS_EM_MEMORIA, (str(os_), int(i)), fazer)


def _reduzir(corpo, mime):
    try:
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(corpo))).convert("RGB")
        im.thumbnail((MINI_PX, MINI_PX))
        saida = io.BytesIO()
        im.save(saida, "JPEG", quality=80, optimize=True)
        return saida.getvalue(), "image/jpeg"
    except Exception:       # noqa: BLE001 — sem Pillow ou imagem que ele não abre: vai a foto inteira
        return corpo, mime


def miniatura(os_, i):
    """A foto reduzida para a janela (a do App vem com 1280x1700). Sem o Pillow, a inteira."""
    return _guardado(_minis, MINIS_EM_MEMORIA, (str(os_), int(i)), lambda: _reduzir(*foto(os_, i)))
```

- [ ] **Step 4: rodar** → passam.

### Task 4: `duvida` (validação, limite, cartão do Teams)

**Files:**
- Create: `thopen/duvida.py`
- Test: `tests/test_thopen_duvida.py`

**Interfaces:**
- Consumes: `fonte_api.segredo`.
- Produces: `duvida.url() -> str`, `duvida.validar(corpo) -> (dados|None, erro|None)` (erro `"isca"` = robô), `duvida.Limite().tenta(ip, agora=None) -> bool`, `duvida.cartao(dados, usina, cab) -> dict`, `duvida.enviar(payload, destino) -> None` (levanta se o Teams recusar); ponto de injeção `_abrir`.

- [ ] **Step 1: testes**

```python
import json, os, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import duvida  # noqa: E402

OK = {"nome": " Ana  Souza ", "contato": "ana@cliente.com.br", "mensagem": "Quando volta a roçada?"}


def test_valida_campos_contato_e_tamanho():
    d, e = duvida.validar(OK)
    assert e is None and d["nome"] == "Ana Souza"
    assert duvida.validar(dict(OK, contato="(85) 99999-1234"))[1] is None
    assert duvida.validar(dict(OK, contato="amanhã"))[1].startswith("Informe um e-mail")
    assert duvida.validar(dict(OK, mensagem=""))[1] == "Preencha nome, contato e a dúvida."
    assert "1000" in duvida.validar(dict(OK, mensagem="x" * 1001))[1]
    assert duvida.validar(dict(OK, site="http://spam"))[1] == "isca"


def test_limite_por_endereco_e_por_dia():
    lim = duvida.Limite(por_ip=(3, 3600), por_dia=5)
    assert [lim.tenta("a", agora=100) for _ in range(4)] == [True, True, True, False]
    assert lim.tenta("a", agora=100 + 3601)                 # a hora passou
    assert lim.tenta("b", agora=200) and not lim.tenta("c", agora=201)   # 5 no dia: o 6º para
    assert lim.tenta("c", agora=100 + 86401)


def test_cartao_do_teams_leva_usina_ronda_e_contato():
    cab = {"os": "15176", "dia": "2026-10-02", "inicio": "07:13", "fim": "08:07", "unidade": "Guaratingueta 5"}
    c = duvida.cartao(duvida.validar(OK)[0], "Guaratinguetá V", cab)
    card = c["attachments"][0]["content"]
    assert c["type"] == "message" and card["type"] == "AdaptiveCard"
    fatos = {f["title"]: f["value"] for f in card["body"][1]["facts"]}
    assert fatos["Usina"] == "Guaratinguetá V" and "02/10/2026" in fatos["Ronda"] and "OS 15176" in fatos["Ronda"]
    assert fatos["Contato"] == "ana@cliente.com.br" and card["body"][2]["text"] == OK["mensagem"]


def test_enviar_posta_json_e_recusa_levanta(monkeypatch):
    vistos = []

    class R:
        status = 202
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(duvida, "_abrir", lambda req, timeout=None: (vistos.append(req), R())[1])
    duvida.enviar({"a": 1}, "https://exemplo/fluxo")
    assert vistos[0].get_method() == "POST" and json.loads(vistos[0].data) == {"a": 1}
    R.status = 400
    with pytest.raises(RuntimeError):
        duvida.enviar({"a": 1}, "https://exemplo/fluxo")
```

- [ ] **Step 2: ver falhar.**
- [ ] **Step 3: implementar `thopen/duvida.py`**

```python
# -*- coding: utf-8 -*-
"""Dúvida do cliente sobre uma ronda (Levi, 09/10/2026: "um campo onde o cliente possa tirar dúvidas e tem que chegar
uma notificação para a gente de alguma maneira").

O aviso vai para um canal do Teams por um fluxo do app Workflows ("Postar em um canal quando uma solicitação de webhook
for recebida"). A URL do fluxo é segredo — quem a tem posta no canal — e vem de THOPEN_DUVIDA_TEAMS (ambiente ou .env
da raiz). Sem URL, a rota diz que o envio não está disponível e a tela esconde o formulário: nunca dizer "enviada" sem
ter avisado ninguém. E-mail não serve: o envio do servidor está barrado no tenant desde 23/09.

A resposta ao cliente é por fora (Levi, 09/10): o formulário pede nome e e-mail ou telefone. Nada é guardado aqui — o
registro é a mensagem no canal; se o Teams recusar, o cliente vê o erro e tenta de novo.

O 5080 é público, sem senha: limite por endereço (3 por hora) e no total (40 por dia), campo-isca contra robô e texto
curto. O endereço vem do CF-Connecting-IP (o túnel da Cloudflare põe; atrás dele o remote_addr é sempre 127.0.0.1).
"""
import json
import re
import threading
import time
import urllib.request

import fonte_api

VARIAVEL = "THOPEN_DUVIDA_TEAMS"
MAX = {"nome": 80, "contato": 120, "mensagem": 1000}
POR_IP = (3, 3600)
POR_DIA = 40
TIMEOUT = 15
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def url():
    return fonte_api.segredo(VARIAVEL)


def validar(corpo):
    b = corpo or {}
    if str(b.get("site") or "").strip():
        return None, "isca"                   # campo escondido: só robô preenche
    d = {"nome": " ".join(str(b.get("nome") or "").split()),
         "contato": " ".join(str(b.get("contato") or "").split()),
         "mensagem": str(b.get("mensagem") or "").strip()}
    if not all(d.values()):
        return None, "Preencha nome, contato e a dúvida."
    for k, n in MAX.items():
        if len(d[k]) > n:
            return None, "O campo %s passa de %d caracteres." % ({"nome": "nome", "contato": "contato",
                                                                  "mensagem": "dúvida"}[k], n)
    if not (_EMAIL.match(d["contato"]) or len(re.sub(r"\D", "", d["contato"])) >= 10):
        return None, "Informe um e-mail ou um telefone com DDD."
    return d, None


class Limite:
    def __init__(self, por_ip=POR_IP, por_dia=POR_DIA):
        self.n_ip, self.janela = por_ip
        self.n_dia = por_dia
        self._ip, self._dia, self._trava = {}, [], threading.Lock()

    def tenta(self, ip, agora=None):
        agora = time.time() if agora is None else agora
        with self._trava:
            self._dia = [t for t in self._dia if agora - t < 86400]
            vistos = [t for t in self._ip.get(ip, []) if agora - t < self.janela]
            if len(vistos) >= self.n_ip or len(self._dia) >= self.n_dia:
                self._ip[ip] = vistos
                return False
            self._ip[ip] = vistos + [agora]
            self._dia.append(agora)
            return True


def cartao(d, usina, cab):
    dia = "%s/%s/%s" % (cab["dia"][8:10], cab["dia"][5:7], cab["dia"][:4])
    fatos = [{"title": "Usina", "value": usina},
             {"title": "Ronda", "value": "%s · %s, das %s às %s · OS %s" % (cab["unidade"], dia, cab["inicio"],
                                                                         cab["fim"], cab["os"])},
             {"title": "Nome", "value": d["nome"]}, {"title": "Contato", "value": d["contato"]}]
    return {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
        "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
                    "version": "1.4", "body": [
                        {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "wrap": True,
                         "text": "Dúvida do cliente sobre a ronda"},
                        {"type": "FactSet", "facts": fatos},
                        {"type": "TextBlock", "wrap": True, "text": d["mensagem"]}]}}]}


def _abrir(req, timeout=TIMEOUT):
    return urllib.request.urlopen(req, timeout=timeout)


def enviar(payload, destino):
    req = urllib.request.Request(destino, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with _abrir(req) as r:
        st = getattr(r, "status", 200)
    if not 200 <= st < 300:                   # o fluxo do Workflows responde 202
        raise RuntimeError("o Teams respondeu %s" % st)
```

- [ ] **Step 4: rodar** → passam.

### Task 5: as rotas no `dashboard_thopen`

**Files:**
- Modify: `thopen/dashboard_thopen.py` (imports; rotas novas depois de `api_operacao`)
- Test: `tests/test_thopen_rondas_rota.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: `GET /api/t/rondas?usina&ano&mes` → `{"disponivel","motivo","rondas":[cab],"duvida":bool}`; `GET /api/t/ronda/<os>` → `detalhe + {"fotos_erro"}`; `GET /api/t/ronda/<os>/foto/<i>[?mini=1]` → imagem; `POST /api/t/duvida` → `{"ok", "erro"?}`.

- [ ] **Step 1: testes** (dados falsos no `fonte_operacao._estado`; Fracttal e Teams falsos)

```python
import os, sys, time
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thopen"))
import dashboard_thopen as dth  # noqa: E402
import duvida, fonte_operacao as fo, fotos_ronda  # noqa: E402

R = {"os": "15176", "usina_id": 86, "dia": "2026-10-02", "hora_inicio": "10:13", "hora_fim": "11:07", "n_fotos": 2,
     "unidade": "Guaratingueta 5", "itens": [["Sujidade dos módulos", "2"]], "achados": {}, "sujidade": 2,
     "vegetacao": None}
DADOS = {k: [] for k, _ in fo.ABAS.values()}
DADOS.update(rondas_com_os=[R, dict(R, os="99999", usina_id=5)],
             de_para=[{"usina_id": 86, "chave_externa": "Guaratinguetá V"}])


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(fo, "_estado", {"dados": DADOS, "ts": time.time(), "erro": None, "carregando": False,
                                        "proxima": 0.0, "disco_lido": True})
    monkeypatch.setattr(fotos_ronda, "anexos", lambda os_: [{"desc": "Sujidade dos módulos — 2", "url": "u", "mime": "image/jpeg"}])
    monkeypatch.setattr(fotos_ronda, "miniatura", lambda os_, i: (b"mini", "image/jpeg"))
    monkeypatch.setattr(duvida, "url", lambda: "https://exemplo/fluxo")
    monkeypatch.setattr(dth, "_LIMITE", duvida.Limite())
    enviados = []
    monkeypatch.setattr(duvida, "enviar", lambda p, d: enviados.append(p))
    c = dth.app.test_client()
    c.enviados = enviados
    return c


def test_lista_do_mes_e_duvida_ligada(cli):
    r = cli.get("/api/t/rondas?usina=Guaratinguet%C3%A1%20V&ano=2026&mes=10").get_json()
    assert r["disponivel"] and r["duvida"] is True and [x["os"] for x in r["rondas"]] == ["15176"]
    assert cli.get("/api/t/rondas?usina=x&ano=2026&mes=13").status_code == 400
    assert cli.get("/api/t/rondas?usina=Guaratinguet%C3%A1%20V&ano=2026&mes=9").get_json()["rondas"] == []


def test_detalhe_e_foto_so_de_os_permitida(cli):
    d = cli.get("/api/t/ronda/15176").get_json()
    assert d["itens"][0]["fotos"] == [0] and d["fotos_erro"] is None
    f = cli.get("/api/t/ronda/15176/foto/0?mini=1")
    assert f.status_code == 200 and f.data == b"mini" and "private" in f.headers["Cache-Control"]
    assert cli.get("/api/t/ronda/99999").status_code == 404           # usina fora do 5080
    assert cli.get("/api/t/ronda/12345/foto/0").status_code == 404     # OS que não é ronda do 5080


def test_fracttal_fora_mostra_a_ronda_e_avisa(cli, monkeypatch):
    def ocupado(os_): raise fotos_ronda.Ocupado("429")
    monkeypatch.setattr(fotos_ronda, "anexos", ocupado)
    d = cli.get("/api/t/ronda/15176").get_json()
    assert d["itens"] and d["fotos"] == [] and "1 minuto" in d["fotos_erro"]


def test_duvida_vai_ao_teams_com_limite(cli):
    corpo = {"usina": "Guaratinguetá V", "os": "15176", "nome": "Ana", "contato": "ana@x.com.br", "mensagem": "Oi?"}
    assert cli.post("/api/t/duvida", json=corpo).get_json() == {"ok": True}
    assert "Guaratinguetá V" in str(cli.enviados[0])
    assert cli.post("/api/t/duvida", json=dict(corpo, usina="Altair")).status_code == 404   # OS de outra usina
    assert cli.post("/api/t/duvida", json=dict(corpo, contato="x")).status_code == 400
    h = {"CF-Connecting-IP": "1.2.3.4"}
    assert [cli.post("/api/t/duvida", json=corpo, headers=h).status_code for _ in range(4)] == [200, 200, 200, 429]


def test_sem_url_do_teams_nao_finge(cli, monkeypatch):
    monkeypatch.setattr(duvida, "url", lambda: "")
    assert cli.get("/api/t/rondas?usina=Guaratinguet%C3%A1%20V&ano=2026&mes=10").get_json()["duvida"] is False
    r = cli.post("/api/t/duvida", json={"usina": "Guaratinguetá V", "os": "15176", "nome": "A", "contato": "a@b.co",
                                        "mensagem": "x"})
    assert r.status_code == 503 and cli.enviados == []


def test_chave_desliga_tudo(cli, monkeypatch):
    monkeypatch.setenv("THOPEN_RONDAS", "0")
    assert cli.get("/api/t/rondas?usina=Guaratinguet%C3%A1%20V&ano=2026&mes=10").get_json()["motivo"] == "desligado"
    assert cli.get("/api/t/ronda/15176").status_code == 404
```

- [ ] **Step 2: ver falhar.**
- [ ] **Step 3: implementar** (imports `rondas_cliente`, `fotos_ronda`, `duvida`; `from flask import Response, abort`)

```python
def _usina_ano_mes():
    """(usina, ano, mes, None) ou (..., resposta 400) — os mesmos limites do /api/t/operacao."""
    usina = (request.args.get("usina") or "").strip()
    try:
        ano, mes = int(request.args.get("ano", "")), int(request.args.get("mes", ""))
    except ValueError:
        return usina, 0, 0, (jsonify({"erro": "ano e mes precisam ser números"}), 400)
    if not usina or not 1 <= mes <= 12 or not 2020 <= ano <= 2100:
        return usina, ano, mes, (jsonify({"erro": "usina, ano (2020 a 2100) e mes (1 a 12) são obrigatórios"}), 400)
    return usina, ano, mes, None


def _rondas_desligadas():
    return os.environ.get("THOPEN_RONDAS", "1").strip() == "0"


@app.route("/api/t/rondas")
def api_rondas():
    """As rondas do mês da usina para a janela do ícone do card (rodada 3, 09/10/2026). Sem pedido ao Fracttal: as
    fotos de cada ronda vêm só quando ela é aberta."""
    usina, ano, mes, erro = _usina_ano_mes()
    if erro:
        return erro
    vazio = {"disponivel": False, "rondas": [], "duvida": False}
    if _rondas_desligadas():
        return jsonify(dict(vazio, motivo="desligado"))
    if (ano, mes) < operacao_mes.DESDE:
        return jsonify(dict(vazio, motivo="antes de 10/2026", disponivel=True))
    dados = fonte_operacao.dados()
    if dados is None:
        return jsonify(dict(vazio, motivo="carregando"))
    return jsonify({"disponivel": True, "motivo": None, "rondas": rondas_cliente.do_mes(dados, usina, ano, mes),
                    "duvida": bool(duvida.url())})


def _ronda_ou_404(os_):
    r = None if _rondas_desligadas() else rondas_cliente.da_os(fonte_operacao.dados(), os_)
    if r is None:
        abort(404)
    return r


@app.route("/api/t/ronda/<int:os_>")
def api_ronda(os_):
    """Uma ronda montada para a janela, com as fotos casadas aos itens (1 pedido ao Fracttal, guardado 20 min)."""
    r = _ronda_ou_404(os_)
    descs, erro = [], None
    try:
        descs = [a["desc"] for a in fotos_ronda.anexos(os_)]
    except fotos_ronda.SemCredencial:
        erro = "As fotos desta ronda não estão disponíveis neste painel."
    except fotos_ronda.Ocupado:
        erro = "O sistema de fotos está ocupado agora. Tente de novo em 1 minuto."
    except Exception as e:                    # noqa: BLE001 — a ronda aparece mesmo sem as fotos
        print("[rondas] anexos da OS %s: %s" % (os_, type(e).__name__), flush=True)
        erro = "Não consegui carregar as fotos agora. Tente de novo em 1 minuto."
    out = rondas_cliente.detalhe(r, descs)
    out["fotos_erro"] = erro
    return jsonify(out)


@app.route("/api/t/ronda/<int:os_>/foto/<int:i>")
def api_ronda_foto(os_, i):
    """A foto (ou a miniatura, ?mini=1): o 5080 baixa do Fracttal e entrega — o link assinado não sai daqui."""
    _ronda_ou_404(os_)
    try:
        corpo, mime = (fotos_ronda.miniatura if request.args.get("mini") else fotos_ronda.foto)(os_, i)
    except fotos_ronda.SemFoto:
        abort(404)
    except Exception as e:                    # noqa: BLE001
        print("[rondas] foto %s/%s: %s" % (os_, i, type(e).__name__), flush=True)
        return Response("foto indisponível agora", status=502, mimetype="text/plain")
    return Response(corpo, mimetype=mime, headers={"Cache-Control": "private, max-age=3600"})


_LIMITE = duvida.Limite()


@app.route("/api/t/duvida", methods=["POST"])
def api_duvida():
    """A dúvida do cliente sobre uma ronda, para o canal do Teams. Sem guardar nada: o registro é a mensagem."""
    destino = duvida.url()
    if _rondas_desligadas() or not destino:
        return jsonify({"ok": False, "erro": "O envio de dúvidas não está disponível agora."}), 503
    b = request.get_json(silent=True) or {}
    dados, usina = fonte_operacao.dados(), str(b.get("usina") or "").strip()
    r = rondas_cliente.da_os(dados, b.get("os"))
    if r is None or operacao_mes._int(r.get("usina_id")) not in operacao_mes.ids_da_usina(dados.get("de_para"), usina):
        return jsonify({"ok": False, "erro": "Ronda não encontrada."}), 404
    d, erro = duvida.validar(b)
    if erro == "isca":
        return jsonify({"ok": True})
    if erro:
        return jsonify({"ok": False, "erro": erro}), 400
    if not _LIMITE.tenta(request.headers.get("CF-Connecting-IP") or request.remote_addr or "?"):
        return jsonify({"ok": False, "erro": "Muitas mensagens em pouco tempo. Tente de novo mais tarde."}), 429
    try:
        duvida.enviar(duvida.cartao(d, usina, rondas_cliente.cabecalho(r)), destino)
    except Exception as e:                    # noqa: BLE001 — sem dado pessoal no log
        print("[duvida] o Teams não recebeu: %s" % type(e).__name__, flush=True)
        return jsonify({"ok": False, "erro": "Não consegui enviar agora. Tente de novo em alguns minutos."}), 502
    return jsonify({"ok": True})
```

O `api_operacao` passa a usar `_usina_ano_mes()` (o mesmo 400 de antes).

- [ ] **Step 4: rodar o teste novo + `tests/test_thopen_operacao_rota.py`** → passam.

### Task 6: a tela (tabela em frases, título, ícone, janela, dúvida)

**Files:**
- Modify: `thopen/templates/dashboard_thopen.html`
- Test: `tests/test_thopen_operacao_tela.py`

- [ ] **Step 1: testes** — troca `test_tabela_por_dia_de_outubro_em_diante` (cabeçalho de 3 colunas; `_opFrase(g)` na célula; sem `op-n`), e acrescenta:

```python
def _frase(s, t):
    if not NODE:
        pytest.skip("node não instalado")
    fn = T[T.index("function _opFrase("):T.index("/* fim _opFrase */")]
    js = ("const nf0=new Intl.NumberFormat('pt-BR');" + fn +
          "\nprocess.stdout.write(_opFrase(%s));" % json.dumps({"s": s, "t": t}))
    r = subprocess.run([NODE, "-e", js], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_frase_do_dia():
    assert _frase("42", "2") == "<b>2</b> trackers parados. <b>42</b> strings sem corrente."
    assert _frase("1", "1") == "<b>1</b> tracker parado. <b>1</b> string sem corrente."
    assert _frase("0", "0") == "Nenhum tracker parado. Nenhuma string sem corrente."
    assert _frase("—", "5") == "<b>5</b> trackers parados."            # sem medição não vira frase
    assert _frase("1.234", "0") == "Nenhum tracker parado. <b>1.234</b> strings sem corrente."


def test_zeladoria_e_titulo_com_a_letra_do_card():
    zt = [d for s, d in regras(CSS) if s == ".op-zt"][0]
    assert "font-size:12px" in zt and "font-weight:700" in zt and "color:#555" in zt
    assert "op-zsub" in corpo("renderOperacao")


def test_icone_das_rondas_no_card_e_fora_de_todo_pdf():
    card = T[T.index('id="opCard"'):T.index('<div class="grid2">')]
    assert 'id="opFotos"' in card and 'aria-label="Fotos das rondas do mês"' in card
    fora = " ".join(s for s, d in regras(CSS) if "display:none" in d.replace(" ", ""))
    assert "body.printing .op-fotos" in fora and "#printArea .op-fotos" in fora and ".rd-fundo" in fora


def test_janela_so_mostra_o_que_a_rota_manda_e_escapa_tudo():
    j = corpo("_rdDesenha")
    assert "_opEsc(" in j and "fotos_erro" in j
    for proibido in ("tecnico", "qualidade", "pendencias", "gps"):
        assert proibido not in j.lower()


def test_formulario_de_duvida_so_com_o_teams_ligado():
    assert "d.duvida" in corpo("abrirRondas") and 'id="dvSite"' in T      # campo-isca
    assert "/api/t/duvida" in corpo("enviarDuvida")


def test_sem_emoji_na_janela():
    assert not EMOJI.search(T[T.index('id="rdFundo"'):])
```

- [ ] **Step 2: ver falhar.**
- [ ] **Step 3: implementar no template** — CSS do mockup (`m4/gera_mock4.py`, bloco "MOCKUP 4"), sem a prévia do Teams e com `body.printing .op-fotos, #printArea .op-fotos{display:none !important}`; tira as regras `op-n`/`op-sub` da tabela; ícone no `#opCard`; `$('opZt').innerHTML='Zeladoria'+(z?`<span class="op-zsub">ronda de ${_opEsc(z.data)}</span>`:'')`; `_cmtPorDia` com 3 colunas e `_opFrase(g)`; `function _opFrase(g){...}` + `/* fim _opFrase */`; janela (`#rdFundo`, `#rdLuz`) com o formulário (`dvNome`, `dvCont`, `dvMsg`, campo-isca `dvSite` escondido) e JS em duas etapas: `abrirRondas()` → `/api/t/rondas` (lista; `d.duvida` liga o formulário) e `_rdAbre(k)` → `/api/t/ronda/<os>` (detalhe) → `_rdDesenha()`; `enviarDuvida()` → POST `/api/t/duvida`. Metodologia: "Tabela do Diário, por dia" passa a falar da frase.
- [ ] **Step 4: rodar `tests/test_thopen_operacao_tela.py`** → passam.

### Task 7: pacote, requisitos e documentação

**Files:**
- Modify: `thopen/deploy/_package_thopen.py` (ITENS + LEIAME: 8 arquivos, variáveis FRACTTAL_CLIENT_ID, FRACTTAL_CLIENT_SECRET, THOPEN_DUVIDA_TEAMS, THOPEN_RONDAS), `railway.toml`, `render.yaml` (comentário "8 arquivos"), `requirements-thopen.txt` (+ `Pillow==12.2.0`), `tests/test_thopen_operacao_rota.py` (contagem e variáveis), `thopen/CLAUDE.md` (seção "Rondas e dúvida (rodada 3)"), `docs/superpowers/plans/2026-10-08-thopen-operacao-no-mes.md` (ponteiro para este plano).

- [ ] **Step 1:** atualizar os testes do pacote para oito arquivos e as variáveis novas; ver falhar.
- [ ] **Step 2:** atualizar pacote, nuvem, requisitos e docs; rodar → passam.

### Task 8: prova de ponta a ponta

- [ ] Suíte inteira: `python -m pytest -q` (base: 1 falha pré-existente conhecida).
- [ ] 5081 com o template e o código novos, dado real (`e2e/dados_out.json` refeito com a leitura nova) e o Fracttal real (FRACTTAL_* do .env principal, só no processo de teste), Teams FALSO (servidor local que guarda o POST): GV outubro → lista, detalhe com 19 fotos, foto ampliada, dúvida chega no falso com o cartão certo; 4ª dúvida do mesmo endereço = 429; OS 99999/12345 = 404; Baixar PDF e PDF Carteira sem ícone; tela a 375 px sem rolagem lateral.
- [ ] Medir: pedidos ao Fracttal por abertura (esperado: 1 + 0 nas reaberturas em 20 min); tempo da 1ª abertura e das miniaturas.

## Nota (09/10, rodada 4)

A dúvida desta rodada (`duvida.py`, `POST /api/t/duvida`, `THOPEN_DUVIDA_TEAMS`, o formulário da janela das rondas)
saiu: virou a contestação por dia da tabela (`contestacao.py`, `POST /api/t/contestar`, `THOPEN_TEAMS_PERFORMANCE` e
`THOPEN_TEAMS_ZELADORIA`). A janela das rondas e as fotos ficam como estão. Ver o spec, seção "Rodada 4".
