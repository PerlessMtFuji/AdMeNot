-- Plany naprawy dla klienta (spec 2026-10-11-plan-qr §4.1): zaszyfrowane bloby na godzinę.
-- body: blob w base64 (odczyt BLOB z D1 w Workerze nie daje pewnego typu). Bez adresu IP.
CREATE TABLE shares (
  id TEXT PRIMARY KEY,
  created TEXT NOT NULL,
  expires TEXT NOT NULL,
  body TEXT NOT NULL
);
CREATE INDEX shares_expires ON shares(expires);
UPDATE schema_info SET version = 4;
