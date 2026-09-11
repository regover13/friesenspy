# Baut modul.cpp zu einem MSFS-WASM-Modul und legt es als Paket in den Community-Ordner.
#
# Die Flags stammen aus dem MSFS2024-Toolset des SDK. Wichtig sind drei:
#   -target wasm32-unknown-wasi   das Ziel
#   --sysroot <SDK>\WASM\wasi-sysroot   die libc dazu
#   --allow-undefined             SimConnect-Funktionen liefert der Simulator zur Laufzeit,
#                                 sie sind beim Linken absichtlich unaufgeloest
#
# Nach dem Bau muss der Simulator NEU GESTARTET werden -- Community-Pakete liest er
# ausschliesslich beim Start.

$ErrorActionPreference = 'Stop'
$sdk = $env:MSFS2024_SDK
if (-not $sdk) { $sdk = 'C:\MSFS 2024 SDK' }
$sdk = $sdk.TrimEnd('\')

$clang = "$sdk\WASM\llvm\bin\clang-cl.exe"
$linker = "$sdk\WASM\llvm\bin\wasm-ld.exe"
$hier = $PSScriptRoot
$obj = "$hier\modul.o"
$wasm = "$hier\modul.wasm"

Write-Output "SDK:      $sdk"
Write-Output "Compiler: $clang"

# ---- 1. Uebersetzen -------------------------------------------------------
# clang-cl ist der MSVC-kompatible Treiber: er kennt "--sysroot" nicht und verschluckt es
# stillschweigend (nur eine Warnung). Eigene clang-Argumente muessen mit /clang: durch-
# gereicht werden -- sonst fehlt die wasi-libc und "bits\alltypes.h" wird nicht gefunden.
& $clang `
    -c `
    -o $obj `
    "$hier\modul.cpp" `
    --target=wasm32-unknown-wasi `
    "/clang:--sysroot=$sdk\WASM\wasi-sysroot" `
    -D_MSFS_WASM=1 -D__wasi__ -D_LIBCPP_HAS_NO_THREADS -D_WINDLL -D_MBCS `
    "-I$sdk\WASM\include" `
    "-I$sdk\SimConnect SDK\include" `
    -Wno-ignored-attributes `
    /clang:-fms-extensions /clang:-fms-compatibility `
    /clang:-flto /clang:-O1
if ($LASTEXITCODE -ne 0) { throw "Uebersetzen fehlgeschlagen ($LASTEXITCODE)" }
Write-Output "uebersetzt: $obj"

# ---- 2. Linken ------------------------------------------------------------
& $linker `
    --no-entry `
    --allow-undefined `
    --export __wasm_call_ctors `
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
