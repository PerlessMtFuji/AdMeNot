"""Mapa komponentów z manifestu: rodzaj, eksport, uprawnienie, akcje, konfiguracja dostępności.

Działa na drzewie XML (lxml z androguard albo xml.etree w testach) — bez importu androguard.
Ocena 2026-10-01 §7.3: eksportowany komponent sam nie dowodzi szkodliwości; to mapa dla reguł.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

ANDROID = "{http://schemas.android.com/apk/res/android}"
KINDS = ("activity", "activity-alias", "service", "receiver", "provider")
A11Y_META = "android.accessibilityservice"


@dataclass(frozen=True)
class A11yConfig:
    retrieve_window: bool
    perform_gestures: bool
    event_types: str | None


@dataclass(frozen=True)
class Component:
    kind: str
    name: str
    exported: bool
    permission: str | None
    actions: tuple[str, ...]
    a11y: A11yConfig | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def component_to_json(c: Component) -> dict[str, Any]:
    return c.to_json()


def component_from_json(data: dict[str, Any]) -> Component:
    a11y = data.get("a11y")
    return Component(data["kind"], data["name"], bool(data["exported"]), data.get("permission"),
                     tuple(data.get("actions") or ()), A11yConfig(**a11y) if a11y else None)


def _attr(el: Any, name: str) -> str | None:
    return el.get(ANDROID + name)


def _full_name(package: str, name: str) -> str:
    return package + name if name.startswith(".") else name if "." in name else f"{package}.{name}"


def _a11y(el: Any, read_xml: Callable[[str], Any]) -> A11yConfig | None:
    for meta in el.findall("meta-data"):
        if _attr(meta, "name") == A11Y_META and (ref := _attr(meta, "resource")):
            xml = read_xml(ref)
            if xml is None:
                return None
            return A11yConfig(_attr(xml, "canRetrieveWindowContent") == "true",
                              _attr(xml, "canPerformGestures") == "true",
                              _attr(xml, "accessibilityEventTypes"))
    return None


def parse_components(root: Any, read_xml: Callable[[str], Any]) -> tuple[Component, ...]:
    package = root.get("package") or ""
    app = root.find("application")
    if app is None:
        return ()
    found = []
    for el in app:
        kind = el.tag if isinstance(el.tag, str) else ""
        if kind not in KINDS or not (raw := _attr(el, "name")):
            continue
        actions = tuple(a for f in el.findall("intent-filter") for x in f.findall("action")
                        if (a := _attr(x, "name")))
        exported_raw = _attr(el, "exported")
        if exported_raw is not None:
            exported = exported_raw == "true"
        else:
            exported = kind != "provider" and bool(el.findall("intent-filter"))
        a11y = _a11y(el, read_xml) if kind == "service" else None
        found.append(Component(kind, _full_name(package, raw), exported,
                               _attr(el, "permission"), actions, a11y))
    return tuple(found)
