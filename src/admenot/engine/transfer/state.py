"""Stan kopii w SQLite — podstawa wznawiania po przerwaniu.

Port `adbbackup/state.py`. Każdy plik ma status: pending / done / error / skipped. Zapis po każdej
paczce (commit), więc po padzie prądu, wyrwaniu kabla czy zamknięciu okna tracimy co najwyżej
jedną paczkę.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files (
    remote    TEXT PRIMARY KEY,
    root      TEXT NOT NULL,
    size      INTEGER NOT NULL,
    mtime     INTEGER NOT NULL,
    local_rel TEXT NOT NULL,
    renamed   INTEGER NOT NULL DEFAULT 0,
    status    TEXT NOT NULL DEFAULT 'pending',
    attempts  INTEGER NOT NULL DEFAULT 0,
    error     TEXT,
    sha256    TEXT,
    updated   REAL
);
CREATE INDEX IF NOT EXISTS ix_files_status ON files(status);
"""


@dataclass
class FileRow:
    remote: str
    root: str
    size: int
    mtime: int
    local_rel: str
    renamed: bool
    status: str
    attempts: int
    error: str | None = None
    sha256: str | None = None


class State:
    def __init__(self, path: Path):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.commit()
        self.db.close()

    # ---- meta -------------------------------------------------------------------------
    def set_meta(self, key: str, value: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, json.dumps(value)))
        self.db.commit()

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    # ---- pliki ------------------------------------------------------------------------
    @staticmethod
    def _row(t: tuple) -> FileRow:
        return FileRow(t[0], t[1], t[2], t[3], t[4], bool(t[5]), t[6], t[7], t[8], t[9])

    _COLS = "remote, root, size, mtime, local_rel, renamed, status, attempts, error, sha256"

    def all_files(self) -> dict[str, FileRow]:
        cur = self.db.execute(f"SELECT {self._COLS} FROM files")
        return {r[0]: self._row(r) for r in cur}

    def used_local(self) -> set[str]:
        return {r[0].casefold() for r in self.db.execute("SELECT local_rel FROM files")}

    def insert(self, f: FileRow) -> None:
        self.db.execute(
            f"INSERT OR REPLACE INTO files({self._COLS}, updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (f.remote, f.root, f.size, f.mtime, f.local_rel, int(f.renamed), f.status, f.attempts,
             f.error, f.sha256, time.time()))

    def update(self, remote: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated"] = time.time()
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE files SET {sets} WHERE remote=?", (*fields.values(), remote))

    def pending(self) -> list[FileRow]:
        cur = self.db.execute(f"SELECT {self._COLS} FROM files WHERE status='pending' ORDER BY remote")
        return [self._row(r) for r in cur]

    def by_status(self, status: str) -> list[FileRow]:
        cur = self.db.execute(f"SELECT {self._COLS} FROM files WHERE status=? ORDER BY remote", (status,))
        return [self._row(r) for r in cur]

    def totals(self) -> dict[str, tuple[int, int]]:
        cur = self.db.execute("SELECT status, COUNT(*), COALESCE(SUM(size),0) FROM files GROUP BY status")
        return {s: (n, b) for s, n, b in cur}

    def commit(self) -> None:
        self.db.commit()
