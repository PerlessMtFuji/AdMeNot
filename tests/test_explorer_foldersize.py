"""Liczby folderów dla kafelków: pliki z `find`, bajty z `du -sb`, stary toybox i foldery bez dostępu."""

from __future__ import annotations

import pytest

from admenot.engine.adb.transport import AdbError
from admenot.engine.explorer.foldersize import FolderStats, folder_stats
from admenot.engine.transfer.guard import q


class Phone:
    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.commands: list[str] = []

    def shell(self, command: str, timeout: float = 20.0) -> str:
        self.commands.append(command)
        for prefix, out in self.answers.items():
            if command.startswith(prefix):
                return out
        raise AssertionError(command)


def test_counts_files_and_real_bytes():
    phone = Phone({
        "find ": "/sdcard/Music/a.mp3\n/sdcard/Music/.thumbnails/.nomedia\n/sdcard/Music/Album/b.mp3\n",
        "du -sb": "30010500\t/sdcard/Music/\n",
    })
    assert folder_stats(phone, "/sdcard/Music") == FolderStats(3, 30010500, partial=False, approx=False)
    root = q("/sdcard/Music/")
    assert phone.commands == [f"find {root} -type f 2>&1 || true", f"du -sb {root} 2>&1 || true"]


def test_denied_subfolder_marks_partial_but_keeps_numbers():
    phone = Phone({
        "find ": "/sdcard/Android/media/x.jpg\nfind: '/sdcard/Android/data/com.a': Permission denied\n",
        "du -sb": "du: /sdcard/Android/data/com.a: Permission denied\n264639009\t/sdcard/Android/\n",
    })
    assert folder_stats(phone, "/sdcard/Android/") == FolderStats(1, 264639009, partial=True, approx=False)


def test_old_toybox_without_du_b_falls_back_to_blocks():
    phone = Phone({
        "find ": "/sdcard/a/x\n",
        "du -sb": "du: Unknown option 'b'\n",
        "du -sk": "12\t/sdcard/a/\n",
    })
    assert folder_stats(phone, "/sdcard/a") == FolderStats(1, 12 * 1024, partial=False, approx=True)


def test_empty_folder():
    phone = Phone({"find ": "", "du -sb": "6976\t/sdcard/Puste/\n"})  # same wpisy podfolderów (jak na OPPO)
    assert folder_stats(phone, "/sdcard/Puste") == FolderStats(0, 0, partial=False, approx=False)
    assert folder_stats(phone, "/sdcard/Puste").view() == {"files": 0, "bytes": 0, "partial": False, "approx": False}


def test_disconnect_is_an_error():
    class Gone:
        def shell(self, command: str, timeout: float = 20.0) -> str:
            raise AdbError("offline", "device offline")

    with pytest.raises(AdbError):
        folder_stats(Gone(), "/sdcard/DCIM")
