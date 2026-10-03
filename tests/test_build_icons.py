import importlib.util
from pathlib import Path

from PIL import Image
from PIL.IcoImagePlugin import IcoFile

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_icons", ROOT / "scripts" / "build_icons.py")
build_icons = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_icons)

ICON_DIR = ROOT / "src" / "admenot" / "assets" / "icon"


def test_small_sizes_use_the_simplified_drawing():
    assert build_icons.source_for(16).name == "admenot-small.svg"
    assert build_icons.source_for(24).name == "admenot-small.svg"
    assert build_icons.source_for(32).name == "admenot.svg"
    assert build_icons.source_for(256).name == "admenot.svg"


def test_ico_takes_every_size_from_its_own_png(tmp_path):
    pngs = {}
    for i, size in enumerate(build_icons.ICO_SIZES):
        path = tmp_path / f"{size}.png"
        Image.new("RGBA", (size, size), (i * 20, 0, 0, 255)).save(path)
        pngs[size] = path
    out = tmp_path / "x.ico"
    build_icons.build_ico(pngs, out)
    with out.open("rb") as f:
        ico = IcoFile(f)
        assert sorted(s for s, _ in ico.sizes()) == sorted(build_icons.ICO_SIZES)
        for i, size in enumerate(build_icons.ICO_SIZES):
            assert ico.getimage((size, size)).convert("RGBA").getpixel((0, 0)) == (i * 20, 0, 0, 255)


def test_committed_icon_has_all_sizes():
    with (ICON_DIR / "admenot.ico").open("rb") as f:
        assert sorted(s for s, _ in IcoFile(f).sizes()) == [16, 20, 24, 32, 40, 48, 64, 256]
    for size in build_icons.PNG_SIZES:
        assert Image.open(ICON_DIR / f"admenot-{size}.png").size == (size, size)


def test_sources_have_no_text_and_ui_copy_matches():
    for name in ("admenot.svg", "admenot-small.svg"):
        assert "<text" not in (ROOT / "assets" / "icon" / name).read_text("utf-8")
    master = (ROOT / "assets" / "icon" / "admenot.svg").read_bytes()
    assert (ROOT / "ui" / "src" / "assets" / "admenot.svg").read_bytes() == master
