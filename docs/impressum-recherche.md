# Recherche: Impressumspflicht für devprops.de-Dienste (insb. FriesenSpy)

**Stand:** 2026-07-07 · **Task:** #65 · **Art:** Recherche (keine Codeänderung)

> **Disclaimer:** Keine Rechtsberatung. Diese Recherche fasst öffentlich zugängliche
> Rechtsquellen und Fachartikel zusammen und ersetzt keine anwaltliche Einzelfallprüfung.
> Im Zweifel Anwalt für IT-/Medienrecht oder Verbraucherzentrale konsultieren.

## 1. Kurzfazit

- **Impressum: wahrscheinlich pflichtig.** FriesenSpy ist technisch öffentlich (kein Login),
  wird dauerhaft/planmäßig betrieben und richtet sich an eine Gruppe (FriesenFlieger-Community)
  außerhalb des eigenen Haushalts/der Familie. Das erfüllt „geschäftsmäßig" i. S. d. § 5 DDG —
  Gewinnerzielungsabsicht ist **nicht** erforderlich. Die enge Ausnahme „ausschließlich
  persönliche/familiäre Zwecke" greift hier voraussichtlich nicht.
- **Datenschutzerklärung: ja, unabhängig davon** (Art. 13 DSGVO). Server-Logs/IP zwingend;
  VATSIM-CID/Callsign/Positionsdaten personenbeziehbar (VATSIM behandelt CID selbst als
  personenbezogen); Push-Abos. Pflicht praktisch ausnahmslos.
- **§ 18 MStV** (redaktionelle Verantwortung): **nicht einschlägig** — reiner Datentracker,
  keine journalistisch-redaktionellen Inhalte.
- **Abmahnrisiko:** praktisch überschaubar (kein wirtschaftliches Interesse klassischer
  Abmahner an einem nicht-kommerziellen Hobby-Tracker), rechtlich aber nicht sauber
  ausgeschlossen; „ist ja nur privat" ist wegen Gruppenbezug + offener Erreichbarkeit wacklig.

## 2. Begründung (Kern)

**§ 5 DDG** (seit 14.05.2024 Nachfolger des TMG, Impressumsregel inhaltlich übernommen)
verlangt Pflichtangaben für „geschäftsmäßige, in der Regel gegen Entgelt angebotene" Dienste.
**„Geschäftsmäßig" ≠ „gewerblich":** keine Gewinnabsicht nötig, es genügt eine nachhaltige,
nicht nur einmalige Tätigkeit. Für **Vereine** ist ausjudiziert, dass sie geschäftsmäßig
handeln, sobald der Auftritt auf Dauer/Nachhaltigkeit angelegt ist — direkte Analogie zu einem
Community-Projekt.

Die Ausnahme **„ausschließlich persönliche/familiäre Zwecke"** ist eng (vgl. Haushaltsausnahme
Art. 2 Abs. 2 lit. c DSGVO) und auf den eigenen Innenkreis zugeschnitten. Ein für eine **Gruppe
Dritter** dauerhaft bereitgestellter, technisch offener Dienst fällt nicht mehr darunter — auch
wenn der Nutzerkreis klein und faktisch geschlossen ist.

**Datenschutz** ist von der Impressumsfrage getrennt: schon IP-Speicherung in Server-Logs löst
die Informationspflicht aus; FriesenSpy verarbeitet zusätzlich personenbeziehbare VATSIM-Daten
und Push-Abos.

## 3. Handlungsempfehlung

### Pflichtangaben Impressum (§ 5 DDG, natürliche Person)
1. Vor- und Nachname (bürgerlicher Name; keine Firmierung nötig)
2. **Ladungsfähige Anschrift** — Postfach reicht **nicht**. Risikoärmere Alternativen (nur
   genannt, nicht empfohlen): c/o-Adresse, Zustellungsbevollmächtigter (§ 171 ZPO; BGH
   07.07.2023), kommerzielle Impressumsdienste.
3. Schnelle elektronische Kontaktmöglichkeit (E-Mail; Telefonpflicht uneinheitlich).
4. Keine weiteren Angaben (kein Gewerbe/Register/Kammer/USt-ID).

### Muster-Struktur Impressum (Platzhalter)
```
Impressum — Angaben gemäß § 5 DDG
[Vorname Nachname]
[Straße Hausnummer] · [PLZ Ort]
Kontakt: E-Mail: [kontakt@devprops.de]
Verantwortlich für den Inhalt: [Name], Anschrift wie oben
(kein journalistisch-redaktionelles Angebot i. S. d. § 18 MStV)
Hinweis: nicht gewerblich, ohne Gewinnerzielungsabsicht betrieben.
```

### Muster-Struktur Datenschutzerklärung (Art. 13 DSGVO, Grundgerüst)
1. Verantwortlicher (Name/Anschrift/E-Mail)
2. Verarbeitete Daten + Zwecke: Server-Logfiles (IP/Zeit/User-Agent, techn. notwendig);
   VATSIM-Flugdaten (CID/Callsign/Position/Statistik, Zweck Live-Tracking); Push-Abos;
   ggf. TeamSpeak-Login-Erkennung
3. Rechtsgrundlage: Art. 6 Abs. 1 lit. f (berechtigtes Interesse) bzw. lit. a (Einwilligung, Push)
4. Speicherdauer/Löschfristen
5. Empfänger/Weitergabe (Hosting-Provider; ggf. Drittland)
6. Betroffenenrechte (Auskunft, Berichtigung, Löschung, …, Beschwerderecht bei Aufsichtsbehörde)
7. Kontakt für Betroffenenanfragen

### Nächste Schritte (priorisiert)
1. **FriesenSpy zuerst** absichern (Impressum + Datenschutz).
2. **Zentrales** Impressum/Datenschutz unter `devprops.de/impressum` bzw. `/datenschutz`, von
   allen öffentlich erreichbaren Diensten verlinken (Nextcloud, Vaultwarden, n8n, Condor-Web,
   MCP-Frontends).
3. Rein für Eigenbedarf laufende Dienste ohne Drittnutzer: Einzelfallprüfung, ob überhaupt ein
   öffentliches Angebot an Dritte vorliegt.

## 4. Quellen

- § 5 DDG — https://www.gesetze-im-internet.de/ddg/__5.html
- HÄRTING: DDG-Handlungsbedarf — https://haerting.de/wissen/handlungsbedarf-fuer-website-betreiber-aufgrund-des-neuen-digitale-dienste-gesetzes-ddg/
- StBK Köln: § 5 DDG Informationspflichten — https://www.stbk-koeln.de/rechtlicher-service/berufsrecht/allgemeine-informationspflichten-nach-5-digitale-dienste-gesetz-ddg/
- Rickert.law: Impressumspflicht § 5 TMG/DDG — https://rickert.law/impressumspflicht-nach-%C2%A7-5-tmg/
- eRecht24: private Homepage — https://www.e-recht24.de/impressum/13095-impressum-fuer-die-private-homepage.html
- eRecht24: ladungsfähige Anschrift — https://www.e-recht24.de/impressum/13082-ladungsfaehige-anschrift.html
- eRecht24: c/o-Adresse — https://www.e-recht24.de/impressum/8369-impressum-c-o-adresse.html
- eRecht24: Impressum & Abmahnungen — https://www.e-recht24.de/impressum/13073-impressum-und-abmahnungen.html
- eRecht24: Datenschutz private Website — https://www.e-recht24.de/datenschutz/13237-datenschutzerklaerung-private-website.html
- IT-Recht Kanzlei: Facebook-Gruppen — https://www.it-recht-kanzlei.de/impressum-facebook-gruppen.html
- ERGO: Vereinswebseite — https://www.ergo.de/de/rechtsportal/internetrecht/vereinswebseite-nicht-ohne-impressum
- ARAG: Impressum für Vereine — https://www.arag.de/vereinsversicherung/sicheres-impressum-fuer-vereine/
- RESMEDIA: § 18 MStV — https://www.res-media.net/18-mstv-das-impressum-und-der-verantwortliche/
- FSM: Anbieterkennzeichnung — https://www.fsm.de/wissen/a-bis-z/anbieterkennzeichnung-impressum/
- giel-rechtsanwalt.de: Datenschutz-Pflicht — https://giel-rechtsanwalt.de/allgemein/datenschutzerklaerung-webseite-pflicht/
- Art. 13 DSGVO — https://dsgvo-gesetz.de/art-13-dsgvo/
- VATSIM Germany Forum: CID/Klarnamen/Datenschutz — https://board.vatsim-germany.org/threads/vatsim-id-klarnamen-und-datenschutz-wie-handhabt-ihr-das.67297/
- VATSIM Germany: DSGVO — https://www.vatsim-germany.org/dsgvo
- abmahnung.org: Impressum private Homepage — https://www.abmahnung.org/impressum-private-homepage/
- zerodox.de: ladungsfähige Anschrift — https://zerodox.de/ladungsfaehige-anschrift-impressum
