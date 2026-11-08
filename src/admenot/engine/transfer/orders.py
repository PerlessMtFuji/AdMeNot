"""Zlecenie ZS dla kopii danych: jedno na kopię i telefon docelowy.

Zlecenie powstaje po zakończonej kopii (`open_for_copy`) i trafia do `meta.json` kopii (numer ZS).
Przy wgrywaniu `order_for_target` ustawia w nim telefon docelowy; ta sama kopia wgrywana na drugi,
inny telefon dostaje własne zlecenie (z tym samym źródłem), więc każdy telefon ma swój protokół.
Migawka źródła nie zawiera nazw folderów ani plików — zlecenia żyją dłużej niż kopia.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from admenot.engine.device.info import DeviceInfo
from admenot.engine.journal.db import Journal, Order

from .store import CopyDir, CopyMeta


def _groups(selection: dict[str, Any]) -> list[str]:
    groups: list[str] = []
    if any(selection.get(k) for k in ("contacts", "sms", "mms", "calls")):
        groups.append("contacts_messages")
    if selection.get("categories") or selection.get("others"):
        groups.append("files")
    if selection.get("apps"):
        groups.append("apps")
    return groups


def source_snapshot(meta: CopyMeta) -> dict[str, Any]:
    """Telefon źródłowy i rozmiar kopii: producent, model, Android, IMEI, liczby, bajty i grupy wyboru."""
    return {"manufacturer": meta.manufacturer, "model": meta.model, "android": meta.android,
            "imei": meta.imei, "serial": meta.serial, "counts": dict(meta.counts), "bytes": meta.bytes,
            "selection_groups": _groups(meta.selection)}


def _copy_id(copy: CopyDir) -> str:
    return f"{copy.path.parent.name}/{copy.path.name}"


def open_for_copy(journal: Journal, copy: CopyDir, now: datetime) -> Order:
    """Zlecenie tej kopii: istniejące (numer w `meta.order` znany dziennikowi) albo nowe."""
    meta = copy.read_meta()
    if meta.order:
        found = journal.order_by_number(meta.order)
        if found is not None:
            return found
    identity = {k: v for k, v in (("imei", meta.imei), ("model", meta.model or None)) if v}
    order = journal.create_transfer_order(
        meta.serial, meta.model, meta.client, identity or None, copy_id=_copy_id(copy),
        source=source_snapshot(meta), received_at=meta.created, copy_expires=meta.expires)
    meta.order = order.number
    copy.write_meta(meta)
    return order


def _target(device: DeviceInfo) -> dict[str, Any]:
    return {"manufacturer": device.manufacturer, "model": device.model, "android": device.android_release,
            "imei": device.imei, "market_name": device.market_name}


def order_for_target(journal: Journal, copy: CopyDir, device: DeviceInfo, now: datetime) -> Order:
    """Zlecenie kopii dla tego telefonu docelowego: ten sam telefon → to samo zlecenie; zlecenie bez
    celu dostaje ten telefon; wszystkie zlecenia kopii mają inny cel → nowe zlecenie."""
    first = open_for_copy(journal, copy, now)
    existing = journal.transfers_for_copy(_copy_id(copy))
    for order in existing:
        if journal.transfer(order.id).target_serial == device.serial:
            return order
    for order in existing:
        if journal.transfer(order.id).target_serial is None:
            journal.set_transfer_target(order.id, device.serial, _target(device))
            return journal.order(order.id)
    record = journal.transfer(first.id)
    new = journal.create_transfer_order(
        first.device_serial, first.device_model, first.client_name, first.device_identity,
        copy_id=record.copy_id, source=record.source, received_at=record.received_at,
        copy_expires=record.copy_expires or copy.read_meta().expires)
    journal.set_transfer_target(new.id, device.serial, _target(device))
    return journal.order(new.id)

