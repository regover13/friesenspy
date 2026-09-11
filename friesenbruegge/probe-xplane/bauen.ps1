# Baut plugin.cpp zu einem X-Plane-Plugin (win.xpl) und legt es in den Plugin-Ordner.
#
# Ein X-Plane-Plugin ist eine ganz normale Windows-DLL mit der Endung .xpl. Gebraucht
# werden nur die SDK-Header und XPLM_64.lib -- alles im SDK-ZIP enthalten.
#
# Ordnerstruktur, die X-Plane erwartet:
#   <X-Plane>/Resources/plugins/FriesenBrueggeProbe/win_x64/FriesenBrueggeProbe.xpl
#
# X-Plane laedt Plugins beim Start. Nach dem Bau muss der Simulator NEU GESTARTET werden.

param(
    [string]$XPlane = "",           # Pfad zur X-Plane-Installation
    [string]$Sdk = "$env:TEMP\xpsdk\SDK"
)

$ErrorActionPreference = 'Stop'
$hier = $PSScriptRoot
$name = "FriesenBrueggeProbe"

if (-not (Test-Path "$Sdk\CHeaders\XPLM\XPLMPlugin.h")) {
    throw "SDK nicht gefunden unter $Sdk -- XPSDK430.zip dorthin entpacken."
}

# ---- MSVC-Umgebung laden --------------------------------------------------
# cl.exe braucht Dutzende Umgebungsvariablen (INCLUDE, LIB, PATH). vcvars64.bat setzt
# sie; damit sie in dieser PowerShell-Sitzung ankommen, wird die Batch in einer cmd
# ausgefuehrt und ihre Umgebung danach ausgelesen.
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
$xpl = "$hier\$name.xpl"
Push-Location $hier
try {
    & cl.exe /nologo /LD /EHsc /O2 /MT `
        /DIBM=1 /DWIN32 /D_CRT_SECURE_NO_WARNINGS `
        /I"$Sdk\CHeaders\XPLM" /I"$Sdk\CHeaders\Widgets" `
        plugin.cpp `
        /link /OUT:"$xpl" `
        "$Sdk\Libraries\Win\XPLM_64.lib" `
        ws2_32.lib
    if ($LASTEXITCODE -ne 0) { throw "Bau fehlgeschlagen ($LASTEXITCODE)" }
} finally {
    Pop-Location
}
Write-Output "gebaut: $xpl  ($((Get-Item $xpl).Length) Bytes)"

# ---- Ins X-Plane legen ----------------------------------------------------
if (-not $XPlane) {
    Write-Output ""
    Write-Output "Kein -XPlane angegeben. Zum Installieren:"
    Write-Output "  .\bauen.ps1 -XPlane 'D:\X-Plane 12'"
    exit 0
}
$ziel = Join-Path $XPlane "Resources\plugins\$name\win_x64"
New-Item -ItemType Directory -Force $ziel | Out-Null
Copy-Item $xpl "$ziel\$name.xpl" -Force
Write-Output "installiert: $ziel\$name.xpl"
Write-Output "X-Plane jetzt NEU STARTEN -- Plugins werden nur beim Start geladen."
