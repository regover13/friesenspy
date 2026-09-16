# Baut bruegge.cpp zu einem MSFS-WASM-Modul und legt es als Paket in den Community-Ordner.
#
# Die Flags stammen aus dem MSFS2024-Toolset des SDK. Wichtig sind drei:
#   -target wasm32-unknown-wasi   das Ziel
#   --sysroot <SDK>\WASM\wasi-sysroot   die libc dazu
#   --allow-undefined             SimConnect-Funktionen liefert der Simulator zur Laufzeit,
#                                 sie sind beim Linken absichtlich unaufgeloest
#   /GS- + -fno-stack-protector   OHNE DIESE BEIDEN LAEUFT GAR NICHTS. clang-cl schaltet
#                                 den Buffer Security Check wie MSVC standardmaessig EIN;
#                                 der erzeugt Aufrufe von __stack_chk_fail, und die kennt
#                                 die MSFS-WASM-Laufzeit nicht. Das Modul wird dann bei der
#                                 Validierung verworfen, BEVOR es laeuft:
#                                   ERR_UNKNOWN_BLANK_IMPORT: __stack_chk_fail not found
#                                   in C library imports (env_WASM___stack_chk_fail)
#                                   ERR_VALIDATION_ERROR (-4095 / fffff001)
#                                 Nach aussen sieht das aus wie ein Modul, das nichts tut --
#                                 kein module_init, keine Meldung, kein Objekt. Sichtbar
#                                 wird es NUR in der DevMode-Konsole (11.09.2026).
#   --export-table                EBENSO NOETIG, sobald das Modul einen Callback uebergibt
#                                 (SimConnect_CallDispatch). Ein Funktionszeiger wird in
#                                 WebAssembly ueber die "indirect function table" aufgeloest,
#                                 und die muss das Modul exportieren. Fehlt sie, kompiliert
#                                 der Simulator das Modul anstandslos und scheitert erst
#                                 danach:
#                                   WASM: Error getting indirect function table in module
#                                 --growable-table steht daneben, weil die Tabelle beim
#                                 Registrieren von Callbacks waechst.
#
# Nach dem Bau muss der Simulator NEU GESTARTET werden -- Community-Pakete liest er
# ausschliesslich beim Start.

# ---------------------------------------------------------------------------------------
# EIN MODUL FUER BEIDE SIMULATOREN -- und deshalb baut das AELTERE SDK (16.09.2026)
#
# Seit 1.14.0 laeuft ein einziges bruegge.wasm in MSFS 2020 UND 2024. Der Schalter
# `-Fuer2020` ist damit ersatzlos entfallen: Er setzte `-DFUER_MSFS2020=1`, und dieses Makro
# gibt es im Quelltext nicht mehr. Ein Schalter, der nichts mehr aendert, ist schlimmer als
# keiner -- er verspricht ein anderes Ergebnis.
#
# ⚠ GEBAUT WIRD GEGEN DAS 2020er SDK, WENN ES DA IST. Das ist keine Nostalgie, sondern die
# einzige Stelle, an der ein Rueckfall auffliegt: Das 2020-SDK kennt die 2024-Erweiterungen
# nicht (`MSFS_IO.h` fehlt dort vollstaendig). Wer versehentlich eine davon benutzt, merkt
# es HIER als Uebersetzungsfehler -- und nicht erst daran, dass MSFS 2020 das fertige Modul
# stillschweigend verwirft. Das aeltere SDK ist der Tuersteher.
#
# Gegengeprueft am 16.09.2026: Beide SDKs erzeugen dasselbe Modul -- 19 Importe, Liste
# zeichengleich. Das 2024er ist also kein falscher Bau, nur ein ungeschuetzter.
# ---------------------------------------------------------------------------------------

$ErrorActionPreference = 'Stop'

$sdk2020 = $env:MSFS_SDK;     if (-not $sdk2020) { $sdk2020 = 'D:\MSFS SDK' }
$sdk2024 = $env:MSFS2024_SDK; if (-not $sdk2024) { $sdk2024 = 'C:\MSFS 2024 SDK' }

if (Test-Path "$sdk2020\WASM\llvm\bin\clang-cl.exe") {
    $sdk = $sdk2020
} elseif (Test-Path "$sdk2024\WASM\llvm\bin\clang-cl.exe") {
    $sdk = $sdk2024
    Write-Warning ("Das MSFS-2020-SDK fehlt -- gebaut wird gegen das 2024er. Das Modul " +
                   "laeuft trotzdem in beiden, aber ein versehentlicher Griff nach einer " +
                   "2024-only-Funktion faellt erst im Simulator auf.")
} else {
    throw "Kein SDK gefunden -- weder '$sdk2020' noch '$sdk2024'."
}
$sdk = $sdk.TrimEnd('\')

$clang = "$sdk\WASM\llvm\bin\clang-cl.exe"
$linker = "$sdk\WASM\llvm\bin\wasm-ld.exe"
$hier = $PSScriptRoot
$obj = "$hier\bruegge.o"
$wasm = "$hier\bruegge.wasm"

Write-Output "SDK:      $sdk"
Write-Output "Compiler: $clang"

# ---- 1. Uebersetzen -------------------------------------------------------
# clang-cl ist der MSVC-kompatible Treiber: er kennt "--sysroot" nicht und verschluckt es
# stillschweigend (nur eine Warnung). Eigene clang-Argumente muessen mit /clang: durch-
# gereicht werden -- sonst fehlt die wasi-libc und "bits\alltypes.h" wird nicht gefunden.
& $clang `
    -c `
    -o $obj `
    "$hier\bruegge.cpp" `
    --target=wasm32-unknown-wasi `
    "/clang:--sysroot=$sdk\WASM\wasi-sysroot" `
    -D_MSFS_WASM=1 -D__wasi__ -D_LIBCPP_HAS_NO_THREADS -D_WINDLL -D_MBCS `
    "-I$sdk\WASM\include" `
    "-I$sdk\SimConnect SDK\include" `
    -Wno-ignored-attributes `
    /clang:-fms-extensions /clang:-fms-compatibility `
    /GS- /clang:-fno-stack-protector `
    /clang:-flto /clang:-O1
if ($LASTEXITCODE -ne 0) { throw "Uebersetzen fehlgeschlagen ($LASTEXITCODE)" }
Write-Output "uebersetzt: $obj"

# ---- 2. Linken ------------------------------------------------------------
& $linker `
    --no-entry `
    --allow-undefined `
    --export __wasm_call_ctors `
    --export-table `
    --growable-table `
    --export-dynamic `
    --export module_init `
    --export module_deinit `
    --export malloc --export free `
    "-L$sdk\WASM\wasi-sysroot\lib\wasm32-wasi" `
    -lc -lc++ -lc++abi `
    --lto-O3 -O3 `
    -o $wasm `
    $obj
if ($LASTEXITCODE -ne 0) { throw "Linken fehlgeschlagen ($LASTEXITCODE)" }
Write-Output "gelinkt:    $wasm  ($((Get-Item $wasm).Length) Bytes)"

# ---- 3. Sich selbst pruefen ----------------------------------------------
# Die drei Fallen oben stehen alle in der Import-/Exporttabelle der fertigen Datei -- sie
# sind also hier messbar und nicht erst nach einem Neustart des Simulators. Genau daran hing
# am 15.09.2026 die halbe Fehlersuche: Ob das Modul sauber gebaut war, liess sich nicht
# feststellen, ohne MSFS zu starten und in der DevMode-Konsole nachzusehen.
#
# Fehlt Python, WARNT das hier nur -- ein gebautes Modul ist ein gebautes Modul, und ein
# fehlendes Pruefwerkzeug soll den Bau nicht scheitern lassen.
$pruefer = "$hier\wasm_pruefen.py"
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Write-Warning "python nicht gefunden -- die drei Build-Fallen sind UNGEPRUEFT."
} elseif (-not (Test-Path $pruefer)) {
    Write-Warning "wasm_pruefen.py fehlt -- die drei Build-Fallen sind UNGEPRUEFT."
} else {
    $bericht = & $python $pruefer $wasm
    $bericht | Select-String -Pattern 'FALLE|Importe|Exporte' | ForEach-Object { Write-Output "  $_" }
    if ($bericht -match '<<<') {
        $bericht | Select-String -Pattern '<<<' | ForEach-Object { Write-Output $_ }
        throw "Das Modul wuerde im Simulator nicht laufen -- s. die Zeilen mit '<<<' oben."
    }
}
