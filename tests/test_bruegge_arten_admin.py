# -*- coding: utf-8 -*-
"""Arten anlegen, ändern, löschen — und was das Löschen kostet.

Der Endpunkt `/api/admin/bruegge/arten` gab es schon, eine Bedienung dafür nicht: Der Admin
LAS die Liste (Auswahllisten, Titelverwaltung), aber anlegen ließ sich eine Art nur von Hand
in der Datenbank. Nutzerwunsch vom 16.09.2026: *„dann brauche ich eine Option, neue Arten
anzulegen, zu ändern und zu löschen (beim löschen passwort)"*.

⚠ **Das Passwort ist der eigentliche Punkt dieser Datei.** Löschen gibt die Titel frei —
bei `tier_gross` wären das über hundert Zuordnungen, die niemand wiederherstellen kann,
weil es sie nur an dieser einen Stelle gibt. Anlegen und Ändern sind rückgängig zu machen,
Löschen nicht.
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def klient(tmp_path, monkeypatch):
    """Nach dem Muster von tests/test_bruegge_endpunkt.py.

    `require_admin` wird überbrückt, `require_confirm` NICHT — sonst prüfte diese Datei
    genau das nicht, wofür sie da ist.
    """
    import app.main as main
    from app.database import init_db

    pfad = str(tmp_path / "t.db")
    init_db(pfad)
    settings = SimpleNamespace(
        DB_PATH=pfad, CALLSIGN_PREFIX="FRS",
        SECRET_KEY="test-nur-fuer-diesen-lauf", ADMIN_PASSWORD="test",
        SSO_SECRET="", FORUM_SSO_URL="", FORUM_SSO_CALLBACK="",
        USER_SESSION_MAX_AGE_SEC=3600, OPENAIP_API_KEY="", VAPID_PUBLIC_KEY="",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "require_admin", lambda request: None)
    if hasattr(main, "_reset_gate_cache"):
        main._reset_gate_cache()
    k = TestClient(main.app)
    k.db = pfad
    return k


def _arten(klient) -> dict:
    d = klient.get("/api/admin/bruegge/arten").json()
    return {a["art"]: a for a in d["arten"]}


class TestAnlegenUndAendern:
    def test_neue_art_anlegen_braucht_kein_passwort(self, klient):
        """Anlegen ist folgenlos — eine Art ohne Titel geht nirgends hinaus."""
        r = klient.post("/api/admin/bruegge/arten",
                        json={"art": "hochsitz", "bedeutung": "Ein Hochsitz"})
        assert r.status_code == 200, r.text
        a = _arten(klient)["hochsitz"]
        assert a["bedeutung"] == "Ein Hochsitz"
        assert a["anforderbar"] is False          # kein Titel → nichts zu liefern
        assert a["gesperrt_weil"] == "kein aktiver Titel"

    def test_bedeutung_aendern_braucht_kein_passwort(self, klient):
        klient.post("/api/admin/bruegge/arten", json={"art": "hochsitz", "bedeutung": "alt"})
        r = klient.post("/api/admin/bruegge/arten", json={"art": "hochsitz", "bedeutung": "neu"})
        assert r.status_code == 200
        assert _arten(klient)["hochsitz"]["bedeutung"] == "neu"

    def test_abschalten_braucht_kein_passwort(self, klient):
        """Abschalten ist die rückgängig zu machende Alternative zum Löschen.

        Genau deshalb darf sie nicht hinter dem Passwort liegen: Wer eine Art loswerden
        will, soll den harmlosen Weg bequemer haben als den endgültigen.
        """
        r = klient.post("/api/admin/bruegge/arten",
                        json={"art": "tier_gross", "status": "aus"})
        assert r.status_code == 200
        a = _arten(klient)["tier_gross"]
        assert a["art_status"] == "aus"
        assert a["gesperrt_weil"] == "vom Nutzer abgeschaltet"
        assert a["titel_gesamt"] > 0              # die Titel sind NICHT weg

    def test_tippfehler_wird_abgewiesen(self, klient):
        r = klient.post("/api/admin/bruegge/arten", json={"art": "Hoch Sitz"})
        assert r.status_code == 400


class TestLoeschenVerlangtPasswort:
    """Der Regressionstest. Ohne `require_confirm` im Löschzweig ist er grün — nachgeprüft."""

    def test_ohne_bestaetigung_403_und_die_art_steht_noch(self, klient):
        vorher = _arten(klient)["tier_gross"]["titel_gesamt"]
        assert vorher > 0

        r = klient.post("/api/admin/bruegge/arten",
                        json={"art": "tier_gross", "loeschen": True})
        assert r.status_code == 403
        assert r.json()["detail"] == "confirm_required"

        # ⚠ Der wichtigere Teil: nicht nur die Antwort, auch die WIRKUNG muss ausbleiben.
        # Ein Endpunkt, der erst löscht und dann 403 meldet, bestünde die Zeile darüber.
        nachher = _arten(klient)
        assert "tier_gross" in nachher
        assert nachher["tier_gross"]["titel_gesamt"] == vorher

    def test_mit_bestaetigung_geht_die_art_weg_und_die_titel_bleiben(self, klient, monkeypatch):
        import app.main as main
        from app.database import get_connection
        monkeypatch.setattr(main, "require_confirm", lambda request: None)

        conn = get_connection(klient.db)
        titel_vorher = conn.execute("SELECT COUNT(*) FROM bruegge_katalog").fetchone()[0]
        zugeordnet = conn.execute(
            "SELECT COUNT(*) FROM bruegge_katalog WHERE art = 'tier_gross'").fetchone()[0]
        conn.close()
        assert zugeordnet > 0

        r = klient.post("/api/admin/bruegge/arten",
                        json={"art": "tier_gross", "loeschen": True})
        assert r.status_code == 200
        assert r.json()["geloescht"] == 1
        assert "tier_gross" not in _arten(klient)

        conn = get_connection(klient.db)
        try:
            # „Wer eine Art wegnimmt, wollte die Bedeutung los, nicht die Objekte."
            assert conn.execute("SELECT COUNT(*) FROM bruegge_katalog").fetchone()[0] == titel_vorher
            assert conn.execute(
                "SELECT COUNT(*) FROM bruegge_katalog WHERE art = 'tier_gross'"
            ).fetchone()[0] == 0
        finally:
            conn.close()

    def test_anlegen_bleibt_frei_wenn_loeschen_gesperrt_ist(self, klient):
        """Die Sperre darf nur den Löschzweig treffen, nicht den ganzen Endpunkt.

        Beides liegt hinter DERSELBEN URL — ein `require_confirm` eine Zeile zu weit oben
        hätte auch das Anlegen passwortpflichtig gemacht, und niemand hätte es gemerkt,
        solange das Bestätigungsfenster im Browser noch offen war.
        """
        assert klient.post("/api/admin/bruegge/arten",
                           json={"art": "hochsitz"}).status_code == 200


class TestBedienungImAdmin:
    """Die Oberfläche — nach dem Muster von tests/test_vr_panel.py am Quelltext geprüft.

    Der Endpunkt allein nützt nichts: Er stand seit dem 14.09.2026 da, und trotzdem ließ
    sich keine Art anlegen, weil `admin.html` ihn nur GET-seitig kannte.
    """

    def _admin(self):
        from pathlib import Path
        return Path(__file__).resolve().parent.parent.joinpath(
            "app", "static", "admin.html").read_text(encoding="utf-8")

    def test_admin_ruft_den_endpunkt_schreibend(self):
        s = self._admin()
        assert "bgArtSpeichern" in s
        assert "bgArtLoeschen" in s
        assert "bgArtenZeichnen" in s

    def test_die_bedienelemente_stehen_da(self):
        s = self._admin()
        for kennung in ("bg-a-neu-art", "bg-a-neu-bedeutung", "bg-a-anlegen", "bg-arten"):
            assert f'id="{kennung}"' in s, kennung

    def test_loeschen_warnt_vor_der_folge(self):
        """Die Titel verlieren ihre Zuordnung — das muss VOR dem Klick dastehen."""
        s = self._admin()
        assert "data-a-loeschen" in s
        assert "Zuordnung" in s

    def test_die_liste_liegt_in_einem_scrollbaren_wrapper(self):
        """UI-Standard aus CLAUDE.md: breite Tabellen sind waagerecht scrollbar."""
        s = self._admin()
        i = s.index('id="bg-arten"')
        assert "table-wrap" in s[max(0, i - 1200):i]
