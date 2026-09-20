# Schnuert bruegge.wasm zu einem MSFS-Community-Paket und legt es in den Community-Ordner.
#
# Ein Paket besteht aus drei Dingen: dem Modul unter modules/, einer manifest.json und
# einer layout.json. Die beiden JSON-Dateien erzeugt normalerweise das SDK-Paketwerkzeug --
# hier von Hand, nach dem Vorbild eines nachweislich funktionierenden WASM-Pakets
# (bkiel-ingamepanels-lnm-vr).
#
# WICHTIG: Ein erster Versuch mit einem knappen manifest.json (nur dependencies,
# content_type, title, creator, package_version, minimum_game_version, release_notes)
# wurde vom Simulator STILLSCHWEIGEND uebergangen -- kein Fehler, keine Meldung, das Modul
# lief einfach nicht. Die hier ergaenzten Felder stammen aus dem Vorbild.
#
# +++ KEIN BOM IN DIESEN DATEIEN. Das hat einen ganzen Tag gekostet (12.09.2026). +++
#
# Hier stand `Set-Content -Encoding UTF8`, und das bedeutet in den beiden PowerShell-Zweigen
# etwas VERSCHIEDENES: Windows PowerShell 5.1 schreibt UTF-8 MIT BOM (ef bb bf), PowerShell 7
# ohne. Dasselbe Skript baute also je nach Aufrufweg ein laufendes oder ein totes Paket --
# und tot heisst hier lautlos tot:
#
#   [Packages] RegisterPackage: Package '...friesenbruegge' registered
#   [Packages] Package '...friesenbruegge' mounted
#   MyLibrary init of community package friesenbruegge took 0.0002
#
# Das Paket wird registriert, gemountet und steht in der Content.xml als "Activated" -- der
# Ordner ist ja da. Aber die layout.json laesst sich mit BOM nicht parsen, MSFS findet NULL
# Inhalte (daher die 0.0002 s), sieht die .wasm nie und hat folglich auch nichts, worueber es
# einen Fehler melden koennte. Kein "WASM: Module ... loaded", keine Ausnahme, nichts.
#
# Gegenprobe, die den Fund traegt: KEINES der drei nachweislich laufenden Pakete auf dieser
# Maschine hat ein BOM -- p42-util-gofish, p42-util-flow-pro und unser eigenes
# friesenflieger-friesenspy-efb beginnen alle mit 7b ("{"). Nur die Bruegge hatte ef bb bf.
#
# Deshalb wird ab hier ueber `UTF8Encoding($false)` geschrieben. Das ist in BEIDEN
# PowerShell-Zweigen dasselbe und nicht vom Aufrufweg abhaengig. Und weil ein stiller Fehler
# genau deshalb teuer war, prueft das Skript am Ende selbst nach.
#
# Nach dem Ablegen muss der Simulator NEU GESTARTET werden.

param(
    [switch]$Fuer2020,     # ins Community-Verzeichnis von MSFS 2020 statt 2024
    # Das ZIP gleich auf den VPS schieben. Bewusst NICHT die Vorgabe: Ein frisch gebautes
    # Paket ist noch nicht im Simulator geprueft, und der Upload faellt nach draussen.
    [switch]$Hochladen
)

$ErrorActionPreference = 'Stop'

function Schreib-OhneBom([string]$Pfad, [string]$Text) {
    # .NET statt Set-Content: versionsunabhaengig, und $false heisst "kein BOM".
    [System.IO.File]::WriteAllText($Pfad, $Text, (New-Object System.Text.UTF8Encoding $false))
}
$hier = $PSScriptRoot
$wasm = "$hier\bruegge.wasm"
if (-not (Test-Path $wasm)) { throw "bruegge.wasm fehlt -- erst .\bauen.ps1 laufen lassen." }

$paketordner = if ($Fuer2020) { 'Microsoft.FlightSimulator_8wekyb3d8bbwe' }
               else            { 'Microsoft.Limitless_8wekyb3d8bbwe' }
$community = "$env:LOCALAPPDATA\Packages\$paketordner\LocalCache\Packages\Community"
if (-not (Test-Path $community)) { throw "Community-Ordner nicht gefunden: $community" }

$paket = Join-Path $community "friesenbruegge"

# ---------------------------------------------------------------------------------------
# EIN PAKET, NICHT VIER.
#
# Bis 1.7.0 lagen der Rauch und das Modul in getrennten Community-Ordnern -- das ZIP
# entpackte vier Stueck (friesenbruegge, devprops-friesenrauch, -mat, -vfx), obwohl die
# Anleitung von EINEM Ordner spricht. Das ist keine Kosmetik: Wer nur drei davon
# hineinkopiert, hat eine Bruegge, die auf Titel zeigt, die es bei ihm nicht gibt, und
# merkt es nur daran, dass nichts raucht.
#
# Ein MSFS-Paket ist aber nichts weiter als ein Ordner mit manifest.json, layout.json und
# Inhalten -- WELCHE Inhalte, steht ihm frei. Die drei Rauchpakete belegen `SimObjects\`,
# `MaterialLibs\` und `VisualEffectLibs\`, das Modul `modules\`: vier disjunkte Aeste, die
# sich in einem Baum nicht in die Quere kommen. Sie werden hier zusammengelegt und
# bekommen EINE layout.json ueber alles.
#
# Die drei Paketdefinitionen im Project Editor bleiben, wie sie sind. Sie sind der
# Bauweg, nicht die Auslieferung -- und der Project Editor braucht je AssetGroup-Typ
# seinen eigenen PackageOrderHint (`CUSTOM_VFX` fuer die Effekte, `MISC` fuer den Rest).
# ---------------------------------------------------------------------------------------

# Erst raeumen, dann bauen: Eine Farbe, die aus `rauch_bauen.py` verschwindet, bliebe sonst
# als Leiche im Ordner liegen und in der layout.json stehen. Die Sicherung davor ist das
# Manifest -- geloescht wird nur, was dieses Skript selbst geschrieben hat.
if (Test-Path $paket) {
    $altesManifest = Join-Path $paket "manifest.json"
    if (Test-Path $altesManifest) {
        $alt = [System.IO.File]::ReadAllText($altesManifest) | ConvertFrom-Json
        if ($alt.title -ne 'FriesenBruegge') {
            throw "$paket enthaelt ein fremdes Paket ('$($alt.title)') -- nicht angeruehrt."
        }
    }
    Remove-Item $paket -Recurse -Force
}

New-Item -ItemType Directory -Force "$paket\modules" | Out-Null
Copy-Item $wasm "$paket\modules\bruegge.wasm" -Force

# ---------------------------------------------------------------------------------------
# DER RAUCH KOMMT MIT HINEIN -- sonst zeigt die Bruegge ins Leere.
#
# Seit 1.7.0 bilden die Rauchgattungen auf unsere EIGENEN Titel ab (`FrsRauch_Signalrot`
# und die fuenf anderen). Wer nur das WASM-Modul bekommt, hat diese SimObjects nicht: Die
# Bruegge faellt dann auf Fremdtitel zurueck (Campout, SayIntentions -- die kaum jemand
# installiert hat) oder meldet GATTUNG_UNBEKANNT.
#
# Gebaut werden die drei Teile im Project Editor (`msfs-rauch\FriesenRauch.xml`), nicht
# hier -- `fspackagetool.exe` ist ohne laufenden Simulator nur ein Wrapper, der nichts tut.
# Fehlen sie, bricht das Skript NICHT ab: Ein Bruegge-Update soll auch dann moeglich sein,
# wenn gerade kein Rauch neu gebaut wurde. Es sagt aber deutlich, was fehlt.
#
# Kopiert werden nur die VERZEICHNISSE der Teilpakete. Deren eigene manifest.json und
# layout.json liegen auf oberster Ebene und bleiben liegen -- sie gelten ja nur fuer ihren
# Teil, und im verschmolzenen Paket zaehlt allein die gemeinsame layout.json weiter unten.
# ---------------------------------------------------------------------------------------
$rauchQuelle = Join-Path (Split-Path $PSScriptRoot -Parent) "msfs-rauch\Packages"
$rauchPakete = @("devprops-friesenrauch", "devprops-friesenrauch-mat",
                 "devprops-friesenrauch-vfx")
# (Bis 20.09.2026 gewann hier der hoehere Wert der Rauch-Teile, weil sie mit dem 2024er SDK
# gebaut waren. Jetzt baut das 2020er SDK -- s. bauen.ps1 und die Schleife unten.)
# ⭐ EINE ZAHL FUER BEIDE SIMULATOREN (16.09.2026) -- hier stand sie je Schalter verschieden.
#
# Seit 1.14.0 ist es EIN Paket fuer MSFS 2020 und 2024, also darf es auch nur EIN Manifest
# geben. Die beiden zaehlen getrennt -- MSFS 2020 steht bei 1.39.6 --, aber das Feld ist
# NICHT die Huerde, fuer die ich es zunaechst gehalten habe. Gemessen an den Paketen, die
# auf dieser Platte nachweislich laufen:
#
#   im MSFS-2024-Community-Ordner   1.4.20 ... 1.37.19   (u. a. SayIntentions, 95ermod)
#   im MSFS-2020-Community-Ordner   1.8.3  ... 1.39.12
#
# Beide Simulatoren nehmen also Werte aus dem jeweils anderen Band an; `SayIntentions` liegt
# sogar mit derselben Zahl in beiden. Die niedrige Zahl ist damit die sichere Wahl -- aber
# nicht, weil die hohe abgelehnt WUERDE (das ist ungeprueft und stand hier zunaechst
# faelschlich als Begruendung), sondern weil sie nichts verspricht, was die Inhalte nicht
# halten.
#
# ⚠ Den tatsaechlich gesetzten Wert bestimmt ohnehin der Rauch: Seine Teilpakete tragen
# derzeit 1.8.16, und weiter unten gewinnt der hoehere Wert.
$minSpiel  = [version]'1.7.35'
$minKompat = [version]'7.26.0.214'
$rauchDa = 0
foreach ($rp in $rauchPakete) {
    $pfad = Join-Path $rauchQuelle $rp
    if (-not (Test-Path (Join-Path $pfad "manifest.json"))) {
        Write-Warning ("Rauchpaket fehlt: $rp -- bauen mit msfs-rauch" + [char]92 + "bauen.ps1")
        continue
    }
    Get-ChildItem $pfad -Directory | Copy-Item -Destination $paket -Recurse -Force
    # ⚠ DIE MINDESTVERSION DER TEILE ZAEHLT NICHT MEHR (20.09.2026). Seit die Teile mit dem
    # MSFS-2020-SDK gebaut werden, tragen ihre Manifeste `minimum_game_version 1.39.12` (die
    # Fassung dieses SDK) und keine `minimum_compatibility_version`. Uebernaehme das Paket den
    # hoeheren Wert, verlangte es von MSFS 2024 (steht bei 1.8.x) eine Version, die es dort nie
    # gibt. Gemessen ist nur, dass MSFS 2024 solche Teile akzeptiert hat -- die Testpakete lagen
    # dort mit 1.39.12 und liefen --, aber ein Paket soll nichts verlangen, was ein Simulator
    # gar nicht erreicht. Es bleibt bei den festen Werten oben.
    $rauchDa++
}
if ($rauchDa -eq $rauchPakete.Count) {
    Write-Output "Rauch aufgenommen: alle $rauchDa Teile"
} else {
    Write-Warning "Nur $rauchDa von $($rauchPakete.Count) Rauchteilen -- das Paket bleibt unvollstaendig."
}
# (Bis 20.09.2026 stand hier: "Der Rauch ist fuer MSFS 2024 kompiliert und in MSFS 2020 UNGEPRUEFT."
# Er ist jetzt mit dem 2020er SDK gebaut und in BEIDEN Simulatoren im Flug belegt.)

# Die Paketversion kommt aus BRUEGGE_VERSION in bruegge.cpp -- EINE Wahrheit, nicht zwei.
#
# Hier stand sie fest auf "1.0.0", waehrend das Modul bei 1.5.0 war. Das fiel niemandem auf,
# weil die Zahl nirgends sichtbar war -- bis das Paket auf die Download-Seite kam, die die
# Version AUS DEM ARCHIV liest (`_efb_package_version` in main.py). Dort haette dauerhaft
# 1.0.0 gestanden, und ein Pilot mit alter Fassung haette keinen Grund gesehen, neu zu laden.
$cpp = Get-Content "$hier\bruegge.cpp" -Raw
if ($cpp -match '#define\s+BRUEGGE_VERSION\s+"([0-9.]+)"') {
    $fassung = $Matches[1]
} else {
    throw "BRUEGGE_VERSION nicht in bruegge.cpp gefunden -- das Manifest braucht sie."
}
Write-Output "Fassung aus bruegge.cpp: $fassung"

# ---------------------------------------------------------------------------------------
# DIE LAYOUT.JSON GEHT UEBER ALLES, WAS IM ORDNER LIEGT.
#
# Sie ist das Inhaltsverzeichnis, nach dem MSFS das Paket liest -- was nicht drinsteht,
# existiert fuer den Simulator nicht, auch wenn die Datei danebenliegt. Solange nur die
# .wasm im Paket lag, war sie von Hand zu schreiben; jetzt sind es ueber sechzig Dateien.
#
# Die Pfade stehen KLEINGESCHRIEBEN und mit Schraegstrichen -- so schreibt sie auch das
# SDK-Paketwerkzeug (nachgesehen in den drei Rauch-layouts, dort steht
# `visualeffectlibs/devprops/friesenrauch/frsrauch_navy.spb`, obwohl die Datei auf der
# Platte `FrsRauch_Navy.spb` heisst). `date` ist Windows-FILETIME: 100-Nanosekunden-
# Schritte seit 1601, je Datei ihre eigene.
# ---------------------------------------------------------------------------------------
$dateien = Get-ChildItem $paket -Recurse -File | Sort-Object FullName
$eintraege = foreach ($d in $dateien) {
    $rel = $d.FullName.Substring($paket.Length + 1).Replace('\', '/').ToLowerInvariant()
    '    {{
      "path": "{0}",
      "size": {1},
      "date": {2}
    }}' -f $rel, $d.Length, $d.LastWriteTimeUtc.ToFileTimeUtc()
}
$groesse = ($dateien | Measure-Object -Property Length -Sum).Sum

# ⚠ FALLS ES NACH DEM VERSCHMELZEN NICHT MEHR RAUCHT, steht der erste Verdacht unten im
# Manifest: `package_order_hint`. Als Einzelpakete standen die Effekte auf `CUSTOM_VFX`,
# SimObjects und Material auf `MISC`. Der Hint sortiert die Ladereihenfolge ZWISCHEN
# Paketen; innerhalb eines Pakets sollte er gegenstandslos sein -- geprueft ist das aber
# nicht. Der Versuch waere, hier `CUSTOM_VFX` einzusetzen. Nichts anderes gleichzeitig
# aendern, sonst ist hinterher nicht klar, woran es lag.

@"
{
  "dependencies": [],
  "content_type": "MISC",
  "title": "FriesenBruegge",
  "manufacturer": "",
  "creator": "devprops",
  "package_version": "$fassung",
  "minimum_game_version": "$minSpiel",
  "minimum_compatibility_version": "$minKompat",
  "export_type": "Community",
  "builder": "Microsoft Flight Simulator 2024",
  "package_order_hint": "MISC",
  "release_notes": {
    "neutral": {
      "LastUpdate": "Seehund-Modelle aus \"Walrus\" von Poly by Google (poly.pizza/m/5T7nIjx9ekP), CC BY 3.0, bearbeitet. Rauchsaeulen: eigenes Werk devprops.",
      "OlderHistory": ""
    }
  },
  "total_package_size": "$groesse"
}
"@ | ForEach-Object { Schreib-OhneBom "$paket\manifest.json" $_ }

# ⚠⚠ NAMENSNENNUNG -- DIE EINZIGE BEDINGUNG DER LIZENZ, UND SIE FEHLTE BEINAHE.
#
# Das Seehund-Modell stammt aus "Walrus" von Poly by Google unter CC BY 3.0. Diese Lizenz
# erlaubt Aenderung und Weitergabe ausdruecklich -- Bedingung ist allein die Nennung des
# Urhebers UND der Hinweis, dass bearbeitet wurde.
#
# Solange das Paket nur auf einem Rechner lag, war das gegenstandslos. Am 14.09.2026 stand
# es unmittelbar vor dem Hochladen an die Gruppe, ohne eine einzige Zeile dazu -- aufgefallen
# ist es der Nebensitzung, nicht mir, und zwar Minuten vorher.
#
# Der Hinweis steht an ZWEI Stellen, weil beide verschiedene Leute erreichen:
#   * CREDITS.txt im Paketordner -- lesbar ohne Simulator, ueberlebt das Auspacken
#   * release_notes im manifest.json -- das zeigt MSFS im Content Manager an
$credits = @"
Die FriesenBruegge -- Herkunft der mitgelieferten Modelle

Seehund (FrsSeehund_Bulle / _Kuh / _Heuler)
    aus "Walrus" von Poly by Google
    https://poly.pizza/m/5T7nIjx9ekP
    Lizenz: CC BY 3.0 -- https://creativecommons.org/licenses/by/3.0/
    BEARBEITET: Stosszaehne entfernt, Proportionen und Kopf auf Phoca vitulina
    geaendert, neu texturiert.

Rauchsaeulen (FrsRauch_*)
    Eigenes Werk, devprops. Textur und Partikelsystem von Hand erzeugt
    (msfs-rauch/rauch_bauen.py, msfs-rauch/paket_bauen.py).

Alles Uebrige verweist nur auf Titel, die im Simulator bereits vorhanden sind --
mitgeliefert wird davon nichts.
"@
Schreib-OhneBom "$paket\CREDITS.txt" $credits

Schreib-OhneBom "$paket\layout.json" (@"
{
  "content": [
$($eintraege -join ",`n")
  ]
}
"@)

# Die Selbstpruefung. Sie ist kein Zierat: Der Fehler, den sie faengt, aeussert sich im
# Simulator ueberhaupt nicht -- weder als Meldung noch als Ausnahme. Wer ihn nicht HIER
# bemerkt, bemerkt ihn erst nach einem Sim-Neustart, und dann sieht er nur: nichts.
foreach ($datei in @("$paket\manifest.json", "$paket\layout.json")) {
    $kopf = [System.IO.File]::ReadAllBytes($datei)[0..2]
    if ($kopf[0] -eq 0xEF -and $kopf[1] -eq 0xBB -and $kopf[2] -eq 0xBF) {
        throw "BOM in $datei -- MSFS wuerde das Paket lautlos uebergehen. Nicht ausliefern."
    }
    # Und gleich noch pruefen, dass es ueberhaupt gueltiges JSON ist.
    try { [System.IO.File]::ReadAllText($datei) | ConvertFrom-Json | Out-Null }
    catch { throw "Kaputtes JSON in ${datei}: $_" }
}
Write-Output "JSON geprueft: kein BOM, parsebar."

Write-Output "Paket liegt: $paket"
Write-Output ("  {0} Dateien, {1:N0} Bytes -- Mindestfassung {2}" -f $dateien.Count, $groesse, $minSpiel)
Get-ChildItem $paket -Directory | ForEach-Object {
    $n = (Get-ChildItem $_.FullName -Recurse -File | Measure-Object).Count
    "  {0,-20} {1,3} Dateien" -f ($_.Name + '\'), $n
}
Write-Output ""

# ---------------------------------------------------------------------------------------
# ALTE EINZELPAKETE WEGRAEUMEN -- zwei Quellen fuer denselben Titel sind eine zu viel.
#
# Bis 1.7.0 lagen `devprops-friesenrauch`, `-mat` und `-vfx` als eigene Ordner im
# Community-Verzeichnis. Ihre Inhalte stecken jetzt in `friesenbruegge`; bleiben sie
# liegen, kennt der Simulator jeden Titel (`FrsRauch_Navy` ...) zweimal und jede
# Effektbibliothek doppelt.
#
# Geloescht wird nur, was sich im eigenen Manifest als unseres ausweist -- Creator
# `devprops` und ein Titel, der mit `friesenrauch` beginnt. Alles andere im
# Community-Ordner gehoert jemand anderem und wird nicht angefasst.
# ---------------------------------------------------------------------------------------
foreach ($rp in $rauchPakete) {
    $altPfad = Join-Path $community $rp
    $altManifest = Join-Path $altPfad "manifest.json"
    if (-not (Test-Path $altManifest)) { continue }
    $am = [System.IO.File]::ReadAllText($altManifest) | ConvertFrom-Json
    if ($am.creator -eq 'devprops' -and $am.title -like 'friesenrauch*') {
        Remove-Item $altPfad -Recurse -Force
        Write-Output "Alten Einzelordner entfernt: $rp (steckt jetzt in friesenbruegge)"
    } else {
        Write-Warning "$rp im Community-Ordner ist nicht unseres -- stehen gelassen."
    }
}

# ---------------------------------------------------------------------------------------
# Das ZIP fuer die Download-Seite -- IMMER mitgebaut, nicht auf Zuruf.
#
# Warum automatisch: Das ZIP liegt von Hand auf dem VPS, und KEIN Deploy fasst es an. Beim
# EFB-Paket ist genau das dreimal schiefgegangen -- der Download lief drei Fassungen hinterher
# und fiel nur im Browsertest auf. Wer sich merken muss, ein ZIP zu bauen, vergisst es; wer es
# ohnehin bekommt, muss es nur noch hochladen.
#
# Der Upload bleibt bewusst ein eigener Schritt (`-Hochladen`): Er faellt nach draussen, und
# ein Paket, das gerade erst gebaut wurde, ist noch nicht im Simulator geprueft.
# ---------------------------------------------------------------------------------------
$zip = Join-Path (Split-Path $hier -Parent) "friesenbruegge.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }

# Ein Ordner, nicht vier -- der Rauch steckt seit 1.7.1 mit drin. Die Anleitung auf der
# Download-Seite sagt "den Ordner friesenbruegge in den Community-Ordner", und ab hier
# stimmt das auch wieder.
Compress-Archive -Path $paket -DestinationPath $zip -CompressionLevel Optimal
$zg = (Get-Item $zip).Length
Write-Output ("ZIP gebaut:  {0}  ({1:N0} Bytes, Fassung {2})" -f $zip, $zg, $fassung)

if ($Hochladen) {
    # Der Pfad ist derselbe wie beim EFB-ZIP -- beide liegen im Volume neben der Datenbank.
    $ziel = "server:/opt/friesenspy/data/efb/friesenbruegge.zip"
    Write-Output "Lade hoch nach $ziel ..."
    & scp -q $zip $ziel
    if ($LASTEXITCODE -eq 0) {
        Write-Output "Hochgeladen. Die Download-Seite zeigt jetzt Fassung $fassung."
    } else {
        Write-Warning "scp ging schief (Code $LASTEXITCODE) -- die Download-Seite bleibt alt!"
    }
} else {
    Write-Output ""
    Write-Output "Noch NICHT auf der Download-Seite. Wenn das Paket im Simulator geprueft ist:"
    Write-Output "    .\paket.ps1 -Hochladen"
    Write-Output "  oder von Hand:  scp `"$zip`" server:/opt/friesenspy/data/efb/"
}

Write-Output ""
Write-Output ("$(if ($Fuer2020) { 'MSFS 2020' } else { 'MSFS 2024' }) jetzt NEU STARTEN -- " +
              "Community-Pakete liest der Simulator nur beim Start.")
