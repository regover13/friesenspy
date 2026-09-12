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
New-Item -ItemType Directory -Force "$paket\modules" | Out-Null
Copy-Item $wasm "$paket\modules\bruegge.wasm" -Force

$groesse = (Get-Item "$paket\modules\bruegge.wasm").Length

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

# Windows-FILETIME: 100-Nanosekunden-Schritte seit 1601. layout.json will genau das.
$filetime = (Get-Item "$paket\modules\bruegge.wasm").LastWriteTimeUtc.ToFileTimeUtc()

@"
{
  "dependencies": [],
  "content_type": "MISC",
  "title": "FriesenBruegge",
  "manufacturer": "",
  "creator": "devprops",
  "package_version": "$fassung",
  "minimum_game_version": "$(if ($Fuer2020) { '1.38.2' } else { '1.7.35' })",
  "minimum_compatibility_version": "7.26.0.214",
  "export_type": "Community",
  "builder": "$(if ($Fuer2020) { 'Microsoft Flight Simulator' } else { 'Microsoft Flight Simulator 2024' })",
  "package_order_hint": "MISC",
  "release_notes": {
    "neutral": {
      "LastUpdate": "",
      "OlderHistory": ""
    }
  },
  "total_package_size": "$groesse"
}
"@ | ForEach-Object { Schreib-OhneBom "$paket\manifest.json" $_ }

@"
{
  "content": [
    {
      "path": "modules/bruegge.wasm",
      "size": $groesse,
      "date": $filetime
    }
  ]
}
"@ | ForEach-Object { Schreib-OhneBom "$paket\layout.json" $_ }

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
Get-ChildItem $paket -Recurse -File | ForEach-Object { "  {0,8}  {1}" -f $_.Length, $_.FullName.Replace($paket, '') }
Write-Output ""

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
Write-Output "MSFS 2024 jetzt NEU STARTEN -- Community-Pakete liest der Simulator nur beim Start."
