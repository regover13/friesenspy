"""Prueft den C++-Quelltext der Bruegge auf die Fallstricke aus
`docs/superpowers/specs/2026-09-13-bruegge-posix-design.md`.

Fuer C++ gibt es hier keine Testsuite, und jeder dieser Funde ist "eine Zeile fehlt" --
genau das laesst sich als Text pruefen. Kommentare werden vorher entfernt: Sonst findet
die Suche die Erklaerung statt der Anweisung.
"""
import re
from pathlib import Path

BRUEGGE = Path(__file__).resolve().parent.parent / "friesenbruegge"


def quelltext(name: str) -> str:
    """Dateiinhalt ohne // - und /* */ - Kommentare."""
    roh = (BRUEGGE / name).read_text(encoding="utf-8")
    ohne_block = re.sub(r"/\*.*?\*/", " ", roh, flags=re.S)
    return re.sub(r"//[^\n]*", "", ohne_block)


def test_native_paths_ist_eingeschaltet():
    """Ohne diese Zeile liefert XPLMGetSystemPath auf macOS HFS-Pfade mit Doppelpunkten.
    Dann findet die Bruegge ihre .url-Datei nie -- der Pruefserver-Weg waere auf dem Mac tot."""
    q = quelltext("xplane/bruegge.cpp")
    assert 'XPLMEnableFeature("XPLM_USE_NATIVE_PATHS", 1)' in q


def test_native_paths_steht_vor_jedem_pfadzugriff():
    """Die Reihenfolge ist der ganze Punkt: nach dem ersten fopen waere die Zeile wirkungslos.

    Gesucht wird NUR innerhalb von XPluginStart. Ueber die ganze Datei gesucht, faende
    `q.index("ziel_laden()")` die Funktionsdefinition weiter oben statt des Aufrufs --
    der Test waere dann dauerhaft rot, ohne dass etwas kaputt waere."""
    q = quelltext("xplane/bruegge.cpp")
    block = q[q.index("PLUGIN_API int XPluginStart"):]
    feature = block.index('XPLMEnableFeature("XPLM_USE_NATIVE_PATHS"')
    for aufruf in ("ziel_laden()", "kennung_laden_oder_erzeugen()"):
        assert feature < block.index(aufruf), f"{aufruf} laeuft vor XPLMEnableFeature"


def test_json_h_rechnet_ohne_locale():
    """%f und strtod fragen LC_NUMERIC. Ein deutscher Pilot meldete sonst 52,123 --
    und laese aus der Antwort des Servers "53.5" eine 53. Gemessen am 13.09.2026."""
    q = quelltext("json.h")
    assert "strtod" not in q
    assert '"%.*f"' not in q


# --------------------------------------------------------------------------------------
# Die POSIX-Fassung: Netz und Nebenlaeufigkeit (Spec, Abschnitte 4 und 5)
# --------------------------------------------------------------------------------------

WIN32_RESTE = ("CreateThread", "CRITICAL_SECTION", "EnterCriticalSection",
               "WaitForSingleObject", "SetEvent", "GetTickCount64", "GetCurrentProcessId",
               "InterlockedExchange", "InterlockedCompareExchange")


def test_netz_h_kennt_kein_xplm():
    """netz.h muss ohne das SDK uebersetzbar bleiben -- sonst ist die Schicht ohne Simulator
    nicht messbar, und fuer macOS und Linux ist das der einzige Test vor dem ersten Piloten."""
    q = quelltext("xplane/netz.h")
    assert "XPLM" not in q


def test_netzthread_meldet_nicht_selbst_ins_log():
    """Das SDK ist nicht threadsicher. Eine XPLMDebugString-Zeile im Netzthread reicht fuer
    einen Absturz, den niemand reproduziert -- deshalb der Ringpuffer."""
    q = quelltext("xplane/netz.h")
    assert "XPLMDebugString" not in q
    assert "netz_log_abholen" in q


def test_keine_win32_nebenlaeufigkeit_mehr():
    """Thread, Wecker und Zeit laufen auf der Standardbibliothek -- auf ALLEN drei
    Plattformen. Zwei Thread-Schichten hiessen: eine wird nie mitgeprueft."""
    for datei in ("xplane/netz.h", "xplane/bruegge.cpp"):
        q = quelltext(datei)
        for name in WIN32_RESTE:
            assert name not in q, f"{name} steht noch in {datei}"


def test_wait_hat_ein_praedikat():
    """Eine condition_variable merkt sich keinen Weckruf, ein Win32-Event schon. Ohne
    Praedikat ginge eine Meldung verloren, der Thread schliefe ewig, netz_ende haenge im join."""
    q = quelltext("xplane/netz.h")
    stelle = q.index("g_wecker.wait(")
    assert "[" in q[stelle:stelle + 120], "wait() ohne Praedikat"


def test_thread_wird_nicht_global_gehalten():
    """Ein globaler std::thread, der beim Entladen der Bibliothek noch joinable ist, ruft
    std::terminate -- X-Plane stuerbe beim Beenden."""
    q = quelltext("xplane/netz.h")
    assert "std::unique_ptr<std::thread>" in q


def test_nosignal_ist_gesetzt():
    """Bleibt gesetzt, auch wenn die Wirkung auf Linux nicht nachstellbar war: Der
    Resolver-Pfad und macOS sind ungemessen (Begruendung steht in netz.h)."""
    q = quelltext("xplane/netz.h")
    assert "CURLOPT_NOSIGNAL" in q


def test_long_optionen_tragen_ein_L():
    """Ein int belegt 4 Byte in einem 8-Byte-Fach; libcurl liest va_arg(long).
    Auf x86-64 klappt das zufaellig, auf arm64-macOS nicht -- und genau das kann der
    Prueflauf auf diesem Server nicht finden."""
    q = quelltext("xplane/netz.h")
    for option in ("CURLOPT_NOSIGNAL", "CURLOPT_CONNECTTIMEOUT", "CURLOPT_TIMEOUT"):
        stelle = q.index(option)
        zeile = q[stelle:q.index("\n", stelle)]
        assert re.search(r",\s*\d+L\s*\)", zeile), f"{option} ohne L-Suffix: {zeile.strip()}"


def test_setopt_zeiger_sind_variadisch():
    """Apple uebergibt variadische Argumente auf arm64 ueber den Stack statt in Registern."""
    q = quelltext("xplane/netz.h")
    assert "(CURL*, CURLoption, ...)" in q
    assert "(CURL*, CURLINFO, ...)" in q


def test_kein_access_vorabtest_auf_die_bibliothek():
    """Seit Big Sur liegen Systembibliotheken im dyld-Cache, nicht als Datei.
    access() schluege fehl, dlopen gelingt."""
    q = quelltext("xplane/netz.h")
    assert "access(" not in q


def test_voller_pfad_vor_nacktem_namen():
    """Sonst gewinnt auf einem Intel-Mac das Homebrew-curl mit eigenem OpenSSL statt Apples
    Bibliothek, der die Keychain vertraut -- und darauf beruht die ganze Entscheidung,
    keine eigene TLS-Bibliothek mitzuliefern."""
    q = quelltext("xplane/netz.h")
    assert q.index('"/usr/lib/libcurl.4.dylib"') < q.index('"libcurl.4.dylib"')


def test_dlopen_laeuft_nicht_im_netzthread():
    """netz_bereit holt libcurl und meldet den Fehlschlag -- das muss im Hauptthread
    geschehen, weil nur er ins Log schreiben darf."""
    q = quelltext("xplane/bruegge.cpp")
    block = q[q.index("PLUGIN_API int XPluginStart"):]
    assert block.index("netz_bereit(") < block.index("netz_start()")
