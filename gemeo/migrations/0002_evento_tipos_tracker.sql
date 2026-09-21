-- 0002 (13/09/2026): dois tipos novos de evento de tracker. Sete Lagoas TRK51/TRK38 ficaram o dia inteiro em 25,8 e 4,3 graus
-- com a frota indo de -46 a +55 (TRAVADOS, comunicam e nao mexem) e a Araputanga TRK5 veio 0,0 fixo com aComm=1 na PV
-- Plataforma (SEM COMUNICACAO) -- ambos saiam como corridas de 'tracker_fora_alvo'. O CHECK do SQLite nao se altera em
-- lugar: recria a tabela com a lista ampliada, preservando ids, UNIQUE e indice.
CREATE TABLE evento_novo (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  usina_id       INTEGER NOT NULL REFERENCES usina(id),
  equipamento_id INTEGER REFERENCES equipamento(id),
  modelo_id      INTEGER REFERENCES modelo(id),
  tipo           TEXT NOT NULL CHECK (tipo IN ('inversor_parado','inversor_abaixo','tracker_fora_alvo','tracker_travado',
                                               'tracker_sem_comunicacao','string_sem_corrente','sensor_em_falha','sem_cobertura')),
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
