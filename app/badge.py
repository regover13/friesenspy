"""Runde Badge-PNGs für FriesenFliegerBummel + FriesenKutter — Text per Pillow auf FF-Hintergründe.

Hintergründe (rund, FriesenFlieger-Markenoptik) liegen unter
``app/static/badge/`` (``winner_bg.png`` / ``medal_bg.png``); der Text wird
zentriert in die ruhigen Zonen gelegt. Strikt die FriesenFlieger-Palette
(``Hex codes.txt`` aus dem Repaint Kit). Varianten:
  - ``render_winner_badge`` — Bummel-Sieger „Absoluter Durchschnitt!" (helle Kuppel, dunkle Schrift).
  - ``render_medal``        — Bummel-Teilnahme „Voll daneben!" (navy Kern, helle Schrift).
  - ``render_kutter_badge`` — Kutter-Abschluss „Voll beladen!" (navy Kern), mit Verlust-Abschnitt
    (SPITZBOOV!/BADEMESTER!/SEEROVER!), falls Fracht geklaut oder versenkt wurde.
Alle tragen die Fußzeile „friesenflieger.de".

Fehlt ein Hintergrund-PNG, wird auf eine schlichte gezeichnete Scheibe
zurückgefallen (Tests/lokal ohne Assets bleiben grün).
"""
from __future__ import annotations

import os
import unicodedata
from io import BytesIO

from PIL import Image, ImageChops, ImageDraw, ImageFont

# Der eingebettete Pillow-Default-Font kann keine Umlaute/diakritischen Zeichen (→ leeres
# Kästchen). Deshalb VOR dem Zeichnen nach ASCII falten: deutsche Umlaute ausschreiben,
# übrige Diakritika (é, ñ …) auf den Grundbuchstaben reduzieren, Rest-Non-ASCII fällt weg.
_UMLAUT = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
})


def _ascii(text: str) -> str:
    if not text:
        return ""
    text = text.translate(_UMLAUT)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")

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
    text = _ascii(text)
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


def _fmt_signed_delta(sec) -> str:
    """Signierter, sekundengenauer Abstand zum Schnitt: '+1:23 zum Schnitt' / 'punktgenau'.

    ASCII-Minus ('-'), weil der eingebettete Pillow-Default-Font typografische Sonderzeichen
    (U+2212 −, U+2014 —) als leeres Kästchen rendert.
    """
    if sec is None:
        return ""
    if sec == 0:
        return "punktgenau"
    a = abs(int(sec))
    return f"{'+' if sec > 0 else '-'}{a // 60}:{a % 60:02d} zum Schnitt"


def _event_caption(dr, d, fill):
    """Event-Name (Überschrift) + Datum als Bildunterschrift unterhalb der Inselkette."""
    ev = d.get("event") or ""
    if ev:
        _ctext(dr, int(_S * 0.750), ev, 20, fill, 0.82)
    date = d.get("date") or ""
    if date:
        _ctext(dr, int(_S * 0.805), date, 16, fill, 0.70)


def render_winner_badge(d: dict) -> bytes:
    """Sieger-Badge: helle Kuppel, dunkle Schrift (Navy/Rot)."""
    img = _load_bg("winner_bg.png") or _fallback_disk(_LBLUE)
    dr = ImageDraw.Draw(img)

    # Slogan zweizeilig — Kuppel ist oben schmal
    _ctext(dr, int(_S * 0.220), "ABSOLUTER", 32, _RED, 0.42)
    _ctext(dr, int(_S * 0.295), "DURCHSCHNITT!", 32, _RED, 0.58)

    _ctext(dr, int(_S * 0.400), d.get("callsign", ""), 60, _NAVY, 0.70)
    if d.get("name"):
        _ctext(dr, int(_S * 0.510), d["name"], 24, _RED, 0.70)

    diff = _fmt_signed_delta(d.get("delta_sec"))
    info = f"{d.get('aircraft') or 'k. A.'} · {_fmt_min(d.get('total_min'))} · {diff}"
    _ctext(dr, int(_S * 0.585), info, 19, _NAVY, 0.70)

    _event_caption(dr, d, _LBLUE)
    _footer(dr, _LBLUE)
    return _finish(img)


def _wrap_two(dr, text: str, font_size: int, max_w: int) -> list[str]:
    """Teilt ``text`` in höchstens zwei möglichst ausgewogene Zeilen, falls einzeilig zu breit.

    Passt der Text in ``max_w``, bleibt es eine Zeile. Sonst wird an der Wortgrenze umbrochen,
    die die längere der beiden Zeilen minimiert (ein einzelnes langes Wort bleibt ungeteilt —
    ``_ctext`` verkleinert es dann).
    """
    text = _ascii(text)
    if not text:
        return []
    if _text_w(dr, text, _font(font_size)) <= max_w:
        return [text]
    words = text.split()
    if len(words) <= 1:
        return [text]
    best_i, best_max = 1, None
    for i in range(1, len(words)):
        w = max(
            _text_w(dr, " ".join(words[:i]), _font(font_size)),
            _text_w(dr, " ".join(words[i:]), _font(font_size)),
        )
        if best_max is None or w < best_max:
            best_max, best_i = w, i
    return [" ".join(words[:best_i]), " ".join(words[best_i:])]


def _kutter_event_heading(dr, d, fill, center: float, size: int):
    """Event-Name als große Überschrift ÜBER der Inselkette (bis zu zwei Zeilen), Datum darunter.

    Der Zeilenblock wird vertikal um ``center`` (Anteil an ``_S``) zentriert; ``size`` ist die
    Schriftgröße der Überschrift.
    """
    ev = d.get("event") or ""
    lines = _wrap_two(dr, ev, size, int(_S * 0.82))
    lh = (size + 6) / _S  # Zeilenhöhe als _S-Anteil
    top = center - (len(lines) * lh) / 2
    for i, ln in enumerate(lines):
        _ctext(dr, int(_S * (top + i * lh)), ln, size, fill, 0.86)
    date = d.get("date") or ""
    if date:
        _ctext(dr, int(_S * 0.775), date, 16, fill, 0.70)


def _kutter_loss_label(stolen_kg: float, sunk_kg: float) -> str | None:
    """Wählt den Verlust-Titel für den Kutter-Badge — pure Funktion, direkt testbar.

    Beide 0 → kein Verlust (None). Nur geklaut → SPITZBOOV!, nur versenkt → BADEMESTER!,
    beides → SEEROVER!.
    """
    if stolen_kg > 0 and sunk_kg > 0:
        return "SEEROVER!"
    if stolen_kg > 0:
        return "SPITZBOOV!"
    if sunk_kg > 0:
        return "BADEMESTER!"
    return None


def render_kutter_badge(d: dict) -> bytes:
    """Kutter-Abschluss-Badge (FriesenKutter-Transportevent) — navy Kern wie ``render_medal``,
    zusätzlich ein Verlust-Abschnitt (geklaut/versenkt), falls die Fracht nicht ankam."""
    img = _load_bg("medal_bg.png") or _fallback_disk(_NAVY)
    dr = ImageDraw.Draw(img)

    _ctext(dr, int(_S * 0.200), "VOLL BELADEN!", 32, _ORANGE, 0.78)
    _ctext(dr, int(_S * 0.305), d.get("callsign", ""), 56, _LBLUE, 0.72)
    # Typcode direkt unter dem Callsign (Name + kg entfallen bewusst).
    _ctext(dr, int(_S * 0.415), d.get("aircraft") or "k. A.", 24, _LBLUE, 0.80)

    stolen_kg = d.get("stolen_kg") or 0
    sunk_kg = d.get("sunk_kg") or 0
    label = _kutter_loss_label(stolen_kg, sunk_kg)
    if label:
        _ctext(dr, int(_S * 0.490), label, 22, _ORANGE, 0.78)
        pieces = []
        if stolen_kg > 0:
            pieces.append(f"{int(round(stolen_kg))} kg geklaut")
        if sunk_kg > 0:
            pieces.append(f"{int(round(sunk_kg))} kg versenkt")
        _ctext(dr, int(_S * 0.540), ", ".join(pieces), 16, _WHITE, 0.85)
        ev_center, ev_size = 0.618, 24
    else:
        ev_center, ev_size = 0.555, 30

    # Event-Name als große Überschrift über die Inselkette.
    _kutter_event_heading(dr, d, _LBLUE, ev_center, ev_size)
    _footer(dr, _LBLUE)
    return _finish(img)


def render_medal(d: dict) -> bytes:
    """Teilnahme-Medaille: navy Kern, helle Schrift (Hellblau/Orange)."""
    img = _load_bg("medal_bg.png") or _fallback_disk(_NAVY)
    dr = ImageDraw.Draw(img)

    _ctext(dr, int(_S * 0.215), "VOLL DANEBEN!", 34, _ORANGE, 0.78)
    _ctext(dr, int(_S * 0.310), d.get("callsign", ""), 58, _LBLUE, 0.72)
    if d.get("name"):
        _ctext(dr, int(_S * 0.430), d["name"], 24, _WHITE, 0.74)

    if d.get("complete") and d.get("delta_sec") is not None:
        res = _fmt_signed_delta(d["delta_sec"])
    else:
        res = "dabei gewesen"
    _ctext(dr, int(_S * 0.520), d.get("aircraft") or "k. A.", 22, _LBLUE, 0.80)
    _ctext(dr, int(_S * 0.585), res, 20, _LBLUE, 0.80)

    _event_caption(dr, d, _LBLUE)
    _footer(dr, _LBLUE)
    return _finish(img)
