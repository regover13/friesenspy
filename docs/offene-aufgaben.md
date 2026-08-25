# Offene Aufgaben

Vom Nutzer vorgemerkt, noch nicht begonnen. **Diese Liste ist kein Ideenspeicher** — was hier
steht, ist gewollt; was erledigt ist, wird gelöscht (die Geschichte steht im Changelog).

Am Projekt arbeiten mehrere Sitzungen parallel, auch in der Cloud. Vor dem Start also pullen
und prüfen, ob eine andere die Aufgabe schon erledigt hat.

---

## Sichtflugkarten: die letzten neun, und was die Automatik nicht kann

Stand 25.08.2026: **437 von 446 gepasst (98 %)** — davon **283 rein automatisch (63,5 %)**, der
Rest von Hand. Die beiden Zahlen und warum beide gebraucht werden, stehen in
[`superpowers/specs/2026-08-23-aip-karten-overlay-design.md`](superpowers/specs/2026-08-23-aip-karten-overlay-design.md),
Abschnitt 3.5.

**Nichts davon ist dringend.** Die 437 halten über AIRAC-Wechsel hinweg (`hand_behalten`), und
die neun offenen sind ausnahmslos Plätze mit einem grundsätzlichen Problem, nicht mit einem
Bedienfehler.

- **EDFH, EDMR** — hier liegt in der Quelle **keine Sichtflugkarte**. Nichts zu holen, außer die
  DFS ergänzt eine. Kein Aufwand hineinstecken.
- **EDDF, EDDH, EDDN, EDDS** — große Verkehrsflughäfen mit eigenem Kartentyp (Bewegungskarte
  ohne Gradnetz). Wäre nur mit einer zweiten, andersartigen Erkennung zu lösen; ob das lohnt,
  entscheidet, ob dort überhaupt VFR geflogen wird.
- **EDDG, EDLW** — 1:200 000-Karten, deren Gradnetz von Kartensymbolen überdeckt ist. Die
  Prüfkette lehnt ab (EDDG: 7 px Residuum, zulässig sind 2). **Nicht von Hand erzwingen** — das
  hebelte genau die Sicherung aus, die den Wert der übrigen 437 garantiert.
- **EDCQ** — das *gedruckte* Gitter ist selbst ungenau (bis 11 px, wo sonst 0–2 px gelten).
  Unlösbar, solange die DFS das Blatt nicht neu satzt.

**Wo der Hebel für die Automatik wirklich liegt** (falls jemand die 63,5 % heben will): beim
**Lesen der Zahlen**, nicht beim Finden des Gitters — Rahmen und Raster werden bei rund 92 %
gefunden. Zwei konkrete, in der Nacht beobachtete Ansätze:

1. **Beschriftete Ticks fehlen oft in der Tickliste**, weil die Zahl den Strich unterbricht (bei
   ETND und EDDE waren genau die beschrifteten Positionen die Lücken im sonst gleichmäßigen
   Raster). Die Rasterlücken als Lesepositionen mitzunehmen, würde vermutlich viele Blätter
   erschließen — gegen 283 messen, nicht gegen 437.
2. Alles, was Abschnitt 3.4 der Spec zur Segmentierung sagt, gilt weiter.

## Forum

- Thema heißt noch **„V13 - Platzhirsch"**, live ist V14 „Zettelwirtschaft". Umbenennen hieße,
  den **ersten Beitrag des Themas** zu ändern — dafür fehlt bislang die ausdrückliche Freigabe.
