"""Budowa minimalnych plików DEX/APK do testów (tylko tabele string_ids/type_ids/class_defs)."""

from __future__ import annotations

import struct
import zipfile
from collections.abc import Sequence
from pathlib import Path


def _descriptor(name: str) -> str:
    return "L" + name.replace(".", "/") + ";"


def make_dex(defined: Sequence[str], extra_types: Sequence[str] = ()) -> bytes:
    descriptors = sorted({_descriptor(n) for n in (*defined, *extra_types)} | {"I", "[B"})
    count = len(descriptors)
    string_ids_off = 0x70
    type_ids_off = string_ids_off + 4 * count
    class_defs_off = type_ids_off + 4 * count
    data_off = class_defs_off + 32 * len(defined)

    string_data = bytearray()
    offsets = []
    for d in descriptors:
        offsets.append(data_off + len(string_data))
        raw = d.encode()
        string_data += bytes([len(raw)]) + raw + b"\x00"  # uleb128 dla długości < 128

    index = {d: i for i, d in enumerate(descriptors)}
    body = struct.pack(f"<{count}I", *offsets) + struct.pack(f"<{count}I", *range(count))
    for name in defined:
        body += struct.pack("<I", index[_descriptor(name)]) + bytes(28)

    header = bytearray(0x70)
    header[:8] = b"dex\n035\x00"
    struct.pack_into("<4I", header, 0x38, count, string_ids_off, count, type_ids_off)
    struct.pack_into("<2I", header, 0x60, len(defined), class_defs_off)
    return bytes(header) + body + bytes(string_data)


def make_apk(path: Path, dex_files: dict[str, bytes], extra: dict[str, bytes] | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in {**dex_files, **(extra or {})}.items():
            z.writestr(name, data)
    return path
