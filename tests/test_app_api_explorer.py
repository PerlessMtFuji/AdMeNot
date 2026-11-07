"""Most GUI ↔ eksplorator plików: sesja (blokada telefonu), przeglądanie, podgląd, tworzenie."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from apphelpers import NOW, make_api
from conftest import GETPROP_OUT, SERIAL
from exifbuild import ASCII, RATIONAL, build_exif, jpeg_bytes, segment, with_segments
from fakephone import make_cli_phone
from faketransfer import FakeStoragePhone, PhoneHost, TransferPhone

from admenot.app import explorer_api
from admenot.engine.adb.sessionlog import session_log_path
from admenot.engine.device.info import GETPROP
from admenot.engine.explorer.plan import TaskPlan, phone_free_bytes
from admenot.engine.explorer.queue import read_tmp_folders, record_tmp_folder
from admenot.engine.oplock import DeviceBusy, device_lock
from admenot.engine.paths import journal_path, logs_dir, telemetry_path
from admenot.engine.settings import (
    EXPLORER_RECENT_MAX,
    EXPLORER_RECENT_PHONES,
    load_settings,
    save_internal,
)
from admenot.engine.transfer.puller import RealPuller

OTHER = "R58W20NEW01"
MTIME = 1_700_000_000
TMP_PART = ".admenot-0123456789ab.part"
TEXT_PL = "Zażółć gęślą jaźń — notatka klienta"


def _photo() -> bytes:
    gps = [(1, ASCII, "N"), (2, RATIONAL, [(52, 1), (13, 1), (472, 10)]),
           (3, ASCII, "E"), (4, RATIONAL, [(21, 1), (0, 1), (421, 10)])]
    return with_segments(jpeg_bytes(), [segment(0xE1, build_exif([(0x010F, ASCII, "OPPO")], None, gps))])


FILES = {
    "DCIM/Camera/IMG_Ąę 1.jpg": _photo(),
    "DCIM/Camera/.hidden.jpg": b"x",
    "Download/notatka Łódź.txt": TEXT_PL.encode("cp1250"),
    "Download/faktura.pdf": b"%PDF-1.4",
    "Music/piosenka.mp3": b"M" * 40,
    "Android/media/com.whatsapp/WhatsApp/Media/a.jpg": b"W",
    "Android/data/com.example/cache.bin": b"d",
}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))


def _storage(root: Path, serial: str, files: dict[str, bytes]) -> FakeStoragePhone:
    for rel, data in files.items():
        path = root / "sdcard" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (MTIME, MTIME))
    storage = FakeStoragePhone(root, serial=serial)
    storage.deny_list_prefixes = {"/sdcard/Android/data"}  # Android 11+ bez dostępu (sonda kłódki)
    return storage


def _host(tmp_path: Path, *, other: bool = False) -> PhoneHost:
    ours = TransferPhone(make_cli_phone(), _storage(tmp_path / "phone", SERIAL, FILES))
    if not other:
        return PhoneHost(ours)
    cli = make_cli_phone()
    cli.static[GETPROP] = GETPROP_OUT.replace("SM-A145R", "SM-A546B").replace(SERIAL, OTHER)
    host = PhoneHost(ours, TransferPhone(cli, _storage(tmp_path / "other", OTHER, {})))
    host.connected = {SERIAL}
    return host


def _api(host: PhoneHost, **kw):
    kw.setdefault("puller_factory", lambda adb_path, serial, log: host.phone(serial))
    kw.setdefault("pusher_factory", lambda adb_path, serial, log: host.phone(serial))
    return make_api(host, **kw)


def _opened(tmp_path: Path, **kw):
    host = _host(tmp_path, other=kw.pop("other", False))
    api, rec = _api(host, **kw)
    opened = api.explorer_open(SERIAL)
    assert "error" not in opened, opened
    return api, rec, host, opened


def _storage_of(host: PhoneHost, serial: str = SERIAL) -> FakeStoragePhone:
    return host.phone(serial).storage


def _lock_free(serial: str = SERIAL) -> bool:
    try:
        with device_lock(journal_path(), serial):
            return True
    except DeviceBusy:
        return False


def _wait_idle(api, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while api._jobs.current() is not None:
        assert time.monotonic() < deadline, "zadanie się nie skończyło"
        time.sleep(0.02)


def test_open_returns_session_and_counts_places(tmp_path):
    _, rec, _, opened = _opened(tmp_path)
    assert opened["device"]["serial"] == SERIAL and opened["sdk"] == 34 and opened["leftovers"] == 0
    assert opened["media"].startswith("http://127.0.0.1:") and opened["media"].endswith("/TOKEN")
    keys = [p["key"] for p in opened["places"]]
    assert keys == ["camera", "downloads", "whatsapp", "music", "all"]
    assert all(p["count"] is None for p in opened["places"])
    counted = rec.of("explorer:places")[-1]["places"]
    assert {p["key"]: p["count"] for p in counted} == {"camera": 1, "downloads": 2, "whatsapp": 1,
                                                       "music": 1, "all": 6}


def test_storage_groups(tmp_path):
    host = _host(tmp_path)
    storage = _storage_of(host)
    storage.total_kb, storage.free_kb = 1000, 400
    movie = storage.root / "sdcard" / "Movies" / "film.mp4"
    movie.parent.mkdir(parents=True)
    movie.write_bytes(b"F" * 2048)
    api, _ = _api(host)
    api.explorer_open(SERIAL)
    got = api.explorer_storage()
    groups = got["groups"]
    assert got["total"] == 1000 * 1024 and got["used"] == 600 * 1024
    assert groups["photos"] == len(_photo()) + 1 and groups["videos"] == 2048 and groups["whatsapp"] == 1
    assert groups["other"] == got["used"] - groups["photos"] - 2048 - 1  # ukryte pliki też zajmują miejsce
    api.explorer_close()


def test_storage_requires_open_explorer(tmp_path):
    api, _ = _api(_host(tmp_path))
    assert api.explorer_storage()["error"]["key"] == "explorer_not_open"


def test_storage_event_after_upload_to_phone(tmp_path):
    api, rec, _, _ = _opened(tmp_path)
    assert not rec.of("explorer:storage")
    local = _pc_dir(tmp_path, "z komputera")
    (local / "a.jpg").write_bytes(b"J" * 10)
    started = api.explorer_upload([str(local / "a.jpg")], "/sdcard/Download")
    _wait_task(api, started["task"], "done")
    deadline = time.monotonic() + 5
    while not rec.of("explorer:storage") and time.monotonic() < deadline:
        time.sleep(0.02)
    event = rec.of("explorer:storage")[-1]
    assert set(event) == {"total", "used", "free", "groups"} and set(event["groups"]) == {"photos", "videos", "whatsapp", "other"}
    api.explorer_close()


def test_place_count_failure_leaves_place_without_count(tmp_path):
    host = _host(tmp_path)
    _storage_of(host).deny_list_prefixes |= {"/sdcard/Music"}
    api, rec = _api(host)
    assert "error" not in api.explorer_open(SERIAL)
    counted = {p["key"]: p["count"] for p in rec.of("explorer:places")[-1]["places"]}
    assert counted["music"] is None and counted["camera"] == 1


def test_open_takes_device_lock(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    assert not _lock_free()
    assert api.start_scan(SERIAL, None)["error"] == {"key": "busy", "message": "explorer"}
    assert api.transfer_inventory(SERIAL, None)["error"]["key"] == "busy"
    assert api.explorer_close() == {}
    assert _lock_free()
    assert "job_id" in api.start_scan(SERIAL, None)


def test_open_busy_when_lock_held_elsewhere(tmp_path):
    api, _ = _api(_host(tmp_path))
    with device_lock(journal_path(), SERIAL):  # inne okno albo CLI wykonuje zlecenie
        assert api.explorer_open(SERIAL)["error"]["key"] == "explorer_busy"
    assert "error" not in api.explorer_open(SERIAL)


def test_open_busy_when_backup_running(tmp_path):
    host = _host(tmp_path)
    api, _ = _api(host, sync=False)
    assert "job_id" in api.transfer_inventory(SERIAL, None)
    _wait_idle(api)
    started, gate = threading.Event(), threading.Event()

    def hold(remotes):
        started.set()
        gate.wait(10)

    _storage_of(host).before_pull = hold
    selection = {"contacts": False, "sms": False, "mms": False, "calls": False,
                 "categories": ["media"], "others": [], "apps": []}
    assert "job_id" in api.start_backup(selection)
    assert started.wait(10)
    try:
        assert api.explorer_open(SERIAL)["error"]["key"] == "explorer_busy"
    finally:
        gate.set()
        _wait_idle(api)
    assert "error" not in api.explorer_open(SERIAL)
    api.explorer_close()


def test_list_and_crumbs(tmp_path):
    api, _, _, opened = _opened(tmp_path)
    name = opened["device"]["name"]
    camera = api.explorer_list("/sdcard/DCIM/Camera/")
    assert camera["path"] == "/sdcard/DCIM/Camera" and camera["locked"] is False and camera["skipped"] == 0
    assert camera["crumbs"] == [{"label": name, "path": "/sdcard"}, {"label": "DCIM", "path": "/sdcard/DCIM"},
                                {"label": "Camera", "path": "/sdcard/DCIM/Camera"}]
    [photo] = camera["entries"]  # ukryty plik niewidoczny
    assert (photo["name"], photo["kind"], photo["type"], photo["ext"]) == ("IMG_Ąę 1.jpg", "file", "image", "jpg")
    assert photo["mtime"] == MTIME and photo["thumb"].startswith(opened["media"] + "/thumb?p=")
    assert photo["url"].startswith(opened["media"] + "/file?p=")
    wa = api.explorer_list("/sdcard/Android/media/com.whatsapp")
    assert wa["crumbs"][-1] == {"label": "WhatsApp", "path": "/sdcard/Android/media/com.whatsapp"}
    downloads = {e["name"]: e for e in api.explorer_list("/sdcard/Download")["entries"]}
    assert downloads["faktura.pdf"]["type"] == "doc"
    assert downloads["faktura.pdf"]["url"].startswith(opened["media"] + "/file?p=")
    assert downloads["notatka Łódź.txt"]["type"] == "text" and downloads["notatka Łódź.txt"]["thumb"] is None
    root = api.explorer_list("/sdcard")
    assert root["crumbs"] == [{"label": name, "path": "/sdcard"}]
    assert {e["name"] for e in root["entries"] if e["kind"] == "dir"} >= {"DCIM", "Download", "Android"}
    # „Ostatnio”: najnowszy pierwszy, bez korzenia pamięci, osobno dla tego telefonu
    assert load_settings().explorer_recents == {SERIAL: ["/sdcard/Download", "/sdcard/Android/media/com.whatsapp",
                                                         "/sdcard/DCIM/Camera"]}


def test_list_denied_folder(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    data = next(e for e in api.explorer_list("/sdcard/Android")["entries"] if e["name"] == "data")
    assert data["locked"] is True
    inside = api.explorer_list("/sdcard/Android/data")
    assert inside["entries"] == [] and inside["locked"] is True
    assert "/sdcard/Android/data" not in load_settings().explorer_recents.get(SERIAL, [])
    assert api.explorer_list("/sdcard/Nie ma")["error"]["key"] == "explorer_missing"
    assert api.explorer_list("/sdcard/../data")["error"]["key"] == "bad_request"
    api.explorer_close()
    assert api.explorer_list("/sdcard")["error"]["key"] == "explorer_not_open"


def test_meta_photo_has_gps(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    meta = api.explorer_meta("/sdcard/DCIM/Camera/IMG_Ąę 1.jpg")["meta"]
    assert meta["gps"]["lat"] == pytest.approx(52.229778, abs=1e-6)
    assert meta["gps"]["lon"] == pytest.approx(21.011694, abs=1e-6)
    assert meta["Make"] == "OPPO" and (meta["width"], meta["height"]) == (320, 240)
    assert (meta["size"], meta["mtime"], meta["path"]) == (len(FILES["DCIM/Camera/IMG_Ąę 1.jpg"]), MTIME,
                                                           "/sdcard/DCIM/Camera/IMG_Ąę 1.jpg")
    assert api.explorer_meta("/sdcard/DCIM/Camera/brak.jpg")["error"]["key"] == "explorer_missing"


def test_open_map_url(tmp_path):
    opened: list[str] = []
    api, _ = _api(_host(tmp_path), open_url=opened.append)
    assert api.explorer_open_map(52.229778, 21.011694) == {}
    assert opened == ["https://www.openstreetmap.org/?mlat=52.229778&mlon=21.011694#map=17/52.229778/21.011694"]
    assert api.explorer_open_map(True, 0)["error"]["key"] == "bad_request"
    assert api.explorer_open_map(91, 0)["error"]["key"] == "bad_request"


def test_text_cp1250(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    got = api.explorer_text("/sdcard/Download/notatka Łódź.txt")
    assert got == {"text": TEXT_PL, "encoding": "cp1250", "truncated": False}
    assert api.explorer_text("/sdcard/Download")["error"]["key"] == "bad_request"


def test_text_more_reads_next_chunk(tmp_path, monkeypatch):
    monkeypatch.setattr(explorer_api, "TEXT_LIMIT", 8)
    api, _, host, _ = _opened(tmp_path)
    body = "ąęść żółw " * 2  # znaki dwubajtowe tną się na granicy kawałka
    path = _storage_of(host).local("/sdcard/Download/długi.txt")
    path.write_bytes(body.encode("utf-8"))
    parts, more = [], False
    while True:
        got = api.explorer_text("/sdcard/Download/długi.txt", more)
        assert got["encoding"] == "utf-8"
        parts.append(got["text"])
        more = True
        if not got["truncated"]:
            break
    assert "".join(parts) == body and len(parts) > 2


def test_text_head_is_light_and_leaves_the_reader_alone(tmp_path):
    api, _, host, _ = _opened(tmp_path)
    storage = _storage_of(host)
    body = "ąę żółw " * 4000  # znaki dwubajtowe: 16 KB tnie się w środku znaku
    storage.local("/sdcard/Download/długi.txt").write_bytes(body.encode("utf-8"))
    api.explorer_text("/sdcard/Download/długi.txt")
    state = api._explorer.text
    previews = dict(api._explorer.stats.previews)

    got = api.explorer_text_head("/sdcard/Download/długi.txt")
    assert got["truncated"] is True and body.startswith(got["text"])
    assert 0 < len(got["text"].encode("utf-8")) <= 16 * 1024 and "�" not in got["text"]
    short = api.explorer_text_head("/sdcard/Download/notatka Łódź.txt")
    assert short == {"text": TEXT_PL, "truncated": False}
    assert api.explorer_text_head("/sdcard/Download")["error"]["key"] == "bad_request"
    assert api._explorer.text == state  # czytnik pełnego tekstu nietknięty
    assert dict(api._explorer.stats.previews) == previews  # a podgląd w dymku się nie liczy


def test_failed_text_head_is_not_a_session_error(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    assert api.explorer_text_head("/sdcard/Download")["error"]["key"] == "bad_request"
    assert api.explorer_text_head("/sdcard/Download/nie ma.txt")["error"]["key"] == "explorer_missing"
    assert not api._explorer.stats.errors  # najechanie to nie działanie serwisanta
    assert api.explorer_text("/sdcard/Download/nie ma.txt")["error"]["key"] == "explorer_missing"
    assert api._explorer.stats.errors == {"explorer_missing": 1}  # zwykłe odczyty liczą się dalej


def test_sheet_reads_every_sheet_and_head_only_the_first(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.title = "Faktury"
    wb.active.append(["Nr", "Kwota"])
    wb.active.append(["F/1", 12.5])
    wb.create_sheet("Notatki")["A1"] = "zażółć"
    api, _, host, _ = _opened(tmp_path)
    wb.save(_storage_of(host).local("/sdcard/Download/zestawienie.xlsx"))
    previews = dict(api._explorer.stats.previews)

    got = api.explorer_sheet("/sdcard/Download/zestawienie.xlsx")
    assert got == {"sheets": [
        {"name": "Faktury", "rows": [["Nr", "Kwota"], ["F/1", "12.5"]], "truncated": False, "hidden": False},
        {"name": "Notatki", "rows": [["zażółć"]], "truncated": False, "hidden": False},
    ], "delimiter": None, "encoding": None}
    head = api.explorer_sheet_head("/sdcard/Download/zestawienie.xlsx")
    assert head == {"names": ["Faktury", "Notatki"], "rows": [["Nr", "Kwota"], ["F/1", "12.5"]], "truncated": False}
    assert dict(api._explorer.stats.previews) == previews  # arkusze nie mają klucza w telemetrii (jak PDF)


def test_sheet_csv_and_problems(tmp_path, monkeypatch):
    api, _, host, _ = _opened(tmp_path)
    storage = _storage_of(host)
    storage.local("/sdcard/Download/lista.csv").write_bytes("Klient;Kwota\r\nŁódź;1,5\r\n".encode("cp1250"))
    got = api.explorer_sheet("/sdcard/Download/lista.csv")
    assert got["sheets"][0]["rows"] == [["Klient", "Kwota"], ["Łódź", "1,5"]]
    assert (got["delimiter"], got["encoding"]) == (";", "cp1250")

    storage.local("/sdcard/Download/strona.xls").write_bytes(b"<html><table></table></html>")
    assert api.explorer_sheet("/sdcard/Download/strona.xls") == {"problem": "unreadable"}
    monkeypatch.setattr(explorer_api, "HEAD_BYTES", 4)
    assert api.explorer_sheet_head("/sdcard/Download/lista.csv") == {"problem": "too_big"}
    assert api.explorer_sheet("/sdcard/Download")["error"]["key"] == "bad_request"
    assert api.explorer_sheet_head("/sdcard/Download/nie ma.csv")["error"]["key"] == "explorer_missing"
    assert api._explorer.stats.errors == {"bad_request": 1}  # tylko pełny podgląd; dymek błędów nie liczy


def test_mkdir_and_new_text(tmp_path):
    api, _, host, _ = _opened(tmp_path)
    storage = _storage_of(host)
    assert api.explorer_mkdir("/sdcard/Download", "Nowy folder") == {"path": "/sdcard/Download/Nowy folder"}
    assert storage.local("/sdcard/Download/Nowy folder").is_dir()
    assert api.explorer_mkdir("/sdcard/Download", "Nowy folder")["error"]["key"] == "explorer_exists"
    assert api.explorer_mkdir("/sdcard/Download", "a/b")["error"]["key"] == "explorer_bad_name"
    assert api.explorer_mkdir("/data/local", "x")["error"]["key"] == "explorer_bad_name"
    made = api.explorer_new_text("/sdcard/Download", "Lista zakupów", "mleko\r\nchleb")
    assert made == {"path": "/sdcard/Download/Lista zakupów.txt"}
    assert storage.local(made["path"]).read_bytes() == b"mleko\nchleb"
    again = api.explorer_new_text("/sdcard/Download", "Lista zakupów.txt", "inna treść")
    assert again["error"]["key"] == "explorer_exists"
    assert storage.local(made["path"]).read_bytes() == b"mleko\nchleb"
    storage.deny_prefixes = {"/sdcard/Music/"}
    assert api.explorer_mkdir("/sdcard/Music", "Nowy")["error"]["key"] == "explorer_denied"
    assert not any(p.name.startswith(".admenot-") for p in storage.local("/sdcard").rglob("*"))
    assert read_tmp_folders(SERIAL) == []


def test_offline_then_same_phone_back_refreshes(tmp_path):
    api, rec, host, _ = _opened(tmp_path)
    storage = _storage_of(host)
    host.connected.discard(SERIAL)
    storage.online = False
    api.list_devices()
    assert rec.of("explorer:offline") == [{"serial": SERIAL}]
    assert api.explorer_list("/sdcard/DCIM")["error"]["key"] == "explorer_offline"
    api.list_devices()
    assert len(rec.of("explorer:offline")) == 1  # zdarzenie tylko przy zmianie
    assert not _lock_free()  # blokada trwa: telefon może wrócić
    host.connected.add(SERIAL)
    storage.reconnect()
    api.list_devices()
    assert rec.of("explorer:online") == [{"serial": SERIAL}]
    assert [e["name"] for e in api.explorer_list("/sdcard/DCIM/Camera")["entries"]] == ["IMG_Ąę 1.jpg"]


def test_other_phone_back_closes(tmp_path):
    api, rec, host, _ = _opened(tmp_path, other=True)
    host.connected.discard(SERIAL)
    _storage_of(host).online = False
    api.list_devices()
    assert rec.of("explorer:offline") == [{"serial": SERIAL}]
    host.connected.add(OTHER)
    api.list_devices()
    assert rec.of("explorer:closed") == [{"serial": SERIAL, "reason": "other_phone"}]
    assert api.explorer_list("/sdcard")["error"]["key"] == "explorer_not_open"
    assert _lock_free()


def test_close_cleans_temp_and_stops_queue(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    temp = api._explorer_temp
    temp.mkdir(parents=True, exist_ok=True)
    (temp / "podglad.bin").write_bytes(b"x")
    queue = api._explorer_queue()
    assert queue.serial == SERIAL and api._explorer_queue() is queue
    assert api.explorer_close() == {}
    assert not temp.exists()
    with pytest.raises(RuntimeError):
        queue.add(TaskPlan("to_pc", [], [], 0, []))  # zamknięta kolejka nie przyjmuje zadań
    assert api.explorer_close() == {}  # ponowne zamknięcie nic nie robi
    temp.mkdir(parents=True)
    (temp / "stary.bin").write_bytes(b"x")
    _api(_host(tmp_path / "again"))  # start programu też czyści
    assert not temp.exists()


def test_shutdown_closes_explorer(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    api._shutdown()
    assert api._explorer is None and _lock_free()


def test_open_sweeps_leftovers_except_live_queue_folders(tmp_path):
    host = _host(tmp_path)
    storage = _storage_of(host)
    for folder in ("/sdcard/Download", "/sdcard/Music"):
        storage.local(f"{folder}/{TMP_PART}").write_bytes(b"part")
        record_tmp_folder(SERIAL, folder)
    api, _ = _api(host)
    api.explorer_open(SERIAL)
    api.explorer_close()
    record_tmp_folder(SERIAL, "/sdcard/Download")
    storage.local(f"/sdcard/Download/{TMP_PART}").write_bytes(b"part")
    storage.local(f"/sdcard/Music/{TMP_PART}").write_bytes(b"part")
    record_tmp_folder(SERIAL, "/sdcard/Music")
    opened = api.explorer_open(SERIAL)
    assert opened["leftovers"] == 2 and read_tmp_folders(SERIAL) == []
    # ponowne otwarcie w trakcie wgrywania: folder pilnowany przez kolejkę zostaje
    queue = api._explorer_queue()
    queue._folders["/sdcard/Music"] = 1
    storage.local(f"/sdcard/Music/{TMP_PART}").write_bytes(b"part")
    storage.local(f"/sdcard/Download/{TMP_PART}").write_bytes(b"part")
    record_tmp_folder(SERIAL, "/sdcard/Music")
    record_tmp_folder(SERIAL, "/sdcard/Download")
    again = api.explorer_open(SERIAL)
    assert again["leftovers"] == 1 and api._explorer_queue() is queue
    assert storage.local(f"/sdcard/Music/{TMP_PART}").exists()
    assert not storage.local(f"/sdcard/Download/{TMP_PART}").exists()
    assert read_tmp_folders(SERIAL) == ["/sdcard/Music"]
    queue._folders.clear()
    api.explorer_close()


def test_no_paths_in_session_log(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    api.explorer_list("/sdcard/DCIM/Camera")
    api.explorer_meta("/sdcard/DCIM/Camera/IMG_Ąę 1.jpg")
    api.explorer_meta("/sdcard/Music/piosenka.mp3")
    api.explorer_text("/sdcard/Download/notatka Łódź.txt")
    api.explorer_mkdir("/sdcard/Download", "Folder Kowalskiego")
    api.explorer_new_text("/sdcard/Download", "Notatka Kowalskiego", "treść")
    api.explorer_close()
    log = session_log_path(logs_dir(), NOW).read_text("utf-8")
    assert "find " in log and "dd if=" in log  # polecenia są, ścieżki zwinięte
    for secret in ("IMG_", "Camera", "piosenka", "Łódź", "notatka", "Kowalskiego", "Download", "Music"):
        assert secret not in log, secret


def _wait_lock_free(timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not _lock_free():
        assert time.monotonic() < deadline, "blokada telefonu nie zwolniona"
        time.sleep(0.02)


def test_shutdown_does_not_wait_for_busy_queue_worker(tmp_path):
    """Okno zamyka się od razu; blokadę telefonu zwalnia dopiero koniec wątku kolejki (np. `sha256sum`)."""
    api, _, _, _ = _opened(tmp_path)
    queue = api._explorer_queue()
    gate = threading.Event()
    queue._worker = threading.Thread(target=gate.wait, args=(10,), daemon=True)  # wątek w długim kroku
    queue._worker.start()
    api._sync = False  # jak w oknie: bez czekania
    started = time.monotonic()
    try:
        api._shutdown()
        assert time.monotonic() - started < 2
        assert api._explorer is None and not _lock_free()
        assert api.explorer_open(SERIAL)["error"] == {"key": "explorer_busy", "message": "device"}
    finally:
        gate.set()
    _wait_lock_free()


def test_open_other_phone_while_busy_keeps_session(tmp_path):
    api, rec, host, _ = _opened(tmp_path, other=True)
    host.connected.add(OTHER)
    api._jobs._current = SimpleNamespace(kind="scan")  # trwa zadanie
    try:
        assert api.explorer_open(OTHER)["error"] == {"key": "explorer_busy", "message": "scan"}
    finally:
        api._jobs._current = None
    assert api._explorer.serial == SERIAL and not rec.of("explorer:closed")
    assert "error" not in api.explorer_open(OTHER)
    assert rec.of("explorer:closed") == [{"serial": SERIAL, "reason": "switched"}]
    assert _lock_free(SERIAL) and not _lock_free(OTHER)
    api.explorer_close()


def test_apk_analysis_refused_while_explorer_open(tmp_path):
    host = _host(tmp_path)
    api, _ = _api(host)
    assert "job_id" in api.start_scan(SERIAL, None)
    assert "error" not in api.explorer_open(SERIAL)
    busy = {"key": "busy", "message": "explorer"}
    assert api.deep_analyze("com.clean.pro.boost")["error"] == busy
    assert api.analyze_selected(["com.clean.pro.boost"])["error"] == busy
    assert api.analyze_all()["error"] == busy
    api.explorer_close()
    assert "job_id" in api.analyze_all()


def test_presence_close_failure_keeps_device_list(tmp_path, monkeypatch):
    api, rec, host, _ = _opened(tmp_path, other=True)
    host.connected.discard(SERIAL)
    _storage_of(host).online = False
    api.list_devices()

    def broken(*args, **kwargs):
        raise RuntimeError("close failed")

    monkeypatch.setattr(api, "_explorer_end", broken)
    host.connected.add(OTHER)
    listed = api.list_devices()
    assert listed["error"] is None and [d["serial"] for d in listed["devices"]] == [OTHER]
    assert rec.of("explorer:closed") == [{"serial": SERIAL, "reason": "other_phone"}]


def test_place_count_unexpected_error_skips_only_that_place(tmp_path, monkeypatch):
    real = explorer_api.count_place

    def count(adb, place):
        if place.key == "music":
            raise RuntimeError("boom")
        return real(adb, place)

    monkeypatch.setattr(explorer_api, "count_place", count)
    _, rec, _, _ = _opened(tmp_path)
    counted = {p["key"]: p["count"] for p in rec.of("explorer:places")[-1]["places"]}
    assert counted["music"] is None and counted["all"] == 6


def test_unexpected_error_log_has_no_paths(tmp_path, monkeypatch):
    api, _, _, _ = _opened(tmp_path)

    secret = "Tajne zdjęcie.jpg"  # nie w linii z raise: traceback pokazuje linię źródła

    def broken(adb, path, **kw):
        raise RuntimeError(f"cannot read '{path}/{secret}'")

    monkeypatch.setattr(explorer_api, "list_dir", broken)
    error = api.explorer_list("/sdcard/DCIM/Kowalski")["error"]
    assert error["key"] == "internal"
    text = Path(error["log"]).read_text("utf-8")
    assert "RuntimeError" in text and "Tajne" not in text and "Kowalski" not in text


# --- Task 9: kopiowanie i wgrywanie, upuszczanie, schowek, telemetria ---------------------------


def _wait_task(api, tid: str, *statuses: str) -> dict:
    api._explorer.queue.wait_for(tid, *statuses)
    return next(t for t in api.explorer_tasks()["tasks"] if t["id"] == tid)


def _pc_dir(tmp_path: Path, name: str = "pc") -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_copy_uses_saved_dest(tmp_path):
    api, rec, _, _ = _opened(tmp_path)
    assert api.explorer_copy(["/sdcard/Download/faktura.pdf"])["error"]["key"] == "explorer_no_dest"
    pc = _pc_dir(tmp_path)
    api._attach(pick_folder=lambda: str(pc), close=lambda: None)
    assert api.explorer_pick_dest() == {"path": str(pc)}
    assert load_settings().explorer_dest == str(pc)
    started = api.explorer_copy(["/sdcard/Download/faktura.pdf", "/sdcard/DCIM/Camera"])
    task = _wait_task(api, started["task"], "done")
    assert (pc / "faktura.pdf").read_bytes() == b"%PDF-1.4"
    assert (pc / "Camera" / "IMG_Ąę 1.jpg").is_file() and (pc / "Camera" / ".hidden.jpg").is_file()
    assert task["kind"] == "to_pc" and task["status"] == "done" and task["done_files"] == 3
    assert task["dest"] == str(pc) and task["failed"] == []
    assert rec.of("explorer:task")[-1]["task"]["status"] == "done"
    other = _pc_dir(tmp_path, "inny")  # jawny folder docelowy też zostaje zapamiętany
    again = api.explorer_copy(["/sdcard/Download/faktura.pdf"], str(other), True)
    assert _wait_task(api, again["task"], "done")["verified"] == "hash"
    assert (other / "faktura.pdf").is_file() and load_settings().explorer_dest == str(other)
    missing = api.explorer_copy(["/sdcard/Download/faktura.pdf"], str(tmp_path / "brak"))
    assert missing["error"]["key"] == "explorer_no_dest"
    assert api.explorer_copy([], str(pc))["error"]["key"] == "bad_request"
    assert api.explorer_copy(["/data/local/x"], str(pc))["error"]["key"] == "bad_request"
    assert api.explorer_copy(["/sdcard/Download/faktura.pdf"], str(pc), "tak")["error"]["key"] == "bad_request"
    api.explorer_close()


def test_copy_problems_returned_before_start(tmp_path, monkeypatch):
    real = explorer_api.plan_to_pc
    monkeypatch.setattr(explorer_api, "plan_to_pc",
                        lambda adb, paths, dest, **kw: real(adb, paths, dest, free_bytes=lambda p: 3, **kw))
    api, rec, _, _ = _opened(tmp_path)
    pc = _pc_dir(tmp_path)
    out = api.explorer_copy(["/sdcard/Download/faktura.pdf"], str(pc))
    assert out == {"problems": [{"key": "no_space", "detail": {"need": 8, "free": 3, "missing": 5}}]}
    assert api.explorer_tasks() == {"tasks": []} and not rec.of("explorer:task")
    assert not (pc / "faktura.pdf").exists()
    local = _pc_dir(tmp_path, "z komputera")
    (local / "a.txt").write_bytes(b"a")
    denied = api.explorer_upload([str(local / "a.txt")], "/sdcard/Android/data")
    assert denied == {"problems": [{"key": "denied", "detail": {"paths": ["/sdcard/Android/data"]}}]}
    assert api.explorer_tasks() == {"tasks": []}
    api.explorer_close()


def test_upload_task_events(tmp_path):
    api, rec, host, _ = _opened(tmp_path)
    local = _pc_dir(tmp_path, "z komputera")
    (local / "zdjęcie.jpg").write_bytes(b"J" * 10)
    (local / "Folder").mkdir()
    (local / "Folder" / "b.txt").write_bytes(b"bb")
    started = api.explorer_upload([str(local / "zdjęcie.jpg"), str(local / "Folder")], "/sdcard/Download")
    task = _wait_task(api, started["task"], "done")
    storage = _storage_of(host)
    assert storage.local("/sdcard/Download/zdjęcie.jpg").read_bytes() == b"J" * 10
    assert storage.local("/sdcard/Download/Folder/b.txt").read_bytes() == b"bb"
    assert task["kind"] == "to_phone" and task["done_files"] == 2 and task["dest"] == "/sdcard/Download"
    statuses = [e["task"]["status"] for e in rec.of("explorer:task") if e["task"]["id"] == started["task"]]
    assert statuses[0] == "queued" and "running" in statuses and statuses[-1] == "done"
    assert api.explorer_upload([str(local / "zdjęcie.jpg")], "/data/local")["error"]["key"] == "bad_request"
    assert api.explorer_upload(["względna.txt"], "/sdcard/Download")["error"]["key"] == "bad_request"
    assert api.explorer_upload("C:\\x", "/sdcard/Download")["error"]["key"] == "bad_request"
    api.explorer_close()


def test_upload_offline_df_maps_to_offline(tmp_path, monkeypatch):
    from admenot.engine.adb.transport import AdbError

    def offline(*args, **kwargs):
        raise AdbError("offline", "device offline")

    api, _, host, _ = _opened(tmp_path)
    local = _pc_dir(tmp_path, "z komputera")
    (local / "a.txt").write_bytes(b"a")
    monkeypatch.setattr(explorer_api, "plan_to_phone", offline)
    _storage_of(host).online = False
    assert api.explorer_upload([str(local / "a.txt")], "/sdcard/Download")["error"]["key"] == "explorer_offline"
    api.explorer_close()


class _GatedPusher:
    """`adb push` czekający na sygnał — pierwsze zadanie trwa, kolejne czekają w kolejce."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.gate = threading.Event()
        self.entered = threading.Event()

    def push(self, *args, **kwargs):
        self.entered.set()
        self.gate.wait(10)
        return self.inner.push(*args, **kwargs)


def test_pause_resume_cancel_roundtrip(tmp_path):
    host = _host(tmp_path)
    gated = _GatedPusher(host.phone(SERIAL))
    api, _ = _api(host, pusher_factory=lambda adb_path, serial, log: gated)
    api.explorer_open(SERIAL)
    local = _pc_dir(tmp_path, "z komputera")
    (local / "a.txt").write_bytes(b"a")
    (local / "b.txt").write_bytes(b"b")
    first = api.explorer_upload([str(local / "a.txt")], "/sdcard/Download")["task"]
    assert gated.entered.wait(5)
    second = api.explorer_upload([str(local / "b.txt")], "/sdcard/Music")["task"]
    try:
        assert api.explorer_pause(second) == {}
        assert _wait_task(api, second, "paused")["status"] == "paused"
        assert api.explorer_resume(second) == {}
        assert _wait_task(api, second, "queued")["status"] == "queued"
        assert api.explorer_cancel(second) == {}
        assert _wait_task(api, second, "cancelled")["status"] == "cancelled"
        assert api.explorer_cancel(first) == {}
    finally:
        gated.gate.set()
    assert _wait_task(api, first, "cancelled")["status"] == "cancelled"
    assert not _storage_of(host).local("/sdcard/Music/b.txt").exists()
    assert api.explorer_pause("t999") == {}  # nieznane zadanie: nic
    assert api.explorer_cancel(7)["error"]["key"] == "bad_request"
    api.explorer_close()
    assert api.explorer_tasks()["error"]["key"] == "explorer_not_open"


def test_pick_upload_and_tasks_without_queue(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    assert api.explorer_tasks() == {"tasks": []}
    assert api.explorer_pick_upload("files") == {"paths": []}  # bez okna
    api._attach(pick_folder=lambda: "C:\\Zdjęcia", close=lambda: None,
                pick_files=lambda: ["C:\\a.jpg", "C:\\b.jpg"])
    assert api.explorer_pick_upload("files") == {"paths": ["C:\\a.jpg", "C:\\b.jpg"]}
    assert api.explorer_pick_upload("folder") == {"paths": ["C:\\Zdjęcia"]}
    api._attach(pick_folder=lambda: None, close=lambda: None)
    assert api.explorer_pick_upload("folder") == {"paths": []}
    assert api.explorer_pick_upload("all")["error"]["key"] == "bad_request"
    api.explorer_close()


def test_clipboard_paths(tmp_path):
    copied = ["C:\\Users\\Jan\\Komputeł.xlsx", "C:\\Users\\Jan\\Loty - zdjęcia"]
    api, _, _, _ = _opened(tmp_path, explorer_clipboard=lambda: list(copied))
    assert api.explorer_clipboard() == {"paths": copied}
    copied.clear()
    assert api.explorer_clipboard() == {"paths": []}
    api.explorer_close()


def test_drop_event_only_when_open(tmp_path):
    local = _pc_dir(tmp_path, "upuszczone")
    (local / "a.jpg").write_bytes(b"a" * 100)
    (local / "Folder" / "sub").mkdir(parents=True)
    (local / "Folder" / "b.txt").write_bytes(b"b" * 20)
    (local / "Folder" / "sub" / "c.txt").write_bytes(b"c" * 3)
    dropped = [str(local / "a.jpg"), str(local / "Folder"), str(local / "zniknął.txt")]
    host = _host(tmp_path)
    api, rec = _api(host)
    api._explorer_drop(dropped)
    assert not rec.of("explorer:drop")
    api.explorer_open(SERIAL)
    api._explorer_drop(dropped)
    assert rec.of("explorer:drop") == [{"paths": dropped, "count": 3, "bytes": 123}]
    api._explorer_drop([])  # nic nie upuszczono (np. tekst z innej aplikacji)
    assert len(rec.of("explorer:drop")) == 1
    api.explorer_close()
    api._explorer_drop(dropped)
    assert len(rec.of("explorer:drop")) == 1


def test_open_folder_only_existing_pc_directory(tmp_path):
    opened: list[Path] = []
    api, _, _, _ = _opened(tmp_path, open_file=opened.append)
    pc = _pc_dir(tmp_path)
    (pc / "program.exe").write_bytes(b"MZ")
    assert api.explorer_open_folder(str(pc)) == {}
    assert opened == [pc]
    assert api.explorer_open_folder(str(pc / "program.exe"))["error"]["key"] == "explorer_not_folder"
    assert api.explorer_open_folder(str(pc / "brak"))["error"]["key"] == "explorer_not_folder"
    assert api.explorer_open_folder("pc")["error"]["key"] == "explorer_not_folder"  # względna
    assert api.explorer_open_folder(None)["error"]["key"] == "bad_request"
    assert opened == [pc]
    api.explorer_close()


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def test_explorer_event_has_no_paths(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    api.set_telemetry(True, False)
    pc = _pc_dir(tmp_path)
    local = _pc_dir(tmp_path, "z komputera")
    (local / "zdjęcie klienta.jpg").write_bytes(b"J" * 10)
    copied = api.explorer_copy(["/sdcard/Download/faktura.pdf", "/sdcard/Music/piosenka.mp3"], str(pc))
    _wait_task(api, copied["task"], "done")
    uploaded = api.explorer_upload([str(local / "zdjęcie klienta.jpg")], "/sdcard/Download")
    _wait_task(api, uploaded["task"], "done")
    api.explorer_meta("/sdcard/DCIM/Camera/IMG_Ąę 1.jpg")
    api.explorer_meta("/sdcard/Download")  # folder: to nie podgląd
    api.explorer_text("/sdcard/Download/notatka Łódź.txt")
    api.explorer_mkdir("/sdcard/Download", "Folder Kowalskiego")
    api.explorer_mkdir("/sdcard/Download", "Folder Kowalskiego")  # explorer_exists
    api.explorer_open_folder(str(pc / "brak"))
    api.explorer_close()
    events = [json.loads(x) for x in telemetry_path().read_text("utf-8").splitlines()]
    shown = [e for e in events if e["type"] == "explorer"]
    assert len(shown) == 1
    event = shown[0]
    assert event["device"]["android"] == "14"
    assert (event["copied_files"], event["uploaded_files"]) == (2, 1)
    assert event["previews"] == {"image": 1, "video": 0, "audio": 0, "text": 1}
    assert event["created"] == {"folder": 1, "text": 0}
    assert event["errors"] == {"explorer_exists": 1, "explorer_not_folder": 1}
    assert isinstance(event["seconds"], int)
    assert event["mb_s"] is None or isinstance(event["mb_s"], int)
    secrets = [*FILES, "faktura", "piosenka", "IMG_", "Łódź", "Kowalski", "zdjęcie", "klienta", str(tmp_path)]
    body = {k: v for k, v in event.items() if k not in ("install", "type", "t", "app", "os", "lang")}
    for text in _strings(body):
        assert "/" not in text and "\\" not in text, text
        assert not any(s in text for s in secrets), text


def test_explorer_event_counts_task_time_and_speed(tmp_path, monkeypatch):
    seen: list[tuple] = []
    real = explorer_api.explorer_event
    monkeypatch.setattr(explorer_api, "explorer_event", lambda *a: seen.append(a) or real(*a))
    ticks = iter(range(0, 1000, 2))
    api, _ = _api(_host(tmp_path))
    api._clock = lambda: float(next(ticks))  # każdy odczyt zegara: +2 s
    api.set_telemetry(True, False)
    api.explorer_open(SERIAL)
    pc = _pc_dir(tmp_path)
    copied = api.explorer_copy(["/sdcard/Music/piosenka.mp3"], str(pc))
    _wait_task(api, copied["task"], "done")  # running (t=0) → done (t=2): 40 B w 2 s
    api.explorer_close()
    (_device, seconds, copied_files, copied_bytes, uploaded_files, uploaded_bytes, *_rest, speeds) = seen[0]
    assert (copied_files, copied_bytes, uploaded_files, uploaded_bytes) == (1, 40, 0, 0)
    assert list(speeds) == [20.0] and seconds >= 4


# --- poprawki po przeglądzie Taska 9 -----------------------------------------------------------


def test_plan_for_replaced_session_is_not_queued(tmp_path, monkeypatch):
    """Plan liczony dla telefonu A nie trafia do kolejki telefonu B otwartego w trakcie planowania."""
    api, _, host, _ = _opened(tmp_path, other=True)
    host.connected.add(OTHER)
    real = explorer_api.plan_to_phone

    def plan_and_switch(*args, **kwargs):
        plan = real(*args, **kwargs)
        api.explorer_close()
        assert "error" not in api.explorer_open(OTHER)
        return plan

    monkeypatch.setattr(explorer_api, "plan_to_phone", plan_and_switch)
    local = _pc_dir(tmp_path, "z komputera")
    (local / "a.txt").write_bytes(b"a")
    out = api.explorer_upload([str(local / "a.txt")], "/sdcard/Download")
    assert out["error"]["key"] == "explorer_not_open"
    assert api._explorer.serial == OTHER and api._explorer.queue is None
    assert api.explorer_tasks() == {"tasks": []}
    assert not _storage_of(host, OTHER).local("/sdcard/Download/a.txt").exists()
    api.explorer_close()


def test_task_ids_are_unique_across_sessions(tmp_path):
    api, _, host, _ = _opened(tmp_path)
    local = _pc_dir(tmp_path, "z komputera")
    (local / "a.txt").write_bytes(b"a")
    (local / "b.txt").write_bytes(b"b")
    old = api.explorer_upload([str(local / "a.txt")], "/sdcard/Download")["task"]
    _wait_task(api, old, "done")
    api.explorer_close()
    api.explorer_open(SERIAL)
    gated = _GatedPusher(host.phone(SERIAL))
    api._pusher_factory = lambda adb_path, serial, log: gated
    new = api.explorer_upload([str(local / "b.txt")], "/sdcard/Music")["task"]
    try:
        assert new != old
        assert gated.entered.wait(5)
        assert api.explorer_cancel(old) == {} and api.explorer_pause(old) == {}  # stary identyfikator: nic
    finally:
        gated.gate.set()
    assert _wait_task(api, new, "done")["status"] == "done"
    assert _storage_of(host).local("/sdcard/Music/b.txt").read_bytes() == b"b"
    api.explorer_close()


def test_upload_into_probed_locked_folder_is_denied_before_start(tmp_path, monkeypatch):
    seen: list = []
    real = explorer_api.plan_to_phone
    monkeypatch.setattr(explorer_api, "plan_to_phone",
                        lambda *a, **kw: seen.append(kw.get("locked")) or real(*a, **kw))
    api, _, _, _ = _opened(tmp_path)
    locked = [e for e in api.explorer_list("/sdcard/Android")["entries"] if e["locked"]]
    assert [e["path"] for e in locked] == ["/sdcard/Android/data"]
    local = _pc_dir(tmp_path, "z komputera")
    (local / "a.txt").write_bytes(b"a")
    out = api.explorer_upload([str(local / "a.txt")], "/sdcard/Android/data/com.example")
    assert out["problems"][0]["key"] == "denied"
    assert seen == [frozenset({"/sdcard/Android/data"})]
    assert api.explorer_tasks() == {"tasks": []}
    api.explorer_close()


def test_close_failure_still_records_telemetry(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    api.set_telemetry(True, False)
    api._explorer_queue()  # zamknięcie czeka na wątek kolejki, potem zwalnia telefon

    def broken():
        raise OSError("close failed")

    api._explorer.stack.callback(broken)
    assert api.explorer_close()["error"]["key"] == "internal"
    events = [json.loads(x) for x in telemetry_path().read_text("utf-8").splitlines()]
    assert [e["type"] for e in events].count("explorer") == 1
    assert _lock_free()


# --- „Ostatnio” osobno dla każdego telefonu ----------------------------------------------------------


def test_recent_folders_are_kept_per_phone(tmp_path):
    api, _, host, opened = _opened(tmp_path, other=True)
    assert opened["recent"] == []
    api.explorer_list("/sdcard/Download")
    api.explorer_list("/sdcard/DCIM/Camera")
    api.explorer_close()
    assert api.explorer_open(SERIAL)["recent"] == ["/sdcard/DCIM/Camera", "/sdcard/Download"]
    api.explorer_close()
    # telefon B (inny klient) nie widzi folderów telefonu A — ani w `explorer_open`, ani w ustawieniach okna
    host.connected.add(OTHER)
    _storage_of(host, OTHER).local("/sdcard/Music").mkdir(parents=True)
    other = api.explorer_open(OTHER)
    assert "error" not in other and other["recent"] == []
    assert "explorer_recents" not in api.get_settings() and "explorer_recent" not in api.get_settings()
    api.explorer_list("/sdcard/Music")
    api.explorer_close()
    assert api.explorer_open(OTHER)["recent"] == ["/sdcard/Music"]
    api.explorer_close()
    assert api.explorer_open(SERIAL)["recent"] == ["/sdcard/DCIM/Camera", "/sdcard/Download"]
    api.explorer_close()


def test_recent_caps_folders_and_phones(tmp_path):
    api, _, host, _ = _opened(tmp_path)
    storage = _storage_of(host)
    for i in range(EXPLORER_RECENT_MAX + 3):
        storage.local(f"/sdcard/F{i}").mkdir(parents=True)
        api.explorer_list(f"/sdcard/F{i}")
    api.explorer_close()
    mine = load_settings().explorer_recents[SERIAL]
    assert mine == [f"/sdcard/F{i}" for i in range(EXPLORER_RECENT_MAX + 2, 2, -1)]
    # najdawniej używany telefon wypada; nasz (używany przed chwilą) przesuwa się na koniec
    others = {f"PHONE{i:02d}": ["/sdcard/DCIM"] for i in range(EXPLORER_RECENT_PHONES - 1)}
    save_internal({"explorer_recents": {**others, SERIAL: mine}})
    api._settings = load_settings()
    api.explorer_open(SERIAL)
    api.explorer_list("/sdcard/F0")
    api._explorer_remember("NEWPHONE", "/sdcard/DCIM")
    api.explorer_close()
    recents = load_settings().explorer_recents
    assert len(recents) == EXPLORER_RECENT_PHONES
    assert "PHONE00" not in recents and list(recents)[-2:] == [SERIAL, "NEWPHONE"]
    assert recents[SERIAL][0] == "/sdcard/F0"


def test_old_flat_recent_list_is_ignored(tmp_path):
    path = Path(os.environ["LOCALAPPDATA"]) / "AdMeNot" / "settings.json"
    api, _ = _api(_host(tmp_path))  # ustawienia testu już istnieją
    data = json.loads(path.read_text("utf-8"))
    data["explorer_recent"] = ["/sdcard/Klient A/Faktury", "/sdcard/DCIM/Camera"]  # format sprzed I2
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    assert load_settings().explorer_recents == {}  # bez błędu
    api, _ = _api(_host(tmp_path / "again"))
    opened = api.explorer_open(SERIAL)
    assert "error" not in opened and opened["recent"] == []
    assert "Klient A" not in json.dumps(api.get_settings(), ensure_ascii=False)
    api.explorer_list("/sdcard/Download")
    assert load_settings().explorer_recents == {SERIAL: ["/sdcard/Download"]}
    api.explorer_close()


# --- rozmiary plików w serwerze mediów -------------------------------------------------------------


def test_listing_a_folder_refreshes_cached_file_sizes(tmp_path):
    api, _, host, _ = _opened(tmp_path)
    media = api._explorer.media
    path = "/sdcard/Download/faktura.pdf"
    assert media.size_of(path) == len(b"%PDF-1.4")
    _storage_of(host).local(path).write_bytes(b"%PDF-1.7 dluzsza wersja")
    assert media.size_of(path) == len(b"%PDF-1.4")  # pamięć podręczna
    api.explorer_list("/sdcard/DCIM/Camera")  # inny folder: bez zmian
    assert media.size_of(path) == len(b"%PDF-1.4")
    api.explorer_list("/sdcard/Download")
    assert media.size_of(path) == len(b"%PDF-1.7 dluzsza wersja")
    api.explorer_close()


# --- wyjście z programu przy trwającym zadaniu ----------------------------------------------------


def _slow_adb(tmp_path: Path) -> tuple[Path, Path]:
    """Atrapa `adb` dla `RealPuller`: pisze do celu po kawałku i nie kończy się sama; zapisuje swój PID."""
    pid_file = tmp_path / "adb.pid"
    script = tmp_path / "slow_adb.py"
    script.write_text(
        "import os, sys, time\n"
        f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
        "with open(sys.argv[-1], 'ab') as fh:\n"
        "    for _ in range(6000):\n"
        "        fh.write(b'x' * 64); fh.flush(); time.sleep(0.01)\n", "utf-8")
    if sys.platform == "win32":
        exe = tmp_path / "slow_adb.cmd"
        exe.write_text(f'@"{sys.executable}" "{script}" %*\r\n', "utf-8")
    else:
        exe = tmp_path / "slow_adb"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', "utf-8")
        exe.chmod(0o755)
    return exe, pid_file


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@pytest.mark.skipif(sys.platform == "win32", reason="sygnał 0 do sprawdzenia procesu — POSIX")
def test_window_close_with_running_copy_kills_adb_and_leaves_no_part(tmp_path):
    exe, pid_file = _slow_adb(tmp_path)
    host = _host(tmp_path)
    api, _ = _api(host, sync=False, puller_factory=lambda adb_path, serial, log: RealPuller(str(exe), serial, log))
    assert "error" not in api.explorer_open(SERIAL)
    pc = _pc_dir(tmp_path)
    closed = threading.Event()
    api._attach(pick_folder=lambda: str(pc), close=closed.set)
    started = api.explorer_copy(["/sdcard/Music/piosenka.mp3"], str(pc))
    part = pc / "piosenka.mp3.admenot-part"
    deadline = time.monotonic() + 10
    while not (pid_file.exists() and part.exists() and part.stat().st_size > 0):
        assert time.monotonic() < deadline, "atrapa adb nie ruszyła"
        time.sleep(0.02)
    pid = int(pid_file.read_text())
    assert _alive(pid) and api._explorer_active() == 1
    assert api._on_closing() is False  # okno czeka na koniec kolejki (nie na wątku GUI)
    assert closed.wait(15), "okno się nie zamknęło"
    assert not _alive(pid), "adb pull nadal działa po zamknięciu programu"
    assert not part.exists() and list(pc.iterdir()) == []  # bez `.admenot-part` i bez niepełnego pliku
    assert api._explorer is None
    assert started["task"].startswith("s1t")
    _wait_lock_free()
    assert api._on_closing() is True  # drugie wywołanie (po `close_fn`) zamyka okno


def test_quit_join_timeout_removes_partials(tmp_path):
    """Wątek kolejki nie skończył się na czas (np. długie `sha256sum`): `.admenot-part` usuwamy sami."""
    api, _, _, _ = _opened(tmp_path)
    queue = api._explorer_queue()
    gate = threading.Event()
    queue._worker = threading.Thread(target=gate.wait, args=(10,), daemon=True)
    queue._worker.start()
    pc = _pc_dir(tmp_path)
    part = pc / "film.mp4.admenot-part"
    part.write_bytes(b"half")
    plan = TaskPlan("to_pc", [], [], 0, [])
    tid = queue.add(plan)
    queue._tasks[tid].inflight[0] = str(part)
    queue._tasks[tid].state.status = "running"
    try:
        started = time.monotonic()
        api._explorer_quit(timeout=0.2)
        assert time.monotonic() - started < 5
        assert not part.exists() and api._explorer is None
    finally:
        gate.set()
    _wait_lock_free()


def test_window_close_without_explorer_tasks_closes_at_once(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    assert api._explorer_active() == 0
    assert api._on_closing() is True
    assert api._explorer is None and _lock_free()


def test_switch_phone_emits_closed_outside_the_session_lock(tmp_path):
    """`explorer:closed` idzie do okna (`run_js` czeka na wątek GUI) już po zwolnieniu `_explorer_lock`."""
    api, rec, host, _ = _opened(tmp_path, other=True)
    host.connected.add(OTHER)
    held: list[bool] = []
    emit = api._emit

    def spy(name, detail):
        if name == "explorer:closed":
            held.append(api._explorer_lock._is_owned())
        emit(name, detail)

    api._emit = spy
    assert "error" not in api.explorer_open(OTHER)
    assert held == [False]
    assert rec.of("explorer:closed") == [{"serial": SERIAL, "reason": "switched"}]
    api.explorer_close()


def test_second_window_close_waits_for_the_first(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    queue = api._explorer_queue()
    queue.active = lambda: 1  # zadania trwają: zamykanie idzie osobnym wątkiem
    entered, leave = threading.Event(), threading.Event()
    calls: list[str] = []

    def slow_quit() -> None:
        entered.set()
        leave.wait(5)

    api._explorer_quit = slow_quit
    api._shutdown = lambda: calls.append("shutdown")
    assert api._on_closing() is False
    assert entered.wait(5)
    assert api._on_closing() is False  # drugi krzyżyk: to samo zamykanie, bez skrótu do `_shutdown`
    assert calls == []
    leave.set()


def test_storage_reports_free_space_like_the_upload_plan(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    usage = api.explorer_storage()
    assert usage["free"] == phone_free_bytes(api._explorer.adb)


def test_upload_can_verify_by_hash(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    local = _pc_dir(tmp_path, "z komputera") / "a.txt"
    local.write_bytes(b"x")
    task = api.explorer_upload([str(local)], "/sdcard/Download", True)["task"]
    done = api._explorer_queue().wait_for(task, "done")
    assert done.verified == "hash"


def test_copy_leaves_out_excluded_paths(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    dest = _pc_dir(tmp_path, "cel")
    paths = ["/sdcard/Download/faktura.pdf", "/sdcard/Download/notatka Łódź.txt"]
    task = api.explorer_copy(paths, str(dest), False, [paths[0]])["task"]
    api._explorer_queue().wait_for(task, "done")
    assert [p.name for p in dest.iterdir()] == ["notatka Łódź.txt"]


def test_retry_bridge_starts_a_new_task_only_for_failed_files(tmp_path):
    api, _, host, _ = _opened(tmp_path)
    assert api.explorer_retry("nie-ma") == {"task": None}
    dest = _pc_dir(tmp_path, "cel")
    storage = _storage_of(host)
    bad = {"on": True}

    def corrupt(cmd: str) -> None:
        if cmd.startswith("sha256sum ") and bad["on"]:
            storage.local("/sdcard/Download/faktura.pdf").write_bytes(os.urandom(storage.local("/sdcard/Download/faktura.pdf").stat().st_size))

    storage.on_shell = corrupt
    task = api.explorer_copy(["/sdcard/Download/faktura.pdf"], str(dest), True)["task"]
    queue = api._explorer_queue()
    assert queue.wait_for(task, "done").verified == "mismatch"
    bad["on"] = False
    again = api.explorer_retry(task)["task"]
    assert queue.wait_for(again, "done").verified == "hash"
