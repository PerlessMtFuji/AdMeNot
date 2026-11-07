"""Kontrole „Stan telefonu” czytane przy skanie; etap 1: powiadomienia witryn w przeglądarkach.

Jeden odczyt `dumpsys notification --noredact` daje kanały witryn (Chrome i inne: jeden kanał na
witrynę), wspólne kanały znanych przeglądarek i aktywne powiadomienia. Firefox z włączonym zdalnym
debugowaniem dodatkowo oddaje listę zgód. Odczyt, którego nie rozumiemy, to „unrecognized”, nigdy
„brak witryn”. Przeglądarka spoza obu sposobów (żadnych kanałów witryn ani grupy „sites” Chromium)
to „unsupported”: serwisant widzi, że jej nie sprawdzono, zamiast żeby po cichu zniknęła. Poprawka to identyfikator (tekst); krok dla niej powstaje tylko dla witryny
albo przeglądarki obecnej w kontroli i nie zablokowanej, po `check_step` (SEC-01).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from admenot.engine.actions import commands as C
from admenot.engine.actions.errors import ActionError
from admenot.engine.actions.steps import Step, check_step
from admenot.engine.adb.transport import AdbError, AdbTransport
from admenot.engine.browsers.firefox_rdp import (
    FIREFOX,
    RdpError,
    notification_permissions,
    socket_present,
    tcp_connect,
)
from admenot.engine.browsers.known import (
    KnownBrowser,
    browser_names,
    known_browsers,
    without_site_notifications,
)
from admenot.engine.parsers.common import UnrecognizedOutput, query_packages
from admenot.engine.parsers.site_notifications import (
    Channel,
    NotificationDump,
    parse_notification_dump,
    site_origin,
    tag_origin,
)

CHECK_STATES = ("ok", "review", "unrecognized")  # etap 2 doda "fix"
SITE_NOTIFICATIONS = "site_notifications"
CHROME = "com.android.chrome"
# Przeglądarki na telefonie: aplikacje, które otwierają dowolny link http (aplikacje z linkami tylko do
# swojej domeny go nie obsługują). Bez MATCH_ALL (0x20000) system przy ustawionej przeglądarce domyślnej
# oddaje tylko ją (sprawdzone na Galaxy A13); starszy Android bez --query-flags dostaje zapytanie zwykłe.
_BROWSER_INTENT = "-a android.intent.action.VIEW -c android.intent.category.BROWSABLE -d http://example.com"
BROWSER_QUERY = f"cmd package query-activities --brief --query-flags 0x20000 {_BROWSER_INTENT}"
BROWSER_QUERY_PLAIN = f"cmd package query-activities --brief {_BROWSER_INTENT}"
# Link http otwiera też otwieracz linków albo menedżer plików. Przeglądarka deklaruje dodatkowo
# MAIN + CATEGORY_APP_BROWSER (Chrome, Firefox, Samsung Internet, Edge, Opera, Brave, DuckDuckGo, Vivaldi).
_APP_BROWSER_INTENT = "-a android.intent.action.MAIN -c android.intent.category.APP_BROWSER"
APP_BROWSER_QUERY = f"cmd package query-activities --brief --query-flags 0x20000 {_APP_BROWSER_INTENT}"
APP_BROWSER_QUERY_PLAIN = f"cmd package query-activities --brief {_APP_BROWSER_INTENT}"
_WEB_PREFIX = "web:"
_CHROMIUM_SITES_GROUP = "sites"  # grupa kanałów witryn Chromium — jest też przy zerze witryn
_BLOCKED = 0  # NotificationChannel.mImportance: IMPORTANCE_NONE
_RDP_DENY = 2
_RDP_ALLOW = 1


@dataclass(frozen=True)
class SiteEntry:
    origin: str
    host: str
    blocked: bool
    active: bool  # ma teraz powiadomienie na ekranie
    fix: str | None  # id poprawki albo None


@dataclass
class BrowserSites:
    package: str
    name: str
    mode: str  # "per_site" | "shared" | "rdp" | "unknown"
    read: str  # "ok" | "partial" | "unrecognized" | "unsupported"
    sites: list[SiteEntry]
    all_fix: str | None = None  # "site_all:<pkg>" dla shared/partial
    rdp_hint: bool = False  # Firefox bez zdalnego debugowania


@dataclass
class DeviceCheck:
    id: str
    state: str
    browsers: list[BrowserSites] = field(default_factory=list)


def _host(origin: str) -> str:
    return origin.split("://", 1)[-1]


def _step_of(fix: str) -> Step | None:
    """Krok dla identyfikatora poprawki (bez sprawdzania, czy witryna istnieje); None = nie ten kształt."""
    kind, _, rest = fix.partition(":")
    package, _, tail = rest.partition(":")
    if kind == "site" and tail:
        return Step("channel", package, {"channel_id": tail})
    if kind == "site_all" and not tail:
        browser = known_browsers().get(package)
        return Step("channel", package, {"channel_id": browser.shared_channel}) if browser else None
    if kind == "site_perm" and tail:
        return Step("site_permission", package,
                    {"origin": tail, "permission": "desktop-notification", "capability": str(_RDP_DENY)})
    return None


def _offer(fix: str) -> str | None:
    """Poprawka tylko, gdy jej krok przechodzi `check_step`: witryna z dziwnym originem jest na
    liście, ale bez poprawki."""
    step = _step_of(fix)
    if step is None:
        return None
    try:
        check_step(step)
    except ActionError:
        return None
    return fix


def _name(package: str, labels: Mapping[str, str | None]) -> str:
    known = known_browsers().get(package)
    if known:
        return known.name
    return browser_names().get(package) or labels.get(package) or package


def _sorted(sites: list[SiteEntry]) -> list[SiteEntry]:
    return sorted(sites, key=lambda s: (not s.active, s.host, s.origin))


def _per_site(package: str, channels: list[Channel], dump: NotificationDump,
              name: str) -> BrowserSites:
    active = {n.channel for n in dump.active if n.package == package}
    sites = []
    for channel in channels:
        origin = site_origin(channel.id)
        if origin is None:  # kanał „web:” o nieznanym kształcie: pokazujemy, nie poprawiamy
            origin = channel.id[len(_WEB_PREFIX):].rsplit(";", 1)[0]
        blocked = channel.importance == _BLOCKED
        sites.append(SiteEntry(origin, _host(origin), blocked, channel.id in active,
                               None if blocked else _offer(f"site:{package}:{channel.id}")))
    return BrowserSites(package, name, "per_site", "ok", _sorted(sites))


def _active_origin(browser: KnownBrowser, tag: str, sub_text: str | None) -> str | None:
    if browser.origin_from == "tag":
        return tag_origin(tag)
    if sub_text and site_origin(f"{_WEB_PREFIX}https://{sub_text};0"):
        return f"https://{sub_text}"
    return None


def _active_sites(browser: KnownBrowser, dump: NotificationDump) -> dict[str, None]:
    """Witryny z aktywnych powiadomień na wspólnym kanale (kolejność pierwszego wystąpienia)."""
    found: dict[str, None] = {}
    for n in dump.active:
        if n.package == browser.package and n.channel == browser.shared_channel:
            origin = _active_origin(browser, n.tag, n.sub_text)
            if origin:
                found[origin] = None
    return found


def _rdp_sites(perms: Mapping[str, int], active: dict[str, None]) -> list[SiteEntry]:
    sites = []
    for origin, capability in perms.items():
        blocked = capability == _RDP_DENY
        fix = None if blocked or capability != _RDP_ALLOW else _offer(f"site_perm:{FIREFOX}:{origin}")
        sites.append(SiteEntry(origin, _host(origin), blocked, origin in active, fix))
    return _sorted(sites)


def _firefox_rdp(adb: AdbTransport) -> dict[str, int] | None:
    """Zgody z Firefoxa (gniazdo już jest) albo None, gdy zdalne debugowanie nie odpowiada."""
    try:
        return notification_permissions(adb, connect=getattr(adb, "rdp_connect", tcp_connect))
    except (RdpError, AdbError):
        return None


def _shared(adb: AdbTransport, browser: KnownBrowser, dump: NotificationDump) -> BrowserSites | None:
    channels = dump.channels.get(browser.package, [])
    has_socket = False
    if browser.rdp_socket:
        try:
            has_socket = socket_present(adb, browser.rdp_socket)
        except AdbError:
            has_socket = False
    if not channels and not has_socket:
        return None  # przeglądarki nie ma na telefonie
    active = _active_sites(browser, dump)
    if has_socket:
        perms = _firefox_rdp(adb)
        if perms is not None:
            return BrowserSites(browser.package, browser.name, "rdp", "ok", _rdp_sites(perms, active))
    shared = next((c for c in channels if c.id == browser.shared_channel), None)
    if shared is not None and shared.importance == _BLOCKED:  # nic nie przyjdzie: nic do czytania
        return BrowserSites(browser.package, browser.name, "shared", "ok", [],
                            rdp_hint=bool(browser.rdp_socket))
    sites = _sorted([SiteEntry(origin, _host(origin), False, True, None) for origin in active])
    all_fix = _offer(f"site_all:{browser.package}") if shared is not None else None
    return BrowserSites(browser.package, browser.name, "shared", "partial", sites, all_fix,
                        rdp_hint=bool(browser.rdp_socket))


def _state(browsers: list[BrowserSites]) -> str:
    if any(b.read == "unrecognized" for b in browsers):
        return "unrecognized"
    review = any(b.read in ("partial", "unsupported") or any(not s.blocked for s in b.sites) for b in browsers)
    return "review" if review else "ok"


def read_site_notifications(adb: AdbTransport, labels: Mapping[str, str | None] | None = None,
                            ) -> DeviceCheck:
    """Błąd transportu (`AdbError`) leci wyżej; nierozpoznany zrzut to stan „unrecognized”."""
    labels = labels or {}
    try:
        dump = parse_notification_dump(adb.shell(C.NOTIFICATIONS_FULL, timeout=30))
    except UnrecognizedOutput:
        return DeviceCheck(SITE_NOTIFICATIONS, "unrecognized")
    if not dump.channels:  # sekcje AppSettings: brak albo puste: nie wiemy, więc nie „brak witryn”
        return DeviceCheck(SITE_NOTIFICATIONS, "unrecognized")
    browsers: list[BrowserSites] = []
    known = known_browsers()
    for package, channels in dump.channels.items():
        if package not in known and any(c.id.startswith(_WEB_PREFIX) for c in channels):
            web = [c for c in channels if c.id.startswith(_WEB_PREFIX)]
            browsers.append(_per_site(package, web, dump, _name(package, labels)))
    for browser in known.values():
        entry = _shared(adb, browser, dump)
        if entry is not None:
            browsers.append(entry)
    seen = {b.package for b in browsers}
    app_browsers: set[str] | None = None  # pytamy dopiero, gdy jest kandydat do „sprawdź ręcznie”
    for package in sorted(_browser_packages(adb) - seen - known.keys() - without_site_notifications()):
        if not dump.channels.get(package):
            continue  # żadnego kanału: przeglądarka nie wysłała jeszcze żadnego powiadomienia
        if _CHROMIUM_SITES_GROUP in dump.groups.get(package, set()):
            browsers.append(BrowserSites(package, _name(package, labels), "per_site", "ok", []))
            continue
        if app_browsers is None:
            app_browsers = _query(adb, (APP_BROWSER_QUERY, APP_BROWSER_QUERY_PLAIN))
        # Bez dowodu, że to przeglądarka (tabela nazw albo CATEGORY_APP_BROWSER), pakiet tylko otwiera
        # linki — otwieracz linków, menedżer plików — i nie dostaje wiersza „sprawdź ręcznie”.
        if package in browser_names() or package in app_browsers:
            browsers.append(BrowserSites(package, _name(package, labels), "unknown", "unsupported", []))
    return DeviceCheck(SITE_NOTIFICATIONS, _state(browsers), browsers)


def debugging_appeared(adb: AdbTransport, check: DeviceCheck) -> bool:
    """Czy przeglądarka z podpowiedzią zdalnego debugowania ma już jego gniazdo — tani odczyt
    (`/proc/net/unix`) do odpytywania w tle zamiast pełnego zrzutu powiadomień co kilka sekund."""
    known = known_browsers()
    sockets = {name for b in check.browsers if b.rdp_hint and b.package in known
               if (name := known[b.package].rdp_socket)}
    if not sockets:
        return False
    try:
        return any(socket_present(adb, name) for name in sorted(sockets))
    except AdbError:
        return False


def _query(adb: AdbTransport, commands: tuple[str, str]) -> set[str]:
    """Pakiety z `query-activities` (z MATCH_ALL, potem bez); nieznany format albo błąd to pusty zbiór."""
    for command in commands:
        try:
            return query_packages(adb.shell(command)) - {"android"}
        except (AdbError, UnrecognizedOutput):
            continue
    return set()


def _browser_packages(adb: AdbTransport) -> set[str]:
    """Pakiety otwierające dowolny link http; pusty zbiór — wtedy zostaje odczyt z samych kanałów."""
    return _query(adb, (BROWSER_QUERY, BROWSER_QUERY_PLAIN))


def read_device_checks(adb: AdbTransport, labels: Mapping[str, str | None] | None = None,
                       ) -> list[DeviceCheck]:
    """Jak kolektory skanu: błąd odczytu (także utrata telefonu) to brak danych, nie wyjątek."""
    try:
        return [read_site_notifications(adb, labels)]
    except Exception:  # noqa: BLE001 — też AdbError: kolektory notują ją jako brak danych
        return [DeviceCheck(SITE_NOTIFICATIONS, "unrecognized")]


def offered_fixes(checks: list[DeviceCheck]) -> set[str]:
    found: set[str] = set()
    for check in checks:
        for browser in check.browsers:
            if browser.all_fix:
                found.add(browser.all_fix)
            found.update(site.fix for site in browser.sites if site.fix)
    return found


def fix_steps(fix: str, checks: list[DeviceCheck]) -> tuple[str, Step] | None:
    """(pakiet, krok) dla poprawki obecnej w kontroli; None = nieznana (albo zablokowana)."""
    if fix not in offered_fixes(checks):
        return None
    step = _step_of(fix)
    return (step.package, step) if step else None

