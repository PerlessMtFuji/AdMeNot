"""Atrapy dla testów mostu `Api` (tests/test_app_api_*.py)."""

import threading
from datetime import datetime

from demalware.app.api import Api
from demalware.app.events import RecordingEmitter
from demalware.engine.apk.analyze import ApkReport
from demalware.engine.settings import save_settings

NOW = datetime(2026, 9, 26, 14, 30, 0)


class NoApk:
    """Analiza APK bez znalezisk: postęp i pusty, poprawny raport dla każdej aplikacji.

    Jak `DeviceApkProvider`: raport (albo błąd) dla każdego celu — brak raportu to luka „apk”
    (przegląd końcowy Planu 4b, T6). `class_count=1`: plik z kodem, w którym nic nie znaleziono;
    raport bez klas `apply_apk_report` traktuje jako niepełną analizę.
    """

    def reports_for(self, apps, progress=None):
        reports = {}
        for i, facts in enumerate(apps, start=1):
            reports[facts.package] = ApkReport(facts.package, facts.version_code, class_count=1)
            if progress:
                progress(i, len(apps), facts.package)
        return reports


class SlowApk:
    """Analiza APK, która czeka na `release` po pierwszej aplikacji."""

    def __init__(self):
        self.release = threading.Event()

    def reports_for(self, apps, progress=None):
        progress(1, len(apps), apps[0].package)
        self.release.wait(5)
        progress(len(apps), len(apps), apps[-1].package)
        return {}


def make_api(phone, *, sync=True, apk=None, **kw):
    # Controller ruling F2: testy nie mogą zależeć od locale Windows — język ustawiony na
    # sztywno przed skonstruowaniem `Api`, które przy starcie wczytuje ustawienia.
    save_settings({"lang": "pl"})
    rec = RecordingEmitter()
    kw.setdefault("open_file", lambda path: None)
    provider = apk or NoApk()
    api = Api(rec, host_factory=lambda path: phone, apk_factory=lambda adb: provider,
              sync_jobs=sync, now=lambda: NOW, **kw)
    return api, rec


def names(rec):
    return [n for n in rec.names() if n != "adb:command"]
