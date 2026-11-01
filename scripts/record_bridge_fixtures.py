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
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "bridge"
sys.path.insert(0, str(ROOT / "tests"))  # conftest.py, fakephone.py, apphelpers.py

from apphelpers import Disk, make_api, policy_factory
from conftest import GETPROP_OUT, SERIAL
from fakephone import make_cli_phone
from faketransfer import FakeStoragePhone, PhoneHost, TransferPhone
from telephony_fixtures import install_telephony

from admenot.engine.apk import cache as C
from admenot.engine.device.info import GETPROP
from admenot.engine.report.pdf import PdfError
from admenot.engine.settings import save_settings
from admenot.engine.transfer import helper, phonesetup, restore_tel
from admenot.engine.transfer.apkcheck import ApkCheck

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
            # kilka telefonów (`PhoneHost`): `adb pull`/`push` idzie do atrapy danego telefonu
            route = phone.phone if isinstance(phone, PhoneHost) else (lambda serial: phone)
            kw["puller_factory"] = lambda adb_path, serial, log: route(serial)
            kw["pusher_factory"] = lambda adb_path, serial, log: route(serial)
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


EXPORT_VCF = "".join(f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Osoba {i}\r\nEND:VCARD\r\n" for i in range(3))
EXPORT_SMS = ("<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n<smses count=\"2\">\n"
              '<sms address="1" body="a" />\n<sms address="2" body="b" />\n</smses>\n')
EXPORT_FILES = {  # rel -> (zawartość, mtime)
    "Kopia/kontakty-stare.vcf": (EXPORT_VCF[:-len("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Osoba 2\r\nEND:VCARD\r\n")],
                                 TRANSFER_MTIME - 86_400),
    "Kopia/kontakty.vcf": (EXPORT_VCF, TRANSFER_MTIME),
    "Backup/sms.xml": (EXPORT_SMS, TRANSFER_MTIME),
}


def _export_phone(tmp: Path) -> TransferPhone:
    """Stary telefon, który odmawia kontaktów i SMS-ów; na karcie leżą ich pliki eksportu."""
    phone = _transfer_phone(tmp)
    phone.storage.deny_uris = {"content://com.android.contacts/contacts", "content://sms"}
    for rel, (data, mtime) in EXPORT_FILES.items():
        path = phone.storage.local("/sdcard/" + rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
        os.utime(path, (mtime, mtime))
    return phone


def _transfer_export(r: Recorder, phone: Any) -> None:
    r.call("list_devices")
    r.call("transfer_inventory", SERIAL, CLIENT)
    r.call("transfer_rescan")
    r.call("start_backup", {**TRANSFER_SELECTION, "calls": False, "mms": True,
                            "exports": {"contacts": "/sdcard/Kopia/kontakty.vcf",
                                        "sms": "/sdcard/Backup/sms.xml"}})
    r.call("transfers")


RESTORE_SERIAL = "R58W20NEW01"
RESTORE_CHOICE = {"groups": ["photos", "videos", "downloads", "whatsapp", "other:Music"], "apks_on": [],
                  "verify_hash": False}
# Pliki APK w Pobranych starego telefonu i ich ocena (podstawiona: bez prawdziwych APK i bazy IOC).
RESTORE_APKS = {"Download/gra.apk": (b"PK" + b"g" * 900, "suspicious", "static", False),
                "Download/szybki-cleaner.apk": (b"PK" + b"e" * 700, "malicious", "ioc", False)}


def _restore_phones(tmp: Path) -> PhoneHost:
    """Stary telefon z kopią (jak `transfer`, plus dwa APK) i nowy Galaxy A54, na którym już jest
    inny plik o ścieżce zdjęcia z kopii — wgrywanie zapisze zdjęcie obok jako „(z kopii)”."""
    old = _transfer_phone(tmp)
    for rel, (data, *_check) in RESTORE_APKS.items():
        path = old.storage.local("/sdcard/" + rel)
        path.write_bytes(data)
        os.utime(path, (TRANSFER_MTIME, TRANSFER_MTIME))
    root = tmp / "new-phone"
    theirs = root / "sdcard" / "DCIM" / "Camera" / "IMG_0001.jpg"
    theirs.parent.mkdir(parents=True)
    theirs.write_bytes(b"photo taken on the new phone")
    os.utime(theirs, (TRANSFER_MTIME, TRANSFER_MTIME))
    cli = make_cli_phone()
    cli.static[GETPROP] = (GETPROP_OUT.replace("SM-A145R", "SM-A546B").replace("[a14]", "[a54x]")
                           .replace(SERIAL, RESTORE_SERIAL).replace("Telefon Anny", "Nowy telefon Anny"))
    return PhoneHost(old, TransferPhone(cli, FakeStoragePhone(root, serial=RESTORE_SERIAL)))


def _apk_checks(copy: Any, files: list[tuple[str, Path]]) -> list[ApkCheck]:
    checks = {"/sdcard/" + rel: c for rel, (_data, *c) in RESTORE_APKS.items()}
    return [ApkCheck(remote, None, *checks[remote]) for remote, _ in files]


def _transfer_restore(r: Recorder, phone: Any) -> None:
    r.call("list_devices")
    r.call("transfer_inventory", SERIAL, CLIENT)
    r.call("start_backup", TRANSFER_SELECTION)
    copy_id = r.events("transfer:done")[0]["copy"]["id"]
    r.call("transfers")  # Historia: kopia bez wgrywań
    with mock.patch("admenot.engine.transfer.restore_plan.load_or_check", _apk_checks):
        r.call("restore_plan", copy_id, RESTORE_SERIAL)
    r.call("start_restore", RESTORE_CHOICE)
    r.call("transfers")  # Historia: „wgrano na …”


RESTORE_TEL_CHOICE = {**RESTORE_CHOICE, "tel": ["contacts", "sms", "calls"]}
SMS_APP = "com.google.android.apps.messaging"


class _FixedNow(datetime):
    """Zegar silnika telefonii w nagraniu: nazwy plików do ręcznego importu mają w sobie godzinę."""

    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        return cls(2026, 9, 26, 14, 31, 0, tzinfo=tz)


def _restore_tel_phones(tmp: Path) -> PhoneHost:
    """Jak `transfer_restore`, a nowy telefon ma pustą telefonię i Wiadomości Google jako domyślną
    aplikację SMS. SMS-y odmawia zapisać `app_process`, więc idą przez aplikację pomocniczą: ta musi
    zostać domyślną aplikacją SMS, a na to telefon prosi o stuknięcie (serwisant stuka, gdy pojawi się
    okno). Rejestru połączeń nie przyjmuje żadna droga z pomocnikiem: plik do ręcznego importu."""
    host = _restore_phones(tmp)
    new = host.phone(RESTORE_SERIAL).storage
    new.telephony = True
    new.role_holders = [SMS_APP]
    new.helper_denied = {"sms", "calls"}
    new.companion_denied = {"calls"}
    new.role_needs_tap = True
    (new.root / "sdcard" / "Download").mkdir(parents=True, exist_ok=True)

    def tap_when_asked(command: str) -> None:
        if command == f"am start -n {helper.PACKAGE}/.RoleActivity":
            new.tap_role(helper.PACKAGE)

    new.on_shell = tap_when_asked
    return host


def _transfer_restore_tel(r: Recorder, phone: Any) -> None:
    r.call("list_devices")
    r.call("transfer_inventory", SERIAL, CLIENT)
    r.call("start_backup", TRANSFER_SELECTION)
    copy_id = r.events("transfer:done")[0]["copy"]["id"]
    with mock.patch("admenot.engine.transfer.restore_plan.load_or_check", _apk_checks):
        r.call("restore_plan", copy_id, RESTORE_SERIAL)
    with (mock.patch.object(phonesetup, "_sleep", lambda s: None),
          mock.patch.object(restore_tel, "datetime", _FixedNow)):
        r.call("start_restore", RESTORE_TEL_CHOICE)
    r.call("transfers")  # Historia: „wgrano na …”


def _stable_transfer(data: dict[str, Any]) -> dict[str, Any]:
    """`transfer:progress`, `transfer:restore_progress` i `transfer:tel_progress` są dławione co 0,5 s,
    więc ich liczba zależy od szybkości komputera: zostaje pierwsze zdarzenie każdego etapu (telefonia:
    kategorii) w wywołaniu (to wysyła się zawsze). Czas kopii, wgrywania i telefonii -> 0, czas zapisu
    stanu wgrywania -> stały."""
    for call in data["calls"]:
        seen: set[tuple[str, str]] = set()
        events = []
        for name, detail in call["events"]:
            if name in ("transfer:progress", "transfer:restore_progress", "transfer:tel_progress"):
                stage = detail["kind"] if name == "transfer:tel_progress" else detail["stage"]
                if (name, stage) in seen:
                    continue
                seen.add((name, stage))
            if name in ("transfer:done", "transfer:restore_done"):
                detail["result"]["seconds"] = 0
                if detail.get("tel"):
                    detail["tel"]["seconds"] = 0
            events.append([name, detail])
        call["events"] = events
    return _stable_restores(data)


def _stable_restores(value: Any) -> Any:
    """`updated` stanu wgrywania to zegar komputera (UTC), nie zegar `Api` — w nagraniu stały."""
    if isinstance(value, dict):
        return {k: ([{**r, "updated": "2026-09-26T12:31:00+00:00"} for r in v] if k == "restores"
                    else _stable_restores(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_stable_restores(v) for v in value]
    return value


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
        "transfer_export": _stable_transfer(_scenario("transfer_export", _transfer_export,
                                                      phone_factory=_export_phone)),
        "transfer_restore": _stable_transfer(_scenario("transfer_restore", _transfer_restore,
                                                       phone_factory=_restore_phones)),
        "transfer_restore_tel": _stable_transfer(_scenario("transfer_restore_tel", _transfer_restore_tel,
                                                           phone_factory=_restore_tel_phones)),
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
