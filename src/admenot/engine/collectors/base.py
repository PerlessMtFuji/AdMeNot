from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Protocol

from admenot.engine.adb.transport import AdbError, AdbTransport
from admenot.engine.facts import AppFacts


@dataclass
class CollectorStatus:
    name: str
    ok: bool
    error: str | None = None
    seconds: float = 0.0
    partial: list[str] = field(default_factory=list)  # aplikacje bez danych mimo ok=True


class Collector(Protocol):
    name: str

    def collect(self, adb: AdbTransport, apps: list[AppFacts]) -> Any: ...

    def apply(self, facts: dict[str, AppFacts], data: Any) -> None: ...


def _timed(collector: Collector, adb: AdbTransport, apps: list[AppFacts]) -> tuple[Any, float]:
    start = time.perf_counter()
    data = collector.collect(adb, apps)
    return data, time.perf_counter() - start


def _covers(collector: Collector, facts: AppFacts) -> bool:
    covers = getattr(collector, "covers", None)
    return covers(facts) if covers is not None else True


def run_collectors(
    adb: AdbTransport,
    facts: dict[str, AppFacts],
    collectors: list[Collector],
    max_workers: int = 6,
    timeout: float = 90.0,
) -> dict[str, CollectorStatus]:
    """Uruchamia kolektory równolegle; błąd kolektora = brak danych, nie awaria skanu.

    Brak danych trafia do `AppFacts.gaps` każdej aplikacji, którą kolektor obejmuje —
    „nie udało się odczytać” nie może wyglądać jak „nic nie znaleziono”.
    Deadline to czas całkowity; wątki po terminie są opuszczane (wywołania adb mają własne limity).
    """
    apps = list(facts.values())
    statuses: dict[str, CollectorStatus] = {}
    deadline = time.monotonic() + timeout
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futures = [(c, pool.submit(_timed, c, adb, apps)) for c in collectors]
        for collector, future in futures:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                data, seconds = future.result(timeout=remaining)
                collector.apply(facts, data)
                partial = sorted(p for p, f in facts.items() if collector.name in f.gaps)
                statuses[collector.name] = CollectorStatus(collector.name, True, None, seconds,
                                                           partial)
            except AdbError as exc:
                statuses[collector.name] = CollectorStatus(collector.name, False, exc.message)
            except TimeoutError:
                statuses[collector.name] = CollectorStatus(collector.name, False, "timeout")
            except Exception as exc:  # noqa: BLE001 — nieznany format u producenta nie może zabić skanu
                statuses[collector.name] = CollectorStatus(
                    collector.name, False, f"{type(exc).__name__}: {exc}"
                )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    for collector in collectors:
        if not statuses[collector.name].ok:
            for f in apps:
                if _covers(collector, f):
                    f.gaps.add(collector.name)
    return statuses
