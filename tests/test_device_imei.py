import pytest

from admenot.engine.adb.transport import AdbError
from admenot.engine.device.imei import luhn_ok, parse_parcel_string, read_imei

# OPPO CPH2271, Android 12: `service call iphonesubinfo 1 s16 com.android.shell` (2026-10-04;
# cyfry zmienione na numer testowy z poprawną sumą kontrolną)
PARCEL = """Result: Parcel(
  0x00000000: 00000000 0000000f 00390034 00300039 '........4.9.9.0.'
  0x00000010: 00310030 00300032 00300030 00300030 '0.1.2.0.0.0.0.0.'
  0x00000020: 00300030 00000034                   '0.0.4...        ')
"""
DENIED = "Result: Parcel(ffffffec 00000000 '........')\n"
EMPTY = "Result: Parcel(00000000 ffffffff   '........')\n"


class Shell:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def shell(self, command, timeout=20.0):
        self.calls.append(command)
        reply = self.replies.get(command)
        if reply is None or isinstance(reply, Exception):
            raise reply or AdbError("command_failed", command)
        return reply


def call(code):
    return f"service call iphonesubinfo {code} s16 com.android.shell"


def test_parses_the_utf16_string_from_a_parcel():
    assert parse_parcel_string(PARCEL) == "499001200000004"
    assert parse_parcel_string(EMPTY) is None
    assert parse_parcel_string(DENIED) is None


def test_luhn():
    assert luhn_ok("499001200000004") and not luhn_ok("499001200000005")
    assert not luhn_ok("12345") and not luhn_ok("")


def test_reads_the_first_valid_imei():
    adb = Shell({call(1): EMPTY, call(2): PARCEL})
    assert read_imei(adb) == "499001200000004"
    assert adb.calls == [call(1), call(2)]


@pytest.mark.parametrize("reply", [DENIED, AdbError("command_failed", "x"),
                                   PARCEL.replace("00000034 ", "00000035 ")])
def test_no_imei_when_denied_failing_or_not_a_valid_number(reply):
    # Inny kod transakcji w innej wersji Androida może zwrócić inny ciąg — bez sumy Luhna nie ufamy mu.
    assert read_imei(Shell({c: reply for c in map(call, range(1, 5))})) is None
