"""Skąd biorą się raporty APK: z telefonu (pobranie + analiza) albo z nagrania (JSON)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from admenot.engine.adb.transport import AdbError, AdbTransport
from admenot.engine.apk.analyze import ApkReport, report_from_json
from admenot.engine.apk.cache import (
    NO_SPACE,
    CacheUsage,
    Estimate,
    NoSpace,
    clear_cache,
    estimate,
    fits,
    has_room,
    prune,
    usage,
)
from admenot.engine.apk.deep import DEEP_TIMEOUT_S, current_deep_version, deep_analyze
from admenot.engine.apk.fetch import PULL_TIMEOUT, FetchedApks, default_cache_dir, fetch_apks
from admenot.engine.apk.isolated import IsolatedAnalyzer
from admenot.engine.apk.results import ResultStore, result_key
from admenot.engine.facts import AppFacts
from admenot.engine.scoring import AppResult

ProgressFn = Callable[[int, int, str], None]


class ApkProvider(Protocol):
    def reports_for(
        self, apps: list[AppFacts], progress: ProgressFn | None = None,
        flagged: frozenset[str] = frozenset(),
    ) -> dict[str, ApkReport]: ...


SYSTEM_APK_MIN_WEIGHT = 10


def select_apk_targets(results: list[AppResult]) -> list[AppFacts]:
    """Aplikacje użytkownika, oznaczone aplikacje systemowe i niezaufane systemowe z istotnym
    sygnałem (preinstalowane adware bywa „bezpieczne” tylko przez limit dla systemowych)."""
    return [
        r.facts for r in results
        if not r.facts.is_system
        or r.verdict != "safe"
        or (not r.trusted and any(f.weight >= SYSTEM_APK_MIN_WEIGHT for f in r.findings))
    ]


class StoredApkProvider:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def reports_for(
        self, apps: list[AppFacts], progress: ProgressFn | None = None,
        flagged: frozenset[str] = frozenset(),
    ) -> dict[str, ApkReport]:
        reports: dict[str, ApkReport] = {}
        for facts in apps:
            path = self.directory / f"{facts.package}.json"
            if path.exists():
                reports[facts.package] = report_from_json(json.loads(path.read_text("utf-8")))
        return reports


@dataclass(frozen=True)
class CachePolicy:
    """Limit pamięci podręcznej i dwie decyzje, które GUI i CLI podejmują inaczej (spec §3.5)."""

    limit_bytes: int
    on_estimate: Callable[[Estimate, CacheUsage], None] = lambda est, use: None
    decide: Callable[[Estimate, CacheUsage], str] = lambda est, use: "skip"  # clear | skip | run


class _CacheRun:
    """Stan pamięci podręcznej jednej analizy: kto skończył, kto w toku, czy zabrakło miejsca."""

    def __init__(self, cache_dir: Path, limit_bytes: int, sizes: dict[str, int],
                 scan: frozenset[str], flagged: frozenset[str],
                 to_fetch: frozenset[str] | None = None) -> None:
        self.cache_dir, self.limit = cache_dir, limit_bytes
        self.sizes, self.scan, self.flagged = sizes, scan, flagged
        self.to_fetch = to_fetch  # None: nie wiadomo, co już jest w pamięci podręcznej
        self.done: set[str] = set()
        self.busy: set[str] = set()
        self.full = False
        self.off = False  # `disk_usage` zawiodło: bez kontroli, jak dawniej (spec §6)
        self.lock = threading.Lock()

    def _need(self, package: str) -> int:
        """Bajty do pobrania: 0, gdy pliki aplikacji są już w pamięci podręcznej (trafienie)."""
        if self.to_fetch is not None and package not in self.to_fetch:
            return 0
        return self.sizes.get(package, 0)

    def before_fetch(self, package: str) -> None:
        with self.lock:
            if self.full:
                raise NoSpace(package)
            # Najpierw `busy`: przycinanie nie usunie wpisu tej aplikacji, który zaraz będzie czytany.
            self.busy.add(package)
            if self.off:
                return
            need = self._need(package)
            try:
                if not has_room(self.cache_dir, need):
                    self._prune(need)
                    if not self.off and not has_room(self.cache_dir, need):
                        self.full = True
                        self.busy.discard(package)  # `after()` nie zostanie wywołane
                        raise NoSpace(package)
            except OSError:
                self.off = True

    def after(self, package: str, no_space: bool = False) -> None:
        with self.lock:
            self.busy.discard(package)
            if no_space:
                self.full = True
            else:
                self.done.add(package)
            self._prune()

    def _prune(self, need: int = 0) -> None:
        if self.off:
            return
        try:
            prune(self.cache_dir, self.limit, scan=self.scan, done=frozenset(self.done),
                  flagged=self.flagged, busy=frozenset(self.busy), need_bytes=need)
        except OSError:
            self.off = True


class DeviceApkProvider:
    def __init__(
        self,
        adb: AdbTransport,
        cache_dir: Path | None = None,
        workers: int = 2,
        timeout_s: float = 60.0,
        fetch: Callable[..., FetchedApks] = fetch_apks,
        analyze: Callable[..., ApkReport] | None = None,
        isolated: Callable[[float], IsolatedAnalyzer] = IsolatedAnalyzer,
        policy: CachePolicy | None = None,
        deep: frozenset[str] = frozenset(),
        deep_analyze: Callable[..., ApkReport] | None = None,
        results: ResultStore | None = None,
    ) -> None:
        self.adb = adb
        self.cache_dir = cache_dir or default_cache_dir()
        self.workers = workers
        self.timeout_s = timeout_s
        self.fetch = fetch
        self.analyze = analyze
        self.isolated = isolated
        self.policy = policy
        self.deep = deep  # pakiety do głębokiej analizy (na żądanie; nigdy w zwykłym skanie)
        self.deep_analyze = deep_analyze
        self.results = results or ResultStore(self.cache_dir.parent / "apk-reports")

    def _prepare(self, apps: list[AppFacts],
                 flagged: frozenset[str]) -> tuple[_CacheRun | None, bool]:
        """Szacunek, ewentualne pytanie i stan przycinania. Zwraca (stan, czy pominąć analizę)."""
        policy = self.policy
        scan = frozenset(f.package for f in apps)
        try:
            use = usage(self.cache_dir, policy.limit_bytes)
        except OSError:
            return None, False  # spec §6: bez `disk_usage` — bez kontroli, jak dawniej
        try:
            est = estimate(self.adb, apps, self.cache_dir)
        except OSError:
            est = None  # jak brak szacunku: analiza bez pytania, chroni ją §3.6
        if est is not None:
            policy.on_estimate(est, use)
            try:
                if not fits(est, self.cache_dir, scan):
                    answer = policy.decide(est, use)
                    if answer == "clear":
                        clear_cache(self.cache_dir)
                    elif answer != "run":
                        return None, True
            except OSError:
                return None, False
        return _CacheRun(self.cache_dir, policy.limit_bytes, est.sizes if est else {}, scan,
                         flagged, est.to_fetch if est else None), False

    def _one(self, facts: AppFacts, run: Callable[..., ApkReport],
             cache: _CacheRun | None = None,
             deep_run: Callable[..., ApkReport] | None = None) -> ApkReport:
        def no_space() -> ApkReport:
            return ApkReport(facts.package, facts.version_code, error=NO_SPACE)

        if cache is not None:
            try:
                cache.before_fetch(facts.package)
            except NoSpace:
                return no_space()
        no_room = False
        try:
            fetched = self.fetch(self.adb, facts.package, self.cache_dir)
            if deep_run is not None and facts.package in self.deep:
                return self._deep(facts, fetched, run, deep_run)
            return self._finish(facts, fetched, run)
        except NoSpace:
            no_room = True
            return no_space()
        except AdbError as exc:
            return ApkReport(facts.package, facts.version_code, error=f"pull: {exc.message}")
        finally:
            if cache is not None:
                cache.after(facts.package, no_space=no_room)

    def _deep(self, facts: AppFacts, fetched: FetchedApks, run: Callable[..., ApkReport],
              deep_run: Callable[..., ApkReport]) -> ApkReport:
        if not fetched.expected:
            # Bez zweryfikowanych skrótów nie ma klucza pamięci: analiza za każdym razem od nowa.
            return self._deep_or_normal(facts, fetched, run, deep_run)
        # Klucz z zweryfikowanych skrótów telefonu (nie z plików na dysku): wpis pasuje tylko
        # do tych samych bajtów co zainstalowane. Pamięć trzyma tylko ścieżki kodu — resztę raportu
        # daje świeża zwykła analiza, a reguły liczone są od nowa (ocena §6, recenzja Etapu 4).
        key = result_key(fetched.expected, current_deep_version())
        if (stored := self.results.get(key)) is not None and stored.code_paths is not None:
            report = self._finish(facts, fetched, run)
            if report.class_count > 0:
                report.code_paths, report.undetermined = stored.code_paths, list(stored.undetermined)
                report.deep = True
            return report
        report = self._deep_or_normal(facts, fetched, run, deep_run)
        if report.deep and not report.error and report.code_paths is not None:
            try:
                self.results.put(key, ApkReport(facts.package, deep=True, files=dict(report.files),
                                                code_paths=report.code_paths,
                                                undetermined=list(report.undetermined)))
            except OSError:
                pass  # brak zapisu = następnym razem analiza od nowa
        return report

    def _deep_or_normal(self, facts: AppFacts, fetched: FetchedApks, run: Callable[..., ApkReport],
                        deep_run: Callable[..., ApkReport]) -> ApkReport:
        report = self._finish(facts, fetched, deep_run)
        if report.class_count > 0:
            return report
        # Głęboka analiza padła (pamięć, limit czasu): zostaje wynik zwykłej analizy, a ścieżki
        # kodu są „nie ustalono” — nieudana próba nie może zamienić sygnałów w „brak sygnałów”.
        normal = self._finish(facts, fetched, run)
        if normal.class_count > 0:
            normal.code_paths, normal.undetermined = [], ["deep_failed"]
        return normal

    def _finish(self, facts: AppFacts, fetched: FetchedApks,
                run: Callable[..., ApkReport]) -> ApkReport:
        report = run(facts.package, fetched.paths)
        if fetched.expected is not None:
            # Między weryfikacją a analizą plik mógł się zmienić (inny proces, dysk): wynik
            # opisywałby bajty, których telefon nie ma — jak przy innej wersji, odrzucamy go.
            changed = sorted(n for n, d in report.files.items() if fetched.expected.get(n) != d)
            if changed:
                return ApkReport(facts.package, facts.version_code,
                                 error=f"identity: {', '.join(changed)} differs from the verified file")
        if not fetched.verified:
            note = "identity: unverified (no sha256sum on the phone)"
            report.error = f"{report.error}; {note}" if report.error else note
        return report

    def reports_for(
        self, apps: list[AppFacts], progress: ProgressFn | None = None,
        flagged: frozenset[str] = frozenset(),
    ) -> dict[str, ApkReport]:
        cache = None
        if self.policy is not None and apps:
            cache, skip = self._prepare(apps, flagged)
            if skip:
                return {f.package: ApkReport(f.package, f.version_code, error=NO_SPACE)
                        for f in apps}
        reports: dict[str, ApkReport] = {}
        analyzers: list[IsolatedAnalyzer] = []
        local = threading.local()
        guard = threading.Lock()

        def run(package: str, paths: list[Path]) -> ApkReport:
            if self.analyze is not None:
                return self.analyze(package, paths)
            if getattr(local, "analyzer", None) is None:
                local.analyzer = self.isolated(self.timeout_s)
                with guard:
                    analyzers.append(local.analyzer)
            return local.analyzer.analyze(package, paths)

        def deep_run(package: str, paths: list[Path]) -> ApkReport:
            if self.deep_analyze is not None:
                return self.deep_analyze(package, paths)
            if getattr(local, "deep", None) is None:
                local.deep = IsolatedAnalyzer(DEEP_TIMEOUT_S, analyze=deep_analyze)
                with guard:
                    analyzers.append(local.deep)
            return local.deep.analyze(package, paths)

        pool = ThreadPoolExecutor(max_workers=self.workers)
        try:
            futures = [(facts, pool.submit(self._one, facts, run, cache, deep_run)) for facts in apps]
            for done, (facts, future) in enumerate(futures, start=1):
                limit = self.timeout_s
                if facts.package in self.deep:
                    limit += DEEP_TIMEOUT_S  # zwykła analiza w deep_analyze + graf wywołań
                try:
                    # Zapas na pobranie: limit analizy pilnuje proces potomny.
                    report = future.result(timeout=limit + PULL_TIMEOUT)
                except FutureTimeout:
                    report = ApkReport(facts.package, facts.version_code, error="timeout")
                except Exception as exc:  # noqa: BLE001 — jedna aplikacja nie może przerwać analizy pozostałych
                    report = ApkReport(facts.package, facts.version_code,
                                       error=f"{type(exc).__name__}: {exc}")
                reports[facts.package] = report
                if progress:
                    progress(done, len(apps), facts.package)
        finally:
            pool.shutdown(wait=self.analyze is None, cancel_futures=True)
            for analyzer in analyzers:
                analyzer.close()
        return reports
