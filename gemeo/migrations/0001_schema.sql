-- gemeo/migrations/0001_schema.sql
-- Schema da Sombra Digital em SQLite (03/09/2026: saiu do PostgreSQL para nao depender de DBA).
-- Convencoes: todo instante e texto ISO 8601 em UTC (tipo TIMESTAMP, convertido pelo db.py); DATE = 'AAAA-MM-DD';
-- BOOLEAN = 0/1; JSON = texto JSON (volta como dict). Chave natural em tudo; nada aqui e ORM.
CREATE TABLE IF NOT EXISTS schema_migrations (nome TEXT PRIMARY KEY, aplicada_em TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')));

CREATE TABLE IF NOT EXISTS usina (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  codigo        TEXT NOT NULL UNIQUE,            -- 'MRO100', 'Santarem 1'
  nome          TEXT NOT NULL,
  fonte         TEXT NOT NULL CHECK (fonte IN ('pg','sunop','axis','apipv','solaredge','owen')),
  fonte_ref     TEXT NOT NULL,                   -- pid no PG ou nome na SunOp
  cliente       TEXT,
  lat           REAL, lon REAL,
  tz            TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
  kwp_dc        REAL, kw_ac REAL,
  n_inversores  INTEGER,
  full_om       BOOLEAN NOT NULL DEFAULT 0,
  ativo         BOOLEAN NOT NULL DEFAULT 1,
  criado_em     TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
  UNIQUE (fonte, fonte_ref)
);

CREATE TABLE IF NOT EXISTS equipamento (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  usina_id       INTEGER NOT NULL REFERENCES usina(id),
  tipo           TEXT NOT NULL CHECK (tipo IN ('inversor','tracker','string','estacao','cabine')),
  codigo_fonte   TEXT NOT NULL,                  -- 'INV_7', 'TRK_17', 'INV_7.I_PV3', 'ESTM', '765'
  nome_exibicao  TEXT,
  pai_id         INTEGER REFERENCES equipamento(id),
  atributos      JSON NOT NULL DEFAULT '{}',     -- numero, kwp, kw_ac, n_strings_esperadas...
  descoberto_em  TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
  ativo          BOOLEAN NOT NULL DEFAULT 1,
  UNIQUE (usina_id, tipo, codigo_fonte)
);
CREATE INDEX IF NOT EXISTS equipamento_pai ON equipamento(pai_id);

CREATE TABLE IF NOT EXISTS alias (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  usina_id       INTEGER REFERENCES usina(id),
  equipamento_id INTEGER REFERENCES equipamento(id),
  sistema        TEXT NOT NULL CHECK (sistema IN ('fracttal','bd_performance','bd_trackers','sunop','apipv','pg')),
  valor          TEXT NOT NULL,
  confianca      TEXT NOT NULL CHECK (confianca IN ('direto','contagem','ordem','limite_skid','manual')),
  origem         TEXT NOT NULL,
  criado_em      TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
  UNIQUE (sistema, valor),
  CHECK (usina_id IS NOT NULL OR equipamento_id IS NOT NULL)
);

-- a tabela grande: ~70 mil linhas/dia por usina como a MRO100; retencao de 90 dias por DELETE (db.retencao)
CREATE TABLE IF NOT EXISTS leitura (
  equipamento_id INTEGER NOT NULL,
  medida         TEXT NOT NULL CHECK (medida IN ('poa','ghi','temp_modulo','temp_ar','vento','p_ac','e_dia',
                                                 'i_string','angulo','angulo_alvo','estado')),
  ts             TIMESTAMP NOT NULL,
  valor          REAL NOT NULL,
  PRIMARY KEY (equipamento_id, medida, ts)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS leitura_ts ON leitura (ts);

CREATE TABLE IF NOT EXISTS ingest_run (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  fonte          TEXT NOT NULL,
  usina_id       INTEGER REFERENCES usina(id),
  ini            TIMESTAMP NOT NULL, fim TIMESTAMP NOT NULL,
  status         TEXT NOT NULL CHECK (status IN ('ok','parcial','falha')),
  n_linhas       INTEGER NOT NULL DEFAULT 0,
  n_requisicoes  INTEGER NOT NULL DEFAULT 0,
  duracao_s      REAL NOT NULL DEFAULT 0,
  cobertura      REAL NOT NULL DEFAULT 0,
  erro           TEXT,
  criado_em      TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now'))
);
CREATE INDEX IF NOT EXISTS ingest_run_fonte_ts ON ingest_run (fonte, criado_em DESC);

CREATE TABLE IF NOT EXISTS modelo (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  usina_id      INTEGER NOT NULL REFERENCES usina(id),
  versao        TEXT NOT NULL,                   -- 'placa', 'cal-2026-10-15'
  parametros    JSON NOT NULL,                   -- pac0_kw, gamma, perdas_fixas, eta_inv, pac0_inferido, gate{}
  tolerancia    REAL NOT NULL DEFAULT 0.08,
  calibrado     BOOLEAN NOT NULL DEFAULT 0,
  calibrado_em  TIMESTAMP,
  metrica       JSON NOT NULL DEFAULT '{}',
  ativo         BOOLEAN NOT NULL DEFAULT 0,
  criado_em     TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')),
  UNIQUE (usina_id, versao)
);
CREATE UNIQUE INDEX IF NOT EXISTS modelo_um_ativo_por_usina ON modelo (usina_id) WHERE ativo;

CREATE TABLE IF NOT EXISTS esperado (
  equipamento_id INTEGER NOT NULL,
  ts             TIMESTAMP NOT NULL,
  modelo_id      INTEGER NOT NULL REFERENCES modelo(id),
  p_esperado_kw  REAL,
  poa_usada      REAL, temp_usada REAL,
  gate           TEXT NOT NULL CHECK (gate IN ('ok','poa_ghi','cobertura','plausibilidade')),
  PRIMARY KEY (equipamento_id, ts, modelo_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS esperado_ts ON esperado (ts);

CREATE TABLE IF NOT EXISTS cascata_dia (
  usina_id       INTEGER NOT NULL REFERENCES usina(id),
  dia            DATE NOT NULL,
  modelo_id      INTEGER NOT NULL REFERENCES modelo(id),
  e_esperado     REAL NOT NULL, e_medido REAL NOT NULL, delta REAL NOT NULL,
  inv_parado     REAL NOT NULL DEFAULT 0, tracker REAL NOT NULL DEFAULT 0,
  string         REAL NOT NULL DEFAULT 0, residuo REAL NOT NULL DEFAULT 0,
  cobertura_gate REAL NOT NULL DEFAULT 0,
  trackers_sem_inversor INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (usina_id, dia, modelo_id)
);

CREATE TABLE IF NOT EXISTS perda_dia (
  equipamento_id INTEGER NOT NULL REFERENCES equipamento(id),
  dia            DATE NOT NULL,
  modelo_id      INTEGER NOT NULL REFERENCES modelo(id),
  parcela        TEXT NOT NULL CHECK (parcela IN ('inv_parado','tracker','string','residuo')),
  kwh            REAL NOT NULL,
  PRIMARY KEY (equipamento_id, dia, modelo_id, parcela)
);

CREATE TABLE IF NOT EXISTS evento (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  usina_id       INTEGER NOT NULL REFERENCES usina(id),
  equipamento_id INTEGER REFERENCES equipamento(id),
  modelo_id      INTEGER REFERENCES modelo(id),
  tipo           TEXT NOT NULL CHECK (tipo IN ('inversor_parado','inversor_abaixo','tracker_fora_alvo',
                                               'string_sem_corrente','sensor_em_falha','sem_cobertura')),
  ini            TIMESTAMP NOT NULL, fim TIMESTAMP,
  severidade     TEXT NOT NULL CHECK (severidade IN ('leve','media','grave')),
  kwh            REAL NOT NULL DEFAULT 0,
  detalhe        JSON NOT NULL DEFAULT '{}',
  UNIQUE (usina_id, equipamento_id, tipo, ini)
);
CREATE INDEX IF NOT EXISTS evento_usina_ini ON evento (usina_id, ini);

CREATE TABLE IF NOT EXISTS meta_mes (
  usina_id       INTEGER NOT NULL REFERENCES usina(id),
  ano INTEGER NOT NULL, mes INTEGER NOT NULL,
  pr_previsto    REAL, ipoa_previsto REAL, p50_mwh REAL,
  disp_alvo      REAL, preco_mwh REAL,
  PRIMARY KEY (usina_id, ano, mes)
);

-- estado pequeno dos ingestores e dos jobs (ex.: updated_at do workbook, modelar.ultimo, publicar.ultimo)
CREATE TABLE IF NOT EXISTS estado (chave TEXT PRIMARY KEY, valor TEXT NOT NULL, atualizado_em TIMESTAMP NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00','now')));
