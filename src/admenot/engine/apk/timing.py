"""Ile potrwa analiza APK (spec trybu ręcznego §4): prędkości stanowiska, ETA i nauka.

Prędkości dotyczą stanowiska (komputer + zwykle ten sam kabel), nie telefonu. Każdy przebieg
analizy mierzy pobieranie, analizę i narzut na aplikację; średnia krocząca trafia do
`apk-timing.json`. Bez historii szacunek jest „orientacyjny” (przedział).
"""

from __future__ import annotations

import json
import math
import os
import threading
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from admenot.engine.apk.cache import Estimate
from admenot.engine.paths import data_dir

MB = 1024 * 1024
TIMING_FILE = "apk-timing.json"
EMA_WEIGHT = 0.3
MIN_APPS = 5
MIN_BYTES = 50 * MB
ROUGH_LOW, ROUGH_HIGH = 0.6, 1.5  # bez historii: zapas na nieznany komputer i kabel
BLEND_FULL_AT = 10  # od tylu aplikacji bieżący przebieg w pełni zastępuje historię
# Granice wiarygodnych prędkości: poza nimi plik jest uszkodzony (NaN, Infinity, 1e308 z json.loads).
MIN_BPS, MAX_BPS = 1024, 100 * 1024 * MB
MAX_PER_APP_S = 3600.0
MAX_SAMPLES = 1_000_000


@dataclass(frozen=True)
class Speeds:
    pull_bps: float  # bajty/s pobierania na wątek, bez narzutu na aplikację
    analyze_bps: float  # bajty/s analizy na wątek
    per_app_s: float  # pm path, sumy kontrolne, zapis wyniku
    samples: int = 0  # 0 = wartości domyślne, szacunek orientacyjny


# Bez historii. Stanowisko testowe (4 przebiegi, OPPO CPH2271, USB 3): pobieranie 33 MB/s, analiza
# 75 MB/s, 1,05 s na aplikację. Domyślne to ok. połowa tych prędkości (pobieranie 16, analiza
# 32 MB/s) i 1,5 s na aplikację — zapas na wolniejszy komputer i USB 2.0, a zakres ROUGH_HIGH
# pokrywa jeszcze ok. 3× wolniejsze stanowisko. Dawne 10/8/1,5 dawały 6–16 min dla skanu 4,3 min.
# Po pierwszym przebiegu liczy się historia (`learn`).
DEFAULT_SPEEDS = Speeds(pull_bps=16 * MB, analyze_bps=32 * MB, per_app_s=1.5)


@dataclass(frozen=True)
class Eta:
    seconds: int
    kind: str  # measured | rough
    low: int
    high: int


class RunStats:
    """Pomiary jednego przebiegu; `add` woła wiele wątków naraz."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.apps = 0
        self.pulled = 0
        self.pulled_bytes = 0
        self.pull_s = 0.0
        self.hits = 0
        self.hit_s = 0.0
        self.analyzed_bytes = 0
        self.analyze_s = 0.0

    def add(self, *, size: int, fetch_s: float, from_cache: bool, analyze_s: float) -> None:
        with self._lock:
            self.apps += 1
            if from_cache:
                self.hits += 1
                self.hit_s += fetch_s
            else:
                self.pulled += 1
                self.pulled_bytes += size
                self.pull_s += fetch_s
            self.analyzed_bytes += size
            self.analyze_s += analyze_s


def measured(run: RunStats, fallback: Speeds) -> Speeds:
    """Prędkości z przebiegu; czego przebieg nie zmierzył, zostaje z `fallback`."""
    per_app = run.hit_s / run.hits if run.hits else fallback.per_app_s
    pull = fallback.pull_bps
    if run.pulled and run.pulled_bytes:
        net = run.pull_s - run.pulled * per_app
        if net > 0:
            pull = run.pulled_bytes / net
    analyze = (run.analyzed_bytes / run.analyze_s
               if run.analyze_s > 0 and run.analyzed_bytes else fallback.analyze_bps)
    return Speeds(pull, analyze, per_app, fallback.samples)


def learn(old: Speeds, run: RunStats) -> Speeds:
    if run.apps < MIN_APPS and run.analyzed_bytes < MIN_BYTES:
        return old  # za mała próbka: szum, nie pomiar
    new = measured(run, old)
    if old.samples == 0:
        return Speeds(new.pull_bps, new.analyze_bps, new.per_app_s, 1)

    def mix(a: float, b: float) -> float:
        return a * (1 - EMA_WEIGHT) + b * EMA_WEIGHT

    return Speeds(mix(old.pull_bps, new.pull_bps), mix(old.analyze_bps, new.analyze_bps),
                  mix(old.per_app_s, new.per_app_s), old.samples + 1)


def blend(history: Speeds, run: RunStats) -> Speeds:
    """Na żywo: im więcej aplikacji za nami, tym bardziej liczy się bieżący przebieg."""
    w = min(1.0, run.apps / BLEND_FULL_AT)
    now = measured(run, history)

    def mix(a: float, b: float) -> float:
        return a * (1 - w) + b * w

    return Speeds(mix(history.pull_bps, now.pull_bps), mix(history.analyze_bps, now.analyze_bps),
                  mix(history.per_app_s, now.per_app_s), history.samples)


def sane(speeds: Speeds) -> bool:
    bps = (speeds.pull_bps, speeds.analyze_bps)
    return (all(math.isfinite(b) and MIN_BPS <= b <= MAX_BPS for b in bps)
            and math.isfinite(speeds.per_app_s) and 0 <= speeds.per_app_s <= MAX_PER_APP_S
            and 0 <= speeds.samples <= MAX_SAMPLES)


def eta_for(speeds: Speeds, *, to_fetch_bytes: int, total_bytes: int, apps: int,
            workers: int) -> Eta:
    if not sane(speeds):  # uszkodzona historia albo pomiar: jak bez historii, nigdy wyjątek
        speeds = DEFAULT_SPEEDS
    lanes = max(1, min(workers, apps))
    s = (to_fetch_bytes / speeds.pull_bps + total_bytes / speeds.analyze_bps
         + apps * speeds.per_app_s) / lanes
    if not math.isfinite(s):
        s = 0.0
    if speeds.samples:
        return Eta(round(s), "measured", round(s), round(s))
    return Eta(round(s), "rough", round(s * ROUGH_LOW), round(s * ROUGH_HIGH))


def estimate_eta(est: Estimate, speeds: Speeds, workers: int,
                 packages: Iterable[str] | None = None) -> Eta:
    if packages is None:
        return eta_for(speeds, to_fetch_bytes=est.to_fetch_bytes, total_bytes=est.total_bytes,
                       apps=est.apps, workers=workers)
    chosen = list(dict.fromkeys(packages))
    sizes = {p: est.sizes.get(p, 0) for p in chosen}
    return eta_for(speeds, to_fetch_bytes=sum(s for p, s in sizes.items() if p in est.to_fetch),
                   total_bytes=sum(sizes.values()), apps=len(chosen), workers=workers)


def live_eta(history: Speeds, run: RunStats | None, est: Estimate | None,
             remaining_apps: int, workers: int) -> int | None:
    if run is None or est is None:
        return None
    if remaining_apps <= 0:
        return 0  # bajty bez znanego rozmiaru nie mają już aplikacji, której by dotyczyły
    speeds = blend(history, run)
    return eta_for(speeds, to_fetch_bytes=max(0, est.to_fetch_bytes - run.pulled_bytes),
                   total_bytes=max(0, est.total_bytes - run.analyzed_bytes),
                   apps=max(0, remaining_apps), workers=workers).seconds


def timing_path() -> Path:
    return data_dir() / TIMING_FILE


def load_speeds(path: Path | None = None) -> Speeds:
    """Uszkodzony albo nieczytelny plik = brak historii, bez błędu dla użytkownika."""
    try:
        raw = json.loads((path or timing_path()).read_text("utf-8"))
        speeds = Speeds(float(raw["pull_bps"]), float(raw["analyze_bps"]),
                        float(raw["per_app_s"]), int(raw["samples"]))
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return DEFAULT_SPEEDS
    return speeds if sane(speeds) else DEFAULT_SPEEDS


def save_speeds(speeds: Speeds, path: Path | None = None) -> None:
    target = path or timing_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(asdict(speeds)), "utf-8")
    os.replace(tmp, target)
