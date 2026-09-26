# Übergabe: gespeicherte Kennung (MSFS-Brügge) und Kniebrett-Paket ohne Eigenfilter

**Für:** die Sitzung am Simulator-Rechner (die mit der Probe `probe-kennung/`)
**Von:** der Server-Sitzung (VPS), 26.09.2026
**Grundlage:** `docs/superpowers/specs/2026-09-26-bruegge-kennung-und-zuordnung-design.md`,
GitHub-Issues #46 und #47 (jeweils der Abschnitt „Beschluss“ oben). Vorher `git pull`.

---

## Aufteilung

| Wer | Was |
|---|---|
| **Du (Simulator-Rechner)** | A) MSFS-Brügge: Kennung in `\work` speichern, Protokoll 3. B) Kniebrett-Paket: Eigenfilter streichen. Bauen, testen, Ergebnis festhalten. |
| **Server-Sitzung** | Server-Seite von Protokoll 3, alle Zuordnungsregeln (Thesen 1–13), Kniebrett-Seite (Thesen 14, 16, 17, 18), Download-Seite, **Hochladen der Pakete nach `/opt/friesenspy/data/efb/`**. |

Die X-Plane-Brügge bleibt, wie sie ist: Sie speichert ihre Kennung schon heute je Installation,
der Server nimmt ihr Protokoll 2 weiter an.

## ⚠ Reihenfolge — bitte wirklich beachten

**Der Server weist heute jede Protokollnummer über 2 mit 426 ab** (`app/main.py`, `bruegge_melden`).
Eine Brügge mit Protokoll 3 setzt dann `g_vertrag_tot` und schweigt. Deshalb:

1. Bauen und die Teile testen, die ohne Server gehen (Datei lesen/schreiben/prüfen, siehe Test).
2. **Gegen den echten Server erst testen, wenn die Server-Sitzung meldet, dass Protokoll 3 live ist.**
   Sie schickt dir eine Nachricht.
3. **Nichts verteilen.** Keine ZIP an Piloten, nichts auf der Download-Seite. Das Hochladen macht die
   Server-Sitzung, und zwar erst auf ausdrückliches Wort des Nutzers, an einem Tag ohne Event.

## A) MSFS-Brügge (`msfs/bruegge.cpp`)

**Vertrag (Protokoll 3):**
- Die Brügge schickt `"protokoll": 3`. Alle übrigen Felder bleiben wie heute (`kennung`,
  `bruegge_version`, `simulator`, `lage` mit `am_boden`, `spur`).
- **Beim Start** liest sie `\work\friesenbruegge.kennung` (Pfad wie in der früheren Fassung; alle
  drei Schreibweisen landen laut Probe in derselben Datei). Gültig ist der Inhalt **nur mit genau
  16 Zeichen `0-9a-f`**, sonst verwerfen und ins Log schreiben, warum. Ein Lesefehler heißt „keine
  Kennung“; eine fehlende Datei meldet `errno` 29, nicht `ENOENT`.
- Hat sie eine gültige Kennung, schickt sie sie **ab der ersten Meldung** mit.
- Hat sie keine, meldet sie ohne. Der Server antwortet dann mit `"kennung": "<16 hex>"`, einer
  **frischen** Zufallskennung, nie der eines Piloten. Die Brügge übernimmt sie wie heute
  (`kennung_uebernehmen`, nur solange sie keine hat) und **schreibt sie sofort** in die Datei:
  `fopen(…, "wb")`, `fwrite`, `fclose`, Ergebnis ins Log.
- **Eine vorhandene Kennung wird nie ersetzt.** Der Server schickt keine andere. Täte er es doch:
  übergehen und ins Log.
- `spur` weiter wie heute mitschicken, der Server wertet sie künftig aus.
- `BRUEGGE_VERSION` anheben (Vorschlag 1.18.0). Kopfkommentar „EIN MODUL“ nachziehen: Die Ablage
  ist zurück, ohne `MSFS_IO.h`, per `fopen` (Beleg: `probe-kennung/ERGEBNIS.md`).
- Importliste mit `wasm_pruefen.py` gegen die Probe vergleichen: dieselben sieben neuen
  wasi-Importe sind erwartet.

**Test ohne Server** (am besten mit einem kleinen Schalter oder einem Prüfserver, wie ihr ihn
schon hattet, `pruefserver.py`):
- Erster Start ohne Datei → Log „keine Kennung“; nach der (simulierten) Antwort wird die Datei
  geschrieben, Inhalt 16 hex.
- Neustart → Log „Kennung gelesen“, sie geht in der ersten Meldung mit.
- Datei von Hand verderben (z. B. `xyz`) → verworfen, gemeldet ohne Kennung.
- MSFS 2020 **und** 2024.

**Test gegen den Server** (erst nach der Nachricht der Server-Sitzung): erster Start bekommt eine
frische Kennung; nach dem Neustart erkennt der Server sie sofort.

## B) Kniebrett-Paket (`msfs-panel/PackageSources/FriesenSpy/src/FriesenSpy.tsx`)

- **Den Filter „das bin ich“ ersatzlos streichen:** `VERKEHR_EIGEN_M`, `VERKEHR_EIGEN_FT` und die
  Abfrage im Verkehrsabruf („Wir selbst. Nach heutigem Stand steht das eigene Flugzeug gar nicht in
  der Liste …“). Die Diagnose, ob je ein Sim-Flugzeug auf der eigenen Position steht, baut die
  Server-Sitzung in die Seite.
- Paketversion anheben, bauen mit `msfs-panel/build-package.ps1`.
- Test: Mit einem zweiten Flugzeug dicht am eigenen (KI oder ein Friese am Nachbarstand) erscheint
  es jetzt im Kniebrett. Ein Geisterbild unter dem eigenen Flugzeug darf **nicht** auftauchen; falls
  doch, bitte Bildschirmfoto und Diagnose.

## Nicht tun

- Nichts am Server anfassen, nichts nach `/opt/` kopieren.
- Nichts verteilen, keine Ankündigung.
- Die X-Plane-Brügge nicht ändern.

## Ergebnis

Als `friesenbruegge/ERGEBNIS-kennung-umsetzung.md`, dann committen und pushen
(`friesenbruegge/**` und `msfs-panel/**` lösen keinen Deploy aus). Hinein gehören: Versionen,
Importliste, Log-Zeilen je Simulator und Schritt, Pfad und Inhalt der Datei, Befund zum Kniebrett-
Paket. Die gebauten ZIPs ins Repo legen, wie bisher; die Server-Sitzung lädt sie hoch, wenn der
Nutzer es sagt. Danach der Server-Sitzung (`projects-c3`) kurz Bescheid geben.

## Umgang

Der Nutzer wird geduzt. In Texten für ihn heißt es immer „FriesenBrügge“. Offene Punkte
nummerieren.
