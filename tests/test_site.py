"""Strona w server/public: linki, brak zasobów z zewnątrz, treść polityki (spec backendu §3, §5.1)."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

PUBLIC = Path(__file__).resolve().parents[1] / "server" / "public"
PAGES = ("index.html", "privacy.html", "pl/index.html", "pl/privacy.html", "404.html")
DOWNLOAD = "https://github.com/PerlessMtFuji/AdMeNot/releases/latest"


class Page(HTMLParser):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.feed(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))

    def all(self, tag: str) -> list[dict[str, str | None]]:
        return [attrs for name, attrs in self.tags if name == tag]


def load(name: str) -> tuple[str, Page]:
    text = (PUBLIC / name).read_text("utf-8")
    return text, Page(text)


def target_file(href: str) -> Path:
    """Adres wewnętrzny → plik w public/ tak, jak go serwuje Cloudflare (auto-trailing-slash)."""
    path = href.split("#")[0].lstrip("/")
    if path == "" or path.endswith("/"):
        return PUBLIC / path / "index.html"
    if "." not in path.rsplit("/", 1)[-1]:
        return PUBLIC / f"{path}.html"
    return PUBLIC / path


@pytest.mark.parametrize("name", PAGES)
def test_page_basics(name):
    _, page = load(name)
    assert page.all("html")[0].get("lang") in ("en", "pl")
    assert {"charset": "utf-8"} in page.all("meta")
    assert any(m.get("name") == "viewport" for m in page.all("meta"))
    assert page.all("script") == []  # bez JavaScriptu


@pytest.mark.parametrize("name", PAGES)
def test_no_external_resources(name):
    _, page = load(name)
    for tag in ("link", "script", "img"):
        for attrs in page.all(tag):
            ref = attrs.get("href") or attrs.get("src") or ""
            assert ref.startswith("/") and not ref.startswith("//"), f"{name}: <{tag}> {ref}"  # zasoby tylko z tego hosta


@pytest.mark.parametrize("name", PAGES)
def test_internal_links_resolve(name):
    _, page = load(name)
    refs = [a.get("href") or a.get("src") or "" for _, a in page.tags]
    for ref in (r for r in refs if r.startswith("/")):
        assert target_file(ref).is_file(), f"{name}: {ref}"


def test_language_switch():
    _, en = load("index.html")
    _, pl = load("pl/index.html")
    assert "/pl/" in [a.get("href") for a in en.all("a")]
    assert "/" in [a.get("href") for a in pl.all("a")]
    _, en_privacy = load("privacy.html")
    _, pl_privacy = load("pl/privacy.html")
    assert "/pl/privacy" in [a.get("href") for a in en_privacy.all("a")]
    assert "/privacy" in [a.get("href") for a in pl_privacy.all("a")]


def test_download_switch_is_consistent():
    flags = set()
    for name in ("index.html", "pl/index.html"):
        _, page = load(name)
        flags.add(page.all("body")[0].get("data-released"))
        assert DOWNLOAD in [a.get("href") for a in page.all("a")]
    assert len(flags) == 1 and flags <= {"true", "false"}


@pytest.mark.parametrize("name", ("privacy.html", "pl/privacy.html"))
def test_privacy_names_the_controller(name):
    text, _ = load(name)
    assert "Eryk Wlodarski" in text
    assert "e.wlodarski@protonmail.com" in text
    assert "selfcheck --online" in text


@pytest.mark.parametrize(
    ("name", "basis"),
    (("privacy.html", "Art. 6(1)(f)"), ("pl/privacy.html", "art. 6 ust. 1 lit. f")),
)
def test_privacy_states_legal_basis_and_transfer(name, basis):
    text, _ = load(name)
    assert basis in text
    assert "Data Privacy Framework" in text


def test_polish_privacy_names_the_authority():
    text, _ = load("pl/privacy.html")
    assert "Prezesa Urzędu Ochrony Danych Osobowych" in text
