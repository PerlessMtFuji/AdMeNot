"""Podpisujący z raportów APK → wpisy do trusted.yaml DO WERYFIKACJI przez człowieka.

python scripts/trusted_signers.py KATALOG_Z_RAPORTAMI_APK [...]

KATALOG to np. tests/fixtures/<nagranie>/apk albo katalog z `admenot capture --apk`.
Wypisuje tylko pakiety pasujące do nazw z trusted.yaml. Wynik trzeba potwierdzić drugim
źródłem (inny telefon z aplikacją ze Sklepu Play) przed wklejeniem do trusted.yaml.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from admenot.engine.allowlist.trust import load_default_trust_list


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 1
    trust = load_default_trust_list()
    found: dict[str, set[str]] = defaultdict(set)
    for directory in argv:
        for path in sorted(Path(directory).glob("*.json")):
            data = json.loads(path.read_text("utf-8"))
            package = data.get("package", "")
            if trust.matches(package) and not data.get("error"):
                found[package].update(data.get("cert_sha256") or [])
    for package in sorted(found):
        print(f"  - {{package: {package}, signers: [{', '.join(sorted(found[package]))}]}}"
              f"  # źródło: {', '.join(argv)} — DO WERYFIKACJI")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
