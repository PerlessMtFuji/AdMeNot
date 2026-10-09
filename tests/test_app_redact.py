from admenot.app.redact import adb_line, redact

HOME = r"C:\Users\Jan Kowalski"


def r(text, **kw):
    kw.setdefault("home", HOME)
    kw.setdefault("user", "jkowal")
    return redact(text, **kw)


def test_profile_path_any_case_and_slashes():
    assert r(r'File "C:\Users\Jan Kowalski\AppData\x.py"') == r'File "%USERPROFILE%\AppData\x.py"'
    assert r("c:/users/jan kowalski/AppData/x.py") == "%USERPROFILE%/AppData/x.py"


def test_account_name_outside_path_but_not_common_names():
    assert r("login jkowal failed") == "login <user> failed"
    assert r("jkowal_tmp stays") == "jkowal_tmp stays"
    assert redact("device admin", home=HOME, user="Admin") == "device admin"


def test_serial_inside_adb_error_message():
    assert r("device 'R58T00TEST' not found", serials=["R58T00TEST"]) == "device '<serial>' not found"
    assert r("short AB stays", serials=["AB"]) == "short AB stays"  # < 4 znaki: nie wycinamy


def test_imei_phone_and_email():
    assert r("imei=356938035643809") == "imei=<imei>"
    assert r("call +48 601 234 567 now") == "call <phone> now"
    assert r("sms 601-234-567") == "sms <phone>"
    assert r("mail jan@example.com") == "mail <email>"


def test_keeps_trace_numbers_and_dates():
    text = ('File "plan.py", line 118, in plan_order\n'
            "Thread 0x000012ac (most recent call first)\n"
            "--- 2026-10-09 14:03:12 took 0.12s, 1048576 B\n")
    assert r(text) == text


def test_adb_line_drops_serial_and_date():
    line = "2026-10-09T14:02:58\tR58T00TEST\tok\t0.12s\tshell:pm list packages -f\n"
    assert adb_line(line, ["R58T00TEST"], home=HOME, user="jkowal") == \
        "14:02:58\tok\t0.12s\tshell:pm list packages -f"


def test_adb_line_redacts_command_and_truncates():
    line = "2026-10-09T14:02:58\tS1\tok\t0.1s\tshell:echo 356938035643809 " + "x" * 400
    out = adb_line(line, ["S1"], home=HOME, user="jkowal")
    assert "<imei>" in out and len(out) == 300


def test_adb_line_bad_format():
    assert adb_line("garbage", []) is None
