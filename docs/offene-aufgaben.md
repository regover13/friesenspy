# Offene Aufgaben

Vom Nutzer vorgemerkt, noch nicht begonnen. **Diese Liste ist kein Ideenspeicher** — was hier
steht, ist gewollt; was erledigt ist, wird gelöscht (die Geschichte steht im Changelog).

Am Projekt arbeiten mehrere Sitzungen parallel, auch in der Cloud. Vor dem Start also pullen
und prüfen, ob eine andere die Aufgabe schon erledigt hat.

---

## Sichtflugkarte: eigener Zugriff statt Umweg über die FSE-Plätze (24.08.2026)

Das „🗺️ Sichtflugkarte festnageln" sitzt zurzeit im Popup der **FSE-Plätze**. Das ist falsch
verkoppelt: FSEconomy hat mit den DFS-Blättern nichts zu tun, und wer die Sichtflugkarte
sehen will, muss eine sachfremde Ebene einschalten, um an den Knopf zu kommen. Der Nutzer hat
das am 24.08.2026 deutlich beanstandet — zum Testen bleibt es vorerst stehen.

Warum es dort gelandet ist: Die Spec sagt „im Platz-Popup", und das einzige Platz-Popup, das
die Karte kennt, ist `_fsePopup`. Es gibt keinen zweiten Flugplatz-Marker.

**Die Ebene muss ihren eigenen Zugriff mitbringen.** Naheliegend: Solange sie eingeschaltet
ist, trägt sie für jedes gepasste Blatt eine kleine Marke an der Feldmitte, beschriftet mit
dem ICAO; ein Klick nagelt fest, ein zweiter gibt frei. Damit ist die Ebene auch ohne
Sim-Position bedienbar und man sieht auf einen Blick, wo es überhaupt Blätter gibt.

Zu klären, bevor jemand anfängt:

- **Ab welchem Zoom?** Bei 446 Blättern wären es sonst 446 Marken auf der Deutschlandkarte.
  Vorbilder mit demselben Problem sind `_fsePlaetzeZoomWache` und `_vrpZoomWache`.
- **Bleiben die Marken sichtbar, während ein Blatt liegt?** Dafür spricht das Umschalten auf
  den Nachbarplatz, dagegen, dass sie auf dem Blatt liegen und es zukleistern.
- Ist das gebaut, gehört die Zeile aus `_fsePopup` wieder heraus — samt
  `test_platz_popup_wird_erst_beim_oeffnen_gebaut`, das nur ihretwegen existiert.

Spec: [`superpowers/specs/2026-08-23-aip-karten-overlay-design.md`](superpowers/specs/2026-08-23-aip-karten-overlay-design.md), Abschnitt 6.

---

Die beiden Einträge vom 16.08.2026 — Mithören über `listen.vatsim.net` und größere Meldepunkte
— sind mit **v13.7.0** erledigt. Warum es so gebaut ist, wie es gebaut ist, steht in
[`superpowers/specs/2026-08-16-mithoeren-und-meldepunkte-design.md`](superpowers/specs/2026-08-16-mithoeren-und-meldepunkte-design.md);
was der Nutzer davon sieht, im Changelog.
