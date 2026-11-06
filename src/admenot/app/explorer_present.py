"""Widoki eksploratora plików dla UI (JSON): miejsca, okruszki ścieżki, wpisy folderu."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from admenot.engine.explorer.listing import Entry, folder_label
from admenot.engine.explorer.media import MediaServer
from admenot.engine.explorer.places import Place

__all__ = ["ROOT", "crumbs", "entry_view", "file_type", "place_view"]

ROOT = "/sdcard"
_TYPES: dict[str, frozenset[str]] = {
    "image": frozenset({"jpg", "jpeg", "jpe", "png", "webp", "gif", "bmp", "heic", "heif"}),
    "video": frozenset({"mp4", "m4v", "mkv", "webm", "3gp", "mov", "avi", "ts"}),
    "audio": frozenset({"mp3", "m4a", "aac", "ogg", "oga", "opus", "wav", "flac", "amr", "awb", "mid", "midi"}),
    "text": frozenset({"txt", "log", "json", "xml", "csv", "md", "ini", "cfg", "conf", "vcf", "srt", "html",
                       "htm", "yml", "yaml"}),
    "apk": frozenset({"apk", "apks", "xapk"}),
    "doc": frozenset({"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "rtf", "epub"}),
}
_THUMBS = frozenset({"jpg", "jpeg", "jpe", "png", "webp", "gif", "bmp"})  # miniatury z serwera (thumbs.py)
_STREAMED = frozenset({"image", "video", "audio"})  # podgląd przez adres pliku na serwerze mediów


def file_type(name: str) -> tuple[str, str]:
    """(typ, rozszerzenie małymi literami bez kropki); typ: image|video|audio|text|apk|doc|other."""
    ext = PurePosixPath(name).suffix[1:].lower()
    kind = next((k for k, exts in _TYPES.items() if ext in exts), "other")
    return kind, ext


def place_view(place: Place) -> dict[str, Any]:
    return {"key": place.key, "path": place.path, "count": place.count, "icon": place.icon}


def entry_view(entry: Entry, media: MediaServer) -> dict[str, Any]:
    if entry.kind == "dir":
        kind, ext, thumb, url = "other", "", None, None
    else:
        kind, ext = file_type(entry.name)
        thumb = media.thumb_url(entry.path) if ext in _THUMBS else None
        url = media.file_url(entry.path) if kind in _STREAMED or ext == "pdf" else None
    return {"name": entry.name, "path": entry.path, "kind": entry.kind, "size": entry.size,
            "mtime": entry.mtime, "label": entry.label, "locked": entry.locked, "type": kind, "ext": ext,
            "thumb": thumb, "url": url}


def crumbs(path: str, root_label: str, apps: Mapping[str, str]) -> list[dict[str, str]]:
    """Okruszki od pamięci telefonu (`root_label` — nazwa telefonu) do `path`; foldery aplikacji
    (`Android/media|data/<pakiet>`) z ludzką nazwą."""
    out = [{"label": root_label, "path": ROOT}]
    rel = path.rstrip("/")[len(ROOT):].strip("/")
    current = ROOT
    for part in rel.split("/") if rel else []:
        current = f"{current}/{part}"
        out.append({"label": folder_label(current, apps) or part, "path": current})
    return out
