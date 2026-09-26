# Ergebnis: gespeicherte Kennung (MSFS-FriesenBrügge 1.18.0) und Kniebrett-Paket 2.3.2

Sitzung am Simulator-Rechner, 26.09.2026. Auftrag: `UEBERGABE-kennung-umsetzung.md`.
Beide Teile sind umgesetzt und in MSFS 2020 und 2024 gegen den echten Server (Protokoll 3) gemessen,
**mit einer Lücke** (Punkt 4 unten). Nichts wurde verteilt, nichts nach `/opt` kopiert, der Server
wurde nur gelesen (Log, Datenbank ohne Schreibzugriff).

## Kurzfassung

| | Ergebnis |
|---|---|
| A) Brügge 1.18.0: Kennung lesen/schreiben, Protokoll 3 | **fertig**, gebaut, in beiden Simulatoren gemessen |
| B) Kniebrett-Paket 2.3.2: Eigenfilter gestrichen | **fertig**, gebaut, Tests grün; **Praxistest steht aus** (Simulator + zweites Flugzeug) |
| Erststart in MSFS 2020 und 2024 | Server vergibt frische Kennung, wird sofort geschrieben |
| Neustart in MSFS 2020 und 2024 | Kennung wird gelesen, mit der ersten Meldung geschickt, Server bietet keine andere an |
| Verdorbene Datei (`xyz`) | verworfen, gemeldet ohne, frische Kennung, neu geschrieben |
| Zuordnung mit vPilot (MSFS 2024) | Server band die Kennung sofort an die CID, s. Punkt 3 |

## A) FriesenBrügge 1.18.0 (`msfs/bruegge.cpp`)

- **Version:** 1.17.0 → **1.18.0**, `"protokoll": 3`.
- **Beim Start** liest `kennung_lesen()` `\work\friesenbruegge.kennung`. Gültig ist nur ein Inhalt aus
  **genau 16 Zeichen 0-9a-f** (ein nachgestellter Zeilenumbruch oder Leerzeichen wird abgeschnitten),
  sonst wird die Datei verworfen und der Grund ins Log geschrieben. Ein Lesefehler heißt „keine
  Kennung“ (`errno` 29 bei fehlender Datei, nicht `ENOENT`).
- **Nach dem Empfang** schreibt `kennung_schreiben()` die Kennung sofort per `fopen(…, "wb")`. Ein
  unvollständiges Schreiben (weniger als 16 Bytes oder `fclose != 0`) wird nicht als Erfolg gemeldet.
- **Eine vorhandene Kennung wird nie ersetzt.** Bietet der Server doch eine andere an, steht
  `Server bot Kennung … an -- uebergangen` im Log (ungetestet, weil der Server es nicht tut).
- **Eine Gültigkeitsregel für Datei und Serverantwort:** `kennung_gueltig()` (genau 16 Zeichen).
  Vorher akzeptierte `kennung_uebernehmen` 8 bis 39 Zeichen, während `kennung_schreiben` nur 16
  ablegte (Fund des Reviews, s. unten).
- **Kopfkommentar nachgezogen:** Nachtrag zur Rückkehr der Ablage; „DER PREIS“ und „DER WEG ZURUECK“
  sind als überholt bzw. widerrufen gekennzeichnet (der zweite empfahl genau den Server-Weg, der am
  25.09.2026 #46 verursacht hat).
- **Gebaut** mit `msfs/bauen.ps1` gegen das 2020er SDK (`D:\MSFS SDK`), Datei 77 462 Bytes.
  `wasm_pruefen.py`: beide Fallen ok, **26 Importe** = die 19 der Brügge 1.17.0 plus **dieselben
  sieben neuen wasi-Importe** wie in der Probe (`path_open`, `fd_read`, `fd_fdstat_get`,
  `fd_fdstat_set_flags`, `fd_prestat_get`, `fd_prestat_dir_name`, `proc_exit`). Kein `MSFS_IO.h`.
- **ZIP:** `friesenbruegge/friesenbruegge.zip` (395 945 Bytes, Fassung 1.18.0) ist neu gebaut und im
  Repo. Nicht hochgeladen.

### Ablage der Datei

| Simulator | Pfad | Inhalt (Beispiel aus den Tests) |
|---|---|---|
| MSFS 2020 | `%LOCALAPPDATA%\Packages\Microsoft.FlightSimulator_8wekyb3d8bbwe\LocalState\packages\friesenbruegge\work\friesenbruegge.kennung` | 16 Bytes, z. B. `eb31ea76bf23bcfd` |
| MSFS 2024 | `%LOCALAPPDATA%\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalState\WASM\MSFS2024\friesenbruegge\work\friesenbruegge.kennung` | 16 Bytes, z. B. `fe62f1b33138c9e4` |

### Log-Zeilen je Simulator und Schritt (Console, vom Nutzer eingefügt)

**MSFS 2020, Erststart (keine Datei):**
```
[FriesenBruegge] Fassung 1.18.0 startet -- verbinde mit SimConnect...
[FriesenBruegge] keine Kennung gespeichert (errno 29) -- melde ohne
[FriesenBruegge] bereit -- Takt 1 s, Kennung (noch keine), meldet an https://friesenspy.devprops.de/api/bruegge/melden
[FriesenBruegge] verbunden mit "KittyHawk" 11.0 (Build 282174.999) -- erkannt als msfs2020
[FriesenBruegge] Kennung vom Server: a86bf4297c2f4b0b (msfs2020)
[FriesenBruegge] Kennung gespeichert: 16 Bytes, fclose=0
```
Die Datei auf der Platte enthielt danach `a86bf4297c2f4b0b`.

**MSFS 2020, Neustart:**
```
[FriesenBruegge] Kennung gelesen: a86bf4297c2f4b0b
[FriesenBruegge] bereit -- Takt 1 s, Kennung a86bf4297c2f4b0b, meldet an …
```
Keine Zeile „Kennung vom Server“, die Datei wurde nicht neu geschrieben.

**MSFS 2020, verdorbene Datei (Inhalt `xyz`, von Hand gesetzt):**
```
[FriesenBruegge] Kennungsdatei verworfen: Inhalt ist nicht genau 16 Zeichen 0-9a-f (3 Bytes) -- melde ohne
[FriesenBruegge] bereit -- Takt 1 s, Kennung (noch keine), meldet an …
[FriesenBruegge] Kennung vom Server: eb31ea76bf23bcfd (msfs2020)
[FriesenBruegge] Kennung gespeichert: 16 Bytes, fclose=0
```

**MSFS 2024, Erststart (Datei vorher weggelegt):**
```
[bruegge.wasm] [FriesenBruegge] keine Kennung gespeichert (errno 29) -- melde ohne
[bruegge.wasm] [FriesenBruegge] Kennung vom Server: fe62f1b33138c9e4 (msfs2024)
[bruegge.wasm] [FriesenBruegge] Kennung gespeichert: 16 Bytes, fclose=0
```

**MSFS 2024, Neustart** (mit der überarbeiteten 1.18.0 nach dem Review):
```
[bruegge.wasm] [FriesenBruegge] Fassung 1.18.0 startet -- verbinde mit SimConnect...
[bruegge.wasm] [FriesenBruegge] Kennung gelesen: fe62f1b33138c9e4
[bruegge.wasm] [FriesenBruegge] bereit -- Takt 1 s, Kennung fe62f1b33138c9e4, meldet an …
[bruegge.wasm] [FriesenBruegge] Der Server lehnt ab (HTTP 502). Die Bruegge meldet weiter.
[bruegge.wasm] [FriesenBruegge] Der Server nimmt wieder an (vorher HTTP 502).
```
Der 502 fiel in einen Deploy der Server-Sitzung; die Brügge meldete weiter und wurde wieder angenommen.

## Befunde

1. **Eine alte Kennungsdatei aus der Zeit vor 1.14.0 liegt bei diesem Nutzer noch in MSFS 2024**
   (`…\WASM\MSFS2024\friesenbruegge\work\friesenbruegge.kennung`, Stand 16.09.2026, `71cf05488d934fd3`,
   geschrieben von der fsIO-Fassung 1.13.x). Sie ist gültig (16 Zeichen), die 1.18.0 hat sie gelesen und
   ab der ersten Meldung geschickt; der Server hat sie ohne Ablehnung angenommen (Takt gesetzt, kein
   426). **Jede Installation, die 1.11 bis 1.13 hatte, dürfte so eine Datei haben.** Der Server muss
   eine Kennung, die er nie vergeben hat oder die längst vergessen ist, als „unbekannt“ behandeln
   (Spec: wird wie eine neue Installation zugeordnet). Bei MSFS 2020 gab es die Datei nicht.
2. **Alte Dateien bleiben nach dem Löschen des Pakets liegen** (auch die vom Simulator übersetzten
   Module in `LocalState`). Eine Neuinstallation findet also die alte Kennung wieder. Steht auch in
   `probe-kennung/ERGEBNIS.md`.
3. **Zuordnung mit vPilot (MSFS 2024, echter Server):** Brügge geladen, danach vPilot verbunden im
   Stand. `bruegge_zuordnung`: `fe62f1b33138c9e4` → CID `1602713`, `msfs2024`, Brügge `1.18.0`,
   Protokoll `3`, 0 Verstöße, zugeordnet 15:03:42Z, Position 50.0456/8.5631 (EDDF). Ein Erfolg steht
   nicht im Log (der Server loggt nur Fehlschläge), sondern nur in der Datenbank.
4. **Nicht geprüft: „nach dem Neustart erkennt der Server die Kennung sofort“.** Der Test lief nicht
   durch, weil die Bindung beim Neustart schon weg war: Sie war unbewährt (nie im Flug, kein
   `bewaehrt_am`), und der Neustart setzte den Nutzer an einen anderen Ort, was eine unbewährte Bindung
   nach These 4 vergessen lässt (`bruegge_zuordnung_vergessen`). Die Zeile war 34 Minuten nach der
   Zuordnung nicht mehr in der Datenbank. Das ist nach Spec, ändert aber die Aussage der Übergabe:
   Ein sofortiges Wiedererkennen gilt nur für eine **bewährte** Bindung (Flug ab 40 kt über 2 Minuten).
   Gemessen ist: Die Brügge schickt die gespeicherte Kennung ab der ersten Meldung mit und behält sie,
   auch wenn der Server sie nicht mehr kennt (`fe62…` blieb nach dem Vergessen gültig). Offen: Neustart
   nach einem echten Flug mit vPilot, dann prüfen, ob die Bindung erhalten bleibt.
5. **Server-Last am 26.09.2026, 17:07 (auf Wunsch des Nutzers, sehr viele Flugzeuge auf dem
   Kniebrett):** unkritisch. Load 1,4 bei 6 Kernen, CPU-Druck 2 bis 4 %, keine Zeile
   „Poll-Zyklus langsam“, keine „database is locked“, keine Fehler in 30 Minuten. FriesenSpy zeigte
   in einer Messung 58 % eines Kerns, fünf Sekunden später 4 % (Spitze). In 2 Minuten:
   1200× `/api/kniebrett/melden`, 401× `/api/live`, 288× `/api/transport/events`. Die Antwort von
   `/api/traffic` war 1,2 bis 2,3 KB.

## B) Kniebrett-Paket 2.3.2

- `VERKEHR_EIGEN_M`, `VERKEHR_EIGEN_FT` und die Abfrage im Verkehrsabruf sind ersatzlos gestrichen.
  `eigen`, `abstand` und `altFt` bleiben, sie dienen weiter der Sortierung.
- `PAKET_VERSION` und `package_version` 2.3.1 → **2.3.2**, Release-Notes wie bei 2.3.0 → 2.3.1
  nachgeführt. Gebaut mit `msfs-panel/build-package.ps1`.
- **Tests:** `test_eigenes_flugzeug_wird_nicht_mehr_ausgefiltert` (statt der alten Gegenprobe) und
  `test_paketversion_gehoben_und_gleichlaufend` (jetzt 2.3.2). `tests/test_vr_panel.py` und
  `tests/test_bruegge_ein_modul.py` zusammen 276 Tests grün.
- **ZIP:** `msfs-panel/friesenspy-efb.zip` (137 766 Bytes) liegt **nur auf dem Simulator-Rechner**:
  `msfs-panel/*.zip` steht in der `.gitignore` (Zeile 42), das ist der bisherige Zustand. Die
  Vorgängerfassung 2.3.0 liegt daneben als `friesenspy-efb-2.3.0.zip`. **`git pull` bringt die ZIP
  nicht; sie muss von diesem Rechner hochgeladen werden.**
- **Nicht getan:** der Praxistest aus der Übergabe (zweites Flugzeug dicht am eigenen, Geisterbild
  unter dem eigenen Flugzeug). Er braucht Simulator und ein zweites Flugzeug.

## Review

Ein Review mit dem Fable-Modell (nur lesend) über den Commit fand:

- **Hoch:** `tests/test_bruegge_ein_modul.py` verbot den Bezeichner `KENNUNG_DATEI` im Code und war
  damit rot. Korrigiert (nur noch die fsIO-Spuren sind verboten), dazu ein neuer Test für die Ablage.
- **Mittel:** Widersprüche im Kopfkommentar, und zwei verschiedene Gültigkeitsregeln für die Kennung.
  Beide behoben.
- **Niedrig:** Erfolgszeile beim Schreiben auch bei Teilschreiben (behoben), ein abweichendes
  Angebot des Servers wurde nicht geloggt (behoben), der Panel-Test prüft nur die Abwesenheit des
  Bezeichners (so gelassen).
- Nebenbefund für die Server-Sitzung: `PROTOKOLL.md` nennt im Kopf noch „Fassung 2 · MSFS 1.17.0“.

## Offene Punkte

1. Praxistest des Kniebrett-Pakets 2.3.2 (zweites Flugzeug dicht am eigenen).
2. Neustart nach einem echten Flug (bewährte Bindung): erkennt der Server sie sofort? (Befund 4)
3. Hochladen der beiden ZIPs macht die Server-Sitzung auf Wort des Nutzers. `friesenspy-efb.zip`
   liegt nur lokal (Befund oben).
4. Steam-Fassungen von MSFS 2020/2024 sind nicht geprüft (Pfad des `\work`-Ordners).

## Zustand des Rechners nach den Tests

In `Community` beider Simulatoren liegt jetzt die **Brügge 1.18.0** (nicht mehr 1.17.0). Sie spricht
Protokoll 3. Das Testpaket
`friesentest` und der lokale Testserver sind entfernt. Die alte 2024-Kennungsdatei vom 16.09.2026 ist
gesichert (Scratchpad der Sitzung) und nicht mehr am Ort.

## Nachtrag 26.09.2026, Abend: 1.18.1 (Kollisionskennung) und Kniebrett-ZIP im Repo

Auf Wunsch der Server-Sitzung, freigegeben vom Nutzer.

- **Brügge 1.18.1:** Liest sie genau `9e3711c100000000`, verwirft sie die Datei-Kennung und meldet
  ohne Kennung, wie bei einer verdorbenen Datei. Das ist die Kennung, die die Fassungen vom 11. bis
  14.09.2026 auf jedem Rechner gleich erfanden und mit der Datei-API nach `\work` schrieben; spätere
  Fassungen haben sie nicht überschrieben. Neuer Test `test_die_kollisionskennung_der_fruehen_fassungen_wird_verworfen`.
- **Gemessen in MSFS 2020** (Datei von Hand auf `9e3711c100000000` gesetzt, Neustart, Flug):
  ```
  [FriesenBruegge] Fassung 1.18.1 startet -- verbinde mit SimConnect...
  [FriesenBruegge] Kennungsdatei verworfen: 9e3711c100000000 ist die Kollisionskennung der Fassungen vom 11. bis 14.09.2026 (auf jedem Rechner dieselbe) -- melde ohne
  [FriesenBruegge] bereit -- Takt 1 s, Kennung (noch keine), meldet an …
  [FriesenBruegge] Kennung vom Server: 426a0e92883bfb63 (msfs2020)
  [FriesenBruegge] Kennung gespeichert: 16 Bytes, fclose=0
  ```
  In MSFS 2024 nicht gemessen: Dort liegt keine solche Datei (Erststart mit `fe62…`). Der Code ist
  derselbe, aber der Fall ist dort nicht durchgespielt.
- **Gebaut:** `bruegge.wasm` 77 683 Bytes, 26 Importe (unverändert), beide Fallen ok.
  `friesenbruegge/friesenbruegge.zip` neu (396 038 Bytes, Fassung 1.18.1). In beiden Community-Ordnern
  liegt jetzt 1.18.1.
- **Kniebrett-ZIP im Repo:** `msfs-panel/friesenspy-efb.zip` (2.3.2, 137 766 Bytes) ist mit
  `git add -f` eingecheckt, damit die Server-Sitzung sie hochladen kann. Die `.gitignore` bleibt
  unverändert (`msfs-panel/*.zip`); die Vorgänger-ZIPs liegen weiter nur lokal.
- **Praxistest Kniebrett (zweites Flugzeug dicht am eigenen):** weiter offen.

## Nachtrag 26.09.2026, 18:25: Bewährung gemessen (MSFS 2024, echter Server 15.22.3)

Brügge 1.18.1, Kennung `fe62f1b33138c9e4` (aus der Datei gelesen), Kniebrett 2.3.2, vPilot nach der
ersten Meldung der Brügge im Stand verbunden, dann Flug bis 106 kt:

```
bruegge_zuordnung: fe62f1b3 | cid 1602713 (FRS49) | msfs2024 | 1.18.1 | protokoll 3
  zugeordnet_am 2026-09-26T16:11:09Z | bewaehrt_am 2026-09-26T16:18:04Z | verstoesse 0 | geloest_am leer
  gesehen_am    2026-09-26T16:23:54Z
```

- **Erste Zuordnung im Stand:** 15:59:07Z, sofort nach dem Verbinden von vPilot (erste Bindung).
  Danach eine neue Zuordnung um 16:11:09Z (`zugeordnet_am`), Ursache nicht untersucht (Nutzer war
  zwischendurch an einen anderen Ort gesprungen; der Server band nach dem Sprung neu).
- **Bewährt** 7 Minuten später, im Flug. Vorher, vor dem Fund des Servers (15.22.3), war eine
  unbewährte Bindung beim Neustart an anderem Ort vergessen worden (Befund 4 oben); das ist damit
  serverseitig behoben und in der Praxis nicht wieder aufgetreten.
- **Noch offen:** Neustart nach einer *bewährten* Bindung. Erkennt der Server die Kennung ohne
  Suche sofort wieder? (Der Nutzer wollte nicht mehr neu starten.)
- **Kniebrett-Praxistest:** Der Nutzer stand mit FRS61 (CID 1031301) etwa 50 m entfernt (beide im
  VATSIM-Datenstrom des Servers, beide stehend). „Ich sehe nur mich“ auf dem Kniebrett, ohne
  Bildschirmfoto und ohne Angabe, ob FRS61 im Simulator selbst sichtbar war. **Nicht ausgewertet.**
