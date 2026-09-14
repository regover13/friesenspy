# Baut die Rauch-Effekte und raeumt hinter sich auf.
#
# ⚠⚠ DER BAU STARTET DEN SIMULATOR -- SICHTBAR, MIT FENSTER.
#
# `fspackagetool.exe` ist nur ein Starter; die eigentliche Arbeit macht MSFS 2024 selbst im
# Baumodus. Auf dem Bildschirm erscheint der normale Startbildschirm ("Spiel wird
# gestartet... (2 Min. 24 Sek.)"), und NACH dem Bau beendet sich der Prozess NICHT von
# selbst -- das Fenster bleibt stehen, bis jemand es wegraeumt.
#
# Am 14.09.2026 sechsmal passiert, jedes Mal musste der Nutzer es von Hand schliessen
# ("das screenshot ding startest du immer! ich muss es immer von hand beenden"). Dieses
# Skript gibt es, damit das nicht mehr von der Sorgfalt des Aufrufers abhaengt.
#
# ⚠ NICHT AUFRUFEN, WAEHREND JEMAND FLIEGT. Der Simulator-Start kommt einer laufenden
# Sitzung dazwischen. Erst ansagen, dann bauen.
param(
    [int]$MaxMinuten = 10    # Notbremse, falls der Bau wirklich haengt
)

$ErrorActionPreference = 'Stop'
$hier = $PSScriptRoot
$werkzeug = "C:\MSFS 2024 SDK\Tools\bin\fspackagetool.exe"
if (-not (Test-Path $werkzeug)) { throw "fspackagetool nicht gefunden: $werkzeug" }

function Raeum-Auf {
    Get-Process fspackagetool, FlightSimulator2024, gamelaunchhelper -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

# Altlasten zuerst: Laeuft noch ein Bauprozess, endet der naechste Aufruf sofort mit Exit 43,
# ohne zu bauen -- das hat am 14.09.2026 zweimal wie ein Fehler ausgesehen und war keiner.
Raeum-Auf
Start-Sleep -Seconds 2

$spb = "$hier\Packages\devprops-friesenrauch-vfx\VisualEffectLibs\devprops\friesenrauch"
$start = Get-Date
Write-Output "Baue -- MSFS startet dabei sichtbar, das dauert ein paar Minuten."

# ⚠ MIT `&` STARTEN, NICHT MIT `Start-Process -NoNewWindow`. Letzteres startet den Prozess
# zwar, aber er schreibt keine einzige Datei -- am 14.09.2026 dreimal belegt (8 Minuten
# Laufzeit, null Ergebnis). Offenbar braucht das Werkzeug die Konsole des Aufrufers.
$auftrag = Start-Job -ScriptBlock {
    param($w, $d)
    Set-Location $d
    & $w "FriesenRauch.xml" 2>&1 | Out-String
} -ArgumentList $werkzeug, $hier

# Fertig ist der Bau, wenn alle sechs .spb NEUER sind als der Start -- nicht, wenn der
# Prozess endet. Er endet naemlich nicht.
$fertig = $false
while (((Get-Date) - $start).TotalMinutes -lt $MaxMinuten) {
    Start-Sleep -Seconds 10
    $neu = @(Get-ChildItem "$spb\*.spb" -ErrorAction SilentlyContinue |
             Where-Object { $_.LastWriteTime -gt $start })
    if ($neu.Count -ge 6) { $fertig = $true; break }
}

Start-Sleep -Seconds 15      # dem Manifest-Schreiben noch Luft lassen
Raeum-Auf
Remove-Job $auftrag -Force -ErrorAction SilentlyContinue

$dauer = [int]((Get-Date) - $start).TotalSeconds
if ($fertig) {
    Write-Output "Effekte gebaut nach $dauer s. Simulator beendet."
} else {
    Write-Output "NICHT fertig nach $dauer s -- Zeitstempel unter Packages\ pruefen."
    exit 1
}
