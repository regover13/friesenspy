# Auftrag für den Nachtlauf ab 00:50 CET, 31.08.2026

**Erteilt vom Nutzer am 30.08.2026 um 23:09 CEST**, wörtlich:

> „Du kommst gleich an das session Limit. Reset morgen 00:50 cet. Ich will, dass du bis 00:50
> wartest und dann selbständig alles ohne mich umsetzt! Keine stops, setze alles um und gib
> mir kritische Themen und die von dir getroffenen Entscheidungen mit alternativen am Ende.
> Sodass wir im schlimmsten Fall nur noch mal korrigieren muss. Aber du kannst nach main
> deployen, solange der generelle Server Betrieb nicht gefährdet ist."

## Was umzusetzen ist

**BEIDE Pläne, vollständig.** Nachgeschärft vom Nutzer um 23:15 CEST: „Nein alles umsetzen!!
A und B!!" — Plan B ist also nicht „soweit die Zeit reicht", sondern Auftrag.

**Plan A:** `docs/superpowers/plans/2026-08-30-handpassung-schutz.md`, Aufgabe 1 bis 8.
**Plan B:** `docs/superpowers/plans/2026-08-30-ground-chart-overlay.md`, Aufgabe 7 bis 18.
Reihenfolge: A zuerst, weil B dessen Sperre und den reparierten Auffrischlauf braucht.

Zu Plan B gehören die Korrekturen aus den beiden Gutachten, die in der Spec stehen, aber im
Plandokument teilweise noch die alte Fassung tragen. **Maßgeblich ist die Spec, Fassung 2**,
insbesondere: Nordungsfenster (100°, 260°) statt (90°, 270°); Meridiangrad als Reihe statt
110540; transparente Füllung beim Drehen statt weiß; Toleranzen in Metern statt Pixeln;
Querabdeckung 70 % statt 55 %; Maßstabsprüfung gegen den Fit statt nur untereinander;
Permutation auch auf der Bildseite; Achsen vorher zusammenfassen; Notbremse verwirft.

### Nachgeschärft um 23:20 CEST: Ich passe die Blätter selbst

Wörtlich: „Dann mach die Charts einfach selbst!! Das ist dann eine einmalige Anpassung.
Updates kommen nur selten. Die späteren Updates kann ich dann Manuel unter admin abarbeiten.
Sie sollen dann einfach als nur offene angezeigt werden."

**Das dreht Plan B um und macht ihn kleiner.** Die Bahnvermessung wird nicht mehr zum
Produktionsjob, der wöchentlich 61 Plätze neu rechnet, sondern zu **meinem Werkzeug für einen
einmaligen Durchgang**. Konkret:

1. Alle Kandidatenblätter holen, Sorte am Kopf erkennen.
2. Bahnvermessung als **Startwert** rechnen — sie ist bei EDDL und EDDM auf 6 m genau.
3. **Jedes Blatt selbst ansehen.** Kontrollpunkte (Schwellen, ARP) ins Bild zeichnen und
   prüfen, ob sie auf den Bahnenden liegen. Wo es nicht sitzt, die Passung von Hand setzen.
4. Ergebnis als **`quelle='hand'`** ablegen. Damit greift die Sperre aus Plan A: Kein
   späterer Lauf kann meine Arbeit überschreiben.

**Der wöchentliche Ground-Job passt danach nichts mehr.** Er vergleicht nur noch den
`quell_hash` des Rohblatts. Ändert sich einer, wird der Platz als **offener Punkt** im Admin
angezeigt — die Vorschlagsliste aus Plan A Aufgabe 6 und 7 ist genau dafür da. Der Nutzer
arbeitet sie von Hand ab.

Das löst nebenbei drei Befunde der Gutachten: Der Job ist jetzt wirklich arbeitsarm (nur zwei
Abrufe je Platz, keine Bildanalyse), die Ausbeutefrage aus Spec 14.1 ist gegenstandslos, und
die 180°-Mehrdeutigkeit bei symmetrischem Querdruck entscheide ich mit den Augen.

**Die Prüfkette bleibt trotzdem im Code** (`app/ground_charts.py`) — als Startwertlieferant
für neue Plätze und als Beleg der Messungen. Sie darf nur nichts mehr allein veröffentlichen.

Im Schlussbericht: wie viele Blätter ich gepasst habe, wie viele ich verworfen habe und warum.



Aufgabe 1 ist bereits erledigt (Commit steht aus): `HandpassungGesperrt` und die Sperre in
`upsert_aip_chart` sind in `app/database.py`, `tests/test_handpassung_schutz.py` hat 7 grüne
Tests. **Offen war der volle Testlauf** — dort sind Fehlschläge in Bestandstests zu erwarten,
die bisher eine Handpassung durch eine Automatikpassung ersetzt haben. Jeden einzeln ansehen,
keinen löschen.

Danach `docs/superpowers/plans/2026-08-30-ground-chart-overlay.md`, soweit die Zeit reicht.

## Rahmen

- **Arbeitszweig:** `aip-ground-charts`. `main` steht auf `origin/main` und soll dort bleiben,
  bis bewusst gemerged wird.
- **Deploy nach `main` ist erlaubt.** Bedingung des Nutzers: der generelle Serverbetrieb darf
  nicht gefährdet werden. Konkret heißt das:
  - Voller Testlauf grün, bevor gemerged wird (Stand vor diesem Vorhaben: 2042 PASS).
  - Nach dem Deploy prüfen, dass der Container läuft und `/api/health` antwortet.
  - **Vor und nach dem Deploy** zählen: `SELECT quelle, status, COUNT(*) FROM aip_charts
    GROUP BY 1,2;` — es müssen 171 Zeilen mit `quelle='hand'` bleiben. Sinkt die Zahl, ist
    die Sperre undicht: sofort zurückrollen.
  - Die Datenbank vorher sichern: `/opt/friesenspy/data/friesenspy.db` nach
    `/root/aip-schutz-backup-2026-08-31/`.
- **Aufgabe 8 zuletzt.** Sie weckt den Auffrischlauf, der 446 Karten anfasst und über 1000
  Abrufe gegen `aip.dfs.de` macht. Ohne Aufgabe 1 bis 7 täte er genau das, was der Nutzer
  verboten hat.
- Keine Rückfragen. Entscheidungen selbst treffen und im Schlussbericht mit den verworfenen
  Alternativen begründen.

## Schutzregeln, die weiter gelten (aus CLAUDE.md)

- `/opt/mailserver/mail-data/`, `/opt/mailserver/config/`, die Nextcloud-Datenbank und alle
  `.env`/`config.env` werden nicht angefasst.
- `docker image prune -a` ist auf dieser Maschine verboten.
- `claude-remote.service` nicht neu starten, nicht rebooten — das beendet alle Sitzungen.
- Vor destruktiven Aktionen in `/opt` nachfragen. Da der Nutzer schläft heißt das: nicht tun.

## Schlussbericht

Am Ende in den Chat, nicht nur in eine Datei:

1. Was umgesetzt und deployt wurde.
2. **Kritische Themen** — was schiefgehen kann, was ich nicht prüfen konnte.
3. **Jede eigene Entscheidung mit der verworfenen Alternative**, damit der Nutzer gezielt
   korrigieren kann statt alles nachzulesen.
