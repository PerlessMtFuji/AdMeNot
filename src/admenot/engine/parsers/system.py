from __future__ import annotations

import re

from admenot.engine.parsers.common import component_packages, parse_components

_ADMIN_COMPONENT = re.compile(r"^\s+([A-Za-z][\w.]*)/[\w.$]+:\s*$")
_COMPONENT_INFO = re.compile(r"ComponentInfo\{([\w.]+)/")
_PACKAGE_NAME = re.compile(r"^[A-Za-z][\w]*(\.[\w]+)+$")
_USER_INFO = re.compile(r"UserInfo\{(\d+):")
_ADMINS_USER = re.compile(r"Enabled Device Admins \(User (\d+)")
_LISTENERS_HEADER = "Allowed notification listeners:"
_APPROVED_LINE = re.compile(r"^\s*(.*?)\s*\(user: (\d+) isPrimary: (true|false)\)\s*$")


def parse_users(text: str) -> list[int]:
    """`pm list users`: identyfikatory profili obecnych na telefonie."""
    return sorted({int(m) for m in _USER_INFO.findall(text)})


def parse_device_admins(text: str) -> set[str]:
    admins: set[str] = set()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "Enabled Device Admins" in line:
            user = _ADMINS_USER.search(line)
            if user and int(user.group(1)) != 0:
                continue  # profil służbowy / drugi użytkownik — poza zakresem skanu
            indent = len(line) - len(line.lstrip(" "))
            for nxt in lines[i + 1:]:
                if nxt.strip() and len(nxt) - len(nxt.lstrip(" ")) <= indent:
                    break
                if m := _ADMIN_COMPONENT.match(nxt):
                    admins.add(m.group(1))
        elif "admin" in line.lower():
            admins.update(_COMPONENT_INFO.findall(line))
    return admins


def parse_role_holders(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines() if _PACKAGE_NAME.match(line.strip())}


def parse_resolved_home(text: str) -> set[str]:
    return component_packages(text) - {"android"}


def parse_resolved_component(text: str) -> str | None:
    """Domyślna aktywność z `resolve-activity`; „android/…ResolverActivity” oznacza brak domyślnej."""
    return next((c for c in parse_components(text) if not c.startswith("android/")), None)


def parse_allowed_listeners(text: str) -> list[str] | None:
    """`dumpsys notification`: słuchacze zatwierdzeni w NotificationManagerze dla profilu 0.

    Od Androida 9 to oni mają dostęp, a `settings secure enabled_notification_listeners` jest
    tylko kopią, która potrafi się rozjechać. None = sekcji nie ma (stary Android) albo jest w nieznanym
    formacie — wtedy liczy się kopia, bo pusta lista uznałaby odebranie dostępu za już zrobione.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != _LISTENERS_HEADER:
            continue
        indent = len(line) - len(line.lstrip(" "))
        approved: list[str] = []
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                continue
            if len(nxt) - len(nxt.lstrip(" ")) <= indent:
                break
            m = _APPROVED_LINE.match(nxt)
            if m is None:
                return None
            if m[2] == "0" and m[3] == "true":
                approved = [c for c in m[1].split(":") if "/" in c]
        return approved
    return None
