# Schnuert modul.wasm zu einem MSFS-Community-Paket und legt es in den Community-Ordner.
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
# Nach dem Ablegen muss der Simulator NEU GESTARTET werden.

$ErrorActionPreference = 'Stop'
$hier = $PSScriptRoot
$wasm = "$hier\modul.wasm"
if (-not (Test-Path $wasm)) { throw "modul.wasm fehlt -- erst .\bauen.ps1 laufen lassen." }

$community = "$env:LOCALAPPDATA\Packages\Microsoft.Limitless_8wekyb3d8bbwe\LocalCache\Packages\Community"
if (-not (Test-Path $community)) { throw "Community-Ordner nicht gefunden: $community" }

$paket = Join-Path $community "friesenbruegge-wasm-probe"
New-Item -ItemType Directory -Force "$paket\modules" | Out-Null
Copy-Item $wasm "$paket\modules\modul.wasm" -Force

$groesse = (Get-Item "$paket\modules\modul.wasm").Length

# Windows-FILETIME: 100-Nanosekunden-Schritte seit 1601. layout.json will genau das.
$filetime = (Get-Item "$paket\modules\modul.wasm").LastWriteTimeUtc.ToFileTimeUtc()

@"
{
  "dependencies": [],
  "content_type": "MISC",
  "title": "FriesenBruegge WASM-Probe",
  "manufacturer": "",
  "creator": "FriesenFlieger",
  "package_version": "0.1.0",
  "minimum_game_version": "1.7.35",
  "minimum_compatibility_version": "7.26.0.214",
  "export_type": "Community",
  "builder": "Microsoft Flight Simulator 2024",
  "package_order_hint": "MISC",
  "release_notes": {
    "neutral": {
      "LastUpdate": "",
      "OlderHistory": ""
    }
  },
  "total_package_size": "$groesse"
}
"@ | Set-Content -Path "$paket\manifest.json" -Encoding UTF8

@"
{
  "content": [
    {
      "path": "modules/modul.wasm",
      "size": $groesse,
      "date": $filetime
    }
  ]
}
"@ | Set-Content -Path "$paket\layout.json" -Encoding UTF8

Write-Output "Paket liegt: $paket"
Get-ChildItem $paket -Recurse -File | ForEach-Object { "  {0,8}  {1}" -f $_.Length, $_.FullName.Replace($paket, '') }
Write-Output ""
Write-Output "MSFS 2024 jetzt NEU STARTEN -- Community-Pakete liest der Simulator nur beim Start."
