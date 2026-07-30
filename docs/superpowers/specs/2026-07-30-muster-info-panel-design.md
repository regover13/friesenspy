# Muster-Info-Panel — Aircraft-Designator überall anklickbar

**Status:** Design (2026-07-30). Neues Feature. Teil 8 (Retry/Nachlese der Zuladungs-Recherche)
ist ein eigenständiger Bugfix und unabhängig auslieferbar.

## Ziel

Der Aircraft-Designator (`C172`, `AS65`, `PZ04` …) wird in **allen** Sichten anklickbar. Der Klick
öffnet ein Modal mit Foto, Muster-Name, Kurztext, den Friesen-Zahlen zu diesem Muster und den
gepflegten Kutter-Gewichten.

## Nutzer-Entscheidungen 2026-07-30

- **Inhalt:** Foto + Kurztext **und** Friesen-Bezug (Variante C), gestaffelt umgesetzt — der
  Friesen-Teil läuft ohne externe Quelle und ist damit nie leer.
- **Fotoquelle:** Wikimedia Commons, **serverseitig geholt und gecacht**. Lizenz, Urheber und
  Beleg-URL werden mitgespeichert und unter dem Bild angezeigt. GFDL-only wird übersprungen.
  Kein Hotlink — keine Besucher-IP an Dritte.
- **Textquelle:** Wikipedia-Extract (Einleitungssätze) mit Quellenangabe. **Kein LLM-Text.**
- **Friesen-Zahlen:** Kernzahlen (Flüge, Stunden, Strecke, Piloten, Zeitraum), **Top-Piloten**
  auf dem Muster, **Kutter-Daten** (MTOW, Leergewicht, Zuladung). Der „letzte Flug damit" wurde
  bewusst **nicht** gewählt.
- **Eigene Fotos:** Admin kann ein eigenes Bild hochladen (Sim-Screenshot o. Ä.), mit optionalem
  Bildnachweis.
- **Alias:** Tippfehler-Kürzel sind auf das richtige Muster umbiegbar (`P24 → PA24`), und die
  Flüge des Alias **zählen zum Zielmuster**.
- **aviatordb.com: nicht in der ersten Version.** Begründung s. „Verworfene Quellen".

## Context — was schon da ist

- `aircraft_payloads` (`database.py:263`), PK `type_code` (normalisiert): **119 Muster**, davon
  118 mit `make_model` — 100 `curated`, 12 `manual`, 7 `llm`. Zweck der Tabelle sind die
  **Kutter-Zuladungen**, nicht Muster-Wissen allgemein.
- `normalize_type_code()` (`database.py:4136`) — Uppercase, vor `/` gekürzt.
- `llm.suggest_aircraft_payload()` (`llm.py:166`) — Claude Sonnet 5 mit Web-Search, liefert
  `make_model` + Gewichte.
- `poller._auto_research_payload()` (`poller.py:1387`) — füllt neu gesehene Typen automatisch vor.
- Admin-Panel „Kutter-Zuladungen" (`admin.html:944 ff.`) mit Bearbeiten + „Vorschlag holen".
- Volume `./data:/opt/friesenspy/data` (`docker-compose.yml`) — Unterordner überleben
  Container-Neubauten. `/static` mountet dagegen **aus dem Image**, Fotos brauchen eine eigene Route.
- Pillow 12.3.0 ist im Container vorhanden (`requirements.txt: pillow>=10.0`).

**Gemessen am Produktionsstand (2026-07-30):** `flight_cache` enthält **40 verschiedene**
Designatoren über 2248 Flüge. **36 davon haben einen `aircraft_payloads`-Eintrag.** Ohne Eintrag:
`AP32` (5 Flüge), `TL20` (2), `PC21` (2), `PIVI` (1) — zusammen 10 Flüge, also **99,6 % Abdeckung**
nach Flugzahl. Das Namensproblem ist im Bestand fast gelöst; es fehlt praktisch nur das Foto.

**Backup-Randbedingung (wichtig für die Speicherwahl):** `/opt/backup/scripts/backup_onedrive.sh:225`
sichert von FriesenSpy **nur die Datenbank** (`sqlite3 .backup`), nicht das Datenverzeichnis. Alles,
was als Datei unter `data/` liegt, ist **nicht** im nächtlichen OneDrive-Backup.

## Datenmodell

Neue Tabelle **`aircraft_types`** — bewusst **nicht** als Erweiterung von `aircraft_payloads`.
Grund: `get_payload_map()` (`database.py:4152`) speist die Kutter-Frachtrechnung und `payload_kg`
ist `NOT NULL`. Jede Zeile dort ist eine Aussage darüber, was ein Muster tragen kann. Ein Muster
nur wegen seines Fotos einzutragen würde es mit einem erfundenen Zuladungswert in die Frachtlogik
schmuggeln.

```sql
CREATE TABLE IF NOT EXISTS aircraft_types (
    type_code           TEXT PRIMARY KEY,   -- normalize_type_code()
    alias_of            TEXT,               -- Tippfehler-Kürzel → echtes Muster (ein Schritt)

    -- importiert: NUR der Import schreibt diese Spalten
    name                TEXT,               -- Hersteller + Modell
    name_source         TEXT,               -- 'payloads' | 'llm'
    wiki_lang           TEXT,               -- 'de' | 'en'
    wiki_title          TEXT,
    extract             TEXT,
    photo_file          TEXT,               -- Dateiname im Cache-Verzeichnis
    photo_licence       TEXT,
    photo_artist        TEXT,
    photo_source_url    TEXT,               -- Commons-Beschreibungsseite

    -- Korrektur: NUR der Admin schreibt diese Spalten
    name_override       TEXT,
    extract_override    TEXT,
    wiki_title_override TEXT,
    photo_override      TEXT,               -- NULL | '-' (kein Foto) | 'blob' (Upload)
    photo_blob          BLOB,
    photo_credit        TEXT,               -- Freitext, gilt für den Upload

    -- Zustand
    fetch_state         TEXT,               -- 'neu' | 'ok' | 'nichts_gefunden' | 'fehler'
    attempts            INTEGER NOT NULL DEFAULT 0,
    checked_at          TEXT,
    updated_at          TEXT
);
```

### Import und Korrektur stehen nebeneinander

Angezeigt wird immer `COALESCE(<feld>_override, <feld>)`. Das ist kein Stilmittel, es löst ein
konkretes Problem: mit einem einzelnen `source`-Feld pro Zeile (wie bei `aircraft_payloads`) würde
**eine** Korrektur die ganze Zeile als `manual` markieren, und das Muster bekäme nie wieder ein
aktualisiertes Foto.

Daraus folgt ohne jede Sperrlogik:

- Eine Korrektur überschreibt nichts, sie legt sich darüber. Andere Felder bleiben am Import und
  werden weiter aktualisiert.
- Korrektur leeren = Importwert gilt wieder, verlustfrei.
- Der Import kann eine Korrektur **strukturell** nicht zertreten, weil er ihre Spalten nicht kennt.

### Alias

`alias_of` wird **einen Schritt** aufgelöst. Selbstbezug (`X → X`) und Ketten (Ziel ist selbst ein
Alias) werden beim Speichern **abgelehnt**, nicht verfolgt. Ein Alias-Kürzel hat keine eigenen
Muster-Daten; es zeigt die des Ziels.

Die Friesen-Zahlen aggregieren über Zielmuster **und** alle darauf zeigenden Aliasse. Damit die
Zahl nachvollziehbar bleibt, schreibt das Panel die Herkunft dazu:

> 18 Flüge (2 davon als `P24` erfasst)

Ohne diesen Zusatz stimmt die angezeigte Zahl nicht mehr mit einer einfachen Abfrage auf
`flight_cache` überein — das war die benannte Schwäche dieser Entscheidung und ist damit entschärft.

## Auflösung eines Musters

### Name

Rangfolge, stark nach schwach:

1. `name_override` — Admin-Eintrag, schlägt alles
2. `aircraft_payloads.make_model` — eure 100 kuratierten + 12 manuellen Namen
3. `llm.suggest_aircraft_payload()` — bestehende Recherche, mit Retry (Teil 8)

### Wikipedia und Foto

`COALESCE(wiki_title_override, wiki_title)` — ist keins gesetzt:

1. `de.wikipedia` `action=query&list=search&srsearch=<Name>` → erster Treffer
2. `de.wikipedia` `/api/rest_v1/page/summary/<Titel>` → `extract`, `description`,
   `originalimage`/`thumbnail`, `wikibase_item`
3. Kein de-Artikel → dasselbe auf `en.wikipedia`
4. Commons `action=query&prop=imageinfo&iiprop=extmetadata|url` für die Bilddatei →
   `LicenseShortName`, `Artist`, `Credit`, `LicenseUrl`, `descriptionurl`

**Gemessen:** die Suche verträgt eure spezifischen Namen. `srsearch="Cessna 172S Skyhawk"` →
erster Treffer `Cessna 172`. Der **direkte** Lemma-Aufruf mit demselben String ergibt dagegen
**HTTP 404** — deshalb immer über die Suche, nie den Namen als Lemma raten.

### Der Treffer wird geprüft, nicht geglaubt

Die Wikipedia-Suche liefert praktisch immer *irgendetwas*. Beide Bedingungen müssen halten:

1. Der gefundene Titel teilt mindestens ein bedeutungstragendes Wort (≥ 3 Zeichen, kein Füllwort)
   mit dem Herstellerteil des Namens.
2. Das `description`-Feld der Summary weist auf ein Luftfahrzeug hin (`Flugzeug`, `Hubschrauber`,
   `Ultraleicht`, `Segelflugzeug`, `aircraft`, `airliner`, `helicopter`, `glider` …).

Fällt eine durch → `fetch_state = 'nichts_gefunden'`, **kein Text, kein Bild**. Das ist eine
Heuristik mit sicherer Fehlerrichtung: sie zeigt im Zweifel nichts statt etwas Falsches.

Ein **Admin-gesetztes Lemma umgeht die Prüfung** — das ist eine bewusste menschliche Entscheidung.

**Was die Prüfung ausdrücklich nicht kann:** `PZ` ist ein gültiger Designator (`PZL.43`, ein
polnischer Bomber von 1938), aber mit Sicherheit nicht das, was der Pilot geflogen hat. Die Prüfung
würde den Bomber brav bestätigen. Das ist ein **Eingabefehler**, kein Auflösungsfehler, und dafür
gibt es den Alias.

### Lizenzfilter

Verwendet werden nur Bilder mit CC0, Public Domain, CC-BY oder CC-BY-SA. **GFDL-only wird
übersprungen** (Copyleft mit Volltextpflicht, für eine Web-Anzeige unpassend). Konkreter Fall:
das Commons-Foto zur `C172` steht unter *GFDL 1.2* — dieses Bild fällt also durch, das Muster
bekommt kein Foto, bis ein Admin eins hochlädt oder ein anderes Lemma setzt.

Angezeigt wird unter jedem Commons-Bild: Urheber, Lizenzkürzel, Link auf die Beschreibungsseite.

## Datenfluss — wer füllt wann

**Drei Auslöser, keiner im Klickpfad.**

1. **Poller**, wie bei den Zuladungen: ein neu gesehener Typcode wird gefüllt.
2. **Nachlese beim Start** über `SELECT DISTINCT aircraft_icao FROM flight_cache` (aktuell 40
   Kürzel, also billig) — schließt genau die Klasse von Lücken, die `AP32` gerissen hat.
3. **Faul beim Klick**, falls trotzdem etwas fehlt — aber **nie synchron**: die API antwortet
   sofort mit den Friesen-Zahlen und `state`, der Abruf wird im Hintergrund angestoßen.

### Retry-Semantik

Der Zustand steht **in der DB**, nicht in einem Set im Prozessgedächtnis:

| `fetch_state` | Bedeutung | Nächster Versuch |
|---|---|---|
| `neu` | noch nie versucht | sofort |
| `ok` | aufgelöst | keiner |
| `nichts_gefunden` | inhaltlich erledigt | nach 30 Tagen |
| `fehler` | Netz, 5xx, Timeout | Backoff: 5 min, 30 min, 4 h, dann täglich |

`fehler` ist **kein Endzustand**. `Overloaded` ist kein „keine Daten" — genau diese Verwechslung
hat `AP32` zwei Monate offen gehalten (s. Teil 8).

## API

- **`GET /api/aircraft/{code}`** → `{ code, alias_of, resolved_code, name, extract, wiki_url,
  photo_url, photo_credit, photo_licence, photo_artist, photo_source_url, state,
  friesen: { fluege, stunden, nm, piloten, von, bis, alias_anteil },
  top: [ { cid, callsign, name, n } ], kutter: { mtow_kg, empty_kg, payload_kg } }`
  Liefert **immer 200**, auch für ein unbekanntes Kürzel — die Friesen-Zahlen sind dann trotzdem echt.
- **`GET /api/aircraft/{code}/photo`** → Bild. Liegt ein `photo_blob` vor, **gewinnt er** über
  `photo_file`. Explizites `Content-Type`, nie `text/html`. `Cache-Control` gesetzt.
- **`GET /api/admin/aircraft-types`** → Liste mit Import- und Korrekturwerten, `fetch_state`,
  `checked_at`, `attempts`.
- **`POST /api/admin/aircraft-types`** → Overrides, `alias_of`, `photo_credit` setzen/leeren.
- **`POST /api/admin/aircraft-types/{code}/refetch`** → neu holen (nutzt `wiki_title_override`,
  falls gesetzt). Schreibt nur Import-Spalten.
- **`POST /api/admin/aircraft-types/{code}/photo`** → Upload.

### Upload

Das Bild wird mit **Pillow** dekodiert und neu geschrieben, max. 1280 px Breite, JPEG. Das erledigt
drei Dinge in einem Schritt:

- **Prüfung** — was Pillow nicht als Bild öffnet, ist keins. Dateiendung und der vom Browser
  gemeldete Content-Type werden nicht geglaubt.
- **EXIF fällt weg.** Ein Handyfoto vom Cockpit trägt sonst GPS-Koordinaten in die Datenbank einer
  öffentlichen Seite.
- **Größe** — typisch 100–200 KB statt mehrerer MB. Grenze **8 MB** vor der Umwandlung.

Der Speicherort ergibt sich aus der Backup-Randbedingung oben:

| Art | Speicher | Warum |
|---|---|---|
| Commons-Foto | Datei unter `data/aircraft-photos/` | wegwerfbar, jederzeit nachladbar; `rm -rf` ist eine legitime Reparatur; bläht das Backup nicht auf |
| eigener Upload | `photo_blob` in der DB | **unersetzlich** → liegt damit ohne Änderung am Backup-Skript in der nächtlichen Sicherung |

Der Dateiname kommt **immer** aus dem normalisierten Typcode, nie aus dem Upload — Pfad-Traversal
ist damit keine Prüffrage, sondern unmöglich.

**Ehrlich benannt:** die DB wächst mit jedem Upload. Bei 40 geflogenen Mustern und ~150 KB sind das
einige MB auf 42 MB Bestand — unkritisch, aber Wachstum, das nicht von allein aufhört.

## Frontend

Eine Hilfsfunktion `acLink(code)` erzeugt überall dasselbe Markup, **ein** delegierter
Klick-Listener am `document` fängt es. Das Modal folgt dem vorhandenen Flugplan-Modal.

Die **acht** Stellen in `app/static/index.html`, jede am 2026-07-30 nachgemessen (Zeile und
umschließende Funktion):

| Zeile | Funktion | Sicht |
|---|---|---|
| 2727 | `renderLiveTable` | Live-Tabelle |
| 3130 | `renderBummelParticipants` | Bummel-Teilnehmer |
| 3229 | `renderBummelStandings` | Bummel-Standings |
| 3379 | `_kutterBannerBlock` | Kutter-Banner |
| 3493 | `openFpModal` | Flugplan-Modal (`fp-aircraft`) |
| 3831 | `_flightRowHtml` | Flugzeile (Flugliste eines Piloten) |
| 4130 | `buildPopupHtml` | Karten-Popup („Muster:") |
| 5158 | `_kutterDetailBody` | Kutter-Detail |

**Nicht betroffen, gegen die erste Fassung dieser Spec korrigiert:** `renderStatsTable`
(4550–4614) und `renderEventsResults` (4652–4748) zeigen den Designator **überhaupt nicht** — dort
gibt es nichts anklickbar zu machen. In den Statistiken ist er über die Flugliste erreichbar
(`_flightRowHtml`, via `openPilotFlights`). Ihn dort als **neue Spalte** zu ergänzen wäre eine
Erweiterung des Auftrags und ist **nicht** Teil dieser Spec.

Der Designator wird **blau** (`--green`, historischer Name) — nach der stehenden UI-Regel ist Blau
Klickbarem vorbehalten, und er ist ab jetzt klickbar. Das Modal ist auf dem Smartphone scrollbar;
enthält es eine Tabelle, gelten `.table-scroll` und die in `CLAUDE.md` dokumentierten Fallen
(Flexbox `min-width: 0`, Verschachtelung in `.scroll-list`).

### Zwei Fallen, die in der Umsetzung zählen

- **`index.html:3176` ist kein HTML.** Das ist der Text für die Zwischenablage
  (`${e.aircraft || '?'}`). Bekommt diese Stelle Markup, klebt `<a class=…>` in der geteilten
  Nachricht. **Bleibt unverändert.**
- **`data-ac` ist schon belegt** — Flugzeilen tragen es für das Flugplan-Modal
  (`index.html:3809`). Das neue Attribut heißt **`data-actype`**, sonst öffnen sich zwei Modals
  übereinander.

### Leerer Zustand

**Jeder** Designator ist klickbar, auch `IMPU` — die Friesen-Zahlen dazu sind echt. Ein Kürzel, das
manchmal blau ist und manchmal nicht, wäre schlechter als ein Panel ohne Foto. Fehlen Muster-Daten,
zeigt das Panel Kürzel, Zahlen, Kutter-Daten und einen Satz:

> Zu diesem Kürzel ist kein Muster bekannt.

Kein Platzhalterbild, kein erfundener Text, keine Vermutung.

## Sichtbarkeit der Top-Piloten

`pilot_visibility` (`database.py:6187`) regelt **Push-Benachrichtigungen** („wer darf über mich
benachrichtigt werden?", mit `services`-Liste) — nicht die Statistik-Anzeige. Der Statistik-Tab und
die Bummel-Standings zeigen Namen und Flugzahlen längst offen. Für die Top-Piloten-Liste gilt
derselbe Maßstab, keine zusätzliche Hürde.

Angemeldet und vom Nutzer entschieden: das Bummel-Feature verbirgt Ranglisten bewusst
(`5d420b3` „verdeckte Reihenfolge verrät kein Ranking"). Hier ist es ein offenes Ranking. Der
Einwand wurde benannt, die Entscheidung fiel dafür.

## Tests

Kein Netz in den Tests — die HTTP-Schicht wird gefälscht.

- **Retry-Regression zum `AP32`-Fall:** ein transienter Fehler darf ein Muster **nicht** dauerhaft
  sperren; ein zweiter Lauf muss es erneut versuchen. Gegen den heutigen
  `_payload_research_attempted`-Mechanismus wäre dieser Test **rot**.
- **Treffer-Prüfung:** ein Artikel ohne Wortüberlappung zum Hersteller **oder** ohne
  Luftfahrzeug-Hinweis in `description` wird verworfen; ein Admin-Lemma umgeht die Prüfung.
- **Alias:** ein Schritt löst auf; Selbstbezug und Kette werden beim Speichern abgelehnt; die
  Flugzahlen addieren sich; `alias_anteil` stimmt.
- **Override-Semantik:** ein Import überschreibt nie eine Korrektur; `override` leeren stellt den
  Importwert wieder her.
- **Foto:** BLOB gewinnt über Datei; GFDL-only wird übersprungen; ein Upload, der kein Bild ist,
  wird abgelehnt; EXIF ist nach der Umwandlung weg; der Pfad kommt aus dem Typcode, nicht aus dem
  Upload.
- **Leerer Zustand:** ein unbekanntes Kürzel liefert Zahlen und **nie** einen 500er.
- **Lizenzfilter:** CC0/PD/CC-BY/CC-BY-SA werden übernommen, GFDL-only nicht.

## Teil 8 (unabhängig): Retry und Nachlese der Zuladungs-Recherche

Eigener, unabhängig auslieferbarer Bugfix. Betrifft die **Kutter-Zuladungen**, nicht dieses
Feature, und soll nicht daran hängen.

**Befund vom 2026-07-30, gemessen:** `AP32` hat keinen `aircraft_payloads`-Eintrag, obwohl die
Auto-Recherche seit `b8b9926` (v7.4.0) existiert, der Key gesetzt ist und die fünf Flüge vom
25.–27.07.2026 stammen. Direkt nachgemessen:

```
AP32 -> None   overloaded_error   (request_id req_011CdXwhjTLWqCv5VGe2KbMv)
PC21 -> None   overloaded_error   (request_id req_011CdXwnr4bS7XBvRCx8VbPG)
TL20 -> {'make_model': 'TL Ultralight TL-2000 Sting', 'mtow_kg': 600.0, …}
PIVI -> {'make_model': 'Pipistrel Virus SW', 'mtow_kg': 600.0, …}
```

Die Anthropic-API war überladen. `suggest_aircraft_payload()` fängt das ab und gibt `None` zurück
(Silent Fail, wie entworfen). Drei Bugs greifen dann ineinander:

1. **Kein Retry bei transientem Fehler.** `poller.py:892` setzt
   `self._payload_research_attempted.add(code)` **vor** dem Versuch und nimmt den Code bei
   Misserfolg nie wieder heraus.
2. **Keine Nachlese.** Ein Muster, das in `flight_cache` steht, aber keinen Eintrag hat, wird nie
   von selbst nachgeholt. Ein zweiter Anlauf braucht einen Prozess-Neustart **und** einen Piloten,
   der genau dieses Muster wieder live fliegt. `AP32` flog zuletzt am 27.07., der Container wurde
   am 29.07. für 10.4.6 neu gebaut — das Fenster war zu.
3. **Auslöser hängt am Live-Poll.** Ein Muster, das erst über einen später eintreffenden Flugplan
   bekannt wird, löst gar nichts aus.

**Fix:**

- Transienten Fehler von „nichts gefunden" unterscheiden und den Code bei transientem Fehler
  **nicht** dauerhaft merken (Zustand + Backoff wie in der Retry-Tabelle oben, in der DB).
- Nachlese-Lauf über `SELECT DISTINCT aircraft_icao FROM flight_cache`, das schließt `AP32`,
  `PC21`, `TL20`, `PIVI`.
- Test: transienter Fehler sperrt nicht dauerhaft (dieselbe Regression wie oben, hier für die
  Zuladungen).

## Verworfene Quellen

**aviatordb.com** — geprüft und **nicht** verwendet.

Die Recherche war zunächst positiv: `/api/icao-lookup` ist in `robots.txt` ausdrücklich für alle
Crawler freigegeben, liefert ohne Key **4989 Einträge** (625 KB) mit `icao`, `manufacturer`,
`model`, und ist exakt über den Designator adressiert. Abdeckung der Gruppen-Kürzel: `K100 → DAHER
/ Kodiak 100`, `PZ04 → PZL-OKECIE / PZL-104 Wilga 35`, `TL20 → TL ULTRALIGHT / TL-2000 Sting`,
`PIVI → PIPISTREL / Virus (piston)`, `IMPU → IMPULSE / Impulse`, `AP32 → AEROPRAKT / A-32 Vixxen`,
`PC21 → PILATUS / PC-21` — **9 von 10** echten Kürzeln, und der einzige Fehltreffer ist `P24`,
der bestätigte Tippfehler, der eben kein Designator ist.

Trotzdem draußen, aus drei Gründen:

1. **Als Foto- und Textquelle untauglich.** Bilder liegen unter
   `img.aviatordb.com/aircraft/<ICAO>/AID-<ICAO>.jpg` **ohne jede Lizenz- oder Urheberangabe**;
   Betreiber ist „Passion Highway, Inc.", die Terms laden per JavaScript nach und waren nicht
   auslesbar. Die Texte sind offenkundig generiert: die Seite zu `IMPU` liefert **kein 404**,
   sondern flüssige Prosa, die einräumt, dass zu Maßen, MTOW und Produktion nichts bekannt ist —
   in derselben souveränen Tonlage wie der echte Ju-52-Artikel. Eine Quelle, die nie „weiß ich
   nicht" sagt, ist als Faktenbasis schlechter als eine Lücke.
2. **Der Nutzen als Namensquelle ist klein.** Sie schließt heute genau **zwei** Lücken (`AP32`,
   `PC21`), und beide liefert die vorhandene LLM-Recherche auch — sie ist nur an `Overloaded`
   gescheitert, also an dem Bug aus Teil 8.
3. **Datenbankherstellerrecht.** Ein Bulk-Import der 4989 Zeilen wäre die Entnahme eines
   wesentlichen Teils einer Datenbank (§ 87a ff. UrhG) — dieselbe Frage, die bei den Bildern gegen
   die Quelle sprach, hier mit zwei Maßstäben zu messen wäre nicht konsistent gewesen.

Nachrüstbar bleibt sie: ein weiteres Feld in derselben Namens-Rangfolge, **zeilenweise** statt als
Bulk-Import, falls die LLM-Recherche im Betrieb unzuverlässig ist.

**Weiter verworfen:**

- **Wikidata als Schlüssel** — es gibt **keine** Property „ICAO aircraft type designator"
  (`wbsearchentities` mit `type=property` liefert für „ICAO aircraft type designator" und
  „aircraft type designator" jeweils ein **leeres** Ergebnis). Die Itemsuche nach `C172` traf
  `Q244479` nur zufällig über den Labeltext — dritter Treffer war eine ILO-Konvention.
- **ICAO Doc 8643 API** — Registrierung und Key nötig, 100 Freicalls, ohnehin keine Fotos.
- **Aviation Edge, SkyLink** — Key, Kontingent, und die Abfrage geht über das **Kennzeichen**;
  VATSIM-Flugpläne tragen kein verlässliches Kennzeichen.
- **Planespotters, JetPhotos** — Fotos pro Kennzeichen, ToS problematisch.
- **Kein Server-State (bei jedem Klick live zu Commons)** — zwei bis drei fremde HTTP-Aufrufe im
  Antwortpfad, das Lemma müsste jedes Mal neu geraten werden, GFDL-Filterung wäre nicht
  korrigierbar, und ein falscher Treffer ließe sich nicht richtigstellen. Ohne gespeicherten
  Zustand gibt es **keinen Pflegeweg** — und der ist bei dieser Datenlage das Wichtigste.
