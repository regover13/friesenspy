# build-package.ps1 -- baut msfs-panel/Package/ aus PackageSources/FriesenSpy/dist.
# Ausfuehren aus msfs-panel/ (oder per vollem Pfad, Skript ist ortsunabhaengig via $PSScriptRoot).
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$dist = Join-Path $root "PackageSources\FriesenSpy\dist"
$manifestSrc = Join-Path $root "PackageSources\FriesenSpy\manifest.json"
$pkg = Join-Path $root "Package"
$appOut = Join-Path $pkg "html_ui\efb_ui\efb_apps\FriesenSpy"
$layoutGen = "D:\User\Tobias\OneDrive\GIT\ga-inventory\MSFSLayoutGenerator.exe"

if (-not (Test-Path $dist)) {
    throw "dist-Ordner fehlt: $dist -- erst 'npm run build' in PackageSources\FriesenSpy ausfuehren (Task 2)."
}
if (-not (Test-Path $layoutGen)) {
    throw "MSFSLayoutGenerator.exe nicht gefunden unter: $layoutGen"
}

if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
New-Item -ItemType Directory -Path $appOut -Force | Out-Null

Copy-Item -Path (Join-Path $dist "*") -Destination $appOut -Recurse -Force
Copy-Item -Path $manifestSrc -Destination (Join-Path $pkg "manifest.json") -Force

$layoutJson = Join-Path $pkg "layout.json"
Set-Content -Path $layoutJson -Value "{}" -Encoding UTF8 -NoNewline

# MSFSLayoutGenerator.exe wird mit relativem Dateinamen aus dem Package-Ordner heraus
# aufgerufen, nicht mit absolutem Pfad -- das ist die einzige tatsaechlich verifizierte
# Nutzung des Tools (s. ga-inventory/CLAUDE.md: "cd <Package>; ..\MSFSLayoutGenerator.exe
# layout.json"). Ein absoluter Pfad aus fremdem cwd wurde nicht getestet.
Push-Location $pkg
& $layoutGen "layout.json"
Pop-Location

Write-Output "Package gebaut: $pkg"
