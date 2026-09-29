import hashlib
import importlib.util
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fetch_tools.py"


def _module():
    spec = importlib.util.spec_from_file_location("fetch_tools", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive(tmp_path, names, top="scrcpy-win64-v9.9"):
    path = tmp_path / "scrcpy.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name in names:
            z.writestr(f"{top}/{name}" if top else name, f"content of {name}")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_pinned_release_is_scrcpy_4_1():
    m = _module()
    assert m.VERSION == "4.1"
    assert m.SHA256 == "5b12172b3264b2889f4583ee64752ce832e29bc8b1089dca81093459697165db"
    assert m.URL.endswith("/v4.1/scrcpy-win64-v4.1.zip")
    assert m.TARGET == ROOT / "src" / "demalware" / "assets" / "tools" / "scrcpy"


def test_install_unpacks_and_writes_version(tmp_path):
    m = _module()
    archive, digest = _archive(tmp_path, [*m.REQUIRED, "SDL3.dll"])
    target = tmp_path / "assets" / "tools" / "scrcpy"
    assert m.install(archive, target, expected=digest, version="9.9") == target
    assert (target / "scrcpy.exe").read_text() == "content of scrcpy.exe"
    assert (target / "SDL3.dll").is_file()
    assert (target / "VERSION").read_text() == "9.9\n"


def test_install_replaces_an_older_copy(tmp_path):
    m = _module()
    archive, digest = _archive(tmp_path, m.REQUIRED)
    target = tmp_path / "tools" / "scrcpy"
    target.mkdir(parents=True)
    (target / "old.dll").write_text("old")
    m.install(archive, target, expected=digest)
    assert not (target / "old.dll").exists()


def test_wrong_checksum_leaves_nothing_behind(tmp_path):
    m = _module()
    archive, _digest = _archive(tmp_path, m.REQUIRED)
    target = tmp_path / "tools" / "scrcpy"
    with pytest.raises(m.FetchError, match="SHA-256"):
        m.install(archive, target, expected="0" * 64)
    assert not target.exists()


def test_missing_file_is_an_error(tmp_path):
    m = _module()
    archive, digest = _archive(tmp_path, [n for n in m.REQUIRED if n != "adb.exe"])
    with pytest.raises(m.FetchError, match="adb.exe"):
        m.install(archive, tmp_path / "tools" / "scrcpy", expected=digest)


@pytest.mark.parametrize("bad", ["../evil.txt", "/abs.txt"])
def test_paths_outside_the_archive_are_refused(tmp_path, bad):
    m = _module()
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(bad, "x")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(m.FetchError, match="path"):
        m.install(archive, tmp_path / "tools" / "scrcpy", expected=digest)
