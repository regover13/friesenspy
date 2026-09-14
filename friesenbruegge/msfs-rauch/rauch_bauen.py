"""Erzeugt die FriesenBrügge-Rauchsäulen für MSFS 2020/2024 — sechs Farben, eigenes Werk.

Das Gegenstück zu ../xplane/rauch_bauen.py. Gleicher Zweck, gleiche Farben, anderes Format.

WARUM SELBST GEBAUT
===================

Am 13.09.2026 im laufenden MSFS 2024 alles geprüft, was es von der Stange gibt:

| Titel | | |
|---|---|---|
| `SIAI_VFX_Smoke_Red` | eine **Wand** über mehrere hundert Meter | und SayIntentions-Abo |
| `Smoke_Volcano` | weiße **Halbkugel**, rund 100 m | Bordmittel, aber unbrauchbar |
| `VfxSpawner` | wird angenommen, zeichnet **nichts** | |
| `ESD_Env_Smoke_Chimney_Small` | grauer Schornstein — und nur **unter 10 °C** | Emerald |
| `item_flare_*` | kompakte Farbwolken, vier Farben | Campout, muss installiert sein |

Keines ist eine Signalsäule, und **mitliefern darf man keines**: Emerald verbietet es wörtlich
(*„refrain from packaging it with your add-on"*), SayIntentions hängt am Abo, Campout ist ein
Fremdpaket. Also bauen wir sie selbst — wie für X-Plane schon geschehen.

DASS DAS GEHT, IST DER FUND DES TAGES
=====================================

Ein MSFS-Partikeleffekt sieht aus wie eine kompilierte Binärdatei (`.spb`), und danach hatte
es ausgesehen, als bräuchte es den Visual-Effects-Editor im DevMode — also Klickarbeit, die
ich nicht leisten kann. Das SDK bringt aber ein Beispielprojekt mit, und dort liegt die
**Quelle**:

    Samples/DevmodeProjects/Misc/SimpleFX/.../EngineSmoke.xml
    Samples/DevmodeProjects/SimObjects/Aircraft/WasmAircraft/.../smoke.xml

Beide sind lesbares XML, und `fspackagetool.exe` macht daraus die `.spb`. Das Format ist ein
Knotengraph: Jeder Knoten hat eine GUID, und Werte werden über GUID-Verweise verdrahtet
(`{GUID}, vorgabewert` — die Null-GUID heißt „keine Verbindung, nimm die Zahl").

Alles, was die X-Plane-Säule ausmacht, hat hier eine Entsprechung:

| X-Plane `.pss` | MSFS-XML |
|---|---|
| `TIME_TO_LIVE` | `ParticleLifetime` |
| `EMIT_RATE` | `ParticleRate` |
| `MAX_PARTICLES` | `Capacity` |
| `TINT` | `Vector4` → `ParticleColor` |
| `ALPHA_CURVE` | `GetBezierCurve` auf `AgeOverLifetime` → `w` des `Vector4` |
| `GRAVITY_CURVE` (negativ) | `GravityVector` mit `GravityScale` −1 |
| Streuung (Min/Max-Spalten) | `RandomValue` |
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

import defusedxml.minidom

HIER = Path(__file__).resolve().parent
QUELLEN = HIER / "PackageSources"
DEFINITIONEN = HIER / "PackageDefinitions"

# Dieselben sechs Farben wie in X-Plane -- vier aus dem FriesenFlieger-Repaint-Kit, zwei
# Signalfarben. Der Server fordert eine FARBE an und muss sich darauf verlassen können, dass
# jeder Pilot sie sieht, gleich in welchem Simulator (PROTOKOLL.md, Abschnitt 3).
FARBEN = {
    "navy":         (0x19, 0x1D, 0x53),
    "hellblau":     (0x8F, 0xBF, 0xF1),
    "rot":          (0x8A, 0x1B, 0x1B),
    "orange":       (0xD7, 0x5F, 0x28),
    "signalrot":    (0xE3, 0x06, 0x13),
    "signalorange": (0xFF, 0x6A, 0x13),
}

# Die Werte stammen aus dem X-Plane-Durchgang vom 13.09.2026, bei dem zehn Anläufe nötig
# waren. Übertragen, nicht neu erfunden:
# ⭐⭐ AB HIER SIEHT MAN DIE SAEULE -- UND DAS WAR DIE GANZE SUCHE VOM 14.09.2026.
#
# `MaxDistanceEmission` ist laut SDK-Doku das EINZIGE Feld, das die Sichtweite eines
# Partikeleffekts steuert:
#
#   "Once the camera exceeds this distance from the emitter, particles will stop being
#    created."   Standardwert: 2000 Meter.
#
# Wir haben es nie gesetzt, also galt die Vorgabe. Der Nutzer mass **1830 m** (6000 ft) --
# die Zahl passt, und sie erklaert, warum DREI andere Versuche nichts brachten:
#
#     minSize="0" im LOD                 regelt die Bildschirmgroesse des MODELLS
#     DistanceToNotAnimate=15000         regelt die Animation, nicht das Spawnen
#     Traeger 2 m -> 90 m -> 300 m       half nur von 100 m auf 1830 m (das Objekt selbst
#                                        war zu klein), darueber nichts
#
# Die 90 m Traegerhoehe bleiben noetig (bei 2 m verschwand das OBJEKT), aber die Schranke
# lag danach im Partikelsystem.
#
# ⚠ WAS ES KOSTET, IST UNGEMESSEN: Ein Emitter, der aus 15 km noch spawnt, laeuft auch
# dann, wenn ihn niemand ansieht. Bei einer Handvoll Baaken ist das vertretbar; bei
# hundert gesetzten Objekten gehoert es gemessen (s. MESSLISTE).
#
# Der Nutzer wollte 10 km. 15000 laesst Luft.
# ⚠ MESSREIHE, NOCH NICHT ABGESCHLOSSEN (14.09.2026):
#
#     eingestellt   wirksam
#      2000 (Vorgabe)  1830 m   passt 1:1
#     15000            6480 m   nur 43 %  <- unerklaert
#     50000            ?        <- dieser Versuch
#
# Bleibt es bei 6480 m, gibt es eine harte Schranke, die die Doku nicht nennt. Waechst es
# mit, wirkt der Wert -- nur nicht linear, und dann laesst sich der Faktor ausrechnen.
MAX_SICHT_M = 50000.0

LEBENSDAUER_S = 30.0
# Am 14.09.2026 von 22 auf 30 gesetzt -- Nutzerentscheidung im Flug, nachdem er beide
# Fassungen gesehen hatte: "ich finde xplane zu gross und msfs zu klein". X-Plane ging im
# selben Zug von 45 herunter. Keine der beiden war die Referenz; beide bewegten sich.
#
# ES WAR EINE ZEILE: Hoehe, Rate, Kapazitaet, Kegelbreite und Endgroesse werden unten aus
# LEBENSDAUER_S und AUFTRIEB_MS GERECHNET -- genau dafuer wurden sie damals abgeleitet.
# Die Saeule wuchs damit von 66 auf 90 m, die Endgroesse von 8,8 auf 12,0 m, die Kapazitaet
# von 907 auf 1237. Die Rate blieb, weil Hoehe und Lebensdauer proportional wachsen.
#
# ⚠ NOCH NICHT IM SIM GESEHEN, UND ES IST EINE LEISTUNGSFRAGE. Die 22 s waren seinerzeit
# eine Leistungsentscheidung -- MSFS-Partikel sind teurer als X-Plane-Partikel, und 30 s
# heissen 36 % mehr gleichzeitige. Ob das traegt, sagt nur der Simulator; das steht in
# friesenbruegge/MESSLISTE.md fuer den naechsten Termin.
# ⚠ DREI GRÖSSEN HÄNGEN AM AUFTRIEB -- SIE WERDEN DESHALB GERECHNET, NICHT EINGETRAGEN.
#
# Das war am 13.09.2026 dreimal hintereinander die Fehlerquelle: Der Auftrieb wurde auf
# Zuruf geändert (zu schnell -> 1,8, dann wieder zurück auf 3,0), und jedes Mal blieben
# Dichte, Kegelbreite und Endgröße auf ihren alten Zahlen stehen. Ergebnisse im Sim: ein
# Fächer über den halben Himmel, dann ein massiver Ball. Beides war nicht "zu wenig
# getunt", sondern schlicht nicht nachgezogen.
#
# Die Säulenhöhe ist `Auftrieb x Lebensdauer`. Daran hängen:
#
#   Dichte je Meter   = Rate x Lebensdauer / Höhe      -> also die RATE
#   Kegelbreite       = tan(11 Grad) x Auftrieb        -> X-Planes INITIAL_PITCH
#   Endgröße          = 0,133 x Höhe                   -> X-Planes 18 m auf 135 m Säule
#
# Wer den Auftrieb ändert, ändert damit automatisch alle drei. Was von Hand bleibt, ist
# nur noch die gewünschte Dichte -- und die ist eine Geschmacksfrage, keine Ableitung.
AUFTRIEB_MS = 3.0         # wie X-Plane (Nutzer, 13.09.2026: "lass es bei 3m")
AUFTRIEB = -AUFTRIEB_MS   # negativer GravityScale = von der Erde weg

_HOEHE_M = AUFTRIEB_MS * LEBENSDAUER_S          # 90 m
DICHTE_JE_M = 11.0        # Partikel je Höhenmeter -- der einzige freie Regler
RATE = DICHTE_JE_M * _HOEHE_M / LEBENSDAUER_S   # Partikel je Sekunde
KAPAZITAET = RATE * LEBENSDAUER_S * 1.25        # mit Luft nach oben

GROESSE_START_M = 0.8     # an der Quelle -- eine Rauchpatrone, kein Krater
GROESSE_ENDE_M = 0.133 * _HOEHE_M               # oben, wo sich die Krone auflösen soll

# Die Kegelbreite: X-Plane streut über `INITIAL_PITCH` um ±11 Grad. Als seitliche
# Geschwindigkeit ist das tan(11 Grad) mal dem Auftrieb -- steigt die Säule schneller,
# darf sie auch breiter streuen, ohne dass der Kegel flacher wird.
SEIT_STREU_MS = 0.194 * AUFTRIEB_MS

# ⚠ OHNE STREUUNG WIRD JEDE RAUCHSÄULE EIN TRICHTER. Genau das war am 13.09.2026 im Sim zu
# sehen: glatte, schnurgerade Kanten und ein zusammenhängender Schlauch statt einzelner
# Wolken ("sieht aus wie ein Trichter"). Der Grund ist rein rechnerisch: Wenn ALLE Partikel
# gleich lange leben, gleich schnell steigen und gleich groß sind, muss daraus eine
# geometrisch exakte Form entstehen.
#
# Die X-Plane-Fassung streut deshalb vier Größen (Min/Max-Spalten in der .pss); beim
# Übertragen nach MSFS hatte ich nur die seitliche mitgenommen. Dieselben Verhältnisse:
#
#     TIME_TO_LIVE   0,55 bis 1,0   -- manche Wolken lösen sich früher auf
#     INITIAL_SPEED  0,5  bis 1,8   -- die Front zerfasert, statt geschlossen zu steigen
#     INITIAL_SIZE   0,8  bis 1,2   -- ungleiche Ballen statt gleichförmiger Perlen
#
# In MSFS macht das `RandomValue` je Partikel, angestoßen über die Partikelnummer (`id`).
LEBEN_MIN_F = 0.55        # Anteil der Lebensdauer, kürzestes Partikel
LEBEN_MAX_F = 1.00
STEIG_MIN_F = 0.50        # Anteil des Auftriebs, langsamstes Partikel
STEIG_MAX_F = 1.80
GROESSE_MIN_F = 0.80      # Anteil der Größe, kleinstes Partikel
GROESSE_MAX_F = 1.20


# ⚠ OHNE DIESEN WERT HÖRT DER EMITTER NIE AUF. Die SDK-Doku ist da eindeutig: Fehlt
# `TimeEmission`, gilt -1 -- "no time limit on emission, the emitter will spawn particles
# indefinitely". Genau das ist passiert: Objekt über den Spawner gelöscht, Rauch blieb
# stehen und wuchs weiter; erst ein kompletter Neustart des Flugs wurde ihn los.
#
# Der Grund, warum das Löschen nicht hilft, steht ebenfalls in der Doku: Ein Effekt wird
# gestoppt, wenn seine FX_CODE-Bedingung FALSCH wird. Ist das Trägerobjekt weg, wird gar
# nichts mehr ausgewertet -- der einmal gespawnte Emitter läuft herrenlos weiter.
# `TimeEmission` ist die einzige Schranke, die auch ohne Objekt noch greift.
#
# ⚠ DIESE ZAHL IST EIN KOMPROMISS, KEINE LÖSUNG -- und sie schneidet in beide Richtungen:
# Sie ist zugleich die Brenndauer einer stehenden Säule UND die Nachlaufzeit nach dem
# Abräumen. Kurz heißt "schnell weg", aber auch "hört von selbst auf, obwohl das Objekt
# noch steht". 300 s waren zu lang (Nutzer, 13.09.2026: "wenn weg, dann weg").
#
# Sauber wird das erst, wenn die Brügge ein Objekt, das stehen bleiben soll, regelmäßig
# ERNEUERT -- dann darf die Brenndauer kurz sein, ohne dass die Markierung ausgeht. Das
# ist ein Eingriff in bruegge.cpp und noch nicht gebaut.
#
# EINE MINUTE. Sobald die Brügge erneuert, ist diese Zahl nur noch die Obergrenze für den
# NACHLAUF einer herrenlosen Säule -- und der soll kurz sein ("wenn weg, dann weg").
# Wie lange eine gewollte Markierung steht, hängt nicht mehr hier dran: Die Brügge setzt
# das Objekt rechtzeitig vor Ablauf neu (s. `RAUCH_ERNEUERN_S` in ../msfs/bruegge.cpp),
# und zwar so lange, wie der Server es verlangt -- gebraucht werden sie meist zwei Stunden.
BRENNDAUER_S = 30.0       # nur noch der Nachlauf, nicht die Standzeit

# Ein fester Namensraum, damit aus demselben Namen immer dieselbe GUID wird. Ohne das
# bekäme jeder Lauf neue GUIDs, und ein Paket-Update zerrisse die Verweise: Die
# Behaviour-Datei des SimObjects verweist den Effekt über genau diese Zahl.
NAMENSRAUM = uuid.UUID("7f3c1a90-5b2e-4d61-9a77-af8e5c000001")


def guid(*teile: str) -> str:
    return "{" + str(uuid.uuid5(NAMENSRAUM, "|".join(teile))).upper() + "}"


NULL = "{00000000-0000-0000-0000-000000000000}"

# Stützstellen der Größenkurve als (Alter 0..1, Anteil an der Spanne 0..1). Bewusst flach
# am Anfang: die ersten Meter bleiben schmal, damit eine Säule entsteht und keine Kugel.
_GROESSE_STUETZEN = ((0.00, 0.00), (0.15, 0.08), (0.40, 0.29), (0.70, 0.62), (1.00, 1.00))

# ⚠ DIESE ZAHLEN SIND ABGENOMMEN -- NICHT NEU ERFINDEN, NICHT "GLÄTTEN".
#
# Sie stammen 1:1 aus der X-Plane-Fassung, die nach zehn Anläufen freigegeben wurde
# ("ja, das gefällt jetzt!!"). Beim Übertragen nach MSFS hatte ich sie eigenmächtig
# abgeflacht, und genau das fiel im Sim auf: bei Alter 0,42 stand 0,16 statt 0,06, bei
# 0,68 dann 0,05 statt 0,018 -- fast dreifache Dichte über die ganze obere Säule, und die
# Stützstelle bei 0,88 fehlte ersatzlos. Die Krone löste sich dadurch nicht auf.
#
# Die Kurve ist absichtlich steil: dicht im ersten Fünftel, damit die Quelle ortbar ist,
# und danach rasch fallend, damit sich der Rauch nach oben verliert.
#
# Gegenüber X-Plane sind die beiden unteren Werte leicht gesenkt (0,70 → 0,58 und
# 0,50 → 0,42): Dieselbe Zahl trägt in MSFS sichtbar dichter als in X-Plane, und im Sim
# war der Fuß der Säule zu deckend (Nutzer, 13.09.2026: "noch ein wenig zu dicht im
# unteren Bereich"). Der steile Abfall darüber bleibt unangetastet.
_ALPHA_STUETZEN = ((0.00, 0.000), (0.02, 0.580), (0.20, 0.420), (0.42, 0.060),
                   (0.68, 0.018), (0.88, 0.005), (1.00, 0.000))

# ⚠ DER WIND DARF NICHT SOFORT VOLL WIRKEN. Als reine Anfangsgeschwindigkeit addiert,
# bekommt jedes Partikel von Geburt an den ganzen Wind -- die Säule liegt dann schon am
# Boden schräg und bleibt ein dünner Strahl (13.09.2026 bei 30 kt gesehen).
#
# Echter Rauch verlässt die Quelle mit eigenem Impuls und wird erst mit der Zeit vom Wind
# übernommen. Diese Kurve ist genau dieser Übergang: Anteil des Windes am Alter.
#
# Was daraus bei 30 kt (15,4 m/s) gegen 3 m/s Auftrieb wird -- gemessen als Knickwinkel,
# 180° = senkrecht, 90° = waagerecht:
#
#     Alter 0,2 →  5 % Wind → 166°   (Vorgabe: 180-160°)
#     Alter 0,4 → 35 % Wind → 119°
#     Alter 0,6 → 75 % Wind → 105°   (Vorgabe: 100-90° nach drei Fünfteln)
#
# Bei schwächerem Wind knickt sie von selbst weniger und später -- der Windvektor ist
# dann kleiner, die Kurve bleibt dieselbe. Genau das war die Anforderung.
# ⚠ DAS AUFLÖSEN HÄNGT AM ALTER, NICHT AN DER STRECKE -- und daran lag die
# kilometerlange Fahne (13.09.2026 bei 27 kt: "das ist etwa 4-5 Mal zu lang!!").
#
# Ein Partikel lebt 12 bis 22 s. Bei Windstille steigt es darin rund 66 m. Bei 27 kt
# (13,9 m/s) legt es zusätzlich bis zu 305 m WAAGERECHT zurück -- die Alpha-Kurve weiß
# davon nichts und löst stur nach derselben Zeit auf.
#
# Diese Kurve dämpft die Deckkraft nach der tatsächlich zurückgelegten waagerechten
# STRECKE. Damit endet die Fahne bei jedem Wind an derselben Stelle, ohne dass der Effekt
# die Windstärke überhaupt kennen muss (der Weg über GetSimVar ist erprobt und tot, s.
# unten im Knotengraphen).
#
# x ist das QUADRAT der Entfernung, normiert: x = (r / Bezugsweite)^2.
#
#     r =  0 m → 1,00      r = 40 m → 0,25
#     r = 20 m → 0,85      r = 50 m → 0,08
#     r = 30 m → 0,55      r = 60 m → 0,00
# ⚠ DIESE WEITE HAENGT AN DER SAEULENHOEHE UND DARF NICHT FEST STEHEN.
#
# Sie stand auf 60 m, eingestellt bei 22 s Lebensdauer und 66 m Saeulenhoehe -- also auf
# 0,91 x Hoehe. Als die Lebensdauer am 14.09.2026 auf 30 s ging, wuchs die Saeule auf 90 m,
# die Bezugsweite blieb aber stehen. Ein Partikel lebt seither laenger und wird weiter
# getragen, trifft die feste 60-m-Grenze also frueher in seinem Leben:
#
#   bei 10 kt, Alter 0,8      22 s / 60 m Bezug  ->  36 m seitlich, Daempfung 0,38
#                             30 s / 60 m Bezug  ->  49 m seitlich, Daempfung 0,10   (!)
#                             30 s / 82 m Bezug  ->  49 m seitlich, Daempfung 0,39
#
# Die 30-s-Umstellung haette die Windreaktion damit VERSCHLECHTERT -- genau das, was am
# selben Tag als Mangel benannt wurde ("reagiert besser auf den Wind" ueber X-Plane). Das
# war ein uebersehener Nebeneffekt, kein Befund ueber MSFS.
#
# Abgeleitet bleibt das Verhaeltnis erhalten: Die Fahne traegt ungefaehr so weit, wie die
# Saeule hoch ist. Bei starkem Wind bleibt die Begrenzung wirksam (27 kt: Daempfung 0,12
# schon bei Alter 0,6), und genau dafuer wurde sie am 13.09.2026 eingefuehrt -- die Fahne
# war "4-5 Mal zu lang".
STRECKE_BEZUG_M = 0.909 * _HOEHE_M    # so weit traegt die Fahne, dann ist sie verschwunden
_STRECKE_STUETZEN = ((0.000, 1.00), (0.111, 0.85), (0.250, 0.55),
                     (0.444, 0.25), (0.694, 0.08), (1.000, 0.00))


def strecke_kurve() -> str:
    return _kurve(_STRECKE_STUETZEN)


# ⚠ AM 14.09.2026 NACH VORN GEZOGEN -- die Kurve wirkte, wo niemand hinsieht.
#
# Sie stand auf ((0,00; 0,00), (0,20; 0,05), (0,40; 0,35), (0,60; 0,75), (1,00; 1,00)) und
# arbeitete damit gegen die ALPHA_CURVE. Nebeneinandergelegt ist der Widerspruch eindeutig:
#
#   Alter 0,2   Alpha 0,42 (gut sichtbar)   Wind  5 %  ->   5 Grad Neigung bei 10 kt
#   Alter 0,5   Alpha 0,05 (fast weg)       Wind 55 %  ->  43 Grad
#
# Der SICHTBARE Teil der Saeule war genau der, in dem der Wind noch nicht wirkte -- und der
# Teil, der abwehte, war schon verblasst. Im Bild stand die Saeule deshalb senkrecht wie
# gemalt (Screenshot 13:35, 10 kt), waehrend X-Plane sichtbar abwehte.
#
# X-Plane dosiert gar nicht: Dort nimmt der Simulator jedes Partikel sofort in den Wind.
# Die Dosierung hier bleibt trotzdem richtig -- ohne sie lag die Saeule am 13.09.2026 bei
# 30 kt platt am Boden. Sie war nur zu spaet angesetzt: Echter Rauch wird binnen weniger
# Sekunden uebernommen, nicht erst nach der Haelfte seines Lebens.
#
# Jetzt bei 10 kt: 42 Grad statt 5 bei Alter 0,2, also im dichten Teil.
# ⚠ OFFEN BEI STARKEM WIND: Bei 30 kt sind es dort 69 Grad statt 14. Das ist die Richtung,
# in die der alte Fehler lag ("ein duenner Strahl"), und es ist UNGEMESSEN -- der Befund
# vom 14.09. stammt von 10 kt. Steht in friesenbruegge/MESSLISTE.md.
_WINDANTEIL_STUETZEN = ((0.00, 0.00), (0.10, 0.25), (0.25, 0.65), (0.50, 0.90),
                        (1.00, 1.00))


def _kurve(stuetzen) -> str:
    """Stützstellen als Kurvenzeichenkette: je Punkt `x,y,NAN,NAN`."""
    return ",".join(f"{t:.3f},{y:.3f},NAN,NAN" for t, y in stuetzen)


def alpha_kurve() -> str:
    return _kurve(_ALPHA_STUETZEN)


def windanteil_kurve() -> str:
    return _kurve(_WINDANTEIL_STUETZEN)


def groessen_kurve() -> str:
    """Die Stützstellen als Kurvenzeichenkette: je Punkt `x,y,NAN,NAN`."""
    spanne = GROESSE_ENDE_M - GROESSE_START_M
    return ",".join(f"{t:.3f},{GROESSE_START_M + anteil * spanne:.3f},NAN,NAN"
                    for t, anteil in _GROESSE_STUETZEN)


def nach_linear(wert_0_255: int) -> float:
    """Einen sRGB-Farbkanal (0..255) in den linearen Farbraum umrechnen.

    ⚠ OHNE DIESE UMRECHNUNG STIMMT KEINE EINZIGE FARBE. Am 13.09.2026 im Sim: `rauch_navy`
    (#191D53, ein sehr dunkles Marineblau) stand als helles LAVENDEL am Himmel, und alle
    sechs Farben wirkten zu hell und zu wenig gesättigt.

    Der Grund ist der klassische Farbraum-Fehler: Ein Wert aus dem Farbwähler (`#191D53`)
    liegt in sRGB vor, die Renderer rechnen aber intern LINEAR. Einfach durch 255 geteilt
    weiterzureichen, verschiebt jede Farbe nach hell -- und dunkle, gesättigte Töne trifft
    es am stärksten. Navys Blauanteil geht von 0,325 auf 0,087, wird also fast viermal
    dunkler; Weiß dagegen bliebe unverändert.

    Die SDK-Doku sagt zum Farbraum von `ParticleColor` nichts (nachgesehen). Das hier ist
    also der begründete Normalfall, nicht eine dokumentierte Vorschrift -- falls die Farben
    danach zu DUNKEL sind, ist die Umrechnung der erste Verdächtige.

    Formel nach der sRGB-Norm (IEC 61966-2-1).
    """
    c = wert_0_255 / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def kommentar_pruefen(xml_text: str) -> None:
    """Sucht doppelte Bindestriche in XML-Kommentaren und sagt, wo sie stehen.

    ⚠ DREIMAL AM SELBEN TAG HINEINGELAUFEN (13.09.2026), zweimal davon, NACHDEM ich den
    Fehler bereits dokumentiert hatte. Ein `--` ist innerhalb eines XML-Kommentars
    verboten (die Norm erlaubt es nur im schließenden `-->`), und es passiert beim
    Schreiben deutscher Sätze fast von selbst: Der Gedankenstrich sitzt in der Tastatur
    näher als im Bewusstsein.

    Der nackte Parser meldet dazu nur "not well-formed, line 195, column 64" -- richtig,
    aber unbrauchbar, weil die Zeilennummer sich auf die ERZEUGTE Datei bezieht und nicht
    auf die Vorlage im Python-Quelltext. Diese Prüfung nennt stattdessen den Satz.
    """
    for stueck in re.findall(r"<!--.*?-->", xml_text, re.S):
        inneres = stueck[4:-3]
        if "--" in inneres:
            zeile = next(z for z in inneres.splitlines() if "--" in z)
            raise ValueError(
                "Doppelter Bindestrich in einem XML-Kommentar (in XML verboten):\n"
                f"    {zeile.strip()}\n"
                "Ersetze ihn durch Komma, Semikolon oder Doppelpunkt.")


def effekt_xml(name: str, farbe: tuple[int, int, int]) -> str:
    """Ein vollständiger Partikeleffekt als Knotengraph."""
    r, g, b = (nach_linear(k) for k in farbe)
    # Jeder Knoten bekommt seine eigene, aus dem Namen abgeleitete GUID.
    G = {k: guid(name, k) for k in (
        "fx", "emitter", "init", "update", "output", "farbe", "alter", "alpha_kurve",
        "groesse_kurve", "auftrieb", "streu_x", "streu_z", "richtung", "summe",
        "wind", "windanteil_kurve", "wind_dosiert", "summe_wind", "id",
        "leben_rnd", "steig_rnd", "steig_dosiert", "gr_rnd", "groesse_gestreut",
        "pos", "pos_split", "x2", "z2", "r2", "r2_norm", "strecke_kurve",
        "alpha_final")}
    # Und die Ausgangswerte (das, was ein Knoten LIEFERT) brauchen eigene GUIDs.
    W = {k: guid(name, "wert", k) for k in (
        "farbe", "alter", "alpha", "auftrieb", "streu_x", "streu_z", "richtung", "summe",
        "wind", "windanteil", "wind_dosiert", "summe_wind",
        "id", "groesse",
        "leben", "steig_f", "steig_dosiert", "gr_f", "groesse_gestreut",
        "pos", "pos_x", "pos_y", "pos_z", "x2", "z2", "r2", "r2_norm",
        "strecke_f", "alpha_final")}

    return f"""<?xml version="1.0" encoding="UTF-8"?>

<SimBase.Document Type="AceXML" version="1,0">
    <Descr>AceXML Document</Descr>
    <WorldBase.Flight>
        <VisualEffect.VisualEffect InstanceId="{G['fx']}">
            <Name>FrsRauch{name.capitalize()}</Name>
            <EmitterList>
                <ObjectReference InstanceId="{G['emitter']}" id="Emitter"/>
            </EmitterList>
        </VisualEffect.VisualEffect>
        <VisualEffect.Emitter InstanceId="{G['emitter']}">
            <ParticleRate>{NULL}, {RATE:.6f}</ParticleRate>
            <Capacity>{KAPAZITAET:.3f}</Capacity>
            <TimeEmission>{BRENNDAUER_S:.6f}</TimeEmission>
            <MaxDistanceEmission>{MAX_SICHT_M:.6f}</MaxDistanceEmission>
            <ParticleInit>
                <ObjectReference InstanceId="{G['init']}" id="BlockParticleInit"/>
            </ParticleInit>
        </VisualEffect.Emitter>
        <VisualEffect.BlockParticleInit InstanceId="{G['init']}">
            <ParticleUpdate>
                <ObjectReference InstanceId="{G['update']}" id="BlockParticleUpdate"/>
            </ParticleUpdate>
            <ParticleLifetime>
                <FloatIn>{W['leben']}, {LEBENSDAUER_S:.6f}</FloatIn>
            </ParticleLifetime>
            <ParticleSize>
                <FloatIn>{W['groesse_gestreut']}, {GROESSE_START_M:.6f}</FloatIn>
            </ParticleSize>
            <ParticleVelocity>
                <Float3In>{W['summe_wind']}, 0.000000, 0.000000, 0.000000</Float3In>
            </ParticleVelocity>
        </VisualEffect.BlockParticleInit>
        <VisualEffect.BlockParticleUpdate InstanceId="{G['update']}">
            <!-- ⚠ DIE GRÖSSE GEHÖRT HIERHER, NICHT IN DEN INIT-BLOCK. Der Init-Block läuft
                 genau einmal, bei der Geburt des Partikels; eine Kurve über das Alter
                 stünde dort ewig bei Alter 0 und lieferte immer denselben Startwert. Nur
                 der Update-Block wird je Bild neu ausgewertet, so wie die Deckkraft im
                 Output-Block (die deshalb von Anfang an funktioniert hat). -->
            <ParticleSize>
                <FloatIn>{W['groesse_gestreut']}, {GROESSE_START_M:.6f}</FloatIn>
            </ParticleSize>
            <!-- Auch die Geschwindigkeit gehoert hierher, seit der Wind am Alter haengt:
                 Im Init-Block gerechnet, bekaeme jedes Partikel seinen Windanteil ein
                 einziges Mal bei der Geburt, also immer den Wert fuer Alter 0, also
                 nie Wind. Erst hier wird er ueber die Lebenszeit nachgefuehrt. -->
            <ParticleVelocity>
                <Float3In>{W['summe_wind']}, 0.000000, 0.000000, 0.000000</Float3In>
            </ParticleVelocity>
            <ParticleOutput>
                <ObjectReference InstanceId="{G['output']}" id="Output"/>
            </ParticleOutput>
        </VisualEffect.BlockParticleUpdate>
        <VisualEffect.Output InstanceId="{G['output']}">
            <ParticleColor>
                <ColorIn>{W['farbe']}, 0, 0, 0, 0</ColorIn>
            </ParticleColor>
        </VisualEffect.Output>

        <!-- Die Farbe. x/y/z sind Rot/Gruen/Blau, w ist die Deckkraft, und die haengt an
             einer Kurve ueber die Lebenszeit, genau wie ALPHA_CURVE in der .pss. -->
        <VisualEffect.Vector4 InstanceId="{G['farbe']}">
            <OutputValue>{W['farbe']}</OutputValue>
            <x>{NULL}, {r:.6f}</x>
            <y>{NULL}, {g:.6f}</y>
            <z>{NULL}, {b:.6f}</z>
            <w>{W['alpha_final']}, 0.000000</w>
        </VisualEffect.Vector4>

        <!-- Das Alter des Partikels, normiert auf 0..1: die x-Achse aller Kurven. -->
        <VisualEffect.GetParticleAttribute InstanceId="{G['alter']}">
            <OutputValue>{W['alter']}</OutputValue>
            <ParticleAttributeType>AgeOverLifetime</ParticleAttributeType>
        </VisualEffect.GetParticleAttribute>

        <!-- Die Deckkraft ueber die Hoehe. Uebertragen aus der X-Plane-Fassung, wo zehn
             Anlaeufe noetig waren. Unten dicht (die Quelle soll ortbar sein), oben duenn
             (die Krone soll sich aufloesen). Format: x,y,NAN,NAN je Stuetzstelle. -->
        <VisualEffect.GetBezierCurve InstanceId="{G['alpha_kurve']}">
            <OutputValue>{W['alpha']}</OutputValue>
            <FXTime>{W['alter']}, 0.000000</FXTime>
            <Curve>{alpha_kurve()}</Curve>
        </VisualEffect.GetBezierCurve>

        <!-- Die Größe über die Lebenszeit: schmal an der Quelle, weit in der Krone. Sie
             wächst absichtlich erst langsam, denn die unteren Meter sollen eine Säule
             sein, an der man die Quelle orten kann, und keine Kugel. Das Verbreitern
             kommt oben, wo sich der Rauch auflösen soll. Wie SIZE_CURVE in X-Plane.

             ⚠ KEIN DOPPELTER BINDESTRICH IN XML-KOMMENTAREN. Das ist laut XML-Norm
             verboten (nur im schließenden Zeichen erlaubt), und der SPB-Compiler bricht
             hart ab: "Error (line:36): '>' wird erwartet". -->
        <VisualEffect.GetBezierCurve InstanceId="{G['groesse_kurve']}">
            <OutputValue>{W['groesse']}</OutputValue>
            <FXTime>{W['alter']}, 0.000000</FXTime>
            <Curve>{groessen_kurve()}</Curve>
        </VisualEffect.GetBezierCurve>

        <!-- Auftrieb: ein NEGATIVER Schwerkraftfaktor zieht nach oben. -->
        <VisualEffect.GravityVector InstanceId="{G['auftrieb']}">
            <OutputValue>{W['auftrieb']}</OutputValue>
            <GravityScale>{NULL}, {AUFTRIEB:.6f}</GravityScale>
        </VisualEffect.GravityVector>

        <!-- Seitliche Streuung. Ohne sie steigen alle Partikel im Gleichschritt, und die
             Saeule bleibt eine Roehre statt zu zerfasern (13.09.2026 in X-Plane gemessen). -->
        <VisualEffect.GetParticleAttribute InstanceId="{G['id']}">
            <OutputValue>{W['id']}</OutputValue>
            <ParticleAttributeType>id</ParticleAttributeType>
        </VisualEffect.GetParticleAttribute>
        <VisualEffect.RandomValue InstanceId="{G['streu_x']}">
            <OutputValue>{W['streu_x']}</OutputValue>
            <MinRandValue>{NULL}, {-SEIT_STREU_MS:.6f}</MinRandValue>
            <MaxRandValue>{NULL}, {SEIT_STREU_MS:.6f}</MaxRandValue>
            <RandSeed>{NULL}, 1024.000000</RandSeed>
            <RandIndex>{W['id']}, 0.000000</RandIndex>
        </VisualEffect.RandomValue>
        <VisualEffect.RandomValue InstanceId="{G['streu_z']}">
            <OutputValue>{W['streu_z']}</OutputValue>
            <MinRandValue>{NULL}, {-SEIT_STREU_MS:.6f}</MinRandValue>
            <MaxRandValue>{NULL}, {SEIT_STREU_MS:.6f}</MaxRandValue>
            <RandSeed>{NULL}, 512.000000</RandSeed>
            <RandIndex>{W['id']}, 0.000000</RandIndex>
        </VisualEffect.RandomValue>
        <VisualEffect.LocalDirection InstanceId="{G['richtung']}">
            <OutputValue>{W['richtung']}</OutputValue>
            <x>{W['streu_x']}, 0.000000</x>
            <z>{W['streu_z']}, 0.000000</z>
        </VisualEffect.LocalDirection>
        <VisualEffect.AddOperation InstanceId="{G['summe']}">
            <OutputValue>{W['summe']}</OutputValue>
            <xVariant>{W['richtung']}, 0.000000</xVariant>
            <yVariant>{W['steig_dosiert']}, 0.000000</yVariant>
        </VisualEffect.AddOperation>

        <!-- Der Wind. Ohne ihn steht die Säule senkrecht wie gemalt, gleich wie kräftig es
             draußen weht (13.09.2026 im Sim gesehen). `Raw` liefert die Windrichtung
             bereits mit der Windgeschwindigkeit skaliert, in Fuß je Sekunde.

             Er kommt in die ANFANGSgeschwindigkeit, nicht in den Update-Block, und das
             genügt: Bei gleichmäßigem Wind trägt jedes Partikel seinen Anteil von Geburt
             an mit, und die Säule legt sich als Ganzes schräg. -->
        <VisualEffect.WindDirection InstanceId="{G['wind']}">
            <WindDirOptions>Raw</WindDirOptions>
            <OutputValue>{W['wind']}</OutputValue>
        </VisualEffect.WindDirection>

        <!-- Der Anteil, mit dem der Wind am jeweiligen Alter zieht: unten fast null,
             oben ganz. Das ist der Unterschied zwischen einer Säule, die sich neigt,
             und einem Strahl, der von der Quelle an schräg liegt. -->
        <VisualEffect.GetBezierCurve InstanceId="{G['windanteil_kurve']}">
            <OutputValue>{W['windanteil']}</OutputValue>
            <FXTime>{W['alter']}, 0.000000</FXTime>
            <Curve>{windanteil_kurve()}</Curve>
        </VisualEffect.GetBezierCurve>
        <VisualEffect.MultiplyOperation InstanceId="{G['wind_dosiert']}">
            <OutputValue>{W['wind_dosiert']}</OutputValue>
            <xVariant>{W['wind']}, 0.000000</xVariant>
            <yVariant>{W['windanteil']}, 0.000000</yVariant>
        </VisualEffect.MultiplyOperation>
        <!-- ===== DIE STRECKE BEGRENZT DIE FAHNE ============================
             Der Weg über `GetSimVar` mit AMBIENT WIND VELOCITY ist erprobt und tot: Ein
             statisches Objekt bekommt die Variable nicht, der Knoten liefert 0, und die
             Fahne blieb bei 27 kt so lang wie ohne alles (13.09.2026 gegengeprüft).

             Hier wird deshalb nicht der Wind geschätzt, sondern die tatsächlich
             zurückgelegte WAAGERECHTE STRECKE gemessen. Das ist genau die Größe, die bei
             Wind zu groß wird, und sie gilt unabhängig davon, woher der Versatz kommt.

             Gerechnet wird mit dem QUADRAT der Entfernung: Die Wurzel bräuchte einen
             weiteren Knotentyp, und die Kurve kann das Quadrat ebenso gut abbilden
             (x = (r/{STRECKE_BEZUG_M:.0f} m)^2). -->
        <VisualEffect.GetParticleAttribute InstanceId="{G['pos']}">
            <OutputValue>{W['pos']}</OutputValue>
            <ParticleAttributeType>Position</ParticleAttributeType>
        </VisualEffect.GetParticleAttribute>
        <VisualEffect.Split InstanceId="{G['pos_split']}">
            <x>{W['pos']}, 0.000000</x>
            <outX>{W['pos_x']}</outX>
            <outY>{W['pos_y']}</outY>
            <outZ>{W['pos_z']}</outZ>
        </VisualEffect.Split>
        <VisualEffect.MultiplyOperation InstanceId="{G['x2']}">
            <OutputValue>{W['x2']}</OutputValue>
            <xVariant>{W['pos_x']}, 0.000000</xVariant>
            <yVariant>{W['pos_x']}, 0.000000</yVariant>
        </VisualEffect.MultiplyOperation>
        <VisualEffect.MultiplyOperation InstanceId="{G['z2']}">
            <OutputValue>{W['z2']}</OutputValue>
            <xVariant>{W['pos_z']}, 0.000000</xVariant>
            <yVariant>{W['pos_z']}, 0.000000</yVariant>
        </VisualEffect.MultiplyOperation>
        <VisualEffect.AddOperation InstanceId="{G['r2']}">
            <OutputValue>{W['r2']}</OutputValue>
            <xVariant>{W['x2']}, 0.000000</xVariant>
            <yVariant>{W['z2']}, 0.000000</yVariant>
        </VisualEffect.AddOperation>
        <VisualEffect.MultiplyOperation InstanceId="{G['r2_norm']}">
            <OutputValue>{W['r2_norm']}</OutputValue>
            <xVariant>{W['r2']}, 0.000000</xVariant>
            <yVariant>{NULL}, {1.0 / (STRECKE_BEZUG_M ** 2):.8f}</yVariant>
        </VisualEffect.MultiplyOperation>
        <VisualEffect.GetBezierCurve InstanceId="{G['strecke_kurve']}">
            <OutputValue>{W['strecke_f']}</OutputValue>
            <FXTime>{W['r2_norm']}, 0.000000</FXTime>
            <Curve>{strecke_kurve()}</Curve>
        </VisualEffect.GetBezierCurve>
        <VisualEffect.MultiplyOperation InstanceId="{G['alpha_final']}">
            <OutputValue>{W['alpha_final']}</OutputValue>
            <xVariant>{W['alpha']}, 0.000000</xVariant>
            <yVariant>{W['strecke_f']}, 0.000000</yVariant>
        </VisualEffect.MultiplyOperation>

        <!-- ===== DIE VIER STREUUNGEN =========================================
             Ohne sie leben alle Partikel gleich lang, steigen gleich schnell und sind
             gleich gross: Daraus MUSS ein glattkantiger Trichter werden. Jede Streuung
             zieht ihre Zufallszahl ueber die Partikelnummer, damit ein Partikel seinen
             Wert behaelt, statt je Bild neu zu wuerfeln. Die Startwerte (`RandSeed`)
             sind verschieden, sonst waeren alle vier Streuungen dieselbe Zahl und die
             Partikel wieder im Gleichschritt.

             Verhaeltnisse wie in X-Plane (Min/Max-Spalten der .pss). -->

        <!-- Lebensdauer: manche Wolken loesen sich frueher auf als andere. -->
        <VisualEffect.RandomValue InstanceId="{G['leben_rnd']}">
            <OutputValue>{W['leben']}</OutputValue>
            <MinRandValue>{NULL}, {LEBENSDAUER_S * LEBEN_MIN_F:.6f}</MinRandValue>
            <MaxRandValue>{NULL}, {LEBENSDAUER_S * LEBEN_MAX_F:.6f}</MaxRandValue>
            <RandSeed>{NULL}, 331.000000</RandSeed>
            <RandIndex>{W['id']}, 0.000000</RandIndex>
        </VisualEffect.RandomValue>

        <!-- Steiggeschwindigkeit: die Front zerfasert, statt geschlossen zu steigen. -->
        <VisualEffect.RandomValue InstanceId="{G['steig_rnd']}">
            <OutputValue>{W['steig_f']}</OutputValue>
            <MinRandValue>{NULL}, {STEIG_MIN_F:.6f}</MinRandValue>
            <MaxRandValue>{NULL}, {STEIG_MAX_F:.6f}</MaxRandValue>
            <RandSeed>{NULL}, 617.000000</RandSeed>
            <RandIndex>{W['id']}, 0.000000</RandIndex>
        </VisualEffect.RandomValue>
        <VisualEffect.MultiplyOperation InstanceId="{G['steig_dosiert']}">
            <OutputValue>{W['steig_dosiert']}</OutputValue>
            <xVariant>{W['auftrieb']}, 0.000000</xVariant>
            <yVariant>{W['steig_f']}, 0.000000</yVariant>
        </VisualEffect.MultiplyOperation>

        <!-- Groesse: ungleiche Ballen statt gleichfoermiger Perlen. Der Zufallsfaktor
             wirkt auf die KURVE, nicht auf einen festen Wert; ein Partikel bleibt also
             ueber seine ganze Lebenszeit anteilig gleich gross oder klein. -->
        <VisualEffect.RandomValue InstanceId="{G['gr_rnd']}">
            <OutputValue>{W['gr_f']}</OutputValue>
            <MinRandValue>{NULL}, {GROESSE_MIN_F:.6f}</MinRandValue>
            <MaxRandValue>{NULL}, {GROESSE_MAX_F:.6f}</MaxRandValue>
            <RandSeed>{NULL}, 929.000000</RandSeed>
            <RandIndex>{W['id']}, 0.000000</RandIndex>
        </VisualEffect.RandomValue>
        <VisualEffect.MultiplyOperation InstanceId="{G['groesse_gestreut']}">
            <OutputValue>{W['groesse_gestreut']}</OutputValue>
            <xVariant>{W['groesse']}, 0.000000</xVariant>
            <yVariant>{W['gr_f']}, 0.000000</yVariant>
        </VisualEffect.MultiplyOperation>

        <VisualEffect.AddOperation InstanceId="{G['summe_wind']}">
            <OutputValue>{W['summe_wind']}</OutputValue>
            <xVariant>{W['summe']}, 0.000000</xVariant>
            <yVariant>{W['wind_dosiert']}, 0.000000</yVariant>
        </VisualEffect.AddOperation>
    </WorldBase.Flight>
</SimBase.Document>
"""


def main() -> None:
    ziel = QUELLEN / "VisualEffectLibs" / "devprops" / "friesenrauch"
    ziel.mkdir(parents=True, exist_ok=True)

    namen = []
    for name, farbe in FARBEN.items():
        datei = f"FrsRauch_{name.capitalize()}"
        inhalt = effekt_xml(name, farbe)
        # ⚠ HIER PRÜFEN, NICHT IM SIMULATOR. Der SPB-Compiler meldet XML-Fehler erst beim
        # Bauen im Project Editor: ein Rückweg, der einen Menschen und mehrere Minuten
        # kostet. Ein Parser an dieser Stelle kostet Millisekunden und findet dasselbe.
        kommentar_pruefen(inhalt)
        defusedxml.minidom.parseString(inhalt)
        (ziel / f"{datei}.xml").write_text(inhalt, encoding="utf-8", newline="\r\n")
        namen.append(datei)
        print(f"  {datei + '.xml':32} #{farbe[0]:02X}{farbe[1]:02X}{farbe[2]:02X}")

    eintraege = "\n".join(f'\t<VisualEffect File="{n}"/>' for n in namen)
    (ziel / "VisualEffectLibrary.vfxlib").write_text(
        f'<VisualEffectLibrary Version="1.0.0">\n{eintraege}\n</VisualEffectLibrary>\n',
        encoding="utf-8", newline="\r\n")
    print(f"  {'VisualEffectLibrary.vfxlib':32} {len(namen)} Effekte")


if __name__ == "__main__":
    main()
