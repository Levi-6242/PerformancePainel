# Gêmeo Digital — Sombra Digital

Serviço separado da plataforma. Ver `docs/superpowers/specs/2026-09-03-gemeo-sombra-digital-design.md` (desenho) e `docs/runbook.md` (operação).

```
python -m pip install -e ".[dev]"
gemeo migrate | ingest | modelar | calibrar | app
python -m pytest -q
```

Segredos em `SECRETS_DIR/gemeo.env` (fora do OneDrive): GEMEO_DB_DSN, POWERPLANTS_DSN, SUNOP_API_TOKEN, GRIDCO_SQL_TOKEN, GEMEO_SENHA.

Deploy no servidor da T.I.: `deploy/README.md`. Operação do dia a dia: `docs/runbook.md`. Mudou lote/período/gate/fusão: `python -m tools.equivalencia` (spec §11).
