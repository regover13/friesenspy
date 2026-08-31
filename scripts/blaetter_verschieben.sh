#!/bin/bash
# Blaetter auf das neue Schema <ICAO>.<sorte>[.roh].png in aip_dfs/ bringen.
#
# ZIEL="" bedeutet Trockenlauf in ein temporaeres Verzeichnis (kopiert statt verschiebt).
set -euo pipefail
DATA=/opt/friesenspy/data
ZIEL=${1:-/tmp/aip_dfs_probe}
ECHT=${2:-nein}

mkdir -p "$ZIEL"
kopie() { if [ "$ECHT" = ja ]; then cp -p "$1" "$2"; else cp "$1" "$2"; fi; }

# --- Sichtflugkarten -------------------------------------------------------------------
# Das abgelegte Blatt ist hier ZUGLEICH das Rohblatt: Der alte Weg kannte keine Trennung,
# der Admin klickte auf genau diese Datei, und rahmen_px (= die migrierten Klickpunkte)
# bezieht sich darauf. Beide Namen bekommen deshalb dieselben Bytes; ein spaeteres
# Nachpassen rechnet dann eine Drehung nahe 0 und legt dasselbe Bild wieder ab.
n_s=0
for f in "$DATA"/aip/[A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9].png; do
  [ -e "$f" ] || continue
  icao=$(basename "$f" .png)
  kopie "$f" "$ZIEL/$icao.sichtflug.png"
  kopie "$f" "$ZIEL/$icao.sichtflug.roh.png"
  n_s=$((n_s+1))
done

# --- Flugplatz- und Rollkarten ---------------------------------------------------------
# Die Sorte steht nur in der Datenbank, nicht im Dateinamen.
n_g=0; n_ersatz=0
while IFS='|' read -r icao sorte; do
  [ -n "$icao" ] || continue
  if [ -f "$DATA/aip_ground/$icao.roh.png" ]; then
    kopie "$DATA/aip_ground/$icao.roh.png" "$ZIEL/$icao.$sorte.roh.png"
  elif [ -f "$DATA/aip_ground/$icao.png" ]; then
    # EDDL, EDDM, EDDP: von der alten Bahnvermessung gepasst, die nur das GENORDETE Blatt
    # ablegte. Das ist north-up, taugt also als Klickvorlage -- ein Nachpassen darauf ergibt
    # eine Drehung nahe 0, und genau das ist richtig.
    kopie "$DATA/aip_ground/$icao.png" "$ZIEL/$icao.$sorte.roh.png"
    n_ersatz=$((n_ersatz+1))
  fi
  [ -f "$DATA/aip_ground/$icao.png" ] && kopie "$DATA/aip_ground/$icao.png" "$ZIEL/$icao.$sorte.png"
  n_g=$((n_g+1))
done < <(sqlite3 "$DATA/friesenspy.db" "SELECT icao||'|'||sorte FROM aip_ground_charts;")

echo "Sichtflug:        $n_s Zeilen -> je 2 Dateien"
echo "Ground:           $n_g Zeilen, davon $n_ersatz ohne eigenes Rohblatt (genordetes genommen)"
echo "Dateien in Ziel:  $(ls "$ZIEL" | wc -l)"
