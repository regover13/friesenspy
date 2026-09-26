# Schnuert probe.wasm zu einem EIGENEN Community-Paket `friesenprobe` (nicht `friesenbruegge`:
# sonst teilten sich Probe und Bruegge denselben \work-Ordner) und legt es in den Community-
# Ordner. Vorbild: ../msfs/paket.ps1 -- dort steht, warum KEIN BOM in die JSON-Dateien darf.
#
#   .\probe_paket.ps1                 # MSFS 2024
#   .\probe_paket.ps1 -Fuer2020       # MSFS 2020
#   .\probe_paket.ps1 -Entfernen [-Fuer2020]   # Probe-Paket wieder loeschen (Schritt 6)
#
# Nach dem Ablegen muss der Simulator NEU GESTARTET werden.

param(
    [switch]$Fuer2020,
    [switch]$Entfernen
)

$ErrorActionPreference = 'Stop'

function Schreib-OhneBom([string]$Pfad, [string]$Text) {
    [System.IO.File]::WriteAllText($Pfad, $Text, (New-Object System.Text.UTF8Encoding $false))
}

$hier = $PSScriptRoot
$wasm = "$hier\probe.wasm"

$paketordner = if ($Fuer2020) { 'Microsoft.FlightSimulator_8wekyb3d8bbwe' }
               else            { 'Microsoft.Limitless_8wekyb3d8bbwe' }
$community = "$env:LOCALAPPDATA\Packages\$paketordner\LocalCache\Packages\Community"
if (-not (Test-Path $community)) { throw "Community-Ordner nicht gefunden: $community" }
$paket = Join-Path $community 'friesenprobe'

if ($Entfernen) {
    if (Test-Path $paket) { Remove-Item $paket -Recurse -Force; Write-Output "Entfernt: $paket" }
    else { Write-Output "Nichts zu entfernen: $paket" }
    return
}

if (-not (Test-Path $wasm)) { throw "probe.wasm fehlt -- erst .\probe_bauen.ps1 laufen lassen." }

if (Test-Path $paket) {
    $altesManifest = Join-Path $paket 'manifest.json'
    if (Test-Path $altesManifest) {
        $alt = [System.IO.File]::ReadAllText($altesManifest) | ConvertFrom-Json
        if ($alt.title -ne 'FriesenProbe') { throw "$paket enthaelt ein fremdes Paket ('$($alt.title)') -- nicht angeruehrt." }
    }
    Remove-Item $paket -Recurse -Force
}

New-Item -ItemType Directory -Force "$paket\modules" | Out-Null
Copy-Item $wasm "$paket\modules\probe.wasm" -Force

$d = Get-Item "$paket\modules\probe.wasm"
$eintrag = '    {{
      "path": "modules/probe.wasm",
      "size": {0},
      "date": {1}
    }}' -f $d.Length, $d.LastWriteTimeUtc.ToFileTimeUtc()

# Dieselben Manifest-Felder wie bei der Bruegge (ein knappes Manifest wird lautlos uebergangen).
Schreib-OhneBom "$paket\manifest.json" @"
{
  "dependencies": [],
  "content_type": "MISC",
  "title": "FriesenProbe",
  "manufacturer": "",
  "creator": "devprops",
  "package_version": "1.0.0",
  "minimum_game_version": "1.7.35",
  "minimum_compatibility_version": "7.26.0.214",
  "export_type": "Community",
  "builder": "Microsoft Flight Simulator 2024",
  "package_order_hint": "MISC",
  "release_notes": {
    "neutral": {
      "LastUpdate": "Messprobe: Haelt eine fopen-Datei im work-Ordner einen Neustart?",
      "OlderHistory": ""
    }
  },
  "total_package_size": "$($d.Length)"
}
"@

Schreib-OhneBom "$paket\layout.json" @"
{
  "content": [
$eintrag
  ]
}
"@

foreach ($datei in @("$paket\manifest.json", "$paket\layout.json")) {
    $kopf = [System.IO.File]::ReadAllBytes($datei)[0..2]
    if ($kopf[0] -eq 0xEF -and $kopf[1] -eq 0xBB -and $kopf[2] -eq 0xBF) { throw "BOM in $datei" }
    [System.IO.File]::ReadAllText($datei) | ConvertFrom-Json | Out-Null
}
Write-Output "Paket liegt: $paket (JSON geprueft: kein BOM, parsebar)"
Write-Output ("$(if ($Fuer2020) { 'MSFS 2020' } else { 'MSFS 2024' }) jetzt NEU STARTEN.")
