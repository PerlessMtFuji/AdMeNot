import pytest

from demalware.engine.evaluation import evaluate, format_evaluation, parse_labels
from demalware.engine.facts import AppFacts
from demalware.engine.scoring import AppResult


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
