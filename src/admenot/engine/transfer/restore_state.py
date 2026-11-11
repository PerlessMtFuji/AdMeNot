"""Stan wgrywania kopii na nowy telefon — SQLite osobno dla każdego telefonu docelowego.

`<kopia>/restore/<device_dir_name(serial)>.sqlite`: pliki (cel, status, próby), rekordy telefonii
(`tel`: kategoria, id rekordu, status, droga) i meta `serial`, `imei` (gdy telefon go podał), `choice`, `status`, `updated`,
`device_changes` (zmiany telefonu do odwrócenia, `phonesetup`; ich główny zapis to `PhoneRecord` poza
kopią, meta stanu jest jego kopią i zapisem stanów sprzed niego), `tel_left` (rekordy telefonii
jeszcze nierozstrzygnięte, `restore_tel`), `scanned` (liczba plików `done` przy ostatnim udanym skanie
galerii, `restore`). Czyta go też widok kopii
(`read_restores`: „wgrano na …”, Banner wznowienia i sprzątania).
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from admenot.engine.paths import device_dir_name, phone_changes_dir

from .store import CopyDir

READ_TIMEOUT = 1.0  # s — odczyt stanu dla widoku kopii
CHANGES_KEY = "device_changes"
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
    error    TEXT,
    own      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_files_status ON files(status);
CREATE TABLE IF NOT EXISTS tel (
    kind   TEXT,
    rid    TEXT,
    status TEXT,
    path   TEXT,
    error  TEXT,
    PRIMARY KEY(kind, rid)
);
CREATE TABLE IF NOT EXISTS apps (
    package  TEXT PRIMARY KEY,
    status   TEXT NOT NULL,
    reason   TEXT,
    code     TEXT,
    attempts INTEGER NOT NULL DEFAULT 0
);
"""


def changes_pending(value: Any) -> bool:
    """Meta `device_changes` z czymś do odwrócenia (pole różne od `None`/`False`; `[]` też się liczy:
    zapisany brak posiadacza roli SMS)."""
    return isinstance(value, dict) and any(v is not None and v is not False for v in value.values())


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
    # `skipped` z naszym niedokończonym plikiem pod celem (grupa odznaczona po przerwaniu) — po
    # ponownym zaznaczeniu wznowienie nadpisze własny plik zamiast zapisywać obok
    own: bool = False


class RestoreState:
    """Stan wgrywania w SQLite (jak `state.State`); meta: `serial`, `choice`, `status`, `updated`."""

    _COLS = "remote, target, grp, size, mtime, status, attempts, error, own"

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)
        if "own" not in {c[1] for c in self.db.execute("PRAGMA table_info(files)")}:  # stan sprzed kolumny
            self.db.execute("ALTER TABLE files ADD COLUMN own INTEGER NOT NULL DEFAULT 0")
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
        return {r[0]: _row(r) for r in self.db.execute(f"SELECT {self._COLS} FROM files")}

    def insert(self, r: RestoreRow) -> None:
        self.db.execute(f"INSERT OR REPLACE INTO files({self._COLS}) VALUES(?,?,?,?,?,?,?,?,?)",
                        (r.remote, r.target, r.grp, r.size, r.mtime, r.status, r.attempts, r.error, int(r.own)))

    def update(self, remote: str, **fields: Any) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE files SET {sets} WHERE remote=?", (*fields.values(), remote))

    def by_status(self, status: str) -> list[RestoreRow]:
        cur = self.db.execute(f"SELECT {self._COLS} FROM files WHERE status=? ORDER BY remote", (status,))
        return [_row(r) for r in cur]

    def taken_alts(self) -> dict[str, str]:
        """Cele, pod którymi może leżeć nasz niedokończony plik (`pushing`, nieudana próba po
        `push` albo taki plik w grupie odznaczonej po przerwaniu) — dla `build_plan(taken_alts=…)`,
        żeby wznowienie nadpisało własny plik zamiast zapisywać obok jako „(z kopii)”."""
        return {r.remote: r.target for r in self.all_files().values() if is_own(r)}

    def commit(self) -> None:
        self.db.commit()

    # ---- telefonia ----------------------------------------------------------------------
    def tel_status(self, kind: str) -> dict[str, str]:
        """Rekordy telefonii kategorii `kind`: id rekordu -> status (`done` | `error` | `manual`)."""
        return dict(self.db.execute("SELECT rid, status FROM tel WHERE kind=?", (kind,)))

    def tel_set(self, kind: str, rids: Iterable[str], status: Literal["done", "error", "manual"],
                path: str, error: str | None = None) -> None:
        """Status rekordów (droga zapisu `path`), z commitem — wznowienie nie zapisze ich drugi raz."""
        self.db.executemany("INSERT OR REPLACE INTO tel(kind, rid, status, path, error) VALUES(?,?,?,?,?)",
                            [(kind, rid, status, path, error) for rid in rids])
        self.db.commit()

    def tel_forget(self, kind: str, rids: Iterable[str]) -> None:
        """Zapomina status rekordów (z commitem): telefon ich już nie ma, więc pójdą jeszcze raz."""
        self.db.executemany("DELETE FROM tel WHERE kind=? AND rid=?", [(kind, rid) for rid in rids])
        self.db.commit()

    # ---- aplikacje ----------------------------------------------------------------------
    def apps_status(self) -> dict[str, tuple[str, str | None, str | None]]:
        """Pakiet -> (status, powód, surowy kod błędu); status: `pending` | `installed` | `exists` |
        `skipped` | `failed`. `pending` = instalacja wysłana, wynik nieznany (rozłączenie)."""
        return {p: (st, rs, cd) for p, st, rs, cd in self.db.execute("SELECT package, status, reason, code FROM apps")}

    def app_set(self, package: str, status: str, reason: str | None = None, code: str | None = None) -> None:
        """Status aplikacji, z commitem; liczba prób zostaje."""
        self.db.execute(
            "INSERT INTO apps(package, status, reason, code) VALUES(?,?,?,?) ON CONFLICT(package) DO UPDATE SET "
            "status=excluded.status, reason=excluded.reason, code=excluded.code", (package, status, reason, code))
        self.db.commit()

    def app_attempt(self, package: str) -> None:
        """Instalacja wysłana: `pending` i próba więcej — wznowienie wie, że pakiet mógł już wejść."""
        self.db.execute(
            "INSERT INTO apps(package, status, attempts) VALUES(?, 'pending', 1) ON CONFLICT(package) DO UPDATE SET "
            "status='pending', reason=NULL, code=NULL, attempts=attempts+1", (package,))
        self.db.commit()


@dataclass(frozen=True)
class RestoreSummary:
    """Stan wgrywania kopii na jeden telefon — do widoku kopii i Bannera wznowienia."""

    serial: str
    status: str  # running | complete | incomplete | stopped | klucz `RestoreError`
    updated: str | None  # ISO-8601 UTC
    # zostały pliki do wgrania (`pending`/`pushing`) i przebieg nie jest `complete`, albo zostały rekordy
    # wybranej telefonii (`tel_left`)
    resumable: bool
    cleanup_pending: bool = False  # zostały zmiany telefonu do odwrócenia (`device_changes`)
    imei: str | None = None  # IMEI telefonu docelowego; stany sprzed tego pola i telefony bez odczytu: None


def _read(path: Path, strict: bool = False) -> tuple[dict[str, Any], int] | None:
    """(meta, liczba plików `pending`/`pushing`) istniejącego stanu albo `None`.
    `strict`: stanu, którego nie da się otworzyć (blokada, brak dostępu — `sqlite3.OperationalError`),
    nie pomijamy, tylko OSError; uszkodzony plik dalej daje `None`.

    Sam odczyt: `mode=rw` bez tworzenia, więc widok kopii niczego nie zakłada, a pozostawiony po
    awarii dziennik transakcji SQLite może się wycofać (`mode=ro` by na nim odmówił i Banner
    wznowienia by zniknął). Krótki `timeout`: wątek API nie czeka za zapisem trwającego
    wgrywania — zablokowany stan jest na ten raz pomijany."""
    try:
        db = sqlite3.connect(f"{path.absolute().as_uri()}?mode=rw", uri=True, timeout=READ_TIMEOUT)
    except sqlite3.OperationalError as exc:
        if strict:
            raise OSError(f"restore state not readable: {exc}") from exc
        return None
    except sqlite3.Error:
        return None
    try:
        meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
        (left,) = db.execute("SELECT COUNT(*) FROM files WHERE status IN ('pending', 'pushing')").fetchone()
    except sqlite3.OperationalError as exc:
        if strict:
            raise OSError(f"restore state not readable: {exc}") from exc
        return None
    except (sqlite3.Error, ValueError):
        return None
    finally:
        db.close()
    return meta, left


def device_changes_pending(path: Path) -> bool:
    """Stan `path` istnieje i ma zmiany telefonu do odwrócenia (odczyt jak w widoku kopii)."""
    found = _read(path) if path.is_file() else None
    return found is not None and changes_pending(found[0].get("device_changes"))


def merge_changes(first: Any, second: Any) -> dict[str, Any]:
    """Dwa zapisy `device_changes` tego samego telefonu w jeden: pole z `first`, gdy coś mówi
    (różne od `None`/`False`), inaczej z `second` — żadna zmiana do odwrócenia nie ginie."""
    a = first if isinstance(first, dict) else {}
    b = second if isinstance(second, dict) else {}
    return {k: a[k] if a.get(k) is not None and a.get(k) is not False else b.get(k)
            for k in dict.fromkeys([*a, *b])}


def _atomic_write(path: Path, text: str) -> None:
    """Plik tymczasowy obok, `fsync` i `os.replace`: zapis jest cały albo go nie ma."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class PhoneRecord:
    """Zapis zmian jednego nowego telefonu poza kopiami: `phone_changes/<device_dir_name(serial)>.json`
    (`paths.phone_changes_dir`), `{"device_changes": {...}}`. `phonesetup` pisze go razem z meta stanu
    wgrywania i usuwa, gdy nic nie zostało do odwrócenia; sprzątanie przy podłączeniu czyta go także
    wtedy, gdy kopii już nie ma. Interfejs meta jak `RestoreState` (`get_meta`/`set_meta`/`close`)."""

    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def for_serial(cls, serial: str) -> PhoneRecord:
        return cls(phone_changes_dir() / f"{device_dir_name(serial)}.json")

    @classmethod
    def of_state(cls, path: Path) -> PhoneRecord:
        """Zapis telefonu stanu `path` (`<kopia>/restore/<device_dir_name(serial)>.sqlite`)."""
        return cls(phone_changes_dir() / f"{path.stem}.json")

    def get_meta(self, key: str, default: Any = None) -> Any:
        """Brak pliku = brak zapisu. Plik, który jest, ale nie daje się odczytać (zablokowany, uszkodzony)
        → OSError: nie wolno go wziąć za brak zapisu ani nadpisać (`_save`, `keep_copy_changes`)."""
        try:
            text = self.path.read_text("utf-8")
        except FileNotFoundError:
            return default
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise OSError(f"phone changes record not readable: {self.path.name}") from exc
        if not isinstance(data, dict):
            raise OSError(f"phone changes record not readable: {self.path.name}")
        return data.get(key, default)

    def set_meta(self, key: str, value: Any) -> None:
        if key != CHANGES_KEY:
            raise ValueError(key)
        if changes_pending(value):
            _atomic_write(self.path, json.dumps({CHANGES_KEY: value}, ensure_ascii=False))
        else:
            self.path.unlink(missing_ok=True)

    @property
    def pending(self) -> bool:
        return changes_pending(self.get_meta(CHANGES_KEY))

    def close(self) -> None:
        pass


def keep_copy_changes(copy: CopyDir) -> None:
    """Przed usunięciem kopii: zmiany telefonów zapisane tylko w jej stanach wgrywania (stany sprzed
    zapisu poza kopią, także bez `serial`/`status`) dopisujemy do zapisu telefonu. Nieudany zapis →
    OSError: kopia zostaje — tak samo przy stanie, którego nie da się otworzyć (blokada) i przy
    nieczytelnym zapisie telefonu. Uszkodzonego pliku stanu i tak nie odczytamy — pomijamy go."""
    try:
        paths = sorted((copy.path / "restore").glob("*.sqlite"))
    except OSError:
        return
    for path in paths:
        found = _read(path, strict=True)
        if found is None:
            continue
        changes = found[0].get(CHANGES_KEY)
        if not changes_pending(changes):
            continue
        record = PhoneRecord.of_state(path)
        record.set_meta(CHANGES_KEY, merge_changes(record.get_meta(CHANGES_KEY), changes))


def _summary(path: Path) -> RestoreSummary | None:
    found = _read(path)
    if found is None:
        return None
    meta, left = found
    serial, status, updated = meta.get("serial"), meta.get("status"), meta.get("updated")
    if not isinstance(serial, str) or not isinstance(status, str):
        return None
    return RestoreSummary(serial, status, updated if isinstance(updated, str) else None,
                          # `complete` z `tel_left`: pliki skończone, a wybranej telefonii jeszcze nie
                          # było (program zamknięty między etapami; most zapisuje `tel_left` przed plikami)
                          (status != "complete" and left > 0) or _tel_left(meta) > 0 or apps_left(meta) > 0,
                          changes_pending(meta.get("device_changes")),
                          meta["imei"] if isinstance(meta.get("imei"), str) else None)


def apps_left(meta: dict[str, Any]) -> int:
    """Aplikacje wybrane do instalacji, a jeszcze nierozstrzygnięte (meta `apps_left`: most ustawia je przed
    plikami, a po etapie aplikacji na liczbę bez wyniku). Stan bez aplikacji w wyborze ich nie liczy."""
    left = meta.get("apps_left")
    choice = meta.get("choice")
    if not isinstance(left, int) or (isinstance(choice, dict) and not choice.get("apps")):
        return 0
    return left


def _tel_left(meta: dict[str, Any]) -> int:
    """Rekordy telefonii jeszcze nierozstrzygnięte (meta `tel_left`, `restore_tel`). Wybór bez telefonii
    (wznowienie tylko plików) ich nie liczy; stan bez wyboru (sama telefonia) — liczy."""
    left = meta.get("tel_left")
    choice = meta.get("choice")
    if not isinstance(left, int) or (isinstance(choice, dict) and not choice.get("tel")):
        return 0
    return left


def read_restores(copy: CopyDir) -> list[RestoreSummary]:
    """Wgrywania tej kopii (po jednym na telefon docelowy), najnowsze pierwsze; nieczytelny stan
    albo stan bez `serial`/`status` (przebieg, który nic nie zaczął) pomijamy."""
    try:
        paths = sorted((copy.path / "restore").glob("*.sqlite"))
    except OSError:
        return []
    found = [s for s in map(_summary, paths) if s is not None]
    return sorted(found, key=lambda s: (s.updated or "", s.serial), reverse=True)


def _row(r: tuple[Any, ...]) -> RestoreRow:
    return RestoreRow(*r[:-1], own=bool(r[-1]))


def is_own(row: RestoreRow) -> bool:
    """Pod celem wiersza może leżeć nasz (niedokończony) plik z poprzedniego podejścia."""
    return (row.status == "pushing" or (row.status in ("pending", "error") and row.error in OWN_PARTIAL)
            or (row.status == "skipped" and row.own))
