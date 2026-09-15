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

param([switch]$Fuer2020)   # gegen das MSFS-2020-SDK bauen statt gegen das 2024er

$ErrorActionPreference = 'Stop'
if ($Fuer2020) {
    $sdk = $env:MSFS_SDK
    if (-not $sdk) { $sdk = 'D:\MSFS SDK' }
} else {
    $sdk = $env:MSFS2024_SDK
    if (-not $sdk) { $sdk = 'C:\MSFS 2024 SDK' }
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
    $(if ($Fuer2020) { '-DFUER_MSFS2020=1' }) `
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
