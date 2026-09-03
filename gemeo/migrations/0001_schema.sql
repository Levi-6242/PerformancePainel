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
