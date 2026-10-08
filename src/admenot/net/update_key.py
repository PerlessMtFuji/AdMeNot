"""Klucze publiczne podpisu manifestu aktualizacji (spec aktualizacji §2.3).

Podpis jest ważny, gdy pasuje do któregokolwiek klucza — nowa wersja programu może dodać nowy
klucz, zanim stary zostanie wycofany. Pusta krotka: każdy manifest jest odrzucany.
Klucz dopisuje `python scripts/publish_update.py keygen` (base64 surowych 32 bajtów).
"""

PUBLIC_KEYS: tuple[str, ...] = ()
