# GPS-Flugerkennung — die fachlichen Anforderungen

Stand: 2026-07-15 · Code: `app/gps_legs.py`, `app/database.py` (`canonicalize_legs`)

Dieses Dokument sammelt an einer Stelle, **was** die Flugerkennung leisten muss und **warum** jede
Regel so aussieht, wie sie aussieht. Es ist kein Änderungsvorschlag, sondern die Referenz, gegen die
Änderungen geprüft werden.

Der Grund für seine Existenz: Die Regeln sind einzeln in Docstrings belegt, aber ihr Zusammenspiel
war nirgends nachlesbar. Zwei Vereinfachungs-Vorschläge vom 2026-07-15 wirkten schlüssig und waren
beide falsch — die Gegenbeweise stehen unter [Fallstricke](#fallstricke). Wer hier etwas vereinfachen
will, sollte diesen Abschnitt zuerst lesen.

---

## 1. Grundprinzip

**Ein Flug wird allein aus dem GPS-Track erkannt.** Nicht aus dem Flugplan, nicht aus dem
Verbindungsabbruch. Der Flugplan wird erst *nachträglich* zugeordnet und ist nie Beweis für einen
Flug.

Daraus folgen vier Sätze, die alles Weitere tragen:

1. **Höhe ist das Leitsignal, Groundspeed nur sekundär.** Die Gruppe fliegt STOL und Helis; eine
   Wilga reist mit ~40 kt. Eine geschwindigkeitsbasierte Erkennung würde diese Flüge nicht sehen.
2. **Eine Landung zählt nur an einem Flugplatz.** Ein Absturz im Watt, ein Hover über dem Feld, ein
   Vollstopp auf der Wiese sind keine Landung.
3. **Ein Flug endet am nächsten *anderen* Platz.** Platzrunden am Startplatz sind Teil des Fluges,
   keine eigenen Flüge — solange keine echte Bodenpause dazwischenliegt.
4. **Im Zweifel nichts behaupten.** Kein geratener Flugzeugtyp, kein Ziel aus dem Flugplan, keine
   gerettete Landung ohne Beleg. Ein ehrliches „unbekannt" ist besser als eine plausible Erfindung.

## 2. Die Schwellen

Alle in `app/gps_legs.py`, sofern nicht anders vermerkt.

| Konstante | Wert | Bedeutung |
|---|---:|---|
| `_GPS_AIR_AGL_FT` | 500 ft | AGL über Boden-Referenz = abgehoben (Leitsignal) |
| `_GPS_CLIMB_MIN_AGL_FT` | 100 ft | Mindest-AGL für den sekundären „schnell + steigend"-Trigger |
| `_GPS_FLYING_GS_KT` | 50 kt | sekundärer Abhebe-Helfer (nur mit Steig-Nachweis) |
| `_GPS_GROUND_AGL_FT` | 300 ft | AGL-Obergrenze für „am Boden" beim Landungs-Guard |
| `_GPS_BLOCK_GS_KT` | 2 kt | Vollstopp = Touchdown-Kandidat |
| `_GPS_SPAWN_MAX_AGL_FT` | 1500 ft | Spawn-in-der-Luft gilt noch als Start an diesem Platz |
| `_GPS_STOP_AND_GO_MAX_SEC` | 300 s | X→X-Landung wird nur binnen dieser Frist absorbiert |
| `gap_minutes` | 30 min | Zeitlücke, die einen Track in Segmente teilt |
| `_BUMMEL_AIRPORT_RADIUS_KM` (`database.py`) | 4,0 km | Platz-Umkreis für Start-/Ziel-Zuordnung |

Für das Zusammenfügen zerschnittener Aufzeichnungen (`app/database.py`):
`_FLOWN_MIN_GS_KT` 60 kt · `_LANDED_MAX_GS_KT` 40 kt · `_RECONNECT_GAP_SAME_FP_MIN` 30 min ·
`_RECONNECT_GAP_NO_FP_MIN` 15 min · `_MAX_GS_KT` 600 kt · `_BUDGET_MARGIN_NM` 10 NM ·
`_DIRECTION_TOLERANCE_KM` 20 km.

## 3. Die Regeln

### 3.1 Abheben

- **Ein Steigflug über 500 ft AGL ist immer ein Abheben.** Die Boden-Referenz bleibt dabei auf der
  Feldhöhe verankert (Minimum) und klettert nicht mit. *Warum:* Wandert sie mit, bleibt der Abstand
  immer nur ein Sample-Schritt (~170–200 ft) und die Schwelle wird nie erreicht — es würde nie ein
  Abheben erkannt. (`test_realistic_gradual_climb`, Fix 923e7f6)
- **Schnell und nachweislich steigend (> 50 kt, > 100 ft AGL, höher als das Vor-Sample) hebt ebenfalls ab.**
  Erkennt Schnelle früher als die reine 500-ft-Schwelle. (`test_fast_aircraft_takeoff_triggers_before_500ft`)
- **Reiner Bodenspeed ohne Steigen ist niemals ein Abheben.** Sonst wäre jeder Startlauf und jeder
  abgebrochene Start ein Geisterflug. (`test_ground_roll_high_gs_no_climb_no_takeoff`)
- **Fehlt die Höhe ganz, bleibt Groundspeed als Notbehelf.** Nur dann.
- **Wer nie abhebt, erzeugt keinen Flug.** Reines Rollen ist strukturell gefiltert, nicht
  weggefiltert. (`test_ghost_never_airborne`)

### 3.2 Landen

- **Vollstopp (< 2 kt) im Platz-Umkreis und unter 300 ft AGL = Landung.** Sie wird **sofort** final;
  es gibt keine Wartezeit und keinen Zwischenzustand. Jedes erneute Abheben ist ein neuer Leg.
  (`test_immediate_finalize_no_dwell`)
- **Kein Platz im Umkreis oder zu hoch → keine Landung, der Leg bleibt offen.** Deckt Absturz und
  Heli-Hover ab. (`test_heli_hover_over_airport_not_landing`)
- **Go-around/Touch-and-Go lösen nichts aus**, solange die Geschwindigkeit nie unter 2 kt fällt.
  (`test_go_around_never_below_2kt`)
- **Landungs-Rettung (#53):** Bricht der Track in der Luft ab, der letzte Punkt liegt aber im
  Platz-Umkreis und unter 300 ft AGL, gilt der Flug dort als beendet. *Warum:* Aufzeichnungsende
  kurz vor dem Aufsetzen ist häufig; ob es ein sauberer Aufsetzer oder ein Absturz war, ist aus GPS
  ohnehin nicht unterscheidbar — „an diesem Platz beendet" stimmt so oder so.
  (`test_track_ends_airborne_near_airport_within_agl_rescues_landing`)
- **Live-Guard für die Rettung:** Ein gerade laufender Anflug darf nicht geschlossen werden. Bei
  StatSim (`rescue_before=None`) ist jede Aufzeichnung abgeschlossen, dort wird immer gerettet.
  (`test_rescue_before_blocks_rescue_when_last_ts_too_recent`)

### 3.3 Start- und Zielplatz

- **Der nächstgelegene Platz im 4-km-Umkreis gewinnt.** (`test_two_close_airports_nearest_wins`)
- **Spawn-in-der-Luft (#49):** Beginnt die Aufzeichnung erst im Steigflug, gilt der Platz unter dem
  ersten Punkt als Startplatz, wenn dieser im Umkreis und unter 1500 ft AGL liegt.
- **Ergänzungs-Flugplätze** (`custom_airports`, #50) sind seit #56 ein **Override**, kein Fallback —
  ein eingetragener Code verdrängt einen bekannten Platz still. Jeder Eintrag braucht einen Grund.
  Kriterium des Nutzers: eingetragen wird, was im Sim anfliegbar ist. Codes ohne ICAO bekommen das
  Präfix `ZZ`. Details: `.claude/skills/track-diagnose/SKILL.md`.

### 3.4 Vom Leg zum Flug

`collapse_same_airport` fasst Roh-Legs zu Flügen zusammen.

- **Platzrunden am Startplatz gehören zum Flug.** X→X wird in den laufenden Flug absorbiert.
  (`test_circuits_at_departure_then_cross_country`)
- **Aber nur bei kurzer Bodenpause (≤ 300 s).** *Warum (v8.1.0, „Reiner 41 min"):* Bei Absorption
  zählt die Bodenzeit als Flugzeit mit. Eine 41-Minuten-Pause wurde so zu Flugzeit. Die Schwelle ist
  bewusst knapp — zu klein trennt einen langen Taxi-Back kosmetisch in zwei Flüge, zu groß
  verschluckt echte Pausen als Flugzeit. Die zweite Fehlerrichtung ist die schlimmere.
  (`test_pause_splits_circuit_and_cross_country`)
- **Eine echte Zwischenlandung splittet.** (`test_real_intermediate_landing_splits`)
- **Eine Segmentgrenze trennt immer** — auch bei gleichem Platz.
  (`test_segment_boundary_does_not_merge_same_airport`)
- **Eine gerettete Landung wird nie absorbiert.** Sie ist strukturell das letzte Leg ihres Segments.
  (`test_rescued_x_to_x_landing_not_absorbed_as_stop_and_go`)

### 3.5 Segmente und zerschnittene Aufzeichnungen

- **Eine Lücke über 30 Minuten teilt den Track in unabhängige Segmente.** Das ist die einzige
  Trennung, die der Detektor selbst vornimmt. (`test_track_gap_splits_legs`)
- **Die `statsim_id`-Grenze wird respektiert — sie ist die Absicht des Piloten.** StatSim vergibt
  pro *Flugplan* eine neue ID. Wer sie ignoriert, verliert Information (siehe
  [Fallstricke](#fallstricke)).
- **Ausnahme (v8.6.5, `_statsim_rows_continuous`):** Sind **beide Seiten der Naht in der Luft**
  (≥ 60 kt) und Zeit/Distanz/Richtung plausibel, hat StatSim einen durchgehenden Flug zerschnitten —
  dann werden die Positionen zusammengehängt. *Warum das Kriterium stimmt:* In der Luft kann ein
  Pilot keinen Flug beenden und keinen neuen filen. Nur dann ist die neue ID sicher **kein** echter
  Flugwechsel. (Live-Fund KNF04WC, `TestStatsimMidAirSplitContinuity`)

### 3.6 Flugplan-Zuordnung

- **Zeitbasiert, nicht startplatzbasiert:** Jedem Leg wird der zeitlich letzte vorher gefilte Plan
  zugeordnet — unabhängig davon, ob dessen Startplatz passt. (`TestFlightplanAsOf`)
- **Ein Plan A→C gilt für beide Legs einer Zwischenlandung A→B, B→C.**
  (`test_single_plan_covers_intermediate_landing_frs96`)
- **Ein verfrühtes Refile wird bewusst nicht repariert** — der Mismatch bleibt als Pilotenfehler
  sichtbar. (`test_premature_refile_before_landing_is_visible`)

## 4. Die bewussten Asymmetrien

Zwei Regeln sehen ähnlich aus und sind absichtlich gegenläufig. Wer eine davon „vereinheitlicht",
zerstört den Zweck.

| | Spawn-Startplatz (#49) | Landungs-Rettung (#53) |
|---|---|---|
| Bei unbekannter Elevation | **permissiv** — Platz gilt | **konservativ** — keine Rettung |
| Warum | Ein zu spät bemerkter Startplatz ist harmlos falsch-positiv | Eine zu Unrecht gerettete Landung ist ein Korrektheitsfehler |

Dasselbe Muster trägt die Stop-and-Go-Schwelle (lieber zu knapp als zu großzügig) und die
Ergänzungs-Flugplätze (lieber nichts eintragen als falsch).

## 5. Was bewusst *nicht* getan wird

- **Kein geratener Flugzeugtyp** (#52). Der frühere `last_known_aircraft`-Fallback war zeitlich blind
  und zeigte Typen aus der Zukunft des Legs. Ohne Plan-Match bleibt `aircraft` `None`.
- **Kein Ziel aus dem Flugplan.** `arrival` ist immer `gps_arrival`. Ein abgestürzter Flug mit
  gefiletem Ziel darf nicht wie gelandet aussehen. (`test_crashed_flight_keeps_arrival_empty_despite_filed_destination`)
- **Kein Zusammenflicken von Pilotenfehlern.** Wenn ein Flug wegen eines eindeutigen Pilotenfehlers
  nicht erkannt wird, ist das kein Anlass für neue Logik. (Nutzer-Regel, 2026-07-15)
- **Kein per-Event-Radius.** 4 km, datenbasiert, für alles.

## 6. Fallstricke

Belegte Irrwege. Jeder wirkte schlüssig.

### Die `statsim_id`-Grenze ist keine Willkür

**Verworfener Vorschlag:** „Das Cluster-Kriterium ist überflüssig — alle Positionen eines Piloten an
den Detektor geben, der segmentiert ohnehin nach 30-Minuten-Lücken."

**Gegenbeweis FRS146, 2025-06-11** (cid 1167724). Drei IDs, drei Flugpläne:

```
23067234  EDWI->EDDW     23067943  EDDW->EDDW     23068336  EDDW->EDWI
```

Zusammengeworfen ergeben die Positionen fünf Roh-Legs mit den Pausen 1303 s / **150 s** / **136 s** /
406 s. Die beiden kurzen liegen unter der 300-s-Schwelle, also absorbiert `collapse_same_airport` die
zwei eigens gefileten EDDW-Platzrunden in den Streckenflug: `EDDW→EDWI, 16:07:54–16:58:41`. **Zwei
Landungen verschwinden.** Der Pilot hat drei Flüge gefiled, also sind es drei Flüge.

### „Mehr komplette Flüge" ist kein Qualitätsmaß

Derselbe Vorschlag lieferte 2767 statt 2755 komplette Flüge und sah dadurch besser aus. Die Zahl
stieg, **weil Flüge verschmolzen** — jede Verschmelzung macht aus zwei Flügen einen kompletten. Wer
das Kriterium ändert, muss Einzelfälle prüfen, nicht Summen.

### Ein Fall ist kein Muster

NAL3WK (2025-08-04) war der Anlass für Task #1: Track A endet mit 80 kt im Anflug, Track B beginnt
46 s später mit 27 kt am Boden — die Naht-Regel verlangt *beide* Seiten in der Luft und trennt.
Gemessen an allen 363 Nähten des Bestands ist das **der einzige** Fall. Und er richtet keinen Schaden
an: Die #53-Rettung erkennt `EDXW→EDDW` + `EDDW→EDDH` aus Track A allein — identisch zum
Merge-Ergebnis, nur die Landezeit ist 3:16 min zu früh. Task #1 wurde ohne Codeänderung geschlossen.

**Die Lehre:** Vor jeder Regeländerung zählen, wie viele Fälle sie betrifft — und prüfen, ob die
betroffenen überhaupt falsch sind.

## 7. Kennzahlen (Produktionsbestand, 2026-07-15)

| | |
|---|---:|
| Flüge gesamt (`canonicalize_legs`, alle Präfixe) | 2957 |
| davon mit erkanntem Startplatz | 2789 |
| davon komplett (Start **und** Ziel) | 2755 |
| Offene Erkennungslücken (Admin-Liste) | 148 |
| Ergänzungs-Flugplätze (`custom_airports`) | 30 |

Nähte zwischen benachbarten `statsim_id`s desselben Piloten (Positions-Lücke ≤ 30 min), **363** gesamt:

| Ausgang | Anzahl |
|---|---:|
| beide Seiten am Boden → getrennt (richtig: eigener Flugplan) | 339 |
| beide Seiten in der Luft → zusammengefügt | 15 |
| A endet am Boden → getrennt (A ist gelandet) | 6 |
| Zeit-/Distanz-/Richtungsprüfung → getrennt | 2 |
| B beginnt am Boden → getrennt (**NAL3WK**, s. o.) | 1 |

## 8. Verwandte Dokumente

- `docs/architecture.md` — Aufbau, Datenfluss, Endpoints
- `.claude/skills/track-diagnose/SKILL.md` — Diagnose einzelner Tracks und der Erkennungslücken-Liste
- `app/gps_legs.py` — der Detektor; die Docstrings tragen die Begründung je Regel
