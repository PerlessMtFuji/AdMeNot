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


def test_release_notes_with_and_without_virustotal(tmp_path):
    m = _module()
    setup = tmp_path / "AdMeNot-0.9.0-setup.exe"
    setup.write_bytes(b"x" * 2 * 1024 * 1024)
    notes = m.release_notes("0.9.0", setup, "ab" * 32, signed=False, vt=None)
    assert "# AdMeNot 0.9.0" in notes and "2.0 MB" in notes and "ab" * 32 in notes
    assert m.UNSIGNED in notes and "VirusTotal: nie sprawdzono" in notes
    vt = m.virustotal.VtResult("https://vt/x", 2, 70, ("Alpha", "Zeta"))
    notes = m.release_notes("0.9.0", setup, "ab" * 32, signed=True, vt=vt)
    assert "VirusTotal: 2/70 — https://vt/x" in notes and "Alpha, Zeta" in notes
    assert "Podpis: podpisany" in notes


@pytest.fixture
def staged(monkeypatch, tmp_path):
    """build() z podstawionymi procesami i katalogami w tmp."""
    m = _module()
    bundle, release, build_dir = tmp_path / "dist" / "AdMeNot", tmp_path / "dist" / "release", tmp_path / "build"
    bundle.mkdir(parents=True)
    build_dir.mkdir()
    (build_dir / "MicrosoftEdgeWebview2Setup.exe").write_bytes(b"wv2")
    iscc = tmp_path / "ISCC.exe"
    iscc.write_bytes(b"")
    monkeypatch.setattr(m, "BUNDLE", bundle)
    monkeypatch.setattr(m, "RELEASE", release)
    monkeypatch.setattr(m, "BUILD", build_dir)
    monkeypatch.setattr(m, "WEBVIEW2_SETUP", build_dir / "MicrosoftEdgeWebview2Setup.exe")
    monkeypatch.setattr(m, "check_release_deps", lambda: None)
    monkeypatch.setattr(m.third_party_notices, "build", lambda tools, ui: ("NOTICES", ["oddpkg"]))
    monkeypatch.setattr(m.release_env, "check", list)
    monkeypatch.setattr(m.release_env, "inventory", lambda: "pkg==1.0  RECORD-sha256=ab\n")

    def no_network(url, dest):
        raise AssertionError(f"test nie pobiera z sieci: {url}")

    monkeypatch.setattr(m, "download", no_network)
    monkeypatch.delenv("ADMENOT_SIGN_CMD", raising=False)
    monkeypatch.delenv("VT_API_KEY", raising=False)
    calls = []

    def runner(command, **kw):
        calls.append(command)
        if isinstance(command, list) and command[0] == str(iscc):
            name = next(a[2:] for a in command if a.startswith("/F"))
            release.mkdir(parents=True, exist_ok=True)
            (release / f"{name}.exe").write_bytes(b"setup")
        stdout = "skan referencyjny\n" if "scan" in command else ""
        if isinstance(command, list) and "Get-AuthenticodeSignature" in " ".join(command):
            stdout = "Valid|CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond\n"
        return subprocess.CompletedProcess(command, 0, stdout, "")

    args = m.parse_args(["--allow-dirty", "--iscc", str(iscc)])
    return m, args, runner, calls, tmp_path


def _step(calls, needle):
    return next(i for i, c in enumerate(calls) if needle in " ".join(map(str, c if isinstance(c, list) else [c])))


def test_build_runs_the_steps_in_order_and_writes_the_outputs(staged):
    m, args, runner, calls, _ = staged
    summary = m.build(args, runner)
    order = [_step(calls, s) for s in ("git status", "fetch_tools.py", "build_phone_db.py",
                                       "build_ui.ps1", "PyInstaller", "selfcheck", "ISCC.exe")]
    assert order == sorted(order)
    assert not any("--device" in c for c in calls if isinstance(c, list))
    iscc = calls[_step(calls, "ISCC.exe")]
    # podstawiony git zwraca puste stdout, więc drzewo jest czyste mimo --allow-dirty
    v = admenot.__version__
    assert f"/DAppVersion={v}" in iscc and f"/DWinVersion={v}.0" in iscc
    assert f"/FAdMeNot-{v}-setup" in iscc
    assert not any(a.startswith("/S") for a in iscc)
    assert (m.BUNDLE / "THIRD_PARTY_NOTICES.txt").read_text("utf-8") == "NOTICES"
    assert (m.BUNDLE / "LICENSE.txt").read_bytes() == (ROOT / "LICENSE").read_bytes()
    setup = next(m.RELEASE.glob("*-setup.exe"))
    assert setup.with_name(setup.name + ".sha256").is_file()
    notes = next(m.RELEASE.glob("*-release-notes.md")).read_text("utf-8")
    assert "VirusTotal: nie sprawdzono" in notes
    assert summary[-1] == m.UNSIGNED
    assert any("oddpkg" in line for line in summary) and any("VT_API_KEY" in line for line in summary)


def test_build_signs_both_exes_and_the_setup_when_a_command_is_set(staged, monkeypatch):
    m, args, runner, calls, _ = staged
    monkeypatch.setenv("ADMENOT_SIGN_CMD", "signtool sign /a {file}")
    summary = m.build(args, runner)
    signed = [c for c in calls if isinstance(c, str) and c.startswith("signtool")]
    assert signed == [f'signtool sign /a "{m.BUNDLE / "AdMeNot.exe"}"',
                      f'signtool sign /a "{m.BUNDLE / "admenot-cli.exe"}"']
    iscc = calls[_step(calls, "ISCC.exe")]
    assert "/DSign" in iscc and "/Sadmenot=signtool sign /a $f" in iscc
    assert summary[-1] == "Podpisane"


def test_device_build_makes_a_reference_and_checks_the_bundle_against_it(staged):
    m, _, runner, calls, _ = staged
    args = m.parse_args(["--allow-dirty", "--device", "--iscc", str(staged[4] / "ISCC.exe")])
    m.build(args, runner)
    reference = m.BUILD / "scan-reference.txt"
    assert reference.read_text("utf-8") == "skan referencyjny\n"
    device = calls[_step(calls, "--reference")]
    assert device[-3:] == ["--device", "--reference", str(reference)]
    assert _step(calls, "scan --apk --all") < _step(calls, "PyInstaller") < _step(calls, "--reference")


def test_dirty_tree_without_the_flag_stops_before_any_build_step(staged):
    m, _, _, _, tmp_path = staged
    calls = []
    args = m.parse_args(["--iscc", str(tmp_path / "ISCC.exe")])
    with pytest.raises(m.BuildError, match="--allow-dirty"):
        m.build(args, fake_runner(calls, " M x\n"))
    assert calls == [["git", "status", "--porcelain"]]


# --- audyt 2026-10-11, REL-01, REL-02, REL-03 -----------------------------------------------------

def test_gates_run_before_any_build_step_and_land_in_the_notes(staged):
    m, args, runner, calls, _ = staged
    m.build(args, runner)
    gates = [_step(calls, s) for s in ("pytest", "ruff", "scan_history.py")]
    assert max(gates) < _step(calls, "fetch_tools.py")
    assert sum(1 for c in calls if isinstance(c, list) and c[:2] == ["npm.cmd", "run"]) == 4
    notes = next(m.RELEASE.glob("*-release-notes.md")).read_text("utf-8")
    assert "Bramki jakości: środowisko = requirements-release.lock; testy Python" in notes
    assert "WebView2 bootstrapper: SHA-256" in notes and "O=Microsoft Corporation" in notes
    assert next(m.RELEASE.glob("*-components.txt")).read_text("utf-8").startswith("pkg==1.0")


def test_a_failing_gate_stops_the_release(staged):
    m, args, runner, calls, _ = staged

    def failing(command, **kw):
        if isinstance(command, list) and "pytest" in command:
            calls.append(command)
            return subprocess.CompletedProcess(command, 1, "1 failed", "")
        return runner(command, **kw)

    with pytest.raises(m.BuildError, match="testy Python"):
        m.build(args, failing)
    assert not any("fetch_tools.py" in " ".join(map(str, c)) for c in calls if isinstance(c, list))


def test_environment_different_from_the_lock_stops_the_release(staged, monkeypatch):
    m, args, runner, _, _ = staged
    monkeypatch.setattr(m.release_env, "check", lambda: ["androguard: 4.2.0 zamiast 4.1.4"])
    with pytest.raises(m.BuildError, match="androguard"):
        m.build(args, runner)


def test_skip_gates_only_for_dirty_builds(staged):
    m, _, runner, calls, tmp_path = staged
    with pytest.raises(SystemExit):
        m.parse_args(["--skip-gates"])
    args = m.parse_args(["--allow-dirty", "--skip-gates", "--iscc", str(tmp_path / "ISCC.exe")])
    m.build(args, runner)
    assert not any("pytest" in c for c in calls if isinstance(c, list))
    notes = next(m.RELEASE.glob("*-release-notes.md")).read_text("utf-8")
    assert "POMINIĘTE" in notes


def test_webview2_with_a_foreign_signature_is_refused(staged):
    m, args, runner, _, _ = staged

    def forged(command, **kw):
        if isinstance(command, list) and "Get-AuthenticodeSignature" in " ".join(command):
            return subprocess.CompletedProcess(command, 0, "Valid|CN=Someone Else, O=Evil Ltd\n", "")
        return runner(command, **kw)

    with pytest.raises(AssertionError, match="nie pobiera z sieci"):
        m.build(args, forged)  # zła kopia z cache usunięta, próba pobrania od nowa
    assert not m.WEBVIEW2_SETUP.exists()


def test_release_env_reports_every_difference():
    spec = importlib.util.spec_from_file_location("release_env", ROOT / "scripts" / "release_env.py")
    env = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(env)
    lock = {"a": "1.0", "b": "2.0"}
    assert env.check(lock, {"a": "1.0", "b": "2.0"}) == []
    assert env.check(lock, {"a": "1.1", "c": "3"}) == ["brak b==2.0", "a: 1.1 zamiast 1.0",
                                                       "spoza listy: c==3"]
    assert env.read_lock()  # zamrożona lista w repo jest poprawna


def test_release_lock_pins_hashes(tmp_path):
    """Format z --generate-hashes: kontynuacje --hash=… nie są przypięciami, a każde przypięcie
    w repo ma skrót (pip install --require-hashes)."""
    spec = importlib.util.spec_from_file_location("release_env", ROOT / "scripts" / "release_env.py")
    env = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(env)
    lock = tmp_path / "lock"
    lock.write_text("# x\nAlpha_Pkg==1.0 \\\n    --hash=sha256:aa \\\n    --hash=sha256:bb\n"
                    "beta==2.0 \\\n    --hash=sha256:cc\n", "utf-8")
    assert env.read_lock(lock) == {"alpha-pkg": "1.0", "beta": "2.0"}
    lines = [s.strip() for s in env.LOCK.read_text("utf-8").splitlines()]
    pins = [i for i, s in enumerate(lines) if "==" in s and not s.startswith("#")]
    assert pins and all(lines[i].endswith("\\") and lines[i + 1].startswith("--hash=sha256:")
                        for i in pins)


def test_unresolved_licenses_block_a_release_until_decided(staged, monkeypatch):
    m, _, runner, _, tmp_path = staged
    monkeypatch.setattr(m.third_party_notices, "build", lambda tools, ui: ("N", ["Google list"]))
    decisions = tmp_path / "decisions.txt"
    monkeypatch.setattr(m, "LICENSE_DECISIONS", decisions)
    clean = m.parse_args(["--iscc", str(tmp_path / "ISCC.exe")])
    monkeypatch.setattr(m, "check_clean", lambda allow, runner=None: False)
    with pytest.raises(m.BuildError, match="Google list"):
        m.build(clean, runner)
    decisions.write_text("# komentarz\nGoogle list | opinia prawna 2026-10\n", "utf-8")
    summary = m.build(clean, runner)
    assert any("Google list — opinia prawna 2026-10" in line for line in summary)


def test_build_without_the_private_phone_source_uses_the_built_database(staged, monkeypatch):
    m, args, runner, calls, tmp_path = staged
    monkeypatch.setattr(m, "PHONE_SOURCE", tmp_path / "no-such-dir")
    db = tmp_path / "phones.db"
    db.write_bytes(b"db")
    monkeypatch.setattr(m, "PHONE_DB", db)
    summary = m.build(args, runner)
    assert not any("build_phone_db.py" in " ".join(map(str, c)) for c in calls if isinstance(c, list))
    assert any("użyta istniejąca phones.db" in line for line in summary)
