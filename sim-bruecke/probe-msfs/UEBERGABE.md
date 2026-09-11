# Übergabe an die Sitzung am Simulator-Rechner

**Für:** eine Claude-Code-Sitzung auf dem Windows-Rechner mit MSFS
**Von:** der Server-Sitzung (VPS), 11.09.2026
**Repo:** `regover13/friesenspy` — diese Datei liegt in `sim-bruecke/probe-msfs/`

> ⚠ **Der Ordner hieß bis zum 11.09.2026 `msfs-kieker/probe/`.** Wenn du den alten Pfad
> aufgerufen bekommen hast: einmal `git pull`, dann stimmt es wieder. Inhaltlich hat sich am
> Probeflug **nichts** geändert — nur der Spawner ist inzwischen als eigenes, event- und
> simulator-unabhängiges Stück entworfen (Issue #25), und dazu passte der alte Name nicht mehr.

---

## Die Aufgabe in einem Satz

**Finde heraus, ob `SimConnect_AICreateSimulatedObject` ein mitgeliefertes Boot im laufenden
Flug an eine frei gewählte Koordinate setzt — und ob es dort liegen bleibt.**

Mehr nicht. Das ist eine Messung, kein Bauauftrag.

## Warum das die einzige Frage ist

Geplant ist ein neuer Eventtyp „FriesenKieker": Die Gruppe fliegt Stellen ab und zählt
Objekte, die der **Server** dort platziert hat. Das geht nur, wenn sich Objekte zur Laufzeit
setzen lassen.

Zwei Wege sind bereits ausgeschlossen und **brauchen nicht nochmal geprüft zu werden**:

- **Szenerie-Pakete** sind statisch — beim Laden gelesen, zur Laufzeit nicht änderbar.
- **Die vorhandenen Robben** aus `regover13/east-frisian-islands-counting-seals` sind
  **LibraryObjects**, keine SimObjects. Im Quelltext steht es wörtlich
  (`generate_seals.py:22`): *„These are the PLACEABLE GUIDs (not SimObject model GUIDs)"*.
  Ein LibraryObject hat keinen Namen, unter dem man es von außen ansprechen könnte.
- **vPilot** ebenfalls: zeichnet nur, was das VATSIM-Netz meldet, und eine
  Injektionsschnittstelle gibt es nicht.

Deshalb **eigene SimObjects** — und Boote als erste Probe, weil MSFS sie mitbringt: kein
3D-Modell, keine Lizenzfrage, kein Blender.

## ⚠ Die Entscheidungsregel — bitte wirklich beachten

> **Klappt es nicht, lassen wir es.** Wörtliche Nutzerentscheidung vom 11.09.2026:
> *„Wir sollten zuerst sicherstellen, dass 7 funktioniert!! Weil sonst lassen wir es!"*

Es gibt **keinen Ersatzplan und es soll keiner gesucht werden**. Wenn der Weg nicht trägt,
ist ein sauberes „nein, und zwar aus diesem Grund" das vollständige und erwünschte Ergebnis.

Bitte also **nicht**: stundenlang Umwege bauen, ein WASM-Modul anfangen, Szenerie-XML
erzeugen, ein Paket schnüren. Ein paar gezielte Varianten durchprobieren (siehe unten) ist
richtig; ein Ausweichprojekt ist es nicht.

## Was bereitliegt

| Datei | Was sie ist |
|---|---|
| `kieker_probe.py` | Das Probe-Skript, 298 Zeilen, ctypes gegen `SimConnect.dll` |
| `README.md` | Bedienung, Vorbereitung, Deutung der Ergebnisse |
| `UEBERGABE.md` | diese Datei |

**Wichtig: Das Skript ist auf einem Linux-Server geschrieben und dort nie gelaufen.** Es gibt
dort weder Windows noch MSFS noch `SimConnect.dll`. Es ist nach der offiziellen Signatur
gebaut, aber jede Zeile davon ist unerprobt. **Erwarte, dass du es anfassen musst** — das ist
der Hauptgrund, warum diese Sitzung überhaupt vor Ort stattfindet.

### Was daran belegt ist und was nicht

| | Stand |
|---|---|
| `RECV_ID` 1 = EXCEPTION, 2 = OPEN | **gegengeprüft** an eigenen Wireshark-Messungen, s. `regover13/FSEconomy-SimConnect-Stub`, `PROTOCOL_NOTES.md` |
| `RECV_ID` 12 = ASSIGNED_OBJECT_ID | aus dem SDK, **ungeprüft** |
| Exception-Nummern (7 = NAME_UNRECOGNIZED usw.) | aus dem SDK, **ungeprüft** |
| `SIMCONNECT_DATA_INITPOSITION` (6 Doubles, 2 DWORDs) | aus dem SDK, **ungeprüft** |
| Signatur von `SimConnect_Open` / `AICreateSimulatedObject` | aus dem SDK, **ungeprüft** |
| Container-Titel eines Boots | **bewusst nicht geraten** — wird gesucht, s. Schritt 1 |

Deshalb gibt das Skript unbekannte Nummern **roh** aus, statt sie zu verschweigen. Eine
unerwartete Zahl ist ein Befund, kein Fehler.

## Vorgehen

### Schritt 0 — `SimConnect.dll` finden

Drei Wege, der erste ist der einfachste:

1. Die DLL **neben `kieker_probe.py` legen** — dann sucht das Skript nicht.
2. MSFS-SDK installiert? Dann findet das Skript sie über `%MSFS_SDK%`.
3. `--dll <pfad>` angeben.

**Nicht die alte FSX-DLL nehmen** (aus `GAC_32`, Version 10.0.61355.0) — sie kennt
`AICreateSimulatedObject` in dieser Form nicht. Genau diese Verwechslung hat im
`FSEconomy-SimConnect-Stub` schon einmal Zeit gekostet.

**Nützliche Gegenprobe, falls etwas nicht aufgeht:** Welche Funktionen exportiert die DLL
überhaupt? Das beantwortet in zehn Sekunden, ob wir an der richtigen Datei arbeiten:

```
dumpbin /exports SimConnect.dll | findstr /i aicreate
```

Kein `dumpbin` zur Hand? `python -c "import ctypes; d=ctypes.WinDLL('SimConnect.dll');
print(hasattr(d,'SimConnect_AICreateSimulatedObject'))"` tut es auch.

### Schritt 1 — echte Container-Titel holen

Titel unterscheiden sich zwischen MSFS 2020 und 2024. Raten ist sinnlos, sie stehen im
Klartext auf der Platte:

```
py kieker_probe.py --titel-suche
```

Das durchsucht die `SimObjects`-Ordner nach `sim.cfg`. Dauert ein paar Minuten. Schneller von
Hand: `...\Packages\Official\...\SimObjects\Boats\<irgendwas>\sim.cfg`, Zeile `title = ...`.

### Schritt 2 — Flug laden, dann setzen

**Ein Flug muss geladen sein**, das Hauptmenü reicht nicht. Am besten in Ostfriesland, damit
Schritt 3 kurz ist.

```
py kieker_probe.py --titel "<der gefundene Titel>"
```

Standardziel ist die **Kachelotplate** (53,66 N / 6,98 O), Sandbank westlich von Juist. Mit
`--lat` / `--lon` beliebig anders — sinnvoll, wenn der geladene Flug woanders steht.

### Schritt 3 — hinsehen (der Teil, den kein Rückgabewert ersetzt)

**Die Objekt-ID beweist nichts Sichtbares.** Der Simulator kann ein Objekt anlegen und
trotzdem nichts zeichnen. Also per Slew oder im Anflug hin:

- Liegt das Boot da?
- Liegt es nach **zwei Minuten immer noch** da? (Die KI-Engine räumt manches wieder ab.)
- Liegt es **auf** dem Wasser oder darin/darüber?

### Schritt 4 — NUR wenn Schritt 3 geklappt hat: läuft so etwas unbemerkt?

Diese Frage ist am 11.09.2026 dazugekommen und **zweitrangig** — sie lohnt sich erst, wenn
ein Objekt nachweislich entsteht. Dann aber entscheidet sie über den Zuschnitt des Pakets.

Hintergrund: Wenn der Spawner ohne Zutun des Piloten läuft, kann er **auch die Position an
den Server melden** (Issue #23) — besser als die EFB-App, die dafür geöffnet sein muss. Dann
gäbe es ein Paket statt zwei. Das setzt aber voraus, dass er von selbst startet und niemanden
stört.

Drei Teilfragen, alle billig zu beantworten:

1. **Gibt es `exe.xml` in MSFS 2024 noch?** Nachsehen, ob die Datei existiert und ob etwas
   darin steht:
   `%APPDATA%\Microsoft Flight Simulator 2024\exe.xml` — und die 2020er-Pfade zum Vergleich.
   Existiert sie samt Einträgen anderer Addons, ist der Weg lebendig.
2. **Startet ein Eintrag wirklich mit?** Einen harmlosen Test eintragen (etwas, das nur eine
   Datei mit Zeitstempel schreibt), Sim starten, nachsehen ob die Datei da ist.
3. **Sieht der Pilot etwas davon?** Konsolenfenster? Windows-Defender- oder
   SmartScreen-Meldung bei einer unsignierten Datei? Das ist kein Schönheitsfehler —
   es entscheidet, ob man das Clubmitgliedern zumuten kann.

**Bitte nichts bauen, nur nachsehen und berichten.** Und: **kein Eintrag in `exe.xml` darf
stehen bleiben**, der nicht bewusst dort hingehört — die Datei startet Programme bei jedem
Simulatorstart.

## Die wahrscheinlichen Stolpersteine, mit Gegenmittel

| Symptom | Vermutung | Was zu probieren ist |
|---|---|---|
| `SimConnect_Open` wirft | kein Flug geladen, oder falsche DLL | Flug laden; Export-Gegenprobe aus Schritt 0 |
| `EXCEPTION 7` (NAME_UNRECOGNIZED) | Titel stimmt nicht | Schritt 1 wiederholen, anderen Titel |
| `EXCEPTION 2` (SIZE_MISMATCH) | **mein Struct-Layout ist falsch** | `InitPosition` prüfen: 6× `c_double`, dann 2× `DWORD`; ggf. `_pack_` testen |
| `EXCEPTION 28/29` (OBJECT_CONTAINER / OBJECT_AI) | Sim lehnt die Erzeugung ab | `OnGround=0` mit echter `Altitude` testen; anderen Objekttyp |
| `KEINE ANTWORT` | Aufruf verpufft folgenlos | Wartezeit hoch (`--warten 30`); ist das ein eigener Befund |
| Objekt-ID da, nichts sichtbar | Höhe/Lage falsch | `Altitude` auf echte Geländehöhe; `OnGround` umschalten; näher herangehen |
| Objekt verschwindet nach Sekunden | KI-Engine räumt auf | **wichtiger Befund** — bitte genau festhalten, wie lange es blieb |

Ein Fehler im Skript ist **erwartbar und in Ordnung**. Reparieren, weiterprobieren, und die
Reparatur im Skript festhalten — sie ist selbst ein Ergebnis.

## ⚠ Nicht pushen, solange du im Simulator bist

Ein Push auf `main` löst GitHub Actions aus, baut das Image neu und **startet den
FriesenSpy-Container neu**. Wer dann mit offenem Kniebrett im Flug ist, bekommt ein schwarzes
Tablet — das ist in diesem Projekt schon passiert und eine stehende Regel.

`sim-bruecke/` landet zwar gar nicht im Image (der Dockerfile kopiert nur `app/` und
`scripts/`), der Neustart passiert trotzdem.

**Also: lokal committen, nicht pushen.** Der Nutzer oder die Server-Sitzung pusht später.

## Was zurückgemeldet werden soll

Kurz und in dieser Reihenfolge — daraus entscheidet sich, ob der Eventtyp gebaut wird:

1. **Die Antwort:** Boot sichtbar und bleibt liegen — ja oder nein?
2. **Die rohe Ausgabe** des Skripts, vollständig (auch die unbekannten RECV-Nummern).
3. **Der Container-Titel**, der funktioniert hat — er ist der Startwert für alles Weitere.
4. **Was am Skript geändert werden musste** (Diff oder Beschreibung).
5. Falls es lief: **Wie lange blieb das Objekt?** Und ruckelte etwas?
6. Falls es nicht lief: **An welchem Schritt genau** und mit welcher Fehlernummer.

Punkt 3 und 4 sind mehr wert als ein „hat geklappt" — sie sind das, worauf das Paket später
aufbaut.

## Ausdrücklich NICHT Teil dieser Aufgabe

- Kein `sim-bruecke`-Paket bauen, keine `manifest.json`, kein `layout.json`.
- Kein WASM-Modul (das ist eine eigene, spätere Messfrage).
- Keine Änderung am FriesenSpy-Server, an `app/` oder an der Datenbank.
- Keine Robben-Modelle, kein Blender.
- Nicht klären, wie viele Objekte der Sim verträgt — erst wenn eines funktioniert.
- Kein `exe.xml`-Autostart.

## Wenn du mehr Zusammenhang brauchst

Die vollständige Spec steht in `docs/superpowers/specs/2026-09-11-friesenkieker-design.md`
(1000 Zeilen). **Für diese Aufgabe reicht Abschnitt 2** („Der Probeflug ist das Tor") und
Abschnitt 13 („Das Paket"). Der Rest beschreibt die Server-Seite und ist hier nicht nötig.
