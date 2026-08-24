# Release 14.0.0 — „Zettelwirtschaft" (veröffentlicht 24.08.2026)

Der Name kommt vom Nutzer (24.08.2026) und ist Selbstironie: Wir haben Bildanalyse,
Gradnetz-Vermessung und eine vierstufige Prüfkette gebaut, um am Ende **Papier** ins Cockpit
zu legen — und 169 der 446 Blätter liegen noch von Hand nach.

**`highlight: true` ist hier zulässig**, weil der Nutzer es ausdrücklich vergeben hat
(„Erstelle die Version V14 als Highlight"). Das ist die einzige gültige Herkunft dieser Marke;
ohne seine Ansage bleibt sie `false`.

**`banner_version` wurde dafür von `off` auf `auto` zurückgestellt** — ohne das bliebe auch
dieses Release stumm, s. den Abschnitt unten.

---

# Release 13.9.0 — Entwurf, noch nicht veröffentlicht

**Status:** wartet auf die Abnahme durch den Nutzer. Der Eintrag steht bewusst **nicht** in
`app/CHANGELOG.json` — solange er dort fehlt, bleibt die ausgelieferte Version **13.8.2** und
es erscheint kein Changelog-Banner. Der Code der Sichtflugkarten ist trotzdem enthalten und
lässt sich in Ruhe ausprobieren.

**`"highlight": true`** ist hier gesetzt, weil der Nutzer es am 23.08.2026 ausdrücklich
vergeben hat („Highlight ja"). Das ist die einzige zulässige Herkunft dieser Marke; ohne
seine Ansage bleibt sie `false`.

## Stand 24.08.2026 — die Nummer ist vergeben, die Ankündigung nicht

**13.9.0 ist ausgeliefert**, aber als stumme Zwischenversion: Der Changelog-Eintrag nennt die
Sichtflugkarten ausdrücklich nicht, `highlight` ist `false`, und die App-Einstellung
`banner_version` steht auf **`off`** — es erscheint also gar kein Banner.

Grund für die Nummer war nicht das Release, sondern der Panel-Cache: Der Kachel-Buster hing an
der Versionsnummer, und die stand einen ganzen Tag unverändert auf 13.8.2, während mehrfach
deployt wurde. Im Kniebrett kam dadurch keine Änderung an. Seither hängt der Kennwert
zusätzlich am Hash der ausgelieferten `index.html`; die Versionsnummer allein trägt das nicht.

**Wichtig beim nächsten echten Release:** `banner_version` muss im Admin zurück auf `auto`,
sonst bleibt auch die nächste Ankündigung stumm.

## Nach der Abnahme

Diesen Block als **ersten** Eintrag in `app/CHANGELOG.json` einfügen — dann springt die
Version auf 13.9.0 und das Banner erscheint bei allen Nutzern:

```json
{
 "version": "13.9.0",
 "date": "2026-08-23",
 "highlight": true,
 "title": "Sichtflugkarten als Karten-Overlay",
 "items": [
  "🗺️ Neue Karten-Ebene „Sichtflugkarte“: Die amtliche DFS-Sichtflugkarte des Flugplatzes liegt halbtransparent über der Karte, und dein Flugzeug bewegt sich darauf — in der Weboberfläche wie im Kniebrett. Sie blendet sich von selbst ein, sobald du im Kartenfeld eines Platzes bist, und wieder aus, wenn du weg bist.",
  "📄 Gezeigt wird das ganze Blatt, nicht nur der Kartenausschnitt — Frequenzen, Platzrunden­höhen und Hinweise bleiben lesbar.",
  "🎯 Die Georeferenzierung rechnet der Server selbst aus Kartenrahmen und Gradnetz. Vier voneinander unabhängige Prüfungen entscheiden, ob eine Karte angezeigt wird; besteht eine davon nicht, bleibt die Karte aus. Eine Karte, die falsch liegt, wäre schlimmer als gar keine.",
  "🛠️ Im Admin lassen sich Karten von Hand passen, die die Automatik nicht schafft — mit Vorschau über der echten Karte, bevor gespeichert wird.",
  "ℹ️ Die Karten stammen von der DFS und sind urheberrechtlich geschützt; sie sind nur angemeldeten Mitgliedern zugänglich."
 ]
}
```

Vor dem Einfügen prüfen, ob das Datum noch stimmt.
