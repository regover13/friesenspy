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

param([switch]$Fuer2020)     # ins Community-Verzeichnis von MSFS 2020 statt 2024

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

# Windows-FILETIME: 100-Nanosekunden-Schritte seit 1601. layout.json will genau das.
$filetime = (Get-Item "$paket\modules\bruegge.wasm").LastWriteTimeUtc.ToFileTimeUtc()

@"
{
  "dependencies": [],
  "content_type": "MISC",
  "title": "FriesenBruegge",
  "manufacturer": "",
  "creator": "devprops",
  "package_version": "1.0.0",
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
Write-Output "MSFS 2024 jetzt NEU STARTEN -- Community-Pakete liest der Simulator nur beim Start."
