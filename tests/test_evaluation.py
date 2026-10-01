import pytest

from demalware.engine.evaluation import (
    ABLATIONS,
    LabelMeta,
    evaluate,
    format_contribution_table,
    format_evaluation,
    format_label_audit,
    format_threshold_table,
    parse_label_meta,
    parse_label_sets,
    parse_labels,
    rescore_without,
)
from demalware.engine.facts import AppFacts
from demalware.engine.rules.model import Finding
from demalware.engine.scoring import AppResult, score_app
from demalware.engine.session import ScanReport


def _r(package: str, verdict: str, score: int = 0) -> AppResult:
    return AppResult(AppFacts(package), [], score, verdict, trusted=False, incomplete=False)


def test_parse_labels_accepts_known_labels():
    labels = parse_labels("com.a: adware\ncom.b: clean\ncom.c: harmful\ncom.d: unsure\n")
    assert labels == {"com.a": "adware", "com.b": "clean", "com.c": "harmful", "com.d": "unsure"}


def test_parse_labels_rejects_unknown_label():
    with pytest.raises(ValueError, match="com.a"):
        parse_labels("com.a: '?'\n")


def test_parse_labels_empty_file():
    assert parse_labels("") == {}


def test_evaluate_confusion_matrix():
    results = [
        _r("com.ad1", "review", 30),     # TP
        _r("com.ad2", "safe", 10),       # FN
        _r("com.bad", "malicious", 80),  # TP
        _r("com.ok1", "safe"),           # TN
        _r("com.ok2", "suspicious", 55), # FP
        _r("com.meh", "review", 30),     # unsure → pominięta
        _r("com.sys", "review", 30),     # bez etykiety → pominięta
    ]
    labels = {"com.ad1": "adware", "com.ad2": "adware", "com.bad": "harmful",
              "com.ok1": "clean", "com.ok2": "clean", "com.meh": "unsure", "com.gone": "adware"}
    ev = evaluate(results, labels)
    pk = lambda rs: sorted(r.facts.package for r in rs)
    assert pk(ev.tp) == ["com.ad1", "com.bad"]
    assert pk(ev.fn) == ["com.ad2"]
    assert pk(ev.fp) == ["com.ok2"]
    assert pk(ev.tn) == ["com.ok1"]
    assert ev.missing == ["com.gone"]
    assert ev.recall == pytest.approx(2 / 3)
    assert ev.precision == pytest.approx(2 / 3)


def test_evaluate_metrics_none_without_data():
    ev = evaluate([], {})
    assert (ev.recall, ev.precision) == (None, None)


def test_format_evaluation_lists_misses_and_false_alarms():
    ev = evaluate([_r("com.ad2", "safe", 10), _r("com.ok2", "review", 30)],
                  {"com.ad2": "adware", "com.ok2": "clean"})
    text = format_evaluation(ev)
    assert "com.ad2" in text and "com.ok2" in text
    assert "Czułość" in text and "Precyzja" in text


def test_threshold_changes_what_counts_as_a_detection():
    results = [_r("com.a", "suspicious", 60), _r("com.b", "review", 30), _r("com.c", "safe", 0)]
    labels = {"com.a": "adware", "com.b": "adware", "com.c": "clean"}
    assert len(evaluate(results, labels).tp) == 2
    assert len(evaluate(results, labels, threshold="suspicious").tp) == 1
    assert len(evaluate(results, labels, threshold="malicious").tp) == 0


def test_label_sets_and_holdout_filter():
    text = "com.a: adware\ncom.b: {label: clean, set: holdout}\n"
    assert parse_labels(text) == {"com.a": "adware", "com.b": "clean"}
    assert parse_label_sets(text) == {"com.a": "tune", "com.b": "holdout"}
    results = [_r("com.a", "review", 30), _r("com.b", "review", 30)]
    ev = evaluate(results, parse_labels(text), only_set="holdout", sets=parse_label_sets(text))
    assert (len(ev.tp), len(ev.fp)) == (0, 1)


def test_threshold_table_lists_every_threshold():
    table = format_threshold_table([_r("com.a", "review", 30)], {"com.a": "adware"}, {"com.a": "tune"})
    for word in ("review", "suspicious", "malicious", "tune"):
        assert word in table


def test_label_meta_reads_both_forms():
    meta = parse_label_meta(
        "a.b: adware\n"
        "c.d: {label: clean, set: holdout, group: g1, basis: 'ręcznie, 2026-09-28'}\n")
    assert meta["a.b"] == LabelMeta("adware", "tune", None, None)
    assert meta["c.d"] == LabelMeta("clean", "holdout", "g1", "ręcznie, 2026-09-28")


def test_group_spanning_tune_and_holdout_is_rejected():
    text = ("a.v1: {label: adware, set: tune, group: fam}\n"
            "a.v2: {label: adware, set: holdout, group: fam}\n")
    with pytest.raises(ValueError, match="fam"):
        parse_label_meta(text)


def test_label_audit_flags_draft_labels_and_missing_basis():
    meta = parse_label_meta("a.b: adware\nc.d: {label: clean, basis: x}\n")
    out = format_label_audit(meta, "draft")
    assert "PROJEKT" in out
    assert "bez podstawy klasyfikacji: 1/2" in out
    assert "holdout: 0" in out


def test_rescore_without_apk_drops_apk_points_and_recomputes_combos():
    facts = AppFacts("com.ads", installed_days=30.0)
    sdk = Finding("DM-ADSDK-02", "apk", 25, {}, {}, {}, category="ads")
    notif = Finding("DM-NOTIF-01", "behavior", 20, {}, {}, {}, category="notif", basis="observed")
    result = score_app(facts, [sdk, notif], trusted=False, low_behavior_data=False)
    assert any(f.rule_id == "DM-COMBO-03" for f in result.findings)
    report = ScanReport(device=None, collectors={}, low_behavior_data=False, results=[result])
    (again,) = rescore_without(report, frozenset({"apk"}))
    assert [f.rule_id for f in again.findings] == ["DM-NOTIF-01"]
    assert again.score == 20


def test_contribution_table_has_one_row_per_ablation():
    report = ScanReport(device=None, collectors={}, low_behavior_data=False, results=[])
    out = format_contribution_table(report, {}, {})
    for name, _ in ABLATIONS:
        assert name in out
