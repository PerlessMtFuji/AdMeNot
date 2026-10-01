import json

from conftest import SERIAL, make_synthetic_adb

from demalware.cli.main import main
from demalware.engine.adb.fake import FakeAdb
from demalware.engine.adb.transport import AdbError
from demalware.engine.apk.analyze import ApkReport
from demalware.engine.collectors.profiles import PM_USERS
from demalware.engine.collectors.system import DEVICE_POLICY
from demalware.engine.foreground import ACTIVITIES, WINDOWS


def test_devices_lists_entries(capsys):
    assert main(["devices"], host=make_synthetic_adb()) == 0
    out = capsys.readouterr().out
    assert SERIAL in out and "device" in out


def test_scan_json(capsys):
    assert main(["scan", "--json", "--lang", "en"], host=make_synthetic_adb()) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["results"][0]["package"] == "com.clean.pro.boost"


def test_scan_text_hides_safe_apps_by_default(capsys):
    assert main(["scan"], host=make_synthetic_adb()) == 0
    out = capsys.readouterr().out
    assert "com.clean.pro.boost" in out and "Szkodliwa" in out
    assert "com.whatsapp" not in out


def test_scan_text_all_shows_safe_apps(capsys):
    assert main(["scan", "--all"], host=make_synthetic_adb()) == 0
    assert "com.whatsapp" in capsys.readouterr().out


def test_no_device(capsys):
    host = make_synthetic_adb("List of devices attached\n\n")
    assert main(["scan"], host=host) == 2
    assert "Nie wykryto telefonu" in capsys.readouterr().err


def test_unauthorized_device(capsys):
    host = make_synthetic_adb("List of devices attached\nABC123 unauthorized usb:1-1\n")
    assert main(["scan"], host=host) == 3
    assert "ABC123" in capsys.readouterr().err


def test_multiple_devices_require_serial(capsys):
    host = make_synthetic_adb(
        f"List of devices attached\n{SERIAL} device usb:1-1\nOTHER1 device usb:1-2\n")
    assert main(["scan"], host=host) == 2
    assert "--serial" in capsys.readouterr().err
    assert main(["scan", "--serial", SERIAL, "--json"], host=host) == 0


def test_unknown_serial(capsys):
    assert main(["scan", "--serial", "NOPE"], host=make_synthetic_adb()) == 2


def test_adb_missing(capsys):
    host = FakeAdb(host={"devices -l": AdbError("adb_missing", "adb executable not found")})
    assert main(["devices"], host=host) == 4
    assert "adb" in capsys.readouterr().err


SIX_SDKS = ["admob", "applovin", "meta", "mintegral", "pangle", "vungle"]


class _FakeDeviceProvider:
    def __init__(self, adb, *args, **kwargs):
        pass

    def reports_for(self, apps, progress=None, flagged=frozenset()):
        for i, f in enumerate(apps, start=1):
            if progress:
                progress(i, len(apps), f.package)
        return {"com.wlive.forecast": ApkReport(
            "com.wlive.forecast", 31, label="Weather\u202e Live", label_padded=True,
            ad_sdks=SIX_SDKS, class_count=500)}


def test_scan_apk_shows_labels_and_progress(capsys, monkeypatch):
    monkeypatch.setattr("demalware.cli.main.DeviceApkProvider", _FakeDeviceProvider)
    assert main(["scan", "--apk"], host=make_synthetic_adb()) == 0
    captured = capsys.readouterr()
    assert "Weather Live (com.wlive.forecast)" in captured.out  # oczyszczona etykieta
    assert "Podejrzana" in captured.out
    assert "Analiza APK 3/3" in captured.err


def test_scan_apk_lists_failures(capsys, monkeypatch):
    class Failing(_FakeDeviceProvider):
        def reports_for(self, apps, progress=None, flagged=frozenset()):
            return {"com.clean.pro.boost": ApkReport("com.clean.pro.boost", error="timeout")}

    monkeypatch.setattr("demalware.cli.main.DeviceApkProvider", Failing)
    assert main(["scan", "--apk"], host=make_synthetic_adb()) == 0
    assert "[apk] com.clean.pro.boost: timeout" in capsys.readouterr().out


def test_who_prints_foreground_and_overlays(capsys):
    adb = make_synthetic_adb()
    adb.responses[ACTIVITIES] = "  topResumedActivity=ActivityRecord{1 u0 com.clean.pro.boost/.Ad t1}\n"
    adb.responses[WINDOWS] = ("  Window #1 Window{a u0 com.clean.pro.boost}:\n"
                              "    mAttrs={ty=APPLICATION_OVERLAY}\n    isOnScreen=true\n")
    assert main(["who", "--delay", "0"], host=adb) == 0
    out = capsys.readouterr().out
    assert "com.clean.pro.boost" in out and "Na pierwszym planie" in out


def test_who_reports_unknown_when_the_phone_does_not_answer(capsys):
    assert main(["who", "--delay", "0", "--lang", "en"], host=make_synthetic_adb()) == 0
    captured = capsys.readouterr()
    assert "Could not tell which app is in the foreground." in captured.out
    assert "Could not read windows over other apps." in captured.out
    assert "No windows over other apps." not in captured.out
    assert "[who] activities:" in captured.err and "[who] windows:" in captured.err


def test_scan_output_explains_incomplete_results_and_profiles(capsys):
    adb = make_synthetic_adb()
    adb.responses[DEVICE_POLICY] = AdbError("timeout", "slow")
    adb.responses[PM_USERS] = "Users:\n\tUserInfo{0:A:c13}\n\tUserInfo{10:W:1030}\n"
    assert main(["scan", "--all"], host=adb) == 0
    out = capsys.readouterr().out
    assert "brak danych: administratorzy urządzenia" in out
    assert "profil" in out and "10" in out


def _safe_only_report(adb):
    import dataclasses

    from demalware.engine.session import run_scan

    report = run_scan(adb)
    return dataclasses.replace(report, results=[r for r in report.results if r.verdict == "safe"])


def test_default_scan_counts_incomplete_safe_apps_separately(capsys):
    """Przegląd końcowy I2: „bez uwag” nigdy nie obejmuje aplikacji z oceną niepełną."""
    from demalware.cli.main import _print_report

    adb = make_synthetic_adb()
    adb.responses[DEVICE_POLICY] = AdbError("timeout", "slow")
    report = _safe_only_report(adb)
    assert report.results and all(r.incomplete for r in report.results)
    _print_report(report, "pl", show_all=False)
    out = capsys.readouterr().out
    assert "✓ Nie wykryto oznak zagrożenia" not in out
    assert "bez uwag" not in out.replace("0 aplikacji bez uwag", "")
    assert f"{len(report.results)} z oceną niepełną" in out
    assert "com.whatsapp" in out and "administratorzy urządzenia" in out
    assert "* ocena niepełna" in out
    _print_report(report, "en", show_all=False)
    out = capsys.readouterr().out
    assert "✓ No signs" not in out and "incomplete assessment" in out


def test_default_scan_all_clean_only_when_nothing_is_missing(capsys):
    from demalware.cli.main import _print_report

    report = _safe_only_report(make_synthetic_adb())
    assert report.results and not any(r.incomplete for r in report.results)
    _print_report(report, "pl", show_all=False)
    out = capsys.readouterr().out
    assert "✓ Nie wykryto oznak zagrożenia" in out and "niepełn" not in out


def test_scan_output_lists_collector_partial(capsys):
    from demalware.engine.collectors.behavior import APPOPS_GET

    adb = make_synthetic_adb()
    adb.responses[APPOPS_GET.format(package="com.whatsapp")] = AdbError("command_failed", "x")
    assert main(["scan"], host=adb) == 0
    out = capsys.readouterr().out
    assert "[appops]" in out and "com.whatsapp" in out


def test_scan_output_says_when_the_profile_list_is_unknown(capsys):
    """Przegląd końcowy M2: nieodczytana lista profili to nie „jeden profil”."""
    adb = make_synthetic_adb()
    adb.responses[PM_USERS] = AdbError("command_failed", "pm list users: denied")
    assert main(["scan"], host=adb) == 0
    assert "Nie udało się odczytać listy profili" in capsys.readouterr().out
    adb.responses[PM_USERS] = "Users:\n\tUserInfo{0:A:c13} running\n"
    assert main(["scan"], host=adb) == 0
    assert "listy profili" not in capsys.readouterr().out
    adb.responses[PM_USERS] = AdbError("command_failed", "pm list users: denied")
    assert main(["scan", "--lang", "en"], host=adb) == 0
    assert "Could not read the list of user profiles" in capsys.readouterr().out


def test_apk_provider_uses_the_limit_and_skips_without_asking(monkeypatch, tmp_path, capsys):
    from collections import namedtuple

    from demalware.cli import main as M
    from demalware.engine.apk import cache as C
    from demalware.engine.apk.cache import Estimate
    from demalware.engine.settings import save_settings

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    save_settings({"apk_cache_limit_gb": 3})
    provider = M._apk_provider(FakeAdb(), "pl")
    assert provider.policy.limit_bytes == 3 * C.GB
    est = Estimate(5 * C.GB, 5 * C.GB, 10, 0, 2 * C.GB, {})
    Use = namedtuple("Use", "size_bytes free_bytes disk_bytes limit_bytes effective_bytes")
    use = Use(0, C.GB, 100 * C.GB, 3 * C.GB, 0)
    provider.policy.on_estimate(est, use)
    assert provider.policy.decide(est, use) == "skip"
    err = capsys.readouterr().err
    assert "5,0 GB" in err and "Za mało miejsca" in err


def test_scan_apk_skipped_for_no_space_keeps_exit_code_and_says_so(capsys, monkeypatch):
    from demalware.engine.apk import cache as C
    from demalware.engine.apk.cache import Estimate

    class NoSpace(_FakeDeviceProvider):
        def __init__(self, adb, policy=None, **kwargs):
            self.policy = policy

        def reports_for(self, apps, progress=None, flagged=frozenset()):
            est = Estimate(5 * C.GB, 5 * C.GB, len(apps), 0, 2 * C.GB, {})
            use = C.CacheUsage(0, C.GB, 100 * C.GB, 3 * C.GB, 0)
            self.policy.on_estimate(est, use)
            assert self.policy.decide(est, use) == "skip"
            return {f.package: ApkReport(f.package, error=C.NO_SPACE) for f in apps}

    monkeypatch.setattr("demalware.cli.main.DeviceApkProvider", NoSpace)
    assert main(["scan", "--apk"], host=make_synthetic_adb()) == 0
    captured = capsys.readouterr()
    assert "Za mało miejsca" in captured.err
    assert "Zabrakło miejsca na dysku: przeanalizowano 0 z 3 aplikacji." in captured.out


def test_print_report_says_when_the_analysis_ran_out_of_space(capsys):
    from datetime import datetime

    from demalware.cli.main import _print_report
    from demalware.engine.device.info import DeviceInfo
    from demalware.engine.session import ApkStatus, ScanReport

    device = DeviceInfo("S", "b", "m", "model", "dev", None, "14", 34, None, 0.0, datetime(2026, 1, 1))
    report = ScanReport(device=device, collectors={}, low_behavior_data=False,
                        results=[], apk=ApkStatus(10, 4, {}, stopped_no_space=True))
    _print_report(report, "en", False)
    out = capsys.readouterr().out
    assert "Ran out of disk space: analyzed 4 of 10 apps." in out


def test_apk_estimate_uses_polish_plural_forms():
    from demalware.cli.main import _apps

    assert [_apps(n, "pl") for n in (1, 2, 4, 5, 12, 14, 21, 22, 24, 25, 112, 122)] == [
        "1 aplikacja", "2 aplikacje", "4 aplikacje", "5 aplikacji", "12 aplikacji",
        "14 aplikacji", "21 aplikacji", "22 aplikacje", "24 aplikacje", "25 aplikacji",
        "112 aplikacji", "122 aplikacje"]
    assert [_apps(n, "en") for n in (1, 2, 0)] == ["1 app", "2 apps", "0 apps"]


def test_apk_estimate_says_what_is_already_cached(capsys, monkeypatch, tmp_path):
    from demalware.cli import main as M
    from demalware.engine.apk import cache as C
    from demalware.engine.apk.cache import Estimate

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    provider = M._apk_provider(FakeAdb(), "pl")
    use = C.CacheUsage(0, 100 * C.GB, 100 * C.GB, 10 * C.GB, 10 * C.GB)
    sizes = {"a": C.GB, "b": C.GB, "c": 30 * 1024**2}
    provider.policy.on_estimate(Estimate(3 * C.GB, 0, 3, 0, 0, sizes), use)
    provider.policy.on_estimate(Estimate(3 * C.GB, 30 * 1024**2, 3, 0, 0, sizes, frozenset({"c"})), use)
    err = capsys.readouterr().err
    assert "Pliki wszystkich aplikacji do analizy APK (3) są już na komputerze" in err
    assert "Analiza APK pobierze ok. 30 MB (1 z 3 aplikacji, pozostałe są już na komputerze)." in err


def test_apk_size_switches_to_mb_below_a_tenth_of_a_gigabyte():
    from demalware.cli.main import _size

    assert [_size(n, "pl") for n in (0, 1, 30 * 1024**2, 1024**3 // 10 + 1, 7 * 1024**3)] == [
        "0,0 GB", "1 MB", "30 MB", "0,1 GB", "7,0 GB"]


def test_scan_deep_passes_the_packages_to_the_provider(capsys, monkeypatch):
    made = {}

    class Recording(_FakeDeviceProvider):
        def __init__(self, adb, *args, **kwargs):
            made.update(kwargs)

    monkeypatch.setattr("demalware.cli.main.DeviceApkProvider", Recording)
    assert main(["scan", "--deep", "com.a.b,com.c.d"], host=make_synthetic_adb()) == 0
    assert made["deep"] == frozenset({"com.a.b", "com.c.d"})  # --deep włącza analizę APK


def test_scan_deep_rejects_a_bad_package_name(capsys):
    assert main(["scan", "--apk", "--deep", "com.a;rm -rf"], host=make_synthetic_adb()) == 2
    assert "com.a;rm -rf" in capsys.readouterr().err


def test_who_watch_records_an_incident_that_the_next_scan_uses(capsys, monkeypatch, tmp_path):
    from demalware.engine.incident import Sample, Timeline

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    timeline = Timeline([Sample(0.0, "com.game", ["com.clean.pro.boost"], None, [])], marks=[0.0])
    seen = {}

    def fake_record(adb, duration_s, interval_s, **kw):
        seen.update(duration=duration_s, interval=interval_s, poll=kw["poll_mark"]())
        return timeline

    monkeypatch.setattr("demalware.cli.main.record", fake_record)
    assert main(["who", "--watch", "30", "--interval", "1.5"], host=make_synthetic_adb()) == 0
    out = capsys.readouterr().out
    assert seen == {"duration": 30.0, "interval": 1.5, "poll": False}
    assert "com.clean.pro.boost" in out and "com.game" in out
    assert (tmp_path / "DeMalware" / "incidents" / f"{SERIAL}.json").exists()

    assert main(["scan", "--json"], host=make_synthetic_adb()) == 0
    results = {r["package"]: r for r in json.loads(capsys.readouterr().out)["results"]}
    assert "DM-INCIDENT-01" in {f["rule_id"] for f in results["com.clean.pro.boost"]["findings"]}


def test_who_watch_without_marks_says_nothing_was_marked(capsys, monkeypatch, tmp_path):
    from demalware.engine.incident import Sample, Timeline

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("demalware.cli.main.record",
                        lambda adb, d, i, **kw: Timeline([Sample(0.0, "com.game", [], None, [])], []))
    assert main(["who", "--watch", "5"], host=make_synthetic_adb()) == 0
    assert "Enter" in capsys.readouterr().out


def test_scan_deep_warns_about_packages_it_did_not_analyze(capsys, monkeypatch):
    monkeypatch.setattr("demalware.cli.main.DeviceApkProvider", _FakeDeviceProvider)
    assert main(["scan", "--deep", "com.not.there"], host=make_synthetic_adb()) == 0
    assert "com.not.there" in capsys.readouterr().err


def test_who_watch_rejects_a_bad_interval(capsys):
    import pytest as _pytest

    for bad in (["--interval", "-1"], ["--interval", "0"], ["--watch", "-5"]):
        with _pytest.raises(SystemExit) as exc:
            main(["who", "--watch", "30", *bad], host=make_synthetic_adb())
        assert exc.value.code == 2
