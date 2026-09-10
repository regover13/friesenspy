# Warum das Speichern einer Zuladung die ganze App anhielt (09.09.2026)

Zwei Stillstände von je rund drei Minuten, mitten im Betrieb. Dieses Dokument hält fest, was
gemessen wurde, was daraus folgte und welche Erklärung dabei **widerlegt** wurde — die falsche
Fährte ist hier so wichtig wie die richtige.

## Der Hergang

Der Nutzer wollte im Admin die Beschreibung eines Musters geraderücken. In der Maske
**„🦐 FriesenKutter – Zuladung je Flugzeugtyp"** stand im Feld *Muster/Name* eine komplette,
mehrzeilige KI-Antwort aus der F22-Recherche. Er ersetzte sie durch `Lockheed Martin F-22 Raptor`
und drückte **zweimal** auf Speichern.

Zeitleiste aus dem nginx-Log (`goaccess.log`, alles Ortszeit):

| Zeit | |
|---|---|
| 19:29:46 | `POST /api/admin/transport/payloads` → 200 |
| 19:29:46 – 19:32:38 | **keine einzige Antwort mehr**, nur 499 (Client bricht ab) |
| 19:32:39 | kurz Luft — und **hier** wird die F22-Zeile geschrieben (`updated_at`) |
| 19:32:39 – 19:34:50 | zweiter Stillstand |
| 19:34:50 / 19:35:01 | **Container-Neustart von Hand** (Docker-Journal), 260 aufgestaute Anfragen sterben mit 502 |
| ab 19:36 | wieder 180–235 Antworten je Minute |

**Der zweite Stillstand endete nicht von allein.** Er lief noch, als der Container umgelegt wurde;
seine wahre Dauer ist unbekannt und beträgt mindestens 2:11.

Dass es **zwei** Klicks waren, erklärt die zwei Stillstände: Der zweite POST lag in der
Warteschlange und wurde um 19:32:39 abgearbeitet — genau dann, als die App das erste Mal wieder
ansprechbar war. Er warf sofort erneut weg, was der erste Durchlauf gerade wiederhergestellt hatte.

## Die Ursache

Drei Bausteine, jeder für sich harmlos:

1. **`admin_upsert_payload` verwarf alle Kutter-Snapshots.** Eine Zeile mit der Begründung
   „Zuladungs-Änderung wirkt auf ALLE Kutter-Events (#66 Task 7)".
2. **Ein verworfener Snapshot wird erst beim nächsten Lesen neu gebildet**, einer nach dem anderen
   (`_frozen_or_compute`, Lazy-Freeze). Der nächste Aufruf von `/api/transport/events` zahlt also
   die Rechnung für *alle* Events auf einmal.
3. **`transport_events()` ist `async def`, enthält aber kein einziges `await`.** Die gesamte
   Rechnung läuft damit *in* der Event-Loop. Solange sie läuft, antwortet die App niemandem —
   nicht langsam, sondern gar nicht.

**Gemessen im Produktionscontainer am 10.09.2026: 111 Sekunden** für die zehn Events im
Retention-Fenster, je Event zwischen 0,9 s und 16,1 s.

## Was es NICHT war

- **Nicht das Sonderzeichen und nicht die Länge des Strings.** `harden_name()`
  (`app/aircraft_info.py`) prüft ausschließlich Länge (> 80 → verworfen) und Zeilenumbrüche; es
  gibt keinen Regex über den Namen, der backtracken könnte. Der Name geht in
  `compute_transport_progress` überhaupt nicht ein — er ist eine Beschriftung. Ein 359-Zeichen-
  Absatz liegt seit Langem folgenlos in `MR20.make_model`.
- **Nicht die Wikipedia-/Foto-Auflösung.** Die erste Hypothese lautete, das Speichern habe eine
  Musterrecherche angestoßen. Sie ist widerlegt: Die `aircraft_types`-Zeile für F22 trägt
  `fetch_state = 'nichts_gefunden'` mit `checked_at = 2026-07-30` — an dem Abend lief dort nichts.
- **Nicht die KI-Recherche.** Der Vorschlags-Endpunkt liegt bereits in `asyncio.to_thread`, mit
  einem Kommentar, der genau diese Gefahr benennt. Der Speicherweg daneben hatte diese
  Absicherung nie.

Der Auslöser war also nicht, *was* im Feld stand, sondern *dass* gespeichert wurde. Ein kurzer
Name hätte dasselbe bewirkt.

## Die Reparatur: eine Zeile weniger, nicht eine mehr

Der erste Reparaturvorschlag war, klüger zu invalidieren (nur bei echter Gewichtsänderung, nur
betroffene Events). Die bessere Frage kam vom Nutzer: **Warum überhaupt invalidieren?**

Sie trägt, und der Code gibt ihr recht:

- Ein **laufendes** Event bekommt nie einen Snapshot (`_frozen_or_compute` friert nur `finished`
  ein). Eine Zuladungskorrektur wirkt dort ohnehin sofort.
- Also konnte das globale Wegwerfen **ausschließlich abgeschlossene** Events treffen — genau die,
  die bleiben sollen, wie sie gewertet wurden.
- Und für den Fall, dass man es doch will, existiert der Hebel längst, aus **derselben Aufgabe
  #66 Task 7**: `admin_update_transport_event` löscht den Snapshot unbedingt und taut auf —
  „Event antippen + speichern". Er kostet ein Event statt zehn und geschieht auf Ansage.

Beide Aufrufe von `delete_progress_snapshots(conn, "kutter")` sind deshalb am 10.09.2026 ersatzlos
entfallen (`admin_upsert_payload`, `admin_set_default_payload`). Die Funktion selbst bleibt — sie
ist getestet und könnte wieder gebraucht werden. In der Maske steht jetzt ein Satz, der den Hebel
sichtbar macht; ohne ihn wäre das Verhalten nur noch schwerer zu erraten als vorher.

## Was offen bleibt

**Die 111 Sekunden sind damit nicht weg, nur seltener.** Sie fallen weiterhin an, wenn ein Event
bewusst neu gerechnet wird, und anteilig bei jedem Aufruf während eines laufenden Kutters.

Ein `cProfile`-Lauf über ein einzelnes Event (Event 1, 16 s real, 52,7 s unter dem Profiler) zeigt,
wo sie liegen:

| | Aufrufe | Zeit |
|---|---|---|
| `geo.haversine` | 4.863.216 | 18,3 s |
| `geo.nearest_airport_icao_fast` | 58.598 | 33,5 s kumuliert |
| `math.radians` | 19.511.462 | 2,4 s |
| `sqlite3 fetchall` | 323 | 2,4 s |

**Es ist fast reines Python, keine Datenbank.** Das ist auch der Grund, warum ein Verschieben in
einen Worker-Thread weniger hilft, als es klingt: Nur SQLite gibt die GIL frei, `haversine` nicht.

Der eigentliche Hebel steckt in `nearest_airport_icao_fast`: Der Index arbeitet mit **1°×1°-Kacheln**
und legt vorsichtshalber eine weitere Kachel Rand darum. Für eine Frage mit rund 4 km Radius wird
damit ein Feld von etwa 3°×3° durchsucht — im Schnitt 83 Flugplätze je Aufruf. Feinere Kacheln
würden die Kandidatenmenge um etwa zwei Größenordnungen senken, ohne am Ergebnis etwas zu ändern;
die zugesicherte Ergebnisgleichheit mit dem Linearscan hängt an der Bounding-Box, nicht an der
Kachelgröße. Ein Gleichheitstest gegen `nearest_airport_icao` gehört in denselben Commit.

## Drei Messfallen aus dieser Untersuchung

- **`docker logs` überlebt keinen Deploy.** Die Logs des Containers, in dem der Vorfall passierte,
  waren beim Nachsehen bereits mit dem 14.27.1-Deploy verschwunden. Wer einen Vorfall aufklären
  will, sichert sie **vor** dem nächsten Ausrollen.
- **`zgrep` über `goaccess.log*` liefert unsortierte Zeilen.** Die rotierten Dateien werden
  hintereinandergehängt, nicht verschränkt. Eine Lückenanalyse darauf erfindet Lücken (hier: eine
  „56-Sekunden-Blockade nach dem Neustart", die es nie gab) und übersieht echte. Erst `sort`, dann
  auswerten.
- **Ein `curl` im Container beweist nichts, wenn es dort kein `curl` gibt.** Am 09.09. um 19:34:00
  steht im Docker-Journal `exec: "curl": executable file not found in $PATH` — der fehlgeschlagene
  Gesundheitstest, der damals zur Fehldiagnose „Server ist tot" führte.
