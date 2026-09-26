"""Wem gehört diese FriesenBrügge? Der Weg ab Protokoll 3 (#46, 26.09.2026).

Beschluss: ``docs/superpowers/specs/2026-09-26-bruegge-kennung-und-zuordnung-design.md``.
Jede Regel unten nennt ihre These.

**Die Kennung benennt die Installation, nicht den Piloten.** Die neue MSFS-Brügge speichert sie
in ``\\work``, die X-Plane-Brügge schon immer. Welche CID dazugehört, steht nur auf dem Server
(``bruegge_zuordnung``). Eine Fehlzuordnung ist damit eine falsche Zeile hier, nie eine geteilte
Kennung.

**Zuordnung und Bewährung sind zwei Dinge.** Zugeordnet wird so früh wie möglich, im Stand nach
dem Login. Bewährt wird im Flug. Eine unbewährte Bindung weicht einem Widerspruch, eine bewährte
nicht.

Die alte MSFS-Brügge (Protokoll 2) läuft bis zum Stichtag über ``main._bruegge_zuordnen``. Dieses
Modul fasst sie nicht an.

**Zustand im Speicher, nicht in der Datenbank:** Sitzungen, Gleichstände, laufende Bewährungen.
Eine unbundene Kennung steht nie in ``bruegge_zuordnung`` -- per Skript ließen sich sonst beliebig
viele Zeilen anlegen. Ein Neustart des Servers verliert diesen Zustand; das kostet höchstens eine
laufende Bewährung, die dann von vorn zählt.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from app import bruegge
from app.database import (
    bruegge_position_loeschen, bruegge_vergebene_cids, bruegge_vs_spitze_merken,
    bruegge_zuordnung_bestaetigen, bruegge_zuordnung_bewaehren, bruegge_zuordnung_holen,
    bruegge_zuordnung_loesen, bruegge_zuordnung_setzen, bruegge_zuordnung_verstoss,
    bruegge_zuordnung_vergessen,
)

#: These 6: Im Stand passt eine Verbindung nur auf den Meter. Gemessen sind 0,4–0,7 m zwischen
#: Brügge und eigenem VATSIM-Eintrag (26.09.2026, MSFS 2024); der Nachbar vom 25.09. stand 22 m
#: daneben. Die Luft bis 5 m ist für MSFS 2020 und X-Plane, die nicht gemessen sind.
STAND_M = 5.0
#: Ab hier gilt die Brügge als stehend -- `GROUND VELOCITY` ist im Stand praktisch null.
STEHT_KT = 1.0
#: Ab hier rollt sie an (These 7).
ROLLT_KT = 3.0
#: These 7: So lange nach dem Anrollen der Brügge darf sich der Partner auf VATSIM mitbewegen.
#: Beim Server sind VATSIM-Positionen bis rund 20 s alt (2–5 s VATSIM, bis 15 s Abruf).
ANROLLEN_S = 30.0
#: Um so viel muss sich eine Verbindung bewegt haben, damit sie als angerollt gilt.
ANGEROLLT_M = 20.0
#: These 2: bewährt wird nur in der Luft und ab dieser Geschwindigkeit (Nutzer: „wirklich warten,
#: bis die Maschine in der Luft ist … 40 Knoten oder mehr").
BEWAEHRT_GS_KT = 40.0
#: These 3: so lange am Stück eindeutig.
BEWAEHRT_S = 120.0
#: Eine längere Lücke zwischen zwei Meldungen unterbricht das „am Stück".
BEWAEHRT_LUECKE_S = 10.0
#: These 9: „vergeben" ist, wessen bewährte Brügge in dieser Frist gemeldet hat.
VERGEBEN_S = 120.0
#: These 8: Sitzungsbeginn ist die erste Meldung nach so langer Ruhe.
SITZUNG_PAUSE_S = 300.0
#: Nach so langer Ruhe wird eine Sitzung aus dem Speicher geräumt.
SITZUNG_VERFALL_S = 1800.0
#: Höchstens so viele Sitzungen im Speicher; darüber fallen die ältesten.
SITZUNG_MAX = 5000
#: Uhrenversatz zwischen VATSIM (`logon_time`) und Server.
LOGON_TOLERANZ_S = 10.0
#: These 4: Ein Widerspruch zählt nur, wenn die VATSIM-Position des Partners frisch ist. Ein
#: hängender Abruf friert die Positionen ein -- das darf keine Bindung löschen.
VATSIM_FRISCH_S = 60.0
#: These 5: Ab so langer Ablehnung erscheint eine Brügge als Hinweis in der Verwaltung.
HINWEIS_AB_S = 120.0
#: ⚠ Die Kennung, die die MSFS-Fassungen vom 11.–14.09.2026 auf JEDEM Rechner gleich erzeugt und
#: in MSFS 2024 nach `\work` geschrieben haben. Spätere Fassungen haben sie nicht überschrieben;
#: 1.18.0 liest sie wieder. Sie wird nie gebunden -- sonst teilten sich wieder mehrere Brügges
#: eine Kennung (der Fehler vom 14.09.). Der Endpunkt vergibt dafür eine frische.
KOLLISIONSKENNUNG = "9e3711c100000000"


@dataclass
class Kand:
    """Eine VATSIM-Verbindung einer im Forum angemeldeten CID, auf jetzt fortgerechnet."""
    cid: int
    callsign: str
    lat: float
    lon: float
    alt_ft: float
    gs_kt: float
    logon_ts: float | None      # Anmeldezeit bei VATSIM, epoch; None = unbekannt
    alter_s: float              # wie alt die VATSIM-Position beim Server ist


@dataclass
class Meldung:
    lat: float
    lon: float
    alt_ft: float
    gs_kt: float
    am_boden: bool
    vs_wirksam: float = 0.0     # die grösste Steigrate der letzten 30 s (s. main)
    sekunden_her: float = 1.0   # seit der letzten angenommenen Meldung (Sprungschranke)
    simulator: str | None = None
    protokoll: int | None = None
    # These 3 (Fable 3): Wie weit die mitgeschickte Sekundenspur zurückreicht, und ihre kleinste
    # Geschwindigkeit. Sie deckt die Lücke zwischen zwei Meldungen -- bei 15 s Takt riss das
    # „am Stück" sonst an jeder Meldung. `None`: keine Spur mitgekommen.
    spur_s: float = 0.0
    spur_min_gs: float | None = None


@dataclass
class Sitzung:
    seit: float
    zuletzt: float
    # These 7: Gleichstand im Stand -- die CIDs und ihre Lage beim Anrollen der Brügge.
    gleichstand: set[int] = field(default_factory=set)
    anroll_ts: float | None = None
    anroll_lage: dict[int, tuple[float, float]] = field(default_factory=dict)
    # These 3: laufende Bewährung -- für welche CID, seit wann, letzte zählende Meldung.
    beweis_cid: int | None = None
    beweis_seit: float | None = None
    beweis_zuletzt: float | None = None


@dataclass
class Ergebnis:
    cid: int | None
    lage_gilt: bool
    kandidaten_da: bool


_SITZUNGEN: dict[str, Sitzung] = {}
#: Nach „vergessen" (Admin) gilt These 8 einmal nicht: Der Pilot ist ja längst verbunden, und die
#: Brügge soll im Stand neu gebunden werden können (Fable 2). Verbraucht beim Binden; wachsen
#: kann die Menge nur mit Klicks auf „vergessen".
_OHNE_ANMELDEZEIT: set[str] = set()
#: These 5: kennung -> {gebunden, passt, seit, zuletzt} -- Brügges, die abgelehnt werden.
ABGELEHNT: dict[str, dict] = {}


def sitzung(kennung: str, jetzt: float, conn=None) -> Sitzung:
    """Die Sitzung dieser Kennung -- neu, wenn es die erste Meldung nach einer Pause ist.

    Fehlt sie im Speicher (etwa nach einem Deploy), wird ihr Beginn aus `bruegge_sitzung`
    zurückgeholt, sofern die letzte Meldung keine Pause her ist (Fable 7)."""
    s = _SITZUNGEN.get(kennung)
    if s is None and conn is not None:
        row = conn.execute("SELECT seit, zuletzt FROM bruegge_sitzung WHERE kennung = ?",
                           (kennung,)).fetchone()
        if row and jetzt - float(row[1]) <= SITZUNG_PAUSE_S:
            s = Sitzung(seit=float(row[0]), zuletzt=float(row[1]))
            _SITZUNGEN[kennung] = s
    if s is None or jetzt - s.zuletzt > SITZUNG_PAUSE_S:
        s = Sitzung(seit=jetzt, zuletzt=jetzt)
        _SITZUNGEN[kennung] = s
        _aufraeumen(jetzt)
    s.zuletzt = jetzt
    return s


def _sitzung_festhalten(conn, kennung: str, s: Sitzung, jetzt: float) -> None:
    """Nur für NICHT gebundene Brügges: Ihr Beginn entscheidet These 8."""
    conn.execute("INSERT INTO bruegge_sitzung (kennung, seit, zuletzt) VALUES (?, ?, ?) "
                 "ON CONFLICT(kennung) DO UPDATE SET seit = excluded.seit, "
                 "zuletzt = excluded.zuletzt", (kennung, s.seit, jetzt))
    if int(jetzt) % 60 == 0:
        conn.execute("DELETE FROM bruegge_sitzung WHERE zuletzt < ?",
                     (jetzt - SITZUNG_VERFALL_S,))
        conn.execute("DELETE FROM bruegge_sitzung WHERE kennung NOT IN ("
                     "SELECT kennung FROM bruegge_sitzung ORDER BY zuletzt DESC LIMIT ?)",
                     (SITZUNG_MAX,))


def _aufraeumen(jetzt: float) -> None:
    for k in [k for k, s in _SITZUNGEN.items() if jetzt - s.zuletzt > SITZUNG_VERFALL_S]:
        del _SITZUNGEN[k]
    for k in [k for k, h in ABGELEHNT.items() if jetzt - h["zuletzt"] > SITZUNG_VERFALL_S]:
        del ABGELEHNT[k]
    if len(_SITZUNGEN) > SITZUNG_MAX:
        for k, _ in sorted(_SITZUNGEN.items(), key=lambda e: e[1].zuletzt)[
                :len(_SITZUNGEN) - SITZUNG_MAX]:
            del _SITZUNGEN[k]


def vergessen_im_speicher(kennung: str) -> None:
    """Was der Speicher zu dieser Kennung weiß, verwerfen (Admin „vergessen").

    Die nächste Zuordnung im Stand verlangt dann EINMAL keine Anmeldung nach dem Sitzungsbeginn
    (These 8): Der Pilot ist längst verbunden, sonst bände sie erst im Flug (Fable 2)."""
    _SITZUNGEN.pop(kennung, None)
    ABGELEHNT.pop(kennung, None)
    _OHNE_ANMELDEZEIT.add(kennung)


def _abstand(m: Meldung, k: Kand) -> float:
    return bruegge.abstand_m(m.lat, m.lon, k.lat, k.lon)


def _plausibel(m: Meldung, k: Kand) -> bool:
    return bruegge.bleibt_plausibel(m.lat, m.lon, m.alt_ft, m.gs_kt, k, m.vs_wirksam)


def _vergeben(conn, kennung: str, kands: list[Kand]) -> set[int]:
    """These 9: CIDs, deren bewährte Brügge gerade meldet UND dort ist, wo ihre Verbindung ist."""
    raus = set()
    for cid, lage in bruegge_vergebene_cids(conn, kennung, VERGEBEN_S).items():
        k = next((k for k in kands if k.cid == cid), None)
        if k is None or lage is None:
            raus.add(cid)
            continue
        if bruegge.abstand_m(lage[0], lage[1], k.lat, k.lon) <= bruegge.schranke_m(
                k.gs_kt, bruegge.PAARUNG_LOESEN_FAKTOR):
            raus.add(cid)
    return raus


def eindeutig_im_flug(m: Meldung, kands: list[Kand], vergeben: set[int]) -> Kand | None:
    """These 2: in der Luft, mindestens 40 kt, und EINE Verbindung ist klar die nächste.

    Klar heißt: jede andere infrage kommende liegt mindestens doppelt so weit weg. Wer eine
    bewährte Brügge hat, die gerade meldet, zählt nicht mit -- er ist schon eindeutig er selbst.
    """
    if m.am_boden or m.gs_kt < BEWAEHRT_GS_KT:
        return None
    pool = sorted((k for k in kands if k.cid not in vergeben), key=lambda k: _abstand(m, k))
    if not pool or not _plausibel(m, pool[0]):
        return None
    if len(pool) > 1 and not _abstand(m, pool[0]) <= _abstand(m, pool[1]) * bruegge.PAARUNG_VORSPRUNG:
        return None
    return pool[0]


def _beweis(s: Sitzung, cid: int | None, jetzt: float, m: Meldung | None = None) -> bool:
    """These 3: 2 Minuten am Stück. Gibt zurück, ob die Dauer jetzt erreicht ist.

    Die Lücke zwischen zwei Meldungen darf so groß sein, wie die Sekundenspur zurückreicht --
    und ist dort eine Stelle unter 40 kt, war es nicht am Stück (Fable 3)."""
    if cid is None:
        s.beweis_cid = s.beweis_seit = s.beweis_zuletzt = None
        return False
    erlaubt = BEWAEHRT_LUECKE_S
    langsam = False
    if m is not None:
        erlaubt = max(erlaubt, m.spur_s + 2.0)
        langsam = m.spur_min_gs is not None and m.spur_min_gs < BEWAEHRT_GS_KT
    luecke = s.beweis_zuletzt is None or jetzt - s.beweis_zuletzt > erlaubt
    if s.beweis_cid != cid or luecke or langsam:
        s.beweis_cid, s.beweis_seit = cid, jetzt
    s.beweis_zuletzt = jetzt
    return jetzt - s.beweis_seit >= BEWAEHRT_S


def _binden(conn, kennung: str, cid: int, m: Meldung, bewaehrt: bool = False) -> Ergebnis:
    conn.execute("DELETE FROM bruegge_sitzung WHERE kennung = ?", (kennung,))
    bruegge_zuordnung_setzen(conn, kennung, cid, m.simulator, m.protokoll or 3)
    bruegge_zuordnung_bestaetigen(conn, kennung, m.lat, m.lon)
    bruegge_vs_spitze_merken(conn, kennung, m.vs_wirksam)
    if bewaehrt:
        bruegge_zuordnung_bewaehren(conn, kennung)
    ABGELEHNT.pop(kennung, None)
    return Ergebnis(cid, True, True)


def _hinweis(kennung: str, gebunden: int, passt: int | None, jetzt: float) -> None:
    h = ABGELEHNT.get(kennung)
    if h is None or h["gebunden"] != gebunden:
        ABGELEHNT[kennung] = {"gebunden": gebunden, "passt": passt, "seit": jetzt,
                              "zuletzt": jetzt}
    else:
        h["passt"] = passt if passt is not None else h["passt"]
        h["zuletzt"] = jetzt


def hinweise(jetzt: float | None = None) -> list[dict]:
    """These 5: Brügges, die seit mindestens ``HINWEIS_AB_S`` abgelehnt werden."""
    jetzt = time.time() if jetzt is None else jetzt
    return [{"kennung": k, **h, "dauer_s": int(h["zuletzt"] - h["seit"])}
            for k, h in ABGELEHNT.items()
            if h["zuletzt"] - h["seit"] >= HINWEIS_AB_S and jetzt - h["zuletzt"] < 300]


def zuordnen(conn, kennung: str, m: Meldung, kands: list[Kand],
             jetzt: float | None = None) -> Ergebnis:
    """Wer meldet hier? Für eine Brügge mit Kennung, ab Protokoll 3 oder X-Plane."""
    jetzt = time.time() if jetzt is None else jetzt
    da = bool(kands)
    if kennung == KOLLISIONSKENNUNG:
        return Ergebnis(None, False, da)
    s = sitzung(kennung, jetzt, conn)
    zeile = bruegge_zuordnung_holen(conn, kennung)
    if zeile:
        return _bekannt(conn, kennung, zeile, m, kands, s, jetzt)
    _sitzung_festhalten(conn, kennung, s, jetzt)
    return _neu(conn, kennung, m, kands, s, jetzt, da)


def _bekannt(conn, kennung: str, zeile: dict, m: Meldung, kands: list[Kand], s: Sitzung,
             jetzt: float) -> Ergebnis:
    """These 10: Eine bekannte Brügge wird ohne Suche zurückgebunden -- oder sie wartet."""
    da = bool(kands)
    cid = int(zeile["cid"])
    gilt = not zeile.get("geloest_am")
    bewaehrt = bool(zeile.get("bewaehrt_am"))

    # Ein Sprung (Ladevorgang, Slew, Flugwechsel) lässt die Bindung RUHEN -- auch eine
    # unbewährte. Einen neuen Flug zu laden ist kein Widerspruch zur Identität; derselbe Pilot
    # bindet danach ohne Suche zurück (These 10). Bis zum 26.09. abends vergaß der Sprung eine
    # unbewährte Bindung, und These 8 sperrte dann den längst verbundenen eigenen Piloten
    # (Fable-Befund 4; beobachtet am Simulator-Rechner beim Neustart an anderem Ort).
    if gilt and bruegge.ist_sprung(m.lat, m.lon, zeile.get("vor_lat"), zeile.get("vor_lon"),
                                   m.sekunden_her, m.gs_kt):
        bruegge_zuordnung_loesen(conn, kennung)
        bruegge_position_loeschen(conn, cid)
        _beweis(s, None, jetzt)
        return Ergebnis(None, False, da)

    partner = next((k for k in kands if k.cid == cid), None)
    if partner is None:
        # These 4: Fehlt der Partner (noch nicht verbunden, abgemeldet), ruht die Bindung --
        # die Erinnerung bleibt, auch bei einer unbewährten. Andere werden nicht betrachtet.
        if gilt:
            bruegge_zuordnung_loesen(conn, kennung)
            bruegge_position_loeschen(conn, cid)
        _beweis(s, None, jetzt)
        andere = _passt_im_stand(m, kands) or eindeutig_im_flug(m, kands, set())
        if andere is not None:
            _hinweis(kennung, cid, andere.cid, jetzt)
        return Ergebnis(None, False, da)

    if _plausibel(m, partner):
        if gilt:
            bruegge_zuordnung_bestaetigen(conn, kennung, m.lat, m.lon)
            bruegge_vs_spitze_merken(conn, kennung, m.vs_wirksam)
        else:
            bruegge_zuordnung_setzen(conn, kennung, cid, m.simulator, m.protokoll or 3)
            bruegge_zuordnung_bestaetigen(conn, kennung, m.lat, m.lon)
        ABGELEHNT.pop(kennung, None)
        if not bewaehrt:
            treffer = eindeutig_im_flug(m, kands, _vergeben(conn, kennung, kands))
            if _beweis(s, treffer.cid if treffer and treffer.cid == cid else None, jetzt, m):
                bruegge_zuordnung_bewaehren(conn, kennung)
        return Ergebnis(cid, True, da)

    # Die Lage passt nicht. These 5 (Fable 1): Passt sie zu jemand anderem, gehört das in den
    # Hinweis der Verwaltung -- gerade das ist der Fall für „vergessen".
    andere = [k for k in kands if k.cid != cid]
    b = _passt_im_stand(m, andere) or eindeutig_im_flug(m, andere, set())
    if b is not None:
        _hinweis(kennung, cid, b.cid, jetzt)
    # These 4: Ein Widerspruch zählt nur mit frischen VATSIM-Daten.
    _beweis(s, None, jetzt)
    if not gilt:
        return Ergebnis(None, False, da)
    if partner.alter_s > VATSIM_FRISCH_S:
        return Ergebnis(cid, False, da)
    if bruegge_zuordnung_verstoss(conn, kennung) >= bruegge.PAARUNG_LOESEN_TAKTE:
        return _widerspruch(conn, kennung, cid, bewaehrt, s, da)
    return Ergebnis(cid, False, da)


def _widerspruch(conn, kennung: str, cid: int, bewaehrt: bool, s: Sitzung,
                 da: bool) -> Ergebnis:
    """These 4: Eine unbewährte Bindung wird vergessen, eine bewährte ruht."""
    if bewaehrt:
        bruegge_zuordnung_loesen(conn, kennung)
    else:
        bruegge_zuordnung_vergessen(conn, kennung)
    bruegge_position_loeschen(conn, cid)
    s.gleichstand.clear()
    s.anroll_ts = None
    _beweis(s, None, time.time())
    return Ergebnis(None, False, da)


def _stehend(k: Kand) -> bool:
    return k.gs_kt < STEHT_KT


def _passt_im_stand(m: Meldung, kands: list[Kand]) -> Kand | None:
    if not (m.am_boden and m.gs_kt < STEHT_KT):
        return None
    nah = [k for k in kands if _stehend(k) and _abstand(m, k) <= STAND_M]
    return nah[0] if len(nah) == 1 else None


def _neu(conn, kennung: str, m: Meldung, kands: list[Kand], s: Sitzung, jetzt: float,
         da: bool) -> Ergebnis:
    """Die erste Zuordnung einer Installation (Thesen 6, 7, 8)."""
    steht = m.am_boden and m.gs_kt < STEHT_KT

    if steht:
        # Ein Halt kurz nach dem Anrollen (Haltelinie) verwirft den Gleichstand nicht -- die
        # Frist aus These 7 läuft weiter (Fable 5).
        if s.gleichstand and s.anroll_ts is not None and jetzt - s.anroll_ts <= ANROLLEN_S:
            return Ergebnis(None, False, da)
        # These 6 und 8: stehend, höchstens 5 m, angemeldet NACH dem Sitzungsbeginn der Brügge.
        # Die Reihenfolge ist immer: Flug laden, die Brügge meldet, dann erst die eigene
        # Verbindung. Wer vorher da war, ist ein Nachbar (25.09.2026). Nach „vergessen" gilt die
        # Anmeldezeit einmal nicht (Fable 2).
        ohne = kennung in _OHNE_ANMELDEZEIT
        nah = [k for k in kands
               if _stehend(k) and _abstand(m, k) <= STAND_M
               and (ohne or (k.logon_ts is not None
                             and k.logon_ts >= s.seit - LOGON_TOLERANZ_S))]
        s.anroll_ts = None
        s.anroll_lage.clear()
        if len(nah) == 1:
            s.gleichstand.clear()
            _OHNE_ANMELDEZEIT.discard(kennung)
            return _binden(conn, kennung, nah[0].cid, m)
        # These 7: Gleichstand -- merken und auf das Anrollen warten.
        s.gleichstand = {k.cid for k in nah} if len(nah) > 1 else set()
        return Ergebnis(None, False, da)

    if m.am_boden:
        # Beim Rollen wird nicht über den Abstand zugeordnet -- nur ein Gleichstand löst sich.
        if s.gleichstand and m.gs_kt >= ROLLT_KT:
            return _anrollen(conn, kennung, m, kands, s, jetzt, da)
        return Ergebnis(None, False, da)

    # These 6 (im Flug): nach dem Bewährt-Maßstab, dann sofort bewährt.
    s.gleichstand.clear()
    treffer = eindeutig_im_flug(m, kands, _vergeben(conn, kennung, kands))
    if _beweis(s, treffer.cid if treffer else None, jetzt, m):
        return _binden(conn, kennung, treffer.cid, m, bewaehrt=True)
    return Ergebnis(None, False, da)


def _anrollen(conn, kennung: str, m: Meldung, kands: list[Kand], s: Sitzung, jetzt: float,
              da: bool) -> Ergebnis:
    """These 7: Die Brügge rollt an. Gehört sie zu der Verbindung, die sich binnen 30 s mitbewegt,
    während die anderen stehen bleiben?"""
    betroffen = [k for k in kands if k.cid in s.gleichstand]
    if s.anroll_ts is None:
        s.anroll_ts = jetzt
        s.anroll_lage = {k.cid: (k.lat, k.lon) for k in betroffen}
    if jetzt - s.anroll_ts > ANROLLEN_S:
        # Keine eindeutige Antwort in der Frist -- dann entscheidet der Flug.
        s.gleichstand.clear()
        s.anroll_ts = None
        return Ergebnis(None, False, da)

    def bewegt(k: Kand) -> bool:
        vor = s.anroll_lage.get(k.cid)
        weg = bruegge.abstand_m(vor[0], vor[1], k.lat, k.lon) if vor else 0.0
        return k.gs_kt >= STEHT_KT or weg > ANGEROLLT_M

    mit = [k for k in betroffen if bewegt(k)]
    if len(mit) == 1 and len(betroffen) >= 2:
        s.gleichstand.clear()
        s.anroll_ts = None
        return _binden(conn, kennung, mit[0].cid, m)
    return Ergebnis(None, False, da)
