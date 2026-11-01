"""Eksport MMS (wiadomości grupowe i ze zdjęciami/filmami) przez dostawcę content://mms.

Co powstaje w katalogu docelowym:
* mms.xml     – format SMS Backup & Restore (SyncTech): <mms> z <parts> (załączniki w base64)
                i <addrs>; da się go przywrócić tą aplikacją. Tekst wiadomości jest czytelny
                w edytorze (atrybut text), załączniki – nie (base64).
* mms_parts/  – te same załączniki jako zwykłe pliki (zdjęcia, filmy, vCard…), nazwane
                <data>_<id wiadomości>_<id części>_<nazwa>. Służą też jako pamięć podręczna:
                po przerwaniu kolejne uruchomienie nie pobiera ich ponownie.

Źródła danych (uprawnienie READ_SMS użytkownika shell):
* content://mms              – nagłówki wiadomości (data w SEKUNDACH – zamieniamy na ms jak SB&R),
* content://mms/part         – wszystkie części naraz (tekst, SMIL, metadane załączników),
* content://mms/<id>/addr    – adresy (nadawca/odbiorcy) – osobno dla każdej wiadomości,
* content read --uri content://mms/part/<id> – zawartość binarna załącznika.

Czego tu NIE ma: czatów RCS (Google Messages „czat”) – nie są w dostawcy MMS/SMS.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from admenot.engine.adb.transport import AdbError, AdbTransport

from .telephony import (
    CategoryResult,
    ContentQueryError,
    Stopped,
    atomic_write,
    content_query,
    phone_key,
    query_with_fallback,
    xml_attr,
)
from .winpath import sanitize_component

RETRY_PAUSE = 0.5  # s; przerwa przed kolejną próbą pobrania załącznika rośnie liniowo
ATTEMPTS = 3

MMS_URI = "content://mms"
PART_URI = "content://mms/part"
B64_CHUNK = 3 * 256 * 1024  # bajtów na kawałek base64: wielokrotność 3 => brak paddingu w środku

# Kolumny tabeli pdu. Pola z dowolnym tekstem (sub, retr_txt, resp_txt) na końcu – parser
# `content query` rozpoznaje granice kolumn po ", <następna_kolumna>=".
MMS_COLS = ["_id", "thread_id", "date", "date_sent", "msg_box", "read", "seen", "locked", "sub_id",
            "text_only", "m_type", "m_size", "v", "pri", "rr", "d_rpt", "read_status", "st", "retr_st",
            "resp_st", "rpt_a", "d_tm", "exp", "ct_t", "ct_l", "ct_cls", "m_cls", "m_id", "tr_id",
            "sub_cs", "retr_txt_cs", "retr_txt", "resp_txt", "sub"]
MMS_COLS_MIN = ["_id", "thread_id", "date", "msg_box", "read", "m_type", "ct_t", "m_size", "sub"]
PART_COLS = ["_id", "mid", "seq", "ct", "chset", "cid", "cl", "fn", "cd", "ctt_s", "ctt_t", "name", "text"]
PART_COLS_MIN = ["_id", "mid", "seq", "ct", "chset", "name", "text"]
ADDR_COLS = ["msg_id", "type", "charset", "address"]

ADDR_FROM, ADDR_TO = "137", "151"
TEXT_TYPES = ("text/plain", "application/smil")
OWN_TOKEN = "insert-address-token"


def _ms(v: str | None) -> str:
    """Kolumna date w MMS jest w sekundach; SB&R i reszta naszego programu używają ms."""
    try:
        n = int(v or 0)
    except ValueError:
        return "0"
    return str(n * 1000 if 0 < n < 100_000_000_000 else n)


def _readable(ms: str) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return ""


def attachment_name(msg: dict, part: dict) -> str:
    """Deterministyczna nazwa pliku załącznika (ta sama przy każdym uruchomieniu)."""
    ms = _ms(msg.get("date"))
    try:
        stamp = datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d_%H%M%S")
    except (ValueError, OSError, OverflowError):
        stamp = "0000-00-00_000000"
    raw = next((part.get(k) for k in ("fn", "name", "cl") if part.get(k)), None) or "zalacznik"
    raw = raw.strip("<>\"' ") or "zalacznik"
    stem, ext = os.path.splitext(raw)
    if not ext or len(ext) > 6:
        ct = (part.get("ct") or "").split(";")[0].strip().lower()
        ext = mimetypes.guess_extension(ct) or {"image/jpg": ".jpg", "text/x-vcard": ".vcf",
                                                 "audio/amr": ".amr"}.get(ct, ".bin")
        stem = raw if len(os.path.splitext(raw)[1]) > 6 else stem
    stem = sanitize_component(stem)[:60]
    return f"{stamp}_{msg['_id']}_{part['_id']}_{stem}{sanitize_component(ext)}"


def needs_binary(part: dict) -> bool:
    ct = (part.get("ct") or "").split(";")[0].strip().lower()
    return part.get("text") is None and ct not in TEXT_TYPES


def message_address(msg_box: str | None, addrs: list[dict]) -> str:
    """Atrybut address jak w SB&R: druga strona rozmowy; przy grupach numery połączone '~'."""
    if msg_box == "1":
        picked = [a["address"] for a in addrs if a.get("type") == ADDR_FROM]
    else:
        picked = [a["address"] for a in addrs if a.get("type") != ADDR_FROM]
    out: list[str] = []
    for a in picked:
        if a and a != OWN_TOKEN and a not in out:
            out.append(a)
    if not out:  # np. wersja robocza – cokolwiek sensownego
        out = [a["address"] for a in addrs if a.get("address") and a["address"] != OWN_TOKEN][:1]
    return "~".join(out)


def _parallel(items: list[Any], fn: Callable[[Any], Any], workers: int, should_stop: Callable[[], bool],
              on_done: Callable[[Any, Any, Exception | None], None]) -> None:
    """Uruchamia fn(item) równolegle; przerwanie = Stopped po zakończeniu bieżących wywołań."""
    if not items:
        return
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(fn, it): it for it in items}
        try:
            for fut in as_completed(futs):
                it = futs[fut]
                try:
                    res, err = fut.result(), None
                except Stopped:
                    raise
                except Exception as exc:  # noqa: BLE001
                    res, err = None, exc
                on_done(it, res, err)
                if should_stop():
                    raise Stopped()
        except BaseException:
            for f in futs:
                f.cancel()
            raise


def _is_online(adb: AdbTransport) -> bool:
    try:
        return adb.run(["get-state"]).strip() == "device"
    except AdbError:
        return False


def export_mms(adb: AdbTransport, out_dir: Path, names: dict[str, str],
               should_stop: Callable[[], bool], shell_v2: bool = True, workers: int = 4) -> CategoryResult:
    raw_dir = out_dir / "raw"
    att_dir = out_dir / "mms_parts"
    xml_path = out_dir / "mms.xml"

    def sink(name: str) -> Callable[[str], None]:
        return lambda txt: atomic_write(raw_dir / name, txt)

    _, msgs = query_with_fallback(adb, MMS_URI, [MMS_COLS, MMS_COLS_MIN], sort="date ASC",
                                  raw_sink=sink("mms.txt"))
    if not msgs:
        return CategoryResult("ok", 0)
    ids = {m["_id"] for m in msgs}

    _, parts = query_with_fallback(adb, PART_URI, [PART_COLS, PART_COLS_MIN], sort="_id ASC",
                                   raw_sink=sink("mms_part.txt"))
    parts_by_msg: dict[str, list[dict[str, str | None]]] = {}
    for p in parts:
        if p.get("mid") in ids:
            parts_by_msg.setdefault(p["mid"], []).append(p)  # type: ignore[arg-type]
    for lst in parts_by_msg.values():
        lst.sort(key=lambda p: (int(p.get("seq") or 0) if (p.get("seq") or "0").lstrip("-").isdigit() else 0,
                                int(p["_id"] or 0)))

    # ---- adresy (osobne zapytanie na każdą wiadomość; wynik zapamiętywany na wypadek przerwania)
    addr_cache_path = raw_dir / "mms_addr.json"
    try:
        addr_cache: dict[str, list[dict[str, str | None]]] = json.loads(
            addr_cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        addr_cache = {}
    todo = [m["_id"] for m in msgs if m["_id"] not in addr_cache]
    addr_errors = 0
    if todo:
        def get_addr(mid: str) -> list[dict[str, str | None]]:
            return content_query(adb, f"content://mms/{mid}/addr", ADDR_COLS)

        def addr_done(mid: str, rows: Any, err: Exception | None) -> None:
            nonlocal addr_errors
            if err is None:
                addr_cache[mid] = rows
            else:
                addr_errors += 1

        try:
            _parallel(todo, get_addr, workers, should_stop, addr_done)
        finally:
            atomic_write(addr_cache_path, json.dumps(addr_cache, ensure_ascii=False))
        if addr_errors and not _is_online(adb):
            raise AdbError("offline", "device disconnected during the MMS export")

    # ---- załączniki binarne (pamięć podręczna = katalog mms_parts)
    att_dir.mkdir(parents=True, exist_ok=True)
    msg_by_id = {m["_id"]: m for m in msgs}
    binaries = [(msg_by_id[mid], p) for mid, lst in parts_by_msg.items() for p in lst if needs_binary(p)]
    files: dict[str, str] = {}
    pending = []
    for m, p in binaries:
        name = attachment_name(m, p)
        files[p["_id"] or ""] = name
        if not (att_dir / name).is_file():
            pending.append((m, p))
    part_errors = 0
    if pending:
        read_cmd = "content read --uri content://mms/part/{}"

        def fetch(item: tuple[dict[str, str | None], dict[str, str | None]]) -> int:
            _, p = item
            pid = p["_id"] or ""
            cmd = read_cmd.format(pid)
            args = ["shell", "-T", cmd] if shell_v2 else ["exec-out", cmd]
            last: Exception | None = None
            for attempt in range(ATTEMPTS):
                if should_stop():
                    raise Stopped()
                try:
                    data = adb.run_bytes(args, timeout=600)
                except AdbError as exc:
                    if exc.kind in ("offline", "no_device", "unauthorized", "adb_missing"):
                        raise
                    last = exc
                    if attempt + 1 < ATTEMPTS:
                        time.sleep(RETRY_PAUSE * (attempt + 1))
                    continue
                target = att_dir / files[pid]
                tmp = target.with_name(target.name + ".tmp")
                with open(tmp, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, target)
                return len(data)
            raise ContentQueryError(str(last))

        def fetch_done(item: Any, size: Any, err: Exception | None) -> None:
            nonlocal part_errors
            if isinstance(err, AdbError):  # utrata połączenia, nie brak jednego załącznika
                raise err
            if err is not None:
                part_errors += 1

        _parallel(pending, fetch, workers, should_stop, fetch_done)

    # ---- mms.xml (zapis strumieniowy – załączniki mogą mieć setki MB)
    tmp = xml_path.with_name(xml_path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as out:
        _write_xml(out, msgs, parts_by_msg, addr_cache, names, att_dir, files)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, xml_path)

    problems = []
    if addr_errors:
        problems.append(f"addresses_missing:{addr_errors}")
    if part_errors:
        problems.append(f"attachments_missing:{part_errors}")
    if problems:
        # Telefon mógł się rozłączyć w trakcie — wtedy kopia ma poczekać i wznowić.
        if not _is_online(adb):
            raise AdbError("offline", "device disconnected during the MMS export")
        return CategoryResult("failed", len(msgs), ",".join(problems))
    return CategoryResult("ok", len(msgs))


# --------------------------------------------------------------------------------------
# XML
# --------------------------------------------------------------------------------------
_MSG_ATTRS = ["date_sent", "msg_box", "read", "seen", "locked", "sub_id", "text_only", "m_type", "m_size", "v",
              "pri", "rr", "d_rpt", "read_status", "st", "retr_st", "resp_st", "rpt_a", "d_tm", "exp", "ct_t",
              "ct_l", "ct_cls", "m_cls", "m_id", "tr_id", "sub_cs", "retr_txt_cs", "retr_txt", "resp_txt", "sub"]
_PART_ATTRS = ["seq", "ct", "name", "chset", "cd", "fn", "cid", "cl", "ctt_s", "ctt_t"]


def _attrs(pairs: Iterable[tuple[str, str | None]]) -> str:
    return " ".join(f'{k}="{xml_attr(v)}"' for k, v in pairs)


def write_b64(out: TextIO, src: BinaryIO) -> None:
    """Zawartość `src` jako base64 do `out` kawałkami (bez całego załącznika w pamięci)."""
    while chunk := src.read(B64_CHUNK):
        out.write(base64.b64encode(chunk).decode("ascii"))


def _write_xml(out, msgs, parts_by_msg, addr_cache, names, att_dir, files) -> None:
    out.write("<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n")
    out.write("<!-- Generated by AdMeNot; SMS Backup & Restore (SyncTech) compatible format. "
              "Attachments also as files in mms_parts/ -->\n")
    out.write(f'<smses count="{len(msgs)}" backup_set="{uuid.uuid4()}" '
              f'backup_date="{int(time.time() * 1000)}" type="full">\n')
    for m in msgs:
        addrs = addr_cache.get(m["_id"], [])
        address = message_address(m.get("msg_box"), addrs)
        nm = [names.get(phone_key(a)) for a in address.split("~") if a]
        contact = ", ".join(n for n in nm if n) or "(Unknown)"
        date = _ms(m.get("date"))
        pairs = [("date", date)] + [(k, _ms(m.get(k)) if k == "date_sent" else m.get(k)) for k in _MSG_ATTRS]
        pairs += [("address", address), ("readable_date", _readable(date)), ("contact_name", contact)]
        out.write(f"  <mms {_attrs(pairs)}>\n    <parts>\n")
        for p in parts_by_msg.get(m["_id"], []):
            out.write("      <part " + _attrs([(k, p.get(k)) for k in _PART_ATTRS] + [("text", p.get("text"))]))
            fname = files.get(p["_id"])
            path = os.path.join(att_dir, fname) if fname else None
            if path and os.path.isfile(path):
                out.write(' data="')
                with open(path, "rb") as f:
                    write_b64(out, f)
                out.write('"')
            out.write(" />\n")
        out.write("    </parts>\n    <addrs>\n")
        for a in addrs:
            out.write("      <addr " + _attrs([("address", a.get("address")), ("type", a.get("type")),
                                               ("charset", a.get("charset"))]) + " />\n")
        out.write("    </addrs>\n  </mms>\n")
    out.write("</smses>\n")


def mms_stats(adb: AdbTransport) -> tuple[int, int]:
    """(liczba MMS, łączny m_size w bajtach) – do szacowania miejsca w skanie."""
    rows = content_query(adb, MMS_URI, ["_id", "m_size"])
    total = 0
    for r in rows:
        try:
            total += int(r.get("m_size") or 0)
        except ValueError:
            pass
    return len(rows), total
