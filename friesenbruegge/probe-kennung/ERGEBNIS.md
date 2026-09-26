# Ergebnis: Hält eine `fopen`-Datei im `\work`-Ordner einen Neustart?

**Ja, in MSFS 2020 und in MSFS 2024.** Gemessen am 26.09.2026 auf dem Simulator-Rechner.
Die gewöhnlichen C-Dateifunktionen (`fopen`/`fread`/`fwrite`/`fclose`) genügen. `MSFS_IO.h` wird
nicht gebraucht, und ein einziges Modul mit denselben Importen wird von beiden Simulatoren
geladen.

## Kurzfassung

| | MSFS 2020 | MSFS 2024 |
|---|---|---|
| Modul mit `fopen`-Importen geladen | ja | ja |
| Schreiben im laufenden Flug | ja | ja |
| Datei nach Neustart des Simulators noch da | **ja** (3 → 6) | **ja** (3 → 6) |
| Datei nach Löschen und Neuablegen des Pakets noch da | **ja** (6 → 9) | **ja** (6 → 9) |
| Ort der Datei | `LocalState\packages\friesenprobe\work\probe_starts.txt` | `LocalState\WASM\MSFS2024\friesenprobe\work\probe_starts.txt` |

Beide Orte liegen unter `%LOCALAPPDATA%\Packages\<Simulator-Paket>\`
(2020: `Microsoft.FlightSimulator_8wekyb3d8bbwe`, 2024: `Microsoft.Limitless_8wekyb3d8bbwe`) und
**außerhalb** des Community-Ordners. Deshalb überlebt die Datei das Löschen des Pakets. Die Ordner
der beiden Simulatoren sind getrennt: Eine Kennung, die MSFS 2020 schreibt, sieht MSFS 2024 nicht.

## Bauen

- SDK: **MSFS-2020-SDK** (`D:\MSFS SDK`), wie bei der Brügge. `probe_bauen.ps1` lief ohne Änderung.
- `probe.wasm`: 40 629 Bytes. `wasm_pruefen.py`: Tabelle exportiert, kein `__stack_chk_*`.

### Importliste der Probe (11)

Neue Importe gegenüber der Brügge sind mit „(neu)“ markiert. Die Brügge hat 19 Importe, davon vier wasi:
`fd_close`, `fd_seek`, `fd_write`, `commit_pages`.

```
wasi_snapshot_preview1::fd_close
wasi_snapshot_preview1::fd_fdstat_get            (neu)
wasi_snapshot_preview1::fd_fdstat_set_flags      (neu)
wasi_snapshot_preview1::fd_prestat_get           (neu)
wasi_snapshot_preview1::fd_prestat_dir_name      (neu)
wasi_snapshot_preview1::fd_read                  (neu)
wasi_snapshot_preview1::fd_seek
wasi_snapshot_preview1::fd_write
wasi_snapshot_preview1::path_open                (neu)
wasi_snapshot_preview1::proc_exit                (neu)
wasi_snapshot_preview1::commit_pages
```

**Sieben neue Importe: `path_open`, `fd_read`, `fd_fdstat_get`, `fd_fdstat_set_flags`,
`fd_prestat_get`, `fd_prestat_dir_name`, `proc_exit`.** Beide Simulatoren haben sie
angenommen. Die Befürchtung der Übergabe, MSFS 2020 verwerfe das Modul wegen dieser Importe
lautlos, hat sich nicht bestätigt.

## Die Schreibweise des Pfads

**Alle drei Schreibweisen (`\work\…`, `/work/…`, `work/…`) landen in derselben Datei.** Im ersten
Start zählt der Zähler deshalb 1, 2, 3 statt dreimal 1: Jede Schreibweise liest, was die vorige
geschrieben hat. Für die Brügge genügt eine, z. B. `\work\friesenbruegge.kennung` wie in der
früheren Fassung, oder `/work/…`.

**`errno` bei fehlender Datei ist 29 („I/O error"), nicht `ENOENT`.** Das war MSFS 2024 im ersten
Start beim Lesen von `\work\probe_starts.txt`, das noch nicht existierte. Wer „Datei fehlt" als
`errno == ENOENT` abfragt, erkennt den Fall nicht. **Ein Lesefehler heißt hier: keine Kennung,
neu zuordnen** — und nicht: Ablage kaputt.

## Die Log-Zeilen

**MSFS 2024, Start 1** (Console, vom Nutzer eingefügt):

```
[probe.wasm] [FriesenProbe] module_init -- Probe fuer die Ablage im \work-Ordner
[probe.wasm] [FriesenProbe] \work\probe_starts.txt: nicht lesbar, errno=29 (I/O error)
[probe.wasm] [FriesenProbe] \work\probe_starts.txt: Start Nr. 1 geschrieben (1 Bytes, fclose=0)
[probe.wasm] [FriesenProbe] /work/probe_starts.txt: gelesen '1' (1 Bytes)
[probe.wasm] [FriesenProbe] /work/probe_starts.txt: Start Nr. 2 geschrieben (1 Bytes, fclose=0)
[probe.wasm] [FriesenProbe] work/probe_starts.txt: gelesen '2' (1 Bytes)
[probe.wasm] [FriesenProbe] work/probe_starts.txt: Start Nr. 3 geschrieben (1 Bytes, fclose=0)
```

**MSFS 2024, nach vollständigem Neustart:**

```
[probe.wasm] [FriesenProbe] module_init -- Probe fuer die Ablage im \work-Ordner
[probe.wasm] [FriesenProbe] \work\probe_starts.txt: gelesen '3' (1 Bytes)
[probe.wasm] [FriesenProbe] \work\probe_starts.txt: Start Nr. 4 geschrieben (1 Bytes, fclose=0)
[probe.wasm] [FriesenProbe] /work/probe_starts.txt: gelesen '4' (1 Bytes)
[probe.wasm] [FriesenProbe] /work/probe_starts.txt: Start Nr. 5 geschrieben (1 Bytes, fclose=0)
[probe.wasm] [FriesenProbe] work/probe_starts.txt: gelesen '5' (1 Bytes)
[probe.wasm] [FriesenProbe] work/probe_starts.txt: Start Nr. 6 geschrieben (1 Bytes, fclose=0)
```

**MSFS 2020: keine Console-Zeilen erfasst.** Der Beleg ist die Datei selbst, gelesen von der Platte
nach jedem Flug: nach Start 1 der Wert `3`, nach dem Neustart `6`, nach dem Paket-Update `9`. Das
ist dieselbe Folge wie in 2024 und beweist, dass `module_init` lief und die Datei gelesen und
geschrieben wurde. Welche Schreibweise im Einzelnen las, ist für 2020 nicht belegt.

## Ablauf der Messung

| Schritt | 2024 | 2020 |
|---|---|---|
| Start 1, Flug geladen | `3` | `3` |
| Simulator beendet, neu gestartet, Flug geladen | `6` | `6` |
| Paket aus `Community\` gelöscht, neu abgelegt, Simulator neu, Flug | `9` | `9` |

Den ersten Neustart in 2024 hat der Nutzer selbst ausgelöst. Alle übrigen liefen per
`Stop-Process -Force` (harter Abbruch des Prozesses, kein sauberes Beenden) und Neustart über
`shell:AppsFolder`. Die Datei hat
den harten Abbruch überstanden. Sie war allerdings mindestens eine Minute vorher geschrieben und
geschlossen worden.

## Was NICHT gemessen ist

1. **Ein Absturz während des Schreibens.** Die Probe schreibt einen Byte in `module_init` und
   schließt sofort. Wer eine längere Datei schreibt, sollte sie atomar ersetzen (in eine
   `.neu`-Datei, dann umbenennen), sofern `rename` in `\work` geht — auch das ist ungeprüft.
2. **Die Steam-Fassung von MSFS 2020/2024.** Gemessen ist die Store-Fassung (`Microsoft.*`-
   Pakete). Der `\work`-Ordner liegt bei Steam an anderer Stelle; das Verfahren dürfte gleich
   sein, ist aber nicht belegt.
3. **Ob die Datei erhalten bleibt, wenn der Nutzer das Paket über den Content Manager statt per
   Ordner tauscht.** Der Ablauf „Ordner löschen, neu hineinlegen" ist gemessen.
4. **Der Aufräum-Fall:** Der Ordner `LocalState\…\friesenprobe\work` bleibt nach dem Löschen des
   Pakets liegen. Das heißt für die Brügge: Wer sie deinstalliert und Monate später neu
   installiert, findet die alte Kennung noch vor. Der Server kennt die Bindung 400 Tage lang, danach
   muss neu gematcht werden. Eine Kennung, die der Server nicht mehr kennt, muss die Brügge
   verwerfen und neu anfragen können.

## Folgerung für die Brügge

Die Ablage der Kennung ist wieder möglich, und zwar ohne `MSFS_IO.h`, also im **einen** Modul für
beide Simulatoren („EIN MODUL" in `../msfs/bruegge.cpp`). Sie braucht `fopen`/`fread`/`fwrite`/
`fclose` und keinen der Wettläufe der asynchronen Datei-API (`aadf482`). Die Probe hat keinen
Bauauftrag: Wie `KENNUNG_HAELT` zurückkommt, ist eine eigene Entscheidung.

Aufgeräumt (26.09.2026): Das Probe-Paket `friesenprobe` ist aus beiden Community-Ordnern entfernt und
die `friesenprobe`-Ordner unter `LocalState` sind gelöscht. **Das Löschen des Pakets allein hat sie
nicht mitgenommen:** Dort lagen neben der `work`-Datei auch die vom Simulator übersetzten Module
(`.dll`, `.lib`, `.obj`, `.cache`, in 2024 auch `.pdb`). Wer die FriesenBrügge deinstalliert, lässt
also mehr als nur die Kennung zurück. Festgehalten in #46.
