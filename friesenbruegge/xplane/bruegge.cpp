// Die FriesenBrügge für X-Plane 12.
//
// Das Gegenstück zu ../msfs/bruegge.cpp. DASSELBE Protokoll (../PROTOKOLL.md), derselbe
// Endpunkt, dieselbe Zustandsmaschine -- nur die drei Stellen, an denen der Simulator
// hereinreicht, sind andere:
//
//   1. LAGE       Datarefs statt SimConnect-Datendefinition.
//   2. OBJEKTE    Ein Dateipfad auf eine .obj statt eines Container-Titels, und eine
//                 INSTANZ statt eines AI-Objekts.
//   3. NETZ       Ein eigener Thread mit WinHTTP statt fsNetworkHttpRequestPost.
//
// Alles dazwischen -- Kennung, Spur, Sprungerkennung, Sollzustands-Abgleich, `steht` --
// ist bewusst Zeile für Zeile dieselbe Überlegung wie im WASM-Modul. Wo eine Lehre aus dem
// MSFS-Weg hier NICHT gilt, steht das dabei; wo sie gilt, steht sie hier nicht noch einmal,
// sondern in ../PROTOKOLL.md.
//
// ---------------------------------------------------------------------------------------
// ZWEI DINGE KANN X-PLANE BESSER, UND BEIDE ÄNDERN DEN ZUSCHNITT
// ---------------------------------------------------------------------------------------
//
// **Die Geländehöhe am ZIELORT ist zu haben.** `XPLMProbeTerrainXYZ` fragt an einer frei
// gewählten Koordinate, nicht unter dem Flugzeug. In MSFS gibt es das nicht: Dort bleibt nur
// `PLANE ALTITUDE - PLANE ALT ABOVE GROUND`, also die Höhe unter dem Flieger, und die stimmt
// 100 m weiter schon nicht mehr (am 12.09.2026 standen zwölf Objekte in einem Raster von
// 180 m: eines versunken, eines sauber, eines schwebend -- alle auf derselben angeforderten
// Höhe). Hier entfällt dieser ganze Fehlerzweig.
//
// **Eine Instanz lässt sich versetzen.** `XPLMInstanceSetPosition` darf jederzeit erneut
// aufgerufen werden. In MSFS legt `AICreateSimulatedObject` das Objekt an, und danach steht
// es -- ein Umsetzen heißt dort wegnehmen und neu erzeugen (s. `versetzt` in bruegge.cpp).
// Hier wird die Lage einfach neu gesetzt.
//
// Zusammen ergeben sie einen Weg, den MSFS nicht hat: Ein Objekt, das gesetzt wird, während
// sein Zielgelände noch gar nicht geladen ist, bekommt zunächst Meereshöhe -- und sobald die
// Probe trifft (der Pilot nähert sich), rückt die Brügge es auf das echte Gelände nach. Das
// Feld `hoehe_gemessen` in `steht` sagt dem Server, welcher der beiden Fälle vorliegt.
//
// ---------------------------------------------------------------------------------------
// WINDOWS ZUERST -- und warum das hier ehrlich dasteht
// ---------------------------------------------------------------------------------------
//
// Die Netzschicht ist WinHTTP, also Windows. Ein X-Plane-Plugin läuft auch auf macOS und
// Linux, und die Gruppe fliegt nicht nur Windows. Der Grund für die Einschränkung ist nicht
// Bequemlichkeit, sondern TLS: Der Endpunkt ist HTTPS, und das heißt auf jeder Plattform eine
// eigene Bibliothek (Secure Transport, OpenSSL) oder libcurl als Abhängigkeit. WinHTTP
// braucht nichts dazu.
//
// Die Trennlinie liegt deshalb an EINER Stelle (`netz_*` weiter unten). Wer macOS oder Linux
// nachrüstet, tauscht diesen Block und sonst nichts.

#define WIN32_LEAN_AND_MEAN 1
#include <windows.h>
#include <winhttp.h>

#define XPLM200 1
#define XPLM210 1
#define XPLM300 1
#define XPLM301 1
#define XPLM400 1
#define XPLM410 1

#include "XPLMPlugin.h"
#include "XPLMProcessing.h"
#include "XPLMDataAccess.h"
#include "XPLMGraphics.h"
#include "XPLMScenery.h"
#include "XPLMInstance.h"
#include "XPLMUtilities.h"

#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cstdint>
#include <cctype>

#include "../json.h"

#pragma comment(lib, "winhttp.lib")

// ---------------------------------------------------------------------------------------
// Feste Größen
// ---------------------------------------------------------------------------------------

// Die Fassung gehört der UMSETZUNG, nicht dem Protokoll. Das WASM-Modul steht bei 1.6.0,
// weil es sechs Runden im Simulator hinter sich hat; diese Brügge fängt bei 1.0.0 an. Was
// beide verbindet, ist `protokoll: 1` -- und das steht in der Meldung daneben.
#define BRUEGGE_VERSION   "1.0.0"
#define SIMULATOR_NAME    "xplane12"

#define BRUEGGE_HOST      L"friesenspy.devprops.de"
#define BRUEGGE_PFAD      L"/api/bruegge/melden"

// Wo die Kennung liegt. `Output/preferences` ist der von Laminar vorgesehene Ort für
// Plugin-Einstellungen und überlebt ein Neuinstallieren des Plugins -- neben der .xpl läge
// sie im selben Ordner, den ein Update überschreibt.
#define KENNUNG_DATEI     "Output/preferences/friesenbruegge.kennung"

#define SPUR_MAX 16
#define SPRUNG_GRAD 0.005         // rund 555 m in der Breite; 600 kt sind 309 m/s
#define MELDUNG_PUFFER 8192
#define ANTWORT_PUFFER 16384
#define SOLL_MAX 32
#define OBJEKTE_MAX 24            // verschiedene .obj gleichzeitig geladen

#define FT_JE_M 3.280839895

// Ein Objekt, das dastehen soll -- und wie es ihm ergangen ist.
struct SollObjekt {
    char   id[40];
    char   art[24];
    double lat, lon, kurs, erwartete_hoehe_ft;
    bool   hat_hoehe;
    bool   auf_boden;

    bool   belegt;
    bool   in_soll;
    int    titel_nr;              // welches Modell der Gattung gerade versucht wird
    XPLMInstanceRef instanz;      // 0 = noch nicht gesetzt
    bool   hoehe_gemessen;        // hat die Terrain-Probe getroffen?
    double hoehe_ft;              // die Höhe, auf der es TATSÄCHLICH steht
    unsigned seit_s;
    char   fehler[32];
};

static SollObjekt g_soll[SOLL_MAX];

struct Lage {
    double lat, lon;
    double alt_msl_ft, alt_agl_ft;
    double gs_kt, kurs, vs_ft_min;
    bool   am_boden;
};

struct SpurPunkt {
    double alter_s;
    double lat, lon, alt_msl_ft, gs_kt, kurs;
};

// ---------------------------------------------------------------------------------------
// Zustand
// ---------------------------------------------------------------------------------------

static unsigned g_sekunden = 0;
static Lage     g_lage = {};
static bool     g_lage_gueltig = false;
static double   g_vor_lat = 0.0, g_vor_lon = 0.0;
static bool     g_vor_gueltig = false;

static SpurPunkt g_spur[SPUR_MAX];
static int       g_spur_anzahl = 0;

static char     g_kennung[40] = {0};
static int      g_takt_s = 1;
static unsigned g_seit_meldung = 0;
static unsigned g_gilt_bis_s = 300;
static unsigned g_letzte_antwort_s = 0;
static unsigned long g_antwort_zu_gross = 0;

static XPLMDataRef g_dr_lat = nullptr, g_dr_lon = nullptr, g_dr_elev = nullptr;
static XPLMDataRef g_dr_agl = nullptr, g_dr_gs = nullptr, g_dr_psi = nullptr;
static XPLMDataRef g_dr_vs = nullptr, g_dr_boden = nullptr;
static XPLMProbeRef g_probe = nullptr;

static void logzeile(const char* text) {
    char z[512];
    std::snprintf(z, sizeof(z), "[FriesenBruegge] %s\n", text);
    XPLMDebugString(z);
}

// ---------------------------------------------------------------------------------------
// Kennung -- dauerhaft, je Installation
// ---------------------------------------------------------------------------------------
//
// Sie ist KEIN Geheimnis: Die Brügge erzeugt sie selbst, sie steht offen in jeder Meldung,
// und sie öffnet nichts. Sie sagt nur "ich bin dieselbe wie vorhin" und erspart dem Server
// den vollen Positionsmatch bei jeder Meldung.
//
// Hier ist das ERHEBLICH einfacher als in MSFS: Ein Plugin ist ein gewöhnlicher Prozess und
// darf die Datei einfach lesen und schreiben. Im WASM-Modul ist das asynchron, und genau
// daraus entstand dort ein Wettlauf -- das Schreiben überholte das eigene Lesen und legte bei
// jedem Start eine neue Kennung an (`g_kennung_fest` in ../msfs/bruegge.cpp).

static void kennung_pfad(char* aus, size_t n) {
    char wurzel[512] = {0};
    XPLMGetSystemPath(wurzel);
    // XPLMGetSystemPath liefert den Pfad MIT Trennzeichen am Ende. Windows nimmt '/' in
    // fopen ebenso an wie '\', deshalb ist hier keine Fallunterscheidung nötig.
    std::snprintf(aus, n, "%s%s", wurzel, KENNUNG_DATEI);
}

static void kennung_erzeugen() {
    // Eindeutig muss sie sein, nicht unvorhersagbar.
    unsigned long long a = (unsigned long long)GetCurrentProcessId();
    unsigned long long b = (unsigned long long)GetTickCount64();
    unsigned long long c = (unsigned long long)(uintptr_t)&g_soll[0];
    std::snprintf(g_kennung, sizeof(g_kennung), "%08llx%08llx",
                  (a ^ (c >> 8)) & 0xFFFFFFFFull, (b ^ (c << 4)) & 0xFFFFFFFFull);
}

static void kennung_laden_oder_erzeugen() {
    char pfad[640];
    kennung_pfad(pfad, sizeof(pfad));

    FILE* f = std::fopen(pfad, "rb");
    if (f) {
        char gelesen[64] = {0};
        size_t n = std::fread(gelesen, 1, sizeof(gelesen) - 1, f);
        std::fclose(f);
        gelesen[n] = '\0';
        // Alles ab dem ersten Zeichen, das nicht in eine Kennung gehört, fällt weg -- so
        // übersteht die Datei einen Zeilenumbruch, den ein Editor hinterlässt.
        for (char* p = gelesen; *p; ++p) {
            if (!std::isalnum((unsigned char)*p)) { *p = '\0'; break; }
        }
        if (std::strlen(gelesen) >= 8) {
            std::snprintf(g_kennung, sizeof(g_kennung), "%s", gelesen);
            logzeile("Kennung gelesen");
            return;
        }
    }

    kennung_erzeugen();
    f = std::fopen(pfad, "wb");
    if (f) {
        std::fwrite(g_kennung, 1, std::strlen(g_kennung), f);
        std::fclose(f);
        logzeile("Kennung neu angelegt");
    } else {
        // Kein Fehlerfall: Die Brügge zieht dann bei jedem Start eine neue, und der Server
        // matcht einmal je Sitzung voll statt einmal je Installation. Bei einer Flugstunde im
        // Sekundentakt ist das ein voller Match statt 3600.
        logzeile("Kennung liess sich nicht speichern -- sie gilt nur fuer diese Sitzung");
    }
}

// ---------------------------------------------------------------------------------------
// Gattung -> .obj-Pfad
// ---------------------------------------------------------------------------------------
//
// DIE ZUORDNUNGSTABELLE GEHÖRT ZUR BRÜGGE, nicht zum Server (PROTOKOLL.md, Abschnitt 3). Der
// Server spricht in Gattungen; welches Modell das ist, weiß nur, wer den Simulator kennt.
//
// Eine Gattung ist eine BEDEUTUNG, kein Modell: In MSFS ist ein `tier_gross` ein Bär, hier
// ein Hirsch. Der Pilot zählt Tiere, nicht Bären -- und ein Event, das auf einer bestimmten
// Art besteht, braucht eine eigene Gattung (wie `robbe`).
//
// ALLE PFADE SIND AUF DER PLATTE NACHGESEHEN, nicht aus einer Doku übernommen. Genau daran
// hing der X-Plane-Probeflug: Der oft zitierte Pfad zu `SailBoat.obj` stammte aus einer
// XPPython3-Doku und nicht von Laminar -- er hielt, aber das war Glück (probe-xplane/
// ERGEBNIS.md). Vier Kandidaten waren vorbereitet, weil der erste hätte falsch sein können.
//
// ⚠ WAS HIER NICHT STEHT, KANN DIE BRÜGGE NICHT -- und meldet es auch nicht in `kann`:
//
//   fahrzeug     X-Plane 12 bringt KEIN Bodenfahrzeug als eigenständige .obj mit. Was der
//                Simulator an Flughafenverkehr zeichnet, liegt in der Szenerie-Bibliothek
//                (`lib/airport/vehicles/...`) und ist nur über XPLMLookupObjects erreichbar,
//                nicht über XPLMLoadObject. Das ist ein gangbarer Weg für später -- aber
//                einer, der eigene Messungen braucht, und geraten wird hier nichts.
//   robbe        kein Modell im Bordbestand, und kein Addon-Gegenstück zu
//   tier_vieh     `human-library-animated` gemessen.
//   tier_wasser
//   rauch        X-Plane zeichnet Rauch über Partikelsysteme, nicht über Objekte.
//   feuer
//   kegel        keine Pylone im Bordbestand.
//
// Die dicken Pötte (BulkCarrier, ContainerCarrier, OilTanker, LNGCarrier) liegen NUR als
// `.agp` vor -- das ist ein Autogen-Punkt für den Szeneriebau, keine ladbare .obj. Deshalb
// ist `boot_gross` hier die Fregatte `Perry.obj` (rund 135 m) und nicht ein Containerschiff.
struct Gattung { const char* art; const char* pfad[5]; };

static const char* const P = "Resources/default scenery/sim objects/";

// Die Pfade stehen relativ zum X-System-Ordner, so will es XPLMLoadObject. Der gemeinsame
// Anfang wird beim Laden davorgesetzt (s. `objekt_holen`) -- das hält die Tabelle lesbar.
static const Gattung g_gattungen[] = {
    // Hirsch und Ricke. Die einzigen Landtiere im Bordbestand -- und der Sache näher als
    // alles, was Asobo für MSFS 2024 mitbringt (dort gibt es 41 Tier-Pakete, aber keine
    // Robbe; hier immerhin Wild und Möwen).
    { "tier_gross",  { "dynamic/deer_buck.obj", "dynamic/deer_doe.obj", nullptr } },
    { "tier_wild",   { "dynamic/deer_buck.obj", "dynamic/deer_doe.obj", nullptr } },
    // Möwen in drei Flugzuständen. `glide` steht ruhig, `flap` schlägt mit den Flügeln --
    // für eine Zählaufgabe aus der Luft ist der Gleitflug die ruhigere Marke.
    { "tier_klein",  { "dynamic/seagull_glide.obj", "dynamic/seagull_flap.obj",
                       "dynamic/seagull_far.obj", nullptr } },
    // Die Ölplattform ist 63 MB gross und entsprechend weit zu sehen -- für die Nordsee das
    // passendste Bauwerk, das der Simulator mitbringt. Dahinter Kleineres.
    { "bauwerk",     { "dynamic/OilPlatform.obj", "dynamic/OilRig.obj",
                       "legacy env files/radio_tower.obj", nullptr } },
    // Segelboote, Motorboote, Schlauchboote. `SailBoat.obj` ist das im Probeflug am
    // 11.09.2026 gesetzte und im Bild gesehene Modell -- es steht deshalb vorn.
    { "boot_klein",  { "dynamic/SailBoat.obj", "ships/Sail_1000_01.obj",
                       "ships/Runabout_750_01.obj", "ships/Dinghy_400_01.obj", nullptr } },
    // Fregatte (~135 m) und die grösste ladbare Yacht (19 m).
    { "boot_gross",  { "dynamic/Perry.obj", "ships/Cruiser_1900_01.obj",
                       "ships/Cruiser_1200_01.obj", nullptr } },
    // ⭐ Der Heissluftballon löst dasselbe Problem wie `rauch` in MSFS: Ein Boot ist erst ab
    // rund 1 km eingeblendet -- ein Ballon steht in der Luft und ist kilometerweit zu sehen.
    // Für jedes Event, bei dem jemand etwas FINDEN soll, ist das wertvoller als das genauere
    // Modell am Boden.
    { "marke",       { "dynamic/balloon1.obj", "dynamic/balloon2.obj",
                       "dynamic/balloon3.obj", "landscape/windsock_orange.obj", nullptr } },
    // Eine Boje markiert einen Punkt auf dem Wasser -- das Gegenstück zu den flachen
    // Landepunkten aus der SayIntentions-Bibliothek in MSFS.
    { "punkt",       { "landscape/buoy.obj", "landscape/radar.obj", nullptr } },
};

static const char* pfad_fuer(const char* art, int n) {
    for (unsigned g = 0; g < sizeof(g_gattungen)/sizeof(g_gattungen[0]); ++g) {
        if (std::strcmp(art, g_gattungen[g].art) != 0) continue;
        if (n < 0 || n >= 5) return nullptr;
        return g_gattungen[g].pfad[n];
    }
    return nullptr;   // unbekannte Gattung: nicht raten, sondern melden
}

static bool gattung_bekannt(const char* art) {
    for (unsigned g = 0; g < sizeof(g_gattungen)/sizeof(g_gattungen[0]); ++g) {
        if (std::strcmp(art, g_gattungen[g].art) == 0) return true;
    }
    return false;
}

// ---------------------------------------------------------------------------------------
// Die geladenen Modelle
// ---------------------------------------------------------------------------------------
//
// Ein `XPLMObjectRef` trägt beliebig viele Instanzen -- dreissig Möwen brauchen EIN geladenes
// Modell. Deshalb ein kleiner Bestand statt eines Ladevorgangs je Objekt.
//
// GELADEN WIRD ASYNCHRON. `XPLMLoadObject` blockiert, bis die Datei gelesen ist, und die
// Ölplattform ist 63 MB gross -- das wäre ein sichtbarer Ruckler mitten im Flug. Der
// Rückruf kommt im Hauptthread, also darf er den Bestand ohne Absicherung anfassen.
struct GeladenesObjekt {
    char pfad[200];
    XPLMObjectRef ref;
    bool laedt;
    bool fehlt;        // X-Plane hat null zurückgegeben: Datei nicht da oder nicht lesbar
};

static GeladenesObjekt g_objekte[OBJEKTE_MAX];

static void objekt_da(XPLMObjectRef ref, void* merker) {
    int i = (int)(intptr_t)merker;
    if (i < 0 || i >= OBJEKTE_MAX) return;
    g_objekte[i].laedt = false;
    if (ref) {
        g_objekte[i].ref = ref;
    } else {
        g_objekte[i].fehlt = true;
        char z[300];
        std::snprintf(z, sizeof(z), "Modell nicht ladbar: %s", g_objekte[i].pfad);
        logzeile(z);
    }
}

// Den Platz eines Modells -- vorhandenen oder neu angelegten. -1, wenn der Bestand voll ist.
static int objekt_holen(const char* kurz) {
    char voll[200];
    std::snprintf(voll, sizeof(voll), "%s%s", P, kurz);

    int frei = -1;
    for (int i = 0; i < OBJEKTE_MAX; ++i) {
        if (g_objekte[i].pfad[0]) {
            if (std::strcmp(g_objekte[i].pfad, voll) == 0) return i;
        } else if (frei < 0) {
            frei = i;
        }
    }
    if (frei < 0) return -1;

    std::snprintf(g_objekte[frei].pfad, sizeof(g_objekte[frei].pfad), "%s", voll);
    g_objekte[frei].ref = nullptr;
    g_objekte[frei].laedt = true;
    g_objekte[frei].fehlt = false;
    XPLMLoadObjectAsync(voll, objekt_da, (void*)(intptr_t)frei);
    return frei;
}

// ---------------------------------------------------------------------------------------
// Das Netz -- ein eigener Thread
// ---------------------------------------------------------------------------------------
//
// Die Flugschleife darf nicht warten. Ein HTTPS-Aufruf über das Internet dauert zwischen
// wenigen Millisekunden und (bei Zeitüberschreitung) fünfzehn Sekunden -- im Flugschleifen-
// Rückruf wäre das ein Standbild.
//
// Deshalb: Der Hauptthread legt die fertige Meldung ab und weckt den Netzthread; der sendet,
// legt die Antwort ab und schläft wieder. Zwischen beiden liegen zwei Puffer und eine
// CRITICAL_SECTION, sonst nichts.
//
// ⚠ KEIN XPLM-AUFRUF IM NETZTHREAD. Das SDK ist nicht threadsicher -- eine einzige
// XPLMDebugString-Zeile an der falschen Stelle reicht für einen Absturz, den niemand
// reproduziert. Der Netzthread sieht deshalb nur char-Puffer.

static HANDLE g_netz_thread = nullptr;
static HANDLE g_netz_wecker = nullptr;
static CRITICAL_SECTION g_schloss;
static volatile LONG g_netz_ende = 0;

static char  g_ausgang[MELDUNG_PUFFER];
static bool  g_ausgang_voll = false;
static char  g_eingang[ANTWORT_PUFFER];
static bool  g_eingang_voll = false;
static int   g_eingang_status = 0;
static unsigned long g_eingang_gross = 0;   // Antwort passte nicht in den Puffer
static bool  g_anfrage_laeuft = false;

static HINTERNET g_sitzung = nullptr;
static HINTERNET g_verbindung = nullptr;

static void netz_schliessen() {
    if (g_verbindung) { WinHttpCloseHandle(g_verbindung); g_verbindung = nullptr; }
    if (g_sitzung)    { WinHttpCloseHandle(g_sitzung);    g_sitzung = nullptr; }
}

// Sitzung und Verbindung werden EINMAL geöffnet und behalten -- so läuft die zweite Meldung
// über dieselbe TLS-Verbindung wie die erste. Bei Sekundentakt ist das der Unterschied
// zwischen einem Handshake je Meldung und einem je Sitzung.
static bool netz_oeffnen() {
    if (g_verbindung) return true;
    netz_schliessen();

    g_sitzung = WinHttpOpen(L"FriesenBruegge/" L"" BRUEGGE_VERSION,
                            WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,
                            WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!g_sitzung) return false;
    // Auflösen, Verbinden, Senden, Empfangen. Die 15 s beim Empfangen sind die Obergrenze,
    // an der die Brügge eine Meldung aufgibt -- der Wächter im Takt räumt sie danach weg.
    WinHttpSetTimeouts(g_sitzung, 10000, 10000, 15000, 15000);

    g_verbindung = WinHttpConnect(g_sitzung, BRUEGGE_HOST, INTERNET_DEFAULT_HTTPS_PORT, 0);
    if (!g_verbindung) { netz_schliessen(); return false; }
    return true;
}

static DWORD WINAPI netz_lauf(LPVOID) {
    static char sendepuffer[MELDUNG_PUFFER];
    static char lesepuffer[ANTWORT_PUFFER];

    while (true) {
        WaitForSingleObject(g_netz_wecker, INFINITE);
        if (InterlockedCompareExchange(&g_netz_ende, 0, 0)) break;

        bool etwas_da = false;
        EnterCriticalSection(&g_schloss);
        if (g_ausgang_voll) {
            std::memcpy(sendepuffer, g_ausgang, sizeof(sendepuffer));
            g_ausgang_voll = false;
            etwas_da = true;
        }
        LeaveCriticalSection(&g_schloss);
        if (!etwas_da) continue;

        int status = 0;
        unsigned long gelesen = 0;
        unsigned long zu_gross = 0;

        if (netz_oeffnen()) {
            HINTERNET anf = WinHttpOpenRequest(g_verbindung, L"POST", BRUEGGE_PFAD, nullptr,
                                               WINHTTP_NO_REFERER,
                                               WINHTTP_DEFAULT_ACCEPT_TYPES,
                                               WINHTTP_FLAG_SECURE);
            if (anf) {
                DWORD laenge = (DWORD)std::strlen(sendepuffer);
                BOOL ok = WinHttpSendRequest(anf, L"Content-Type: application/json\r\n",
                                             (DWORD)-1L, (LPVOID)sendepuffer, laenge,
                                             laenge, 0);
                if (ok) ok = WinHttpReceiveResponse(anf, nullptr);
                if (ok) {
                    DWORD code = 0, n = sizeof(code);
                    if (WinHttpQueryHeaders(anf,
                            WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                            WINHTTP_HEADER_NAME_BY_INDEX, &code, &n,
                            WINHTTP_NO_HEADER_INDEX)) {
                        status = (int)code;
                    }
                    // Den Rumpf in Stücken lesen, bis nichts mehr kommt.
                    DWORD da = 0;
                    while (WinHttpQueryDataAvailable(anf, &da) && da > 0) {
                        DWORD platz = (DWORD)(sizeof(lesepuffer) - 1 - gelesen);
                        if (platz == 0) {
                            // Die Antwort ist grösser als der Puffer. Sie wird GAR NICHT
                            // ausgewertet -- ein halb gelesener Sollzustand räumte alles ab,
                            // was hinter der Schnittstelle stand, und setzte es beim nächsten
                            // Takt neu. Das wäre ein Flackern, dessen Ursache niemand fände.
                            zu_gross = gelesen + da;
                            break;
                        }
                        DWORD nimm = (da < platz) ? da : platz;
                        DWORD tat = 0;
                        if (!WinHttpReadData(anf, lesepuffer + gelesen, nimm, &tat) || tat == 0)
                            break;
                        gelesen += tat;
                    }
                    lesepuffer[gelesen] = '\0';
                } else {
                    // Verbindung hin -- beim nächsten Mal neu aufbauen.
                    netz_schliessen();
                }
                WinHttpCloseHandle(anf);
            } else {
                netz_schliessen();
            }
        }

        EnterCriticalSection(&g_schloss);
        g_eingang_status = status;
        g_eingang_gross = zu_gross;
        if (zu_gross == 0 && gelesen > 0) {
            std::memcpy(g_eingang, lesepuffer, gelesen + 1);
        } else {
            g_eingang[0] = '\0';
        }
        g_eingang_voll = true;
        LeaveCriticalSection(&g_schloss);
    }

    netz_schliessen();
    return 0;
}

static void netz_senden(const char* text) {
    EnterCriticalSection(&g_schloss);
    std::snprintf(g_ausgang, sizeof(g_ausgang), "%s", text);
    g_ausgang_voll = true;
    LeaveCriticalSection(&g_schloss);
    SetEvent(g_netz_wecker);
}

// ---------------------------------------------------------------------------------------
// Die Lage lesen
// ---------------------------------------------------------------------------------------

static void lage_lesen() {
    if (!g_dr_lat || !g_dr_lon) { g_lage_gueltig = false; return; }
    g_lage.lat        = XPLMGetDatad(g_dr_lat);
    g_lage.lon        = XPLMGetDatad(g_dr_lon);
    g_lage.alt_msl_ft = XPLMGetDatad(g_dr_elev) * FT_JE_M;
    // `y_agl` gibt es in X-Plane direkt -- in MSFS braucht es dafür ein eigenes SimVar.
    g_lage.alt_agl_ft = g_dr_agl ? XPLMGetDataf(g_dr_agl) * FT_JE_M : 0.0;
    // `groundspeed` steht in m/s, gemeldet wird in Knoten.
    g_lage.gs_kt      = g_dr_gs ? XPLMGetDataf(g_dr_gs) * 1.943844 : 0.0;
    // `psi` ist der RECHTWEISENDE Kurs -- derselbe Bezug wie in MSFS und im VATSIM-Feed.
    g_lage.kurs       = g_dr_psi ? XPLMGetDataf(g_dr_psi) : 0.0;
    g_lage.vs_ft_min  = g_dr_vs ? XPLMGetDataf(g_dr_vs) : 0.0;
    g_lage.am_boden   = g_dr_boden ? (XPLMGetDatai(g_dr_boden) != 0) : false;
    g_lage_gueltig = true;
}

// ---------------------------------------------------------------------------------------
// Die Meldung bauen
// ---------------------------------------------------------------------------------------
//
// Zeichengleich mit ../msfs/bruegge.cpp, bis auf `hoehe_gemessen`. Das ist Absicht: Der
// Server darf an keiner Stelle wissen müssen, welcher Simulator gerade redet.

static void meldung_bauen(char* puffer, size_t groesse) {
    JsonSchreiber j(puffer, groesse);
    j.roh("{");
    j.feld("protokoll");       j.ganzzahl(1);            j.komma();
    j.feld("simulator");       j.text(SIMULATOR_NAME);   j.komma();
    j.feld("bruegge_version"); j.text(BRUEGGE_VERSION);  j.komma();
    if (g_antwort_zu_gross > 0) {
        j.feld("antwort_zu_gross"); j.ganzzahl((long)g_antwort_zu_gross); j.komma();
    }
    j.feld("kennung");         j.text(g_kennung);        j.komma();

    // `kann` wird AUS der Gattungstabelle erzeugt, nicht danebengeschrieben. Im WASM-Modul
    // stand dieselbe Liste einmal zu viel, und beim Eintragen der Gattung `robbe` meldete es
    // prompt, es könne eine Gattung nicht, die es setzen konnte.
    j.feld("kann");
    j.roh("[");
    for (unsigned g = 0; g < sizeof(g_gattungen)/sizeof(g_gattungen[0]); ++g) {
        if (g) j.komma();
        j.text(g_gattungen[g].art);
    }
    j.roh("]");
    j.komma();

    j.feld("lage");
    j.roh("{");
    j.feld("lat");        j.zahl(g_lage.lat, 6);         j.komma();
    j.feld("lon");        j.zahl(g_lage.lon, 6);         j.komma();
    j.feld("alt_msl_ft"); j.zahl(g_lage.alt_msl_ft, 1);  j.komma();
    j.feld("alt_agl_ft"); j.zahl(g_lage.alt_agl_ft, 1);  j.komma();
    j.feld("gs_kt");      j.zahl(g_lage.gs_kt, 1);       j.komma();
    j.feld("kurs");       j.zahl(g_lage.kurs, 1);        j.komma();
    j.feld("vs_ft_min");  j.zahl(g_lage.vs_ft_min, 0);   j.komma();
    j.feld("am_boden");   j.roh(g_lage.am_boden ? "true" : "false");
    j.roh("}");
    j.komma();

    j.feld("spur");
    j.roh("[");
    for (int i = 0; i < g_spur_anzahl; ++i) {
        if (i) j.komma();
        j.roh("{");
        j.feld("alter_s");    j.zahl(g_spur[i].alter_s, 1);    j.komma();
        j.feld("lat");        j.zahl(g_spur[i].lat, 6);        j.komma();
        j.feld("lon");        j.zahl(g_spur[i].lon, 6);        j.komma();
        j.feld("alt_msl_ft"); j.zahl(g_spur[i].alt_msl_ft, 1); j.komma();
        j.feld("gs_kt");      j.zahl(g_spur[i].gs_kt, 1);      j.komma();
        j.feld("kurs");       j.zahl(g_spur[i].kurs, 1);
        j.roh("}");
    }
    j.roh("]");
    j.komma();

    // `steht` meldet, wie es JEDEM Objekt aus `soll` ergangen ist -- auch den gescheiterten.
    //
    // ⚠ EIN ZUSTAND FEHLT HIER, UND ZWAR MIT GRUND: `verschwunden` gibt es in X-Plane nicht.
    // Eine Instanz gehört dem Plugin und bleibt, bis das Plugin sie zerstört -- in MSFS
    // stirbt ein AI-Objekt mit der SimConnect-Verbindung, und zweimal verschwand dort
    // derselbe Aufruf unterschiedlich (einmal nach einer Sekunde spurlos, einmal 600 s
    // stabil). Die Brügge behauptet hier also nicht, etwas zu überwachen, was sie nicht
    // überwachen kann.
    j.feld("steht");
    j.roh("[");
    bool erstes = true;
    for (int i = 0; i < SOLL_MAX; ++i) {
        if (!g_soll[i].belegt) continue;
        if (!erstes) j.komma();
        erstes = false;
        j.roh("{");
        j.feld("id"); j.text(g_soll[i].id); j.komma();
        if (g_soll[i].fehler[0]) {
            j.feld("zustand"); j.text("fehlgeschlagen"); j.komma();
            j.feld("fehler");  j.text(g_soll[i].fehler);
        } else if (!g_soll[i].instanz) {
            j.feld("zustand"); j.text("fehlgeschlagen"); j.komma();
            j.feld("fehler");  j.text("NOCH_NICHT_GESETZT");
        } else {
            j.feld("zustand");  j.text("steht"); j.komma();
            j.feld("hoehe_ft"); j.zahl(g_soll[i].hoehe_ft, 1); j.komma();
            // ⚠ NEU GEGENÜBER FASSUNG 1 DES PROTOKOLLS, und der Server darf es ignorieren.
            //
            // `hoehe_ft` ist hier nicht immer eine MESSUNG: Steht das Ziel ausserhalb des
            // geladenen Geländes, trifft die Terrain-Probe nicht, und das Objekt bekommt
            // Meereshöhe. Das sieht in der Meldung genauso aus wie ein Wattobjekt auf 0 ft --
            // und der Server soll nach Protokoll gerade daraus schliessen dürfen, ob eine
            // Stelle taugt. Ohne dieses Feld wäre das ein stiller Fehlschluss.
            //
            // Die Brügge rückt das Objekt nach, sobald die Probe trifft (s. objekt_setzen);
            // solange steht hier `false`.
            j.feld("hoehe_gemessen");
            j.roh(g_soll[i].hoehe_gemessen ? "true" : "false"); j.komma();
            j.feld("seit_s");   j.ganzzahl((long)(g_sekunden - g_soll[i].seit_s));
        }
        j.roh("}");
    }
    j.roh("]");
    j.roh("}");
}

// ---------------------------------------------------------------------------------------
// Objekte setzen, versetzen, wegnehmen
// ---------------------------------------------------------------------------------------

// Die Lage eines Objekts in lokalen Metern -- und die Höhe, auf der es dabei landet.
//
// DREI FÄLLE, in dieser Reihenfolge:
//   1. Der Server gibt eine Höhe vor  -> sie gilt, und die Probe bleibt aussen vor.
//   2. Die Terrain-Probe trifft       -> das Objekt sitzt auf dem Gelände am ZIELORT.
//   3. Die Probe trifft nicht         -> Meereshöhe, und `gemessen` bleibt false.
//
// Fall 3 ist kein Fehler, sondern der Normalfall für ein Objekt, das gesetzt wird, bevor der
// Pilot in seine Nähe kommt: X-Plane hält nur einen Umkreis des Geländes geladen. Die Brügge
// versucht es jede Sekunde erneut und rückt nach, sobald es geladen ist.
static void lage_rechnen(const SollObjekt& o, double* x, double* y, double* z,
                         double* hoehe_ft, bool* gemessen) {
    if (o.hat_hoehe) {
        XPLMWorldToLocal(o.lat, o.lon, o.erwartete_hoehe_ft / FT_JE_M, x, y, z);
        *hoehe_ft = o.erwartete_hoehe_ft;
        *gemessen = true;      // vom Server vorgegeben -- nichts zu messen
        return;
    }

    XPLMWorldToLocal(o.lat, o.lon, 0.0, x, y, z);
    *hoehe_ft = 0.0;
    *gemessen = false;

    if (!g_probe) return;
    XPLMProbeInfo_t treffer{};
    treffer.structSize = sizeof(treffer);
    if (XPLMProbeTerrainXYZ(g_probe, (float)*x, (float)*y, (float)*z, &treffer)
            != xplm_ProbeHitTerrain) {
        return;
    }
    *y = treffer.locationY;
    // Zurück in Weltkoordinaten, um die erreichte Höhe MELDEN zu können. Der Server hat kein
    // Geländemodell -- die Rückmeldung ist sein einziger Weg zu erfahren, worauf ein Objekt
    // steht (PROTOKOLL.md, Abschnitt 4).
    double r_lat, r_lon, r_alt;
    XPLMLocalToWorld(*x, *y, *z, &r_lat, &r_lon, &r_alt);
    *hoehe_ft = r_alt * FT_JE_M;
    *gemessen = true;
}

static void objekt_setzen(int i) {
    SollObjekt& o = g_soll[i];

    const char* kurz = pfad_fuer(o.art, o.titel_nr);
    if (!kurz) {
        std::snprintf(o.fehler, sizeof(o.fehler), "%s",
                      gattung_bekannt(o.art) ? "KEIN_MODELL_MEHR" : "GATTUNG_UNBEKANNT");
        return;
    }

    int oi = objekt_holen(kurz);
    if (oi < 0) { std::snprintf(o.fehler, sizeof(o.fehler), "MODELLBESTAND_VOLL"); return; }
    if (g_objekte[oi].laedt) return;          // noch am Laden -- der nächste Takt sieht nach
    if (g_objekte[oi].fehlt) {
        // Der nächste Kandidat der Gattung rückt nach. Genau dafür ist die Liste da: Am
        // 12.09.2026 fiel in MSFS die ganze Gattung `fahrzeug` aus, weil ein einziger Titel
        // im 2024er Bestand fehlte.
        ++o.titel_nr;
        return;
    }

    double x, y, z, hoehe;
    bool gemessen;
    lage_rechnen(o, &x, &y, &z, &hoehe, &gemessen);

    o.instanz = XPLMCreateInstance(g_objekte[oi].ref, nullptr);
    if (!o.instanz) {
        std::snprintf(o.fehler, sizeof(o.fehler), "KEINE_INSTANZ");
        return;
    }

    XPLMDrawInfo_t lage{};
    lage.structSize = sizeof(lage);
    lage.x = (float)x;  lage.y = (float)y;  lage.z = (float)z;
    lage.pitch = 0.0f;  lage.heading = (float)o.kurs;  lage.roll = 0.0f;
    XPLMInstanceSetPosition(o.instanz, &lage, nullptr);

    o.hoehe_ft = hoehe;
    o.hoehe_gemessen = gemessen;
    o.seit_s = g_sekunden;
}

// Die Lage aller stehenden Objekte nachführen -- jede Sekunde, aus Weltkoordinaten.
//
// ⚠ WARUM NICHT `XPLMInstanceSetAutoShift`, das im Probeflug nachweislich arbeitete:
//
// X-Plane zeichnet in lokalen Metern, und dieses System verschiebt sich, wenn der Flieger weit
// genug fliegt. AutoShift lässt X-Plane die Instanz dabei mitführen. Nachgeführt werden muss
// hier aber ohnehin -- wegen der Terrain-Probe, die erst trifft, wenn das Zielgelände geladen
// ist. Und wer aus Weltkoordinaten frisch rechnet, hat den Shift damit schon erledigt.
//
// Beides gleichzeitig wäre kein Gewinn, sondern zwei Stellen, an denen dieselbe Position
// entsteht -- und bei Widerspruch zuckte das Objekt eine Sekunde lang zwischen ihnen.
static void objekte_nachfuehren() {
    for (int i = 0; i < SOLL_MAX; ++i) {
        SollObjekt& o = g_soll[i];
        if (!o.belegt || !o.instanz) continue;

        double x, y, z, hoehe;
        bool gemessen;
        lage_rechnen(o, &x, &y, &z, &hoehe, &gemessen);

        XPLMDrawInfo_t lage{};
        lage.structSize = sizeof(lage);
        lage.x = (float)x;  lage.y = (float)y;  lage.z = (float)z;
        lage.pitch = 0.0f;  lage.heading = (float)o.kurs;  lage.roll = 0.0f;
        XPLMInstanceSetPosition(o.instanz, &lage, nullptr);

        // Die Höhe erst dann als gemessen führen, wenn die Probe wirklich getroffen hat --
        // ein einmal getroffener Wert wird nicht wieder zurückgenommen, denn Gelände ändert
        // sich nicht.
        if (gemessen) {
            o.hoehe_ft = hoehe;
            o.hoehe_gemessen = true;
        }
    }
}

static void objekt_wegnehmen(int i) {
    SollObjekt& o = g_soll[i];
    if (o.instanz) XPLMDestroyInstance(o.instanz);
    std::memset(&o, 0, sizeof(o));
}

static void alles_abraeumen() {
    for (int i = 0; i < SOLL_MAX; ++i) {
        if (g_soll[i].belegt) objekt_wegnehmen(i);
    }
}

static int soll_platz(const char* id) {
    int frei = -1;
    for (int i = 0; i < SOLL_MAX; ++i) {
        if (g_soll[i].belegt && std::strcmp(g_soll[i].id, id) == 0) return i;
        if (!g_soll[i].belegt && frei < 0) frei = i;
    }
    return frei;
}

// ---------------------------------------------------------------------------------------
// Der Sollzustand-Abgleich
// ---------------------------------------------------------------------------------------
//
// `soll` ist die VOLLSTÄNDIGE Liste dessen, was jetzt dastehen soll -- kein Strom von
// Befehlen. Geht eine Anfrage verloren oder hängt das Netz kurz, holt die nächste Antwort den
// Zustand von allein wieder ein; bei Befehlen bliebe eine verpasste Löschung für immer stehen.

static void soll_abgleichen(const char* json) {
    for (int i = 0; i < SOLL_MAX; ++i) g_soll[i].in_soll = false;

    const char* e = json_array(json, "soll");
    while (e) {
        char id[40];
        if (!json_text_in(e, "id", id, sizeof(id)) || id[0] == '\0') {
            e = json_naechstes(e); continue;
        }
        int i = soll_platz(id);
        if (i < 0) { e = json_naechstes(e); continue; }   // voll -- der Server sieht es
                                                          // daran, dass das Objekt in `steht`
                                                          // fehlt
        SollObjekt& o = g_soll[i];
        bool neu = !o.belegt;
        if (neu) {
            std::memset(&o, 0, sizeof(o));
            std::snprintf(o.id, sizeof(o.id), "%s", id);
            o.belegt = true;
            o.seit_s = g_sekunden;
        }

        char n_art[24] = {0};
        json_text_in(e, "art", n_art, sizeof(n_art));
        double n_lat  = json_zahl_in(e, "lat", o.lat);
        double n_lon  = json_zahl_in(e, "lon", o.lon);
        double n_kurs = json_zahl_in(e, "kurs", 0.0);
        bool   hat = false;
        double n_hoehe = json_zahl_in(e, "erwartete_hoehe_ft", 0.0, &hat);
        bool   n_auf_boden = (json_zahl_in(e, "auf_boden", 0.0) > 0.5);

        // GATTUNGSWECHSEL ist der einzige Grund, ein stehendes Objekt neu zu erzeugen: Er
        // heisst ein anderes Modell. Ort und Ausrichtung übernimmt `objekte_nachfuehren`
        // von selbst -- in MSFS muss ein Objekt dafür weg und neu hin, weil
        // `AICreateSimulatedObject` es anlegt und es danach steht.
        bool modellwechsel = o.instanz && n_art[0] && std::strcmp(o.art, n_art) != 0;

        std::snprintf(o.art, sizeof(o.art), "%s", n_art);
        o.lat = n_lat;
        o.lon = n_lon;
        o.kurs = n_kurs;
        o.hat_hoehe = hat;
        o.erwartete_hoehe_ft = n_hoehe;
        o.auf_boden = n_auf_boden;
        o.in_soll = true;

        if (modellwechsel) {
            XPLMDestroyInstance(o.instanz);
            o.instanz = nullptr;
            o.titel_nr = 0;
            o.fehler[0] = '\0';
            o.hoehe_gemessen = false;
            o.seit_s = g_sekunden;
        }

        e = json_naechstes(e);
    }

    for (int i = 0; i < SOLL_MAX; ++i) {
        SollObjekt& o = g_soll[i];
        if (!o.belegt) continue;
        if (!o.in_soll) { objekt_wegnehmen(i); continue; }
        if (o.fehler[0]) continue;     // abgelehnt -- NICHT jede Sekunde erneut versuchen.
                                       // Der Server entscheidet, wann es wieder losgeht: Er
                                       // nimmt die id aus `soll` und schickt sie neu.
        if (!o.instanz) objekt_setzen(i);
    }
}

// ---------------------------------------------------------------------------------------
// Die Antwort lesen
// ---------------------------------------------------------------------------------------

static void antwort_lesen(const char* json) {
    // Der Server bestimmt den Takt, nicht die Brügge. Er darf ihn je Meldung und je Pilot
    // verschieden setzen -- und über die Admin-Drossel für alle auf einmal ändern, ohne
    // Deploy und ohne dass ein Pilot etwas tun muss.
    double takt = json_zahl(json, "naechste_frage_in_s", (double)g_takt_s);
    if (takt < 1.0) takt = 1.0;
    if (takt > 900.0) takt = 900.0;
    g_takt_s = (int)takt;

    double gilt = json_zahl(json, "gilt_bis_s", (double)g_gilt_bis_s);
    if (gilt < 0.0) gilt = 0.0;
    g_gilt_bis_s = (unsigned)gilt;
    g_letzte_antwort_s = g_sekunden;

    soll_abgleichen(json);
}

// Was der Netzthread abgelegt hat, im Hauptthread auswerten.
static void antwort_abholen() {
    static char kopie[ANTWORT_PUFFER];
    int status = 0;
    unsigned long zu_gross = 0;
    bool etwas_da = false;

    EnterCriticalSection(&g_schloss);
    if (g_eingang_voll) {
        std::snprintf(kopie, sizeof(kopie), "%s", g_eingang);
        status = g_eingang_status;
        zu_gross = g_eingang_gross;
        g_eingang_voll = false;
        etwas_da = true;
    }
    LeaveCriticalSection(&g_schloss);
    if (!etwas_da) return;

    g_anfrage_laeuft = false;

    if (status == 426) {
        // Protokollfassung zu alt: aufräumen und anhalten. Weiterzureden hiesse, in einem
        // Vertrag zu reden, den auf der anderen Seite niemand mehr liest.
        logzeile("Server: Protokollfassung zu alt (426) -- die Bruegge haelt an.");
        alles_abraeumen();
        g_takt_s = 900;
        return;
    }
    if (status == 429) {
        g_takt_s = (g_takt_s * 2 > 60) ? 60 : g_takt_s * 2;
        return;
    }
    if (zu_gross > 0) {
        // Geht mit der nächsten Meldung hinaus, damit der Server ERFÄHRT, warum Objekte
        // fehlen, statt es zu raten -- und die Zahl sagt ihm, wie weit er kürzen muss.
        g_antwort_zu_gross = zu_gross;
        return;
    }
    if (!(status >= 200 && status < 300)) return;
    if (!kopie[0]) return;

    g_antwort_zu_gross = 0;
    antwort_lesen(kopie);
}

static void melden() {
    if (g_anfrage_laeuft) return;          // eine Anfrage reicht; die nächste wartet
    static char puffer[MELDUNG_PUFFER];
    meldung_bauen(puffer, sizeof(puffer));
    netz_senden(puffer);
    g_anfrage_laeuft = true;
    g_spur_anzahl = 0;                     // was mitging, ist mitgegangen
}

// ---------------------------------------------------------------------------------------
// Der Takt
// ---------------------------------------------------------------------------------------

static float takt(float, float, int, void*) {
    ++g_sekunden;
    antwort_abholen();
    lage_lesen();
    objekte_nachfuehren();

    if (!g_lage_gueltig) return 1.0f;

    // Ein SPRUNG ist kein Flug. Nach dem Start liefert ein Simulator erst Unsinn, dann seinen
    // Standard-Startpunkt, dann den geladenen Flug -- und jeder dieser Werte sieht für sich
    // vernünftig aus. Eine Liste bekannter Fehlorte deckt immer nur die ab, die schon
    // aufgefallen sind; der Sprung verrät den Ladevorgang, ohne dass man einen einzigen Ort
    // kennen muss. Dasselbe gilt nach jedem Flugwechsel -- und der kommt im Alltag häufiger
    // vor als ein Simulatorstart.
    if (g_vor_gueltig) {
        double dlat = g_lage.lat - g_vor_lat;
        double dlon = g_lage.lon - g_vor_lon;
        if (dlat > SPRUNG_GRAD || dlat < -SPRUNG_GRAD ||
            dlon > SPRUNG_GRAD || dlon < -SPRUNG_GRAD) {
            g_spur_anzahl = 0;
            g_vor_lat = g_lage.lat;
            g_vor_lon = g_lage.lon;
            g_seit_meldung = 0;
            return 1.0f;                   // dieser Punkt geht NICHT hinauf
        }
    }
    g_vor_lat = g_lage.lat;
    g_vor_lon = g_lage.lon;
    g_vor_gueltig = true;

    if (g_spur_anzahl < SPUR_MAX) {
        SpurPunkt& s = g_spur[g_spur_anzahl++];
        s.alter_s = 0.0;
        s.lat = g_lage.lat;
        s.lon = g_lage.lon;
        s.alt_msl_ft = g_lage.alt_msl_ft;
        s.gs_kt = g_lage.gs_kt;
        s.kurs = g_lage.kurs;
    }
    for (int i = 0; i < g_spur_anzahl; ++i) g_spur[i].alter_s += 1.0;

    // Kommt länger keine Antwort, fällt der Sollzustand. Ohne das bliebe bei einem Netzausfall
    // stehen, was der Server längst zurückgenommen hat -- für eine Baake hiesse das eine
    // Station, die nie verschwindet.
    if (g_gilt_bis_s > 0 && g_letzte_antwort_s > 0 &&
        g_sekunden > g_letzte_antwort_s + g_gilt_bis_s) {
        alles_abraeumen();
        g_letzte_antwort_s = 0;            // nur EINMAL abräumen, nicht jede Sekunde erneut
    }

    if (++g_seit_meldung >= (unsigned)g_takt_s) {
        g_seit_meldung = 0;
        melden();
    }
    return 1.0f;
}

// ---------------------------------------------------------------------------------------
// Das Plugin
// ---------------------------------------------------------------------------------------

PLUGIN_API int XPluginStart(char* name, char* sig, char* beschreibung) {
    std::strcpy(name, "Die FriesenBruegge");
    std::strcpy(sig, "de.friesenflieger.bruegge");
    std::strcpy(beschreibung,
                "Meldet die Position an FriesenSpy und setzt, was der Server anfordert.");

    InitializeCriticalSection(&g_schloss);
    g_netz_wecker = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    g_netz_thread = CreateThread(nullptr, 0, netz_lauf, nullptr, 0, nullptr);

    kennung_laden_oder_erzeugen();

    g_dr_lat   = XPLMFindDataRef("sim/flightmodel/position/latitude");
    g_dr_lon   = XPLMFindDataRef("sim/flightmodel/position/longitude");
    g_dr_elev  = XPLMFindDataRef("sim/flightmodel/position/elevation");
    g_dr_agl   = XPLMFindDataRef("sim/flightmodel/position/y_agl");
    g_dr_gs    = XPLMFindDataRef("sim/flightmodel/position/groundspeed");
    g_dr_psi   = XPLMFindDataRef("sim/flightmodel/position/psi");
    g_dr_vs    = XPLMFindDataRef("sim/flightmodel/position/vh_ind_fpm");
    g_dr_boden = XPLMFindDataRef("sim/flightmodel/failures/onground_any");
    if (!g_dr_lat || !g_dr_lon || !g_dr_elev) {
        // Ohne Position gibt es nichts zu melden. Die Zeile im Log ist der einzige Weg, auf
        // dem das jemand erfährt -- ein Plugin, das nichts tut, sieht von aussen aus wie ein
        // Plugin, das nicht geladen wurde.
        logzeile("FEHLT: Positions-Datarefs nicht gefunden -- die Bruegge meldet nichts.");
    }

    g_probe = XPLMCreateProbe(xplm_ProbeY);
    XPLMRegisterFlightLoopCallback(takt, 1.0f, nullptr);
    logzeile("Fassung " BRUEGGE_VERSION " geladen.");
    return 1;
}

PLUGIN_API void XPluginStop(void) {
    XPLMUnregisterFlightLoopCallback(takt, nullptr);
    alles_abraeumen();
    for (int i = 0; i < OBJEKTE_MAX; ++i) {
        if (g_objekte[i].ref) XPLMUnloadObject(g_objekte[i].ref);
    }
    if (g_probe) XPLMDestroyProbe(g_probe);

    // Den Netzthread ordentlich beenden. Er hängt in WaitForSingleObject -- also erst das
    // Ende-Kennzeichen setzen, dann wecken, dann warten. Ohne das Warten stürbe der Prozess
    // mitten in einem WinHTTP-Aufruf.
    InterlockedExchange(&g_netz_ende, 1);
    if (g_netz_wecker) SetEvent(g_netz_wecker);
    if (g_netz_thread) {
        WaitForSingleObject(g_netz_thread, 20000);
        CloseHandle(g_netz_thread);
        g_netz_thread = nullptr;
    }
    if (g_netz_wecker) { CloseHandle(g_netz_wecker); g_netz_wecker = nullptr; }
    DeleteCriticalSection(&g_schloss);
    logzeile("entladen.");
}

PLUGIN_API int XPluginEnable(void) { return 1; }

PLUGIN_API void XPluginDisable(void) {
    // Abschalten heisst: nichts mehr stehen lassen. Ein Pilot, der das Plugin im
    // Plugin-Manager ausschaltet, will keine Objekte mehr sehen.
    alles_abraeumen();
}

PLUGIN_API void XPluginReceiveMessage(XPLMPluginID, int nachricht, void*) {
    // XPLM_MSG_AIRPORT_LOADED und XPLM_MSG_SCENERY_LOADED heissen beide: die Welt ist eine
    // andere geworden. Die Sprungerkennung fängt das ohnehin ab; hier wird nur die gemerkte
    // Vorposition verworfen, damit der erste Punkt danach nicht gegen einen Ort aus dem
    // vorigen Flug verglichen wird.
    if (nachricht == XPLM_MSG_AIRPORT_LOADED || nachricht == XPLM_MSG_SCENERY_LOADED) {
        g_vor_gueltig = false;
        g_spur_anzahl = 0;
    }
}
