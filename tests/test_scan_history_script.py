import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scan_history.py"
IMEI = "490154203237518"  # przykładowy IMEI z poprawną sumą Luhna (lista dozwolonych w repo)


def _module():
    spec = importlib.util.spec_from_file_location("scan_history", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["scan_history"] = module
    spec.loader.exec_module(module)
    return module


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "core.autocrlf", "false")
    return repo


def _commit(repo, files):
    for name, content in files.items():
        path = repo / name
        if content is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")
    return _git(repo, "rev-parse", "--short", "HEAD")


def test_luhn():
    m = _module()
    assert m.luhn_ok(IMEI)
    assert not m.luhn_ok("490154203237519")


def test_find_detects_each_rule():
    m = _module()
    text = "\n".join([
        f"imei={IMEI}",
        "[ro.serialno]: [ABC123XYZ]",
        "kontakt: jan.kowalski@poczta.test",
        "Account {name=jan.kowalski, type=com.google}",
        'SSID: "DomKowalskich"',
        "tel. +999 123 456 789",
        r"C:\Users\Testowy\AppData",
    ])
    assert sorted(rule for rule, _ in m.find(text, frozenset())) == [
        "account", "email", "imei", "phone", "serial", "user_path", "wifi"]


def test_find_sees_values_inside_json_strings():
    # nagrania mostu trzymają wyjście poleceń jako napisy JSON, więc cudzysłowy są escapowane
    m = _module()
    text = json.dumps({"out": 'ssid="DomNowakow" SSID: "SiecNowakow" {"serial": "Q7Z9TEST"}'})
    assert sorted(m.find(text, frozenset())) == [
        ("serial", "Q7Z9TEST"), ("wifi", "DomNowakow"), ("wifi", "SiecNowakow")]


def test_find_skips_fractions_and_invalid_imei():
    m = _module()
    assert m.find("ratio=0.833333333333332 x=490154203237519", frozenset()) == []


def test_find_serial_skips_placeholders():
    m = _module()
    text = "[ro.serialno]: [{SERIAL}]\n[ro.serialno]: [<redacted>]\n[ro.serialno]: […]"
    assert m.find(text, frozenset()) == []


def test_find_skips_example_domains_common_user_dirs_and_allowed_values():
    m = _module()
    text = f"anna.k@example.com x@mail.example.org C:\\Users\\Public\\ imei {IMEI}"
    assert m.find(text, frozenset({IMEI})) == []


def test_mask_keeps_last_four():
    m = _module()
    assert m.mask(IMEI) == "*" * 11 + "7518"
    assert m.mask("ab") == "ab"


def test_load_allow_reads_values_and_ignores_comments(tmp_path):
    m = _module()
    allow = tmp_path / "allow.txt"
    allow.write_text(f"# nagłówek\n\n{IMEI}  # IMEI testowy\nABC123XYZ\n", "utf-8")
    assert m.load_allow(allow) == frozenset({IMEI, "ABC123XYZ"})
    assert m.load_allow(tmp_path / "brak.txt") == frozenset()


def test_scan_sees_blobs_removed_from_the_branch(tmp_path):
    m = _module()
    repo = _repo(tmp_path)
    first = _commit(repo, {"fixtures/getprop.txt": f"[persist.imei]: [{IMEI}]\n"})
    _commit(repo, {"fixtures/getprop.txt": None, "README": "nic\n"})
    hits = m.scan(repo, frozenset())
    assert hits == [m.Hit("imei", IMEI, "fixtures/getprop.txt", first)]


def test_scan_skips_binary_blobs(tmp_path):
    m = _module()
    repo = _repo(tmp_path)
    _commit(repo, {"blob.bin": b"\0\1\2" + IMEI.encode()})
    assert m.scan(repo, frozenset()) == []


def test_main_masks_values_and_sets_exit_code(tmp_path, capsys):
    m = _module()
    repo = _repo(tmp_path)
    _commit(repo, {"a.txt": "czysto\n"})
    allow = tmp_path / "allow.txt"
    allow.write_text("", "utf-8")
    assert m.main(["--repo", str(repo), "--allow", str(allow)]) == 0
    _commit(repo, {"b.txt": f"imei {IMEI}\n"})
    assert m.main(["--repo", str(repo), "--allow", str(allow)]) == 1
    out = capsys.readouterr().out
    assert "*" * 11 + "7518" in out
    assert IMEI not in out
    assert "b.txt" in out
