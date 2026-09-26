import struct

import pytest
from dexutil import make_apk, make_dex

from demalware.engine.apk.dex import DexFormatError, read_apk_types, read_dex_types


def test_read_dex_types_defined_and_referenced():
    data = make_dex(["com.app.Main", "com.applovin.sdk.AppLovinSdk"],
                    extra_types=["dalvik.system.DexClassLoader"])
    types = read_dex_types(data)
    assert types.defined == {"com.app.Main", "com.applovin.sdk.AppLovinSdk"}
    assert types.referenced == types.defined | {"dalvik.system.DexClassLoader"}  # bez "I" i "[B"


def test_read_dex_types_rejects_non_dex():
    with pytest.raises(DexFormatError):
        read_dex_types(b"PK\x03\x04" + bytes(200))


def test_read_dex_types_rejects_truncated_file():
    data = make_dex(["com.app.Main"])
    with pytest.raises(DexFormatError):
        read_dex_types(data[:0x78])


def test_read_dex_types_rejects_class_def_index_out_of_range():
    data = bytearray(make_dex(["com.app.Main"]))
    class_defs_off = struct.unpack_from("<I", data, 0x64)[0]
    struct.pack_into("<I", data, class_defs_off, 999)
    with pytest.raises(DexFormatError):
        read_dex_types(bytes(data))


def test_read_apk_types_merges_multidex_and_splits(tmp_path):
    base = make_apk(tmp_path / "base.apk", {
        "classes.dex": make_dex(["com.app.Main"]),
        "classes2.dex": make_dex(["com.mbridge.msdk.Foo"]),
    }, extra={"assets/classes.dex": b"not a dex", "res/raw/x.bin": b"\x00"})
    split = make_apk(tmp_path / "split_feature.apk", {"classes.dex": make_dex(["com.app.Feature"])})
    types, errors = read_apk_types([base, split])
    assert types.defined == {"com.app.Main", "com.mbridge.msdk.Foo", "com.app.Feature"}
    assert errors == []  # assets/classes.dex to nie jest kod aplikacji


def test_read_apk_types_keeps_going_after_broken_dex_and_bad_zip(tmp_path):
    base = make_apk(tmp_path / "base.apk", {
        "classes.dex": make_dex(["com.app.Main"]),
        "classes2.dex": b"dex\n035\x00" + bytes(10),
    })
    broken = tmp_path / "split_config.xhdpi.apk"
    broken.write_bytes(b"not a zip")
    types, errors = read_apk_types([base, broken])
    assert types.defined == {"com.app.Main"}
    assert len(errors) == 2
    assert any("classes2.dex" in e for e in errors)
    assert any("split_config.xhdpi.apk" in e for e in errors)
