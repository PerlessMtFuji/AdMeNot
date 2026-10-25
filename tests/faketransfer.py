"""FakeStoragePhone — stary telefon z katalogu, do testów kopii danych (Etap 1).

Emuluje z katalogu `root` (wzór: skrypt `adb-backup/tests/fake_adb.py`):
* pamięć: `root/sdcard/…` = `/sdcard/…` (`find … -exec stat`, `stat`, `df -k`, `sha256sum`),
* providery: `content query --uri U` zwraca treść pliku `root/providers/<nazwa>.txt`, gdzie nazwa to
  URI z `://` i `/` zamienionymi na `_` (patrz `provider_file`); treść jest gotowym wyjściem
  `content query` (`Row: 0 _id=1, …`),
* załączniki MMS: `content read --uri content://mms/part/N` -> bajty z `root/mms_parts/N`,
* `adb pull` (jako `Puller`): kopiuje z `root/sdcard`, zachowując czas modyfikacji.

Awarie: `fail_after_files` (po tylu pobranych plikach pull urywa się w środku pliku, a telefon
przechodzi w stan `offline` do `reconnect()`), `deny_uris` (odmowa dostępu do providera),
`online` / `get_state()` (`"device"` / `"offline"`).
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shlex
from collections.abc import Callable
from pathlib import Path

from admenot.engine.adb.transport import AdbError
from admenot.engine.transfer.puller import PullResult

_MMS_PREFIX = "content://mms/part/"


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
        self.free_kb = 70_000_000
        self.commands: list[str] = []  # polecenia shell w kolejności wywołań
        self.pulled: list[str] = []  # zdalne ścieżki plików pobranych `pull`

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
        argv = shlex.split(command)
        handler = {"find": self._find, "stat": self._stat, "df": self._df,
                   "sha256sum": self._sha256, "content": self._content, "ls": self._ls}.get(argv[0])
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

    def _stat(self, args: list[str]) -> bytes:
        assert args[0] == "-c" and args[1] == "%s|%Y|%n", args
        out: list[str] = []
        for remote in args[2:]:
            path = self.local(remote)
            if not path.exists():
                raise AdbError("command_failed", f"stat: '{remote}': No such file or directory")
            st = path.stat()
            out.append(f"{st.st_size}|{int(st.st_mtime)}|{remote}")
        return ("\n".join(out) + "\n").encode("utf-8")

    def _df(self, args: list[str]) -> bytes:
        used = self.total_kb - self.free_kb
        pct = round(100 * used / self.total_kb)
        return (f"Filesystem 1K-blocks Used Available Use% Mounted on\n"
                f"/dev/fuse {self.total_kb} {used} {self.free_kb} {pct}% /storage/emulated\n"
                ).encode()

    def _sha256(self, args: list[str]) -> bytes:
        lines = []
        for remote in args:
            path = self.local(remote)
            if not path.is_file():
                raise AdbError("command_failed", f"sha256sum: {remote}: No such file or directory")
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {remote}")
        return ("\n".join(lines) + "\n").encode("utf-8")

    def _content(self, args: list[str]) -> bytes:
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

    # ---- Puller ---------------------------------------------------------------------------
    def pull(self, remotes: list[str], target: Path, should_stop: Callable[[], bool],
             tick: Callable[[], None]) -> PullResult:
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
