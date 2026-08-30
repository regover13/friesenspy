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

**Wenn Plan B die Ausbeute nicht hebt** (heute 2 von rund 10 Blättern unter 15 m), wird er
trotzdem vollständig gebaut — die Prüfkette weist schlechte Passungen ab, es erscheint dann
eben nur für wenige Plätze eine Karte. Das ist kein Grund anzuhalten, gehört aber in den
Schlussbericht mit der gemessenen Quote.



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
