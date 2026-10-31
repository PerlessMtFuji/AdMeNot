"""Pomocnik na telefonie: zapis hurtowy kontaktów, SMS, MMS i połączeń.

Dwie drogi z tym samym protokołem (kod Javy w `android/helper/`):
- `app_process` jako shell z `.dex` w `/data/local/tmp/admenot/`;
- `am instrument` aplikacji pomocniczej `pl.admenot.helper` (gdy shell nie ma uprawnień).

Wejście to plik JSON Lines: nagłówek `{"kind": …, "v": 1}`, potem rekord na linię z `"id"`
(`telplan.record_id`). Części MMS leżą obok pliku wejścia pod nazwą względną. Wyjście, po linii:
`OK <id>`, `ERR <id> <kod>`, `DENIED`, `DONE <ok> <err>`; instrumentacja opakowuje każdą w
`INSTRUMENTATION_STATUS: line=…`.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from ..adb.transport import AdbTransport
from .pusher import Pusher
from .telrecords import CallRecord, ContactRecord, MmsRecord, SmsRecord
from .winpath import sanitize_component

HELPER_DIR = "/data/local/tmp/admenot"
HELPER_IN = f"{HELPER_DIR}/in"
PACKAGE = "pl.admenot.helper"
COMPANION_IN = f"/sdcard/Android/data/{PACKAGE}/files/in"
RUNNER = f"{PACKAGE}/.Runner"
MAIN_CLASS = f"{PACKAGE}.Main"
INPUT_NAME = "input.jsonl"
SUMS = "SHA256SUMS"
HELPER_BIN = Path(__file__).resolve().parent / "helper_bin"
ARTIFACTS: dict[str, str] = {"dex": "admenot-helper.dex", "apk": "admenot-helper.apk"}
DEX_REMOTE = f"{HELPER_DIR}/{ARTIFACTS['dex']}"
_STATUS = "INSTRUMENTATION_STATUS: line="
RUN_TIMEOUT = 6 * 3600.0  # 10 000 SMS na OPPO to ~4 min; zapas na wolne telefony


class HelperBroken(Exception):
    """Artefakt pomocnika niezgodny z `SHA256SUMS` (lokalnie albo po wgraniu na telefon)."""


# --------------------------------------------------------------------------------------
# Artefakty
# --------------------------------------------------------------------------------------
def read_sums(bin_dir: Path) -> dict[str, str]:
    """`SHA256SUMS`: `<sha256>  <plik>` oraz `sources=<sha256>` -> {plik|"sources": sha}."""
    out: dict[str, str] = {}
    try:
        text = (bin_dir / SUMS).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("sources="):
            out["sources"] = line.removeprefix("sources=")
        elif line:
            digest, _, name = line.partition("  ")
            out[name.strip()] = digest.strip()
    return out


def artifact(name: Literal["dex", "apk"], bin_dir: Path | None = None) -> tuple[Path, str]:
    d = HELPER_BIN if bin_dir is None else bin_dir
    path = d / ARTIFACTS[name]
    want = read_sums(d).get(ARTIFACTS[name])
    try:
        have = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise HelperBroken(f"{path.name}: {exc}") from exc
    if want is None or have != want:
        raise HelperBroken(f"{path.name}: hash does not match {SUMS}")
    return path, have


def sources_digest(src_root: Path) -> str:
    """SHA-256 wszystkich plików źródeł pomocnika (ścieżka względna + treść), w stałej kolejności."""
    h = hashlib.sha256()
    for p in sorted(x for x in src_root.rglob("*") if x.is_file()):
        rel = p.relative_to(src_root).as_posix()
        h.update(rel.encode("utf-8") + b"\0")
        h.update(p.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


# --------------------------------------------------------------------------------------
# Wejście
# --------------------------------------------------------------------------------------
def _sms(r: SmsRecord) -> dict:
    return {"address": r.address, "date": r.date, "date_sent": r.date_sent, "type": r.type,
            "read": r.read, "status": r.status, "subject": r.subject, "body": r.body}


def _call(r: CallRecord) -> dict:
    return {"number": r.number, "date": r.date, "duration": r.duration, "type": r.type,
            "presentation": r.presentation, "name": r.name}


def _contact(r: ContactRecord) -> dict:
    return {"starred": 1 if r.starred else 0,
            "rows": [{"mimetype": d.mimetype, "values": dict(d.values)} for d in r.rows]}


def _mms(r: MmsRecord, parts_out: Path, seq: list[int]) -> dict:
    parts = []
    for p in r.parts:
        rel = None
        if p.file is not None:
            seq[0] += 1
            rel = f"p{seq[0]}-{sanitize_component(p.name or p.file.name)}"
            shutil.copyfile(p.file, parts_out / rel)
        parts.append({"ct": p.content_type, "name": p.name, "text": p.text, "file": rel})
    return {"date": r.date, "date_sent": r.date_sent, "msg_box": r.msg_box, "read": r.read,
            "subject": r.subject, "addrs": [[a, t] for a, t in r.addrs], "parts": parts}


def encode(kind: str, records: list[tuple[str, object]], parts_out: Path) -> Path:
    """Plik wejścia pomocnika w `parts_out` (tam też kopie części MMS); zwraca jego ścieżkę."""
    parts_out.mkdir(parents=True, exist_ok=True)
    seq = [0]
    path = parts_out / INPUT_NAME
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"kind": kind, "v": 1}) + "\n")
        for rid, rec in records:
            if kind == "sms":
                row = _sms(rec)  # type: ignore[arg-type]
            elif kind == "calls":
                row = _call(rec)  # type: ignore[arg-type]
            elif kind == "contacts":
                row = _contact(rec)  # type: ignore[arg-type]
            elif kind == "mms":
                row = _mms(rec, parts_out, seq)  # type: ignore[arg-type]
            else:
                raise ValueError(f"unknown kind {kind!r}")
            fh.write(json.dumps({"id": rid, **row}, ensure_ascii=False) + "\n")
    return path


# --------------------------------------------------------------------------------------
# Wyjście
# --------------------------------------------------------------------------------------
@dataclass
class WriteOutcome:
    ok: set[str] = field(default_factory=set)
    failed: dict[str, str] = field(default_factory=dict)
    denied: bool = False
    finished: bool = False


def _protocol_line(raw: str) -> str | None:
    line = raw.strip()
    if line.startswith(_STATUS):
        return line.removeprefix(_STATUS)
    if line.startswith("INSTRUMENTATION_"):
        return None
    return line


def parse_output(lines: Iterable[str]) -> WriteOutcome:
    """Linie pomocnika (także opakowane przez instrumentację); po `DENIED` nic się nie liczy."""
    out = WriteOutcome()
    for raw in lines:
        line = _protocol_line(raw)
        if not line:
            continue
        word, _, rest = line.partition(" ")
        if word == "DENIED":
            out.denied = True
            break
        if word == "OK" and rest:
            out.ok.add(rest.strip())
        elif word == "ERR" and rest:
            rid, _, code = rest.strip().partition(" ")
            out.failed[rid] = code or "error"
        elif word == "DONE":
            out.finished = True
    return out


# --------------------------------------------------------------------------------------
# Pisarze
# --------------------------------------------------------------------------------------
class Writer(Protocol):
    def write(self, kind: str, records: list[tuple[str, object]],
              on_line: Callable[[], None]) -> WriteOutcome: ...


def _never() -> bool:
    return False


def _noop() -> None:
    return None


def _push(pusher: Pusher, locals_: list[Path], remote: str) -> None:
    res = pusher.push(locals_, remote, _never, _noop)
    if res.rc != 0:
        raise HelperBroken(f"push to {remote} failed: {' '.join(res.lines[-1:])}")


def _run(adb: AdbTransport, command: str, on_line: Callable[[], None]) -> WriteOutcome:
    lines = adb.shell(command, timeout=RUN_TIMEOUT).splitlines()
    for raw in lines:
        if _protocol_line(raw):
            on_line()
    return parse_output(lines)


def _account_args(account: tuple[str, str] | None, flag: Callable[[str, str], str]) -> str:
    if account is None:
        return ""
    return " " + flag(shlex.quote(account[0]), shlex.quote(account[1]))


class AppProcessWriter:
    """`app_process` jako shell; `.dex` wgrywany i sprawdzany raz na obiekt."""

    def __init__(self, adb: AdbTransport, pusher: Pusher, account: tuple[str, str] | None) -> None:
        self.adb, self.pusher, self.account = adb, pusher, account
        self._installed = False

    def _install(self) -> None:
        local, digest = artifact("dex")
        self.adb.shell(f"mkdir -p {HELPER_IN}")
        _push(self.pusher, [local], DEX_REMOTE)
        got = self.adb.shell(f"sha256sum {DEX_REMOTE}").split()
        if not got or got[0].lower() != digest:
            raise HelperBroken("helper .dex on the phone does not match")
        self._installed = True

    def write(self, kind: str, records: list[tuple[str, object]],
              on_line: Callable[[], None]) -> WriteOutcome:
        if not self._installed:
            self._install()
        with tempfile.TemporaryDirectory(prefix="admenot-helper-") as tmp:
            path = encode(kind, records, Path(tmp))
            try:
                self.adb.shell(f"mkdir -p {HELPER_IN}")
                _push(self.pusher, sorted(Path(tmp).iterdir()), HELPER_IN + "/")
                cmd = (f"CLASSPATH={DEX_REMOTE} app_process / {MAIN_CLASS} write "
                       f"{HELPER_IN}/{path.name}"
                       + _account_args(self.account, lambda t, n: f"--account {t} {n}"))
                return _run(self.adb, cmd, on_line)
            finally:
                self.adb.shell(f"rm -rf {HELPER_IN}")


class CompanionWriter:
    """`am instrument` aplikacji pomocniczej; wejście w jej `files/in/` (znika z odinstalowaniem)."""

    def __init__(self, adb: AdbTransport, pusher: Pusher, account: tuple[str, str] | None) -> None:
        self.adb, self.pusher, self.account = adb, pusher, account

    def write(self, kind: str, records: list[tuple[str, object]],
              on_line: Callable[[], None]) -> WriteOutcome:
        with tempfile.TemporaryDirectory(prefix="admenot-helper-") as tmp:
            path = encode(kind, records, Path(tmp))
            _push(self.pusher, sorted(Path(tmp).iterdir()), COMPANION_IN + "/")
            cmd = (f"am instrument -w -r -e cmd write -e input {COMPANION_IN}/{path.name}"
                   + _account_args(self.account,
                                   lambda t, n: f"-e account_type {t} -e account_name {n}")
                   + f" {RUNNER}")
            return _run(self.adb, cmd, on_line)
