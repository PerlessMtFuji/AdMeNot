"""Zwijanie ścieżek plików klienta: `/sdcard/DCIM/a.jpg` → `/sdcard/<path>`.

Wspólne dla raportów błędów (`app.redact`) i logu sesji na dysku (`adb.sessionlog`): nazwy plików
i folderów klienta (pamięć telefonu, katalog kopii danych na komputerze) nie trafiają do logów ani
raportów (spec przenoszenia danych §2). Separatory `[\\/]+` obejmują też podwojone ukośniki
wsteczne z `str(OSError)` (`'C:\\\\Users\\\\…'`).

Najpierw ścieżki w cudzysłowie (nazwy ze spacjami i apostrofami, `q()` w poleceniach,
`str(OSError)`): cudzysłów zamykający musi stać przed separatorem albo końcem linii, więc apostrof
w nazwie („Jan's”) nie urywa dopasowania. Potem bez cudzysłowu — do końca linii albo do znanego
ogranicznika (`: `, tabulator, ` -opcja`, ` -> `, ` does not exist`), nie do pierwszej spacji.
"""

from __future__ import annotations

import re

_SEP = r"[\\/]+"
_ROOT = (r"(?:/sdcard|/storage/(?:emulated/\d+|self/primary|[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4})"
         rf"|{_SEP}AdMeNot{_SEP}transfers)")
_QUOTED = re.compile(
    rf"(['\"])([^'\"\r\n]*?{_ROOT}){_SEP}[^\r\n]*?\1(?=[\s:,;)\]]|$)",
    re.IGNORECASE | re.MULTILINE)
_BARE_END = (r"(?=['\"](?=[\s:,;)\]]|$)"
             r"|['\"]?(?::\s|\s+(?:-[A-Za-z]|->\s|does\snot\sexist)|[\t\r\n]|$))")
_BARE = re.compile(rf"({_ROOT}){_SEP}(?!<path>)[^\t\r\n]*?{_BARE_END}",
                   re.IGNORECASE | re.MULTILINE)
_PULL = re.compile(r"(host:pull -a -Z) (?!<\d+ files>).*")  # starsze wpisy z listą plików


def client_paths(text: str) -> str:
    """`/sdcard/DCIM/a.jpg` → `/sdcard/<path>`; tak samo `/storage/…` i katalog kopii."""
    text = _PULL.sub(r"\1 <paths>", text)
    text = _QUOTED.sub(r"\1\2/<path>\1", text)
    return _BARE.sub(r"\1/<path>", text)
