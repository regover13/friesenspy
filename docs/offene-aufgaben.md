# Offene Aufgaben

Vom Nutzer vorgemerkt, noch nicht begonnen. **Diese Liste ist kein Ideenspeicher** — was hier
steht, ist gewollt; was erledigt ist, wird gelöscht (die Geschichte steht im Changelog).

Am Projekt arbeiten mehrere Sitzungen parallel, auch in der Cloud. Vor dem Start also pullen
und prüfen, ob eine andere die Aufgabe schon erledigt hat.

## 1. Klick auf `listen.vatsim.net`

Aus der Oberfläche heraus zu [listen.vatsim.net](https://listen.vatsim.net) verlinken, um
mitzuhören.

**Vor der Umsetzung klären:** Von wo aus der Klick gehen soll — Controller-Eintrag, Callsign,
Live-Tab? Der Auftrag lautete nur „Klick auf listen.vatsim.net" (16.08.2026); der Ort ist
offen. Nicht raten, sondern nachfragen.

## 2. VRP aus OpenAIP größer und prominenter darstellen

Die visuellen Meldepunkte (VRP) des OpenAIP-Layers sind zu klein und zu unauffällig
(16.08.2026).

Zu beachten: OpenAIP kommt als **Kachel-Layer** — die Darstellung einzelner Punktarten lässt
sich darin nicht ohne Weiteres ändern. Vor der Umsetzung prüfen, ob die VRP über eine eigene
Quelle zu bekommen sind (OpenAIP-API) und als eigene Ebene darübergelegt werden müssen. Das
ist mehr Arbeit als eine Stilanpassung — vorher mit dem Nutzer abstimmen.
