# Offene Aufgaben

Vom Nutzer vorgemerkt, noch nicht begonnen. **Diese Liste ist kein Ideenspeicher** — was hier
steht, ist gewollt; was erledigt ist, wird gelöscht (die Geschichte steht im Changelog).

Am Projekt arbeiten mehrere Sitzungen parallel, auch in der Cloud. Vor dem Start also pullen
und prüfen, ob eine andere die Aufgabe schon erledigt hat.

---

## Sichtflugkarten: es fehlen noch zwei

Stand 25.08.2026 abends, aus der Datenbank: **444 von 446 gepasst**. Offen sind nur noch
**EDDN** und **EDMR**.

**Die frühere Liste "die letzten neun" war falsch — in beide Richtungen.** Sie stand hier
noch mit 437 und nannte neun Karten als grundsätzlich unlösbar, darunter EDFH, EDDF, EDDH,
EDDS, EDDG, EDLW und EDCQ. Sieben davon hat der Nutzer inzwischen von Hand gesetzt. Die
Begründung, die hier stand ("große Verkehrsflughäfen mit eigenem Kartentyp, Bewegungskarte
ohne Gradnetz"), war zudem sachlich falsch: EDFH etwa trägt auf Seite 3 eine reguläre,
genordete Sichtflugkarte mit vollem Gradnetz, EDDN auf Seite 3 ebenfalls. Die Einordnung
war aus dem *Scheitern der Automatik* erschlossen, nicht aus dem Blatt — geprüft hatte ich
nur die abgelegte Seite, nicht das Kapitel.

**Lehre für die nächste solche Liste:** „die Automatik schafft es nicht" und „es gibt keine
Karte" sind zwei verschiedene Aussagen. Wer die zweite schreibt, muss die Kapitelseiten
angesehen haben.

### EDDN — quer gedruckt

Seite 3 ist eine reguläre Sichtflugkarte, um 90° gedreht gesetzt. Genordet wird sie mit
`--drehen 270`. Die Handpassung ist gerechnet und besteht alle sieben Proben:

```
Breite 299=49:35, 518=49:30, 737=49:25
Länge  192=10:50, 334=10:55, 476=11:00, 618=11:05, 760=11:10, 903=11:15, 1045=11:20
Rahmen 85,238 .. 1147,817   Residuen 0,00 px / 0,67 px   cos-Probe 49,52° gegen 49,50°
```

Warum die Automatik dort scheitert, ist gemessen und gehört zum Rasterlücken-Thema: Die
beschrifteten Ticks fehlen in der Tickliste, weil die Zahl den Strich unterbricht. Damit
fällt die Belegung unter 0,75 und `raster()` greift das Drei- bzw. Doppelte des echten
Abstands (131,25 statt 43,75 px; 56,89 statt 28,44 px).

### EDMR — Koordinate

`airportsdata` kennt EDMR nicht, wie 28 weitere der 446 Plätze. Der wöchentliche
Bestandslauf fällt für sie seit jeher auf OpenAIP zurück (`platz_koordinate`); die
Admin-Endpunkte taten es nicht und antworteten mit **409 „Koordinate des Platzes
unbekannt"** — ausgerechnet bei den Plätzen, für die man den Seitenwähler am ehesten
braucht. Behoben: beide Endpunkte benutzen jetzt dieselbe Auflösung wie der Job.

EDMRs Karte ist Seite 2 (Ottobrunn HEL, 1:50 000, genordet, Ticks im Minutenabstand).

## Forum

- Thema heißt noch **„V13 - Platzhirsch"**, live ist V14 „Zettelwirtschaft". Umbenennen hieße,
  den **ersten Beitrag des Themas** zu ändern — dafür fehlt bislang die ausdrückliche Freigabe.
