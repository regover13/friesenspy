"""Erzeugt die PWA-Icons für FriesenSpy (passend zum dunklen Radar-Look der SPA).

Einmalig bzw. bei Design-Änderung ausführen:  python generate_icons.py
Schreibt PNGs nach app/static/. Benötigt Pillow.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join("app", "static")

BG = (7, 21, 37)          # --bg-panel  #071525
RING = (45, 156, 219)     # --green     #2d9cdb (das Teal-Blau der App)
TEXT = (212, 232, 245)    # --text-bright #d4e8f5

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _draw(size: int, *, safe: float = 1.0) -> Image.Image:
    """Quadratisches Icon. safe < 1.0 hält den Inhalt für maskable in der Schutzzone."""
    img = Image.new("RGB", (size, size), BG)
    d = ImageDraw.Draw(img)
    cx = cy = size / 2
    r = size * 0.40 * safe

    # Radar-Ring
    lw = max(2, int(size * 0.025))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=RING, width=lw)
    # Fadenkreuz-Linie (dezent)
    d.line([cx - r, cy, cx + r, cy], fill=(45, 156, 219), width=max(1, lw // 2))

    # "FRS" zentriert
    font = _font(int(size * 0.30 * safe))
    text = "FRS"
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text((cx - tw / 2 - box[0], cy - th / 2 - box[1]), text, font=font, fill=TEXT)
    return img


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    _draw(192).save(os.path.join(OUT_DIR, "icon-192.png"))
    _draw(512).save(os.path.join(OUT_DIR, "icon-512.png"))
    # Maskable: Inhalt in der ~80%-Schutzzone, voller dunkler Hintergrund
    _draw(512, safe=0.72).save(os.path.join(OUT_DIR, "icon-maskable-512.png"))
    # Apple-Touch-Icon (iOS, 180px, ohne Transparenz)
    _draw(180).save(os.path.join(OUT_DIR, "apple-touch-icon.png"))
    print("Icons geschrieben nach", OUT_DIR)


if __name__ == "__main__":
    main()
