"""Log techniczny sesji (spec §7.5): polecenia ADB, status i czas — bez wyjścia poleceń.

GUI dostaje każde polecenie na żywo (`on_command`, z wyjściem obciętym do OUTPUT_LIMIT) dla
konsoli ADB — bez wyjścia zrzutu powiadomień z treścią (`--noredact`), danych z providerów (`content`)
i listy kont (`dumpsys account`), o ile serwisant nie wpisał go sam. Polecenia wpisane w konsoli
mają `tag="console"` i prefiks `console:` w logu.
W pliku logu ścieżki plików klienta (`/sdcard/…`, katalog kopii) są zwinięte (`client_paths`).
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from admenot.engine.adb.transport import AdbError, AdbTransport
from admenot.engine.clientpaths import client_paths

_LOCK = threading.Lock()  # kolektory wołają adb z wielu wątków naraz
OUTPUT_LIMIT = 4096
_PRIVATE = "--noredact"  # zrzut powiadomień z tytułami i treścią
# Dane klienta z providerów (kontakty, SMS, połączenia, MMS) — `content query` / `content read`,
# także w postaci `host:shell -T …` i `host:exec-out …`.
_CONTENT = re.compile(r"^(?:host:(?:shell -T |exec-out ))?content (?:query|read)(?:\s|$)")
# Konta na telefonie (plan telefonii): `dumpsys account` wypisuje adresy e-mail klienta.
_ACCOUNTS = re.compile(r"^(?:host:(?:shell -T |exec-out ))?dumpsys account(?:\s|$)")

OnCommand = Callable[[dict[str, Any]], None]


def session_log_path(logs_dir: Path, now: datetime) -> Path:
    return logs_dir / f"{now:%Y-%m-%d}.log"


class SessionLogAdb:
    def __init__(self, inner: AdbTransport, path: Path,
                 now: Callable[[], datetime] = datetime.now,
                 on_command: OnCommand | None = None, tag: str | None = None) -> None:
        self.inner = inner
        self.serial = inner.serial
        self.path = path
        self._now = now
        self.on_command = on_command
        self.tag = tag
        path.parent.mkdir(parents=True, exist_ok=True)

    def with_serial(self, serial: str) -> SessionLogAdb:
        return SessionLogAdb(self.inner.with_serial(serial), self.path, self._now,
                             self.on_command, self.tag)

    def tagged(self, tag: str) -> SessionLogAdb:
        return SessionLogAdb(self.inner, self.path, self._now, self.on_command, tag)

    def shell(self, command: str, timeout: float = 20.0) -> str:
        return self._logged(command, lambda: self.inner.shell(command, timeout=timeout))

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        return self._logged("host:" + " ".join(args), lambda: self.inner.run(args, timeout=timeout))

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        what = "host:" + " ".join(args)
        start = time.perf_counter()
        try:
            data = self.inner.run_bytes(args, timeout=timeout)
        except AdbError as exc:
            self._record(what, f"error:{exc.kind}", start, exc.message)
            raise
        self._record(what, "ok", start, f"<{len(data)} B>")  # obraz nie trafia do konsoli
        return data

    def note(self, what: str, status: str = "info") -> None:
        """Wpis bez wywołania adb (np. linia wyjścia scrcpy) — log sesji i konsola ADB."""
        self._record(what, status, time.perf_counter(), "")

    def _logged(self, what: str, call: Callable[[], str]) -> str:
        start = time.perf_counter()
        try:
            out = call()
        except AdbError as exc:
            self._record(what, f"error:{exc.kind}", start, exc.message)
            raise
        self._record(what, "ok", start, out)
        return out

    def _record(self, what: str, status: str, start: float, output: str) -> None:
        duration = time.perf_counter() - start
        stamp = self._now().isoformat(timespec="seconds")
        shown = f"{self.tag}:{what}" if self.tag else what
        # Plik logu (trzymany dłużej niż kopia danych) bez nazw plików i folderów klienta;
        # konsola na żywo (`on_command`) dostaje polecenie bez zmian.
        line = f"{stamp}\t{self.serial}\t{status}\t{duration:.2f}s\t{client_paths(shown)}\n"
        with _LOCK, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        if self.on_command is not None:
            if _PRIVATE in what and status == "ok" and self.tag != "console":  # treść powiadomień klienta
                output = f"<{len(output.encode())} B>"
            elif (_CONTENT.match(what) or _ACCOUNTS.match(what)) and status == "ok" \
                    and self.tag != "console":
                output = ""  # kontakty, wiadomości i konta klienta nie trafiają do konsoli
            self.on_command({"time": stamp, "serial": self.serial, "command": what,
                             "status": status, "duration": round(duration, 2),
                             "output": output[:OUTPUT_LIMIT], "tag": self.tag})
