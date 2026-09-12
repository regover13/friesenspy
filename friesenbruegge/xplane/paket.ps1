# Schnuert FriesenBruegge.xpl zu einem ZIP fuer die Download-Seite.
#
# Anders als bei MSFS gibt es hier kein Manifest und keine layout.json -- X-Plane braucht nur
# den richtigen Ordner. Das ZIP traegt deshalb genau die Struktur, die der Pilot in
# <X-Plane>/Resources/plugins/ entpackt:
#
#   FriesenBruegge/
#     win_x64/
#       FriesenBruegge.xpl
#     LIESMICH.txt
#
# Der Upload bleibt ein eigener Schritt (-Hochladen): Er faellt nach draussen, und ein Paket,
# das gerade erst gebaut wurde, ist noch nicht im Simulator geprueft.

param(
    [switch]$Hochladen
)

$ErrorActionPreference = 'Stop'
$hier = $PSScriptRoot
$name = "FriesenBruegge"
$xpl = "$hier\$name.xpl"
if (-not (Test-Path $xpl)) { throw "$name.xpl fehlt -- erst .\bauen.ps1 laufen lassen." }

# Die Fassung kommt aus BRUEGGE_VERSION in bruegge.cpp -- EINE Wahrheit, nicht zwei. Beim
# MSFS-Paket stand sie eine Zeit lang fest auf 1.0.0, waehrend das Modul bei 1.5.0 war; auf
# der Download-Seite haette dauerhaft die falsche Zahl gestanden, und ein Pilot mit alter
# Fassung haette keinen Grund gesehen, neu zu laden.
$cpp = Get-Content "$hier\bruegge.cpp" -Raw
if ($cpp -match '#define\s+BRUEGGE_VERSION\s+"([0-9.]+)"') {
    $fassung = $Matches[1]
} else {
    throw "BRUEGGE_VERSION nicht in bruegge.cpp gefunden."
}

# Im Temp zusammenstellen, damit im Repo nichts liegen bleibt.
$bau = Join-Path $env:TEMP "bruegge-xplane-$([guid]::NewGuid().ToString('N').Substring(0,8))"
$ordner = Join-Path $bau $name
New-Item -ItemType Directory -Force "$ordner\win_x64" | Out-Null
Copy-Item $xpl "$ordner\win_x64\$name.xpl" -Force

# Eine Begleitdatei, die X-Plane nicht kennt und nicht braucht: Die Download-Seite liest die
# Version AUS DEM ARCHIV (`_efb_package_version` in main.py), damit die angezeigte gar nicht
# erst von der ausgelieferten abweichen kann. Ein MSFS-Paket hat dafuer seine manifest.json --
# ein X-Plane-Plugin hat nichts dergleichen, also kommt hier eine dazu.
$fassungsdatei = @"
{
  "package_version": "$fassung",
  "simulator": "xplane12",
  "creator": "devprops"
}
"@
[System.IO.File]::WriteAllText((Join-Path $ordner "fassung.json"), $fassungsdatei,
                               (New-Object System.Text.UTF8Encoding $false))

$liesmich = @"
Die FriesenBruegge fuer X-Plane 12 -- Fassung $fassung

EINBAUEN
  Diesen Ordner ($name) nach <X-Plane 12>\Resources\plugins\ kopieren, sodass am Ende
  diese Datei liegt:

      <X-Plane 12>\Resources\plugins\$name\win_x64\$name.xpl

  Danach X-Plane NEU STARTEN. Plugins liest der Simulator nur beim Start.

WAS SIE TUT
  Sie meldet die eigene Position im Sekundentakt an FriesenSpy -- damit steht das Flugzeug
  auf der Karte, ohne dass das Kniebrett offen sein muss. Und sie setzt, was der Server
  anfordert: Tiere, Boote, Bauwerke, Marken.

  Ohne VATSIM geschieht nichts. Wer nicht eingeloggt ist, erscheint nicht -- unabhaengig
  davon, was hier installiert ist.

NUR WINDOWS
  Diese Fassung laeuft auf Windows. macOS und Linux brauchen eine andere Netzschicht
  (HTTPS); wer sie braucht, sagt Bescheid.

NACHSEHEN, OB SIE LAEUFT
  In <X-Plane 12>\Log.txt steht nach dem Start eine Zeile:

      [FriesenBruegge] Fassung $fassung geladen.

devprops.de -- fuer die FriesenFlieger
"@
[System.IO.File]::WriteAllText("$ordner\LIESMICH.txt", $liesmich,
                               (New-Object System.Text.UTF8Encoding $false))

$zip = Join-Path (Split-Path $hier -Parent) "friesenbruegge-xplane.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $ordner -DestinationPath $zip -CompressionLevel Optimal
Remove-Item $bau -Recurse -Force

$zg = (Get-Item $zip).Length
Write-Output ("ZIP gebaut:  {0}  ({1:N0} Bytes, Fassung {2})" -f $zip, $zg, $fassung)

if ($Hochladen) {
    # Derselbe Ort wie das MSFS- und das Kniebrett-ZIP: im Volume neben der Datenbank. KEIN
    # Deploy fasst diese Dateien an -- beim Kniebrett-ZIP ist genau das dreimal schiefgegangen,
    # der Download lief drei Fassungen hinterher und fiel nur im Browsertest auf.
    $ziel = "server:/opt/friesenspy/data/efb/friesenbruegge-xplane.zip"
    Write-Output "Lade hoch nach $ziel ..."
    & scp -q $zip $ziel
    if ($LASTEXITCODE -eq 0) {
        Write-Output "Hochgeladen. Die Download-Seite zeigt jetzt Fassung $fassung."
    } else {
        Write-Warning "scp ging schief (Code $LASTEXITCODE) -- die Download-Seite bleibt alt!"
    }
} else {
    Write-Output ""
    Write-Output "Noch NICHT auf der Download-Seite. Wenn das Plugin im Simulator geprueft ist:"
    Write-Output "    .\paket.ps1 -Hochladen"
}
