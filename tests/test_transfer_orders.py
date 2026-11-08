"""Zlecenie ZS dla kopii danych: założenie po kopii, cel przy wgrywaniu."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from admenot.engine.device.info import DeviceInfo
from admenot.engine.journal.db import Journal
from admenot.engine.transfer import orders, store

NOW = datetime(2026, 11, 8, 12, 0, 0)


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "data"))


def _device(serial: str = "SRC", imei: str | None = "356938035643809") -> DeviceInfo:
    return DeviceInfo(
        serial=serial, brand="samsung", manufacturer="samsung", model="SM-A145R", device="a14",
        market_name="Galaxy A14", android_release="14", sdk=34, security_patch=None, uptime_s=1.0,
        local_now=NOW, imei=imei)


def _copy() -> store.CopyDir:
    copy = store.create_copy("SRC", _device(), "Anna K.", NOW)
    meta = copy.read_meta()
    meta.counts = {"contacts": 412, "files": 9}
    meta.bytes = 12345
    meta.selection = {"contacts": True, "sms": False, "mms": False, "calls": False,
                      "categories": ["media"], "others": ["SekretnyFolder", ""], "apps": ["com.a"]}
    copy.write_meta(meta)
    return copy


@pytest.fixture
def journal(tmp_path):
    with Journal(tmp_path / "j.db", now=lambda: NOW) as j:
        yield j


def test_open_for_copy_creates_once(journal):
    copy = _copy()
    first = orders.open_for_copy(journal, copy, NOW)
    second = orders.open_for_copy(journal, copy, NOW)
    assert first.number == second.number and first.kind == "transfer"
    assert copy.read_meta().order == first.number
    assert first.client_name == "Anna K."
    record = journal.transfer(first.id)
    assert record.copy_id == copy.read_meta().id and record.copy_expires == copy.read_meta().expires
    assert record.received_at == copy.read_meta().created


def test_open_for_copy_replaces_unknown_number(journal):
    copy = _copy()
    meta = copy.read_meta()
    meta.order = "ZS/2020/0101/01"
    copy.write_meta(meta)
    order = orders.open_for_copy(journal, copy, NOW)
    assert order.number != "ZS/2020/0101/01" and copy.read_meta().order == order.number


def test_order_for_target_sets_target_on_first_phone(journal):
    copy = _copy()
    opened = orders.open_for_copy(journal, copy, NOW)
    order = orders.order_for_target(journal, copy, _device("A", "111"), NOW)
    assert order.number == opened.number
    record = journal.transfer(order.id)
    assert record.target_serial == "A"
    assert record.target == {"manufacturer": "samsung", "model": "SM-A145R", "android": "14",
                             "imei": "111", "market_name": "Galaxy A14"}


def test_order_for_target_without_order_opens_one(journal):
    copy = _copy()
    order = orders.order_for_target(journal, copy, _device("A"), NOW)
    assert copy.read_meta().order == order.number
    assert journal.transfer(order.id).target_serial == "A"


def test_same_copy_second_phone_gets_new_order(journal):
    copy = _copy()
    orders.open_for_copy(journal, copy, NOW)
    a = orders.order_for_target(journal, copy, _device("A", "111"), NOW)
    b = orders.order_for_target(journal, copy, _device("B", "222"), NOW)
    assert a.number != b.number
    assert journal.transfer(a.id).target_serial == "A"
    assert journal.transfer(a.id).target["imei"] == "111"
    rec_b = journal.transfer(b.id)
    assert rec_b.target_serial == "B" and rec_b.copy_id == journal.transfer(a.id).copy_id
    assert rec_b.source == journal.transfer(a.id).source
    assert copy.read_meta().order == a.number


def test_same_phone_again_reuses_order(journal):
    copy = _copy()
    first = orders.order_for_target(journal, copy, _device("A"), NOW)
    again = orders.order_for_target(journal, copy, _device("A"), NOW)
    assert first.number == again.number
    assert len(journal.transfers_for_copy(copy.read_meta().id)) == 1


def test_source_snapshot_has_no_paths(tmp_path):
    snapshot = orders.source_snapshot(_copy().read_meta())
    text = json.dumps(snapshot)
    assert "/sdcard" not in text and "SekretnyFolder" not in text
    assert snapshot["counts"] == {"contacts": 412, "files": 9} and snapshot["bytes"] == 12345
    assert snapshot["imei"] == "356938035643809" and snapshot["serial"] == "SRC"
    assert snapshot["selection_groups"] == ["contacts_messages", "files", "apps"]
    assert (snapshot["manufacturer"], snapshot["model"], snapshot["android"]) == ("samsung", "SM-A145R", "14")
