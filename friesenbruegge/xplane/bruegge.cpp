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
// NETZ UND NEBENLÄUFIGKEIT LIEGEN IN `netz.h`
// ---------------------------------------------------------------------------------------
//
// Dort steckt alles, was die Plattformen unterscheidet: WinHTTP unter Windows, libcurl auf
// macOS und Linux -- und die Threadschicht, die beide teilen. `netz.h` kennt das X-Plane-SDK
// nicht und lässt sich deshalb ohne Simulator übersetzen und messen
// (`pruefen/netz_pruefen.cpp`); für Mac und Linux ist das der einzige Test vor dem ersten
// Piloten.
//
// Hier stand bis zum 13.09.2026: "Die Trennlinie liegt an EINER Stelle (netz_*). Wer macOS
// oder Linux nachrüstet, tauscht diesen Block und sonst nichts." **Das war zu wenig.**
// Windows steckte außerdem in der Thread- und Zeitschicht (CreateThread, CRITICAL_SECTION,
// GetTickCount64) und in einer fehlenden Zeile bei den Pfaden -- und `json.h` rechnete
// locale-abhängig, was ausgerechnet deutsche Piloten getroffen hätte.

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
#include "netz.h"

#include <chrono>
#if defined(_WIN32)
  #include <process.h>
  static inline unsigned long eigene_prozessnummer() { return (unsigned long)_getpid(); }
#else
  #include <unistd.h>
  static inline unsigned long eigene_prozessnummer() { return (unsigned long)getpid(); }
#endif


// ---------------------------------------------------------------------------------------
// Feste Größen
// ---------------------------------------------------------------------------------------

// Die Fassung gehört der UMSETZUNG, nicht dem Protokoll. Das WASM-Modul steht bei 1.6.0,
// weil es sechs Runden im Simulator hinter sich hat; diese Brügge fängt bei 1.0.0 an. Was
// beide verbindet, ist `protokoll: 1` -- und das steht in der Meldung daneben.
#define BRUEGGE_VERSION   "1.4.0"
#define SIMULATOR_NAME    "xplane12"


// Wo die Kennung liegt. `Output/preferences` ist der von Laminar vorgesehene Ort für
// Plugin-Einstellungen und überlebt ein Neuinstallieren des Plugins -- neben der .xpl läge
// sie im selben Ordner, den ein Update überschreibt.
#define KENNUNG_DATEI     "Output/preferences/friesenbruegge.kennung"

// ---------------------------------------------------------------------------------------
// Und daneben darf eine Datei stehen, die das Ziel umbiegt.
// ---------------------------------------------------------------------------------------
//
// Eine Zeile, z. B.  http://127.0.0.1:8099/api/bruegge/melden
//
// WOZU: Der Server liefert `soll` nur an einen Piloten, den er ueber die Position einem
// VATSIM-Flug zuordnen konnte (PROTOKOLL.md, Abschnitt 5). Das ist richtig so -- es heisst
// aber, dass sich das OBJEKTSETZEN ohne VATSIM-Verbindung gar nicht pruefen laesst. Am
// 13.09.2026 hat genau das eine Stunde gekostet: Die Bruegge lief nachweislich, meldete
// sauber, bekam aber immer ein leeres `soll`, weil der VATSIM-Client des Piloten seinen
// eigenen Simulator nicht fand.
//
// Mit dieser Datei zeigt die Bruegge auf `pruefserver.py` im selben Ordner. Der nimmt die
// Meldung entgegen, zeigt sie an und antwortet mit einem Sollzustand, den man von Hand
// zusammenstellt -- also genau die Auskunft, die sonst der Server gaebe.
//
// ⚠ SIE IST KEIN SCHALTER FUER DEN BETRIEB. Wer sie liegen laesst, meldet an niemanden; das
// Log sagt bei jedem Start, welches Ziel gilt. Ohne die Datei ist das Ziel fest einkompiliert
// und kann von aussen nicht verbogen werden.
#define ZIEL_DATEI        "Output/preferences/friesenbruegge.url"

#define SPUR_MAX 16
#define SPRUNG_GRAD 0.005         // rund 555 m in der Breite; 600 kt sind 309 m/s
// Am 14.09.2026 von 32 auf 200 gehoben, gleichlautend mit der MSFS-Fassung.
//
// ⚠ BEIDE PUFFER IN `netz.h` MUSSTEN MITGEHEN -- ANTWORT_PUFFER (die Antwort traegt
// `soll` je Objekt) und MELDUNG_PUFFER (die Meldung traegt `steht` je Objekt). Die
// Rechnung steht dort.
//
// ⚠ Die Leistung ist UNGEMESSEN: Gemessen sind 30 gleichzeitige Instanzen (12.09.2026).
#define SOLL_MAX 200
// Wie viele VERSCHIEDENE .obj gleichzeitig geladen sein duerfen.
//
// ⚠ DAS IST UNSERE GRENZE, NICHT DIE VON X-PLANE. `XPLMLoadObject` kennt keine Obergrenze,
// dort begrenzt allein der Speicher. Hier stand bis zum 16.09.2026 eine 24 ohne jede
// Begruendung -- und sie wurde unversehens zur harten Schranke, als der Katalogdurchlauf
// (scripts/katalog_durchpruefen.py) viele verschiedene Modelle nacheinander setzen wollte:
// nach 24 nur noch `MODELLBESTAND_VOLL`.
//
// Die Ursache war aber nicht die Zahl, sondern dass NIE EINES FREIGEGEBEN WURDE
// (`XPLMUnloadObject` stand allein in `XPluginStop`). Das ist der eigentliche Fix, s.
// `modell_aufraeumen` -- und mit ihm ist die Zahl hier nur noch die Frage, wie viele
// verschiedene Modelle GLEICHZEITIG SICHTBAR sein duerfen.
//
// 64 statt 24, weil das die Frage beantwortet, um die es wirklich geht: Eine Station mit
// Robben, Windrad, Kran, Fahrzeugen, Rauch und Flaggen kommt schnell auf ein Dutzend
// verschiedener Modelle, und bei 24 waere die Luft duenn geworden, ohne dass jemand es
// vorher gemerkt haette -- gemerkt haette es der Pilot mitten im Event.
//
// Der Platz kostet nichts: `GeladenesObjekt` sind 200 Byte Pfad plus Zeiger und zwei
// Wahrheitswerte, also rund 216 Byte. 64 davon sind 14 kB statischer Speicher. Was Speicher
// kostet, sind die MODELLE -- und die laedt X-Plane ohnehin nur, wenn sie gebraucht werden
// (die Oelplattform allein ist 63 MB). Ein hoeheres Limit laedt nichts zusaetzlich; es
// erlaubt nur, mehr gleichzeitig stehen zu lassen.
#define OBJEKTE_MAX 64

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
    int    objekt_idx;            // Platz in `g_objekte`, -1 = keiner -- s. modell_aufraeumen
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
    unsigned long long a = (unsigned long long)eigene_prozessnummer();
    unsigned long long b = (unsigned long long)
        std::chrono::steady_clock::now().time_since_epoch().count();
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

// Die zuletzt empfangene Antwort. Sie traegt seit Protokollfassung 2 die Titel, und der
// Nachrueck-Fall (Pfad scheitert -> naechsten probieren) braucht sie noch, wenn
// `soll_abgleichen` laengst durchgelaufen ist.
//
// ⚠ Immer die ZULETZT empfangene, nicht die, unter der ein Objekt entstanden ist. Aendert
// der Server die Liste einer Art, gilt sofort die neue -- er ist die Wahrheit, nicht das
// Gedaechtnis der Bruegge.
static char g_antwort[ANTWORT_PUFFER] = {0};

// ---------------------------------------------------------------------------------------
// Art -> .obj-Pfad: DIE ZUORDNUNG KOMMT VOM SERVER (Protokollfassung 2, 14.09.2026)
// ---------------------------------------------------------------------------------------
//
// ⚠ HIER STAND `g_gattungen[]` -- 15 Arten, 35 Pfade. Entfernt, wie in der MSFS-Bruegge und
// aus demselben Grund (PROTOKOLL.md, Zeile eins):
//
//     Die Bruegge ist dumm. Alle Klugheit bleibt auf dem Server.
//
// Eine Tabelle im Client kostet ein Release, sobald sich etwas aendert -- und sie weiss
// nichts darueber, was tatsaechlich funktioniert. Der Server fuehrt 2935 Titel mit
// Pruefergebnis; was hier stand, steht jetzt dort.
//
// ⚠ WAS DABEI AUFFIEL, ALS DIE TABELLE GELESEN WURDE: Zwei Verneinungen in ihren Kommentaren
// waren falsch. "X-Plane bringt kein Bodenfahrzeug als eigenstaendige .obj mit" -- es bringt
// 333 mit, unter `airport scenery/`. "Kein Windrad im Bestand" -- es sind drei, sie heissen
// nur `WindTbn2m5_100.obj`. Beide Male lag es am Suchmuster, nicht am Bestand. Im selben
// Zweig liegen 64 Leuchttuerme.
//
// Die Pfade stehen weiterhin relativ zum X-System-Ordner, so will es XPLMLoadObject -- der
// Server schickt sie in genau dieser Form, weil sein Katalog sie so fuehrt.

// Den n-ten Pfad einer Art -- aus der letzten Antwort des Servers.
static const char* pfad_fuer(const char* art, int n) {
    static char puffer[256];   // X-Plane-Pfade sind lang: "Resources/default scenery/..."
    if (!json_titel_fuer(g_antwort, art, n, puffer, sizeof(puffer))) return nullptr;
    return puffer;
}

// Kennt der Server diese Art? Eine LEERE Liste zaehlt als bekannt -- das unterscheidet
// "gibt es hier nicht" von "gibt es gar nicht".
static bool art_bekannt(const char* art) {
    return json_art_bekannt(g_antwort, art);
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
static int objekt_holen(const char* voll) {
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

// Läuft gerade eine Anfrage? Gehört zur Ablaufsteuerung hier, nicht ins Netz: Der Takt
// stellt damit sicher, dass nicht zwei Meldungen gleichzeitig unterwegs sind.
static bool g_anfrage_laeuft = false;

// Steht ZIEL_DATEI da, gilt, was drinsteht. Sonst bleibt es beim einkompilierten Ziel.
//
// Der Parser ist mit Absicht knapp: Er versteht `http://host[:port]/pfad` und dasselbe mit
// https. Was er nicht versteht, verwirft er -- ein halb gelesenes Ziel waere schlimmer als
// gar keins, denn dann meldete die Bruegge irgendwohin und niemand wuesste wohin.
static void ziel_laden() {
    char wurzel[512] = {0};
    XPLMGetSystemPath(wurzel);
    char pfad[640];
    std::snprintf(pfad, sizeof(pfad), "%s%s", wurzel, ZIEL_DATEI);

    FILE* f = std::fopen(pfad, "rb");
    if (!f) {
        logzeile("Ziel: friesenspy.devprops.de (fest einkompiliert)");
        return;
    }
    char zeile[400] = {0};
    size_t n = std::fread(zeile, 1, sizeof(zeile) - 1, f);
    std::fclose(f);
    zeile[n] = '\0';
    for (char* p = zeile; *p; ++p) {
        if (*p == '\r' || *p == '\n' || *p == ' ' || *p == '\t') { *p = '\0'; break; }
    }

    bool sicher;
    const char* rest;
    if (std::strncmp(zeile, "https://", 8) == 0)     { sicher = true;  rest = zeile + 8; }
    else if (std::strncmp(zeile, "http://", 7) == 0) { sicher = false; rest = zeile + 7; }
    else { logzeile("Ziel-Datei unbrauchbar (kein http:// oder https://) -- bleibe beim Standard"); return; }

    // Host bis zum ersten ':' oder '/'.
    char host[160] = {0};
    size_t i = 0;
    while (rest[i] && rest[i] != ':' && rest[i] != '/' && i < sizeof(host) - 1) {
        host[i] = rest[i];
        ++i;
    }
    if (i == 0) { logzeile("Ziel-Datei unbrauchbar (kein Rechnername)"); return; }

    unsigned port = sicher ? 443u : 80u;
    if (rest[i] == ':') {
        ++i;
        unsigned gelesen = 0;
        bool ziffern = false;
        while (rest[i] >= '0' && rest[i] <= '9') { gelesen = gelesen * 10 + (unsigned)(rest[i] - '0'); ++i; ziffern = true; }
        if (!ziffern || gelesen == 0 || gelesen > 65535) { logzeile("Ziel-Datei unbrauchbar (Portnummer)"); return; }
        port = gelesen;
    }
    const char* rumpf = (rest[i] == '/') ? rest + i : "/";

    netz_ziel(host, port, rumpf, sicher);

    char sage[500];
    std::snprintf(sage, sizeof(sage), "Ziel UMGEBOGEN auf %s://%s:%u%s (%s)",
                  sicher ? "https" : "http", host, port, rumpf, ZIEL_DATEI);
    logzeile(sage);
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
    j.feld("protokoll");       j.ganzzahl(2);            j.komma();
    j.feld("simulator");       j.text(SIMULATOR_NAME);   j.komma();
    j.feld("bruegge_version"); j.text(BRUEGGE_VERSION);  j.komma();
    if (g_antwort_zu_gross > 0) {
        j.feld("antwort_zu_gross"); j.ganzzahl((long)g_antwort_zu_gross); j.komma();
    }
    j.feld("kennung");         j.text(g_kennung);        j.komma();

    // ⚠ HIER STAND `kann` -- entfernt mit Protokollfassung 2 (14.09.2026).
    //
    // Ohne eigene Artentabelle kann die Bruegge nichts mehr behaupten. Der Server schickt
    // fuer den gemeldeten Simulator, was er hat, und erfaehrt aus `steht`, was tatsaechlich
    // stand. Belegt statt behauptet -- und ausgewertet hat er `kann` ohnehin nie.

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

// Weiter unten definiert -- `objekt_setzen` und `objekt_wegnehmen` brauchen sie
// beide, und sie steht bei den anderen Modell-Funktionen.
static void modell_aufraeumen(int idx);

static void objekt_setzen(int i) {
    SollObjekt& o = g_soll[i];

    const char* pfad = pfad_fuer(o.art, o.titel_nr);
    if (!pfad) {
        // Zwei verschiedene Befunde, und der Server soll sie unterscheiden koennen:
        // KEIN_MODELL_MEHR heisst "die Art gibt es, aber keiner ihrer Pfade liess sich
        // laden" (die Dateien fehlen bei DIESEM Piloten), GATTUNG_UNBEKANNT heisst "der
        // Server hat zu dieser Art gar nichts mitgeschickt".
        //
        // ⚠ `ART_UNBEKANNT` seit 1.3.0 (16.09.2026) -- vorher `GATTUNG_UNBEKANNT`. Seit dem
        // 14.09.2026 heisst es im ganzen Haus „Art", nur dieser Fehlercode hinkte hinterher
        // und stand dem Nutzer im Admin vor der Nase: *"Gattung unbekannt? wir haben jetzt
        // Arten, keine Gattungen mehr!"*
        //
        // ⚠ DER SERVER NIMMT BEIDE SCHREIBWEISEN AN (`_BRUEGGE_KEIN_URTEIL` in app/main.py),
        // und das muss so bleiben, solange eine Bruegge vor 1.3.0 fliegt. Ein Fehlercode ist
        // ein Vertrag: Wer ihn umbenennt und die alte Fassung streicht, legt bei jedem
        // Piloten, der nicht herunterlaedt, Titel still.
        std::snprintf(o.fehler, sizeof(o.fehler), "%s",
                      art_bekannt(o.art) ? "KEIN_MODELL_MEHR" : "ART_UNBEKANNT");
        return;
    }

    int oi = objekt_holen(pfad);
    if (oi < 0) { std::snprintf(o.fehler, sizeof(o.fehler), "MODELLBESTAND_VOLL"); return; }
    // Wer welches Modell benutzt -- daran haengt die Freigabe (s. `modell_aufraeumen`).
    // Wechselt ein Objekt den Titel (`titel_nr` rueckt nach), gibt der alte Platz frei,
    // sobald ihn niemand mehr braucht.
    if (o.objekt_idx != oi) {
        const int vorher = o.objekt_idx;
        o.objekt_idx = oi;
        if (vorher >= 0) modell_aufraeumen(vorher);
    }
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
    // Den Platz MERKEN, bevor er weggeraeumt wird -- danach ist er 0 und zeigte auf das
    // erste Modell im Bestand.
    const int idx = o.objekt_idx;
    std::memset(&o, 0, sizeof(o));
    o.objekt_idx = -1;
    modell_aufraeumen(idx);
}

// Ein Modell freigeben, sobald es KEIN Soll-Objekt mehr braucht (1.3.0, 16.09.2026).
//
// ⚠⚠ **Vorher wurde im Betrieb nie eines freigegeben.** `XPLMUnloadObject` stand
// ausschliesslich in `XPluginStop`; `g_objekte` fuellte sich bis OBJEKTE_MAX und blieb voll.
// Fuer den Flugbetrieb faellt das nicht auf -- eine Robbenkolonie sind 200 Instanzen EINES
// Modells. Es faellt auf, sobald viele VERSCHIEDENE Modelle nacheinander kommen:
//
// Beim Durchpruefen des Katalogs (scripts/katalog_durchpruefen.py, 16.09.2026) war nach
// 24 Titeln Schluss, und alles Weitere meldete `MODELLBESTAND_VOLL`. Ein Lauf ueber die
// 2928 X-Plane-Titel haette 122 Simulator-Neustarts gebraucht.
//
// Gezaehlt wird ueber `objekt_idx` statt ueber einen Referenzzaehler: Der Index steht ohnehin
// im Soll-Objekt, und ein Zaehler waere eine zweite Wahrheit, die beim naechsten Umbau
// auseinanderlaeuft. Der Durchlauf ist SOLL_MAX Schritte lang -- das ist einmal je
// abgeraeumtem Objekt, nicht je Takt.
static void modell_aufraeumen(int idx) {
    if (idx < 0 || idx >= OBJEKTE_MAX || !g_objekte[idx].pfad[0]) return;
    if (g_objekte[idx].laedt) return;      // der Rueckruf kommt noch und will den Platz
    for (int i = 0; i < SOLL_MAX; ++i) {
        if (g_soll[i].belegt && g_soll[i].objekt_idx == idx) return;   // noch in Benutzung
    }
    if (g_objekte[idx].ref) XPLMUnloadObject(g_objekte[idx].ref);
    std::memset(&g_objekte[idx], 0, sizeof(g_objekte[idx]));
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
            // ⚠ NACH dem memset, und das ist kein Beiwerk: 0 waere ein GUELTIGER Platz im
            // Modellbestand. Jedes frische Soll-Objekt haette damit behauptet, Modell 0 zu
            // benutzen -- und `modell_aufraeumen` haette genau dieses eine nie freigegeben.
            o.objekt_idx = -1;
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
    static NetzMeldung m;
    if (!netz_antwort(&m)) return;

    // Die Antwort AUFHEBEN: Seit Protokollfassung 2 traegt sie die Titel, und der
    // Nachrueck-Fall braucht sie spaeter noch -- `m` wird beim naechsten Abholen
    // ueberschrieben.
    std::snprintf(g_antwort, sizeof(g_antwort), "%s", m.text);
    const char* kopie = g_antwort;
    int status = (int)m.code;
    unsigned long zu_gross = m.zu_gross ? (unsigned long)m.laenge : 0ul;

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

    // ⚠ Diese Zeile MUSS vor jedem Dateizugriff stehen. Ohne sie liefert XPLMGetSystemPath
    // auf macOS einen klassischen HFS-Pfad mit Doppelpunkten ("Macintosh HD:Applications:
    // X-Plane 12:"), den fopen nicht öffnet -- die .url-Datei für den Prüfserver wäre dort
    // unauffindbar und die Kennung würde bei jedem Start neu erfunden. Der SDK-Header sagt
    // es ausdrücklich: "All plugins should enable this feature on OS X."
    // Unter Windows dreht sie die Schrägstriche von \ auf /; fopen trägt beides.
    XPLMEnableFeature("XPLM_USE_NATIVE_PATHS", 1);

    // Das Ziel MUSS vor dem Netzthread feststehen -- er liest es ohne Schloss, weil es
    // sich danach nie wieder ändert.
    ziel_laden();

    // ⚠ Hier, nicht im Netzthread: Auf macOS und Linux wird libcurl an dieser Stelle per
    // dlopen geholt, und ein Fehlschlag muss ins Log -- was der Netzthread nicht darf.
    char netztext[256] = {0};
    if (netz_bereit(netztext, sizeof(netztext))) {
        logzeile(netztext);
        netz_start();
    } else {
        logzeile(netztext);
        logzeile("Die Bruegge laeuft weiter, meldet aber nichts.");
    }

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

    // Den Netzthread ordentlich beenden: Ende setzen, wecken, warten. Ohne das Warten
    // stürbe der Prozess mitten in einem Netzaufruf.
    netz_ende();
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
