# tests/test_vrp.py
"""Meldepunkte (VRP): Bestand, Ausschnitt, Auffrischung und die Ebene im Frontend.

Spec: docs/superpowers/specs/2026-08-16-mithoeren-und-meldepunkte-design.md (Teil B).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from app import vrp
from app.poller import VRP_MAX_ALTER_TAGE, VatsimPoller, _vrp_faellig

INDEX = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(
    encoding="utf-8"
)


# ---------------------------------------------------------------------------
# Umwandlung der API-Einträge
# ---------------------------------------------------------------------------

def test_punkt_traegt_name_lage_pflicht_und_hoehe():
    p = vrp._punkt_aus({
        "name": "WHISKEY",
        "compulsory": True,
        "geometry": {"type": "Point", "coordinates": [8.5, 53.5]},
        "elevation": {"value": 30.0, "unit": 0, "referenceDatum": 1},
    })
    name, lat, lon, pflicht, hoehe = p
    assert (name, lat, lon, pflicht) == ("WHISKEY", 53.5, 8.5, True)
    assert hoehe == 98      # 30 m = 98 ft


def test_geojson_ist_lon_lat_nicht_lat_lon():
    """Die klassische Verwechslung — sie führt Punkte um den halben Kontinent."""
    _, lat, lon, _, _ = vrp._punkt_aus({
        "name": "N", "geometry": {"type": "Point", "coordinates": [10.0, 50.0]},
    })
    assert (lat, lon) == (50.0, 10.0)


def test_hoehe_in_fremder_einheit_wird_verworfen():
    """OpenAIP liefert Meter (unit 0). Eine umgerechnete Zahl aus unbekannter Einheit wäre
    schlimmer als gar keine — auf einer Karte, nach der geflogen wird."""
    assert vrp._hoehe_ft({"value": 1000, "unit": 1}) is None
    assert vrp._hoehe_ft(None) is None
    assert vrp._hoehe_ft({"unit": 0}) is None


@pytest.mark.parametrize("eintrag", [
    {"name": "", "geometry": {"type": "Point", "coordinates": [8.0, 53.0]}},
    {"name": "X", "geometry": {"type": "LineString", "coordinates": [8.0, 53.0]}},
    {"name": "X", "geometry": {"type": "Point", "coordinates": [8.0]}},
    {"name": "X", "geometry": {"type": "Point", "coordinates": [999.0, 53.0]}},
    {"name": "X"},
])
def test_unbrauchbare_eintraege_fallen_raus(eintrag):
    assert vrp._punkt_aus(eintrag) is None


# ---------------------------------------------------------------------------
# Ausschnitt
# ---------------------------------------------------------------------------

def _bestand(*punkte):
    return vrp.VrpBestand(punkte=list(punkte), stand="2026-08-16T00:00:00+00:00")


def test_nur_was_im_umkreis_liegt():
    nah = ("NAH", 53.51, 8.51, True, 100)
    fern = ("FERN", 48.0, 11.0, False, None)
    treffer, gekappt = vrp.punkte_im_umkreis(_bestand(nah, fern), 53.5, 8.5, 50)
    assert [w["n"] for w in treffer.values()] == ["NAH"]
    assert gekappt is False


def test_der_schluessel_ist_stabil_und_nicht_der_name():
    """Namen gibt es weltweit vielfach ('NOVEMBER' hunderte Male). Zwei gleichnamige Punkte
    im selben Ausschnitt dürfen sich nicht gegenseitig verschlucken — sonst verschwindet im
    Browser bei jedem Nachladen einer von beiden."""
    b = _bestand(("NOVEMBER", 53.50, 8.50, True, None),
                 ("NOVEMBER", 53.52, 8.52, False, None))
    treffer, _ = vrp.punkte_im_umkreis(b, 53.5, 8.5, 50)
    assert len(treffer) == 2
    assert set(treffer) == {"0", "1"}


def test_deckel_greift_und_meldet_sich():
    b = vrp.VrpBestand(punkte=[
        (f"P{i}", 53.5 + i * 0.0005, 8.5, False, None) for i in range(vrp.MAX_PUNKTE + 25)
    ])
    treffer, gekappt = vrp.punkte_im_umkreis(b, 53.5, 8.5, 50)
    assert len(treffer) == vrp.MAX_PUNKTE
    assert gekappt is True


def test_gekappt_wird_liefert_die_naechsten():
    """Eine Scheibe statt des vollen Rechtecks — aber die um den Bezugspunkt, nicht die
    ersten aus der Liste."""
    fern = [(f"F{i}", 53.5 + 0.4 + i * 0.0005, 8.5, False, None) for i in range(vrp.MAX_PUNKTE)]
    nah = [(f"N{i}", 53.5 + i * 0.0001, 8.5, False, None) for i in range(10)]
    treffer, gekappt = vrp.punkte_im_umkreis(vrp.VrpBestand(punkte=fern + nah), 53.5, 8.5, 100)
    assert gekappt is True
    namen = {w["n"] for w in treffer.values()}
    assert {f"N{i}" for i in range(10)} <= namen


def test_radius_wird_serverseitig_gedeckelt():
    weit = ("WEIT", 58.0, 8.5, False, None)     # ~500 km nördlich
    treffer, _ = vrp.punkte_im_umkreis(_bestand(weit), 53.5, 8.5, 100_000)
    assert treffer == {}


# ---------------------------------------------------------------------------
# Ablage
# ---------------------------------------------------------------------------

def test_speichern_und_laden_sind_zueinander_passend(tmp_path):
    pfad = tmp_path / "vrp.json"
    punkte = [("W", 53.5, 8.5, True, 98)]
    vrp.speichern(pfad, punkte, "2026-08-16T10:00:00+00:00")
    b = vrp.laden(pfad)
    assert b.punkte == punkte           # Tupel, nicht Listen — sonst bricht das Entpacken
    assert b.stand == "2026-08-16T10:00:00+00:00"


def test_speichern_laesst_keine_halbe_datei_zurueck(tmp_path):
    """Geschrieben wird daneben und dann umbenannt. Ein Abbruch hinterließe sonst eine Datei,
    die beim nächsten Start nicht parst — die Ebene wäre still weg."""
    pfad = tmp_path / "vrp.json"
    vrp.speichern(pfad, [("A", 1.0, 2.0, False, None)], "x")
    assert list(tmp_path.iterdir()) == [pfad]


def test_fehlende_ablage_ist_kein_fehler(tmp_path):
    assert vrp.laden(tmp_path / "gibtsnicht.json").punkte == []


def test_kaputte_ablage_ist_kein_fehler(tmp_path):
    """Ohne Meldepunkte läuft alles weiter, nur die Ebene bleibt leer — wie ohne
    OpenAIP-Schlüssel die Kachel-Ebene."""
    pfad = tmp_path / "vrp.json"
    pfad.write_text("{kein json", encoding="utf-8")
    assert vrp.laden(pfad).punkte == []


def test_ablage_liegt_im_datenverzeichnis():
    """Neben der Datenbank, also im Volume — das überlebt den Container. NICHT im Repo: die
    Quelle verlangt einen Schlüssel, den nur der Server hat."""
    assert vrp.pfad_fuer("/opt/friesenspy/data/friesenspy.db") == Path(
        "/opt/friesenspy/data/vrp_openaip.json"
    )


# ---------------------------------------------------------------------------
# Abruf
# ---------------------------------------------------------------------------

def _antwort(seite: int, letzte: int):
    return {
        "page": seite, "limit": 1000, "totalCount": letzte * 2, "totalPages": letzte,
        "nextPage": (seite + 1) if seite < letzte else None,
        "items": [{
            "name": f"P{seite}",
            "compulsory": False,
            "geometry": {"type": "Point", "coordinates": [8.0, 53.0]},
        }],
    }


@pytest.mark.asyncio
async def test_abruf_blaettert_bis_nextpage_fehlt():
    gesehen = []

    def handler(request: httpx.Request) -> httpx.Response:
        gesehen.append(request)
        seite = int(request.url.params.get("page"))
        return httpx.Response(200, json=_antwort(seite, 3))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        punkte = await vrp.abrufen("geheim", client=client)

    assert [p[0] for p in punkte] == ["P1", "P2", "P3"]
    assert [int(r.url.params["page"]) for r in gesehen] == [1, 2, 3]


@pytest.mark.asyncio
async def test_schluessel_geht_im_header_nicht_in_der_url():
    """Eine URL landet im Zweifel in einem Log oder einer Fehlermeldung. Beide Wege sind
    erlaubt (OpenAPI-Schema), also nehmen wir den, der nicht ausplaudert."""
    gesehen = []

    def handler(request: httpx.Request) -> httpx.Response:
        gesehen.append(request)
        return httpx.Response(200, json=_antwort(1, 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await vrp.abrufen("streng-geheim", client=client)

    assert gesehen[0].headers["x-openaip-api-key"] == "streng-geheim"
    assert "streng-geheim" not in str(gesehen[0].url)
    assert "apiKey" not in str(gesehen[0].url)


@pytest.mark.asyncio
async def test_abruf_holt_nur_die_gebrauchten_felder():
    """Ohne fields kämen createdBy, updatedAt und Konsorten auf JEDER Seite mit."""
    gesehen = []

    def handler(request: httpx.Request) -> httpx.Response:
        gesehen.append(request)
        return httpx.Response(200, json=_antwort(1, 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await vrp.abrufen("k", client=client)

    felder = gesehen[0].url.params["fields"].split(",")
    assert set(felder) == {"name", "compulsory", "geometry", "elevation"}


@pytest.mark.asyncio
async def test_ohne_laenderangabe_kommt_der_weltbestand():
    """Entscheidung des Nutzers (16.08.2026): weltweit. In Deutschland fliegt er OFM,
    OpenAIP ist die Karte für den Rest der Welt — ein Zuschnitt fehlte genau dort, wo diese
    Ebene gebraucht wird."""
    gesehen = []

    def handler(request: httpx.Request) -> httpx.Response:
        gesehen.append(request)
        return httpx.Response(200, json=_antwort(1, 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await vrp.abrufen("k", client=client)

    assert "country" not in gesehen[0].url.params


@pytest.mark.asyncio
async def test_bbox_wird_nicht_benutzt():
    """Laut Doku „mainly intended for export use-cases … rate limited" — bei Überlastung 429."""
    assert "bbox" not in vrp._FELDER
    gesehen = []

    def handler(request: httpx.Request) -> httpx.Response:
        gesehen.append(request)
        return httpx.Response(200, json=_antwort(1, 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await vrp.abrufen("k", client=client)

    assert "bbox" not in gesehen[0].url.params


# ---------------------------------------------------------------------------
# Auffrischung im Poller
# ---------------------------------------------------------------------------

def test_frischer_bestand_ist_nicht_faellig():
    jung = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert _vrp_faellig(jung) is False


def test_alter_bestand_ist_faellig():
    alt = (datetime.now(timezone.utc) - timedelta(days=VRP_MAX_ALTER_TAGE + 1)).isoformat()
    assert _vrp_faellig(alt) is True


def test_unlesbares_datum_gilt_als_faellig():
    """Lieber einmal zu viel geholt als ein Bestand, der stillschweigend vergreist."""
    assert _vrp_faellig("") is True
    assert _vrp_faellig("neulich") is True


def test_beide_jobs_sind_registriert(tmp_path):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    p = VatsimPoller(db_path=str(tmp_path / "x.db"))
    p._scheduler = AsyncIOScheduler()
    p._register_jobs()
    ids = {j.id for j in p._scheduler.get_jobs()}
    assert {"vrp_initial", "vrp_refresh"} <= ids
    assert p._scheduler.get_job("vrp_refresh").trigger.interval.total_seconds() == 24 * 3600


@pytest.mark.asyncio
async def test_ohne_schluessel_wird_nichts_geholt(tmp_path, monkeypatch):
    async def platzt(*a, **k):
        raise AssertionError("es darf ohne Schlüssel gar nicht erst abgerufen werden")

    monkeypatch.setattr(vrp, "abrufen", platzt)
    p = VatsimPoller(db_path=str(tmp_path / "x.db"), openaip_api_key="")
    await p._refresh_vrp()


@pytest.mark.asyncio
async def test_fehlgeschlagener_abruf_laesst_den_bestand_stehen(tmp_path, monkeypatch):
    """Silent fail wie bei den Telegram-Alerts: Nichts daran ist es wert, den Scheduler zu
    gefährden — und ein halber Bestand wäre schlimmer als der alte."""
    alt = vrp.VrpBestand(punkte=[("ALT", 53.5, 8.5, True, None)], stand="2020-01-01T00:00:00+00:00")
    vrp.bestand_setzen(alt)

    async def platzt(*a, **k):
        raise httpx.ConnectError("kein Netz")

    monkeypatch.setattr(vrp, "abrufen", platzt)
    p = VatsimPoller(db_path=str(tmp_path / "x.db"), openaip_api_key="k")
    await p._refresh_vrp()
    assert vrp.bestand().punkte == alt.punkte
    vrp.bestand_setzen(vrp.VrpBestand())


@pytest.mark.asyncio
async def test_erfolgreicher_abruf_legt_ab_und_schwenkt_um(tmp_path, monkeypatch):
    neu = [("NEU", 53.5, 8.5, False, 120)]

    async def liefert(*a, **k):
        return neu

    monkeypatch.setattr(vrp, "abrufen", liefert)
    db = tmp_path / "friesenspy.db"
    p = VatsimPoller(db_path=str(db), openaip_api_key="k")
    vrp.bestand_setzen(vrp.VrpBestand())
    await p._refresh_vrp()

    assert vrp.bestand().punkte == neu
    abgelegt = json.loads(vrp.pfad_fuer(str(db)).read_text(encoding="utf-8"))
    assert abgelegt["punkte"] == [list(neu[0])]
    assert abgelegt["stand"]
    vrp.bestand_setzen(vrp.VrpBestand())


# ---------------------------------------------------------------------------
# Die Ebene im Frontend
# ---------------------------------------------------------------------------

def test_ebene_steht_in_der_auswahl():
    assert "liveOverlays['Meldepunkte']" in INDEX


def test_vrp_wird_vor_der_layers_control_registriert():
    """Sonst zeigt der Haken dauerhaft den falschen Zustand (Fund von OpenAIP/FSE)."""
    assert INDEX.index("_addPreferredVrpLayer(liveMap") < INDEX.index("liveOverlays,")


def test_daten_kommen_aus_dem_ausschnitt_endpunkt():
    assert "'/api/vrp'" in INDEX


def test_gruppe_ist_eine_featuregroup():
    """Nur FeatureGroup.addLayer() feuert 'layeradd', an dem die Label-Wache hängt."""
    assert "const _vrpGruppe = L.featureGroup()" in INDEX


def test_kein_canvas_renderer_in_der_ebene():
    """Die Live-Karte läuft mit leaflet-rotate; das Plugin trägt SVG-Pfade und DOM-Marker,
    den Canvas-Ursprung aber nicht — der Versatz verdoppelt sich mit jeder Zoomstufe."""
    start = INDEX.index("//  MELDEPUNKTE (VRP)")
    ende = INDEX.index("//  Fremdverkehr als Karten-Ebene")
    block = INDEX[start:ende]
    assert "L.canvas" not in block
    assert "L.divIcon" in block


def test_meldepflicht_ist_am_symbol_zu_sehen():
    """Gefüllt = meldepflichtig, hohl = auf Anforderung. Die einzige Unterscheidung, die die
    Quelle hergibt — und die einzige, die im Flug zählt."""
    assert "'vrp-marke' + (pflicht ? ' vrp-pflicht' : '')" in INDEX
    assert ".vrp-marke polygon { fill: none;" in INDEX
    assert ".vrp-marke.vrp-pflicht polygon { fill: #e07be0; }" in INDEX


def test_name_erscheint_erst_ab_der_labelschwelle():
    assert "const _VRP_LABEL_MIN_ZOOM = 11;" in INDEX
    assert "className: 'vrp-label'" in INDEX


def test_ebene_bleibt_unterhalb_der_zoomschwelle_leer():
    assert "const _VRP_MIN_ZOOM = 9;" in INDEX
    assert "if (map.getZoom() < _VRP_MIN_ZOOM) { _vrpLeeren(); return; }" in INDEX


def test_symbolgroesse_haengt_an_einer_klasse_nicht_an_seticon():
    """Ein setIcon je Marker beim Überschreiten der Schwelle ist im Kniebrett als Aufblitzen
    sichtbar (derselbe Fund, der setIcon aus dem Verkehrs-Takt genommen hat)."""
    start = INDEX.index("//  MELDEPUNKTE (VRP)")
    ende = INDEX.index("//  Fremdverkehr als Karten-Ebene")
    block = INDEX[start:ende]
    assert ".setIcon(" not in block      # der Kommentar darf das Wort nennen, der Code nicht
    assert "classList.toggle('vrp-gross', gross)" in block
    assert ".leaflet-container.vrp-gross .vrp-marke svg { transform: scale(1); }" in INDEX


def test_attribution_nennt_openaip():
    """CC BY-NC 4.0 verlangt die Namensnennung, und L.marker bringt anders als L.TileLayer
    keine mit — also von Hand, solange die Ebene an ist."""
    assert 'const _VRP_ATTR = \'&copy; <a href="https://www.openaip.net">OpenAIP</a>\';' in INDEX
    assert "_vrpAttributionAn(map)" in INDEX
    assert "_vrpAttributionAus(map)" in INDEX


def test_eigener_merker_schluessel():
    """Ein geteilter Schlüssel überschriebe beim Umschalten den Zustand einer anderen Ebene."""
    assert "const _VRP_PREF_KEY = 'friesenspy_vrp';" in INDEX
    assert "_prefSchreib(_VRP_PREF_KEY" in INDEX


def test_ebene_ist_im_kniebrett_nicht_ausgeblendet():
    """Anders als das Mithören: Meldepunkte sind im Cockpit genau das, was man braucht."""
    assert "html.vr-panel .vrp-marke" not in INDEX
