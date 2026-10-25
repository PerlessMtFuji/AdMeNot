"""Bezpieczne nazwy Windows i planowanie ścieżek lokalnych kopii telefonu."""

from __future__ import annotations

from admenot.engine.transfer.winpath import PathPlanner, remote_rel, sanitize_component


def test_sanitize_invalid_chars():
    assert sanitize_component("a:b?.pdf") == "a_b_.pdf"
    assert sanitize_component('x"<>|*y') == "x_____y"


def test_sanitize_reserved_names():
    assert sanitize_component("CON.txt") == "_CON.txt"
    assert sanitize_component("nul") == "_nul"


def test_sanitize_trailing_dot_and_space():
    assert sanitize_component("x. ") == "x_"
    assert sanitize_component("..") == "_"


def test_remote_rel():
    assert remote_rel("/sdcard/DCIM/a.jpg") == "DCIM/a.jpg"
    assert remote_rel("/storage/emulated/0/DCIM/a.jpg") == "DCIM/a.jpg"


def test_case_insensitive_collision():
    pl = PathPlanner(4000)
    assert pl.local_rel("/sdcard/D/Case.txt", 6) == "D/Case.txt"
    assert pl.local_rel("/sdcard/D/case.txt", 6) == "D/case (2).txt"
    assert pl.renamed == {"/sdcard/D/case.txt": "D/case (2).txt"}


def test_taken_survives_between_planners():
    first = PathPlanner(4000)
    first.local_rel("/sdcard/IMG.jpg", 6)
    second = PathPlanner(4000, taken=first.taken)
    assert second.local_rel("/sdcard/img.jpg", 6) == "img (2).jpg"


def test_long_path_is_shortened_keeping_extension():
    pl = PathPlanner(60)
    remote = "/sdcard/" + "bardzo_dluga_nazwa/" * 5 + "plik.jpg"
    rel = pl.local_rel(remote, 6)
    assert rel.startswith("_dlugie_sciezki/")
    assert rel.endswith(".jpg")
    assert pl.renamed[remote] == rel
