"""Granice analizy niezaufanego APK (audyt 2026-10-11, PERF-01)."""

import zipfile

import pytest

from admenot.engine.apk import limits
from admenot.engine.apk.analyze import analyze_apk
from admenot.engine.apk.limits import ApkRejected, preflight


def _zip(path, entries, compression=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, "w", compression) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def test_ordinary_apk_passes(tmp_path):
    preflight(_zip(tmp_path / "base.apk", {"AndroidManifest.xml": b"x" * 100, "classes.dex": b"d"}))


def test_non_zip_is_left_to_the_parser(tmp_path):
    (tmp_path / "base.apk").write_bytes(b"PK")
    preflight(tmp_path / "base.apk")


def test_zip_bomb_entry_is_rejected_before_parsing(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "RATIO_MIN_SIZE", 1024 * 1024)
    bomb = _zip(tmp_path / "base.apk", {"res/raw/a.bin": b"\0" * (8 * 1024 * 1024)})
    with pytest.raises(ApkRejected, match="compression ratio"):
        preflight(bomb)
    parsed = []
    report = analyze_apk("com.x", [bomb], read_manifest=lambda p: parsed.append(p))
    assert report.error.startswith("rejected:") and parsed == []


def test_oversized_parsed_entry_and_too_many_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(limits, "MAX_PARSED_ENTRY", 1000)
    big = _zip(tmp_path / "a.apk", {"resources.arsc": b"r" * 2000}, zipfile.ZIP_STORED)
    with pytest.raises(ApkRejected, match="resources.arsc"):
        preflight(big)
    monkeypatch.setattr(limits, "MAX_ENTRIES", 3)
    many = _zip(tmp_path / "b.apk", {f"f{i}": b"" for i in range(4)})
    with pytest.raises(ApkRejected, match="entries"):
        preflight(many)


def test_process_memory_limit_applies_in_a_child_process():
    """Limit ustawiony w osobnym procesie: duża alokacja kończy się MemoryError, nie zawieszeniem."""
    import subprocess
    import sys

    code = ("from admenot.engine.apk.limits import limit_process_memory\n"
            "assert limit_process_memory(512 * 1024 * 1024)\n"
            "try:\n"
            "    b = bytearray(1024 * 1024 * 1024)\n"
            "except MemoryError:\n"
            "    print('limited')\n")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                         check=False)
    assert out.stdout.strip() == "limited", out.stderr
