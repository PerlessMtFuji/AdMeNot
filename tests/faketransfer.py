"""FakeStoragePhone — stary telefon z katalogu, do testów kopii danych (Etap 1).

Emuluje z katalogu `root` (wzór: skrypt `adb-backup/tests/fake_adb.py`):
* pamięć: `root/sdcard/…` = `/sdcard/…` (`find … -exec stat`, `stat`, `df -k`, `sha256sum`),
* providery: `content query --uri U` zwraca treść pliku `root/providers/<nazwa>.txt`, gdzie nazwa to
  URI z `://` i `/` zamienionymi na `_` (patrz `provider_file`); treść jest gotowym wyjściem
  `content query` (`Row: 0 _id=1, …`),
* załączniki MMS: `content read --uri content://mms/part/N` -> bajty z `root/mms_parts/N`,
* `adb pull` (jako `Puller`): kopiuje z `root/sdcard`, zachowując czas modyfikacji,
* aplikacje (`apps`: pakiet -> {nazwa APK: bajty}): `pm path`, `sha256sum` i `adb pull` pliku APK
  pod `APK_DIR` — tyle, ile potrzebuje `backup_apks`.

Haki testowe: `before_pull(remotes)` wołane na początku każdego `pull` (np. zmiana albo usunięcie
pliku w trakcie kopii), `pull_calls` = liczba wywołań `pull`, `on_shell(command)` wołane przed
każdym poleceniem shell (może rzucić `AdbError`, np. przekroczenie czasu `stat`).

Awarie: `fail_after_files` (po tylu pobranych plikach pull urywa się w środku pliku, a telefon
przechodzi w stan `offline` do `reconnect()`), `deny_uris` (odmowa dostępu do providera),
`online` / `get_state()` (`"device"` / `"offline"`).

Nowy telefon (Etap 2, wgrywanie): `push(locals_, remote, …)` (jako `Pusher`) kopiuje do `root/sdcard`,
zachowując czas modyfikacji; katalog docelowy musi istnieć po `mkdir -p`. `content call … scan_volume`
zlicza `scans`; `push_calls` = liczba wywołań `push`; `pushed` = zdalne ścieżki wgranych plików.
Awarie: `deny_prefixes` (push pod taką ścieżkę -> `adb: error: … Permission denied`, rc 1),
`mkdir -p` nowego katalogu pod takim prefiksem -> `AdbError` z `mkdir: '<ścieżka>': Permission denied`,
`fail_after_push_files` (po tylu wgranych plikach następny jest urwany w połowie, a telefon przechodzi
w `offline` do `reconnect()`; licznik liczy pliki ŁĄCZNIE z wielu wywołań i nie zeruje się sam —
test po `reconnect()` ustawia `fail_after_push_files = None`; pozostałe równoległe `push` dostają rc 1
i nic już nie zapisują), `push` sprawdza `safe_target(remote)` jak `RealPusher`, `free_kb` (None = domyślne 70 000 000, bez zmian przy push; liczba =
zmniejszana o rozmiar wgranych plików, zwracana przez `df -k`). `stat … STAT_TAIL` daje linię błędu na
plik (`stat: '<ścieżka>': No such file or directory`) i kod 0 zamiast `AdbError`; `deny_stat_prefixes` —
`stat` takich ścieżek kończy się `Permission denied`.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shlex
import threading
from collections.abc import Callable
from pathlib import Path

from admenot.engine.adb.transport import AdbError
from admenot.engine.transfer.guard import STAT_TAIL, safe_target
from admenot.engine.transfer.puller import PullResult

_MMS_PREFIX = "content://mms/part/"
DEFAULT_FREE_KB = 70_000_000
APK_DIR = "/data/app/~~fake==/{package}-1"


def provider_file(root: Path, uri: str) -> Path:
    """Plik z gotowym wyjściem `content query` dla danego URI."""
    return root / "providers" / (uri.replace("://", "_").replace("/", "_") + ".txt")


def write_provider(root: Path, uri: str, rows: list[dict[str, str | None]], cols: list[str]) -> None:
    """Zapisuje wyjście `content query` dla `uri` w postaci, w jakiej zwraca je telefon."""
    path = provider_file(root, uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"Row: {i} " + ", ".join(f"{c}={'NULL' if r.get(c) is None else r[c]}" for c in cols)
             for i, r in enumerate(rows)]
    text = "\n".join(lines) + "\n" if lines else "No result found.\n"
    path.write_text(text, encoding="utf-8", newline="")


class FakeStoragePhone:
    def __init__(self, root: Path, serial: str = "FAKE") -> None:
        self.root = root
        self.serial: str | None = serial
        self.fail_after_files: int | None = None
        self.deny_uris: set[str] = set()
        self.online = True
        self.total_kb = 120_000_000
        self.free_kb: int | None = None
        self.deny_prefixes: set[str] = set()
        self.deny_stat_prefixes: set[str] = set()
        self.fail_after_push_files: int | None = None
        self.push_calls = 0
        self.pushed: list[str] = []
        self.scans = 0
        self._push_lock = threading.Lock()
        self.commands: list[str] = []  # polecenia shell w kolejności wywołań
        self.pulled: list[str] = []  # zdalne ścieżki plików pobranych `pull`
        self.pull_calls = 0
        self.before_pull: Callable[[list[str]], None] | None = None
        self.on_shell: Callable[[str], None] | None = None
        self.apps: dict[str, dict[str, bytes]] = {}

    # ---- stan ---------------------------------------------------------------------------
    def get_state(self) -> str:
        return "device" if self.online else "offline"

    def reconnect(self) -> None:
        self.online = True

    def local(self, remote: str) -> Path:
        assert remote == "/sdcard" or remote.startswith("/sdcard/"), remote
        return self.root / "sdcard" / remote[len("/sdcard"):].lstrip("/")

    # ---- AdbTransport -------------------------------------------------------------------
    def with_serial(self, serial: str) -> FakeStoragePhone:
        self.serial = serial
        return self

    def shell(self, command: str, timeout: float = 20.0) -> str:
        return self._shell(command).decode("utf-8")

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        if args == ["get-state"]:
            if not self.online:
                raise AdbError("offline", "device offline")
            return "device\n"
        if len(args) == 3 and args[:2] == ["shell", "-T"]:
            return self._shell(args[2]).decode("utf-8")
        if len(args) == 3 and args[0] == "pull":
            return self._pull_apk(args[1], Path(args[2]))
        raise AdbError("command_failed", f"fake: unsupported {args}")

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        if len(args) == 3 and args[:2] == ["shell", "-T"]:
            return self._shell(args[2])
        if len(args) == 2 and args[0] == "exec-out":
            return self._shell(args[1])
        raise AdbError("command_failed", f"fake: unsupported {args}")

    # ---- polecenia shell ----------------------------------------------------------------
    def _shell(self, command: str) -> bytes:
        if not self.online:
            raise AdbError("offline", "device offline")
        self.commands.append(command)
        if self.on_shell is not None:
            self.on_shell(command)
        if command.endswith(STAT_TAIL):  # `stat … 2>&1 || true`: błędy jako linie wyniku, kod 0
            argv = shlex.split(command[: -len(STAT_TAIL)])
            assert argv[0] == "stat", argv
            return self._stat(argv[1:], tolerant=True)
        argv = shlex.split(command)
        if argv[:2] == ["pm", "path"] and len(argv) == 3:
            return self._pm_path(argv[2])
        handler = {"find": self._find, "stat": self._stat, "df": self._df,
                   "sha256sum": self._sha256, "content": self._content, "ls": self._ls,
                   "mkdir": self._mkdir}.get(argv[0])
        if handler is None:
            raise AdbError("command_failed", f"{argv[0]}: inaccessible or not found")
        return handler(argv[1:])

    def _find(self, args: list[str]) -> bytes:
        i = 0
        while args[i] in ("-H", "-L"):
            i += 1
        roots: list[str] = []
        while i < len(args) and not args[i].startswith("-"):
            roots.append(args[i])
            i += 1
        expr = args[i:]
        prune_paths: set[str] = set()
        prune_names: set[str] = set()
        j = 0
        maxdepth: int | None = None
        if expr[:1] == ["-maxdepth"]:
            maxdepth = int(expr[1])
            j = 2
        match_name: str | None = None
        while j < len(expr) and expr[j] in ("-path", "-name"):
            if expr[j] == "-name" and expr[j + 2] == "-type":  # filtr nazwy, bez -prune
                match_name = expr[j + 1]
                j += 2
                break
            (prune_paths if expr[j] == "-path" else prune_names).add(expr[j + 1])
            j += 4  # -path X -prune -o
        assert expr[j:j + 6] == ["-type", "f", "-exec", "stat", "-c", "%s|%Y|%n"], expr[j:]
        out: list[str] = []
        for remote in roots:
            base = self.local(remote)
            if not base.is_dir():
                raise AdbError("command_failed", f"find: {remote}: No such file or directory")
            for dirpath, dirnames, filenames in os.walk(base):
                rel = os.path.relpath(dirpath, base).replace(os.sep, "/")
                rdir = remote if rel == "." else f"{remote.rstrip('/')}/{rel}"
                if maxdepth is not None and (0 if rel == "." else rel.count("/") + 1) + 1 >= maxdepth:
                    dirnames[:] = []
                dirnames[:] = [d for d in dirnames
                               if d not in prune_names and f"{rdir}/{d}" not in prune_paths]
                for name in filenames:
                    if name in prune_names or (match_name and not fnmatch.fnmatchcase(name, match_name)):
                        continue
                    st = os.stat(os.path.join(dirpath, name))
                    out.append(f"{st.st_size}|{int(st.st_mtime)}|{rdir}/{name}")
        return ("\n".join(sorted(out)) + "\n").encode("utf-8") if out else b""

    def _ls(self, args: list[str]) -> bytes:
        assert args[0] == "-1" and len(args) == 2, args
        base = self.local(args[1])
        if not base.is_dir():
            raise AdbError("command_failed", f"ls: {args[1]}: No such file or directory")
        return "".join(f"{p.name}\n" for p in sorted(base.iterdir())).encode("utf-8")

    def _stat(self, args: list[str], tolerant: bool = False) -> bytes:
        """Jak toybox + `adb shell`: błąd = kod 1 (`AdbError`, wynik ginie), chyba że `tolerant`
        (przyrostek `STAT_TAIL`) — wtedy linia błędu na każdy plik i dalej."""
        assert args[0] == "-c" and args[1] == "%s|%Y|%n", args
        out: list[str] = []
        for remote in args[2:]:
            path = self.local(remote)
            error = None
            if any(remote.startswith(p) for p in self.deny_stat_prefixes):
                error = f"stat: '{remote}': Permission denied"
            elif not path.exists():
                error = f"stat: '{remote}': No such file or directory"
            if error is not None:
                if not tolerant:
                    raise AdbError("command_failed", error)
                out.append(error)
                continue
            st = path.stat()
            out.append(f"{st.st_size}|{int(st.st_mtime)}|{remote}")
        return ("\n".join(out) + "\n").encode("utf-8")

    def _df(self, args: list[str]) -> bytes:
        free = DEFAULT_FREE_KB if self.free_kb is None else self.free_kb
        used = self.total_kb - free
        pct = round(100 * used / self.total_kb)
        return (f"Filesystem 1K-blocks Used Available Use% Mounted on\n"
                f"/dev/fuse {self.total_kb} {used} {free} {pct}% /storage/emulated\n"
                ).encode()

    def _sha256(self, args: list[str]) -> bytes:
        lines = []
        for remote in args:
            if (apk := self._apk(remote)) is not None:
                lines.append(f"{hashlib.sha256(apk).hexdigest()}  {remote}")
                continue
            path = self.local(remote)
            if not path.is_file():
                raise AdbError("command_failed", f"sha256sum: {remote}: No such file or directory")
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {remote}")
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _mkdir(self, args: list[str]) -> bytes:
        """Jak toybox: odmowa przy jednym katalogu nie zatrzymuje pozostałych; kod 1 na końcu. Pod
        `deny_prefixes` katalogu, którego jeszcze nie ma, nie da się utworzyć (istniejący — bez błędu)."""
        assert args[0] == "-p" and len(args) >= 2, args
        errors: list[str] = []
        for remote in args[1:]:
            path = self.local(remote)
            if not path.is_dir() and any((remote + "/").startswith(p) for p in self.deny_prefixes):
                errors.append(f"mkdir: '{remote}': Permission denied")
                continue
            path.mkdir(parents=True, exist_ok=True)
        if errors:
            raise AdbError("command_failed", "\n".join(errors))
        return b""

    def _content(self, args: list[str]) -> bytes:
        if args[0] == "call":
            assert args[1:] == ["--uri", "content://media", "--method", "scan_volume",
                                "--arg", "external_primary"], args
            self.scans += 1
            return b"Result: Bundle[{}]\n"
        if args[0] == "query":
            uri = args[args.index("--uri") + 1]
            if uri in self.deny_uris:
                raise AdbError("command_failed", f"Error while accessing provider:{uri}\n"
                                                 "java.lang.SecurityException: Permission Denial")
            path = provider_file(self.root, uri)
            if not path.is_file():
                raise AdbError("command_failed", f"Error while accessing provider:{uri}\n"
                                                 "java.lang.IllegalArgumentException: Unknown URL")
            return path.read_bytes()
        assert args[:2] == ["read", "--uri"] and args[2].startswith(_MMS_PREFIX), args
        part = self.root / "mms_parts" / args[2][len(_MMS_PREFIX):]
        if not part.is_file():
            raise AdbError("command_failed", f"Error while accessing provider:mms\n"
                                             f"java.io.FileNotFoundException: No entry for {args[2]}")
        return part.read_bytes()

    # ---- aplikacje ------------------------------------------------------------------------
    def _apk(self, remote: str) -> bytes | None:
        for package, files in self.apps.items():
            prefix = APK_DIR.format(package=package) + "/"
            if remote.startswith(prefix) and remote[len(prefix):] in files:
                return files[remote[len(prefix):]]
        return None

    def _pm_path(self, package: str) -> bytes:
        if package not in self.apps:
            raise AdbError("command_failed", f"Error: Unknown package: {package}")
        return "".join(f"package:{APK_DIR.format(package=package)}/{n}\n"
                       for n in self.apps[package]).encode("utf-8")

    def _pull_apk(self, remote: str, local: Path) -> str:
        if not self.online:
            raise AdbError("offline", "device offline")
        apk = self._apk(remote)
        if apk is None:
            raise AdbError("command_failed", f"remote object '{remote}' does not exist")
        local.write_bytes(apk)
        return f"{remote}: 1 file pulled\n"

    def has_apk(self, remote: str) -> bool:
        return self._apk(remote) is not None

    # ---- Puller ---------------------------------------------------------------------------
    def pull(self, remotes: list[str], target: Path, should_stop: Callable[[], bool],
             tick: Callable[[], None]) -> PullResult:
        self.pull_calls += 1
        if self.before_pull is not None:
            self.before_pull(remotes)
        lines: list[str] = []
        if not self.online:
            return PullResult(1, ["adb: error: device offline"], False)
        count = 0
        for remote in remotes:
            src = self.local(remote)
            if not src.exists():
                lines.append(f"adb: error: failed to stat remote object '{remote}': "
                             "No such file or directory")
                continue
            if src.is_dir():
                dest_root = target / src.name
                items = [(f, dest_root / f.relative_to(src)) for f in sorted(src.rglob("*")) if f.is_file()]
            else:
                items = [(src, target / src.name if target.is_dir() else target)]
            for file, dest in items:
                if self.fail_after_files is not None and len(self.pulled) >= self.fail_after_files:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(file.read_bytes()[: file.stat().st_size // 2])
                    self.online = False
                    lines.append("adb: error: failed to read copy response: device offline")
                    return PullResult(1, lines, False)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(file.read_bytes())
                st = file.stat()
                os.utime(dest, (st.st_atime, st.st_mtime))
                self.pulled.append("/sdcard/" + file.relative_to(self.root / "sdcard").as_posix())
                count += 1
                tick()
                if should_stop():
                    return PullResult(1, lines, True)
        lines.append(f"{count} files pulled, 0 skipped.")
        return PullResult(1 if any(x.startswith("adb: error") for x in lines) else 0, lines, False)

    # ---- Pusher ---------------------------------------------------------------------------
    def push(self, locals_: list[Path], remote: str, should_stop: Callable[[], bool],
             tick: Callable[[], None]) -> PullResult:
        safe_target(remote)
        with self._push_lock:
            self.push_calls += 1
        lines: list[str] = []
        count = 0
        offline = "adb: error: failed to copy: device offline"
        for src in locals_:
            target = remote + src.name if remote.endswith("/") else remote
            with self._push_lock:  # równoległe push-e: jedno urwanie kabla zatrzymuje wszystkie
                if not self.online:
                    return PullResult(1, [*lines, offline], False)
                if any(target.startswith(p) for p in self.deny_prefixes):
                    lines.append(f"adb: error: failed to copy '{src}' to '{target}': "
                                 "remote couldn't create file: Permission denied")
                    continue
                dest = self.local(target)
                if not dest.parent.is_dir():
                    lines.append(f"adb: error: failed to copy '{src}' to '{target}': "
                                 "remote couldn't create file: No such file or directory")
                    continue
                data = src.read_bytes()
                if self.fail_after_push_files is not None and len(self.pushed) >= self.fail_after_push_files:
                    dest.write_bytes(data[: len(data) // 2])
                    self.online = False
                    return PullResult(1, [*lines, offline], False)
                dest.write_bytes(data)
                st = src.stat()
                os.utime(dest, (st.st_atime, st.st_mtime))
                self.pushed.append(target)
                if self.free_kb is not None:
                    self.free_kb -= -(-len(data) // 1024)
            count += 1
            tick()
            if should_stop():
                return PullResult(1, lines, True)
        lines.append(f"{count} files pushed, 0 skipped.")
        return PullResult(1 if any(x.startswith("adb: error") for x in lines) else 0, lines, False)


_STORAGE_TOOLS = {"find", "stat", "ls", "df", "content", "sha256sum", "mkdir"}


class TransferPhone:
    """Telefon do testów mostu kopii: skan aplikacji z `FakePhone` (pakiety, ustawienia), pamięć,
    providery, APK i `pull` z `FakeStoragePhone`. Jest też `Puller` (puller_factory → ta atrapa)."""

    def __init__(self, cli, storage: FakeStoragePhone) -> None:
        self.cli = cli
        self.storage = storage

    @property
    def serial(self) -> str | None:
        return self.cli.serial

    def with_serial(self, serial: str) -> TransferPhone:
        self.cli.with_serial(serial)
        self.storage.with_serial(serial)
        return self

    def _storage_cmd(self, command: str) -> bool:
        argv = shlex.split(command)
        if argv[:2] == ["pm", "path"] and len(argv) == 3:
            return argv[2] in self.storage.apps
        return bool(argv) and argv[0] in _STORAGE_TOOLS

    def shell(self, command: str, timeout: float = 20.0) -> str:
        if self._storage_cmd(command):
            return self.storage.shell(command, timeout)
        return self.cli.shell(command, timeout)

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        if args == ["get-state"]:
            return self.storage.run(args, timeout)
        if len(args) == 3 and args[:2] == ["shell", "-T"] and self._storage_cmd(args[2]):
            return self.storage.run(args, timeout)
        if len(args) == 3 and args[0] == "pull" and self.storage.has_apk(args[1]):
            return self.storage.run(args, timeout)
        return self.cli.run(args, timeout)

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        cmd = args[-1] if args and args[0] in ("shell", "exec-out") else ""
        if cmd and self._storage_cmd(cmd):
            return self.storage.run_bytes(args, timeout)
        return self.cli.run_bytes(args, timeout)

    def pull(self, remotes: list[str], target: Path, should_stop: Callable[[], bool],
             tick: Callable[[], None]) -> PullResult:
        return self.storage.pull(remotes, target, should_stop, tick)

    def push(self, locals_: list[Path], remote: str, should_stop: Callable[[], bool],
             tick: Callable[[], None]) -> PullResult:
        return self.storage.push(locals_, remote, should_stop, tick)


class PhoneHost:
    """Host adb z kilkoma telefonami (stary i nowy przy wgrywaniu kopii): `with_serial` oddaje
    atrapę danego telefonu, `devices -l` listuje wszystkie podłączone (`connected`). Do
    `puller_factory`/`pusher_factory` mostu: `phone(serial)`."""

    def __init__(self, *phones: TransferPhone) -> None:
        self.phones = {p.storage.serial: p for p in phones}
        self.connected = set(self.phones)
        self.serial: str | None = None

    def phone(self, serial: str) -> TransferPhone:
        return self.phones[serial]

    def with_serial(self, serial: str) -> TransferPhone:
        return self.phones[serial].with_serial(serial)

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        if args == ["devices", "-l"]:
            lines = [f"{s}  device usb:1-{i} model:SM_A145R transport_id:{i}"
                     for i, s in enumerate(sorted(self.connected), start=1)]
            return "List of devices attached\n" + "".join(line + "\n" for line in lines) + "\n"
        raise AdbError("command_failed", f"fake host: unsupported {args}")

    def shell(self, command: str, timeout: float = 20.0) -> str:
        raise AdbError("command_failed", "fake host: shell without serial")

    def run_bytes(self, args: list[str], timeout: float = 20.0) -> bytes:
        raise AdbError("command_failed", f"fake host: unsupported {args}")
