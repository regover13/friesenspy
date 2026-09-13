# Laedt ein in der CI gebautes Bruegge-Paket auf den Server.
#
# Das Schnueren macht dieses Skript seit dem 13.09.2026 NICHT mehr -- es entsteht im
# Workflow `.github/workflows/bruegge-xplane.yml` aus allen drei Plattformen und EINEM
# Commit. Lokal geschnuert hiesse: ein Windows-Binary von heute neben CI-Binaries von
# gestern, und genau dieser Fall hat beim MSFS-Paket schon einmal eine falsche Fassung
# auf die Download-Seite gebracht.
#
# Der Upload bleibt Handarbeit, und zwar mit Absicht: Ein frisch gebautes Paket ist noch
# nicht im Simulator geprueft.
#
# Ablauf:
#   1. Workflow laufen lassen (Actions -> "Bruegge X-Plane bauen" -> Run workflow)
#   2. Artefakt "friesenbruegge-xplane" herunterladen und entpacken
#   3. Unter Windows einmal starten und im Log.txt nachsehen (s. CLAUDE.md)
#   4. .\paket.ps1 -Datei friesenbruegge-xplane.zip

param(
    [Parameter(Mandatory = $true)][string]$Datei
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Datei)) { throw "$Datei gibt es nicht." }

# Derselbe Ort wie das MSFS- und das Kniebrett-ZIP: im Volume neben der Datenbank. KEIN
# Deploy fasst diese Dateien an -- beim Kniebrett-ZIP ist genau das dreimal schiefgegangen,
# der Download lief drei Fassungen hinterher und fiel nur im Browsertest auf.
$ziel = "server:/opt/friesenspy/data/efb/friesenbruegge-xplane.zip"
Write-Output "Lade hoch nach $ziel ..."
& scp -q $Datei $ziel
if ($LASTEXITCODE -eq 0) {
    Write-Output "Hochgeladen. Die Download-Seite liest die Fassung aus dem Archiv."
} else {
    Write-Warning "scp ging schief (Code $LASTEXITCODE) -- die Download-Seite bleibt alt!"
}
