# Offene Aufgaben

Vom Nutzer vorgemerkt, noch nicht begonnen. **Diese Liste ist kein Ideenspeicher** — was hier
steht, ist gewollt; was erledigt ist, wird gelöscht (die Geschichte steht im Changelog).

Am Projekt arbeiten mehrere Sitzungen parallel, auch in der Cloud. Vor dem Start also pullen
und prüfen, ob eine andere die Aufgabe schon erledigt hat.

**Beide Aufgaben unten sind spezifiziert** und sollen in **einer** Version geliefert werden
(Vorschlag v13.7.0): [`superpowers/specs/2026-08-16-mithoeren-und-meldepunkte-design.md`](superpowers/specs/2026-08-16-mithoeren-und-meldepunkte-design.md).
Dort steht auch, was vor der Umsetzung noch zu klären ist (OpenAIP-Schlüssel, Länderumfang).

## 1. Mithören über `listen.vatsim.net`

Ein kleines **Lautsprechersymbol hinter dem Callsign in der Live-Ansicht**, das auf
`https://listen.vatsim.net/live/<CALLSIGN>` zeigt — dort läuft die Frequenz, auf der der Pilot
gerade ist. Vorbild ist [vatsim-radar.com](https://vatsim-radar.com), dort sitzt es neben der
COM1-Frequenz mit dem Titel „Listen as \<Callsign\>" (Nutzer, 16.08.2026).

Beim Umsetzen beachten:

- **Im Kniebrett nicht anzeigen.** Ein externer Link ist dort nutzlos: Das EFB-Panel hat
  keinen Browser, in den er sich öffnen ließe. Die Wache dafür ist
  `document.documentElement.classList.contains('vr-panel')`.
- Blau (`--green`) ist in diesem Projekt Klickbarem vorbehalten — hier also richtig, das
  Symbol *ist* ein Link. Das Callsign selbst bleibt neutral.
- Ziel in einem neuen Tab öffnen (`target="_blank"` mit `rel="noopener"`).
- Ob der Stream für jeden Piloten existiert, ist ungeprüft. Ein toter Link ist verschmerzbar;
  ein Symbol, das nie funktioniert, wäre es nicht — bei Gelegenheit an einem Friesen
  ausprobieren.

## 2. VRP aus OpenAIP größer und prominenter darstellen

Die visuellen Meldepunkte (VRP) des OpenAIP-Layers sind zu klein und zu unauffällig
(16.08.2026).

Zu beachten: OpenAIP kommt als **Kachel-Layer** — die Darstellung einzelner Punktarten lässt
sich darin nicht ohne Weiteres ändern. Vor der Umsetzung prüfen, ob die VRP über eine eigene
Quelle zu bekommen sind (OpenAIP-API) und als eigene Ebene darübergelegt werden müssen. Das
ist mehr Arbeit als eine Stilanpassung — vorher mit dem Nutzer abstimmen.
