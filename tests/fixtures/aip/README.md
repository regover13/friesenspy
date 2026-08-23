# Prüfstand für die AIP-Kartenerkennung

**Hier liegen keine echten Kartenblätter, und das ist Absicht.** `regover13/friesenspy` ist ein
öffentliches Repo; die DFS-Sichtflugkarten tragen „© DFS Deutsche Flugsicherung GmbH". Sie hier
abzulegen wäre eine Veröffentlichung — genau das, was die Spec ausschließt (Zugriff nur durch
`forum_login_gate`, kein Export). Messwerte echter Blätter sind dagegen Tatsachen und kein Werk;
sie stehen in `messwerte.json`.

| Datei | Zweck |
|---|---|
| `blatt_bauen.py` | erzeugt synthetische Blätter mit Doppelrahmen, Gradnetz und Beschriftung |
| `messwerte.json` | was 446 echte Blätter am 23.08.2026 ergaben — Referenz für den Erstlauf |

## Synthetische Blätter

Für die Erkennung ist das kein Verlust, sondern ein Gewinn: Ein erzeugtes Blatt ist
deterministisch, und man kann gezielt die Fälle bauen, an denen die Erkennung früher gescheitert
ist. Alle vier sind nachweislich erkannt worden:

```python
from blatt_bauen import blatt_bauen

blatt_bauen()                              # Standardlayout, Feld 132/180/817/865
blatt_bauen(stoerstriche=True)             # Hindernissymbole im Randband (Fall EDCQ)
blatt_bauen(rahmen_kreuzen=True)           # unterbrochene Rahmenlinie (Fall "Berichtigung:")
blatt_bauen(kopf_fuss_linien=True)         # Layoutlinien als Paar -- darf den Rahmen nicht kapern
blatt_bauen(tick_lat_px=54.78, tick_lon_px=32.1)   # feines Gitter (Fall EDAB, 31 Ticks)
```

**Die Beschriftung heißt `breite_links` und `laenge_oben`**, nicht „grad_…": Die Breite steht
im linken Band, die Länge im oberen. Die erste Fassung hatte beide vertauscht — eine Breite
von 54° im Längenband —, und `passung_rechnen` lieferte dann stumm `None`. Namen, die man
verwechseln kann, verwechselt man auch.

Die Ziffernformen in `blatt_bauen.py` sind **nicht** die der DFS. Sie prüfen Segmentierung und
Schablonenvergleich als Verfahren; die echten Schablonen gewinnt `scripts/aip_schablonen.py`
aus den Blättern auf dem Server.

## Messwerte

`messwerte.json` hält je ICAO fest, ob die Karte automatisch gepasst wurde, auf welchem Weg
(`direkt`, `kapitelseite`, `openaip`), das gefundene Kartenfeld, die Rasterabstände und den
Fehler der Gegenprobe. Stand: **410 von 446 gepasst (91,9 %)**, AIRAC 2026AUG20.

Damit ist der Erstlauf von `scripts/aip_bestand.py` überprüfbar: Weicht die Quote deutlich ab,
stimmt etwas nicht — und zwar bevor jemand mit der Handarbeit an den 36 Ausreißern anfängt.
