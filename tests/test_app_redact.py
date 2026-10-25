import pytest

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


def test_other_profile_and_short_name_paths():
    assert r(r"C:\Users\JANKOW~1\AppData\Local\Temp\x") == r"%USERPROFILE%\AppData\Local\Temp\x"
    assert r('d:/users/Ola/Desktop/a.apk "x"') == '%USERPROFILE%/Desktop/a.apk "x"'
    assert r(r'File "C:\Users\Jan Kowalski\x.py"') == r'File "%USERPROFILE%\x.py"'


# --- audyt 2026-10-11, PRIV-02 -------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Phone (123) 456-7890", "tel. 123.456.7890", "+48 (22) 600-00-00"])
def test_phone_numbers_with_brackets_and_dots(text):
    assert "<phone>" in redact(text, home="", user="")


def test_version_numbers_are_not_phones():
    assert redact("Windows 10.0.26100.4652", home="", user="") == "Windows 10.0.26100.4652"


def test_android_account_names_and_known_client_names():
    out = redact("Account {name=anna.kowalska, type=example}; client Anna Kowalska, kowalska",
                 home="", user="", names=["Anna  Kowalska"])
    assert "anna" not in out.lower() and "kowalska" not in out.lower()
    assert "Account {name=<account>, type=example}" in out


def test_other_profile_with_a_space_is_removed_whole():
    out = redact("C:/Users/Anna Kowalska/Documents/test.txt", home=r"C:\Users\Operator", user="")
    assert out == "%USERPROFILE%/Documents/test.txt"


def test_unc_paths():
    assert redact(r"open \\fileserver\klienci\Kowalski\a.txt", home="", user="") == (
        r"open <unc>\Kowalski\a.txt")


def test_client_paths_on_phone_are_collapsed():
    assert r("find -H '/sdcard/Music' '/sdcard/WhatsApp Business' -type f") == \
        "find -H '/sdcard/<path>' '/sdcard/<path>' -type f"
    assert r("stat: /storage/emulated/0/Download/faktura.pdf: No such file") == \
        "stat: /storage/emulated/0/<path> No such file"
    assert r("ls -1 /sdcard") == "ls -1 /sdcard"  # sam korzeń to nie dane klienta
    assert r("pull:host:pull -a -Z /sdcard/DCIM/Moje zdj.jpg /sdcard/b.jpg D:/kopia/files") == \
        "pull:host:pull -a -Z <paths>"


def test_client_paths_in_copy_folder_are_collapsed():
    raw = (r"[WinError 32] used: 'C:\Users\Jan Kowalski\AppData\Local\AdMeNot\transfers"
           r"\R58-ab\20261025-120000\files\DCIM\Moje zdj.jpg'")
    out = r(raw)
    assert "DCIM" not in out and "Moje" not in out and "R58-ab" not in out
    assert out.endswith(r"\AdMeNot\transfers/<path>'")
    assert r(r"D:\data\admenot\transfers\R58-ab\x\files\a.jpg failed") == \
        r"D:\data\admenot\transfers/<path> failed"


def test_adb_line_collapses_client_paths():
    line = "2026-10-25T12:00:00\tR58T00TEST\tok\t0.1s\tfind -H '/sdcard/Music' -type f\n"
    assert adb_line(line, ["R58T00TEST"], home=HOME, user="x") == \
        "12:00:00\tok\t0.1s\tfind -H '/sdcard/<path>' -type f"
