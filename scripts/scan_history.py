"""Skan całej historii gita pod kątem danych osobowych z nagrań telefonów.

python scripts/scan_history.py [--repo .] [--allow scripts/scan_history_allow.txt]

Przegląda każdy blob osiągalny z dowolnej gałęzi lub tagu, także pliki już usunięte. Sekrety
(klucze, tokeny) sprawdza osobno gitleaks. Skrypt niczego w repozytorium nie zmienia.
Kod wyjścia: 0 — brak nierozstrzygniętych trafień, 1 — są trafienia.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOW = ROOT / "scripts" / "scan_history_allow.txt"
BINARY_PROBE = 8192
# zaślepki w nagraniach i dokumentach, nie wartości
PLACEHOLDER = re.compile(r"^(\{.*\}|<.*>|…|\.\.\.|unknown|null|none)$", re.IGNORECASE)
EXAMPLE_DOMAIN = re.compile(r"@([a-z0-9-]+\.)*example\.(com|org|net)$", re.IGNORECASE)
COMMON_USER_DIRS = {"public", "default", "all users"}


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    keep: Callable[[str], bool] = lambda value: True


RULES = (
    # 15 cyfr z poprawną sumą Luhna; nie część ułamka ani dłuższej liczby
    Rule("imei", re.compile(r"(?<![0-9.])(?P<v>[0-9]{15})(?![0-9])"), luhn_ok),
    # \\? — cudzysłowy escapowane, gdy wyjście polecenia leży w napisie JSON (nagrania mostu)
    Rule("serial", re.compile(r"(?:\[ro(?:\.boot)?\.serialno\]: \[|\\?\"serial\\?\": \\?\")"
                              r"(?P<v>[^\]\"\\]+)")),
    Rule("email", re.compile(r"(?P<v>[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"),
         lambda value: not EXAMPLE_DOMAIN.search(value)),
    Rule("account", re.compile(r"(?:Account \{name=|account=)(?P<v>[^,}\s`]+)")),
    Rule("wifi", re.compile(r"(?:SSID: \\?\"|ssid=(?:\\?\")?)(?P<v>[^\\\",}\s`]+)", re.IGNORECASE)),
    Rule("phone", re.compile(r"(?<![0-9A-Za-z])(?P<v>\+[0-9][0-9 -]{7,17}[0-9])(?![0-9])"),
         lambda value: 9 <= sum(c.isdigit() for c in value) <= 15),
    Rule("user_path", re.compile(r"(?:[A-Za-z]:\\{1,2}Users\\{1,2}|/[a-z]/Users/)"
                                 r"(?P<v>[^\\/\s\"'`]+)", re.IGNORECASE),
         lambda value: value.lower() not in COMMON_USER_DIRS),
)


@dataclass(frozen=True)
class Hit:
    rule: str
    value: str
    path: str
    commit: str


def find(text: str, allow: frozenset[str]) -> list[tuple[str, str]]:
    found = []
    for rule in RULES:
        for match in rule.pattern.finditer(text):
            value = match.group("v").strip()
            if value and value not in allow and not PLACEHOLDER.match(value) and rule.keep(value):
                found.append((rule.name, value))
    return list(dict.fromkeys(found))


def mask(value: str) -> str:
    return "*" * max(len(value) - 4, 0) + value[-4:]


def load_allow(path: Path) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    values = (line.split("#", 1)[0].strip() for line in path.read_text("utf-8").splitlines())
    return frozenset(v for v in values if v)


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True,
                          check=True).stdout


def blob_paths(repo: Path) -> dict[str, str]:
    """Skrót bloba → pierwsza ścieżka, pod którą występuje (wszystkie gałęzie i tagi)."""
    listed: dict[str, str] = {}
    for line in _git(repo, "rev-list", "--objects", "--all").decode("utf-8", "replace").splitlines():
        sha, _, path = line.partition(" ")
        if path:
            listed.setdefault(sha, path)
    kinds = _git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype)",
                 stdin="".join(f"{sha}\n" for sha in listed).encode())
    blobs = {line.split()[0] for line in kinds.decode().splitlines() if line.endswith(" blob")}
    return {sha: path for sha, path in listed.items() if sha in blobs}


def blob_contents(repo: Path, shas: list[str]) -> Iterator[tuple[str, bytes]]:
    proc = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def feed() -> None:
        proc.stdin.write("".join(f"{sha}\n" for sha in shas).encode())
        proc.stdin.close()

    threading.Thread(target=feed, daemon=True).start()
    for _ in shas:
        sha, _kind, size = proc.stdout.readline().decode().split()
        content = proc.stdout.read(int(size))
        proc.stdout.read(1)  # znak nowej linii po zawartości
        yield sha, content
    proc.wait()


def first_commit(repo: Path, sha: str) -> str:
    commits = _git(repo, "log", "--all", "--reverse", "--format=%h", f"--find-object={sha}")
    return (commits.decode().split() or ["?"])[0]


def scan(repo: Path, allow: frozenset[str]) -> list[Hit]:
    paths = blob_paths(repo)
    hits = []
    for sha, content in blob_contents(repo, list(paths)):
        if b"\0" in content[:BINARY_PROBE]:
            continue
        found = find(content.decode("utf-8", "replace"), allow)
        if found:
            commit = first_commit(repo, sha)
            hits += [Hit(rule, value, paths[sha], commit) for rule, value in found]
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--allow", type=Path, default=ALLOW)
    args = parser.parse_args(argv)
    hits = scan(args.repo, load_allow(args.allow))
    for hit in hits:
        print(f"{hit.rule:10} {mask(hit.value):24} {hit.commit:10} {hit.path}")
    print(f"trafienia: {len(hits)}" if hits else "brak trafień")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
