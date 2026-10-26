from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

from admenot.engine.apk.analyze import ApkReport
from admenot.engine.apk.iocs import Ioc, IocList
from admenot.engine.transfer import apkcheck
from admenot.engine.transfer.apkcheck import BUNDLE_EXT, check_apks, load_or_check
from admenot.engine.transfer.store import CopyDir

PKG = "com.example.app"
CERT_A, CERT_B = "aa" * 32, "bb" * 32
HASH = "cc" * 32
NO_IOCS = IocList(1, ())


def _copy(tmp_path, verdicts=None, app_cert=None):
    copy = CopyDir(tmp_path / "copy")
    copy.apps_dir.mkdir(parents=True, exist_ok=True)
    if verdicts is not None:
        copy.verdicts_path.write_text(json.dumps(
            [{"package": p, "version_code": vc, "verdict": v} for p, (vc, v) in verdicts.items()]),
            encoding="utf-8")
    if app_cert:
        apk = copy.apps_dir / PKG / "5" / "base.apk"
        apk.parent.mkdir(parents=True)
        apk.write_bytes(b"old")
    return copy


def _file(tmp_path, name="a.apk", data=b"x"):
    path = tmp_path / name
    path.write_bytes(data)
    return (f"/sdcard/Download/{name}", path)


def _report(**kw):
    kw.setdefault("package", PKG)
    kw.setdefault("cert_sha256", [CERT_A])
    kw.setdefault("files", {"a.apk": HASH})
    return ApkReport(**kw)


def _run(copy, report, iocs=NO_IOCS, name="a.apk"):
    f = _file(copy.path.parent, name)
    return check_apks(copy, [f], iocs, lambda r, p: report)[0]


def _certs(monkeypatch, cert):
    monkeypatch.setattr(apkcheck, "read_manifest",
                        lambda p: SimpleNamespace(cert_sha256=(cert,), package=PKG))


def test_inherits_malicious_from_old_phone(tmp_path):
    copy = _copy(tmp_path, {PKG: (1, "malicious")})
    c = _run(copy, _report(cert_sha256=[]))
    assert (c.outcome, c.level, c.default_on) == ("malicious", "installed", False)


def test_inherits_suspicious_unchecked(tmp_path):
    c = _run(_copy(tmp_path, {PKG: (1, "suspicious")}), _report())
    assert (c.outcome, c.level, c.default_on) == ("suspicious", "installed", False)


def test_ioc_sha256_is_malicious(tmp_path):
    iocs = IocList(1, (Ioc("sha256", HASH, "fam", "https://x", date(2026, 1, 1)),))
    c = _run(_copy(tmp_path), _report(), iocs)
    assert (c.outcome, c.level, c.default_on) == ("malicious", "ioc", False)


def test_non_exclusive_signer_is_not_malicious(tmp_path):
    iocs = IocList(1, (Ioc("signer", CERT_A, "fam", "https://x", date(2026, 1, 1)),))
    assert _run(_copy(tmp_path), _report(), iocs).outcome != "malicious"
    excl = IocList(1, (Ioc("signer", CERT_A, "fam", "https://x", date(2026, 1, 1), True),))
    assert _run(_copy(tmp_path), _report(), excl).outcome == "malicious"


def test_same_cert_as_installed_clean_app_is_clean(tmp_path, monkeypatch):
    _certs(monkeypatch, CERT_A)
    c = _run(_copy(tmp_path, {PKG: (5, "clean")}, app_cert=True), _report())
    assert (c.outcome, c.level, c.default_on) == ("clean", "installed", True)


def test_other_cert_than_installed_clean_app_is_suspicious(tmp_path, monkeypatch):
    _certs(monkeypatch, CERT_B)
    c = _run(_copy(tmp_path, {PKG: (5, "clean")}, app_cert=True), _report())
    assert (c.outcome, c.level, c.default_on) == ("suspicious", "installed", False)


def test_unknown_app_cert_falls_through_to_static(tmp_path):
    c = _run(_copy(tmp_path, {PKG: (5, "clean")}), _report())
    assert (c.outcome, c.level) == ("clean", "static")


def test_static_red_flags_suspicious(tmp_path):
    c = _run(_copy(tmp_path), _report(ad_sdks=["x"], dynamic_code=True))
    assert (c.outcome, c.level, c.default_on) == ("suspicious", "static", False)
    c = _run(_copy(tmp_path), _report(ad_sdks=["x"], obfuscation_ratio=0.5))
    assert c.outcome == "suspicious"


def test_padded_label_suspicious(tmp_path):
    assert _run(_copy(tmp_path), _report(label_padded=True)).outcome == "suspicious"


def test_plain_apk_clean(tmp_path):
    c = _run(_copy(tmp_path), _report(ad_sdks=["x"]))
    assert (c.outcome, c.level, c.default_on) == ("clean", "static", True)


def test_never_malicious_without_confirmation(tmp_path):
    c = _run(_copy(tmp_path, {}), _report(label_padded=True, ad_sdks=["x"], dynamic_code=True,
                                          obfuscation_ratio=1.0))
    assert c.outcome != "malicious"


def test_bundle_is_unknown_and_uploaded(tmp_path):
    copy = _copy(tmp_path)

    def boom(r, p):
        raise AssertionError("bundle must not be analyzed")

    for ext in BUNDLE_EXT:
        f = _file(tmp_path, "b" + ext)
        c = check_apks(copy, [f], NO_IOCS, boom)[0]
        assert (c.outcome, c.level, c.default_on) == ("unknown", "none", True)


def test_rejected_apk_unknown(tmp_path):
    c = _run(_copy(tmp_path), _report(error="rejected: too big"))
    assert (c.outcome, c.level, c.default_on) == ("unknown", "none", True)


def test_no_package_unknown(tmp_path):
    assert _run(_copy(tmp_path), _report(package="")).outcome == "unknown"


def test_partial_error_still_uses_fields(tmp_path):
    c = _run(_copy(tmp_path), _report(error="dex: boom", label_padded=True))
    assert c.outcome == "suspicious"


def test_old_copy_without_verdicts(tmp_path):
    copy = _copy(tmp_path)
    assert copy.read_verdicts() is None
    iocs = IocList(1, (Ioc("sha256", HASH, "fam", "https://x", date(2026, 1, 1)),))
    assert _run(copy, _report(), iocs).level == "ioc"
    assert _run(copy, _report()).level == "static"


def test_default_analyze_rejects_zip_bomb_before_manifest(tmp_path, monkeypatch):
    from admenot.engine.apk.limits import ApkRejected

    def reject(p):
        raise ApkRejected("bomb")

    monkeypatch.setattr(apkcheck, "preflight", reject)
    monkeypatch.setattr(apkcheck, "read_manifest",
                        lambda p: (_ for _ in ()).throw(AssertionError("parsed")))
    report = apkcheck._analyze_file("x", [tmp_path / "a.apk"])
    assert report.error.startswith("rejected:")


def test_results_cached(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    files = [_file(tmp_path)]
    calls = []

    def fake(remote, paths):
        calls.append(remote)
        return _report()

    monkeypatch.setattr(apkcheck, "_analyze_file", fake)
    first = load_or_check(copy, files)
    second = load_or_check(copy, files)
    assert first == second and len(calls) == 1
    files[0][1].write_bytes(b"changed")
    load_or_check(copy, files)
    assert len(calls) == 2


def _sha_ioc_list(data: bytes):
    import hashlib
    return IocList(1, (Ioc("sha256", hashlib.sha256(data).hexdigest(), "fam", "https://x",
                           date(2026, 1, 1)),))


def test_unreadable_manifest_sha256_ioc_is_malicious(tmp_path):
    f = _file(tmp_path, data=b"evil")
    for rep in (_report(package=""), _report(package="", files={})):
        c = check_apks(_copy(tmp_path), [f], _sha_ioc_list(b"evil"), lambda r, p, rep=rep: rep)[0]
        assert (c.outcome, c.level, c.default_on) == ("malicious", "ioc", False)
    c = check_apks(_copy(tmp_path), [f], NO_IOCS, lambda r, p: _report(package=""))[0]
    assert (c.outcome, c.level, c.default_on) == ("unknown", "none", True)


def test_rejected_sha256_ioc_is_malicious(tmp_path):
    f = _file(tmp_path, data=b"bomb")
    rep = ApkReport("", error="rejected: bomb")
    c = check_apks(_copy(tmp_path), [f], _sha_ioc_list(b"bomb"), lambda r, p: rep)[0]
    assert (c.outcome, c.level, c.default_on) == ("malicious", "ioc", False)
    c = check_apks(_copy(tmp_path), [f], NO_IOCS, lambda r, p: rep)[0]
    assert (c.outcome, c.level, c.default_on) == ("unknown", "none", True)


def test_analyze_exception_is_unknown(tmp_path):
    def boom(r, p):
        raise RuntimeError("x")

    c = check_apks(_copy(tmp_path), [_file(tmp_path)], NO_IOCS, boom)[0]
    assert (c.outcome, c.level, c.default_on) == ("unknown", "none", True)


def test_installed_certs_skips_unreadable_old_apk(tmp_path, monkeypatch):
    copy = _copy(tmp_path)
    for vc in ("1", "2"):
        apk = copy.apps_dir / PKG / vc / "base.apk"
        apk.parent.mkdir(parents=True)
        apk.write_bytes(b"x")

    def fake(p):
        if "1" in p.parent.name:
            raise ValueError("bad")
        return SimpleNamespace(cert_sha256=(CERT_A,), package=PKG)

    monkeypatch.setattr(apkcheck, "read_manifest", fake)
    assert apkcheck._installed_certs(copy, PKG) == {CERT_A}
