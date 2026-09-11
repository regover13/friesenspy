# Probeflug X-Plane: Lässt sich ein Objekt zur Laufzeit setzen?

Das Gegenstück zu [`../probe-msfs/`](../probe-msfs/). **Dieselbe Frage, andere Schnittstelle** —
und anders als bei MSFS ist hier noch **nichts gemessen**. Alles, was wir über X-Plane wissen,
stammt aus Dokumentation; dieser Probeflug soll das ändern.

Warum das zählt: Rund **ein Drittel der Gruppe fliegt X-Plane** (Nutzerangabe, 11.09.2026).
Ein Kieker, der nur MSFS bedient, schlösse mehr Leute aus als jede andere Einschränkung.

## Was anders ist als in MSFS

| | MSFS | X-Plane |
|---|---|---|
| Objekt benennen | Container-Titel `Boat01` | Dateipfad einer `.obj` |
| Koordinaten | `lat`/`lon` direkt | lokale Meter, `XPLMWorldToLocal` |
| Auf den Boden setzen | `OnGround=1`, der Sim macht es | selbst fragen: `XPLMProbeTerrainXYZ` |
| Lebensdauer | stirbt mit der SimConnect-Verbindung | Instanz gehört dem Plugin — **zu prüfen** |
| Autostart | `exe.xml` oder WASM-Paket | `Resources/plugins/` — der reguläre Weg |
| Netzzugriff | bei WASM offen, extern klar | ein Plugin ist ein normaler Prozess |

**Die heikelste Stelle ist der Pfad.** `XPLMLoadObject` will eine Datei, und der oft genannte
Pfad `Resources/default scenery/sim objects/dynamic/SailBoat.obj` stammt aus einer
XPPython3-Doku, nicht von Laminar. Genau so ist in der Kieker-Spec der Container-Titel
`Boat_Small` entstanden, den es nie gab. Deshalb probiert das Plugin **mehrere Kandidaten der
Reihe nach** und meldet, welcher trägt — ein Fehlschlag je Pfad ist erwartet und kein Fehler.

**Die zweite Stelle sind die Koordinaten.** X-Plane zeichnet in lokalen Metern, und dieses
System verschiebt sich, wenn der Flieger weit genug fliegt. Ohne Gegenmaßnahme wandert ein
„feststehendes" Objekt davon. `XPLMInstanceSetAutoShift` (X-Plane 12) lässt X-Plane das selbst
nachführen — der Aufruf nimmt nur die Instanz, er *ist* das Einschalten.

## Bauen

Gebraucht werden das SDK (ZIP, ~2 MB) und Visual Studio. Ein X-Plane-Plugin ist eine ganz
normale Windows-DLL mit der Endung `.xpl`.

```powershell
# SDK holen und entpacken (einmalig)
Invoke-WebRequest https://developer.x-plane.com/wp-content/plugins/code-sample-generation/sdk_zip_files/XPSDK430.zip -OutFile $env:TEMP\XPSDK430.zip
Expand-Archive $env:TEMP\XPSDK430.zip $env:TEMP\xpsdk

# bauen und gleich installieren
.\bauen.ps1 -XPlane "D:\X-Plane 12"
```

Ohne `-XPlane` wird nur gebaut. Das Skript lädt die MSVC-Umgebung selbst (`vcvars64.bat`).

**Eine Falle steckt schon drin:** `winsock2.h` muss **vor** allem stehen, was `windows.h`
einzieht — und die XPLM-Header tun das. Andernfalls kommt zuerst das alte `winsock.h` (1.1)
herein, und es hagelt „sockaddr: struct Typneudefinition".

## Messen

```powershell
# 1. Horcher starten (nimmt entgegen, was das Plugin meldet)
py ..\horcher.py

# 2. X-Plane starten, Flug laden -- am besten am Wasser
# 3. Zusehen, was im Horcher erscheint
```

Das Plugin wartet **zehn Sekunden** nach dem Start, bevor es etwas setzt. Vorher ist die
Position unbrauchbar — dieselbe Falle wie in MSFS, wo das Hauptmenü `0 / 90` lieferte.

## Was welche Ausgabe bedeutet

| Zeile im Horcher | Bedeutung |
|---|---|
| gar nichts | Das Plugin wurde nicht geladen. `Log.txt` in X-Plane ansehen. |
| `XPluginStart` | Geladen. Ab hier läuft es. |
| `datarefs = FEHLEN` | Die Positions-Datarefs heißen anders — ernster Befund. |
| `pfad_fehlgeschlagen` | Dieser Kandidat existiert nicht; der nächste kommt. |
| `objekt_geladen` | **Der Pfad trägt.** Dieser Name ist ein Ergebnis. |
| `probe_ergebnis` | Die Terrain-Probe hat nicht getroffen — Höhe unklar. |
| `ERFOLG_autoshift_an` | Alles gesetzt. **Jetzt hinsehen.** |
| `laeuft_noch_sekunden` | Lebenszeichen alle 30 s — zeigt, ob die Instanz überdauert. |

## Und dann hinsehen

**Die Meldung beweist nichts Sichtbares** — dieselbe Regel wie in MSFS. Dort hat ein „nichts
gesehen" beinahe zu einem falschen Nein geführt: Das Objekt war ein kleines Motorboot, 200 m
entfernt, 40 Sekunden lang. Erst ein Kreuzfahrtschiff in 150 m Entfernung mit zehn Minuten
Standzeit brachte den Beweis.

**Also: groß, nah und lange.** Ein „nichts gesehen" bei knapper Gelegenheit ist kein Befund.
