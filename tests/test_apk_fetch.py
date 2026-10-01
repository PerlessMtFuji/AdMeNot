import errno
import hashlib
import json
import os
import threading

import pytest

from demalware.engine.adb.fake import FakeAdb
from demalware.engine.adb.transport import AdbError
from demalware.engine.apk.cache import NoSpace
from demalware.engine.apk.fetch import PM_PATH, fetch_apks, parse_pm_path, sha256_command

BASE = "/data/app/~~Rg8wIz5Z==/com.clean.x-a1B2==/base.apk"
SPLIT = "/data/app/~~Rg8wIz5Z==/com.clean.x-a1B2==/split_config.arm64_v8a.apk"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _adb(files=None, remotes=(BASE, SPLIT), sha=True, serial="PHONE-A"):
    files = files if files is not None else {BASE: b"base-bytes", SPLIT: b"split"}
    responses = {PM_PATH.format(package="com.clean.x"): "".join(f"package:{r}\n" for r in remotes)}
    if sha is True:
        responses[sha256_command(list(remotes))] = "".join(
            f"{_sha(files[r])}  {r}\n" for r in remotes if r in files)
    elif sha is not None:
        responses[sha256_command(list(remotes))] = sha
    return FakeAdb(responses, serial=serial, files=files)


def _pulls(adb):
    return [c for c in adb.calls if c.startswith("host:pull")]


def test_parse_pm_path():
    assert parse_pm_path(f"package:{BASE}\r\npackage:{SPLIT}\n\n") == [BASE, SPLIT]


def test_sha256_command_quotes_paths():
    assert sha256_command(["/a b/base.apk"]) == "sha256sum '/a b/base.apk'"


def test_fetch_pulls_all_splits_and_records_hashes(tmp_path):
    fetched = fetch_apks(_adb(), "com.clean.x", tmp_path)
    assert fetched.verified
    assert [p.name for p in fetched.paths] == ["base.apk", "split_config.arm64_v8a.apk"]
    assert fetched.paths[0].read_bytes() == b"base-bytes"
    manifest = json.loads((fetched.paths[0].parent / "files.json").read_text("utf-8"))
    assert manifest == {"base.apk": _sha(b"base-bytes"), "split_config.arm64_v8a.apk": _sha(b"split")}


def test_same_installed_bytes_reuse_cache_but_always_ask_the_phone(tmp_path):
    fetch_apks(_adb(), "com.clean.x", tmp_path)
    adb = _adb()
    fetched = fetch_apks(adb, "com.clean.x", tmp_path)
    assert _pulls(adb) == []
    assert adb.calls[:2] == [PM_PATH.format(package="com.clean.x"), sha256_command([BASE, SPLIT])]
    assert fetched.verified


def test_other_phone_with_same_version_gets_its_own_bytes(tmp_path):
    """Reprodukcja z audytu: ten sam pakiet i versionCode, różne pliki na dwóch telefonach."""
    fetch_apks(_adb(serial="PHONE-A"), "com.clean.x", tmp_path)
    other = {BASE: b"repacked-base", SPLIT: b"split"}
    adb = _adb(files=other, serial="PHONE-B")
    fetched = fetch_apks(adb, "com.clean.x", tmp_path)
    assert fetched.paths[0].read_bytes() == b"repacked-base"
    assert _pulls(adb)


def test_hash_mismatch_after_pull_is_an_error_and_leaves_no_cache(tmp_path):
    adb = _adb(sha=f"{'0' * 64}  {BASE}\n{_sha(b'split')}  {SPLIT}\n")
    with pytest.raises(AdbError, match="sha256"):
        fetch_apks(adb, "com.clean.x", tmp_path)
    assert [p.name for p in (tmp_path / "com.clean.x").iterdir()] == []


def test_without_sha256sum_files_are_unverified_and_never_reused(tmp_path):
    first = fetch_apks(_adb(sha=AdbError("command_failed", "sha256sum: not found")),
                       "com.clean.x", tmp_path)
    assert first.verified is False
    adb = _adb(sha=AdbError("command_failed", "sha256sum: not found"))
    fetch_apks(adb, "com.clean.x", tmp_path)
    assert _pulls(adb)  # bez skrótu z telefonu nie ma czego porównać — zawsze pobieramy


def test_partial_sha256_output_is_unverified(tmp_path):
    adb = _adb(sha=f"{_sha(b'base-bytes')}  {BASE}\n")  # brak linii dla splitu
    assert fetch_apks(adb, "com.clean.x", tmp_path).verified is False


def test_fetch_uninstalled_app_raises(tmp_path):
    with pytest.raises(AdbError):
        fetch_apks(_adb(remotes=()), "com.clean.x", tmp_path)


def test_failed_pull_leaves_no_cache_and_retries(tmp_path):
    with pytest.raises(AdbError):
        fetch_apks(_adb(files={BASE: b"base"}), "com.clean.x", tmp_path)  # brak splitu na telefonie
    assert list((tmp_path / "com.clean.x").iterdir()) == []
    assert len(fetch_apks(_adb(), "com.clean.x", tmp_path).paths) == 2


def test_concurrent_fetches_of_one_package_do_not_collide(tmp_path):
    results, errors = [], []

    def run():
        try:
            results.append(fetch_apks(_adb(), "com.clean.x", tmp_path))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert {tuple(p.read_bytes() for p in r.paths) for r in results} == {(b"base-bytes", b"split")}


_NO_SHA = AdbError("command_failed", "sha256sum: not found")


def test_unverified_fetch_of_other_phone_does_not_overwrite_earlier_paths(tmp_path):
    """Przegląd końcowy I1: telefon A i B bez `sha256sum`, ten sam pakiet."""
    a = fetch_apks(_adb(sha=_NO_SHA, serial="PHONE-A"), "com.clean.x", tmp_path)
    b = fetch_apks(_adb(files={BASE: b"phone-b-base", SPLIT: b"phone-b-split"}, sha=_NO_SHA,
                        serial="PHONE-B"), "com.clean.x", tmp_path)
    assert [p.read_bytes() for p in a.paths] == [b"base-bytes", b"split"]
    assert [p.read_bytes() for p in b.paths] == [b"phone-b-base", b"phone-b-split"]
    assert a.paths[0].parent != b.paths[0].parent


def test_old_unverified_dirs_are_swept_but_fresh_ones_kept(tmp_path):
    import os
    import time

    old = fetch_apks(_adb(sha=_NO_SHA), "com.clean.x", tmp_path).paths[0].parent
    fresh = fetch_apks(_adb(sha=_NO_SHA), "com.clean.x", tmp_path).paths[0].parent
    stale = time.time() - 2 * 3600
    os.utime(old, (stale, stale))
    fetch_apks(_adb(sha=_NO_SHA), "com.clean.x", tmp_path)
    assert not old.exists()
    assert fresh.exists()


def test_backup_without_sha256sum_copies_this_phones_files(tmp_path):
    from demalware.engine.actions.backup import backup_apks

    cache = tmp_path / "cache"
    fetch_apks(_adb(files={BASE: b"phone-b-base", SPLIT: b"phone-b-split"}, sha=_NO_SHA,
                    serial="PHONE-B"), "com.clean.x", cache)
    target = tmp_path / "backups" / "com.clean.x" / "unknown"
    saved = backup_apks(_adb(sha=_NO_SHA, serial="PHONE-A"), "com.clean.x", None, target, cache)
    assert [p.read_bytes() for p in saved] == [b"base-bytes", b"split"]


def test_cache_hit_refreshes_last_use(tmp_path):
    first = fetch_apks(_adb(), "com.clean.x", tmp_path)
    entry = first.paths[0].parent
    os.utime(entry, (1_000_000, 1_000_000))
    fetch_apks(_adb(), "com.clean.x", tmp_path)
    assert entry.stat().st_mtime > 1_000_000


@pytest.mark.parametrize("message", [
    "adb: error: cannot create 'x': No space left on device",
    "failed to copy: There is not enough space on the disk.",
])
def test_pull_without_space_is_no_space_and_leaves_nothing(tmp_path, message):
    adb = _adb()
    real_run = adb.run

    def run(args, timeout=20.0):
        if args[0] == "pull":
            raise AdbError("command_failed", message)
        return real_run(args, timeout)

    adb.run = run
    with pytest.raises(NoSpace):
        fetch_apks(adb, "com.clean.x", tmp_path)
    assert list((tmp_path / "com.clean.x").iterdir()) == []


def test_disk_full_while_writing_is_no_space(tmp_path):
    adb = _adb()

    def run(args, timeout=20.0):
        raise OSError(errno.ENOSPC, "No space left on device")

    adb.run = run
    with pytest.raises(NoSpace):
        fetch_apks(adb, "com.clean.x", tmp_path)
