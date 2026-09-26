import importlib.util
import io
import sys
from pathlib import Path

from phonedb import write_sources

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_phone_db.py"


def _script():
    spec = importlib.util.spec_from_file_location("build_phone_db", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_builds_assets(tmp_path, capsys):
    _, gplay = write_sources(tmp_path / "szklodo")
    out = tmp_path / "assets"
    argv = ["--source", str(tmp_path / "szklodo"), "--gplay", str(gplay), "--out", str(out)]
    assert _script().main(argv) == 0
    assert (out / "phones.db").is_file()
    assert len(list((out / "phones").glob("*.webp"))) == 9
    printed = capsys.readouterr().out
    assert "Telefony: 10 (pominięte bez nazwy: 1), ze zdjęciem: 9" in printed
    assert "Kody modeli: 13 (konflikty: 1), nazwy: 11, lista Google: 7" in printed


def test_script_reports_missing_source_and_writes_nothing(tmp_path, capsys):
    out = tmp_path / "assets"
    argv = ["--source", str(tmp_path / "nope"), "--gplay", str(tmp_path / "g.csv"),
            "--out", str(out)]
    assert _script().main(argv) == 1
    assert "Brak" in capsys.readouterr().err
    assert not out.exists()


def test_script_reports_empty_images_dir(tmp_path, capsys):
    images, gplay = write_sources(tmp_path / "szklodo")
    for webp in images.glob("*.webp"):
        webp.unlink()
    out = tmp_path / "assets"
    argv = ["--source", str(tmp_path / "szklodo"), "--gplay", str(gplay), "--out", str(out)]
    assert _script().main(argv) == 1
    assert "Brak" in capsys.readouterr().err
    assert not out.exists()


def test_script_reports_malformed_json(tmp_path, capsys):
    _, gplay = write_sources(tmp_path / "szklodo")
    data = tmp_path / "szklodo" / "data" / "phones_full_data.json"
    data.write_text("[{", encoding="utf-8")
    out = tmp_path / "assets"
    argv = ["--source", str(tmp_path / "szklodo"), "--gplay", str(gplay), "--out", str(out)]
    assert _script().main(argv) == 1
    assert "Błąd" in capsys.readouterr().err
    assert not out.exists()


def test_script_output_survives_cp1250_console(tmp_path, monkeypatch):
    _, gplay = write_sources(tmp_path / "szklodo")
    out = tmp_path / "assets"
    argv = ["--source", str(tmp_path / "szklodo"), "--gplay", str(gplay), "--out", str(out)]
    fake_stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1250")
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    assert _script().main(argv) == 0
    fake_stdout.flush()
    printed = fake_stdout.buffer.getvalue().decode("utf-8")
    assert "Zdjęcia: skopiowane 9" in printed
