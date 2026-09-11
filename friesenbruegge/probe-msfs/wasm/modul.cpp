// Probeflug Teil 2: Kann ein WASM-Modul das, was das externe Programm kann?
//
// Zwei Fragen in einem Modul, weil beide denselben Bau brauchen:
//
//   1. Erreicht SimConnect_AICreateSimulatedObject ein WASM-Modul? (Spec 13.4, Frage 1)
//   2. Darf ein WASM-Modul ins Netz? (MSFS_Network.h sagt ja -- ungeprueft)
//
// Frage 2 ist zugleich der Rueckkanal: Das Modul meldet jeden Schritt per HTTP an einen
// kleinen Server auf diesem Rechner. Damit braucht es keinen Dev-Mode und keine
// Sim-Konsole, um zu erfahren, was passiert ist -- und wenn gar nichts ankommt, ist auch
// das ein Befund.
//
// Gebaut mit dem SDK-eigenen clang, s. bauen.ps1 daneben.

#include <MSFS/MSFS.h>
#include <MSFS/MSFS_WindowsTypes.h>
#include <MSFS/MSFS_Network.h>
#include <SimConnect.h>

#include <cstdio>
#include <cstring>

static HANDLE g_sim = 0;
static bool g_versucht = false;
static DWORD g_sekunden = 0;
static DWORD g_lagen = 0;

// ---------------------------------------------------------------------------
// Rueckkanal Nr. 3: ein gemeinsamer Speicherbereich (ClientData).
//
// Noetig geworden, weil die beiden anderen ausfallen koennen: fprintf landet in MSFS 2020
// NICHT in der Konsole (11.09.2026 gemessen -- das Modul laedt, initialisiert und meldet
// dann gar nichts), und fsNetworkHttpRequestGet erreichte kein 127.0.0.1. ClientData
// funktioniert unabhaengig von beidem und ist von einem externen Programm lesbar; SPAD.neXt
// macht es auf demselben Rechner genauso.
//
// Aufbau: 16 DWORDs. In [0] steht, wie weit das Modul gekommen ist, in [1] der letzte
// Fehlerwert, in [2] die Objekt-ID. Ab [3] die Messpunkte der Lage-Frage:
//   [3] HRESULT der drei AddToDataDefinition (ver-odert)
//   [4] HRESULT von RequestDataOnSimObject
//   [5] Zahl der empfangenen Lagemeldungen
//   [6] Breite * 100000, [7] Laenge * 100000  (als DWORD, also ohne Vorzeichen lesen)
//   [8] Zahl der vergangenen Sekunden
#define CD_NAME   "FriesenBruegge.Status"
#define CD_ID     1
#define CD_DEF    1
#define CD_WORTE  16

static DWORD g_status[CD_WORTE] = {0};
static bool  g_cd_bereit = false;

enum Schritt {
    S_START = 1, S_OPEN = 2, S_DATADEF = 3, S_SUBSCRIBE = 4, S_DISPATCH = 5,
    S_EVENT = 6, S_CREATE_GERUFEN = 7, S_OBJEKT_DA = 8, S_EXCEPTION = 9,
};

// Schreibt ein einzelnes Feld, ohne den Schritt zu veraendern.
static void feld(int nr, DWORD wert);

static void status(DWORD schritt, DWORD wert2 = 0, DWORD wert3 = 0)
{
    g_status[0] = schritt;
    if (wert2) g_status[1] = wert2;
    if (wert3) g_status[2] = wert3;
    if (g_cd_bereit) {
        SimConnect_SetClientData(g_sim, CD_ID, CD_DEF, 0, 0,
                                 sizeof(g_status), g_status);
    }
}

static void feld(int nr, DWORD wert)
{
    if (nr < 0 || nr >= CD_WORTE) return;
    g_status[nr] = wert;
    if (g_cd_bereit) {
        SimConnect_SetClientData(g_sim, CD_ID, CD_DEF, 0, 0,
                                 sizeof(g_status), g_status);
    }
}

enum {
    EV_SEKUNDE = 1,
    // ACHTUNG, hier lag vermutlich der EXCEPTION-3-Fehler vom 11.09.2026:
    // DEF_LAGE stand auf 1 -- derselbe Wert wie CD_DEF. SimConnect_AddToDataDefinition und
    // SimConnect_AddToClientDataDefinition nehmen BEIDE eine SIMCONNECT_DATA_DEFINITION_ID,
    // also denselben Nummernraum. ID 1 war als ClientData-Definition belegt; die spaetere
    // Benutzung als Datendefinition endete mit UNRECOGNIZED_ID. Der externe Probeflug hat
    // den Fehler nicht, weil er gar kein ClientData anlegt -- deshalb fiel es dort nie auf.
    DEF_LAGE   = 10,
    REQ_LAGE   = 20,
    REQ_BOOT   = 4711,
};

// Die Lage des Flugzeugs -- dieselben drei Werte wie im externen Probeflug.
struct Lage {
    double lat;
    double lon;
    double alt;
};

// ---------------------------------------------------------------------------
// Rueckkanal: eine GET-Anfrage an den Messrechner. Die Antwort interessiert nicht,
// die Zeile im Server-Log ist das Ergebnis.
static void melde(const char* was, long zahl)
{
    char url[512];
    std::snprintf(url, sizeof(url),
                  "http://127.0.0.1:8099/wasm?schritt=%s&wert=%ld", was, zahl);
    FsNetworkHttpRequestParam p{};
    p.postField = nullptr;
    p.headerOptions = nullptr;
    p.headerOptionsSize = 0;
    p.data = nullptr;
    p.dataSize = 0;
    fsNetworkHttpRequestGet(url, &p, nullptr, nullptr);
    // Zusaetzlich in die Sim-Konsole, falls der Dev-Mode doch an ist.
    std::fprintf(stderr, "[FriesenBruegge] %s = %ld\n", was, zahl);
}

// ---------------------------------------------------------------------------
static void boot_setzen(const Lage& lage)
{
    // VIER Varianten nebeneinander, je 120 m auseinander. Grund: Aus WASM heraus landete
    // ein Boot mit OnGround=1 und Altitude=0 auf 49,1 ft statt am Boden (11.09.2026,
    // extern gemessen an Objekt 16384) -- derselbe Aufruf setzt extern sauber auf (2,0 ft).
    // Die Koordinate stimmte dabei exakt, ein Feldversatz in der Struktur scheidet also aus.
    // Welcher der beiden Werte ignoriert oder umgedeutet wird, zeigt der Vergleich:
    //
    //   0: OnGround=1, Alt=0     wie bisher -- die Referenz
    //   1: OnGround=0, Alt=0     wird die Hoehe ueberhaupt beachtet?
    //   2: OnGround=0, Alt=500   kommt ein bekannter Wert unveraendert an?
    //   3: OnGround=1, Alt=500   was gewinnt, wenn beide gesetzt sind?
    //
    // Von aussen mit --boote-zaehlen abzulesen: die Laenge sagt, welche Variante es ist.
    struct Variante { unsigned long on_ground; double alt; };
    const Variante varianten[4] = {
        { 1, 0.0 },
        { 0, 0.0 },
        { 0, 500.0 },
        { 1, 500.0 },
    };

    const double grad_lon = 120.0 / (111320.0 * 0.59);   // cos(53.8 Grad)

    for (int i = 0; i < 4; ++i) {
        SIMCONNECT_DATA_INITPOSITION pos{};
        pos.Latitude  = lage.lat;
        pos.Longitude = lage.lon + grad_lon * (i + 1);
        pos.Altitude  = varianten[i].alt;
        pos.Pitch     = 0.0;
        pos.Bank      = 0.0;
        pos.Heading   = 210.0;
        pos.OnGround  = varianten[i].on_ground;
        pos.Airspeed  = 0;

        // DIE ALTE FASSUNG IST DER NORMALFALL -- sie bedient beide Simulatoren.
        //
        // MSFS 2020 kennt _EX1 nicht (fehlt in seinem SimConnect.h). Die Fassung ohne
        // Suffix steht dagegen in BEIDEN SDKs, und sie ist aus WASM erreichbar: am
        // 11.09.2026 in MSFS 2024 gemessen, vier Boote, Hoehen identisch zum _EX1-Lauf
        // (49,0 / 0,0 / 500,0 / 49,2 ft). Ein gemeinsames Modul ist damit baubar.
        //
        // Der Umweg ueber _EX1 entstand aus einem Fehlschluss: p42-util-gofish benutzt sie,
        // woraus geschlossen wurde, die andere gehe nicht. Mit -DNUTZE_EX1 laesst sie sich
        // weiterhin waehlen -- etwa wenn spaeter Liveries gebraucht werden, die nur _EX1 kann.
#ifdef NUTZE_EX1
        HRESULT hr = SimConnect_AICreateSimulatedObject_EX1(g_sim, "Boat01", "", pos,
                                                            REQ_BOOT + i);
#else
        HRESULT hr = SimConnect_AICreateSimulatedObject(g_sim, "Boat01", pos, REQ_BOOT + i);
#endif
        melde("create_aufgerufen", (long)hr);
        status(S_CREATE_GERUFEN, (DWORD)(hr & 0xFFFF));
    }
}

// ---------------------------------------------------------------------------
void CALLBACK dispatch(SIMCONNECT_RECV* pData, DWORD cbData, void* pContext)
{
    switch (pData->dwID) {
    case SIMCONNECT_RECV_ID_OPEN:
        melde("open_bestaetigt", 1);
        break;

    case SIMCONNECT_RECV_ID_EVENT: {
        // Einmalig, sobald der Sim laeuft: Lage anfordern. Im module_init ist noch kein
        // Flug geladen -- dieselbe Falle wie beim externen Probeflug, wo die Position
        // 0/90 zurueckkam.
        auto* evt = (SIMCONNECT_RECV_EVENT*)pData;
        if (evt->uEventID != EV_SEKUNDE) break;

        g_sekunden++;
        feld(8, g_sekunden);

        // Die Lage EINMAL anfordern, sobald der Sim laeuft. Im module_init ist noch kein
        // Flug geladen -- dieselbe Falle wie beim externen Probeflug, wo 0/90 zurueckkam.
        if (g_sekunden == 1) {
            status(S_EVENT);
            HRESULT r = SimConnect_RequestDataOnSimObject(
                g_sim, REQ_LAGE, DEF_LAGE, SIMCONNECT_OBJECT_ID_USER,
                SIMCONNECT_PERIOD_SECOND);
            melde("request_hr", (long)r);
            feld(4, (DWORD)r);
        }

        // Rueckfallebene: Kommt nach acht Sekunden keine Lagemeldung, wird trotzdem
        // gesetzt -- an einem festen Punkt. Sonst bliebe der Lauf ohne jedes Ergebnis,
        // und die zweite Frage (kann WASM ueberhaupt setzen?) waere mit erschlagen.
        if (g_sekunden == 8 && !g_versucht) {
            g_versucht = true;
            melde("rueckfall_feste_koordinate", 0);
            Lage fest{ 53.78721, 7.90970, 0.0 };   // Wangerooge, Standort des Probeflugs
            boot_setzen(fest);
        }
        break;
    }

    case SIMCONNECT_RECV_ID_SIMOBJECT_DATA: {
        auto* d = (SIMCONNECT_RECV_SIMOBJECT_DATA*)pData;
        if (d->dwRequestID == REQ_LAGE) {
            Lage* lage = (Lage*)&d->dwData;
            g_lagen++;
            feld(5, g_lagen);
            feld(6, (DWORD)(long)(lage->lat * 100000.0));
            feld(7, (DWORD)(long)(lage->lon * 100000.0));
            melde("lage_lat_e5", (long)(lage->lat * 100000.0));
            melde("lage_lon_e5", (long)(lage->lon * 100000.0));
            // Nur beim ERSTEN Mal setzen -- die Anfrage laeuft im Sekundentakt weiter,
            // damit sichtbar bleibt, ob die Meldungen anhalten.
            if (!g_versucht) {
                g_versucht = true;
                boot_setzen(*lage);
            }
        }
        break;
    }

    case SIMCONNECT_RECV_ID_ASSIGNED_OBJECT_ID: {
        auto* z = (SIMCONNECT_RECV_ASSIGNED_OBJECT_ID*)pData;
        // DAS ist die Antwort auf Frage 1.
        melde("ERFOLG_objekt_id", (long)z->dwObjectID);
        status(S_OBJEKT_DA, 0, z->dwObjectID);
        break;
    }

    case SIMCONNECT_RECV_ID_EXCEPTION: {
        auto* ex = (SIMCONNECT_RECV_EXCEPTION*)pData;
        melde("exception", (long)ex->dwException);
        status(S_EXCEPTION, ex->dwException);
        break;
    }

    default:
        break;
    }
}

// ---------------------------------------------------------------------------
extern "C" MSFS_CALLBACK void module_init(void)
{
    melde("module_init", 0);

    HRESULT hr = SimConnect_Open(&g_sim, "FriesenBruegge-WASM-Probe", nullptr, 0, 0, 0);
    melde("open_hr", (long)hr);
    if (hr != S_OK) {
        return;
    }

    // ClientData einrichten, sobald die Verbindung steht.
    SimConnect_MapClientDataNameToID(g_sim, CD_NAME, CD_ID);
    SimConnect_CreateClientData(g_sim, CD_ID, sizeof(g_status),
                                SIMCONNECT_CREATE_CLIENT_DATA_FLAG_DEFAULT);
    SimConnect_AddToClientDataDefinition(g_sim, CD_DEF, 0, sizeof(g_status));
    g_cd_bereit = true;
    status(S_OPEN);

    // Drei Doubles -- identisch zum externen Probeflug.
    // Rueckgabewerte melden -- ohne sie blieb offen, warum die spaetere Abfrage mit
    // EXCEPTION 3 endete.
    HRESULT d1 = SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "PLANE LATITUDE", "degrees");
    HRESULT d2 = SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "PLANE LONGITUDE", "degrees");
    HRESULT d3 = SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "PLANE ALTITUDE", "feet");
    melde("datadef_hr", (long)(d1 | d2 | d3));
    status(S_DATADEF);
    feld(3, (DWORD)(d1 | d2 | d3));

    // "1sec" feuert erst, wenn der Sim laeuft -- der Aufhaenger, um nicht im Hauptmenue
    // zu setzen.
    hr = SimConnect_SubscribeToSystemEvent(g_sim, EV_SEKUNDE, "1sec");
    melde("subscribe_hr", (long)hr);

    hr = SimConnect_CallDispatch(g_sim, dispatch, nullptr);
    melde("calldispatch_hr", (long)hr);
    status(S_DISPATCH);
}

extern "C" MSFS_CALLBACK void module_deinit(void)
{
    melde("module_deinit", 0);
    if (g_sim) {
        SimConnect_Close(g_sim);
        g_sim = 0;
    }
}
