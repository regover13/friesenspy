# Offene Aufgaben

Vom Nutzer vorgemerkt, noch nicht begonnen. **Diese Liste ist kein Ideenspeicher** — was hier
steht, ist gewollt; was erledigt ist, wird gelöscht (die Geschichte steht im Changelog).

Am Projekt arbeiten mehrere Sitzungen parallel, auch in der Cloud. Vor dem Start also pullen
und prüfen, ob eine andere die Aufgabe schon erledigt hat.

---

## AIP-Kartenblätter: was noch von Hand durchzusehen ist

Stand 31.08.2026, aus der Datenbank. **Die beiden früher hier offenen Sichtflugkarten (EDDN,
EDMR) sind gepasst** — der Nutzer hat sie von Hand gesetzt.

Nach dem Rückbau der Automatik (31.08.2026) sagt der Status, ob ein **Mensch** die Karte
angesehen hat. Danach steht:

| Sorte | Status | Zahl | Was zu tun ist |
|---|---|---|---|
| Sichtflugkarte | `gepasst` | 171 | nichts |
| Sichtflugkarte | `auto` | 275 | durchsehen; bestätigen macht daraus `gepasst` |
| Flugplatzkarte | `auto` | 30 | dito — von Claude gesetzt, vom Nutzer ungeprüft |
| Flugplatzkarte | `offen` | 10 | Blatt liegt vor, Lage fehlt |
| Rollkarte | `auto` | 38 | durchsehen |
| Rollkarte | `offen` | 32 | Blatt liegt vor, Lage fehlt |

**`auto` heißt ungeprüft, nicht falsch.** Der Status stirbt aus, sobald der Nutzer eine Karte
durchsieht; neu entsteht er nur, wenn er Claude eine Passung aufträgt.

**Die 336 Plätze ohne Flugplatzkarten-Zeile stehen als „nicht nachgesehen".** Der alte
Bestandslauf hat sie durchaus geprüft und dort kein Blatt in Flugplatzkarten-Farbe gefunden —
dieses Ergebnis wurde aber nie festgehalten, es fiel mit der Automatik weg. Das ist kein
Datenverlust, sondern die ausdrückliche Absicht: „Vielleicht finde ich ja eine geeignete
Karte, die du nicht gefunden hast." Wer nachsieht und keine findet, hält das jetzt mit
„keine passende Seite" fest — dann steht dort `nicht gefunden` statt „nicht nachgesehen".

**Die 13 Plätze mit auffälligen OurAirports-Längen** (EDAK, EDAZ, EDBH, EDPH, EDSI, EDMB,
EDLA, EDQA, EDNG, EDQC, EDRB, EDLP, dazu EDDN/EDDS) wurden beim maschinellen Passen
übersprungen, weil dort Stopways in derselben Grauabstufung wie die Bahn gezeichnet sind und
die Längenmessung verfälschten (EDDV: 2784 m für eine 2340-m-Bahn). Von Hand ist das kein
Hindernis — man klickt die Schwellen, statt sie zu messen.

## Forum

- Thema heißt noch **„V13 - Platzhirsch"**, live ist V14 „Zettelwirtschaft". Umbenennen hieße,
  den **ersten Beitrag des Themas** zu ändern — dafür fehlt bislang die ausdrückliche Freigabe.
