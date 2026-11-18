"""Lista nieudanych pozycji kopii i wgrywania — z samych stanów SQLite i `meta.json`, bez telefonu.

Surowe kody błędów zostają w bazie i w logu; na zewnątrz idzie tylko powód z `REASONS`
(`reason_key`). `retryable` mówi, czy ponowienie ma sens: plik, który zniknął z telefonu, i aplikacja
odrzucona z przyczyny trwałej (`PERMANENT_APP_REASONS`) nie wrócą.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .restore_state import RestoreState, restore_state_path
from .state import State
from .store import CopyDir

REASONS = ("no_space", "denied", "disconnected", "vanished", "changed", "rejected", "verify", "other")
# Aplikacja odrzucona z przyczyny, której ponowienie nie zmieni.
PERMANENT_APP_REASONS = frozenset({"too_old", "no_abi", "version_downgrade", "invalid_apk", "conflict"})

_NO_SPACE = frozenset({"no_space", "disk_full", "enospc"})
_DISCONNECTED = frozenset({"disconnect", "disconnected", "no_device", "offline"})
_VANISHED = frozenset({"vanished", "missing"})
_REJECTED = frozenset({"failed", "user_restricted", "no_consent"}) | PERMANENT_APP_REASONS
_VERIFY = frozenset({"hash_mismatch", "hash_unavailable"})
_PHONE_PREFIXES = ("/storage/emulated/0/", "/sdcard/")


@dataclass(frozen=True)
class Failure:
    kind: Literal["file", "app", "tel"]
    group: str  # plik: grupa/root; app: "apps"; tel: "contacts" | "sms" | "calls" | …
    name: str  # plik: nazwa pliku; app: etykieta albo pakiet; tel: rodzaj
    folder: str  # plik: folder na telefonie (bez nazwy); app: pakiet; tel: ""
    reason: str  # jeden z REASONS
    count: int = 1  # tel: liczba nieudanych rekordów danego rodzaju
    retryable: bool = True


def reason_key(raw: str | None) -> str:
    """Surowy kod błędu -> powód z `REASONS`; wszystko nieznane to `other`."""
    code = (raw or "").strip().lower()
    if code in _NO_SPACE:
        return "no_space"
    if code == "denied":
        return "denied"
    if code in _DISCONNECTED:
        return "disconnected"
    if code in _VANISHED:
        return "vanished"
    if code == "changed":
        return "changed"
    if code in _REJECTED or code.startswith("install_failed"):
        return "rejected"
    if code in _VERIFY:
        return "verify"
    return "other"


def _split_remote(remote: str) -> tuple[str, str]:
    """(folder bez `/sdcard/`, nazwa pliku) ze ścieżki na telefonie."""
    path = remote
    for prefix in _PHONE_PREFIXES:
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    folder, _, name = path.rpartition("/")
    return folder, name


def _file(group: str, remote: str, reason: str) -> Failure:
    folder, name = _split_remote(remote)
    return Failure("file", group, name, folder, reason, retryable=reason != "vanished")


def _app(package: str, raw: str | None, labels: dict[str, str]) -> Failure:
    reason = reason_key(raw)
    retry = (raw or "").strip().lower() not in PERMANENT_APP_REASONS and reason != "vanished"
    return Failure("app", "apps", labels.get(package) or package, package, reason, retryable=retry)


def _ordered(files: list[Failure], apps: list[Failure], tel: list[Failure]) -> list[Failure]:
    files.sort(key=lambda f: (f.folder, f.name))
    apps.sort(key=lambda f: (f.name, f.folder))
    tel.sort(key=lambda f: f.name)
    return [*files, *apps, *tel]


def backup_failures(copy: CopyDir) -> list[Failure]:
    """Nieudane pozycje kopii: pliki `error` (`skipped` z `vanished` to nie błąd, nie wchodzą),
    aplikacje i kategorie telefonii ze statusem `failed`. Brak stanu → `[]`."""
    if not copy.state_path.is_file():
        return []
    state = State(copy.state_path)
    try:
        files = [_file(r.root, r.remote, reason_key(r.error)) for r in state.by_status("error")]
        apps_meta: dict[str, Any] = state.get_meta("apps", {})
        tel_meta: dict[str, Any] = state.get_meta("telephony", {})
    finally:
        state.close()
    labels = copy.read_app_labels()
    apps = [_app(p, v.get("error"), labels) for p, v in apps_meta.items() if v.get("status") == "failed"]
    tel = [Failure("tel", k, k, "", reason_key(v.get("error")))
           for k, v in tel_meta.items() if v.get("status") == "failed"]
    return _ordered(files, apps, tel)


def restore_failures(copy: CopyDir, serial: str) -> list[Failure]:
    """Nieudane pozycje wgrywania na telefon `serial`: pliki `denied`/`error`, aplikacje `failed`,
    rekordy telefonii `error` zliczone według rodzaju. Brak stanu → `[]`."""
    path = restore_state_path(copy, serial)
    if not path.is_file():
        return []
    state = RestoreState(path)
    try:
        files = [_file(r.grp, r.remote, "denied" if r.status == "denied" else reason_key(r.error))
                 for status in ("denied", "error") for r in state.by_status(status)]
        apps_raw = [(p, rs) for p, (st, rs, _code) in state.apps_status().items() if st == "failed"]
        tel_rows = state.db.execute(
            "SELECT kind, COUNT(*), MIN(error) FROM tel WHERE status='error' GROUP BY kind").fetchall()
    finally:
        state.close()
    labels = copy.read_app_labels()
    apps = [_app(p, rs, labels) for p, rs in apps_raw]
    tel = [Failure("tel", k, k, "", reason_key(err), count=n) for k, n, err in tel_rows]
    return _ordered(files, apps, tel)
