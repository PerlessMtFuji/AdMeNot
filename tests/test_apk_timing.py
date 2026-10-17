import json

import pytest

from admenot.engine.apk.cache import Estimate
from admenot.engine.apk.timing import (
    DEFAULT_SPEEDS,
    MB,
    RunStats,
    Speeds,
    blend,
    estimate_eta,
    eta_for,
    learn,
    live_eta,
    load_speeds,
    save_speeds,
)

KNOWN = Speeds(pull_bps=10 * MB, analyze_bps=20 * MB, per_app_s=1.0, samples=3)


def _est(sizes, to_fetch):
    return Estimate(sum(sizes.values()), sum(sizes[p] for p in to_fetch), len(sizes), 0,
                    0, dict(sizes), frozenset(to_fetch))


def test_eta_formula_divides_by_workers_and_counts_cache_only_in_analysis():
    eta = eta_for(KNOWN, to_fetch_bytes=100 * MB, total_bytes=200 * MB, apps=10, workers=2)
    # (100/10 + 200/20 + 10*1) / 2 = 15 s
    assert eta == eta.__class__(15, "measured", 15, 15)


def test_eta_never_uses_more_workers_than_apps():
    assert eta_for(KNOWN, to_fetch_bytes=0, total_bytes=20 * MB, apps=1, workers=2).seconds == 2


def test_without_history_eta_is_a_rough_range():
    eta = eta_for(DEFAULT_SPEEDS, to_fetch_bytes=0, total_bytes=0, apps=100, workers=1)
    assert eta.kind == "rough"
    assert eta.low == round(eta.seconds * 0.6) and eta.high == round(eta.seconds * 1.5)


def test_estimate_eta_for_a_subset_uses_its_sizes_and_cache_state():
    est = _est({"a": 10 * MB, "b": 20 * MB, "c": 40 * MB}, to_fetch={"b", "c"})
    eta = estimate_eta(est, KNOWN, workers=1, packages=["a", "b"])
    # pobranie tylko b (20 MB / 10) + analiza a+b (30 MB / 20) + 2 aplikacje * 1 s = 2 + 1.5 + 2
    assert eta.seconds == round(5.5)


def _run(apps=10, size=10 * MB, pull_s=2.0, hit=False, analyze_s=0.5):
    run = RunStats()
    for _ in range(apps):
        run.add(size=size, fetch_s=pull_s, from_cache=hit, analyze_s=analyze_s)
    return run


def test_first_measurement_replaces_the_defaults():
    run = _run(apps=10, size=10 * MB, pull_s=2.0, analyze_s=0.5)
    new = learn(DEFAULT_SPEEDS, run)
    assert new.samples == 1
    # brak trafień w pamięci: narzut z domyślnych; pobieranie = bajty / (czas - narzut)
    expected_pull = 100 * MB / (20.0 - 10 * DEFAULT_SPEEDS.per_app_s)
    assert abs(new.pull_bps - expected_pull) < 1
    assert abs(new.analyze_bps - 100 * MB / 5.0) < 1


def test_later_measurements_are_an_ema_with_weight_0_3():
    run = _run(apps=10, size=10 * MB, pull_s=1.0 + 1.0, analyze_s=1.0)  # 10 MB/s analizy
    new = learn(KNOWN, run)
    assert abs(new.analyze_bps - (KNOWN.analyze_bps * 0.7 + 10 * MB * 0.3)) < 1
    assert new.samples == KNOWN.samples + 1


def test_small_runs_do_not_teach():
    assert learn(KNOWN, _run(apps=4, size=1 * MB)) == KNOWN
    assert learn(KNOWN, _run(apps=1, size=60 * MB)) != KNOWN  # ≥ 50 MB wystarczy


def test_cache_hits_measure_the_per_app_overhead():
    run = _run(apps=5, size=10 * MB, pull_s=0.4, hit=True, analyze_s=0.5)
    run.add(size=0, fetch_s=0.0, from_cache=True, analyze_s=0.0)
    new = learn(Speeds(1, 1, 9.0, 0), run)
    assert abs(new.per_app_s - (0.4 * 5) / 6) < 1e-6


def test_live_eta_blends_history_with_the_current_run():
    est = _est({f"p{i}": 10 * MB for i in range(20)}, to_fetch={f"p{i}" for i in range(20)})
    run = _run(apps=10, size=10 * MB, pull_s=2.0, analyze_s=0.5)
    seconds = live_eta(KNOWN, run, est, remaining_apps=10, workers=1)
    assert seconds is not None and seconds > 0
    assert live_eta(KNOWN, None, est, 10, 1) is None
    assert live_eta(KNOWN, run, None, 10, 1) is None


def test_blend_weight_grows_with_the_sample():
    tiny = _run(apps=1, size=10 * MB, pull_s=2.0, analyze_s=10.0)  # bardzo wolna analiza
    assert blend(KNOWN, tiny).analyze_bps > blend(KNOWN, _run(apps=10, size=10 * MB, analyze_s=10.0)).analyze_bps


def test_load_save_roundtrip_and_broken_file(tmp_path):
    path = tmp_path / "apk-timing.json"
    assert load_speeds(path) == DEFAULT_SPEEDS
    save_speeds(KNOWN, path)
    assert load_speeds(path) == KNOWN
    path.write_text("{oops", "utf-8")
    assert load_speeds(path) == DEFAULT_SPEEDS
    path.write_text(json.dumps({"pull_bps": -1, "analyze_bps": 1, "per_app_s": 1, "samples": 1}), "utf-8")
    assert load_speeds(path) == DEFAULT_SPEEDS


@pytest.mark.parametrize("raw", [
    '{"pull_bps": NaN, "analyze_bps": 1, "per_app_s": 1, "samples": 1}',
    '{"pull_bps": 1, "analyze_bps": Infinity, "per_app_s": 1, "samples": 1}',
    '{"pull_bps": 1, "analyze_bps": 1, "per_app_s": NaN, "samples": 1}',
    '{"pull_bps": 1e308, "analyze_bps": 1, "per_app_s": 1, "samples": 1}',
    '{"pull_bps": 1, "analyze_bps": 1, "per_app_s": 1e308, "samples": 1}',
    '{"pull_bps": 1, "analyze_bps": 1, "per_app_s": 1, "samples": 1e308}',
])
def test_non_finite_or_absurd_timing_file_falls_back_to_defaults(tmp_path, raw):
    path = tmp_path / "apk-timing.json"
    path.write_text(raw, "utf-8")
    assert load_speeds(path) == DEFAULT_SPEEDS


@pytest.mark.parametrize("speeds", [
    Speeds(float("nan"), 1.0, 1.0, 1), Speeds(1.0, float("inf"), 1.0, 1),
    Speeds(1e-320, 1.0, 1.0, 1), Speeds(1.0, 1.0, float("inf"), 0),
])
def test_eta_never_raises_on_broken_speeds(speeds):
    eta = eta_for(speeds, to_fetch_bytes=100 * MB, total_bytes=100 * MB, apps=10, workers=1)
    fallback = eta_for(DEFAULT_SPEEDS, to_fetch_bytes=100 * MB, total_bytes=100 * MB, apps=10, workers=1)
    assert eta == fallback


def test_live_eta_is_zero_when_no_apps_remain():
    est = _est({f"p{i}": 10 * MB for i in range(20)}, to_fetch={f"p{i}" for i in range(20)})
    run = _run(apps=5, size=10 * MB)  # część bajtów niepobrana (np. brak rozmiaru), ale aplikacji już nie ma
    assert live_eta(KNOWN, run, est, remaining_apps=0, workers=1) == 0
    assert live_eta(KNOWN, run, est, remaining_apps=-1, workers=1) == 0
