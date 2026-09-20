# Baut den Rauch und den Seehund mit dem MSFS-2020-SDK -- fuer BEIDE Simulatoren.
#
# (Bis 20.09.2026 baute dieses Skript mit dem 2024er SDK und startete MSFS 2024 sichtbar. Das
# Ergebnis lief in MSFS 2020 nicht: rosa Seehunde -- KTX2-Texturen --, kein Rauch -- die 2024er
# Behavior-Vorlage. Der Bau mit dem 2020er SDK laeuft in beiden, im Flug belegt.)
#
# ⚠⚠ AUCH DAS 2020er WERKZEUG STARTET DEN SIMULATOR -- im Baumodus, ohne Fenster.
#
# Gemessen am 20.09.2026: `fspackagetool.exe` ruft `FlightSimulator.exe -I ; BuildAssetPackages
# <Projekt> ...` auf, und dieser Prozess bleibt nach dem Bau stehen. Wer nur das Werkzeug
# beendet, laesst den Simulator zurueck -- und der naechste Bau kommt dann nicht durch (er
# schrieb NICHTS, 200 Sekunden lang). Deshalb raeumt dieses Skript vier Prozesse ab, wie
# `bauen.ps1` es fuer 2024 tut; hier heisst der Simulator `FlightSimulator`, nicht
# `FlightSimulator2024`.
#
# ⚠ NICHT AUFRUFEN, WAEHREND JEMAND IM SIMULATOR SITZT (Nutzer, 20.09.2026: "ich bin in SIM
# kein kompellieren!"). Der Bau laeuft rund eine Minute, belastet den Rechner und startet einen
# zweiten Simulatorprozess -- erst ansagen, dann bauen. Das Skript bricht ab, wenn schon ein
# Simulator laeuft.
#
# Der Bau nimmt FriesenRauch.xml, die `paket_bauen.py` zusammen mit den Quellen erzeugt.
param(
    [int]$MaxMinuten = 8,     # Notbremse
    [switch]$Trotzdem         # nur wenn der Nutzer es ausdruecklich will
)

$ErrorActionPreference = 'Stop'
$hier = $PSScriptRoot
$sdk2020 = $env:MSFS_SDK; if (-not $sdk2020) { $sdk2020 = 'D:\MSFS SDK' }
$werkzeug = Join-Path $sdk2020 'Tools\bin\fspackagetool.exe'
if (-not (Test-Path $werkzeug)) { throw "fspackagetool (2020) nicht gefunden: $werkzeug" }
if (-not (Test-Path "$hier\FriesenRauch.xml")) {
    throw "FriesenRauch.xml fehlt -- erst 'python paket_bauen.py' ausfuehren."
}

function Raeum-Auf {
    Get-Process fspackagetool, FlightSimulator, gamelaunchhelper, gamingservicesui -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

$laeuft = Get-Process FlightSimulator, FlightSimulator2024 -ErrorAction SilentlyContinue
if ($laeuft -and -not $Trotzdem) {
    throw "Ein Simulator laeuft ($(($laeuft | ForEach-Object Name) -join ', ')) -- nicht bauen, solange jemand drinsitzt."
}
Raeum-Auf
Start-Sleep -Seconds 2

# Der Bau merkt sich Zeitstempel: Eine geaenderte Textur oder Datei wird sonst nicht immer
# neu gebaut (die abgedunkelte Seehund-Textur blieb beim ersten Versuch unberuehrt).
foreach ($d in 'Packages\devprops-friesenrauch', 'Packages\devprops-friesenrauch-mat', 'Packages\devprops-friesenrauch-vfx', '_PackageInt') {
    $x = Join-Path $hier $d
    if (Test-Path -LiteralPath $x) { Remove-Item -LiteralPath $x -Recurse -Force }
}

$start = Get-Date
Write-Output "Baue Rauch und Seehund -- der Simulator startet dabei im Baumodus (ohne Fenster)."
$auftrag = Start-Job -ScriptBlock {
    param($w, $d)
    Set-Location $d
    & $w "FriesenRauch.xml" 2>&1 | Out-String
} -ArgumentList $werkzeug, $hier

# Fertig ist der Bau, wenn die letzten Dateien der drei Teilpakete da sind und eine Weile
# nichts mehr geschrieben wurde -- der Prozess endet ja nicht von selbst.
$erwartet = @(
    "$hier\Packages\devprops-friesenrauch-vfx\VisualEffectLibs\devprops\friesenrauch\VisualEffectLibrary.xml",
    "$hier\Packages\devprops-friesenrauch-mat\MaterialLibs\friesenrauch-mat\Library.xml",
    "$hier\Packages\devprops-friesenrauch\SimObjects\Misc\FrsSeehund\texture\SEEHUND.PNG.DDS.json"
)
$RuheSekunden = 20
$fertig = $false
while (((Get-Date) - $start).TotalMinutes -lt $MaxMinuten) {
    Start-Sleep -Seconds 5
    if (@($erwartet | Where-Object { Test-Path $_ }).Count -eq $erwartet.Count) {
        # ⚠ NICHT `Get-ChildItem "...\devprops-friesenrauch*" -Recurse`: Ein Platzhalter im Pfad
        # durchsucht die Unterordner nicht -- das lieferte nichts, die Ruhe-Erkennung schlug nie an,
        # und das Skript wartete jedes Mal die vollen acht Minuten (20.09.2026, zweimal).
        $neueste = Get-ChildItem "$hier\Packages" -Recurse -File -ErrorAction SilentlyContinue |
                   Where-Object { $_.FullName -like '*devprops-friesenrauch*' } |
                   Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($neueste -and ((Get-Date) - $neueste.LastWriteTime).TotalSeconds -ge $RuheSekunden) { $fertig = $true; break }
    }
}

Start-Sleep -Seconds 3
Raeum-Auf
Remove-Job $auftrag -Force -ErrorAction SilentlyContinue
$noch = Get-Process fspackagetool, FlightSimulator, gamelaunchhelper, gamingservicesui -ErrorAction SilentlyContinue
if ($noch) { Write-Warning "Prozess noch da: $(($noch | ForEach-Object Name) -join ', ')" }

$dauer = [int]((Get-Date) - $start).TotalSeconds
if ($fertig) {
    Write-Output "Rauch und Seehund gebaut nach $dauer s. Simulator beendet."
} else {
    Write-Output "NICHT fertig nach $dauer s -- unter Packages\ nachsehen."
    exit 1
}
