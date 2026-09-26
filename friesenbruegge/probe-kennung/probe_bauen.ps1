# Baut probe.cpp zu probe.wasm -- mit denselben Schaltern wie ../msfs/bauen.ps1.
#
# ⚠ UNGETESTET: auf dem Server geschrieben, dort gibt es kein MSFS-SDK. Weicht etwas von
# ../msfs/bauen.ps1 ab, gilt bauen.ps1 -- das baut die Brügge nachweislich.
#
# Gebaut wird gegen das 2020er SDK, wenn es da ist (wie bei der Brügge): Nur dort fällt ein
# Griff nach einer 2024-only-Funktion schon beim Übersetzen auf.

$ErrorActionPreference = 'Stop'

$sdk2020 = $env:MSFS_SDK;     if (-not $sdk2020) { $sdk2020 = 'D:\MSFS SDK' }
$sdk2024 = $env:MSFS2024_SDK; if (-not $sdk2024) { $sdk2024 = 'C:\MSFS 2024 SDK' }
if (Test-Path "$sdk2020\WASM\llvm\bin\clang-cl.exe") { $sdk = $sdk2020 }
elseif (Test-Path "$sdk2024\WASM\llvm\bin\clang-cl.exe") {
    $sdk = $sdk2024
    Write-Warning "Das MSFS-2020-SDK fehlt -- gebaut wird gegen das 2024er."
} else { throw "Kein SDK gefunden -- weder '$sdk2020' noch '$sdk2024'." }
$sdk = $sdk.TrimEnd('\')

$clang  = "$sdk\WASM\llvm\bin\clang-cl.exe"
$linker = "$sdk\WASM\llvm\bin\wasm-ld.exe"
$hier = $PSScriptRoot
$obj  = "$hier\probe.o"
$wasm = "$hier\probe.wasm"

& $clang `
    -c -o $obj "$hier\probe.cpp" `
    --target=wasm32-unknown-wasi `
    "/clang:--sysroot=$sdk\WASM\wasi-sysroot" `
    -D_MSFS_WASM=1 -D__wasi__ -D_LIBCPP_HAS_NO_THREADS -D_WINDLL -D_MBCS `
    "-I$sdk\WASM\include" `
    -Wno-ignored-attributes `
    /clang:-fms-extensions /clang:-fms-compatibility `
    /GS- /clang:-fno-stack-protector `
    /clang:-flto /clang:-O1
if ($LASTEXITCODE -ne 0) { throw "Uebersetzen fehlgeschlagen ($LASTEXITCODE)" }

& $linker `
    --no-entry --allow-undefined `
    --export __wasm_call_ctors --export-table --growable-table --export-dynamic `
    --export module_init --export module_deinit `
    --export malloc --export free `
    "-L$sdk\WASM\wasi-sysroot\lib\wasm32-wasi" `
    -lc -lc++ -lc++abi `
    --lto-O3 -O3 `
    -o $wasm $obj
if ($LASTEXITCODE -ne 0) { throw "Linken fehlgeschlagen ($LASTEXITCODE)" }
Write-Output "gelinkt: $wasm ($((Get-Item $wasm).Length) Bytes)"

# Die Importliste ist das erste Ergebnis: Welche wasi-Funktionen zieht fopen herein?
$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($python) { & $python "$hier\..\msfs\wasm_pruefen.py" $wasm }
else { Write-Warning "python fehlt -- Importliste bitte von Hand pruefen." }
