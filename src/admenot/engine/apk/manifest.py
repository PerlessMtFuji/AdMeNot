"""Manifest, etykieta, ikona i certyfikat z base.apk przez androguard (import leniwy: skan bez --apk go nie ładuje)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from admenot.engine.apk.components import Component, parse_components

# Ikona trafia do UI jako data URI, więc tylko bitmapy rozpoznane po nagłówku, nie po rozszerzeniu.
# Pierwszeństwo ma xxhdpi (144 px wystarcza na awatar 44 px przy DPI 300%); XML-e (ikony
# adaptacyjne, wektory) pomijamy — wtedy UI zostaje przy inicjale.
ICON_MAX_BYTES = 512 * 1024
_ICON_DPIS = (480, 640, 65536)


def icon_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def icon_uri(data: bytes) -> str | None:
    mime = icon_mime(data)
    if mime is None or len(data) > ICON_MAX_BYTES:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _read_icon(apk) -> str | None:  # apk: androguard.core.apk.APK (import leniwy)
    seen: set[str] = set()
    for dpi in _ICON_DPIS:
        path = apk.get_app_icon(max_dpi=dpi)
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            uri = icon_uri(apk.get_file(path))
        except Exception:  # noqa: BLE001, S112 — brak pliku w archiwum: szukamy dalej
            continue
        if uri:
            return uri
    return None


@dataclass(frozen=True)
class ManifestInfo:
    package: str
    version_code: int | None
    label: str | None
    cert_sha256: tuple[str, ...]
    icon: str | None = None  # data URI bitmapy z launchera
    components: tuple[Component, ...] | None = None  # None = nie odczytano


def _int_attr(raw: object) -> int | None:
    return int(raw) if raw is not None and str(raw).isdigit() else None


def _long_version_code(apk) -> int | None:  # apk: androguard.core.apk.APK
    """versionCodeMajor << 32 | versionCode — ten sam „długi” kod, który pokazuje dumpsys."""
    code = _int_attr(apk.get_androidversion_code())
    if code is None:
        return None
    try:
        major = _int_attr(apk.get_attribute_value("manifest", "versionCodeMajor")) or 0
    except Exception:  # noqa: BLE001 — brak atrybutu w nietypowym manifeście: sam versionCode
        major = 0
    return (major << 32) | (code & 0xFFFFFFFF)


def _resource_xml(apk, ref: str):  # apk: androguard.core.apk.APK
    # androguard 4.1.4: ARSCParser jest w androguard.core.axml (get_res_id_by_key i
    # get_resolved_res_configs istnieją); w zdekodowanym manifeście @xml/a11y bywa liczbą @7F...
    from androguard.core.axml import AXMLPrinter

    res = apk.get_android_resources()
    if res is None:
        return None
    key = ref.lstrip("@")
    try:
        res_id = int(key, 16)
    except ValueError:
        res_type, _, name = key.partition("/")
        res_id = res.get_res_id_by_key(apk.get_package(), res_type, name)
    if res_id is None:
        return None
    for _, value in res.get_resolved_res_configs(res_id):
        if value and value.endswith(".xml"):
            return AXMLPrinter(apk.get_file(value)).get_xml_obj()
    return None


def read_manifest(base_apk: Path) -> ManifestInfo:
    from loguru import logger

    logger.disable("androguard")  # androguard loguje każdy krok na stderr
    from androguard.core.apk import APK

    apk = APK(str(base_apk))
    try:
        label = apk.get_app_name() or None
    except Exception:  # noqa: BLE001 — uszkodzone resources.arsc nie może zabić analizy; etykieta nie jest krytyczna
        label = None
    try:
        icon = _read_icon(apk)
    except Exception:  # noqa: BLE001 — jak etykieta: ikona jest tylko ozdobą
        icon = None
    version_code = _long_version_code(apk)
    certs = tuple(sorted(c.sha256.hex() for c in apk.get_certificates()))
    try:
        components = parse_components(apk.get_android_manifest_xml(), lambda ref: _resource_xml(apk, ref))
    except Exception:  # noqa: BLE001 — nietypowy manifest: mapa komponentów „nieznana”, nie pusta
        components = None
    return ManifestInfo(apk.get_package() or "", version_code, label, certs, icon, components)
