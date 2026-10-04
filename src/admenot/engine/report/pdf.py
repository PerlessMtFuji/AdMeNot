"""HTML → PDF przez Microsoft Edge w trybie headless (spec §9.3; ten sam silnik co WebView2).

Edge dostaje własny, tymczasowy profil, żeby nie przejął zadania otwarty Edge użytkownika.
PDF powstaje obok jako *.tmp.pdf i zastępuje plik docelowy dopiero po udanym wydruku.
msedge.exe potrafi się zakończyć, zanim jego proces potomny dopisze PDF (np. Edge kończący
aktualizację — próba wydania 0.9.0), więc na kompletny plik czekamy jeszcze chwilę.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

EDGE_ENV = "ADMENOT_EDGE"
EDGE_TIMEOUT_S = 60.0
_EDGE_BASES = ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")
SETTLE_S = 15.0  # ile czekać na PDF po zakończeniu msedge.exe
POLL_S = 0.25
_replace = os.replace  # podmieniane w testach (zablokowany plik)
_sleep = time.sleep
_clock = time.monotonic


class PdfError(Exception):
    def __init__(self, key: str, detail: str = "") -> None:  # no_browser | timeout | failed | locked
        super().__init__(key)
        self.key = key
        self.detail = detail


def find_edge(env: Mapping[str, str] | None = None) -> Path | None:
    env = os.environ if env is None else env
    override = env.get(EDGE_ENV)
    if override:
        return Path(override) if Path(override).is_file() else None
    for var in _EDGE_BASES:
        base = env.get(var)
        if base:
            path = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if path.is_file():
                return path
    return None


def edge_command(edge: Path, html: Path, pdf: Path, profile: Path) -> list[str]:
    return [
        str(edge), "--headless", "--disable-gpu", "--disable-extensions", "--no-first-run",
        "--no-default-browser-check", f"--user-data-dir={profile}", "--no-pdf-header-footer",
        f"--print-to-pdf={pdf}", html.resolve().as_uri(),
    ]


def _complete(tmp: Path) -> bool:
    try:
        data = tmp.read_bytes()
    except OSError:  # jeszcze nie ma albo Edge go trzyma
        return False
    return data.startswith(b"%PDF-") and data.rstrip().endswith(b"%%EOF")


def _wait_for_pdf(tmp: Path, deadline: float) -> bool:
    while not _complete(tmp):
        if _clock() >= deadline:
            return False
        _sleep(POLL_S)
    return True


def _discard(tmp: Path) -> None:
    try:
        tmp.unlink(missing_ok=True)
    except OSError:  # Edge wciąż pisze: zostanie *.tmp.pdf, usunie go następny wydruk
        pass


def html_to_pdf(html: Path, pdf: Path, edge: Path | None = None,
                run: Callable[..., Any] = subprocess.run,
                timeout: float = EDGE_TIMEOUT_S) -> None:
    edge = edge or find_edge()
    if edge is None:
        raise PdfError("no_browser")
    pdf.parent.mkdir(parents=True, exist_ok=True)
    tmp = pdf.with_name(pdf.stem + ".tmp.pdf")
    tmp.unlink(missing_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="admenot-edge-",
                                         ignore_cleanup_errors=True) as profile:
            # stdout/stderr do DEVNULL: procesy potomne Edge nie trzymają otwartych potoków
            run(edge_command(edge, html, tmp, Path(profile)), timeout=timeout, check=False,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as exc:
        tmp.unlink(missing_ok=True)
        raise PdfError("timeout") from exc
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise PdfError("failed", str(exc)) from exc
    if not _wait_for_pdf(tmp, _clock() + SETTLE_S):
        _discard(tmp)
        raise PdfError("failed", "no PDF output")
    try:
        _replace(tmp, pdf)
    except PermissionError as exc:  # PDF otwarty w przeglądarce PDF
        _discard(tmp)
        raise PdfError("locked", str(exc)) from exc
