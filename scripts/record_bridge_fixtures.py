"""Nagrywa scenariusze mostu GUI z prawdziwego `Api` na FakePhone → tests/fixtures/bridge/*.json.

Atrapa mostu w UI (ui/src/lib/fakeBridge.ts) odtwarza te pliki, a tests/test_bridge_fixtures.py
pilnuje, że są aktualne. Po zmianie `Api`, `present.py` albo zdarzeń uruchom:

    .venv/Scripts/python scripts/record_bridge_fixtures.py
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "bridge"
sys.path.insert(0, str(ROOT / "tests"))  # conftest.py, fakephone.py, apphelpers.py

from apphelpers import Disk, make_api, policy_factory
from conftest import SERIAL
from fakephone import make_cli_phone
from faketransfer import FakeStoragePhone, TransferPhone
from telephony_fixtures import install_telephony

from admenot.engine.apk import cache as C
from admenot.engine.report.pdf import PdfError
from admenot.engine.settings import save_settings

CLIENT = "Anna K."
DISABLE = "pm disable-user --user 0 com.wlive.forecast"
ADWARE = {"com.clean.pro.boost": "remove", "com.wlive.forecast": "disable"}
ADWARE_PACKAGE = "com.clean.pro.boost"


def _sort_adb_runs(events: list[list[Any]]) -> list[list[Any]]:
    """Ruling F3: kolektory skanu działają w wątkach (`run_collectors`), więc kolejność kolejnych
    `adb:command` w jednym przebiegu jest niedeterministyczna. Stabilne sortowanie każdego
    ciągłego przebiegu po (command, status); zdarzenia innego typu zostają na swoich miejscach."""
    result = list(events)
    i = 0
    while i < len(result):
        if result[i][0] != "adb:command":
            i += 1
            continue
        j = i
        while j < len(result) and result[j][0] == "adb:command":
            j += 1
        run = result[i:j]
        run.sort(key=lambda e: (e[1]["command"], e[1]["status"]))
        result[i:j] = run
        i = j
    return result


class Recorder:
    """Woła metody `Api` i zbiera parę (wynik, zdarzenia) dla każdego wywołania."""

    def __init__(self, phone: Any, lang: str = "pl", apk_mode: str = "full", **kw: Any) -> None:
        # apphelpers.make_api pina język i tryb APK (save_settings) i czas na NOW zanim zbuduje `Api`.
        self.api, self.emitter = make_api(phone, sync=True, lang=lang, apk_mode=apk_mode,
                                          poll_interval=0.0, **kw)
        if apk_mode != "full":
            # `NoApk` z make_api pomija `CachePolicy`, więc trybu ręcznego by nie było.
            self.api._apk_factory = policy_factory([])
        self.calls: list[dict[str, Any]] = []

    def call(self, method: str, *args: Any) -> Any:
        start = len(self.emitter.events)
        result = getattr(self.api, method)(*args)
        events = _sort_adb_runs([[name, detail] for name, detail in self.emitter.events[start:]])
        self.calls.append({"method": method, "args": list(args), "result": result,
                           "events": events})
        return result

    def events(self, name: str) -> list[Any]:
        return [d for c in self.calls for n, d in c["events"] if n == name]


_PART_DIR = re.compile(r"\.(part|unverified)-[A-Za-z0-9_]+")


def _normalize(value: Any, tmp: str) -> Any:
    """Czas trwania -> 0.0, katalog tymczasowy (np. w `adb pull … <kopia>`) -> `<tmp>`.

    `fetch_apks` (Plan 4b Task 3) pobiera do unikalnego katalogu roboczego
    (`tempfile.mkdtemp(prefix=".part-", ...)`), żeby dwa równoczesne skany się nie zobaczyły —
    nazwa jest losowa przy każdym uruchomieniu, więc trzeba ją też ujednolicić, inaczej nagranie
    nigdy nie byłoby stabilne. Tak samo `.unverified-…` (pobranie bez `sha256sum`).
    """
    if isinstance(value, dict):
        return {k: (0.0 if k == "duration" else _normalize(v, tmp)) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v, tmp) for v in value]
    if isinstance(value, str):
        text = value.replace(tmp, "<tmp>").replace(tmp.replace("\\", "/"), "<tmp>")
        return _PART_DIR.sub(r".\1-X", text)
    return value


@contextmanager
def _isolated(lang: str = "pl") -> Iterator[str]:
    keys = ("LOCALAPPDATA", "ADMENOT_ASSETS")
    saved = {k: os.environ.get(k) for k in keys}
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["LOCALAPPDATA"] = str(Path(tmp) / "data")
        os.environ["ADMENOT_ASSETS"] = str(Path(tmp) / "no-assets")
        # Ruling F2: nagranie nie może zależeć od locale Windows -- język na sztywno zanim
        # jakikolwiek `Api` wczyta ustawienia (make_api robi to samo, ale robimy to i tu, na
        # wszelki wypadek, gdyby krok scenariusza zbudował `Api` inaczej).
        save_settings({"lang": lang, "apk_mode_default": "full"})
        try:
            yield tmp
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def _scenario(name: str, steps: Callable[[Recorder, Any], None], lang: str = "pl",
              apk_mode: str = "full",
              phone_factory: Callable[[Path], Any] | None = None) -> dict[str, Any]:
    # Dysk na sztywno: szacunek i pytanie o miejsce nie mogą zależeć od komputera nagrywającego.
    with _isolated(lang) as tmp, mock.patch.object(C, "disk_usage",
                                                   lambda path: Disk(500 * C.GB, 0, 500 * C.GB)):
        kw: dict[str, Any] = {}
        if phone_factory is None:
            phone = make_cli_phone()
        else:
            phone = phone_factory(Path(tmp))
            kw["puller_factory"] = lambda adb_path, serial, log: phone
        recorder = Recorder(phone, lang, apk_mode=apk_mode, **kw)
        steps(recorder, phone)
        return _normalize({"name": name, "calls": recorder.calls}, tmp)


def _adware(r: Recorder, phone: Any) -> None:
    phone.on_admin_screen = lambda p: setattr(p.apps["com.clean.pro.boost"], "admin", False)
    r.call("list_devices")
    r.call("history", None)  # UI przy starcie pyta o znane telefony (Controller.loadKnownSerials)
    r.call("start_scan", SERIAL, CLIENT)
    r.call("preview_plan", ADWARE, [])
    r.call("execute", ADWARE, [])
    r.call("history", None)
    number = r.events("exec:order")[0]["order"]
    r.call("undo", number, None, None)
    r.call("history", None)


def _manual(r: Recorder, phone: Any) -> None:
    phone.on_admin_screen = lambda p: setattr(p.apps[ADWARE_PACKAGE], "admin", False)
    r.call("list_devices")
    r.call("history", None)  # UI przy starcie pyta o znane telefony (Controller.loadKnownSerials)
    r.call("start_scan", SERIAL, CLIENT)
    r.call("selection_eta", [ADWARE_PACKAGE])
    r.call("analyze_selected", [ADWARE_PACKAGE])
    r.call("preview_plan", {ADWARE_PACKAGE: "remove"}, [])
    r.call("execute", {ADWARE_PACKAGE: "remove"}, [])
    r.call("history", None)


def _disconnect(r: Recorder, phone: Any) -> None:
    r.call("list_devices")
    r.call("history", None)  # UI przy starcie pyta o znane telefony (Controller.loadKnownSerials)
    r.call("start_scan", SERIAL, CLIENT)
    r.call("preview_plan", {"com.wlive.forecast": "disable"}, [])
    phone.lose_response.add(DISABLE)
    r.call("execute", {"com.wlive.forecast": "disable"}, [])
    phone.lose_response.clear()
    phone.disconnected = False
    r.call("history", None)
    number = r.events("exec:disconnected")[0]["order"]
    r.call("resume", number)


def _fake_pdf(html: Path, pdf: Path) -> None:
    pdf.write_bytes(b"%PDF-1.4 fake")


def _report(r: Recorder, phone: Any) -> None:
    r.call("list_devices")
    r.call("history", None)  # UI przy starcie pyta o znane telefony (Controller.loadKnownSerials)
    r.call("start_scan", SERIAL, CLIENT)
    r.call("preview_plan", {"com.wlive.forecast": "disable"}, [])  # „Podsumowanie”
    r.call("execute", {"com.wlive.forecast": "disable"}, [])
    number = r.events("exec:order")[0]["order"]
    with mock.patch("admenot.engine.report.files.html_to_pdf", _fake_pdf):
        r.call("report", number)
    with mock.patch("admenot.engine.report.files.html_to_pdf",
                    mock.Mock(side_effect=PdfError("locked"))):
        r.call("report", number)
    r.call("service")
    r.call("save_service", {"name": "Serwis Ząb", "address": "ul. Długa 1", "phone": "600 000 000"})
    r.call("history", None)


TRANSFER_MTIME = 1_700_000_000
TRANSFER_FILES = {
    "DCIM/Camera/IMG_0001.jpg": b"A" * 3000,
    "DCIM/Camera/IMG_0002.jpg": b"B" * 2000,
    "Download/faktura.pdf": b"%PDF" + b"c" * 500,
    "WhatsApp/Media/WhatsApp Images/IMG-1.jpg": b"W" * 800,
    "Music/song.mp3": b"M" * 400,
    "notes.txt": b"loose file",
}
TRANSFER_SELECTION = {"contacts": True, "sms": True, "mms": False, "calls": True,
                      "categories": ["media", "downloads", "whatsapp"], "others": ["Music"],
                      "apps": ["com.whatsapp"]}


def _transfer_phone(tmp: Path) -> TransferPhone:
    root = tmp / "old-phone"
    for rel, data in TRANSFER_FILES.items():
        path = root / "sdcard" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (TRANSFER_MTIME, TRANSFER_MTIME))
    install_telephony(root, mms=False)
    storage = FakeStoragePhone(root, serial=SERIAL)
    storage.apps = {"com.whatsapp": {"base.apk": b"PK-whatsapp"}}
    return TransferPhone(make_cli_phone(), storage)


def _transfer(r: Recorder, phone: Any) -> None:
    r.call("list_devices")
    r.call("transfers")
    r.call("transfer_inventory", SERIAL, CLIENT)
    r.call("start_backup", TRANSFER_SELECTION)
    r.call("transfers")


def _stable_transfer(data: dict[str, Any]) -> dict[str, Any]:
    """`transfer:progress` jest dławiony co 0,5 s, więc ich liczba zależy od szybkości komputera:
    zostaje pierwsze zdarzenie każdego etapu w wywołaniu (to wysyła się zawsze). Czas kopii -> 0."""
    for call in data["calls"]:
        seen: set[str] = set()
        events = []
        for name, detail in call["events"]:
            if name == "transfer:progress":
                if detail["stage"] in seen:
                    continue
                seen.add(detail["stage"])
            if name == "transfer:done":
                detail["result"]["seconds"] = 0
            events.append([name, detail])
        call["events"] = events
    return data


def _devices_only(output: str) -> Callable[[Recorder, Any], None]:
    def steps(r: Recorder, phone: Any) -> None:
        phone.host["devices -l"] = output
        r.call("list_devices")
    return steps


def _clean(adware: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(adware)
    data["name"] = "clean"
    data["calls"] = [c for c in data["calls"] if c["method"] in ("list_devices", "start_scan")]
    for call in data["calls"]:
        for name, detail in call["events"]:
            if name in ("scan:done", "apk:done"):
                scan = detail["scan"]
                scan["apps"] = [a for a in scan["apps"] if a["verdict"] == "safe"]
                counts = scan["counts"]
                for key in ("malicious", "suspicious", "review"):
                    counts[key] = 0
                counts["safe"] = counts["total"] = len(scan["apps"])
                counts["admins"] = sum(a["is_admin"] for a in scan["apps"])
                counts["non_play"] = sum(not a["is_system"] and not a["from_play"]
                                         for a in scan["apps"])
                counts["user"] = sum(not a["is_system"] for a in scan["apps"])
            if name == "scan:done":
                detail["interrupted"] = []
    return data


def record_all() -> dict[str, dict[str, Any]]:
    adware = _scenario("adware", _adware)
    unauthorized = f"List of devices attached\n{SERIAL}  unauthorized usb:1-1 transport_id:3\n"
    many = (f"List of devices attached\n{SERIAL}  device usb:1-1 model:SM_A145R\n"
            "HT7A1B2C3  device usb:1-2 model:Pixel_7\n")
    return {
        "adware": adware,
        # Teksty silnika po angielsku: zrzuty do README.md (ui/readme-shots, `?lang=en`).
        "adware-en": _scenario("adware-en", _adware, lang="en"),
        "clean": _clean(adware),
        "manual": _scenario("manual", _manual, apk_mode="manual"),
        "disconnect": _scenario("disconnect", _disconnect),
        "report": _scenario("report", _report),
        "transfer": _stable_transfer(_scenario("transfer", _transfer,
                                               phone_factory=_transfer_phone)),
        "unauthorized": _scenario("unauthorized", _devices_only(unauthorized)),
        "many": _scenario("many", _devices_only(many)),
        "empty": _scenario("empty", _devices_only("List of devices attached\n\n")),
    }


def write_all(out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, data in record_all().items():
        path = out / f"{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for path in write_all():
        print(path.relative_to(ROOT))
