"""Zmiany nowego telefonu (appop, rola SMS, aplikacja pomocnicza, katalog pomocnika) i ich odwracanie.

Wszystkie polecenia idą przez prawdziwego strażnika `TelephonyWriteAdb` opakowującego atrapę telefonu.
"""

from __future__ import annotations

import shutil

import pytest
from faketransfer import FakeStoragePhone

from admenot.engine.paths import device_dir_name, phone_changes_dir
from admenot.engine.transfer import helper, phonesetup
from admenot.engine.transfer.phonesetup import (
    DeviceChanges,
    cleanup,
    device_changes,
    install_companion,
    mark_helper_dir,
    open_changes,
    pending_cleanup,
    read_appop,
    set_appop_allow,
    sms_role_holders,
    take_sms_role,
    telephony_adb,
)
from admenot.engine.transfer.restore_state import (
    RestoreState,
    keep_copy_changes,
    read_restores,
    restore_state_path,
)
from admenot.engine.transfer.store import CopyDir

PREV = "com.google.android.apps.messaging"
PKG = helper.PACKAGE

# `adb -s TESTSERIAL000001 shell dumpsys role` (OPPO CPH2271, Android 12), fragment, końce linii CRLF
OPPO_DUMPSYS_ROLE = (
    "ROLE STATE (dumpsys role):\r\n{\r\n  user_states={\r\n    user_id=0\r\n    version=-1\r\n"
    "    packages_hash=4EDB71C99ABF66F502320077BDBD69BF1D46493D296C78F48E7C09F4B84FF405\r\n"
    "    roles=[\r\n"
    "      {\r\n        name=android.app.role.SYSTEM_COMPANION_DEVICE_PROVIDER\r\n"
    "        fallback_enabled=false\r\n        holders=com.google.android.gms\r\n      }\r\n"
    "      {\r\n        name=android.app.role.SMS\r\n        fallback_enabled=false\r\n"
    "        holders=com.google.android.apps.messaging\r\n      }\r\n"
    "      {\r\n        name=android.app.role.SYSTEM_UI_INTELLIGENCE\r\n        fallback_enabled=false\r\n"
    "      }\r\n"
    "      {\r\n        name=android.app.role.DIALER\r\n        fallback_enabled=false\r\n"
    "        holders=com.google.android.dialer\r\n      }\r\n"
    "    ]\r\n  }\r\n}\r\n"
)
# `adb -s testserial000002 shell dumpsys role` (Xiaomi Redmi Note 12 Pro, MIUI/Android 13): bez `fallback_enabled`
XIAOMI_DUMPSYS_ROLE = (
    "      {\r\n        name=android.app.role.SMS\r\n        holders=com.google.android.apps.messaging\r\n"
    "      }\r\n      {\r\n        name=android.app.role.SYSTEM_UI_INTELLIGENCE\r\n      }\r\n"
    "      {\r\n        name=android.app.role.DIALER\r\n        holders=com.google.android.dialer\r\n      }\r\n"
)


class _Out:
    serial = "X"

    def __init__(self, out: str) -> None:
        self.out = out

    def shell(self, command: str, timeout: float = 20.0) -> str:
        return self.out


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    monkeypatch.setattr(phonesetup, "_sleep", lambda s: None)


def _setup(tmp_path, **kw):
    (tmp_path / "phone" / "sdcard").mkdir(parents=True)
    phone = FakeStoragePhone(tmp_path / "phone", serial="NEW")
    phone.role_holders = [PREV]
    for k, v in kw.items():
        setattr(phone, k, v)
    copy = CopyDir(tmp_path / "copy")
    state = RestoreState(restore_state_path(copy, "NEW"))
    return phone, copy, state, telephony_adb(phone, state)


def _never() -> bool:
    return False


def _with_helper_dir(phone, adb, state) -> None:
    mark_helper_dir(state)
    adb.shell(f"mkdir -p {helper.HELPER_IN}")
    src = phone.root.parent / "input.jsonl"
    src.write_text("{}\n", encoding="utf-8")
    assert phone.push([src], helper.HELPER_IN + "/", _never, lambda: None).rc == 0
    assert phone.tmp_files


# ---- odczyty ----------------------------------------------------------------------------------
def test_sms_role_holders_parses_real_dumpsys():
    assert sms_role_holders(_Out(OPPO_DUMPSYS_ROLE)) == (PREV,)
    assert sms_role_holders(_Out(XIAOMI_DUMPSYS_ROLE)) == (PREV,)
    no_holder = OPPO_DUMPSYS_ROLE.replace("        holders=com.google.android.apps.messaging\r\n", "")
    assert sms_role_holders(_Out(no_holder)) == ()  # nie bierze `holders=` sąsiedniej roli


def test_read_appop_real_outputs():
    # `appops get com.android.shell WRITE_SMS` na OPPO (wpis po wcześniejszym `set … default`)
    assert read_appop(_Out("WRITE_SMS: default; time=+2h37m59s813ms ago; "
                           "rejectTime=+15m4s912ms ago\r\n")) == "default"
    # brak wpisu (OPPO przed spike'iem): obowiązuje tryb domyślny, przywracamy go jawnie (R5)
    assert read_appop(_Out("No operations.\r\nDefault mode: ignore\r\n")) == "ignore"
    assert read_appop(_Out("No operations.\r\n")) == "default"
    assert read_appop(_Out("Uid mode: WRITE_SMS: allow\nWRITE_SMS: ignore; time=+1s ago\n")) == "ignore"


# ---- Review Focus 1 i 5 ----------------------------------------------------------------------
def test_cleanup_restores_empty_role_and_default_appop(tmp_path):
    phone, copy, state, adb = _setup(tmp_path, role_holders=[], appop="default")
    set_appop_allow(adb, state)
    assert phone.appop == "allow"
    assert install_companion(adb, state) == "ok"
    assert take_sms_role(adb, state, lambda r: None, _never, _never) == "ok"
    assert phone.role_holders == [PKG]
    _with_helper_dir(phone, adb, state)
    assert device_changes(state) == DeviceChanges("default", (), True, True)
    res = cleanup(adb, state, lambda r: None, _never)
    assert res.ok and (res.role_ok, res.appop_ok, res.companion_removed, res.helper_removed) == (
        True, True, True, True)
    assert phone.role_holders == [] and phone.appop == "default"
    assert PKG not in phone.installed and phone.tmp_files == set()
    assert f"cmd role remove-role-holder android.app.role.SMS {PKG}" in phone.commands
    assert device_changes(state) == DeviceChanges()
    assert pending_cleanup([copy], "NEW") == []


def test_cleanup_restores_effective_default_when_no_appop_entry(tmp_path):
    phone, _, state, adb = _setup(tmp_path, appop=None, appop_default="ignore")
    set_appop_allow(adb, state)
    assert device_changes(state).appop_prev == "ignore"
    assert cleanup(adb, state, lambda r: None, _never).ok
    assert phone.appop == "ignore"  # nie `default`: na OPPO jawne `default` pozwala shellowi pisać SMS


def test_cleanup_after_crash_restores_role(tmp_path):
    phone, copy, state, adb = _setup(tmp_path)
    assert install_companion(adb, state) == "ok"
    assert take_sms_role(adb, state, lambda r: None, _never, _never) == "ok"
    _with_helper_dir(phone, adb, state)
    state.set_meta("serial", "NEW")
    state.set_meta("status", "running")
    state.db.close()  # program zamknięty bez sprzątania (bez `close()`)
    assert phone.role_holders == [PKG]

    assert pending_cleanup([copy], "NEW") == [restore_state_path(copy, "NEW")]
    assert pending_cleanup([copy], "OTHER") == []
    (summary,) = read_restores(copy)
    assert summary.cleanup_pending
    state2 = RestoreState(restore_state_path(copy, "NEW"))
    res = cleanup(telephony_adb(phone, state2), state2, lambda r: None, _never)
    assert res.ok
    assert phone.role_holders == [PREV]
    assert PKG not in phone.installed and phone.tmp_files == set()
    assert pending_cleanup([copy], "NEW") == []
    assert not read_restores(copy)[0].cleanup_pending


def _record(serial: str = "NEW"):
    return phone_changes_dir() / f"{device_dir_name(serial)}.json"


def test_changes_are_recorded_per_phone_outside_the_copy(tmp_path):
    """Zapis zmian telefonu leży też poza kopią (`phone_changes/<telefon>.json`): usunięta kopia nie
    zabiera go ze sobą, sprzątanie przy podłączeniu czyta go stamtąd i na końcu usuwa."""
    phone, copy, state, adb = _setup(tmp_path, appop="default")
    set_appop_allow(adb, state)
    assert install_companion(adb, state) == "ok"
    assert take_sms_role(adb, state, lambda r: None, _never, _never) == "ok"
    _with_helper_dir(phone, adb, state)
    assert _record().is_file()
    state.close()
    shutil.rmtree(copy.path)  # kopia usunięta przed sprzątaniem

    (path,) = pending_cleanup([], "NEW")
    assert path == _record() and pending_cleanup([], "OTHER") == []
    record = open_changes(path)
    assert device_changes(record) == DeviceChanges("default", (PREV,), True, True)
    assert cleanup(telephony_adb(phone, record), record, lambda r: None, _never).ok
    assert phone.role_holders == [PREV] and phone.appop == "default"
    assert PKG not in phone.installed and phone.tmp_files == set()
    assert not _record().exists() and pending_cleanup([], "NEW") == []


def test_state_and_record_merge_so_nothing_is_forgotten(tmp_path):
    """Stan sprzed zapisu poza kopią (zmiany tylko w kopii) i zapis telefonu z innego wgrywania: sprzątanie
    widzi obie listy i czyści obie."""
    phone, copy, state, adb = _setup(tmp_path)
    assert install_companion(adb, state) == "ok"
    assert take_sms_role(adb, state, lambda r: None, _never, _never) == "ok"
    state.set_meta("device_changes", {"appop_prev": "default", "role_prev": None, "companion": False,
                                      "helper_dir": False})  # stary stan: tylko w kopii
    phone.appop = "allow"
    assert device_changes(state) == DeviceChanges("default", (PREV,), True, False)
    assert pending_cleanup([copy], "NEW") == [restore_state_path(copy, "NEW")]  # zapis telefonu pokrywa stan
    assert cleanup(telephony_adb(phone, state), state, lambda r: None, _never).ok
    assert phone.role_holders == [PREV] and phone.appop == "default" and PKG not in phone.installed
    assert not _record().exists() and pending_cleanup([copy], "NEW") == []


def test_keep_copy_changes_moves_old_states_to_the_phone_record(tmp_path):
    _phone, copy, state, _adb = _setup(tmp_path)
    state.set_meta("device_changes", {"appop_prev": None, "role_prev": [PREV], "companion": True,
                                      "helper_dir": False})
    state.close()
    keep_copy_changes(copy)
    record = open_changes(_record())
    assert device_changes(record) == DeviceChanges(None, (PREV,), True, False)
    keep_copy_changes(CopyDir(tmp_path / "missing"))  # kopia bez stanów: nic


def test_cleanup_waits_for_tap_until_role_restored(tmp_path, monkeypatch):
    phone, _, state, adb = _setup(tmp_path)
    assert install_companion(adb, state) == "ok"
    assert take_sms_role(adb, state, lambda r: None, _never, _never) == "ok"
    phone.role_restore_needs_tap = True
    polls = []

    def sleep(seconds):
        assert seconds == phonesetup.TAP_POLL
        polls.append(seconds)
        if len(polls) == 2:
            phone.tap_role(PREV)

    monkeypatch.setattr(phonesetup, "_sleep", sleep)
    taps: list[str | None] = []
    res = cleanup(adb, state, taps.append, _never)
    assert res.ok and len(polls) == 2
    assert taps == ["sms_role_restore", None]
    assert "am start -a android.settings.MANAGE_DEFAULT_APPS_SETTINGS" in phone.commands
    assert phone.role_holders == [PREV] and PKG not in phone.installed


def test_cleanup_stop_keeps_changes_pending(tmp_path):
    phone, copy, state, adb = _setup(tmp_path, appop="default")
    set_appop_allow(adb, state)
    assert install_companion(adb, state) == "ok"
    assert take_sms_role(adb, state, lambda r: None, _never, _never) == "ok"
    phone.role_restore_needs_tap = True
    stops = iter([False, True])
    taps: list[str | None] = []
    res = cleanup(adb, state, taps.append, lambda: next(stops))
    assert not res.ok and not res.role_ok and not res.companion_removed
    assert res.appop_ok and phone.appop == "default"  # bezpieczne kroki i tak zrobione
    assert taps == ["sms_role_restore", None]
    assert device_changes(state) == DeviceChanges(None, (PREV,), True, False)
    assert pending_cleanup([copy], "NEW") == [restore_state_path(copy, "NEW")]
    # następne podłączenie: rola wraca bez stuknięcia, reszta też
    phone.role_restore_needs_tap = False
    assert cleanup(adb, state, taps.append, _never).ok
    assert phone.role_holders == [PREV] and PKG not in phone.installed
    assert pending_cleanup([copy], "NEW") == []


def test_cleanup_is_idempotent_and_quiet_without_changes(tmp_path):
    phone, _, state, adb = _setup(tmp_path)
    assert cleanup(adb, state, lambda r: None, _never).ok
    assert phone.commands == []  # nic nie zmienialiśmy, więc nic nie wysyłamy


def test_appop_prev_not_overwritten_on_resume(tmp_path):
    phone, copy, state, adb = _setup(tmp_path, appop="default")
    set_appop_allow(adb, state)
    state.close()
    state2 = RestoreState(restore_state_path(copy, "NEW"))
    assert phone.appop == "allow"
    set_appop_allow(telephony_adb(phone, state2), state2)  # wznowienie: odczyt pokazuje już `allow`
    assert device_changes(state2).appop_prev == "default"
    assert cleanup(telephony_adb(phone, state2), state2, lambda r: None, _never).ok
    assert phone.appop == "default"


def test_refused_appop_set_leaves_nothing_to_restore(tmp_path):
    """Telefon nie przyjął `appops set … allow`: tryb nadal jest poprzedni, więc nie ma czego odwracać
    (sprzątanie, które ponawiałoby tę samą odmowę, nigdy by się nie udało)."""
    phone, copy, state, adb = _setup(tmp_path, appop="ignore", appop_refused={"allow", "ignore"})
    set_appop_allow(adb, state)
    assert phone.appop == "ignore"
    assert device_changes(state).appop_prev is None
    assert pending_cleanup([copy], "NEW") == []


def test_restore_appop_already_back_is_restored_without_set(tmp_path):
    """Zapisany poprzedni tryb, a telefon już go ma (np. `set` wcześniej odmówiony albo przywrócony
    ręcznie): sprzątanie uznaje appop za przywrócone bez `appops set`, którego telefon by odmówił."""
    phone, copy, state, adb = _setup(tmp_path, appop="ignore", appop_refused={"ignore"})
    phonesetup._update(state, appop_prev="ignore")
    res = cleanup(adb, state, lambda r: None, _never)
    assert res.ok and res.appop_ok
    assert not any(c.startswith("appops set") for c in phone.commands)
    assert device_changes(state) == DeviceChanges()
    assert pending_cleanup([copy], "NEW") == []


def test_restore_appop_refused_set_keeps_change_pending(tmp_path):
    phone, _, state, adb = _setup(tmp_path, appop="default")
    set_appop_allow(adb, state)
    assert phone.appop == "allow" and device_changes(state).appop_prev == "default"
    phone.appop_refused = {"default"}
    assert not cleanup(adb, state, lambda r: None, _never).appop_ok
    assert device_changes(state).appop_prev == "default"


def test_install_blocked_reports_blocked(tmp_path):
    phone, _, state, adb = _setup(tmp_path, install_blocked=True)
    assert install_companion(adb, state) == "blocked"
    assert device_changes(state).companion  # sprzątanie i tak sprawdzi `pm list`
    res = cleanup(adb, state, lambda r: None, _never)
    assert res.ok and res.companion_removed
    assert f"pm uninstall {PKG}" not in phone.commands
    assert device_changes(state) == DeviceChanges()


def test_install_removes_leftover_first_and_checks_apk(tmp_path, monkeypatch):
    phone, _, state, adb = _setup(tmp_path)
    phone.installed.add(PKG)  # pozostałość po awarii
    assert install_companion(adb, state) == "ok"
    assert f"pm uninstall {PKG}" in phone.commands and PKG in phone.installed

    def broken(name, bin_dir=None):
        raise helper.HelperBroken("admenot-helper.apk: hash does not match SHA256SUMS")

    monkeypatch.setattr(helper, "artifact", broken)
    installs = len(phone.host_commands)
    with pytest.raises(helper.HelperBroken):
        install_companion(adb, state)
    assert len(phone.host_commands) == installs  # niezweryfikowany APK nie trafia na telefon


def test_uninstall_only_after_role_confirmed(tmp_path):
    phone, _, state, adb = _setup(tmp_path)
    assert install_companion(adb, state) == "ok"
    assert take_sms_role(adb, state, lambda r: None, _never, _never) == "ok"
    phone.role_restore_needs_tap = True
    res = cleanup(adb, state, lambda r: None, lambda: True)
    assert not res.role_ok and not res.companion_removed
    assert f"pm uninstall {PKG}" not in phone.commands
    assert PKG in phone.installed and phone.role_holders == [PKG]
    phone.role_restore_needs_tap = False
    assert cleanup(adb, state, lambda r: None, _never).ok
    restore = phone.commands.index(f"cmd role add-role-holder android.app.role.SMS {PREV}")
    assert phone.commands.index(f"pm uninstall {PKG}") > restore
    assert phone.role_holders == [PREV]  # odinstalowanie nie zabrało roli poprzedniej aplikacji


# ---- rola SMS dla aplikacji pomocniczej -------------------------------------------------------
def test_take_sms_role_waits_for_tap(tmp_path, monkeypatch):
    phone, _, state, adb = _setup(tmp_path, role_needs_tap=True)
    assert install_companion(adb, state) == "ok"
    monkeypatch.setattr(phonesetup, "_sleep", lambda s: phone.tap_role(PKG))
    taps: list[str | None] = []
    assert take_sms_role(adb, state, taps.append, _never, _never) == "ok"
    assert taps == ["sms_role_grant", None]
    assert f"am start -n {PKG}/.RoleActivity" in phone.commands
    assert device_changes(state).role_prev == (PREV,)


def test_take_sms_role_skip_tap(tmp_path):
    phone, _, state, adb = _setup(tmp_path, role_needs_tap=True)
    assert install_companion(adb, state) == "ok"
    taps: list[str | None] = []
    assert take_sms_role(adb, state, taps.append, _never, lambda: True) == "skipped"
    assert taps == ["sms_role_grant", None]
    assert device_changes(state).role_prev == (PREV,)  # sprzątanie i tak sprawdzi rolę
    assert cleanup(adb, state, lambda r: None, _never).ok and phone.role_holders == [PREV]


def test_take_sms_role_keeps_saved_prev_on_resume(tmp_path):
    _, _, state, adb = _setup(tmp_path)
    assert install_companion(adb, state) == "ok"
    assert take_sms_role(adb, state, lambda r: None, _never, _never) == "ok"
    assert take_sms_role(adb, state, lambda r: None, _never, _never) == "ok"  # odczyt: już nasza
    assert device_changes(state).role_prev == (PREV,)


# ---- stan ------------------------------------------------------------------------------------
def test_tel_status_and_set(tmp_path):
    copy = CopyDir(tmp_path / "copy")
    state = RestoreState(restore_state_path(copy, "NEW"))
    assert state.tel_status("sms") == {}
    state.tel_set("sms", ["a", "b"], "done", "app_process")
    state.tel_set("sms", ["b"], "error", "companion", "ERR_X")
    state.tel_set("calls", ["a"], "manual", "file")
    state.close()
    state = RestoreState(restore_state_path(copy, "NEW"))
    assert state.tel_status("sms") == {"a": "done", "b": "error"}
    assert state.tel_status("calls") == {"a": "manual"}
    row = state.db.execute("SELECT path, error FROM tel WHERE kind='sms' AND rid='b'").fetchone()
    assert row == ("companion", "ERR_X")


# ---- R14: nigdy nie odinstalowujemy posiadacza roli SMS ----------------------------------------
def test_install_leftover_holding_role_is_blocked_not_uninstalled(tmp_path):
    phone, _, state, adb = _setup(tmp_path, role_holders=[PKG])
    phone.installed.add(PKG)  # pozostałość po niedokończonym sprzątaniu, z rolą SMS
    assert install_companion(adb, state) == "blocked"
    assert f"pm uninstall {PKG}" not in phone.commands and phone.host_commands == []
    assert PKG in phone.installed and phone.role_holders == [PKG]
    assert device_changes(state) == DeviceChanges(None, None, True, False)


def test_cleanup_leftover_holding_role_waits_for_tap_then_uninstalls(tmp_path, monkeypatch):
    phone, _, state, adb = _setup(tmp_path, role_holders=[PKG])
    phone.installed.add(PKG)
    assert install_companion(adb, state) == "blocked"
    polls = []

    def sleep(seconds):
        polls.append(seconds)
        if len(polls) == 2:
            phone.tap_role(PREV)

    monkeypatch.setattr(phonesetup, "_sleep", sleep)
    taps: list[str | None] = []
    res = cleanup(adb, state, taps.append, _never)
    assert res.ok and len(polls) == 2 and taps == ["sms_role_restore", None]
    settings = phone.commands.index("am start -a android.settings.MANAGE_DEFAULT_APPS_SETTINGS")
    assert phone.commands.index(f"pm uninstall {PKG}") > settings
    assert not any(c.startswith("cmd role") for c in phone.commands)  # nie wiemy, komu oddać rolę
    assert PKG not in phone.installed and phone.role_holders == [PREV]
    assert device_changes(state) == DeviceChanges()


def test_cleanup_leftover_holding_role_stop_keeps_it_installed(tmp_path):
    phone, copy, state, adb = _setup(tmp_path, role_holders=[PKG])
    phone.installed.add(PKG)
    assert install_companion(adb, state) == "blocked"
    res = cleanup(adb, state, lambda r: None, lambda: True)
    assert not res.role_ok and not res.companion_removed
    assert f"pm uninstall {PKG}" not in phone.commands and PKG in phone.installed
    assert pending_cleanup([copy], "NEW") == [restore_state_path(copy, "NEW")]


def test_uninstall_refused_while_we_hold_role(tmp_path):
    phone, _, state, adb = _setup(tmp_path, role_holders=[PKG])
    phone.installed.add(PKG)
    assert phonesetup._uninstall_companion(adb) is False
    # wywołanie z cleanup także przy `role_ok=True` (np. rola wróciła do nas po potwierdzeniu)
    phonesetup._update(state, companion=True)
    assert phonesetup._remove_companion(adb, state, True) is False
    assert f"pm uninstall {PKG}" not in phone.commands and PKG in phone.installed
    assert device_changes(state).companion
    phone.tap_role(PREV)
    assert phonesetup._remove_companion(adb, state, True) is True
    assert PKG not in phone.installed and phone.role_holders == [PREV]
