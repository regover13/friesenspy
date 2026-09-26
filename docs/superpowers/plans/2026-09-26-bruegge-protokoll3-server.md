# Umsetzungsplan: Server-Seite von Paket 2 (Protokoll 3, Kennung je Installation)

**Spec:** `docs/superpowers/specs/2026-09-26-bruegge-kennung-und-zuordnung-design.md` (Thesen 1–13, 18).
**Client-Seite:** Simulator-Rechner, `friesenbruegge/UEBERGABE-kennung-umsetzung.md`.
**Ausführung:** Server-Sitzung, Aufgabe für Aufgabe mit Tests zuerst. Gepusht wird erst, wenn
alle Aufgaben stehen und niemand fliegt; danach bekommt der Simulator-Rechner Bescheid.

## Globale Randbedingungen
- Protokoll 2 der **alten MSFS-Brügge** (≤ 1.17.0) läuft bis zu einem Stichtag unverändert über
  `_bruegge_zuordnen` weiter (vier Wochen nach dem Release; der Tag wird beim Release gesetzt).
  Danach 426. X-Plane mit Protokoll 2 läuft dauerhaft über den neuen Weg.
- Protokoll 3 (neue MSFS-Brügge) und jede X-Plane-Brügge laufen über den **neuen Weg**.
- Unbundene Kennungen stehen nie in der Datenbank, nur im Speicher mit Verfallszeit.
- Datenbank-Transaktionen umspannen keinen Netzabruf.
- `"highlight": false` in jedem Changelog-Eintrag. Tests: `/home/claude/.venv-friesenspy`.

## Aufgaben

1. **Protokoll 3 annehmen.** `_BRUEGGE_PROTOKOLL = 3`; über 3 bleibt es bei 426. MSFS mit
   Protokoll 2 nach `_BRUEGGE_P2_MSFS_BIS` ebenfalls 426 (Vorgabe `None` = kein Stichtag).
2. **Schema.** `bruegge_zuordnung` bekommt `bewaehrt_am` und `protokoll`. `bruegge_zuordnung_setzen`
   räumt ältere Zeilen derselben CID und desselben Simulators nur noch bei Protokoll 2 weg.
   `bruegge_kennung_fuer` antwortet nur mit Zeilen von Protokoll 2 (oder ohne Angabe).
3. **Frische Kennung beim ersten Kontakt** (Protokoll 3 ohne Kennung): sofort `token_hex(8)` in
   der Antwort, Sitzung im Speicher (`seit`, `zuletzt`, letzte Lagen). Verfall nach 30 min Ruhe.
4. **Kandidaten über die CID.** Alle Verbindungen, deren CID sich im Forum angemeldet hat, gleich
   unter welchem Rufzeichen: `live_positions` plus Verkehrs-Schnappschuss des Pollers. Der
   Schnappschuss bekommt `logon` (Anmeldezeit); `/api/traffic` gibt sie nicht heraus.
5. **Der neue Weg `_bruegge_zuordnen_v3`:**
   - *Bekannte Kennung* (Zeile vorhanden): CID online und Lage passt → sofort binden, ohne Suche
     (These 10). Nicht online → Bindung ruht, Erinnerung bleibt. Widerspruch (vier Verstöße mit
     frischen VATSIM-Daten, oder Sprung) → unbewährt: Zeile löschen; bewährt: ruhen lassen (These 4).
   - *Unbekannte Kennung, im Stand:* genau eine Verbindung höchstens 5 m entfernt, stehend,
     angemeldet nach Sitzungsbeginn der Brügge → binden (Thesen 6, 8). Mehrere → Gleichstand
     merken; beim Anrollen der Brügge gewinnt die Verbindung, die sich binnen 30 s ebenfalls
     bewegt, während die anderen stehen (These 7). Beim Rollen sonst nichts.
   - *Unbekannte Kennung, im Flug:* Bewährt-Maßstab (unten) → binden und sofort bewährt.
6. **Bewähren** (Thesen 2, 3, 9): in der Luft (`am_boden` falsch), mindestens 40 kt, die gebundene
   Verbindung ist die nächste und jede andere mindestens doppelt so weit weg; Piloten mit gerade
   meldender bewährter Brügge zählen nicht mit. 120 s am Stück (Lücke über 10 s oder eine
   verfehlte Meldung setzt zurück) → `bewaehrt_am`.
7. **Belegt-Test und Rückfall ohne Sperre** gelten im neuen Weg nicht.
8. **Sekundenstrom:** Einträge der Brügge tragen `cs` und `bw` (bewährt). Das Kniebrett nutzt
   `bw` bereits als Anker (Paket 1).
9. **Verwaltung:** Liste der Brügges, die seit Minuten abgelehnt werden („gebunden an A, passt zu
   B“), und ein Knopf „vergessen“ (Zeile löschen).
10. **Doku:** `PROTOKOLL.md` (Protokoll 3), `docs/api.md`, Changelog, README (Deinstallieren),
    Hinweis auf der Download-Seite erst mit dem Release der neuen Brügge.
