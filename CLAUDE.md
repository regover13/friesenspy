# FriesenSpy

VATSIM Live-Tracker für die FriesenFlieger-Gruppe.

## Stack

Python 3.11, FastAPI, APScheduler, SQLite (WAL), httpx, pydantic-settings, airportsdata, ts3

## Lokale Entwicklung

```bash
pip install -r requirements.txt
# config.env anlegen (SECRET_KEY erforderlich; Friesen-Erkennung via CALLSIGN_PREFIX=FRS)
uvicorn app.main:app --reload
# http://localhost:8091
```

## Tests

```bash
pytest tests/ -v
```

**`app/CHANGELOG.json` NICHT anfassen, solange eine Suite läuft.** `version.py` liest die
Datei einmal beim Import, `test_load_changelog_matches_module_constant` liest sie erneut und
vergleicht — wer dazwischen einen Eintrag einfügt, bekommt einen Fehlschlag, der nichts mit
dem Code zu tun hat (zweimal passiert am 04.09.2026). Bei parallelen Sitzungen gilt das auch
für die *andere*: Erst die Suite abwarten, dann die Version schreiben.

## Offene Aufgaben

Vom Nutzer vorgemerkte, noch nicht begonnene Arbeiten stehen in
[`docs/offene-aufgaben.md`](docs/offene-aufgaben.md) — dort nachsehen, bevor etwas Neues
angefangen wird. Am Projekt arbeiten mehrere Sitzungen parallel (auch in der Cloud): vor dem
Start pullen und prüfen, ob eine andere die Aufgabe schon erledigt hat.

**Zwei Nummernräume — nicht verwechseln.** Verweise wie `#23`, `#52` oder `#84` in
Code-Kommentaren sind eine **eigene Zählung**, die nie in GitHub geführt wurde; es gibt
dafür keine Liste, die Nummern leben ausschließlich an den Fundstellen im Code (vergeben
sind 1–84, u. a. in `poller.py`, `geo.py`, `gps_legs.py`, `calendar_sync.py`,
`transport_stacks.py`). **GitHub-Issues** gibt es erst seit dem 04.09.2026; sie beginnen bei
#14. **Die Nummern 14, 15 und 18 existieren dadurch doppelt.**

Im Zweifel entscheidet der Ort: Steht die Nummer in einem Kommentar neben einem beschriebenen
Fund, ist die alte Zählung gemeint — sie mit `gh issue view` nachzuschlagen führt in die Irre.
Neue Funde gehören als GitHub-Issue angelegt, nicht als weitere Kommentar-Nummer.

## `"highlight": false` — „GROSSES UPDATE" vergibt allein der Nutzer (stehende Regel)

Jeder neue Changelog-Eintrag bekommt **`"highlight": false`**. Ohne Ausnahme, egal wie groß die
Änderung sich anfühlt: neue Funktion, neue Karten-Ebene, mehrere Teile in einem Release — der
Haken bleibt aus. Er zeichnet im Versionsverlauf die rote Marke **„GROSSES UPDATE"**, und die
setzt **ausschließlich der Nutzer**, ausdrücklich und in seinen eigenen Worten.

**Die Versionsnummer ist davon unberührt** und keine Streitfrage: Ein Release bekommt die
Nummer, die passt (auch MINOR, 13.6.x → 13.7.0). Wer hier korrigiert, korrigiert `highlight` —
nicht die Nummer.

Am 17.08.2026 schiefgegangen: v13.7.0 ging mit `highlight: true` raus. Beim Zurücknehmen wurde
dann fälschlich die Nummer angefasst statt des Hakens — der Ärger kam von der roten Marke.

## Zum Lesen Bestimmtes muss beim Nutzer ankommen (stehende Regel — IMMER einhalten)

**In einer Cloud-Session sieht der Nutzer keine Datei, die nur im Repo liegt.** Die Sitzung
läuft auf einem fremden Rechner; „steht in `docs/…`" heißt für ihn: nicht lesbar, außer er
sucht es sich auf GitHub zusammen. Das ist mehrfach passiert und war jedes Mal ärgerlich.

**Regel:** Alles, was der Nutzer *lesen* soll — Specs, Entwürfe, Analysen, Berichte,
Vergleiche, Empfehlungen — wird **zusätzlich zum Commit als Artifact veröffentlicht**, und die
Antwort nennt den Link. Nicht auf Nachfrage, sondern unaufgefordert im selben Zug wie der Push.
Wird ein solches Dokument später geändert, wird **dasselbe** Artifact aktualisiert (gleicher
Dateipfad bzw. `url`), damit der Link, den er sich gemerkt hat, weiter stimmt.

Nicht gemeint sind Quelltext, Tests und Konfiguration — die gehören ins Repo und sonst nirgends.
Die Faustregel ist die Absicht: **Soll er es lesen oder soll es laufen?** Nur Ersteres braucht
einen Link.

## Deployment

GitHub Push → main-Branch → GitHub Actions → GHCR → SSH-Deploy auf VPS

- Container: `ghcr.io/regover13/friesenspy:latest`
- Port: 8091 (intern), friesenspy.devprops.de (extern)
- DB: `/opt/friesenspy/data/friesenspy.db` (Volume)
- Config: `/opt/friesenspy/config.env` (niemals in git!)
- **Discord-Meldung nach jedem Deploy:** letzter Schritt in `deploy.yml`, meldet Erfolg (grün, nach
  bestandenem Health-Check) oder Fehlschlag (rot) mit Version, Commit-Titel und Link zum Workflow-Log.
  Braucht das Repo-Secret `DISCORD_WEBHOOK` (Discord-Kanal-Webhook, **ohne** `/github`-Suffix).
  Fehlt das Secret, wird der Schritt übersprungen — der Deploy bleibt grün.

## VPS-Einrichtung (einmalig)

```bash
mkdir -p /opt/friesenspy/data
# config.env anlegen mit echten CIDs + Token
# nginx-Config: nginx/friesenspy.devprops.de.conf einbinden
# certbot: certbot --nginx -d friesenspy.devprops.de
```

## Kniebrett-Standards (stehende Regeln — IMMER einhalten)

- **Im MSFS-Kniebrett hält KEIN Browser-Speicher über einen Sim-Neustart.** Nicht
  `localStorage`, nicht `sessionStorage`, nicht Cookies — unabhängig von Attributen und
  Laufzeiten. Beim Start ist der gesamte Bereich leer (gemessen 16.08.2026: `localStorage` von
  8 Schlüsseln auf 0, gesetztes Cookie fort). Wer etwas merken will, hat genau zwei
  Möglichkeiten: **MSFS' eigene Ablage** (`SetStoredData`, in der EFB-Shell als `DataStore` —
  derselbe Weg wie beim GTN 750), oder den **Server**, verankert an einer dort abgelegten
  Kennung (so machen es `panel_devices` und `panel_prefs`). Eine dritte gibt es nicht.
- **`features.localStorage` in der Selbstdiagnose beantwortet das NICHT.** Die Sonde schreibt
  und liest im selben Atemzug; sie kann „funktioniert" von „überlebt einen Neustart" nicht
  unterscheiden. Dasselbe gilt inzwischen für `speicher.merkerDa` (s.
  `docs/efb-panel-debugging.md`). Der einzige gültige Nachweis ist ein Wert, der **vor** der
  Sitzung geschrieben wurde.
- **Funktioniert etwas im Kniebrett nachweislich, ist es die Vorlage — nicht nur der Beleg.**
  Am 16.08.2026 sind zwei Releases (13.6.0, 13.6.2) verpufft, weil aus „das Anmelde-Cookie hält
  ja auch" auf Cookie-Persistenz geschlossen wurde, statt `_iframe_samesite` und
  `getOrCreateDeviceId` zu lesen. Beide hätten die Antwort gegeben; in `panel_devices` stand
  seit dem 13.08. wörtlich, dass Coherent GT Cookies nur im Speicher hält. Erst die
  Konfiguration des funktionierenden Vorbilds lesen, dann die eigene schreiben.

- **Der Cache-Buster des Panels hängt am Dateihash, nicht an der Versionsnummer.**
  `/panel` leitet auf `/panel?v=<VERSION>.<kurzhash der index.html>` um. Der Hash ist kein
  Beiwerk: Am 24.08.2026 wurde einen ganzen Tag lang bei unveränderter Version 13.8.2
  zwölfmal deployt — die URL blieb dieselbe, Coherent GT lieferte aus dem Cache, und im
  Kniebrett kam **keine einzige** Änderung an. Wer den Kennwert wieder auf `VERSION` allein
  zurückdreht, baut genau diese Falle neu; `tests/test_vr_panel.py` prüft gegen
  `_panel_kennwert()` und nicht gegen `VERSION`.

- **Ein Deploy startet den Container neu und trifft jede offene Sitzung.** SSE bricht ab,
  laufende Anfragen sterben. Am 24.08.2026 wurde dreimal deployt, nachdem ein Mitglied sein
  EFB-Panel geöffnet hatte; sein Tablet war danach schwarz. Änderungen sammeln statt einzeln
  ausliefern, und zu Flugzeiten vorher fragen. Ob jemand fliegt, steht im nginx-Log
  (`/panel`, `/api/live`).

## UI-Standards (stehende Regeln — IMMER einhalten)

- **Blau (#2d9cdb, CSS-Variable `--green` — historischer Name!) ist Klickbarem vorbehalten:**
  Links, klickbare Strecken-Zellen, klickbare Zeilen. Callsigns und andere reine Anzeige-Texte
  bleiben neutral (weiß/mono) — „blau = da passiert was beim Klick" muss überall stimmen.
- **Breite Tabellen/Feeds sind auf dem Smartphone horizontal scrollbar, nie gequetscht:**
  jede Tabelle gehört in einen Wrapper mit `overflow-x: auto; -webkit-overflow-scrolling: touch`,
  und die Tabelle selbst braucht `width: max-content; min-width: 100%` (sonst hat der Wrapper
  nichts zu scrollen). Fertige Klassen: `.table-scroll` (index.html), `.table-wrap` (admin.html).
  Gilt ausdrücklich auch für alle NEUEN Ansichten (z. B. kommende Kutter-Live-Ansicht).
  **Flexbox-Falle (v8.6.5-Fund):** liegt der Wrapper in einem Flex-Container (z. B. `#app` in
  admin.html, `display:flex; flex-direction:column`), reicht `.table-wrap`/`.table-scroll`
  allein NICHT — Flex-Items dürfen sich per CSS-Default nicht unter ihre Inhaltsbreite
  schrumpfen (`min-width:auto`), eine breite Tabelle sprengt dann das ganze Flex-Item und
  `overflow-x:hidden` am `body` schneidet den Überstand einfach ab, statt dass die innere
  Scrollbar greift. Jeder Flex-Item-Container um eine scrollbare Tabelle braucht zusätzlich
  `min-width: 0` (in admin.html bereits auf `.panel` gesetzt).
  **Verschachtelungs-Falle (v8.6.6-Fund, wichtiger als die Flexbox-Falle oben):** steckt
  `.table-wrap` INNERHALB einer vertikal begrenzten `.scroll-list` (`max-height:280px;
  overflow-y:auto` — Piloten/Flugplätze/Erkennungslücken), braucht `.table-wrap` selbst
  ZWINGEND dieselbe Höhenbegrenzung (`.scroll-list .table-wrap { max-height: 280px; overflow:
  auto; }`). Ohne sie ist `.table-wrap` so hoch wie die GESAMTE Tabelle (bei vielen Zeilen
  mehrere tausend Pixel) — seine horizontale Scrollbar sitzt dann an SEINEM EIGENEN unteren
  Rand, weit unterhalb des durch `.scroll-list` sichtbar gemachten 280-px-Fensters, und ist
  praktisch nie zu sehen (auch mit korrektem `overflow-x:auto`!). **Zusätzlich (unabhängiges
  zweites Problem, gleicher Fund):** Windows/Edge/Chrome blenden eine technisch korrekt
  scrollende Box trotzdem unsichtbar, wenn keine Scrollbar-Styles gesetzt sind (Overlay-
  Scrollbar, nur bei aktivem Hover/Scrollen sichtbar) — `scrollbar-width`/`scrollbar-color`
  (Firefox) + `::-webkit-scrollbar*` (Chrome/Edge/Safari) erzwingen eine dauerhaft sichtbare
  Leiste. Beide Fixes sind nötig, einer allein reicht nicht — vor jeder neuen scrollbaren
  Tabelle in `.scroll-list` beide prüfen. Bei vielen Spalten zusätzlich erwägen, Aktionen-
  Buttons in eine eigene Zeile UNTER die Daten zu legen (`colspan`), statt in eine Spalte ganz
  rechts, die sonst erst nach Scrollen erreichbar ist (Erkennungslücken-Muster).

- **Eine Geste, die auf dem ganzen Dokument lauscht, muss Karte und Scroll-Bereiche
  aussparen.** Das Herunterziehen zum Aktualisieren (`_ziehErlaubt`, v14.20.0) hängt an
  `document` und feuert damit über jedem Element. Auf dem Karten-Tab steht die Seite *immer*
  ganz oben (`scrollY === 0`) und die Leaflet-Karte füllt fast den Bildschirm — ohne die
  Ausnahme für `.leaflet-container` hätte jedes Verschieben des Ausschnitts nach Süden die
  App aktualisiert. Dasselbe gilt für `.scroll-list`/`.table-scroll`: dort entscheidet der
  `scrollTop` des **Vorfahren**, nicht der des berührten Elements. Wer eine weitere solche
  Geste baut, prüft beide Fälle — `tests/test_zieh_aktualisieren.py` ist die Vorlage.

## AIP-Kartenblätter (stehende Regeln — IMMER einhalten)

Sichtflug-, Flugplatz- und Rollkarten der DFS, als Ebenen über der Live-Karte. Seit dem
31.08.2026 vollständig ohne Automatik — der Rückbau war eine ausdrückliche
Nutzerentscheidung („Wir bauen die Automatik komplett zurück. Für alle Kartentypen! Wir
belassen es bei einer einfachen Hash-Aktualitätsprüfung.").

- **Eine Tabelle: `aip_charts_dfs`, Schlüssel `(icao, sorte)`.** Nicht `icao` allein — alle
  110 Plätze mit Flugplatzkarte haben auch eine Sichtflugkarte (gemessen), mit einteiligem
  Schlüssel kollidierten genau diese 110 Zeilen. Dasselbe gilt im Frontend: `_groundAktiv`
  und Geschwister halten `"<ICAO>|<sorte>"`, nie die nackte ICAO.
- **Eine Passung entsteht ausschließlich aus zwei geklickten Punkten mit Koordinaten**
  (`ground_charts.handpassung`). Wer Rahmenerkennung, Gradnetz-Vermessung oder
  Ziffernlesen zurückbaut, baut etwas zurück, das bewusst entfernt wurde: Das Verfahren kam
  über drei von 107 Plätzen nicht hinaus, weil 271 der 446 Plätze in OurAirports keine
  Schwellenkoordinaten haben. `tests/test_aip_charts.py` und `tests/test_ground_charts.py`
  binden an die **Abwesenheit** dieser Funktionen.
- **`nicht_gefunden` wird geschrieben, nicht hergeleitet.** Ein Platz ohne Zeile heißt
  „nicht nachgesehen" — das ist kein Status, sondern die Abwesenheit eines Eintrags. Wäre
  der Status hergeleitet, ließe sich „ich habe nachgesehen, es gibt keine" nicht
  festhalten, und die Arbeitsliste bliebe dauerhaft unabarbeitbar.
- **Die Seite wird als `seite_nr` geführt, nie als URL.** Eine DFS-Seiten-URL enthält den
  AIRAC (`…/BasicVFR/2026AUG20/pages/…`) und liefert nach dem nächsten Zyklus 404 — für
  **alle** Zeilen gleichzeitig, und zwar genau dann, wenn sich Blätter ändern könnten. Der
  dauerhafte Bezeichner ist `airport_links.aip_url`; der Job löst daraus frisch auf.
- **`gesehener_hash` ist der DFS-Rohbytes-Hash, über den zuletzt jemand geurteilt hat** —
  nicht der Hash der Datei auf der Platte. Nach einem „verwerfen" fallen die beiden
  auseinander, und das ist richtig so: Ohne das Nachziehen fände der nächste Wochenlauf
  denselben abweichenden Hash und legte die Zeile sofort wieder vor.
- **Die Sperre heißt `PassungGesperrt`, ihr Prädikat ist `status='gepasst'`** (früher
  `quelle='hand'`). Sie greift nur, wenn ein **Lagefeld** mitkommt — der Wochenlauf soll
  melden können, ohne die Passung anzurühren. Sie ist weiterhin nötig, obwohl kein Job mehr
  rechnet: Der Seitenwähler bleibt, und am 25.08.2026 hat genau der EDAZ auf 0/0/0/0
  gesetzt.
- **Eine Karte ohne Passung geht nie nach `pruefen`.** Die Frage „stimmt die Passung auf dem
  neuen Blatt noch?" ist dort gegenstandslos; bei `offen` wird das neue Blatt schlicht das
  gültige. Damit kann eine Zeile mit `nord=sued=west=ost=0` konstruktiv nicht in einen
  Zustand geraten, aus dem ein Fehlgriff sie ans Kniebrett ausliefert.
- **Die Platzkarte liegt per `zIndex` über der Sichtflugkarte, nie an ihrer Stelle.** Ein um
  37° gedrehtes Blatt wird als achsenparalleles Rechteck abgelegt, dessen Ecken durchsichtig
  sind (bei EDDL rund die halbe Fläche) — die füllt die Sichtflugkarte darunter. **Nicht**
  über `bringToFront()`: Das hängt an der Einfügereihenfolge und kippt, sobald eine Karte
  nach dem SSE-Ereignis neu geladen wird.
- **`aip_charts`, `aip_ground_charts` und `aip_chart_vorschlaege` sind stillgelegt, aber
  nicht gelöscht.** Sie tragen die Daten, aus denen die Migration liest. Ein `DROP` ist eine
  eigene, bewusste Entscheidung — erst wenn der neue Stand geprüft ist.
- **Keine Datenbank-Transaktion darf einen Netzabruf umspannen.** Der Wochenlauf committete
  anfangs erst am Ende und hielt damit eine Schreibtransaktion über hunderte DFS-Abrufe
  offen. In WAL bleiben Leser unberührt, andere **Schreiber** nicht: `save_prefile_sigs` im
  15-Sekunden-Poll scheiterte am 31.08.2026 79 Mal mit „database is locked". Jetzt wird nach
  jedem Schreiben committet.
- **Die Höflichkeitspause gehört in den Abrufer, nicht neben die Aufrufstelle.** Stand sie
  nur um die zwei offensichtlichen Abrufe je Karte, ging die Kapitelauflösung ungebremst
  durch — gemessen 28 Anfragen je Sekunde auf aip.dfs.de. In `_hole()` gebunden ist jeder
  Weg zur DFS gebremst, auch ein künftiger.

## Datenbank (stehende Regeln — IMMER einhalten)

- **Keine Datenbank-Transaktion darf einen Netzabruf umspannen.** Die Regel steht auch bei den
  AIP-Kartenblättern, gilt aber überall — sie ist auf dieser Codebasis inzwischen **dreimal**
  verletzt worden, jedes Mal mit demselben Bild: `database is locked` bei allen anderen
  Schreibern, HTTP 500 bei echten Nutzern, eine App, die für Minuten nicht antwortet.
  Der AIP-Wochenlauf hielt sie über hunderte DFS-Abrufe (31.08.2026), `_fetch_statsim_tracks`
  2 min 43 s (14.20.3), `_check_transport_events` über den Anthropic-Aufruf (14.20.6).
  Das Muster für den Ausweg steht in `_gen_flight_quip`: Kontext lesen, committen, schließen,
  **dann** das Netz fragen, für das Schreiben eine frische Verbindung.
- **`busy_timeout` steht auf 15 s (`get_connection`) — das ist das Netz, nicht die Lösung.**
  Es macht aus einem Fehler eine Verzögerung. Wer ihn hebt, weil „es wieder klemmt", verlängert
  nur die Zeit, in der niemand merkt, dass eine Transaktion hängt. 15 s = ein Poll-Zyklus: Was
  länger braucht, ist kein Gedränge mehr.
- **Wenn die App langsam wird: erst die Log-Zeile lesen, dann den Container neu starten.**
  Der Neustart setzt die Kurve zurück (20 s Ausfall) — er löscht aber auch die Spur, also
  vorher `docker logs friesenspy-friesenspy-1 | grep "Poll-Zyklus langsam"` wegschreiben.
  **Zwei naheliegende Hebel sind gemessen und fallen aus** (04.09.2026, Belege im Kommentar
  zu GitHub-Issue #16):
  *Andere Container abschalten (Condor)* — die Maschine hatte Luft, Load maximal 4,2 bei
  6 Kernen, FriesenSpy selbst nie über 0,8 Kerne (13,7 % → 78,6 % über den Abend).
  *Höhere Priorität / nice / `cpu_shares`* — der Wartedruck auf CPU (PSI `cpu_some_pressure`)
  lag im Maximum bei **2,12 %**, `throttled` durchgehend 0, und Limits gibt es keine
  (`NanoCpus=0, CpuShares=0, CpuQuota=0`). Der Prozess wartete nicht auf Rechenzeit, er war
  beschäftigt; Priorität regelt aber nur die Reihenfolge bei Gedränge.
  Wirksam wäre allein ein Eintrag im Docker-Watchdog (`/opt/docker-watchdog/watchdog.sh`,
  Vorgabe 200 % — bei 79 % schlägt der nie an, nötig wären ~120 %). **Bewusst nicht gesetzt:**
  Ein automatischer Neustart reisst offene Sitzungen und Kniebretter ab und löscht die Spur,
  bevor jemand sie gelesen hat. Erst einen echten Fall messen.
- **Ein Leg ohne `logoff_time` heißt nicht „fliegt noch" — es heißt „GPS sah keine
  Landung".** Wer nach dem Ende eines Legs fragt, nimmt `logoff_time or last_pos_ts`.
  `_in_window` prüfte nur `logoff_time` und ließ Legs ohne Landung unabhängig vom Fenster
  durch; die Events-Karte zeichnete dadurch einen Flug von 09:42Z in ein Fenster ab 17:00Z
  und stand danach im Nordatlantik (14.20.4). Dasselbe Feld trägt `connection_closed`, das
  aus demselben Grund NICHT „Flug beendet" bedeutet (s. `canonicalize_legs`).
- **Wird der Poller langsam, steht die Aufschlüsselung im Log** (`Poll-Zyklus langsam: … —
  abruf 3,10 s · db 0,40 s …`, ab 2 s Gesamtlaufzeit). Sie misst Wanduhr, nicht Rechenzeit:
  Ein blockierter Event-Loop zeigt sich als Wartezeit in einem *fremden* Abschnitt — die
  Aufschlüsselung sagt, wo gewartet wurde, und benennt damit nicht zwingend den Schuldigen.

## Projektstruktur

- `app/config.py` — pydantic-settings, CALLSIGN_PREFIX (Friesen-Erkennung), ADMIN_PASSWORD, VAPID
- `app/database.py` — SQLite WAL, alle DB-Funktionen
- `app/vatsim.py` — VATSIM-API-Client
- `app/geo.py` — Haversine, ICAO→Koordinaten, Event-Filter
- `app/aip_charts.py` — DFS-Blätter beschaffen und ablegen (AIRAC-Auflösung, Kapitelseiten)
- `app/ground_charts.py` — Blattkunde, Handpassung aus zwei Punkten, Nordung
- `app/runway_ref.py` — Bahnschwellen aus OurAirports (Hilfe beim Passen)
- `scripts/aip_bestand.py` — Wochenlauf: Hash-Vergleich, meldet Änderungen, rechnet nichts
- `app/alerts.py` — Telegram-Alerts (silent fail)
- `app/teamspeak.py` — TeamSpeak-ServerQuery-Client (parse_frs, fetch_channel_clients)
- `app/poller.py` — APScheduler, Flug-State-Machine, SSE-Queue
- `app/main.py` — FastAPI-App, REST + SSE-Endpoints
- `app/static/index.html` — Vanilla-JS-SPA (4 Tabs)
- `msfs-panel/` — MSFS-2024-EFB-App "FriesenSpy" (Coherent-GT-Panel, rendert `/panel` per
  iframe); eigener Node/esbuild-Build, s. `docs/superpowers/specs/2026-08-12-msfs-efb-panel-design.md`

## Konfiguration (config.env — NIE in git)

```bash
# Friesen werden über das Callsign-Präfix erkannt (NICHT über eine CID-Liste).
CALLSIGN_PREFIX=FRS              # Default: FRS
SECRET_KEY=<random-string>
PUSH_OVERVIEW_PASSWORD=          # Optional — Extra-Passwort für die versteckte Push-Diagnose
                                 # (/admin/push-overview, unscheinbarer Link ganz unten im Admin).
                                 # Leer = Feature komplett aus (Seite/Endpoint = 404).
TELEGRAM_BOT_TOKEN=          # Optional
TELEGRAM_CHAT_ID=            # Optional
VATSIM_POLL_INTERVAL=15
VATSIM_REJOIN_DEBOUNCE_SEC=900   # Default: 900 s (15 min) — Reconnect-Fenster Online-Push
LOG_LEVEL=INFO                   # Default: INFO — App-Logger sichtbar (unter uvicorn sonst nur WARNING+)
DB_PATH=/opt/friesenspy/data/friesenspy.db
ANTHROPIC_API_KEY=               # Optional — FriesenKutter-Zuladungs-Vorschlag (Claude Haiku 4.5 + Web-Search,
                                 # llm.py:25 _SUGGEST_MODEL, seit v7.4.2 — NICHT Sonnet 5; Sonnet 5 macht nur die
                                 # Sprüche, llm.py:295). Denselben Key wie TSBot verwenden.

# TeamSpeak-Login-Benachrichtigung (Phase 1, alle Optional)
TS_NOTIFY_ENABLED=false      # Default: false — Feature aktivieren
TS_HOST=127.0.0.1            # Default: 127.0.0.1
TS_QUERY_PORT=10011          # Default: 10011
TS_QUERY_USER=               # ServerQuery-Login
TS_QUERY_PASS=               # ServerQuery-Passwort
TS_SERVER_ID=1               # Default: 1
TS_NOTIFY_CHANNEL_ID=0       # Default: 0 = ganzer Server; sonst Kanal-ID
TS_EXCLUDE_CHANNEL_IDS=      # CSV Kanal-IDs, die nie benachrichtigen (z. B. Verwaltung)
TS_MIN_DWELL_POLLS=1         # Verweildauer: muss beim Folge-Poll noch da sein (0 = sofort)
TS_POLL_INTERVAL=30          # Default: 30 Sekunden
TS_REJOIN_DEBOUNCE_SEC=900   # Default: 900 s (15 min) Debounce gegen Re-Join-Spam
```

Hinweis: Der `ts_poll`-Job läuft jetzt, sobald `TS_NOTIFY_ENABLED=true` (Live-Anzeige im
Live-Tab + Widget-Zähler, gespeist aus `poller.ts_clients` via `/api/teamspeak`). VAPID ist
nur noch für Push-Benachrichtigungen nötig, nicht für die Anzeige.

## Cloud-Session: wenn CLI-`git` kein Credential hat (Fallback)

In einer Claude-Code-**Cloud-Session** (claude.ai/code) bekommt CLI-`git` normalerweise ein
kurzlebiges, scoped GitHub-Installations-Token über den Proxy — es liegt KEIN Key/PAT dauerhaft
im Container (so soll es sein). Schlägt die Token-Ausstellung beim Container-Start fehl, stehen in
`GITHUB_TOKEN`/`GH_TOKEN` nur Platzhalter und **`git push` bricht** mit
`could not read Username/Password … terminal prompts disabled` ab. Das ist ein
Provisionierungs-Fehler der Session, **kein** Repo-, Netz- oder Setup-Bug (github.com ist über den
Egress-Proxy erreichbar; MCP-GitHub-Tools funktionieren derweil weiter, anderer Auth-Pfad).

**Wichtig — nur der SCHREIBpfad ist betroffen:** Dieses Repo ist **public**, deshalb funktionieren
`clone`/`fetch`/`git ls-remote origin` **immer anonym, ganz ohne Credential**. Ein erfolgreicher
Lesetest beweist also NICHT, dass `push` geht — das war der reale Fall (Klonen ging, Push nicht).
**Schnelltest zu Session-Beginn deshalb mit dem Schreibpfad:** `git push --dry-run origin HEAD`
— authentifiziert und prüft die Refs, überträgt/ändert aber nichts. Geht das ohne Prompt, geht
auch der echte `push`.

**Recovery, in dieser Reihenfolge:**
1. **Dauerhafter Fix (nur der Nutzer):** GitHub-App-Verbindung in claude.ai/code → GitHub-Integration
   für `regover13/friesenspy` neu autorisieren. Danach stellt jede neue Session ihr Token wieder
   korrekt aus. Das ist der eigentliche Hebel — aus der Session heraus NICHT reparierbar.
2. **Frische Cloud-Session** starten (war es ein einmaliger Ausstellungs-Fehler, ist sie sauber).
3. **Ohne CLI-git trotzdem liefern:** Doku/Einzeldateien via GitHub-**MCP-Tools** direkt committen;
   ganze Code-Stände über den **Bundle-Weg** übergeben. Beides funktioniert nachweislich.
4. NICHT tun: 8× mit Backoff retryen, Session-Ingress-Token als Credential missbrauchen, oder
   dauerhaft einen PAT/SSH-Key in der Cloud hinterlegen.

**Signatur-„Fehler" `%G? = N` ist ein False Positive:** Die Commit-Signatur-Prüfung passiert im
Cloud-**Harness**, nicht im Repo (dieses Repo hat KEINE eigenen git-Hooks und keine
`gpg.ssh.allowedSignersFile`). Der Sandbox fehlt nur die `allowedSignersFile` für die lokale
*Verifikation* — die Commits tragen trotzdem eine gültige SSH-Signatur. Kein History-Rewrite
deswegen (ändert nur SHAs bereits gepushter Branches).
