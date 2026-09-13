#!/usr/bin/env bash
# Alles, was sich ohne Simulator über die Brügge sagen lässt -- in einem Aufruf.
#
# ⚠ Was dieser Lauf NICHT kann (Spec, Abschnitt 12): die arm64-Aufrufkonvention, die
# dyld-Namensauflösung, das Vertrauen der Keychain in die Let's-Encrypt-Kette, das
# Deployment-Target, Gatekeeper -- und alles, wofür X-Plane laufen muss. Diese Maschine ist
# x86-64 mit OpenSSL. Er ersetzt keinen Flugtest; er verkleinert nur, was ungeprüft bleibt.
set -euo pipefail
hier="$(cd "$(dirname "$0")" && pwd)"
sdk="${XPSDK:-/tmp/xpsdk/SDK}"
cd "$hier"

if [ ! -f "$sdk/CHeaders/XPLM/XPLMPlugin.h" ]; then
    echo "SDK fehlt unter $sdk. Einmalig holen:"
    echo "  mkdir -p /tmp/xpsdk && cd /tmp/xpsdk && curl -sSLO \\"
    echo "    https://developer.x-plane.com/wp-content/plugins/code-sample-generation/sdk_zip_files/XPSDK430.zip"
    echo "  unzip -q XPSDK430.zip"
    exit 1
fi

echo "== 1. Zahlen ohne Locale =="
g++ -std=c++17 -O1 -o json_locale json_locale.cpp
./json_locale

echo ""
echo "== 2. Die .xpl bauen, wie ubuntu-22.04 es in der CI tut =="
g++ -std=c++17 -shared -fPIC -fvisibility=hidden -pthread -O2 -DLIN=1 \
    -DXPLM200=1 -DXPLM210=1 -DXPLM300=1 -DXPLM301=1 -DXPLM400=1 -DXPLM410=1 \
    -I"$sdk/CHeaders/XPLM" -I"$sdk/CHeaders/Widgets" \
    -o FriesenBruegge.xpl ../bruegge.cpp -ldl
echo "   $(stat -c%s FriesenBruegge.xpl) Bytes"

echo ""
echo "== 3. Was das Binary exportiert und verlangt =="
anzahl=$(nm -D --defined-only FriesenBruegge.xpl | grep -c XPlugin)
echo "   XPlugin-Symbole: $anzahl (soll: 5)"
[ "$anzahl" = "5" ]
readelf -d FriesenBruegge.xpl | grep NEEDED | sed 's/^/   /'
if readelf -d FriesenBruegge.xpl | grep -q libcurl; then
    echo "   FEHLER: libcurl steht in NEEDED -- es soll per dlopen kommen."
    exit 1
fi
echo "   hoechste Symbolversion: $(objdump -T FriesenBruegge.xpl \
    | grep -oE 'GLIBC(XX)?_[0-9.]+' | sort -Vu | tail -1)"

echo ""
echo "== 4. Ladetest: findet dlopen die Einstiegspunkte? =="
gcc -o laden laden.c -ldl
./laden ./FriesenBruegge.xpl

echo ""
echo "== 5. Gegenstellen starten =="
python3 ../../pruefserver.py > /tmp/pruefserver.log 2>&1 &
pruef=$!
python3 -c "
import socket
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,1)
s.bind(('127.0.0.1',8098)); s.listen(8)
while True:
    k,_=s.accept(); k.close()
" > /tmp/kapper.log 2>&1 &
kapper=$!
trap 'kill $pruef $kapper 2>/dev/null || true' EXIT
sleep 1.5

echo ""
echo "== 6. Netz- und Threadschicht =="
g++ -std=c++17 -pthread -o netz_pruefen netz_pruefen.cpp -ldl
./netz_pruefen

echo ""
echo "Durchgelaufen. Ungeprueft bleibt, was oben im Kopf dieser Datei steht."
