"""Granice analizy niezaufanego APK (audyt 2026-10-11, PERF-01).

Proces analizy ma limit czasu (`isolated.py`), ale parser zasobów może zająć pamięć szybciej,
niż minie limit. Dlatego: przed parsowaniem sprawdzamy katalog ZIP (tylko nagłówki, bez
rozpakowania), a proces potomny dostaje limit pamięci (Windows: Job Object, gdzie indziej
RLIMIT_AS). Przekroczenie kończy analizę jednej aplikacji błędem, nie całe stanowisko.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

MAX_ENTRIES = 50_000
MAX_PARSED_ENTRY = 256 * 1024 * 1024  # manifest, resources.arsc, classes*.dex — czytane w całości
MAX_RATIO = 1000  # stopień kompresji typowy dla bomb ZIP…
RATIO_MIN_SIZE = 16 * 1024 * 1024  # …liczony dla wpisów, które po rozpakowaniu są duże
PROCESS_MEMORY = 2 * 1024 * 1024 * 1024
_PARSED = re.compile(r"^(AndroidManifest\.xml|resources\.arsc|classes\d*\.dex)$")


class ApkRejected(ValueError):
    """Archiwum przekracza granice bezpiecznej analizy."""


def preflight(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
    except (OSError, zipfile.BadZipFile):
        return  # to nie ZIP: nie ma czego rozpakować, parser sam zgłosi uszkodzony plik
    if len(entries) > MAX_ENTRIES:
        raise ApkRejected(f"{path.name}: {len(entries)} entries")
    for entry in entries:
        if _PARSED.match(entry.filename) and entry.file_size > MAX_PARSED_ENTRY:
            raise ApkRejected(f"{path.name}: {entry.filename} is {entry.file_size} bytes")
        if (entry.file_size > RATIO_MIN_SIZE
                and entry.file_size > MAX_RATIO * max(entry.compress_size, 1)):
            raise ApkRejected(f"{path.name}: {entry.filename} compression ratio too high")


def limit_process_memory(limit: int = PROCESS_MEMORY) -> bool:
    """Limit pamięci bieżącego procesu (wołane w procesie analizy). False = nie udało się."""
    try:
        if sys.platform == "win32":
            return _job_object_limit(limit)
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        return True
    except Exception:  # noqa: BLE001 — limit to dodatkowa ochrona; bez niego zostaje limit czasu
        return False


def _job_object_limit(limit: int) -> bool:
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Io(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    limit_process_memory_flag = 0x100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    extended_limit_information = 9  # JobObjectExtendedLimitInformation
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = limit_process_memory_flag
    info.ProcessMemoryLimit = limit
    if not kernel32.SetInformationJobObject(wintypes.HANDLE(job), extended_limit_information,
                                            ctypes.byref(info), ctypes.sizeof(info)):
        return False
    return bool(kernel32.AssignProcessToJobObject(wintypes.HANDLE(job),
                                                  wintypes.HANDLE(kernel32.GetCurrentProcess())))
