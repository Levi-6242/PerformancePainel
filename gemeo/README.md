# Gêmeo Digital — Sombra Digital

Serviço separado da plataforma. Ver `docs/superpowers/specs/2026-09-03-gemeo-sombra-digital-design.md` (desenho) e `docs/runbook.md` (operação).

```
python -m pip install -e ".[dev]"
gemeo migrate | ingest | modelar | calibrar | app
python -m pytest -q
```

Segredos em `SECRETS_DIR/gemeo.env` (fora do OneDrive): SUNOP_API_TOKEN, GRIDCO_SQL_TOKEN, GEMEO_SENHA; opcionais GEMEO_DB_CAMINHO e POWERPLANTS_DSN.

Banco: **SQLite embutido** (03/09/2026), um arquivo fora do OneDrive (`%LOCALAPPDATA%\GridCo\gemeo\gemeo.sqlite` por padrão). Sem servidor, sem DBA.

Deploy no servidor da T.I.: `deploy/README.md`. Operação do dia a dia: `docs/runbook.md`. Mudou lote/período/gate/fusão: `python -m tools.equivalencia` (spec §11).
