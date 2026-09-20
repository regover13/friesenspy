# Baut die Marken (Wuerfel, Lichtsaeulen, Punktlicht) mit dem MSFS-2024-SDK.
#
# ⭐ WARUM DIE MARKEN EIN EIGENES SKRIPT UND EIN EIGENES SDK HABEN (20.09.2026)
#
# Die Marken tragen an jedem Material die glTF-Erweiterung `ASOBO_material_emissive`
# (`emissiveNightMultiplier`), der einzige Regler fuer ihre Helligkeit in MSFS 2024. Der 2020er
# Compiler ENTFERNT sie beim Bauen: Im Quell-glTF steht emissiveNightMultiplier 6.0, das fertige
# `Packages\...\FrsTestWuerfel_M6.gltf` hat nur `emissiveFactor`, und `extensionsUsed` fuehrt nur
# `ASOBO_normal_map_convention` und `asobo_optimized` -- der Multiplikator wirkte damit in keinem
# Simulator (gemessen am 2020er Bau, `D:\MSFS SDK`). Also baut dieses Skript mit dem 2024er SDK
# (`C:\MSFS 2024 SDK\Tools\bin\fspackagetool.exe`) aus `FriesenMarken.xml`.
#
# Rauch und Seehund bleiben bei `bauen.ps1` und dem 2020er SDK: Die 2024er Toolchain macht aus
# PNG-Texturen `.KTX2`, die MSFS 2020 nicht liest (rosa Seehunde), und kennt nur die 2024er
# Behavior-Vorlage `ASOBO_VFX_Template`, mit der MSFS 2020 nicht raucht. Zwei SDKs, zwei Projekte,
# getrennte Zwischenordner (`_PackageInt` fuer 2020, `_PackageInt2024` hier) -- beide Toolchains
# legen dort ihre eigenen Zwischenformate ab.
#
# ⚠ UNGEMESSEN: Ob ein mit dem 2024er SDK kompiliertes, textur- und behaviorfreies Modell in
# MSFS 2020 laedt. Die Marken haben weder Textur noch Behavior (nur Farbfaktoren) -- genau die
# beiden Dinge, an denen die 2024er Toolchain Rauch und Seehund fuer 2020 unbrauchbar machte --,
# aber gemessen ist es erst, wenn jemand die Titel in MSFS 2020 setzt.
#
# ⚠⚠ DAS 2024er WERKZEUG ZEIGT DEN XBOX-STARTBILDSCHIRM -- UND DER MUSS WIEDER WEG.
#
# `fspackagetool.exe` ist nur ein Starter. Sichtbar wird beim 2024er Bau nicht der Simulator,
# sondern der Xbox-Startbildschirm (Prozess `gamingservicesui`, Fenster "Microsoft Flight
# Simulator 2024"); der Prozess des Werkzeugs endet nach dem Bau nicht von selbst, und das Fenster
# bleibt stehen, bis jemand es wegraeumt (14.09.2026: der Nutzer musste es jedes Mal von Hand
# schliessen; Nutzerkorrektur 20.09.2026: es ist der Startbildschirm, nicht der laufende Simulator).
# Das 2020er Werkzeug laeuft dagegen ohne Fenster (`bauen.ps1`).
#
# ⭐ DAS AUFRAEUMEN DER VIER PROZESSE IST PFLICHT, KEIN BEIWERK: `fspackagetool`,
# `FlightSimulator2024`, `gamelaunchhelper` und `gamingservicesui`. Es steht deshalb in einem
# `finally` und laeuft auch, wenn der Bau ein Timeout erreicht, das Skript mit einem Fehler
# abbricht oder mit Strg+C beendet wird -- nicht nur im Erfolgsfall.
#
# ⚠ NICHT AUFRUFEN, WAEHREND JEMAND IM SIMULATOR SITZT (Nutzer, 20.09.2026: "ich bin in SIM kein
# kompellieren!"). Der Start belastet den Rechner und kommt einer laufenden Sitzung dazwischen und
# das Aufraeumen wuerde ihren Simulator beenden; erst ansagen, dann bauen. Nie zwei Simulatoren
# gleichzeitig: Das Skript bricht ab, wenn MSFS 2020 oder 2024 laeuft (`-Trotzdem` erzwingt es,
# nur auf ausdruecklichen Wunsch).
#
# Danach ins Paket: `msfs\paket.ps1` nimmt `Packages\devprops-friesenmarken` als vierten Teil ins
# ZIP und in den Community-Ordner auf. Der Simulator liest Community-Pakete nur beim Start.
param(
    [int]$MaxMinuten = 10,    # Notbremse, falls der Bau wirklich haengt
    [switch]$Trotzdem         # nur wenn der Nutzer es ausdruecklich will
)

$ErrorActionPreference = 'Stop'
$hier = $PSScriptRoot
$sdk2024 = $env:MSFS2024_SDK; if (-not $sdk2024) { $sdk2024 = 'C:\MSFS 2024 SDK' }
$werkzeug = Join-Path $sdk2024.TrimEnd('\') 'Tools\bin\fspackagetool.exe'
if (-not (Test-Path $werkzeug)) { throw "fspackagetool (2024) nicht gefunden: $werkzeug" }
if (-not (Test-Path "$hier\FriesenMarken.xml")) {
    throw "FriesenMarken.xml fehlt -- erst 'python paket_bauen.py' ausfuehren."
}

function Raeum-Auf {
    # ⚠ VIER PROZESSE, NICHT DREI. `gamingservicesui` ist der Xbox-Startbildschirm, der als Fenster
    # "Microsoft Flight Simulator 2024" stehen bleibt, nachdem alles andere weg ist (14.09.2026: der
    # Nutzer musste ihn jedes Mal von Hand schliessen). Der Simulator heisst hier `FlightSimulator2024`,
    # nicht `FlightSimulator` wie beim 2020er Bau.
    Get-Process fspackagetool, FlightSimulator2024, gamelaunchhelper, gamingservicesui -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

$laeuft = Get-Process FlightSimulator, FlightSimulator2024 -ErrorAction SilentlyContinue
if ($laeuft -and -not $Trotzdem) {
    throw "Ein Simulator laeuft ($(($laeuft | ForEach-Object Name) -join ', ')) -- nicht bauen, solange jemand drinsitzt."
}

# Altlasten zuerst: Laeuft noch ein Bauprozess, endet der naechste Aufruf sofort mit Exit 43, ohne zu
# bauen -- das hat am 14.09.2026 zweimal wie ein Fehler ausgesehen und war keiner.
Raeum-Auf
Start-Sleep -Seconds 2

# Der Bau merkt sich Zeitstempel: Eine geaenderte Datei wird sonst nicht immer neu gebaut (bei der
# abgedunkelten Seehund-Textur blieb das erste Ergebnis unberuehrt). Also vorher wegraeumen -- nur
# DIESES Paket und den Zwischenordner der 2024er Toolchain, nie `Packages\devprops-friesenrauch*`.
$paket = Join-Path $hier 'Packages\devprops-friesenmarken'
foreach ($x in @($paket, (Join-Path $hier '_PackageInt2024'))) {
    if (Test-Path -LiteralPath $x) { Remove-Item -LiteralPath $x -Recurse -Force }
}

$start = Get-Date
$auftrag = $null
$fertig = $false
Write-Output "Baue die Marken mit dem 2024er SDK -- das Werkzeug zeigt den Xbox-Startbildschirm, das Skript schliesst ihn danach."

try {
    # ⚠ MIT `&` IM JOB STARTEN, NICHT MIT `Start-Process -NoNewWindow`. Letzteres startet den Prozess
    # zwar, aber er schreibt keine einzige Datei -- am 14.09.2026 dreimal belegt (8 Minuten Laufzeit,
    # null Ergebnis). Offenbar braucht das Werkzeug die Konsole des Aufrufers.
    $auftrag = Start-Job -ScriptBlock {
        param($w, $d)
        Set-Location $d
        & $w "FriesenMarken.xml" 2>&1 | Out-String
    } -ArgumentList $werkzeug, $hier

    # Fertig ist der Bau, wenn unter dem Paket eine Weile NICHTS MEHR geschrieben wurde und mindestens
    # eine Datei neuer ist als der Start -- nicht, wenn der Prozess endet. Er endet naemlich nicht.
    #
    # ⚠ NICHT `Get-ChildItem "...\devprops-friesenmarken*" -Recurse`: Ein Platzhalter im Pfad durchsucht
    # die Unterordner nicht -- das lieferte nichts, die Ruhe-Erkennung schlug nie an, und das (2020er)
    # Skript wartete jedes Mal die vollen acht Minuten (20.09.2026, zweimal). Deshalb der volle Pfad.
    $RuheSekunden = 40
    while (((Get-Date) - $start).TotalMinutes -lt $MaxMinuten) {
        Start-Sleep -Seconds 10
        $neueste = Get-ChildItem -LiteralPath $paket -Recurse -File -ErrorAction SilentlyContinue |
                   Where-Object { $_.LastWriteTime -gt $start } |
                   Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($neueste -and ((Get-Date) - $neueste.LastWriteTime).TotalSeconds -ge $RuheSekunden) {
            $fertig = $true
            break
        }
    }
    Start-Sleep -Seconds 15      # dem Manifest-Schreiben noch Luft lassen
}
finally {
    # ⭐ PFLICHT, AUCH IM FEHLER- UND TIMEOUT-PFAD: Der Startbildschirm und die drei anderen Prozesse
    # muessen weg, egal wie das Skript endet.
    Raeum-Auf
    if ($auftrag) { Remove-Job $auftrag -Force -ErrorAction SilentlyContinue }
}

Start-Sleep -Seconds 3
$noch = Get-Process fspackagetool, FlightSimulator2024, gamelaunchhelper, gamingservicesui -ErrorAction SilentlyContinue
if ($noch) { Write-Warning "Prozess noch da: $(($noch | ForEach-Object Name) -join ', ')" }

$dauer = [int]((Get-Date) - $start).TotalSeconds
if (-not $fertig) {
    Write-Output "NICHT fertig nach $dauer s -- unter Packages\devprops-friesenmarken nachsehen (Prozesse sind aufgeraeumt)."
    exit 1
}

# ⭐ DIE PROBE, WEGEN DER DIESES SKRIPT ES GIBT: Steht die Erweiterung im FERTIGEN glTF? Der 2020er Bau
# hat sie stillschweigend entfernt -- gemeldet wurde nichts. Jedes Wuerfel- und Saeulenmodell muss sie
# tragen (auch die Testtitel); das Licht hat sie bewusst nicht.
$modelle = Get-ChildItem -LiteralPath $paket -Recurse -File -Filter *.gltf -ErrorAction SilentlyContinue |
           Where-Object { $_.Name -match '^Frs(Test)?(Wuerfel|Saeule)_' }
$ohne = @($modelle | Where-Object { -not (Select-String -LiteralPath $_.FullName -Pattern 'ASOBO_material_emissive' -Quiet) })
if ($modelle.Count -eq 0) {
    Write-Warning "Kein Wuerfel-/Saeulenmodell im gebauten Paket gefunden -- die Ausgabe pruefen."
    exit 2
}
if ($ohne.Count -gt 0) {
    Write-Warning ("ASOBO_material_emissive fehlt im gebauten glTF: " + (($ohne | ForEach-Object Name) -join ', '))
    exit 2
}
Write-Output "Marken gebaut nach $dauer s: $($modelle.Count) Wuerfel-/Saeulenmodelle, alle mit ASOBO_material_emissive. Prozesse aufgeraeumt."
Write-Output "Weiter: msfs\paket.ps1 nimmt das Teilpaket ins ZIP und in den Community-Ordner auf."
