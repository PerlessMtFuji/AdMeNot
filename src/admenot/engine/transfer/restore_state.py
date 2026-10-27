"""Stan wgrywania kopii na nowy telefon — SQLite osobno dla każdego telefonu docelowego.

`<kopia>/restore/<device_dir_name(serial)>.sqlite`: pliki (cel, status, próby) i meta `serial`,
`choice`, `status`, `updated`. Czyta go też widok kopii (`read_restores`: „wgrano na …” i Banner
wznowienia).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from admenot.engine.paths import device_dir_name

from .store import CopyDir

READ_TIMEOUT = 1.0  # s — odczyt stanu dla widoku kopii
# Powody nieudanej próby po `push` — pod celem może leżeć nasz niedokończony plik.
OWN_PARTIAL = frozenset({"interrupted", "disconnect", "push_failed", "hash_mismatch"})

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS files (
    remote   TEXT PRIMARY KEY,
    target   TEXT NOT NULL,
    grp      TEXT NOT NULL,
    size     INTEGER NOT NULL,
    mtime    INTEGER NOT NULL,
    status   TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    error    TEXT
);
CREATE INDEX IF NOT EXISTS ix_files_status ON files(status);
"""


def restore_state_path(copy: CopyDir, serial: str) -> Path:
    """Stan wgrywania kopii na telefon `serial`: `<kopia>/restore/<device_dir_name(serial)>.sqlite`."""
    return copy.path / "restore" / f"{device_dir_name(serial)}.sqlite"


@dataclass
class RestoreRow:
    remote: str  # ścieżka na starym telefonie (klucz w kopii)
    target: str  # cel na nowym telefonie
    grp: str
    size: int
    mtime: int
    status: str  # pending | pushing | done | exists | denied | error | skipped
    attempts: int
    error: str | None = None


class RestoreState:
    """Stan wgrywania w SQLite (jak `state.State`); meta: `serial`, `choice`, `status`, `updated`."""

    _COLS = "remote, target, grp, size, mtime, status, attempts, error"

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.commit()
        self.db.close()

    def set_meta(self, key: str, value: Any) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, json.dumps(value)))
        self.db.commit()

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def all_files(self) -> dict[str, RestoreRow]:
        return {r[0]: RestoreRow(*r) for r in self.db.execute(f"SELECT {self._COLS} FROM files")}

    def insert(self, r: RestoreRow) -> None:
        self.db.execute(f"INSERT OR REPLACE INTO files({self._COLS}) VALUES(?,?,?,?,?,?,?,?)",
                        (r.remote, r.target, r.grp, r.size, r.mtime, r.status, r.attempts, r.error))

    def update(self, remote: str, **fields: Any) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE files SET {sets} WHERE remote=?", (*fields.values(), remote))

    def by_status(self, status: str) -> list[RestoreRow]:
        cur = self.db.execute(f"SELECT {self._COLS} FROM files WHERE status=? ORDER BY remote", (status,))
        return [RestoreRow(*r) for r in cur]

    def taken_alts(self) -> dict[str, str]:
        """Cele, pod którymi może leżeć nasz niedokończony plik (`pushing` albo nieudana próba po
        `push`) — dla `build_plan(taken_alts=…)`, żeby wznowienie nadpisało własny plik zamiast
        zapisywać obok jako „(z kopii)”."""
        return {r.remote: r.target for r in self.all_files().values() if is_own(r)}

    def commit(self) -> None:
        self.db.commit()


@dataclass(frozen=True)
class RestoreSummary:
    """Stan wgrywania kopii na jeden telefon — do widoku kopii i Bannera wznowienia."""

    serial: str
    status: str  # running | complete | incomplete | stopped | klucz `RestoreError`
    updated: str | None  # ISO-8601 UTC
    resumable: bool  # zostały pliki do wgrania (`pending`/`pushing`) i przebieg nie jest `complete`


def _summary(path: Path) -> RestoreSummary | None:
    """Sam odczyt istniejącego pliku: `mode=rw` bez tworzenia, więc widok kopii niczego nie
    zakłada, a pozostawiony po awarii dziennik transakcji SQLite może się wycofać (`mode=ro` by
    na nim odmówił i Banner wznowienia by zniknął). Krótki `timeout`: wątek API nie czeka za
    zapisem trwającego wgrywania — zablokowany stan jest na ten raz pomijany."""
    try:
        db = sqlite3.connect(f"{path.absolute().as_uri()}?mode=rw", uri=True, timeout=READ_TIMEOUT)
    except sqlite3.Error:
        return None
    try:
        meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
        (left,) = db.execute("SELECT COUNT(*) FROM files WHERE status IN ('pending', 'pushing')").fetchone()
    except (sqlite3.Error, ValueError):
        return None
    finally:
        db.close()
    serial, status, updated = meta.get("serial"), meta.get("status"), meta.get("updated")
    if not isinstance(serial, str) or not isinstance(status, str):
        return None
    return RestoreSummary(serial, status, updated if isinstance(updated, str) else None,
                          status != "complete" and left > 0)


def read_restores(copy: CopyDir) -> list[RestoreSummary]:
    """Wgrywania tej kopii (po jednym na telefon docelowy), najnowsze pierwsze; nieczytelny stan
    albo stan bez `serial`/`status` (przebieg, który nic nie zaczął) pomijamy."""
    try:
        paths = sorted((copy.path / "restore").glob("*.sqlite"))
    except OSError:
        return []
    found = [s for s in map(_summary, paths) if s is not None]
    return sorted(found, key=lambda s: (s.updated or "", s.serial), reverse=True)


def is_own(row: RestoreRow) -> bool:
    """Pod celem wiersza może leżeć nasz (niedokończony) plik z poprzedniego podejścia."""
    return row.status == "pushing" or (row.status in ("pending", "error") and row.error in OWN_PARTIAL)
