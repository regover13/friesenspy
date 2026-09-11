// Probeflug X-Plane: Laesst sich ein Objekt zur Laufzeit setzen -- und bleibt es?
//
// Das Gegenstueck zu friesenbruegge/probe-msfs/. Dieselbe Frage, andere Schnittstelle:
// X-Plane kennt kein SimConnect und keine Container-Titel, sondern laedt eine .obj-Datei
// und zeichnet sie als "Instanz".
//
// Vier Dinge sind hier anders als in MSFS, und alle vier sind der Grund, warum das
// gemessen und nicht angenommen gehoert:
//
//   1. KEIN Container-Titel. XPLMLoadObject will einen Dateipfad relativ zum
//      X-System-Ordner. Ob "Resources/default scenery/sim objects/dynamic/SailBoat.obj"
//      in X-Plane 12 existiert, ist die erste offene Frage -- der Pfad stammt aus einer
//      Doku, nicht von Laminar. Deshalb probiert das Plugin MEHRERE Pfade der Reihe nach
//      und meldet, welcher trug.
//   2. KEINE Weltkoordinaten. Gezeichnet wird in lokalen Metern (OpenGL), umgerechnet mit
//      XPLMWorldToLocal. Dieses lokale System VERSCHIEBT SICH, wenn der Flieger weit
//      genug fliegt -- ohne Gegenmassnahme wandert ein "feststehendes" Objekt davon.
//      XPLMInstanceSetAutoShift (X-Plane 12) laesst X-Plane das selbst nachfuehren.
//   3. KEIN OnGround=1. In MSFS setzte der Sim das Objekt selbst auf Gelaende oder Wasser.
//      Hier muss die Hoehe gefragt werden: XPLMProbeTerrainXYZ.
//   4. Die Objekte gehoeren dem Plugin, nicht einer Verbindung. In MSFS starben sie beim
//      SimConnect_Close -- ob X-Plane das auch so haelt, sagt erst der Versuch.
//
// Rueckkanal wie beim WASM-Modul: jeder Schritt geht per HTTP an horcher.py auf
// 127.0.0.1:8099. Ein Plugin ist ein normaler Prozess im Sim, Netzzugriff ist hier -- anders
// als bei WASM -- keine offene Frage.

// ACHTUNG, Reihenfolge: winsock2.h MUSS vor allem stehen, was windows.h einzieht -- und
// die XPLM-Header tun das. Andernfalls kommt zuerst das alte winsock.h (1.1) herein und
// winsock2.h kollidiert damit ("sockaddr: struct Typneudefinition", Dutzende Folgefehler).
// WIN32_LEAN_AND_MEAN haelt winsock.h aus windows.h heraus.
#define WIN32_LEAN_AND_MEAN 1
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#define XPLM200 1
#define XPLM210 1
#define XPLM300 1
#define XPLM301 1
#define XPLM400 1
#define XPLM410 1
#define XPLM420 1

#include "XPLMPlugin.h"
#include "XPLMProcessing.h"
#include "XPLMDataAccess.h"
#include "XPLMGraphics.h"
#include "XPLMScenery.h"
#include "XPLMInstance.h"
#include "XPLMUtilities.h"

#include <cstdio>
#include <cstring>
#include <string>

#pragma comment(lib, "ws2_32.lib")

// Kandidaten fuer das Boot. Der erste, der laedt, gewinnt -- und sein Name ist ein
// Ergebnis, das im Bericht stehen muss.
static const char* KANDIDATEN[] = {
    "Resources/default scenery/sim objects/dynamic/SailBoat.obj",
    "Resources/default scenery/sim objects/dynamic/Boat.obj",
    "Resources/default scenery/sim objects/dynamic/ship.obj",
    "Resources/default scenery/sim objects/apt objects/boat.obj",
    nullptr,
};

static XPLMObjectRef   g_obj = nullptr;
static XPLMInstanceRef g_instanz = nullptr;
static XPLMProbeRef    g_probe = nullptr;
static XPLMDataRef     g_lat = nullptr, g_lon = nullptr;
static int             g_takt = 0;
static double          g_ziel_lat = 0, g_ziel_lon = 0;

// ---------------------------------------------------------------------------
// Rueckkanal. Ein roher HTTP-GET ueber Winsock -- keine Bibliothek, damit der Bau
// nichts weiter braucht als das SDK.
// Alles, was in einer URL Aerger macht, wird zu %XX. Ohne das zerbricht ein Wert mit
// LEERZEICHEN die ganze Anfrage: "GET /xplane?wert=Resources/default scenery/... HTTP/1.1"
// liest der Server als Pfad "…/default" und Version "scenery/sim" -- die Meldung geht
// verloren, und im Server hagelt es Tracebacks. Genau das ist am 11.09.2026 passiert: Die
// wichtigste Zeile (welcher .obj-Pfad traegt) fehlte im Protokoll, obwohl alles lief.
static std::string url_sicher(const char* roh)
{
    static const char* HEX = "0123456789ABCDEF";
    std::string aus;
    for (const unsigned char* p = (const unsigned char*)roh; *p; ++p) {
        if (isalnum(*p) || *p == '-' || *p == '_' || *p == '.' || *p == '~') {
            aus += (char)*p;
        } else {
            aus += '%';
            aus += HEX[*p >> 4];
            aus += HEX[*p & 15];
        }
    }
    return aus;
}

static void melde(const char* schritt, const char* wert)
{
    std::string w = url_sicher(wert);
    char anfrage[1400];
    std::snprintf(anfrage, sizeof(anfrage),
                  "GET /xplane?schritt=%s&wert=%s HTTP/1.1\r\n"
                  "Host: 127.0.0.1:8099\r\nConnection: close\r\n\r\n",
                  schritt, w.c_str());

    char zeile[900];
    std::snprintf(zeile, sizeof(zeile), "[FriesenBruegge] %s = %s\n", schritt, wert);
    XPLMDebugString(zeile);      // landet zusaetzlich in Log.txt

    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) return;
    sockaddr_in ziel{};
    ziel.sin_family = AF_INET;
    ziel.sin_port = htons(8099);
    inet_pton(AF_INET, "127.0.0.1", &ziel.sin_addr);
    if (connect(s, (sockaddr*)&ziel, sizeof(ziel)) == 0) {
        send(s, anfrage, (int)std::strlen(anfrage), 0);
    }
    closesocket(s);
}

static void melde_zahl(const char* schritt, double wert)
{
    char puffer[64];
    std::snprintf(puffer, sizeof(puffer), "%.5f", wert);
    melde(schritt, puffer);
}

// ---------------------------------------------------------------------------
// Wird einmal aufgerufen, sobald ein Flug laeuft. Vorher ist die Position unbrauchbar --
// dieselbe Falle wie in MSFS, wo das Hauptmenue 0/90 lieferte.
static void boot_setzen()
{
    double m_lat = XPLMGetDatad(g_lat);
    double m_lon = XPLMGetDatad(g_lon);
    melde_zahl("flugzeug_lat", m_lat);
    melde_zahl("flugzeug_lon", m_lon);

    // 200 m oestlich, wie in MSFS.
    g_ziel_lat = m_lat;
    g_ziel_lon = m_lon + 200.0 / (111320.0 * 0.60);

    // --- Objekt laden: welcher Pfad traegt? ---
    for (int i = 0; KANDIDATEN[i]; ++i) {
        g_obj = XPLMLoadObject(KANDIDATEN[i]);
        if (g_obj) {
            melde("objekt_geladen", KANDIDATEN[i]);
            break;
        }
        melde("pfad_fehlgeschlagen", KANDIDATEN[i]);
    }
    if (!g_obj) {
        melde("ABBRUCH", "kein_ladbares_objekt_gefunden");
        return;
    }

    // --- Hoehe: das Gegenstueck zu OnGround=1 ---
    double x, y, z;
    XPLMWorldToLocal(g_ziel_lat, g_ziel_lon, 0.0, &x, &y, &z);

    XPLMProbeInfo_t treffer{};
    treffer.structSize = sizeof(treffer);
    XPLMProbeResult pr = XPLMProbeTerrainXYZ(g_probe, (float)x, (float)y, (float)z, &treffer);
    if (pr == xplm_ProbeHitTerrain) {
        melde_zahl("gelaende_y", treffer.locationY);
        y = treffer.locationY;      // auf den Boden setzen
    } else {
        melde("probe_ergebnis", pr == xplm_ProbeError ? "fehler" : "kein_treffer");
    }

    // --- Instanz erzeugen und positionieren ---
    const char* keine_datarefs[] = { nullptr };
    g_instanz = XPLMCreateInstance(g_obj, keine_datarefs);
    if (!g_instanz) {
        melde("ABBRUCH", "XPLMCreateInstance_lieferte_null");
        return;
    }
    melde("instanz_erzeugt", "ok");

    XPLMDrawInfo_t lage{};
    lage.structSize = sizeof(lage);
    lage.x = (float)x;
    lage.y = (float)y;
    lage.z = (float)z;
    lage.pitch = 0;
    lage.heading = 210;
    lage.roll = 0;
    float leer = 0;
    XPLMInstanceSetPosition(g_instanz, &lage, &leer);
    melde("position_gesetzt", "ok");

    // Damit das Objekt stehen bleibt, wenn das lokale Koordinatensystem wandert.
    // Nimmt nur die Instanz -- kein Ein/Aus-Schalter, der Aufruf selbst IST das Einschalten.
    XPLMInstanceSetAutoShift(g_instanz);
    melde("ERFOLG_autoshift_an", "1");
}

// ---------------------------------------------------------------------------
static float takt(float, float, int, void*)
{
    ++g_takt;
    if (g_takt == 10) {          // ~10 s nach Start: der Flug steht
        boot_setzen();
    }
    if (g_takt > 10 && g_takt % 30 == 0) {
        // Lebenszeichen -- zeigt, ob die Instanz ueberdauert.
        melde("laeuft_noch_sekunden", std::to_string(g_takt).c_str());
    }
    return 1.0f;                 // jede Sekunde wieder
}

// ---------------------------------------------------------------------------
PLUGIN_API int XPluginStart(char* name, char* sig, char* beschreibung)
{
    std::strcpy(name, "FriesenBruegge Probe");
    std::strcpy(sig, "de.friesenflieger.bruegge.probe");
    std::strcpy(beschreibung, "Misst, ob sich Objekte zur Laufzeit setzen lassen.");

    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
    melde("XPluginStart", "geladen");

    g_lat = XPLMFindDataRef("sim/flightmodel/position/latitude");
    g_lon = XPLMFindDataRef("sim/flightmodel/position/longitude");
    melde("datarefs", (g_lat && g_lon) ? "gefunden" : "FEHLEN");

    g_probe = XPLMCreateProbe(xplm_ProbeY);
    XPLMRegisterFlightLoopCallback(takt, 1.0f, nullptr);
    return 1;
}

PLUGIN_API void XPluginStop(void)
{
    melde("XPluginStop", "entladen");
    if (g_instanz) XPLMDestroyInstance(g_instanz);
    if (g_obj)     XPLMUnloadObject(g_obj);
    if (g_probe)   XPLMDestroyProbe(g_probe);
    XPLMUnregisterFlightLoopCallback(takt, nullptr);
    WSACleanup();
}

PLUGIN_API int  XPluginEnable(void)  { melde("XPluginEnable", "1"); return 1; }
PLUGIN_API void XPluginDisable(void) { melde("XPluginDisable", "0"); }
PLUGIN_API void XPluginReceiveMessage(XPLMPluginID, int, void*) {}
