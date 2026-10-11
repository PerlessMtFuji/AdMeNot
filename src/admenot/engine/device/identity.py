"""Tożsamość telefonu w zleceniu (przegląd 2026-10-11): numer seryjny ADB nie wystarcza — tanie
telefony mają często ten sam numer (np. 0123456789ABCDEF), więc zlecenie zapisuje też android_id,
IMEI i model, a wznowienie i cofnięcie sprawdzają, czy to wciąż ten telefon."""

from __future__ import annotations

from typing import Any

from admenot.engine.device.info import DeviceInfo


def identity_of(device: DeviceInfo) -> dict[str, str]:
    """Znane identyfikatory telefonu do zapisu w zleceniu (puste pomijamy)."""
    found = {"android_id": device.android_id, "imei": device.imei, "model": device.model or None}
    return {key: value for key, value in found.items() if value}


def same_device(stored: dict[str, Any] | None, device: DeviceInfo) -> bool | None:
    """True: ten sam telefon; False: na pewno inny (albo po przywróceniu ustawień fabrycznych);
    None: nie wiadomo — zlecenie sprzed zapisu tożsamości albo telefon bez identyfikatorów."""
    if not stored:
        return None
    current = identity_of(device)
    for key in ("android_id", "imei"):  # android_id pierwszy: zmienia się po resecie, IMEI nie
        if stored.get(key) and current.get(key):
            return bool(stored[key] == current[key])
    if stored.get("model") and current.get("model") and stored["model"] != current["model"]:
        return False
    return None


def device_key(device: DeviceInfo) -> str:
    """Klucz katalogu kopii APK telefonu: numer seryjny, przy znanym android_id także on."""
    return f"{device.serial}#{device.android_id}" if device.android_id else device.serial
