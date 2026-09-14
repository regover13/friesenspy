# -*- coding: utf-8 -*-
"""Die Formkorrekturen am Seehund -- Backen, Schwanzflosse, Schnauze.

Eigene Datei, weil hier die Zahlen sitzen, an denen man dreht. `seehund_bauen.py` ruft das
auf; wer die Form aendert, aendert sie hier und nirgends sonst.

WAS DAS WALROSS VOM SEEHUND UNTERSCHEIDET (Nutzer, 14.09.2026)
1. DIE BACKEN. Ein Walross hat fleischige Haengebacken, in denen die Stosszaehne sitzen --
   nimmt man die Zaehne weg, bleiben die Backen. Ein Seehund hat eine schmale, runde
   Schnauze.
2. DIE SCHWANZFLOSSE. Beim Modell spreizen die Hinterflossen ab Y +0,47 auf 0,186 m halbe
   Breite -- ein weites V. Ein Seehund legt sie zusammen; sie bilden einen fast
   geschlossenen Faecher. Von oben ist das der auffaelligste Unterschied, und von oben
   wird gezaehlt.
3. DIE SCHNAUZE. Gemessen am ROHMODELL -- es kommt also nicht vom Entfernen der Zaehne:

       |X| 0.0 .. 16.4   vorderstes Y  -354,4      <- die Mitte liegt ZURUECK
       |X| 49.1 .. 65.4  vorderstes Y  -367,7      <- hier steht der Lippenwulst vor

   Zwei Oberlippenwuelste mit einer Kerbe dazwischen. Eine Robbe hat einen Bogen.

⚠⚠ DIE WICHTIGSTE REGEL DIESER DATEI: KLEINE TEILE WERDEN STARR BEWEGT.
Jede Korrektur hier verschiebt Ecken nach ihrer Lage -- die Schnauzenrundung zum Beispiel
nach |x|. Wendet man das auf eine kompakte Augenkugel an, deren Ecken ueber verschiedene
|x| verteilt sind, zieht man sie auseinander. Genau das ist am 14.09.2026 passiert und war
im Bild sofort zu sehen ("Die Nase und augen hast du wie die Backen lang gezogen"):

    Teil              im Rohmodell              danach
    Nase (black)      0,095 x 0,095 x 0,095     0,037 x 0,122 x 0,036   <- Stab
    Auge (black)      0,061 x 0,061 x 0,061     0,025 x 0,061 x 0,023

Deshalb werden zusammenhaengende Inseln unterhalb von STARR_ANTEIL der Modelllaenge als
starre Koerper behandelt: Die Verschiebung wird EINMAL fuer ihren Schwerpunkt gerechnet und
dann auf alle ihre Ecken angewandt. Sie wandern mit, behalten aber ihre Form.

⚠⚠ UND GLAETTEN IST HIER KEIN WEG -- einmal probiert, einmal zurueckgenommen. Das Modell
hat 698 offene Kanten in 6 Randschleifen; es ist aus getrennten Teilen gebaut. Eine
Randecke hat keine vollstaendige Nachbarschaft, wandert beim Glaetten nach innen, der Rand
kollabiert. Ergebnis war ein zerknittertes Maul mit durchschlagenden schwarzen Flaechen.
Wer es dennoch will, muss zuerst die Raender schliessen -- Modellierarbeit, kein
Rechenschritt.
"""
from __future__ import annotations

# ⚠⚠ ALLE LAENGSANGABEN SIND ANTEILE, NICHT METER -- 0,0 ist die Schnauze, 1,0 das Ende
# der Hinterflossen.
#
# Hier stand einmal Meter, und das war ueber Stunden falsch, ohne aufzufallen: Zum
# Zeitpunkt der Formkorrektur ist das Tier zwar schon auf 1,70 m skaliert, aber noch NICHT
# zentriert -- es liegt bei Y -0,643 .. +1,057, weil der Ursprung erst danach gesetzt
# wird. Meine Zahlen waren aber auf das fertige, zentrierte Modell (-0,85 .. +0,85)
# geschrieben. Folge: Die Schnauze bekam statt der vollen Wirkung nur 48 %, und die
# Brustpartie lag komplett ausserhalb des Bereichs.
#
# Gemerkt habe ich es erst, als der Nutzer sagte "ich sehe keinen Unterschied. Beides
# gleich schlecht" -- gemessen war die groesste Aenderung 1,1 cm, waehrend der
# Funktionstest 10-15 cm auswies. Der Test hatte recht; er lief nur mit Koordinaten, die
# es im Modell gar nicht gab.
#
# Als Anteile kann das nicht mehr passieren, und es traegt ausserdem die drei Groessen
# (Bulle 1,80 m / Kuh 1,60 m / Heuler 0,85 m) ohne eine einzige weitere Zahl.

# --- die Stellschrauben ---------------------------------------------------------------
# Kopf: von KOPF_AB (unveraendert) nach vorn bis zur Spitze auf KOPF_BREITE zusammenziehen.
# ⚠ KOPF_AB weit genug nach hinten, sonst entsteht eine STUFE. Die Hoehenstauchung
# (KOPF_HOEHE) endet bei KOPF_AB abrupt; stand der Wert bei 0,25, sah man hinter dem
# Kopf einen Knick im Ruecken -- der Nutzer hat ihn am 14.09.2026 als Bogen
# nachgezeichnet, den er dort erwartet. Mit 0,40 laeuft sie ueber das doppelte Stueck
# aus und verschwindet im Verlauf.
KOPF_AB, KOPF_BIS, KOPF_BREITE = 0.40, 0.00, 0.52
# Die Backen sitzen auch in der Hoehe zu dick auf -- etwas flacher, am Scheitel gemessen.
KOPF_HOEHE = 0.88

# Schwanzflosse: ab SCHWANZ_AB nach hinten auf SCHWANZ_BREITE zusammenlegen.
SCHWANZ_AB, SCHWANZ_BIS, SCHWANZ_BREITE = 0.70, 1.00, 0.28

# ⚠ ZUSAMMENSCHIEBEN ALLEIN REICHT NICHT -- DER SPALT BLEIBT. Beim ersten Anlauf wurden die
# Flossen schmaler, und der Einschnitt zwischen ihnen wurde einfach mit schmaler: Er reicht
# im Rohmodell fast bis zur Koerpermitte, und das ist der Unterschied, den man von oben
# sieht. Auf dem Referenzfoto bilden die Hinterflossen EINEN Faecher mit fuenf Zehen.
# Also wandern Ecken nahe der Mittelebene in +Y und fuellen die Kerbe.
SPALT_NAEHE, SPALT_FUELLEN = 0.075, 0.16

# Die Schnauzenkontur auf einen Bogen ziehen: in der Mitte am weitesten vorn, nach aussen
# glatt zurueckweichend.
#
# ⚠ RUND HEISST RUND IN BEIDEN RICHTUNGEN. Zuerst ging nur |x| in die Rechnung ein -- also
# die Kontur von OBEN. Von der Seite blieb sie eine Kante, und ein einzelner Vertex am
# Kinn, der auf der Mittelebene sitzt (|x| = 0), wurde auf die vorderste Position gezogen
# und ragte als Zipfel unter der Schnauze heraus (Nutzer, 14.09.2026, im Bild eingekreist):
#
#     vorderste Ecke unter der Nase   Y -0,8442  Z +0,2405  X 0,0000
#     ihre Nachbarn                              Z +0,2856 .. +0,3057
#
# Jetzt zaehlt der Abstand von der SCHNAUZENACHSE, also sqrt(x^2 + (z - z_achse)^2). Damit
# weicht die Kontur nach unten genauso zurueck wie zur Seite, und das Kinn bleibt hinten.
SCHNAUZE_LAENGE, SCHNAUZE_TIEFE = 0.12, 0.055

# Die Lippenwuelste (Material `lightbrown`) zusaetzlich schrumpfen -- ISOTROP um ihren
# eigenen Schwerpunkt, damit aus der Kugel keine Scheibe wird.
WULST_MATERIAL, WULST_ZIEHEN = "lightbrown", 0.58

# ⚠ DIE BRUSTSCHUERZE -- der massige Hals des Walrosses (Nutzer, 14.09.2026, im Bild
# markiert: "sollte nicht dieser ganze teil weg?"). Gemessen an der Seitenkontur:
#
#     Y -0,77   Z 0,065 .. 0,446      <- reicht fast bis zum Boden UND bis ganz hoch
#     Y -0,70   Z 0,041 .. 0,460
#     Y -0,54   Z 0,013 .. 0,458
#
# Ein Walross hat einen massiven Nacken und eine Brust wie ein Fass; unter dem angehobenen
# Kopf steht eine senkrechte Wand. Ein Seehund hebt den Kopf auf einem schlanken Hals, und
# darunter ist Luft.
#
# Deshalb wird die Unterseite im vorderen Bereich angehoben -- aber NUR nahe der
# Mittelebene: Bei Y -0,54 liegen dort auch die Vorderflossen (|X| bis 0,261), und die
# gehoeren auf den Sand. HALS_BREITE trennt Rumpf von Flosse.
# ⚠ ERSTER ANLAUF WIRKUNGSLOS -- die Gewichtung lag falsch. Mit HALS_BREITE 0,135 und
# linearem Abfall bekamen ausgerechnet die tiefsten Ecken fast nichts ab: Sie sitzen bei
# |X| 0,109, also am Rand des Bereichs, wo der lineare Abfall schon bei 0,19 steht.
# Nachgerechnet ergab das 1,3 cm Hebung statt der beabsichtigten zehn.
# Jetzt ein PLATEAU bis zur halben Breite, und erst dann der Abfall.
HALS_AB, HALS_BIS = 0.40, 0.00
HALS_HEBUNG, HALS_BREITE, HALS_Z_MAX = 0.21, 0.175, 0.26

# Die Nase ist nach dem Entzerren 0,051 m gross und damit noch zu wuchtig fuer einen
# Seehund (Nutzer, 14.09.2026). Sie ist die einzige `black`-Insel auf der Mittelebene --
# die beiden anderen sind die Augen bei |X| 0,037.
NASE_ZIEHEN, NASE_MITTE = 0.72, 0.012

# ⚠ DER NACKENBUCKEL -- die Rueckenlinie schwingt, statt zu fallen (Nutzer, 14.09.2026,
# als glatter Bogen nachgezeichnet). Gemessen an der Oberkante je Laengsscheibe:
#
#     Anteil 0,083   Z 0,419
#     Anteil 0,125   Z 0,405      <- Senke
#     Anteil 0,167   Z 0,432      <- Buckel, hoechster Punkt des ganzen Tieres
#     Anteil 0,208   Z 0,381
#     Anteil 0,250   Z 0,318
#
# Ein Walross hat dort einen fleischigen Nacken; ein Seehund faellt vom Kopf glatt ab.
#
# ⚠ EINE GLOCKE, KEINE BLENDE. Eine Blende (wie bei Kopf und Hals) hat ihr Maximum am
# RAND -- damit wuerde auch der Kopf abgesenkt, und der soll oben bleiben. Die Glocke
# wirkt nur um NACKEN_MITTE herum und laeuft nach beiden Seiten aus.
#
# ⚠ UND DIE GLOCKE MUSS DEN KOPF AUSSPAREN. Erster Anlauf: Mitte 0,17, Breite 0,15 -- damit
# reichte sie bis zum Kopf bei Anteil 0,069 und senkte ihn um 1,5 cm mit. Der Buckel wurde
# absolut kleiner, RELATIV zum Kopf blieb er gleich, und genau den sieht man. Nachgemessen
# liegen die hoechsten Ecken alle auf der Rueckenmitte (|X| < 0,02):
#
#     Anteil 0,069   Z 0,348      <- Kopf
#     Anteil 0,113   Z 0,347
#     Anteil 0,196   Z 0,360      <- steigt UEBER den Kopf, und das ist der Fehler
#
# Mit Mitte 0,20 und Breite 0,13 faellt der Kopf aus dem Wirkungsbereich (Abstand 0,131).
NACKEN_MITTE, NACKEN_BREITE = 0.20, 0.13
NACKEN_SENKEN, NACKEN_Z_AB = 0.035, 0.55

# Inseln, deren groesste Ausdehnung darunter liegt (Anteil an der Modelllaenge), gelten als
# starre Koerper. Augen 0,061 / Nase 0,095 / Wuelste 0,245 bei 1,70 m Laenge -- also bis
# 14 %; der Rumpf liegt bei 100 %. 0,30 trennt sauber, ohne knapp zu sein.
STARR_ANTEIL = 0.30


def entzerren(netz, faktoren) -> tuple[int, float]:
    """Kleine Teile von der ANISOTROPEN Skalierung befreien. (Teile, Streckung vorher).

    ⚠ HIER SASS DER FEHLER, UND ZWAR NICHT DA, WO ICH IHN ZUERST GESUCHT HABE.
    Das Tier wird je Achse verschieden skaliert (X 0,00071 / Y 0,00175 / Z 0,00067), weil
    das Walross gedrungen ist und ein Seehund schlank. Fuer den Rumpf ist das richtig --
    fuer jedes kompakte Detail ist es verheerend: Eine Augenkugel wird dabei 2,5-fach in
    die Laenge gezogen. Gemessen, nachdem der Nutzer es im Bild gesehen hatte:

        Nase   im Roh 0,095 x 0,095 x 0,095   ->   0,039 x 0,093 x 0,037
        Auge   im Roh 0,061 x 0,061 x 0,061   ->   0,025 x 0,060 x 0,023

    Ich hatte zuerst die Formkorrektur verdaechtigt und sie starr gemacht -- richtig, aber
    wirkungslos, weil die Verzerrung schon vorher entstand. Erst der Vergleich mit dem
    Rohmodell hat die Stelle gezeigt.

    Also: Jedes kleine Teil wird um seinen Schwerpunkt zurueckskaliert, auf den
    GEOMETRISCHEN MITTELWERT der drei Faktoren. Das ist der Kompromiss zwischen "so gross
    wie im Original" (Y-Faktor, zu gross gegenueber dem schmalen Kopf) und "so schmal wie
    der Koerper" (X-Faktor, kaum noch sichtbar).
    """
    sx, sy, sz = faktoren
    g = (abs(sx) * abs(sy) * abs(sz)) ** (1.0 / 3.0)
    k = (g / sx, g / sy, g / sz)
    if all(abs(w - 1.0) < 1e-6 for w in k):
        return 0, 1.0

    y_vorn = min(v.co.y for v in netz.vertices)
    laenge = max(v.co.y for v in netz.vertices) - y_vorn

    teile = 0
    schlimmste = 1.0
    for gruppe in _inseln(netz):
        ecken = [netz.vertices[i].co for i in gruppe]
        spannen = [max(p[a] for p in ecken) - min(p[a] for p in ecken) for a in range(3)]
        if max(spannen) >= laenge * STARR_ANTEIL:
            continue
        schlimmste = max(schlimmste, max(spannen) / (min(spannen) or 1e-9))
        mitte = [sum(p[a] for p in ecken) / len(ecken) for a in range(3)]
        for i in gruppe:
            v = netz.vertices[i]
            v.co = tuple(mitte[a] + (v.co[a] - mitte[a]) * k[a] for a in range(3))
        teile += 1
    return teile, schlimmste


def _blende(wert: float, von: float, bis: float) -> float:
    """0 bei `von`, 1 bei `bis`, glatt dazwischen (smoothstep)."""
    spanne = bis - von
    if abs(spanne) < 1e-9:
        return 0.0
    t = (wert - von) / spanne
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return t * t * (3.0 - 2.0 * t)


def _glocke(wert: float, mitte: float, breite: float) -> float:
    """1,0 bei `mitte`, 0,0 ab `breite` Abstand, glatt dazwischen.

    Gegenstueck zu `_blende`: Die hat ihr Maximum am Rand des Bereichs, diese in der Mitte.
    Fuer eine oertlich begrenzte Delle oder Beule ist das die richtige Form.
    """
    d = abs(wert - mitte) / breite
    if d >= 1.0:
        return 0.0
    return (1.0 - d * d) ** 2


def _inseln(netz) -> list[list[int]]:
    """Zusammenhaengende Eckengruppen, ueber die Kanten des Netzes verfolgt."""
    nachbarn: dict[int, set[int]] = {}
    for k in netz.edges:
        a, b = k.vertices
        nachbarn.setdefault(a, set()).add(b)
        nachbarn.setdefault(b, set()).add(a)

    offen = set(range(len(netz.vertices)))
    raus = []
    while offen:
        start = offen.pop()
        gruppe = [start]
        stapel = [start]
        while stapel:
            v = stapel.pop()
            for n in nachbarn.get(v, ()):
                if n in offen:
                    offen.discard(n)
                    gruppe.append(n)
                    stapel.append(n)
        raus.append(gruppe)
    return raus


def _verschieben(x: float, y: float, z: float, y_vorn: float, laenge: float, x_ref: float,
                 boden_z: float, z_achse: float, hoehe: float) -> tuple[float, float, float]:
    """Die eigentliche Abbildung -- fuer eine Ecke ODER fuer einen Schwerpunkt.

    ⚠ `y` kommt in Metern herein, die Konstanten sind ANTEILE (0 = Schnauze, 1 = Ende).
    Umgerechnet wird genau hier, mit `y_vorn` und `laenge` aus dem Netz selbst -- damit
    kann die Korrektur nicht wieder an der falschen Stelle greifen, egal wo das Modell
    gerade liegt und welche Groesse gebaut wird.
    """
    # ⚠ Der Name hier hiess einmal `anteil` -- und zehn Zeilen tiefer heisst eine lokale
    # Variable der Schnauzenrundung genauso. Ab dort war die Funktion ein float, und der
    # Bau brach mit "'float' object is not callable" ab.
    def _bei(a: float) -> float:
        return y_vorn + a * laenge

    w_kopf = _blende(y, _bei(KOPF_AB), _bei(KOPF_BIS))
    w_schwanz = _blende(y, _bei(SCHWANZ_AB), _bei(SCHWANZ_BIS))

    x *= (1.0 - w_kopf * (1.0 - KOPF_BREITE)) * \
         (1.0 - w_schwanz * (1.0 - SCHWANZ_BREITE))

    # Die Kerbe zwischen den Hinterflossen fuellen -- hier wird aus "zwei Lappen" ein Faecher.
    if w_schwanz > 0 and abs(x) < SPALT_NAEHE:
        y += w_schwanz * (1.0 - abs(x) / SPALT_NAEHE) * SPALT_FUELLEN

    # Die Schnauze runden -- aus zwei Lippenwuelsten wird ein Bogen.
    w_rund = _blende(y, y_vorn + SCHNAUZE_LAENGE, y_vorn)
    if w_rund > 0:
        # Abstand von der Schnauzenachse, nicht blosses |x| -- s. oben.
        abstand = (x * x + (z - z_achse) * (z - z_achse)) ** 0.5
        anteil = min(1.0, abstand / x_ref)
        y = y * (1.0 - w_rund) + (y_vorn + SCHNAUZE_TIEFE * anteil * anteil) * w_rund

    # Die Hoehe nur am Kopf, und ueber dem Boden -- sonst saenke das Tier ein.
    if w_kopf > 0:
        z = boden_z + (z - boden_z) * (1.0 - w_kopf * (1.0 - KOPF_HOEHE))

    # Die Brustschuerze anheben -- s. oben. Je tiefer die Ecke sitzt, desto staerker, damit
    # der Uebergang zum Ruecken unberuehrt bleibt.
    w_hals = _blende(y, _bei(HALS_AB), _bei(HALS_BIS))
    if w_hals > 0 and abs(x) < HALS_BREITE and z < boden_z + HALS_Z_MAX:
        tiefe = 1.0 - (z - boden_z) / HALS_Z_MAX
        schmal = min(1.0, (1.0 - abs(x) / HALS_BREITE) * 2.0)   # Plateau bis zur Haelfte
        z += HALS_HEBUNG * w_hals * tiefe * schmal

    # Den Nackenbuckel abtragen -- s. oben. Nur die oberen Ecken, damit der Bauch bleibt.
    anteil_y = (y - y_vorn) / laenge if laenge else 0.0
    w_nacken = _glocke(anteil_y, NACKEN_MITTE, NACKEN_BREITE)
    if w_nacken > 0:
        hoch = (z - boden_z) / (hoehe or 1.0)
        if hoch > NACKEN_Z_AB:
            staerke = (hoch - NACKEN_Z_AB) / (1.0 - NACKEN_Z_AB)
            z -= NACKEN_SENKEN * w_nacken * min(1.0, staerke)

    return x, y, z


def anpassen(netz, boden_z: float = 0.0) -> tuple[int, int]:
    """Ecken verschieben (Objektkoordinaten, Meter). Gibt (starre Teile, Ecken) zurueck."""
    # Die Schnauzenspitze und die halbe Kopfbreite dort MESSEN statt eintragen -- sonst
    # bricht die Rundung, sobald jemand an KOPF_BREITE dreht oder eine Groesse aendert.
    y_vorn = min(v.co.y for v in netz.vertices)
    y_hinten = max(v.co.y for v in netz.vertices)
    laenge = y_hinten - y_vorn
    vorn = [v.co for v in netz.vertices if v.co.y < y_vorn + SCHNAUZE_LAENGE]
    x_ref = max((abs(p.x) for p in vorn), default=0.0) * KOPF_BREITE or 1e-9
    # Die Hoehe der Schnauzenachse -- Mitte zwischen Ober- und Unterkante ganz vorn.
    z_achse = ((max(p.z for p in vorn) + min(p.z for p in vorn)) / 2.0) if vorn else 0.0
    hoehe = max(v.co.z for v in netz.vertices) - boden_z

    starr = 0
    starre_ecken = 0
    for gruppe in _inseln(netz):
        ecken = [netz.vertices[i].co for i in gruppe]
        gross = max(max(p[a] for p in ecken) - min(p[a] for p in ecken) for a in range(3))

        if gross < laenge * STARR_ANTEIL:
            # ⚠ STARR: einmal fuer den Schwerpunkt rechnen, dann alle gleich verschieben.
            mx = sum(p.x for p in ecken) / len(ecken)
            my = sum(p.y for p in ecken) / len(ecken)
            mz = sum(p.z for p in ecken) / len(ecken)
            nx, ny, nz = _verschieben(mx, my, mz, y_vorn, laenge, x_ref, boden_z, z_achse, hoehe)
            dx, dy, dz = nx - mx, ny - my, nz - mz
            for i in gruppe:
                v = netz.vertices[i]
                v.co = (v.co.x + dx, v.co.y + dy, v.co.z + dz)
            starr += 1
            starre_ecken += len(gruppe)
        else:
            for i in gruppe:
                v = netz.vertices[i]
                v.co = _verschieben(v.co.x, v.co.y, v.co.z, y_vorn, laenge, x_ref, boden_z, z_achse, hoehe)

    return starr, starre_ecken


def wuelste_einziehen(netz) -> tuple[int, float]:
    """Die Lippenwuelste schrumpfen -- isotrop, damit die Kugelform bleibt.

    Erwartet ein Mesh (nicht bmesh): gebraucht wird nur Flaeche -> Material -> Ecken.

    ⚠ GEWICHTET NACH MATERIALANTEIL, nicht hart nach Zugehoerigkeit. Eine Ecke am Rand des
    Wulstes gehoert auch zu `brown`-Flaechen; zoege man sie voll mit, risse eine Stufe zur
    Wange. Der Anteil ihrer `lightbrown`-Flaechen an allen ihren Flaechen ist das Mass.
    """
    nummer = next((i for i, m in enumerate(netz.materials)
                   if m and m.name == WULST_MATERIAL), None)
    if nummer is None:
        return 0, 0.0

    zu_wulst: dict[int, int] = {}
    gesamt: dict[int, int] = {}
    for p in netz.polygons:
        for vi in p.vertices:
            gesamt[vi] = gesamt.get(vi, 0) + 1
            if p.material_index == nummer:
                zu_wulst[vi] = zu_wulst.get(vi, 0) + 1
    if not zu_wulst:
        return 0, 0.0

    # Der Schwerpunkt, auf den hin geschrumpft wird -- nur die voll zugehoerigen Ecken
    # bestimmen ihn, sonst zoege der Rand ihn in die Wange.
    kern = [vi for vi, n in zu_wulst.items() if n == gesamt[vi]] or list(zu_wulst)
    my = sum(netz.vertices[vi].co.y for vi in kern) / len(kern)
    mz = sum(netz.vertices[vi].co.z for vi in kern) / len(kern)

    vorher = max(abs(netz.vertices[vi].co.x) for vi in zu_wulst)
    for vi, n in zu_wulst.items():
        f = 1.0 - (n / gesamt[vi]) * (1.0 - WULST_ZIEHEN)
        v = netz.vertices[vi]
        # In X zur Mittelebene, in Y/Z zum Schwerpunkt -- der liegt auf EINER Seite, und
        # zoege man X auch dorthin, verschmoelzen die beiden Wuelste zu einem.
        v.co = (v.co.x * f, my + (v.co.y - my) * f, mz + (v.co.z - mz) * f)
    nachher = max(abs(netz.vertices[vi].co.x) for vi in zu_wulst)
    return len(zu_wulst), 1.0 - nachher / (vorher or 1.0)


def nase_kleiner(netz) -> tuple[int, float]:
    """Die Nase schrumpfen -- die einzige `black`-Insel auf der Mittelebene.

    Getrennt von `entzerren`, weil das eine Korrektur ist (Rundheit wiederherstellen) und
    das hier eine Gestaltungsfrage (wie gross soll eine Robbennase sein). Wer daran dreht,
    dreht an NASE_ZIEHEN und nicht an der Entzerrung.
    """
    nummer = next((i for i, m in enumerate(netz.materials) if m and m.name == "black"), None)
    if nummer is None:
        return 0, 0.0
    schwarz = {vi for p in netz.polygons if p.material_index == nummer for vi in p.vertices}

    for gruppe in _inseln(netz):
        if not schwarz.issuperset(gruppe):
            continue
        ecken = [netz.vertices[i].co for i in gruppe]
        mitte = [sum(p[a] for p in ecken) / len(ecken) for a in range(3)]
        if abs(mitte[0]) > NASE_MITTE:      # die Augen sitzen seitlich
            continue
        vorher = max(max(p[a] for p in ecken) - min(p[a] for p in ecken) for a in range(3))
        for i in gruppe:
            v = netz.vertices[i]
            v.co = tuple(mitte[a] + (v.co[a] - mitte[a]) * NASE_ZIEHEN for a in range(3))
        return len(gruppe), vorher * NASE_ZIEHEN
    return 0, 0.0


# ⭐ DEN KOPF KUERZEN -- Nutzerwunsch 14.09.2026, im Bild zwischen zwei Strichen markiert:
# "den Kopf etwa 30-50% kuerzer". Gemeint ist der Abschnitt HINTER Augen und Nase bis zum
# Nacken; das Walross hat dort einen langen, fleischigen Hals, der Seehund einen kurzen.
#
# ⚠ EIGENER SCHRITT VOR `anpassen`, NICHT DARIN. Die Kuerzung aendert y_vorn und die
# Laenge -- und auf beiden bauen saemtliche Anteile in `anpassen` auf. Liefe sie mittendrin,
# rechneten die folgenden Korrekturen mit veralteten Grenzen, und wir haetten denselben
# Fehler wie bei den Metern (s. Kopf dieser Datei).
KOPF_KUERZEN_AB, KOPF_KUERZEN_BIS, KOPF_KUERZEN = 0.04, 0.22, 0.60


def kopf_kuerzen(netz) -> tuple[float, float]:
    """Den Halsabschnitt stauchen. Gibt (Kuerzung in m, neue Laenge) zurueck."""
    y_vorn = min(v.co.y for v in netz.vertices)
    y_hinten = max(v.co.y for v in netz.vertices)
    laenge = y_hinten - y_vorn
    y_ab = y_vorn + KOPF_KUERZEN_AB * laenge
    y_bis = y_vorn + KOPF_KUERZEN_BIS * laenge
    spanne = y_bis - y_ab
    if spanne <= 0:
        return 0.0, laenge
    versatz = spanne * (1.0 - KOPF_KUERZEN)

    def neues_y(y: float) -> float:
        if y <= y_ab:
            return y + versatz                      # Schnauze rueckt nach hinten
        if y >= y_bis:
            return y                                # Rumpf bleibt, wo er ist
        t = (y - y_ab) / spanne
        return y_ab + versatz + t * spanne * KOPF_KUERZEN

    # ⚠ Kleine Inseln (Augen, Nase, Wuelste) am Schwerpunkt rechnen und geschlossen
    # verschieben -- sonst zieht die Stauchung sie in die Laenge. Dieselbe Regel wie in
    # `anpassen`, und aus demselben teuer bezahlten Grund.
    for gruppe in _inseln(netz):
        ecken = [netz.vertices[i].co for i in gruppe]
        gross = max(max(p[a] for p in ecken) - min(p[a] for p in ecken) for a in range(3))
        if gross < laenge * STARR_ANTEIL:
            my = sum(p.y for p in ecken) / len(ecken)
            d = neues_y(my) - my
            for i in gruppe:
                v = netz.vertices[i]
                v.co = (v.co.x, v.co.y + d, v.co.z)
        else:
            for i in gruppe:
                v = netz.vertices[i]
                v.co = (v.co.x, neues_y(v.co.y), v.co.z)

    neu = max(v.co.y for v in netz.vertices) - min(v.co.y for v in netz.vertices)
    return laenge - neu, neu
