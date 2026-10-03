import shutil

import pytest
from fakephone import FakeApp, FakePhone, apk_bytes

from admenot.engine.actions.context import read_phone_context
from admenot.engine.actions.executor import ExecOptions, run_order, start_order, undo, verify
from admenot.engine.actions.planner import plan_app
from admenot.engine.adb.transport import AdbError
from admenot.engine.allowlist.trust import load_protected_list
from admenot.engine.apk.fetch import fetch_apks
from admenot.engine.facts import AppFacts
from admenot.engine.journal.db import Journal

SAW = "android.permission.SYSTEM_ALERT_WINDOW"  # aplikacje w tych testach mogą rysować nad innymi
SPLITS = ("base.apk", "split_config.arm64_v8a.apk")
BACKUP = ("backups", "SERIAL", "com.spam", "7")


@pytest.fixture
def journal(tmp_path):
    with Journal(tmp_path / "journal.db") as j:
        yield j


def _phone(keeps_apk=False, sha256sum=False):
    return FakePhone([
        FakeApp("com.spam", version_code=7, apks=SPLITS, keeps_apk=keeps_apk),
        FakeApp("com.android.launcher", system=True, home_activity=".Launcher"),
    ], sdk=31, sha256sum=sha256sum)


def _remove(phone, journal, tmp_path, options=None):
    ctx = read_phone_context(phone)
    plan = plan_app("com.spam", "remove", AppFacts("com.spam", version_code=7, requested_permissions={SAW}), ctx,
                    load_protected_list(), tmp_path / "backups" / "SERIAL")
    order = start_order(journal, phone.serial, "Test", [plan])
    return order, run_order(phone, journal, order.id, options or ExecOptions())


def test_remove_backs_up_all_splits_then_uninstalls(journal, tmp_path):
    phone = _phone()
    order, (outcome,) = _remove(phone, journal, tmp_path)
    assert outcome.ok and not phone.apps["com.spam"].installed
    backup = tmp_path.joinpath(*BACKUP)
    assert sorted(p.name for p in backup.glob("*.apk")) == sorted(SPLITS)
    assert (backup / ".complete").exists()
    assert (backup / "base.apk").read_bytes() == apk_bytes("com.spam", "base.apk")
    assert verify(phone, journal, order.id) == {}


def test_undo_prefers_install_existing(journal, tmp_path):
    phone = _phone(keeps_apk=True)
    order, _ = _remove(phone, journal, tmp_path)
    assert undo(phone, journal, order.id) == []
    assert phone.apps["com.spam"].installed
    assert "cmd package install-existing --user 0 com.spam" in phone.calls
    assert not [c for c in phone.calls if c.startswith("host:install")]


def test_undo_reinstalls_from_backup_when_apk_is_gone(journal, tmp_path):
    phone = _phone()
    order, _ = _remove(phone, journal, tmp_path)
    assert undo(phone, journal, order.id) == []
    app = phone.apps["com.spam"]
    assert app.installed and app.enabled
    (install,) = [c for c in phone.calls if c.startswith("host:install")]
    assert install.startswith("host:install-multiple ") and "split_config.arm64_v8a.apk" in install


def test_failed_backup_blocks_uninstall(journal, tmp_path):
    phone = _phone()
    phone.fail["pm path com.spam"] = AdbError("command_failed", "")
    _, (outcome,) = _remove(phone, journal, tmp_path)
    assert outcome.failed == [("backup", "backup_failed"), ("installed", "skipped")]
    assert phone.apps["com.spam"].installed
    assert "pm uninstall --user 0 com.spam" not in phone.calls
    assert phone.apps["com.spam"].appops["SYSTEM_ALERT_WINDOW"] == "deny"  # wyciszenie zostaje


def test_uninstall_failure_with_exit_code_zero(journal, tmp_path):
    phone = _phone()
    phone.fail["pm uninstall --user 0 com.spam"] = "Failure [DELETE_FAILED_INTERNAL_ERROR]\n"
    _, (outcome,) = _remove(phone, journal, tmp_path)
    assert outcome.failed == [("installed", "failed")]
    assert phone.apps["com.spam"].installed


def test_backup_reuses_apk_cache_and_is_not_refetched(journal, tmp_path):
    phone = _phone(keeps_apk=True, sha256sum=True)
    fetch_apks(phone, "com.spam", tmp_path / "apk-cache")  # jak analiza APK przed naprawą
    phone.calls.clear()
    order, _ = _remove(phone, journal, tmp_path, ExecOptions(apk_cache_dir=tmp_path / "apk-cache"))
    assert not [c for c in phone.calls if c.startswith("host:pull")]
    assert tmp_path.joinpath(*BACKUP, "split_config.arm64_v8a.apk").exists()
    undo(phone, journal, order.id)
    _remove(phone, journal, tmp_path)  # drugie usunięcie tej samej wersji: kopia już jest
    assert not [c for c in phone.calls if c.startswith("host:pull")]


def test_reinstall_without_backup_is_reported(journal, tmp_path):
    phone = _phone()
    order, _ = _remove(phone, journal, tmp_path)
    shutil.rmtree(tmp_path / "backups")
    errors = undo(phone, journal, order.id)
    assert (errors[0][0].step["kind"], errors[0][1]) == ("installed", "no_backup")
    assert not phone.apps["com.spam"].installed
    assert journal.order(order.id).status == "partially_undone"


def test_undo_remove_keeps_app_disabled_if_it_was_disabled_before(journal, tmp_path):
    for keeps_apk in (False, True):
        phone = _phone(keeps_apk=keeps_apk)
        phone.apps["com.spam"].enabled = False  # wyłączona przed naprawą
        order, _ = _remove(phone, journal, tmp_path / str(keeps_apk))
        assert undo(phone, journal, order.id) == []
        app = phone.apps["com.spam"]
        assert app.installed and app.enabled is False, keeps_apk


def test_failed_restore_keeps_other_steps_for_a_later_undo(journal, tmp_path):
    phone = FakePhone([
        FakeApp("com.spam", version_code=7, apks=SPLITS, home_activity=".Home"),
        FakeApp("com.android.launcher", system=True, home_activity=".Launcher"),
    ], sdk=31, home="com.spam/.Home")
    order, _ = _remove(phone, journal, tmp_path)
    original = phone._install
    phone._install = lambda files: (_ for _ in ()).throw(
        AdbError("command_failed", "Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]"))
    errors = undo(phone, journal, order.id)
    assert errors and not phone.apps["com.spam"].installed
    assert not [a for a in journal.actions(order.id) if a.error == "app_gone"]
    phone._install = original  # serwisant zwolnił miejsce
    assert undo(phone, journal, order.id) == []
    assert phone.apps["com.spam"].installed and phone.home == "com.spam/.Home"
    assert journal.order(order.id).status == "undone"


def test_backup_fails_when_the_cache_entry_vanished_after_fetch(journal, tmp_path, monkeypatch):
    """Wpis przycięty (np. przez CLI obok) między `fetch_apks` a kopią: bez kopii nie odinstalowujemy."""
    from admenot.engine.actions import backup as B
    from admenot.engine.apk.fetch import FetchedApks

    gone = tmp_path / "apk-cache" / "com.spam" / "id"
    monkeypatch.setattr(B, "fetch_apks", lambda adb, package, cache_dir: FetchedApks(
        [gone / name for name in SPLITS], verified=True))
    phone = _phone()
    _, (outcome,) = _remove(phone, journal, tmp_path)
    assert outcome.failed == [("backup", "backup_failed"), ("installed", "skipped")]
    assert phone.apps["com.spam"].installed
    backup = tmp_path.joinpath(*BACKUP)
    assert not B.is_complete(backup) and not (backup / ".complete").exists()
    assert not backup.with_name(backup.name + ".part").exists()


def test_backup_copies_exactly_the_fetched_files(tmp_path, monkeypatch):
    """Inny plik w katalogu wpisu (np. z innej instalacji) nie trafia do kopii."""
    from admenot.engine.actions import backup as B
    from admenot.engine.apk.fetch import FetchedApks

    cached = tmp_path / "apk-cache" / "com.spam" / "id"
    cached.mkdir(parents=True)
    for name in (*SPLITS, "stray.apk"):
        (cached / name).write_bytes(name.encode())
    monkeypatch.setattr(B, "fetch_apks", lambda adb, package, cache_dir: FetchedApks(
        [cached / name for name in SPLITS], verified=True))
    target = tmp_path / "backups" / "S" / "com.spam" / "7"
    paths = B.backup_apks(None, "com.spam", 7, target, tmp_path / "apk-cache")
    assert sorted(p.name for p in paths) == sorted(SPLITS)
    assert B.is_complete(target)
