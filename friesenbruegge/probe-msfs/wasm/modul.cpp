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

enum {
    EV_SEKUNDE = 1,
    DEF_LAGE   = 1,
    REQ_LAGE   = 1,
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
    // 200 m oestlich, wie im externen Probeflug -- schliesst EXCEPTION 33 aus.
    const double grad_lon = 200.0 / (111320.0 * 0.59);   // cos(53.8 Grad)

    SIMCONNECT_DATA_INITPOSITION pos{};
    pos.Latitude  = lage.lat;
    pos.Longitude = lage.lon + grad_lon;
    pos.Altitude  = 0.0;
    pos.Pitch     = 0.0;
    pos.Bank      = 0.0;
    pos.Heading   = 210.0;
    pos.OnGround  = 1;
    pos.Airspeed  = 0;

    // _EX1 statt der alten Fassung, mit zusaetzlichem Livery-Parameter.
    //
    // DAS war der Fehler (11.09.2026): Das Modul importierte
    // SimConnect_AICreateSimulatedObject ohne Suffix -- in WASM offenbar nicht vorhanden.
    // Ein unaufloesbarer Import laesst den Simulator das GANZE Modul verwerfen, lautlos:
    // kein module_init, keine Meldung, kein Objekt. Aufgefallen ist es erst am Vergleich
    // mit p42-util-gofish, einem produktiven Addon, das Objekte aus WASM setzt -- dessen
    // Modul importiert ausschliesslich die _EX1-Fassung.
    HRESULT hr = SimConnect_AICreateSimulatedObject_EX1(g_sim, "Boat01", "", pos, REQ_BOOT);
    melde("create_aufgerufen", (long)hr);
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
        if (evt->uEventID == EV_SEKUNDE && !g_versucht) {
            g_versucht = true;
            // FESTE Koordinate statt Lage-Abfrage.
            //
            // Der Umweg ueber RequestDataOnSimObject scheiterte mit EXCEPTION 3
            // (UNRECOGNIZED_ID, 11.09.2026) -- die Datendefinition kam nicht zustande, und
            // die Rueckgabewerte von AddToDataDefinition wurden nicht geprueft. Fuer die
            // eigentliche Frage ist die Abfrage aber gar nicht noetig: Ob ein WASM-Modul
            // ein Objekt SETZEN kann, zeigt ein fester Punkt genauso -- und zwar ohne eine
            // zweite Fehlerquelle dazwischen.
            Lage fest{ 53.78721, 7.90970, 0.0 };   // Wangerooge, Standort des Probeflugs
            boot_setzen(fest);
        }
        break;
    }

    case SIMCONNECT_RECV_ID_SIMOBJECT_DATA: {
        auto* d = (SIMCONNECT_RECV_SIMOBJECT_DATA*)pData;
        if (d->dwRequestID == REQ_LAGE) {
            Lage* lage = (Lage*)&d->dwData;
            melde("lage_lat_e5", (long)(lage->lat * 100000.0));
            melde("lage_lon_e5", (long)(lage->lon * 100000.0));
            boot_setzen(*lage);
        }
        break;
    }

    case SIMCONNECT_RECV_ID_ASSIGNED_OBJECT_ID: {
        auto* z = (SIMCONNECT_RECV_ASSIGNED_OBJECT_ID*)pData;
        // DAS ist die Antwort auf Frage 1.
        melde("ERFOLG_objekt_id", (long)z->dwObjectID);
        break;
    }

    case SIMCONNECT_RECV_ID_EXCEPTION: {
        auto* ex = (SIMCONNECT_RECV_EXCEPTION*)pData;
        melde("exception", (long)ex->dwException);
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

    // Drei Doubles -- identisch zum externen Probeflug.
    // Rueckgabewerte melden -- ohne sie blieb offen, warum die spaetere Abfrage mit
    // EXCEPTION 3 endete.
    HRESULT d1 = SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "PLANE LATITUDE", "degrees");
    HRESULT d2 = SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "PLANE LONGITUDE", "degrees");
    HRESULT d3 = SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "PLANE ALTITUDE", "feet");
    melde("datadef_hr", (long)(d1 | d2 | d3));

    // "1sec" feuert erst, wenn der Sim laeuft -- der Aufhaenger, um nicht im Hauptmenue
    // zu setzen.
    hr = SimConnect_SubscribeToSystemEvent(g_sim, EV_SEKUNDE, "1sec");
    melde("subscribe_hr", (long)hr);

    hr = SimConnect_CallDispatch(g_sim, dispatch, nullptr);
    melde("calldispatch_hr", (long)hr);
}

extern "C" MSFS_CALLBACK void module_deinit(void)
{
    melde("module_deinit", 0);
    if (g_sim) {
        SimConnect_Close(g_sim);
        g_sim = 0;
    }
}
