"""Most GUI ↔ eksplorator plików: sesja (blokada telefonu), przeglądanie, podgląd, tworzenie."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest
from apphelpers import NOW, make_api
from conftest import GETPROP_OUT, SERIAL
from exifbuild import ASCII, RATIONAL, build_exif, jpeg_bytes, segment, with_segments
from fakephone import make_cli_phone
from faketransfer import FakeStoragePhone, PhoneHost, TransferPhone

from admenot.app import explorer_api
from admenot.engine.adb.sessionlog import session_log_path
from admenot.engine.device.info import GETPROP
from admenot.engine.explorer.plan import TaskPlan
from admenot.engine.explorer.queue import read_tmp_folders, record_tmp_folder
from admenot.engine.oplock import DeviceBusy, device_lock
from admenot.engine.paths import journal_path, logs_dir
from admenot.engine.settings import load_settings

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
    assert downloads["faktura.pdf"]["type"] == "doc" and downloads["faktura.pdf"]["url"] is None
    assert downloads["notatka Łódź.txt"]["type"] == "text" and downloads["notatka Łódź.txt"]["thumb"] is None
    root = api.explorer_list("/sdcard")
    assert root["crumbs"] == [{"label": name, "path": "/sdcard"}]
    assert {e["name"] for e in root["entries"] if e["kind"] == "dir"} >= {"DCIM", "Download", "Android"}
    # „Ostatnio”: najnowszy pierwszy, bez korzenia pamięci
    assert load_settings().explorer_recent == ["/sdcard/Download", "/sdcard/Android/media/com.whatsapp",
                                               "/sdcard/DCIM/Camera"]


def test_list_denied_folder(tmp_path):
    api, _, _, _ = _opened(tmp_path)
    data = next(e for e in api.explorer_list("/sdcard/Android")["entries"] if e["name"] == "data")
    assert data["locked"] is True
    inside = api.explorer_list("/sdcard/Android/data")
    assert inside["entries"] == [] and inside["locked"] is True
    assert "/sdcard/Android/data" not in load_settings().explorer_recent
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
