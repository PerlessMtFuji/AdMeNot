import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

import admenot

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_release.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_release"] = module
    spec.loader.exec_module(module)
    return module


def fake_runner(calls, stdout="", returncode=0):
    def runner(command, **kw):
        calls.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout, "")
    return runner


def test_version_comes_from_the_package():
    m = _module()
    assert m.read_version() == admenot.__version__
    assert m.windows_version("0.9.0") == "0.9.0.0"


def test_read_version_rejects_a_file_without_a_version(tmp_path):
    m = _module()
    init = tmp_path / "__init__.py"
    init.write_text('__version__ = "dev"\n', "utf-8")
    with pytest.raises(m.BuildError):
        m.read_version(init)


def test_setup_name_marks_dirty_builds():
    m = _module()
    assert m.setup_name("0.9.0", dirty=False) == "AdMeNot-0.9.0-setup"
    assert m.setup_name("0.9.0", dirty=True) == "AdMeNot-0.9.0-dirty-setup"


def test_dirty_tree_needs_the_flag():
    m = _module()
    calls = []
    with pytest.raises(m.BuildError, match="--allow-dirty"):
        m.check_clean(False, fake_runner(calls, " M src/x.py\n"))
    assert calls == [["git", "status", "--porcelain"]]
    assert m.check_clean(True, fake_runner([], " M src/x.py\n")) is True
    assert m.check_clean(False, fake_runner([], "")) is False


def test_a_failed_step_names_the_step_and_shows_the_tail():
    m = _module()
    output = "\n".join(f"line {i}" for i in range(100))
    with pytest.raises(m.BuildError) as error:
        m.run("PyInstaller", ["pyinstaller", "x.spec"], fake_runner([], output, returncode=1))
    text = str(error.value)
    assert error.value.step == "PyInstaller" and "pyinstaller x.spec" in text
    assert "line 99" in text and "line 50" not in text


def test_stop_processes_escapes_quotes(tmp_path):
    m = _module()
    calls = []
    directory = tmp_path / "O'Brien" / "AdMeNot"
    m.stop_processes_in(directory, fake_runner(calls))
    script = calls[0][-1]
    assert calls[0][:3] == ["powershell", "-NoProfile", "-Command"]
    assert f"-like '{str(directory.resolve()).replace(chr(39), chr(39) * 2)}\\*'" in script
    assert "Stop-Process -Force" in script


def test_find_iscc_explains_what_is_missing(tmp_path):
    m = _module()
    with pytest.raises(m.BuildError, match="Inno Setup"):
        m.find_iscc(tmp_path / "ISCC.exe")


def test_sha256_file_next_to_the_setup(tmp_path):
    m = _module()
    setup = tmp_path / "AdMeNot-0.9.0-setup.exe"
    setup.write_bytes(b"setup")
    digest = m.write_sha256(setup)
    assert digest == hashlib.sha256(b"setup").hexdigest()
    sha_file = tmp_path / "AdMeNot-0.9.0-setup.exe.sha256"
    assert sha_file.read_text("utf-8") == f"{digest} *AdMeNot-0.9.0-setup.exe\n"
