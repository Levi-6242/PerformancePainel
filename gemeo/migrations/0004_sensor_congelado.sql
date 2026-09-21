-- 0004 (17/09/2026): tipo de evento `sensor_congelado`. A POA medida e a ENTRADA do modelo — um
-- piranometro travado nao produz um evento, produz um ESPERADO INTEIRO ERRADO, e ate aqui nada
-- avisava. O caso que motivou veio da plataforma: o combiner da Tanabi 2 repetindo 13 zeros desde
-- 28/05 enquanto o inversor gerava 92 kW. O `sensor_em_falha` existente e outra coisa: e a razao
-- POA/GHI fora da faixa, que nao pega sensor repetindo um valor plausivel.
-- O CHECK do SQLite nao se altera em lugar: recria a tabela, preservando ids, UNIQUE e indice.
CREATE TABLE evento_novo (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  usina_id       INTEGER NOT NULL REFERENCES usina(id),
  equipamento_id INTEGER REFERENCES equipamento(id),
  modelo_id      INTEGER REFERENCES modelo(id),
  tipo           TEXT NOT NULL CHECK (tipo IN ('inversor_parado','inversor_abaixo','tracker_fora_alvo','tracker_travado',
                                               'tracker_sem_comunicacao','string_sem_corrente','sensor_em_falha',
                                               'sensor_congelado','sem_cobertura')),
  ini            TIMESTAMP NOT NULL, fim TIMESTAMP,
  severidade     TEXT NOT NULL CHECK (severidade IN ('leve','media','grave')),
  kwh            REAL NOT NULL DEFAULT 0,
  detalhe        JSON NOT NULL DEFAULT '{}',
  UNIQUE (usina_id, equipamento_id, tipo, ini)
);
INSERT INTO evento_novo (id, usina_id, equipamento_id, modelo_id, tipo, ini, fim, severidade, kwh, detalhe)
  SELECT id, usina_id, equipamento_id, modelo_id, tipo, ini, fim, severidade, kwh, detalhe FROM evento;
DROP TABLE evento;
ALTER TABLE evento_novo RENAME TO evento;
CREATE INDEX IF NOT EXISTS evento_usina_ini ON evento (usina_id, ini);
INSERT OR REPLACE INTO sqlite_sequence (name, seq) SELECT 'evento', COALESCE(MAX(id), 0) FROM evento;
