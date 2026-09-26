import pytest

from demalware.engine.adb.fake import FakeAdb
from demalware.engine.adb.transport import AdbError
from demalware.engine.apk.fetch import PM_PATH, fetch_apks, parse_pm_path

BASE = "/data/app/~~Rg8wIz5Z==/com.clean.x-a1B2==/base.apk"
SPLIT = "/data/app/~~Rg8wIz5Z==/com.clean.x-a1B2==/split_config.arm64_v8a.apk"


def _adb(pm_path=f"package:{BASE}\npackage:{SPLIT}\n", files=None):
    return FakeAdb({PM_PATH.format(package="com.clean.x"): pm_path},
                   files=files if files is not None else {BASE: b"base-bytes", SPLIT: b"split"})


def test_parse_pm_path():
    assert parse_pm_path(f"package:{BASE}\r\npackage:{SPLIT}\n\n") == [BASE, SPLIT]


def test_fetch_pulls_all_splits_into_versioned_dir(tmp_path):
    adb = _adb()
    paths = fetch_apks(adb, "com.clean.x", 42, tmp_path)
    assert [p.name for p in paths] == ["base.apk", "split_config.arm64_v8a.apk"]
    assert paths[0].parent == tmp_path / "com.clean.x" / "42"
    assert paths[0].read_bytes() == b"base-bytes"


def test_fetch_reuses_cache_for_same_version(tmp_path):
    fetch_apks(_adb(), "com.clean.x", 42, tmp_path)
    adb = _adb()
    fetch_apks(adb, "com.clean.x", 42, tmp_path)
    assert adb.calls == []  # ani pm path, ani pull


def test_fetch_new_version_pulls_again(tmp_path):
    fetch_apks(_adb(), "com.clean.x", 42, tmp_path)
    adb = _adb(files={BASE: b"v43", SPLIT: b"s"})
    paths = fetch_apks(adb, "com.clean.x", 43, tmp_path)
    assert paths[0].read_bytes() == b"v43"
    assert any(c.startswith("host:pull") for c in adb.calls)


def test_fetch_unknown_version_is_never_cached(tmp_path):
    fetch_apks(_adb(), "com.clean.x", None, tmp_path)
    adb = _adb()
    fetch_apks(adb, "com.clean.x", None, tmp_path)
    assert any(c.startswith("host:pull") for c in adb.calls)


def test_fetch_uninstalled_app_raises(tmp_path):
    with pytest.raises(AdbError):
        fetch_apks(_adb(pm_path=""), "com.clean.x", 42, tmp_path)


def test_failed_pull_leaves_no_complete_cache_and_retries(tmp_path):
    with pytest.raises(AdbError):
        fetch_apks(_adb(files={BASE: b"base"}), "com.clean.x", 42, tmp_path)  # brak splitu
    assert not (tmp_path / "com.clean.x" / "42").exists()
    adb = _adb()
    assert len(fetch_apks(adb, "com.clean.x", 42, tmp_path)) == 2
    assert any(c.startswith("host:pull") for c in adb.calls)


def test_fetch_rejects_empty_file(tmp_path):
    with pytest.raises(AdbError):
        fetch_apks(_adb(files={BASE: b"", SPLIT: b"s"}), "com.clean.x", 42, tmp_path)


def test_fetch_rejects_suspicious_remote_name(tmp_path):
    adb = _adb(pm_path="package:/data/app/x/../../evil.sh\n", files={"/data/app/x/../../evil.sh": b"x"})
    with pytest.raises(AdbError):
        fetch_apks(adb, "com.clean.x", 42, tmp_path)


def test_fetch_rejects_invalid_package_name(tmp_path):
    with pytest.raises(ValueError):
        fetch_apks(_adb(), "../com.clean.x", 42, tmp_path)
