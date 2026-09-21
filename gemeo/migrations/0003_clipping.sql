-- 0003_clipping.sql — a parcela de clipping na cascata (17/09/2026).
-- O esperado vem do PVWatts sobre a POA medida, e o PVWatts nao conhece o limite AC do inversor:
-- em usina sobredimensionada o modelo espera mais do que o equipamento entrega, e isso caia todo no
-- RESIDUO como perda inexplicada. A parcela nao cria perda nova, reclassifica o residuo. Decisao do
-- Levi (17/09): clipping NAO conta como perda evitavel — e de projeto, nao de operacao.
ALTER TABLE cascata_dia ADD COLUMN clipping REAL NOT NULL DEFAULT 0;

-- perda_dia.parcela tem CHECK; o SQLite nao altera CHECK, entao recria a tabela com o valor novo.
CREATE TABLE IF NOT EXISTS perda_dia_novo (
  equipamento_id INTEGER NOT NULL REFERENCES equipamento(id),
  dia            DATE NOT NULL,
  modelo_id      INTEGER NOT NULL REFERENCES modelo(id),
  parcela        TEXT NOT NULL CHECK (parcela IN ('inv_parado','tracker','string','clipping','residuo')),
  kwh            REAL NOT NULL,
  PRIMARY KEY (equipamento_id, dia, modelo_id, parcela)
);
INSERT OR IGNORE INTO perda_dia_novo SELECT * FROM perda_dia;
DROP TABLE perda_dia;
ALTER TABLE perda_dia_novo RENAME TO perda_dia;
