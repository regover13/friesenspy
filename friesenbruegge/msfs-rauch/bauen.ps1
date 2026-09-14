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
    # ⚠ VIER PROZESSE, NICHT DREI. gamingservicesui fehlte bis zum 14.09.2026 -- das ist
    # der Xbox-Startbildschirm, der als Fenster "Microsoft Flight Simulator 2024" stehen
    # bleibt, nachdem alles andere weg ist. Der Nutzer musste ihn jedes Mal von Hand
    # schliessen ("er ist immer noch da!!").
    Get-Process fspackagetool, FlightSimulator2024, gamelaunchhelper, gamingservicesui -ErrorAction SilentlyContinue |
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

# Fertig ist der Bau, wenn unter Packages\ eine Weile NICHTS MEHR geschrieben wurde --
# nicht, wenn der Prozess endet. Er endet naemlich nicht.
#
# ⚠ HIER STAND "wenn alle sechs .spb neuer sind als der Start", und das war zu eng.
# Am 14.09.2026 kam der Seehund als SimObject dazu; an den Rauch-Effekten aenderte sich
# dabei nichts, also schrieb der Builder die .spb gar nicht neu. Der Bau war nach zwei
# Minuten fertig -- das Skript haette bis zum 10-Minuten-Timeout gewartet und dann
# "NICHT fertig" gemeldet, obwohl alles dastand.
#
# Die Ruhe-Erkennung ist unabhaengig davon, WAS gebaut wird: Sobald seit $RuheSekunden
# keine Datei mehr angefasst wurde und mindestens eine neuer ist als der Start, ist der
# Builder durch. Das traegt auch alles, was spaeter noch dazukommt.
$RuheSekunden = 40
$fertig = $false
while (((Get-Date) - $start).TotalMinutes -lt $MaxMinuten) {
    Start-Sleep -Seconds 10
    $neueste = Get-ChildItem "$hier\Packages" -Recurse -File -ErrorAction SilentlyContinue |
               Where-Object { $_.LastWriteTime -gt $start } |
               Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($neueste -and ((Get-Date) - $neueste.LastWriteTime).TotalSeconds -ge $RuheSekunden) {
        $fertig = $true
        break
    }
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
