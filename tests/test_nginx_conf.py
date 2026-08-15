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
