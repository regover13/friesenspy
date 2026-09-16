# -*- coding: utf-8 -*-
"""„Deine Fassung ist veraltet" — der einzige Weg, der den Piloten erreicht (16.09.2026).

**Die FriesenBrügge kann selbst nichts sagen.** Sie schreibt nach ``stderr`` (MSFS) bzw.
``XPLMDebugString`` (X-Plane); im Flug sieht das niemand — selbst ihre eingebaute
426-Warnung („es hilft nur ein neues Paket") ist damit faktisch stumm. Und alles, was man
*in* sie einbaut, erreicht nur den, der schon aktualisiert hat, also gerade nicht den, um den
es geht. Bleiben Website und Kniebrett.

Beide Brügge senden ihre Fassung seit jeher mit (``bruegge_version``, MSFS wie X-Plane) — der
Server hat sie bis zu diesem Stand **weggeworfen**. Damit ließ sich nicht einmal beantworten,
wer veraltet unterwegs ist.

Der Test bindet beide Enden: den Server (speichern, vergleichen, ausliefern) und den
Hinweiskasten in `index.html`, der die Antwort auswertet.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.database import (get_connection, init_db, touch_panel_device,
                          bind_panel_device, bruegge_zuordnung_setzen,
                          bruegge_version_merken, set_app_setting)
from app.forum_sso import USER_COOKIE, make_user_token
from tests.test_bruegge_endpunkt import (  # noqa: F401  (`klient` ist eine Fixture)
    klient, _meldung, _friese_anlegen,
)

SECRET = "s3cr3t-key"
CID = 1602713
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
_NODE = shutil.which("node")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    p = str(tmp_path / "t.db")
    init_db(p)
    settings = SimpleNamespace(
        DB_PATH=p, CALLSIGN_PREFIX="FRS", SECRET_KEY=SECRET, ADMIN_PASSWORD="pw",
        SSO_SECRET="shared-forum-secret", FORUM_SSO_URL="https://board.example/sso",
        FORUM_SSO_CALLBACK="https://friesenspy.example/sso/callback",
        USER_SESSION_MAX_AGE_SEC=1200, OPENAIP_API_KEY="", VAPID_PUBLIC_KEY="",
        BRUEGGE_PACKAGE_PATH="",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    # Die Fassungen kommen sonst aus den hinterlegten ZIPs -- die gibt es im Test nicht, und
    # ein fehlendes Archiv heißt „keine Aussage" (dann ist NICHTS veraltet). Genau deshalb
    # wird hier gesetzt statt gemockt-weggelassen: Sonst wären alle Prüfungen grün, ohne
    # etwas zu prüfen.
    monkeypatch.setattr(main, "_bruegge_paket_info",
                        lambda sim: {"verfuegbar": True,
                                     "version": "1.12.0" if sim == "msfs" else "1.2.2"})
    monkeypatch.setattr(main, "_efb_package_version", lambda pfad: "2.3.0")
    main._reset_gate_cache()
    # Ohne scharfgeschaltetes Board-Login gibt `_current_cid` grundsaetzlich None zurueck --
    # dann waere jede Pruefung hier gruen, ohne etwas zu pruefen.
    conn = get_connection(p)
    set_app_setting(conn, "forum_login_enabled", "1")
    conn.commit()
    conn.close()
    return SimpleNamespace(client=TestClient(main.app), db=p)


def _cookie(cid: int = CID) -> dict:
    return {USER_COOKIE: make_user_token(SECRET, "Tobias", str(cid), False, time.time() + 3600)}


def _bruegge_anlegen(db, kennung="K1", simulator="msfs2024", version="1.9.0", cid=CID):
    conn = get_connection(db)
    bruegge_zuordnung_setzen(conn, kennung, cid, simulator)
    bruegge_version_merken(conn, kennung, version)
    conn.commit()
    conn.close()


class TestServer:
    def test_ohne_anmeldung_gibt_es_nichts_zu_sagen(self, env):
        """Kein Fehler: Die Seite fragt bei jedem Aufbau, ein 401 wäre ein Fehlalarm."""
        r = env.client.get("/api/me/fassungen")
        assert r.status_code == 200
        assert r.json()["bruegge"]["meine"] == []

    def test_eine_alte_bruegge_wird_als_veraltet_gemeldet(self, env):
        _bruegge_anlegen(env.db, version="1.9.0")
        d = env.client.get("/api/me/fassungen", cookies=_cookie()).json()
        (b,) = d["bruegge"]["meine"]
        assert b["version"] == "1.9.0" and b["aktuell"] == "1.12.0"
        assert b["veraltet"] is True

    def test_die_neueste_fassung_loest_nichts_aus(self, env):
        _bruegge_anlegen(env.db, version="1.12.0")
        (b,) = env.client.get("/api/me/fassungen", cookies=_cookie()).json()["bruegge"]["meine"]
        assert b["veraltet"] is False

    def test_zeichenkettenvergleich_waere_falschherum(self, env):
        """`"1.9.0" > "1.10.0"` als Text — der Vergleich muss zahlenweise sein."""
        _bruegge_anlegen(env.db, version="1.9.0", kennung="K1")
        d = env.client.get("/api/me/fassungen", cookies=_cookie()).json()
        assert d["bruegge"]["meine"][0]["veraltet"] is True

    def test_eine_bruegge_ohne_gemeldete_fassung_wird_nicht_verdaechtigt(self, env):
        """`None` heißt „hat noch nicht gemeldet", nicht „alt".

        Ein Hinweis auf Verdacht verbrennt das Vertrauen in alle anderen.
        """
        conn = get_connection(env.db)
        bruegge_zuordnung_setzen(conn, "K0", CID, "msfs2024")
        conn.commit()
        conn.close()
        (b,) = env.client.get("/api/me/fassungen", cookies=_cookie()).json()["bruegge"]["meine"]
        assert b["version"] is None and b["veraltet"] is False

    def test_xplane_wird_gegen_das_xplane_paket_gehalten(self, env):
        """Zwei Pakete, zwei Zahlen — eine X-Plane-Brügge 1.2.2 ist aktuell, keine 1.12.0."""
        _bruegge_anlegen(env.db, kennung="X1", simulator="xplane12", version="1.2.2")
        (b,) = env.client.get("/api/me/fassungen", cookies=_cookie()).json()["bruegge"]["meine"]
        assert b["aktuell"] == "1.2.2" and b["veraltet"] is False

    def test_fremde_brueggen_gehen_niemanden_etwas_an(self, env):
        _bruegge_anlegen(env.db, kennung="F1", cid=999999, version="1.0.0")
        d = env.client.get("/api/me/fassungen", cookies=_cookie()).json()
        assert d["bruegge"]["meine"] == []

    def test_auch_das_kniebrett_paket_steht_drin(self, env):
        """Der Zusatz vom 16.09.2026: auf der Website zählt auch das EFB-Paket."""
        conn = get_connection(env.db)
        bind_panel_device(conn, "d" * 40, CID, "Tablet")
        touch_panel_device(conn, "d" * 40, paket_version="2.1.0")
        conn.commit()
        conn.close()
        d = env.client.get("/api/me/fassungen", cookies=_cookie()).json()
        (k,) = d["kniebrett"]["meine"]
        assert k["version"] == "2.1.0" and k["veraltet"] is True
        assert k["geraet"] == "d" * 12, "die Geräte-ID ist ein Zugangsschlüssel — gekürzt"


class TestMeldungSpeichert:
    """Die Version muss beim Melden ankommen — sonst hat der Endpunkt oben nichts zu zeigen.

    Bis zum 16.09.2026 kam sie nicht an: Beide Brügge senden `bruegge_version` seit jeher,
    der Server hat das Feld gelesen und weggeworfen.
    """

    def test_die_gemeldete_fassung_landet_in_der_zuordnung(self, klient, tmp_path):
        db = str(tmp_path / "t.db")
        _friese_anlegen(db)
        klient.post("/api/bruegge/melden", json=_meldung(bruegge_version="1.7.3"))
        conn = get_connection(db)
        row = conn.execute("SELECT bruegge_version FROM bruegge_zuordnung").fetchone()
        conn.close()
        assert row is not None and row[0] == "1.7.3"

    def test_eine_meldung_ohne_feld_loescht_die_bekannte_fassung_nicht(self, klient, tmp_path):
        """Sonst sähe ein Ausfall des Feldes aus wie ein Gerät, das nie gemeldet hat."""
        db = str(tmp_path / "t.db")
        _friese_anlegen(db)
        klient.post("/api/bruegge/melden", json=_meldung(bruegge_version="1.7.3"))
        ohne = _meldung()
        ohne.pop("bruegge_version", None)
        klient.post("/api/bruegge/melden", json=ohne)
        conn = get_connection(db)
        row = conn.execute("SELECT bruegge_version FROM bruegge_zuordnung").fetchone()
        conn.close()
        assert row[0] == "1.7.3"


@pytest.mark.skipif(not _NODE, reason="node fehlt")
class TestHinweisImBrowser:
    """Der Kasten selbst — ausgeführt, nicht nur gelesen."""

    def _lauf(self, antwort: dict, im_panel=False, merker=None) -> dict:
        start = INDEX.index("const _FASSUNG_HINWEIS_KEY")
        ende = INDEX.index("function _paketHinweisWeg(")
        quelle = INDEX[start:ende]
        harness = """
'use strict';
const zustand = { text: '', versteckt: true, gemerkt: null, dataset: {} };
const kasten = { hidden: true, dataset: zustand.dataset };
Object.defineProperty(kasten, 'hidden', {
  get: () => zustand.versteckt, set: (v) => { zustand.versteckt = v; },
});
const textFeld = { set textContent(v) { zustand.text = v; }, get textContent() { return zustand.text; } };
global.document = {
  documentElement: { classList: { contains: (k) => k === 'vr-panel' && IM_PANEL } },
  getElementById: (id) => id === 'fassung-hinweis' ? kasten
                        : id === 'fassung-hinweis-text' ? textFeld : null,
};
global.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(ANTWORT) });
global._prefLies = () => MERKER;
global._prefSchreib = (k, v) => { zustand.gemerkt = v; };
QUELLE
_fassungenPruefen();
setTimeout(() => {
  // ERST ablesen, DANN wegklicken -- sonst misst der Test seinen eigenen Klick. (Genau so
  // ist er beim ersten Anlauf rot geworden, und der Code war richtig.)
  const gesehen = { text: zustand.text, versteckt: zustand.versteckt };
  _fassungHinweisWeg();
  console.log(JSON.stringify(Object.assign(gesehen, { gemerkt: zustand.gemerkt })));
}, 30);
"""
        js = (harness
              .replace("IM_PANEL", "true" if im_panel else "false")
              .replace("ANTWORT", json.dumps(antwort))
              .replace("MERKER", json.dumps(merker))
              .replace("QUELLE", quelle))
        p = subprocess.run([_NODE, "-e", js], capture_output=True, text=True, timeout=20)
        assert p.returncode == 0, p.stderr
        return json.loads(p.stdout.strip().splitlines()[-1])

    def _antwort(self, bruegge=(), kniebrett=()):
        return {"bruegge": {"aktuell": {"msfs": "1.12.0", "xplane": "1.2.2"},
                            "meine": list(bruegge)},
                "kniebrett": {"aktuell": "2.3.0", "meine": list(kniebrett)}}

    def test_eine_alte_bruegge_zeigt_den_kasten(self):
        z = self._lauf(self._antwort(bruegge=[
            {"kennung": "K1", "simulator": "msfs2024", "version": "1.9.0",
             "aktuell": "1.12.0", "veraltet": True}]))
        assert z["versteckt"] is False
        assert "1.9.0" in z["text"] and "1.12.0" in z["text"]
        assert "friesenspy.devprops.de/download" in z["text"], (
            "im Kniebrett lässt sich nichts herunterladen — die Adresse muss dastehen")

    def test_ist_alles_aktuell_bleibt_es_still(self):
        z = self._lauf(self._antwort(bruegge=[
            {"kennung": "K1", "simulator": "msfs2024", "version": "1.12.0",
             "aktuell": "1.12.0", "veraltet": False}]))
        assert z["versteckt"] is True

    def test_nur_die_juengste_bruegge_je_simulator_zaehlt(self):
        """Die Kennung wechselt bei jedem Sim-Start — ältere Zeilen sind Karteileichen.

        Ohne diese Regel stünde eine Dauerwarnung für eine Fassung da, die längst ersetzt ist.
        """
        z = self._lauf(self._antwort(bruegge=[
            {"kennung": "neu", "simulator": "msfs2024", "version": "1.12.0",
             "aktuell": "1.12.0", "veraltet": False},
            {"kennung": "alt", "simulator": "msfs2024", "version": "1.9.0",
             "aktuell": "1.12.0", "veraltet": True}]))
        assert z["versteckt"] is True

    def test_auf_der_website_zaehlt_auch_das_kniebrett_paket(self):
        z = self._lauf(self._antwort(kniebrett=[
            {"geraet": "abc", "version": "2.1.0", "veraltet": True}]))
        assert z["versteckt"] is False and "Kniebrett-Paket" in z["text"]

    def test_im_kniebrett_bleibt_das_paket_seinem_eigenen_hinweis_ueberlassen(self):
        """Dort meldet die Hülle die wirklich laufende Fassung — zwei Kästen wären dieselbe
        Nachricht zweimal."""
        z = self._lauf(self._antwort(kniebrett=[
            {"geraet": "abc", "version": "2.1.0", "veraltet": True}]), im_panel=True)
        assert z["versteckt"] is True

    def test_weggeklickt_gilt_fuer_genau_diesen_stand(self):
        eintrag = [{"kennung": "K1", "simulator": "msfs2024", "version": "1.9.0",
                    "aktuell": "1.12.0", "veraltet": True}]
        z = self._lauf(self._antwort(bruegge=eintrag))
        assert z["gemerkt"] and "1.9.0" in z["gemerkt"]
        # Mit genau diesem Merker kommt er nicht wieder ...
        z2 = self._lauf(self._antwort(bruegge=eintrag), merker=z["gemerkt"])
        assert z2["versteckt"] is True
        # ... bei einer neueren Fassung dagegen schon.
        eintrag2 = [dict(eintrag[0], aktuell="1.13.0")]
        z3 = self._lauf(self._antwort(bruegge=eintrag2), merker=z["gemerkt"])
        assert z3["versteckt"] is False


class TestBeideEnden:
    """Server und Seite müssen denselben Endpunkt meinen."""

    def test_die_seite_fragt_den_endpunkt_den_es_gibt(self):
        assert "/api/me/fassungen" in INDEX
        quelle = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(
            encoding="utf-8")
        assert '@app.get("/api/me/fassungen")' in quelle

    def test_der_endpunkt_liegt_nicht_hinter_dem_gate(self):
        """`/api/me` steht in der Allowlist — sonst käme die Antwort nie an."""
        assert any(p in ("/api/me",) for p in main._GATE_ALLOW_PREFIXES)
