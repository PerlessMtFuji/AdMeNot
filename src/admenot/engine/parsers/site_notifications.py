from __future__ import annotations

import re
from dataclasses import dataclass, field

from admenot.engine.parsers.common import UnrecognizedOutput
from admenot.engine.parsers.notifications import _PKG, _USER

_GROUP = re.compile(r"NotificationChannelGroup\{mId='([^']*)'")
_CHANNEL = re.compile(r"NotificationChannel\{mId='([^']*)', mName=(.*?), mDescription=.*?mImportance=(-?\d+)")
_APP = re.compile(r"^(\s*)AppSettings: ([\w.]+) \((\d+)\)")
_CHANNEL_OF_RECORD = re.compile(r"Notification\(channel=(\S+)")
_TAG = re.compile(r"\btag=(\S+)")
_SUBTEXT = re.compile(r"android\.subText=String \((.*)\)\s*$", re.MULTILINE)
_SITE_ID = re.compile(r"^web:(https?://[A-Za-z0-9.-]+(?::\d{1,5})?);\d+$")
_TAG_ORIGIN = re.compile(r"^p#(https?://[A-Za-z0-9.-]+(?::\d{1,5})?)/#")
_USER_UID_RANGE = 100000  # uid / 100000 = id profilu; interesuje nas tylko użytkownik 0


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    importance: int


@dataclass(frozen=True)
class ActiveSiteNotification:
    package: str
    channel: str
    tag: str
    sub_text: str | None


@dataclass
class NotificationDump:
    channels: dict[str, list[Channel]] = field(default_factory=dict)  # pakiet → kanały (z AppSettings)
    groups: dict[str, set[str]] = field(default_factory=dict)  # pakiet → id grup kanałów (Chromium: „sites”)
    active: list[ActiveSiteNotification] = field(default_factory=list)  # rekordy z Notification List, user 0


def _list_body(text: str) -> str | None:
    # Jak _notification_list, ale treść powiadomienia bywa wielolinijkowa i zaczyna linie w kolumnie 0 —
    # sekcję kończy dopiero nagłówek kolejnej sekcji (wcięty, kończy się dwukropkiem).
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "Notification List:":
            indent = len(line) - len(line.lstrip(" "))
            body: list[str] = []
            for nxt in lines[i + 1:]:
                nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                if nxt.strip().endswith(":") and 0 < nxt_indent <= indent:
                    break
                body.append(nxt)
            return "\n".join(body)
    return None


def _active(body: str) -> list[ActiveSiteNotification]:
    found: list[ActiveSiteNotification] = []
    for chunk in body.split("NotificationRecord(")[1:]:
        head = chunk[:600]
        pkg = _PKG.search(head)
        if not pkg:
            continue
        user = _USER.search(head)
        if user and int(user.group(1)) != 0:
            continue
        channel = _CHANNEL_OF_RECORD.search(head)
        tag = _TAG.search(head)
        sub = _SUBTEXT.search(chunk)
        found.append(ActiveSiteNotification(
            package=pkg.group(1),
            channel=channel.group(1) if channel else "",
            tag=tag.group(1) if tag and tag.group(1) != "null" else "",
            sub_text=sub.group(1) if sub else None,
        ))
    return found


def _channels(text: str) -> tuple[dict[str, list[Channel]], dict[str, set[str]]]:
    result: dict[str, list[Channel]] = {}
    groups: dict[str, set[str]] = {}
    current: list[Channel] | None = None
    package = ""
    app_indent = 0
    for line in text.splitlines():
        app = _APP.match(line)
        if app:
            app_indent = len(app.group(1))
            # inne profile (uid >= 100000) pomijamy, ich kanały to nie kanały użytkownika 0
            package = app.group(2)
            current = result.setdefault(package, []) if int(app.group(3)) < _USER_UID_RANGE else None
            continue
        if current is None:
            continue
        if line.strip() and len(line) - len(line.lstrip(" ")) <= app_indent:
            current = None
            continue
        ch = _CHANNEL.search(line)
        if ch:
            current.append(Channel(ch.group(1), ch.group(2), int(ch.group(3))))
        elif group := _GROUP.search(line):
            groups.setdefault(package, set()).add(group.group(1))
    return result, groups


def parse_notification_dump(text: str) -> NotificationDump:
    body = _list_body(text)
    channels, groups = _channels(text)
    if body is None and not channels:
        raise UnrecognizedOutput("neither 'Notification List:' nor 'AppSettings:' in dumpsys notification")
    # Sekcje AppSettings bez ani jednego odczytanego kanału to inny format (producent, Android), nie
    # „brak kanałów”: puste listy dawałyby fałszywe OK w kontroli i „wyłączony” w kroku `channel`.
    if (channels or "NotificationChannel{" in text) and not any(channels.values()):
        raise UnrecognizedOutput("AppSettings sections without a readable NotificationChannel")
    return NotificationDump(channels=channels, groups=groups, active=_active(body) if body is not None else [])


def site_origin(channel_id: str) -> str | None:
    m = _SITE_ID.match(channel_id)
    return m.group(1) if m else None


def tag_origin(tag: str) -> str | None:
    m = _TAG_ORIGIN.match(tag)
    return m.group(1) if m else None
