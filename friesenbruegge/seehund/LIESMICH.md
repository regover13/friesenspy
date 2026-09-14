# Der Seehund

Ein eigenes Robbenmodell für beide Simulatoren, gebaut am 14.09.2026.

> **Herkunft und Lizenz**
> Grundlage ist **„Walrus" von Poly by Google**, aus dem Nachlass des 2021 abgeschalteten
> Dienstes, archiviert auf [poly.pizza/m/5T7nIjx9ekP](https://poly.pizza/m/5T7nIjx9ekP).
> Lizenz **CC BY 3.0** — Änderung und Weitergabe sind ausdrücklich erlaubt, Bedingung ist
> allein die Namensnennung. Sie gehört damit in jedes Paketmanifest und auf die
> Downloadseite. Die Rohdatei liegt hier als `grundlage_walrus_polybygoogle.glb`.

## Warum überhaupt ein eigenes

**Es gibt in keinem der beiden Simulatoren eine Robbe.** Das ist keine Vermutung, sondern
das Ergebnis von vier Durchgängen:

| durchsucht | Ergebnis |
|---|---|
| MSFS 2020/2024, 45 Tiertitel + 41 Tierpakete | nichts |
| MSFS, 2642 Titel aus den gestreamten `.fsarchive` | nichts |
| X-Plane 12, alle 1146 Bordobjekte | nichts |
| X-Plane, Szeneriebibliothek | nichts |

Superspuds `human-library-animated` hat welche — aber es ist ein **MSFS**-Paket. Für das
Drittel der Gruppe, das X-Plane fliegt, hätte es nie etwas gelöst. Und eine Anfrage lief
ins Leere: Der Autor war zuletzt vor rund einem Jahr online.

Deshalb steht unser Modell **vor** seinen Titeln, nicht dahinter: Wer sein 556-MB-Addon
hat, bekommt als Zugabe die animierte Robbe; alle anderen brauchen nichts weiter.

## Warum ausgerechnet ein Walross

Vier freie Modelle standen zur Wahl, alle CC BY. Zwei davon — beide *„Sea lion"* genannt —
**sitzen aufrecht** wie im Zoo; von oben sieht man einen Rücken mit hochgerecktem Kopf.
Die beiden *„Walrus"* liegen ausgestreckt auf dem Bauch, Flossen seitlich, und genau so
liegt ein Seehund auf der Sandbank.

**Die Pose entscheidet, nicht der Dateiname.** Ein liegendes Walross ohne Stoßzähne ist
einem Seehund von oben näher als ein sitzender Seelöwe — und von oben wird gezählt.

## Die Maße

Belegt, nicht geschätzt: [Seehundstation Norddeich](https://seehundstation-norddeich.de/website/seehundstation/der-seehund/allgemeines/)
(Weibchen 1,60 m, Männchen 1,80 m) und [Deutscher Jagdverband](https://www.jagdverband.de/zahlen-fakten/tiersteckbriefe/seehund-phoca-vitulina)
(1,20–1,80 m; Heuler 80–90 cm).

| | Länge | Breite | Höhe |
|---|---|---|---|
| `bulle` | 1,80 m | 0,66 | 0,46 |
| `kuh` | 1,60 m | 0,58 | 0,42 |
| `heuler` | 0,85 m | 0,34 | 0,25 |

Drei Größen, weil eine Liegegruppe aus Bullen, Kühen und Heulern besteht — zwanzig exakt
gleich große Tiere nebeneinander sehen von oben nach Tapete aus. Breite und Höhe wachsen
bewusst **nicht** linear mit: Ein Heuler ist gedrungener als ein Bulle.

## Die Dateien

| | |
|---|---|
| `seehund_bauen.py` | Hauptskript: importiert, formt, skaliert, speichert |
| `form.py` | **alle Stellschrauben der Form** — wer daran dreht, dreht hier |
| `textur.py` | die Palettentextur und die UV-Zuordnung |
| `export_xplane.py` | schreibt drei OBJ8-Dateien |
| `export_msfs.py` | schreibt die SimObject-Struktur in die Paketquelle |
| `rundum.py` | rendert das Modell von acht Seiten, zur Beurteilung |

Alle laufen unter Blender:

```
"D:\Program Files\Blender Foundation\Blender 3.0\blender.exe" --background --python seehund_bauen.py
```

## Was beim Nachbauen wehtut

Fünf Dinge, die jeweils Zeit gekostet haben und in den Dateien ausführlich stehen:

1. **Alle Längsangaben in `form.py` sind Anteile, keine Meter.** Zur Korrekturzeit liegt
   das Tier bei Y −0,643 … +1,057 — der Ursprung wird erst danach gesetzt. Mit Metern
   greifen die Korrekturen an der falschen Stelle, und zwar ohne dass es auffällt.
2. **Kleine Teile werden starr bewegt.** Jede Korrektur verschiebt Ecken nach ihrer Lage;
   auf eine Augenkugel angewandt zieht das sie in die Länge. Dasselbe gilt für die
   anisotrope Skalierung — sie streckt jedes kompakte Detail um Faktor 2,5.
3. **Glätten geht nicht.** Das Modell hat 698 offene Kanten in 6 Randschleifen; beim
   Glätten kollabieren die Ränder.
4. **Blender bringt Python 3.9 mit** — `Path.write_text(newline=…)` gibt es dort nicht.
5. **Die MSFS-Textur braucht `texture/` UND eine `.png.xml`**, sonst sammelt der Package
   Builder sie stillschweigend nicht ein. Details in `export_msfs.py`.

## Noch nicht geschehen

**Im Simulator gesehen hat das Modell niemand** — weder in MSFS noch in X-Plane. Das ist
der nächste Schritt; die Art `robbe` ist auf dem Server für beide Simulatoren zugeordnet,
unsere Titel auf den vorderen Rängen.
