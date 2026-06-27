"""Badge-PNGs für FriesenFliegerBummel — server-seitig mit Pillow gezeichnet.

Kein externer Dienst, keine gebündelten Fonts: nutzt Pillows skalierbaren Default-Font
(``ImageFont.load_default(size=...)``, seit Pillow 10). Zwei Varianten:
  - ``render_winner_badge`` — großes Sieger-Badge „Absoluter Durchschnitt!".
  - ``render_medal``        — kleine Teilnahme-Medaille „Voll daneben!".
Beide tragen die Fußzeile „friesenflieger.de".
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

# FriesenSpy-Farbwelt
_BG = (7, 21, 37)
_ACCENT = (45, 156, 219)
_GOLD = (255, 210, 74)
_TEXT = (224, 232, 240)
_DIM = (138, 160, 184)
_BRAND = "friesenflieger.de"


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


def _fit_font(draw, text, max_w, start_size, min_size=12):
    """Größte Font-Größe ≤ start_size, bei der text in max_w passt."""
    size = start_size
    while size > min_size and _text_w(draw, text, _font(size)) > max_w:
        size -= 2
    return _font(size)


def _footer(draw, w, h):
    f = _font(13)
    tw = _text_w(draw, _BRAND, f)
    draw.text((w - tw - 12, h - 24), _BRAND, font=f, fill=_ACCENT)


def _png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_winner_badge(d: dict) -> bytes:
    W, H, pad = 640, 240, 24
    img = Image.new("RGB", (W, H), _BG)
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 0, W - 1, H - 1], outline=_ACCENT, width=2)
    dr.rectangle([0, 0, W, 6], fill=_GOLD)  # Gold-Akzent oben

    dr.text((pad, 18), f"FRIESENFLIEGERBUMMEL · {d.get('date', '')}", font=_font(15), fill=_DIM)

    head = _fit_font(dr, "ABSOLUTER DURCHSCHNITT!", W - 2 * pad, 34)
    dr.text((pad, 44), "ABSOLUTER DURCHSCHNITT!", font=head, fill=_GOLD)

    dr.text((pad, 96), d.get("callsign", ""), font=_font(46), fill=_TEXT)
    if d.get("name"):
        dr.text((pad, 150), d["name"], font=_font(20), fill=_DIM)

    delta = d.get("delta")
    diff = "punktgenau am Schnitt" if delta in (0, 0.0) else f"±{_fmt_min(delta)} zum Schnitt"
    line = f"{d.get('aircraft', '—')}   ·   {_fmt_min(d.get('total_min'))}   ·   {diff}"
    dr.text((pad, 192), line, font=_font(18), fill=_ACCENT)

    _footer(dr, W, H)
    return _png(img)


def render_medal(d: dict) -> bytes:
    W, H, pad = 380, 150, 16
    img = Image.new("RGB", (W, H), _BG)
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 0, W - 1, H - 1], outline=_ACCENT, width=2)
    dr.rectangle([0, 0, W, 5], fill=_ACCENT)

    dr.text((pad, 12), "FRIESENFLIEGERBUMMEL", font=_font(12), fill=_DIM)
    dr.text((pad, 30), "VOLL DANEBEN!", font=_font(26), fill=_ACCENT)
    dr.text((pad, 66), d.get("callsign", ""), font=_font(26), fill=_TEXT)
    if d.get("name"):
        dr.text((pad, 98), d["name"], font=_font(14), fill=_DIM)

    if d.get("complete") and d.get("delta") is not None:
        res = "punktgenau" if d["delta"] in (0, 0.0) else f"±{_fmt_min(d['delta'])} zum Schnitt"
    else:
        res = "dabei gewesen"
    dr.text((pad, 120), f"{d.get('aircraft', '—')} · {d.get('date', '')} · {res}",
            font=_font(12), fill=_DIM)

    _footer(dr, W, H)
    return _png(img)
