import hashlib
import subprocess
from datetime import date

import pytest
from httpstub import Stub, serve

from admenot.net import installer, update

BODY = b"MZ" + b"\0" * 50_000


def manifest(url, **changes):
    fields = {"latest": "9.9.9", "published": date(2026, 10, 20), "min_supported": "0.9.0",
              "url": url, "sha256": hashlib.sha256(BODY).hexdigest(), "size": len(BODY),
              "notes": {"pl": "p", "en": "e"}, "min_reason": None, "raw": b""}
    fields.update(changes)
    return update.Manifest(**fields)


@pytest.fixture
def server():
    stub = Stub(body=BODY, content_type="application/octet-stream")
    stop = serve(stub)
    yield stub
    stop()


def test_download_verifies_and_renames(server, tmp_path):
    path = installer.download(manifest(server.url + "/s.exe"), directory=tmp_path)
    assert path == tmp_path / "AdMeNot-9.9.9-setup.exe" and path.read_bytes() == BODY
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("changes", [{"size": len(BODY) + 1}, {"sha256": "0" * 64}])
def test_mismatch_is_corrupt_and_leaves_nothing(server, tmp_path, changes):
    with pytest.raises(installer.Corrupt):
        installer.download(manifest(server.url + "/s.exe", **changes), directory=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_unwritable_directory_is_an_os_error(server, tmp_path):
    blocker = tmp_path / "plik"
    blocker.write_text("x")
    with pytest.raises(OSError):
        installer.download(manifest(server.url + "/s.exe"), directory=blocker / "updates")


def test_launch_runs_the_setup_detached(tmp_path):
    seen = {}

    def popen(args, **kw):
        seen.update(args=args, **kw)

    setup = tmp_path / "AdMeNot-9.9.9-setup.exe"
    installer.launch(setup, popen=popen)
    assert seen["args"] == [str(setup), "/SILENT", "/NORESTART", "/UPDATE=1"]
    assert seen["close_fds"] is True
    assert seen["creationflags"] == (getattr(subprocess, "DETACHED_PROCESS", 0)
                                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def test_cleanup_keeps_only_newer_installers(tmp_path):
    for name in ("AdMeNot-0.9.1-setup.exe", "AdMeNot-0.9.2-setup.exe", "AdMeNot-0.9.3-setup.exe",
                 "AdMeNot-0.9.3-setup.exe.part", "notatki.txt"):
        (tmp_path / name).write_bytes(b"x")
    installer.cleanup("0.9.2", tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["AdMeNot-0.9.3-setup.exe", "notatki.txt"]


def test_cleanup_without_directory_is_quiet(tmp_path):
    installer.cleanup("0.9.2", tmp_path / "brak")
