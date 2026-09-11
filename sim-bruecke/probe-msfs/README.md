# Probeflug: Lässt sich ein SimObject zur Laufzeit setzen?

**Das ist das Tor.** Klappt es, bauen wir den FriesenKieker. Klappt es nicht, lassen wir es —
so hat der Nutzer am 11.09.2026 entschieden. Alles andere in der
[Spec](../../docs/superpowers/specs/2026-09-11-friesenkieker-design.md) wartet darauf.

Läuft auf dem **Windows-Rechner mit dem Simulator**, nicht auf dem Server.

---

## Was geprüft wird

Ob `SimConnect_AICreateSimulatedObject` ein mitgeliefertes Boot an eine frei gewählte
Koordinate setzt — ohne Szenerie-Paket, ohne Neustart, im laufenden Flug.

Boote, weil MSFS sie als SimObjects mitbringt: **kein 3D-Modell nötig, keine Lizenzfrage,
kein Blender.** Wenn der Weg trägt, trägt er später auch Robben; wenn nicht, hat er keine
Modellierungsarbeit gekostet.

## Vorbereitung

Gebraucht wird `SimConnect.dll`. Drei Wege, der erste ist der einfachste:

1. Die DLL **neben dieses Skript legen** — dann sucht das Skript nicht.
2. Das MSFS-SDK installieren (dann findet das Skript sie über `%MSFS_SDK%`).
3. `--dll <pfad>` angeben.

Die DLL liegt beim SDK unter `SimConnect SDK\lib\SimConnect.dll`. **Nicht** die alte
FSX-DLL nehmen (die aus `GAC_32`, Version 10.0.61355.0) — die kennt
`AICreateSimulatedObject` in dieser Form nicht. Das ist genau die DLL-Verwechslung, die im
Repo `FSEconomy-SimConnect-Stub` schon einmal für Verwirrung gesorgt hat.

## Schritt 1 — echte Container-Titel holen

Einen Titel zu raten ist sinnlos; sie unterscheiden sich zwischen MSFS 2020 und 2024. Sie
stehen im Klartext auf der Platte:

```
py kieker_probe.py --titel-suche
```

Das durchsucht die `SimObjects`-Ordner nach `sim.cfg` und zeigt alle Titel, die nach Booten
aussehen. Dauert ein paar Minuten (es läuft über die Laufwerke). Schneller geht es von Hand:

```
...\Packages\Official\...\SimObjects\Boats\<irgendwas>\sim.cfg
```

Dort ist die Zeile `title = ...` der gesuchte Wert.

## Schritt 2 — Flug laden, dann setzen

**Ein Flug muss geladen sein**, das Hauptmenü reicht nicht. Am besten irgendwo in
Ostfriesland, damit der nächste Schritt kurz ist.

```
py kieker_probe.py --titel "<der gefundene Titel>"
```

Standardziel ist die **Kachelotplate** (53,66 N / 6,98 O) — Sandbank westlich von Juist,
flach, frei, von EDWR/EDWG gut anzufliegen. Mit `--lat` / `--lon` beliebig anders.

## Schritt 3 — hinsehen

**Die Objekt-ID beweist noch nichts.** Der Simulator kann ein Objekt anlegen und trotzdem
nichts zeichnen. Also per Slew oder im Anflug hin und nachsehen:

- Liegt das Boot da?
- Liegt es nach zwei Minuten **immer noch** da? (Manche Objekte räumt die KI wieder ab.)
- Steht es auf dem Wasser oder im Wasser?

## Was welches Ergebnis bedeutet

| Ausgabe | Bedeutung | Dann |
|---|---|---|
| `ERFOLG: Objekt-ID …` **und sichtbar** | Der Weg trägt. | Kieker bauen |
| `ERFOLG` aber **nichts zu sehen** | angelegt, nicht gezeichnet | Höhe/OnGround/Kategorie probieren |
| `EXCEPTION 7 — NAME_UNRECOGNIZED` | Titel falsch | Schritt 1 wiederholen |
| `EXCEPTION 28/29 — OBJECT_CONTAINER/OBJECT_AI` | Sim lehnt die Erzeugung ab | ernst; vermutlich Kategorie |
| `KEINE ANTWORT` | Aufruf verpufft folgenlos | eigener Befund, bitte melden |
| `SimConnect_Open ging nicht durch` | kein Flug geladen oder falsche DLL | Vorbereitung prüfen |

**Die wichtigste Zeile des Skripts ist die Warteschleife.** `AICreateSimulatedObject` meldet
fast immer Erfolg; ob wirklich etwas entstanden ist, kommt erst danach als
`ASSIGNED_OBJECT_ID` oder `EXCEPTION` zurück. Ohne dieses Nachfassen ginge ein
fehlgeschlagener Probeflug als „hat geklappt" durch.

## Ehrlicher Hinweis

Dieses Skript ist auf dem Linux-Server geschrieben und **dort nie gelaufen** — es gibt hier
weder Windows noch MSFS noch `SimConnect.dll`. Es ist nach der offiziellen Signatur gebaut und
meldet bei jedem Schritt, was es tut; ein Fehlschlag ist deshalb auswertbar. Die
RECV-Nummern (1 = EXCEPTION, 2 = OPEN) sind gegen die eigenen Wireshark-Messungen in
`FSEconomy-SimConnect-Stub/PROTOCOL_NOTES.md` gegengeprüft, die übrigen Enum-Werte stammen aus
dem SDK und sind ungeprüft — deshalb gibt das Skript unbekannte Nummern **roh** aus, statt sie
zu verschweigen.

Wenn etwas klemmt: Ausgabe herschicken, dann repariere ich das Skript statt zu raten.
