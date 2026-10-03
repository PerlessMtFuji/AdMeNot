"""Ikona AdMeNot: PNG i ICO z wzorców w assets/icon/ (spec 2026-10-03 §3.3).

Użycie: python scripts/build_icons.py — po każdej zmianie SVG. Wyniki są w repozytorium.
Wymaga `npm ci` w ui/ (renderer @resvg/resvg-js).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "assets" / "icon"
OUT = ROOT / "src" / "admenot" / "assets" / "icon"
UI_COPY = ROOT / "ui" / "src" / "assets" / "admenot.svg"
PNG_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
SMALL_MAX = 24  # do tego rozmiaru uproszczony rysunek — pełny zlewa się w plamę


def source_for(size: int) -> Path:
    return SOURCES / ("admenot-small.svg" if size <= SMALL_MAX else "admenot.svg")


def render(svg: Path, size: int, out: Path) -> None:
    subprocess.run(["node", "scripts/render-icon.mjs", str(svg), str(size), str(out)],
                   cwd=ROOT / "ui", check=True)


def build_ico(pngs: dict[int, Path], out: Path) -> None:
    # Każda klatka z własnego PNG; Pillow bierze obraz z append_images zamiast skalować największy.
    images = [Image.open(pngs[size]).convert("RGBA") for size in ICO_SIZES]
    largest = images[-1]
    largest.save(out, format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pngs = {}
    for size in PNG_SIZES:
        pngs[size] = OUT / f"admenot-{size}.png"
        render(source_for(size), size, pngs[size])
    build_ico(pngs, OUT / "admenot.ico")
    UI_COPY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCES / "admenot.svg", UI_COPY)
    print(f"Ikona: {OUT}")


if __name__ == "__main__":
    main()
