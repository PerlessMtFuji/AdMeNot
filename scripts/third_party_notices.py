"""Wykaz licencji składników paczki: THIRD_PARTY_NOTICES.txt (spec wydania §7).

Pakiety Pythona: domknięcie zależności `admenot` i `pywebview` w środowisku builda (bez
extras i bez pakietów, których tu nie ma, np. tylko dla macOS) plus PyInstaller (bootloader
w exe). Do tego Python, scrcpy z adb, biblioteki WebView2 SDK z pywebview i biblioteki, które
trafiają do zbudowanego UI, oraz listę urządzeń Google Play (`data/supported_devices.csv`).
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

ROOTS = ("admenot", "pywebview")
ROOT = Path(__file__).resolve().parents[1]
GPLAY_CSV = ROOT / "data" / "supported_devices.csv"
GPLAY_URL = "https://storage.googleapis.com/play_public/supported_devices.csv"
# devDependencies, które vite wkleja do zbudowanego UI (czcionka, runtime Svelte, CSS Tailwinda)
UI_BUNDLED = ("@fontsource-variable/manrope", "svelte", "tailwindcss")
LICENSE_FILE = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE)[^/]*$", re.IGNORECASE)
REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
EXTRA = re.compile(r"\bextra\s*==")
# pakiety bez licencji w metadanych, choć tekst licencji jest w dist-info (klucz: _key)
LICENSE_OVERRIDES = {"clr-loader": "MIT"}
# pywebview dołącza Microsoft.Web.WebView2.Core/WinForms.dll i WebView2Loader.dll; tekstu
# licencji nie ma obok nich, więc wklejamy standardową licencję WebView2 SDK (BSD, Microsoft)
WEBVIEW2_DLL = "webview/lib/Microsoft.Web.WebView2.Core.dll"
WEBVIEW2_LICENSE = """Copyright (C) Microsoft Corporation. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

   * Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
   * Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.
   * The name of Microsoft Corporation, or the names of its contributors
may not be used to endorse or promote products derived from this
software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE."""


@dataclass(frozen=True)
class Component:
    name: str
    version: str
    license: str | None
    texts: tuple[str, ...] = ()


def _key(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def python_closure(roots=ROOTS, dist=metadata.distribution) -> list[metadata.Distribution]:
    found: dict[str, metadata.Distribution] = {}
    todo = list(roots)
    while todo:
        name = todo.pop()
        if _key(name) in found:
            continue
        try:
            d = dist(name)
        except metadata.PackageNotFoundError:
            continue  # zależność innej platformy — nie ma jej w paczce
        found[_key(name)] = d
        for requirement in d.requires or []:
            match = REQUIREMENT.match(requirement)
            if match and not EXTRA.search(requirement):
                todo.append(match.group(1))
    return [found[k] for k in sorted(found) if k != "admenot"]


def license_of(d: metadata.Distribution) -> str | None:
    meta = d.metadata
    if meta.get("License-Expression"):
        return meta["License-Expression"]
    text = (meta.get("License") or "").strip()
    if text and "\n" not in text and len(text) < 120:  # niektóre pakiety wklejają tu cały tekst
        return text
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or []
                   if c.startswith("License ::")]
    return (", ".join(classifiers) or (text.splitlines()[0] if text else None)
            or LICENSE_OVERRIDES.get(_key(meta["Name"] or "")))


def _license_texts(d: metadata.Distribution) -> tuple[str, ...]:
    texts = []
    for f in d.files or []:
        path = str(f).replace("\\", "/")
        if ".dist-info/" in path and LICENSE_FILE.search(path):
            try:
                texts.append(f.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                pass
    return tuple(texts)


def python_components(dists) -> list[Component]:
    return [Component(d.metadata["Name"], d.version, license_of(d), _license_texts(d))
            for d in dists]


def ui_components(ui_dir: Path) -> list[Component]:
    package = json.loads((ui_dir / "package.json").read_text("utf-8"))
    components = []
    for name in sorted({*package.get("dependencies", {}), *UI_BUNDLED}):
        root = ui_dir / "node_modules" / name
        meta = json.loads((root / "package.json").read_text("utf-8"))
        texts = tuple(p.read_text("utf-8", errors="replace") for p in sorted(root.iterdir())
                      if p.is_file() and LICENSE_FILE.search(p.name))
        components.append(Component(name, meta.get("version", "?"), meta.get("license"), texts))
    return components


def _python() -> Component:
    license_file = Path(sys.base_prefix) / "LICENSE.txt"
    texts = (license_file.read_text("utf-8", errors="replace"),) if license_file.is_file() else ()
    return Component("Python", sys.version.split()[0], "PSF-2.0", texts)


def _scrcpy(tools: Path) -> Component:
    return Component("scrcpy + adb (Android platform-tools)",
                     (tools / "VERSION").read_text("utf-8").strip(), "Apache-2.0",
                     ((tools / "LICENSE.txt").read_text("utf-8", errors="replace"),))


def _gplay(csv: Path) -> Component:
    # plik nie ma własnej wersji ani daty — wersją jest skrót treści
    return Component("Google Play supported devices (supported_devices.csv)",
                     hashlib.sha256(csv.read_bytes()).hexdigest()[:12],
                     "brak jawnej licencji, lista publikowana przez Google do pobrania / "
                     "no explicit license, list published by Google for download",
                     (f"Źródło / Source: {GPLAY_URL}",))


def _file_version(path: Path) -> str:
    """Wersja pliku z zasobu VERSIONINFO (Windows); "?", gdy się nie da."""
    try:
        version = ctypes.windll.version
        size = version.GetFileVersionInfoSizeW(str(path), None)
        buffer = ctypes.create_string_buffer(size)
        info, length = ctypes.c_void_p(), ctypes.c_uint()
        if not (size and version.GetFileVersionInfoW(str(path), 0, size, buffer)
                and version.VerQueryValueW(buffer, "\\", ctypes.byref(info), ctypes.byref(length))):
            return "?"
        ms, ls = ctypes.cast(info, ctypes.POINTER(ctypes.c_uint32 * 4)).contents[2:4]  # VS_FIXEDFILEINFO
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except (AttributeError, OSError):
        return "?"


def _webview2_sdk(dll: Path) -> Component:
    return Component("Microsoft Edge WebView2 SDK (via pywebview)", _file_version(dll),
                     "BSD-3-Clause (Microsoft WebView2 SDK)", (WEBVIEW2_LICENSE,))


def render(components: list[Component]) -> str:
    parts = ["AdMeNot — składniki innych autorów / third-party components", ""]
    for c in components:
        parts += ["=" * 78, f"{c.name} {c.version}",
                  f"Licencja / License: {c.license or 'nieznana / unknown'}"]
        for text in c.texts:
            parts += ["", text.strip()]
        parts.append("")
    return "\n".join(parts) + "\n"


def missing_licenses(components: list[Component]) -> list[str]:
    return [c.name for c in components if not c.license]


def build(tools: Path, ui_dir: Path) -> tuple[str, list[str]]:
    components = [_python(), *python_components(python_closure()),
                  *python_components([metadata.distribution("pyinstaller")]),
                  _webview2_sdk(Path(metadata.distribution("pywebview").locate_file(WEBVIEW2_DLL))),
                  _scrcpy(tools), _gplay(GPLAY_CSV), *ui_components(ui_dir)]
    return render(components), missing_licenses(components)
