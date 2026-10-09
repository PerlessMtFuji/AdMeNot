-- Raporty błędów z programu (spec raportów błędów §6.1). Bez kolumny z adresem IP (spec backendu §2.2).
-- created: czas serwera UTC w formacie datetime('now'), żeby porównanie z '-90 days' działało tekstowo.
CREATE TABLE reports (
  id TEXT PRIMARY KEY,
  created TEXT NOT NULL,
  kind TEXT NOT NULL,
  app TEXT NOT NULL,
  os TEXT NOT NULL,
  lang TEXT NOT NULL,
  error_type TEXT NOT NULL,
  error_where TEXT,
  body TEXT NOT NULL,
  seen INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX reports_created ON reports(created);
UPDATE schema_info SET version = 2;
