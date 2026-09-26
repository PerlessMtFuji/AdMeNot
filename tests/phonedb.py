"""Mała baza telefonów do testów: rekordy w formacie Szklodo, atrapy zdjęć i wycinek listy Google."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from demalware.engine.device.info import DeviceInfo
from demalware.engine.phones.build import build_phone_db
from demalware.engine.phones.names import record_slugs

GSM = "https://www.gsmarena.com/"

RECORDS = [
    {"name": "Samsung Galaxy A14", "manufacturer": "Samsung",
     "url": GSM + "samsung_galaxy_a14-12151.php",
     "models": "SM-A145F, SM-A145F/DSN, SM-A145M, SM-A145P, SM-A145R",
     "year": "2023, February 28",
     "displaysize": "6.6 inches, 104.9 cm2 (~83.9% screen-to-body ratio)",
     "batdescription1": "Li-Po 5000 mAh, non-removable"},
    {"name": "Samsung Galaxy A14 5G", "manufacturer": "Samsung",
     "url": GSM + "samsung_galaxy_a14_5g-12004.php",
     "models": "SM-A146B, SM-A146B/DS, SM-A146P", "year": "2023, January 04"},
    {"name": "Samsung Galaxy A57", "manufacturer": "Samsung",
     "url": GSM + "samsung_galaxy_a57_5g-14379.php",
     "models": "‎SM-A576B, SM-A576B/DS", "year": "2026, March 25"},
    {"name": "Samsung Galaxy S25+", "manufacturer": "Samsung",
     "url": GSM + "samsung_galaxy_s25+-13609.php",
     "models": "SM-S936B, SM-S936B/DS", "year": "2025, January 22"},
    {"name": "Samsung Galaxy M31", "manufacturer": "Samsung",
     "url": GSM + "samsung_galaxy_m31-10025.php", "models": "SM-M315F",
     "year": "2020, February 25"},
    {"name": "Samsung Galaxy M31 Prime", "manufacturer": "Samsung",
     "url": GSM + "samsung_galaxy_m31_prime-10490.php", "models": "SM-M315F, &, 1050;100",
     "year": "2020, October 17"},
    {"name": "Xiaomi Redmi Note 13", "manufacturer": "Xiaomi",
     "url": GSM + "xiaomi_redmi_note_13-12776.php", "year": "2024, January 15"},
    {"name": "Google Pixel 7", "manufacturer": "Google",
     "url": GSM + "google_pixel_7-11903.php", "models": "GVU6C, GQML3, GO3Z5",
     "year": "2022, October 13"},
    {"name": "Huawei nova 8", "manufacturer": "Huawei",
     "url": GSM + "huawei_nova_8-10687.php", "year": "2020, December 23"},
    {"name": "Oppo Reno6 Pro 5G (Snapdragon)", "manufacturer": "OPPO",
     "url": GSM + "oppo_reno6_pro_5g_(snapdragon)-11093.php", "models": "CPH2247",
     "year": "2021, September 09"},
    {"name": "", "manufacturer": "Nokia", "url": GSM + "nokia_x-1.php"},
]
NO_PHOTO = {"google-pixel-7"}

GPLAY_CSV = (
    "Retail Branding,Marketing Name,Device,Model\r\n"
    "Samsung,Galaxy A14,a14m,SM-A145R\r\n"
    "Samsung,Galaxy A14 LTE,a14lte,SM-A145X\r\n"
    "Samsung,Galaxy A57 5G,a57x,SM-A576E\r\n"
    "Redmi,Redmi Note 13,sapphire,23129RAA4G\r\n"
    "Google,Pixel 7,panther,Pixel 7\r\n"
    "Oppo,CPH2271,OP4F97,CPH2271\r\n"
    "Huawei,华为畅享8,HWFLA-H,FLA-AL00\r\n"
)


def write_sources(root: Path) -> tuple[Path, Path]:
    """Układ katalogów jak w Szklodo; zwraca (katalog zdjęć, CSV Google w UTF-16)."""
    images = root / "public" / "assets" / "phones"
    images.mkdir(parents=True)
    for slug in record_slugs(RECORDS):
        if slug and slug not in NO_PHOTO:
            (images / f"{slug}.webp").write_bytes(b"RIFF\0\0\0\0WEBP" + slug.encode())
            (images / f"{slug}-sm.webp").write_bytes(b"small")
    (root / "data").mkdir()
    (root / "data" / "phones_full_data.json").write_text(
        json.dumps(RECORDS, ensure_ascii=False), "utf-8")
    gplay = root / "supported_devices.csv"
    gplay.write_bytes(GPLAY_CSV.encode("utf-16"))
    return images, gplay


def make_phone_assets(root: Path) -> Path:
    images, gplay = write_sources(root / "szklodo")
    assets = root / "assets"
    build_phone_db(RECORDS, images, gplay, assets)
    return assets


def make_device(model: str, brand: str = "samsung", manufacturer: str = "samsung",
                device: str = "unknown", market_name: str | None = None) -> DeviceInfo:
    return DeviceInfo(
        serial="S1", brand=brand, manufacturer=manufacturer, model=model, device=device,
        market_name=market_name, android_release="14", sdk=34, security_patch=None,
        uptime_s=3600.0, local_now=datetime(2026, 9, 26, 14, 0, 0),
    )
