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
- [TS-Login-Benachrichtigung](#ts-login-benachrichtigung-phase-1)
- [Karten-Layer](#️-karten-layer)
- [Links teilen & Deep-Linking](#-links-teilen--deep-linking)
- [Woher kommen die Daten?](#woher-kommen-die-daten)
- [Für Entwickler](#für-entwickler)

---

## Was ist FriesenSpy?

FriesenSpy überwacht automatisch alle VATSIM-Verbindungen mit dem Callsign-Prefix **`FRS`** — das sind die Piloten der FriesenFlieger. Alle 15 Sekunden werden die Echtzeit-Daten von VATSIM abgerufen. Wenn ein Friese online geht, wird das sofort angezeigt, der GPS-Track aufgezeichnet und (optional) eine Benachrichtigung verschickt.

Es wird kein VATSIM-Account benötigt. FriesenSpy liest ausschließlich öffentliche Daten.

> **Test-Connects** (keine Bewegung, kein Flugplan) werden herausgefiltert — ein Flug erscheint nur wenn er mindestens ~1 km zurückgelegt hat oder länger als 5 Minuten dauerte. Echte Kurzstrecken erscheinen damit vollständig. Flüge, die FriesenSpy selbst aufgezeichnet hat und die auch in StatSim vorhanden sind, werden nie doppelt gezählt.

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

**Flugplan-Änderungserkennung während des Fluges:** Ändert ein Pilot seinen Flugplan während einer aktiven Verbindung, reagiert FriesenSpy sofort beim nächsten 15-Sekunden-Poll:
- **Kein Plan → Plan eingereicht**: DEP/ARR wird dem laufenden Flug-Eintrag nachgetragen.
- **Plan A → Plan B** (z.B. nach Zwischenstopp): der laufende Flug wird sauber abgeschlossen und ein neues Segment mit dem neuen Flugplan geöffnet.

**Beispiel:** Pilot fliegt Bonn (EDKB) → Köln (EDDK) ohne Flugplan (20 Min), landet, reconnect mit Flugplan Köln (EDDK) → Düsseldorf (EDDL) — das sind **zwei Flüge**: der erste startete in Bonn (~11 km von EDDK entfernt, außerhalb der 10-km-Grenze).

**Woher kommen die Airport-Koordinaten?** Der Geo-Check nutzt das Python-Package [`airportsdata`](https://github.com/mborsetti/airportsdata), das eine vollständige ICAO-Datenbank eingebettet enthält — inklusive aller deutschen Sonderlandeplätze und Kleinflugplätze (z.B. EDKB, EDKV, EDRV). Die Koordinaten stammen aus der [OurAirports](https://ourairports.com)-Datenbank. Es findet kein API-Call statt — die Abfrage ist offline und instant.

---

## Die vier Tabs im Überblick

### ✈ Live

Zeigt alle Friesen, die gerade auf VATSIM fliegen — in Echtzeit, ohne Neuladen der Seite. Darunter erscheinen **eingereichte Flugpläne (Prefiles)**: Piloten, die bereits einen Plan aufgegeben haben, aber noch nicht verbunden sind. Die Prefile-Liste aktualisiert sich etwa jede Minute automatisch (das TeamSpeak-Panel alle 30 Sekunden); die Live-Positionen darüber laufen in Echtzeit per Server-Sent-Events.

**Was du siehst:**
- Callsign, Abflug- und Zielflughafen, Flugzeugtyp
- Wie lange der Pilot bereits online ist
- Aktuelle Position, Höhe, Geschwindigkeit und Kurs
- Eingereichte Flugpläne (FRS*-Callsign, noch nicht online) mit geplantem Datum und Uhrzeit (aus DOF-Feld)

**Was du tun kannst:**
- **Flugplan (DEP→ARR) anklicken** → öffnet das Flugplan-Modal mit allen Details (Route, Reiseflughöhe, Bemerkungen, TAS, Flight Rules usw.)
- **◎ anklicken** → springt direkt auf den Karte-Tab und zentriert die Karte auf diesen Piloten
- **⎘ anklicken** → kopiert einen direkten Link zu diesem Flugplan in die Zwischenablage — zum Teilen

Die Liste aktualisiert sich über eine permanente Server-Verbindung (Server-Sent Events) live im Hintergrund — du siehst neue Positionen, ohne die Seite neu laden zu müssen. Der farbige Punkt oben rechts im Header zeigt an, ob die Verbindung aktiv ist (grün = verbunden, rot = getrennt).

**🎧 Im TeamSpeak:** Ist die TeamSpeak-Überwachung aktiv (`TS_NOTIFY_ENABLED=true`), erscheint im Live-Tab zusätzlich ein Panel mit allen Friesen, die gerade im FriesenFlieger-TeamSpeak sind, samt Anzahl. Angezeigt wird nur das **FRS-Callsign** (z. B. `FRS49`) — Klarnamen und sonstige Nickname-Zusätze werden weggelassen. Nicht-Friesen (ohne FRS-Tag) werden nicht angezeigt. Bei kurzzeitig nicht erreichbarem TeamSpeak bleibt der letzte Stand stehen.

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

> **Datenschutz:** In der Pilotenliste wird der vollständige VATSIM-Name angezeigt. Alle dort sichtbaren Namen sind öffentlich im VATSIM-Datenfeed (`data.vatsim.net`) — FriesenSpy zeigt keine zusätzlichen privaten Daten.

**Was du siehst:**
- **KPI-Box** oben: Gesamtanzahl aktiver Piloten, Flüge, Flugstunden, Durchschnitt pro Tag, aktivster Pilot und durchschnittliche Flugdauer im gewählten Zeitraum
- **Liniendiagramm**: Flugaktivität über Zeit — umschaltbar zwischen Piloten, Flügen, Stunden und Ø Flugdauer; wählbare Zeiträume: 30 Tage, 90 Tage (beide mit Wochentag-Labels) und 365 Tage (monatlich)
- **Pilotenliste**: alle Piloten mit Anzahl geloggter Flüge und letztem Flugdatum — sortierbar nach Flügen, Flugzeit oder Datum (Klick auf Spaltenheader)

**Was du tun kannst:**
- **Pilot anklicken** → klappt die Einzelflug-Liste für diesen Piloten auf; Daten kommen sofort aus dem lokalen Cache, ein Update von StatSim läuft automatisch im Hintergrund
- **„Alle Flüge laden (letztes Jahr)"** → erzwingt einen vollständigen 365-Tage-Refresh von StatSim für diesen Piloten (dauert etwas länger)
- **◎** neben einem Einzelflug → öffnet den GPS-Track dieses Fluges auf der Karte
- **⎘** neben einem Einzelflug → kopiert den Link zu genau diesem Flug

> **„Ich sehe nur 30 Tage Statistik"** — Das ist der Default. Oben links im Statistiken-Tab gibt es einen Umschalter für **30 / 90 / 365 Tage**. Für Piloten, die FriesenSpy noch nicht kannte, werden beim ersten Anklicken automatisch die letzten 31 Tage von StatSim geholt. Für das vollständige letzte Jahr einmal **„Alle Flüge laden (letztes Jahr)"** klicken — das dauert einige Sekunden.

Einzelflüge können aus zwei Quellen stammen — erkennbar am Badge:
- **Kein Badge** = FriesenSpy hat den Flug live aufgezeichnet → voller GPS-Track auf der Karte verfügbar
- **◌ StatSim** = Flug kommt aus der StatSim-Datenbank → kein GPS-Track, nur Flugplan-Daten (Start, Ziel, Dauer)

---

### 🔍 Event-Suche

Wer von den Friesen war bei einem bestimmten Event dabei?

Oben erscheint die **FriesenEvents-Liste** — Events aus dem FriesenFlieger-Google-Kalender, letzte 365 Tage bis heute, inkl. Wiederholungstermine, neueste zuerst. Ein Klick füllt Datum, Uhrzeit und ICAO-Code automatisch vor und **startet die Suche sofort**. Events ohne erkannten ICAO-Code suchen weltweit (`global`).

**Wie es funktioniert:**
Du gibst einen **ICAO-Code** (z.B. `EDDK`) oder **`global`** für weltweite Suche ein, sowie einen **Zeitraum**. Bei ICAO-Suche wird zusätzlich ein **Radius in km** berücksichtigt. FriesenSpy sucht alle Friesen-Flüge, deren Route durch den Bereich verlief oder die dort gestartet/gelandet sind. Piloten werden gefunden, wenn ihr Flug das Zeitfenster **überlappt** — auch wer schon früher gestartet oder erst nach Event-Ende gelandet ist.

**Was du siehst:**
- **Karte** (oben) mit allen gefundenen GPS-Tracks gleichzeitig eingezeichnet
- **Pilotenliste** (darunter) mit Callsign, Strecke und Flugdauer
- Piloten die nur in StatSim gefunden werden, erscheinen mit **◌ StatSim**-Badge — GPS-Tracks werden automatisch von StatSim nachgeladen und auf der Karte angezeigt (falls verfügbar)

**Was du tun kannst:**
- **Track auf der Karte anklicken** oder **Flug-Zeile in der Pilotenliste anklicken** → hebt diesen Track farblich hervor, alle anderen werden transparent
- **„↺ Alle Tracks"** → blendet alle Tracks wieder gleichmäßig ein
- **Callsign in der Pilotenliste anklicken** → öffnet das Flugdetail-Modal mit Strecke, Flugzeugtyp und weiteren Infos
- **⎘** → Link zu dieser Event-Suche teilen — alle Filtereinstellungen stecken in der URL, der Empfänger sieht dasselbe Ergebnis

> **Tipp:** Der ICAO-Code muss nicht exakt der Veranstaltungsort sein — ein Radius von 50–100 km um den nächsten Flughafen reicht in der Regel aus.

---

## 🏁 FriesenFliegerBummel

Der **FriesenFliegerBummel** ist ein besonderer Event-Typ — ein „Schätzweltmeister"-Rennen: Es gewinnt **nicht der Schnellste**, sondern wer mit der **Summe seiner Gate-to-Gate-Blockzeiten am dichtesten an der Durchschnittszeit aller Teilnehmer** liegt.

**Automatische Erkennung — kein Admin-Aufwand:** Ein Termin im FriesenFlieger-Kalender wird als Bummel erkannt, sobald im **Titel oder in der Beschreibung** das Stichwort „Bummel" steht **und** mindestens **zwei Flugplätze** (ICAO-Codes) hinterlegt sind. Eine Plausibilitätsprüfung verhindert Fehlerkennungen: Liegen zwei Streckenflugplätze weiter als ~600 nm auseinander, wird der Termin nicht als Bummel gewertet.

**Wertung (bewusst robust):**
- **Teilnahme ohne Anmeldung** — jeder Friese, der die Strecke im Zeitfenster fliegt, ist automatisch dabei.
- **Reihenfolge und Richtung egal:** Die Strecke `A–B–C` darf in beliebiger Richtung und Reihenfolge geflogen werden (auch alternative Routings wie `A→C→B`). Gewertet wird, wer **alle Flugplätze** der Strecke besucht hat.
- **Gewertete Zeit** = Summe der Blockzeiten (erste bis letzte Bewegung, inkl. Taxi) aller Beine zwischen den Wettbewerbs-Flugplätzen. Tatsächlich geflogene Meilen, Warteschleifen und Umwege spielen keine Rolle.
- **Niemand fällt still raus:** Piloten, die noch nicht alle Flugplätze besucht haben, werden separat als „unvollständig" mit den fehlenden Flugplätzen aufgelistet.
- **GPS statt Flugplan:** Ob ein Pilot an einem Flugplatz war, erkennt FriesenSpy am **GPS-Track** (erste/letzte Position am Flugplatz), nicht am eingereichten Flugplan. Ein Tippfehler im Flugplan kann eine Wertung also nicht verhindern; der Flugplan dient nur als Rückfall, wenn kein Track vorliegt.

**Fairness-Verdeckung — keine Zeitvorteile durch Nachschauen:** Solange das Rennen läuft, bleiben Durchschnittszeit, Einzelzeiten und das Ranking verborgen — ein noch nicht geflogener Pilot könnte seine Zeit sonst bewusst auf den Schnitt ausrichten. Sichtbar sind nur: wer teilnimmt, Callsign, Flugzeugtyp, Flugplan (Start/Ziel/Route), Abfluguhrzeit, Fortschritt (besuchte Flugplätze, fehlende Flugplätze, Anzahl Beine) und wer gerade unterwegs ist. Die vollständige Auswertung (Zeiten, Schnitt, Ranking) erscheint frühestens bei `dtend` — dem Renn-Ende aus dem Kalendertermin (fehlt es → Mitternacht UTC am Ende des Starttags) — und erst wenn keine Nachzügler mehr in der Luft sind. Einmal enthüllt, bleibt das Ergebnis dauerhaft sichtbar.

**Was du siehst:**
- **Live-Tab:** Solange ein Bummel läuft, zeigt ein Banner oben den aktuellen Teilnahme-Zwischenstand (wer dabei ist, wer gerade unterwegs ist) — ohne Zeiten, solange das Rennen noch nicht enthüllt ist.
- **Events-Tab:** Bummel-Termine tragen ein **🏁 BUMMEL**-Badge. Vor der Enthüllung sieht man Teilnahme und Fortschritt. Nach der Enthüllung öffnet ein Klick das vollständige Ranking (Platz, Pilot, Flugzeug, Beine, Block-Gesamtzeit, Abstand zum Schnitt) samt „unvollständig"-Liste — und **darunter die komplette normale Event-Ansicht** (Karte + alle Piloten im Umkreis, auch Nicht-Teilnehmer; gewertete Piloten tragen ihr Bummel-Standing als Badge).

---

## 🔔 Benachrichtigungen (Push Notifications)

FriesenSpy kann dich benachrichtigen, wenn ein Friese auf VATSIM online geht — auch wenn der Browser im Hintergrund läuft oder der PC gesperrt ist. Optional auch schon beim **Einreichen oder Ändern eines Flugplans** (Prefile), bevor der Pilot online geht — auch bei Änderungen an Abflugzeit, Abflug- oder Zielflughafen. Die Notification enthält Datum und Uhrzeit des geplanten Fluges (aus dem DOF-Feld). Ist der Pilot bereits online, werden Prefile-Änderungen ignoriert.

Zusätzlich kann FriesenSpy Push-Benachrichtigungen senden, wenn ein Friese dem **FriesenFlieger-TeamSpeak** beitritt (siehe [TS-Login-Benachrichtigung](#ts-login-benachrichtigung-phase-1)).

Das Bell-Symbol 🔔 oben rechts im Header öffnet das Benachrichtigungs-Panel.

**Einrichten:**
1. 🔔 klicken → Panel öffnet sich
2. „Beim Online-gehen benachrichtigen" aktivieren
3. Browser fragt nach Erlaubnis → **Zulassen**
4. Optional: Filtern auf bestimmte Piloten (Alle Friesen oder nur ausgewählte)
5. Optional: „Auch bei eingereichten Flugplänen" — standardmäßig aktiv
6. **Speichern**

**Plattformen:**

| Plattform | Wie einrichten | Hinweis |
|-----------|---------------|---------|
| Windows (Edge / Chrome) | Direkt im Browser abonnieren | Funktioniert ohne weitere Schritte |
| Android (Chrome) | Direkt im Browser abonnieren | Chrome empfohlen; Edge auf Android kann Probleme machen |
| iPhone / iPad | Erst als App installieren, dann abonnieren | Safari → Teilen ⬆ → „Zum Home-Bildschirm" → App öffnen → 🔔 |

**Als App installieren:** FriesenSpy ist eine PWA (Web-App-Manifest + Service Worker). Oben auf der Seite erscheint ein **Install-Banner** („📲 FriesenSpy als App installieren") — schließbar (merkt sich das Wegklicken), und ausgeblendet, sobald die App installiert ist. Auf Android/Desktop (Chrome/Edge) öffnet der Button den nativen Install-Dialog; auf iPhone/iPad zeigt der Banner die manuelle Anleitung (Safari → Teilen ⬆ → „Zum Home-Bildschirm"). Installiert läuft FriesenSpy im eigenen Fenster mit App-Icon.

> **Hinweis bei „Nur bestimmte Piloten":** Neue Mitglieder der FriesenFlieger werden nicht automatisch in die Auswahl aufgenommen. Nach einem Neuzugang einmal das Panel öffnen, den neuen Piloten anhaken und erneut speichern.

**„Push zurücksetzen"-Button** (kleiner Link unterhalb des Panels): Falls Benachrichtigungen nicht ankommen, obwohl sie aktiviert sind — dieser Button deregistriert den Service Worker und erzwingt eine frische Registrierung beim Push-Dienst. Danach einmal neu abonnieren.

**Reconnect-Debounce (Online):** Geht ein Pilot innerhalb von `VATSIM_REJOIN_DEBOUNCE_SEC` Sekunden (Default: 900 s / 15 min) erneut online, wird das als vPilot-Reconnect gewertet und löst **keine** zweite „ist online!"-Benachrichtigung aus. Erst nach Ablauf des Fensters gilt es als neue Session. Die Live-Anzeige/State-Machine bleibt davon unberührt — nur das Versenden wird gedämpft.

---

## TS-Login-Benachrichtigung (Phase 1)

FriesenSpy kann eine Web-Push-Benachrichtigung senden, wenn ein Friese dem FriesenFlieger-TeamSpeak beitritt — auch wenn kein Browser offen ist. Das Feature ist **optional** und standardmäßig deaktiviert (`TS_NOTIFY_ENABLED=false`).

> 📡 **Wie komme ich ins TeamSpeak?** Login-Daten für den TeamSpeak und alle weiteren Kommunikationskanäle der FriesenFlieger findest du im Forum: [board.friesenflieger.de – TS & Kommunikationskanäle](https://board.friesenflieger.de/viewtopic.php?t=720).

**Wie es funktioniert:**

Alle `TS_POLL_INTERVAL` Sekunden (Default: 30 s) fragt FriesenSpy den TeamSpeak-Server über die ServerQuery-Schnittstelle (Port 10011) ab. Es wird verglichen, welche FRS-Nummern gerade im konfigurierten Kanal sitzen — neu Beigetretene lösen eine Push-Benachrichtigung aus. Der erste erfolgreiche Poll setzt nur die Baseline (keine Notification). Ein `TS_NOTIFY_CHANNEL_ID=0` überwacht den gesamten Server. Mit `TS_EXCLUDE_CHANNEL_IDS` (komma-separierte Kanal-IDs) lassen sich einzelne Kanäle ausnehmen — z. B. der Verwaltungs-Baum, in dem Beitritte niemanden benachrichtigen sollen.

**Datenschutz / Consent (Subjekt-Seite):** Ob über die TS-Beitritte einer Person überhaupt benachrichtigt werden darf, steuert der Admin über die Tabelle `ts_consent`:

| Sichtbarkeit | Bedeutung |
|---|---|
| `everyone` | Benachrichtigungen erlaubt (Default wenn kein Eintrag) |
| `nobody` | Keine Benachrichtigungen über diese FRS |

Consent wird vom Admin via CLI gesetzt (kein Web-UI):

```bash
python manage_ts_consent.py set FRS135 nobody
python manage_ts_consent.py set FRS135 everyone
python manage_ts_consent.py get FRS135
python manage_ts_consent.py list
python manage_ts_consent.py delete FRS135
```

**Empfänger-Auswahl (eine für alles):** Die Piloten-Auswahl im Benachrichtigungs-Panel („Alle Friesen" / „Nur bestimmte Piloten") gilt für **Online, Flugplan UND TeamSpeak** gemeinsam. Beim Umschalten auf „Nur bestimmte" sind zunächst alle angehakt — du entfernst die Haken bei denen, die du *nicht* willst (auch bei dir selbst → kein Selbst-Ping, für alle drei Typen). Die Checkbox „🎧 Bei TeamSpeak-Beitritt benachrichtigen" steuert separat, ob TS-Pings überhaupt erwünscht sind. TS-Beitritte werden über das VATSIM-Callsign (= FRS-Nummer) der CID zugeordnet und gegen dieselbe Auswahl geprüft.

Hinweis: Im Modus „Nur bestimmte" bekommen reine TS-Leute **ohne** VATSIM-Flug keinen Ping (nicht in der Liste). Im Modus „Alle" schon.

**Verweildauer-Bestätigung:** `TS_MIN_DWELL_POLLS` (Default: 1) legt fest, wie viele *zusätzliche* Polls eine FRS präsent bleiben muss, bevor benachrichtigt wird. Bei `1` muss sie beim Folge-Poll noch da sein — kurzes „Reinschauen" (vor dem nächsten Poll wieder weg) löst dann **keine** Benachrichtigung aus (Kosten: bis zu ein Poll-Intervall mehr Verzögerung). `0` = sofort beim ersten Erkennen.

**Debounce:** Ein schnelles Re-Join (z.B. TS-Client-Neustart) löst innerhalb von `TS_REJOIN_DEBOUNCE_SEC` Sekunden (Default: 900 s / 15 min) keine erneute Benachrichtigung aus.

**Neue Abhängigkeit:** `ts3` (in `requirements.txt`). Das Paket wird nur beim TS-Poll geladen (lazy import); der Rest von FriesenSpy läuft ohne `ts3`.

**config.env-Variablen:**

```bash
TS_NOTIFY_ENABLED=false      # Default: false — auf true setzen um Feature zu aktivieren
TS_HOST=127.0.0.1            # Default: 127.0.0.1
TS_QUERY_PORT=10011          # Default: 10011
TS_QUERY_USER=               # ServerQuery-Login
TS_QUERY_PASS=               # ServerQuery-Passwort
TS_SERVER_ID=1               # Default: 1
TS_NOTIFY_CHANNEL_ID=0       # Default: 0 = ganzer Server; Kanal-ID für Zielkanal
TS_EXCLUDE_CHANNEL_IDS=      # Komma-separierte Kanal-IDs, die NIE benachrichtigen (z. B. Verwaltung)
TS_MIN_DWELL_POLLS=1         # Default: 1 = muss beim Folge-Poll noch da sein (0 = sofort)
TS_POLL_INTERVAL=30          # Default: 30 Sekunden
TS_REJOIN_DEBOUNCE_SEC=900   # Default: 900 s (15 min)
```

> Der `ts_poll`-Job wird registriert, sobald `TS_NOTIFY_ENABLED=true` ist — die **Live-Anzeige** (Live-Tab-Panel + Widget-Zähler) funktioniert auch ohne VAPID. Für **Push-Benachrichtigungen** müssen zusätzlich die VAPID-Keys konfiguriert sein (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT_EMAIL`); fehlen sie, läuft nur die Anzeige.

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

Jeder Zustand in FriesenSpy ist als Link teilbar — der aktuelle Tab, ein geöffneter Flugplan, eine Event-Suche, ein bestimmter GPS-Track, ein geöffnetes Flugdetail-Modal. Der gesamte Zustand steckt im URL-Hash (`#...`), sodass sich beim Neuladen der Seite genau derselbe Zustand öffnet.

Das ⎘-Symbol neben Piloten und Flügen kopiert den fertigen Link direkt in die Zwischenablage. Wenn das Flugdetail-Modal geöffnet ist, enthält der kopierte Link auch genau diesen Flug — der Empfänger sieht beim Öffnen des Links das Modal direkt.

---

## Woher kommen die Daten?

FriesenSpy kombiniert zwei Datenquellen:

| | FriesenSpy (Live) | StatSim (Historisch) |
|---|---|---|
| **GPS-Track** | ✅ lokal (alle 15 s aufgezeichnet) | ✅ lokal gecacht (ab erstem Abruf) |
| **Event-Suche auf Karte** | ✅ Track sichtbar | ✅ Track sichtbar |
| **Flugplan (DEP/ARR)** | ✅ | ✅ |
| **Flugdauer** | ✅ | ✅ |
| **Verfügbarkeit** | Nur wenn FriesenSpy läuft | Letztes Jahr via API |
| **GPS-Aufbewahrung** | Dauerhaft | Dauerhaft (nach erstem Abruf) |
| **Fluganzahl in Statistiken** | ✅ gezählt | ✅ gezählt (Duplikate gefiltert) |

**FriesenSpy (Live):** Jede VATSIM-Position wird alle 15 Sekunden abgerufen und gespeichert. Das ergibt einen präzisen GPS-Track für jeden Flug. Flugdaten bleiben **dauerhaft** in der Datenbank.

**StatSim:** Eine öffentliche Datenbank mit historischen VATSIM-Flügen ([statsim.net](https://statsim.net)). FriesenSpy fragt StatSim ergänzend ab, um Flüge zu finden, die vor dem Start von FriesenSpy stattgefunden haben oder bei einem Serverausfall nicht aufgezeichnet wurden. StatSim liefert GPS-Tracks, die beim ersten Abruf lokal gespeichert werden.

> FriesenSpy-Tracks enthalten dichtere Positionsdaten (15-Sekunden-Intervalle). StatSim dient als Rückfall für ältere Zeiträume oder bei Serverausfall.

**Wie ein „Flug" bestimmt wird.** Eine VATSIM-Verbindung ist über `(CID, Logon-Zeit)` eindeutig — das ist der Schlüssel für einen Flug. Container-Neustarts oder doppelte Aufzeichnungen können nie mehr Duplikate erzeugen (struktureller Unique-Index). Ein **vorübergehender Reconnect** (z. B. kurzer Netzausfall) erzeugt technisch zwei Verbindungen, wird aber zu **einem** Flug zusammengeführt, solange Callsign und Flugplan passen und der Reconnect geografisch plausibel anschließt (ein 10-Minuten-Ausfall, bei dem der Sim weiterfliegt, wird korrekt als ein Flug gewertet). Die Disconnect-Lücke zählt nicht zur Flugzeit. Alle Ansichten (Statistik, Events, Piloten-Detail) berechnen Flugzahl und -dauer aus **einer** gemeinsamen Funktion — die Zahlen stimmen überall überein. Fehlerhafte Altdaten werden reversibel bereinigt (markiert, nicht gelöscht).

Pro Flug werden zwei Zeiten geführt: **Online-Zeit** (wie lange der Pilot mit VATSIM verbunden war, logon→logoff) und **Block-Zeit** (tatsächliche Bewegung von der ersten bis zur letzten Fahrt, gate-to-gate). So zählt z. B. langes Parken am Gate bei laufender Verbindung zwar in die Online-Zeit, nicht aber in die Block-Zeit. Block-Zeit gibt es nur für FriesenSpy-Aufzeichnungen (StatSim liefert keine GPS-Spur dafür).

---

## Für Entwickler

### Stack

| Schicht | Technologie |
|---------|-------------|
| Backend | Python 3.11, FastAPI, APScheduler |
| Datenbank | SQLite (WAL-Mode) |
| HTTP-Client | httpx (async) |
| TS-Client | ts3 (ServerQuery, nur bei TS_NOTIFY_ENABLED) |
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
VATSIM_REJOIN_DEBOUNCE_SEC=900              # s, Default: 900 (15 min) — Reconnect-Fenster Online-Push
DB_PATH=friesenspy.db                       # Lokal: relativer Pfad OK
LOG_LEVEL=INFO                              # Default: INFO — App-Logger (Push/Poll sichtbar)
TELEGRAM_BOT_TOKEN=                         # Optional
TELEGRAM_CHAT_ID=                           # Optional
STATSIM_API_KEY=                            # Optional: historische Flüge via statsim.net
OPENAIP_API_KEY=                            # Optional: OpenAIP-Overlay (Luftraum, Navaids)
VAPID_PUBLIC_KEY=                           # Optional: Web Push Public Key (base64url)
VAPID_PRIVATE_KEY=                          # Optional: Web Push Private Key (base64url, 43 Zeichen)
VAPID_CONTACT_EMAIL=                        # Optional: mailto:... für Web Push
# TeamSpeak-Login-Benachrichtigung (alle optional, Default: deaktiviert)
TS_NOTIFY_ENABLED=false
TS_HOST=127.0.0.1
TS_QUERY_PORT=10011
TS_QUERY_USER=
TS_QUERY_PASS=
TS_SERVER_ID=1
TS_NOTIFY_CHANNEL_ID=0                      # 0 = ganzer Server
TS_EXCLUDE_CHANNEL_IDS=                     # Kanal-IDs (CSV), die nie benachrichtigen
TS_MIN_DWELL_POLLS=1                        # muss beim Folge-Poll noch da sein (0 = sofort)
TS_POLL_INTERVAL=30
TS_REJOIN_DEBOUNCE_SEC=900
```

### Tests

```bash
pytest tests/ -v
```

261 Tests, keine externen Abhängigkeiten (alles gemockt).

### Deployment

GitHub Push auf `main` → GitHub Actions baut Docker-Image → pushed nach GHCR → SSH-Deploy auf VPS.

```
main branch
    └─► GitHub Actions (.github/workflows/deploy.yml)
            └─► docker build → ghcr.io/regover13/friesenspy:latest
                    └─► SSH: docker compose pull + up -d
```

### Versionierung & Changelog

Die Versionsnummer + der Changelog liegen als Repo-Datei **`app/CHANGELOG.json`** (neueste Version
zuerst; je Eintrag `version`, `date`, `title`, `items`). `app/version.py` liest sie ein, das Frontend
bekommt sie über `/api/frontend-config`. Im Header erscheint eine kleine Versionsnummer (Klick öffnet
den **Versionsverlauf**); bei einer neuen Version sehen Nutzer einmalig ein **Banner** mit den
Neuerungen (per ✕ wegklickbar, gemerkt in `localStorage['fs_changelog_seen']`).

**Neues Release veröffentlichen:** bei einer signifikanten Änderung in `app/CHANGELOG.json` einen
neuen Eintrag **ganz oben** einfügen (semantische Version `MAJOR.MINOR.PATCH` + Datum + `items`).
Schema: „großer Wurf" → Major (Flugplan-Zuordnung = 2.0.0, OpenAIP = 3.0.0, TeamSpeak = 4.0.0,
PWA = 5.0.0), kleineres Feature → Minor, reiner Bugfix → Patch. Nach dem
Deploy erscheint das Banner automatisch bei allen Nutzern, die die Version noch nicht gesehen haben.

### Projektstruktur

```
FriesenSpy/
├── app/
│   ├── main.py        # FastAPI-App, REST + SSE-Endpoints
│   ├── config.py      # pydantic-settings (liest config.env)
│   ├── database.py    # SQLite WAL, alle DB-Funktionen
│   ├── vatsim.py      # VATSIM-API-Client + Callsign-Filter
│   ├── statsim.py     # StatSim API-Client (historische Flüge)
│   ├── geo.py         # Haversine, ICAO→Koordinaten via airportsdata (offline), Event-Filter
│   ├── alerts.py      # Telegram-Alerts (silent fail)
│   ├── calendar_sync.py # FriesenFlieger Google-Kalender (iCal-Parser, alle 6h via Poller)
│   ├── teamspeak.py   # TeamSpeak-ServerQuery-Client (FRS-Parsing, fetch_channel_clients)
│   ├── poller.py      # APScheduler, Flug-State-Machine, Kalender-Sync, SSE-Fan-out
│   ├── version.py     # liest CHANGELOG.json → VERSION + CHANGELOG
│   ├── CHANGELOG.json # Versionsverlauf (Quelle für Header-Badge, Banner, Verlauf)
│   └── static/
│       ├── index.html # Vanilla-JS-SPA (4 Tabs)
│       ├── sw.js      # Service Worker (Web-Push + PWA)
│       ├── manifest.webmanifest # PWA-Manifest (installierbar)
│       ├── icon-192.png / icon-512.png / icon-maskable-512.png / apple-touch-icon.png
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
| `/robots.txt` | GET | Bot-Indizierung gesperrt (`Disallow: /`) |
| `/health` | GET | `{"status": "ok"}` |
| `/api/live` | GET | Aktuelle Live-Positionen (inkl. Flugplan-Felder) |
| `/api/prefiles` | GET | Eingereichte VATSIM-Flugpläne (FRS*, noch nicht online) |
| `/api/teamspeak` | GET | Aktuell im TeamSpeak befindliche FRS + Anzahl (letzter TS-Poll-Snapshot) |
| `/api/stats?days=30&sort_by=last_flight&sort_dir=desc` | GET | Letzter Flug + Fluganzahl + Flugzeit pro Pilot, sortierbar |
| `/api/stats/activity?days=30` | GET | Flugaktivität über Zeit (täglich/monatlich) |
| `/api/pilots/{cid}/flights?days=365` | GET | Einzelflüge eines Piloten (FriesenSpy + StatSim) |
| `/api/pilots/{cid}/live-track` | GET | GPS-Track des aktuell laufenden Fluges |
| `/api/flights/{id}/track` | GET | GPS-Track eines FriesenSpy-Fluges |
| `/api/flights/statsim/{id}/track` | GET | GPS-Track eines StatSim-Fluges |
| `/api/events?icao=EDDK&radius=150&start=...&end=...` | GET | Event-Teilnehmer mit Tracks (Overlap-Logik) |
| `/api/calendar/events` | GET | FriesenEvents letzte 365 Tage bis heute, inkl. RRULE-Expansion + `route`/`is_bummel` (Google-Kalender-Cache) |
| `/api/bummel/races` | GET | Liste aller bekannten Bummel-Rennen (`id, name, route, dtstart, dtend, status, participant_count, calendar_uid`) |
| `/api/bummel/race/{id}` | GET | Öffentliche Sicht eines Rennens — vor Enthüllung redigiert (keine Zeiten/Schnitt/Ranking), danach vollständiges Ergebnis |
| `/api/bummel/active` | GET | Laufendes/wartendes Rennen als redigierte Sicht fürs Live-Banner — sonst `null`; bereits enthüllte Rennen erscheinen hier nicht mehr |
| `/widget` | GET | Einbettbares iframe-Widget (heller friesenflieger.de-Stil, inkl. Prefiles + TS-Zähler `🎧 N im TS`) |
| `/widget/preview` | GET | Vorschau + Einbettungscode für das Widget |
| `/api/sse` | GET | Server-Sent Events Stream |

Details: siehe [docs/api.md](docs/api.md)
