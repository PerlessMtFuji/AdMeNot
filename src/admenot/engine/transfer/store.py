"""Katalog kopii danych telefonu: `meta.json`, stan wznawiania i usuwanie po 7 dniach.

Układ: `<transfers>/<device_dir_name(serial)>/<RRRRMMDD-GGMMSS>/` z `meta.json`, `stan.sqlite`
oraz katalogami `pliki`, `telefon`, `aplikacje`. Identyfikator kopii to `<telefon>/<znacznik>`
z ukośnikiem na każdym systemie. Kopię usuwamy tylko wtedy, gdy ma dokładnie ten kształt
(jak `retention` dla kopii APK) — identyfikator nie może wyprowadzić poza katalog kopii.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from admenot.engine.device.info import DeviceInfo
from admenot.engine.paths import device_dir_name, transfers_dir

KEEP_DAYS = 7
META = "meta.json"
_STAMP_FORMAT = "%Y%m%d-%H%M%S"
_STAMP = re.compile(r"[0-9]{8}-[0-9]{6}")
_SAFE_PART = re.compile(r"[A-Za-z0-9_-]+")

Status = Literal["in_progress", "complete", "incomplete"]


@dataclass
class CopyMeta:
    id: str
    serial: str
    manufacturer: str
    model: str
    android: str
    imei: str | None
    client: str | None
    created: datetime
    expires: datetime
    status: Status
    selection: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    bytes: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "serial": self.serial, "manufacturer": self.manufacturer,
            "model": self.model, "android": self.android, "imei": self.imei, "client": self.client,
            "created": self.created.isoformat(), "expires": self.expires.isoformat(),
            "status": self.status, "selection": self.selection, "counts": self.counts,
            "bytes": self.bytes,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> CopyMeta:
        status = data["status"]
        if status not in ("in_progress", "complete", "incomplete"):
            raise ValueError(f"nieznany status kopii: {status!r}")
        return cls(
            id=str(data["id"]), serial=str(data["serial"]), manufacturer=str(data["manufacturer"]),
            model=str(data["model"]), android=str(data["android"]), imei=data.get("imei"),
            client=data.get("client"), created=datetime.fromisoformat(data["created"]),
            expires=datetime.fromisoformat(data["expires"]), status=status,
            selection=dict(data.get("selection") or {}), counts=dict(data.get("counts") or {}),
            bytes=int(data.get("bytes") or 0),
        )


class CopyDir:
    def __init__(self, path: Path):
        self.path = path

    @property
    def meta_path(self) -> Path:
        return self.path / META

    @property
    def state_path(self) -> Path:
        return self.path / "stan.sqlite"

    @property
    def files_dir(self) -> Path:
        return self.path / "pliki"

    @property
    def phone_dir(self) -> Path:
        return self.path / "telefon"

    @property
    def apps_dir(self) -> Path:
        return self.path / "aplikacje"

    def read_meta(self) -> CopyMeta:
        return CopyMeta.from_json(json.loads(self.meta_path.read_text(encoding="utf-8")))

    def write_meta(self, meta: CopyMeta) -> None:
        """Atomowo: plik tymczasowy obok i `os.replace`, więc przerwanie nie zostawia pół pliku."""
        tmp = self.meta_path.with_name(META + ".tmp")
        tmp.write_text(json.dumps(meta.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.meta_path)


def create_copy(serial: str, device: DeviceInfo, client: str | None, now: datetime) -> CopyDir:
    """Nowy katalog kopii. Zajęty znacznik (druga kopia w tej samej sekundzie) — następna wolna sekunda."""
    parent = transfers_dir() / device_dir_name(serial)
    parent.mkdir(parents=True, exist_ok=True)
    stamp_time = now.replace(microsecond=0)
    while True:
        stamp = stamp_time.strftime(_STAMP_FORMAT)
        path = parent / stamp
        try:
            path.mkdir()
        except FileExistsError:
            stamp_time += timedelta(seconds=1)
            continue
        break
    copy = CopyDir(path)
    try:
        copy.files_dir.mkdir()
        copy.phone_dir.mkdir()
        copy.apps_dir.mkdir()
        copy.write_meta(CopyMeta(
            id=f"{parent.name}/{stamp}", serial=serial, manufacturer=device.manufacturer,
            model=device.model, android=device.android_release, imei=device.imei, client=client,
            created=stamp_time, expires=stamp_time + timedelta(days=KEEP_DAYS), status="in_progress"))
    except BaseException:
        shutil.rmtree(path, ignore_errors=True)  # nie zostawiamy katalogu bez meta.json
        raise
    return copy


def _copy_dirs() -> list[CopyDir]:
    """Wszystkie katalogi o kształcie kopii, najnowsze pierwsze (znacznik czasu, potem telefon)."""
    root = transfers_dir()
    found: list[CopyDir] = []
    try:
        devices = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return []
    for device in devices:
        with contextlib.suppress(OSError):
            found.extend(CopyDir(c) for c in device.iterdir() if _STAMP.fullmatch(c.name) and c.is_dir())
    return sorted(found, key=lambda c: (c.path.name, c.path.parent.name), reverse=True)


def _readable(copy: CopyDir) -> CopyMeta | None:
    try:
        meta = copy.read_meta()
    except (OSError, ValueError, KeyError, TypeError):  # JSONDecodeError i błędy daty to ValueError
        return None
    # Identyfikator bierzemy z położenia katalogu: przeniesiony czy ręcznie zmieniony meta.json nie myli kopii.
    meta.id = f"{copy.path.parent.name}/{copy.path.name}"
    return meta


def find_resumable(serial: str) -> CopyDir | None:
    """Najnowsza niedokończona kopia tego telefonu."""
    for copy in _copy_dirs():
        if copy.path.parent.name != device_dir_name(serial):
            continue
        meta = _readable(copy)
        if meta is not None and meta.serial == serial and meta.status == "in_progress":
            return copy
    return None


def list_copies() -> list[CopyMeta]:
    """Wszystkie kopie, najnowsze pierwsze; uszkodzony `meta.json` pomijamy."""
    return [m for m in (_readable(c) for c in _copy_dirs()) if m is not None]


def _resolve(copy_id: str) -> CopyDir:
    """Katalog kopii z identyfikatora; każdy inny kształt niż `<telefon>/<RRRRMMDD-GGMMSS>` to ValueError."""
    parts = copy_id.split("/")
    if len(parts) != 2 or not _SAFE_PART.fullmatch(parts[0]) or not _STAMP.fullmatch(parts[1]):
        raise ValueError(f"niepoprawny identyfikator kopii: {copy_id!r}")
    root = transfers_dir().resolve()
    path = (root / parts[0] / parts[1]).resolve()
    if path.parent.parent != root or path.parent.name != parts[0] or path.name != parts[1]:
        raise ValueError(f"niepoprawny identyfikator kopii: {copy_id!r}")
    if not path.is_dir() or not (path / META).is_file():
        raise ValueError(f"to nie jest katalog kopii: {copy_id!r}")
    return CopyDir(path)


def extend(copy_id: str) -> CopyMeta:
    """Przedłuża o kolejne `KEEP_DAYS` dni od dotychczasowego terminu (bez limitu)."""
    copy = _resolve(copy_id)
    try:
        meta = copy.read_meta()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"nieczytelny meta.json kopii: {copy_id!r}") from exc
    meta.expires += timedelta(days=KEEP_DAYS)
    copy.write_meta(meta)
    meta.id = copy_id
    return meta


def delete(copy_id: str) -> None:
    """Najpierw dane, na końcu `meta.json` i pusty katalog. Błąd w połowie (np. zablokowany plik)
    zostawia `meta.json`, więc kopia nadal jest widoczna i następne usunięcie ją dokończy."""
    path = _resolve(copy_id).path
    for child in list(path.iterdir()):
        if child.name == META:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    (path / META).unlink()
    path.rmdir()


def purge_expired(now: datetime, busy: Callable[[str], bool]) -> list[str]:
    """Usuwa kopie po terminie. Kopia, której telefon jest zajęty (`busy(serial)`), i kopia z
    nieczytelnym `meta.json` zostają: nie kasujemy tego, czego nie umiemy rozpoznać."""
    removed: list[str] = []
    for copy in _copy_dirs():
        meta = _readable(copy)
        if meta is None or meta.expires > now or busy(meta.serial):
            continue
        try:
            delete(meta.id)
        except (OSError, ValueError):  # np. plik otwarty w innym programie: zostaje do następnego razu
            continue
        removed.append(meta.id)
    return removed
