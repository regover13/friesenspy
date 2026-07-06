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
- [FriesenFliegerBummel](#-friesenfliegerbummel)
- [FriesenKutter (Transportflüge)](#-friesenkutter-transportflüge)
  - [Verwaltung (Admin)](#verwaltung-admin)
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

### Wie FriesenSpy Flüge zählt (GPS-only, seit v8.0.0)

Seit v8.0.0 ist der **GPS-Track die einzige Wahrheit** für „was ist ein Flug". FriesenSpy
erkennt Abheben und Landung direkt aus den aufgezeichneten Positionen — nicht mehr aus dem
Verbindungsende oder einem Flugplanwechsel:

- **Abheben** wird an der Höhe über dem Boden erkannt (nicht an der Geschwindigkeit — damit
  auch ein langsam steigendes STOL/Heli sauber erfasst wird).
- **Landung zählt nur an einem echten Flugplatz** (Umkreis-Check, siehe unten). Eine Außenlandung
  ist per GPS nicht von einem Absturz zu unterscheiden — deshalb wird sie bewusst nie als Ankunft
  gewertet; der Flug bleibt offen, bis der Pilot tatsächlich an einem Platz landet.
- **Zwischenlandungen ohne neuen Flugplan** werden dadurch automatisch als eigene Flüge erfasst —
  A → B → C ist jetzt garantiert zwei Flüge, auch wenn der Pilot nie neu gefiled hat.
- **Die Ankunft zählt sofort**, sobald der GPS-Track sie zeigt — ein Disconnect ist dafür nicht
  mehr nötig. Eine Platzrunde (mehrere Landungen am selben Platz, z.B. Touch-and-Go) bleibt dabei
  weiterhin **ein** Flug, keine Mehrfachzählung.
- Der **eingereichte Flugplan** (DEP/ARR) bleibt erhalten und wird weiterhin angezeigt — er ist
  aber nur noch Beschriftung, keine Grundlage mehr für die Flugzählung selbst.

**Fallback ohne GPS-Track:** Fehlt ein Track (z. B. reine StatSim-Historie oder ein Serverausfall
mitten im Flug), fällt FriesenSpy auf die klassische, refile-/disconnect-basierte Erkennung
zurück (Reconnect-Merge über Callsign + Flugplan + Zeitlücke, wie zuvor) — Details dazu unter
[`docs/architecture.md`](docs/architecture.md) → „GPS-Leg-Erkennung" / `canonicalize_legs`.

**Historie rückwirkend neu bewertet:** Mit der Aktivierung wurde die komplette bestehende
Flug-Historie nach dem neuen Verfahren neu berechnet (kein Daten-Backfill nötig, die GPS-Tracks
lagen bereits vor) — deshalb ist v8.0.0 ein Major-Release.

**Flugzeit vs. Blockzeit:** Pro Flug werden zwei Zeiten unterschieden — **Flugzeit** (Abheben →
Landung, reine Luftzeit) und **Blockzeit** (gate-to-gate: Bewegung inkl. Taxi, ab Losrollen bis
zum Stillstand nach der Landung; belegte Standphasen ab 10 Minuten — z. B. eine Zwischenlandung
ohne Disconnect — zählen nicht mit). Beide erscheinen getrennt in den Fluglisten.

**Woher kommen die Airport-Koordinaten?** Der Geo-Check nutzt das Python-Package [`airportsdata`](https://github.com/mborsetti/airportsdata), das eine vollständige ICAO-Datenbank eingebettet enthält — inklusive aller deutschen Sonderlandeplätze und Kleinflugplätze (z.B. EDKB, EDKV, EDRV). Die Koordinaten stammen aus der [OurAirports](https://ourairports.com)-Datenbank. Es findet kein API-Call statt — die Abfrage ist offline und instant.

> **Landeplatz-Radius:** Ein datenbasiert ermittelter, **fester Radius von 4 km** um einen
> Flugplatz gilt für die gesamte Platz-Zuordnung (Flugerkennung, FriesenFliegerBummel,
> FriesenKutter) — klein genug, um eng benachbarte Plätze (z. B. Ostfriesische Inseln) nicht zu
> verwechseln. Es gibt **keinen** separat einstellbaren Radius mehr pro Bummel-Rennen oder
> Kutter-Event.

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
- **⛶ Vollbild** (Button unten links) — Karte auf den ganzen Bildschirm vergrößern, **Esc** oder erneuter Klick verlässt es wieder

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
- **◎** neben einem Einzelflug → öffnet den GPS-Track dieses Fluges in einem eigenen Fenster (mit **⛶ Vollbild**)
- **⎘** neben einem Einzelflug → kopiert den Link zu genau diesem Flug

> **„Ich sehe nur 30 Tage Statistik"** — Das ist der Default. Oben links im Statistiken-Tab gibt es einen Umschalter für **30 / 90 / 365 Tage**. Für Piloten, die FriesenSpy noch nicht kannte, werden beim ersten Anklicken automatisch die letzten 31 Tage von StatSim geholt. Für das vollständige letzte Jahr einmal **„Alle Flüge laden (letztes Jahr)"** klicken — das dauert einige Sekunden.

Einzelflüge können aus zwei Quellen stammen — erkennbar am Badge:
- **Kein Badge** = FriesenSpy hat den Flug live aufgezeichnet → GPS-Track sofort verfügbar
- **◌ StatSim** = Flug kommt aus der StatSim-Datenbank → GPS-Track wird im Hintergrund automatisch nachgeladen (kann etwas dauern); bis dahin nur Flugplan-Daten (Start, Ziel, Dauer)

**GPS-Route und Flugplan getrennt (seit v8.0.0):** Die Einzelflug-Liste zeigt zwei eigene Spalten
— die tatsächlich geflogene **GPS-Route** (woher/wohin die Landung wirklich erkannt wurde) und
daneben den **eingereichten Flugplan** (DEP/ARR), falls vorhanden; beide können bei einer
Zwischenlandung ohne Refile auseinanderfallen. Ein noch nicht gelandeter (offener) Flug trägt ein
**„🛫 läuft"**-Kennzeichen statt eines Ziels. Flüge unter einem **Nicht-`FRS`-Callsign** (z. B. ein
anderes Rufzeichen desselben Piloten) erscheinen ebenfalls in der Liste, tragen aber ein **„nicht
gewertet"**-Badge — sie zählen nicht in Statistik, FriesenFliegerBummel oder FriesenKutter.

---

### 🔍 Event-Suche

Wer von den Friesen war bei einem bestimmten Event dabei?

Oben erscheint die **FriesenEvents-Liste** — Events aus dem FriesenFlieger-Google-Kalender, letzte 365 Tage bis heute, inkl. Wiederholungstermine, neueste zuerst. Ein Klick füllt Datum, Uhrzeit und ICAO-Code automatisch vor und **startet die Suche sofort**; das zuletzt angeklickte Event bleibt in der Liste hervorgehoben. Events ohne erkannten ICAO-Code suchen weltweit (`global`). Die Liste holt sich beim erneuten Öffnen des Events-Tabs automatisch frische Daten — im Google-Kalender gelöschte Termine verschwinden dadurch spätestens beim nächsten Kalender-Sync (alle 6h) auch hier.

**Wie es funktioniert:**
Du gibst einen **ICAO-Code** (z.B. `EDDK`) oder **`global`** für weltweite Suche ein, sowie einen **Zeitraum**. Bei ICAO-Suche wird zusätzlich ein **Radius in km** berücksichtigt. FriesenSpy sucht alle Friesen-Flüge, deren Route durch den Bereich verlief oder die dort gestartet/gelandet sind. Piloten werden gefunden, wenn ihr Flug das Zeitfenster **überlappt** — auch wer schon früher gestartet oder erst nach Event-Ende gelandet ist.

**Was du siehst:**
- **Karte** (oben) mit allen gefundenen GPS-Tracks gleichzeitig eingezeichnet (werden pro Flug nachgeladen, sobald die Suche fertig ist)
- **Pilotenliste** (darunter), je Pilot eine Flugtabelle im selben Format wie in den Statistiken: Callsign, Aircraft, GPS-Strecke, Flugplan (falls vorhanden), Datum, Flugzeit, Blockzeit, Distanz, Track und Quelle
- Piloten die nur in StatSim gefunden werden, erscheinen mit **◌ StatSim**-Badge — GPS-Tracks werden automatisch von StatSim nachgeladen und auf der Karte angezeigt (falls verfügbar)

**Was du tun kannst:**
- **Track auf der Karte anklicken** oder **Flug-Zeile in der Pilotenliste anklicken** → hebt diesen Track farblich hervor, alle anderen werden transparent
- **„↺ Alle Tracks"** → blendet alle Tracks wieder gleichmäßig ein
- **⛶ Vollbild** (Button unten links auf der Karte) — Esc oder erneuter Klick verlässt es wieder
- **GPS-Strecke anklicken** → öffnet das GPS-Detail-Fenster (Start/Landung UTC, Distanz); **Flugplan anklicken** (falls vorhanden) → öffnet das Flugplan-Fenster; **Track-Symbol** → öffnet den GPS-Track in einem eigenen Fenster (mit **⛶ Vollbild**)
- **⎘** → Link zu dieser Event-Suche teilen — alle Filtereinstellungen stecken in der URL, der Empfänger sieht dasselbe Ergebnis

> **Tipp:** Der ICAO-Code muss nicht exakt der Veranstaltungsort sein — ein Radius von 50–100 km um den nächsten Flughafen reicht in der Regel aus.

---

## 🏁 FriesenFliegerBummel

Der **FriesenFliegerBummel** ist ein besonderer Event-Typ — ein „Schätzweltmeister"-Rennen: Es gewinnt **nicht der Schnellste**, sondern wer mit der **Summe seiner Gate-to-Gate-Blockzeiten am dichtesten an der Durchschnittszeit aller Teilnehmer** liegt.

**Automatische Erkennung — kein Admin-Aufwand:** Ein Termin im FriesenFlieger-Kalender wird als Bummel erkannt, sobald im **Titel oder in der Beschreibung** das Stichwort „Bummel" steht **und** mindestens **zwei Flugplätze** (ICAO-Codes) hinterlegt sind. Eine Plausibilitätsprüfung verhindert Fehlerkennungen: Liegen zwei Streckenflugplätze weiter als ~600 nm auseinander, wird der Termin nicht als Bummel gewertet.

**Wertung (bewusst robust):**
- **Teilnahme ohne Anmeldung** — jeder Friese, der die Strecke im Zeitfenster fliegt, ist automatisch dabei.
- **Reihenfolge und Richtung egal:** Die Strecke `A–B–C` darf in beliebiger Richtung und Reihenfolge geflogen werden (auch alternative Routings wie `A→C→B`). Gewertet wird, wer **alle Flugplätze** der Strecke besucht hat.
- **Zwischenlandungen sind erlaubt (Bummel = gemütlich):** Wer mit Zwischenstopp fliegt (z.B. `A→X→B`), kommt trotzdem in die Wertung. Gezählt wird die **Tour** vom ersten Start an einem Streckenflugplatz bis zur letzten Landung an einem Streckenflugplatz; die **Standzeit der Zwischenstopps zählt nicht mit** (nur die reine Flugzeit der Beine).
- **Frühstarter zählen mit:** Wer schon vor dem offiziellen Event-Start losfliegt, aber währenddessen unterwegs ist, wird mit seiner **vollen Blockzeit** gewertet.
- **Gewertete Zeit** = Summe der Blockzeiten (Bewegungszeit gate-to-gate inkl. Taxi und kurzer Halte; längere Standphasen ab 10 min — z. B. eine Zwischenlandung ohne Disconnect — zählen nicht) der Tour-Beine. Tatsächlich geflogene Meilen, Warteschleifen und Umwege spielen keine Rolle.
- **Niemand fällt still raus:** Piloten, die noch nicht alle Flugplätze besucht haben, werden separat als „unvollständig" mit den fehlenden Flugplätzen aufgelistet.
- **GPS statt Flugplan:** Ob ein Pilot an einem Flugplatz war, erkennt FriesenSpy am **GPS-Track** (erste/letzte Position am Flugplatz), nicht am eingereichten Flugplan. Ein Tippfehler im Flugplan kann eine Wertung also nicht verhindern; der Flugplan dient nur als Rückfall, wenn kein Track vorliegt. Wie nah eine Position an einem Streckenflugplatz liegen muss, steuert der **feste, globale 4-km-Radius** (siehe oben) — es gibt keinen separat einstellbaren Radius mehr pro Rennen.

**Fairness-Verdeckung — keine Zeitvorteile durch Nachschauen:** Solange das Rennen läuft, bleiben Durchschnittszeit, Einzelzeiten und das Ranking verborgen — ein noch nicht geflogener Pilot könnte seine Zeit sonst bewusst auf den Schnitt ausrichten. Sichtbar sind nur: wer teilnimmt, Callsign, Flugzeugtyp, Flugplan (Start/Ziel/Route), Abfluguhrzeit, Fortschritt (besuchte Flugplätze, fehlende Flugplätze, Anzahl Legs) und wer gerade unterwegs ist. Die vollständige Auswertung (Zeiten, Schnitt, Ranking) erscheint frühestens bei `dtend` — dem Renn-Ende aus dem Kalendertermin (fehlt es → Mitternacht UTC am Ende des Starttags) — und erst wenn keine Nachzügler mehr in der Luft sind. Einmal enthüllt, bleibt das Ergebnis dauerhaft sichtbar.

**Was du siehst:**
- **Live-Tab:** Solange ein Bummel läuft, zeigt ein Banner oben den aktuellen Teilnahme-Zwischenstand (wer dabei ist, wer gerade unterwegs ist) — ohne Zeiten, solange das Rennen noch nicht enthüllt ist.
- **Events-Tab:** Bummel-Termine tragen ein **🏁 BUMMEL**-Badge. Vor der Enthüllung sieht man Teilnahme und Fortschritt. Nach der Enthüllung öffnet ein Klick das vollständige Ranking (Platz, Pilot, Flugzeug, Legs, Block-Gesamtzeit, Abstand zum Schnitt — signiert und sekundengenau, damit auch bei gleicher Minuten-Blockzeit klar ist, wer näher am Schnitt liegt) samt „unvollständig"-Liste — und **darunter die komplette normale Event-Ansicht** (Karte + alle Piloten im Umkreis, auch Nicht-Teilnehmer; gewertete Piloten tragen ihr Bummel-Standing als Badge). Im enthüllten Ranking erscheint außerdem ein **„Für Forum kopieren"**-Button — er erzeugt einen fertig formatierten Ergebnistext zum Einfügen in board.friesenflieger.de. Manuell angelegte Bummel (ohne Kalender-Termin) erscheinen ebenfalls in dieser Liste und sind anklickbar.
- **Push-Benachrichtigungen:** FriesenSpy benachrichtigt (sofern Push aktiviert ist), wenn das Rennen **gestartet** wird — der Trigger ist der erste Pilot, der eine Blockzeit an einem Streckenflugplatz erreicht — und wenn die **Ergebnisse enthüllt** werden. Beide Ereignisse sind Latches (feuern nur einmal je Rennen) und können je Rennen über die Admin-Seite abgeschaltet werden. Diese Benachrichtigungen erreichen nur Abonnenten mit aktiviertem **„Events"-Schalter** (opt-in).

### Badge fürs Forum

Nach der Enthüllung eines Bummels bekommt jeder Teilnehmer ein **Badge-PNG**, das er als Bild in seine Forensignatur bei board.friesenflieger.de einbinden kann — über eine feste URL, die Foren direkt als Bild erkennen (`.png`-Suffix).

- **Sieger (Rang 1):** Badge „Absoluter Durchschnitt!" mit Callsign, Name, Flugzeugmuster, Block-Gesamtzeit und Zeitdifferenz zum Schnitt.
- **Alle anderen Teilnehmer** (auch unvollständige): Medaille „Voll daneben!".
- Beide Badges sind **rund (256 px)** mit transparenten Rändern im echten FriesenFlieger-Look (Flugzeug, ostfriesische Inselkette, Vereinsfarben) und tragen die Fußzeile **friesenflieger.de**.

Im enthüllten Ranking erscheinen je Pilot zwei Schaltflächen: **🎖 Badge** öffnet das PNG direkt; **📋 Forum** kopiert den fertigen BBCode `[img]…/badge/{cid}.png[/img]` in die Zwischenablage — zum direkten Einfügen in board.friesenflieger.de. Die Badges werden serverseitig mit Pillow gezeichnet und unter `data/badges/` gecacht. Vor der Enthüllung liefert der Endpoint 404.

### Verwaltung (Admin)

Die Admin-Seite ist unter `/admin` erreichbar und passwortgeschützt. Das Passwort wird über `ADMIN_PASSWORD` in `config.env` gesetzt (leer = Admin-Bereich deaktiviert; niemals in git). Der Login setzt ein signiertes httponly-Cookie (`fs_admin`), das für die Browsersitzung gültig bleibt — ein Passwort- oder Key-Wechsel invalidiert alle bestehenden Cookies sofort.

**Was die Admin-Seite kann:**
- **Rennen manuell anlegen** — auch ohne Kalender-Termin, mit frei wählbarer Strecke, Start- und (optionalem) Endtermin sowie Anwesenheitsradius. Ein fehlendes `dtend` wird auf Mitternacht UTC des Starttags gesetzt.
- **Rennen bearbeiten und löschen** — nachträgliche Korrekturen an Name, Strecke, Termin oder Radius; Löschen entfernt das Rennen dauerhaft.
- **Enthüllung steuern** — Notfall-Enthüllung (sofort zeigen) oder wieder verbergen, z. B. um einen Fehler zu korrigieren, bevor das Ergebnis öffentlich wird.
- **Teilnehmer-Korrekturen (Overrides)** — einzelne Piloten ausschließen (`exclude`), disqualifizieren (`disqualify`), manuell als Sieger markieren (`winner`) oder mit einer manuell eingegebenen Block-Zeit werten (`manual`). Overrides wirken auf alle öffentlichen Sichten; Durchschnitt und Ranking werden neu berechnet.
- **Push-Benachrichtigungen je Rennen** — Start- und Enthüllungs-Push für ein einzelnes Rennen an- oder abschalten.
- **Vorschau** — vollständige Wertung mit Zeiten und Ranking einsehen, solange das Rennen noch läuft — ohne die öffentliche Sicht zu enthüllen.
- **Badge-Vorschau** — in der Renn-Vorschau je Teilnehmer **🎖 Badge** (öffnet das Badge-PNG, auch schon **vor** der Enthüllung) und **📋 Forum** (kopiert den öffentlichen `[img]…[/img]`-BBCode).
- **Hinweis-Banner steuern** — bestimmen, welcher Changelog-Eintrag als Startseiten-Banner erscheint: `auto` (neuester Highlight-Eintrag), `off` (kein Banner) oder eine konkrete Version.
- **Push-Test & Broadcast** — eine Test-Benachrichtigung nur ans eigene Gerät senden oder eine freie Nachricht (Titel + Text) an alle Abonnenten bzw. nur Events-Abonnenten.
- **Piloten-Verwaltung** — bekannte Piloten auflisten, manuell anlegen oder umbenennen und löschen (Namenspflege; **keine** Mitglieder-Allowlist — Friesen werden weiter über das Callsign-Präfix `FRS` erkannt).

---

## 🦐 FriesenKutter (Transportflüge)

Der **FriesenKutter** ist ein kleines „FSE für Friesen": ein Transportflug-Event, bei dem die Gruppe Nachschub zu einem Ziel fliegt (z.B. Wangerooge → Helgoland) und FriesenSpy **automatisch mitzählt, wie viel Fracht bewegt wurde** — ohne jede Vorbereitung, gespeist aus den ohnehin getrackten FRS-Flügen.

**So läuft es:**

- **Anlegen:** entweder ein Kalendertermin mit dem Stichwort **„FriesenKutter"** im Titel (wird automatisch erkannt, wie beim Bummel) — oder manuell im Admin. Beide erscheinen gemischt.
- **Fracht-Manifest:** Jedes Event hat eine Frachtliste (z.B. *1 t Fischbrötchen + 500 kg Friesen Tee*), die zusammen das Ziel ergibt. Die eingehenden Flüge füllen sie **der Reihe nach** auf; jeder Flug bekommt seine Frachtart.
- **Nur in eine Richtung:** Fracht zählt auf dem Weg **zum Ziel**. Der Rückflug fliegt leer und erscheint im Feed als „leer".
- **Zuladung pro Flugzeugtyp:** Wie viel ein Flug lädt, hängt vom Muster ab (MTOW − Leergewicht − Tankfüllung, alles im Admin einstellbar). Für unbekannte Muster holt der Admin per Klick einen **KI-Vorschlag** (Claude); der Wert bleibt frei anpassbar.
- **Anzeige:** Im Events-Tab zeigt eine Karte einen **segmentierten Ziel-Balken** je Frachtart und darunter den **Flug-Feed** (neueste oben), der sich live aktualisiert.
- **Push:** Start des Events, erreichtes Ziel und eine Feierabend-Zusammenfassung („X Frachtflüge, Y t bewegt") gehen an die Events-Abonnenten. Bleibt ein Event komplett ohne Frachtflug, entfällt die Feierabend-Zusammenfassung (und der dafür sonst nötige KI-Aufruf) — das Event gilt trotzdem als abgeschlossen. Push für ein einzelnes Event lässt sich im Admin an- oder abschalten (analog zum Bummel).
- **Frachtart-Katalog:** Im Admin pflegbare Frachtarten mit Emoji und optionaler Obergrenze pro Flug — z.B. Krabbenbrötchen 🦐 oder Filmrollen 🎞️ (max 100 kg). Ist eine Frachtart gedeckelt, nimmt der Rest der Zuladung eines Flugs automatisch die nächste Frachtart mit (Co-Load).
- **Lustige KI-Sprüche (optional):** Ist der Schalter im Admin aktiv, schreibt Claude zu jedem Flug einen Einzeiler im Friesen-Humor — mit Bezug auf Vorname, Fleiß, Tempo und Umwege — plus eine launige Tagesend-Zusammenfassung.
- **Fracht direkt im Kalendertermin:** Eine Zeile wie `Fracht: 1000 Krabbenbrötchen, 500 Friesentee` in der Termin-Beschreibung befüllt das Manifest beim Kalender-Sync automatisch (Namen gegen den Katalog abgeglichen). Nur beim erstmaligen Anlegen — spätere Admin-Bearbeitungen bleiben bei erneutem Sync erhalten.
- **Ohne Disconnect zählen:** Fracht wird bereits erfasst, sobald du am Ziel-Flugplatz landest (GPS-erkannte Landung) — du musst nicht disconnecten. Einmal erkannt, bleibt die Fracht dauerhaft gezählt, auch wenn du danach weiterfliegst.
- **Reservierung, Teilnehmerliste & verlorene Fracht:** Wer Richtung Ziel abhebt, reserviert seine Zuladung sofort sichtbar im Balken (»davon X kg unterwegs«); eine Teilnehmerliste zeigt wer fliegt, angekommen ist oder zurückkehrt. Wer sein Ziel nie erreicht, verliert die Ladung — »Kutter versunken« oder »geklaut«, im Feed und in der Bilanz sichtbar. Der Erkennungs-Umkreis ist der feste, globale 4-km-Radius (siehe oben) — es gibt keinen separat einstellbaren Radius mehr pro Event.
- **Forum-Badge nach der Feierabend-Bilanz:** Sobald ein Event abgeschlossen ist, bekommt jeder Teilnehmer ein rundes Badge-PNG „Voll beladen!" (Callsign, Flugzeugmuster, gelieferte kg) — bei verlorener Fracht zusätzlich mit Verlust-Titel **SPITZBOOV!** (geklaut), **BADEMESTER!** (versenkt) oder **SEEROVER!** (beides). Im Events-Tab erscheinen dafür je Teilnehmer **🎖 Badge** (öffnet das PNG) und **📋 Forum** (kopiert den BBCode) über dem Flug-Feed — analog zum Bummel-Badge.
- **Status im Admin:** Die Admin-Event-Liste zeigt pro Event ein Status-Badge — **Geplant** (vor `dtstart`), **Läuft** (zwischen `dtstart` und `dtend`), **Wartet** (`dtend` erreicht, Feierabend-Bilanz aber noch nicht erstellt — z. B. Nachzügler in der Luft) oder **Feierabend** (Bilanz erstellt). Rein admin-seitig, keine Änderung am Piloten-Frontend.

## 🔔 Benachrichtigungen (Push Notifications)

FriesenSpy kann dich benachrichtigen, wenn ein Friese auf VATSIM online geht — auch wenn der Browser im Hintergrund läuft oder der PC gesperrt ist. Optional auch schon beim **Einreichen oder Ändern eines Flugplans** (Prefile), bevor der Pilot online geht — auch bei Änderungen an Abflugzeit, Abflug- oder Zielflughafen. Die Notification enthält Datum und Uhrzeit des geplanten Fluges (aus dem DOF-Feld). Ist der Pilot bereits online, werden Prefile-Änderungen ignoriert.

Zusätzlich kann FriesenSpy Push-Benachrichtigungen senden, wenn ein Friese dem **FriesenFlieger-TeamSpeak** beitritt (siehe [TS-Login-Benachrichtigung](#ts-login-benachrichtigung-phase-1)).

Über den **„Events"-Schalter** lassen sich außerdem **Event-Erinnerungen** aktivieren: FriesenSpy sendet dann ~1 h vor jedem FriesenEvent im Kalender einen Push — und benachrichtigt auch bei Bummel-Start und Ergebnisenthüllung. Die ~1h-Erinnerung speist sich aus drei Quellen (Kalender-Events, Bummel-Rennen, Kutter-Events) und läuft dadurch auch für **manuell** im Admin angelegte Bummel/Kutter (nicht nur Kalender-Termine); pro Rennen/Event lässt sich der Push im Admin abschalten, dann bleibt auch die Erinnerung aus. Dieser Schalter ist separat opt-in und standardmäßig deaktiviert.

Das Bell-Symbol 🔔 oben rechts im Header öffnet das Benachrichtigungs-Panel.

**Einrichten:**
1. 🔔 klicken → Panel öffnet sich
2. „Beim Online-gehen benachrichtigen" aktivieren
3. Browser fragt nach Erlaubnis → **Zulassen**
4. Optional: Filtern auf bestimmte Piloten (Alle Friesen oder nur ausgewählte)
5. Optional: „Auch bei eingereichten Flugplänen" — standardmäßig aktiv
6. Optional: **„Events"** — Erinnerung ~1 h vor jedem FriesenEvent + Bummel-Start/Ergebnis (opt-in, Standard: aus)
7. **Speichern**

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

Auch ein **FriesenFliegerBummel** ist teilbar: in der Bummel-Ansicht (sowohl verdeckt als auch nach Enthüllung) kopiert ein **⎘ Teilen**-Knopf den Direkt-Link in die Zwischenablage. Der Link (`#tab=events&bummel=<id>`) öffnet beim Empfänger direkt diesen Bummel. Läuft oder wartet gerade ein Bummel, führt zudem ein **🏁 Zum Bummel**-Knopf im Live-Banner (Live-Tab) direkt in dieselbe Detailansicht.

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

**Wie ein „Flug" bestimmt wird (GPS-only, seit v8.0.0).** Eine VATSIM-Verbindung ist über `(CID, Logon-Zeit)` eindeutig — Container-Neustarts oder doppelte Aufzeichnungen können nie mehr Duplikate erzeugen (struktureller Unique-Index). Die eigentliche **Flugzählung** läuft aber über `canonicalize_legs`: Abheben und Landung werden direkt aus dem GPS-Track erkannt, unabhängig davon, ob die Verbindung dabei getrennt wird. Eine Verbindung kann dadurch **mehrere** Flüge enthalten (Zwischenlandung ohne Refile), und ein Flug zählt bereits bei der GPS-Landung, nicht erst beim Disconnect. **Nur wenn kein GPS-Track vorliegt** (reine StatSim-Historie, Serverausfall mitten im Flug), fällt FriesenSpy auf die klassische refile-/disconnect-basierte Erkennung zurück: ein **vorübergehender Reconnect** (z. B. kurzer Netzausfall) erzeugt technisch zwei Verbindungen, wird aber zu **einem** Flug zusammengeführt, solange Callsign und Flugplan passen und der Reconnect geografisch plausibel anschließt. Alle Ansichten (Statistik, Events, Piloten-Detail, Bummel, Kutter) berechnen Flugzahl und -dauer aus **einer** gemeinsamen Funktion (`canonicalize_legs`, für die globale Statistik über den materialisierten `flight_cache`) — die Zahlen stimmen überall überein. Fehlerhafte Altdaten werden reversibel bereinigt (markiert, nicht gelöscht).

Pro Flug werden zwei Zeiten geführt: **Flugzeit** (Abheben → Landung, `duration_min`) und **Blockzeit** (`block_min`, Summe der tatsächlichen Bewegung gate-to-gate inkl. Taxi; kurze Halte wie Rollhalt zählen mit, belegte Standphasen ab 10 min — etwa eine Zwischenlandung ohne Disconnect — nicht). So zählt z. B. langes Parken am Gate oder auf dem Vorfeld zwar in die Flugzeit, nicht aber in die Blockzeit. Blockzeit gibt es nur für FriesenSpy-Aufzeichnungen (StatSim liefert keine GPS-Spur dafür).

Verliert der VATSIM-Datenfeed einen Piloten kurzzeitig (Feed-Aussetzer), wird die Session beim Wiederauftauchen mit derselben Logon-Zeit nahtlos **wieder geöffnet** — es entstehen weder Duplikate noch verwaiste Tracks. Sollte dennoch einmal ein Flug ohne eigenen Eintrag bleiben (historischer Schaden), rekonstruiert der Server ihn beim Start automatisch aus StatSim + eigenem GPS-Track (`reconstruct_orphaned_flights`).

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
ADMIN_PASSWORD=                             # Optional: Admin-Seite aktivieren (leer = aus; nie in git!)
ANTHROPIC_API_KEY=                          # Optional: FriesenKutter-Zuladungs-Vorschlag (Claude); denselben Key wie TSBot nutzen
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

684 Tests, keine externen Abhängigkeiten (alles gemockt).

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
│   ├── database.py    # SQLite WAL, alle DB-Funktionen (inkl. canonicalize_legs, flight_cache, app_settings, Pilots-CRUD)
│   ├── gps_legs.py    # Reiner GPS-Leg-Detektor (Abheben/Landung aus Positionen, ohne DB) + collapse_same_airport; Spawn-Startplatz- und Landungs-Rettungs-Guards (#49/#53)
│   ├── vatsim.py      # VATSIM-API-Client + Callsign-Filter
│   ├── statsim.py     # StatSim API-Client (historische Flüge)
│   ├── geo.py         # Haversine, ICAO→Koordinaten via airportsdata (offline) + custom_airports (#50, Override seit #56, Radius-Override seit #62), Event-Filter
│   ├── alerts.py      # Telegram-Alerts (silent fail)
│   ├── badge.py       # Badge-Rendering mit Pillow (Sieger-Badge + Medaille, data/badges/-Cache)
│   ├── calendar_sync.py # FriesenFlieger Google-Kalender (iCal-Parser, alle 6h via Poller)
│   ├── teamspeak.py   # TeamSpeak-ServerQuery-Client (FRS-Parsing, fetch_channel_clients)
│   ├── poller.py      # APScheduler, Flug-State-Machine, Kalender-Sync, SSE-Fan-out
│   ├── version.py     # liest CHANGELOG.json → VERSION + CHANGELOG
│   ├── CHANGELOG.json # Versionsverlauf (Quelle für Header-Badge, Banner, Verlauf)
│   └── static/
│       ├── index.html # Vanilla-JS-SPA (4 Tabs)
│       ├── admin.html # Admin-Verwaltung (passwortgeschützt, Bummel-Verwaltung)
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
| `/api/bummel/race/{id}/badge/{cid}.png` | GET | Badge-PNG für Forensignatur (Sieger oder Medaille); erst nach Enthüllung verfügbar, sonst 404 |
| `/admin` | GET | Admin-Seite (passwortgeschützt, `ADMIN_PASSWORD`) |
| `/api/admin/login` | POST | Admin-Login, setzt `fs_admin`-Cookie |
| `/api/admin/logout` | POST | Cookie löschen |
| `/api/admin/me` | GET | Session prüfen (`{"admin":true}` oder 401) |
| `/api/admin/bummel/races` | GET | Volle Rennen-Liste (inkl. `revealed_at`, `started_at`, `push_enabled`, `overrides[]`) |
| `/api/admin/bummel/races` | POST | Manuelles Rennen anlegen |
| `/api/admin/bummel/races/{id}` | POST/DELETE | Rennen bearbeiten / löschen |
| `/api/admin/bummel/races/{id}/reveal` | POST | Notfall-Enthüllung |
| `/api/admin/bummel/races/{id}/hide` | POST | Enthüllung zurücksetzen |
| `/api/admin/bummel/races/{id}/push` | POST | Push für Rennen an/abschalten |
| `/api/admin/bummel/races/{id}/override` | POST | Teilnehmer-Override setzen |
| `/api/admin/bummel/races/{id}/override/{cid}` | DELETE | Override entfernen |
| `/api/admin/bummel/races/{id}/preview` | GET | Vollständige Wertung (Admin-Vorschau) |
| `/api/admin/bummel/races/{race_id}/badge/{cid}.png` | GET | Badge-Vorschau ohne Reveal-Gate (immer frisch, `no-store`) |
| `/api/admin/banner` | GET/POST | Hinweis-Banner-Auswahl lesen/setzen (`auto`/`off`/Version) |
| `/api/admin/push/test` | POST | Test-Push nur ans eigene Gerät (`endpoint`) |
| `/api/admin/push/broadcast` | POST | Freie Push-Nachricht (`title`, `body`, `audience`) |
| `/api/admin/pilots` | GET/POST | Piloten auflisten / anlegen/umbenennen |
| `/api/admin/pilots/{cid}` | DELETE | Pilot entfernen |
| `/widget` | GET | Einbettbares iframe-Widget (heller friesenflieger.de-Stil, inkl. Prefiles + TS-Zähler `🎧 N im TS`) |
| `/widget/preview` | GET | Vorschau + Einbettungscode für das Widget |
| `/api/sse` | GET | Server-Sent Events Stream |

Details: siehe [docs/api.md](docs/api.md)
