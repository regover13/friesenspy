"""Runde Badge-PNGs für FriesenFliegerBummel — Text per Pillow auf FF-Hintergründe.

Hintergründe (rund, FriesenFlieger-Markenoptik) liegen unter
``app/static/badge/`` (``winner_bg.png`` / ``medal_bg.png``); der Text wird
zentriert in die ruhigen Zonen gelegt. Strikt die FriesenFlieger-Palette
(``Hex codes.txt`` aus dem Repaint Kit). Zwei Varianten:
  - ``render_winner_badge`` — Sieger „Absoluter Durchschnitt!" (helle Kuppel, dunkle Schrift).
  - ``render_medal``        — Teilnahme „Voll daneben!" (navy Kern, helle Schrift).
Beide tragen die Fußzeile „friesenflieger.de".

Fehlt ein Hintergrund-PNG, wird auf eine schlichte gezeichnete Scheibe
zurückgefallen (Tests/lokal ohne Assets bleiben grün).
"""
from __future__ import annotations

import os
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFont

# FriesenFlieger-Palette (Hex codes.txt)
_NAVY = (25, 29, 83)      # 191D53 dunkelblau
_LBLUE = (143, 191, 241)  # 8FBFF1 hellblau
_RED = (138, 27, 27)      # 8A1B1B rot
_ORANGE = (215, 95, 40)   # D75F28 orange
_WHITE = (238, 244, 253)

_BRAND = "friesenflieger.de"

_OUT = 256          # Ausgabe-Durchmesser (px)
_S = 512            # Arbeits-/Render-Auflösung (Supersampling → AA beim Verkleinern)
_BG_DIR = os.path.join(os.path.dirname(__file__), "static", "badge")


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def _fmt_min(m) -> str:
    if m is None:
        return "—"
    m = int(round(m))
    h, mm = divmod(m, 60)
    return f"{h}h {mm:02d}m" if h else f"{mm}m"


def _text_w(draw, text, font) -> int:
    l, _, r, _ = draw.textbbox((0, 0), text, font=font)
    return r - l


def _fit_font(draw, text, max_w, start_size, min_size=10):
    """Größte Font ≤ start_size, bei der text in max_w passt."""
    size = start_size
    while size > min_size and _text_w(draw, text, _font(size)) > max_w:
        size -= 2
    return _font(size)


def _ctext(draw, y, text, size, fill, max_w_frac=0.78):
    """Horizontal zentrierten Text (auf _S-Canvas) bei Oberkante y zeichnen."""
    if not text:
        return
    font = _fit_font(draw, text, int(_S * max_w_frac), size)
    w = _text_w(draw, text, font)
    draw.text(((_S - w) / 2, y), text, font=font, fill=fill)


def _load_bg(name: str) -> Image.Image | None:
    path = os.path.join(_BG_DIR, name)
    if not os.path.exists(path):
        return None
    return Image.open(path).convert("RGBA").resize((_S, _S), Image.LANCZOS)


def _fallback_disk(center_fill) -> Image.Image:
    """Schlichte runde Scheibe, falls kein Hintergrund-Asset vorhanden ist."""
    img = Image.new("RGBA", (_S, _S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.ellipse([4, 4, _S - 5, _S - 5], fill=center_fill, outline=_NAVY, width=10)
    dr.ellipse([26, 26, _S - 27, _S - 27], outline=_ORANGE, width=4)
    return img


def _circle_mask() -> Image.Image:
    """Antialiased Kreis-Maske (für saubere runde Kante)."""
    big = Image.new("L", (_S * 4, _S * 4), 0)
    ImageDraw.Draw(big).ellipse([0, 0, _S * 4 - 1, _S * 4 - 1], fill=255)
    return big.resize((_S, _S), Image.LANCZOS)


def _finish(img: Image.Image) -> bytes:
    # runde Kante erzwingen + auf Ausgabegröße verkleinern
    img.putalpha(ImageChops.multiply(img.getchannel("A"), _circle_mask()))
    img = img.resize((_OUT, _OUT), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _footer(dr, fill):
    f = _font(20)
    w = _text_w(dr, _BRAND, f)
    dr.text(((_S - w) / 2, int(_S * 0.86)), _BRAND, font=f, fill=fill)


def render_winner_badge(d: dict) -> bytes:
    """Sieger-Badge: helle Kuppel, dunkle Schrift (Navy/Rot)."""
    img = _load_bg("winner_bg.png") or _fallback_disk(_LBLUE)
    dr = ImageDraw.Draw(img)

    # Slogan zweizeilig — Kuppel ist oben schmal
    _ctext(dr, int(_S * 0.220), "ABSOLUTER", 32, _RED, 0.42)
    _ctext(dr, int(_S * 0.295), "DURCHSCHNITT!", 32, _RED, 0.58)

    _ctext(dr, int(_S * 0.405), d.get("callsign", ""), 64, _NAVY, 0.70)
    if d.get("name"):
        _ctext(dr, int(_S * 0.530), d["name"], 24, _RED, 0.70)

    delta = d.get("delta")
    diff = "punktgenau" if delta in (0, 0.0) else f"±{_fmt_min(delta)} zum Schnitt"
    info = f"{d.get('aircraft', '—')} · {_fmt_min(d.get('total_min'))} · {diff}"
    _ctext(dr, int(_S * 0.600), info, 20, _NAVY, 0.66)

    _footer(dr, _LBLUE)
    return _finish(img)


def render_medal(d: dict) -> bytes:
    """Teilnahme-Medaille: navy Kern, helle Schrift (Hellblau/Orange)."""
    img = _load_bg("medal_bg.png") or _fallback_disk(_NAVY)
    dr = ImageDraw.Draw(img)

    _ctext(dr, int(_S * 0.235), "VOLL DANEBEN!", 34, _ORANGE, 0.78)
    _ctext(dr, int(_S * 0.330), d.get("callsign", ""), 60, _LBLUE, 0.72)
    if d.get("name"):
        _ctext(dr, int(_S * 0.460), d["name"], 24, _WHITE, 0.74)

    if d.get("complete") and d.get("delta") is not None:
        res = "punktgenau" if d["delta"] in (0, 0.0) else f"±{_fmt_min(d['delta'])} zum Schnitt"
    else:
        res = "dabei gewesen"
    _ctext(dr, int(_S * 0.545), f"{d.get('aircraft', '—')} · {d.get('date', '')}", 22, _LBLUE, 0.80)
    _ctext(dr, int(_S * 0.600), res, 22, _LBLUE, 0.80)

    _footer(dr, _LBLUE)
    return _finish(img)
