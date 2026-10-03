"""CLI `device`: rozpoznany model, zdjęcie i ręczny wybór zdjęcia (spec §4)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable

from admenot.engine.adb.transport import AdbTransport
from admenot.engine.device.info import DeviceInfo, read_device_info
from admenot.engine.phones.provider import PhoneImageProvider, PhoneMatch

MESSAGES = {
    "pl": {
        "confidence": {"manual": "wybrane ręcznie", "exact": "dokładne",
                       "approximate": "przybliżone (~ podobny model)", "none": "brak (sylwetka)"},
        "step": {"override": "zdjęcie wskazane dla {matched}", "model_code": "kod modelu {matched}",
                 "market_name": "nazwa handlowa „{matched}”",
                 "gplay": "lista urządzeń Google „{matched}”", "fuzzy": "podobna nazwa „{matched}”",
                 "silhouette": "model nierozpoznany", "no_db": "brak bazy telefonów"},
        "match": "Dopasowanie: {confidence}, {step}",
        "photo": "Zdjęcie: {path}",
        "silhouette": "Sylwetka: {path}",
        "phone": "Telefon: {brand} {model} · {device} · Android {release} (SDK {sdk}) · "
                 "poprawka {patch} · uptime {uptime:.1f} h · SN {serial}",
        "no_db": "Baza telefonów nie jest zbudowana. Uruchom: python scripts/build_phone_db.py",
        "unknown_slug": "Nie ma w bazie telefonu „{slug}”. Znajdź nazwę: "
                        "admenot device --search <tekst>",
        "no_model": "Telefon nie podaje kodu modelu (ro.product.model), nie da się zapisać wyboru.",
        "saved": "Zapisano zdjęcie dla {model}: {slug}",
        "cleared": "Usunięto ręczny wybór zdjęcia dla {model}.",
        "not_set": "Dla {model} nie było ręcznego wyboru zdjęcia.",
        "no_results": "Brak telefonów pasujących do „{text}”.",
    },
    "en": {
        "confidence": {"manual": "chosen manually", "exact": "exact",
                       "approximate": "approximate (~ similar model)", "none": "none (silhouette)"},
        "step": {"override": "photo chosen for {matched}", "model_code": "model code {matched}",
                 "market_name": "marketing name “{matched}”",
                 "gplay": "Google device list “{matched}”", "fuzzy": "similar name “{matched}”",
                 "silhouette": "model not recognized", "no_db": "no phone database"},
        "match": "Match: {confidence}, {step}",
        "photo": "Photo: {path}",
        "silhouette": "Silhouette: {path}",
        "phone": "Phone: {brand} {model} · {device} · Android {release} (SDK {sdk}) · "
                 "patch {patch} · uptime {uptime:.1f} h · SN {serial}",
        "no_db": "The phone database is not built. Run: python scripts/build_phone_db.py",
        "unknown_slug": "No phone “{slug}” in the database. Find it: "
                        "admenot device --search <text>",
        "no_model": "The phone reports no model code (ro.product.model); cannot save the choice.",
        "saved": "Saved photo for {model}: {slug}",
        "cleared": "Removed the manual photo choice for {model}.",
        "not_set": "There was no manual photo choice for {model}.",
        "no_results": "No phones match “{text}”.",
    },
}

DEVICE_FIELDS = ("serial", "brand", "manufacturer", "model", "device", "market_name",
                 "android_release", "sdk", "security_patch", "uptime_s")

PickDevice = Callable[[AdbTransport, str | None, str], str]


def cmd_device(args: argparse.Namespace, host: AdbTransport, lang: str,
               pick_device: PickDevice) -> int:
    m = MESSAGES[lang]
    provider = PhoneImageProvider.default()
    needs_db = args.search is not None or args.set_photo or args.clear_photo
    if needs_db and not provider.available:
        print(m["no_db"], file=sys.stderr)
        return 2
    if args.search is not None:
        return _search(provider, args.search, lang)
    serial = pick_device(host, args.serial, lang)
    args.picked_serial = serial
    info = read_device_info(host.with_serial(serial))
    out = sys.stderr if args.json else sys.stdout  # potwierdzenia nie psują JSON-a
    if args.set_photo:
        try:
            provider.set_override(info.model, args.set_photo)
        except KeyError:
            print(m["unknown_slug"].format(slug=args.set_photo), file=sys.stderr)
            return 2
        except ValueError:
            print(m["no_model"], file=sys.stderr)
            return 2
        print(m["saved"].format(model=info.model, slug=args.set_photo), file=out)
    elif args.clear_photo:
        key = "cleared" if provider.clear_override(info.model) else "not_set"
        print(m[key].format(model=info.model), file=out)
    match = provider.match(info)
    if args.json:
        data = {"device": {k: getattr(info, k) for k in DEVICE_FIELDS}, "match": match.to_dict()}
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        _print_match(info, match, lang)
    return 0


def _search(provider: PhoneImageProvider, text: str, lang: str) -> int:
    results = provider.search(text, limit=20)
    if not results:
        print(MESSAGES[lang]["no_results"].format(text=text))
    for r in results:
        print(f"{r.slug}\t{r.name}" + (f" ({r.year})" if r.year else ""))
    return 0


def _print_match(info: DeviceInfo, match: PhoneMatch, lang: str) -> None:
    m = MESSAGES[lang]
    if match.phone:
        prefix = "~ " if match.confidence == "approximate" else ""
        year = f" ({match.phone.year})" if match.phone.year else ""
        print(f"{prefix}{match.phone.name}{year}")
    else:
        print(info.market_name or f"{info.brand} {info.model}".strip())
    step = m["step"][match.step].format(matched=match.matched or "")
    print(m["match"].format(confidence=m["confidence"][match.confidence], step=step))
    print(m["photo" if match.has_photo else "silhouette"].format(path=match.image))
    print(m["phone"].format(
        brand=info.brand, model=info.model, device=info.device, release=info.android_release,
        sdk=info.sdk, patch=info.security_patch or "?", uptime=info.uptime_s / 3600,
        serial=info.serial))
    if match.step == "no_db":
        print(m["no_db"])
