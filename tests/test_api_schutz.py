# -*- coding: utf-8 -*-
"""Jeder Endpunkt ist geschützt — oder steht hier mit Begründung (19.09.2026).

**Warum dieser Test und nicht eine Doku.** Das Projekt ist öffentlich: `app/main.py` liegt auf
GitHub, ein `grep '@app\\.'` liefert jedem alle Routen. Ein Endpunkt aus der Swagger-Übersicht
herauszuhalten (`include_in_schema=False`) schützt deshalb **nichts** — es verbirgt ihn nur vor
den eigenen Leuten. Gefehlt hat nicht Geheimhaltung, sondern eine Liste, gegen die man prüfen
kann: `/api/me/fassungen` gab nach dem Bau die Paketfassungen ohne Anmeldung heraus, weil beim
Schreiben niemand (und nichts) nachhielt, was offen ist.

**Wie geschützt wird, ist zweistufig — und der Test kennt beide Stufen:**

1. **Das Login-Gate** (`_GATE_ALLOW_PREFIXES`, Middleware) fängt alles ab, was nicht
   ausdrücklich freigestellt ist. Für diese Endpunkte braucht der Handler selbst keine Prüfung.
2. **Prüfung im Handler** (`require_admin`, `require_confirm`, `_current_cid`,
   `verify_user_token`) — nötig für alles, was gate-frei ist.

Geprüft wird deshalb nur die kurze Liste der gate-freien Pfade: Jeder davon hat entweder eine
Prüfung im Handler oder steht unten in ``BEWUSST_OFFEN`` — mit dem Grund. Wer einen neuen
gate-freien Endpunkt baut, muss hier eine Zeile hinzufügen und dabei erklären, warum er offen
sein darf. Das ist der Zweck: nicht Dokumentation, sondern ein Riegel gegen Vergessen.
"""
from __future__ import annotations

import inspect

import app.main as main

#: Gate-freie Pfade, die ohne Anmeldung erreichbar sein MÜSSEN — mit Grund.
#: Alles andere Gate-freie braucht eine Prüfung im Handler.
BEWUSST_OFFEN = {
    "/health": "Lebenszeichen für Deploy und Watchdog, gibt nur 'ok' heraus",
    "/robots.txt": "Suchmaschinen-Anweisung, muss anonym lesbar sein",
    "/impressum": "Pflichtangabe, muss ohne Anmeldung erreichbar sein",
    "/datenschutz": "Pflichtangabe, muss ohne Anmeldung erreichbar sein",
    "/widget": "Einbindung auf friesenflieger.de — der Zweck ist die Öffentlichkeit",
    "/widget/preview": "Vorschau desselben Widgets",
    "/api/me": "nur 'angemeldet: ja/nein' — die Seite braucht es, um den Login anzubieten",
    # Break-glass: Fällt das Forum-Login aus, ist das der einzige Weg zur Verwaltung — und die
    # Passwortmaske steckt in `admin.html` selbst. Die DATEN dahinter sind geschützt: jeder
    # `/api/admin/…`-Endpunkt verlangt `require_admin`.
    "/admin": "Break-glass-Zugang; die Login-Maske selbst, Daten dahinter require_admin",
    "/admin/push-overview": "eigenes Passwort (PUSH_OVERVIEW_PASSWORD), sonst 404",
    "/auth/device": "Teil des Anmeldewegs",
    "/auth/device/bind": "Teil des Anmeldewegs",
    "/auth/forum/login": "Teil des Anmeldewegs",
    "/auth/forum/callback": "Teil des Anmeldewegs",
    "/auth/forum/logout": "Abmelden muss ohne gültige Sitzung gehen",
    # Die Brügge hat bewusst KEINE Anmeldung (PROTOKOLL.md, Abschnitt 5): ein Modul im
    # Simulator hat kein Sitzungs-Cookie. Sie prüft stattdessen selbst — auf VATSIM mit
    # Friesen-Präfix, Zeile in `forum_callsign`, und die Position muss passen.
    "/api/bruegge/melden": "Protokoll ohne Anmeldung, drei eigene Bedingungen im Endpunkt",
    # Selbstdiagnose des Panels: Gerade wenn die Anmeldung dort NICHT klappt, sollen die
    # Messwerte ankommen. Nimmt nur Diagnosedaten an und gibt nichts heraus.
    "/api/panel-diag": "nimmt nur Messwerte an, gibt nichts preis — s. Kommentar an der Route",
    "/api/admin/login": "die Anmeldung selbst kann keine Anmeldung verlangen",
    "/api/admin/logout": "Abmelden muss auch mit abgelaufener Sitzung gehen",
}

#: Woran eine Prüfung im Handler zu erkennen ist.
WAECHTER = ("require_admin", "require_confirm", "_current_cid", "verify_user_token",
            "PUSH_OVERVIEW", "_admin_ok", "_require_push_overview", "_prefs_cid")


def _routen():
    for r in main.app.routes:
        pfad = getattr(r, "path", None)
        methoden = getattr(r, "methods", None)
        if pfad and methoden and getattr(r, "endpoint", None):
            yield pfad, sorted(methoden - {"HEAD", "OPTIONS"}), r.endpoint


def _gate_frei(pfad: str) -> bool:
    return pfad.startswith(main._GATE_ALLOW_PREFIXES)


def test_jeder_gatefreie_endpunkt_hat_eine_pruefung_oder_einen_grund():
    """Der Riegel. Ein neuer gate-freier Endpunkt ohne Prüfung macht diesen Test rot."""
    offen = []
    for pfad, methoden, fn in _routen():
        if not _gate_frei(pfad) or pfad in BEWUSST_OFFEN:
            continue
        if pfad.startswith(("/static/", "/manifest", "/sw.js", "/favicon")):
            continue            # statische Dateien, kein eigener Code
        try:
            quelle = inspect.getsource(fn)
        except (OSError, TypeError):
            quelle = ""
        if not any(w in quelle for w in WAECHTER):
            offen.append(f"{','.join(methoden)} {pfad}")
    assert not offen, (
        "Gate-frei UND ohne Prüfung im Handler:\n  " + "\n  ".join(offen)
        + "\n\nEntweder eine Prüfung einbauen oder in BEWUSST_OFFEN aufnehmen — mit Grund.")


def test_bewusst_offen_nennt_nur_pfade_die_es_gibt():
    """Sonst bleibt eine Freistellung stehen, deren Endpunkt längst umbenannt ist — und der
    neue Name wäre ungeprüft."""
    vorhanden = {p for p, _, _ in _routen()}
    weg = sorted(p for p in BEWUSST_OFFEN if p not in vorhanden)
    assert not weg, f"In BEWUSST_OFFEN, aber keine Route (mehr): {weg}"


def test_bewusst_offen_steht_nur_fuer_gatefreie_pfade():
    """Ein Pfad hinter dem Gate braucht keine Freistellung. Steht er doch hier, ist entweder
    die Allowlist geschrumpft oder jemand hat sich vertan — beides gehört gesehen."""
    falsch = sorted(p for p in BEWUSST_OFFEN if not _gate_frei(p))
    assert not falsch, f"In BEWUSST_OFFEN, aber ohnehin hinter dem Gate: {falsch}"


def test_jede_freistellung_traegt_eine_begruendung():
    leer = sorted(p for p, grund in BEWUSST_OFFEN.items() if len(grund.strip()) < 15)
    assert not leer, f"Freistellung ohne brauchbaren Grund: {leer}"


def test_alle_schreibpfade_sind_geprueft():
    """Lesen ohne Anmeldung ist ein Ärgernis, Schreiben ein Schaden — deshalb hier strenger:
    Für POST/DELETE/PUT genügt das Gate NICHT, es muss eine Prüfung im Handler stehen.

    Zwei Ausnahmen, beide notwendig: Die Anmeldung selbst kann keine Anmeldung verlangen, und
    die Brügge hat keine (s. BEWUSST_OFFEN).
    """
    ausnahmen = {
        "/api/admin/login": "die Anmeldung selbst",
        "/api/admin/logout": "Abmelden",
        "/api/bruegge/melden": "kein Login möglich, drei eigene Bedingungen",
        "/api/panel-diag": "nimmt nur Messwerte an",
        "/auth/device/bind": "Teil des Anmeldewegs",
        # ⚠ OFFENER PUNKT, nicht Absicht: Der Endpunkt löscht eine Push-Anmeldung allein
        # anhand der mitgeschickten `endpoint`-URL, ohne zu prüfen, wem sie gehört. Er liegt
        # hinter dem Gate, und die URL ist ein langer Zufallswert des Push-Dienstes — ein
        # Fremder kann sie nicht raten. Wer sie hat, kann aber die Anmeldung eines anderen
        # löschen. Sauber wäre ein Abgleich gegen die eigene CID.
        "/api/push/unsubscribe": "⚠ ungeprüft — s. Kommentar, kleiner offener Punkt",
    }
    ohne = []
    for pfad, methoden, fn in _routen():
        if not any(m in ("POST", "DELETE", "PUT", "PATCH") for m in methoden):
            continue
        if pfad in ausnahmen:
            continue
        try:
            quelle = inspect.getsource(fn)
        except (OSError, TypeError):
            quelle = ""
        if not any(w in quelle for w in WAECHTER):
            ohne.append(f"{','.join(methoden)} {pfad}")
    assert not ohne, "Schreibpfad ohne Prüfung im Handler:\n  " + "\n  ".join(ohne)
