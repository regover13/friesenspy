# Muster-Info-Panel — Aircraft-Designator überall anklickbar

**Status:** Design (2026-07-30, **Rev. 2 nach Fable-Review**). Neues Feature. Teil 8
(Retry/Nachlese der Zuladungs-Recherche) ist ein eigenständiger Bugfix und unabhängig auslieferbar.

Rev. 1 hatte **vier blockierende Fehler**, alle von der Prüfung gefunden und hier eingearbeitet:
die Zahlenbasis lag auf der falschen Spalte (B1), die Treffer-Prüfung verwarf die
Hubschrauber-Flotte der Gruppe (B2), Wikimedia sperrt das Netz dieses Servers ohne
User-Agent (B3), und der Retry-Backoff hatte keinen Ausführer (B4). Was aus Rev. 1 geprüft und
**bestätigt** wurde, steht unter „Von der Prüfung bestätigt".

## Ziel

Der Aircraft-Designator (`C172`, `AS65`, `PZ04` …) wird in **allen** Sichten anklickbar. Der Klick
öffnet ein Modal mit Foto, Muster-Name, Kurztext, den Friesen-Zahlen zu diesem Muster und den
gepflegten Kutter-Gewichten.

## Nutzer-Entscheidungen 2026-07-30

- **Inhalt:** Foto + Kurztext **und** Friesen-Bezug (Variante C), gestaffelt umgesetzt — der
  Friesen-Teil läuft ohne externe Quelle und ist damit nie leer.
- **Fotoquelle:** Wikimedia Commons, **serverseitig geholt und gecacht**. Lizenz, Urheber und
  Beleg-URL werden mitgespeichert und unter dem Bild angezeigt. Kein Hotlink — keine Besucher-IP
  an Dritte.
- **Textquelle:** Wikipedia-Extract (Einleitungssätze) mit Quellenangabe. **Kein LLM-Text.**
- **Friesen-Zahlen:** Kernzahlen (Flüge, Stunden, Strecke, Piloten, Zeitraum), **Top-Piloten**
  auf dem Muster, **Kutter-Daten** (MTOW, Leergewicht, Zuladung). Der „letzte Flug damit" wurde
  bewusst **nicht** gewählt.
- **Eigene Fotos:** Admin kann ein eigenes Bild hochladen (Sim-Screenshot o. Ä.), mit optionalem
  Bildnachweis.
- **Alias:** Tippfehler-Kürzel sind auf das richtige Muster umbiegbar (`P24 → PA24`), und die
  Flüge des Alias **zählen zum Zielmuster**.
- **aviatordb.com: nicht in der ersten Version.** Begründung s. „Verworfene Quellen".
- **Alias mit eigener Zuladungszeile (Rev. 2):** Das Panel zeigt die Zielwerte **und warnt**; die
  Kutter-Frachtrechnung bleibt **unangetastet**. Begründung s. „Alias".

## Context — was schon da ist

- `aircraft_payloads` (`database.py:263`), PK `type_code` (normalisiert): **119 Muster**, davon
  118 mit `make_model` — 100 `curated`, 12 `manual`, 7 `llm`. Zweck der Tabelle sind die
  **Kutter-Zuladungen**, nicht Muster-Wissen allgemein.
- `normalize_type_code()` (`database.py:4136`) — Uppercase, vor `/` gekürzt.
- `llm.suggest_aircraft_payload()` (`llm.py:166`) — **Claude Haiku 4.5** (`llm.py:25`
  `_SUGGEST_MODEL = "claude-haiku-4-5"`) mit Web-Search, liefert `make_model` + Gewichte.
  **Rev. 2:** Rev. 1 schrieb hier „Sonnet 5" — abgeschrieben aus der Repo-`CLAUDE.md`, die an
  dieser Stelle ebenfalls falsch ist und mitkorrigiert wird. Sonnet 5 läuft in `llm.py:295`, für
  eine andere Funktion. Genau der in der übergeordneten `CLAUDE.md` dokumentierte Altfehler:
  Tabelle geglaubt statt Quelle geprüft.
- `poller._auto_research_payload()` (`poller.py:1387`) — füllt neu gesehene Typen automatisch vor.
- Admin-Panel „Kutter-Zuladungen" (`admin.html:944 ff.`), Button „💡 KI-Vorschlag"
  (`admin.html:961`).
- Volume `./data:/opt/friesenspy/data` (`docker-compose.yml`) — Unterordner überleben
  Container-Neubauten. `/static` mountet dagegen **aus dem Image**, Fotos brauchen eine eigene Route.
- Pillow 12.3.0 ist im Container vorhanden (`requirements.txt: pillow>=10.0`).

### Die maßgebliche Spalte (B1 — der schwerste Fehler aus Rev. 1)

Rev. 1 hat auf `flight_cache.aircraft_icao` gemessen. **Diese Spalte ist unbrauchbar als
Zahlenbasis:** sie existiert erst seit **2026-06-09** und ist nur in **357 von 2256** Zeilen
gefüllt. Angezeigt (und beim Klick übergeben) wird dagegen `aircraft`, gefüllt in **2232** Zeilen.

**Verbindlich für alle Aggregationen, die Nachlese und den Klickpfad:**

```sql
normalize_type_code(COALESCE(NULLIF(aircraft_icao,''), aircraft))
```

Genau **ein** Wert pro Flug — die beiden Spalten dürfen **nie** per `OR` addiert werden
(Doppelzählung). Gemessen: bei 358 Zeilen sind beide gefüllt, in **357** stimmen sie überein; sie
gehen genau **einmal** auseinander (`aircraft_icao='C208'` vs. `aircraft='C172'`, ein
Flugplanwechsel während der Session). `aircraft_icao` hat Vorrang, weil es das spezifischere Feld
ist; die Abweichung betrifft einen Flug von 2256.

**Gemessener Produktionsstand (2026-07-30) mit dieser Spalte:**

| | Rev. 1 (falsch) | Rev. 2 (gemessen) |
|---|---|---|
| Flüge mit Code | 2248 | **2234** |
| verschiedene Kürzel | 40 | **89** |
| Kürzel ohne `aircraft_payloads`-Eintrag | 4 | **33** |
| davon betroffene Flüge | 10 | **74** |
| Abdeckung nach Flugzahl | „99,6 %" | **96,7 %** |
| häufigstes Muster | C172, 73 Flüge | **C172, 506 Flüge** |

Häufigste Muster: C172 506, PA24 311, C208 242, EC45 137, DA40 118, AEST 72.

**Fehlerszenario, das Rev. 1 ausgeliefert hätte:** Klick auf das blaue `C172` in der Flugliste →
Panel zeigt „73 Flüge", während dieselbe Liste darunter Hunderte auflistet. Die Nachlese über
`DISTINCT aircraft_icao` hätte 40 von 89 klickbaren Kürzeln befüllt.

### Backup-Randbedingung (wichtig für die Speicherwahl)

`/opt/backup/scripts/backup_onedrive.sh:225` sichert von FriesenSpy **nur die Datenbank**
(`sqlite3 .backup`), nicht das Datenverzeichnis. Alles, was als Datei unter `data/` liegt, ist
**nicht** im nächtlichen OneDrive-Backup.

### Netzwerk-Randbedingung (B3 — vom Server aus gemessen)

**Wikimedia sperrt das Contabo-Netz dieses Servers.** Aus dem Produktions-Container gemessen:

```
Default-UA (python-urllib/…)  ->  HTTP 403 Forbidden
    "Contabo networks are forbidden due to abuse unhandled by Contabo"
aussagekräftiger UA gesetzt   ->  HTTP 200
```

Rev. 1 behauptete „gemessen" — gemessen wurde aber über ein Fetch-Werkzeug, **nicht vom VPS**.
Ohne User-Agent funktioniert das Feature auf dieser Maschine überhaupt nicht. Der Block greift
zudem nicht deterministisch an jedem Edge (derselbe UA bekam einmal 403, Minuten später 200) —
403 ist also **transient**, nicht endgültig.

**Verbindlich:**

- Ein **aussagekräftiger User-Agent mit Kontakt** wird bei jedem Wikimedia-Aufruf gesetzt (die
  Wikimedia-Nutzungsregeln verlangen das ohnehin), z. B.
  `FriesenSpy/<version> (https://friesenspy.devprops.de; <kontakt>)`.
- **403 und 429 sind transiente Fehler** (s. Retry-Tabelle), niemals `nichts_gefunden`.
- **Abnahmekriterium:** ein Probelauf **vom Server aus** (nicht aus einer Entwicklungsumgebung)
  muss für mindestens fünf echte Muster Text und Foto liefern.

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
    photo_credit        TEXT,               -- Bildnachweis; gilt für Upload UND Commons (Rev. 2)

    -- Zustand
    fetch_state         TEXT,               -- 'neu' | 'ok' | 'nichts_gefunden' | 'fehler'
    attempts            INTEGER NOT NULL DEFAULT 0,
    checked_at          TEXT,
    updated_at          TEXT,

    -- Rev. 2 (W6): 'blob' ist nur mit vorhandenem Blob ein gültiger Zustand
    CHECK (photo_override IS NULL OR photo_override IN ('-', 'blob')),
    CHECK (photo_override <> 'blob' OR photo_blob IS NOT NULL)
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

**Rev. 2 (W6):** `photo_credit` gilt **auch für Commons-Bilder**, nicht nur für Uploads. Grund:
`Artist` ist auf Commons Freitext-HTML und gelegentlich falsch oder unbrauchbar; ohne diesen Weg
wäre eine fehlerhafte Urheberangabe nur durch Fotoverzicht korrigierbar. Ist `photo_credit`
gesetzt, ersetzt es die importierte Attributionszeile vollständig — der Link auf die
Beschreibungsseite (`photo_source_url`) bleibt immer sichtbar.

### Alias

`alias_of` wird **einen Schritt** aufgelöst. Beim Speichern wird abgelehnt:

- **Selbstbezug** (`X → X`),
- **Ziel ist selbst ein Alias** (`A → B`, wenn `B.alias_of` gesetzt ist),
- **Rev. 2 (W5.1): auf den Code selbst zeigt bereits ein Alias.** Ohne diese Prüfung entsteht eine
  Kette in der anderen Anlegereihenfolge: `P24 → PA24` speichern (erlaubt, PA24 ist kein Alias),
  danach `PA24 → X` speichern (erlaubt, X ist kein Alias) — und die Ein-Schritt-Auflösung von
  `P24` landet auf einer Alias-Zeile ohne eigene Daten, das Panel bleibt leer. Der Test aus Rev. 1
  („Kette wird abgelehnt") wäre dabei **grün** geblieben.

Ein Alias-Kürzel hat keine eigenen Muster-Daten; es zeigt die des Ziels.

**Friesen-Zahlen** aggregieren über Zielmuster **und** alle darauf zeigenden Aliasse. Die Herkunft
wird ausgewiesen, damit die Zahl nachvollziehbar bleibt:

> 332 Flüge (21 davon als `P24` erfasst)

**Rev. 2 (W5.2):** `alias_anteil` ist deshalb **eine Liste** `[{code, n}, …]`, keine einzelne Zahl
— es können mehrere Aliasse auf dasselbe Ziel zeigen. Real vorhanden sind heute zwei solche
Kandidatenpaare: `SA65`/`AS65` und `JU5`/`JU52`.

**Rev. 2 (W5.3) — Alias mit eigener Zuladungszeile.** `P24` (381 kg, `manual`) und `SA65`
(2389/929 kg, `manual`) haben eigene `aircraft_payloads`-Zeilen. Das Panel zeigt die
**Zielwerte**, die Kutter-Frachtrechnung nutzt weiter die **eigene** Zeile des Kürzels — zwei
Zahlen für dasselbe Kürzel.

Gemessen, wie oft das je zum Tragen kam: `transport_cargo_losses` enthält **keine** Zeile für
`P24`, `SA65`, `PA24` oder `AS65`. Über `transport_quips` (nur gewertete Kutter-Flüge erhalten
einen Spruch) findet sich genau **ein** Flug: cid 1470798, FRS102, `P24`, 2026-07-01, EDWG → EDXH,
Event 1. `SA65` war nie in einem Kutter-Event. Und der Unterschied in diesem einen Fall: **381 kg
gegen 381,5 kg — ein halbes Kilo.**

**Entscheidung:** Das Panel zeigt die Zielwerte und **darunter einen Hinweis**, dass für dieses
Kürzel eine eigene Zuladungszeile existiert und die Frachtrechnung diese verwendet. An der
Kutter-Logik wird **nichts** geändert. Eine funktionierende Frachtrechnung wegen 0,5 kg
anzufassen wäre unverhältnismäßig; der Widerspruch wird sichtbar statt versteckt.

## Auflösung eines Musters

### Name

Rangfolge, stark nach schwach:

1. `name_override` — Admin-Eintrag, schlägt alles
2. `aircraft_payloads.make_model` — eure 100 kuratierten + 12 manuellen Namen
3. `llm.suggest_aircraft_payload()` (Haiku 4.5) — bestehende Recherche, mit Retry (Teil 8)

**Rev. 2 (B2/W8) — der Name wird vor Benutzung gehärtet.** Die DB enthält nachweislich
unbrauchbare `make_model`-Werte aus alten LLM-Läufen: `MR20` trägt einen **359 Zeichen langen
Prosa-Absatz**, `PZ` (ein Tippcode) trägt die Halluzination „Pilatus PC-6 Turbo Porter". Ein Name
gilt nur als Suchanfrage, wenn er **einzeilig und ≤ 80 Zeichen** ist; sonst gilt er als nicht
vorhanden und die Rangfolge geht einen Schritt weiter. Ohne diese Härtung sprengt `MR20` die
Such-API mit `cirrussearch-query-too-long` (Limit 300 Zeichen) und landet in ewigem Retry.

### Wikipedia und Foto

`COALESCE(wiki_title_override, wiki_title)` — ist keins gesetzt:

1. `de.wikipedia` `action=query&list=search&srsearch=<Name>&srlimit=3` → **die ersten drei Treffer**
2. Für jeden Treffer in Reihenfolge: `/api/rest_v1/page/summary/<Titel>` → `extract`,
   `description`, `originalimage`/`thumbnail`, `wikibase_item`; der **erste, der die Prüfung
   besteht**, gewinnt
3. Kein tauglicher de-Treffer → dasselbe auf `en.wikipedia`
4. **Rev. 2 (W1):** `page/media-list` des gewählten Artikels → **alle** Bildkandidaten, nicht nur
   `originalimage`
5. Commons `action=query&prop=imageinfo&iiprop=extmetadata|url` je Kandidat →
   `LicenseShortName`, `Artist`, `Credit`, `LicenseUrl`, `descriptionurl`; das erste Bild mit
   zulässiger Lizenz gewinnt

**Gemessen:** die Suche verträgt eure spezifischen Namen. `srsearch="Cessna 172S Skyhawk"` →
erster Treffer `Cessna 172`. Der **direkte** Lemma-Aufruf mit demselben String ergibt dagegen
**HTTP 404** — deshalb immer über die Suche, nie den Namen als Lemma raten.

**Implementierungsfalle (W1, von der Prüfung selbst erlebt):** `page/media-list` liefert auf
de.wikipedia `Datei:`-Titel; die Commons-API braucht `File:`. Ohne Umschreibung kommt still kein
`imageinfo` zurück.

### Der Treffer wird geprüft, nicht geglaubt

Die Wikipedia-Suche liefert praktisch immer *irgendetwas*. Ein Treffer gilt als tauglich, wenn
**beide** Bedingungen halten:

1. Der Titel teilt mindestens ein bedeutungstragendes Wort (≥ 3 Zeichen, kein Füllwort) mit dem
   **vollständigen Namen** — nicht nur mit dem Herstellerteil.
2. `description` **oder**, falls die leer ist, der Anfang von `extract` weist auf ein Luftfahrzeug
   hin (`Flugzeug`, `Hubschrauber`, `Ultraleicht`, `Segelflugzeug`, `aircraft`, `airliner`,
   `helicopter`, `glider` …).

Fällt bei allen drei Treffern eine Bedingung durch → `fetch_state = 'nichts_gefunden'`, **kein
Text, kein Bild**. Heuristik mit sicherer Fehlerrichtung: im Zweifel nichts statt etwas Falsches.

Ein **Admin-gesetztes Lemma umgeht die Prüfung** — bewusste menschliche Entscheidung.

**Rev. 2 (B2) — warum Rev. 1 hier blockierend falsch war.** Die alte Fassung prüfte die
Überlappung nur gegen den **Herstellerteil** und nur gegen den **ersten** Treffer. Gegen die
echten `make_model`-Werte gemessen, verwarf sie die halbe Hubschrauber-Flotte der Gruppe:

| Muster | Flüge | `make_model` | korrekter de-Artikel | Rev. 1 |
|---|---|---|---|---|
| EC45 | 137 | `Airbus H145 (D3)` | *MBB/Kawasaki BK 117* (2. Treffer) | verworfen |
| AEST | 72 | `Aerostar 600` | *Piper PA-60* | verworfen |
| AS65 | 26 | `Aérospatiale/Airbus Helicopters AS365N3 Dauphin 2` | *Eurocopter AS365 Dauphin* (en) | verworfen |
| EC35, EC30, EC25, AS50 | — | „Airbus H1xx …" | *Eurocopter EC 1xx* | verworfen |

Dazu war „Herstellerteil" nie definiert. Jede Erste-Wort-Heuristik scheitert an
`de Havilland Canada …` und `TL Ultralight …` (beide ersten Wörter < 3 Zeichen) sowie an
`MBB/Airbus …`. Und `description` ist bei korrekten Artikeln wie *Piper PA-60* oder
*Scheibe SF 25* **leer** — Bedingung 2 hätte sie allein deswegen verworfen.

**Was die Prüfung ausdrücklich nicht kann:** Sie validiert den Hersteller, nicht das Modell. Fehlt
der Modellartikel, kann ein anderes Muster desselben Herstellers durchkommen. Und ein gültiger
Designator, der nicht das geflogene Flugzeug bezeichnet, ist ein **Eingabefehler** — dafür gibt es
den Alias, nicht die Prüfung.

### Lizenzfilter

**Rev. 2 (W4): Whitelist exakter, normalisierter Lizenzkürzel — kein Substring-Vergleich.**
`LicenseShortName` ist Freitext mit Leerzeichen (gemessen: `CC BY-SA 4.0`, `Public domain`,
`GFDL 1.2`). Ein Substring-Test auf `"CC BY"` würde `CC BY-NC-ND 2.0` durchlassen und ein
NC/ND-Bild veröffentlichen — beide Testfälle aus Rev. 1 wären dabei grün geblieben.

Zulässig: CC0, Public domain / PD-*, CC BY (2.0/2.5/3.0/4.0), CC BY-SA (2.0/2.5/3.0/4.0).
Ausgeschlossen: alles mit `NC` oder `ND`, und GFDL **als einzige** Lizenz.

**Dual lizenzierte Bilder** (auf Commons häufig GFDL **und** CC-BY-SA) tragen teils nur „GFDL" im
`LicenseShortName`; die „only"-Unterscheidung braucht die weiteren `extmetadata`-Felder
(`UsageTerms`, `LicenseUrl`, Lizenz-Kategorien), nicht bloß das Kürzel.

Angezeigt wird unter jedem Commons-Bild: Urheber, Lizenzkürzel, Link auf die Beschreibungsseite —
oder `photo_credit`, falls gesetzt.

**Rev. 2 (W1) — die C172 bekommt ein Foto.** Rev. 1 schloss aus dem GFDL-Filter, das mit 506
Flügen häufigste Muster der Gruppe bleibe dauerhaft ohne Bild. Das war ein Pipeline-Fehler, kein
Lizenzproblem: das Leitbild ist GFDL 1.2, aber **derselbe Artikel** enthält mindestens vier
verwendbare Bilder (`Cessna 172 D-EVLB.jpg` CC BY-SA 3.0, `Cessna 172T.jpg` CC BY-SA 4.0, zwei
Public Domain). Der Filter bleibt, die Ein-Kandidaten-Pipeline fällt (Schritt 4 oben).

## Datenfluss — wer füllt wann

**Vier Auslöser, keiner im Klickpfad.**

1. **Poller**, wie bei den Zuladungen: ein neu gesehener Typcode wird gefüllt.
2. **Nachlese beim Start** über die maßgebliche Spalte (s. oben) — schließt die Klasse von Lücken,
   die `AP32` gerissen hat. **Rev. 2:** Das sind **89** Kürzel, nicht 40. Bei bis zu drei
   Fremdaufrufen je Kürzel plus Bildkandidaten sind das ~250 Requests beim ersten Start — also
   **serialisiert mit Drossel**, nicht parallel, und wegen B3 mit gesetztem User-Agent. „40
   Kürzel, also billig" aus Rev. 1 stimmt nicht.
3. **Rev. 2 (B4): periodischer Retry-Job** (APScheduler, alle 5 min):
   `SELECT … WHERE fetch_state='fehler' AND checked_at älter als der fällige Backoff`.
4. **Faul beim Klick**, falls trotzdem etwas fehlt — aber **nie synchron**: die API antwortet
   sofort mit den Friesen-Zahlen und `state`, der Abruf wird im Hintergrund angestoßen.

**Rev. 2 (W3) — der Klick-Auslöser ist eingegrenzt.** Der Hintergrund-Abruf und das Anlegen einer
`aircraft_types`-Zeile passieren **nur** für Codes, die in der maßgeblichen Spalte von
`flight_cache` vorkommen oder gerade live sind. Ohne diese Grenze wäre
`for i in $(seq 1 100000); curl /api/aircraft/JUNK$i` ein Verstärker: beliebig viele Zeilen plus
bis zu drei Wikimedia-Aufrufe je Code, von einer IP, die dort wegen „abuse" schon vorbelastet ist
(B3). Unbekannte Codes werden beantwortet, aber **nicht gespeichert und nicht recherchiert**.

### Retry-Semantik

Der Zustand steht **in der DB**, nicht in einem Set im Prozessgedächtnis:

| `fetch_state` | Bedeutung | Nächster Versuch |
|---|---|---|
| `neu` | noch nie versucht | sofort |
| `ok` | aufgelöst | keiner — **außer** die Foto-Datei fehlt (W2) oder Admin drückt *Neu holen* |
| `nichts_gefunden` | inhaltlich erledigt | nach 30 Tagen |
| `fehler` | Netz, Timeout, 5xx, **403, 429** | Backoff 5 min, 30 min, 4 h, dann täglich — angestoßen von Auslöser 3 |

`fehler` ist **kein Endzustand**. `Overloaded` ist kein „keine Daten" — genau diese Verwechslung
hat `AP32` zwei Monate offen gehalten (s. Teil 8). **403 gehört ausdrücklich hierher**, siehe B3:
sonst begräbt der Contabo-Block jedes Muster für 30 Tage als „nichts gefunden".

**Rev. 2 (B4):** Rev. 1 definierte diesen Backoff, aber **keinen Ausführer** — Poller reagiert nur
auf *neue* Codes, die Nachlese läuft nur *beim Start*. Ein `fehler` wäre also bis zum nächsten
Container-Neubau liegen geblieben: strukturell dieselbe Lücke, die Teil 8 schließen soll, nur mit
DB-Zustand statt Set.

**Rev. 2 (W2): `ok` heißt nicht „nie wieder".** Rev. 1 nannte `rm -rf data/aircraft-photos/` eine
„legitime Reparatur" und begründete das Override-Modell damit, dass Import-Felder „weiter
aktualisiert" werden — bei `ok` = „keiner" wäre beides leer gewesen. Nach so einer Reparatur (oder
nach einem Restore aus dem OneDrive-Backup, das die Fotodateien **nicht** enthält) sagt die DB
`photo_file` gesetzt, die Datei fehlt, und nichts lädt je nach. Deshalb:

- Die Foto-Route setzt bei fehlender Datei den Zustand auf `neu` zurück.
- Die Nachlese beim Start prüft zusätzlich auf `photo_file gesetzt, Datei fehlt`.

## API

- **`GET /api/aircraft/{code}`** → `{ code, alias_of, resolved_code, name, extract, wiki_url,
  photo_url, photo_credit, photo_licence, photo_artist, photo_source_url, state,
  friesen: { fluege, stunden, nm, piloten, von, bis, alias_anteil: [{code, n}] },
  top: [ { cid, callsign, name, n } ],
  kutter: { mtow_kg, empty_kg, payload_kg, eigene_zeile_hinweis } }`
  Liefert **immer 200**, auch für ein unbekanntes Kürzel — die Friesen-Zahlen sind dann trotzdem
  echt. Unbekannte Codes werden nicht gespeichert (W3).
- **`GET /api/aircraft/{code}/photo`** → Bild. Liegt ein `photo_blob` vor, **gewinnt er** über
  `photo_file`. Explizites `Content-Type`, nie `text/html`. `Cache-Control` gesetzt; `photo_url`
  trägt **`?v=<updated_at>`**, sonst zeigen Browser nach einem Fotowechsel weiter das alte Bild.
  Fehlt die Datei → Zustand auf `neu` (W2), Antwort 404.
- **`GET /api/admin/aircraft-types`** → Liste mit Import- und Korrekturwerten, `fetch_state`,
  `checked_at`, `attempts`.
- **`POST /api/admin/aircraft-types`** → Overrides, `alias_of`, `photo_credit` setzen/leeren.
- **`POST /api/admin/aircraft-types/{code}/refetch`** → neu holen (nutzt `wiki_title_override`,
  falls gesetzt). Schreibt nur Import-Spalten.
- **`POST /api/admin/aircraft-types/{code}/photo`** → Upload.

### Upload

Das Bild wird mit **Pillow** dekodiert und neu geschrieben, max. 1280 px Breite, JPEG:

- **Prüfung** — was Pillow nicht als Bild öffnet, ist keins. Dateiendung und der vom Browser
  gemeldete Content-Type werden nicht geglaubt.
- **EXIF fällt weg.** Ein Handyfoto vom Cockpit trägt sonst GPS-Koordinaten in die Datenbank einer
  öffentlichen Seite.
- **Größe** — typisch 100–200 KB statt mehrerer MB. Grenze **8 MB** vor der Umwandlung.

| Art | Speicher | Warum |
|---|---|---|
| Commons-Foto | Datei unter `data/aircraft-photos/` | wegwerfbar, jederzeit nachladbar; bläht das Backup nicht auf |
| eigener Upload | `photo_blob` in der DB | **unersetzlich** → liegt damit ohne Änderung am Backup-Skript in der nächtlichen Sicherung |

Der Dateiname kommt **immer** aus dem normalisierten Typcode, nie aus dem Upload — Pfad-Traversal
ist damit keine Prüffrage, sondern unmöglich.

**Ehrlich benannt:** die DB wächst mit jedem Upload. Bei 89 Kürzeln und ~150 KB sind das einige MB
auf 42 MB Bestand — unkritisch, aber Wachstum, das nicht von allein aufhört.

## Frontend

Eine Hilfsfunktion `acLink(code)` erzeugt überall dasselbe Markup, **ein** delegierter
Klick-Listener am `document` fängt es. Das Modal folgt dem vorhandenen Flugplan-Modal.

Die **acht** Stellen in `app/static/index.html`, jede am 2026-07-30 nachgemessen und von der
Prüfung unabhängig bestätigt:

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

**Nicht betroffen:** `renderStatsTable` (4550–4614) und `renderEventsResults` (4652–4748) zeigen
den Designator **überhaupt nicht**. In den Statistiken ist er über die Flugliste erreichbar
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
manchmal blau ist und manchmal nicht, wäre schlechter als ein Panel ohne Foto. Fehlen Muster-Daten:

> Zu diesem Kürzel ist kein Muster bekannt.

Kein Platzhalterbild, kein erfundener Text, keine Vermutung.

## Sichtbarkeit der Top-Piloten

`pilot_visibility` (`database.py:6187`) regelt **Push-Benachrichtigungen** („wer darf über mich
benachrichtigt werden?", mit `services`-Liste) — nicht die Statistik-Anzeige; von der Prüfung am
Code bestätigt. Der Statistik-Tab und die Bummel-Standings zeigen Namen und Flugzahlen längst
offen. Für die Top-Piloten-Liste gilt derselbe Maßstab, keine zusätzliche Hürde.

Angemeldet und vom Nutzer entschieden: das Bummel-Feature verbirgt Ranglisten bewusst
(`5d420b3` „verdeckte Reihenfolge verrät kein Ranking"). Hier ist es ein offenes Ranking. Der
Einwand wurde benannt, die Entscheidung fiel dafür.

## Tests

Kein Netz in den Tests — die HTTP-Schicht wird gefälscht.

**Rev. 2: Die Leitfrage bei jedem Test ist „kann er grün sein, obwohl der Bug da ist?".** Vier
Tests aus Rev. 1 wären das gewesen; sie sind unten ersetzt.

- **Maßgebliche Spalte (B1):** ein Flug mit `aircraft_icao=NULL, aircraft='C172'` zählt zu `C172`;
  ein Flug mit beiden gefüllt zählt **einmal**, nicht zweimal; die Nachlese erfasst Codes, die nur
  in `aircraft` stehen. Fixture aus echten Daten: 2234 Flüge / 89 Codes.
- **Treffer-Prüfung (B2), mit den real gemessenen Fällen als Fixtures** — nicht mit erfundenen:
  `Airbus H145 (D3)` findet *MBB/Kawasaki BK 117* über den 2. Treffer; `Aerostar 600` findet
  *Piper PA-60* trotz fehlender Herstellerüberlappung; `AS365N3 Dauphin 2` findet den en-Artikel;
  `description=None` verwirft nicht; `MR20` (359-Zeichen-Prosa) wird vor der Suche als
  unbrauchbarer Name verworfen und löst **keinen** API-Fehler aus.
- **User-Agent (B3):** jeder ausgehende Wikimedia-Request trägt den UA; eine 403-Antwort führt zu
  `fehler`, **nicht** zu `nichts_gefunden`.
- **Retry-Ausführer (B4), mit kontrollierter Uhr:** Fehler bei t₀ → Job-Lauf bei t₀+2 min versucht
  **nicht**, Job-Lauf bei t₀+6 min versucht **erneut**. (Rev. 1 prüfte „zwei Läufe versuchen es
  zweimal" — das wäre grün gewesen, ohne dass je ein zweiter Lauf stattfindet.)
- **Fotokandidaten (W1):** ein Artikel, dessen Leitbild GFDL-only ist, aber dessen media-list ein
  CC-BY-SA-Bild enthält, ergibt ein Foto; `Datei:` wird zu `File:` umgeschrieben.
- **`ok` ist nicht endgültig (W2):** fehlende Datei bei `fetch_state='ok'` setzt auf `neu` zurück.
- **Klick-Eingrenzung (W3):** ein Code, der in `flight_cache` nicht vorkommt, legt **keine** Zeile
  an und löst **keinen** Fremdaufruf aus.
- **Lizenzfilter (W4):** Whitelist statt Substring — `CC BY-NC-ND 2.0` und `CC BY-ND` werden
  **abgelehnt** (bei Substring-Vergleich durchgekommen), `GFDL 1.2` allein abgelehnt, „GFDL +
  CC-BY-SA dual" **angenommen**.
- **Alias (W5):** ein Schritt löst auf; Selbstbezug, Ziel-ist-Alias **und
  auf-mich-zeigt-ein-Alias** werden abgelehnt; Flugzahlen addieren sich; `alias_anteil` ist eine
  Liste und stimmt bei zwei Aliassen auf dasselbe Ziel.
- **Override (W6):** Import überschreibt nie eine Korrektur; leeren stellt den Importwert wieder
  her; `photo_override='blob'` ohne Blob wird abgelehnt (CHECK); `photo_credit` ersetzt auch die
  Commons-Attribution.
- **Foto allgemein:** BLOB gewinnt über Datei; ein Upload, der kein Bild ist, wird abgelehnt; EXIF
  ist nach der Umwandlung weg; der Pfad kommt aus dem Typcode, nicht aus dem Upload.
- **Leerer Zustand:** ein unbekanntes Kürzel liefert Zahlen und **nie** einen 500er.

**Abnahme am laufenden System (B3):** Probelauf **vom Server aus** für mindestens fünf echte
Muster, darunter `C172` (Foto trotz GFDL-Leitbild) und `EC45` (Treffer über den 2. Suchtreffer).

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

**Rev. 2 (B1) — der Umfang ist größer als gedacht.** Rev. 1 nannte vier Lücken (`AP32`, `PC21`,
`TL20`, `PIVI`), gemessen auf `aircraft_icao`. Auf der maßgeblichen Spalte sind es **33 Kürzel mit
74 Flügen**, u. a. `P28S` (11), `NAV` (5), `AP32` (5), `PA60` (3), `M20T` (3), `FK9` (3).

**Was die Nachlese kostet** — Rev. 1 nannte sie „billig", ohne eine Zahl. Laut `docs/architecture.md:202`
(dort gemessen): **~4 ct und ~30 s je Recherche**. Für 33 Kürzel also **~1,30 € und ~17 min**,
serialisiert. Unkritisch, aber nicht kostenlos, und **nur serialisiert** — dieselbe Doku hält fest,
dass ein einzelner `PZ04`-Request mit dem neueren `web_search_20260209`-Tool schon einmal über
9 Minuten lief und den 120-s-Client-Timeout riss, dessen stille SDK-Retries jeden abgebrochenen
Versuch voll bezahlten (14 $ in zwei Tagen). Die Nachlese darf deshalb **nicht** parallel feuern
und braucht einen harten Deckel je Lauf.

**Rev. 2 (W8) — nicht jede Lücke will gefüllt werden.** Unter den 33 sind Müllcodes mit Flügen:
`NAV` (5), `AERO` (2), `F22` (1), `182` (1). Eine Nachlese über alle Kürzel recherchiert die brav
mit, und Haiku liefert dann Namen wie den vorhandenen `PZ → "Pilatus PC-6 Turbo Porter"` (ein
Tippcode!) oder den Prosa-Absatz unter `MR20`. Der Name-Härtungsfilter oben fängt die Prosa; die
Halluzinationen fängt er nicht. Deshalb: LLM-Ergebnisse der Nachlese im Admin **als solche
sichtbar** (`source='llm'`, `checked_at`), damit sie geprüft werden können, statt still zu gelten.

Nebenbei korrigiert: Rev. 1 erzählte, die Treffer-Prüfung würde für `PZ` den PZL.43-Bomber
bestätigen. Das trifft nicht zu — `PZ` hat längst einen (halluzinierten) PC-6-Namen in Rang 2, der
Bomber käme nie zum Zug.

**Fix:**

- Transienten Fehler von „nichts gefunden" unterscheiden und den Code bei transientem Fehler
  **nicht** dauerhaft merken (Zustand + Backoff in der DB, mit dem periodischen Job aus
  Auslöser 3).
- Nachlese-Lauf über die maßgebliche Spalte (nicht `DISTINCT aircraft_icao`).
- Test mit kontrollierter Uhr wie oben, nicht „zwei Läufe versuchen es zweimal".

## Von der Prüfung bestätigt

Nachgemessen und **korrekt**: alle Datei-/Zeilenangaben (`database.py:263`, `:4136`, `:4152`,
`:6187`, `llm.py:166`, `poller.py:892`, `:1387`, `backup_onedrive.sh:225`), alle acht
`index.html`-Stellen samt umschließender Funktion, `index.html:3176` als Clipboard-Text und
`:3809` als belegtes `data-ac`, die Abwesenheit des Designators in `renderStatsTable` und
`renderEventsResults`, die Commits `b8b9926` und `5d420b3`, Pillow 12.3.0, das Compose-Volume
(per `docker inspect`), die DB-Zahlen 119/118/100/12/7, GFDL 1.2 als Lizenz des C172-Leitbilds,
`srsearch` → „Cessna 172" und direktes Lemma → 404, die aviatordb-`robots.txt`-Freigabe, das
Backup-Argument (nur DB gesichert), die Blau-Regel, die beiden Scroll-Fallen und die
`pilot_visibility`-Einordnung. Auch die Zählung „genau acht Stellen" hielt einer unabhängigen
Suche stand.

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
- **Kein Server-State (bei jedem Klick live zu Commons)** — mehrere fremde HTTP-Aufrufe im
  Antwortpfad, das Lemma müsste jedes Mal neu geraten werden, GFDL-Filterung wäre nicht
  korrigierbar, und ein falscher Treffer ließe sich nicht richtigstellen. Ohne gespeicherten
  Zustand gibt es **keinen Pflegeweg** — und der ist bei dieser Datenlage das Wichtigste.
