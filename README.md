# FriesenSpy

VATSIM Live-Tracker für die FriesenFlieger Virtual Airline. Zeigt wer von der Gruppe gerade online fliegt — mit Live-Karte, Statistiken und Event-Suche.

**Live:** https://friesenspy.devprops.de

---

## Inhaltsverzeichnis

- [Was ist FriesenSpy?](#was-ist-friesenspy)
- [Die vier Tabs im Überblick](#die-vier-tabs-im-überblick)
  - [Live](#-live)
  - [Karte](#️-karte)
  - [Statistiken](#-statistiken)
  - [Event-Suche](#-event-suche)
- [Benachrichtigungen](#-benachrichtigungen-push-notifications)
- [Karten-Layer](#️-karten-layer)
- [Links teilen & Deep-Linking](#-links-teilen--deep-linking)
- [Woher kommen die Daten?](#woher-kommen-die-daten)
- [Für Entwickler](#für-entwickler)

---

## Was ist FriesenSpy?

FriesenSpy überwacht automatisch alle VATSIM-Verbindungen mit dem Callsign-Prefix **`FRS`** — das sind die Piloten der FriesenFlieger. Alle 15 Sekunden werden die Echtzeit-Daten von VATSIM abgerufen. Wenn ein Friese online geht, wird das sofort angezeigt, der GPS-Track aufgezeichnet und (optional) eine Benachrichtigung verschickt.

Es wird kein VATSIM-Account benötigt. FriesenSpy liest ausschließlich öffentliche Daten.

> **Kurzflüge ≤ 5 Minuten** werden grundsätzlich herausgefiltert — kurze Verbindungsabbrüche und Test-Connects erscheinen weder in der Flugliste noch in den Statistiken oder Charts. Flüge, die FriesenSpy selbst aufgezeichnet hat und die auch in StatSim vorhanden sind, werden nie doppelt gezählt.

### Wie FriesenSpy Flüge zählt

VATSIM-Piloten trennen die Verbindung manchmal kurz, ohne dass ein echter Flugwechsel stattfindet. FriesenSpy erkennt solche Fragmente automatisch und fasst sie zu einem Flug zusammen.

**Zwei Einträge werden zu einem Flug gemergt, wenn:**
- gleicher Callsign
- Zeitlücke ≤ 5 Minuten
- und einer der folgenden Fälle zutrifft:

| Fall | Beschreibung | Beispiel |
|------|-------------|---------|
| **Gleicher Flugplan** | Beide Einträge haben denselben DEP+ARR | Verbindungsabbruch mid-flight, sofort reconnect mit gleichem Plan |
| **Kein Flugplan → Flugplan** | Erster Eintrag ohne DEP/ARR, zweiter mit Flugplan — **und** erste GPS-Position des ersten Eintrags liegt innerhalb 10 km des DEP-Airports | Pilot steht am GAT, gibt Flugplan auf, reconnect; oder Pilot startet, merkt nach 5 Min dass FP fehlt, reconnect |

**Was nicht gemergt wird:**
- Zwei Einträge mit **unterschiedlichen** Flugplänen (verschiedenes DEP oder ARR) → immer zwei separate Flüge
- Kein-FP-Eintrag gefolgt von Flugplan, aber **Startposition > 10 km** vom DEP-Airport entfernt → zwei separate Flüge (Pilot war woanders)

**Beispiel:** Pilot fliegt Bonn (EDKB) → Köln (EDDK) ohne Flugplan (20 Min), landet, reconnect mit Flugplan Köln (EDDK) → Düsseldorf (EDDL) — das sind **zwei Flüge**: der erste startete in Bonn (~11 km von EDDK entfernt, außerhalb der 10-km-Grenze).

---

## Die vier Tabs im Überblick

### ✈ Live

Zeigt alle Friesen, die gerade auf VATSIM fliegen — in Echtzeit, ohne Neuladen der Seite.

**Was du siehst:**
- Callsign, Abflug- und Zielflughafen, Flugzeugtyp
- Wie lange der Pilot bereits online ist
- Aktuelle Position, Höhe, Geschwindigkeit und Kurs

**Was du tun kannst:**
- **Callsign anklicken** → öffnet das Flugplan-Modal mit allen Details (Route, Reiseflughöhe, Bemerkungen usw.)
- **◎ anklicken** → springt direkt auf den Karte-Tab und zentriert die Karte auf diesen Piloten
- **⎘ anklicken** → kopiert einen direkten Link zu diesem Flugplan in die Zwischenablage — zum Teilen

Die Liste aktualisiert sich über eine permanente Server-Verbindung (Server-Sent Events) live im Hintergrund — du siehst neue Positionen, ohne die Seite neu laden zu müssen. Der farbige Punkt oben rechts im Header zeigt an, ob die Verbindung aktiv ist (grün = verbunden, rot = getrennt).

---

### 🗺️ Karte

Interaktive Karte mit allen aktuell fliegenden Friesen.

**Was du siehst:**
- Flugzeug-Symbole, die sich in Flugrichtung drehen
- Beim Klick auf ein Symbol: Popup mit Callsign, Strecke, Flugzeugtyp, Höhe und Geschwindigkeit
- Den bisherigen **GPS-Track** des aktuellen Fluges als Linie — der Track wächst alle 15 Sekunden mit und zeigt den genauen Weg seit dem Start

**Was du tun kannst:**
- Karte frei verschieben und zoomen
- Karten-Layer wechseln (Auswahl oben rechts, siehe [Karten-Layer](#️-karten-layer))
- Von einem anderen Tab aus mit ◎ direkt zu einem bestimmten Piloten springen

---

### 📊 Statistiken

Übersicht über alle aufgezeichneten Flüge der FriesenFlieger.

> **Hinweis:** Es werden ausschließlich Flüge mit einem `FRS`-Callsign gezählt. Flüge desselben Piloten unter einem anderen Callsign erscheinen nicht in den Statistiken.

**Was du siehst:**
- **KPI-Box** oben: Gesamtanzahl aktiver Piloten, Flüge, Flugstunden, Durchschnitt pro Tag, aktivster Pilot und durchschnittliche Flugdauer im gewählten Zeitraum
- **Liniendiagramm**: Flugaktivität über Zeit — umschaltbar zwischen Piloten, Flügen, Stunden und Ø Flugdauer; wählbare Zeiträume: 30 Tage, 90 Tage (beide mit Wochentag-Labels) und 365 Tage (monatlich)
- **Pilotenliste**: alle Piloten mit Anzahl geloggter Flüge und letztem Flugdatum

**Was du tun kannst:**
- **Pilot anklicken** → klappt die Einzelflug-Liste für diesen Piloten auf; Daten kommen sofort aus dem lokalen Cache, ein Update von StatSim läuft automatisch im Hintergrund
- **„Alle Flüge laden (letztes Jahr)"** → erzwingt einen vollständigen 365-Tage-Refresh von StatSim für diesen Piloten (dauert etwas länger)
- **◎** neben einem Einzelflug → öffnet den GPS-Track dieses Fluges auf der Karte
- **⎘** neben einem Einzelflug → kopiert den Link zu genau diesem Flug

Einzelflüge können aus zwei Quellen stammen — erkennbar am Badge:
- **Kein Badge** = FriesenSpy hat den Flug live aufgezeichnet → voller GPS-Track auf der Karte verfügbar
- **◌ StatSim** = Flug kommt aus der StatSim-Datenbank → kein GPS-Track, nur Flugplan-Daten (Start, Ziel, Dauer)

---

### 🔍 Event-Suche

Wer von den Friesen war bei einem bestimmten Event dabei?

**Wie es funktioniert:**
Du gibst einen **ICAO-Code** (z.B. `EDDK` für Köln/Bonn), einen **Radius in km** und einen **Zeitraum** ein. FriesenSpy sucht dann alle Friesen-Flüge, deren Route durch diesen Bereich verlief oder die dort gestartet bzw. gelandet sind.

**Was du siehst:**
- **Karte** (oben) mit allen gefundenen GPS-Tracks gleichzeitig eingezeichnet
- **Pilotenliste** (darunter) mit Callsign, Strecke und Flugdauer
- Piloten ohne GPS-Track (StatSim-Treffer über Flugplan-DEP/ARR) erscheinen mit **◌ StatSim**-Badge — sie werden gefunden, aber ohne Kartendarstellung

**Was du tun kannst:**
- **Track auf der Karte anklicken** oder **Flug-Zeile in der Pilotenliste anklicken** → hebt diesen Track farblich hervor, alle anderen werden transparent
- **„↺ Alle Tracks"** → blendet alle Tracks wieder gleichmäßig ein
- **Callsign in der Pilotenliste anklicken** → öffnet das Flugdetail-Modal mit Strecke, Flugzeugtyp und weiteren Infos
- **⎘** → Link zu dieser Event-Suche teilen — alle Filtereinstellungen stecken in der URL, der Empfänger sieht dasselbe Ergebnis

> **Tipp:** Der ICAO-Code muss nicht exakt der Veranstaltungsort sein — ein Radius von 50–100 km um den nächsten Flughafen reicht in der Regel aus.

---

## 🔔 Benachrichtigungen (Push Notifications)

FriesenSpy kann dich benachrichtigen, wenn ein Friese auf VATSIM online geht — auch wenn der Browser im Hintergrund läuft oder der PC gesperrt ist.

Das Bell-Symbol 🔔 oben rechts im Header öffnet das Benachrichtigungs-Panel.

**Einrichten:**
1. 🔔 klicken → Panel öffnet sich
2. „Beim Online-gehen benachrichtigen" aktivieren
3. Browser fragt nach Erlaubnis → **Zulassen**
4. Optional: Filtern auf bestimmte Piloten (Alle Friesen oder nur ausgewählte)
5. **Speichern**

**Plattformen:**

| Plattform | Wie einrichten | Hinweis |
|-----------|---------------|---------|
| Windows (Edge / Chrome) | Direkt im Browser abonnieren | Funktioniert ohne weitere Schritte |
| Android (Chrome) | Direkt im Browser abonnieren | Chrome empfohlen; Edge auf Android kann Probleme machen |
| iPhone / iPad | Erst als App installieren, dann abonnieren | Safari → Teilen ⬆ → „Zum Home-Bildschirm" → App öffnen → 🔔 |

> **Hinweis bei „Nur bestimmte Piloten":** Neue Mitglieder der FriesenFlieger werden nicht automatisch in die Auswahl aufgenommen. Nach einem Neuzugang einmal das Panel öffnen, den neuen Piloten anhaken und erneut speichern.

**„Push zurücksetzen"-Button** (kleiner Link unterhalb des Panels): Falls Benachrichtigungen nicht ankommen, obwohl sie aktiviert sind — dieser Button deregistriert den Service Worker und erzwingt eine frische Registrierung beim Push-Dienst. Danach einmal neu abonnieren.

---

## 🗺️ Karten-Layer

Alle Karten in FriesenSpy (Live-Tab, Track-Ansicht, Event-Suche) verwenden dieselbe Layer-Auswahl. Deine Wahl wird im Browser gespeichert und beim nächsten Besuch automatisch wiederhergestellt.

**Basis-Layer (einer ist immer aktiv):**

| Layer | Am besten für |
|-------|---------------|
| **OpenFlightMap (VFR)** | Luftfahrtkarte mit Lufträumen, Funkfeuern, Platzrunden — schaltet sich automatisch bei Zoom 7–12 ein |
| **OpenTopoMap** | Gelände und Höhenlinien |
| **ESRI Satellit** | Satellitenbilder — schaltet sich automatisch außerhalb des OFM-Bereichs ein (Zoom ≤ 6 oder ≥ 13) |
| **Light CARTO** | Heller, neutraler Straßenatlas |
| **Dark CARTO** | Dunkle Variante, passend zum Interface |

**OpenAIP-Overlay** (zusätzliche Checkbox): Legt Lufträume, Flugplätze und Navaids aus der OpenAIP-Datenbank über den gewählten Basis-Layer. Besonders nützlich in Kombination mit Satellit oder CARTO. Ist nur verfügbar, wenn auf dem Server ein OpenAIP API-Key konfiguriert ist.

---

## 🔗 Links teilen & Deep-Linking

Jeder Zustand in FriesenSpy ist als Link teilbar — der aktuelle Tab, ein geöffneter Flugplan, eine Event-Suche, ein bestimmter GPS-Track. Der gesamte Zustand steckt im URL-Hash (`#...`), sodass sich beim Neuladen der Seite genau derselbe Zustand öffnet.

Das ⎘-Symbol neben Piloten und Flügen kopiert den fertigen Link direkt in die Zwischenablage.

---

## Woher kommen die Daten?

FriesenSpy kombiniert zwei Datenquellen:

| | FriesenSpy (Live) | StatSim (Historisch) |
|---|---|---|
| **GPS-Track** | ✅ voller Track (alle 15 s aufgezeichnet) | ❌ nicht verfügbar |
| **Event-Suche auf Karte** | ✅ Track sichtbar | ❌ nur in der Liste (◌ Badge) |
| **Flugplan (DEP/ARR)** | ✅ | ✅ |
| **Flugdauer** | ✅ | ✅ |
| **Verfügbarkeit** | Nur wenn FriesenSpy läuft | Letztes Jahr via API |
| **GPS-Aufbewahrung** | 365 Tage | — |
| **Fluganzahl in Statistiken** | ✅ gezählt | ✅ gezählt (Duplikate gefiltert) |

**FriesenSpy (Live):** Jede VATSIM-Position wird alle 15 Sekunden abgerufen und gespeichert. Das ergibt einen präzisen GPS-Track für jeden Flug. Flugdaten bleiben **365 Tage** in der Datenbank.

**StatSim:** Eine öffentliche Datenbank mit historischen VATSIM-Flügen ([statsim.net](https://statsim.net)). FriesenSpy fragt StatSim ergänzend ab, um Flüge zu finden, die vor dem Start von FriesenSpy stattgefunden haben oder bei einem Serverausfall nicht aufgezeichnet wurden. StatSim liefert keine GPS-Tracks, nur Flugplan-Daten (Start, Ziel, Dauer).

> Flüge, die FriesenSpy live aufgezeichnet hat, sind immer vollständiger als StatSim-Einträge. StatSim dient als Rückfall für ältere Zeiträume.

---

## Für Entwickler

### Stack

| Schicht | Technologie |
|---------|-------------|
| Backend | Python 3.11, FastAPI, APScheduler |
| Datenbank | SQLite (WAL-Mode) |
| HTTP-Client | httpx (async) |
| Frontend | Vanilla JS, Leaflet.js (Single-Page-App) |
| Deployment | Docker, GitHub Actions → GHCR → SSH |

### Lokale Entwicklung

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# config.env anlegen (SECRET_KEY ist Pflicht)
cp config.env.example config.env   # dann editieren

# Server starten
uvicorn app.main:app --reload
# → http://localhost:8091
```

### config.env

```bash
SECRET_KEY=<beliebiger-zufalls-string>     # Pflicht
CALLSIGN_PREFIX=FRS                         # Default: FRS
VATSIM_POLL_INTERVAL=15                     # Sekunden, Default: 15
DB_PATH=friesenspy.db                       # Lokal: relativer Pfad OK
TELEGRAM_BOT_TOKEN=                         # Optional
TELEGRAM_CHAT_ID=                           # Optional
STATSIM_API_KEY=                            # Optional: historische Flüge via statsim.net
OPENAIP_API_KEY=                            # Optional: OpenAIP-Overlay (Luftraum, Navaids)
VAPID_PUBLIC_KEY=                           # Optional: Web Push Public Key (base64url)
VAPID_PRIVATE_KEY=                          # Optional: Web Push Private Key (base64url, 43 Zeichen)
VAPID_CONTACT_EMAIL=                        # Optional: mailto:... für Web Push
```

### Tests

```bash
pytest tests/ -v
```

180 Tests, keine externen Abhängigkeiten (alles gemockt).

### Deployment

GitHub Push auf `main` → GitHub Actions baut Docker-Image → pushed nach GHCR → SSH-Deploy auf VPS.

```
main branch
    └─► GitHub Actions (.github/workflows/deploy.yml)
            └─► docker build → ghcr.io/regover13/friesenspy:latest
                    └─► SSH: docker compose pull + up -d
```

### Projektstruktur

```
FriesenSpy/
├── app/
│   ├── main.py        # FastAPI-App, REST + SSE-Endpoints
│   ├── config.py      # pydantic-settings (liest config.env)
│   ├── database.py    # SQLite WAL, alle DB-Funktionen
│   ├── vatsim.py      # VATSIM-API-Client + Callsign-Filter
│   ├── statsim.py     # StatSim API-Client (historische Flüge)
│   ├── geo.py         # Haversine, ICAO→Koordinaten, Event-Filter
│   ├── alerts.py      # Telegram-Alerts (silent fail)
│   ├── poller.py      # APScheduler, Flug-State-Machine, SSE-Queue
│   └── static/
│       ├── index.html # Vanilla-JS-SPA (4 Tabs)
│       └── favicon.ico
├── tests/             # pytest-Tests
├── docs/              # Architektur, API, Deployment
├── nginx/             # nginx-Konfiguration für friesenspy.devprops.de
├── .github/workflows/ # CI/CD: Build → GHCR → SSH-Deploy
├── Dockerfile
└── docker-compose.yml
```

### API

| Endpoint | Methode | Beschreibung |
|----------|---------|--------------|
| `/` | GET | SPA (index.html) |
| `/health` | GET | `{"status": "ok"}` |
| `/api/live` | GET | Aktuelle Live-Positionen (inkl. Flugplan-Felder) |
| `/api/stats?days=30` | GET | Letzter Flug + Fluganzahl pro Pilot |
| `/api/stats/activity?days=30` | GET | Flugaktivität über Zeit (täglich/monatlich) |
| `/api/pilots/{cid}/flights?days=365` | GET | Einzelflüge eines Piloten (FriesenSpy + StatSim) |
| `/api/pilots/{cid}/live-track` | GET | GPS-Track des aktuell laufenden Fluges |
| `/api/flights/{id}/track` | GET | GPS-Track eines FriesenSpy-Fluges |
| `/api/flights/statsim/{id}/track` | GET | GPS-Track eines StatSim-Fluges |
| `/api/events?icao=EDDK&radius=150&start=...&end=...` | GET | Event-Teilnehmer mit Tracks |
| `/api/sse` | GET | Server-Sent Events Stream |

Details: siehe [docs/api.md](docs/api.md)
