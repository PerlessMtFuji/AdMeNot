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
przechodzi w stan `offline` do `reconnect()`), `deny_uris` (odmowa dostępu do providera: kod 0,
komunikat na stderr — widoczny tylko z `CONTENT_TAIL`, jak na Xiaomi bez ustawień zabezpieczeń),
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
`stat` takich ścieżek kończy się `Permission denied`. `stat_unquoted` — linie błędu bez cudzysłowów
(`stat: <ścieżka>: No such file or directory`).

Telefonia nowego telefonu (Etap 3), w pamięci:
* providery `providers["sms" | "mms" | "calls" | "contacts" | "raw_contacts" | "data"]` to listy wierszy
  (`dict` kolumna -> tekst albo `None`). `content query` ich URI (`TEL_URIS`) zwraca je w kolejności
  kolumn z `--projection` (brak kolumny = `NULL`), gdy lista jest niepusta albo `telephony = True`
  (pusty nowy telefon: „No result found.”); inaczej jak dotąd plik z `providers/` albo „Unknown URL”.
  Każdy zapis pomocnika włącza `telephony`, dopisuje wiersze i aktualizuje plik w `providers/`. Adresy MMS: `mms_addrs[_id]` dla `content://mms/<_id>/addr`.
  SMS/MMS dostają `thread_id` (jeden wątek na `phone_key` adresu), a `content://mms-sms/conversations`
  zwraca wątki; flaga `no_threads` daje `thread_id=0` i brak wątków.
* pomocnik: `CLASSPATH=<dex> app_process / … write <wejście> [--account T N]` (wymaga wgranego `.dex`)
  i `am instrument -w -r -e cmd write -e input <wejście> [-e account_type T -e account_name N] <runner>`
  (wymaga zainstalowanej aplikacji pomocniczej) czytają prawdziwe JSON Lines z `helper.encode` i
  odpowiadają protokołem: `OK <id>`, `DENIED`, `DONE <ok> <err>`; instrumentacja opakowuje linie
  w `INSTRUMENTATION_STATUS: line=…`. Odmowy: `helper_denied` (kategorie dla `app_process`;
  dodatkowo SMS/MMS przez `app_process` tylko przy `appop == "allow"`, jak OPPO), `companion_denied`
  (dla instrumentacji; SMS/MMS tylko, gdy pomocnik ma rolę SMS). Brakująca część MMS -> `ERR <id>
  missing_part`. `fail_after_records`: po tylu zapisanych rekordach (łącznie, `records_written`)
  telefon przechodzi w `offline` w środku paczki (zapisane wiersze zostają, linie wyjścia giną:
  `AdbError("offline")`).
* `appops get/set com.android.shell WRITE_SMS`: `appop` (`None` = brak wpisu: `No operations.`
  i `Default mode: <appop_default>`, bez tej linii, gdy `appop_default is None`); `appop_refused`:
  tryby, których `appops set` nie ustawia (tryb zostaje, wyjście z komunikatem o odmowie).
* rola SMS: `role_holders`, `dumpsys role` w formacie OPPO; `cmd role add-role-holder` /
  `remove-role-holder`. `role_needs_tap`: nadanie roli pomocnikowi nic nie zmienia, test „stuka”
  przez `tap_role(pkg)`; `role_restore_needs_tap`: to samo dla oddania roli innej aplikacji i zdjęcia
  jej z pomocnika. `am start` zapisuje intencję w `started`.
* aplikacje: `installed` (`pm list packages`, `pm uninstall` — odinstalowanie posiadacza roli SMS
  zostawia rolę pustą, `adb install -g <apk>` z `host_commands`; `install_blocked` -> `Failure
  [INSTALL_FAILED_USER_RESTRICTED: …]`, ponowna instalacja -> `INSTALL_FAILED_ALREADY_EXISTS`).
  Instalacja nie zakłada katalogu wejścia `helper.COMPANION_IN` (jak prawdziwy telefon: `push` do
  `.../in/` bez wcześniejszego `mkdir -p` kończy się błędem), odinstalowanie usuwa `Android/data/<pakiet>`.
* `accounts: list[(typ, nazwa)]` dla `dumpsys account`; `tmp_files`: pliki pod `/data/local/tmp/admenot`
  (lokalnie `root/data_local_tmp/admenot`, `mkdir -p`, `push`, `stat`, `sha256sum`, `rm -rf`).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import threading
from collections.abc import Callable
from pathlib import Path

from admenot.engine.adb.transport import AdbError
from admenot.engine.transfer import helper
from admenot.engine.transfer import telephony as tel
from admenot.engine.transfer.guard import CONTENT_TAIL, SMS_ROLE, STAT_TAIL, safe_push_target
from admenot.engine.transfer.puller import PullResult
from admenot.engine.transfer.telplan import CONTACTS_URI, DATA_URI, RAW_URI

_MMS_PREFIX = "content://mms/part/"
DEFAULT_FREE_KB = 70_000_000
APK_DIR = "/data/app/~~fake==/{package}-1"
TEL_URIS = {"content://sms": "sms", "content://mms": "mms", "content://call_log/calls": "calls",
            CONTACTS_URI: "contacts", RAW_URI: "raw_contacts", DATA_URI: "data"}
CONVERSATIONS_URI = "content://mms-sms/conversations?simple=true"
_MMS_ADDR = re.compile(r"content://mms/([0-9]+)/addr")
_TMP_LOCAL = "data_local_tmp/admenot"


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
        self.stat_unquoted = False  # linie błędu `stat: <ścieżka>: …` (bez cudzysłowów, nie toybox)
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
        # telefonia (Etap 3)
        self.telephony = False  # puste providery w pamięci odpowiadają „No result found.”
        self.providers: dict[str, list[dict[str, str | None]]] = {k: [] for k in TEL_URIS.values()}
        self.mms_addrs: dict[str, list[dict[str, str | None]]] = {}
        self.no_threads = False
        self._threads: dict[str, str] = {}
        self.helper_denied: set[str] = set()
        self.companion_denied: set[str] = set()
        self.fail_after_records: int | None = None
        self.records_written = 0
        self.appop: str | None = "default"
        self.appop_default: str | None = "ignore"
        self.appop_refused: set[str] = set()  # tryby, których `appops set` nie zmienia (odmowa telefonu)
        self.role_holders: list[str] = []
        self.role_needs_tap = False
        self.role_restore_needs_tap = False
        self.started: list[str] = []  # intencje `am start`
        self.installed: set[str] = set()
        self.install_blocked = False
        self.host_commands: list[list[str]] = []  # polecenia hosta (`install`)
        self.accounts: list[tuple[str, str]] = []
        # eksplorator plików
        self.deny_list_prefixes: set[str] = set()  # listowanie (`find`, `ls`) pod takim prefiksem -> Permission denied
        self.listing_extra: dict[str, list[tuple[str, int, int]]] = {}  # folder -> (nazwa, rozmiar, mtime) tylko w listingu
        self.scanned: list[str] = []  # ścieżki z `content call … scan_file`

    # ---- stan ---------------------------------------------------------------------------
    def get_state(self) -> str:
        return "device" if self.online else "offline"

    def reconnect(self) -> None:
        self.online = True

    def local(self, remote: str) -> Path:
        if remote == helper.HELPER_DIR or remote.startswith(helper.HELPER_DIR + "/"):
            return self.root / _TMP_LOCAL / remote[len(helper.HELPER_DIR):].lstrip("/")
        assert remote == "/sdcard" or remote.startswith("/sdcard/"), remote
        return self.root / "sdcard" / remote[len("/sdcard"):].lstrip("/")

    @property
    def tmp_files(self) -> set[str]:
        """Pliki pod `/data/local/tmp/admenot` (zdalne ścieżki)."""
        base = self.root / _TMP_LOCAL
        if not base.is_dir():
            return set()
        return {f"{helper.HELPER_DIR}/{p.relative_to(base).as_posix()}" for p in base.rglob("*") if p.is_file()}

    def tap_role(self, package: str) -> None:
        """Stuknięcie na telefonie: `package` zostaje domyślną aplikacją SMS."""
        self.role_holders = [package]

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
        if len(args) == 3 and args[:2] == ["install", "-g"]:
            return self._install(args)
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
        if command.endswith(CONTENT_TAIL):  # `content query … 2>&1`: błąd providera na stdout
            argv = shlex.split(command[: -len(CONTENT_TAIL)])
            if argv[0] == "ls":  # błąd `ls` na stdout (jak `2>&1`), kod 0
                try:
                    return self._ls(argv[1:])
                except AdbError as exc:
                    return exc.message.encode("utf-8")
            assert argv[:2] == ["content", "query"], argv
            return self._content(argv[1:], merged=True)
        argv = shlex.split(command)
        if (out := self._tel_shell(argv)) is not None:
            return out
        if argv[:2] == ["pm", "path"] and len(argv) == 3:
            return self._pm_path(argv[2])
        if argv[:2] == ["head", "-c"] and len(argv) == 4:  # nagłówek pliku eksportu
            path = self.local(argv[3])
            if not path.is_file():
                raise AdbError("command_failed", f"head: {argv[3]}: No such file or directory")
            with path.open("rb") as fh:
                return fh.read(int(argv[2]))
        if argv[:2] == ["tail", "-c"] and len(argv) == 4 and argv[2].startswith("+"):
            path = self.local(argv[3])
            if not path.is_file():
                raise AdbError("command_failed", f"tail: {argv[3]}: No such file or directory")
            return path.read_bytes()[int(argv[2][1:]) - 1:]
        if argv[0] == "dd":
            return self._dd(argv[1:])
        handler = {"find": self._find, "stat": self._stat, "df": self._df,
                   "sha256sum": self._sha256, "content": self._content, "ls": self._ls,
                   "mkdir": self._mkdir, "mv": self._mv}.get(argv[0])
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
        if expr[:4] == ["-mindepth", "1", "-maxdepth", "1"]:  # listing folderu eksploratora
            assert expr[4:] == ["-exec", "stat", "-c", "%f|%s|%Y|%n", "{}", "+"] and len(roots) == 1, args
            return self._list(roots[0])
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

    def _list(self, remote: str) -> bytes:
        """`find '<folder>/' -mindepth 1 -maxdepth 1 -exec stat -c '%f|%s|%Y|%n' {} +` (tryb hex jak toybox)."""
        if any(remote.startswith(p) for p in self.deny_list_prefixes):
            raise AdbError("command_failed", f"find: '{remote}': Permission denied")
        base = self.local(remote)
        if not base.is_dir():
            raise AdbError("command_failed", f"find: '{remote}': No such file or directory")
        prefix = remote.rstrip("/") + "/"
        out: list[str] = []
        for p in sorted(base.iterdir()):
            st = p.stat()
            out.append(f"{0x41f9 if p.is_dir() else 0x81b0:x}|{4096 if p.is_dir() else st.st_size}"
                       f"|{int(st.st_mtime)}|{prefix}{p.name}")
        out += [f"81b0|{size}|{mtime}|{prefix}{name}" for name, size, mtime in self.listing_extra.get(prefix[:-1], [])]
        return ("\n".join(out) + "\n").encode("utf-8") if out else b""

    def _ls(self, args: list[str]) -> bytes:
        assert args[:1] == ["-1"] and len(args) == 2 or len(args) == 1, args
        if any(args[-1].startswith(p) for p in self.deny_list_prefixes):
            raise AdbError("command_failed", f"ls: {args[-1]}: Permission denied")
        base = self.local(args[-1])
        if not base.is_dir():
            raise AdbError("command_failed", f"ls: {args[-1]}: No such file or directory")
        return "".join(f"{p.name}\n" for p in sorted(base.iterdir())).encode("utf-8")

    def _dd(self, args: list[str]) -> bytes:
        """`dd if=<plik> bs=N skip=K status=none [count=C]` — bloki po `bs` bajtów."""
        opts = dict(a.split("=", 1) for a in args)
        path = self.local(opts["if"])
        if not path.is_file():
            raise AdbError("command_failed", f"dd: {opts['if']}: No such file or directory")
        bs = int(opts["bs"])
        data = path.read_bytes()[int(opts["skip"]) * bs:]
        return data[: int(opts["count"]) * bs] if "count" in opts else data

    def _mv(self, args: list[str]) -> bytes:
        """`mv -n <src> <dst>`: nigdy nie nadpisuje (jak toybox: cichy brak działania)."""
        assert args[0] == "-n" and len(args) == 3, args
        src, dst = self.local(args[1]), self.local(args[2])
        if not src.exists():
            raise AdbError("command_failed", f"mv: '{args[1]}': No such file or directory")
        if not dst.exists():
            src.rename(dst)
        return b""

    def _stat(self, args: list[str], tolerant: bool = False) -> bytes:
        """Jak toybox + `adb shell`: błąd = kod 1 (`AdbError`, wynik ginie), chyba że `tolerant`
        (przyrostek `STAT_TAIL`) — wtedy linia błędu na każdy plik i dalej."""
        with_mode = args[1] == "%f|%s|%Y|%n"
        assert args[0] == "-c" and (with_mode or args[1] == "%s|%Y|%n"), args
        out: list[str] = []
        for remote in args[2:]:
            path = self.local(remote)
            error = None
            shown = remote if self.stat_unquoted else f"'{remote}'"
            if any(remote.startswith(p) for p in self.deny_stat_prefixes):
                error = f"stat: {shown}: Permission denied"
            elif not path.exists():
                error = f"stat: {shown}: No such file or directory"
            if error is not None:
                if not tolerant:
                    raise AdbError("command_failed", error)
                out.append(error)
                continue
            st = path.stat()
            mode = f"{0x41f9 if path.is_dir() else 0x81b0:x}|" if with_mode else ""
            out.append(f"{mode}{st.st_size}|{int(st.st_mtime)}|{remote}")
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

    def _content(self, args: list[str], merged: bool = False) -> bytes:
        if args[0] == "call" and args[-2] == "--arg" and "scan_file" in args:
            assert args[1:-1] == ["--uri", "content://media", "--method", "scan_file", "--arg"], args
            self.scanned.append(args[-1])
            return b"Result: Bundle[{}]\n"
        if args[0] == "call":
            assert args[1:] == ["--uri", "content://media", "--method", "scan_volume",
                                "--arg", "external_primary"], args
            self.scans += 1
            return b"Result: Bundle[{}]\n"
        if args[0] == "query":
            # Jak prawdziwy telefon: błąd providera idzie na stderr, a kod wyjścia to 0 —
            # bez `2>&1` (merged) adb zwraca pusty stdout.
            uri = args[args.index("--uri") + 1]
            error = None
            rows = self._tel_rows(uri)
            if uri in self.deny_uris:
                error = f"Error while accessing provider:{uri}\njava.lang.SecurityException: Permission Denial\n"
            elif rows is not None:
                cols = args[args.index("--projection") + 1].split(":") if "--projection" in args else None
                return _render(rows, cols).encode("utf-8")
            elif not provider_file(self.root, uri).is_file():
                error = f"Error while accessing provider:{uri}\njava.lang.IllegalArgumentException: Unknown URL\n"
            if error is not None:
                return error.encode("utf-8") if merged else b""
            return provider_file(self.root, uri).read_bytes()
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

    # ---- telefonia: polecenia -------------------------------------------------------------
    def _tel_shell(self, argv: list[str]) -> bytes | None:
        """Polecenia zapisu telefonii; `None` = nie nasze (obsługa jak dotąd)."""
        if argv and argv[0].startswith("CLASSPATH="):
            return self._app_process(argv)
        head = argv[:2]
        if head == ["am", "instrument"]:
            return self._instrument(argv)
        if head == ["am", "start"]:
            self.started.append(" ".join(argv[2:]))
            return f"Starting: Intent {{ {' '.join(argv[2:])} }}\n".encode()
        if head == ["appops", "get"]:
            assert argv[2:] == ["com.android.shell", "WRITE_SMS"], argv
            if self.appop is not None:
                return f"WRITE_SMS: {self.appop}; time=+1m2s3ms ago\n".encode()
            default = "" if self.appop_default is None else f"Default mode: {self.appop_default}\n"
            return f"No operations.\n{default}".encode()
        if head == ["appops", "set"]:
            assert argv[2:4] == ["com.android.shell", "WRITE_SMS"] and len(argv) == 5, argv
            if argv[4] in self.appop_refused:
                return b"Security exception: shell cannot change WRITE_SMS\n"
            self.appop = argv[4]
            return b""
        if head == ["cmd", "role"]:
            return self._role(argv[2:])
        if head == ["dumpsys", "role"]:
            return self._dumpsys_role().encode()
        if head == ["dumpsys", "account"]:
            lines = [f"    Account {{name={n}, type={t}}}\n" for t, n in self.accounts]
            return (f"User UserInfo{{0:Właściciel:c13}}:\n  Accounts: {len(lines)}\n" + "".join(lines)
                    + "\n  Active Sessions: 0\n").encode()
        if head == ["pm", "list"]:
            assert argv[2] == "packages" and len(argv) == 4, argv
            return "".join(f"package:{p}\n" for p in sorted(self.installed) if p.startswith(argv[3])).encode()
        if head == ["pm", "uninstall"]:
            return self._uninstall(argv[2])
        if head == ["pm", "grant"]:
            return b""
        if head == ["rm", "-rf"]:
            assert len(argv) == 3 and self.local(argv[2]).is_relative_to(self.root / _TMP_LOCAL), argv
            shutil.rmtree(self.local(argv[2]), ignore_errors=True)
            return b""
        return None

    def _install(self, args: list[str]) -> str:
        if not self.online:
            raise AdbError("offline", "device offline")
        self.host_commands.append(list(args))
        if self.install_blocked:
            raise AdbError("command_failed", f"Performing Streamed Install\nadb: failed to install {args[2]}: "
                                             "Failure [INSTALL_FAILED_USER_RESTRICTED: Install canceled by user]")
        if helper.PACKAGE in self.installed:
            raise AdbError("command_failed", f"adb: failed to install {args[2]}: Failure "
                                             f"[INSTALL_FAILED_ALREADY_EXISTS: Attempt to re-install "
                                             f"{helper.PACKAGE} without first uninstalling.]")
        self.installed.add(helper.PACKAGE)  # `Android/data/<pakiet>` nie istnieje do pierwszego `mkdir -p`
        return "Performing Streamed Install\nSuccess\n"

    def _uninstall(self, package: str) -> bytes:
        if package not in self.installed:
            raise AdbError("command_failed", "Failure [DELETE_FAILED_INTERNAL_ERROR]")
        self.installed.discard(package)
        if package in self.role_holders:  # rola nie wraca do poprzedniej aplikacji sama
            self.role_holders = [p for p in self.role_holders if p != package]
        shutil.rmtree(self.local(f"/sdcard/Android/data/{package}"), ignore_errors=True)
        return b"Success\n"

    def _role(self, args: list[str]) -> bytes:
        assert len(args) == 3 and args[1] == SMS_ROLE, args
        op, pkg = args[0], args[2]
        if op == "add-role-holder":
            if pkg == helper.PACKAGE:
                if pkg not in self.installed:
                    raise AdbError("command_failed", f"Package {pkg} not found")
                if self.role_needs_tap:
                    return b""
            elif self.role_restore_needs_tap:
                return b""
            self.role_holders = [pkg]  # rola SMS ma jednego posiadacza
            return b""
        assert op == "remove-role-holder", args
        if not self.role_restore_needs_tap:
            self.role_holders = [p for p in self.role_holders if p != pkg]
        return b""

    def _dumpsys_role(self) -> str:
        def role(name: str, holders: list[str]) -> str:
            return ("      {\n" f"        name={name}\n        fallback_enabled=false\n"
                    + "".join(f"        holders={h}\n" for h in holders) + "      }\n")

        return ("ROLE STATE (dumpsys role):\n{\n  user_states={\n    user_id=0\n    version=-1\n    roles=[\n"
                + role("android.app.role.SYSTEM_UI_INTELLIGENCE", [])
                + role(SMS_ROLE, self.role_holders)
                + role("android.app.role.DIALER", ["com.google.android.dialer"])
                + "    ]\n  }\n}\n")

    # ---- telefonia: pomocnik --------------------------------------------------------------
    def _app_process(self, argv: list[str]) -> bytes:
        assert argv[0] == f"CLASSPATH={helper.DEX_REMOTE}" and argv[1:5] == [
            "app_process", "/", helper.MAIN_CLASS, "write"], argv
        if not self.local(helper.DEX_REMOTE).is_file():
            raise AdbError("command_failed", f"Error: Could not find or load main class {helper.MAIN_CLASS}")
        account = (argv[7], argv[8]) if argv[6:7] == ["--account"] else None
        kind, records = self._read_input(argv[5])
        if kind in self.helper_denied or (kind in ("sms", "mms") and self.appop != "allow"):
            return b"DENIED\n"
        return "".join(line + "\n" for line in self._write(kind, records, account, argv[5])).encode("utf-8")

    def _instrument(self, argv: list[str]) -> bytes:
        assert argv[2:4] == ["-w", "-r"] and argv[-1] == helper.RUNNER, argv
        extras = dict(zip(argv[5:-1:3], argv[6:-1:3], strict=True))
        assert argv[4:-1:3] == ["-e"] * len(extras) and extras["cmd"] == "write", argv
        if helper.PACKAGE not in self.installed:
            raise AdbError("command_failed", f"INSTRUMENTATION_FAILED: {helper.RUNNER}")
        account = (extras["account_type"], extras["account_name"]) if "account_type" in extras else None
        kind, records = self._read_input(extras["input"])
        if kind in self.companion_denied or (kind in ("sms", "mms") and self.role_holders != [helper.PACKAGE]):
            lines = ["DENIED"]
        else:
            lines = self._write(kind, records, account, extras["input"])
        status = "".join(f"INSTRUMENTATION_STATUS: line={line}\nINSTRUMENTATION_STATUS_CODE: 1\n"
                         for line in lines)
        return (status + "INSTRUMENTATION_RESULT: done=1\nINSTRUMENTATION_CODE: -1\n").encode("utf-8")

    def _read_input(self, remote: str) -> tuple[str, list[dict]]:
        lines = self.local(remote).read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        assert header["v"] == 1, header
        return header["kind"], [json.loads(line) for line in lines[1:] if line]

    def _write(self, kind: str, records: list[dict], account: tuple[str, str] | None, remote: str) -> list[str]:
        self.telephony = True
        out: list[str] = []
        parts_dir = self.local(remote).parent
        for rec in records:
            if self.fail_after_records is not None and self.records_written >= self.fail_after_records:
                self.online = False
                raise AdbError("offline", "device offline")
            if kind == "mms" and any(p["file"] and not (parts_dir / p["file"]).is_file() for p in rec["parts"]):
                out.append(f"ERR {rec['id']} missing_part")
                continue
            {"sms": self._add_sms, "calls": self._add_call, "contacts": self._add_contact,
             "mms": self._add_mms}[kind](rec, account)
            self.records_written += 1
            out.append(f"OK {rec['id']}")
        for uri in TEL_URIS:
            self._mirror(uri)
        ok = sum(1 for x in out if x.startswith("OK"))
        return [*out, f"DONE {ok} {len(out) - ok}"]

    # ---- telefonia: providery -------------------------------------------------------------
    def _tel_rows(self, uri: str) -> list[dict[str, str | None]] | None:
        if uri == CONVERSATIONS_URI:
            threads = sorted({r.get("thread_id") for k in ("sms", "mms") for r in self.providers[k]}
                             - {None, "0"}, key=int)
            return [{"_id": t} for t in threads]
        if m := _MMS_ADDR.fullmatch(uri):
            return self.mms_addrs.get(m.group(1))
        kind = TEL_URIS.get(uri)
        if kind is None or not (self.telephony or self.providers[kind]):
            return None
        return self.providers[kind]

    def _mirror(self, uri: str) -> None:
        rows = self.providers[TEL_URIS[uri]]
        if rows:
            cols = list(dict.fromkeys(c for r in rows for c in r))
            write_provider(self.root, uri, rows, cols)

    def _next_id(self, kind: str) -> str:
        return str(max((int(r["_id"]) for r in self.providers[kind] if r.get("_id")), default=0) + 1)

    def _thread(self, addresses: list[str]) -> str:
        if self.no_threads:
            return "0"
        key = ",".join(sorted(tel.phone_key(a) for a in addresses))
        return self._threads.setdefault(key, str(len(self._threads) + 1))

    def _add_sms(self, rec: dict, account: tuple[str, str] | None) -> None:
        self.providers["sms"].append({
            "_id": self._next_id("sms"), "thread_id": self._thread([rec["address"]]),
            "address": rec["address"], "date": str(rec["date"]), "date_sent": str(rec["date_sent"]),
            "type": str(rec["type"]), "read": str(rec["read"]), "status": str(rec["status"]),
            "locked": "0", "sub_id": "-1", "protocol": None, "service_center": None,
            "subject": rec["subject"], "body": rec["body"]})

    def _add_call(self, rec: dict, account: tuple[str, str] | None) -> None:
        self.providers["calls"].append({
            "_id": self._next_id("calls"), "number": rec["number"], "date": str(rec["date"]),
            "duration": str(rec["duration"]), "type": str(rec["type"]),
            "presentation": str(rec["presentation"]), "subscription_id": None, "name": rec["name"]})

    def _add_mms(self, rec: dict, account: tuple[str, str] | None) -> None:
        mid = self._next_id("mms")
        self.providers["mms"].append({
            "_id": mid, "thread_id": self._thread([a for a, _ in rec["addrs"]]),
            "date": str(rec["date"] // 1000), "date_sent": str(rec["date_sent"] // 1000),
            "msg_box": str(rec["msg_box"]), "read": str(rec["read"]), "sub": rec["subject"]})
        self.mms_addrs[mid] = [{"type": str(t), "address": a} for a, t in rec["addrs"]]

    def _add_contact(self, rec: dict, account: tuple[str, str] | None) -> None:
        cid = self._next_id("contacts")
        name = next((r["values"].get("data1") for r in rec["rows"] if r["mimetype"] == tel.M_NAME), None)
        self.providers["contacts"].append({"_id": cid, "starred": str(rec["starred"]), "display_name": name})
        self.providers["raw_contacts"].append({
            "_id": cid, "contact_id": cid, "deleted": "0",
            "account_type": account[0] if account else None, "account_name": account[1] if account else None})
        for r in rec["rows"]:
            vals = r["values"]
            self.providers["data"].append({
                "contact_id": cid, "raw_contact_id": cid, "mimetype": r["mimetype"],
                "is_primary": vals.get("is_primary", "0"),
                **{f"data{i}": vals.get(f"data{i}") for i in range(2, 11)}, "data1": vals.get("data1")})


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
        safe_push_target(remote)
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
                                 "remote couldn't create file: "
                                 + ("Is a directory" if remote.endswith("/") else "No such file or directory"))
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


def _render(rows: list[dict[str, str | None]], cols: list[str] | None) -> str:
    """Wyjście `content query` dla wierszy w pamięci, w kolejności kolumn projekcji."""
    if not rows:
        return "No result found.\n"
    cols = cols or list(dict.fromkeys(c for r in rows for c in r))
    return "".join(f"Row: {i} " + ", ".join(f"{c}={'NULL' if r.get(c) is None else r[c]}" for c in cols) + "\n"
                   for i, r in enumerate(rows))


_STORAGE_TOOLS = {"find", "stat", "ls", "df", "content", "sha256sum", "mkdir", "head", "tail", "dd", "mv"}
_TEL_HEADS = (["am", "instrument"], ["dumpsys", "role"], ["dumpsys", "account"], ["rm", "-rf"],
              ["cmd", "role", "add-role-holder"], ["cmd", "role", "remove-role-holder"])
_TEL_INTENTS = (f"{helper.PACKAGE}/.RoleActivity", "android.settings.MANAGE_DEFAULT_APPS_SETTINGS")


def _telephony_cmd(argv: list[str]) -> bool:
    """Zapis telefonii (Etap 3) idzie do `FakeStoragePhone`: pomocnik, appop shell, rola SMS, aplikacja
    pomocnicza, jej katalogi i intencje. Polecenia skanu i naprawy (`--user 0`, `cmd role
    get-role-holders`, ekrany ustawień) zostają przy `FakePhone`."""
    if not argv:
        return False
    if argv[0].startswith("CLASSPATH=") or any(argv[:len(h)] == h for h in _TEL_HEADS):
        return True
    if argv[:2] == ["am", "start"] and any(i in argv for i in _TEL_INTENTS):
        return True
    if argv[0] == "appops" and argv[2:3] == ["com.android.shell"]:
        return True
    return argv[0] == "pm" and argv[1:2] in (["list"], ["uninstall"], ["grant"]) and helper.PACKAGE in argv


class TransferPhone:
    """Telefon do testów mostu kopii: skan aplikacji z `FakePhone` (pakiety, ustawienia), pamięć,
    providery, APK i `pull` z `FakeStoragePhone`. Jest też `Puller` (puller_factory → ta atrapa).
    Zapis telefonii (pomocnik, appop shell, rola SMS, `install -g`, intencje roli) też idzie do
    `FakeStoragePhone` (`_telephony_cmd`)."""

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
        return (bool(argv) and argv[0] in _STORAGE_TOOLS) or _telephony_cmd(argv)

    def shell(self, command: str, timeout: float = 20.0) -> str:
        if self._storage_cmd(command):
            return self.storage.shell(command, timeout)
        return self.cli.shell(command, timeout)

    def run(self, args: list[str], timeout: float = 20.0) -> str:
        if args == ["get-state"] or args[:2] == ["install", "-g"]:
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
