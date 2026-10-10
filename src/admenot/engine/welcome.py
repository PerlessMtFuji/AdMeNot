"""Ostrzeżenie o ryzyku przy pierwszym uruchomieniu (spec kroku H §3, §9).

Podniesienie `WELCOME_VERSION` pokazuje ostrzeżenie ponownie wszystkim (GUI i CLI).
Tekst dla GUI jest w `ui/src/lib/i18n` (`welcome.risk*`); `RISK_LINES` to ta sama treść dla CLI.
"""

from __future__ import annotations

from datetime import UTC, datetime

from admenot.engine.settings import Settings, save_internal

WELCOME_VERSION = 1

RISK_LINES = {
    "pl": (
        "AdMeNot jest w wersji beta i może zawierać błędy.",
        ("Program wyłącza i usuwa aplikacje na telefonie klienta. Decyzja o każdej zmianie należy "
         "do serwisanta, który odpowiada za nią przed klientem."),
        "Większość zmian da się cofnąć w Historii; usunięcia aplikacji bez kopii APK nie zawsze.",
        "Przed naprawą zrób kopię ważnych danych klienta.",
        "Program jest udostępniany „tak jak jest”, bez żadnej gwarancji (licencja PolyForm Shield 1.0.0).",
    ),
    "en": (
        "AdMeNot is a beta and may contain bugs.",
        ("The program disables and removes apps on the customer's phone. Every change is the "
         "technician's decision, and the technician answers for it to the customer."),
        "Most changes can be undone in History; removing an app without an APK copy cannot always be undone.",
        "Back up the customer's important data before a repair.",
        "The program is provided “as is”, without any warranty (PolyForm Shield 1.0.0 license).",
    ),
}


def welcome_needed(settings: Settings) -> bool:
    return settings.welcome_version is None or settings.welcome_version < WELCOME_VERSION


def utc_stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def accept_risk(now: datetime) -> Settings:
    return save_internal({"welcome_version": WELCOME_VERSION, "welcome_at": utc_stamp(now)})
