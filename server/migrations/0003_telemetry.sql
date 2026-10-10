-- Statystyki użycia (spec kroku H §7.1). Bez adresu IP (spec backendu §2.2).
-- created: czas serwera (retencja, limit dzienny); t: godzina zdarzenia z programu (zegar użytkownika).
CREATE TABLE events (
  install TEXT NOT NULL,
  created TEXT NOT NULL,
  t TEXT NOT NULL,
  type TEXT NOT NULL,
  app TEXT NOT NULL,
  body TEXT NOT NULL
);
CREATE INDEX events_created ON events(created);
CREATE INDEX events_install ON events(install);
UPDATE schema_info SET version = 3;
