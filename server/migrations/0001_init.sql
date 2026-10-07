-- Wersja schematu; tabele z danymi dochodzą w krokach F, G, I, każda we własnej migracji
-- (spec backendu §2.3). Żadna kolumna nie przechowuje adresu IP (§2.2).
CREATE TABLE schema_info (version INTEGER NOT NULL);
INSERT INTO schema_info (version) VALUES (1);
