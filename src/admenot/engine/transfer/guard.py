"""Strażnik odczytu: na starym telefonie wykonujemy WYŁĄCZNIE polecenia tylko-do-odczytu.

Allowlista poleceń + odrzucanie metaznaków powłoki poza fragmentami w apostrofach.
`ReadOnlyAdb` opakowuje transport tak, że nic innego niż odczyt się nie przedostanie —
także `adb push`/`install`/`shell` bez `-T` czy `exec-out`. `ApkReadAdb` to ten sam strażnik
z jednym wyjątkiem na kopię APK jednego pakietu: `pm path <pakiet>` i `adb pull` jego plików `.apk`.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from pathlib import PurePosixPath

from admenot.engine.adb.transport import AdbTransport

_ALLOWED_CMDS = {"getprop", "find", "stat", "content", "df", "sha256sum", "md5sum", "ls", "head"}
HEAD_LIMIT = 65536  # największy odczyt `head -c` (nagłówek pliku eksportu)
_FIND_EXEC_ALLOWED = {"stat", "sha256sum", "md5sum"}
_FIND_FORBIDDEN = {"-delete", "-fprint", "-fprint0", "-fprintf", "-fls", "-ok", "-okdir", "-execdir"}
_META = set(";|&<>`$\n\r\\(){}*?[]~!#")
_MMS_PART_URI = re.compile(r"content://mms/part/[0-9]{1,18}")
_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+")
# Błąd providera (np. odmowa na Xiaomi) `content query` pisze na stderr z kodem 0 — bez tego
# przyrostka adb zwraca pusty stdout, który wyglądał jak „0 kontaktów”.
CONTENT_TAIL = " 2>&1"


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
    """Rzuca UnsafeCommand, jeśli polecenie nie wygląda na bezpieczny odczyt.

    Jedyny dozwolony operator powłoki to stały przyrostek `CONTENT_TAIL` po `content query`."""
    if cmd.endswith(CONTENT_TAIL):
        rest = cmd[: -len(CONTENT_TAIL)]
        if not rest.startswith("content query "):
            raise UnsafeCommand(f"Przyrostek dozwolony tylko po 'content query': {cmd[:120]}")
        cmd = rest
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
    if words[0] == "head":
        # Wyłącznie początek jednego pliku pod /sdcard/ w postaci kanonicznej (nagłówek pliku eksportu).
        try:
            a = shlex.split(cmd)
        except ValueError:
            raise UnsafeCommand(f"Nieczytelne polecenie head: {cmd[:120]}") from None
        if (len(a) != 4 or a[1] != "-c" or not a[2].isascii() or not a[2].isdigit()
                or int(a[2]) > HEAD_LIMIT):
            raise UnsafeCommand(f"Dozwolone jest wyłącznie 'head -c N <plik>': {cmd[:120]}")
        safe_target(a[3])
        if cmd != f"head -c {a[2]} {q(a[3])}":
            raise UnsafeCommand(f"Niekanoniczna postać head: {cmd[:120]}")
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


ACCOUNTS_CMD = "dumpsys account"


class TelPlanReadAdb(ReadOnlyAdb):
    """`ReadOnlyAdb` + dokładnie `dumpsys account` przez `shell` — odczyt kont nowego telefonu dla planu
    telefonii (`telplan.build_tel_plan`: kontakty z konta, które się zsynchronizuje, są pomijane)."""

    def with_serial(self, serial: str) -> TelPlanReadAdb:
        return TelPlanReadAdb(self.inner.with_serial(serial))

    def shell(self, command: str, timeout: float = 20.0) -> str:
        if command == ACCOUNTS_CMD:
            return self.inner.shell(command, timeout=timeout)
        return super().shell(command, timeout=timeout)


_APPEND_CMDS = {"stat", "sha256sum", "df", "ls", "getprop", "mkdir", "content"}
STAT_TAIL = " 2>&1 || true"  # błędy `stat` na stdout, zawsze kod 0 (adb gubi stdout przy kodzie ≠ 0)
_SCAN_VOLUME = ["content", "call", "--uri", "content://media", "--method", "scan_volume",
                "--arg", "external_primary"]
SCAN_VOLUME_CMD = " ".join(_SCAN_VOLUME)  # skan mediów po wgraniu (Android 10+)


def safe_target(remote: str) -> str:
    """Ścieżka na nowym telefonie: pod `/sdcard/`, bez `..` i bez znaku nowej linii."""
    if not remote.startswith("/sdcard/") or "\n" in remote or ".." in PurePosixPath(remote).parts:
        raise UnsafeCommand(f"Niedozwolona ścieżka docelowa: {remote[:120]!r}")
    return remote


def assert_append_only(cmd: str) -> None:
    """Rzuca UnsafeCommand, jeśli polecenie na NOWYM telefonie mogłoby coś usunąć, przenieść lub zmienić.

    Dozwolone: odczyty (`stat`, `sha256sum`, `df`, `ls`, `getprop`), `mkdir -p` pod `/sdcard/`
    i dokładnie jedno `content call` (skan mediów po wgraniu). Jedyny dozwolony operator powłoki to
    stały przyrostek `STAT_TAIL` po `stat` (wynik z liniami błędów i kod 0 — `stat` paczkami w planie).
    """
    if cmd.endswith(STAT_TAIL):
        rest = cmd[: -len(STAT_TAIL)]
        if not rest.startswith("stat "):
            raise UnsafeCommand(f"Przyrostek dozwolony tylko po 'stat': {cmd[:120]}")
        _assert_append_only_plain(rest)
        return
    _assert_append_only_plain(cmd)


def _assert_append_only_plain(cmd: str) -> None:
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


# --------------------------------------------------------------------------------------
# Zapis telefonii (kontakty, SMS, MMS, połączenia) przez pomocnika na nowym telefonie
# --------------------------------------------------------------------------------------
_HELPER_PATH = re.compile(r"[A-Za-z0-9._/-]+")  # nazwy wejścia są ASCII, więc bez cytowania
SMS_ROLE = "android.app.role.SMS"
_APPOP_MODES = ("allow", "default", "ignore", "deny", "foreground")
_HELPER_PERMISSIONS = ("READ_CONTACTS", "WRITE_CONTACTS", "READ_CALL_LOG", "WRITE_CALL_LOG", "READ_SMS")


def safe_helper_target(remote: str) -> str:
    """Cel wgrania pomocnika: pod `/data/local/tmp/admenot/` albo `COMPANION_IN/`, bez `..` i nowej linii."""
    from admenot.engine.transfer import (
        helper,  # późny import: helper importuje pusher, a ten ten moduł
    )

    ok = remote.startswith((f"{helper.HELPER_DIR}/", f"{helper.COMPANION_IN}/"))
    if not ok or "\n" in remote or "\r" in remote or ".." in PurePosixPath(remote).parts:
        raise UnsafeCommand(f"Niedozwolona ścieżka docelowa: {remote[:120]!r}")
    return remote


def safe_push_target(remote: str) -> str:
    """Cel `adb push`: `/sdcard/` (pliki) albo katalog pomocnika."""
    try:
        return safe_target(remote)
    except UnsafeCommand:
        return safe_helper_target(remote)


def _helper_input(path: str, base: str) -> str:
    if (not _HELPER_PATH.fullmatch(path) or not path.startswith(f"{base}/") or path.endswith("/")
            or ".." in PurePosixPath(path).parts):
        raise UnsafeCommand(f"Niedozwolona ścieżka wejścia: {path[:120]!r}")
    return path


def _account_args_ok(*values: str) -> None:
    if any(not v or "\n" in v or "\r" in v or "\0" in v for v in values):
        raise UnsafeCommand("Niepoprawne dane konta")


def _fixed_commands(helper) -> frozenset[str]:
    d, p = helper.HELPER_DIR, helper.PACKAGE
    out = {
        f"mkdir -p {helper.HELPER_IN}", f"rm -rf {helper.HELPER_IN}", f"rm -rf {d}",
        f"mkdir -p {helper.COMPANION_IN}",
        f"sha256sum {helper.DEX_REMOTE}",
        "appops get com.android.shell WRITE_SMS",
        f"pm list packages {p}", f"pm uninstall {p}",
        "dumpsys role", "dumpsys account",
        f"cmd role remove-role-holder {SMS_ROLE} {p}",
        f"am start -n {p}/.RoleActivity",
        "am start -a android.settings.MANAGE_DEFAULT_APPS_SETTINGS",
    }
    out |= {f"appops set com.android.shell WRITE_SMS {m}" for m in _APPOP_MODES}
    out |= {f"pm grant {p} android.permission.{perm}" for perm in _HELPER_PERMISSIONS}
    return frozenset(out)


def assert_telephony_write(cmd: str, role_restore: Callable[[], frozenset[str]]) -> None:
    """Rzuca UnsafeCommand, jeśli polecenie nie jest jednym z dokładnych kroków zapisu telefonii.

    Przepuszcza to, co `assert_append_only`, oraz allowlistę z `TelephonyWriteAdb`. Każda forma jest
    porównywana z postacią kanoniczną (jak `head`), więc nic poza nią nie przejdzie."""
    from admenot.engine.transfer import helper

    try:
        assert_append_only(cmd)
        return
    except UnsafeCommand:
        pass
    _unquoted_view(cmd)  # metaznaki poza cudzysłowami
    bad = UnsafeCommand(f"Polecenie spoza allowlisty zapisu telefonii: {cmd[:120]}")
    if cmd in _fixed_commands(helper):
        return
    try:
        t = shlex.split(cmd)
    except ValueError:
        raise UnsafeCommand(f"Nieczytelne polecenie: {cmd[:120]}") from None
    pkg = helper.PACKAGE

    if t[:5] == [f"CLASSPATH={helper.DEX_REMOTE}", "app_process", "/", helper.MAIN_CLASS, "write"] \
            and len(t) in (6, 9):
        path = _helper_input(t[5], helper.HELPER_IN)
        acct = ""
        if len(t) == 9:
            _account_args_ok(t[7], t[8])
            acct = f" --account {q(t[7])} {q(t[8])}"
        if t[6:7] in ([], ["--account"]) and cmd == (
                f"CLASSPATH={helper.DEX_REMOTE} app_process / {helper.MAIN_CLASS} write {path}{acct}"):
            return
        raise bad

    if t[:3] == ["cmd", "role", "add-role-holder"]:
        if (len(t) == 5 and t[3] == SMS_ROLE and _PACKAGE.fullmatch(t[4])
                and (t[4] == pkg or t[4] in role_restore())
                and cmd == f"cmd role add-role-holder {SMS_ROLE} {t[4]}"):
            return
        raise UnsafeCommand(f"Rola SMS tylko dla pomocnika albo zapisanego posiadacza: {cmd[:120]}")

    if t[:9] == ["am", "instrument", "-w", "-r", "-e", "cmd", "write", "-e", "input"] and len(t) in (11, 17):
        path = _helper_input(t[9], helper.COMPANION_IN)
        acct = ""
        if len(t) == 17:
            _account_args_ok(t[12], t[15])
            if (t[10], t[11], t[13], t[14]) != ("-e", "account_type", "-e", "account_name"):
                raise bad
            acct = f" -e account_type {q(t[12])} -e account_name {q(t[15])}"
        if t[-1] == helper.RUNNER and cmd == (
                f"am instrument -w -r -e cmd write -e input {path}{acct} {helper.RUNNER}"):
            return
        raise bad

    raise bad


class TelephonyWriteAdb:
    """`AppendOnlyAdb` + wąska allowlista kroków zapisu kontaktów i wiadomości (pomocnik na telefonie).

    `role_restore` zwraca pakiety zapisane jako poprzedni posiadacz roli SMS — tylko im wolno ją oddać."""

    def __init__(self, inner: AdbTransport, role_restore: Callable[[], frozenset[str]]) -> None:
        self.inner = inner
        self.role_restore = role_restore

    @property
    def serial(self) -> str | None:
        return self.inner.serial

    def with_serial(self, serial: str) -> TelephonyWriteAdb:
        return TelephonyWriteAdb(self.inner.with_serial(serial), self.role_restore)

    def shell(self, command: str, timeout: float = 20.0) -> str:
        assert_telephony_write(command, self.role_restore)
        return self.inner.shell(command, timeout=timeout)

    def _check_run(self, args: list[str]) -> None:
        cmd = _shell_T_command(args)
        if cmd is not None:
            assert_telephony_write(cmd, self.role_restore)
        elif args == ["get-state"]:
            return
        elif len(args) == 3 and args[:2] == ["install", "-g"]:
            from admenot.engine.transfer import helper

            try:
                apk = str(helper.artifact("apk")[0])
            except helper.HelperBroken as exc:
                raise UnsafeCommand(f"Artefakt APK pomocnika niepoprawny: {exc}") from None
            if args[2] != apk:
                raise UnsafeCommand(f"Instalacja dozwolona tylko dla APK pomocnika: {args[2][:120]}")
        else:
            raise UnsafeCommand(f"Polecenie hosta spoza allowlisty: {' '.join(args)[:120]}")

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        self._check_run(args)
        return self.inner.run(args, timeout=timeout)

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        if _shell_T_command(args) is None:
            raise UnsafeCommand(f"Polecenie hosta spoza allowlisty: {' '.join(args)[:120]}")
        self._check_run(args)
        return self.inner.run_bytes(args, timeout=timeout)
