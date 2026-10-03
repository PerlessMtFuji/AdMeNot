import struct
import zipfile

import pytest
from dexutil import make_apk, make_dex

from admenot.engine.apk import dex as dexmod
from admenot.engine.apk.dex import DexFormatError, read_apk_types, read_dex_types


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


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_read_apk_types_skips_corrupt_entry_and_keeps_later_dex(tmp_path, compression):
    path = tmp_path / "base.apk"
    with zipfile.ZipFile(path, "w", compression=compression) as z:
        z.writestr("classes.dex", make_dex(["com.a.A"]))
        z.writestr("classes2.dex", make_dex([f"com.mid.C{i}" for i in range(50)]))
        z.writestr("classes3.dex", make_dex(["com.c.C"]))
    info = zipfile.ZipFile(path).getinfo("classes2.dex")
    raw = bytearray(path.read_bytes())
    data_start = info.header_offset + 30 + len(info.filename)
    raw[data_start + 40] ^= 0xFF  # uszkodzony wpis: zły CRC (stored) albo zepsuty strumień deflate
    raw[data_start + 41] ^= 0xFF
    path.write_bytes(bytes(raw))
    types, errors = read_apk_types([path])
    assert {"com.a.A", "com.c.C"} <= types.defined
    assert len(errors) == 1 and "classes2.dex" in errors[0]


def test_oversized_dex_entry_is_an_error_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(dexmod, "MAX_DEX_BYTES", 1024)
    apk = tmp_path / "base.apk"
    with zipfile.ZipFile(apk, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("classes.dex", b"\0" * 4096)  # dobrze się kompresuje: „bomba” w miniaturze
    types, errors = read_apk_types([apk])
    assert types.defined == set()
    assert errors and "too large" in errors[0]


def test_too_many_dex_entries_are_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(dexmod, "MAX_DEX_ENTRIES", 2)
    apk = tmp_path / "base.apk"
    with zipfile.ZipFile(apk, "w") as z:
        for i in ("", "2", "3"):
            z.writestr(f"classes{i}.dex", b"not dex")
    _, errors = read_apk_types([apk])
    assert any("too many DEX entries" in e for e in errors)
