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

## X-Plane mitdenken (vorgemerkt 11.09.2026)

**Alles, was gerade an Simulator-Anbindung entworfen wird, setzt stillschweigend MSFS voraus.**
Der Nutzer hat vorgemerkt, dass X-Plane mitgedacht werden muss — **bevor** das erste Paket
gebaut wird, nicht danach.

Betroffen sind zwei laufende Vorhaben:

- **#20 FriesenKieker** — der Spawner, der Objekte setzt. Hängt an `SimConnect`, das es in
  X-Plane nicht gibt.
- **#23 Kniebrett meldet die Position zurück** — hängt heute an der MSFS-2024-EFB-App.

**Warum das jetzt zählt und nicht später:** Nur **4 von 61 Piloten** haben überhaupt eine
Kniebrett-Gerätebindung (`panel_devices`, Stand 11.09.2026, alle vier in den letzten 60 Tagen
aktiv). Ein Weg, der ausschließlich über die MSFS-2024-EFB-App führt, erreicht also einen sehr
kleinen Teil der Gruppe. Wie viele X-Plane fliegen, **wissen wir nicht** — der VATSIM-Feed
meldet den Simulator nicht. Das ist die erste zu klärende Frage, und sie ist eher im Forum zu
beantworten als durch Messen.

### Was sicher ist und was nicht

**Sicher unproblematisch: die Server-Seite.** Wertung, Deckungsprüfung, Endpunkte und
Datenmodell des Kiekers sind simulator-agnostisch — sie rechnen mit Koordinaten, Höhe und
Zeit. Auch der Positions-Endpunkt aus #23 fragt nicht, wer meldet. **Dort ist nichts
verbaut.**

**Simulator-spezifisch ist ausschließlich das Paket.** Der ursprünglich vorgesehene Ordnername
`msfs-kieker/` schrieb MSFS fest; er heißt seit dem 11.09.2026 **`sim-bruecke/`**, und der
MSFS-Probeflug liegt darin als `probe-msfs/`. Der Entwurf dazu steht in **#25** — eine
event-unabhängige Brücke, die für alle drei Simulatoren dasselbe Protokoll spricht.

### Was ich dazu weiß — und was davon ungeprüft ist

Nicht am Gerät nachgesehen, nur aus allgemeiner Kenntnis; **vor jeder Planung zu bestätigen:**

| Frage | MSFS | X-Plane (unbestätigt) |
|---|---|---|
| Objekte zur Laufzeit setzen | `SimConnect_AICreateSimulatedObject` | `XPLMInstance`-API (`XPLMCreateInstance` + `XPLMLoadObject`) — scheint gut zu passen |
| Eigene Position lesen | SimVars | Datarefs `sim/flightmodel/position/latitude` / `longitude` / `elevation` |
| Höhe über Grund | nur über Umwege | `sim/flightmodel/position/y_agl` — **direkt vorhanden** |
| Erweiterungssprache | WASM / externes Programm | XPLM-Plugin (C), oder XPPython3 |
| Tablet-Oberfläche wie das EFB | ja (MSFS 2024) | kein Gegenstück |

**Ein Punkt sticht heraus:** X-Plane liefert die **Höhe über Grund direkt**. Die Spec zu #20
musste sich in Abschnitt 4.2 ausdrücklich auf MSL beschränken, weil FriesenSpy kein
Geländemodell hat. Für X-Plane fiele diese Einschränkung weg — was den Kieker über Land
(Norwegen, Berge) erst richtig brauchbar machte. Das ist ein Argument **für** X-Plane, nicht
nur eine Pflichtübung.

### Erst zu klären, bevor etwas gebaut wird

1. Wer in der Gruppe fliegt X-Plane? (Forum, nicht messbar.)
2. Lohnt sich ein zweites Paket überhaupt für diese Zahl?
3. Falls ja: Ordnerstruktur und Namensgebung **vor** dem ersten Paket-Commit festlegen.
4. Der Positions-Endpunkt (#23) sollte von vornherein so beschrieben werden, dass ein
   X-Plane-Plugin ihn ohne Änderung bedienen kann — das kostet jetzt nichts.

## Forum

- Thema heißt noch **„V13 - Platzhirsch"**, live ist V14 „Zettelwirtschaft". Umbenennen hieße,
  den **ersten Beitrag des Themas** zu ändern — dafür fehlt bislang die ausdrückliche Freigabe.
