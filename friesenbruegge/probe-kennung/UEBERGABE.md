# Übergabe an die Sitzung am Simulator-Rechner

**Für:** eine Claude-Code-Sitzung auf dem Windows-Rechner mit MSFS 2020, MSFS 2024 und den SDKs
**Von:** der Server-Sitzung (VPS), 26.09.2026
**Repo:** `regover13/friesenspy`. Diese Datei liegt in `friesenbruegge/probe-kennung/`. Vorher `git pull`.

---

## Die Aufgabe in einem Satz

**Finde heraus, ob ein WASM-Modul mit den gewöhnlichen C-Dateifunktionen (`fopen`) eine Datei im
`\work`-Ordner seines Pakets ablegen kann, die einen vollständigen Neustart übersteht, und zwar
in MSFS 2020 UND in MSFS 2024.**

Das ist eine Messung, kein Bauauftrag. Ein sauberes „nein, und zwar aus diesem Grund“ ist ein
vollständiges Ergebnis.

## Warum

Die MSFS-FriesenBrügge vergisst ihre Kennung seit 1.14.0 bei jedem Start des Simulators. Der
Server muss sie deshalb bei jedem Start neu über die Position einem Piloten zuordnen. Genau das
ist am 25.09.2026 schiefgegangen (GitHub-Issue #46): Die Brügge des Nutzers bekam die Kennung
seines Nachbarn am Stand und wurde danach bis zum Neustart von MSFS abgewiesen. Die Szenarien
dazu stehen als Kommentar in #46 und #47.

Überlebt die Kennung einen Neustart, meldet die Brügge ab der ersten Meldung, wer sie ist. Der
Server kennt die Bindung an die CID 400 Tage lang. Ein Positionsvergleich wäre dann nur noch
einmal je Installation nötig statt bei jedem Start.

Nutzer, 26.09.2026: *„Das GTN750 hatte auch in MSFS 2020 seine Lizenz gespeichert! Warum können
wir das nicht?!“*

## Was schon versucht wurde, und was nicht

- **Von Anfang an (11.09.2026, `b7050ac`) speicherte die Brügge ihre Kennung mit der neuen
  Datei-API aus `MSFS_IO.h`** (`fsIOOpen`, `fsIOOpenRead`, `fsIOWrite`, `fsIOClose`) unter
  `\work\friesenbruegge.kennung`, hinter dem Schalter `KENNUNG_HAELT`.
- **Diese API gibt es nur im SDK von 2024.** Im SDK von 2020 fehlt `MSFS_IO.h` ganz. Ein Modul,
  das sie importiert, verwirft MSFS 2020 lautlos beim Laden (`ERR_UNKNOWN_BLANK_IMPORT`).
- **Am 16.09.2026 (`b0771bf`, Brügge 1.14.0) ist die Ablage deshalb ersatzlos entfallen**, für ein
  gemeinsames Modul für beide Simulatoren. Begründung im Kopf von `../msfs/bruegge.cpp`
  („EIN MODUL“).
- Die Datei-API war asynchron und hat am 14.09. drei Wettläufe gekostet (`aadf482`). Wer die
  Ablage zurückbringt, liest die zuerst.
- **Nie versucht:** die gewöhnlichen C-Funktionen `fopen`/`fread`/`fwrite`/`fclose` aus der
  wasi-libc, die beide SDKs mitbringen (`WASM\wasi-sysroot`). Übersetzen lässt sich das. **Offen ist,
  ob MSFS 2020 die wasi-Importe annimmt, die `fopen` hereinzieht, und ob `\work` dort ankommt.**
- Das GTN 750 geht einen anderen Weg: Es ist ein JavaScript-Instrument und speichert über
  `SetStoredData`. Genau so hält das FriesenSpy-Kniebrett seit dem 13.08. seine Geräte-ID
  (`docs/efb-panel-debugging.md`). Ein reines WASM-Modul wie die Brügge kommt an diese Ablage
  nicht heran. **Nicht Teil dieser Probe.**

## Was bereitliegt

| Datei | Was sie ist |
|---|---|
| `probe.cpp` | Probemodul, rund 80 Zeilen. Zählt die eigenen Starts in einer Datei, mit drei Schreibweisen des Pfads (`\work\…`, `/work/…`, `work/…`), und schreibt jedes Ergebnis mit `errno` ins Log |
| `probe_bauen.ps1` | Bauskript mit den Schaltern aus `../msfs/bauen.ps1`, danach die Importliste über `../msfs/wasm_pruefen.py`. **Ungetestet**, auf dem Server geschrieben. Weicht etwas ab, gilt `../msfs/bauen.ps1` |

Kein Paket-Skript: Schnüre ein **eigenes Paket** (z. B. `friesenprobe`) nach dem Vorbild von
`../msfs/paket.ps1`. **Nicht** in das Paket `friesenbruegge` legen: Dann teilten sich Probe und
Brügge denselben `\work`-Ordner, und die installierte Brügge des Nutzers würde angefasst.

## Ablauf

1. **Bauen.** `probe_bauen.ps1` ausführen. Die **Importliste** notieren und mit der der aktuellen
   Brügge vergleichen (`python ..\msfs\wasm_pruefen.py ..\msfs\bruegge.wasm`, 19 Importe). Welche
   wasi-Funktionen sind neu (`path_open`, `fd_read`, `fd_seek`, `fd_close`, `fd_prestat_*` …)?
2. **MSFS 2024.** Paket in den Community-Ordner, Simulator starten, Flug laden. Im Log müssen
   die Zeilen `[FriesenProbe]` stehen, dort, wo auch die `[FriesenBruegge]`-Zeilen erscheinen.
   Notieren, welche Schreibweise des Pfads geschrieben hat.
3. **Simulator vollständig beenden** (Prozess weg, nicht nur zurück ins Menü), wieder starten,
   Flug laden. Steht bei derselben Schreibweise **„Start Nr. 2“**? Die Datei auf der Platte suchen
   und den Pfad notieren (unter `…\LocalState\packages\<paketname>\work\` oder ähnlich).
4. **MSFS 2020**, dasselbe. Vorher prüfen, ob `module_init` überhaupt im Log erscheint. Fehlt die
   Zeile, hat MSFS 2020 das Modul wegen der Importe verworfen: Das ist das Ergebnis.
5. **Paket-Update:** Das Probe-Paket löschen und neu hineinlegen (wie ein Pilot, der eine neue
   `friesenbruegge.zip` installiert), neu starten. Zählt der Zähler weiter?
6. Probe-Paket wieder entfernen.

## Nicht tun

- `../msfs/bruegge.cpp` nicht ändern und keine neue `friesenbruegge.zip` bauen oder verteilen.
- Nichts am Server anfassen.
- Keinen Umweg bauen, falls `fopen` scheitert (keine JavaScript-Hülle, kein Kniebrett-Weg).
  Ergebnis festhalten, fertig.

## Nebenfrage, nur falls es sich ohne Aufwand ergibt

**Trennt vPilot die VATSIM-Verbindung, wenn MSFS abstürzt oder hart beendet wird?** Davon hängt
Szenario S7 in #46 ab. **Nicht absichtlich** im Live-Netz herbeiführen, ohne den Nutzer vorher
zu fragen.

## Ergebnis

In diese Ordner als `ERGEBNIS.md`, dann committen und pushen. `friesenbruegge/**` löst keinen
Deploy aus. Hinein gehören:

- SDK, gegen das gebaut wurde
- Importliste der Probe, die neuen Importe gegenüber der Brügge hervorgehoben
- je Simulator und Start die `[FriesenProbe]`-Zeilen im Wortlaut
- die Schreibweise des Pfads, die funktioniert, und der Ort der Datei auf der Platte
- ob die Datei das Paket-Update überlebt
- bei einem Nein: die Fehlermeldung oder `errno` im Wortlaut

## Umgang

Der Nutzer wird geduzt. In Texten für ihn heißt es immer „FriesenBrügge“. Offene Punkte
nummerieren, damit er mit „mach 2“ antworten kann.
