import threading

import pytest
from apphelpers import make_api
from conftest import SERIAL
from fakephone import make_cli_phone
from updatehelpers import signed

from admenot import __version__
from admenot.app.api import Api
from admenot.app.events import RecordingEmitter
from admenot.engine.settings import load_settings, save_settings
from admenot.net import client, installer, update


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))
    monkeypatch.setenv("ADMENOT_ASSETS", str(tmp_path / "no-assets"))


def no_fetch():
    raise client.BackendError("offline")


def api_with(**kw):
    kw.setdefault("update_fetch", no_fetch)
    return make_api(make_cli_phone(), **kw)


def cache(key, **changes):
    update.store(update.verify(signed(key, **changes)))


def frozen_api(download, launch, **kw):
    api, rec = api_with(frozen=True, update_download=download, launch_setup=launch, **kw)
    closed = []
    api._attach(pick_folder=lambda: None, close=lambda: closed.append(True))
    return api, rec, closed


def test_no_manifest_no_banner():
    api, _ = api_with()
    view = api.update_state()
    assert view["available"] is None and view["retired"] is None and view["installable"] is False


def test_new_version_and_dismiss(signing_key):
    cache(signing_key)
    api, _ = api_with()
    assert api.update_state()["available"]["version"] == "9.9.9"
    assert api.dismiss_update("9.9.9")["dismissed"] is True
    assert load_settings().dismissed_update == "9.9.9"
    assert api.dismiss_update("")["error"]["key"] == "bad_request"


def test_retired_version_blocks_new_changes_only(signing_key):
    cache(signing_key, min_supported="9.0.0", min_reason={"pl": "Błąd cofania", "en": "Undo bug"})
    api, _ = api_with()
    err = api.execute({"com.clean.pro.boost": "disable"}, [])["error"]
    assert (err["key"], err["message"], err["min_supported"]) == ("retired", "Błąd cofania", "9.0.0")
    assert api.resume("2026/0001")["error"]["key"] == "retired"
    assert api.undo("2026/0001")["error"]["key"] == "unknown_order"  # cofanie nie jest blokowane
    assert "job_id" in api.start_scan(SERIAL)


def test_dev_build_opens_the_download_page(signing_key):
    cache(signing_key)
    opened = []
    api, _ = api_with(frozen=False, open_url=opened.append)
    assert api.install_update() == {"opened": True}
    assert opened == [update.download_page("pl")]


def test_install_downloads_launches_and_quits(signing_key, tmp_path):
    cache(signing_key)
    setup = tmp_path / "AdMeNot-9.9.9-setup.exe"
    launched = []

    def download(manifest, progress, cancelled):
        assert manifest.latest == "9.9.9" and cancelled() is False
        progress(5, 10)
        setup.write_bytes(b"MZ")
        return setup

    api, rec, closed = frozen_api(download, launched.append)
    assert "job_id" in api.install_update()
    assert rec.of("update:progress") == [{"done": 5, "total": 10}]
    assert launched == [setup] and closed == [True]


@pytest.mark.parametrize(("error", "key"), [
    (installer.Corrupt("9.9.9"), "update_corrupt"),
    (client.BackendError("offline"), "update_download"),
    (PermissionError("brak dostępu"), "update_download"),
])
def test_download_errors_keep_the_program_open(signing_key, error, key):
    cache(signing_key)

    def download(manifest, progress, cancelled):
        raise error

    def launch(path):
        pytest.fail("instalator uruchomiony mimo błędu pobierania")

    api, rec, closed = frozen_api(download, launch)
    api.install_update()
    (failure,) = rec.of("job:error")
    assert (failure["key"], failure["kind"]) == (key, "update") and closed == []


def test_launch_failure_points_to_the_page(signing_key, tmp_path):
    cache(signing_key)

    def launch(path):
        raise OSError("zablokowane przez antywirus")

    api, rec, closed = frozen_api(lambda m, p, c: tmp_path / "s.exe", launch)
    api.install_update()
    (failure,) = rec.of("job:error")
    assert failure["key"] == "update_launch_failed" and failure["page"] == update.download_page("pl")
    assert closed == []


def test_cancelled_download_is_quiet(signing_key):
    cache(signing_key)

    def download(manifest, progress, cancelled):
        raise client.Cancelled

    api, rec, closed = frozen_api(download, lambda p: None)
    api.install_update()
    assert rec.of("job:error") == [] and rec.of("job:end") and closed == []


def test_install_refused_while_another_job_runs(signing_key):
    cache(signing_key)
    release = threading.Event()

    def download(manifest, progress, cancelled):
        release.wait(5)
        raise client.Cancelled

    api, _, _ = frozen_api(download, lambda p: None, sync=False)
    api.install_update()
    try:
        assert api.install_update()["error"]["key"] == "busy"
    finally:
        release.set()
        assert api._jobs.wait(5)


def test_install_without_update():
    api, _, _ = frozen_api(lambda *a: None, lambda p: None)
    assert api.install_update()["error"]["key"] == "update_none"


def test_updated_message_once():
    save_settings({"last_run_version": "0.0.1"})
    api, _ = api_with()
    assert api.update_state()["updated_to"] == __version__
    again, _ = api_with()
    assert again.update_state()["updated_to"] is None


def test_first_run_is_not_an_update():
    api, _ = api_with()
    assert api.update_state()["updated_to"] is None
    assert load_settings().last_run_version == __version__


def test_settings_from_a_newer_version_do_not_block_start(tmp_path):
    path = tmp_path / "data" / "AdMeNot" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"schema": 99, "lang": "pl"}', "utf-8")
    api = Api(RecordingEmitter(), host_factory=lambda p: make_cli_phone(), apk_factory=None,
              sync_jobs=True, update_fetch=no_fetch)
    assert api.update_state()["updated_to"] is None


def test_turning_checks_on_wakes_the_checker():
    api, _ = api_with()
    woken = []
    api._updates.poke = lambda: woken.append(True)
    api.save_settings({"check_updates": False})
    assert woken == []
    api.save_settings({"check_updates": True})
    assert woken == [True]


def test_check_now_emits_the_new_state(signing_key):
    api, rec = api_with(update_fetch=lambda: update.verify(signed(signing_key)))
    api._updates.check_now()
    assert rec.of("update:state")[-1]["available"]["version"] == "9.9.9"
