"""Repo-nginx-Config fuer friesenspy.devprops.de (Review-Fund, Important, v12.10.x).

Systemseitig ist gzip_types in /etc/nginx/nginx.conf auskommentiert (nur der Default text/html
gilt) und gzip_proxied steht auf dem Default "off" -- beides fassen wir laut CLAUDE.md nicht an.
Die drei Karten-Datendateien (Platzrunden-GeoJSON, FSE-Plaetze, FSE-Landeflaechen, zusammen
791 KB unkomprimiert) gingen dadurch ungenutzt komprimierbar ueber die Leitung. Fix liegt allein
in der Repo-Config, die vollstaendig per proxy_pass an FastAPI serviert."""
from pathlib import Path

CONF = (Path(__file__).resolve().parents[1] / "nginx" / "friesenspy.devprops.de.conf").read_text(
    encoding="utf-8"
)


def test_gzip_ist_eingeschaltet():
    assert "gzip on;" in CONF


def test_gzip_wirkt_auch_hinter_proxy_pass():
    """Jede Antwort dieses vHosts kommt per proxy_pass von FastAPI (kein lokal servierter
    Static-Content) -- ohne gzip_proxied bleibt der Default "off" bestehen und gzip_types
    greift nie, egal wie es konfiguriert ist."""
    assert "gzip_proxied" in CONF
    assert "gzip_proxied any;" in CONF or "gzip_proxied off;" not in CONF


def test_gzip_types_deckt_die_kartendaten_ab():
    # Ueber "gzip_types application" suchen -- die erklaerenden Kommentare oben erwaehnen
    # "gzip_types" ebenfalls woertlich, ohne dahinter die Liste zu tragen.
    stelle = CONF.index("gzip_types application")
    zeile = CONF[stelle:CONF.index(";", stelle)]
    for mimetype in ("application/json", "application/geo+json", "application/javascript", "text/css"):
        assert mimetype in zeile, f"{mimetype} fehlt in gzip_types"


# ---------------------------------------------------------------------------------------
#  Das meldende Kniebrett (GitHub-Issue #23)
# ---------------------------------------------------------------------------------------
#
# Ohne eigene `location` liegt der Endpunkt im 120-r/m-Topf der ganzen Website -- zusammen
# mit /api/live, /api/traffic, /api/me und allem anderen, was dasselbe Gerät lädt. Bei einem
# Takt von 1 s sind das allein 60 r/m für das Melden. Genau diese Falle ist am 14.09.2026
# bei der FriesenBrügge zugeschnappt (67 Meldungen mit HTTP 429), und dort fuhr nicht
# einmal ein Browser daneben.

def test_kniebrett_hat_eine_eigene_zone():
    assert "zone=friesenspy_kniebrett:10m" in CONF


def test_die_kniebrett_zone_ist_nicht_die_der_bruegge():
    """Getrennte Zonen: Wer beides nutzt, läge sonst mit 120 r/m in einem 180er-Topf."""
    stelle = CONF.index("location = /api/kniebrett/melden")
    block = CONF[stelle:CONF.index("}", stelle)]
    assert "zone=friesenspy_kniebrett" in block
    assert "friesenspy_bruegge" not in block


def test_kniebrett_location_ist_exakt_und_nicht_als_prefix():
    """Prefix würde /api/kniebrett/... insgesamt aus dem allgemeinen Limit nehmen; es gibt
    aber nur diesen einen Takt-Endpunkt."""
    assert "location = /api/kniebrett/melden {" in CONF


def test_kniebrett_steht_vor_dem_allgemeinen_api_block():
    """Bei nginx gewinnt der längste Prefix, die Reihenfolge ist also technisch egal --
    für den Leser aber nicht: Beide Sonderwege gehören zusammen und vor den Regelfall."""
    assert CONF.index("location = /api/kniebrett/melden") < CONF.index("location /api/ {")
