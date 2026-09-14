# Baut bruegge.cpp zur FriesenBruegge fuer X-Plane 12 (FriesenBruegge.xpl).
#
# Ein X-Plane-Plugin ist eine gewoehnliche Windows-DLL mit der Endung .xpl. Gebraucht werden
# nur die SDK-Header und XPLM_64.lib -- beides im SDK-ZIP enthalten.
#
# Ordnerstruktur, die X-Plane erwartet:
#   <X-Plane>/Resources/plugins/FriesenBruegge/win_x64/FriesenBruegge.xpl
#
# Nach dem Bau muss X-Plane NEU GESTARTET werden -- Plugins liest es nur beim Start.

param(
    # Pfad zur X-Plane-Installation. LEER heisst nicht "nicht installieren", sondern
    # "selbst suchen" -- s. unten.
    [string]$XPlane = "",
    [switch]$NurBauen,                        # ausdruecklich NICHT installieren
    [string]$Sdk = "$env:TEMP\xpsdk\SDK"
)

$ErrorActionPreference = 'Stop'
$hier = $PSScriptRoot
$name = "FriesenBruegge"

if (-not (Test-Path "$Sdk\CHeaders\XPLM\XPLMPlugin.h")) {
    throw @"
SDK nicht gefunden unter $Sdk. Einmalig holen:

  Invoke-WebRequest https://developer.x-plane.com/wp-content/plugins/code-sample-generation/sdk_zip_files/XPSDK430.zip -OutFile `$env:TEMP\XPSDK430.zip
  Expand-Archive `$env:TEMP\XPSDK430.zip `$env:TEMP\xpsdk
"@
}

# ---- MSVC-Umgebung laden --------------------------------------------------
# cl.exe braucht Dutzende Umgebungsvariablen (INCLUDE, LIB, PATH). vcvars64.bat setzt sie;
# damit sie in dieser PowerShell-Sitzung ankommen, wird die Batch in einer cmd ausgefuehrt
# und ihre Umgebung danach ausgelesen.
$vcvars = Get-ChildItem "C:\Program Files\Microsoft Visual Studio" -Recurse -Filter vcvars64.bat -ErrorAction SilentlyContinue |
          Select-Object -First 1 -ExpandProperty FullName
if (-not $vcvars) { throw "vcvars64.bat nicht gefunden -- ist Visual Studio installiert?" }
Write-Output "vcvars: $vcvars"

cmd /c "`"$vcvars`" >nul 2>&1 && set" | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') {
        Set-Item -Path "env:$($matches[1])" -Value $matches[2] -ErrorAction SilentlyContinue
    }
}

# ---- Uebersetzen und Linken ----------------------------------------------
# /utf-8 ist nicht kosmetisch: Ohne die Angabe liest MSVC die Quelldatei als ANSI, und die
# Umlaute in den Kommentaren werden zu Bytefolgen, die der Parser stellenweise falsch
# abgrenzt. Die Datei ist UTF-8 ohne BOM -- wie alles in diesem Projekt.
$xpl = "$hier\$name.xpl"
Push-Location $hier
try {
    & cl.exe /nologo /LD /EHsc /O2 /MT /utf-8 `
        /DIBM=1 /DWIN32 /D_CRT_SECURE_NO_WARNINGS `
        /I"$Sdk\CHeaders\XPLM" /I"$Sdk\CHeaders\Widgets" `
        bruegge.cpp `
        /link /OUT:"$xpl" `
        "$Sdk\Libraries\Win\XPLM_64.lib" `
        winhttp.lib
    if ($LASTEXITCODE -ne 0) { throw "Bau fehlgeschlagen ($LASTEXITCODE)" }
} finally {
    Pop-Location
}

# Die Fassung steht in bruegge.cpp -- EINE Wahrheit. Hier wird sie nur vorgelesen, damit beim
# Bauen sichtbar ist, was gerade entsteht.
$cpp = Get-Content "$hier\bruegge.cpp" -Raw
if ($cpp -match '#define\s+BRUEGGE_VERSION\s+"([0-9.]+)"') { $fassung = $Matches[1] }
Write-Output ("gebaut: {0}  ({1:N0} Bytes, Fassung {2})" -f $xpl, (Get-Item $xpl).Length, $fassung)

# ---- Ins X-Plane legen ----------------------------------------------------
# ---------------------------------------------------------------------------------------
# INSTALLIEREN IST DIE VORGABE, NICHT DIE AUSNAHME.
#
# Hier stand: ohne `-XPlane` wird gebaut und ein Hinweis ausgegeben, wie man installiert.
# Das ging am 14.09.2026 schief -- die Fassung 1.2.0 lag gebaut im Arbeitsordner, waehrend
# im Simulator die alte 1.1.0 lief. Beim Probeflug wurde damit genau das getestet, was sich
# NICHT geaendert hatte. Der Hinweis stand da, wurde gelesen und blieb trotzdem folgenlos.
#
# Das MSFS-Gegenstueck (`msfs\paket.ps1`) macht es seit jeher richtig: Es legt das Paket
# ohne Zutun in den Community-Ordner. Wer nur bauen will, sagt das jetzt ausdruecklich
# (`-NurBauen`) -- die stille Vorgabe darf nicht die sein, bei der nichts ankommt.
# ---------------------------------------------------------------------------------------
if ($NurBauen) {
    Write-Output ""
    Write-Output "Nur gebaut (-NurBauen). Im Simulator laeuft weiter, was dort liegt."
    exit 0
}
if (-not $XPlane) {
    # Die ueblichen Orte durchgehen, statt den Nutzer fragen zu lassen.
    $kandidaten = @("D:\X-Plane 12", "C:\X-Plane 12", "$env:USERPROFILE\X-Plane 12",
                    "E:\X-Plane 12")
    $XPlane = $kandidaten | Where-Object { Test-Path "$_\Resources\plugins" } | Select-Object -First 1
    if (-not $XPlane) {
        Write-Warning "X-Plane nicht gefunden -- gesucht in: $($kandidaten -join ', ')"
        Write-Warning "Mit Pfad aufrufen:  .\bauen.ps1 -XPlane 'D:\X-Plane 12'"
        exit 1
    }
    Write-Output "X-Plane gefunden: $XPlane"
}
if (-not (Test-Path "$XPlane\Resources\plugins")) {
    throw "Kein X-Plane unter $XPlane -- Resources\plugins fehlt."
}
$ziel = Join-Path $XPlane "Resources\plugins\$name\win_x64"
New-Item -ItemType Directory -Force $ziel | Out-Null

# Die eigenen Objekte muessen MIT -- ohne sie meldet die Bruegge fuer `rauch` schlicht
# OBJ_NICHT_GEFUNDEN, und zwar lautlos aus Sicht des Piloten. Sie entstehen aus
# rauch_bauen.py und liegen unter objekte/.
$eigene = Join-Path $hier "objekte"
if (Test-Path $eigene) {
    $objZiel = Join-Path $XPlane "Resources\plugins\$name\objekte"
    New-Item -ItemType Directory -Force $objZiel | Out-Null
    Copy-Item "$eigene\*" $objZiel -Force
    Write-Output ("eigene Objekte: {0} Dateien nach {1}" -f (Get-ChildItem $eigene -File).Count, $objZiel)
} else {
    Write-Warning "objekte/ fehlt -- erst 'py rauch_bauen.py' laufen lassen, sonst kann die Bruegge keinen Rauch setzen."
}
# Laeuft X-Plane, ist die .xpl gesperrt -- dann sagt das Skript das, statt einen
# Zugriffsfehler durchzureichen.
try {
    Copy-Item $xpl "$ziel\$name.xpl" -Force
} catch {
    throw "Kopieren fehlgeschlagen -- laeuft X-Plane noch? ($_)"
}
Write-Output "installiert: $ziel\$name.xpl"
Write-Output "X-Plane jetzt NEU STARTEN -- Plugins werden nur beim Start geladen."
