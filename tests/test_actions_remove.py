import shutil

import pytest
from fakephone import FakeApp, FakePhone, apk_bytes

from demalware.engine.actions.context import read_phone_context
from demalware.engine.actions.executor import ExecOptions, run_order, start_order, undo, verify
from demalware.engine.actions.planner import plan_app
from demalware.engine.adb.transport import AdbError
from demalware.engine.allowlist.trust import load_protected_list
from demalware.engine.facts import AppFacts
from demalware.engine.journal.db import Journal

SPLITS = ("base.apk", "split_config.arm64_v8a.apk")
BACKUP = ("backups", "SERIAL", "com.spam", "7")


@pytest.fixture
def journal(tmp_path):
    with Journal(tmp_path / "journal.db") as j:
        yield j


def _phone(keeps_apk=False):
    return FakePhone([
        FakeApp("com.spam", version_code=7, apks=SPLITS, keeps_apk=keeps_apk),
        FakeApp("com.android.launcher", system=True, home_activity=".Launcher"),
    ], sdk=31)


def _remove(phone, journal, tmp_path, options=None):
    ctx = read_phone_context(phone)
    plan = plan_app("com.spam", "remove", AppFacts("com.spam", version_code=7), ctx,
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
    cache = tmp_path / "apk-cache" / "com.spam" / "7"
    cache.mkdir(parents=True)
    for name in SPLITS:
        (cache / name).write_bytes(apk_bytes("com.spam", name))
    (cache / ".complete").write_text("", encoding="utf-8")
    phone = _phone(keeps_apk=True)
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
