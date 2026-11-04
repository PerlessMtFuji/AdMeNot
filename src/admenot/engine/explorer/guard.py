"""Strażnik poleceń eksploratora plików: każde polecenie adb eksploratora przechodzi przez `assert_explorer`.

Allowlista poleceń (odczyt pod `/sdcard/`, `mkdir -p`, `mv -n` i `rm -f` wyłącznie na naszym pliku
tymczasowym `.admenot-<12 hex>.part`, skan mediów) + odrzucanie metaznaków powłoki poza apostrofami
(`_unquoted_view` ze strażnika transferu). Nic nie nadpisuje i nie usuwa cudzych plików.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from admenot.engine.adb.transport import AdbTransport
from admenot.engine.transfer.guard import (
    _SCAN_VOLUME,
    CONTENT_TAIL,
    SCAN_VOLUME_CMD,
    STAT_TAIL,
    UnsafeCommand,
    _unquoted_view,
    q,
    safe_target,
)
from admenot.engine.transfer.puller import PullResult
from admenot.engine.transfer.pusher import Pusher

__all__ = [
    "HEAD_LIMIT", "SCAN_VOLUME_CMD", "STREAM_BLOCK", "TMP_PREFIX", "TMP_SUFFIX", "ExplorerAdb",
    "ExplorerPusher", "UnsafeCommand", "assert_explorer", "explorer_pusher", "is_tmp_name", "safe_read_path",
    "stream_args",
]

TMP_PREFIX = ".admenot-"
TMP_SUFFIX = ".part"
HEAD_LIMIT = 1048576  # największy odczyt `head -c` (1 MiB)
STREAM_BLOCK = 65536  # rozmiar bloku `dd`; wywołujący sam odrzuca `offset % STREAM_BLOCK` bajtów
_TMP_NAME = re.compile(r"\.admenot-[0-9a-f]{12}\.part")
_STAT_FORMAT = "%f|%s|%Y|%n"
_SCAN_FILE_PREFIX = ["content", "call", "--uri", "content://media", "--method", "scan_file", "--arg"]
_ALLOWED_CMDS = {"find", "stat", "sha256sum", "df", "ls", "head", "tail", "dd", "getprop", "content",
                 "mkdir", "mv", "rm"}


def is_tmp_name(name: str) -> bool:
    """Dokładnie `.admenot-<12 hex>.part`."""
    return _TMP_NAME.fullmatch(name) is not None


def safe_read_path(path: str) -> str:
    """Ścieżka do odczytu: pod `/sdcard/`, bez `..`, bez nowej linii."""
    return safe_target(path)


def _tmp_path(path: str) -> str:
    safe_target(path)
    if not is_tmp_name(PurePosixPath(path).name):
        raise UnsafeCommand(f"To nie nasz plik tymczasowy: {path[:120]!r}")
    return path


def _digits(value: str, what: str) -> int:
    if not value.isascii() or not value.isdigit():
        raise UnsafeCommand(f"Niepoprawna liczba w {what}: {value[:40]!r}")
    return int(value)


def assert_explorer(cmd: str) -> None:
    """Rzuca UnsafeCommand, jeśli polecenie nie jest jednym z dozwolonych poleceń eksploratora."""
    if cmd.endswith(STAT_TAIL):
        rest = cmd[: -len(STAT_TAIL)]
        if not rest.startswith("stat "):
            raise UnsafeCommand(f"Przyrostek dozwolony tylko po 'stat': {cmd[:120]}")
        cmd = rest
    elif cmd.endswith(CONTENT_TAIL):
        rest = cmd[: -len(CONTENT_TAIL)]
        if not rest.startswith(("ls ", "content query ")):
            raise UnsafeCommand(f"Przyrostek dozwolony tylko po 'ls' i 'content query': {cmd[:120]}")
        cmd = rest
    view = _unquoted_view(cmd)
    # `str.split()` i `shlex.split` inaczej tną słowa (NBSP, \x0b,  …) — poza apostrofami tylko zwykła spacja.
    if any(ch.isspace() and ch != " " for ch in view):
        raise UnsafeCommand(f"Niedozwolony biały znak poza cudzysłowem: {cmd[:120]!r}")
    words = view.split()
    if not words or words[0] not in _ALLOWED_CMDS:
        raise UnsafeCommand(f"Polecenie spoza allowlisty: {cmd[:120]}")
    try:
        t = shlex.split(cmd)
    except ValueError:
        raise UnsafeCommand(f"Nieczytelne polecenie: {cmd[:120]}") from None
    bad = UnsafeCommand(f"Niedozwolona postać polecenia: {cmd[:120]}")
    if not t or t[0] != words[0]:
        raise bad
    name = t[0]

    if name == "find":
        if len(t) == 4 and t[2:] == ["-type", "f"]:  # zliczanie plików miejsca
            safe_read_path(t[1])
        elif len(t) == 10 and t[2:] == ["-type", "f", "-exec", "stat", "-c", "%s", "{}", "+"]:  # sumowanie rozmiarów
            safe_read_path(t[1])
        elif (len(t) != 12 or t[2:] != ["-mindepth", "1", "-maxdepth", "1", "-exec", "stat", "-c",
                                      _STAT_FORMAT, "{}", "+"]):
            raise bad
        else:
            safe_read_path(t[1])
    elif name == "stat":
        if len(t) < 4 or t[1] != "-c" or t[2] != _STAT_FORMAT:
            raise bad
        for p in t[3:]:
            safe_read_path(p)
    elif name == "sha256sum":
        if len(t) != 2:
            raise bad
        safe_read_path(t[1])
    elif name == "df":
        if t != ["df", "-k", "/sdcard"]:
            raise bad
    elif name == "ls":
        if len(t) != 2:
            raise bad
        safe_read_path(t[1])
    elif name == "head":
        if len(t) != 4 or t[1] != "-c" or _digits(t[2], "head") > HEAD_LIMIT:
            raise bad
        safe_read_path(t[3])
    elif name == "tail":
        if len(t) != 4 or t[1] != "-c" or not t[2].startswith("+"):
            raise bad
        _digits(t[2][1:], "tail")
        safe_read_path(t[3])
    elif name == "dd":
        _assert_dd(t, bad)
    elif name == "getprop":
        if len(t) != 2 or not re.fullmatch(r"[A-Za-z0-9._-]+", t[1]):
            raise bad
    elif name == "content":
        _assert_content(t, bad)
    elif name == "mkdir":
        if len(t) < 3 or t[1] != "-p":
            raise bad
        for p in t[2:]:
            safe_target(p)
    elif name == "mv":
        if len(t) != 4 or t[1] != "-n":
            raise bad
        src, dst = _tmp_path(t[2]), safe_target(t[3])
        if PurePosixPath(src).parent != PurePosixPath(dst).parent:
            raise UnsafeCommand(f"mv tylko w obrębie jednego folderu: {cmd[:120]}")
    elif name == "rm":
        if len(t) != 3 or t[1] != "-f":
            raise bad
        _tmp_path(t[2])
    else:
        raise bad


def _assert_dd(t: list[str], bad: UnsafeCommand) -> None:
    if len(t) not in (5, 6) or not t[1].startswith("if=") or t[2] != f"bs={STREAM_BLOCK}" \
            or not t[3].startswith("skip=") or t[4] != "status=none":
        raise bad
    safe_read_path(t[1][3:])
    _digits(t[3][5:], "dd skip")
    if len(t) == 6:
        if not t[5].startswith("count="):
            raise bad
        _digits(t[5][6:], "dd count")


def _assert_content(t: list[str], bad: UnsafeCommand) -> None:
    if t[:2] == ["content", "query"]:
        return
    if t == _SCAN_VOLUME:
        return
    if len(t) == len(_SCAN_FILE_PREFIX) + 1 and t[:-1] == _SCAN_FILE_PREFIX:
        arg = t[-1]
        if (not arg.startswith("/storage/emulated/0/") or "\n" in arg or "\r" in arg
                or ".." in PurePosixPath(arg).parts):
            raise bad
        return
    raise bad


def stream_args(path: str, offset: int) -> list[str]:
    """Argumenty `exec-out` czytające plik od bloku `offset // STREAM_BLOCK`.

    `dd` szybko skacze do bloku (`tail -c +N` czyta cały plik od początku); wywołujący odrzuca
    pierwsze `offset % STREAM_BLOCK` bajtów strumienia. `status=none` — statystyki `dd` nie mogą wyciec do danych."""
    if offset < 0:
        raise UnsafeCommand("Ujemne przesunięcie")
    cmd = f"dd if={q(safe_read_path(path))} bs={STREAM_BLOCK} skip={offset // STREAM_BLOCK} status=none"
    assert_explorer(cmd)
    return ["exec-out", cmd]


class ExplorerAdb:
    """`AdbTransport` eksploratora: tylko polecenia z `assert_explorer`, `get-state`, `pull` spod `/sdcard/`
    i `push` wyłącznie do pliku tymczasowego `.admenot-<12 hex>.part` pod `/sdcard/`."""

    def __init__(self, inner: AdbTransport) -> None:
        self.inner = inner

    @property
    def serial(self) -> str | None:
        return self.inner.serial

    def with_serial(self, serial: str) -> ExplorerAdb:
        return ExplorerAdb(self.inner.with_serial(serial))

    def stream_args(self, path: str, offset: int) -> list[str]:
        return stream_args(path, offset)

    def shell(self, command: str, timeout: float = 20.0) -> str:
        assert_explorer(command)
        return self.inner.shell(command, timeout=timeout)

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        if len(args) == 3 and args[0] == "shell" and args[1] == "-T":
            assert_explorer(args[2])
        elif args == ["get-state"]:
            pass
        elif len(args) == 3 and args[0] == "pull":
            safe_read_path(args[1])
        elif len(args) == 3 and args[0] == "push":
            _tmp_path(args[2])
        else:
            raise UnsafeCommand(f"Polecenie hosta spoza allowlisty: {' '.join(args)[:120]}")
        return self.inner.run(args, timeout=timeout)

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        if len(args) != 2 or args[0] != "exec-out" or args[1].split(" ", 1)[0] not in ("dd", "head", "tail"):
            raise UnsafeCommand(f"Odczyt binarny spoza allowlisty: {' '.join(args)[:120]}")
        assert_explorer(args[1])
        return self.inner.run_bytes(args, timeout=timeout)


class ExplorerPusher:
    """`Pusher` eksploratora: `push` jednego pliku wyłącznie do naszego pliku tymczasowego
    `.admenot-<12 hex>.part` pod `/sdcard/` (jak `ExplorerAdb.run(["push", …])`); inny cel — `UnsafeCommand`
    przed uruchomieniem `adb`. Reszta (log bez nazw, przerywanie) — w `inner` (np. `RealPusher`)."""

    def __init__(self, inner: Pusher) -> None:
        self.inner = inner

    def push(self, locals_: list[Path], remote: str, should_stop: Callable[[], bool],
             tick: Callable[[], None]) -> PullResult:
        if len(locals_) != 1:
            raise UnsafeCommand("Eksplorator wgrywa jeden plik na raz")
        return self.inner.push(locals_, _tmp_path(remote), should_stop, tick)


def explorer_pusher(pusher: Pusher) -> ExplorerPusher:
    """Owija `pusher` strażnikiem eksploratora (bez podwójnego owijania)."""
    return pusher if isinstance(pusher, ExplorerPusher) else ExplorerPusher(pusher)
