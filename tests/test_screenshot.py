import pytest
from fakephone import make_cli_phone, png_bytes
from PIL import Image

from demalware.engine import paths
from demalware.engine.adb.transport import AdbError
from demalware.engine.foreground import ACTIVITIES, WINDOWS, Foreground
from demalware.engine.journal.db import Journal
from demalware.engine.screenshot import (
    capture_png,
    context_of,
    delete_shots,
    is_black,
    take_screenshot,
    write_report_copy,
)
from demalware.engine.texts import screenshot_caption


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    return tmp_path


def test_capture_requires_a_png():
    phone = make_cli_phone()
    assert capture_png(phone) == phone.screen
    phone.screen = b"error: no display\n"
    with pytest.raises(AdbError, match="PNG"):
        capture_png(phone)


def test_black_means_black_not_just_uniform():
    assert is_black(png_bytes(color=(0, 0, 0), dot=False)) is True
    assert is_black(png_bytes(color=(3, 5, 8), dot=False)) is True
    assert is_black(png_bytes(color=(0, 0, 0), dot=True)) is False
    assert is_black(png_bytes(color=(255, 255, 255), dot=False)) is False
    assert is_black(b"not an image") is False


def test_report_copy_is_a_small_jpeg(tmp_path):
    target = tmp_path / "1.jpg"
    assert write_report_copy(png_bytes(size=(1080, 2400)), target) is True
    with Image.open(target) as img:
        assert img.format == "JPEG" and max(img.size) == 1280
    assert write_report_copy(b"not an image", tmp_path / "2.jpg") is False
    assert not (tmp_path / "2.jpg").exists()


def test_context_uses_scan_names_and_keeps_unknown_overlays():
    fg = Foreground("com.clean.pro.boost", ["com.wlive.forecast"])
    names = {"com.clean.pro.boost": "Cleaner Pro"}
    assert context_of(fg, names, False) == {
        "foreground": {"package": "com.clean.pro.boost", "name": "Cleaner Pro"},
        "overlays": [{"package": "com.wlive.forecast", "name": "com.wlive.forecast"}],
        "black": False}
    assert context_of(Foreground(None, None), {}, True) == {
        "foreground": None, "overlays": None, "black": True}


def test_take_screenshot_saves_files_and_context():
    phone = make_cli_phone()
    phone.static[ACTIVITIES] = "  topResumedActivity=ActivityRecord{1 u0 com.clean.pro.boost/.Ad t1}\n"
    phone.static[WINDOWS] = ""
    with Journal(paths.journal_path()) as journal:
        shot = take_screenshot(phone, journal, "R58", {}, None)
        png, jpg = paths.screenshot_files(shot.id)
        assert png.read_bytes() == phone.screen and jpg.is_file()
        assert shot.context["foreground"]["package"] == "com.clean.pro.boost"
        assert shot.context["overlays"] == [] and shot.context["black"] is False
        delete_shots(journal, [shot.id])
        assert not png.exists() and not jpg.exists()
        assert journal.orphan_screenshots() == []


def test_foreground_errors_do_not_block_the_screenshot():
    phone = make_cli_phone()
    phone.fail[ACTIVITIES] = AdbError("timeout", "slow")
    phone.fail[WINDOWS] = AdbError("timeout", "slow")
    with Journal(paths.journal_path()) as journal:
        shot = take_screenshot(phone, journal, "R58", {}, None)
    assert shot.context["foreground"] is None and shot.context["overlays"] is None


def test_failed_capture_leaves_no_row():
    phone = make_cli_phone()
    phone.disconnected = True
    with Journal(paths.journal_path()) as journal:
        with pytest.raises(AdbError):
            take_screenshot(phone, journal, "R58", {}, None)
        assert journal.orphan_screenshots() == []


def test_caption_pl_and_en():
    context = {"foreground": {"package": "a", "name": "Cleaner Pro"},
               "overlays": [{"package": "b", "name": "Weather Live"}], "black": False}
    assert screenshot_caption(context, "pl") == (
        "Na pierwszym planie: Cleaner Pro · nakładki: Weather Live")
    assert screenshot_caption(context, "en") == (
        "In the foreground: Cleaner Pro · overlays: Weather Live")
    assert screenshot_caption({"foreground": None, "overlays": None, "black": False}, "pl") == (
        "nie udało się ustalić, co było na ekranie")


def test_black_screen_caption_does_not_blame_the_app():
    text = screenshot_caption({"foreground": None, "overlays": [], "black": True}, "pl")
    assert text == "czarny ekran — telefon uśpiony albo aplikacja chroni obraz"
    assert "uśpiony" in text and "chroniony przez aplikację" not in text
