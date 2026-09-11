# Messliste für den nächsten Simulator-Termin

**Alles, was an der Brügge noch ungemessen ist — in einem Zug abzuarbeiten.**

Diese Liste gibt es, weil am 11.09.2026 acht Simulator-Neustarts draufgingen: Nach jedem Fund
wurde sofort gebaut und neu gestartet, statt erst fertigzubauen und dann alles am Stück zu
messen. Die laufende Sim-Sitzung ist die knappe Ressource, nicht die Bauzeit.

---

## Vorbereitung (einmal, vor dem Start)

**Der Stand ist schon abgelegt** — Paket `friesenbruegge` liegt im Community-Ordner, Fassung
**1.1.0**. Nichts mehr zu bauen.

```
MSFS 2024 starten  →  Flug laden  →  vPilot verbinden (FRS49 oder FRS49N)
```

Ohne VATSIM-Verbindung geschieht **nichts** — das ist die Regel, nicht der Fehler. Und ohne
Forum-Login der CID ebenso wenig.

**Nach dem Verbinden höchstens 10 Sekunden warten**, dann steht die Zuordnung.

---

## 1. Setzt die Brügge ein Objekt aus `soll`?

**Die Kernfrage.** Alles Weitere hängt daran.

Im Admin (`/admin`, Panel „🌉 Brügge") ein `boot_gross` anfordern — Breite und Länge aus der
eigenen Position, ein paar hundert Meter versetzt. Oder per curl:

```
POST /api/admin/bruegge/soll   {"art":"boot_gross","lat":…,"lon":…}
```

| Beobachtung | heißt |
|---|---|
| Schiff steht da | ✅ die Brügge setzt |
| nichts zu sehen | `--boote-zaehlen` als Gegenprobe (s. unten) — das Auge taugt nicht |

⚠ **Ein „ich sehe nichts" ist ohne Gegenprobe nichts wert.** Ein `Boat01` misst acht Meter und
ist erst ab rund **1 km** eingeblendet (am 11.09. gemessen); ein `CruiseShip01` ab 22 km.
Deshalb im Zweifel:

```
python probe-msfs/kieker_probe.py --boote-zaehlen --radius 5000
```

---

## 2. Kommt `steht` korrekt zurück?

Das ist der einzige Weg, auf dem der Server erfährt, ob eine Stelle taugt — **FriesenSpy hat
kein Geländemodell.**

```
GET /api/admin/bruegge      →  die Melder-Tabelle
```

Zu prüfen: Meldet die Brügge `zustand: steht` mit einer **plausiblen Höhe**? Am Wasser rund
0 ft, über Land die Geländehöhe.

⚠ Die Höhe wird aus `PLANE ALTITUDE − PLANE ALT ABOVE GROUND` **gerechnet**, weil `OnGround=1`
aus WASM heraus nicht aufsetzt (gemessen: 49 ft auf Wangerooge, 122–130 ft in Seattle). Das
ist die Höhe **unter dem Flugzeug**, nicht am Zielort — für ein Objekt wenige hundert Meter
daneben taugt sie, für eines 5 km weiter nicht.

**Gegenprobe:** Objekt weit weg anfordern (5–10 km) und schauen, ob die gemeldete Höhe von der
tatsächlichen abweicht.

---

## 3. Räumt sie ab, was aus `soll` verschwindet?

Im Admin auf „wegnehmen" klicken. Innerhalb eines Takts (1 s) sollte das Objekt verschwinden.

**Das ist der Kern des Sollzustands-Gedankens:** Die Brügge befolgt keine Befehle, sondern
gleicht ab. Geht eine Anfrage verloren, holt die nächste den Zustand wieder ein.

---

## 4. Was passiert bei einer unbekannten Gattung?

Der Admin lässt nur die fünf bekannten zu — für diesen Test also per curl eine erfinden, oder
im Modul einen Titel verstellen, den MSFS nicht kennt.

**Erwartet:** `steht[].zustand = "fehlgeschlagen"` mit `fehler`, und **kein** erneuter Versuch
im Sekundentakt. Ohne diese Bremse versuchte die Brügge es für immer.

---

## 5. Überlebt ein Objekt einen Flugwechsel?

Objekt setzen, dann im Sim einen anderen Flug laden.

**Erwartet:** Die Brügge räumt beim `FlightLoaded` alles ab und setzt neu, was der Server für
die neue Lage schickt. (Dass die Objekte den Wechsel technisch überleben, ist gemessen — sie
gehören aber zur alten Position des Piloten.)

---

## 6. Was tut sie bei Netzausfall?

WLAN aus, oder den Container kurz anhalten.

**Erwartet:** Nach `gilt_bis_s` (300 s) räumt die Brügge alles ab. Ohne das bliebe stehen, was
der Server längst zurückgenommen hat — für eine Baake hieße das eine Station, die nie
verschwindet.

⚠ Das dauert fünf Minuten. Lohnt sich nur, wenn ohnehin Zeit ist.

---

## 7. Die Drossel

Im Admin den Schieber auf 15 s, dann auf „ganz aus".

**Erwartet:** Der Takt im nginx-Log folgt sofort, ohne Deploy. „Aus" ist 900 s, nicht 0 — eine
Brügge ohne Antwort könnte Abschaltung nicht von Netzausfall unterscheiden.

```
grep 'bruegge/melden' /var/log/nginx/access.log | tail -5 | awk '{print $4}'
```

---

## Was NICHT mehr zu messen ist

Am 11.09.2026 bereits im Flug bestätigt:

- Positionsmeldung über HTTPS aus WASM ✅
- Zuordnung allein über die Position, ohne Anmeldung ✅
- Steigflug (1900 ft, 1044 ft Höhendifferenz gehalten) ✅
- Abfangen (nachlaufende Höhenschranke) ✅
- Absturz und Respawn (Selbstheilung) ✅
- VATSIM-Trennung und Wiederverbindung ✅
- Sprungerkennung beim Laden (0/90, Seattle) ✅

---

## Danach

Ergebnisse in [`probe-msfs/ERGEBNIS.md`](probe-msfs/ERGEBNIS.md), offene Punkte in
[`../docs/offene-aufgaben.md`](../docs/offene-aufgaben.md). Was sich am Vertrag ändert, gehört
in [`PROTOKOLL.md`](PROTOKOLL.md) — **und dann in alle drei Umsetzungen.**
