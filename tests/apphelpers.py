"""Atrapy dla testów mostu `Api` (tests/test_app_api_*.py)."""

import threading
from collections import namedtuple
from datetime import datetime
from typing import ClassVar

from admenot.app.api import Api
from admenot.app.events import RecordingEmitter
from admenot.engine.apk import cache as C
from admenot.engine.apk.analyze import ApkReport
from admenot.engine.apk.fetch import FetchedApks, default_cache_dir
from admenot.engine.apk.providers import DeviceApkProvider
from admenot.engine.settings import save_settings

NOW = datetime(2026, 9, 26, 14, 30, 0)


class NoApk:
    """Analiza APK bez znalezisk: postęp i pusty, poprawny raport dla każdej aplikacji.

    Jak `DeviceApkProvider`: raport (albo błąd) dla każdego celu — brak raportu to luka „apk”
    (przegląd końcowy Planu 4b, T6). `class_count=1`: plik z kodem, w którym nic nie znaleziono;
    raport bez klas `apply_apk_report` traktuje jako niepełną analizę.
    """

    def reports_for(self, apps, progress=None, flagged=frozenset()):
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

    def reports_for(self, apps, progress=None, flagged=frozenset()):
        progress(1, len(apps), apps[0].package)
        self.release.wait(5)
        progress(len(apps), len(apps), apps[-1].package)
        return {}


Disk = namedtuple("Disk", "total used free")


def fake_fetch(cache_dir, package):
    """Pobranie bez telefonu: 1 bajt we wpisie `<pakiet>/id`, jak gotowy wpis `fetch_apks`."""
    entry = cache_dir / package / "id"
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "base.apk").write_bytes(b"x")
    return FetchedApks([entry / "base.apk"], verified=True)


def policy_factory(policies):
    """Prawdziwy `DeviceApkProvider` z polityką od `Api`; `stat` podaje 1 GB na każdy cel.

    `NoApk` pomija `CachePolicy`, więc tryb ręczny (pytanie o tryb, `apk:manual`) widać tylko
    z tym dostawcą; trzeba też podstawić `cache.disk_usage` (`Disk`).
    """
    def factory(adb, policy=None, **kw):
        policies.append(policy)
        real = adb.shell

        def shell(command, timeout=20.0):
            if command.startswith("stat -c"):
                paths = [a.strip("'") for a in command.split() if a.endswith(".apk'") or
                         (a.endswith(".apk") and "*" not in a)]
                return "".join(f"{C.GB} {path}\n" for path in paths)
            return real(command, timeout)

        adb.shell = shell
        return DeviceApkProvider(adb, cache_dir=default_cache_dir(), workers=1,
                                 fetch=lambda a, package, d: fake_fetch(d, package),
                                 analyze=lambda package, paths: ApkReport(package, class_count=1),
                                 policy=policy)
    return factory


def make_api(phone, *, sync=True, apk=None, lang="pl", apk_mode="full", **kw):
    # Controller ruling F2: testy nie mogą zależeć od locale Windows — język ustawiony na
    # sztywno przed skonstruowaniem `Api`, które przy starcie wczytuje ustawienia.
    # Tryb APK „full”: zadanie synchroniczne nie odpowie na pytanie o tryb (spec trybu ręcznego).
    save_settings({"lang": lang, "apk_mode_default": apk_mode})
    rec = RecordingEmitter()
    kw.setdefault("open_file", lambda path: None)
    provider = apk or NoApk()
    api = Api(rec, host_factory=lambda path: phone, apk_factory=lambda adb, policy=None, **kw: provider,
              sync_jobs=sync, now=lambda: NOW, **kw)
    return api, rec


def names(rec):
    return [n for n in rec.names() if n != "adb:command"]


class FakeScrcpyProc:
    def __init__(self, lines):
        self.pid = 4242
        self.lines = [line.encode("utf-8") + b"\n" for line in lines]
        self.ended = threading.Event()
        self.code = 0

    @property
    def stdout(self):
        yield from self.lines
        self.ended.wait(5)

    def wait(self, timeout=None):
        self.ended.wait(5)
        return self.code


class FakeScrcpy:
    """scrcpy do testów mostu: każdy start oddaje nagrane linie i „działa” do zamknięcia."""

    LINES: ClassVar[list[str]] = ["scrcpy 4.1 <https://github.com/Genymobile/scrcpy>",
                                  "[server] INFO: Device: [samsung] samsung SM-A145R (Android 14)",
                                  "INFO: Texture: 576x1280"]

    def __init__(self, available=True):
        self.available = available
        self.procs: list[FakeScrcpyProc] = []
        self.envs: list[dict] = []
        self.cmds: list[list[str]] = []

    def spawn(self, cmd, env):
        self.cmds.append(cmd)
        self.envs.append(env)
        proc = FakeScrcpyProc(self.LINES)
        self.procs.append(proc)
        return proc

    @staticmethod
    def kill(proc):
        proc.code = 1
        proc.ended.set()


def mirror_factory(fake: FakeScrcpy):
    from pathlib import Path

    from admenot.engine.mirror import Mirror

    def build(on_state, on_warning, on_line, *, adb):
        return Mirror(on_state, on_warning, on_line, adb=adb,
                      scrcpy=lambda: Path("C:/tools/scrcpy.exe") if fake.available else None,
                      spawn=fake.spawn, kill=fake.kill)

    return build
