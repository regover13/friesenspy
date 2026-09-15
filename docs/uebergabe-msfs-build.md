# Übergabe an eine LOKALE Session (Windows) — FriesenBrügge bauen

> ## ✅ ERLEDIGT am 15.09.2026 abends — und der Verdacht war falsch
>
> **Kein BOM.** `layout.json` und `manifest.json` beginnen beide mit `7B 0D 0A 20` (`{\r\n␣`).
> Der Zehn-Sekunden-Griff hat den Build also nicht überflüssig gemacht.
>
> **Auch die drei Build-Fallen waren es nicht** — und das ließ sich ohne Simulator messen:
> Die Import- und Exporttabelle der installierten `bruegge.wasm` zeigt `__indirect_function_table`
> exportiert (Falle 2 aus), kein `__stack_chk_*` unter den 21 Importen (Falle 1 aus), alle
> SimConnect-Funktionen als `env::`-Importe (Falle 3 aus), `module_init` und `module_deinit`
> exportiert. Das Paket war formal einwandfrei: 64 Einträge in der `layout.json`, null
> Größenabweichungen gegen die Platte.
>
> **Die Ursache stand derweil in Issue #38, bestätigt und ungenutzt.** `g_takt_s` wurde beim
> Weltwechsel nicht zurückgesetzt: Wer einmal auf 900 s gedrosselt war, kam nur über einen
> Neustart des Simulators zurück — der Ausschalter war eine Einbahnstraße. Das ist jetzt
> behoben (Brügge **1.11.0**), mit `g_vertrag_tot` als Ausnahme für den toten Vertrag nach
> einem `426`.
>
> **Ein Punkt des Auftrags ist so nicht baubar:** „`SimConnect_Open` im Sekundentakt
> wiederholen" braucht einen Taktgeber, und den hat ein reines WASM-Modul ausschließlich
> über SimConnect selbst. In keinem der 21 SDK-Header (`WASM\include\MSFS`) steht ein Frame-
> oder Timer-Callback für Module; `MSFS_Events.h` kennt nur Key-Events. Gebaut sind deshalb
> drei Sofortversuche und — der eigentliche Gewinn — Logzeilen.
>
> **Punkt 3 ist halb:** Das Panel (2.3.0) sendet die drei Werte, gelesen werden müssen sie in
> `app/static/index.html:9021`. Das war dieser Sitzung gesperrt; s. `COORDINATION.md`.
>
> **Noch nicht ausgeliefert.** Beide Pakete liegen im Community-Ordner und warten auf den
> Kontrollstart. 2723 Tests grün, acht neue Regressionstests einzeln gegengeprüft.

**Stand: 15.09.2026, abends.** Geschrieben von der Server-Session auf dem VPS. Sie kann alles
außer einem: das MSFS-WASM-Modul bauen. Dafür braucht es das MSFS-SDK, und das ist
proprietär — anders als das X-Plane-SDK, das der Workflow `bruegge-xplane.yml` frei per URL
zieht.

---

## ⚠ ZUERST MESSEN, NICHT BAUEN

Es gibt einen dringenden Verdacht, der **keinen Build braucht** und ihn womöglich überflüssig
macht. Er kostet zehn Sekunden:

```powershell
$p = "$env:LOCALAPPDATA\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community\friesenbruegge"
Format-Hex -Path "$p\layout.json"   -Count 4
Format-Hex -Path "$p\manifest.json" -Count 4
```

| Ergebnis | Bedeutung |
|---|---|
| `7B 22 ...` (`{"`) | in Ordnung — weiter bei „Der eigentliche Auftrag" |
| `EF BB BF ...` | **gefunden.** UTF-8-BOM. Kein Build nötig — `paket.ps1` neu laufen lassen, es schreibt seit dem 12.09. ohne BOM und prüft sich selbst |

**Warum das der erste Griff ist:** Genau dieser Fehler hat am 12.09.2026 schon einmal einen
ganzen Tag gekostet. MSFS registriert und mountet das Paket, führt es in der `Content.xml`
als „Activated", kann die `layout.json` aber nicht parsen — findet null Inhalte und sieht die
`.wasm` nie. **Keine Fehlermeldung, keine Logzeile.** Steht alles in
`friesenbruegge/MESSLISTE.md`, Abschnitt „Zuerst: lädt das Modul überhaupt?".

---

## Was heute gemessen wurde (der Anlass)

Die FriesenBrügge des Nutzers (CID 1602713, FRS49) hat **88 Minuten lang keine einzige
Anfrage** an den Server geschickt. Gemessen am Container, nicht am nginx-Log — wichtig, weil
erfolgreiche Brügge-Meldungen bewusst nicht protokolliert werden (`fs_bruegge_loggen`):

```bash
docker logs friesenspy-friesenspy-1 --since 3m 2>&1 | grep -c "bruegge/melden"     # 0
docker logs friesenspy-friesenspy-1 --since 3m 2>&1 | grep -c "kniebrett/melden"   # 162
```

**Im selben Simulator, im selben Zeitraum, meldete das EFB-Panel 1587-mal.** MSFS lief also,
der Server war erreichbar, die Verbindung stand. Nur die Brügge schwieg.

Ausgeschlossen wurde außerdem:

| geprüft | Ergebnis |
|---|---|
| Server lehnt ab? | nein — es kommt gar keine Anfrage an |
| VATSIM nötig? | nein — sie meldet auch ohne, der Server lehnt dann nur ab |
| Aus-Takt (900 s) schuld? | nein — 88 Minuten sind sechsmal 900 s |
| Wache gegen hängende Anfragen fehlt? | nein — `anfrage_bewachen()` wird in `sekunde()` gerufen |
| Modul nicht installiert? | nein — Package wird registriert und gemountet |

**Der auffälligste Befund** stammt aus zwei Logs desselben Nutzers, an verschiedenen Starts:

| Zeile | Start A | Start B |
|---|---|---|
| `WASM: Module path is ...bruegge.wasm` | ✅ | ✅ |
| `WASM: Warning get ... function pointer` (5×) | ✅ | ❌ |
| `WASM: Module bruegge.wasm loaded...` | ✅ | ❌ |
| `WASM: Module bruegge.wasm initialized.` | ✅ | ❌ |

In Start B wurde das Modul **gar nicht geladen** — und genau das passt zum BOM-Verdacht oben.

---

## Der eigentliche Auftrag (falls das Modul lädt)

Drei Änderungen in `friesenbruegge/msfs/bruegge.cpp`, nach Dringlichkeit:

### 1. Die Brügge muss sagen, dass sie lebt

**Sie ist das einzige Modul im Simulator ohne jede Lebensäußerung.** Zum Vergleich, aus dem
Log des Nutzers:

```
[CampOutModule.wasm]  Connecting to SimConnect...
[CampOutModule.wasm]  SimConnect connected.
[gofishmodule.wasm]   [GF][INFO] SimConnect connected.
[flowmodule.wasm]     [FL][INFO] SimConnect registrations complete.
```

Die Brügge: nichts. Kein einziges `printf` im ganzen Quelltext. Deshalb hat die Suche heute
Stunden gedauert statt Sekunden.

**Zu ergänzen:** je eine Zeile beim geglückten und beim misslungenen Start, nach demselben
Muster wie die anderen Module (`[FriesenBruegge] ...`).

### 2. `SimConnect_Open` braucht einen Wiederholversuch

```c
extern "C" MSFS_CALLBACK void module_init(void) {
    if (SimConnect_Open(&g_sim, "FriesenBruegge", nullptr, 0, 0, 0) != S_OK) return;
```

**Schlägt es fehl, kehrt `module_init` zurück und es gibt keinen zweiten Versuch** — das
Modul bleibt geladen und tut für den Rest der Sitzung nichts. Von außen genau das Bild, das
wir messen. Ob es hier zutrifft, ist unbewiesen; der stumme Abbruch ist aber in jedem Fall
ein Mangel.

**Vorschlag:** bei Fehlschlag im Sekundentakt erneut versuchen, mit einer Logzeile beim
ersten Fehlschlag (nicht bei jedem — sonst flutet es die Konsole).

### 3. Drei fehlende SimVars (für die Server-Seite)

Das EFB-Panel liest heute nur fünf Werte, die Brügge acht. Diese drei fehlen dem **Panel**
(`msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.tsx`, nicht der Brügge):

| SimVar | wofür |
|---|---|
| `PLANE ALT ABOVE GROUND` | echtes AGL statt aus der Platzhöhe geschätztem |
| `SIM ON GROUND` | „am Boden", heute hartkodiert `false` |
| `VERTICAL SPEED` | Steigrate, heute im Browser aus zwei Höhen geschätzt |

**Warum das auf dem Server hängt:** Solange sie fehlen, ist die Brügge die reichere Quelle —
und nur deshalb hat sie bei gleichzeitigem Betrieb den Vortritt. Sind sie da, sind beide
Quellen gleichwertig, und dann gehört das Kniebrett nach vorn (es kennt die Identität ohne
Raten und kostet den Server keinen einzigen Datenbankzugriff). Das ist Punkt 5 und 6 der
Server-Liste.

⚠ **Das ist ein Panel-Release, kein Brügge-Release** — zwei verschiedene Pakete
(`friesenspy-efb.zip` bzw. `friesenbruegge.zip`), keines zieht das andere nach.

---

## Der Build

```powershell
cd <repo>\friesenbruegge\msfs
.\bauen.ps1              # gegen das MSFS-2024-SDK
.\bauen.ps1 -Fuer2020    # gegen das 2020er
```

Das Skript erwartet das SDK unter `$env:MSFS2024_SDK` bzw. `C:\MSFS 2024 SDK`.

### Drei Fallen, alle schon einmal zugeschnappt — sie stehen als Kommentar im Skript

| Flag | ohne es passiert |
|---|---|
| `/GS-` + `-fno-stack-protector` | `ERR_UNKNOWN_BLANK_IMPORT: __stack_chk_fail`, Modul wird **vor** dem Start verworfen |
| `--export-table` + `--growable-table` | `WASM: Error getting indirect function table` — erst beim Callback |
| `--allow-undefined` | SimConnect-Funktionen sind beim Linken absichtlich unaufgelöst |

**Alle drei sehen von außen gleich aus: ein Modul, das nichts tut.** Sichtbar wird es nur in
der DevMode-Konsole.

### Nach dem Bau

1. **Simulator neu starten** — Community-Pakete liest er ausschließlich beim Start
2. In der DevMode-Konsole auf die eine Zeile achten:
   ```
   WASM: Module bruegge.wasm loaded
   ```
   Kommt sie nicht, ist jede weitere Messung sinnlos
3. Gegenprobe vom Server aus (die Server-Session kann das):
   ```bash
   docker logs friesenspy-friesenspy-1 --since 2m 2>&1 | grep -c "bruegge/melden"
   ```
   Erwartet: rund 60 je Minute je Brügge

---

## Was NICHT zu tun ist

- **Nicht am Protokoll ändern.** Der Vertrag zwischen Brügge und Server steht in
  `friesenbruegge/PROTOKOLL.md`; eine Änderung dort braucht beide Seiten und eine Absprache.
- **Nicht das ZIP auf den Server laden.** Aus `bruegge-xplane.yml`: *„Ein Paket, das gerade
  erst gebaut wurde, ist noch nicht im Simulator geprüft."* Erst der Kontrollstart.
- **Nicht `app/` anfassen** — die Server-Seite läuft in einer eigenen Sitzung und wird
  laufend deployt.

---

## Stand der Server-Seite (Kontext, nichts zu tun)

Läuft produktiv als **v14.49.x**, Issue #23 ist umgesetzt:

- `POST /api/kniebrett/melden` — das Kniebrett meldet alle erkannten Friesen in Reichweite
- Schalter im Admin: `aus` / `eigene` / `alle`, global und je Pilot
- Vorrang bei gleichzeitigem Betrieb: **Brügge vor Kniebrett** (sie liefert AGL und
  „am Boden", s. Auftrag 3 oben)
- Committet, aber noch nicht deployt: Lasthebel-Fix, Schild im Sekundentakt,
  Brügge-Aus-Takt 900 → 60

**Offene Issues:** [#38](https://github.com/regover13/friesenspy/issues/38) (dieser Fall),
[#23](https://github.com/regover13/friesenspy/issues/23) (Fremdverkehr als vierte
Schalterstufe, in Arbeit).
