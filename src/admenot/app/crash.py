"""Raporty błędów (spec raportów błędów §3, §5.1, §6.4): pliki w crashes/, wysyłka na klik.

Raport powstaje w chwili błędu, już po wycięciu danych (`redact`), i czeka w pliku; podgląd w UI
to dokładnie treść wysyłki. Zapis nigdy nie rzuca — awaria raportu nie może pogłębić awarii programu.
Moduł nie importuje `admenot.app.errors` na poziomie modułu (errors importuje crash).
"""

from __future__ import annotations

import faulthandler
import json
import os
import platform
import re
import secrets
import string
import sys
import threading
import traceback
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from admenot import __version__
from admenot.app.redact import adb_line, redact
from admenot.engine.adb.sessionlog import session_log_path
from admenot.engine.paths import crashes_dir, logs_dir
from admenot.net import client

FORMAT = 1
KINDS = ("error", "ui", "thread", "exit")
CRASH_TEST = "ADMENOT_CRASH_TEST"
ENDPOINT = "/api/v1/reports"
MAX_FILES = 20
KEEP_DAYS = 30
MESSAGE_LIMIT = 1000
TRACE_LIMIT = 16 * 1024
LOG_LIMIT = 8 * 1024
TYPE_LIMIT = 200
WHERE_LIMIT = 300
ADB_LINES = 50
ADB_READ = 64 * 1024  # z końca logu sesji czytamy tylko tyle bajtów
COMMENT_LIMIT = 1000
MARKER = "running.json"
FAULT = "fault.txt"
LOCK = "session.lock"
ID_RE = re.compile(r"^\d{8}-\d{6}-[a-z0-9]{4}$")
SENT_RE = re.compile(r"^R-[0-9A-HJKMNP-TV-Z]{6}$")
_ALPHABET = string.ascii_lowercase + string.digits

Now = Callable[[], datetime]
Post = Callable[[str, dict[str, Any]], dict[str, Any]]


class UnknownCrash(Exception):
    """Nie ma raportu o tym identyfikatorze (albo identyfikator ma zły kształt)."""


class _Session:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.serials: set[str] = set()
        self.device: dict[str, str] | None = None
        self.seen: dict[tuple[str, str | None], str] = {}  # (typ, miejsce) → id
        self.started: datetime | None = None
        self.fault: Any = None  # plik faulthandlera (Task 3)
        self.handler_was_enabled = False
        self.lock_file: Any = None  # uchwyt blokady sesji (jedna instancja GUI naraz)
        self.claimed = False


_session = _Session()
_send_lock = threading.Lock()  # wywołania API z JS idą z wątków roboczych — jedna wysyłka naraz


def reset_session() -> None:
    global _session
    _session = _Session()


def note_serials(serials: Iterable[str]) -> None:
    with _session.lock:
        _session.serials.update(s for s in serials if s)


def note_device(serial: str, manufacturer: str, model: str, android: str) -> None:
    with _session.lock:
        if serial:
            _session.serials.add(serial)
        _session.device = {"manufacturer": manufacturer, "model": model, "android": android}


def _log_failure(exc: BaseException) -> None:
    try:
        from admenot.app.errors import log_exception  # errors importuje crash

        log_exception(exc)
    except Exception:  # noqa: BLE001, S110 — ostatnia linia obrony
        pass


def _tail(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    return text if len(text) <= limit else text[-limit:]


def _where(exc: BaseException) -> str | None:
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return None
    last = frames[-1]
    return f"{Path(last.filename).name}:{last.lineno} in {last.name}"[:WHERE_LIMIT]


def _lang() -> str:
    from admenot.engine.settings import effective_lang, load_settings, system_lang

    try:
        return effective_lang(load_settings())
    except Exception:  # noqa: BLE001 — np. SettingsTooNew
        return system_lang()


def _adb_tail(now: datetime, serials: set[str]) -> list[str] | None:
    path = session_log_path(logs_dir(), now)
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - ADB_READ))
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    lines = [adb_line(line, serials) for line in raw.splitlines()[-ADB_LINES - 1:]]
    kept = [line for line in lines if line]
    return kept[-ADB_LINES:] or None


def _path(crash_id: str) -> Path:
    if not isinstance(crash_id, str) or not ID_RE.match(crash_id):
        raise UnknownCrash(str(crash_id))
    path = crashes_dir() / f"{crash_id}.json"
    if not path.is_file():
        raise UnknownCrash(crash_id)
    return path


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("kind") not in KINDS:
        return None
    return data


def _load(crash_id: str) -> dict[str, Any]:
    data = _read(_path(crash_id))
    if data is None:
        raise UnknownCrash(crash_id)
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def capture(exc: BaseException | None = None, *, kind: str = "error",
            context: dict[str, Any] | None = None, type_: str | None = None,
            message: str | None = None, trace: str | None = None, where: str | None = None,
            log_tail: str | None = None, now: Now | None = None) -> str | None:
    """Zapisuje raport (albo zwiększa `count` duplikatu); zwraca identyfikator, przy błędzie None."""
    try:
        return _capture(exc, kind, context or {}, type_, message, trace, where, log_tail,
                        (now or datetime.now)())
    except Exception as failure:  # noqa: BLE001 — zapis raportu nigdy nie rzuca
        _log_failure(failure)
        return None


def _capture(exc: BaseException | None, kind: str, context: dict[str, Any], type_: str | None,
             message: str | None, trace: str | None, where: str | None, log_tail: str | None,
             stamp: datetime) -> str:
    if kind not in KINDS:
        raise ValueError(kind)
    if exc is not None:
        type_ = type_ or type(exc).__name__
        message = str(exc) if message is None else message
        trace = trace or "".join(traceback.format_exception(exc))
        where = where or _where(exc)
    type_ = (type_ or "Error")[:TYPE_LIMIT]
    with _session.lock:
        serials = set(_session.serials)
        device = dict(_session.device) if _session.device else None
        known = _session.seen.get((type_, where))
    if known is not None:
        path = crashes_dir() / f"{known}.json"
        data = _read(path)
        if data is not None and data["sent"] is None:
            data["count"] += 1
            _write(path, data)
            return known

    def clean(text: str | None, limit: int) -> str | None:
        return _tail(redact(text, serials), limit) if text else None

    crash_id = f"{stamp:%Y%m%d-%H%M%S}-{''.join(secrets.choice(_ALPHABET) for _ in range(4))}"
    data = {
        "format": FORMAT, "kind": kind, "created": stamp.isoformat(timespec="seconds"), "count": 1,
        "app": __version__, "os": f"{platform.system()} {platform.version()}", "lang": _lang(),
        "context": {"call": context.get("call"), "job": context.get("job"),
                    "screen": context.get("screen"), "device": device},
        "error": {"type": type_, "message": (redact(message or "", serials))[:MESSAGE_LIMIT],
                  "where": redact(where, serials)[:WHERE_LIMIT] if where else None,
                  "trace": clean(trace, TRACE_LIMIT)},
        "log_tail": clean(log_tail, LOG_LIMIT),
        "adb_tail": _adb_tail(stamp, serials),
        "sent": None, "announced": False,
    }
    _write(crashes_dir() / f"{crash_id}.json", data)
    with _session.lock:
        _session.seen[(type_, where)] = crash_id
    prune(now=lambda: stamp)
    return crash_id


def _files() -> list[Path]:
    try:
        # tylko pliki o kształcie identyfikatora (nie running.json); nazwa zaczyna się od czasu → kolejność
        return sorted(p for p in crashes_dir().glob("*.json") if ID_RE.match(p.stem))
    except OSError:
        return []


def prune(now: Now | None = None) -> None:
    """Usuwa pliki uszkodzone, starsze niż KEEP_DAYS i nadmiarowe ponad MAX_FILES (najstarsze)."""
    limit = (now or datetime.now)() - timedelta(days=KEEP_DAYS)
    try:
        for leftover in crashes_dir().glob("*.tmp"):  # resztki nieudanych zapisów
            leftover.unlink(missing_ok=True)
    except OSError:
        pass
    kept: list[Path] = []
    for path in _files():
        data = _read(path)
        stale = data is None
        if data is not None:
            try:
                stale = datetime.fromisoformat(data["created"]) < limit
            except (TypeError, ValueError):
                stale = True
        if stale:
            path.unlink(missing_ok=True)
        else:
            kept.append(path)
    for path in kept[:-MAX_FILES] if len(kept) > MAX_FILES else []:
        path.unlink(missing_ok=True)


def list_reports() -> list[dict[str, Any]]:
    out = []
    for path in reversed(_files()):
        data = _read(path)
        if data is not None:
            out.append({"id": path.stem, "kind": data["kind"], "created": data["created"],
                        "type": data["error"]["type"],
                        "sent_id": data["sent"]["id"] if data["sent"] else None})
    return out


def startup_reports() -> list[str]:
    """Niewysłane raporty po awarii (`exit`, `thread`), każdy pokazany w banerze tylko raz."""
    ids = []
    for path in _files():
        data = _read(path)
        if data and data["kind"] in ("exit", "thread") and data["sent"] is None \
                and not data.get("announced"):
            data["announced"] = True
            _write(path, data)
            ids.append(path.stem)
    return ids


def _body(data: dict[str, Any], include_adb: bool, comment: str | None) -> dict[str, Any]:
    with _session.lock:
        serials = set(_session.serials)
    text = redact((comment or "").strip(), serials)[:COMMENT_LIMIT]
    return {"format": FORMAT, "kind": data["kind"], "app": data["app"], "os": data["os"],
            "lang": data["lang"], "count": data["count"], "created": data["created"],
            "context": data["context"], "error": data["error"], "log_tail": data["log_tail"],
            "adb_tail": data["adb_tail"] if include_adb else None, "comment": text or None}


def preview(crash_id: str, include_adb: bool, comment: str | None) -> dict[str, Any]:
    data = _load(crash_id)
    return {"body": _body(data, include_adb, comment), "has_adb": bool(data["adb_tail"])}


def send(crash_id: str, include_adb: bool, comment: str | None, post: Post | None = None,
         now: Now | None = None) -> str:
    with _send_lock:
        path = _path(crash_id)
        data = _load(crash_id)
        if data["sent"]:
            return data["sent"]["id"]
        result = (post or client.post_json)(ENDPOINT, _body(data, include_adb, comment))
        sent_id = result.get("id")
        if not isinstance(sent_id, str) or not SENT_RE.match(sent_id):
            raise client.BackendError("invalid")
        data["sent"] = {"id": sent_id, "at": (now or datetime.now)().isoformat(timespec="seconds")}
        _write(path, data)
        return sent_id


def discard(crash_id: str) -> None:
    _path(crash_id).unlink(missing_ok=True)


def claim_session() -> bool:
    """Blokada na czas życia procesu: tylko pierwsza instancja GUI zarządza znacznikiem i zrzutem."""
    try:
        if _session.claimed:
            return True
        directory = crashes_dir()
        directory.mkdir(parents=True, exist_ok=True)
        handle = (directory / LOCK).open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        _session.lock_file = handle
        _session.claimed = True
        return True
    except Exception as failure:  # noqa: BLE001
        _log_failure(failure)
        return False


def start_session(now: Now | None = None) -> None:
    """Tylko z `run_gui`: znacznik „program działa” i zrzut stosu przy awarii (spec §3.1 pkt 4)."""
    try:
        directory = crashes_dir()
        directory.mkdir(parents=True, exist_ok=True)
        started = (now or datetime.now)()
        _session.started = started
        (directory / MARKER).write_text(
            json.dumps({"app": __version__, "started": started.isoformat(timespec="seconds")}),
            "utf-8")
        _session.handler_was_enabled = faulthandler.is_enabled()
        _session.fault = (directory / FAULT).open("w", encoding="utf-8")
        faulthandler.enable(_session.fault, all_threads=True)
    except Exception as failure:  # noqa: BLE001
        _log_failure(failure)


def end_session() -> None:
    try:
        if not _session.claimed:
            return  # cudza sesja — nie ruszamy jej znacznika ani zrzutu
        if _session.fault is not None:
            faulthandler.disable()
            _session.fault.close()
            _session.fault = None
            if _session.handler_was_enabled and sys.__stderr__ is not None:
                faulthandler.enable(sys.__stderr__)  # np. pytest miał własny
        for name in (MARKER, FAULT):
            (crashes_dir() / name).unlink(missing_ok=True)
        if _session.lock_file is not None:
            _session.lock_file.close()  # zamknięcie uchwytu zwalnia blokadę
            _session.lock_file = None
        _session.claimed = False
    except Exception as failure:  # noqa: BLE001
        _log_failure(failure)


def _log_since(started: datetime) -> str:
    """Wpisy `app-*.log` (format `log_exception`) z czasem ≥ `started`, z dnia startu i dziś."""
    days = {started.date(), datetime.now().date()}
    entries: list[str] = []
    for day in sorted(days):
        try:
            text = (logs_dir() / f"app-{day:%Y-%m-%d}.log").read_text("utf-8", errors="replace")
        except OSError:
            continue
        for chunk in re.split(r"(?m)^--- ", text)[1:]:
            head, _, _rest = chunk.partition("\n")
            try:
                stamp = datetime.fromisoformat(head.strip())
            except ValueError:
                continue
            if stamp >= started:
                entries.append("--- " + chunk)
    return "".join(entries).strip()


def recover(now: Now | None = None) -> str | None:
    """Przy starcie, przed `start_session`: raport `exit`, jeśli poprzednia sesja padła ze śladem."""
    try:
        directory = crashes_dir()
        marker = directory / MARKER
        crash_id = None
        if marker.is_file():
            try:
                started = datetime.fromisoformat(json.loads(marker.read_text("utf-8"))["started"])
            except (OSError, ValueError, KeyError, TypeError):
                started = None
            fault = ""
            if started is not None:
                try:
                    fault = (directory / FAULT).read_text("utf-8", errors="replace").strip()
                except OSError:
                    fault = ""
                log = _log_since(started)
                if fault or log:
                    first = fault.splitlines()[0] if fault else "AdMeNot zakończył się nieoczekiwanie"
                    crash_id = capture(kind="exit", type_="fatal" if fault else "exit",
                                       message=first, trace=fault or None, log_tail=log or None,
                                       now=now)
            marker.unlink(missing_ok=True)
            (directory / FAULT).unlink(missing_ok=True)
        prune(now=now)
        return crash_id
    except Exception as failure:  # noqa: BLE001
        _log_failure(failure)
        return None


def install_hooks() -> None:
    """Nieobsłużony wyjątek w wątku albo w głównym wątku → raport `thread` (bez komunikatu w UI)."""
    previous_sys = sys.excepthook
    previous_thread = threading.excepthook

    def on_sys(exc_type, exc, tb):  # type: ignore[no-untyped-def]
        if exc is not None and not issubclass(exc_type, (SystemExit, KeyboardInterrupt)):
            capture(exc, kind="thread", context={"call": "main"})
        previous_sys(exc_type, exc, tb)

    def on_thread(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is not None and args.exc_type is not SystemExit:
            name = args.thread.name if args.thread is not None else "?"
            capture(args.exc_value, kind="thread", context={"call": f"thread:{name}"})
        previous_thread(args)

    sys.excepthook = on_sys
    threading.excepthook = on_thread
