import json
from pathlib import Path

from admenot.app.telemetry_events import sample

I18N = Path(__file__).resolve().parents[1] / "ui" / "src" / "lib" / "i18n"


def test_every_event_type_is_described_in_both_languages():
    types = {e["type"] for e in sample()["basic"]}
    for lang in ("pl", "en"):
        what = json.loads((I18N / f"{lang}.json").read_text("utf-8"))["privacy"]["what"]
        assert types <= set(what), lang
        assert {"common", "packages", "never"} <= set(what), lang
