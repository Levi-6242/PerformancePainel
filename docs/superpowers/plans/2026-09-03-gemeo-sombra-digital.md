# Gêmeo Digital — Sombra Digital (Níveis 1–3) — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Colocar no ar, para as usinas do piloto (Santarém 1 e MRO100), um serviço que calcula a geração esperada por inversor com modelo físico sobre a irradiância medida, decompõe o delta em perdas com nome e mostra tudo nas telas Frota e Usina — acessível pela plataforma.

**Architecture:** Um pacote `gemeo/` com três pontos de entrada que só se falam pelo banco PostgreSQL próprio: `ingest` (um laço por fonte: PostgreSQL `powerplants`, API SunOp, API BD_Performance), `modelar` (job idempotente a cada 15 min: gate de duas portas → esperado pvlib → decomposição → eventos → cascata) e `app` (Flask só-leitura sob o prefixo `/gemeo`, proxiado pela plataforma). `ingest_run` é o contrato de frescor e cobertura.

**Tech Stack:** Python ≥ 3.12 · psycopg2-binary · pandas · numpy · pvlib · Flask · waitress · requests · openpyxl · pytest · PostgreSQL 16 · SQL puro versionado (sem ORM) · GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-03-gemeo-sombra-digital-design.md` — o plano argumenta a partir dela; execute com os dois abertos.

## Global Constraints

- Sempre **pt-BR**, inclusive comentários e mensagens de commit. Comentário explica **por quê**, citando o caso real.
- **Sem emoji na interface**; severidade se comunica por cor; tema tokens_grid R00: navy `#191528`, lime `#A9DB21`, status `#2E7D32/#B9770E/#B3261E/#6E6A80`.
- Todo `ts` é `timestamptz` gravado em **UTC**; fuso da usina em `usina.tz`; conversão só na consulta.
- Toda escrita é **upsert pela chave natural**; **nenhum upsert grava NULL sobre valor**; ciclo vazio grava `ingest_run` com `falha` e **nenhuma** leitura.
- SunOp: lote de **600** pathnames, **teto diário de 600 requisições**, pausa fora de **05:40–18:20** (fuso da usina), sobreposição de **30 min**, reconciliação de **24 h** uma vez por dia.
- Modelo: grade de **15 min**; gate POA/GHI em `[0,3; 3]` com GHI > 100 e mediana diária em ±30 % da referência de 30 dias; dia exige **≥ 8 h** válidas; PVWatts com γ **−0,0035**, perdas **0,14**, η **0,96**; tracker: excesso sobre a **mediana da frota** > **5°**; parado = medido < **1 kW** com esperado > **20 kW**; string zerada < **0,1 A** com mediana do inversor > **0,5 A**; instalada = > **1 A** em 30 dias.
- Calibração: CV da POA (10–14 h) < **0,25**; calibrado = ≥ **30** dias limpos e desvio < **0,03**; tolerância **0,08** antes, **0,03** depois.
- Comparação de floats sempre por **tolerância 1e-6**, nunca `==`.
- O gêmeo **não importa** `plataforma/app.py`. Nenhum caminho fixo de máquina no código.
- Nada aqui pode reiniciar, matar ou reconfigurar a plataforma (5050), o worker, o Thopen (5080), os `cloudflared` ou as tarefas agendadas existentes.

---

## Mapa de arquivos

O projeto nasce como pasta `gemeo/` na raiz **deste** repositório (como `plataforma/` e `thopen/`) e migra para `Grid-Co-CODE/gemeo` quando o repositório existir — o pacote já é autocontido para isso.

```
gemeo/
  pyproject.toml                 pacote `gemeo`, script `gemeo = gemeo.cli:main`
  config.toml                    não-segredo: usinas do piloto, ritmos, tetos, porta
  README.md                      como rodar; aponta para o runbook
  gemeo/
    __init__.py
    cli.py                       gemeo migrate | ingest | modelar | calibrar | app | importar-alias | inspecionar-cadastro
    core/
      config.py                  Config + carregar(): config.toml + SECRETS_DIR/gemeo.env
      db.py                      conectar, migrar, upsert_leituras, registrar_ingest_run, marca_dagua, requisicoes_hoje
      tempo.py                   piso_grade, janela, dia_local, dentro_janela_solar
      alias.py                   resolver, gravar (de-para como dado)
      modelos.py                 UsinaRef, EquipRef (dataclasses compartilhadas)
    ingest/
      base.py                    Ingestor (ciclo, marca d'água, ingest_run, Disjuntor), Busca
      pg.py                      IngestorPG — raw_weather_station, raw_inverter, raw_tracker
      sunop.py                   IngestorSunOp — metadata em disco, lote 600 atravessando usinas, teto
      cadastro.py                IngestorCadastro — API BD_Performance → usina, equipamento, alias, meta_mes
      runner.py                  três laços em threads; `gemeo ingest`
    modelar/
      grade.py                   carregar_grade(): leituras → Grade (DataFrames na grade de 15 min)
      gate.py                    avaliar(): duas portas → gate por instante + motivo por dia
      esperado.py                temp_celula, inferir_pac0, esperado_inversor (pvlib)
      decomposicao.py            decompor(): parado / tracker / string / resíduo
      eventos.py                 detectar(): as seis assinaturas
      rollup.py                  cascata(): cascata_dia + perda_dia
      job.py                     modelar(): orquestra e persiste; `gemeo modelar`
      calibrar.py                calibrar(): dias limpos → versão nova de modelo
    app/
      server.py                  criar_app(), prefixo /gemeo, login, rotas, waitress
      consultas.py               frota(), usina(), saude() — todo SQL das telas
      templates/ base.html login.html frota.html usina.html
      static/ tokens.css gemeo.css uplot.min.js uplot.min.css
  migrations/0001_schema.sql
  tools/importar_alias.py  tools/equivalencia.py  tools/golden_from_spike.py
  tests/ conftest.py  fixtures/  test_*.py
  deploy/ instalar_tarefas.ps1  backup.ps1  README.md
  docs/runbook.md
.github/workflows/gemeo-ci.yml   (na raiz do repositório)
plataforma/app.py                +rota proxy /gemeo/*   (Tarefa 20)
docs/redesign/Monitoramento (novo design).html   +entrada de menu   (Tarefa 20)
```

**Fixtures que já existem** (extraídas dos spikes em 03/09, `docs/superpowers/plans/golden/`): `santarem1_2026-08-26.json`, `santarem1_2026-09-01.json`, `mro100_2026-08-26.json`, `mro100_2026-08-31.json`, `mro100_trk_inv.json`. A Tarefa 1 as move para `gemeo/tests/fixtures/golden/`. Formato: `{"usina","fonte","tz","kwp","kw_ac","n_inv","dia","estacao":{"poa":{ts:valor},...},"inv_p":{inv:{ts:kw}},"inv_e_dia","trk_ang","trk_alvo","str_i":{"inv.k":{ts:A}},"sunop_pot_esp_pu","veredito_esperado":{...}}` com `ts` no formato `YYYY-MM-DDTHH:MM` **em hora local da usina**.

**Interfaces compartilhadas** (`gemeo/core/modelos.py`, criado na Tarefa 1):

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class UsinaRef:
    id: int
    codigo: str          # "MRO100", "Santarem 1"
    fonte: str           # "pg" | "sunop" | "axis"
    fonte_ref: str       # pid no PG ("10") ou nome na SunOp ("MRO100")
    tz: str              # "America/Belem"
    kwp: float = 0.0
    kw_ac: float = 0.0
    lat: float | None = None
    lon: float | None = None

@dataclass(frozen=True)
class EquipRef:
    id: int
    usina_id: int
    tipo: str            # inversor | tracker | string | estacao | cabine
    codigo_fonte: str    # "INV_7", "TRK_17", "INV_7.I_PV3", "ESTM", "765"
    pai_id: int | None = None
    atributos: dict = field(default_factory=dict)   # numero, kwp, kw_ac, n_strings_esperadas...
```

---

## Fase A — Fundação

### Tarefa 1: Esqueleto do pacote, CLI e configuração com segredos

**Files:**
- Create: `gemeo/pyproject.toml`, `gemeo/config.toml`, `gemeo/README.md`, `gemeo/gemeo/__init__.py`, `gemeo/gemeo/cli.py`, `gemeo/gemeo/core/__init__.py`, `gemeo/gemeo/core/config.py`, `gemeo/gemeo/core/modelos.py` (código acima), `gemeo/tests/__init__.py`, `gemeo/tests/test_core_config.py`
- Move: `docs/superpowers/plans/golden/*.json` → `gemeo/tests/fixtures/golden/`

**Interfaces:**
- Produces: `Config` (dataclass congelada), `carregar(caminho_config: Path | None = None, secrets_dir: Path | None = None) -> Config`, `SegredoAusente(RuntimeError)`. Segredos em `SECRETS_DIR/gemeo.env`, linhas `CHAVE=VALOR`: `GEMEO_DB_DSN`, `POWERPLANTS_DSN`, `SUNOP_API_TOKEN`, `GRIDCO_SQL_TOKEN`, `GEMEO_SENHA`.

- [ ] **Passo 1: Escrever o teste que falha**

```python
# gemeo/tests/test_core_config.py
"""config.toml + SECRETS_DIR/gemeo.env viram um Config congelado. Segredo faltando falha NOMEANDO
a chave — a plataforma perdeu horas em 25/07 com um token velho 'sequestrando' a renovação em
silêncio; aqui, ausência é erro em voz alta."""
from pathlib import Path
import pytest
from gemeo.core.config import carregar, SegredoAusente

TOML = """
[usinas]
piloto = ["MRO100", "Santarem 1"]
[ritmo_min]
pg = 15
sunop_fino = 15
sunop_lento = 60
cadastro = 30
modelar = 15
[sunop]
teto_dia = 600
lote = 600
janela = ["05:40", "18:20"]
[ingest]
sobreposicao_min = 30
[modelar]
grade_min = 15
[app]
porta = 5070
[caminhos]
cache_dir = "cache"
"""
ENV = "GEMEO_DB_DSN=postgresql://g:g@localhost/gemeo\nPOWERPLANTS_DSN=postgresql://l:l@h/powerplants\nSUNOP_API_TOKEN=abc\nGRIDCO_SQL_TOKEN=def\nGEMEO_SENHA=s\n"


def _monta(tmp_path, env=ENV):
    (tmp_path / "config.toml").write_text(TOML, encoding="utf-8")
    (tmp_path / "gemeo.env").write_text(env, encoding="utf-8")
    return tmp_path


def test_carrega_config_e_segredos(tmp_path):
    d = _monta(tmp_path)
    cfg = carregar(d / "config.toml", secrets_dir=d)
    assert cfg.usinas_piloto == ("MRO100", "Santarem 1")
    assert cfg.ritmo_min["sunop_lento"] == 60
    assert cfg.teto_sunop_dia == 600 and cfg.lote_pathnames == 600
    assert cfg.janela_solar == ("05:40", "18:20")
    assert cfg.db_dsn.startswith("postgresql://g:g")
    assert cfg.sunop_token == "abc" and cfg.senha_app == "s"
    assert cfg.cache_dir == (d / "cache").resolve()


def test_segredo_ausente_nomeia_a_chave(tmp_path):
    d = _monta(tmp_path, env="GEMEO_DB_DSN=x\n")
    with pytest.raises(SegredoAusente) as e:
        carregar(d / "config.toml", secrets_dir=d)
    assert "POWERPLANTS_DSN" in str(e.value)


def test_config_e_imutavel(tmp_path):
    d = _monta(tmp_path)
    cfg = carregar(d / "config.toml", secrets_dir=d)
    with pytest.raises(Exception):
        cfg.teto_sunop_dia = 1  # type: ignore[misc]
```

- [ ] **Passo 2: Rodar para ver falhar**

Run: `cd gemeo && python -m pytest tests/test_core_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gemeo'`

- [ ] **Passo 3: Criar o pacote, o `pyproject.toml` e o `config.py`**

```toml
# gemeo/pyproject.toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "gemeo"
version = "0.1.0"
description = "Gemeo digital das usinas Grid Co - sombra digital (niveis 1-3)"
requires-python = ">=3.12"
dependencies = [
  "psycopg2-binary>=2.9", "pandas>=2.2", "numpy>=1.26", "pvlib>=0.11",
  "flask>=3.0", "waitress>=3.0", "requests>=2.31", "openpyxl>=3.1",
]
[project.optional-dependencies]
dev = ["pytest>=8"]
[project.scripts]
gemeo = "gemeo.cli:main"
[tool.setuptools.packages.find]
where = ["."]
include = ["gemeo*"]
[tool.pytest.ini_options]
testpaths = ["tests"]
```

```toml
# gemeo/config.toml — NÃO-SEGREDO. Segredos ficam em SECRETS_DIR/gemeo.env, fora do OneDrive.
[usinas]
piloto = ["MRO100", "Santarem 1"]
[ritmo_min]
pg = 15
sunop_fino = 15
sunop_lento = 60
cadastro = 30
modelar = 15
[sunop]
teto_dia = 600
lote = 600
janela = ["05:40", "18:20"]
[ingest]
sobreposicao_min = 30
[modelar]
grade_min = 15
[app]
porta = 5070
[caminhos]
cache_dir = "cache"
```

```python
# gemeo/gemeo/core/config.py
"""Configuração = config.toml (não-segredo, versionado) + SECRETS_DIR/gemeo.env (segredo, fora de
pasta sincronizada). Dois arquivos, dois donos — a mesma separação que a plataforma adotou depois de
o tokens.txt e o tokens_runtime.json se pisarem."""
from __future__ import annotations
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

SEGREDOS = ("GEMEO_DB_DSN", "POWERPLANTS_DSN", "SUNOP_API_TOKEN", "GRIDCO_SQL_TOKEN", "GEMEO_SENHA")


class SegredoAusente(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    db_dsn: str
    powerplants_dsn: str
    sunop_token: str
    bd_api_token: str
    senha_app: str
    usinas_piloto: tuple[str, ...]
    ritmo_min: dict[str, int]
    teto_sunop_dia: int
    lote_pathnames: int
    janela_solar: tuple[str, str]
    sobreposicao_min: int
    grade_min: int
    porta_app: int
    cache_dir: Path
    sunop_base: str = "https://gridco-api.sunop.net"
    bd_api_base: str = "https://app.gridco.com.br/db_performace"


def _ler_env(caminho: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not caminho.exists():
        return out
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        k, v = linha.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def carregar(caminho_config: Path | None = None, secrets_dir: Path | None = None) -> Config:
    caminho_config = Path(caminho_config or os.environ.get("GEMEO_CONFIG", "config.toml"))
    secrets_dir = Path(secrets_dir or os.environ.get("SECRETS_DIR", caminho_config.parent))
    t = tomllib.loads(caminho_config.read_text(encoding="utf-8"))
    env = {**_ler_env(secrets_dir / "gemeo.env"), **{k: v for k, v in os.environ.items() if k in SEGREDOS}}
    faltam = [k for k in SEGREDOS if not env.get(k)]
    if faltam:
        raise SegredoAusente(f"faltam em {secrets_dir / 'gemeo.env'}: {', '.join(faltam)}")
    cache = Path(t.get("caminhos", {}).get("cache_dir", "cache"))
    if not cache.is_absolute():
        cache = (caminho_config.parent / cache)
    return Config(
        db_dsn=env["GEMEO_DB_DSN"], powerplants_dsn=env["POWERPLANTS_DSN"],
        sunop_token=env["SUNOP_API_TOKEN"], bd_api_token=env["GRIDCO_SQL_TOKEN"], senha_app=env["GEMEO_SENHA"],
        usinas_piloto=tuple(t["usinas"]["piloto"]), ritmo_min=dict(t["ritmo_min"]),
        teto_sunop_dia=int(t["sunop"]["teto_dia"]), lote_pathnames=int(t["sunop"]["lote"]),
        janela_solar=tuple(t["sunop"]["janela"]), sobreposicao_min=int(t["ingest"]["sobreposicao_min"]),
        grade_min=int(t["modelar"]["grade_min"]), porta_app=int(t["app"]["porta"]), cache_dir=cache.resolve(),
    )
```

```python
# gemeo/gemeo/cli.py
"""`gemeo <comando>`. Cada comando importa só o que usa: o app não carrega pvlib, o ingest não carrega Flask."""
from __future__ import annotations
import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gemeo")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="aplica as migracoes SQL pendentes")
    sub.add_parser("ingest", help="laco de ingestao (tres fontes)")
    m = sub.add_parser("modelar", help="roda o modelo para as usinas do piloto")
    m.add_argument("--ini"); m.add_argument("--fim"); m.add_argument("--usina")
    c = sub.add_parser("calibrar", help="gera versao calibrada do modelo")
    c.add_argument("--usina", required=True); c.add_argument("--dias", type=int, default=45)
    sub.add_parser("app", help="sobe as telas (waitress)")
    ia = sub.add_parser("importar-alias", help="planilha de-para -> tabela alias")
    ia.add_argument("xlsx")
    sub.add_parser("inspecionar-cadastro", help="imprime os headers das abas do BD_Performance")
    a = p.parse_args(argv)
    if a.cmd == "migrate":
        from gemeo.core import db; from gemeo.core.config import carregar
        cfg = carregar(); conn = db.conectar(cfg.db_dsn)
        for nome in db.migrar(conn): print("aplicada", nome)
        return 0
    if a.cmd == "ingest":
        from gemeo.ingest.runner import rodar; return rodar()
    if a.cmd == "modelar":
        from gemeo.modelar.job import rodar_cli; return rodar_cli(a.ini, a.fim, a.usina)
    if a.cmd == "calibrar":
        from gemeo.modelar.calibrar import rodar_cli; return rodar_cli(a.usina, a.dias)
    if a.cmd == "app":
        from gemeo.app.server import servir; return servir()
    if a.cmd == "importar-alias":
        from tools.importar_alias import rodar_cli; return rodar_cli(a.xlsx)
    if a.cmd == "inspecionar-cadastro":
        from gemeo.ingest.cadastro import inspecionar_cli; return inspecionar_cli()
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

`gemeo/gemeo/__init__.py` e `gemeo/gemeo/core/__init__.py`: vazios. `gemeo/gemeo/core/modelos.py`: o código das interfaces compartilhadas acima. Mover as fixtures: `git mv docs/superpowers/plans/golden gemeo/tests/fixtures/golden`.

- [ ] **Passo 4: Instalar em modo editável e rodar os testes**

Run: `cd gemeo && python -m pip install -e ".[dev]" && python -m pytest tests/test_core_config.py -q`
Expected: 3 passed

- [ ] **Passo 5: Commit**

```bash
git add gemeo/ docs/superpowers/plans/
git commit -m "feat(gemeo): esqueleto do pacote, CLI e configuracao com segredos fora do OneDrive"
```

### Tarefa 2: Banco — conexão, migrações e o schema `gemeo`

**Files:**
- Create: `gemeo/gemeo/core/db.py`, `gemeo/migrations/0001_schema.sql`, `gemeo/tests/conftest.py`, `gemeo/tests/test_core_db_migracoes.py`

**Interfaces:**
- Consumes: `Config.db_dsn` (Tarefa 1).
- Produces: `conectar(dsn: str)` → conexão psycopg2 com `search_path=gemeo,public`; `migrar(conn, pasta: Path | None = None) -> list[str]` (nomes aplicados nesta chamada; idempotente via tabela `gemeo.schema_migrations`); fixture pytest `conn` (schema `gemeo` recriado por sessão em `GEMEO_TEST_DSN`; testes de banco são **pulados** sem a variável — não falham).

- [ ] **Passo 1: Escrever o teste que falha**

```python
# gemeo/tests/conftest.py
"""Banco de teste = GEMEO_TEST_DSN (um PostgreSQL local). Sem a variável, os testes de banco são
PULADOS e não falham: a máquina do analista não tem PostgreSQL (verificado 03/09) e a suíte de
modelo/gate/decomposição — que é pandas puro — precisa rodar mesmo assim."""
import os
import pytest
import psycopg2

DSN = os.environ.get("GEMEO_TEST_DSN")


@pytest.fixture(scope="session")
def conn():
    if not DSN:
        pytest.skip("GEMEO_TEST_DSN nao definido: sem PostgreSQL de teste")
    c = psycopg2.connect(DSN)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS gemeo CASCADE; CREATE SCHEMA gemeo;")
    c.autocommit = False
    from gemeo.core import db
    with c.cursor() as cur:
        cur.execute("SET search_path TO gemeo, public")
    db.migrar(c)
    yield c
    c.close()
```

```python
# gemeo/tests/test_core_db_migracoes.py
from pathlib import Path
from gemeo.core import db

TABELAS = {"usina", "equipamento", "alias", "leitura", "ingest_run", "modelo", "esperado",
           "cascata_dia", "perda_dia", "evento", "meta_mes", "estado", "schema_migrations"}


def test_migrar_cria_todas_as_tabelas(conn):
    with conn.cursor() as cur:
        cur.execute("select table_name from information_schema.tables where table_schema='gemeo'")
        assert TABELAS <= {r[0] for r in cur.fetchall()}


def test_migrar_e_idempotente(conn):
    assert db.migrar(conn) == []          # segunda chamada: nada a aplicar


def test_leitura_tem_chave_natural(conn):
    with conn.cursor() as cur:
        cur.execute("""select count(*) from information_schema.table_constraints
                       where table_schema='gemeo' and table_name='leitura' and constraint_type='PRIMARY KEY'""")
        assert cur.fetchone()[0] == 1
```

- [ ] **Passo 2: Rodar para ver falhar**

Run: `cd gemeo && set GEMEO_TEST_DSN=postgresql://postgres:postgres@localhost:5432/gemeo_test && python -m pytest tests/test_core_db_migracoes.py -q`
Expected: FAIL — `ImportError: cannot import name 'db'` (sem a variável: 3 skipped)

- [ ] **Passo 3: Escrever o schema e o `db.py`**

```sql
-- gemeo/migrations/0001_schema.sql
-- Schema da Sombra Digital. Convencoes: todo ts e timestamptz em UTC (fuso na usina);
-- chave natural em tudo; leitura particionada por mes; nada aqui e ORM.
CREATE TABLE IF NOT EXISTS schema_migrations (nome text PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS usina (
  id            serial PRIMARY KEY,
  codigo        text NOT NULL UNIQUE,            -- 'MRO100', 'Santarem 1'
  nome          text NOT NULL,
  fonte         text NOT NULL CHECK (fonte IN ('pg','sunop','axis','apipv','solaredge','owen')),
  fonte_ref     text NOT NULL,                   -- pid no PG ou nome na SunOp
  cliente       text,
  lat           double precision, lon double precision,
  tz            text NOT NULL DEFAULT 'America/Sao_Paulo',
  kwp_dc        double precision, kw_ac double precision,
  n_inversores  int,
  full_om       boolean NOT NULL DEFAULT false,
  ativo         boolean NOT NULL DEFAULT true,
  criado_em     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (fonte, fonte_ref)
);

CREATE TABLE IF NOT EXISTS equipamento (
  id             serial PRIMARY KEY,
  usina_id       int NOT NULL REFERENCES usina(id),
  tipo           text NOT NULL CHECK (tipo IN ('inversor','tracker','string','estacao','cabine')),
  codigo_fonte   text NOT NULL,                  -- 'INV_7', 'TRK_17', 'INV_7.I_PV3', 'ESTM', '765'
  nome_exibicao  text,
  pai_id         int REFERENCES equipamento(id),
  atributos      jsonb NOT NULL DEFAULT '{}'::jsonb,   -- numero, kwp, kw_ac, n_strings_esperadas...
  descoberto_em  timestamptz NOT NULL DEFAULT now(),
  ativo          boolean NOT NULL DEFAULT true,
  UNIQUE (usina_id, tipo, codigo_fonte)
);
CREATE INDEX IF NOT EXISTS equipamento_pai ON equipamento(pai_id);

CREATE TABLE IF NOT EXISTS alias (
  id             serial PRIMARY KEY,
  usina_id       int REFERENCES usina(id),
  equipamento_id int REFERENCES equipamento(id),
  sistema        text NOT NULL CHECK (sistema IN ('fracttal','bd_performance','bd_trackers','sunop','apipv','pg')),
  valor          text NOT NULL,
  confianca      text NOT NULL CHECK (confianca IN ('direto','contagem','ordem','limite_skid','manual')),
  origem         text NOT NULL,
  criado_em      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (sistema, valor),
  CHECK (usina_id IS NOT NULL OR equipamento_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS leitura (
  equipamento_id int NOT NULL,
  medida         text NOT NULL CHECK (medida IN ('poa','ghi','temp_modulo','temp_ar','vento','p_ac','e_dia',
                                                 'i_string','angulo','angulo_alvo','estado')),
  ts             timestamptz NOT NULL,
  valor          double precision NOT NULL,
  PRIMARY KEY (equipamento_id, medida, ts)
) PARTITION BY RANGE (ts);
-- particoes mensais: o ingest cria a do mes corrente e a do proximo ao subir (ver db.garantir_particoes)
CREATE TABLE IF NOT EXISTS leitura_default PARTITION OF leitura DEFAULT;
CREATE INDEX IF NOT EXISTS leitura_eq_med_ts ON leitura (equipamento_id, medida, ts DESC);

CREATE TABLE IF NOT EXISTS ingest_run (
  id             serial PRIMARY KEY,
  fonte          text NOT NULL,
  usina_id       int REFERENCES usina(id),
  ini            timestamptz NOT NULL, fim timestamptz NOT NULL,
  status         text NOT NULL CHECK (status IN ('ok','parcial','falha')),
  n_linhas       int NOT NULL DEFAULT 0,
  n_requisicoes  int NOT NULL DEFAULT 0,
  duracao_s      double precision NOT NULL DEFAULT 0,
  cobertura      double precision NOT NULL DEFAULT 0,
  erro           text,
  criado_em      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ingest_run_fonte_ts ON ingest_run (fonte, criado_em DESC);

CREATE TABLE IF NOT EXISTS modelo (
  id            serial PRIMARY KEY,
  usina_id      int NOT NULL REFERENCES usina(id),
  versao        text NOT NULL,                   -- 'placa', 'cal-2026-10-15'
  parametros    jsonb NOT NULL,                  -- pac0_kw, gamma, perdas_fixas, eta_inv, pac0_inferido, gate{}
  tolerancia    double precision NOT NULL DEFAULT 0.08,
  calibrado     boolean NOT NULL DEFAULT false,
  calibrado_em  timestamptz,
  metrica       jsonb NOT NULL DEFAULT '{}'::jsonb,
  ativo         boolean NOT NULL DEFAULT false,
  criado_em     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (usina_id, versao)
);
CREATE UNIQUE INDEX IF NOT EXISTS modelo_um_ativo_por_usina ON modelo (usina_id) WHERE ativo;

CREATE TABLE IF NOT EXISTS esperado (
  equipamento_id int NOT NULL,
  ts             timestamptz NOT NULL,
  modelo_id      int NOT NULL REFERENCES modelo(id),
  p_esperado_kw  double precision,
  poa_usada      double precision, temp_usada double precision,
  gate           text NOT NULL CHECK (gate IN ('ok','poa_ghi','cobertura','plausibilidade')),
  PRIMARY KEY (equipamento_id, ts, modelo_id)
);

CREATE TABLE IF NOT EXISTS cascata_dia (
  usina_id       int NOT NULL REFERENCES usina(id),
  dia            date NOT NULL,
  modelo_id      int NOT NULL REFERENCES modelo(id),
  e_esperado     double precision NOT NULL, e_medido double precision NOT NULL, delta double precision NOT NULL,
  inv_parado     double precision NOT NULL DEFAULT 0, tracker double precision NOT NULL DEFAULT 0,
  string         double precision NOT NULL DEFAULT 0, residuo double precision NOT NULL DEFAULT 0,
  cobertura_gate double precision NOT NULL DEFAULT 0,
  trackers_sem_inversor int NOT NULL DEFAULT 0,
  PRIMARY KEY (usina_id, dia, modelo_id)
);

CREATE TABLE IF NOT EXISTS perda_dia (
  equipamento_id int NOT NULL REFERENCES equipamento(id),
  dia            date NOT NULL,
  modelo_id      int NOT NULL REFERENCES modelo(id),
  parcela        text NOT NULL CHECK (parcela IN ('inv_parado','tracker','string','residuo')),
  kwh            double precision NOT NULL,
  PRIMARY KEY (equipamento_id, dia, modelo_id, parcela)
);

CREATE TABLE IF NOT EXISTS evento (
  id             serial PRIMARY KEY,
  usina_id       int NOT NULL REFERENCES usina(id),
  equipamento_id int REFERENCES equipamento(id),
  modelo_id      int REFERENCES modelo(id),
  tipo           text NOT NULL CHECK (tipo IN ('inversor_parado','inversor_abaixo','tracker_fora_alvo',
                                               'string_sem_corrente','sensor_em_falha','sem_cobertura')),
  ini            timestamptz NOT NULL, fim timestamptz,
  severidade     text NOT NULL CHECK (severidade IN ('leve','media','grave')),
  kwh            double precision NOT NULL DEFAULT 0,
  detalhe        jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (usina_id, equipamento_id, tipo, ini)
);

CREATE TABLE IF NOT EXISTS meta_mes (
  usina_id       int NOT NULL REFERENCES usina(id),
  ano int NOT NULL, mes int NOT NULL,
  pr_previsto    double precision, ipoa_previsto double precision, p50_mwh double precision,
  disp_alvo      double precision, preco_mwh double precision,
  PRIMARY KEY (usina_id, ano, mes)
);

-- estado pequeno dos ingestores (ex.: updated_at do workbook que o cadastro viu por ultimo)
CREATE TABLE IF NOT EXISTS estado (chave text PRIMARY KEY, valor text NOT NULL, atualizado_em timestamptz NOT NULL DEFAULT now());
```

```python
# gemeo/gemeo/core/db.py
"""Acesso ao banco do gemeo: conexao, migracoes em SQL puro, e os poucos upserts que valem regra.
SQL puro de proposito — quem for depurar as 23h precisa ler o schema, nao um ORM."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
from typing import Iterable
import psycopg2
import psycopg2.extras

PASTA_MIGRACOES = Path(__file__).resolve().parents[2] / "migrations"


def conectar(dsn: str):
    conn = psycopg2.connect(dsn, options="-c search_path=gemeo,public")
    conn.autocommit = False
    return conn


def migrar(conn, pasta: Path | None = None) -> list[str]:
    """Aplica em ordem os .sql ainda nao registrados em schema_migrations. Idempotente."""
    pasta = pasta or PASTA_MIGRACOES
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS gemeo")
        cur.execute("CREATE TABLE IF NOT EXISTS gemeo.schema_migrations (nome text PRIMARY KEY, aplicada_em timestamptz NOT NULL DEFAULT now())")
        cur.execute("SELECT nome FROM gemeo.schema_migrations")
        feitas = {r[0] for r in cur.fetchall()}
        aplicadas = []
        for arq in sorted(pasta.glob("*.sql")):
            if arq.name in feitas:
                continue
            cur.execute(arq.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO gemeo.schema_migrations (nome) VALUES (%s)", (arq.name,))
            aplicadas.append(arq.name)
    conn.commit()
    return aplicadas


def garantir_particoes(conn, meses: Iterable[dt.date]) -> None:
    """Cria a particao mensal de leitura para cada mes pedido (o ingest chama para o mes corrente e o
    proximo). Sem particao, a linha cai na DEFAULT — funciona, mas a retencao por mes deixa de ser um DROP."""
    with conn.cursor() as cur:
        for m in meses:
            ini = m.replace(day=1)
            fim = (ini.replace(year=ini.year + (ini.month // 12), month=ini.month % 12 + 1))
            nome = f"leitura_{ini:%Y_%m}"
            cur.execute(f"CREATE TABLE IF NOT EXISTS {nome} PARTITION OF leitura FOR VALUES FROM (%s) TO (%s)", (ini, fim))
    conn.commit()
```

- [ ] **Passo 4: Rodar os testes**

Run (com PostgreSQL): `cd gemeo && python -m pytest tests/test_core_db_migracoes.py -q` → Expected: 3 passed. Sem PostgreSQL: 3 skipped.

- [ ] **Passo 5: Commit**

```bash
git add gemeo/gemeo/core/db.py gemeo/migrations/0001_schema.sql gemeo/tests/conftest.py gemeo/tests/test_core_db_migracoes.py
git commit -m "feat(gemeo): schema gemeo em SQL versionado e runner de migracoes idempotente"
```

### Tarefa 3: Upsert de leituras, `ingest_run` e marca d'água

**Files:**
- Modify: `gemeo/gemeo/core/db.py` (acrescentar funções abaixo de `garantir_particoes`)
- Create: `gemeo/tests/test_core_db_upsert.py`

**Interfaces:**
- Produces: `upsert_leituras(conn, linhas: Iterable[tuple[int, str, dt.datetime, float | None]]) -> int` (linhas com `valor None` são **ignoradas**, nunca gravadas); `registrar_ingest_run(conn, fonte, usina_id, ini, fim, status, n_linhas=0, n_requisicoes=0, duracao_s=0.0, cobertura=0.0, erro=None) -> int`; `marca_dagua(conn, usina_id: int) -> dt.datetime | None` (maior `ts` de leitura da usina); `requisicoes_hoje(conn, fonte: str, dia_utc: dt.date) -> int`; `ler_estado(conn, chave) -> str | None`; `gravar_estado(conn, chave, valor)`.

- [ ] **Passo 1: Escrever o teste que falha**

```python
# gemeo/tests/test_core_db_upsert.py
"""'Vazio nunca sobrescreve' como PROPRIEDADE da escrita, nao como cuidado de quem chama. A plataforma
aprendeu isso com o pg_trk congelado 33h e com o _sunop_str_med_ent cacheando foto vazia."""
import datetime as dt
import pytest
from gemeo.core import db

UTC = dt.timezone.utc


@pytest.fixture
def usina_eq(conn):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz) VALUES ('T1','Teste','pg','1','America/Belem') RETURNING id")
        u = cur.fetchone()[0]
        cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte) VALUES (%s,'inversor','INV_1') RETURNING id", (u,))
        e = cur.fetchone()[0]
    conn.commit()
    yield u, e
    with conn.cursor() as cur:
        cur.execute("DELETE FROM leitura; DELETE FROM ingest_run; DELETE FROM equipamento; DELETE FROM usina")
    conn.commit()


def test_none_nunca_sobrescreve_valor(conn, usina_eq):
    _, e = usina_eq
    ts = dt.datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    assert db.upsert_leituras(conn, [(e, "p_ac", ts, 150.0)]) == 1
    assert db.upsert_leituras(conn, [(e, "p_ac", ts, None)]) == 0
    with conn.cursor() as cur:
        cur.execute("SELECT valor FROM leitura WHERE equipamento_id=%s", (e,))
        assert cur.fetchone()[0] == pytest.approx(150.0)


def test_valor_novo_vence_na_colisao(conn, usina_eq):
    _, e = usina_eq
    ts = dt.datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    db.upsert_leituras(conn, [(e, "p_ac", ts, 150.0)])
    db.upsert_leituras(conn, [(e, "p_ac", ts, 151.5)])
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), max(valor) FROM leitura WHERE equipamento_id=%s", (e,))
        n, v = cur.fetchone()
    assert n == 1 and v == pytest.approx(151.5)


def test_marca_dagua_e_o_maior_ts_da_usina(conn, usina_eq):
    u, e = usina_eq
    assert db.marca_dagua(conn, u) is None
    t1 = dt.datetime(2026, 9, 1, 12, 0, tzinfo=UTC); t2 = t1 + dt.timedelta(minutes=15)
    db.upsert_leituras(conn, [(e, "p_ac", t2, 1.0), (e, "p_ac", t1, 1.0)])
    assert db.marca_dagua(conn, u) == t2


def test_ingest_run_e_requisicoes_hoje(conn, usina_eq):
    u, _ = usina_eq
    hoje = dt.datetime.now(UTC)
    db.registrar_ingest_run(conn, "sunop", u, hoje, hoje, "ok", n_linhas=10, n_requisicoes=3, duracao_s=1.2, cobertura=1.0)
    db.registrar_ingest_run(conn, "sunop", u, hoje, hoje, "falha", n_requisicoes=1, erro="403 borda")
    assert db.requisicoes_hoje(conn, "sunop", hoje.date()) == 4
    assert db.requisicoes_hoje(conn, "pg", hoje.date()) == 0


def test_estado_pequeno(conn):
    assert db.ler_estado(conn, "cadastro.updated_at") is None
    db.gravar_estado(conn, "cadastro.updated_at", "2026-09-02T14:51")
    db.gravar_estado(conn, "cadastro.updated_at", "2026-09-03T08:00")
    assert db.ler_estado(conn, "cadastro.updated_at") == "2026-09-03T08:00"
```

- [ ] **Passo 2: Rodar para ver falhar**

Run: `cd gemeo && python -m pytest tests/test_core_db_upsert.py -q` → Expected: FAIL `AttributeError: module 'gemeo.core.db' has no attribute 'upsert_leituras'` (ou 5 skipped sem PostgreSQL)

- [ ] **Passo 3: Implementar (acrescentar ao final de `db.py`)**

```python
def upsert_leituras(conn, linhas: Iterable[tuple[int, str, dt.datetime, float | None]]) -> int:
    """Grava (equipamento, medida, ts, valor). Valor None e DESCARTADO antes de chegar ao banco — e a
    propriedade 'vazio nunca sobrescreve'. Na colisao, o valor novo vence (correcao tardia da fonte)."""
    validas = [(e, m, ts, float(v)) for e, m, ts, v in linhas if v is not None]
    if not validas:
        return 0
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO leitura (equipamento_id, medida, ts, valor) VALUES %s "
            "ON CONFLICT (equipamento_id, medida, ts) DO UPDATE SET valor = EXCLUDED.valor",
            validas, page_size=5000)
    conn.commit()
    return len(validas)


def registrar_ingest_run(conn, fonte: str, usina_id: int | None, ini: dt.datetime, fim: dt.datetime, status: str,
                         n_linhas: int = 0, n_requisicoes: int = 0, duracao_s: float = 0.0,
                         cobertura: float = 0.0, erro: str | None = None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingest_run (fonte, usina_id, ini, fim, status, n_linhas, n_requisicoes, duracao_s, cobertura, erro) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (fonte, usina_id, ini, fim, status, n_linhas, n_requisicoes, duracao_s, cobertura, erro))
        rid = cur.fetchone()[0]
    conn.commit()
    return rid


def marca_dagua(conn, usina_id: int) -> dt.datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT max(l.ts) FROM leitura l JOIN equipamento e ON e.id = l.equipamento_id WHERE e.usina_id = %s", (usina_id,))
        return cur.fetchone()[0]


def requisicoes_hoje(conn, fonte: str, dia_utc: dt.date) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT coalesce(sum(n_requisicoes),0) FROM ingest_run WHERE fonte=%s AND (criado_em AT TIME ZONE 'UTC')::date = %s", (fonte, dia_utc))
        return int(cur.fetchone()[0])


def ler_estado(conn, chave: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT valor FROM estado WHERE chave=%s", (chave,))
        r = cur.fetchone()
        return r[0] if r else None


def gravar_estado(conn, chave: str, valor: str) -> None:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO estado (chave, valor) VALUES (%s,%s) ON CONFLICT (chave) DO UPDATE SET valor=EXCLUDED.valor, atualizado_em=now()", (chave, valor))
    conn.commit()
```

- [ ] **Passo 4: Rodar os testes** — `python -m pytest tests/test_core_db_upsert.py -q` → 5 passed (ou 5 skipped)

- [ ] **Passo 5: Commit**

```bash
git add gemeo/gemeo/core/db.py gemeo/tests/test_core_db_upsert.py
git commit -m "feat(gemeo): upsert de leituras que nunca grava vazio, ingest_run e marca d'agua"
```

### Tarefa 4: Tempo — grade de 15 min, janela incremental, fuso da usina

**Files:**
- Create: `gemeo/gemeo/core/tempo.py`, `gemeo/tests/test_core_tempo.py`

**Interfaces:**
- Produces: `GRADE_MIN = 15`; `piso_grade(ts: datetime, minutos: int = 15) -> datetime`; `janela(agora: datetime, marca: datetime | None, sobreposicao_min: int, reconciliar: bool = False, dias_iniciais: int = 3) -> tuple[datetime, datetime]`; `dia_local(ts: datetime, tz: str) -> date`; `dentro_janela_solar(agora: datetime, tz: str, janela: tuple[str, str]) -> bool`. Todos os `datetime` são **aware** (UTC); passar naive levanta `ValueError`.

- [ ] **Passo 1: Escrever o teste que falha**

```python
# gemeo/tests/test_core_tempo.py
"""Tudo em UTC aware. Naive levanta erro: foi um filtro sem fuso que zerou o resultado em silencio
no dbt ('ultimas 2 horas' caiu no futuro)."""
import datetime as dt
import pytest
from gemeo.core import tempo

UTC = dt.timezone.utc


def test_piso_grade_arredonda_para_baixo():
    assert tempo.piso_grade(dt.datetime(2026, 9, 3, 12, 14, 59, tzinfo=UTC)) == dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
    assert tempo.piso_grade(dt.datetime(2026, 9, 3, 12, 15, tzinfo=UTC)) == dt.datetime(2026, 9, 3, 12, 15, tzinfo=UTC)


def test_naive_e_erro():
    with pytest.raises(ValueError):
        tempo.piso_grade(dt.datetime(2026, 9, 3, 12, 0))


def test_janela_sem_marca_volta_dias_iniciais():
    agora = dt.datetime(2026, 9, 3, 12, 7, tzinfo=UTC)
    ini, fim = tempo.janela(agora, None, sobreposicao_min=30, dias_iniciais=3)
    assert ini == agora - dt.timedelta(days=3) and fim == agora


def test_janela_incremental_volta_a_sobreposicao():
    agora = dt.datetime(2026, 9, 3, 12, 7, tzinfo=UTC)
    marca = dt.datetime(2026, 9, 3, 11, 45, tzinfo=UTC)
    ini, fim = tempo.janela(agora, marca, sobreposicao_min=30)
    assert ini == dt.datetime(2026, 9, 3, 11, 15, tzinfo=UTC) and fim == agora


def test_janela_reconciliar_volta_24h():
    agora = dt.datetime(2026, 9, 3, 12, 7, tzinfo=UTC)
    ini, _ = tempo.janela(agora, agora - dt.timedelta(minutes=10), sobreposicao_min=30, reconciliar=True)
    assert ini == agora - dt.timedelta(hours=24)


def test_dia_local_usa_o_fuso_da_usina():
    # 02:30 UTC de 04/09 ainda e 23:30 de 03/09 em Belem (UTC-3)
    assert tempo.dia_local(dt.datetime(2026, 9, 4, 2, 30, tzinfo=UTC), "America/Belem") == dt.date(2026, 9, 3)


def test_janela_solar():
    j = ("05:40", "18:20")
    assert tempo.dentro_janela_solar(dt.datetime(2026, 9, 3, 15, 0, tzinfo=UTC), "America/Belem", j)     # 12:00 local
    assert not tempo.dentro_janela_solar(dt.datetime(2026, 9, 3, 23, 0, tzinfo=UTC), "America/Belem", j) # 20:00 local
```

- [ ] **Passo 2: Rodar para ver falhar** — `python -m pytest tests/test_core_tempo.py -q` → `ModuleNotFoundError: gemeo.core.tempo`

- [ ] **Passo 3: Implementar**

```python
# gemeo/gemeo/core/tempo.py
"""Tempo: grade de 15 min, janela incremental e fuso da usina. Tudo aware em UTC — naive e erro."""
from __future__ import annotations
import datetime as dt
from zoneinfo import ZoneInfo

GRADE_MIN = 15


def _exige_aware(ts: dt.datetime) -> None:
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError(f"timestamp sem fuso: {ts!r} — tudo no gemeo e aware em UTC")


def piso_grade(ts: dt.datetime, minutos: int = GRADE_MIN) -> dt.datetime:
    _exige_aware(ts)
    return ts.replace(minute=(ts.minute // minutos) * minutos, second=0, microsecond=0)


def janela(agora: dt.datetime, marca: dt.datetime | None, sobreposicao_min: int,
           reconciliar: bool = False, dias_iniciais: int = 3) -> tuple[dt.datetime, dt.datetime]:
    """Inicio da busca: sem marca d'agua = `dias_iniciais` para tras (primeiro ciclo de uma usina);
    com marca = marca menos a sobreposicao (a ingestao das fontes atrasa); reconciliar = 24h inteiras,
    uma vez por dia, para pegar correcao feita la atras."""
    _exige_aware(agora)
    if reconciliar:
        return agora - dt.timedelta(hours=24), agora
    if marca is None:
        return agora - dt.timedelta(days=dias_iniciais), agora
    _exige_aware(marca)
    return marca - dt.timedelta(minutes=sobreposicao_min), agora


def dia_local(ts: dt.datetime, tz: str) -> dt.date:
    _exige_aware(ts)
    return ts.astimezone(ZoneInfo(tz)).date()


def dentro_janela_solar(agora: dt.datetime, tz: str, janela_hm: tuple[str, str]) -> bool:
    _exige_aware(agora)
    local = agora.astimezone(ZoneInfo(tz))
    h0, m0 = map(int, janela_hm[0].split(":")); h1, m1 = map(int, janela_hm[1].split(":"))
    minuto = local.hour * 60 + local.minute
    return h0 * 60 + m0 <= minuto <= h1 * 60 + m1
```

- [ ] **Passo 4: Rodar** — 7 passed. **Passo 5: Commit** — `git commit -m "feat(gemeo): grade de 15 min, janela incremental e fuso da usina, tudo aware em UTC"`

### Tarefa 5: Alias — o de-para como dado, e a importação da planilha de trackers

**Files:**
- Create: `gemeo/gemeo/core/alias.py`, `gemeo/tools/__init__.py`, `gemeo/tools/importar_alias.py`, `gemeo/tests/test_core_alias.py`

**Interfaces:**
- Produces: `CONFIANCAS = ("direto","contagem","ordem","limite_skid","manual")`; `resolver(conn, sistema: str, valor: str) -> int | None` (equipamento_id); `gravar(conn, sistema, valor, confianca, origem, equipamento_id=None, usina_id=None) -> int` (upsert por `(sistema, valor)`); `tools.importar_alias.ler_planilha(caminho) -> list[LinhaAlias]` (puro, sem banco) e `importar(conn, linhas) -> dict` com contagens. `LinhaAlias(usina_sup, tracker_sup, numero, code_fracttal, confianca)`.
- Mapeamento da coluna "Como casou" da planilha → `confianca`: `direto`→`direto`; `por contagem da sub-usina`→`contagem`; `por skid da planilha BD_Trackers`→`contagem`; `por ordem da sub-usina (CONFIRMAR)`→`ordem`; `por bloco na serie unica (CONFIRMAR)`→`ordem`; `por limite dos skids...`→`limite_skid`. Linha sem `Code Fracttal` é ignorada.

- [ ] **Passo 1: Escrever o teste que falha**

```python
# gemeo/tests/test_core_alias.py
"""O de-para e DADO com confianca, nao codigo. A planilha docs/de-para-trackers-supervisorio-fracttal.xlsx
(4.313 pares, 03/09) entra linha a linha; a coluna 'Como casou' vira a confianca."""
import openpyxl
from tools.importar_alias import ler_planilha, CONFIANCA_POR_COMO_CASOU


def _xlsx(tmp_path):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "De-Para Trackers"
    ws.append(["Fonte", "UFV Supervisório", "UFV Fracttal", "Tracker Supervisório", "Tracker Fracttal", "Code Fracttal", "Cabine (Fracttal)", "Como casou", "Observação"])
    ws.append(["Athon (SunOp)", "MRO100", "Athon - Mãe do Rio 1 - PA", "TRK_7", "Tracker 7", "MRO100-ETKR7.101", "101", "por limite dos skids (CONFIRMAR)", ""])
    ws.append(["API PV", "Guatambu 2 (129)", "Thopen - Guatambú 1 - SC", "TRK11", "Tracker 1.101", "THPN-GTB100-ETKR1.101", "101", "por contagem da sub-usina", ""])
    ws.append(["API PV", "Junco 2.3 (136)", "Thopen - Junco 1 - PI", "TRK5", "", "", "", "", "excedente do supervisorio - este tracker nao existe no Fracttal"])
    p = tmp_path / "depara.xlsx"; wb.save(p); return p


def test_le_planilha_e_mapeia_confianca(tmp_path):
    linhas = ler_planilha(_xlsx(tmp_path))
    assert len(linhas) == 2                         # a linha sem code e ignorada
    a, b = linhas
    assert (a.usina_sup, a.tracker_sup, a.numero, a.code_fracttal, a.confianca) == ("MRO100", "TRK_7", 7, "MRO100-ETKR7.101", "limite_skid")
    assert (b.numero, b.confianca) == (11, "contagem")


def test_todo_como_casou_conhecido_tem_confianca():
    assert set(CONFIANCA_POR_COMO_CASOU.values()) <= {"direto", "contagem", "ordem", "limite_skid", "manual"}
```

- [ ] **Passo 2: Rodar para ver falhar** — `ModuleNotFoundError: tools.importar_alias`

- [ ] **Passo 3: Implementar**

```python
# gemeo/gemeo/core/alias.py
"""O de-para entre sistemas como dado de primeira classe, com confianca. E o '7o de-para' que a
sondagem do Fracttal pediu — sem ele, falha e telemetria nao se cruzam."""
from __future__ import annotations

CONFIANCAS = ("direto", "contagem", "ordem", "limite_skid", "manual")


def resolver(conn, sistema: str, valor: str) -> int | None:
    with conn.cursor() as cur:
        cur.execute("SELECT equipamento_id FROM alias WHERE sistema=%s AND valor=%s", (sistema, valor))
        r = cur.fetchone()
        return r[0] if r else None


def gravar(conn, sistema: str, valor: str, confianca: str, origem: str,
           equipamento_id: int | None = None, usina_id: int | None = None) -> int:
    if confianca not in CONFIANCAS:
        raise ValueError(f"confianca invalida: {confianca}")
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO alias (usina_id, equipamento_id, sistema, valor, confianca, origem) VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (sistema, valor) DO UPDATE SET equipamento_id=EXCLUDED.equipamento_id, usina_id=EXCLUDED.usina_id, "
            "confianca=EXCLUDED.confianca, origem=EXCLUDED.origem RETURNING id",
            (usina_id, equipamento_id, sistema, valor, confianca, origem))
        rid = cur.fetchone()[0]
    conn.commit()
    return rid
```

```python
# gemeo/tools/importar_alias.py
"""Planilha de-para trackers (supervisorio x Fracttal) -> tabela alias. Leitura pura, gravacao a parte."""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path

CONFIANCA_POR_COMO_CASOU = {
    "direto": "direto",
    "por contagem da sub-usina": "contagem",
    "por skid da planilha bd_trackers": "contagem",
    "por ordem da sub-usina (confirmar)": "ordem",
    "por bloco na serie unica (confirmar)": "ordem",
    "por limite dos skids (confirmar)": "limite_skid",
    "por limite dos skids, ordem do mab100": "limite_skid",
}


@dataclass(frozen=True)
class LinhaAlias:
    usina_sup: str
    tracker_sup: str
    numero: int
    code_fracttal: str
    confianca: str


def _numero(nome: str) -> int | None:
    m = re.search(r"(\d+)", str(nome or ""))
    return int(m.group(1)) if m else None


def ler_planilha(caminho: Path) -> list[LinhaAlias]:
    import openpyxl
    ws = openpyxl.load_workbook(caminho, read_only=True)["De-Para Trackers"]
    linhas = iter(ws.iter_rows(values_only=True))
    cab = [str(c or "").strip() for c in next(linhas)]
    col = {n: cab.index(n) for n in ("UFV Supervisório", "Tracker Supervisório", "Code Fracttal", "Como casou")}
    out = []
    for r in linhas:
        code = str(r[col["Code Fracttal"]] or "").strip()
        if not code:
            continue
        como = str(r[col["Como casou"]] or "").strip().lower()
        conf = CONFIANCA_POR_COMO_CASOU.get(como, "manual")
        num = _numero(r[col["Tracker Supervisório"]])
        if num is None:
            continue
        out.append(LinhaAlias(str(r[col["UFV Supervisório"]]).strip(), str(r[col["Tracker Supervisório"]]).strip(), num, code, conf))
    return out


def importar(conn, linhas: list[LinhaAlias]) -> dict:
    """Casa cada linha com o tracker da usina pelo NUMERO (equipamento.atributos->>'numero') e grava
    alias(sistema='fracttal', valor=code). Usina e resolvida pelo alias 'bd_performance' do nome do
    supervisorio, ou pelo codigo da usina."""
    from gemeo.core import alias as al
    n_ok = n_sem_usina = n_sem_trk = 0
    with conn.cursor() as cur:
        for ln in linhas:
            cur.execute("SELECT id FROM usina WHERE codigo=%s", (ln.usina_sup,))
            r = cur.fetchone()
            if not r:
                cur.execute("SELECT usina_id FROM alias WHERE sistema='bd_performance' AND valor=%s AND usina_id IS NOT NULL", (ln.usina_sup,))
                r = cur.fetchone()
            if not r:
                n_sem_usina += 1; continue
            cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='tracker' AND (atributos->>'numero')::int=%s", (r[0], ln.numero))
            e = cur.fetchone()
            if not e:
                n_sem_trk += 1; continue
            al.gravar(conn, "fracttal", ln.code_fracttal, ln.confianca, "planilha de-para 03/09/2026", equipamento_id=e[0], usina_id=r[0])
            n_ok += 1
    return {"gravados": n_ok, "sem_usina": n_sem_usina, "sem_tracker": n_sem_trk}


def rodar_cli(xlsx: str) -> int:
    from gemeo.core import db
    from gemeo.core.config import carregar
    cfg = carregar(); conn = db.conectar(cfg.db_dsn)
    print(importar(conn, ler_planilha(Path(xlsx))))
    return 0
```

`gemeo/tools/__init__.py`: vazio.

- [ ] **Passo 4: Rodar** — `python -m pytest tests/test_core_alias.py -q` → 2 passed. **Passo 5: Commit** — `git commit -m "feat(gemeo): alias como dado com confianca e importacao da planilha de-para"`

## Fase B — Conectores

### Tarefa 6: Ingestor base — ciclo, marca d'água, disjuntor e o contrato `ingest_run`

**Files:**
- Create: `gemeo/gemeo/ingest/__init__.py`, `gemeo/gemeo/ingest/base.py`, `gemeo/tests/test_ingest_base.py`

**Interfaces:**
- Consumes: `db.marca_dagua`, `db.upsert_leituras`, `db.registrar_ingest_run` (Tarefa 3); `tempo.janela` (Tarefa 4); `UsinaRef` (Tarefa 1).
- Produces: `Busca(leituras: list[tuple[int,str,datetime,float]], n_requisicoes: int = 0, esperadas: int = 0)`; `Disjuntor(pausa_s: float)` com `aberto() -> bool` e `abrir(motivo: str)`; `class Ingestor` com atributo `fonte`, `__init__(cfg, conn, usinas: list[UsinaRef])`, métodos abstratos `descobrir(usina) -> None` e `buscar(usina, ini, fim) -> Busca`, e `ciclo(agora: datetime | None = None, reconciliar: bool = False) -> list[int]` (ids de `ingest_run`). Regras do ciclo: disjuntor aberto → run `falha` com erro `disjuntor`, sem chamar `buscar`; exceção em `buscar` → run `falha` com o texto do erro; `Busca` vazia → run `falha`, cobertura 0, **nenhuma** leitura; senão `upsert` e cobertura = `len(leituras)/esperadas` (1,0 se `esperadas == 0`), status `ok` se ≥ 0,9 senão `parcial`.

- [ ] **Passo 1: Escrever o teste que falha** — usa um ingestor falso e um banco falso (sem PostgreSQL): o que se testa aqui é a REGRA do ciclo.

```python
# gemeo/tests/test_ingest_base.py
"""O ciclo e onde as regras de honestidade moram: ciclo vazio grava falha e nada mais; disjuntor aberto
nem chama a fonte; excecao vira ingest_run com o erro em texto. Testado com dublês — sem banco."""
import datetime as dt
from gemeo.core.modelos import UsinaRef
from gemeo.ingest import base

UTC = dt.timezone.utc
U = UsinaRef(id=1, codigo="T1", fonte="pg", fonte_ref="1", tz="America/Belem")


class BancoFalso:
    def __init__(self):
        self.leituras, self.runs, self.marca = [], [], None
    def marca_dagua(self, conn, usina_id): return self.marca
    def upsert_leituras(self, conn, linhas): ls = list(linhas); self.leituras += ls; return len(ls)
    def registrar_ingest_run(self, conn, **kw): self.runs.append(kw); return len(self.runs)


class Falso(base.Ingestor):
    fonte = "falso"
    def __init__(self, resposta, *a, **kw):
        super().__init__(*a, **kw); self.resposta = resposta; self.chamadas = 0
    def descobrir(self, usina): pass
    def buscar(self, usina, ini, fim):
        self.chamadas += 1
        if isinstance(self.resposta, Exception): raise self.resposta
        return self.resposta


def _ing(resposta, banco):
    ing = Falso(resposta, cfg=type("C", (), {"sobreposicao_min": 30})(), conn=None, usinas=[U])
    ing._db = banco
    return ing


def test_busca_vazia_grava_falha_e_nenhuma_leitura():
    b = BancoFalso(); ing = _ing(base.Busca(leituras=[]), b)
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    assert b.leituras == [] and b.runs[0]["status"] == "falha" and b.runs[0]["cobertura"] == 0


def test_busca_boa_grava_e_mede_cobertura():
    ts = dt.datetime(2026, 9, 3, 11, 0, tzinfo=UTC)
    b = BancoFalso(); ing = _ing(base.Busca(leituras=[(7, "p_ac", ts, 1.0)] * 9, esperadas=10, n_requisicoes=2), b)
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    r = b.runs[0]
    assert len(b.leituras) == 9 and r["status"] == "ok" and abs(r["cobertura"] - 0.9) < 1e-9 and r["n_requisicoes"] == 2


def test_cobertura_baixa_e_parcial():
    ts = dt.datetime(2026, 9, 3, 11, 0, tzinfo=UTC)
    b = BancoFalso(); ing = _ing(base.Busca(leituras=[(7, "p_ac", ts, 1.0)] * 5, esperadas=10), b)
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    assert b.runs[0]["status"] == "parcial"


def test_excecao_vira_run_com_erro():
    b = BancoFalso(); ing = _ing(RuntimeError("timeout na fonte"), b)
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    assert b.runs[0]["status"] == "falha" and "timeout" in b.runs[0]["erro"]


def test_disjuntor_aberto_nao_chama_a_fonte():
    b = BancoFalso(); ing = _ing(base.Busca(leituras=[]), b)
    ing.disjuntor.abrir("403 da borda")
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    assert ing.chamadas == 0 and b.runs[0]["erro"].startswith("disjuntor")


def test_janela_parte_da_marca_menos_sobreposicao():
    b = BancoFalso(); b.marca = dt.datetime(2026, 9, 3, 11, 45, tzinfo=UTC)
    vistas = {}
    class Espia(Falso):
        def buscar(self, usina, ini, fim): vistas["ini"] = ini; return base.Busca(leituras=[])
    ing = Espia(None, cfg=type("C", (), {"sobreposicao_min": 30})(), conn=None, usinas=[U]); ing._db = b
    ing.ciclo(agora=dt.datetime(2026, 9, 3, 12, 0, tzinfo=UTC))
    assert vistas["ini"] == dt.datetime(2026, 9, 3, 11, 15, tzinfo=UTC)
```

- [ ] **Passo 2: Rodar para ver falhar** — `ModuleNotFoundError: gemeo.ingest`

- [ ] **Passo 3: Implementar**

```python
# gemeo/gemeo/ingest/base.py
"""Ingestor: um laco por fonte, com marca d'agua, disjuntor e o contrato ingest_run. Falha e dado."""
from __future__ import annotations
import datetime as dt
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from gemeo.core import db as _db_mod
from gemeo.core import tempo
from gemeo.core.modelos import UsinaRef


@dataclass
class Busca:
    leituras: list[tuple[int, str, dt.datetime, float]] = field(default_factory=list)
    n_requisicoes: int = 0
    esperadas: int = 0


class Disjuntor:
    """Abre por `pausa_s` segundos. Enquanto aberto, o ciclo nem chama a fonte — insistir na borda da
    SunOp so alimenta o bloqueio (403 CloudFront = rate limit da conta, nao token)."""
    def __init__(self, pausa_s: float = 90.0):
        self.pausa_s, self._ate, self.motivo = pausa_s, 0.0, ""
    def aberto(self) -> bool:
        return time.time() < self._ate
    def abrir(self, motivo: str) -> None:
        self._ate, self.motivo = time.time() + self.pausa_s, motivo


class Ingestor(ABC):
    fonte: str = "?"

    def __init__(self, cfg, conn, usinas: list[UsinaRef]):
        self.cfg, self.conn, self.usinas = cfg, conn, usinas
        self.disjuntor = Disjuntor()
        self._db = _db_mod           # trocavel nos testes

    @abstractmethod
    def descobrir(self, usina: UsinaRef) -> None: ...

    @abstractmethod
    def buscar(self, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime) -> Busca: ...

    def ciclo(self, agora: dt.datetime | None = None, reconciliar: bool = False) -> list[int]:
        agora = agora or dt.datetime.now(dt.timezone.utc)
        ids = []
        for u in self.usinas:
            t0 = time.time()
            marca = self._db.marca_dagua(self.conn, u.id)
            ini, fim = tempo.janela(agora, marca, self.cfg.sobreposicao_min, reconciliar=reconciliar)
            if self.disjuntor.aberto():
                ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim,
                                                         status="falha", cobertura=0.0, erro=f"disjuntor aberto: {self.disjuntor.motivo}"))
                continue
            try:
                b = self.buscar(u, ini, fim)
            except Exception as e:                       # noqa: BLE001 — a fonte falhou; registra e segue
                ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim,
                                                         status="falha", cobertura=0.0, duracao_s=time.time() - t0,
                                                         erro=f"{type(e).__name__}: {e}"[:400]))
                continue
            if not b.leituras:
                ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim,
                                                         status="falha", n_requisicoes=b.n_requisicoes,
                                                         duracao_s=time.time() - t0, cobertura=0.0, erro="fonte devolveu vazio"))
                continue
            n = self._db.upsert_leituras(self.conn, b.leituras)
            cob = min(1.0, n / b.esperadas) if b.esperadas else 1.0
            ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim,
                                                     status="ok" if cob >= 0.9 else "parcial", n_linhas=n,
                                                     n_requisicoes=b.n_requisicoes, duracao_s=time.time() - t0, cobertura=cob))
        return ids
```

`gemeo/gemeo/ingest/__init__.py`: vazio.

- [ ] **Passo 4: Rodar** — 6 passed. **Passo 5: Commit** — `git commit -m "feat(gemeo): ingestor base com marca d'agua, disjuntor e ingest_run como contrato"`

### Tarefa 7: Ingestor PostgreSQL `powerplants` (Thopen/PG)

**Files:**
- Create: `gemeo/gemeo/ingest/pg.py`, `gemeo/tests/test_ingest_pg.py`

**Interfaces:**
- Consumes: `Ingestor`, `Busca` (Tarefa 6); `UsinaRef` com `fonte_ref` = `power_plant_id`.
- Produces: `IngestorPG(cfg, conn, usinas, conn_fonte)` com `fonte = "pg"`; `descobrir(usina)` cria `equipamento` por `device_id` (estação de `raw_weather_station`, inversor de `raw_inverter` com strings `string_N_current` como filhas, tracker de `raw_tracker`) com `atributos.numero`; `buscar(usina, ini, fim) -> Busca`. Função pura `linhas_de(json_data: dict, tabela: str, mapa_eq: dict) -> list[tuple]` — é ela que os testes cobrem sem banco. Chaves reais (verificadas em 03/09): `raw_weather_station`: `irradiance_poa`, `irradiance_ghi`, `module_temperature`, `air_temperature`, `wind_speed`; `raw_inverter`: `active_power` (kW), `daily_active_energy`, `state_simplified`, `string_N_current`; `raw_tracker`: `posat`, `posal`.

- [ ] **Passo 1: Escrever o teste que falha**

```python
# gemeo/tests/test_ingest_pg.py
"""Parse do json_data das tabelas raw_* → leituras normalizadas. Chaves reais medidas em 03/09/2026."""
import datetime as dt
from gemeo.ingest import pg

UTC = dt.timezone.utc
TS = dt.datetime(2026, 9, 3, 15, 0, tzinfo=UTC)


def test_weather_vira_cinco_medidas():
    mapa = {("estacao", "900"): 50}
    ls = pg.linhas_de({"irradiance_poa": 812.5, "irradiance_ghi": 700.0, "module_temperature": 48.2,
                       "air_temperature": 31.0, "wind_speed": 2.1, "rain_signal": 0}, "raw_weather_station", "900", TS, mapa)
    assert {(m, v) for _, m, _, v in ls} == {("poa", 812.5), ("ghi", 700.0), ("temp_modulo", 48.2), ("temp_ar", 31.0), ("vento", 2.1)}
    assert all(e == 50 for e, *_ in ls)


def test_inversor_e_suas_strings():
    mapa = {("inversor", "765"): 10, ("string", "765.string_1"): 11, ("string", "765.string_2"): 12}
    ls = pg.linhas_de({"active_power": 150.0, "daily_active_energy": 1479.9, "state_simplified": 2,
                       "string_1_current": 8.4, "string_2_current": 0.0, "string_3_current": None}, "raw_inverter", "765", TS, mapa)
    d = {(e, m): v for e, m, _, v in ls}
    assert d[(10, "p_ac")] == 150.0 and d[(10, "e_dia")] == 1479.9 and d[(10, "estado")] == 2
    assert d[(11, "i_string")] == 8.4 and d[(12, "i_string")] == 0.0
    assert (13, "i_string") not in d                     # string_3 sem equipamento cadastrado e None: fora


def test_tracker_angulos():
    mapa = {("tracker", "77"): 3}
    ls = pg.linhas_de({"posat": -12.5, "posal": -13.0, "flh_com": 0}, "raw_tracker", "77", TS, mapa)
    assert {(m, v) for _, m, _, v in ls} == {("angulo", -12.5), ("angulo_alvo", -13.0)}


def test_valor_nao_numerico_e_descartado():
    ls = pg.linhas_de({"active_power": "erro"}, "raw_inverter", "765", TS, {("inversor", "765"): 10})
    assert ls == []
```

- [ ] **Passo 2: Rodar para ver falhar** — `ModuleNotFoundError: gemeo.ingest.pg`

- [ ] **Passo 3: Implementar**

```python
# gemeo/gemeo/ingest/pg.py
"""Fonte PostgreSQL `powerplants` (Thopen): raw_weather_station, raw_inverter, raw_tracker.
So leitura. Timestamps ja sao timestamptz (UTC) — nenhuma conversao na gravacao."""
from __future__ import annotations
import datetime as dt
import re

from gemeo.core.modelos import UsinaRef
from gemeo.ingest.base import Busca, Ingestor

MEDIDAS = {
    "raw_weather_station": {"irradiance_poa": "poa", "irradiance_ghi": "ghi", "module_temperature": "temp_modulo",
                            "air_temperature": "temp_ar", "wind_speed": "vento"},
    "raw_inverter": {"active_power": "p_ac", "daily_active_energy": "e_dia", "state_simplified": "estado"},
    "raw_tracker": {"posat": "angulo", "posal": "angulo_alvo"},
}
TIPO = {"raw_weather_station": "estacao", "raw_inverter": "inversor", "raw_tracker": "tracker"}
_STR = re.compile(r"^string_(\d+)_current$")


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def linhas_de(json_data: dict, tabela: str, device_id: str, ts: dt.datetime, mapa_eq: dict) -> list[tuple]:
    """(equipamento_id, medida, ts, valor) para um registro cru. Valor nao numerico e descartado."""
    out = []
    eid = mapa_eq.get((TIPO[tabela], str(device_id)))
    if eid is not None:
        for chave, medida in MEDIDAS[tabela].items():
            v = _num(json_data.get(chave))
            if v is not None:
                out.append((eid, medida, ts, v))
    if tabela == "raw_inverter":
        for chave, val in json_data.items():
            m = _STR.match(chave)
            if not m:
                continue
            sid = mapa_eq.get(("string", f"{device_id}.string_{m.group(1)}"))
            v = _num(val)
            if sid is not None and v is not None:
                out.append((sid, "i_string", ts, v))
    return out


class IngestorPG(Ingestor):
    fonte = "pg"

    def __init__(self, cfg, conn, usinas: list[UsinaRef], conn_fonte):
        super().__init__(cfg, conn, usinas)
        self.fonte_conn = conn_fonte

    def _mapa(self, usina: UsinaRef) -> dict:
        with self.conn.cursor() as cur:
            cur.execute("SELECT tipo, codigo_fonte, id FROM equipamento WHERE usina_id=%s AND ativo", (usina.id,))
            return {(t, c): i for t, c, i in cur.fetchall()}

    def descobrir(self, usina: UsinaRef) -> None:
        """Equipamento novo na fonte vira linha em `equipamento` com atributos.numero; o cadastro
        enriquece depois. Strings nascem das chaves string_N_current do ultimo registro do inversor."""
        pid = int(usina.fonte_ref)
        with self.fonte_conn.cursor() as src, self.conn.cursor() as cur:
            for tabela, tipo in TIPO.items():
                src.execute(f"SELECT DISTINCT device_id FROM public.{tabela} WHERE power_plant_id=%s AND timestamp >= now() - interval '7 days'", (pid,))
                for (dev,) in src.fetchall():
                    cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, atributos) VALUES (%s,%s,%s,%s) "
                                "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING RETURNING id",
                                (usina.id, tipo, str(dev), '{"numero": %d}' % int(dev)))
                    if tabela != "raw_inverter":
                        continue
                    src.execute("SELECT json_data FROM public.raw_inverter WHERE power_plant_id=%s AND device_id=%s ORDER BY timestamp DESC LIMIT 1", (pid, dev))
                    r = src.fetchone()
                    cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte=%s", (usina.id, str(dev)))
                    inv_id = cur.fetchone()[0]
                    for chave in (r[0] if r else {}):
                        m = _STR.match(chave)
                        if m:
                            cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, pai_id, atributos) VALUES (%s,'string',%s,%s,%s) "
                                        "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING",
                                        (usina.id, f"{dev}.string_{m.group(1)}", inv_id, '{"numero": %d}' % int(m.group(1))))
        self.conn.commit()

    def buscar(self, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime) -> Busca:
        mapa = self._mapa(usina)
        pid = int(usina.fonte_ref)
        leituras: list[tuple] = []
        with self.fonte_conn.cursor() as src:
            for tabela in MEDIDAS:
                src.execute(f"SELECT timestamp, device_id, json_data FROM public.{tabela} "
                            "WHERE power_plant_id=%s AND timestamp > %s AND timestamp <= %s", (pid, ini, fim))
                for ts, dev, jd in src.fetchall():
                    leituras.extend(linhas_de(jd or {}, tabela, str(dev), ts, mapa))
        n_series = len(mapa)
        esperadas = int(n_series * max(1, (fim - ini).total_seconds() / 300))   # 5 min por serie
        return Busca(leituras=leituras, n_requisicoes=len(MEDIDAS), esperadas=esperadas)
```

- [ ] **Passo 4: Rodar** — 4 passed. **Passo 5: Commit** — `git commit -m "feat(gemeo): ingestor PostgreSQL powerplants (estacao, inversores, strings, trackers)"`

### Tarefa 8: Ingestor SunOp — metadata em disco, lote de 600 atravessando usinas, teto diário

**Files:**
- Create: `gemeo/gemeo/ingest/sunop.py`, `gemeo/tests/test_ingest_sunop.py`
- Fixture (já existe): `gemeo/tests/fixtures/sunop_metadata_mro100.json` — 34 itens reais do `/v2/metadata` da MRO100 cobrindo cada tipo de pathname.

**Interfaces:**
- Consumes: `Ingestor`, `Busca`, `Disjuntor` (Tarefa 6); `db.requisicoes_hoje`, `db.upsert_leituras`, `db.registrar_ingest_run` (Tarefa 3); `tempo.dentro_janela_solar`, `tempo.janela` (Tarefa 4); `Config.sunop_base/sunop_token/lote_pathnames/teto_sunop_dia/janela_solar/cache_dir`.
- Produces: `classificar(pathname: str) -> tuple[str, str, str, dict] | None` → `(tipo, codigo_fonte, medida, atributos)` ou `None` se o pathname não interessa; `GRUPOS = {"fino": {"estacao","inversor"}, "lento": {"tracker","string"}}`; `IngestorSunOp(cfg, conn, usinas, grupo: str, http=None)` com `fonte = "sunop"` (ou `"axis"` se `usinas[0].fonte == "axis"`); `metadata(usina) -> list[dict]` (cache em `cfg.cache_dir/sunop_meta_<codigo>.json`, validade 24 h); `descobrir(usina)`; **`ciclo()` sobrescrito**: uma baixa para TODAS as usinas do grupo, lotes de `cfg.lote_pathnames` atravessando usinas, `period="15m"` no grupo lento, resultado recortado por usina e um `ingest_run` por usina; fora da janela solar não busca (run `falha` com erro `fora da janela solar`); teto diário via `requisicoes_hoje` → run `falha` `teto diario`; HTTP 403 → `disjuntor.abrir`. Timestamps vêm no fuso da usina (`use_plant_timezone=true`) e são convertidos para UTC com `usina.tz`.

- [ ] **Passo 1: Escrever o teste que falha**

```python
# gemeo/tests/test_ingest_sunop.py
"""Metadata real (34 itens da MRO100) → equipamentos; lote atravessando usinas; teto e 403 → disjuntor.
HTTP e banco sao dubles: o que se testa e o contrato, nao a SunOp."""
import datetime as dt
import json
from pathlib import Path
from gemeo.ingest import sunop

FIX = json.load(open(Path(__file__).parent / "fixtures" / "sunop_metadata_mro100.json", encoding="utf-8"))


def test_classificar_cada_tipo():
    assert sunop.classificar("MRO100.ESTM.POA.IRAD") == ("estacao", "ESTM", "poa", {})
    assert sunop.classificar("MRO100.INV_7.MEDIDAS.P") == ("inversor", "INV_7", "p_ac", {"numero": 7})
    assert sunop.classificar("MRO100.INV_7.MEDIDAS.EPD") == ("inversor", "INV_7", "e_dia", {"numero": 7})
    assert sunop.classificar("MRO100.INV_7.MEDIDAS.STR.I_PV3") == ("string", "INV_7.I_PV3", "i_string", {"numero": 3, "inversor": "INV_7"})
    assert sunop.classificar("MRO100.TRK_17.MEDIDAS.POSAT") == ("tracker", "TRK_17", "angulo", {"numero": 17})
    assert sunop.classificar("MRO100.TRK_17.MEDIDAS.POSAL") == ("tracker", "TRK_17", "angulo_alvo", {"numero": 17})
    assert sunop.classificar("MRO100.TRK_17.STATUS.WORKSTATE") == ("tracker", "TRK_17", "estado", {"numero": 17})
    assert sunop.classificar("MRO100.CALC.POT.ESP") is None and sunop.classificar("MRO100.TRK_1.ALARME.AUTO_ON") is None


def test_metadata_real_vira_equipamentos_distintos():
    eqs = sunop.equipamentos_de(FIX)
    tipos = {(t, c) for t, c, _ in eqs}
    assert ("estacao", "ESTM") in tipos and ("inversor", "INV_25") in tipos
    assert ("string", "INV_1.I_PV18") in tipos and ("tracker", "TRK_120") in tipos
    assert len(eqs) == len(tipos)                     # um equipamento por (tipo, codigo)


def test_lotes_atravessam_usinas():
    lotes = sunop.lotear(["A.1", "A.2", "B.1", "B.2", "B.3"], tamanho=2)
    assert lotes == [["A.1", "A.2"], ["B.1", "B.2"], ["B.3"]]


def test_ts_local_vira_utc():
    ts = sunop.ts_utc("2026-08-26T12:00:00", "America/Belem")
    assert ts == dt.datetime(2026, 8, 26, 15, 0, tzinfo=dt.timezone.utc)


def test_403_abre_o_disjuntor_e_nao_grava():
    class Resp:
        status_code = 403
        text = "Forbidden (CloudFront)"
        def json(self): return []
    class Http:
        def post(self, *a, **k): return Resp()
    ing = sunop.IngestorSunOp.__new__(sunop.IngestorSunOp)
    from gemeo.ingest.base import Disjuntor
    ing.disjuntor = Disjuntor(); ing.http = Http(); ing.cfg = type("C", (), {"sunop_base": "http://x", "sunop_token": "t"})()
    assert ing._analog(["P.1"], "2026-08-26T00:00:00", "2026-08-26T23:59:59", None) == {}
    assert ing.disjuntor.aberto()
```

- [ ] **Passo 2: Rodar para ver falhar** — `ModuleNotFoundError: gemeo.ingest.sunop`

- [ ] **Passo 3: Implementar**

```python
# gemeo/gemeo/ingest/sunop.py
"""Fonte SunOp (Athon; Axis e a mesma classe com outra instancia). Tres regras que custaram caro:
metadata em DISCO (e a chamada que derruba a borda quando refeita), lote de pathnames atravessando
usinas (o que corta a CONTAGEM — o period so corta payload), e teto diario proprio (a cota e
compartilhada com a plataforma)."""
from __future__ import annotations
import datetime as dt
import json
import re
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from gemeo.core import db as _db
from gemeo.core import tempo
from gemeo.core.modelos import UsinaRef
from gemeo.ingest.base import Busca, Ingestor

_RX = [
    (re.compile(r"^\w+\.ESTM[^.]*\.POA\.IRAD$"), lambda m: ("estacao", "ESTM", "poa", {})),
    (re.compile(r"^\w+\.ESTM[^.]*\.GHI\.IRAD$"), lambda m: ("estacao", "ESTM", "ghi", {})),
    (re.compile(r"^\w+\.ESTM[^.]*\.PNL\.TEMP$"), lambda m: ("estacao", "ESTM", "temp_modulo", {})),
    (re.compile(r"^\w+\.ESTM[^.]*\.AR\.TEMP$"), lambda m: ("estacao", "ESTM", "temp_ar", {})),
    (re.compile(r"^\w+\.ESTM[^.]*\.AR\.VEL$"), lambda m: ("estacao", "ESTM", "vento", {})),
    (re.compile(r"^\w+\.INV_(\d+)\.MEDIDAS\.P$"), lambda m: ("inversor", f"INV_{m.group(1)}", "p_ac", {"numero": int(m.group(1))})),
    (re.compile(r"^\w+\.INV_(\d+)\.MEDIDAS\.EPD$"), lambda m: ("inversor", f"INV_{m.group(1)}", "e_dia", {"numero": int(m.group(1))})),
    (re.compile(r"^\w+\.INV_(\d+)\.MEDIDAS\.Workstate$"), lambda m: ("inversor", f"INV_{m.group(1)}", "estado", {"numero": int(m.group(1))})),
    (re.compile(r"^\w+\.INV_(\d+)\.MEDIDAS\.STR\.I_PV(\d+)$"), lambda m: ("string", f"INV_{m.group(1)}.I_PV{m.group(2)}", "i_string", {"numero": int(m.group(2)), "inversor": f"INV_{m.group(1)}"})),
    (re.compile(r"^\w+\.TRK_(\d+)\.MEDIDAS\.POSAT$"), lambda m: ("tracker", f"TRK_{m.group(1)}", "angulo", {"numero": int(m.group(1))})),
    (re.compile(r"^\w+\.TRK_(\d+)\.MEDIDAS\.POSAL$"), lambda m: ("tracker", f"TRK_{m.group(1)}", "angulo_alvo", {"numero": int(m.group(1))})),
    (re.compile(r"^\w+\.TRK_(\d+)\.STATUS\.WORKSTATE$"), lambda m: ("tracker", f"TRK_{m.group(1)}", "estado", {"numero": int(m.group(1))})),
]
GRUPOS = {"fino": {"estacao", "inversor"}, "lento": {"tracker", "string"}}
PERIOD = {"fino": None, "lento": "15m"}


def classificar(pathname: str):
    for rx, f in _RX:
        m = rx.match(pathname)
        if m:
            return f(m)
    return None


def equipamentos_de(metadata: list[dict]) -> list[tuple[str, str, dict]]:
    vistos, out = set(), []
    for it in metadata:
        c = classificar(str(it.get("pathname") or ""))
        if c and (c[0], c[1]) not in vistos:
            vistos.add((c[0], c[1])); out.append((c[0], c[1], c[3]))
    return out


def lotear(pathnames: list[str], tamanho: int) -> list[list[str]]:
    return [pathnames[i:i + tamanho] for i in range(0, len(pathnames), tamanho)]


def ts_utc(texto: str, tz: str) -> dt.datetime:
    return dt.datetime.fromisoformat(texto).replace(tzinfo=ZoneInfo(tz)).astimezone(dt.timezone.utc)


class IngestorSunOp(Ingestor):
    def __init__(self, cfg, conn, usinas: list[UsinaRef], grupo: str = "fino", http=None):
        super().__init__(cfg, conn, usinas)
        self.grupo, self.http = grupo, http or requests.Session()
        self.fonte = "axis" if usinas and usinas[0].fonte == "axis" else "sunop"

    # ── metadata em disco ────────────────────────────────────────────────────
    def metadata(self, usina: UsinaRef) -> list[dict]:
        cache = Path(self.cfg.cache_dir) / f"sunop_meta_{usina.codigo}.json"
        if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
            return json.load(open(cache, encoding="utf-8"))
        r = self.http.get(f"{self.cfg.sunop_base}/data/v2/metadata", params={"plant": usina.fonte_ref, "size": 6000},
                          headers={"Authorization": f"Bearer {self.cfg.sunop_token}"}, timeout=60)
        if r.status_code == 403:
            self.disjuntor.abrir("403 da borda no metadata")
            raise RuntimeError("403 da borda no metadata")
        r.raise_for_status()
        itens = r.json().get("data", [])
        cache.parent.mkdir(parents=True, exist_ok=True)
        json.dump(itens, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
        return itens

    def descobrir(self, usina: UsinaRef) -> None:
        eqs = equipamentos_de(self.metadata(usina))
        with self.conn.cursor() as cur:
            for tipo, codigo, atr in eqs:
                if tipo == "string":
                    continue
                cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, atributos) VALUES (%s,%s,%s,%s) "
                            "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING", (usina.id, tipo, codigo, json.dumps(atr)))
            for tipo, codigo, atr in eqs:
                if tipo != "string":
                    continue
                cur.execute("SELECT id FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte=%s", (usina.id, atr["inversor"]))
                pai = cur.fetchone()
                cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, pai_id, atributos) VALUES (%s,'string',%s,%s,%s) "
                            "ON CONFLICT (usina_id, tipo, codigo_fonte) DO NOTHING", (usina.id, codigo, pai[0] if pai else None, json.dumps({"numero": atr["numero"]})))
        self.conn.commit()

    # ── busca ─────────────────────────────────────────────────────────────────
    def _pathnames(self, usina: UsinaRef) -> dict[str, tuple[int, str]]:
        """pathname -> (equipamento_id, medida) para o grupo deste ingestor."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT tipo, codigo_fonte, id FROM equipamento WHERE usina_id=%s AND ativo", (usina.id,))
            ids = {(t, c): i for t, c, i in cur.fetchall()}
        out = {}
        for it in self.metadata(usina):
            p = str(it.get("pathname") or ""); c = classificar(p)
            if c and c[0] in GRUPOS[self.grupo] and (c[0], c[1]) in ids:
                out[p] = (ids[(c[0], c[1])], c[2])
        return out

    def _analog(self, pathnames: list[str], ini: str, fim: str, period: str | None) -> dict:
        params = {"fill_missing": "false", "source": "Historical", "start_time": ini, "end_time": fim, "use_plant_timezone": "true"}
        if period:
            params["period"] = period
        r = self.http.post(f"{self.cfg.sunop_base}/data/v2/analog_values", params=params, json={"pathnames": pathnames},
                           headers={"Authorization": f"Bearer {self.cfg.sunop_token}"}, timeout=120)
        if r.status_code == 403:
            self.disjuntor.abrir(f"403 da borda: {r.text[:80]}")
            return {}
        if r.status_code != 200:
            return {}
        out: dict[str, list] = {}
        for rec in r.json() or []:
            v = rec.get("value")
            if isinstance(v, (int, float)):
                out.setdefault(rec["pathname"], []).append((rec["timestamp"], float(v)))
        return out

    def buscar(self, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime) -> Busca:
        """Uma usina so — usado quando o ciclo conjunto nao se aplica (testes, reprocesso)."""
        return self._buscar_varias([usina], ini, fim)[usina.id]

    def _buscar_varias(self, usinas: list[UsinaRef], ini: dt.datetime, fim: dt.datetime) -> dict[int, Busca]:
        mapa = {u.id: self._pathnames(u) for u in usinas}
        todos = [p for m in mapa.values() for p in m]
        tz0 = usinas[0].tz
        ini_l = ini.astimezone(ZoneInfo(tz0)).strftime("%Y-%m-%dT%H:%M:%S"); fim_l = fim.astimezone(ZoneInfo(tz0)).strftime("%Y-%m-%dT%H:%M:%S")
        bruto: dict[str, list] = {}; n = 0
        for lote in lotear(todos, self.cfg.lote_pathnames):
            hoje = dt.datetime.now(dt.timezone.utc).date()
            if self._db.requisicoes_hoje(self.conn, self.fonte, hoje) + n >= self.cfg.teto_sunop_dia:
                self.disjuntor.abrir("teto diario de requisicoes")
                break
            bruto.update(self._analog(lote, ini_l, fim_l, PERIOD[self.grupo])); n += 1
        passo = 15 if PERIOD[self.grupo] else 5
        out = {}
        for u in usinas:
            ls = [(eid, med, ts_utc(t, u.tz), v) for p, (eid, med) in mapa[u.id].items() for t, v in bruto.get(p, [])]
            esperadas = int(len(mapa[u.id]) * max(1, (fim - ini).total_seconds() / (passo * 60)))
            out[u.id] = Busca(leituras=ls, n_requisicoes=n if u is usinas[0] else 0, esperadas=esperadas)
        return out

    def ciclo(self, agora: dt.datetime | None = None, reconciliar: bool = False) -> list[int]:
        """Sobrescreve o ciclo base: UMA baixa para todas as usinas do grupo (lotes atravessam usinas),
        janela comum = a mais antiga entre as marcas d'agua. Fora da janela solar, nao busca."""
        agora = agora or dt.datetime.now(dt.timezone.utc)
        ids = []
        ativas = [u for u in self.usinas if tempo.dentro_janela_solar(agora, u.tz, self.cfg.janela_solar)]
        for u in self.usinas:
            if u not in ativas:
                ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=agora, fim=agora, status="falha", cobertura=0.0, erro="fora da janela solar"))
        if not ativas:
            return ids
        if self.disjuntor.aberto():
            return ids + [self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=agora, fim=agora, status="falha", cobertura=0.0, erro=f"disjuntor aberto: {self.disjuntor.motivo}") for u in ativas]
        janelas = [tempo.janela(agora, self._db.marca_dagua(self.conn, u.id), self.cfg.sobreposicao_min, reconciliar=reconciliar) for u in ativas]
        ini, fim = min(j[0] for j in janelas), agora
        t0 = time.time()
        try:
            buscas = self._buscar_varias(ativas, ini, fim)
        except Exception as e:                       # noqa: BLE001
            return ids + [self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim, status="falha", cobertura=0.0, duracao_s=time.time() - t0, erro=f"{type(e).__name__}: {e}"[:400]) for u in ativas]
        for u in ativas:
            b = buscas[u.id]
            if not b.leituras:
                ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim, status="falha", n_requisicoes=b.n_requisicoes, cobertura=0.0, erro="fonte devolveu vazio")); continue
            n = self._db.upsert_leituras(self.conn, b.leituras)
            cob = min(1.0, n / b.esperadas) if b.esperadas else 1.0
            ids.append(self._db.registrar_ingest_run(self.conn, fonte=self.fonte, usina_id=u.id, ini=ini, fim=fim, status="ok" if cob >= 0.9 else "parcial", n_linhas=n, n_requisicoes=b.n_requisicoes, duracao_s=time.time() - t0, cobertura=cob))
        return ids
```

- [ ] **Passo 4: Rodar** — 5 passed. **Passo 5: Commit** — `git commit -m "feat(gemeo): ingestor SunOp com metadata em disco, lote atravessando usinas e teto diario"`

### Tarefa 9: Ingestor de cadastro — API BD_Performance → usina, equipamento, alias, meta_mes

**Files:**
- Create: `gemeo/gemeo/ingest/cadastro.py`, `gemeo/tests/test_ingest_cadastro.py`

**Interfaces:**
- Consumes: `db.ler_estado/gravar_estado` (Tarefa 3); `alias.gravar` (Tarefa 5); `Config.bd_api_base/bd_api_token/usinas_piloto`.
- Produces: `linhas_da_aba(http, base, token, sheet_id, header_row) -> list[dict]` (cada linha = `{header: valor}` só das linhas após `header_row`, páginas de 500); `IngestorCadastro(cfg, conn, http=None)` com `ciclo(force=False) -> dict` (contagens) — só rebaixa se `updated_at` do workbook `bd_performance` mudou (guardado em `estado['cadastro.updated_at']`); `aplicar_equipamentos(conn, linhas, piloto) -> dict`; `inspecionar_cli()` imprime os headers de cada aba (para conferir Info Geral, Info Mensal e BD_Trackers no primeiro uso real). Formato real da API (03/09): `GET /api/workbooks` → `[{key, updated_at, sheet_count}]`; `GET /api/sheets` → `[{id, sheet_name, workbook_key, header_row, row_count}]`; `GET /api/sheets/{id}/rows?offset&limit=500` → `{"rows":[{"row_number", "headers":[...], "values":[...]}]}`.
- Colunas da aba Equipamentos (reais): `Cliente`, `Usina Supervisório`, `Usina Fractall`, `Equipamento`, `Equipamento Supervisório`, `Equipamento Parente`, `Potência (kWp)`, `N de Inversores`, `String Box`, `Full O&M`, `Strings Ativas`. Linha com `Equipamento Parente == "UFV"` é o cabeçalho da usina; as demais são inversores.

- [ ] **Passo 1: Escrever o teste que falha**

```python
# gemeo/tests/test_ingest_cadastro.py
"""Linhas da API (headers + values) viram usina/equipamento/alias. HTTP e um dublê com o formato real."""
from gemeo.ingest import cadastro

HDR = ["", "Cliente", "Usina", "Usina Supervisório", "Usina Fractall", "Equipamento", "Equipamento Supervisório",
       "Equipamento Parente", "Chave", "Chave 2", "Potência (kWp)", "N de Inversores", "String Box", "Full O&M", "Strings Ativas", "Observações"]


def _row(n, vals):
    return {"row_number": n, "headers": HDR, "values": vals + [None] * (len(HDR) - len(vals))}


class Http:
    def __init__(self):
        self.pags = {0: {"rows": [
            _row(4, [None, "Athon", "MRO100", "MRO100", "Athon - Mãe do Rio 1 - PA", "UFV", None, "UFV", "MRO100", "MRO100", 6942.0, 25, "Não", "Sim", None]),
            _row(5, [None, "Athon", "MRO100", "MRO100", "Athon - Mãe do Rio 1 - PA", "Inversor 1.1", "INV_1", "UFV", "MRO100", "MRO100INV_1", 277.68, None, "Não", "Sim", 17]),
            _row(6, [None, "Athon", "MRO100", "MRO100", "Athon - Mãe do Rio 1 - PA", "Inversor 1.2", "INV_2", "UFV", "MRO100", "MRO100INV_2", 277.68, None, "Não", "Sim", 17]),
        ]}, 500: {"rows": []}}
    def get(self, url, params=None, headers=None, timeout=None):
        off = int((params or {}).get("offset", 0))
        class R:
            status_code = 200
            def __init__(s, j): s._j = j
            def json(s): return s._j
            def raise_for_status(s): pass
        return R(self.pags.get(off, {"rows": []}))


def test_linhas_da_aba_pula_cabecalho_e_pagina():
    ls = cadastro.linhas_da_aba(Http(), "http://x", "tok", sheet_id=46, header_row=3)
    assert len(ls) == 3 and ls[1]["Equipamento Supervisório"] == "INV_1" and ls[1]["Strings Ativas"] == 17


def test_separa_usina_de_inversores():
    ls = cadastro.linhas_da_aba(Http(), "http://x", "tok", sheet_id=46, header_row=3)
    us, invs = cadastro.separar_equipamentos(ls, piloto=("MRO100",))
    assert us["MRO100"]["kwp"] == 6942.0 and us["MRO100"]["n_inversores"] == 25 and us["MRO100"]["full_om"] is True
    assert us["MRO100"]["fracttal"] == "Athon - Mãe do Rio 1 - PA"
    assert [i["codigo_fonte"] for i in invs["MRO100"]] == ["INV_1", "INV_2"]
    assert invs["MRO100"][0]["nome"] == "Inversor 1.1" and invs["MRO100"][0]["n_strings_esperadas"] == 17


def test_usina_fora_do_piloto_e_ignorada():
    ls = cadastro.linhas_da_aba(Http(), "http://x", "tok", sheet_id=46, header_row=3)
    us, invs = cadastro.separar_equipamentos(ls, piloto=("OUTRA",))
    assert us == {} and invs == {}
```

- [ ] **Passo 2: Rodar para ver falhar** — `ModuleNotFoundError: gemeo.ingest.cadastro`

- [ ] **Passo 3: Implementar**

```python
# gemeo/gemeo/ingest/cadastro.py
"""Cadastro e metas vindos da Gridco Performance API (BD_Performance). Rebaixa so se o updated_at do
workbook mudou — a mesma revalidacao barata do bd_api da plataforma."""
from __future__ import annotations
import json
import requests

from gemeo.core import alias as _alias
from gemeo.core import db as _db


def _get(http, base, token, caminho, params=None):
    r = http.get(f"{base}{caminho}", params=params, headers={"Accept": "application/json", "Authorization": f"Bearer {token}"}, timeout=90)
    r.raise_for_status()
    return r.json()


def linhas_da_aba(http, base: str, token: str, sheet_id: int, header_row: int) -> list[dict]:
    """Cada linha vira {header: valor}; linhas ate header_row sao cabecalho e saem. Pagina de 500."""
    out, off = [], 0
    while True:
        j = _get(http, base, token, f"/api/sheets/{sheet_id}/rows", {"offset": off, "limit": 500})
        rows = j.get("rows") or []
        for r in rows:
            if int(r.get("row_number") or 0) <= header_row:
                continue
            hs, vs = r.get("headers") or [], r.get("values") or []
            out.append({str(h).strip(): vs[i] if i < len(vs) else None for i, h in enumerate(hs) if str(h).strip()})
        if len(rows) < 500:
            return out
        off += 500


def _sim(v) -> bool:
    return str(v or "").strip().lower() in ("sim", "s", "true", "1")


def separar_equipamentos(linhas: list[dict], piloto: tuple[str, ...]) -> tuple[dict, dict]:
    """Aba Equipamentos → (usinas, inversores por usina), so para as usinas do piloto."""
    usinas: dict[str, dict] = {}
    invs: dict[str, list] = {}
    for ln in linhas:
        cod = str(ln.get("Usina Supervisório") or "").strip()
        if cod not in piloto:
            continue
        if str(ln.get("Equipamento") or "").strip().upper() == "UFV" or str(ln.get("Equipamento Parente") or "").strip().upper() == "UFV" and not str(ln.get("Equipamento Supervisório") or "").strip():
            usinas[cod] = {"cliente": ln.get("Cliente"), "fracttal": ln.get("Usina Fractall"), "kwp": ln.get("Potência (kWp)"),
                           "n_inversores": ln.get("N de Inversores"), "full_om": _sim(ln.get("Full O&M")), "string_box": _sim(ln.get("String Box"))}
            continue
        invs.setdefault(cod, []).append({"codigo_fonte": str(ln.get("Equipamento Supervisório") or "").strip(), "nome": ln.get("Equipamento"),
                                         "kwp": ln.get("Potência (kWp)"), "n_strings_esperadas": ln.get("Strings Ativas")})
    return usinas, invs


class IngestorCadastro:
    fonte = "cadastro"

    def __init__(self, cfg, conn, http=None):
        self.cfg, self.conn, self.http = cfg, conn, http or requests.Session()

    def _sheets(self) -> dict[str, dict]:
        lst = _get(self.http, self.cfg.bd_api_base, self.cfg.bd_api_token, "/api/sheets")
        lst = lst if isinstance(lst, list) else lst.get("items") or []
        return {str(s["sheet_name"]).strip().lower(): s for s in lst if s.get("workbook_key") == "bd_performance"}

    def ciclo(self, force: bool = False) -> dict:
        wbs = _get(self.http, self.cfg.bd_api_base, self.cfg.bd_api_token, "/api/workbooks")
        wb = next((w for w in (wbs if isinstance(wbs, list) else wbs.get("items") or []) if w.get("key") == "bd_performance"), {})
        versao = str(wb.get("updated_at") or "")
        if not force and versao and versao == _db.ler_estado(self.conn, "cadastro.updated_at"):
            return {"mudou": False}
        sheets = self._sheets()
        eq = sheets["equipamentos"]
        linhas = linhas_da_aba(self.http, self.cfg.bd_api_base, self.cfg.bd_api_token, eq["id"], int(eq.get("header_row") or 0))
        usinas, invs = separar_equipamentos(linhas, self.cfg.usinas_piloto)
        res = aplicar_equipamentos(self.conn, usinas, invs)
        _db.gravar_estado(self.conn, "cadastro.updated_at", versao)
        return {"mudou": True, **res}


def aplicar_equipamentos(conn, usinas: dict, invs: dict) -> dict:
    n_u = n_i = 0
    with conn.cursor() as cur:
        for cod, u in usinas.items():
            cur.execute("UPDATE usina SET cliente=%s, kwp_dc=%s, n_inversores=%s, full_om=%s WHERE codigo=%s RETURNING id",
                        (u["cliente"], u["kwp"], u["n_inversores"], u["full_om"], cod))
            r = cur.fetchone()
            if not r:
                continue
            n_u += 1
            if u.get("fracttal"):
                _alias.gravar(conn, "fracttal", str(u["fracttal"]), "direto", "aba Equipamentos", usina_id=r[0])
            for iv in invs.get(cod, []):
                cur.execute("UPDATE equipamento SET nome_exibicao=%s, atributos = atributos || %s::jsonb WHERE usina_id=%s AND tipo='inversor' AND codigo_fonte=%s RETURNING id",
                            (iv["nome"], json.dumps({"kwp": iv["kwp"], "n_strings_esperadas": iv["n_strings_esperadas"]}), r[0], iv["codigo_fonte"]))
                e = cur.fetchone()
                if e:
                    n_i += 1
                    _alias.gravar(conn, "bd_performance", f"{cod}|{iv['nome']}", "direto", "aba Equipamentos", equipamento_id=e[0], usina_id=r[0])
    conn.commit()
    return {"usinas": n_u, "inversores": n_i}


def inspecionar_cli() -> int:
    from gemeo.core.config import carregar
    cfg = carregar(); http = requests.Session()
    for nome, s in sorted(IngestorCadastro(cfg, None, http)._sheets().items()):
        if nome in ("equipamentos", "info geral", "info mensal", "bd_trackers"):
            j = _get(http, cfg.bd_api_base, cfg.bd_api_token, f"/api/sheets/{s['id']}/rows", {"offset": int(s.get('header_row') or 0), "limit": 1})
            print(f"{s['sheet_name']} (id {s['id']}, header_row {s.get('header_row')}):", (j.get("rows") or [{}])[0].get("headers"))
    return 0
```

> **Info Geral, Info Mensal e BD_Trackers** entram na Tarefa 9b (após o primeiro `gemeo inspecionar-cadastro` no servidor, que imprime os headers reais dessas abas). Até lá, kWp/n_inversores vêm da linha UFV da aba Equipamentos; `meta_mes` e o pai dos trackers ficam vazios — e a tela mostra isso, não esconde.

- [ ] **Passo 4: Rodar** — 3 passed. **Passo 5: Commit** — `git commit -m "feat(gemeo): ingestor de cadastro pela API do BD_Performance com revalidacao por updated_at"`

### Tarefa 10: Runner — três laços em threads e o comando `gemeo ingest`

**Files:**
- Create: `gemeo/gemeo/ingest/runner.py`, `gemeo/tests/test_ingest_runner.py`

**Interfaces:**
- Consumes: `IngestorPG` (7), `IngestorSunOp` (8), `IngestorCadastro` (9), `db.conectar/garantir_particoes` (2), `Config.ritmo_min`.
- Produces: `usinas_do_piloto(conn, codigos) -> list[UsinaRef]`; `montar(cfg, conn_gemeo, conn_fonte, usinas) -> list[tuple[str, objeto, int]]` (rótulo, ingestor, minutos); `laco(rotulo, ingestor, minutos, parar: threading.Event) -> None` (chama `ciclo()` a cada `minutos`, reconciliando uma vez por dia às 03:00 UTC, nunca deixa exceção matar a thread); `rodar() -> int` (CLI).

- [ ] **Passo 1: Escrever o teste que falha**

```python
# gemeo/tests/test_ingest_runner.py
"""O laco nunca morre por excecao da fonte e para quando o Event manda. Ritmo em minutos, do config."""
import threading
from gemeo.ingest import runner


class Ing:
    def __init__(self, falha=False): self.n = 0; self.falha = falha; self.fonte = "x"
    def ciclo(self, reconciliar=False):
        self.n += 1
        if self.falha: raise RuntimeError("fonte fora")


def test_laco_para_no_event_e_sobrevive_a_excecao():
    parar = threading.Event(); ing = Ing(falha=True)
    def _depois(): parar.set()
    t = threading.Timer(0.3, _depois); t.start()
    runner.laco("x", ing, minutos=0.001, parar=parar)     # 0,001 min = 60 ms entre ciclos
    assert ing.n >= 2                                      # continuou apos a excecao


def test_montar_usa_o_ritmo_do_config():
    cfg = type("C", (), {"ritmo_min": {"pg": 15, "sunop_fino": 15, "sunop_lento": 60, "cadastro": 30}, "usinas_piloto": ("MRO100",),
                        "sobreposicao_min": 30, "cache_dir": ".", "sunop_base": "", "sunop_token": "", "lote_pathnames": 600, "teto_sunop_dia": 600, "janela_solar": ("05:40","18:20"), "bd_api_base": "", "bd_api_token": ""})()
    from gemeo.core.modelos import UsinaRef
    us = [UsinaRef(1, "MRO100", "sunop", "MRO100", "America/Belem"), UsinaRef(2, "Santarem 1", "pg", "10", "America/Belem")]
    itens = runner.montar(cfg, conn_gemeo=None, conn_fonte=None, usinas=us)
    assert {(r, m) for r, _, m in itens} == {("pg", 15), ("sunop_fino", 15), ("sunop_lento", 60), ("cadastro", 30)}
```

- [ ] **Passo 2: Rodar para ver falhar** — `ModuleNotFoundError: gemeo.ingest.runner`

- [ ] **Passo 3: Implementar**

```python
# gemeo/gemeo/ingest/runner.py
"""`gemeo ingest`: um processo, tres laços em threads (pg, sunop fino/lento, cadastro), cada um com
seu ritmo e seu disjuntor. Exceção da fonte nunca mata a thread — vira ingest_run e o laco segue."""
from __future__ import annotations
import datetime as dt
import threading
import time
import traceback

from gemeo.core import db
from gemeo.core.modelos import UsinaRef


def usinas_do_piloto(conn, codigos: tuple[str, ...]) -> list[UsinaRef]:
    with conn.cursor() as cur:
        cur.execute("SELECT id, codigo, fonte, fonte_ref, tz, coalesce(kwp_dc,0), coalesce(kw_ac,0), lat, lon FROM usina WHERE ativo AND codigo = ANY(%s)", (list(codigos),))
        return [UsinaRef(*r) for r in cur.fetchall()]


def montar(cfg, conn_gemeo, conn_fonte, usinas: list[UsinaRef]) -> list[tuple[str, object, int]]:
    from gemeo.ingest.cadastro import IngestorCadastro
    from gemeo.ingest.pg import IngestorPG
    from gemeo.ingest.sunop import IngestorSunOp
    pg = [u for u in usinas if u.fonte == "pg"]; su = [u for u in usinas if u.fonte in ("sunop", "axis")]
    itens: list[tuple[str, object, int]] = []
    if pg:
        itens.append(("pg", IngestorPG(cfg, conn_gemeo, pg, conn_fonte), int(cfg.ritmo_min["pg"])))
    if su:
        itens.append(("sunop_fino", IngestorSunOp(cfg, conn_gemeo, su, grupo="fino"), int(cfg.ritmo_min["sunop_fino"])))
        itens.append(("sunop_lento", IngestorSunOp(cfg, conn_gemeo, su, grupo="lento"), int(cfg.ritmo_min["sunop_lento"])))
    itens.append(("cadastro", IngestorCadastro(cfg, conn_gemeo), int(cfg.ritmo_min["cadastro"])))
    return itens


def laco(rotulo: str, ingestor, minutos: float, parar: threading.Event) -> None:
    ultimo_reconcilia: dt.date | None = None
    while not parar.is_set():
        agora = dt.datetime.now(dt.timezone.utc)
        reconciliar = agora.hour == 3 and ultimo_reconcilia != agora.date()
        try:
            if hasattr(ingestor, "descobrir"):
                for u in getattr(ingestor, "usinas", []):
                    ingestor.descobrir(u)
            ingestor.ciclo(reconciliar=reconciliar) if "reconciliar" in ingestor.ciclo.__code__.co_varnames else ingestor.ciclo()
            if reconciliar:
                ultimo_reconcilia = agora.date()
        except Exception:                                   # noqa: BLE001 — o laco nao morre
            print(f"[{rotulo}] ciclo falhou:\n{traceback.format_exc()}", flush=True)
        parar.wait(minutos * 60)


def rodar() -> int:
    from gemeo.core.config import carregar
    import psycopg2
    cfg = carregar()
    conn = db.conectar(cfg.db_dsn); conn_fonte = psycopg2.connect(cfg.powerplants_dsn)
    hoje = dt.date.today()
    db.garantir_particoes(conn, [hoje, (hoje.replace(day=28) + dt.timedelta(days=4))])
    usinas = usinas_do_piloto(conn, cfg.usinas_piloto)
    if not usinas:
        print("nenhuma usina do piloto em `usina` — rode o cadastro primeiro (gemeo ingest cria as linhas base a partir do config)")
    parar = threading.Event()
    threads = [threading.Thread(target=laco, args=(r, i, m, parar), name=r, daemon=True) for r, i, m in montar(cfg, conn, conn_fonte, usinas)]
    for t in threads:
        t.start()
    try:
        while any(t.is_alive() for t in threads):
            time.sleep(5)
    except KeyboardInterrupt:
        parar.set()
    return 0
```

> Cada ingestor SunOp precisa de conexão própria por thread (psycopg2 não é thread-safe por conexão): na Tarefa 21 o `rodar` passa a abrir uma conexão por laço. Está registrado ali para não ficar esquecido aqui.

- [ ] **Passo 4: Rodar** — 2 passed. **Passo 5: Commit** — `git commit -m "feat(gemeo): runner com um laco por fonte e o comando gemeo ingest"`

---

## Fase C — Modelo

### Tarefa 11: Grade — leituras (do banco ou de fixture) na grade de 15 min

**Files:**
- Create: `gemeo/gemeo/modelar/__init__.py`, `gemeo/gemeo/modelar/grade.py`, `gemeo/tests/test_modelar_grade.py`

**Interfaces:**
- Produces: `@dataclass Grade(usina: UsinaRef, indice: DatetimeIndex (UTC, 15 min), estacao: DataFrame[poa, ghi, temp_modulo, temp_ar], inv_p: DataFrame[cols=ids de inversor], inv_e: DataFrame, trk_ang: DataFrame[cols=ids de tracker], trk_alvo: DataFrame, str_i: DataFrame[cols=ids de string], pai: dict[int,int], tipo: dict[int,str], atributos: dict[int,dict], nome: dict[int,str])`; `carregar_grade(conn, usina, ini, fim, grade_min=15) -> Grade`; `grade_de_fixture(caminho: Path) -> Grade` — mesma estrutura a partir dos golden (`tests/fixtures/golden/*.json`; ids sintéticos: inversores 1000+n, trackers 2000+n, strings 3000+k, estação 1). **A fixture é o que permite testar todo o modelo sem PostgreSQL.**

- [ ] **Passo 1: Escrever o teste que falha**

```python
# gemeo/tests/test_modelar_grade.py
from pathlib import Path
import pandas as pd
from gemeo.modelar import grade

G = Path(__file__).parent / "fixtures" / "golden"


def test_fixture_mro100_vira_grade_de_15_min():
    g = grade.grade_de_fixture(G / "mro100_2026-08-31.json")
    assert g.usina.codigo == "MRO100" and g.indice.freq == pd.Timedelta("15min") and g.indice.tz is not None
    assert g.inv_p.shape[1] == 25 and g.trk_ang.shape[1] == 120 and g.str_i.shape[1] == 36
    # ids sinteticos da fixture: inversor n -> 1000+n, tracker n -> 2000+n, string "inv.k" -> 3000 + inv*100 + k
    assert g.estacao.poa.max() > 900 and g.tipo[2017] == "tracker" and g.pai[3101] == 1001


def test_fixture_santarem_sem_trackers():
    g = grade.grade_de_fixture(G / "santarem1_2026-08-26.json")
    assert g.inv_p.shape[1] == 10 and g.trk_ang.shape[1] == 0 and g.str_i.shape[1] == 0


def test_ts_da_fixture_e_hora_local_convertida_para_utc():
    g = grade.grade_de_fixture(G / "mro100_2026-08-26.json")
    # 12:00 local (Belem, UTC-3) = 15:00 UTC; o pico de POA da MRO100 fica entre 12h e 14h locais
    assert g.estacao.poa.idxmax().tz_convert("America/Belem").hour in (11, 12, 13, 14)
```

- [ ] **Passo 2: Rodar para ver falhar** — `ModuleNotFoundError: gemeo.modelar`

- [ ] **Passo 3: Implementar**

```python
# gemeo/gemeo/modelar/grade.py
"""Leituras → DataFrames na grade de 15 min (UTC). Duas origens, mesma estrutura: o banco e os golden
dos spikes — e o segundo que deixa a suite do modelo rodar sem PostgreSQL."""
from __future__ import annotations
import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from gemeo.core.modelos import UsinaRef

MEDIDAS_ESTACAO = ("poa", "ghi", "temp_modulo", "temp_ar")


@dataclass
class Grade:
    usina: UsinaRef
    indice: pd.DatetimeIndex
    estacao: pd.DataFrame
    inv_p: pd.DataFrame
    inv_e: pd.DataFrame
    trk_ang: pd.DataFrame
    trk_alvo: pd.DataFrame
    str_i: pd.DataFrame
    pai: dict[int, int] = field(default_factory=dict)
    tipo: dict[int, str] = field(default_factory=dict)
    atributos: dict[int, dict] = field(default_factory=dict)
    nome: dict[int, str] = field(default_factory=dict)


def _regrade(df: pd.DataFrame, indice: pd.DatetimeIndex) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(index=indice)
    return df.resample("15min").mean().reindex(indice)


def carregar_grade(conn, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime, grade_min: int = 15) -> Grade:
    with conn.cursor() as cur:
        cur.execute("SELECT id, tipo, pai_id, atributos, coalesce(nome_exibicao, codigo_fonte) FROM equipamento WHERE usina_id=%s AND ativo", (usina.id,))
        eqs = cur.fetchall()
        cur.execute("SELECT l.equipamento_id, l.medida, l.ts, l.valor FROM leitura l JOIN equipamento e ON e.id=l.equipamento_id "
                    "WHERE e.usina_id=%s AND l.ts >= %s AND l.ts < %s", (usina.id, ini, fim))
        rows = cur.fetchall()
    tipo = {i: t for i, t, *_ in eqs}; pai = {i: p for i, _, p, *_ in eqs if p}
    atributos = {i: (a or {}) for i, _, _, a, _ in eqs}; nome = {i: n for i, *_, n in eqs}
    df = pd.DataFrame(rows, columns=["eq", "medida", "ts", "valor"])
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    indice = pd.date_range(pd.Timestamp(ini).floor("15min"), pd.Timestamp(fim).ceil("15min"), freq="15min", tz="UTC")
    def _wide(medida, tipos):
        sub = df[(df.medida == medida) & df.eq.map(tipo).isin(tipos)] if not df.empty else df
        if sub.empty:
            return pd.DataFrame(index=indice)
        return _regrade(sub.pivot_table(index="ts", columns="eq", values="valor", aggfunc="mean"), indice)
    est = pd.DataFrame(index=indice)
    for m in MEDIDAS_ESTACAO:
        w = _wide(m, {"estacao"})
        est[m] = w.mean(axis=1) if not w.empty else float("nan")
    return Grade(usina, indice, est, _wide("p_ac", {"inversor"}), _wide("e_dia", {"inversor"}),
                 _wide("angulo", {"tracker"}), _wide("angulo_alvo", {"tracker"}), _wide("i_string", {"string"}), pai, tipo, atributos, nome)


def grade_de_fixture(caminho: Path) -> Grade:
    j = json.load(open(caminho, encoding="utf-8"))
    tz = ZoneInfo(j["tz"])
    def _serie(d: dict) -> pd.Series:
        if not d:
            return pd.Series(dtype=float)
        s = pd.Series({pd.Timestamp(k).tz_localize(tz).tz_convert("UTC"): float(v) for k, v in d.items()})
        return s.sort_index()
    dia = pd.Timestamp(j["dia"]).tz_localize(tz)
    indice = pd.date_range(dia.tz_convert("UTC"), (dia + pd.Timedelta(days=1)).tz_convert("UTC"), freq="15min", inclusive="left")
    est = pd.DataFrame({m: _serie(j["estacao"].get(m, {})) for m in MEDIDAS_ESTACAO}).reindex(indice)
    tipo, pai, atributos, nome = {}, {}, {}, {}
    def _bloco(chave, base, tipo_eq):
        cols = {}
        for k, d in (j.get(chave) or {}).items():
            eid = base + int(str(k).split(".")[-1]) if tipo_eq != "string" else 3000 + int(str(k).split(".")[0]) * 100 + int(str(k).split(".")[1])
            cols[eid] = _serie(d); tipo[eid] = tipo_eq; nome[eid] = f"{tipo_eq} {k}"
            atributos[eid] = {"numero": int(str(k).split(".")[-1])}
            if tipo_eq == "string":
                pai[eid] = 1000 + int(str(k).split(".")[0])
        return pd.DataFrame(cols).reindex(indice) if cols else pd.DataFrame(index=indice)
    inv_p = _bloco("inv_p", 1000, "inversor"); inv_e = _bloco("inv_e_dia", 1000, "inversor")
    trk_ang = _bloco("trk_ang", 2000, "tracker"); trk_alvo = _bloco("trk_alvo", 2000, "tracker")
    str_i = _bloco("str_i", 3000, "string")
    tipo[1] = "estacao"; nome[1] = "ESTM"
    for eid in inv_p.columns:
        atributos[eid].update({"kwp": j["kwp"] / j["n_inv"], "kw_ac": j["kw_ac"] / j["n_inv"]})
    usina = UsinaRef(id=0, codigo=j["usina"], fonte=j["fonte"], fonte_ref="", tz=j["tz"], kwp=j["kwp"], kw_ac=j["kw_ac"], lat=-2.05, lon=-47.55)
    return Grade(usina, indice, est, inv_p, inv_e, trk_ang, trk_alvo, str_i, pai, tipo, atributos, nome)
```

> O de-para tracker→inversor da fixture (`mro100_trk_inv.json`, nomes `Inversor 1.x`/`2.x`) é aplicado na Tarefa 14 pela função `trk_por_inversor`, que casa `Inversor 1.7` → inversor 1007 pelo número; os 62 trackers cujo nome não existe na aba Equipamentos ficam **sem inversor** de propósito — é o caso real que a tela precisa mostrar.

- [ ] **Passo 4: Rodar** — 3 passed. **Passo 5: Commit** — `git commit -m "feat(gemeo): grade de 15 min a partir do banco ou dos golden dos spikes"`

### Tarefa 12: Gate de duas portas — plausibilidade POA × GHI e cobertura

**Files:**
- Create: `gemeo/gemeo/modelar/gate.py`, `gemeo/tests/test_modelar_gate.py`

**Interfaces:**
- Consumes: `Grade.estacao` (Tarefa 11).
- Produces: `@dataclass ParamsGate(poa_max=1400.0, ghi_max=1400.0, razao_min=0.3, razao_max=3.0, ghi_min_razao=100.0, tolerancia_dia=0.30, horas_min_dia=8.0, ghi_dia=50.0)`; `avaliar(estacao: DataFrame, referencia_razao: float | None, params: ParamsGate, tz: str) -> Resultado(gate: Series[str] ("ok"|"poa_ghi"|"cobertura"|"plausibilidade"), motivo_dia: dict[date, str] ("ok"|"poa_ghi"|"cobertura"), razao_dia: dict[date, float])`. `referencia_razao` é a mediana de POA/GHI dos últimos 30 dias da usina (None no primeiro dia → usa a mediana do próprio intervalo).

- [ ] **Passo 1: Escrever o teste que falha**

```python
# gemeo/tests/test_modelar_gate.py
"""As duas portas. Caso real 1 (Santarem, 02/09): POA leu 0,12 do GHI com inversores normais — sensor
em falha, e um gate por faixa deixaria passar. Caso real 2 (MRO100, 21–24/08): ETM sem dado — sai
por cobertura, nao por plausibilidade."""
import datetime as dt
import numpy as np
import pandas as pd
from pathlib import Path
from gemeo.modelar import gate, grade

G = Path(__file__).parent / "fixtures" / "golden"
P = gate.ParamsGate()


def _dia_limpo():
    g = grade.grade_de_fixture(G / "mro100_2026-08-26.json")
    return g.estacao, g.usina.tz


def test_dia_limpo_passa_inteiro():
    est, tz = _dia_limpo()
    r = gate.avaliar(est, referencia_razao=None, params=P, tz=tz)
    assert r.motivo_dia[dt.date(2026, 8, 26)] == "ok"
    diurno = est.ghi > 50
    assert (r.gate[diurno] == "ok").mean() > 0.95


def test_sensor_de_poa_em_falha_reprova_por_poa_ghi():
    est, tz = _dia_limpo()
    est = est.copy(); est["poa"] = est["poa"] * 0.12            # o caso de Santarem em 02/09
    r = gate.avaliar(est, referencia_razao=1.23, params=P, tz=tz)
    assert r.motivo_dia[dt.date(2026, 8, 26)] == "poa_ghi"
    assert (r.gate[est.ghi > 100] == "poa_ghi").all()


def test_sem_poa_reprova_por_cobertura():
    est, tz = _dia_limpo()
    est = est.copy(); est["poa"] = np.nan                       # ETM muda o dia inteiro (MRO100 21–24/08)
    r = gate.avaliar(est, referencia_razao=1.23, params=P, tz=tz)
    assert r.motivo_dia[dt.date(2026, 8, 26)] == "cobertura"
    assert (r.gate == "cobertura").all()


def test_valor_fora_de_faixa_e_plausibilidade():
    est, tz = _dia_limpo()
    est = est.copy(); i = est.poa.idxmax(); est.loc[i, "poa"] = 2500.0
    r = gate.avaliar(est, referencia_razao=1.23, params=P, tz=tz)
    assert r.gate[i] == "plausibilidade" and r.motivo_dia[dt.date(2026, 8, 26)] == "ok"
```

- [ ] **Passo 2: Rodar para ver falhar** — `ModuleNotFoundError: gemeo.modelar.gate`

- [ ] **Passo 3: Implementar**

```python
# gemeo/gemeo/modelar/gate.py
"""Gate de sensor com DUAS portas. Plausibilidade: faixa e razao POA/GHI (instante e dia). Cobertura:
o instante exige POA; o dia exige horas minimas. O modelo so roda onde o gate diz 'ok'."""
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ParamsGate:
    poa_max: float = 1400.0
    ghi_max: float = 1400.0
    razao_min: float = 0.3
    razao_max: float = 3.0
    ghi_min_razao: float = 100.0
    tolerancia_dia: float = 0.30
    horas_min_dia: float = 8.0
    ghi_dia: float = 50.0


@dataclass
class Resultado:
    gate: pd.Series
    motivo_dia: dict[dt.date, str] = field(default_factory=dict)
    razao_dia: dict[dt.date, float] = field(default_factory=dict)


def avaliar(estacao: pd.DataFrame, referencia_razao: float | None, params: ParamsGate, tz: str) -> Resultado:
    poa, ghi = estacao["poa"], estacao["ghi"]
    dia = pd.Series(estacao.index.tz_convert(ZoneInfo(tz)).date, index=estacao.index)
    gate = pd.Series("ok", index=estacao.index, dtype=object)
    # porta 1a: faixa
    fora = (poa < 0) | (poa > params.poa_max) | (ghi < 0) | (ghi > params.ghi_max)
    gate[fora.fillna(False)] = "plausibilidade"
    # porta 1b: razao POA/GHI no instante e no dia
    razao = (poa / ghi).where(ghi > params.ghi_min_razao)
    ruim_inst = razao.notna() & ~razao.between(params.razao_min, params.razao_max)
    gate[ruim_inst & (gate == "ok")] = "poa_ghi"
    razao_dia = razao.groupby(dia).median()
    ref = referencia_razao if referencia_razao else float(np.nanmedian(razao_dia.values)) if razao_dia.notna().any() else None
    dias_ruins = set(razao_dia[(razao_dia / ref - 1).abs() > params.tolerancia_dia].index) if ref else set()
    gate[dia.isin(dias_ruins) & (gate == "ok")] = "poa_ghi"
    # porta 2: cobertura — instante sem POA nao roda; dia com poucas horas validas nao conta
    gate[poa.isna()] = "cobertura"
    motivo: dict[dt.date, str] = {}
    slots_min = params.horas_min_dia * 4
    for d, idx in dia.groupby(dia).groups.items():
        g = gate.loc[idx]; diurno = (ghi.loc[idx] > params.ghi_dia).sum()
        if d in dias_ruins:
            motivo[d] = "poa_ghi"
        elif (g == "ok").sum() < min(slots_min, max(diurno, 1)) and (g == "ok").sum() < slots_min:
            motivo[d] = "cobertura"
        else:
            motivo[d] = "ok"
        if motivo[d] == "cobertura":
            gate.loc[idx] = gate.loc[idx].where(gate.loc[idx] != "ok", "cobertura")
    return Resultado(gate=gate, motivo_dia=motivo, razao_dia={d: (float(v) if pd.notna(v) else float("nan")) for d, v in razao_dia.items()})
```

- [ ] **Passo 4: Rodar** — 4 passed. **Passo 5: Commit** — `git commit -m "feat(gemeo): gate de duas portas (POA x GHI e cobertura) com os casos reais dos spikes"`

### Tarefa 13: Esperado — PVWatts sobre a POA medida, por inversor

**Files:**
- Create: `gemeo/gemeo/modelar/esperado.py`, `gemeo/tests/test_modelar_esperado.py`

**Interfaces:**
- Consumes: `Grade` (11), `Resultado` do gate (12).
- Produces: `@dataclass ParamsModelo(kwp: float, pac0_kw: float, gamma=-0.0035, perdas_fixas=0.14, eta_inv=0.96, pac0_inferido=False)`; `temp_celula(temp_modulo, temp_ar, poa) -> Series`; `inferir_pac0(p_ac: Series, kw_ac_placa: float | None, kwp: float) -> tuple[float, bool]` (placa quando existe; senão o máximo observado, marcado inferido); `esperado_inversor(poa, temp_cel, p: ParamsModelo) -> Series` (kW); `esperado_por_inversor(grade, gate, params_por_inv: dict[int, ParamsModelo]) -> DataFrame[cols=ids]` (NaN onde o gate ≠ ok).

- [ ] **Passo 1: Escrever o teste que falha**

```python
# gemeo/tests/test_modelar_esperado.py
"""Numeros de referencia: a 1000 W/m2 e 25 C, 277,68 kWp com perdas 14% e eta 0,96 dao 229,2 kW de AC
(277,68 x 0,86 x 0,96) com teto folgado (300 kW); a curva de carga parcial do PVWatts desvia ~0,2%, por isso
rel=1e-2. Teto 1e9 NAO serve: zeta -> 0 zera o AC. Com teto de 200 kW, 200. Zero POA da zero."""
import numpy as np
import pandas as pd
import pytest
from pathlib import Path
from gemeo.modelar import esperado, gate, grade

G = Path(__file__).parent / "fixtures" / "golden"


def test_ponto_de_referencia_stc():
    p = esperado.ParamsModelo(kwp=277.68, pac0_kw=300.0)
    s = esperado.esperado_inversor(pd.Series([1000.0, 0.0]), pd.Series([25.0, 25.0]), p)
    assert s.iloc[0] == pytest.approx(277.68 * 0.86 * 0.96, rel=1e-2) and s.iloc[1] == 0.0


def test_teto_ac_limita():
    p = esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0)
    assert esperado.esperado_inversor(pd.Series([1000.0]), pd.Series([25.0]), p).iloc[0] == pytest.approx(200.0, rel=1e-3)


def test_temperatura_alta_reduz():
    p = esperado.ParamsModelo(kwp=277.68, pac0_kw=300.0)
    frio, quente = esperado.esperado_inversor(pd.Series([800.0, 800.0]), pd.Series([25.0, 55.0]), p)
    assert quente < frio and quente / frio == pytest.approx(1 - 0.0035 * 30, rel=1e-3)


def test_inferir_pac0_prefere_a_placa_e_marca_quando_infere():
    obs = pd.Series([150.0, 200.0, 199.0, 0.0])
    assert esperado.inferir_pac0(obs, kw_ac_placa=214.0, kwp=277.68) == (214.0, False)
    v, inf = esperado.inferir_pac0(obs, kw_ac_placa=None, kwp=277.68)
    assert v == pytest.approx(200.0, abs=0.1) and inf is True  # quantil 0,999 de 4 pontos = 199,997


def test_esperado_por_inversor_respeita_o_gate():
    g = grade.grade_de_fixture(G / "mro100_2026-08-26.json")
    r = gate.avaliar(g.estacao, None, gate.ParamsGate(), g.usina.tz)
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    e = esperado.esperado_por_inversor(g, r, params)
    assert e.shape == g.inv_p.shape
    assert e[r.gate != "ok"].isna().all().all() and e[r.gate == "ok"].notna().all().all()
    assert 0 < e.max().max() <= 200.0
```

- [ ] **Passo 2: Rodar para ver falhar** — `ModuleNotFoundError: gemeo.modelar.esperado`

- [ ] **Passo 3: Implementar**

```python
# gemeo/gemeo/modelar/esperado.py
"""Esperado fisico por inversor: PVWatts (pvlib) sobre a POA MEDIDA. Sem transposicao e sem geometria —
o sensor esta no plano dos modulos (POA/GHI ~1,2 nas usinas de tracker, verificado). O esperado tem de
ser fisico: os modelos aprendidos da saida (POT.ESP, AIML da SunOp) igualam o medido e nao veem perda."""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pvlib


@dataclass(frozen=True)
class ParamsModelo:
    kwp: float
    pac0_kw: float
    gamma: float = -0.0035
    perdas_fixas: float = 0.14
    eta_inv: float = 0.96
    pac0_inferido: bool = False


def temp_celula(temp_modulo: pd.Series, temp_ar: pd.Series, poa: pd.Series) -> pd.Series:
    """Temperatura de modulo medida; sem ela, ar + 0,03 x POA (NOCT simplificado); sem nada, 25 C."""
    return temp_modulo.where(temp_modulo.notna(), (temp_ar + 0.03 * poa.fillna(0))).fillna(25.0)


def inferir_pac0(p_ac: pd.Series, kw_ac_placa: float | None, kwp: float) -> tuple[float, bool]:
    if kw_ac_placa and kw_ac_placa > 0:
        return float(kw_ac_placa), False
    obs = float(np.nanquantile(p_ac.dropna().values, 0.999)) if p_ac.notna().any() else 0.0
    return (obs, True) if obs > 0 else (float(kwp), True)


def esperado_inversor(poa: pd.Series, temp_cel: pd.Series, p: ParamsModelo) -> pd.Series:
    pdc = pvlib.pvsystem.pvwatts_dc(poa.fillna(0).values, temp_cel.fillna(25).values, p.kwp, p.gamma) * (1 - p.perdas_fixas)
    # pdc0 do PVWatts e a entrada DC em que o inversor atinge a placa (pac0 = eta_nom x pdc0): passar a placa
    # direto limitaria em 0,96 x 200 = 192 kW. E a curva de eficiencia tem um termo -0,0059/zeta, entao um
    # "teto infinito" leva zeta a zero e o AC a ZERO - o teto tem de ser realista, nunca 1e9.
    pac = pvlib.inverter.pvwatts(pdc, p.pac0_kw / p.eta_inv, eta_inv_nom=p.eta_inv)
    return pd.Series(np.asarray(pac, dtype=float), index=poa.index)


def esperado_por_inversor(grade, gate_res, params_por_inv: dict[int, ParamsModelo]) -> pd.DataFrame:
    est = grade.estacao
    tcel = temp_celula(est["temp_modulo"], est["temp_ar"], est["poa"])
    ok = gate_res.gate == "ok"
    cols = {}
    for eid, p in params_por_inv.items():
        cols[eid] = esperado_inversor(est["poa"], tcel, p).where(ok)
    return pd.DataFrame(cols, index=grade.indice)
```

- [ ] **Passo 4: Rodar** — 5 passed. **Passo 5: Commit** — `git commit -m "feat(gemeo): esperado fisico por inversor com PVWatts sobre a POA medida"`

### Tarefa 14: Decomposição — parado / tracker / string / resíduo, por inversor e instante

**Files:**
- Create: `gemeo/gemeo/modelar/decomposicao.py`
- Create: `gemeo/tests/sintetico.py` (grade pequena de valores redondos, usada pelas Tarefas 14–16)
- Create: `gemeo/tests/golden.py` (atalhos dos golden tests: fixture → gate → esperado de placa; de-para da MRO100)
- Test: `gemeo/tests/test_modelar_decomposicao.py`

**Interfaces:**
- Consumes: `Grade` (Tarefa 11), `esperado_por_inversor(...) -> DataFrame` (Tarefa 13; NaN onde o gate reprovou), `ParamsModelo`.
- Produces: `ParamsDecomp`, `Decomposicao` (DataFrames na grade: `delta, parado, tracker, string, residuo` por inversor; `ok, parado_flag, viva` booleanos por inversor; `zeradas` por inversor; `excesso` e `perda_trk` por tracker; `instaladas: dict[inv, list[str_id]]`; `trk_sem_inversor: list[int]`), `decompor(grade, esp, trk_inv, p, instaladas=None) -> Decomposicao` (universo de strings instaladas dos últimos 30 dias; `None` = derivar da janela), `trk_inv_da_grade(grade) -> dict[int, int]`, `f_direta(...)`, `excesso_trackers(...)`.
- Regras (spec §8.4): parado = medido < 1 kW com esperado > 20 kW → delta inteiro; tracker = esperado × média, nos trackers do inversor, de `f_direta × (1 − cos(excesso))`, excesso = |ângulo − mediana da frota| só acima de 5°, tracker mudo no último ângulo por até 6 h; string = (esperado − tracker) × zeradas ÷ instaladas; resíduo = resto. Tracker sem inversor → perda estimada com o esperado médio por inversor, atribuída à usina.

- [ ] **Step 1: Escrever a grade sintética, os atalhos golden e os testes (falham: módulo não existe)**

```python
# gemeo/tests/sintetico.py
"""Grade sintetica pequena para os testes de invariantes do modelo: 2 inversores, 3 trackers (o 2003 sem
inversor), 4 strings no inversor 1001, 8 slots por dia a partir das 09:00 de Belem. Valores redondos de
proposito — o teste enxerga a regra, nao o ruido. `dias=3` empilha 29, 30 e 31/08 (para o 'abaixo dos pares')."""
import pandas as pd

from gemeo.core.modelos import UsinaRef
from gemeo.modelar.grade import Grade


def grade_sintetica(n: int = 8, dias: int = 1, poa: float = 800.0, ghi: float = 700.0) -> Grade:
    partes = [pd.date_range(f"2026-08-{28 + k:02d}T12:00", periods=n, freq="15min", tz="UTC") for k in range(4 - dias, 4)]
    idx = partes[0]
    for p in partes[1:]:
        idx = idx.union(p)
    est = pd.DataFrame({"poa": poa, "ghi": ghi, "temp_modulo": 45.0, "temp_ar": 30.0}, index=idx)
    inv_p = pd.DataFrame({1001: 180.0, 1002: 180.0}, index=idx)
    inv_e = pd.DataFrame(index=idx)
    trk = pd.DataFrame({2001: 20.0, 2002: 20.0, 2003: 20.0}, index=idx)   # mediana da frota = 20; o teste desloca um
    alvo = trk.copy()
    strs = pd.DataFrame({3101: 8.0, 3102: 8.0, 3103: 8.0, 3104: 8.0}, index=idx)
    pai = {3101: 1001, 3102: 1001, 3103: 1001, 3104: 1001, 2001: 1001, 2002: 1002}
    tipo = {1001: "inversor", 1002: "inversor", 2001: "tracker", 2002: "tracker", 2003: "tracker",
            3101: "string", 3102: "string", 3103: "string", 3104: "string", 1: "estacao"}
    usina = UsinaRef(id=0, codigo="SINT", fonte="sunop", fonte_ref="", tz="America/Belem", kwp=555.36, kw_ac=400.0, lat=-2.05, lon=-47.55)
    atributos = {1001: {"kwp": 277.68, "kw_ac": 200.0}, 1002: {"kwp": 277.68, "kw_ac": 200.0}}
    return Grade(usina, idx, est, inv_p, inv_e, trk, alvo, strs, pai, tipo, atributos, {})
```

```python
# gemeo/tests/golden.py
"""Atalhos dos golden tests: fixture -> grade -> gate -> esperado de placa (kwp e kw_ac do proprio
inversor), e o de-para tracker->inversor da MRO100 congelado em mro100_trk_inv.json (aba BD_Trackers)."""
import json
from pathlib import Path

import pandas as pd

from gemeo.modelar import esperado, gate, grade

G = Path(__file__).parent / "fixtures" / "golden"


def esperado_de_placa(caminho: Path):
    g = grade.grade_de_fixture(caminho)
    r = gate.avaliar(g.estacao, None, gate.ParamsGate(), g.usina.tz)
    params = {i: esperado.ParamsModelo(kwp=g.atributos[i]["kwp"], pac0_kw=g.atributos[i]["kw_ac"]) for i in g.inv_p.columns}
    return g, r, esperado.esperado_por_inversor(g, r, params)


def sem_gate(g) -> gate.Resultado:
    """Gate 'ok' em todo slot — para a grade sintetica, que tem 2 h e nunca passaria nas 8 h minimas do dia."""
    return gate.Resultado(gate=pd.Series("ok", index=g.indice, dtype=object))


def veredito(caminho: Path) -> dict:
    """O veredito do spike congelado na fixture e o contrato do golden test — quem muda o numero muda a fixture."""
    return json.load(open(caminho, encoding="utf-8"))["veredito_esperado"]


def trk_inv_mro100(g) -> dict[int, int]:
    # "Inversor 1.4" -> INV_4 -> id 1004. O skid 2 numera de outro jeito (pendencia do de-para, ver spec §13):
    # o que nao casa com um inversor da grade fica SEM inversor, e e assim que o modelo deve tratar.
    m = json.load(open(G / "mro100_trk_inv.json", encoding="utf-8"))
    out = {}
    for n, nome in m.items():
        eid = 1000 + int(str(nome).split(".")[-1])
        if eid in g.inv_p.columns:
            out[2000 + int(n)] = eid
    return out
```

```python
# gemeo/tests/test_modelar_decomposicao.py
"""Invariantes (spec §11.1) sobre a grade sintetica e os vereditos dos spikes sobre os golden da MRO100."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))  # sintetico.py e golden.py moram ao lado dos testes
from golden import G, esperado_de_placa, sem_gate, trk_inv_mro100, veredito  # noqa: E402
from sintetico import grade_sintetica  # noqa: E402
from gemeo.modelar import decomposicao as dc  # noqa: E402
from gemeo.modelar import esperado  # noqa: E402

P = dc.ParamsDecomp(f_direta_fixa=0.6)
MAPA = {2001: 1001, 2002: 1002}
UNIVERSO = {1001: [3101, 3102, 3103, 3104], 1002: []}   # strings instaladas, como o job traz dos 30 dias
H = 0.25


def _esp(g):
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    return esperado.esperado_por_inversor(g, sem_gate(g), params)


def test_parcelas_somam_o_delta_onde_ha_dado_e_zeram_onde_nao_ha():
    g = grade_sintetica()
    g.inv_p[1001] = 120.0; g.trk_ang[2002] = 50.0; g.str_i[3104] = 0.0
    g.inv_p.iloc[3, 1] = np.nan
    d = dc.decompor(g, _esp(g), MAPA, P)
    soma = d.parado + d.tracker + d.string + d.residuo
    assert (soma - d.delta).abs().where(d.ok, 0.0).max().max() < 1e-6
    assert soma.where(~d.ok, 0.0).abs().max().max() < 1e-6 and d.delta[1002].isna().sum() == 1


def test_parado_leva_o_delta_inteiro_e_exclui_tracker_e_string():
    g = grade_sintetica()
    g.inv_p[1001] = 0.0; g.trk_ang[2001] = 50.0; g.str_i[3104] = 0.0
    d = dc.decompor(g, _esp(g), MAPA, P)
    assert d.parado_flag[1001].all() and (d.parado[1001] - d.delta[1001]).abs().max() < 1e-6
    assert d.tracker[1001].abs().max() < 1e-6 and d.string[1001].abs().max() < 1e-6 and d.residuo[1001].abs().max() < 1e-6


def test_nan_nunca_vira_perda():
    g = grade_sintetica()
    g.inv_p[1001] = np.nan
    esp = _esp(g); esp[1002] = np.nan
    d = dc.decompor(g, esp, MAPA, P)
    for eid in (1001, 1002):
        assert d.delta[eid].isna().all() and not d.ok[eid].any()
        assert (d.parado[eid].abs() + d.tracker[eid].abs() + d.string[eid].abs() + d.residuo[eid].abs()).max() < 1e-6


def test_tracker_so_conta_acima_de_5_graus_e_vale_cosseno_vezes_fracao_direta():
    g = grade_sintetica()
    g.trk_ang[2002] = 24.0
    assert dc.decompor(g, _esp(g), MAPA, P).tracker[1002].abs().max() < 1e-6
    g.trk_ang[2002] = 50.0
    esp = _esp(g); d = dc.decompor(g, esp, MAPA, P)
    alvo = esp[1002] * 0.6 * (1 - np.cos(np.radians(30.0)))
    assert (d.tracker[1002] - alvo).abs().max() < 1e-6 and (d.excesso[2002] - 30.0).abs().max() < 1e-6


def test_tracker_sem_inversor_vai_para_a_usina():
    g = grade_sintetica()
    g.trk_ang[2003] = 50.0
    d = dc.decompor(g, _esp(g), MAPA, P)
    assert d.trk_sem_inversor == [2003] and d.perda_trk[2003].sum() > 0
    assert d.tracker.abs().max().max() < 1e-6 and d.perda_trk[2001].abs().max() < 1e-6


def test_tracker_mudo_fica_no_ultimo_angulo_por_um_limite_e_depois_e_dado_ausente():
    g = grade_sintetica()
    g.trk_ang[2002] = [50.0, 50.0] + [np.nan] * 6
    d = dc.decompor(g, _esp(g), MAPA, P)
    assert (d.tracker[1002] > 0).all()                       # 6 h de limite cobre os 8 slots
    d2 = dc.decompor(g, _esp(g), MAPA, dc.ParamsDecomp(f_direta_fixa=0.6, trk_mudo_slots=2))
    assert (d2.tracker[1002].iloc[:4] > 0).all() and d2.tracker[1002].iloc[4:].abs().max() < 1e-6
    assert d2.excesso[2002].iloc[4:].isna().all()             # ausente, nao zero: os eventos precisam saber


def test_string_zerada_com_inversor_vivo_e_a_fracao_das_instaladas():
    g = grade_sintetica()
    g.str_i[3104] = 0.0; g.trk_ang[2001] = 50.0
    esp = _esp(g); d = dc.decompor(g, esp, MAPA, P, instaladas=UNIVERSO)
    assert (d.zeradas[1001] == 1).all() and d.instaladas[1001] == [3101, 3102, 3103, 3104]
    assert (d.string[1001] - (esp[1001] - d.tracker[1001]) / 4).abs().max() < 1e-6


def test_string_nao_conta_com_inversor_morto_nem_fora_do_universo_instalado():
    g = grade_sintetica()
    g.str_i[[3101, 3102, 3103]] = 0.3; g.str_i[3104] = 0.0; g.str_i.iloc[0] = 5.0
    d = dc.decompor(g, _esp(g), MAPA, P, instaladas=UNIVERSO)
    assert d.string[1001].abs().max() < 1e-6 and not d.viva[1001].iloc[1:].any()
    g = grade_sintetica()
    g.str_i[3104] = 0.0
    esp = _esp(g); d = dc.decompor(g, esp, MAPA, P, instaladas={1001: [3101, 3102, 3104]})
    assert d.instaladas[1001] == [3101, 3102, 3104] and (d.string[1001] - esp[1001] / 3).abs().max() < 1e-6


def test_universo_instalado_vem_do_historico_ou_da_propria_janela():
    g = grade_sintetica(); g.str_i[3104] = 0.0
    assert dc.decompor(g, _esp(g), MAPA, P).instaladas[1001] == [3101, 3102, 3103]   # so a janela: 3104 nunca passou de 1 A
    assert dc.decompor(g, _esp(g), MAPA, P, instaladas=UNIVERSO).instaladas[1001] == [3101, 3102, 3103, 3104]


@pytest.mark.parametrize("arq", ["mro100_2026-08-26.json", "mro100_2026-08-31.json"])
def test_golden_mro100_reproduz_o_veredito_do_spike(arq):
    g, r, esp = esperado_de_placa(G / arq)
    v = veredito(G / arq)
    d = dc.decompor(g, esp, trk_inv_mro100(g), dc.ParamsDecomp())
    for n in v["inv_parado"]:
        sol = (esp[1000 + int(n)] > 20).fillna(False)
        assert d.parado_flag[1000 + int(n)][sol].mean() > 0.9
    top = list((d.perda_trk.sum() * H).sort_values(ascending=False).index[:5])
    assert {2000 + t for t in v["trackers"]} <= set(top), top
    e_dia = float(esp.sum().sum() * H)
    assert abs(float(d.residuo.sum().sum() * H)) / e_dia < v["residuo_max_pct"] / 100
    assert float(d.string.sum().sum() * H) / e_dia < 0.01
    assert len(d.trk_sem_inversor) < 10
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd gemeo && python -m pytest tests/test_modelar_decomposicao.py -q`
Expected: FAIL — `ModuleNotFoundError: gemeo.modelar.decomposicao`.

- [ ] **Step 3: Implementar a decomposição**

```python
# gemeo/gemeo/modelar/decomposicao.py
"""Decomposicao do delta (esperado - medido) por inversor e instante em quatro parcelas com nome:
parado | tracker | string | residuo. Invariantes que os testes cobram: as parcelas somam o delta onde ha
dado; parado exclui as outras; NaN nunca vira perda; tracker sem inversor no alias vai para a usina."""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pvlib

from gemeo.modelar.grade import Grade


@dataclass(frozen=True)
class ParamsDecomp:
    parado_medido_max: float = 1.0      # kW: abaixo disto o inversor esta parado...
    parado_esperado_min: float = 20.0   # ...desde que o modelo esperasse mais do que isto
    excesso_min_graus: float = 5.0      # abaixo disto o desvio do tracker e ruido (TRK_DISP_LEVE da plataforma)
    trk_mudo_slots: int = 24            # tracker mudo fica no ultimo angulo por ate 6 h; alem disso e dado ausente
    str_zero_a: float = 0.1
    str_viva_a: float = 0.5
    str_instalada_a: float = 1.0
    ghi_min_fdir: float = 50.0
    f_direta_fixa: float | None = None  # testes e usinas sem lat/lon: fracao direta constante em vez de Erbs


@dataclass
class Decomposicao:
    delta: pd.DataFrame
    parado: pd.DataFrame
    tracker: pd.DataFrame
    string: pd.DataFrame
    residuo: pd.DataFrame
    ok: pd.DataFrame
    parado_flag: pd.DataFrame
    viva: pd.DataFrame
    zeradas: pd.DataFrame
    excesso: pd.DataFrame
    perda_trk: pd.DataFrame
    instaladas: dict[int, list[int]] = field(default_factory=dict)
    trk_sem_inversor: list[int] = field(default_factory=list)


def f_direta(estacao: pd.DataFrame, indice: pd.DatetimeIndex, lat, lon, p: ParamsDecomp) -> pd.Series:
    """Fracao direta da irradiancia (Erbs sobre o GHI com a posicao solar): e o quanto o desalinhamento de
    um tracker custa. Sem coordenadas nao ha posicao solar — usa 0,6 (ceu claro tipico) ate o cadastro
    (Info Geral) trazer lat/lon."""
    ghi = estacao["ghi"].fillna(0.0)
    if p.f_direta_fixa is not None or lat is None or lon is None:
        fixa = p.f_direta_fixa if p.f_direta_fixa is not None else 0.6
        return pd.Series(fixa, index=indice).where(ghi > p.ghi_min_fdir, 0.0)
    solpos = pvlib.solarposition.get_solarposition(indice, lat, lon)
    erbs = pvlib.irradiance.erbs(ghi.values, solpos["zenith"].values, indice)
    fd = 1.0 - np.asarray(erbs["dhi"], dtype=float) / np.maximum(ghi.values, 1.0)
    return pd.Series(np.clip(fd, 0.0, 1.0), index=indice).where(ghi > p.ghi_min_fdir, 0.0)


def excesso_trackers(trk_ang: pd.DataFrame, p: ParamsDecomp) -> pd.DataFrame:
    """|angulo - mediana da frota|: zero abaixo do limiar, NaN onde nao ha angulo conhecido. A referencia e a
    FROTA, nao o alvo do proprio tracker — o Tracker 17 da MRO100 (31/08) estava a 0,9 graus do alvo dele e a
    35 da frota: o alvo e que estava errado (mesma regua 'deteccao por alvo' que matou 119 falsos na plataforma)."""
    if trk_ang.empty:
        return pd.DataFrame(index=trk_ang.index)
    ang = trk_ang.ffill(limit=p.trk_mudo_slots)
    exc = ang.sub(ang.median(axis=1), axis=0).abs()
    return exc.where((exc > p.excesso_min_graus) | exc.isna(), 0.0)


def trk_inv_da_grade(grade: Grade) -> dict[int, int]:
    """De-para tracker -> inversor pelo `pai_id` do cadastro (alias bd_trackers resolvido no ingest)."""
    return {e: grade.pai[e] for e, t in grade.tipo.items() if t == "tracker" and e in grade.pai}


def decompor(grade: Grade, esp: pd.DataFrame, trk_inv: dict[int, int], p: ParamsDecomp = ParamsDecomp(),
             instaladas: dict[int, list[int]] | None = None) -> Decomposicao:
    idx = grade.indice
    fd = f_direta(grade.estacao, idx, grade.usina.lat, grade.usina.lon, p)
    exc = excesso_trackers(grade.trk_ang, p)
    frac = (1.0 - np.cos(np.radians(exc))).mul(fd, axis=0) if not exc.empty else exc
    invs = list(esp.columns)

    def zeros(cols):
        return pd.DataFrame(0.0, index=idx, columns=list(cols))

    delta = pd.DataFrame(np.nan, index=idx, columns=invs)
    A, B, C, R, zer = zeros(invs), zeros(invs), zeros(invs), zeros(invs), zeros(invs)
    ok = pd.DataFrame(False, index=idx, columns=invs); par = ok.copy(); viva = ok.copy()
    perda_trk = zeros(frac.columns)
    universo: dict[int, list[int]] = {}
    for eid in invs:
        e = esp[eid]
        m = grade.inv_p[eid] if eid in grade.inv_p.columns else pd.Series(np.nan, index=idx)
        ok_i = e.notna() & m.notna()
        d_i = (e - m).where(ok_i)
        par_i = ok_i & (m < p.parado_medido_max) & (e > p.parado_esperado_min)
        ativo = ok_i & ~par_i
        a = d_i.where(par_i, 0.0)
        meus = [t for t, i in trk_inv.items() if i == eid and t in frac.columns]
        if meus:
            b = (e * frac[meus].mean(axis=1).fillna(0.0)).where(ativo, 0.0)
            for t in meus:
                perda_trk[t] = (e * frac[t] / len(meus)).where(ativo, 0.0).fillna(0.0)
        else:
            b = pd.Series(0.0, index=idx)
        # universo instalado: o job traz os canais com > 1 A nos ultimos 30 dias (uma string morta a janela
        # inteira CONTINUA instalada — e justamente a que interessa); sem esse historico (fixtures), vale a janela
        if instaladas is not None:
            cols = [s for s in instaladas.get(eid, []) if s in grade.str_i.columns]
        else:
            cols = [s for s in grade.str_i.columns if grade.pai.get(s) == eid and grade.str_i[s].max() > p.str_instalada_a]
        universo[eid] = cols
        if cols:
            cur = grade.str_i[cols]
            viva_i = cur.median(axis=1) > p.str_viva_a
            n_zero = (cur < p.str_zero_a).sum(axis=1).where(viva_i, 0)
            c = ((e - b) * n_zero / len(cols)).where(ativo, 0.0)
        else:
            viva_i, n_zero, c = pd.Series(False, index=idx), pd.Series(0, index=idx), pd.Series(0.0, index=idx)
        delta[eid], A[eid], B[eid], C[eid] = d_i, a, b, c
        R[eid] = (d_i - a - b - c).where(ok_i, 0.0)
        ok[eid], par[eid], viva[eid], zer[eid] = ok_i, par_i, viva_i, n_zero.astype(float)
    # tracker sem inversor: perda estimada com o esperado MEDIO por inversor e a densidade media de
    # trackers por inversor; nao entra na cascata de nenhum inversor (quebraria 'parcelas somam o delta'),
    # entra em perda_dia do proprio tracker e no contador trackers_sem_inversor da usina
    sem = [t for t in frac.columns if trk_inv.get(t) not in invs]
    if sem:
        e_ref = esp.mean(axis=1)
        n_por_inv = max(1.0, len(frac.columns) / max(1, len(invs)))
        for t in sem:
            perda_trk[t] = (e_ref * frac[t] / n_por_inv).where(e_ref.notna(), 0.0).fillna(0.0)
    return Decomposicao(delta, A, B, C, R, ok, par, viva, zer, exc, perda_trk, universo, sem)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd gemeo && python -m pytest tests/test_modelar_decomposicao.py -q`
Expected: 11 passed. Se o golden falhar no resíduo ou nos trackers, **não afrouxe o número**: abra a fixture e compare com `resultado.json` do spike — o veredito é o contrato.

- [ ] **Step 5: Commit**

```bash
git add gemeo/gemeo/modelar/decomposicao.py gemeo/tests/sintetico.py gemeo/tests/golden.py gemeo/tests/test_modelar_decomposicao.py
git commit -m "feat(gemeo): decomposicao do delta em parado, tracker, string e residuo (Tarefa 14)"
```

---

### Tarefa 15: Eventos — as seis assinaturas com início, fim, kWh e severidade

**Files:**
- Create: `gemeo/gemeo/modelar/eventos.py`
- Test: `gemeo/tests/test_modelar_eventos.py`

**Interfaces:**
- Consumes: `Grade`, `gate.Resultado` (motivo_dia, razao_dia), `esp` (Tarefa 13), `Decomposicao` (Tarefa 14).
- Produces: `ParamsEventos`, `Evento(tipo, equipamento_id, ini, fim, kwh, severidade, detalhe)`, `severidade(kwh, e_ref) -> str`, `detectar(grade, gate_res, esp, d, p) -> list[Evento]`. A Tarefa 16 persiste em `evento` com upsert por `(usina_id, equipamento_id, tipo, ini)`.
- Regras (spec §8.5): `inversor_parado` ≥ 90 % dos slots com sol (esperado > 20 kW) no dia; `inversor_abaixo` razão do dia < 0,90 × mediana dos pares por 3 dias seguidos (ignora quem já está `parado`); `tracker_fora_alvo` excesso > 10° por ≥ 4 slots diurnos seguidos; `string_sem_corrente` zerada em TODOS os slots vivos do inversor no dia; `sensor_em_falha` / `sem_cobertura` pelo motivo do gate, sempre `grave`. Severidade pelo kWh sobre o esperado do período: < 1 % leve, 1–5 % média, > 5 % grave.

- [ ] **Step 1: Escrever os testes (falham: módulo não existe)**

```python
# gemeo/tests/test_modelar_eventos.py
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from golden import G, esperado_de_placa, sem_gate, trk_inv_mro100, veredito  # noqa: E402
from sintetico import grade_sintetica  # noqa: E402
from gemeo.modelar import decomposicao as dc  # noqa: E402
from gemeo.modelar import esperado, eventos, gate  # noqa: E402

P = dc.ParamsDecomp(f_direta_fixa=0.6)
MAPA = {2001: 1001, 2002: 1002}
UNIVERSO = {1001: [3101, 3102, 3103, 3104], 1002: []}   # strings instaladas, como o job traz dos 30 dias
H = 0.25


def _tudo(g):
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    r = sem_gate(g)
    esp = esperado.esperado_por_inversor(g, r, params)
    return r, esp, dc.decompor(g, esp, MAPA, P, instaladas=UNIVERSO)


def _do_tipo(evs, tipo):
    return [e for e in evs if e.tipo == tipo]


def test_severidade_pelo_kwh_sobre_o_esperado():
    assert eventos.severidade(5.0, 1000.0) == "leve" and eventos.severidade(30.0, 1000.0) == "media"
    assert eventos.severidade(60.0, 1000.0) == "grave" and eventos.severidade(0.0, 0.0) == "leve"


def test_sensor_e_cobertura_viram_evento_grave_de_dia_inteiro():
    g = grade_sintetica(); r, esp, d = _tudo(g)
    dia = g.indice[0].tz_convert("America/Belem").date()
    r.motivo_dia = {dia: "poa_ghi"}; r.razao_dia = {dia: 0.12}
    evs = eventos.detectar(g, r, esp, d)
    ev = _do_tipo(evs, "sensor_em_falha")
    assert len(ev) == 1 and ev[0].severidade == "grave" and ev[0].equipamento_id is None and ev[0].ini == g.indice[0]
    assert ev[0].fim == g.indice[-1] + pd.Timedelta(minutes=15) and ev[0].detalhe["razao_poa_ghi"] == 0.12
    r.motivo_dia = {dia: "cobertura"}
    assert len(_do_tipo(eventos.detectar(g, r, esp, d), "sem_cobertura")) == 1


def test_inversor_parado_o_dia_inteiro():
    g = grade_sintetica(); g.inv_p[1001] = 0.0
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "inversor_parado")
    assert [e.equipamento_id for e in ev] == [1001]
    assert ev[0].kwh == pytest.approx(float(d.parado[1001].sum() * H), rel=1e-6) and ev[0].severidade == "grave"
    assert ev[0].ini == g.indice[0] and ev[0].fim == g.indice[-1] + pd.Timedelta(minutes=15)


def test_inversor_parado_so_uma_parte_do_dia_nao_e_evento():
    g = grade_sintetica(); g.inv_p.iloc[:4, 0] = 0.0
    r, esp, d = _tudo(g)
    assert not _do_tipo(eventos.detectar(g, r, esp, d), "inversor_parado")


def test_inversor_abaixo_dos_pares_por_tres_dias():
    g = grade_sintetica(dias=3); g.inv_p[1002] = 100.0
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "inversor_abaixo")
    assert [e.equipamento_id for e in ev] == [1002] and ev[0].fim is None and ev[0].ini == g.indice[0]
    assert ev[0].kwh == pytest.approx(float((esp[1002] - 100.0).sum() * H), rel=1e-6) and len(ev[0].detalhe["razoes"]) == 3
    g = grade_sintetica(dias=3); g.inv_p.iloc[8:, 1] = 100.0          # so 2 dias abaixo
    r, esp, d = _tudo(g)
    assert not _do_tipo(eventos.detectar(g, r, esp, d), "inversor_abaixo")


def test_tracker_fora_do_alvo_exige_uma_hora_seguida():
    g = grade_sintetica(); g.trk_ang[2002] = [50.0] * 6 + [20.0] * 2
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "tracker_fora_alvo")
    assert [e.equipamento_id for e in ev] == [2002] and ev[0].fim == g.indice[5] + pd.Timedelta(minutes=15)
    assert ev[0].kwh == pytest.approx(float(d.perda_trk[2002].iloc[:6].sum() * H), rel=1e-6) and ev[0].detalhe["excesso_max"] == pytest.approx(30.0, abs=1e-6)
    g = grade_sintetica(); g.trk_ang[2002] = [50.0] * 2 + [20.0] * 6
    r, esp, d = _tudo(g)
    assert not _do_tipo(eventos.detectar(g, r, esp, d), "tracker_fora_alvo")


def test_string_sem_corrente_o_dia_inteiro():
    g = grade_sintetica(); g.str_i[3104] = 0.0
    r, esp, d = _tudo(g)
    ev = _do_tipo(eventos.detectar(g, r, esp, d), "string_sem_corrente")
    assert [e.equipamento_id for e in ev] == [3104] and ev[0].detalhe["inversor_id"] == 1001
    assert ev[0].kwh == pytest.approx(float(d.string[1001].sum() * H), rel=1e-6)
    g = grade_sintetica(); g.str_i.iloc[:4, 3] = 0.0                     # metade do dia nao e 'sem corrente'
    r, esp, d = _tudo(g)
    assert not _do_tipo(eventos.detectar(g, r, esp, d), "string_sem_corrente")


@pytest.mark.parametrize("arq", ["mro100_2026-08-26.json", "mro100_2026-08-31.json"])
def test_golden_mro100_eventos(arq):
    g, r, esp = esperado_de_placa(G / arq)
    v = veredito(G / arq)
    d = dc.decompor(g, esp, trk_inv_mro100(g), dc.ParamsDecomp())
    evs = eventos.detectar(g, r, esp, d)
    assert {e.equipamento_id for e in _do_tipo(evs, "inversor_parado")} == {1000 + int(n) for n in v["inv_parado"]}
    assert {2000 + t for t in v["trackers"]} <= {e.equipamento_id for e in _do_tipo(evs, "tracker_fora_alvo")}
    assert len(_do_tipo(evs, "string_sem_corrente")) == v["strings_sem_corrente"]
    assert not _do_tipo(evs, "sensor_em_falha") and not _do_tipo(evs, "sem_cobertura")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd gemeo && python -m pytest tests/test_modelar_eventos.py -q`
Expected: FAIL — `ImportError: cannot import name 'eventos'`.

- [ ] **Step 3: Implementar os eventos**

```python
# gemeo/gemeo/modelar/eventos.py
"""As seis assinaturas viram `evento` (ini, fim, kWh, severidade). Regras da spec §8.5: as de inversor e de
string sao por DIA LOCAL, a de tracker por corrida de slots, as de sensor pelo motivo do gate. Tudo e
recomputavel: a Tarefa 16 grava por (usina, equipamento, tipo, ini) e o mesmo dia rodado duas vezes da o mesmo."""
from __future__ import annotations
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from gemeo.modelar.decomposicao import Decomposicao
from gemeo.modelar.gate import Resultado
from gemeo.modelar.grade import Grade

H = 0.25  # horas por slot da grade de 15 min
PASSO = pd.Timedelta(minutes=15)


@dataclass(frozen=True)
class ParamsEventos:
    parado_frac_min: float = 0.90
    parado_esperado_min: float = 20.0
    min_slots_sol: int = 4
    abaixo_razao: float = 0.90
    abaixo_dias: int = 3
    trk_excesso_min: float = 10.0
    trk_slots_min: int = 4
    ghi_diurno: float = 50.0
    str_zero_a: float = 0.1
    str_slots_min: int = 4


@dataclass
class Evento:
    tipo: str
    equipamento_id: int | None
    ini: pd.Timestamp
    fim: pd.Timestamp | None
    kwh: float
    severidade: str
    detalhe: dict = field(default_factory=dict)


def severidade(kwh: float, e_ref: float) -> str:
    """< 1 % do esperado do periodo = leve; ate 5 % = media; acima = grave. Sem esperado nao ha regua: leve."""
    if e_ref <= 0:
        return "leve"
    f = kwh / e_ref
    return "leve" if f < 0.01 else "media" if f <= 0.05 else "grave"


def _corridas(mask: pd.Series) -> list[tuple[int, int]]:
    """Sequencias contiguas de True, como (posicao inicial, posicao final) inclusivas."""
    out, ini = [], None
    for i, v in enumerate(mask.fillna(False).values):
        if v and ini is None:
            ini = i
        if not v and ini is not None:
            out.append((ini, i - 1)); ini = None
    if ini is not None:
        out.append((ini, len(mask) - 1))
    return out


def detectar(grade: Grade, gate_res: Resultado, esp: pd.DataFrame, d: Decomposicao, p: ParamsEventos = ParamsEventos()) -> list[Evento]:
    idx = grade.indice
    dia = pd.Series(idx.tz_convert(ZoneInfo(grade.usina.tz)).date, index=idx)
    grupos = dia.groupby(dia).groups
    e_dia = (esp.sum(axis=1, min_count=1).fillna(0.0) * H).groupby(dia).sum()
    diurno = (grade.estacao["ghi"] > p.ghi_diurno).fillna(False)
    evs: list[Evento] = []
    # sensor e cobertura: um evento por dia reprovado, sempre grave — e um dia inteiro sem modelo
    for dd, motivo in gate_res.motivo_dia.items():
        if motivo in ("poa_ghi", "cobertura"):
            sl = idx[(dia == dd).values]
            if len(sl):
                evs.append(Evento("sensor_em_falha" if motivo == "poa_ghi" else "sem_cobertura", None, sl[0], sl[-1] + PASSO, 0.0, "grave",
                                  {"motivo": motivo, "razao_poa_ghi": gate_res.razao_dia.get(dd)}))
    # inversor parado: >= 90 % dos slots COM SOL parados. Sobre as 96 celulas do dia a fracao nunca passava
    # de 0,4 (a noite entra no denominador) — foi o erro do primeiro ensaio na MRO100
    for eid in d.parado_flag.columns:
        sol = (esp[eid] > p.parado_esperado_min).fillna(False)
        for dd, rot in grupos.items():
            s, f = sol.loc[rot], d.parado_flag[eid].loc[rot]
            if s.sum() >= p.min_slots_sol and f[s].mean() >= p.parado_frac_min:
                sl = f[f].index
                kwh = float(d.parado[eid].loc[rot].sum() * H)
                evs.append(Evento("inversor_parado", eid, sl[0], sl[-1] + PASSO, kwh, severidade(kwh, float(e_dia.get(dd, 0.0))),
                                  {"dia": str(dd), "slots_sol": int(s.sum())}))
    parados = {ev.equipamento_id for ev in evs if ev.tipo == "inversor_parado"}
    # inversor abaixo dos pares: razao do dia < 0,90 x mediana dos pares, 3 dias seguidos; medido e esperado
    # mascarados pelos MESMOS instantes (sem isso a razao saia 1,47 no spike: maca com laranja)
    med = grade.inv_p.reindex(columns=esp.columns)
    e_ok, m_ok = esp.where(d.ok), med.where(d.ok)
    r_dia = (m_ok * H).groupby(dia).sum(min_count=1) / (e_ok * H).groupby(dia).sum(min_count=1)
    if len(r_dia) >= p.abaixo_dias:
        ult = list(r_dia.index[-p.abaixo_dias:])
        rel = r_dia.div(r_dia.median(axis=1), axis=0)
        for eid in r_dia.columns:
            v = rel.loc[ult, eid]
            if eid in parados or not v.notna().all() or not (v < p.abaixo_razao).all():
                continue
            falta = (e_ok[eid] - m_ok[eid]).clip(lower=0.0)
            kwh = float(falta[dia.isin(ult).values].sum() * H)
            evs.append(Evento("inversor_abaixo", eid, idx[(dia == ult[0]).values][0], None, kwh, severidade(kwh, float(e_dia.reindex(ult).sum())),
                              {"razoes": [round(float(x), 3) for x in v]}))
    # tracker fora do alvo: excesso > 10 graus por >= 1 h seguida, de dia; NaN (mudo ha mais de 6 h) nao e desvio
    for t in d.excesso.columns:
        mask = (d.excesso[t] > p.trk_excesso_min) & diurno
        for a, b in _corridas(mask):
            if b - a + 1 < p.trk_slots_min:
                continue
            kwh = float(d.perda_trk[t].iloc[a:b + 1].sum() * H)
            evs.append(Evento("tracker_fora_alvo", t, idx[a], idx[b] + PASSO, kwh, severidade(kwh, float(e_dia.get(dia.iloc[a], 0.0))),
                              {"excesso_max": float(d.excesso[t].iloc[a:b + 1].max())}))
    # string sem corrente: zerada em TODOS os slots em que o inversor estava vivo — a regua da plataforma;
    # o kWh e a parcela 'string' do inversor dividida entre as zeradas
    for eid, cols in d.instaladas.items():
        if not cols:
            continue
        cur = grade.str_i[cols]
        for dd, rot in grupos.items():
            viva = d.viva[eid].loc[rot]
            if viva.sum() < p.str_slots_min:
                continue
            n_zer = d.zeradas[eid].loc[rot].replace(0, np.nan)
            for s in cols:
                zer = cur[s].loc[rot] < p.str_zero_a
                if zer[viva].all():
                    sl = zer[viva].index
                    kwh = float((d.string[eid].loc[rot] / n_zer).fillna(0.0).sum() * H)
                    evs.append(Evento("string_sem_corrente", s, sl[0], sl[-1] + PASSO, kwh, severidade(kwh, float(e_dia.get(dd, 0.0))),
                                      {"dia": str(dd), "inversor_id": eid}))
    return evs
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd gemeo && python -m pytest tests/test_modelar_eventos.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add gemeo/gemeo/modelar/eventos.py gemeo/tests/test_modelar_eventos.py
git commit -m "feat(gemeo): as seis assinaturas viram eventos com kWh e severidade (Tarefa 15)"
```

---

### Tarefa 16: Cascata diária, `perda_dia` e o job `gemeo modelar` (persistência idempotente)

**Files:**
- Create: `gemeo/gemeo/modelar/rollup.py`
- Create: `gemeo/gemeo/modelar/job.py`
- Create: `gemeo/tests/semear.py` (fixture golden → banco de teste; serve ao job e ao app)
- Test: `gemeo/tests/test_modelar_rollup.py` (pandas puro, roda sem banco)
- Test: `gemeo/tests/test_modelar_job.py` (banco; pula sem `GEMEO_TEST_DSN`)

**Interfaces:**
- Consumes: `Grade`/`carregar_grade` (T11), `gate.avaliar/ParamsGate/Resultado` (T12), `esperado.*` (T13), `decomposicao.decompor/trk_inv_da_grade` (T14), `eventos.detectar/Evento` (T15), `db.conectar/gravar_estado` (T2–3), `runner.usinas_do_piloto` (T10).
- Produces: `rollup.Cascata(por_dia, perda_dia, razao_inv_dia)`, `rollup.cascata(grade, gate_res, esp, d, ghi_diurno=50, str_zero_a=0.1) -> Cascata`; `job.Modelo`, `job.modelo_ativo(conn, usina_id)`, `job.params_por_inversor(grade, mod, p_ac_hist)`, `job.instaladas_30d`, `job.p_ac_30d`, `job.referencia_razao`, `job.janela_padrao(agora, tz)`, `job.modelar(conn, usina, ini, fim, mod=None) -> dict`, `job.persistir(...)`, `job.rodar_cli(ini, fim, usina)`. Estado `modelar.ultimo` (JSON) para o `/healthz` da Tarefa 18.
- Contrato: o job carrega **3 dias locais** (o "abaixo dos pares" exige 3; hoje é recomputado a cada 15 min), grava `esperado` por upsert e **apaga-e-regrava** `cascata_dia`, `perda_dia` e `evento` da janela — rodar duas vezes deixa o banco igual.

- [ ] **Step 1: Escrever a semeadura e os testes (falham: módulos não existem)**

```python
# gemeo/tests/semear.py
"""Semeia o banco de teste com uma fixture golden: usina, equipamentos (estacao, inversores, trackers com
pai pelo de-para, strings) e leituras em UTC. Devolve a UsinaRef e o mapa 'chave da fixture' -> id.
Serve ao teste do job (Tarefa 16) e aos do app (Tarefa 18)."""
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from gemeo.core import db
from gemeo.core.modelos import UsinaRef


def semear_fixture(conn, caminho: Path, trk_inv: dict[str, str] | None = None) -> tuple[UsinaRef, dict]:
    j = json.load(open(caminho, encoding="utf-8"))
    tz = ZoneInfo(j["tz"]); n_inv = int(j["n_inv"])
    ids: dict[str, int] = {}
    with conn.cursor() as cur:
        cur.execute("INSERT INTO usina (codigo, nome, fonte, fonte_ref, tz, kwp_dc, kw_ac, n_inversores, lat, lon) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (j["usina"], j["usina"], j["fonte"], j["usina"], j["tz"], j["kwp"], j["kw_ac"], n_inv, -2.05, -47.55))
        uid = cur.fetchone()[0]

        def eq(tipo, codigo, pai=None, atributos=None):
            cur.execute("INSERT INTO equipamento (usina_id, tipo, codigo_fonte, pai_id, atributos) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                        (uid, tipo, codigo, pai, json.dumps(atributos or {})))
            return cur.fetchone()[0]

        ids["estacao"] = eq("estacao", "ESTM")
        for n in j["inv_p"]:
            ids[f"inv:{n}"] = eq("inversor", f"INV_{n}", None, {"numero": int(n), "kwp": j["kwp"] / n_inv, "kw_ac": j["kw_ac"] / n_inv})
        for n in (j.get("trk_ang") or {}):
            pai = ids.get("inv:" + str(trk_inv[n]).split(".")[-1]) if trk_inv and n in trk_inv else None
            ids[f"trk:{n}"] = eq("tracker", f"TRK_{n}", pai, {"numero": int(n)})
        for k in (j.get("str_i") or {}):
            i, s = k.split(".")
            ids[f"str:{k}"] = eq("string", f"INV_{i}.I_PV{s}", ids[f"inv:{i}"], {"numero": int(s)})
    conn.commit()

    def ts_utc(k):
        return pd.Timestamp(k).tz_localize(tz).tz_convert("UTC").to_pydatetime()

    linhas = [(ids["estacao"], m, ts_utc(k), v) for m, serie in j["estacao"].items() for k, v in serie.items()]
    for chave, pref, medida in (("inv_p", "inv", "p_ac"), ("inv_e_dia", "inv", "e_dia"), ("trk_ang", "trk", "angulo"),
                                ("trk_alvo", "trk", "angulo_alvo"), ("str_i", "str", "i_string")):
        for k, serie in (j.get(chave) or {}).items():
            linhas += [(ids[f"{pref}:{k}"], medida, ts_utc(t), v) for t, v in serie.items()]
    db.upsert_leituras(conn, linhas)
    usina = UsinaRef(id=uid, codigo=j["usina"], fonte=j["fonte"], fonte_ref=j["usina"], tz=j["tz"], kwp=j["kwp"], kw_ac=j["kw_ac"], lat=-2.05, lon=-47.55)
    return usina, ids
```

```python
# gemeo/tests/test_modelar_rollup.py
"""Invariantes da cascata na grade sintetica e os vereditos dos spikes (Santarem 1: inversor 106 parado e os
saos entre 0,90 e 1,05; MRO100 31/08: parado ~1,6 MWh e trackers ~0,1 MWh, como o spike registrou)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from golden import G, esperado_de_placa, sem_gate, trk_inv_mro100, veredito  # noqa: E402
from sintetico import grade_sintetica  # noqa: E402
from gemeo.modelar import decomposicao as dc  # noqa: E402
from gemeo.modelar import esperado, rollup  # noqa: E402

P = dc.ParamsDecomp(f_direta_fixa=0.6)
MAPA = {2001: 1001, 2002: 1002}
UNIVERSO = {1001: [3101, 3102, 3103, 3104], 1002: []}
H = 0.25


def _tudo(g):
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    r = sem_gate(g)
    esp = esperado.esperado_por_inversor(g, r, params)
    return r, esp, dc.decompor(g, esp, MAPA, P, instaladas=UNIVERSO)


def test_cascata_fecha_por_dia_e_perda_dia_bate_com_a_cascata():
    g = grade_sintetica(dias=2)
    g.inv_p[1001] = 120.0; g.trk_ang[2002] = 50.0; g.str_i[3104] = 0.0
    g.trk_ang[2003] = -10.0   # -10 e nao 50: com dois em 50 a MEDIANA da frota viraria 50 e o 2001 e que ficaria 'fora'
    r, esp, d = _tudo(g)
    c = rollup.cascata(g, r, esp, d)
    assert len(c.por_dia) == 2 and (c.por_dia.delta - (c.por_dia.e_esperado - c.por_dia.e_medido)).abs().max() < 1e-6
    soma = c.por_dia[list(rollup.PARCELAS)].sum(axis=1)
    assert (soma - c.por_dia.delta).abs().max() < 1e-6
    assert c.por_dia.cobertura_gate.between(0, 1).all() and (c.por_dia.trackers_sem_inversor == 1).all()
    inv = c.perda_dia[c.perda_dia.equipamento_id.isin(esp.columns)]
    for parcela in rollup.PARCELAS:
        por_dia = inv[inv.parcela == parcela].groupby("dia").kwh.sum().reindex(c.por_dia.index).fillna(0.0)
        assert (por_dia - c.por_dia[parcela]).abs().max() < 1e-6, parcela
    trk = c.perda_dia[c.perda_dia.equipamento_id == 2003]
    assert len(trk) == 2 and (trk.parcela == "tracker").all() and (trk.kwh > 0).all()
    strs = c.perda_dia[c.perda_dia.equipamento_id == 3104]
    assert (strs.kwh.values - c.por_dia.string.values < 1e-6).all() and (strs.parcela == "string").all()


def test_cascata_nao_inventa_energia_onde_nao_ha_dado():
    g = grade_sintetica(); g.inv_p[1001] = np.nan
    r, esp, d = _tudo(g)
    c = rollup.cascata(g, r, esp, d)
    assert c.por_dia.e_esperado.iloc[0] == pytest.approx(float(esp[1002].sum() * H), rel=1e-6)
    assert c.razao_inv_dia[1001].isna().all() and c.razao_inv_dia[1002].notna().all()


@pytest.mark.parametrize("arq", ["santarem1_2026-08-26.json", "santarem1_2026-09-01.json"])
def test_golden_santarem_inversor_106_parado_e_saos_dentro_da_faixa(arq):
    g, r, esp = esperado_de_placa(G / arq); v = veredito(G / arq)
    d = dc.decompor(g, esp, {}, dc.ParamsDecomp())
    c = rollup.cascata(g, r, esp, d)
    parados = {1000 + int(n) for n in v["inv_parado"]}
    dia = c.por_dia.index[0]
    for eid in parados:
        assert c.perda_dia[(c.perda_dia.equipamento_id == eid) & (c.perda_dia.parcela == "inv_parado")].kwh.sum() > 0
    saos = c.razao_inv_dia.loc[dia].drop(list(parados))
    assert saos.between(v["razao_saos_min"], v["razao_saos_max"]).all(), saos.round(3).to_dict()


def test_golden_mro100_31_08_reproduz_a_cascata_do_spike():
    g, r, esp = esperado_de_placa(G / "mro100_2026-08-31.json")
    d = dc.decompor(g, esp, trk_inv_mro100(g), dc.ParamsDecomp())
    c = rollup.cascata(g, r, esp, d)
    x = c.por_dia.iloc[0]
    # resultado.json do spike 2 em 31/08: inv_parado 1634,9 | tracker 102,6 | string 0,3 | esperado 41068 | medido 38971
    assert x.inv_parado == pytest.approx(1634.9, rel=0.05) and x.tracker == pytest.approx(102.6, rel=0.10)
    assert x.e_medido == pytest.approx(38971.0, rel=0.02) and x.e_esperado == pytest.approx(41068.0, rel=0.03)
    assert x.string < 5.0 and x.cobertura_gate > 0.9
```

```python
# gemeo/tests/test_modelar_job.py
"""Job de ponta a ponta sobre o banco semeado com a fixture golden da MRO100 (31/08): persiste esperado,
cascata_dia, perda_dia e evento, e rodar duas vezes deixa o banco IGUAL. Pula sem GEMEO_TEST_DSN."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from semear import semear_fixture  # noqa: E402
from gemeo.modelar import job  # noqa: E402

G = Path(__file__).parent / "fixtures" / "golden"
UTC = dt.timezone.utc


@pytest.fixture
def mro100(conn):
    trk_inv = json.load(open(G / "mro100_trk_inv.json", encoding="utf-8"))
    usina, ids = semear_fixture(conn, G / "mro100_2026-08-31.json", trk_inv)
    yield usina, ids
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evento; DELETE FROM perda_dia; DELETE FROM cascata_dia; DELETE FROM esperado; "
                    "DELETE FROM modelo; DELETE FROM leitura; DELETE FROM equipamento; DELETE FROM usina; DELETE FROM estado")
    conn.commit()


def _foto(conn):
    out = []
    with conn.cursor() as cur:
        for sql in ("SELECT count(*), round(sum(p_esperado_kw)::numeric, 3) FROM esperado",
                    "SELECT count(*), round(sum(delta)::numeric, 3) FROM cascata_dia",
                    "SELECT count(*), round(sum(kwh)::numeric, 3) FROM perda_dia",
                    "SELECT count(*), round(sum(kwh)::numeric, 3) FROM evento"):
            cur.execute(sql); out.append(cur.fetchone())
    return out


def test_job_persiste_e_e_idempotente(conn, mro100):
    usina, ids = mro100
    ini, fim = dt.datetime(2026, 8, 31, 3, 0, tzinfo=UTC), dt.datetime(2026, 9, 1, 3, 0, tzinfo=UTC)   # 00:00 -> 24:00 de Belem
    res = job.modelar(conn, usina, ini, fim)
    assert res["modelo"] == "placa" and res["dias"] >= 1 and res["e_esperado"] > 30000 and res["inferidos"] == 0
    foto1 = _foto(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT e_esperado, e_medido, inv_parado, tracker, cobertura_gate FROM cascata_dia WHERE usina_id=%s AND dia=%s", (usina.id, dt.date(2026, 8, 31)))
        e_esp, e_med, parado, tracker, cob = cur.fetchone()
        assert e_esp > e_med and parado > 1000 and tracker > 50 and cob > 0.9
        cur.execute("SELECT equipamento_id FROM evento WHERE tipo='inversor_parado'")
        assert {r[0] for r in cur.fetchall()} == {ids["inv:22"]}
        cur.execute("SELECT count(*) FROM evento WHERE tipo='tracker_fora_alvo' AND equipamento_id = ANY(%s)", ([ids["trk:4"], ids["trk:17"]],))
        assert cur.fetchone()[0] >= 2
        cur.execute("SELECT count(*) FROM esperado WHERE gate='ok' AND p_esperado_kw IS NULL")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT versao, ativo, tolerancia FROM modelo")
        assert cur.fetchone() == ("placa", True, 0.08)
    job.modelar(conn, usina, ini, fim)
    assert _foto(conn) == foto1


def test_janela_padrao_cobre_tres_dias_locais():
    agora = dt.datetime(2026, 9, 3, 15, 7, tzinfo=UTC)          # 12:07 em Belem
    ini, fim = job.janela_padrao(agora, "America/Belem")
    assert ini == dt.datetime(2026, 9, 1, 3, 0, tzinfo=UTC) and fim == agora
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd gemeo && python -m pytest tests/test_modelar_rollup.py tests/test_modelar_job.py -q`
Expected: FAIL — `ImportError: cannot import name 'rollup'`; os de banco pulam sem DSN.

- [ ] **Step 3: Implementar a cascata e o job**

```python
# gemeo/gemeo/modelar/rollup.py
"""Do instante ao dia: `cascata_dia` (usina) e `perda_dia` (equipamento), em kWh, por dia LOCAL. O medido
que entra no delta e o MASCARADO pelos mesmos instantes do esperado (maca com maca — sem isso a razao
saia 1,47 no spike); o contador do dia fica para a meta, que nao tem gate. So DataFrames: quem persiste
e o job."""
from __future__ import annotations
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from gemeo.modelar.decomposicao import Decomposicao
from gemeo.modelar.gate import Resultado
from gemeo.modelar.grade import Grade

H = 0.25
PARCELAS = ("inv_parado", "tracker", "string", "residuo")


@dataclass
class Cascata:
    por_dia: pd.DataFrame        # index dia local; e_esperado, e_medido, delta, 4 parcelas, cobertura_gate, trackers_sem_inversor
    perda_dia: pd.DataFrame      # equipamento_id, dia, parcela, kwh — so kwh != 0
    razao_inv_dia: pd.DataFrame  # index dia, coluna por inversor: medido/esperado nos mesmos instantes


def cascata(grade: Grade, gate_res: Resultado, esp: pd.DataFrame, d: Decomposicao,
            ghi_diurno: float = 50.0, str_zero_a: float = 0.1) -> Cascata:
    idx = grade.indice
    dia = pd.Series(idx.tz_convert(ZoneInfo(grade.usina.tz)).date, index=idx)
    med = grade.inv_p.reindex(columns=esp.columns)
    e_ok, m_ok = esp.where(d.ok), med.where(d.ok)
    e_esp = (e_ok.sum(axis=1, min_count=1).fillna(0.0) * H).groupby(dia).sum()
    e_med = (m_ok.sum(axis=1, min_count=1).fillna(0.0) * H).groupby(dia).sum()
    por_dia = pd.DataFrame({"e_esperado": e_esp, "e_medido": e_med, "delta": e_esp - e_med})
    frames = {"inv_parado": d.parado, "tracker": d.tracker, "string": d.string, "residuo": d.residuo}
    for nome, df in frames.items():
        por_dia[nome] = (df.sum(axis=1) * H).groupby(dia).sum()
    diurno = (grade.estacao["ghi"] > ghi_diurno).fillna(False)
    ok_diurno = ((gate_res.gate == "ok") & diurno).groupby(dia).sum()
    por_dia["cobertura_gate"] = (ok_diurno / diurno.groupby(dia).sum().replace(0, np.nan)).fillna(0.0)
    por_dia["trackers_sem_inversor"] = len(d.trk_sem_inversor)
    linhas: list[tuple] = []

    def junta(eid, serie_kw, parcela):
        for dd, v in (serie_kw * H).groupby(dia).sum().items():
            if abs(v) > 1e-9:
                linhas.append((int(eid), dd, parcela, float(v)))

    for eid in esp.columns:
        for nome, df in frames.items():
            junta(eid, df[eid], nome)
    for t in d.perda_trk.columns:            # mapeados e sem inversor: a perda e do proprio tracker
        junta(t, d.perda_trk[t], "tracker")
    for eid, cols in d.instaladas.items():   # a parcela do inversor dividida entre as zeradas de cada slot
        if not cols:
            continue
        quota = (d.string[eid] / d.zeradas[eid].replace(0, np.nan)).fillna(0.0)
        for s in cols:
            junta(s, quota.where((grade.str_i[s] < str_zero_a) & d.viva[eid], 0.0), "string")
    perda = pd.DataFrame(linhas, columns=["equipamento_id", "dia", "parcela", "kwh"])
    razao = ((m_ok * H).groupby(dia).sum(min_count=1)) / ((e_ok * H).groupby(dia).sum(min_count=1))
    return Cascata(por_dia, perda, razao)
```

```python
# gemeo/gemeo/modelar/job.py
"""`gemeo modelar`: para cada usina do piloto, carrega os ultimos 3 dias locais (o 'abaixo dos pares' pede
3 dias, e o dia de hoje e recomputado a cada 15 min), roda gate -> esperado -> decomposicao -> eventos ->
cascata e persiste por chave natural. Idempotente: rodar duas vezes deixa o banco igual."""
from __future__ import annotations
import datetime as dt
import json
import time
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import psycopg2.extras

from gemeo.core.modelos import UsinaRef
from gemeo.modelar import decomposicao as dc
from gemeo.modelar import esperado as esp_mod
from gemeo.modelar import eventos as ev_mod
from gemeo.modelar import gate as gate_mod
from gemeo.modelar import rollup
from gemeo.modelar.grade import Grade, carregar_grade

PLACA = {"gamma": -0.0035, "perdas_fixas": 0.14, "eta_inv": 0.96, "gate": {}}
DIAS_CONTEXTO = 3


@dataclass(frozen=True)
class Modelo:
    id: int
    versao: str
    parametros: dict
    tolerancia: float
    calibrado: bool


def modelo_ativo(conn, usina_id: int) -> Modelo:
    """A versao ativa; sem nenhuma, nasce a 'placa' (gamma -0,35 %/C, perdas 14 %, eta 0,96, tolerancia 0,08,
    calibrado=false) — e a faixa 'modelo de placa — nao calibrado' das telas vem daqui."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, versao, parametros, tolerancia, calibrado FROM modelo WHERE usina_id=%s AND ativo", (usina_id,))
        r = cur.fetchone()
        if r is None:
            cur.execute("INSERT INTO modelo (usina_id, versao, parametros, tolerancia, calibrado, ativo) VALUES (%s,'placa',%s,0.08,false,true) "
                        "ON CONFLICT (usina_id, versao) DO UPDATE SET ativo=true RETURNING id, versao, parametros, tolerancia, calibrado",
                        (usina_id, json.dumps(PLACA)))
            r = cur.fetchone()
    conn.commit()
    return Modelo(int(r[0]), r[1], r[2] if isinstance(r[2], dict) else json.loads(r[2]), float(r[3]), bool(r[4]))


def params_por_inversor(grade: Grade, mod: Modelo, p_ac_hist: dict[int, pd.Series] | None = None) -> dict[int, esp_mod.ParamsModelo]:
    """kwp e kw_ac do proprio inversor (equipamento.atributos, vindos do cadastro); sem kwp, a placa da usina
    dividida pelos inversores; sem kw_ac, infere do maximo observado (30 dias se o job trouxe, senao a
    janela) e marca `pac0_inferido` — a tela mostra."""
    invs = [e for e, t in grade.tipo.items() if t == "inversor"]
    pr = mod.parametros
    out = {}
    for eid in invs:
        at = grade.atributos.get(eid, {})
        kwp = float(at.get("kwp") or (grade.usina.kwp / max(1, len(invs))))
        serie = (p_ac_hist or {}).get(eid)
        if serie is None:
            serie = grade.inv_p[eid] if eid in grade.inv_p.columns else pd.Series(dtype=float)
        pac0, inferido = esp_mod.inferir_pac0(serie, at.get("kw_ac"), kwp)
        out[eid] = esp_mod.ParamsModelo(kwp=kwp, pac0_kw=pac0, gamma=float(pr.get("gamma", PLACA["gamma"])),
                                        perdas_fixas=float(pr.get("perdas_fixas", PLACA["perdas_fixas"])),
                                        eta_inv=float(pr.get("eta_inv", PLACA["eta_inv"])), pac0_inferido=inferido)
    return out


def instaladas_30d(conn, usina_id: int, ate: dt.datetime, dias: int = 30) -> dict[int, list[int]]:
    """Universo de strings: canal com > 1 A em algum momento dos ultimos 30 dias, agrupado pelo inversor pai."""
    with conn.cursor() as cur:
        cur.execute("SELECT e.pai_id, e.id FROM leitura l JOIN equipamento e ON e.id=l.equipamento_id "
                    "WHERE e.usina_id=%s AND e.tipo='string' AND l.medida='i_string' AND l.ts >= %s AND l.ts < %s "
                    "GROUP BY e.pai_id, e.id HAVING max(l.valor) > 1.0 ORDER BY e.pai_id, e.id",
                    (usina_id, ate - dt.timedelta(days=dias), ate))
        out: dict[int, list[int]] = {}
        for pai, sid in cur.fetchall():
            out.setdefault(pai, []).append(sid)
    return out


def p_ac_30d(conn, usina_id: int, ate: dt.datetime, dias: int = 30) -> dict[int, pd.Series]:
    """Quantil 0,999 da potencia AC por inversor nos ultimos 30 dias, calculado no banco — e o que
    `inferir_pac0` precisa quando o cadastro nao traz kw_ac."""
    with conn.cursor() as cur:
        cur.execute("SELECT e.id, percentile_cont(0.999) WITHIN GROUP (ORDER BY l.valor) FROM leitura l "
                    "JOIN equipamento e ON e.id=l.equipamento_id WHERE e.usina_id=%s AND e.tipo='inversor' AND l.medida='p_ac' "
                    "AND l.ts >= %s AND l.ts < %s AND l.valor > 0 GROUP BY e.id", (usina_id, ate - dt.timedelta(days=dias), ate))
        return {int(eid): pd.Series([float(q)]) for eid, q in cur.fetchall() if q is not None}


def referencia_razao(conn, usina_id: int, ate: dt.datetime, tz: str = "UTC", dias: int = 30) -> float | None:
    """Referencia movel do gate: mediana, em 30 dias, da mediana diaria de POA/GHI (GHI > 100). Com menos
    de 3 dias devolve None e o gate usa a propria janela."""
    with conn.cursor() as cur:
        cur.execute("SELECT (p.ts AT TIME ZONE %s)::date, percentile_cont(0.5) WITHIN GROUP (ORDER BY p.valor / g.valor) "
                    "FROM leitura p JOIN leitura g ON g.equipamento_id=p.equipamento_id AND g.ts=p.ts AND g.medida='ghi' "
                    "JOIN equipamento e ON e.id=p.equipamento_id "
                    "WHERE e.usina_id=%s AND e.tipo='estacao' AND p.medida='poa' AND g.valor > 100 AND p.ts >= %s AND p.ts < %s "
                    "GROUP BY 1", (tz, usina_id, ate - dt.timedelta(days=dias), ate))
        vals = [float(v) for _, v in cur.fetchall() if v is not None]
    return float(np.median(vals)) if len(vals) >= 3 else None


def janela_padrao(agora: dt.datetime, tz: str, dias: int = DIAS_CONTEXTO) -> tuple[dt.datetime, dt.datetime]:
    local = agora.astimezone(ZoneInfo(tz))
    ini = (local - dt.timedelta(days=dias - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return ini.astimezone(dt.timezone.utc), agora


def persistir(conn, usina: UsinaRef, mod: Modelo, grade: Grade, r: gate_mod.Resultado, esp: pd.DataFrame,
              evs: list[ev_mod.Evento], casc: rollup.Cascata) -> None:
    est = grade.estacao
    tcel = esp_mod.temp_celula(est["temp_modulo"], est["temp_ar"], est["poa"])
    linhas = []
    for eid in esp.columns:
        col = esp[eid]
        for ts, g in r.gate.items():
            poa = est["poa"].get(ts)
            if poa is None or pd.isna(poa):      # sem POA nao ha o que dizer: a ausencia e o evento de cobertura
                continue
            v = col.get(ts); t = tcel.get(ts)
            linhas.append((int(eid), ts.to_pydatetime(), mod.id, None if pd.isna(v) else float(v), float(poa),
                           None if pd.isna(t) else float(t), str(g)))
    dias = [d for d in casc.por_dia.index]
    ini_g, fim_g = grade.indice[0].to_pydatetime(), (grade.indice[-1] + pd.Timedelta(minutes=15)).to_pydatetime()
    with conn.cursor() as cur:
        if linhas:
            psycopg2.extras.execute_values(
                cur, "INSERT INTO esperado (equipamento_id, ts, modelo_id, p_esperado_kw, poa_usada, temp_usada, gate) VALUES %s "
                     "ON CONFLICT (equipamento_id, ts, modelo_id) DO UPDATE SET p_esperado_kw=EXCLUDED.p_esperado_kw, "
                     "poa_usada=EXCLUDED.poa_usada, temp_usada=EXCLUDED.temp_usada, gate=EXCLUDED.gate", linhas, page_size=5000)
        # apaga-e-regrava a janela: e o que torna o job idempotente sem chave para 'evento sem equipamento'
        cur.execute("DELETE FROM cascata_dia WHERE usina_id=%s AND modelo_id=%s AND dia = ANY(%s)", (usina.id, mod.id, dias))
        cur.execute("DELETE FROM perda_dia WHERE modelo_id=%s AND dia = ANY(%s) AND equipamento_id IN (SELECT id FROM equipamento WHERE usina_id=%s)",
                    (mod.id, dias, usina.id))
        cur.execute("DELETE FROM evento WHERE usina_id=%s AND modelo_id=%s AND ini >= %s AND ini < %s", (usina.id, mod.id, ini_g, fim_g))
        # 'abaixo dos pares' e sempre recomputado dos ultimos 3 dias: o aberto de ontem sai, o de hoje entra
        cur.execute("DELETE FROM evento WHERE usina_id=%s AND modelo_id=%s AND tipo='inversor_abaixo' AND fim IS NULL", (usina.id, mod.id))
        casc_rows = [(usina.id, dd, mod.id, float(x.e_esperado), float(x.e_medido), float(x.delta), float(x.inv_parado), float(x.tracker),
                      float(x.string), float(x.residuo), float(x.cobertura_gate), int(x.trackers_sem_inversor))
                     for dd, x in casc.por_dia.iterrows() if x.e_esperado > 0]
        if casc_rows:
            psycopg2.extras.execute_values(cur, "INSERT INTO cascata_dia (usina_id, dia, modelo_id, e_esperado, e_medido, delta, inv_parado, "
                                                "tracker, string, residuo, cobertura_gate, trackers_sem_inversor) VALUES %s", casc_rows)
        perda_rows = [(int(x.equipamento_id), x.dia, mod.id, x.parcela, float(x.kwh)) for x in casc.perda_dia.itertuples()]
        if perda_rows:
            psycopg2.extras.execute_values(cur, "INSERT INTO perda_dia (equipamento_id, dia, modelo_id, parcela, kwh) VALUES %s", perda_rows)
        ev_rows = [(usina.id, e.equipamento_id, mod.id, e.tipo, e.ini.to_pydatetime(), e.fim.to_pydatetime() if e.fim is not None else None,
                    e.severidade, float(e.kwh), json.dumps(e.detalhe, default=str)) for e in evs]
        if ev_rows:
            psycopg2.extras.execute_values(cur, "INSERT INTO evento (usina_id, equipamento_id, modelo_id, tipo, ini, fim, severidade, kwh, detalhe) VALUES %s "
                                                "ON CONFLICT (usina_id, equipamento_id, tipo, ini) DO UPDATE SET fim=EXCLUDED.fim, "
                                                "severidade=EXCLUDED.severidade, kwh=EXCLUDED.kwh, detalhe=EXCLUDED.detalhe, modelo_id=EXCLUDED.modelo_id", ev_rows)
    conn.commit()


def modelar(conn, usina: UsinaRef, ini: dt.datetime, fim: dt.datetime, mod: Modelo | None = None) -> dict:
    t0 = time.time()
    mod = mod or modelo_ativo(conn, usina.id)
    grade = carregar_grade(conn, usina, ini, fim)
    pg = gate_mod.ParamsGate(**(mod.parametros.get("gate") or {}))
    r = gate_mod.avaliar(grade.estacao, referencia_razao(conn, usina.id, fim, usina.tz), pg, usina.tz)
    params = params_por_inversor(grade, mod, p_ac_30d(conn, usina.id, fim))
    esp = esp_mod.esperado_por_inversor(grade, r, params)
    d = dc.decompor(grade, esp, dc.trk_inv_da_grade(grade), dc.ParamsDecomp(), instaladas=instaladas_30d(conn, usina.id, fim))
    evs = ev_mod.detectar(grade, r, esp, d)
    casc = rollup.cascata(grade, r, esp, d)
    persistir(conn, usina, mod, grade, r, esp, evs, casc)
    return {"usina": usina.codigo, "modelo": mod.versao, "dias": int(len(casc.por_dia)), "eventos": len(evs),
            "e_esperado": round(float(casc.por_dia.e_esperado.sum()), 1), "e_medido": round(float(casc.por_dia.e_medido.sum()), 1),
            "inferidos": sum(1 for p in params.values() if p.pac0_inferido), "duracao_s": round(time.time() - t0, 1)}


def rodar_cli(ini: str | None, fim: str | None, usina: str | None) -> int:
    """`gemeo modelar [--ini AAAA-MM-DD] [--fim AAAA-MM-DD] [--usina CODIGO]` — datas em dia LOCAL da usina;
    sem datas, os ultimos 3 dias ate agora. Grava `estado.modelar.ultimo` para o /healthz."""
    from gemeo.core import db
    from gemeo.core.config import carregar
    from gemeo.ingest.runner import usinas_do_piloto
    cfg = carregar(); conn = db.conectar(cfg.db_dsn)
    usinas = usinas_do_piloto(conn, (usina,) if usina else cfg.usinas_piloto)
    if not usinas:
        print("nenhuma usina do piloto no banco — rode `gemeo ingest` (cadastro) primeiro", flush=True)
        return 1
    agora = dt.datetime.now(dt.timezone.utc); t0 = time.time(); resumos = []
    for u in usinas:
        if ini:
            i0 = pd.Timestamp(ini).tz_localize(u.tz).tz_convert("UTC").to_pydatetime()
            f0 = (pd.Timestamp(fim or ini) + pd.Timedelta(days=1)).tz_localize(u.tz).tz_convert("UTC").to_pydatetime()
        else:
            i0, f0 = janela_padrao(agora, u.tz)
        try:
            res = modelar(conn, u, i0, f0)
        except Exception as e:                                   # noqa: BLE001 — uma usina nao derruba as outras
            conn.rollback()
            res = {"usina": u.codigo, "erro": f"{type(e).__name__}: {e}"[:300]}
        resumos.append(res); print(json.dumps(res, ensure_ascii=False), flush=True)
    db.gravar_estado(conn, "modelar.ultimo", json.dumps({"em": agora.isoformat(), "duracao_s": round(time.time() - t0, 1), "usinas": resumos},
                                                         ensure_ascii=False, default=str))
    return 0 if all("erro" not in r for r in resumos) else 1
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd gemeo && python -m pytest -q`
Expected: os de rollup passam; `test_modelar_job` passa com `GEMEO_TEST_DSN` (na CI da Tarefa 21) e pula sem.

- [ ] **Step 5: Commit**

```bash
git add gemeo/gemeo/modelar/rollup.py gemeo/gemeo/modelar/job.py gemeo/tests/semear.py gemeo/tests/test_modelar_rollup.py gemeo/tests/test_modelar_job.py
git commit -m "feat(gemeo): cascata diaria, perda_dia e o job idempotente gemeo modelar (Tarefa 16)"
```

---

### Tarefa 17: Calibração — dias limpos → `perdas_fixas` → versão nova de `modelo`

**Files:**
- Create: `gemeo/gemeo/modelar/calibrar.py`
- Test: `gemeo/tests/test_modelar_calibrar.py`

**Interfaces:**
- Consumes: `job.modelo_ativo/params_por_inversor/p_ac_30d/referencia_razao/janela_padrao` (T16), `esperado.esperado_por_inversor` (T13), `gate.avaliar` (T12), `carregar_grade` (T11), tabelas `cascata_dia`, `evento`, `modelo`.
- Produces: `ParamsCalib`, `cv_poa_dia(poa, tz) -> dict[date, float]`, `dias_limpos(cobertura, dias_com_evento, cv, p) -> list[date]`, `razoes_por_dia(grade, r, params) -> DataFrame`, `ajustar_perdas(grade, r, params, dias, p) -> (perdas, metrica)`, `calibrar(conn, usina, dias=45, p, agora=None) -> dict`, `rodar_cli(usina, dias)`.
- Regra (spec §8, Calibração): dia limpo = sem `evento` de equipamento, `cobertura_gate ≥ 0,9`, CV da POA 10–14 h < 0,25. Ajusta `perdas_fixas` até a mediana medido/esperado dos inversores sãos ser 1,0. Versão nova `cal-AAAA-MM-DD` com `metrica`; **só vira ativa** (tolerância 0,03) com ≥ 30 dias limpos e desvio < 0,03 — antes fica gravada inativa e a placa segue no ar.

- [ ] **Step 1: Escrever os testes (falham: módulo não existe)**

```python
# gemeo/tests/test_modelar_calibrar.py
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from golden import G, esperado_de_placa, sem_gate  # noqa: E402
from sintetico import grade_sintetica  # noqa: E402
from gemeo.modelar import calibrar, esperado  # noqa: E402

D = dt.date(2026, 8, 31)


def test_cv_da_poa_entre_10_e_14_estavel_e_instavel():
    g = grade_sintetica()                       # 09:00-10:45 de Belem: so os 4 slots das 10 h entram
    cv = calibrar.cv_poa_dia(g.estacao["poa"], g.usina.tz)
    assert list(cv) == [D] and cv[D] == pytest.approx(0.0, abs=1e-9)
    g.estacao["poa"] = [800.0, 800.0, 800.0, 800.0, 200.0, 900.0, 200.0, 900.0]
    assert calibrar.cv_poa_dia(g.estacao["poa"], g.usina.tz)[D] > 0.25


def test_dias_limpos_filtra_evento_cobertura_e_instabilidade():
    d1, d2, d3, d4 = (dt.date(2026, 8, k) for k in (28, 29, 30, 31))
    cob = {d1: 0.95, d2: 0.95, d3: 0.5, d4: 0.95}
    cv = {d1: 0.1, d2: 0.1, d3: 0.1, d4: 0.4}
    assert calibrar.dias_limpos(cob, {d2}, cv, calibrar.ParamsCalib()) == [d1]


def test_ajustar_perdas_leva_a_razao_dos_saos_a_um():
    g = grade_sintetica(dias=3)
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    r = sem_gate(g)
    esp = esperado.esperado_por_inversor(g, r, params)
    g.inv_p[1001] = esp[1001] * 0.9; g.inv_p[1002] = esp[1002] * 0.9
    dias = sorted(set(g.indice.tz_convert(g.usina.tz).date))
    perdas, m = calibrar.ajustar_perdas(g, r, params, dias, calibrar.ParamsCalib())
    assert perdas == pytest.approx(1 - 0.86 * 0.9, abs=2e-3)      # DC linear em (1 - perdas); o clipping AC nao entra aqui
    assert m["razao_mediana"] == pytest.approx(1.0, abs=1e-3) and m["n_dias"] == 3 and m["desvio"] < 1e-6


def test_ajustar_perdas_sem_dias_e_erro():
    g = grade_sintetica()
    params = {i: esperado.ParamsModelo(kwp=277.68, pac0_kw=200.0) for i in g.inv_p.columns}
    with pytest.raises(ValueError):
        calibrar.ajustar_perdas(g, sem_gate(g), params, [], calibrar.ParamsCalib())


def test_golden_mro100_31_08_calibra_entre_10_e_25_por_cento():
    g, r, esp = esperado_de_placa(G / "mro100_2026-08-31.json")
    params = {i: esperado.ParamsModelo(kwp=g.atributos[i]["kwp"], pac0_kw=g.atributos[i]["kw_ac"]) for i in g.inv_p.columns}
    perdas, m = calibrar.ajustar_perdas(g, r, params, [D], calibrar.ParamsCalib())
    assert 0.10 < perdas < 0.25 and m["razao_mediana"] == pytest.approx(1.0, abs=2e-3) and m["n_dias"] == 1


def test_calibrar_no_banco_recusa_dia_com_evento(conn):
    import json
    from semear import semear_fixture
    from gemeo.modelar import job
    trk_inv = json.load(open(G / "mro100_trk_inv.json", encoding="utf-8"))
    usina, _ = semear_fixture(conn, G / "mro100_2026-08-31.json", trk_inv)
    try:
        UTC = dt.timezone.utc
        job.modelar(conn, usina, dt.datetime(2026, 8, 31, 3, tzinfo=UTC), dt.datetime(2026, 9, 1, 3, tzinfo=UTC))
        res = calibrar.calibrar(conn, usina, dias=3, agora=dt.datetime(2026, 9, 1, 2, tzinfo=UTC))
        assert res["erro"] == "sem dias limpos" and res["com_evento"] == 1      # 31/08 tem inversor 22 parado: nao calibra
        with conn.cursor() as cur:
            cur.execute("SELECT versao FROM modelo"); assert [r[0] for r in cur.fetchall()] == ["placa"]
    finally:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM evento; DELETE FROM perda_dia; DELETE FROM cascata_dia; DELETE FROM esperado; "
                        "DELETE FROM modelo; DELETE FROM leitura; DELETE FROM equipamento; DELETE FROM usina; DELETE FROM estado")
        conn.commit()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd gemeo && python -m pytest tests/test_modelar_calibrar.py -q`
Expected: FAIL — `ImportError: cannot import name 'calibrar'`.

- [ ] **Step 3: Implementar a calibração**

```python
# gemeo/gemeo/modelar/calibrar.py
"""`gemeo calibrar`: dias limpos -> ajusta perdas_fixas ate a mediana medido/esperado dos inversores saos
ser 1,0 -> versao NOVA de `modelo` com metrica. So vira ativa (e tolerancia 0,03) com >= 30 dias limpos e
desvio < 0,03; antes disso fica gravada, inativa, para inspecao — o modelo de placa continua no ar e o
delta informa sem alarmar."""
from __future__ import annotations
import datetime as dt
import json
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from gemeo.core.modelos import UsinaRef
from gemeo.modelar import esperado as esp_mod
from gemeo.modelar import gate as gate_mod
from gemeo.modelar import job
from gemeo.modelar.grade import Grade, carregar_grade

H = 0.25


@dataclass(frozen=True)
class ParamsCalib:
    cv_max: float = 0.25            # CV da POA entre 10 h e 14 h: acima disso o dia e instavel (22-24/08 de Santarem)
    cobertura_min: float = 0.90
    dias_min_calibrado: int = 30
    desvio_max: float = 0.03
    tolerancia_calibrado: float = 0.03
    tolerancia_placa: float = 0.08
    razao_sao_min: float = 0.5      # inversor com razao abaixo disto no dia esta parado/abaixo: nao calibra ninguem
    iteracoes: int = 4


def cv_poa_dia(poa: pd.Series, tz: str, h_ini: int = 10, h_fim: int = 14) -> dict[dt.date, float]:
    local = poa.index.tz_convert(ZoneInfo(tz))
    meio = poa[(local.hour >= h_ini) & (local.hour < h_fim)]
    dia = pd.Series(meio.index.tz_convert(ZoneInfo(tz)).date, index=meio.index)
    g = meio.groupby(dia)
    cv = g.std() / g.mean().replace(0, np.nan)
    return {d: (float(v) if pd.notna(v) else float("nan")) for d, v in cv.items()}


def dias_limpos(cobertura: dict[dt.date, float], dias_com_evento: set[dt.date], cv: dict[dt.date, float], p: ParamsCalib) -> list[dt.date]:
    """Sem evento de equipamento, cobertura do gate >= 0,9 e POA estavel."""
    return sorted(d for d, c in cobertura.items()
                  if c >= p.cobertura_min and d not in dias_com_evento and d in cv and pd.notna(cv[d]) and cv[d] < p.cv_max)


def razoes_por_dia(grade: Grade, r: gate_mod.Resultado, params: dict[int, esp_mod.ParamsModelo]) -> pd.DataFrame:
    """medido/esperado por (dia local, inversor) nos MESMOS instantes — a mesma regua do rollup."""
    esp = esp_mod.esperado_por_inversor(grade, r, params)
    med = grade.inv_p.reindex(columns=esp.columns)
    ok = esp.notna() & med.notna()
    dia = pd.Series(grade.indice.tz_convert(ZoneInfo(grade.usina.tz)).date, index=grade.indice)
    return ((med.where(ok) * H).groupby(dia).sum(min_count=1)) / ((esp.where(ok) * H).groupby(dia).sum(min_count=1))


def ajustar_perdas(grade: Grade, r: gate_mod.Resultado, params: dict[int, esp_mod.ParamsModelo], dias: list[dt.date], p: ParamsCalib) -> tuple[float, dict]:
    """Itera perdas_fixas ate a mediana das razoes dos saos, nos dias limpos, ser 1,0. O DC do PVWatts e
    linear em (1 - perdas), entao cada passo e quase exato; o clipping AC e o que pede mais de um."""
    if not dias:
        raise ValueError("sem dias limpos para calibrar")
    perdas = next(iter(params.values())).perdas_fixas

    def avalia(perdas_: float) -> pd.Series:
        pr = {e: esp_mod.ParamsModelo(q.kwp, q.pac0_kw, q.gamma, perdas_, q.eta_inv, q.pac0_inferido) for e, q in params.items()}
        raz = razoes_por_dia(grade, r, pr).reindex(dias)
        return raz.where(raz >= p.razao_sao_min).median(axis=1)

    for _ in range(p.iteracoes):
        med_dia = avalia(perdas)
        R = float(np.nanmedian(med_dia.values)) if med_dia.notna().any() else float("nan")
        if not np.isfinite(R) or R <= 0:
            raise ValueError("razoes invalidas nos dias limpos")
        if abs(R - 1.0) < 1e-4:
            break
        # perdas fora de [0, 0,5] nao e calibracao, e sensor ou cadastro errado: trava e a metrica denuncia
        perdas = float(min(0.5, max(0.0, 1.0 - (1.0 - perdas) * R)))
    med_dia = avalia(perdas)
    R = float(np.nanmedian(med_dia.values))
    metrica = {"razao_mediana": round(R, 4), "desvio": round(float(np.nanstd(med_dia.values)), 4),
               "n_dias": int(med_dia.notna().sum()), "dias": [str(d) for d in dias], "perdas_fixas": round(perdas, 4)}
    return perdas, metrica


def calibrar(conn, usina: UsinaRef, dias: int = 45, p: ParamsCalib = ParamsCalib(), agora: dt.datetime | None = None) -> dict:
    agora = agora or dt.datetime.now(dt.timezone.utc)
    tz = ZoneInfo(usina.tz)
    mod = job.modelo_ativo(conn, usina.id)
    ini, fim = job.janela_padrao(agora, usina.tz, dias)
    with conn.cursor() as cur:
        cur.execute("SELECT dia, cobertura_gate FROM cascata_dia WHERE usina_id=%s AND modelo_id=%s AND dia >= %s",
                    (usina.id, mod.id, ini.astimezone(tz).date()))
        cobertura = {d: float(c) for d, c in cur.fetchall()}
        cur.execute("SELECT DISTINCT (ini AT TIME ZONE %s)::date FROM evento WHERE usina_id=%s AND equipamento_id IS NOT NULL AND ini >= %s",
                    (usina.tz, usina.id, ini))
        com_evento = {r[0] for r in cur.fetchall()}
    grade = carregar_grade(conn, usina, ini, fim)
    r = gate_mod.avaliar(grade.estacao, job.referencia_razao(conn, usina.id, fim, usina.tz),
                         gate_mod.ParamsGate(**(mod.parametros.get("gate") or {})), usina.tz)
    limpos = dias_limpos(cobertura, com_evento, cv_poa_dia(grade.estacao["poa"], usina.tz), p)
    if not limpos:
        return {"usina": usina.codigo, "erro": "sem dias limpos", "dias_cascata": len(cobertura), "com_evento": len(com_evento)}
    params = job.params_por_inversor(grade, mod, job.p_ac_30d(conn, usina.id, fim))
    perdas, metrica = ajustar_perdas(grade, r, params, limpos, p)
    calibrado = metrica["n_dias"] >= p.dias_min_calibrado and metrica["desvio"] < p.desvio_max
    versao = f"cal-{agora.astimezone(tz).date()}"
    parametros = {**mod.parametros, "perdas_fixas": perdas, "base": mod.versao}
    with conn.cursor() as cur:
        if calibrado:
            cur.execute("UPDATE modelo SET ativo=false WHERE usina_id=%s AND ativo", (usina.id,))
        cur.execute("INSERT INTO modelo (usina_id, versao, parametros, tolerancia, calibrado, calibrado_em, metrica, ativo) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (usina_id, versao) DO UPDATE SET parametros=EXCLUDED.parametros, "
                    "tolerancia=EXCLUDED.tolerancia, calibrado=EXCLUDED.calibrado, calibrado_em=EXCLUDED.calibrado_em, "
                    "metrica=EXCLUDED.metrica, ativo=EXCLUDED.ativo RETURNING id",
                    (usina.id, versao, json.dumps(parametros), p.tolerancia_calibrado if calibrado else p.tolerancia_placa,
                     calibrado, agora if calibrado else None, json.dumps(metrica), calibrado))
        mid = cur.fetchone()[0]
    conn.commit()
    return {"usina": usina.codigo, "versao": versao, "modelo_id": int(mid), "calibrado": calibrado, "ativo": calibrado, **metrica}


def rodar_cli(usina: str, dias: int) -> int:
    from gemeo.core import db
    from gemeo.core.config import carregar
    from gemeo.ingest.runner import usinas_do_piloto
    cfg = carregar(); conn = db.conectar(cfg.db_dsn)
    usinas = usinas_do_piloto(conn, (usina,))
    if not usinas:
        print(f"usina {usina!r} nao esta no banco", flush=True)
        return 1
    res = calibrar(conn, usinas[0], dias)
    print(json.dumps(res, ensure_ascii=False, default=str), flush=True)
    return 0 if "erro" not in res else 1
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd gemeo && python -m pytest tests/test_modelar_calibrar.py -q`
Expected: 5 passed, 1 skipped (o de banco, sem DSN).

- [ ] **Step 5: Commit**

```bash
git add gemeo/gemeo/modelar/calibrar.py gemeo/tests/test_modelar_calibrar.py
git commit -m "feat(gemeo): calibracao por dias limpos com versao nova de modelo (Tarefa 17)"
```

---

## Fase D — Telas

### Tarefa 18: Consultas das telas — Frota, Usina e saúde, em dicts testáveis

**Files:**
- Create: `gemeo/gemeo/app/__init__.py` (vazio)
- Create: `gemeo/gemeo/app/formato.py`
- Create: `gemeo/gemeo/app/consultas.py`
- Test: `gemeo/tests/test_app_formato.py`, `gemeo/tests/test_app_consultas.py`

**Interfaces:**
- Consumes: tabelas do schema (T2), `estado.modelar.ultimo` (T16), `Config` (T1).
- Produces: `formato.num/mw/pct/brl/idade`; `consultas.faixa(delta, tolerancia)`, `causa_dominante(cascata)`, `motivo_nao_modelada(u, agora)`, `frota(conn, agora) -> dict`, `usina(conn, usina_id, agora) -> dict`, `saude(conn, cfg, agora) -> dict`, `exp_do_jwt(token) -> datetime | None`. Tudo JSON-serializável; `agora` é parâmetro (nunca `now()`) para as telas serem testáveis sobre um dia congelado.
- Régua (spec §9): `delta = (medido − esperado) / esperado`; **dentro** se `delta ≥ −tolerancia`; **moderado** se `−0,08 ≤ delta < −tolerancia`; **grave** se `delta < −0,08`. Com a placa (`tolerancia` 0,08) a faixa moderada fica vazia de propósito. "Aparece na régua" = usina ativa com equipamento, `ingest_run` ok nas últimas 24 h, gate de hoje não reprovado e esperado calculado. Frescor > 30 min → `frio`.

- [ ] **Step 1: Escrever os testes (falham: módulos não existem)**

```python
# gemeo/tests/test_app_formato.py
import datetime as dt
from gemeo.app import formato as f


def test_numeros_em_pt_br():
    assert f.num(1234.5, 1) == "1.234,5" and f.num(0.0, 0) == "0" and f.num(None) == "—"
    assert f.mw(148200.0) == "148,2" and f.mw(950.0) == "0,95" and f.pct(-0.044) == "−4,4%" and f.pct(None) == "—"
    assert f.brl(1400.0) == "R$ 1,4 mil" and f.brl(390.0) == "R$ 390" and f.brl(None) == "—"


def test_idade_em_minutos_e_horas():
    ref = dt.datetime(2026, 9, 3, 15, 0, tzinfo=dt.timezone.utc)
    assert f.idade(ref - dt.timedelta(minutes=7), ref) == "7 min" and f.idade(ref - dt.timedelta(hours=26), ref) == "26 h"
    assert f.idade(None, ref) == "nunca"
```

```python
# gemeo/tests/test_app_consultas.py
"""As regras puras da tela (faixa, causa, motivo) sem banco; e a Frota e a Usina de ponta a ponta sobre o
banco semeado com a MRO100 de 31/08 (pula sem GEMEO_TEST_DSN)."""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from gemeo.app import consultas as c  # noqa: E402

G = Path(__file__).parent / "fixtures" / "golden"
UTC = dt.timezone.utc


def test_faixa_da_regua_com_placa_e_com_modelo_calibrado():
    assert c.faixa(-0.02, 0.08) == "dentro" and c.faixa(-0.05, 0.08) == "dentro" and c.faixa(-0.09, 0.08) == "grave"
    assert c.faixa(-0.05, 0.03) == "moderado" and c.faixa(-0.081, 0.03) == "grave" and c.faixa(0.01, 0.03) == "dentro"
    assert c.faixa(None, 0.03) == "sem_dado"


def test_causa_dominante_e_a_maior_parcela():
    assert c.causa_dominante({"inv_parado": 1600.0, "tracker": 100.0, "string": 0.0, "residuo": 300.0}) == "inversor parado"
    assert c.causa_dominante({"inv_parado": 0.0, "tracker": 0.0, "string": 0.0, "residuo": 0.0}) == "dentro da tolerância do modelo"
    assert c.causa_dominante(None) == "sem cascata hoje"


def test_motivo_nao_modelada():
    agora = dt.datetime(2026, 8, 31, 20, 0, tzinfo=UTC)
    base = {"n_equip": 5, "ultimo_ingest_ok": agora - dt.timedelta(hours=1), "gate_hoje": "ok", "esperado_kw": 100.0}
    assert c.motivo_nao_modelada(base, agora) is None
    assert c.motivo_nao_modelada({**base, "n_equip": 0}, agora) == "sem equipamentos no cadastro"
    assert c.motivo_nao_modelada({**base, "ultimo_ingest_ok": agora - dt.timedelta(hours=30)}, agora) == "sem ingestão ok nas últimas 24 h"
    assert c.motivo_nao_modelada({**base, "gate_hoje": "poa_ghi"}, agora) == "sensor em falha hoje (POA × GHI)"
    assert c.motivo_nao_modelada({**base, "gate_hoje": "cobertura"}, agora) == "sem cobertura de sensor hoje"
    assert c.motivo_nao_modelada({**base, "esperado_kw": None}, agora) == "sem esperado calculado hoje"


def test_exp_do_jwt():
    import base64
    payload = base64.urlsafe_b64encode(json.dumps({"exp": 1790000000}).encode()).decode().rstrip("=")
    assert c.exp_do_jwt(f"x.{payload}.y") == dt.datetime.fromtimestamp(1790000000, UTC)
    assert c.exp_do_jwt("nao-e-jwt") is None and c.exp_do_jwt("") is None


@pytest.fixture
def mro100_modelada(conn):
    from semear import semear_fixture
    from gemeo.core import db
    from gemeo.modelar import job
    trk_inv = json.load(open(G / "mro100_trk_inv.json", encoding="utf-8"))
    usina, ids = semear_fixture(conn, G / "mro100_2026-08-31.json", trk_inv)
    ini, fim = dt.datetime(2026, 8, 31, 3, tzinfo=UTC), dt.datetime(2026, 9, 1, 3, tzinfo=UTC)
    job.modelar(conn, usina, ini, fim)
    db.registrar_ingest_run(conn, "sunop", usina.id, ini, fim, "ok", n_linhas=100, cobertura=1.0)
    with conn.cursor() as cur:   # o ingest_run 'ok' precisa parecer recente para o 'agora' congelado da tela
        cur.execute("UPDATE ingest_run SET criado_em=%s", (dt.datetime(2026, 8, 31, 19, 50, tzinfo=UTC),))
    conn.commit()
    yield usina, ids
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evento; DELETE FROM perda_dia; DELETE FROM cascata_dia; DELETE FROM esperado; DELETE FROM modelo; "
                    "DELETE FROM ingest_run; DELETE FROM leitura; DELETE FROM equipamento; DELETE FROM usina; DELETE FROM estado")
    conn.commit()


def test_frota_e_usina_sobre_o_banco_semeado(conn, mro100_modelada):
    usina, ids = mro100_modelada
    agora = dt.datetime(2026, 8, 31, 20, 0, tzinfo=UTC)        # 17:00 em Belem, com sol
    fr = c.frota(conn, agora)
    assert [u["codigo"] for u in fr["usinas"]] == ["MRO100"] and fr["nao_modeladas"] == []
    u = fr["usinas"][0]
    assert u["esperado_kw"] > 0 and u["medido_kw"] > 0 and u["faixa"] in ("dentro", "moderado", "grave")
    assert u["cascata"]["inv_parado"] > 1000 and u["causa"] == "inversor parado" and u["perda_kwh"] > 1000
    assert fr["totais"]["confianca"] == 1.0 and fr["regua"]["tolerancia"] == 0.08 and fr["regua"]["calibradas"] == 0
    us = c.usina(conn, usina.id, agora)
    assert us["cabecalho"]["codigo"] == "MRO100" and us["cabecalho"]["n_inversores"] == 25 and us["cabecalho"]["n_trackers"] == 120
    assert len(us["curva"]) > 40 and all(p["esperado_kw"] is None or p["esperado_kw"] >= 0 for p in us["curva"])
    assert us["cascata"]["inv_parado"] > 1000 and any(e["tipo"] == "inversor_parado" for e in us["eventos"])
    inv22 = next(i for i in us["inversores"] if i["id"] == ids["inv:22"])
    assert inv22["status"] == "parado" and inv22["inv_parado"] > 1000
    assert us["trackers"][0]["id"] in (ids["trk:4"], ids["trk:17"]) and us["sensor"]["cobertura_gate"] > 0.9
    # sem ingestao recente a usina sai da regua com motivo, nao some
    fr2 = c.frota(conn, agora + dt.timedelta(hours=30))
    assert fr2["usinas"] == [] and fr2["nao_modeladas"][0]["motivo"] == "sem ingestão ok nas últimas 24 h"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd gemeo && python -m pytest tests/test_app_formato.py tests/test_app_consultas.py -q`
Expected: FAIL — `ModuleNotFoundError: gemeo.app`.

- [ ] **Step 3: Implementar formato e consultas**

```python
# gemeo/gemeo/app/__init__.py
```

```python
# gemeo/gemeo/app/formato.py
"""Numeros em pt-BR para as telas: virgula decimal, ponto de milhar, travessao para o que nao existe.
O sinal de menos e o tipografico (U+2212), como nos mockups."""
from __future__ import annotations
import datetime as dt


def num(v: float | None, casas: int = 1) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.{casas}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return ("−" if v < 0 else "") + s


def mw(kw: float | None) -> str:
    if kw is None:
        return "—"
    v = kw / 1000.0
    return num(v, 2) if abs(v) < 1 else num(v, 1)


def pct(frac: float | None, casas: int = 1) -> str:
    return "—" if frac is None else num(frac * 100.0, casas) + "%"


def brl(v: float | None) -> str:
    if v is None:
        return "—"
    return f"R$ {num(v / 1000.0, 1)} mil" if abs(v) >= 1000 else f"R$ {num(v, 0)}"


def idade(ts: dt.datetime | None, agora: dt.datetime) -> str:
    if ts is None:
        return "nunca"
    m = int((agora - ts).total_seconds() // 60)
    return f"{m} min" if m < 120 else f"{m // 60} h"
```

```python
# gemeo/gemeo/app/consultas.py
"""Todo o SQL das telas, em funcoes banco -> dict (JSON-serializavel). O app so renderiza. 'Agora' e
parametro (nunca now()) para as telas serem testaveis sobre um dia congelado — e para 'viajar no tempo'
ao depurar: `/gemeo/?agora=2026-08-31T20:00:00Z`."""
from __future__ import annotations
import base64
import datetime as dt
import json
from zoneinfo import ZoneInfo

FRIO_MIN = 30          # frescor: acima disto a usina fica cinza antes de qualquer outra cor (spec §9)
DEFICIT_GRAVE = 0.08   # faixa 'deficit grave' da regua
H = 0.25
NOMES_PARCELA = {"inv_parado": "inversor parado", "tracker": "trackers fora do alvo",
                 "string": "strings sem corrente", "residuo": "resíduo (não explicado)"}


def faixa(delta: float | None, tolerancia: float) -> str:
    """dentro | moderado | grave | sem_dado. delta = (medido - esperado)/esperado; negativo = deficit."""
    if delta is None:
        return "sem_dado"
    if delta >= -tolerancia:
        return "dentro"
    return "moderado" if delta >= -DEFICIT_GRAVE else "grave"


def causa_dominante(c: dict | None) -> str:
    if not c:
        return "sem cascata hoje"
    k = max(NOMES_PARCELA, key=lambda n: c.get(n) or 0.0)
    return NOMES_PARCELA[k] if (c.get(k) or 0.0) > 0 else "dentro da tolerância do modelo"


def motivo_nao_modelada(u: dict, agora: dt.datetime) -> str | None:
    """Por que a usina do cadastro nao esta na regua — None quando esta. E a definicao de 'aparece na
    tela' da spec §6: ativa, com equipamento, ingest ok em 24 h, gate de hoje nao reprovado, esperado."""
    if not u.get("n_equip"):
        return "sem equipamentos no cadastro"
    if u.get("ultimo_ingest_ok") is None or agora - u["ultimo_ingest_ok"] > dt.timedelta(hours=24):
        return "sem ingestão ok nas últimas 24 h"
    if u.get("gate_hoje") in ("poa_ghi", "plausibilidade"):
        return "sensor em falha hoje (POA × GHI)"
    if u.get("gate_hoje") == "cobertura":
        return "sem cobertura de sensor hoje"
    if u.get("esperado_kw") is None:
        return "sem esperado calculado hoje"
    return None


def exp_do_jwt(token: str) -> dt.datetime | None:
    """`exp` do token de API da SunOp (validade ~1 ano): o /healthz alarma 30 dias antes."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload))["exp"]
        return dt.datetime.fromtimestamp(int(exp), dt.timezone.utc)
    except Exception:                       # noqa: BLE001 — token que nao e JWT nao tem validade legivel
        return None


def _dia_utc(dia: dt.date, tz: ZoneInfo) -> tuple[dt.datetime, dt.datetime]:
    ini = dt.datetime.combine(dia, dt.time.min, tzinfo=tz)
    return ini.astimezone(dt.timezone.utc), (ini + dt.timedelta(days=1)).astimezone(dt.timezone.utc)


def _q(conn, sql: str, params: tuple = ()) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def _usinas(conn, usina_id: int | None = None) -> list[dict]:
    filtro = "AND u.id=%s" if usina_id else ""
    rows = _q(conn, f"""
        SELECT u.id, u.codigo, u.nome, u.fonte, u.tz, coalesce(u.kwp_dc,0), coalesce(u.kw_ac,0), u.cliente,
               (SELECT count(*) FROM equipamento e WHERE e.usina_id=u.id AND e.ativo),
               (SELECT max(r.criado_em) FROM ingest_run r WHERE r.usina_id=u.id AND r.status='ok'),
               (SELECT max(l.ts) FROM leitura l JOIN equipamento e ON e.id=l.equipamento_id WHERE e.usina_id=u.id),
               m.id, m.versao, coalesce(m.tolerancia, 0.08), coalesce(m.calibrado, false)
        FROM usina u LEFT JOIN modelo m ON m.usina_id=u.id AND m.ativo
        WHERE u.ativo {filtro} ORDER BY u.codigo""", (usina_id,) if usina_id else ())
    chaves = ("id", "codigo", "nome", "fonte", "tz", "kwp", "kw_ac", "cliente", "n_equip", "ultimo_ingest_ok", "ultima_leitura",
              "modelo_id", "modelo_versao", "tolerancia", "calibrado")
    return [dict(zip(chaves, r)) for r in rows]


def _ultimo_slot(conn, usina_id: int, modelo_id: int | None, agora: dt.datetime) -> dt.datetime | None:
    if modelo_id is None:
        return None
    r = _q(conn, "SELECT max(x.ts) FROM esperado x JOIN equipamento e ON e.id=x.equipamento_id "
                 "WHERE e.usina_id=%s AND x.modelo_id=%s AND x.p_esperado_kw IS NOT NULL AND x.ts <= %s", (usina_id, modelo_id, agora))
    return r[0][0] if r and r[0][0] else None


def _agora_da_usina(conn, usina_id: int, modelo_id: int, slot: dt.datetime) -> tuple[float | None, float | None, str | None]:
    esp = _q(conn, "SELECT sum(x.p_esperado_kw), min(x.gate) FROM esperado x JOIN equipamento e ON e.id=x.equipamento_id "
                   "WHERE e.usina_id=%s AND x.modelo_id=%s AND x.ts=%s", (usina_id, modelo_id, slot))
    med = _q(conn, "SELECT sum(v) FROM (SELECT avg(l.valor) v FROM leitura l JOIN equipamento e ON e.id=l.equipamento_id "
                   "WHERE e.usina_id=%s AND e.tipo='inversor' AND l.medida='p_ac' AND l.ts >= %s AND l.ts < %s GROUP BY l.equipamento_id) s",
             (usina_id, slot, slot + dt.timedelta(minutes=15)))
    e = float(esp[0][0]) if esp and esp[0][0] is not None else None
    m = float(med[0][0]) if med and med[0][0] is not None else None
    return e, m, (esp[0][1] if esp else None)


def _cascata(conn, usina_id: int, modelo_id: int | None, dia: dt.date) -> dict | None:
    if modelo_id is None:
        return None
    r = _q(conn, "SELECT e_esperado, e_medido, delta, inv_parado, tracker, string, residuo, cobertura_gate, trackers_sem_inversor "
                 "FROM cascata_dia WHERE usina_id=%s AND modelo_id=%s AND dia=%s", (usina_id, modelo_id, dia))
    if not r:
        return None
    ch = ("e_esperado", "e_medido", "delta", "inv_parado", "tracker", "string", "residuo", "cobertura_gate", "trackers_sem_inversor")
    return {k: (float(v) if k != "trackers_sem_inversor" else int(v)) for k, v in zip(ch, r[0])}


def _gate_hoje(conn, usina_id: int, ini: dt.datetime, fim: dt.datetime) -> str:
    r = _q(conn, "SELECT tipo FROM evento WHERE usina_id=%s AND tipo IN ('sensor_em_falha','sem_cobertura') AND ini >= %s AND ini < %s LIMIT 1",
           (usina_id, ini, fim))
    return {"sensor_em_falha": "poa_ghi", "sem_cobertura": "cobertura"}.get(r[0][0], "ok") if r else "ok"


def _preco(conn, usina_id: int, dia: dt.date) -> float | None:
    r = _q(conn, "SELECT preco_mwh FROM meta_mes WHERE usina_id=%s AND ano=%s AND mes=%s", (usina_id, dia.year, dia.month))
    return float(r[0][0]) if r and r[0][0] is not None else None


def _min(agora: dt.datetime, ts: dt.datetime | None) -> int | None:
    return None if ts is None else int((agora - ts).total_seconds() // 60)


def _ciclo(conn) -> dict:
    r = _q(conn, "SELECT valor FROM estado WHERE chave='modelar.ultimo'")
    try:
        return json.loads(r[0][0]) if r else {}
    except Exception:                       # noqa: BLE001
        return {}


def frota(conn, agora: dt.datetime) -> dict:
    usinas = []
    for u in _usinas(conn):
        tz = ZoneInfo(u["tz"]); hoje = agora.astimezone(tz).date(); ini, fim = _dia_utc(hoje, tz)
        slot = _ultimo_slot(conn, u["id"], u["modelo_id"], agora)
        esp_kw = med_kw = gate_agora = None
        if slot:
            esp_kw, med_kw, gate_agora = _agora_da_usina(conn, u["id"], u["modelo_id"], slot)
        casc = _cascata(conn, u["id"], u["modelo_id"], hoje)
        preco = _preco(conn, u["id"], hoje)
        delta = (med_kw - esp_kw) / esp_kw if esp_kw and med_kw is not None else None
        perda_kwh = max(0.0, casc["delta"]) if casc else 0.0
        u.update({
            "hoje": str(hoje), "slot": slot, "esperado_kw": esp_kw, "medido_kw": med_kw, "delta": delta, "gate_agora": gate_agora,
            "gate_hoje": _gate_hoje(conn, u["id"], ini, fim), "cascata": casc, "preco_mwh": preco, "perda_kwh": perda_kwh,
            "perda_brl": (perda_kwh / 1000.0 * preco) if preco else None, "causa": causa_dominante(casc),
            "faixa": faixa(delta, float(u["tolerancia"])), "idade_leitura_min": _min(agora, u["ultima_leitura"]),
            "idade_esperado_min": _min(agora, slot)})
        u["frio"] = u["idade_leitura_min"] is None or u["idade_leitura_min"] > FRIO_MIN
        u["motivo"] = motivo_nao_modelada(u, agora)
        usinas.append(u)
    modeladas = sorted([u for u in usinas if u["motivo"] is None], key=lambda u: -(u["perda_brl"] or u["perda_kwh"]))
    nao = [{"id": u["id"], "codigo": u["codigo"], "fonte": u["fonte"], "motivo": u["motivo"]} for u in usinas if u["motivo"]]
    tot_esp = sum(u["esperado_kw"] for u in modeladas if u["esperado_kw"] is not None)
    tot_med = sum(u["medido_kw"] for u in modeladas if u["medido_kw"] is not None)
    com_preco = [u["perda_brl"] for u in modeladas if u["perda_brl"] is not None]
    confianca = (sum(1 for u in usinas if u["gate_agora"] == "ok" and not u["frio"]) / len(usinas)) if usinas else 0.0
    faixas = {k: sum(1 for u in modeladas if u["faixa"] == k) for k in ("dentro", "moderado", "grave", "sem_dado")}
    tol = min([float(u["tolerancia"]) for u in modeladas], default=0.08)
    return {
        "agora": agora.isoformat(), "ciclo": _ciclo(conn), "usinas": modeladas, "nao_modeladas": nao,
        "totais": {"esperado_kw": tot_esp, "medido_kw": tot_med, "delta": ((tot_med - tot_esp) / tot_esp) if tot_esp else None,
                   "perda_kwh": sum(u["perda_kwh"] for u in modeladas), "perda_brl": sum(com_preco) if com_preco else None,
                   "confianca": confianca, "n_modeladas": len(modeladas), "n_usinas": len(usinas)},
        "regua": {"tolerancia": tol, "faixas": faixas, "calibradas": sum(1 for u in modeladas if u["calibrado"]),
                  "barras": [{"id": u["id"], "codigo": u["codigo"], "faixa": u["faixa"], "frio": u["frio"]} for u in modeladas]},
    }


def usina(conn, usina_id: int, agora: dt.datetime) -> dict | None:
    us = _usinas(conn, usina_id)
    if not us:
        return None
    u = us[0]; tz = ZoneInfo(u["tz"]); hoje = agora.astimezone(tz).date(); ini, fim = _dia_utc(hoje, tz)
    mid = u["modelo_id"]
    n_tipo = dict(_q(conn, "SELECT tipo, count(*) FROM equipamento WHERE usina_id=%s AND ativo GROUP BY tipo", (usina_id,)))
    slot = _ultimo_slot(conn, usina_id, mid, agora)
    esp_kw, med_kw, gate_agora = _agora_da_usina(conn, usina_id, mid, slot) if slot else (None, None, None)
    delta = (med_kw - esp_kw) / esp_kw if esp_kw and med_kw is not None else None
    cabecalho = {"id": usina_id, "codigo": u["codigo"], "nome": u["nome"], "fonte": u["fonte"], "cliente": u["cliente"], "tz": u["tz"],
                 "kwp": u["kwp"], "kw_ac": u["kw_ac"], "n_inversores": int(n_tipo.get("inversor", 0)), "n_trackers": int(n_tipo.get("tracker", 0)),
                 "n_strings": int(n_tipo.get("string", 0)), "modelo_versao": u["modelo_versao"], "calibrado": bool(u["calibrado"]),
                 "tolerancia": float(u["tolerancia"]), "hoje": str(hoje), "slot": slot, "esperado_kw": esp_kw, "medido_kw": med_kw,
                 "delta": delta, "faixa": faixa(delta, float(u["tolerancia"])), "gate_agora": gate_agora,
                 "idade_leitura_min": _min(agora, u["ultima_leitura"]), "idade_esperado_min": _min(agora, slot)}
    cabecalho["frio"] = cabecalho["idade_leitura_min"] is None or cabecalho["idade_leitura_min"] > FRIO_MIN
    # curva do dia: esperado (dia inteiro, o que o modelo ja calculou) x medido (ate agora), na grade de 15 min
    esp_curva = dict(_q(conn, "SELECT x.ts, sum(x.p_esperado_kw) FROM esperado x JOIN equipamento e ON e.id=x.equipamento_id "
                              "WHERE e.usina_id=%s AND x.modelo_id=%s AND x.ts >= %s AND x.ts < %s GROUP BY x.ts", (usina_id, mid, ini, fim))) if mid else {}
    med_curva = dict(_q(conn, "SELECT b, sum(v) FROM (SELECT date_bin('15 minutes', l.ts, TIMESTAMPTZ '2000-01-01') b, l.equipamento_id, avg(l.valor) v "
                              "FROM leitura l JOIN equipamento e ON e.id=l.equipamento_id WHERE e.usina_id=%s AND e.tipo='inversor' AND l.medida='p_ac' "
                              "AND l.ts >= %s AND l.ts < %s GROUP BY 1, 2) s GROUP BY b", (usina_id, ini, min(fim, agora))))
    curva = [{"ts": ts.isoformat(), "hora": ts.astimezone(tz).strftime("%H:%M"),
              "esperado_kw": (float(esp_curva[ts]) if esp_curva.get(ts) is not None else None),
              "medido_kw": (float(med_curva[ts]) if med_curva.get(ts) is not None else None)}
             for ts in sorted(set(esp_curva) | set(med_curva))]
    casc = _cascata(conn, usina_id, mid, hoje)
    preco = _preco(conn, usina_id, hoje)
    eventos = [{"id": r[0], "tipo": r[1], "equipamento_id": r[2], "equipamento": r[3], "ini": r[4].isoformat(), "hora_ini": r[4].astimezone(tz).strftime("%H:%M"),
                "fim": r[5].isoformat() if r[5] else None, "severidade": r[6], "kwh": float(r[7]), "detalhe": r[8] or {}}
               for r in _q(conn, "SELECT ev.id, ev.tipo, ev.equipamento_id, coalesce(e.nome_exibicao, e.codigo_fonte, 'estação'), ev.ini, ev.fim, "
                                 "ev.severidade, ev.kwh, ev.detalhe FROM evento ev LEFT JOIN equipamento e ON e.id=ev.equipamento_id "
                                 "WHERE ev.usina_id=%s AND (ev.ini >= %s OR ev.fim IS NULL) AND ev.ini < %s ORDER BY ev.kwh DESC, ev.ini", (usina_id, ini, fim))]
    perdas: dict[int, dict[str, float]] = {}
    for eid, parcela, kwh in _q(conn, "SELECT p.equipamento_id, p.parcela, p.kwh FROM perda_dia p JOIN equipamento e ON e.id=p.equipamento_id "
                                      "WHERE e.usina_id=%s AND p.modelo_id=%s AND p.dia=%s", (usina_id, mid, hoje)) if mid else []:
        perdas.setdefault(int(eid), {})[parcela] = float(kwh)
    # por inversor: medido e esperado nos MESMOS instantes (a regua do rollup), parcelas do perda_dia, status pelos eventos
    por_inv = {int(r[0]): (float(r[1]), float(r[2])) for r in _q(conn,
        "SELECT s.equipamento_id, sum(s.v)*0.25, sum(x.p_esperado_kw)*0.25 FROM (SELECT date_bin('15 minutes', l.ts, TIMESTAMPTZ '2000-01-01') b, "
        "l.equipamento_id, avg(l.valor) v FROM leitura l JOIN equipamento e ON e.id=l.equipamento_id WHERE e.usina_id=%s AND e.tipo='inversor' "
        "AND l.medida='p_ac' AND l.ts >= %s AND l.ts < %s GROUP BY 1, 2) s JOIN esperado x ON x.equipamento_id=s.equipamento_id AND x.ts=s.b "
        "AND x.modelo_id=%s AND x.p_esperado_kw IS NOT NULL GROUP BY 1", (usina_id, ini, fim, mid))} if mid else {}
    ev_por_eq: dict[int, str] = {}
    for e in eventos:
        if e["equipamento_id"] and e["tipo"] in ("inversor_parado", "inversor_abaixo"):
            ev_por_eq.setdefault(e["equipamento_id"], "parado" if e["tipo"] == "inversor_parado" else "abaixo")
    inversores = []
    for eid, nome, at in _q(conn, "SELECT id, coalesce(nome_exibicao, codigo_fonte), atributos FROM equipamento WHERE usina_id=%s AND tipo='inversor' AND ativo "
                                  "ORDER BY (atributos->>'numero')::int NULLS LAST, codigo_fonte", (usina_id,)):
        med, esp = por_inv.get(int(eid), (None, None))
        razao = (med / esp) if esp else None
        p = perdas.get(int(eid), {})
        status = ev_por_eq.get(int(eid)) or ("sem_dado" if razao is None else "atencao" if razao < 0.9 else "ok")
        inversores.append({"id": int(eid), "nome": nome, "kwp": (at or {}).get("kwp"), "medido_kwh": med, "esperado_kwh": esp, "razao": razao,
                           "inv_parado": p.get("inv_parado", 0.0), "tracker": p.get("tracker", 0.0), "string": p.get("string", 0.0),
                           "residuo": p.get("residuo", 0.0), "status": status})

    def _top(tipo: str, parcela: str, n: int = 15) -> list[dict]:
        rows = _q(conn, "SELECT e.id, coalesce(e.nome_exibicao, e.codigo_fonte), e.pai_id, p.kwh FROM perda_dia p JOIN equipamento e ON e.id=p.equipamento_id "
                        "WHERE e.usina_id=%s AND e.tipo=%s AND p.parcela=%s AND p.modelo_id=%s AND p.dia=%s ORDER BY p.kwh DESC LIMIT %s",
                  (usina_id, tipo, parcela, mid, hoje, n)) if mid else []
        return [{"id": int(r[0]), "nome": r[1], "pai_id": r[2], "kwh": float(r[3])} for r in rows]

    razao_dia = _q(conn, "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY p.valor / g.valor) FROM leitura p JOIN leitura g ON g.equipamento_id=p.equipamento_id "
                         "AND g.ts=p.ts AND g.medida='ghi' JOIN equipamento e ON e.id=p.equipamento_id WHERE e.usina_id=%s AND e.tipo='estacao' AND p.medida='poa' "
                         "AND g.valor > 100 AND p.ts >= %s AND p.ts < %s", (usina_id, ini, fim))
    sensor = {"razao_poa_ghi": (float(razao_dia[0][0]) if razao_dia and razao_dia[0][0] is not None else None),
              "cobertura_gate": (casc["cobertura_gate"] if casc else None), "gate_hoje": _gate_hoje(conn, usina_id, ini, fim),
              "trackers_sem_inversor": (casc["trackers_sem_inversor"] if casc else None)}
    return {"agora": agora.isoformat(), "ciclo": _ciclo(conn), "cabecalho": cabecalho, "curva": curva, "cascata": casc, "preco_mwh": preco,
            "perda_brl": ((max(0.0, casc["delta"]) / 1000.0 * preco) if (casc and preco) else None), "eventos": eventos, "inversores": inversores,
            "trackers": _top("tracker", "tracker"), "strings": _top("string", "string"), "sensor": sensor}


def saude(conn, cfg, agora: dt.datetime) -> dict:
    """/healthz: por fonte o ultimo ciclo (idade, status, cobertura), SunOp hoje / teto, ultimo modelar, banco, e a
    validade do token de API da SunOp (alarme 30 dias antes)."""
    fontes = {}
    try:
        rows = _q(conn, "SELECT DISTINCT ON (fonte) fonte, criado_em, status, cobertura, n_requisicoes FROM ingest_run ORDER BY fonte, criado_em DESC")
        banco = True
    except Exception as e:                  # noqa: BLE001 — sem banco a resposta e o proprio diagnostico
        return {"ok": False, "banco": False, "erro": f"{type(e).__name__}: {e}"[:200], "agora": agora.isoformat()}
    for fonte, em, status, cob, nreq in rows:
        fontes[fonte] = {"ultimo": em.isoformat(), "idade_min": _min(agora, em), "status": status, "cobertura": float(cob)}
    hoje = _q(conn, "SELECT coalesce(sum(n_requisicoes),0) FROM ingest_run WHERE fonte LIKE 'sunop%%' AND (criado_em AT TIME ZONE 'UTC')::date = %s",
              (agora.astimezone(dt.timezone.utc).date(),))
    sunop_hoje = int(hoje[0][0]) if hoje else 0
    ciclo = _ciclo(conn)
    exp = exp_do_jwt(getattr(cfg, "sunop_token", "") or "")
    dias_token = (exp - agora).days if exp else None
    problemas = []
    for f, v in fontes.items():
        if v["status"] != "ok" or (v["idade_min"] or 0) > 120:
            problemas.append(f"{f}: {v['status']} há {v['idade_min']} min")
    if ciclo.get("em"):
        idade_ciclo = _min(agora, dt.datetime.fromisoformat(ciclo["em"]))
        if idade_ciclo is not None and idade_ciclo > 45:
            problemas.append(f"modelar há {idade_ciclo} min")
    else:
        problemas.append("modelar nunca rodou")
    if dias_token is not None and dias_token < 30:
        problemas.append(f"token SunOp vence em {dias_token} dias")
    if sunop_hoje >= getattr(cfg, "teto_sunop_dia", 600):
        problemas.append(f"SunOp no teto: {sunop_hoje}")
    return {"ok": not problemas, "banco": banco, "agora": agora.isoformat(), "fontes": fontes,
            "sunop": {"requisicoes_hoje": sunop_hoje, "teto": getattr(cfg, "teto_sunop_dia", 600), "token_exp": exp.isoformat() if exp else None, "token_dias": dias_token},
            "modelar": ciclo, "problemas": problemas}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd gemeo && python -m pytest tests/test_app_formato.py tests/test_app_consultas.py -q`
Expected: 6 passed, 1 skipped (o de banco, sem DSN).

- [ ] **Step 5: Commit**

```bash
git add gemeo/gemeo/app/ gemeo/tests/test_app_formato.py gemeo/tests/test_app_consultas.py
git commit -m "feat(gemeo): consultas das telas Frota, Usina e saude (Tarefa 18)"
```

---

<!-- CONTINUA: Tarefa 19 -->
