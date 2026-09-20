# -*- coding: utf-8 -*-
"""Welcher Titel BEDEUTET welche Art -- die Erstbefuellung, nicht die Wahrheit.

Die Wahrheit steht in `bruegge_katalog`: eine Zeile je (Simulator, Titel), mit
Pruefergebnis, Art, Rang und Status. Diese Datei fuellt sie EINMAL und wird danach
nicht mehr gelesen -- gepflegt wird im Admin.

## Warum das ueberhaupt hier landet

Bis zum 14.09.2026 trug jede Bruegge ihre eigene Tabelle (`g_gattungen[]` in
`msfs/bruegge.cpp` und `xplane/bruegge.cpp`). Das widerspricht dem Leitbild des Protokolls:

    Die Bruegge ist dumm. Alle Klugheit bleibt auf dem Server.

Und es kostete real: FRS61s aeltere Bruegge kannte `robbe` und `tier_wild` nicht und meldete
`GATTUNG_UNBEKANNT` -- eine Korrektur haette einen Windows-Build und eine Verteilung an
61 Piloten gebraucht. Ein Server-Release kostet einen Push.

**Der Server ist dafuer auch besser ausgeruestet.** Der Katalog kennt 2935 Titel, davon
1693 EINZELN im laufenden Simulator gesetzt und gezeichnet. Er weiss, was tatsaechlich
funktioniert; eine statische Tabelle im Client kann das grundsaetzlich nicht.

## Die Regeln fuer diese Tabelle

**Eine Art faltet die SIMULATOREN zusammen, nicht die Varianten** (PROTOKOLL.md,
Abschnitt 3). `boot_klein` ist in MSFS `Boat01` und in X-Plane `SailBoat.obj` -- dieselbe
Bedeutung, zwei Baender. Aber jede Rauchfarbe ist eine EIGENE Art: Der Server fordert
`rauch_signalrot` an und muss sich darauf verlassen koennen, dass jeder Pilot rote Saeulen
sieht.

**Der Rang ist die Reihenfolge, in der die Bruegge probiert.** Scheitert Titel 1, rueckt
Titel 2 nach -- kein theoretischer Fall: `ASO_Ambulance_Japan` liegt im MSFS-2020-Bestand,
aber nicht in 2024; er ist dort der EINZIGE Krankenwagen, und faellt er aus, verliert die
Art `krankenwagen` ihr Praedikat "ueberall" (s. `bruegge_arten_zustand`).

⚠ **Die Bruegge nimmt IMMER Rang 1** und rueckt nur bei einem Fehlschlag nach. Wer gemischte
Gruppen will -- drei Kuehe, ein Bulle --, bekommt sie deshalb NICHT ueber mehrere Titel in
einer Art: Es stuende ueberall dasselbe. Dafuer braucht es ein Wuerfeln auf dem Server, wie
es `kurs_zufall` fuer die Richtung schon tut.

**Ein Titel gehoert zu HOECHSTENS einer Art.** Das ist keine technische Schranke,
sondern eine Entscheidung vom 14.09.2026: Vorher standen 13 von 91 Titeln in mehreren
Arten (`item_flare_red` war `rauch`, `rauch_rot` UND `rauch_signalrot`), und der Katalog
haette das Pruefergebnis dann mehrfach fuehren muessen. Mit dem Wegfall der Fremdtitel und
des Sammelbegriffs `rauch` loeste sich die Mehrfachzuordnung von selbst auf.

## Was am 14.09.2026 gestrichen wurde -- und warum

| weg | Grund (Nutzerentscheidung) |
|---|---|
| `feuer`, `kegel`, `leuchtrakete`, `punkt` | haengen ganz an SayIntentions, das ein ABO braucht |
| `rauch_gelb`, `rauch_gruen` | ein Campout-Titel statt eigenem Modell, kein X-Plane |
| `tier_wild` | in X-Plane DIESELBEN zwei Hirsche wie `tier_gross` -- unterschied nichts |
| `tier_wasser` | beide Titel standen auch unter `robbe` |
| `himmel` | Polarlicht und Fallschirm in einer Art: eine Restekiste |
| `rauch` (Sammelbegriff) | alle sechs Farben laufen jetzt in BEIDEN Simulatoren aus eigener Fertigung |
| `bauwerk` | *"Windmuehlen und Oelplattform sind voellig unterschiedliche Dinge!"* -- wird `windrad` |
| `marke` | *"Das sind Heissluftballons, keine Marker!"* -- wird `windsack`, `flagge`, `ballon` |

**Alle Fremdtitel aus dem Rauch sind raus** (*"Wir nehmen nur unseren eigenen Rauch"*).

**Heimatlos geworden und bewusst OHNE Art:** `dynamic/OilPlatform.obj`,
`dynamic/OilRig.obj`, `legacy env files/radio_tower.obj`. Sie bleiben im Katalog stehen und
sind damit jederzeit wieder zuzuordnen -- das ist der ganze Sinn der Liste. Fuer die Nordsee
waere eine Oelplattform naheliegend; sie braucht dann eine eigene Art, keine Sammelrubrik.
"""

from __future__ import annotations

# Pfadstamm der X-Plane-Bordobjekte. Der Katalog fuehrt den VOLLEN Pfad, weil X-Plane keine
# Titel kennt -- `XPLMLoadObject` nimmt den Pfad relativ zum X-System-Ordner.
XP = "Resources/default scenery/sim objects/"
# Unser eigenes Plugin-Verzeichnis.
XP_EIGEN = "Resources/plugins/FriesenBruegge/objekte/"
# Das Autogen. `katalog_sammeln.py` liess es zunaechst ganz aus ("Autogen-Bausteine -- die
# gehoeren in eine Szenerie, nicht an eine Kieker-Station"), und im Grundsatz stimmt das:
# Dort liegen Baenke, Gartentische und Basketballkoerbe. Unter `US/industrial/` steht aber
# auch, was aus der Luft eine Marke abgibt -- Windraeder, LEUCHTTUERME, Tanks, Seecontainer.
# Sechs solche Zweige sind seit dem 14.09.2026 gezielt aufgenommen.
XP_AUTOGEN = "Resources/default scenery/1000 autogen/"

# Und der Flugplatz-Zweig -- Tankwagen, Schlepper, Busse, Kraene. Beide Zweige kamen
# erst am 14.09.2026 in den Katalog, nachdem im Flug belegt war, dass X-Plane auch
# Autogen- und Szenerieobjekte laedt und zeichnet (Windrad und Leuchtturm, Niederbayern).
XP_APT = "Resources/default scenery/airport scenery/"
# ⭐ `Common_Elements` und die Strassenobjekte kamen erst am 15.09.2026 in den Katalog. Sie
# standen pauschal auf der Ausschlussliste ("was nur im Verbund funktioniert"), und fuer
# Zaeune, Lampen und Absperrungen stimmt das -- nicht aber fuer den Krankenwagen, das Zelt,
# die Flughafenfeuerwehr, den Leitkegel und den Fahnenmast. An denen scheiterten fuenf
# Artenpaare, obwohl beide Simulatoren sie hatten.
XP_CE = XP_APT + "Common_Elements/"
# ⚠ NUR `static`. Die `dynamic`-Zwillinge sind fuer den fahrenden Verkehr gedacht.
XP_ROADS = "Resources/default scenery/1000 roads/objects/"

# `aus` statt Loeschen: Der Titel bleibt sichtbar und ist mit einem Klick wieder da.
AUS = "aus"

# art -> (Bedeutung, {simulator: [titel | (titel, status)]})
#
# Die Reihenfolge IST der Rang. `simulator` ist der Bestand, in dem der Titel gefunden
# wurde -- welcher Simulator ihn SETZEN kann, steht im Katalog unter `geprueft_in` und ist
# etwas anderes (`BlackBear` liegt im 2020er Bestand und funktioniert in 2024).
ARTEN: dict[str, tuple[str, dict[str, list]]] = {

    # --- Tiere ------------------------------------------------------------------------
    # ⚠ HIER STAND DER BESTE BELEG FUER DEN GANZEN UMBAU. Von den fuenf Titeln, die die
    # Bruegge fuehrte, SCHEITERN DREI nachweislich -- `PolarBear`, `Bear_U_Maritimus` und
    # `deer_o_hemionus` melden alle EXCEPTION_22 (CREATE_OBJECT_FAILED), geprueft am
    # 12.09.2026 im laufenden MSFS 2024. Die Bruegge probierte sie trotzdem bei jedem
    # Fehlversuch durch, weil eine Tabelle im Client kein Gedaechtnis hat.
    #
    # Und der Katalog kennt einen Baeren, den die Bruegge NICHT kannte: `SyrianBear` steht.
    # Genau deshalb gehoert die Zuordnung dorthin, wo die Pruefergebnisse liegen.
    #
    # Die drei gescheiterten bleiben trotzdem in der Liste -- auf `aus`. Wer sie loescht,
    # verliert die Information, dass sie schon einmal versucht wurden.
    "tier_gross": ("Ein grosses Landtier zum Zaehlen", {
        "msfs2020": ["BlackBear", "GrizzlyBear", "SyrianBear", ("PolarBear", AUS)],
        "msfs2024": [("Bear_U_Maritimus", AUS), ("deer_o_hemionus", AUS)],
        "xplane12": [XP + "dynamic/deer_buck.obj", XP + "dynamic/deer_doe.obj"],
    }),
    # `ahqa puffin walking` stand hier vorn und ist raus: "human-library-animated Raus".
    # Uebrig bleiben drei Bordvoegel -- die hat jeder Pilot.
    "tier_klein": ("Ein kleiner Vogel", {
        "msfs2020": ["Seagull", "Goose", "Flamingo"],
        "xplane12": [XP + "dynamic/seagull_glide.obj", XP + "dynamic/seagull_flap.obj",
                     XP + "dynamic/seagull_far.obj"],
    }),
    # ⚠ Haengt VOLLSTAENDIG an human-library-animated -- wer das Paket nicht hat, sieht
    # nichts. X-Plane bringt kein Nutzvieh mit (in 7000 .obj kein einziges Tier ausserhalb
    # von `dynamic/`). Noch nicht entschieden, ob die Art so bleiben darf.
    "tier_vieh": ("Nutzvieh auf der Weide", {
        "msfs2024": ["ahqa cow walking", "ahqa sheep walking", "ahqa goat walking",
                     "ahqa donkey walking"],
    }),
    # ⭐ SEIT DEM 14.09.2026 EIGENES MODELL -- und das war kein Ausweichen, sondern der
    # einzige Weg. In KEINEM der beiden Simulatoren gibt es eine Robbe:
    #
    #   MSFS 2020/2024   45 Tiertitel + 41 Tierpakete durchsucht, dazu 2642 Titel aus den
    #                    gestreamten .fsarchive-Dateien -- kein seal, sea lion, walrus
    #   X-Plane 12       alle 1146 Bordobjekte und die Szeneriebibliothek -- nichts
    #
    # Superspuds `human-library-animated` hat welche, ist aber ein MSFS-Paket: Fuer das
    # Drittel der Gruppe, das X-Plane fliegt, haette es nie etwas geloest. Deshalb steht
    # unser Modell VOR seinen Titeln und nicht dahinter -- wer sein 556-MB-Addon hat,
    # bekommt als Zugabe die animierte Robbe, alle anderen brauchen nichts weiter.
    #
    # Herkunft: "Walrus" von Poly by Google (poly.pizza/m/5T7nIjx9ekP), CC BY 3.0 --
    # Aenderung und Weitergabe ausdruecklich erlaubt, Bedingung ist die Namensnennung.
    # Stosszaehne entfernt, Backen eingezogen, Schnauze gerundet, Schwanzflosse
    # geschlossen, Hals gekuerzt. Drei Groessen nach den Angaben der Seehundstation
    # Norddeich: Bulle 1,80 m, Kuh 1,60 m, Heuler 0,85 m.
    # ⚠ DIE DREI `ahqa`-TITEL STEHEN AUF `aus`, UND DAS IST EINE NUTZERENTSCHEIDUNG
    # (14.09.2026): *"gibt es die art Robbe wieder? NUR mit unseren eigenen Robben?"*
    # Dieselbe Linie wie beim Rauch -- was ein Fremdpaket braucht, geht nicht hinaus, auch
    # nicht als Nachruecker. Geloescht sind sie nicht: Ein Klick im Admin holt sie zurueck.
    #
    # ⚠ ZWISCHENZEITLICH WAREN DARAUS DREI ARTEN GEWORDEN (`seehund_kuh`, `seehund_bulle`,
    # `seehund_heuler`), und dahinter stand ein echter Grund: Ein Soll-Eintrag traegt genau
    # EINE Art, und die Bruegge nimmt daraus IMMER Rang 1 -- sie rueckt nur nach, wenn ein
    # Titel scheitert. Mit einer Sammelart `robbe` steht an jeder Station folglich eine Kuh;
    # gemischte Kolonien gaebe es nur ueber drei getrennte Arten.
    #
    # Zusammengefasst wurde trotzdem, weil `Ein Titel gehoert zu HOECHSTENS einer Art` die
    # Wahl erzwingt -- beides nebeneinander geht nicht. Wer die Mischung will, baut sie an
    # der richtigen Stelle: ein Wuerfeln unter den Titeln einer Art, so wie der Server schon
    # den Kurs wuerfelt (`kurs_zufall`, v14.43.0). Dann bleibt es bei einer Art.
    # ⚠⚠ DREI ARTEN, NICHT EINE -- und dahinter steht der Rang-1-Mechanismus.
    #
    # Der Weg hierher ging zweimal hin und her, und beide Male aus gutem Grund. Am
    # 15.09.2026 fragte der Nutzer: *"gibt es die art Robbe wieder? NUR mit unseren eigenen
    # Robben?"* -- daraufhin wurden die drei zu einer Art `robbe` gefaltet. Seine Antwort
    # darauf war eindeutig: *"unsere robben sollen schon trennbar sein. also bitte 3 Arten
    # fuer Robben."*
    #
    # Und das ist technisch zwingend: Ein Soll-Eintrag traegt genau EINE Art, und die
    # Bruegge nimmt daraus IMMER Rang 1. Mit einer Sammelart `robbe` staende an jeder
    # Station dieselbe Kuh -- eine Kolonie aus sechs Kuehen, zwei Bullen und zwei Heulern
    # gibt es nur ueber drei getrennte Arten. Zusammenfalten liesse sich das erst, wenn der
    # Server unter den Titeln einer Art wuerfelt, so wie er den Kurs schon wuerfelt.
    #
    # `robbe` selbst steht in `bruegge_art` auf `aus` und traegt nur noch die drei
    # `ahqa`-Fremdtitel -- die sind seit dem 15.09.2026 stillgelegt (*"NUR mit unseren
    # eigenen Robben"*), dieselbe Linie wie beim Rauch. Geloescht ist nichts.
    #
    # Herkunft des Modells: "Walrus" von Poly by Google (poly.pizza/m/5T7nIjx9ekP),
    # CC BY 3.0. Stosszaehne entfernt, Backen eingezogen, Schnauze gerundet, Schwanzflosse
    # geschlossen, Hals gekuerzt. Drei Groessen nach den Angaben der Seehundstation
    # Norddeich: Bulle 1,80 m, Kuh 1,60 m, Heuler 0,85 m.
    "seehund_kuh": ("Eine Seehund-Kuh, 1,60 m", {
        "msfs2024": ["FrsSeehund_Kuh"],
        "xplane12": [XP_EIGEN + "seehund_kuh.obj"],
    }),
    "seehund_bulle": ("Ein Seehund-Bulle, 1,80 m", {
        "msfs2024": ["FrsSeehund_Bulle"],
        "xplane12": [XP_EIGEN + "seehund_bulle.obj"],
    }),
    "seehund_heuler": ("Ein Heuler, 0,85 m", {
        "msfs2024": ["FrsSeehund_Heuler"],
        "xplane12": [XP_EIGEN + "seehund_heuler.obj"],
    }),
    # Bleibt als Huelle stehen -- die Fremdtitel sind damit jederzeit wieder zu holen.
    "robbe": ("Eine Robbe (Sammelbegriff, stillgelegt)", {
        "msfs2024": [("ahqa seal moving", AUS), ("ahqa sea lion moving", AUS),
                     ("ahqa walrus moving", AUS)],
    }),

    # --- Fahrzeuge und Schiffe ---------------------------------------------------------
    # ⚠ X-Plane fehlt hier NICHT, weil es keine Fahrzeuge haette -- es hat 333, darunter
    # `airport scenery/Common_Elements/fire_department/fire_truck_small_1.obj`. Sie stehen
    # nur nicht im Katalog: `katalog_sammeln.py` durchsucht bewusst allein `sim objects/`.
    # Bis zu einem Sammellauf ueber `airport scenery/` bleibt die Art MSFS-eigen.
    #
    # ⚠ Alle fuenf stehen im MSFS-2020-Bestand und funktionieren in MSFS 2024 -- in der
    # Bruegge-Tabelle sahen sie wie 2024er Titel aus. Genau diese Verwechslung meint die
    # Trennung `simulator` (wo gefunden) gegen `geprueft_in` (wo gesetzt) im Katalog.
    # ⚠ HIER STAND X-PLANE GAR NICHT -- und das war kein Befund, sondern eine Luecke im
    # Sammellauf: Der durchsuchte bis zum 14.09.2026 nur `sim objects/`, und die
    # Flugplatzfahrzeuge liegen in `airport scenery/`. Zum Nutzer gesagt hatte ich damals
    # trotzdem, X-Plane habe keine Fahrzeuge; seine Antwort ("das glaub ich nicht!") war
    # richtig, es sind rund 300. Eine Verneinung ist nur so gut wie das Suchmuster.
    # ⚠⚠ `fahrzeug` IST AM 15.09.2026 ZERFALLEN -- in sechs Arten, und das war faellig.
    # Sie warf Tankwagen, Pushback, Bus, Feuerwehr und Crew-Car in einen Topf; wer ein
    # Feuerwehrauto anfordern wollte, bekam mit gleicher Wahrscheinlichkeit einen
    # Gepaeckschlepper. Die Titel lagen alle schon da, es fehlte nur die Trennung.
    #
    # Anlass war der Satz des Nutzers: *"16 Arten waren viel zu wenig fuer so viele
    # Objekte!"* -- und genau hier lag der groesste Hebel, ohne ein einziges neues Modell.
    #
    # Die Art selbst steht in `bruegge_art` auf `aus` statt geloescht zu sein; wer die alte
    # Einteilung zurueckwill, hat sie mit einem Klick.
    "flugplatzfahrzeug": ("Ein Flugplatzfahrzeug -- Pushback, Schlepper, Catering", {
        "msfs2020": ["ASO_Pushback_White", "ASO_Tug01_White", "ASO_CarUtility01",
                     "ASO_TruckUtility01"],
        "xplane12": [XP_APT + "Dynamic_Vehicles/TUG_MA30.obj",
                     XP_APT + "Dynamic_Vehicles/catering_truck.obj",
                     XP_APT + "Dynamic_Vehicles/TUG_660.obj"],
    }),
    "tankwagen": ("Ein Tankwagen", {
        "msfs2020": ["ASO_FuelTruck01_White", "ASO_FuelTruck02_White"],
        "xplane12": [XP_APT + "Dynamic_Vehicles/Fuel_Truck_Large.obj",
                     XP_APT + "Dynamic_Vehicles/Fuel_Truck_Small.obj"],
    }),
    "feuerwehr": ("Ein Feuerwehrfahrzeug", {
        "msfs2020": ["ASO_Firetruck01", "ASO_Firetruck02"],
        # Gross zuerst: Der Striker 6x6 ist ein Flughafenloeschfahrzeug und aus der Luft
        # zu erkennen, das kleine Loeschfahrzeug kaum.
        "xplane12": [XP_CE + "fire_department/striker_6x6_1.obj",
                     XP_CE + "fire_department/striker_4x4_1.obj",
                     XP_CE + "fire_department/fire_truck_small_1.obj"],
    }),
    "krankenwagen": ("Ein Krankenwagen", {
        # ⚠ `ASO_Ambulance_Japan` liegt im MSFS-2020-Bestand und ist dort der EINZIGE
        # Krankenwagen -- faellt er in MSFS 2024 aus, hat die Art dort nichts mehr, und die
        # Regel sperrt sie in BEIDEN Simulatoren. Ein zweiter MSFS-Titel waere Vorsorge.
        "msfs2020": ["ASO_Ambulance_Japan"],
        "xplane12": [XP_CE + "Vehicles/ambulance_eu_01.obj",
                     XP_CE + "Vehicles/ambulance_eu_02.obj",
                     XP_CE + "Vehicles/ambulance_us_01.obj"],
    }),
    "bus": ("Ein Bus", {
        "msfs2024": ["Microsoft_Bus_EUR_Vintage", "Microsoft_Bus_Modern",
                     "Microsoft_Bus_NA_Vintage"],
        "xplane12": [XP_ROADS + "cars_EU/static/s_busIC_01.obj",
                     XP_APT + "Ramp_Equipment/pax_bus_1.obj",
                     XP_APT + "Ramp_Equipment/pax_bus_2.obj"],
    }),
    "auto": ("Ein Personenwagen", {
        "msfs2024": ["Microsoft_Car_EUR_01", "Microsoft_Car_EUR_02",
                     "Microsoft_Car_EUR_03", "Microsoft_Car_EUR_04"],
        "xplane12": [XP_ROADS + "cars_EU/static/compact_1_blue.obj",
                     XP_ROADS + "cars_EU/static/compact_2_black.obj",
                     XP_ROADS + "cars/static/VWPassat_S.obj",
                     XP_APT + "Dynamic_Vehicles/crew_car.obj"],
    }),

    # --- Geraet am Boden, neu am 15.09.2026 --------------------------------------------
    "gabelstapler": ("Ein Gabelstapler", {
        "msfs2024": ["Microsoft_Forklift_Large", "Microsoft_Forklift_Medium"],
        "xplane12": [XP_APT + "Euro_Airports/Vehicles/Forklifts/Forklift_DFG430_green.obj",
                     XP_APT + "Euro_Airports/Vehicles/Forklifts/Forklift_DFG430_green_palette.obj",
                     XP_APT + "Ramp_Equipment/cargo_loader_ch70w.obj"],
    }),
    "baufahrzeug": ("Ein Baufahrzeug", {
        "msfs2024": ["Microsoft_Bulldozer"],
        "xplane12": [XP_APT + "construction/bulldozer_1.obj",
                     XP_APT + "construction/excavator_1.obj",
                     XP_APT + "construction/wheel_loader_1.obj"],
    }),
    "jetway": ("Eine Fluggastbruecke", {
        "msfs2024": ["EDDF_Jetway_01", "EHAM_Jetway_01", "EGLL_Jetway_01"],
        "xplane12": [XP_APT + "Ramp_Equipment/Ang_Jetway_400cm.obj",
                     XP_APT + "Ramp_Equipment/Ang_Jetway_250cm.obj"],
    }),
    "seecontainer": ("Ein Seecontainer", {
        "msfs2024": ["Drop_Container"],
        "xplane12": [XP_AUTOGEN + "US/industrial/containers/container_20f_01a.obj",
                     XP_AUTOGEN + "US/industrial/containers/container_20f_02a.obj",
                     XP_AUTOGEN + "US/industrial/containers/container_40f_01a.obj"],
    }),
    "zelt": ("Ein Zelt", {
        "msfs2024": ["LFPB_AS_Tent_01", "LFPB_AS_Tent_Dome_Blue",
                     "LFPB_AS_Tent_Dome_Orange"],
        "xplane12": [XP_CE + "camping/tent_01_green.obj",
                     XP_CE + "camping/tent_01_white.obj",
                     XP_CE + "camping/tent_01_green_open.obj"],
    }),
    "leitkegel": ("Ein Leitkegel", {
        "msfs2024": ["Cone_Medium"],
        "xplane12": [XP_CE + "Miscellaneous/traffic_cone_1.obj",
                     XP_CE + "Miscellaneous/traffic_cone_2.obj",
                     XP_CE + "Miscellaneous/traffic_cone_stack_1.obj"],
    }),
    "boot_klein": ("Ein kleines Boot -- Segler, Motorboot, Kajuetboot bis rund 20 m", {
        "msfs2020": ["Boat01", "Boat02", "FishingBoat", "Yacht01"],
        # ⚠ Die beiden Cruiser sind KAJUETBOOTE, keine Kreuzer: X-Plane schreibt die Laenge
        # in ZENTIMETERN in den Dateinamen, `Cruiser_1900` ist also 19 m lang. Sie standen
        # bis zum 15.09.2026 unter `boot_gross` und lieferten dort Faktor 15 zu wenig.
        "xplane12": [XP + "dynamic/SailBoat.obj", XP + "ships/Sail_1000_01.obj",
                     XP + "ships/Runabout_750_01.obj",
                     XP + "ships/Cruiser_1900_01.obj",      # 19 m
                     XP + "ships/Cruiser_1200_01.obj",      # 12 m
                     # "Dinghy Deaktivieren" -- ein Schlauchboot ist aus der Luft nichts.
                     (XP + "ships/Dinghy_400_01.obj", AUS)],
    }),
    # ⚠⚠ HIER VERSPRACH DIE ART IN BEIDEN SIMULATOREN DASSELBE UND LIEFERTE ZWEIERLEI --
    # Faktor 15 in der Laenge. Der Nutzer sah es im Flug: "Warum habe ich lauter
    # Kreuzfahrtschiffe in MSFS und nicht in xplane" (14.09.2026).
    #
    # Die Ursache ist eine Namensverwechslung. X-PLANE SCHREIBT DIE LAENGE IN ZENTIMETERN
    # IN DEN DATEINAMEN: `Sail_1000` ist ein 10-m-Segler, `Runabout_750` ein 7,5-m-Motorboot
    # und `Cruiser_1900` ein 19-m-KAJUETBOOT. "Cruiser" heisst dort Kabinenkreuzer, nicht
    # Kreuzer -- waehrend MSFS' `CruiseShip01` ein echtes Kreuzfahrtschiff von rund 290 m ist.
    #
    # Grosse Schiffe hat X-Plane sehr wohl, und bei DENEN ist die Zahl die Laenge in METERN.
    # Sie liegen nur woanders, und das ist der eigentliche Grund, warum sie niemand fand:
    #
    #     ships/Cruiser_1900_01.obj           <- fertiges Objekt, eine Datei
    #     ships/parts/BulkCarrier_342A_*.obj  <- BAUSTEINE der Szeneriebibliothek
    #
    # Ein Frachter entsteht dort aus `_BaseModel` + `_Static_Add` + `_Flags` + `_Dynamic_Add`,
    # zusammengesetzt ueber die library.txt. Fuer uns zaehlt die Ausnahme: `_StaticOnly`
    # traegt das GANZE Schiff in einer Datei -- davon gibt es genau zwei (190B und 342A).
    #
    # ⚠ UNGEMESSEN, ob `XPLMLoadObject` ein Objekt aus `parts/` ueberhaupt laedt -- dieselbe
    # offene Frage wie beim Autogen (Windrad, Leuchtturm). DESHALB BLEIBEN DIE CRUISER ALS
    # RUECKFALL auf Rang 5/6: Laedt ein Baustein nicht, meldet X-Plane einen Fehlschlag, die
    # Bruegge rueckt nach, und es steht wie bisher ein Kajuetboot da statt gar nichts.
    # ⭐⭐ AM 15.09.2026 IM FLUG GEMESSEN UND IM BILD BELEGT: `XPLMLoadObject` LAEDT EIN
    # OBJEKT AUS `ships/parts/`, UND X-PLANE ZEICHNET ES VOLLSTAENDIG.
    #
    # Das war die letzte offene Frage vor fuenf neuen Arten. `BulkCarrier_342A_StaticOnly`
    # stand in niederbayerischen Feldern -- mit Rumpf, roten Aufbauten, allen Lukendeckeln,
    # den Ladekraenen und der Beschriftung am Rumpf. `ContainerCarrier_399A_BaseModel`
    # daneben ebenso. Beide meldeten `steht`, und der Nutzer sah beide.
    #
    # ⚠ Das war NICHT selbstverstaendlich: Unter `parts/` liegen Bausteine der
    # Szeneriebibliothek, aus denen X-Plane ein Schiff sonst zusammensetzt
    # (`_BaseModel` + `_Static_Add` + `_Flags` + `_ContainersA/B`). Dass ein Baustein allein
    # laedt UND aussieht wie ein Schiff, musste gemessen werden -- "erzeugt" und "gezeichnet"
    # sind zwei verschiedene Dinge, das hat der Rauch teuer genug gelehrt.
    #
    # `_StaticOnly` steht trotzdem vorn, wo es sie gibt: Sie traegt das ganze Schiff in EINER
    # Datei. Es gibt genau zwei davon (342A und 190B).
    #
    # ⚠ `boot_gross` BLEIBT als Sammelbegriff und behaelt die Frachter, die keine eigene Art
    # tragen. Ohne das haette es nach der Aufteilung in X-Plane nichts mehr -- und ein
    # Kajuetboot als "Schiff" auszugeben war genau der Fehler, der die Sache ausloeste
    # ("Warum habe ich lauter Kreuzfahrtschiffe in MSFS und nicht in xplane"). Die beiden
    # Cruiser stehen jetzt bei `boot_klein`, wo sie mit 19 m und 12 m hingehoeren.
    "boot_gross": ("Ein grosses Schiff (Sammelbegriff)", {
        "msfs2020": ["CruiseShip01", "CruiseShip02", "CargoShip01"],
        # "Dynamic Perry wuerde ich schon direkt deaktivieren. Das ist ein Kriegsschiff."
        "xplane12": [XP + "ships/parts/BulkCarrier_155B_BaseModel.obj",
                     XP + "ships/parts/BulkCarrier_190C_BaseModel.obj",
                     XP + "ships/parts/ContainerCarrier_155A_BaseModel.obj",
                     (XP + "dynamic/Perry.obj", AUS)],
    }),
    "schiff_massengut": ("Ein Massengutfrachter", {
        "msfs2024": ["Microsoft_Ships_BulkItaly_1", "Microsoft_Ships_Nikos_1",
                     "Microsoft_Ships_OreShenzhen_1"],
        "xplane12": [XP + "ships/parts/BulkCarrier_342A_StaticOnly.obj",   # im Bild belegt
                     XP + "ships/parts/BulkCarrier_190B_StaticOnly.obj",
                     XP + "ships/parts/BulkCarrier_342B_BaseModel.obj",
                     XP + "ships/parts/BulkCarrier_190A_BaseModel.obj",
                     XP + "ships/parts/BulkCarrier_155A_BaseModel.obj"],
    }),
    "schiff_container": ("Ein Containerschiff", {
        "msfs2024": ["Microsoft_Ships_MscBremen_1", "Microsoft_Ships_Belgorod_1",
                     "Microsoft_Ships_CMACGMExupery_1", "Microsoft_Ships_LucyBorchard_1"],
        "xplane12": [XP + "ships/parts/ContainerCarrier_399A_BaseModel.obj",  # im Bild belegt
                     XP + "ships/parts/ContainerCarrier_399B_BaseModel.obj"],
    }),
    "schiff_tanker": ("Ein Oeltanker", {
        "msfs2024": ["Microsoft_Ships_TIAsiaULCC_1", "Microsoft_Ships_GoldenState_1",
                     "Microsoft_Ships_Ivyan_1"],
        # Gross zuerst -- 250 m vor 190 m vor 183 m.
        "xplane12": [XP + "ships/parts/OilTanker_250A_BaseModel.obj",
                     XP + "ships/parts/OilTanker_250B_BaseModel.obj",
                     XP + "ships/parts/OilTanker_190A_BaseModel.obj",
                     XP + "ships/parts/OilTanker_183A_BaseModel.obj",
                     XP + "ships/parts/OilTanker_183B_BaseModel.obj"],
    }),
    "schiff_gastanker": ("Ein Gastanker", {
        "msfs2024": ["Microsoft_Ships_Taitar4CG_1"],
        "xplane12": [XP + "ships/parts/LNGCarrier_190A_BaseModel.obj",
                     XP + "ships/parts/LNGCarrier_190B_BaseModel.obj",
                     XP + "ships/parts/LNGCarrier_190C_BaseModel.obj",
                     XP + "ships/parts/LNGCarrier_190D_BaseModel.obj"],
    }),
    "schnellboot": ("Ein schnelles Motorboot", {
        "msfs2024": ["Microsoft_Ships_BHLExpress5_1"],
        "xplane12": [XP + "ships/parts/SpeedBoat_1300_01_BaseModel.obj",
                     XP + "ships/parts/SpeedBoat_1300_02_BaseModel.obj",
                     XP + "ships/parts/SpeedBoat_1300_03_BaseModel.obj"],
    }),

    # --- Marken: aus einer Art sind drei geworden -----------------------------------
    #
    # "Windmuehlen und Oelplattform sind voellig unterschiedliche Dinge! Ausserdem ein
    # Windsack?!" -- die alte Art `bauwerk` warf alles zusammen, was gross und gebaut
    # war. Jetzt trennt sie sich nach dem, was der Pilot tatsaechlich sieht.
    #
    # ⚠ HIER STAND ERST "X-Plane hat kein Windrad, null Treffer in ueber 7000 .obj". Das war
    # falsch, und der Fehler lag im Suchmuster, nicht im Bestand: Die Datei heisst
    # `WindTbn2m5_100.obj` -- abgekuerzt, also findet weder `turbine` noch `windmill` sie.
    # Eine Verneinung ist nur so gut wie das Muster, mit dem gesucht wurde (14.09.2026,
    # nachdem der Nutzer widersprach: "Windraeder in xplane!! Glaub ich nicht!").
    #
    # 2m5 = 2,5 MW, 100 = 100 m Nabenhoehe, drei Varianten (b/c). Sie liegen im AUTOGEN,
    # das `katalog_sammeln.py` bewusst auslaesst -- deshalb stehen sie noch nicht im Katalog
    # und werden beim Befuellen angelegt.
    #
    # ⚠ UNGEMESSEN, ob `XPLMLoadObject` ein Autogen-Objekt laedt. Der Pfad existiert, und
    # mehr braucht die Schnittstelle nicht; Autogen-Objekte sind aber fuer Kacheln gemacht
    # und koennten eigene Annahmen mitbringen. Erster Messkandidat im naechsten X-Plane-Lauf.
    # Faellt es aus, waere OpenSceneryX der Ausweg -- aber das ist eine Fremdabhaengigkeit,
    # und die vermeiden wir, solange der Bordbestand traegt.
    "windrad": ("Ein Windrad", {
        "msfs2020": ["Windmill"],
        "msfs2024": ["windmill"],
        "xplane12": [XP_AUTOGEN + "US/industrial/power/objects/WindTbn2m5_100.obj",
                     XP_AUTOGEN + "US/industrial/power/objects/WindTbn2m5_100b.obj",
                     XP_AUTOGEN + "US/industrial/power/objects/WindTbn2m5_100c.obj"],
    }),
    # ⚠ NUR X-PLANE, und das ist ein harter Befund: MSFS hat keinen Leuchtturm als
    # SimObject. `asobo-simobjects-landmarks` enthaelt GENAU SECHS Titel -- Windmill,
    # Windsock, Smoke_Volcano, VfxSpawner und die 2024er Kleinschreibungen davon. Das ist
    # Asobos gesamter Landmark-Bestand, den SimConnect ansprechen kann; alles andere, was in
    # MSFS "Landmark" heisst, ist Szenerie (BGL) und hat keinen Titel.
    #
    # X-Plane bringt dagegen 64 mit, im Autogen unter `US/industrial/lighthouses`. Die Zahl
    # im Dateinamen ist die HOEHE IN METERN (13 bis 64) -- fuer die Nordsee sind die hohen
    # die richtigen. Dieselbe Autogen-Frage wie beim Windrad: ob `XPLMLoadObject` sie laedt,
    # ist ungemessen.
    "leuchtturm": ("Ein Leuchtturm", {
        "xplane12": [XP_AUTOGEN + "US/industrial/lighthouses/lighthouse_50_1a.obj",
                     XP_AUTOGEN + "US/industrial/lighthouses/lighthouse_64_1a.obj",
                     XP_AUTOGEN + "US/industrial/lighthouses/lighthouse_33_1a.obj"],
    }),
    # Der einzige Neuzugang, den BEIDE Simulatoren aus dem Bordbestand bedienen.
    # Windsock_05/_08 stammen aus dem Ostfriesland-Paket -- passender geht es kaum.
    "windsack": ("Ein Windsack", {
        "msfs2024": ["windsock", "Windsock_05", "Windsock_08"],
        "msfs2020": ["Windsock"],
        "xplane12": [XP + "landscape/windsock_orange.obj", XP + "landscape/windsock.obj",
                     XP + "landscape/windsock_lit.obj"],
    }),
    # ⭐ SEIT DEM 15.09.2026 BEIDSEITIG. Hier stand vorher, X-Planes `Flags` seien
    # Schiffsaufbauten und keine Fahnenmasten -- das stimmte, war aber nicht die ganze
    # Wahrheit: Der echte Mast heisst `flagpole_20m_1.obj` und liegt in `Common_Elements`,
    # dem Zweig, den der Sammellauf pauschal auslliess. Wieder eine Verneinung, die nur so
    # gut war wie ihr Suchmuster.
    "flagge": ("Eine Flagge an einem Mast", {
        "msfs2020": ["Flag_Orange", "Flag_Yellow", "Flag_Checker", "Flag_RWB",
                     "Flag_White", "Flag_Green", "flag_DE"],
        "xplane12": [XP_CE + "Miscellaneous/flagpole_20m_1.obj"],
    }),
    # ⚠ MSFS 2024 HAT EINEN HEISSLUFTBALLON IM STANDARD (Nutzer, 14.09.2026) -- er steht
    # nur nicht im Katalog, weil er ein FLUGZEUG ist und `katalog_sammeln.py` in MSFS keine
    # Flugzeugordner durchsucht (die 14 Treffer der Kategorie `Airplanes` sind Sitze).
    #
    # Damit haengt er an derselben offenen Frage wie `flugzeug_echo` und Geschwister:
    # Nimmt `AICreateSimulatedObject` einen Flugzeugtitel an, oder braucht es
    # `AICreateNonATCAircraft`? EIN Versuch mit dem Ballon beantwortet beides -- und das
    # macht ihn zum guenstigsten Messkandidaten von allen: ein Objekt, fuenf Arten.
    #
    # Ein Ballon steht in der LUFT und ist kilometerweit zu sehen; fuer ein Suchspiel ist das
    # mehr wert als jedes Bodenmodell -- am 13.09.2026 fand ein Pilot auf EDMV drei Hirsche
    # NICHT, obwohl alle sechs Objekte nachweislich dastanden.
    "ballon": ("Ein Heissluftballon in der Luft", {
        "xplane12": [XP + "dynamic/balloon1.obj", XP + "dynamic/balloon2.obj",
                     XP + "dynamic/balloon3.obj", XP + "dynamic/balloon4.obj"],
    }),

    # --- Abgestellte Flugzeuge (Nutzerwunsch 14.09.2026) -------------------------------
    #
    # ⚠ ZWEI DINGE SIND HIER UNGEPRUEFT, und beide entscheiden, ob die Arten in MSFS
    # ueberhaupt tragen:
    #
    #   1. In MSFS ist ein Flugzeug ein SimObject vom Typ *Airplane*, und dafuer gibt es
    #      einen EIGENEN Aufruf (`AICreateNonATCAircraft`). Ob `AICreateSimulatedObject` --
    #      der, den die Bruegge benutzt -- einen Flugzeugtitel ueberhaupt annimmt, hat noch
    #      niemand gemessen. In X-Plane stellt sich die Frage nicht: Die `*_static.obj` sind
    #      ganz gewoehnliche Objekte.
    #   2. `katalog_sammeln.py` durchsucht in MSFS nur `SimObjects/{Animals,Boats,
    #      GroundVehicles,Landmarks,Misc}`. Flugzeuge liegen woanders und stehen deshalb
    #      NICHT im Katalog -- die 14 Treffer der Kategorie `Airplanes` sind Sitze
    #      (`SEAT_*`) und Polarlichter, keine Flugzeuge.
    #
    # Deshalb stehen hier vorerst nur X-Plane-Titel. Sobald beides geklaert ist, kommen die
    # MSFS-Baender dazu -- ohne Client-Release, genau dafuer liegt die Liste jetzt hier.
    #
    # Die Einteilung folgt der deutschen Lesart: ECHO-Klasse sind einmotorige Landflugzeuge
    # bis 2 t (C172, PA28, BE58 -- das, was auf einem Friesen-Platz steht), GA meint hier das
    # groessere Geschaeftsreisegeraet darueber, AIRLINER den Linienverkehr.
    "flugzeug_echo": ("Ein abgestelltes Echo-Klasse-Flugzeug", {
        "xplane12": [XP + "apt_aircraft/prop/C172/C172_static.obj",
                     XP + "apt_aircraft/prop/PA28/PA28_N157WA.obj",
                     XP + "apt_aircraft/prop/BE58/BE58_static.obj"],
    }),
    "flugzeug_ga": ("Ein abgestelltes Geschaeftsreiseflugzeug", {
        "xplane12": [XP + "apt_aircraft/turboprop/BE9L/BE9L_static.obj",
                     XP + "apt_aircraft/turboprop/P180/P180_static.obj",
                     XP + "apt_aircraft/turboprop/AT72_DLH/AT72_DLH_static.obj"],
    }),
    "flugzeug_airliner": ("Ein abgestellter Verkehrsflieger", {
        "xplane12": [XP + "apt_aircraft/jet/A320_DLH/A320_DLH_static.obj",
                     XP + "apt_aircraft/jet/A320_EZY/A320_EZY_static.obj",
                     XP + "apt_aircraft/heavy/B744_UAL/B744_UAL_static.obj"],
    }),
    # ⚠ LEER, UND DAS IST DER PUNKT. Weder X-Plane noch MSFS bringen ein statisches
    # Oldtimer-Flugzeug mit -- keine Ju 52, keine DC-3, keine Piper Cub (gesucht in allen
    # 298 statischen X-Plane-Flugzeugen und im MSFS-Katalog). Die Art steht trotzdem
    # hier: Eine Art ohne aktiven Titel ist nirgends anzufordern, aber sie ist da, und
    # der Tag, an dem ein Titel auftaucht, kostet dann keinen Client-Release mehr.
    "flugzeug_klassik": ("Ein abgestelltes Oldtimer-Flugzeug", {}),

    # --- Rauch: sechs Farben, beide Simulatoren, alles aus eigener Fertigung ------------
    #
    # "Wir nehmen nur unseren eigenen Rauch. Wir haben alle sechs Farben in allen
    # Simulatoren! Das SayIntentions und Campout: alles raus!"
    #
    # Damit faellt auch der Sammelbegriff `rauch` weg: Er hiess "irgendeine gut sichtbare
    # Saeule" und war noetig, solange nicht jede Farbe ueberall lief. Jetzt fordert der
    # Server die Farbe an, die er meint.
    "rauch_signalrot":    ("Signalrote Rauchsaeule", {
        "msfs2024": ["FrsRauch_Signalrot"], "xplane12": [XP_EIGEN + "rauch_signalrot.obj"]}),
    "rauch_signalorange": ("Signalorange Rauchsaeule", {
        "msfs2024": ["FrsRauch_Signalorange"], "xplane12": [XP_EIGEN + "rauch_signalorange.obj"]}),
    "rauch_rot":          ("Rote Rauchsaeule (Friesenfarbe)", {
        "msfs2024": ["FrsRauch_Rot"], "xplane12": [XP_EIGEN + "rauch_rot.obj"]}),
    "rauch_orange":       ("Orange Rauchsaeule (Friesenfarbe)", {
        "msfs2024": ["FrsRauch_Orange"], "xplane12": [XP_EIGEN + "rauch_orange.obj"]}),
    "rauch_hellblau":     ("Hellblaue Rauchsaeule (Friesenfarbe)", {
        "msfs2024": ["FrsRauch_Hellblau"], "xplane12": [XP_EIGEN + "rauch_hellblau.obj"]}),
    "rauch_navy":         ("Navy Rauchsaeule (Friesenfarbe)", {
        "msfs2024": ["FrsRauch_Navy"], "xplane12": [XP_EIGEN + "rauch_navy.obj"]}),
}

# --- Marken: Wuerfel, Saeulen, Licht -- alles eigene Fertigung, in allen drei Simulatoren -------
#
# "ich brauche auch immer Vergleichbares in den anderen beiden Sims" (Nutzer, 20.09.2026).
# Anlass: In MSFS 2024 liegen `Peace_Tower_Light` (eine sehr helle weisse Saeule) und
# `wENLK_lightdummy` (kleine rote Wuerfel) auf der Platte -- in MSFS 2020 gibt es nichts
# Vergleichbares (EXCEPTION_22, aus Szenerie-Paketen), und X-Plane hat nur Uplights, keine
# Wuerfel. Also eigene Objekte, die ueberall gleich aussehen:
#
#   * `wuerfel_<farbe>`   3 m, massiv, in einer der sechs Friesenfarben  -- gut bei Tag
#   * `saeule_<farbe>`    100 m hoch, schmal, leuchtend; dazu `saeule_weiss`
#   * `licht`             ein warmes Punktlicht, wie die zwei Lichtpunkte auf der Wiese
#
# ⚠ Die Farbe traegt Bedeutung, deshalb je Farbe eine Art und kein Wuerfeln -- wie beim Rauch.
# ⚠ Artnamen hoechstens 23 Zeichen (`char art[24]` in beiden Bruegge).
_MARKEN_FARBEN = {
    "navy": "Navy", "hellblau": "Hellblau", "rot": "Rot", "orange": "Orange",
    "signalrot": "Signalrot", "signalorange": "Signalorange",
}
for _f, _titel in _MARKEN_FARBEN.items():
    ARTEN[f"wuerfel_{_f}"] = (f"Ein Wuerfel, 3 m, in {_titel} (Friesenfarbe)", {
        "msfs2024": [f"FrsWuerfel_{_titel}"], "xplane12": [XP_EIGEN + f"wuerfel_{_f}.obj"]})
for _f, _titel in {"weiss": "Weiss", **_MARKEN_FARBEN}.items():
    ARTEN[f"saeule_{_f}"] = (f"Eine schmale Lichtsaeule, 100 m hoch, in {_titel}"
                             + ("" if _f == "weiss" else " (Friesenfarbe)"), {
        "msfs2024": [f"FrsSaeule_{_titel}"], "xplane12": [XP_EIGEN + f"saeule_{_f}.obj"]})
ARTEN["licht"] = ("Ein einfaches warmes Punktlicht, leuchtet nachts", {
    "msfs2024": ["FrsLicht_Warm"], "xplane12": [XP_EIGEN + "licht_warm.obj"]})


def erstbefuellung() -> list[dict]:
    """Die Zuordnung flach, in der Form, die ``bruegge_katalog`` braucht.

    Titel, die der Katalog noch nicht kennt (unser eigener Rauch etwa -- er entstand nach
    dem letzten Sammellauf), werden dabei ANGELEGT. Die Liste soll vollstaendig sein.
    """
    raus = []
    for art, (bedeutung, je_sim) in ARTEN.items():
        for simulator, titel in je_sim.items():
            # Der Rang zaehlt JE SIMULATOR von vorn -- er ist die Reihenfolge, in der die
            # Bruegge probiert, und die bekommt sie immer nur fuer ihren eigenen Bestand.
            rang = 0
            for eintrag in titel:
                name, status = eintrag if isinstance(eintrag, tuple) else (eintrag, "aktiv")
                rang += 1
                raus.append({"simulator": simulator, "titel": name, "art": art,
                             "rang": rang, "status": status, "bedeutung": bedeutung})
    return raus


#: Alle Arten, die es gibt -- fuer die Auswahl im Admin und die Pruefung im Endpunkt.
ALLE_ARTEN = tuple(ARTEN)
