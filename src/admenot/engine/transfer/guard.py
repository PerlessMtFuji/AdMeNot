"""Strażnik odczytu: na starym telefonie wykonujemy WYŁĄCZNIE polecenia tylko-do-odczytu.

Allowlista poleceń + odrzucanie metaznaków powłoki poza fragmentami w apostrofach.
`ReadOnlyAdb` opakowuje transport tak, że nic innego niż odczyt się nie przedostanie —
także `adb push`/`install`/`shell` bez `-T` czy `exec-out`. `ApkReadAdb` to ten sam strażnik
z jednym wyjątkiem na kopię APK jednego pakietu: `pm path <pakiet>` i `adb pull` jego plików `.apk`.
"""

from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath

from admenot.engine.adb.transport import AdbTransport

_ALLOWED_CMDS = {"getprop", "find", "stat", "content", "df", "sha256sum", "md5sum", "ls"}
_FIND_EXEC_ALLOWED = {"stat", "sha256sum", "md5sum"}
_FIND_FORBIDDEN = {"-delete", "-fprint", "-fprint0", "-fprintf", "-fls", "-ok", "-okdir", "-execdir"}
_META = set(";|&<>`$\n\r\\(){}*?[]~!#")
_MMS_PART_URI = re.compile(r"content://mms/part/[0-9]{1,18}")
_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+")


class UnsafeCommand(Exception):
    """Polecenie nie jest bezpiecznym odczytem — nie trafia na telefon."""


def _unquoted_view(cmd: str) -> str:
    """Polecenie z zawartością cudzysłowów zastąpioną przez 'Q'.

    Rzuca UnsafeCommand przy metaznakach poza cudzysłowami albo przy aktywnych znakach
    ($, `, \\) wewnątrz podwójnych cudzysłowów (shlex.quote ich nie generuje).
    '{}' (po -exec) jest dozwolone jako całe słowo.
    """
    out: list[str] = []
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c == "'":
            j = cmd.find("'", i + 1)
            if j == -1:
                raise UnsafeCommand("Niezamknięty apostrof")
            out.append("Q")
            i = j + 1
        elif c == '"':
            j = cmd.find('"', i + 1)
            if j == -1:
                raise UnsafeCommand("Niezamknięty cudzysłów")
            if any(ch in cmd[i + 1:j] for ch in "$`\\"):
                raise UnsafeCommand("Aktywne znaki w cudzysłowie")
            out.append("Q")
            i = j + 1
        else:
            out.append(c)
            i += 1
    view = "".join(out)
    if "\n" in view or "\r" in view:  # str.split() zjadłby je jako białe znaki, a sh -c uruchomiłby drugie polecenie
        raise UnsafeCommand(f"Nowa linia poza cudzysłowem: {cmd[:120]!r}")
    for word in view.split():
        if word == "{}":
            continue
        if any(ch in _META for ch in word):
            raise UnsafeCommand(f"Niedozwolone metaznaki powłoki: {cmd[:120]}")
    return view


def assert_read_only(cmd: str) -> None:
    """Rzuca UnsafeCommand, jeśli polecenie nie wygląda na bezpieczny odczyt."""
    words = _unquoted_view(cmd).split()
    if not words or words[0] not in _ALLOWED_CMDS:
        raise UnsafeCommand(f"Polecenie spoza allowlisty: {cmd[:120]}")
    if words[0] == "content":
        if len(words) >= 2 and words[1] == "read":
            # wyłącznie odczyt pojedynczego załącznika MMS
            a = shlex.split(cmd)
            if len(a) == 4 and a[2] == "--uri" and _MMS_PART_URI.fullmatch(a[3]):
                return
            raise UnsafeCommand(f"Niedozwolone 'content read': {cmd[:120]}")
        if len(words) < 2 or words[1] != "query":
            raise UnsafeCommand("Dozwolone jest wyłącznie 'content query' (i odczyt załącznika MMS)")
    if words[0] == "find":
        # Także po `shlex.split`: powłoka zdejmuje cudzysłowy, więc `'-delete'` to wciąż `-delete`.
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            raise UnsafeCommand(f"Nieczytelne polecenie find: {cmd[:120]}") from None
        for seq in (words, tokens):
            for i, w in enumerate(seq):
                if w in _FIND_FORBIDDEN:
                    raise UnsafeCommand(f"Niedozwolona akcja find: {w}")
                if w == "-exec" and (i + 1 >= len(seq) or seq[i + 1] not in _FIND_EXEC_ALLOWED):
                    raise UnsafeCommand("find -exec dozwolone tylko dla stat/sha256sum/md5sum")


def q(path: str) -> str:
    """Cytowanie ścieżki dla powłoki urządzenia (mksh/toybox) — POSIX."""
    return shlex.quote(path)


def _shell_T_command(args: list[str]) -> str | None:
    if len(args) == 3 and args[0] == "shell" and args[1] == "-T":
        return args[2]
    return None


def _read_command(args: list[str]) -> str | None:
    """Polecenie z `shell -T <cmd>` albo `exec-out <cmd>` (binarny odczyt bez zmiany końców linii)."""
    if len(args) == 2 and args[0] == "exec-out":
        return args[1]
    return _shell_T_command(args)


class ReadOnlyAdb:
    """`AdbTransport` przepuszczający tylko odczyt: `shell`, `shell -T`, `get-state`; binarnie także `exec-out`."""

    def __init__(self, inner: AdbTransport) -> None:
        self.inner = inner

    @property
    def serial(self) -> str | None:
        return self.inner.serial

    def with_serial(self, serial: str) -> ReadOnlyAdb:
        return ReadOnlyAdb(self.inner.with_serial(serial))

    def shell(self, command: str, timeout: float = 20.0) -> str:
        assert_read_only(command)
        return self.inner.shell(command, timeout=timeout)

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        cmd = _shell_T_command(args)
        if cmd is not None:
            assert_read_only(cmd)
        elif args != ["get-state"]:
            raise UnsafeCommand(f"Polecenie hosta spoza allowlisty: {' '.join(args)[:120]}")
        return self.inner.run(args, timeout=timeout)

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        cmd = _read_command(args)
        if cmd is None:
            raise UnsafeCommand(f"Polecenie hosta spoza allowlisty: {' '.join(args)[:120]}")
        assert_read_only(cmd)
        return self.inner.run_bytes(args, timeout=timeout)


_APPEND_CMDS = {"stat", "sha256sum", "df", "ls", "getprop", "mkdir", "content"}
_SCAN_VOLUME = ["content", "call", "--uri", "content://media", "--method", "scan_volume",
                "--arg", "external_primary"]


def safe_target(remote: str) -> str:
    """Ścieżka na nowym telefonie: pod `/sdcard/`, bez `..` i bez znaku nowej linii."""
    if not remote.startswith("/sdcard/") or "\n" in remote or ".." in PurePosixPath(remote).parts:
        raise UnsafeCommand(f"Niedozwolona ścieżka docelowa: {remote[:120]!r}")
    return remote


def assert_append_only(cmd: str) -> None:
    """Rzuca UnsafeCommand, jeśli polecenie na NOWYM telefonie mogłoby coś usunąć, przenieść lub zmienić.

    Dozwolone: odczyty (`stat`, `sha256sum`, `df`, `ls`, `getprop`), `mkdir -p` pod `/sdcard/`
    i dokładnie jedno `content call` (skan mediów po wgraniu).
    """
    words = _unquoted_view(cmd).split()
    if not words or words[0] not in _APPEND_CMDS:
        raise UnsafeCommand(f"Polecenie spoza allowlisty: {cmd[:120]}")
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        raise UnsafeCommand(f"Nieczytelne polecenie: {cmd[:120]}") from None
    if words[0] == "content":
        if tokens != _SCAN_VOLUME:
            raise UnsafeCommand(f"Dozwolone jest wyłącznie skanowanie mediów: {cmd[:120]}")
    elif words[0] == "mkdir":
        if len(tokens) < 3 or tokens[1] != "-p":
            raise UnsafeCommand(f"Dozwolone jest wyłącznie 'mkdir -p': {cmd[:120]}")
        for path in tokens[2:]:
            safe_target(path)


class AppendOnlyAdb:
    """`AdbTransport` dla nowego telefonu: tylko `shell -T <polecenie dopisujące/odczytujące>` i `get-state`."""

    def __init__(self, inner: AdbTransport) -> None:
        self.inner = inner

    @property
    def serial(self) -> str | None:
        return self.inner.serial

    def with_serial(self, serial: str) -> AppendOnlyAdb:
        return AppendOnlyAdb(self.inner.with_serial(serial))

    def shell(self, command: str, timeout: float = 20.0) -> str:
        assert_append_only(command)
        return self.inner.shell(command, timeout=timeout)

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        cmd = _shell_T_command(args)
        if cmd is not None:
            assert_append_only(cmd)
        elif args != ["get-state"]:
            raise UnsafeCommand(f"Polecenie hosta spoza allowlisty: {' '.join(args)[:120]}")
        return self.inner.run(args, timeout=timeout)

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        cmd = _shell_T_command(args)
        if cmd is None:
            raise UnsafeCommand(f"Polecenie hosta spoza allowlisty: {' '.join(args)[:120]}")
        assert_append_only(cmd)
        return self.inner.run_bytes(args, timeout=timeout)


class ApkReadAdb:
    """`ReadOnlyAdb` + dokładnie to, czego potrzebuje `backup_apks` dla jednego pakietu:
    `pm path <pakiet>` (odczyt ścieżek) i `pull <ścieżka bezwzględna .apk> <plik lokalny>`."""

    def __init__(self, inner: AdbTransport, package: str) -> None:
        if not _PACKAGE.fullmatch(package):
            raise UnsafeCommand(f"Niepoprawna nazwa pakietu: {package[:120]}")
        self.inner = inner
        self.ro = ReadOnlyAdb(inner)
        self.package = package

    @property
    def serial(self) -> str | None:
        return self.inner.serial

    def with_serial(self, serial: str) -> ApkReadAdb:
        return ApkReadAdb(self.inner.with_serial(serial), self.package)

    def shell(self, command: str, timeout: float = 20.0) -> str:
        if command == f"pm path {self.package}":
            return self.inner.shell(command, timeout=timeout)
        return self.ro.shell(command, timeout=timeout)

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        if len(args) == 3 and args[0] == "pull":
            remote = PurePosixPath(args[1])
            if remote.is_absolute() and remote.suffix == ".apk" and ".." not in remote.parts:
                return self.inner.run(args, timeout=timeout)
            raise UnsafeCommand(f"Niedozwolone pobranie: {args[1][:120]}")
        return self.ro.run(args, timeout=timeout)

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        return self.ro.run_bytes(args, timeout=timeout)
