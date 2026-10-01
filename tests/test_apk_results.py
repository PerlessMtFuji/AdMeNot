from demalware.engine.apk.analyze import ApkReport
from demalware.engine.apk.results import ResultStore, result_key


def test_key_depends_on_all_files_and_analyzer_version():
    a = result_key({"base.apk": "1" * 64, "split.apk": "2" * 64}, "deep-1")
    assert a == result_key({"split.apk": "2" * 64, "base.apk": "1" * 64}, "deep-1")
    assert a != result_key({"base.apk": "1" * 64}, "deep-1")
    assert a != result_key({"base.apk": "1" * 64, "split.apk": "2" * 64}, "deep-2")


def test_store_round_trip_and_miss(tmp_path):
    store = ResultStore(tmp_path)
    key = result_key({"base.apk": "1" * 64}, "deep-1")
    assert store.get(key) is None
    store.put(key, ApkReport("com.x", class_count=5, deep=True))
    assert store.get(key).deep is True


def test_corrupt_entry_is_a_miss(tmp_path):
    store = ResultStore(tmp_path)
    key = result_key({"base.apk": "1" * 64}, "deep-1")
    (tmp_path / f"{key}.json").write_text("{not json", "utf-8")
    assert store.get(key) is None


def test_deep_origin_separates_framework_libraries():
    from demalware.engine.apk.deep import _origin_of

    origin = _origin_of("com.x")
    assert origin("androidx.work.impl.utils.PackageManagerHelper") == "library"
    assert origin("com.google.android.gms.dynamite.DynamiteModule") == "library"
    assert origin("com.x.Main") == "app" and origin("a.b.c") == "unknown"


def test_deep_version_follows_the_sdk_list():
    from demalware.engine.apk.deep import deep_version

    assert deep_version(b"a").startswith("deep-2+") and deep_version(b"a") != deep_version(b"b")
