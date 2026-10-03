"""Slugi, kody modeli i nazwy telefonów: jedna normalizacja dla budowania bazy i dopasowania."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

_URL_SLUG = re.compile(r"/([a-z0-9_+]+)-\d+\.php", re.IGNORECASE)
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_CODE = re.compile(r"[A-Z0-9][A-Z0-9._+ -]{1,39}")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_INCHES = re.compile(r"(\d+(?:\.\d+)?)\s*inch", re.IGNORECASE)
_BATTERY = re.compile(r"(\d{3,5})\s*mAh", re.IGNORECASE)

NETWORK_TOKENS = frozenset({"4g", "5g", "lte"})
# Marki z `ro.product.brand` i z listy Google → marka producenta w danych Szklodo.
BRAND_ALIASES = {
    "redmi": "xiaomi",
    "poco": "xiaomi",
    "lge": "lg",
    "tct alcatel": "alcatel",
    "hmd global": "nokia",
}


def slug_from_url(url: str | None) -> str | None:
    """Jak `slugFromUrl` w Szklodo: `samsung_galaxy_s25+-13609.php` → `samsung-galaxy-s25-plus`."""
    m = _URL_SLUG.search(url or "")
    if not m:
        return None
    slug = m.group(1).lower().replace("+", "-plus").replace("_", "-")
    return re.sub(r"-+", "-", slug).strip("-")


def slug_from_name(name: str) -> str:
    return _NON_ALNUM.sub("-", name.lower()).strip("-")


def record_slugs(records: Iterable[Mapping]) -> list[str | None]:
    """Slugi jak nazwy plików WebP w Szklodo: bez nazwy → None, powtórki → `-2`, `-3`…"""
    used: set[str] = set()
    slugs: list[str | None] = []
    for record in records:
        name = record.get("name") or ""
        if not name.strip():
            slugs.append(None)
            continue
        base = slug_from_url(record.get("url"))
        if base is None:
            base = slug_from_name(name)
        base = base or "model"
        slug, n = base, 2
        while slug in used:
            slug, n = f"{base}-{n}", n + 1
        used.add(slug)
        slugs.append(slug)
    return slugs


def model_key(raw: str | None) -> str | None:
    """`sm-a145f/DSN` → `SM-A145F`; spacje zwinięte, niewidoczne znaki usunięte."""
    key = " ".join(_INVISIBLE.sub("", raw or "").upper().split("/")[0].split())
    return key or None


def split_codes(models: str | None) -> list[str]:
    codes: list[str] = []
    for part in (models or "").split(","):
        code = model_key(part)
        if (code and _CODE.fullmatch(code) and any(c.isdigit() for c in code)
                and code not in codes):
            codes.append(code)
    return codes


def name_tokens(text: str) -> list[str]:
    """Małe litery, `+` → `plus`, bez znaków spoza [a-z0-9], bez powtórzonych sąsiadów."""
    words = _NON_ALNUM.sub(" ", _INVISIBLE.sub("", text).lower().replace("+", " plus ")).split()
    return [w for i, w in enumerate(words) if i == 0 or w != words[i - 1]]


def norm_name(text: str) -> str:
    return " ".join(name_tokens(text))


def key_tokens(tokens: Iterable[str]) -> frozenset[str]:
    """Tokeny numeru modelu (`a14`, `12`), bez oznaczeń sieci."""
    return frozenset(t for t in tokens if any(c.isdigit() for c in t) and t not in NETWORK_TOKENS)


def canonical_brand(brand: str) -> str:
    name = norm_name(brand)
    return BRAND_ALIASES.get(name, name)


def with_brand(brand: str, name: str) -> str:
    """Znormalizowana nazwa z marką na początku; pusta, gdy z nazwy nic nie zostało."""
    tokens = name_tokens(name)
    if not tokens:
        return ""
    prefix = brand.split()
    if prefix and tokens[:len(prefix)] != prefix:
        tokens = prefix + tokens
    return " ".join(tokens)


def parse_year(text: str | None) -> int | None:
    m = _YEAR.search(text or "")
    return int(m.group()) if m else None


def parse_display_in(text: str | None) -> float | None:
    m = _INCHES.search(text or "")
    return float(m.group(1)) if m else None


def parse_battery_mah(text: str | None) -> int | None:
    m = _BATTERY.search(text or "")
    return int(m.group(1)) if m else None
