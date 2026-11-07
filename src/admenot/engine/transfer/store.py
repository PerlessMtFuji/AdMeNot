"""Katalog kopii danych telefonu: `meta.json`, stan wznawiania i usuwanie po terminie.

Układ: `<transfers>/<device_dir_name(serial)>/<RRRRMMDD-GGMMSS>/` z `meta.json`, `state.sqlite`,
`manifest.csv`, `log.txt` oraz katalogami `files`, `phone`, `apps` (nazwy niezależne od języka).
Identyfikator kopii to `<telefon>/<znacznik>` z ukośnikiem na każdym systemie. Kopię usuwamy tylko wtedy, gdy ma dokładnie ten kształt
(jak `retention` dla kopii APK) — identyfikator nie może wyprowadzić poza katalog kopii.

Folderów kopii może być kilka (`copy_roots`): nowe kopie trafiają do bieżącego (`paths.transfers_dir`),
a kopie z folderów używanych wcześniej (`Settings.transfer_roots`) dalej są widoczne, przywracalne,
przedłużalne i usuwane po swoim terminie (termin leży w `meta.json` każdej kopii).
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
from typing import TYPE_CHECKING, Any, Literal

from admenot.engine.device.info import DeviceInfo
from admenot.engine.paths import device_dir_name, transfers_dir
from admenot.engine.settings import (
    TRANSFER_ROOTS_MAX,
    load_settings,
    save_internal,
    settings_transaction,
)

if TYPE_CHECKING:
    from .inventory import AppEntry

KEEP_DAYS = 7  # domyślny termin; most podaje `Settings.transfer_keep_days`
META = "meta.json"
VERDICTS = "verdicts.json"
# Notatka serwisanta poza `meta.json`: kopia w toku przepisuje meta (liczniki, status) i nie może
# nadpisać notatki dopisanej w tym czasie.
NOTE = "note.txt"
NOTE_MAX = 2000  # znaków
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

    def read_note(self) -> str | None:
        """Notatka serwisanta; brak pliku albo nieczytelny plik → None (widok kopii się nie psuje)."""
        try:
            return (self.path / NOTE).read_text(encoding="utf-8").strip() or None
        except (OSError, UnicodeDecodeError):
            return None

    def write_note(self, text: str | None) -> None:
        """Atomowo jak `write_meta`; pusta notatka usuwa plik."""
        path = self.path / NOTE
        if not text:
            path.unlink(missing_ok=True)
            return
        tmp = path.with_name(NOTE + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    @property
    def state_path(self) -> Path:
        return self.path / "state.sqlite"

    @property
    def files_dir(self) -> Path:
        return self.path / "files"

    @property
    def phone_dir(self) -> Path:
        return self.path / "phone"

    @property
    def apps_dir(self) -> Path:
        return self.path / "apps"

    def read_meta(self) -> CopyMeta:
        return CopyMeta.from_json(json.loads(self.meta_path.read_text(encoding="utf-8")))

    def write_meta(self, meta: CopyMeta) -> None:
        """Atomowo: plik tymczasowy obok i `os.replace`, więc przerwanie nie zostawia pół pliku."""
        tmp = self.meta_path.with_name(META + ".tmp")
        tmp.write_text(json.dumps(meta.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.meta_path)

    @property
    def verdicts_path(self) -> Path:
        return self.path / VERDICTS

    def write_verdicts(self, entries: list[AppEntry]) -> None:
        """Werdykty aplikacji starego telefonu (także pominiętych); atomowo jak `write_meta`."""
        data = [{"package": e.package, "version_code": e.version_code, "verdict": e.verdict} for e in entries]
        tmp = self.verdicts_path.with_name(VERDICTS + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.verdicts_path)

    def read_verdicts(self) -> dict[str, tuple[int | None, str]] | None:
        """Pakiet -> (versionCode, werdykt); `None`, gdy pliku brak (kopia sprzed zmiany) albo jest nieczytelny."""
        try:
            data = json.loads(self.verdicts_path.read_text(encoding="utf-8"))
            result: dict[str, tuple[int | None, str]] = {}
            for item in data:
                code = item["version_code"]
                result[str(item["package"])] = (None if code is None else int(code), str(item["verdict"]))
            return result
        except (OSError, ValueError, KeyError, TypeError):
            return None


def create_copy(serial: str, device: DeviceInfo, client: str | None, now: datetime,
                keep_days: int = KEEP_DAYS) -> CopyDir:
    """Nowy katalog kopii w bieżącym folderze kopii, z terminem `keep_days` dni. Zajęty znacznik
    (druga kopia w tej samej sekundzie) — następna wolna sekunda. Pod blokadą ustawień: zmiana
    folderu kopii w tym czasie widzi już gotową kopię i zapamiętuje stary folder."""
    with settings_transaction():
        return _create_copy(serial, device, client, now, keep_days)


def _create_copy(serial: str, device: DeviceInfo, client: str | None, now: datetime, keep_days: int) -> CopyDir:
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
            created=stamp_time, expires=stamp_time + timedelta(days=keep_days), status="in_progress"))
    except BaseException:
        shutil.rmtree(path, ignore_errors=True)  # nie zostawiamy katalogu bez meta.json
        raise
    return copy


def _path_key(path: Path) -> str:
    try:
        return os.path.normcase(str(path.resolve()))
    except OSError:  # niedostępny dysk sieciowy
        return os.path.normcase(os.path.abspath(path))


def copy_roots() -> list[Path]:
    """Foldery kopii: bieżący pierwszy (także gdy jeszcze nie istnieje), potem istniejące foldery
    z `Settings.transfer_roots`, bez duplikatów. Nieistniejący zapamiętany folder (np. odłączony
    pendrive) pomijamy, ale nie zapominamy — jego kopie wrócą po podłączeniu."""
    roots = [transfers_dir()] + [Path(p) for p in load_settings().transfer_roots]
    seen: set[str] = set()
    result: list[Path] = []
    for i, root in enumerate(roots):
        key = _path_key(root)
        if key in seen or (i and not root.is_dir()):
            continue
        seen.add(key)
        result.append(root)
    return result


def _root_dirs(root: Path) -> list[CopyDir]:
    """Katalogi o kształcie kopii w jednym folderze kopii."""
    found: list[CopyDir] = []
    try:
        devices = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return []
    for device in devices:
        with contextlib.suppress(OSError):
            found.extend(CopyDir(c) for c in device.iterdir() if _STAMP.fullmatch(c.name) and c.is_dir())
    return found


def _newest_first(dirs: list[CopyDir]) -> list[CopyDir]:
    return sorted(dirs, key=lambda c: (c.path.name, c.path.parent.name), reverse=True)


def _all_copy_dirs() -> list[CopyDir]:
    """Wszystkie katalogi kopii ze wszystkich folderów — także o tym samym identyfikatorze."""
    return _newest_first([c for root in copy_roots() for c in _root_dirs(root)])


def _copy_dirs() -> list[CopyDir]:
    """Katalogi kopii, najnowsze pierwsze (znacznik czasu, potem telefon). Ten sam identyfikator
    w dwóch folderach: wygrywa pierwszy folder z `copy_roots()` (jak w `resolve`)."""
    seen: set[str] = set()
    found: list[CopyDir] = []
    for root in copy_roots():
        for copy in _root_dirs(root):
            copy_id = f"{copy.path.parent.name}/{copy.path.name}"
            if copy_id not in seen:
                seen.add(copy_id)
                found.append(copy)
    return _newest_first(found)


RootState = Literal["copies", "empty", "missing", "unreadable"]


def _root_state(root: Path) -> RootState:
    """Co wiadomo o folderze kopii. `empty` tylko wtedy, gdy folder istnieje, cały dał się
    przejrzeć i nie ma w nim katalogu kopii z `meta.json` (także nieczytelnym — takiej kopii nie
    usuwamy, więc folderu też nie zapominamy). Błąd odczytu to `unreadable`, nie `empty`."""
    try:
        devices = [d for d in root.iterdir() if d.is_dir()]
    except FileNotFoundError:
        return "missing"
    except OSError:  # brak dostępu, dysk sieciowy offline, „urządzenie nie jest gotowe”
        return "unreadable"
    try:
        for device in devices:
            for c in device.iterdir():
                if _STAMP.fullmatch(c.name) and (c / META).is_file():
                    return "copies"
    except OSError:
        return "unreadable"
    return "empty"


def root_has_copies(root: Path) -> bool:
    """Czy w folderze na pewno leży choć jeden katalog kopii z `meta.json`."""
    return _root_state(root) == "copies"


def _may_hold_copies(root: Path) -> bool:
    """Przy zmianie folderu: czy poprzedni folder trzeba zapamiętać. Nie tylko gdy widać w nim
    kopie, ale też gdy nie da się go teraz odczytać (odłączony pendrive, dysk sieciowy offline):
    jego kopie wrócą po podłączeniu. Pomijamy tylko folder na pewno pusty oraz folder, którego
    brak, choć jego nadrzędny folder jest dostępny (nigdy nie powstał albo go usunięto)."""
    state = _root_state(root)
    if state == "missing":
        return not root.parent.is_dir()
    return state != "empty"


def forget_empty_roots() -> None:
    """Usuwa z `Settings.transfer_roots` foldery na pewno puste (`_root_state` == `empty`).
    Nieistniejący albo nieczytelny folder zostaje (odłączony dysk). Pod blokadą ustawień, żeby
    nie zgubić folderu dopisanego właśnie przy zmianie folderu kopii."""
    with settings_transaction():
        roots = load_settings().transfer_roots
        keep = [p for p in roots if _root_state(Path(p)) != "empty"]
        if keep != roots:
            save_internal({"transfer_roots": keep})


def remember_root(root: Path) -> None:
    """Po zmianie folderu kopii: dopisuje poprzedni folder `root` do `Settings.transfer_roots`, gdy
    mogą w nim leżeć kopie (`_may_hold_copies`). Najpierw zapomina foldery bez kopii; przy pełnej
    liście (`TRANSFER_ROOTS_MAX`) wypada najdawniej zapamiętany."""
    with settings_transaction():
        if _path_key(root) == _path_key(transfers_dir()) or not _may_hold_copies(root):
            return
        forget_empty_roots()
        roots = load_settings().transfer_roots
        if any(_path_key(Path(p)) == _path_key(root) for p in roots):
            return
        save_internal({"transfer_roots": [*roots, str(root)][-TRANSFER_ROOTS_MAX:]})


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


def resolve(copy_id: str) -> CopyDir:
    """Katalog kopii z identyfikatora, szukany w `copy_roots()` po kolei (pierwszy folder wygrywa).
    Każdy inny kształt niż `<telefon>/<RRRRMMDD-GGMMSS>`, katalog wyprowadzający poza swój folder
    kopii (np. przez dowiązanie) i katalog bez `meta.json` to ValueError."""
    parts = copy_id.split("/")
    if len(parts) != 2 or not _SAFE_PART.fullmatch(parts[0]) or not _STAMP.fullmatch(parts[1]):
        raise ValueError(f"niepoprawny identyfikator kopii: {copy_id!r}")
    for root_dir in copy_roots():
        try:
            root = root_dir.resolve()
            path = (root / parts[0] / parts[1]).resolve()
        except OSError:
            continue
        if path.parent.parent != root or path.parent.name != parts[0] or path.name != parts[1]:
            continue
        if path.is_dir() and (path / META).is_file():
            return CopyDir(path)
    raise ValueError(f"to nie jest katalog kopii: {copy_id!r}")


def extend(copy_id: str, keep_days: int = KEEP_DAYS) -> CopyMeta:
    """Przedłuża o kolejne `keep_days` dni od dotychczasowego terminu (bez limitu)."""
    copy = resolve(copy_id)
    try:
        meta = copy.read_meta()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"nieczytelny meta.json kopii: {copy_id!r}") from exc
    meta.expires += timedelta(days=keep_days)
    copy.write_meta(meta)
    meta.id = copy_id
    return meta


def set_note(copy_id: str, text: str | None) -> CopyMeta:
    """Notatka serwisanta do kopii (także w toku). Za długa → ValueError."""
    text = (text or "").strip()
    if len(text) > NOTE_MAX:
        raise ValueError(f"notatka dłuższa niż {NOTE_MAX} znaków")
    copy = resolve(copy_id)
    try:
        meta = copy.read_meta()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"nieczytelny meta.json kopii: {copy_id!r}") from exc
    copy.write_note(text or None)
    meta.id = copy_id
    return meta


def delete(copy_id: str) -> None:
    """Najpierw dane, na końcu `meta.json` i pusty katalog. Błąd w połowie (np. zablokowany plik)
    zostawia `meta.json`, więc kopia nadal jest widoczna i następne usunięcie ją dokończy.
    Przedtem zmiany nowych telefonów zapisane tylko w stanach wgrywania kopii trafiają do zapisu
    telefonu poza kopią (`restore_state.keep_copy_changes`); nieudany zapis (OSError) — kopia zostaje."""
    _delete_dir(resolve(copy_id))


def _delete_dir(copy: CopyDir) -> None:
    from .restore_state import keep_copy_changes  # restore_state importuje ten moduł

    keep_copy_changes(copy)
    path = copy.path
    for child in list(path.iterdir()):
        if child.name == META:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    (path / META).unlink()
    path.rmdir()


def copy_dir(copy_id: str) -> CopyDir:
    """Katalog kopii z identyfikatora (`<telefon>/<RRRRMMDD-GGMMSS>`); każdy inny kształt albo
    katalog bez `meta.json` → ValueError."""
    return resolve(copy_id)


def purge_expired(now: datetime, busy: Callable[[str], bool], busy_copy: Callable[[str], bool]) -> list[str]:
    """Usuwa kopie po terminie. Kopia, której telefon jest zajęty (`busy(serial)`), kopia właśnie
    używana (`busy_copy(id)`, np. wgrywana na nowy telefon) i kopia z nieczytelnym `meta.json`
    zostają: nie kasujemy tego, czego nie umiemy rozpoznać. Zmiany nowego telefonu do odwrócenia
    nie giną z kopią (`delete`). Przechodzi po wszystkich folderach kopii (`copy_roots`) i usuwa
    katalog, który znalazła (także kopię przesłoniętą tym samym id w pierwszym folderze), a na
    końcu zapomina foldery, w których nie została żadna kopia (`forget_empty_roots`)."""
    removed: list[str] = []
    for copy in _all_copy_dirs():
        meta = _readable(copy)
        if meta is None or meta.expires > now or busy(meta.serial) or busy_copy(meta.id):
            continue
        try:
            _delete_dir(copy)
        except (OSError, ValueError):  # np. plik otwarty w innym programie: zostaje do następnego razu
            continue
        removed.append(meta.id)
    forget_empty_roots()
    return removed
