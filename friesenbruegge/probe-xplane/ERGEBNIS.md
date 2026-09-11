# Ergebnis des X-Plane-Probeflugs

**Gemessen:** 11.09.2026, X-Plane 12 auf `D:\X-Plane 12`
**Gegenstück zu** [`../probe-msfs/ERGEBNIS.md`](../probe-msfs/ERGEBNIS.md)

---

## Die Antwort

**Ja.** Ein X-Plane-Plugin setzt ein mitgeliefertes Objekt zur Laufzeit an eine frei gewählte
Koordinate, X-Plane zeichnet es vollständig, und es bleibt liegen.

**Sichtbestätigung:** Screenshot 11:29:34 — ein Segelboot mit gesetzten Segeln (Rumpfaufschrift
„Laminar Research"), voll texturiert und mit Schattenwurf, auf einer Wiese zwischen Bäumen und
Wohnhaus bei `47.80461 / 12.99683`.

**Damit ist der zweite Hauptweg belegt.** Rund ein Drittel der Gruppe fliegt X-Plane; bis heute
war dazu nichts gemessen, nur gelesen.

## Das Protokoll

```
11:10:50  XPluginStart              geladen   Das Plugin wurde von X-Plane geladen
11:10:50  datarefs                 gefunden   Positions-Datarefs vorhanden
11:10:50  XPluginEnable                   1   Freigeschaltet
11:27:51  flugzeug_lat             47.80461
11:27:51  flugzeug_lon             12.99683
11:27:51  gelaende_y              335.11093   Terrain-Probe hat getroffen
11:27:51  instanz_erzeugt                ok   XPLMCreateInstance lieferte eine Instanz
11:27:51  position_gesetzt               ok
11:27:51  ERFOLG_autoshift_an             1   AutoShift aktiv
11:28:11  laeuft_noch_sekunden           30
11:28:41  laeuft_noch_sekunden           60
11:29:14  laeuft_noch_sekunden           90
11:29:45  laeuft_noch_sekunden          120
11:30:15  laeuft_noch_sekunden          150
```

Bemerkenswert ist der Zeitsprung: Das Plugin wurde um **11:10:50** geladen, gesetzt wurde erst
um **11:27:51**. Dazwischen lag das Laden des Flugs. Das Plugin wartet auf den ersten
Flugschleifen-Takt nach zehn Sekunden — im Hauptmenü wäre die Position unbrauchbar, dieselbe
Falle wie in MSFS, wo dort `0 / 90` zurückkam.

## Was gegenüber MSFS bestätigt, was widerlegt wurde

| Annahme vorher | Ergebnis |
|---|---|
| Pfad `…/sim objects/dynamic/SailBoat.obj` existiert | **stimmt** — 2,5 MB, auf der Platte nachgesehen |
| Objekte brauchen kein eigenes 3D-Modell | **stimmt** — Segelboot, Ölplattform, Fregatte, Hirsche und Möwen liegen bei |
| Koordinaten sind lokal, nicht lat/lon | **stimmt** — `XPLMWorldToLocal` nötig |
| `XPLMInstanceSetAutoShift` löst das Mitwandern | **arbeitet** — Objekt blieb über 150 s stabil |
| Kein `OnGround=1`-Gegenstück | **stimmt** — `XPLMProbeTerrainXYZ` lieferte 335,11 m |
| Plugins starten automatisch | **stimmt** — `Resources/plugins/`, keine Registrierung nötig |
| Ein Plugin darf ins Netz | **stimmt** — 14 HTTP-Meldungen kamen an |

**Der Pfad war die heikelste Annahme** und stammte aus einer XPPython3-Doku, nicht von Laminar.
Genau so war in der Kieker-Spec der Container-Titel `Boat_Small` entstanden, den es nie gab.
Diesmal hielt die Quelle.

## Mitgelieferte Objekte — mehr als erwartet

In `Resources/default scenery/sim objects/dynamic/`:

| Datei | wofür |
|---|---|
| `SailBoat.obj` | das Testobjekt |
| `OilPlatform.obj`, `OilRig.obj` | passt zur Nordsee |
| `Perry.obj` | Fregatte |
| **`deer_buck.obj`, `deer_doe.obj`** | **Tiere** |
| **`seagull_far/flap/glide.obj`** | **Möwen**, in drei Flugzuständen |

Für einen Zähl-Event ist das reichhaltiger als MSFS' Bootssortiment — und Hirsche und Möwen
stehen der ursprünglichen Robben-Idee näher als alles, was Asobo für MSFS 2024 ausliefert
(dort gibt es 41 Tier-Pakete, aber keine Robbe).

## Noch offen

**Ob die Instanz das Entladen des Plugins überdauert.** In MSFS sterben Objekte mit der
SimConnect-Verbindung — das war der folgenreichste Befund dort. Hier zerstört das Plugin seine
Instanz in `XPluginStop` selbst, die Frage ist also noch nicht beantwortet. Für den Zuschnitt
zählt sie wenig: Die Brügge läuft ohnehin durch, solange geflogen wird.

**Ob es in der Demo läuft.** Diese Messung fand in einer Installation unter `D:\X-Plane 12`
statt; das Flugzeug stand bei 47,8 N / 13,0 O, also im Alpenraum und nicht in der
Demo-Region Seattle. Ob eine reine Demo-Installation Plugins lädt, bleibt damit ungeprüft.

## Ein Fehler im Messaufbau

Im Protokoll fehlt die Zeile `objekt_geladen`, die sagen sollte, **welcher** `.obj`-Pfad trägt.
Ursache: Der Pfad enthält **Leerzeichen**, und der Rückkanal schickte ihn ungeschützt in eine
URL. `GET /xplane?wert=Resources/default scenery/… HTTP/1.1` liest ein HTTP-Server als Pfad
`…/default` und Version `scenery/sim` — die Meldung ging verloren, und im Horcher hagelte es
Tracebacks (30 KB um 14 echte Zeilen herum).

Der Befund steht trotzdem: `instanz_erzeugt` kann nur folgen, wenn das Objekt geladen wurde —
sonst bricht das Plugin vorher ab —, und der Pfad ist auf der Platte verifiziert.

Behoben: `url_sicher()` kodiert jetzt jedes Sonderzeichen als `%XX`, und der Horcher fängt
abgebrochene Verbindungen ab, statt je Meldung einen Traceback zu drucken. **Die Reparatur
greift erst beim nächsten X-Plane-Start** — bei laufendem Simulator ist die `.xpl` gesperrt.

Das ist derselbe Fehlertyp wie zweimal zuvor an diesem Tag: Ein Messaufbau, der im einfachen
Fall funktioniert, misst im schwierigen etwas anderes — oder gar nichts.
