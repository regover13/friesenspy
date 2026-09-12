// Die FriesenBrügge für MSFS 2020 und 2024.
//
// Sie meldet dem FriesenSpy-Server, wo der Pilot gerade ist, und stellt hin, was der Server
// ihr nennt. Der Vertrag steht in ../PROTOKOLL.md (Fassung 1, abgenommen 11.09.2026).
//
//     Die Brügge ist dumm. Alle Klugheit bleibt auf dem Server.
//
// Sie weiß nicht, ob gerade gezählt, gesucht oder gerätselt wird. Ein neuer Eventtyp braucht
// deshalb keine Änderung an ihr und kein neues Paket beim Piloten -- und genau das ist der
// Grund, warum dieses Modul so wenig kann.
//
// GEMESSEN, bevor eine Zeile davon entstand (Belege in ../probe-msfs/ERGEBNIS.md):
//
//   - Ein WASM-Modul kann die eigene Position lesen. Der frühere EXCEPTION 3 war eine
//     ID-Kollision im eigenen Quelltext, kein Simulator-Verhalten.
//   - Es kann Objekte setzen; sie bleiben stehen (364 s gemessen) und überleben sogar einen
//     Flugwechsel, solange die SimConnect-Verbindung offen ist.
//   - `OnGround=1` ist aus WASM heraus unbrauchbar -- es setzt nicht auf, sondern auf einen
//     ortsabhängigen Wert (49 ft auf Wangerooge, 122-130 ft in Seattle). `OnGround=0` mit
//     einer gerechneten Höhe trifft dagegen exakt.
//   - Nach dem Start liefert der Simulator erst 0/90, dann Seattle, dann den geladenen Flug.
//     Jeder Wert sieht für sich vernünftig aus; nur der SPRUNG verrät den Ladevorgang.

#include <MSFS/MSFS.h>
#include <MSFS/MSFS_WindowsTypes.h>
#include <MSFS/MSFS_Network.h>
#include <SimConnect.h>

// Die Datei-API gibt es NUR im MSFS-2024-SDK -- MSFS_IO.h fehlt im 2020er vollstaendig
// (geprueft 11.09.2026). Damit ist die dauerhafte Kennung eine Eigenschaft von MSFS 2024;
// unter MSFS 2020 zieht die Bruegge bei jedem Start eine neue.
//
// Das kostet weniger, als es klingt: Der Server matcht dann einmal je SITZUNG voll statt
// einmal je Installation. Bei einer Flugstunde im Sekundentakt ist das ein voller Match
// statt 3600 -- der Nutzen der Kennung bleibt praktisch vollstaendig erhalten.
#ifndef FUER_MSFS2020
#include <MSFS/MSFS_IO.h>
#define KENNUNG_HAELT 1
#endif

#include <cstdio>
#include <cstring>
#include <cstdlib>

#include "json.h"

// ---------------------------------------------------------------------------------------
// Feste Größen
// ---------------------------------------------------------------------------------------

#define BRUEGGE_VERSION   "1.1.2"
#define BRUEGGE_URL       "https://friesenspy.devprops.de/api/bruegge/melden"
#define KENNUNG_DATEI     "\\work\\friesenbruegge.kennung"

#ifdef FUER_MSFS2020
#define SIMULATOR_NAME "msfs2020"
#else
#define SIMULATOR_NAME "msfs2024"
#endif

// Die eigene Lage wird JEDE SEKUNDE gelesen -- unabhängig davon, wie oft gesendet wird.
// Was zwischen zwei Meldungen anfällt, geht als `spur` mit; bei Regeltakt 1 s ist sie leer
// oder trägt einen Punkt, bei gedrosseltem Takt trägt sie den vollen Zwischenweg. Ohne sie
// verlöre jede Drosselung unwiederbringlich Auflösung.
#define SPUR_MAX 16

// Ein Sprung über diese Weite zwischen zwei Sekunden ist kein Flug, sondern ein Ladevorgang,
// ein Slew oder ein Flugwechsel. 600 kt sind 309 m/s.
#define SPRUNG_GRAD 0.005     // rund 555 m in der Breite

// Soviel Puffer braucht die Meldung mit voller Spur, großzügig gerechnet.
#define MELDUNG_PUFFER 8192

// Soviele Objekte haelt die Bruegge gleichzeitig. Der Simulator vertraegt deutlich mehr
// (im Probeflug gemessen), aber eine feste Obergrenze im Modul ist billiger als eine
// dynamische Verwaltung -- und der Server weiss ohnehin, was er anfordert.
#define SOLL_MAX 32

enum {
    EV_SEKUNDE   = 1,
    EV_SIMSTART  = 2,
    EV_FLUGGELADEN = 3,
    DEF_LAGE     = 10,
    REQ_LAGE     = 20,
    // Je gesetztem Objekt eine eigene Anfrage-Nummer -- so bleibt zuzuordnen, welches Objekt
    // meldet. Der Abstand zu den uebrigen IDs ist Absicht: SIMCONNECT_DATA_DEFINITION_ID ist
    // ein gemeinsamer Nummernraum, und eine Kollision endet mit UNRECOGNIZED_ID an einer
    // Stelle, die voellig unverdaechtig aussieht (11.09.2026 gemessen).
    REQ_ERZEUGEN = 1000,      // 1000 .. 1000+SOLL_MAX
    REQ_OBJEKT   = 2000,      // 2000 .. 2000+SOLL_MAX
};

// Ein Objekt, das dastehen soll -- und wie es ihm ergangen ist.
struct SollObjekt {
    char   id[40];
    char   art[24];
    double lat, lon, kurs, erwartete_hoehe_ft;
    bool   hat_hoehe;

    bool   belegt;            // Platz in Benutzung
    bool   in_soll;           // steht in der aktuellen Antwort des Servers
    bool   erzeugt_gerufen;   // AICreateSimulatedObject ist raus
    DWORD  objekt_id;         // vom Simulator vergeben, 0 = noch keine
    double hoehe_ft;          // zuletzt gemeldete Hoehe
    DWORD  letzte_meldung_s;  // Sekunde der letzten Lagemeldung
    DWORD  seit_s;            // seit wann im aktuellen Zustand
    char   fehler[32];        // gesetzt, wenn das Erzeugen abgelehnt wurde
};

static SollObjekt g_soll[SOLL_MAX];

// Die Lagedaten, in genau dieser Reihenfolge in der Datendefinition angemeldet.
struct Lage {
    double lat;
    double lon;
    double alt_msl_ft;
    double alt_agl_ft;
    double gs_kt;
    double kurs;
    double am_boden;
    // Die Steig-/Sinkrate. KEINE Zugabe: Der Server braucht sie fuer die Hoehenschranke.
    // Ohne sie rechnet er mit 0 und faellt auf die Untergrenze von 300 ft zurueck -- ein
    // steigendes Flugzeug weicht aber zwangslaeufig von seiner 29 s alten VATSIM-Hoehe ab,
    // bei 1000 ft/min um 483 ft. Genau daran ist die Zuordnung im ersten Flug gerissen
    // (11.09.2026, Fassung 1.0.1).
    double vs_ft_min;
};

struct SpurPunkt {
    double alter_s;
    double lat, lon, alt_msl_ft, gs_kt, kurs;
};

// ---------------------------------------------------------------------------------------
// Zustand
// ---------------------------------------------------------------------------------------

static HANDLE  g_sim = 0;
static bool    g_welt_da = false;         // SimStart/FlightLoaded ist gekommen
static DWORD   g_sekunden = 0;            // seit dem letzten Welt-Signal
static Lage    g_lage = {};
static bool    g_lage_gueltig = false;
static double  g_vor_lat = 0.0, g_vor_lon = 0.0;
static bool    g_vor_gueltig = false;

static SpurPunkt g_spur[SPUR_MAX];
static int       g_spur_anzahl = 0;

static char    g_kennung[40] = {0};
static int     g_takt_s = 1;              // was der Server zuletzt vorgegeben hat
static DWORD   g_seit_meldung = 0;
static FsNetworkRequestId g_laufend = 0;  // 0 = keine Anfrage offen
static DWORD   g_gilt_bis_s = 300;        // wie lange `soll` ohne neue Auskunft gilt
static DWORD   g_letzte_antwort_s = 0;    // Sekunde der letzten angekommenen Antwort
static DWORD   g_laufend_seit = 0;        // Sekunden -- gegen haengende Anfragen

// ---------------------------------------------------------------------------------------
// Kennung -- dauerhaft, wo es geht
// ---------------------------------------------------------------------------------------

// Die Kennung ist KEIN Geheimnis: Die Brügge erzeugt sie selbst, sie steht offen in jeder
// Meldung, und sie öffnet nichts. Sie sagt nur "ich bin dieselbe wie vorhin" -- und erspart
// dem Server damit, den vollen Positionsmatch bei jeder Meldung neu zu rechnen.
//
// Geht das Speichern schief, ist das kein Fehlerfall: Die Brügge zieht dann bei jedem Start
// eine neue, und der Server matcht einmal je Sitzung voll statt einmal je Installation. Bei
// einer Flugstunde im Sekundentakt ist das ein voller Match statt 3600 -- der Nutzen bleibt
// praktisch vollständig erhalten.
static void kennung_erzeugen() {
    // Kein Zufallsgenerator nötig und keiner verfügbar, der hier etwas Besseres liefern
    // würde: Die Kennung muss eindeutig sein, nicht unvorhersagbar.
    unsigned long long a = (unsigned long long)(size_t)&g_sim;
    unsigned long long b = (unsigned long long)std::rand();
    unsigned long long c = (unsigned long long)(g_sekunden + 1) * 2654435761u;
    std::snprintf(g_kennung, sizeof(g_kennung), "%08llx%08llx",
                  (a ^ c) & 0xFFFFFFFFull, (b ^ (a >> 16)) & 0xFFFFFFFFull);
}

#ifdef KENNUNG_HAELT
// Hier landet die gelesene Kennung, sobald der Lesevorgang fertig ist.
static char g_kennung_gelesen[64] = {0};

static void kennung_gelesen(FsIOFile datei, char* puffer, int, int bytes, void*) {
    if (bytes > 0 && bytes < (int)sizeof(g_kennung_gelesen)) {
        std::memcpy(g_kennung_gelesen, puffer, bytes);
        g_kennung_gelesen[bytes] = '\0';
    }
    fsIOClose(datei);
}
#endif

static void kennung_schreiben() {
#ifdef KENNUNG_HAELT
    FsIOFile w = fsIOOpen(KENNUNG_DATEI,
                          FsIOOpenFlag_WRONLY | FsIOOpenFlag_CREAT | FsIOOpenFlag_TRUNC,
                          nullptr, nullptr);
    if (w != FS_IO_ERROR_FILE) {
        fsIOWrite(w, g_kennung, 0, (int)std::strlen(g_kennung), nullptr, nullptr);
        fsIOClose(w);
    }
#endif
}

static void kennung_laden_oder_erzeugen() {
#ifdef KENNUNG_HAELT
    // Lesen ist asynchron: Der Callback kommt spaeter, moeglicherweise erst nach der ersten
    // Meldung. Das ist hinnehmbar -- eine Meldung mit frischer Kennung kostet einen vollen
    // Match, mehr nicht -- und deshalb wird hier NICHT gewartet.
    static char puffer[64];
    fsIOOpenRead(KENNUNG_DATEI, FsIOOpenFlag_RDONLY, 0, (int)sizeof(puffer) - 1,
                 kennung_gelesen, nullptr);
#endif
    kennung_erzeugen();
    kennung_schreiben();
}

// Ist die Kennung aus der Datei inzwischen eingetroffen? Dann gilt sie -- sie ist die
// aeltere und damit die, die der Server schon kennt.
static void kennung_pruefen() {
#ifdef KENNUNG_HAELT
    if (g_kennung_gelesen[0] == '\0') return;
    // Nur uebernehmen, wenn sie plausibel aussieht: 16 Hexziffern, wie kennung_erzeugen sie
    // baut. Eine halb geschriebene oder fremde Datei soll nicht durchschlagen.
    size_t n = std::strlen(g_kennung_gelesen);
    if (n == 16) {
        bool hex = true;
        for (size_t i = 0; i < n; ++i) {
            char c = g_kennung_gelesen[i];
            if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) { hex = false; break; }
        }
        if (hex) std::snprintf(g_kennung, sizeof(g_kennung), "%s", g_kennung_gelesen);
    }
    g_kennung_gelesen[0] = '\0';
#endif
}

// ---------------------------------------------------------------------------------------
// Gattung -> Container-Titel
// ---------------------------------------------------------------------------------------
//
// DIE ZUORDNUNGSTABELLE GEHOERT ZUR BRUEGGE, nicht zum Server. Sie kennt ihren Simulator;
// der Server kennt ihn nicht. Eine Gattung ist eine BEDEUTUNG, kein Modell -- welches Tier
// ein tier_gross ist, darf sich zwischen Simulatoren unterscheiden, denn der Pilot zaehlt
// Tiere, nicht Baeren.
//
// Alle Titel hier sind im Probeflug gesetzt und im Bild gesehen worden
// (../probe-msfs/ERGEBNIS.md).
static const char* titel_fuer(const char* art) {
    if (std::strcmp(art, "tier_gross") == 0)  return "BlackBear";
    if (std::strcmp(art, "bauwerk") == 0)     return "Windmill";
    if (std::strcmp(art, "fahrzeug") == 0)    return "ASO_Ambulance_Japan";
    if (std::strcmp(art, "boot_klein") == 0)  return "Boat01";
    if (std::strcmp(art, "boot_gross") == 0)  return "CruiseShip01";
    return nullptr;   // unbekannte Gattung: nicht raten, sondern melden
}

// ---------------------------------------------------------------------------------------
// Die Meldung bauen
// ---------------------------------------------------------------------------------------

static void meldung_bauen(char* puffer, size_t groesse) {
    JsonSchreiber j(puffer, groesse);
    j.roh("{");
    j.feld("protokoll");       j.ganzzahl(1);                 j.komma();
    j.feld("simulator");       j.text(SIMULATOR_NAME);        j.komma();
    j.feld("bruegge_version"); j.text(BRUEGGE_VERSION);       j.komma();
    j.feld("kennung");         j.text(g_kennung);             j.komma();

    // `kann` geht bei JEDER Anfrage mit, nicht nur beim ersten Mal: Der Server hält keine
    // Sitzung, und eine zustandslose Meldung übersteht jeden Neustart auf beiden Seiten.
    j.feld("kann");
    j.roh("[\"tier_gross\",\"bauwerk\",\"fahrzeug\",\"boot_klein\",\"boot_gross\"]");
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
    j.feld("am_boden");   j.roh(g_lage.am_boden > 0.5 ? "true" : "false");
    j.roh("}");
    j.komma();

    // `alter_s` ist das Alter des Punktes BEIM ABSENDEN, keine Uhrzeit. Der Server rechnet
    // gegen seine eigene Empfangszeit auf -- damit hängt nichts an der Systemuhr des Piloten,
    // die falsch gehen darf.
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
    // Ohne diese Rueckmeldung versuchte die Bruegge ein abgelehntes Objekt jede Sekunde
    // erneut, fuer immer, und der Server erfuehre nie, dass die Stelle unbrauchbar ist.
    //
    // Das Feld bleibt auch dann drin, wenn nichts dasteht -- als leeres Array. Sonst muesste
    // der Server zwischen "nichts gesetzt" und "Feld fehlt" raten, und das sind zwei sehr
    // verschiedene Dinge.
    //
    // Die Gegenseite gibt es seit dem 12.09.2026: Bis dahin sendete die Bruegge diesen Block
    // und der Server warf ihn weg (`bruegge_steht_melden` in database.py). Aufgefallen ist
    // das erst im Simulator, als es zu messen galt.
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
        } else if (g_soll[i].objekt_id == 0) {
            j.feld("zustand"); j.text("fehlgeschlagen"); j.komma();
            j.feld("fehler");  j.text("KEINE_ANTWORT");
        } else if (g_sekunden > g_soll[i].letzte_meldung_s + 5) {
            j.feld("zustand"); j.text("verschwunden"); j.komma();
            j.feld("seit_s");  j.ganzzahl((long)(g_sekunden - g_soll[i].letzte_meldung_s));
        } else {
            j.feld("zustand");  j.text("steht"); j.komma();
            j.feld("hoehe_ft"); j.zahl(g_soll[i].hoehe_ft, 1); j.komma();
            j.feld("seit_s");   j.ganzzahl((long)(g_sekunden - g_soll[i].seit_s));
        }
        j.roh("}");
    }
    j.roh("]");
    j.roh("}");
}

// ---------------------------------------------------------------------------------------
// Der Sollzustand-Abgleich
// ---------------------------------------------------------------------------------------
//
// `soll` ist die VOLLSTAENDIGE Liste dessen, was jetzt dastehen soll -- kein Strom von
// Befehlen. Die Bruegge vergleicht sie mit dem, was sie tatsaechlich gesetzt hat, und gleicht
// in beide Richtungen ab:
//
//   in soll, noch nicht gesetzt        erzeugen
//   in soll, gesetzt, lebt             nichts
//   in soll, gesetzt, verschwunden     neu erzeugen
//   gesetzt, nicht mehr in soll        entfernen
//
// Der Unterschied zu Befehlen entscheidet ueber die Robustheit: Geht eine Anfrage verloren,
// haengt das Netz kurz oder startet der Simulator neu, holt die naechste Antwort den Zustand
// von allein wieder ein. Bei Befehlen bliebe eine verpasste Loeschung fuer immer stehen.

// Der Platz eines Objekts -- vorhandener oder freier. -1, wenn alles belegt ist.
static int soll_platz(const char* id) {
    int frei = -1;
    for (int i = 0; i < SOLL_MAX; ++i) {
        if (g_soll[i].belegt && std::strcmp(g_soll[i].id, id) == 0) return i;
        if (!g_soll[i].belegt && frei < 0) frei = i;
    }
    return frei;
}

// Die Gelaendehoehe unter dem Flugzeug.
//
// Gebraucht, weil OnGround aus WASM heraus NICHT aufsetzt: Es landet auf einem ortsabhaengigen
// Wert (49 ft auf Wangerooge, 122-130 ft in Seattle, 213-216 ft an einem ungeladenen Ort --
// alles am 11.09.2026 gemessen). OnGround=0 mit einer gerechneten Hoehe trifft dagegen auf
// die Nachkommastelle genau.
//
// ACHTUNG, die Grenze: Das ist die Hoehe UNTER DEM FLUGZEUG, nicht am Zielort. Fuer ein
// Objekt wenige hundert Meter daneben taugt sie, fuer eines 5 km weiter nicht. An den
// Friesischen Inseln faellt das kaum ins Gewicht -- Watt und Wasser liegen auf Meereshoehe.
// Wo der Server es besser weiss, schickt er erwartete_hoehe_ft mit.
static double gelaendehoehe() {
    if (!g_lage_gueltig) return 0.0;
    double h = g_lage.alt_msl_ft - g_lage.alt_agl_ft;
    // Ueber Wasser meldet MSFS manchmal ein leicht negatives AGL. Auf 0 zu klemmen ist
    // richtiger, als ein Objekt einen Meter unter den Meeresspiegel zu setzen.
    return (h < 0.0 && h > -50.0) ? 0.0 : h;
}

static void objekt_erzeugen(int i) {
    SollObjekt& o = g_soll[i];
    const char* titel = titel_fuer(o.art);
    if (!titel) {
        // Unbekannte Gattung: nicht raten. Der Server erfaehrt es ueber `steht` und kann
        // etwas anderes anfordern -- oder die Stelle auslassen.
        std::snprintf(o.fehler, sizeof(o.fehler), "GATTUNG_UNBEKANNT");
        o.erzeugt_gerufen = true;
        return;
    }

    SIMCONNECT_DATA_INITPOSITION pos{};
    pos.Latitude  = o.lat;
    pos.Longitude = o.lon;
    pos.Altitude  = o.hat_hoehe ? o.erwartete_hoehe_ft : gelaendehoehe();
    pos.Pitch     = 0.0;
    pos.Bank      = 0.0;
    pos.Heading   = o.kurs;
    pos.OnGround  = 0;        // s. gelaendehoehe() -- OnGround=1 ist aus WASM unbrauchbar
    pos.Airspeed  = 0;

    HRESULT hr = SimConnect_AICreateSimulatedObject(g_sim, titel, pos, REQ_ERZEUGEN + i);
    o.erzeugt_gerufen = true;
    o.seit_s = g_sekunden;
    if (hr != S_OK) {
        std::snprintf(o.fehler, sizeof(o.fehler), "CREATE_HR_%08lX", (unsigned long)hr);
    }
}

static void objekt_entfernen(int i) {
    SollObjekt& o = g_soll[i];

    // SimConnect_AIRemoveObject -- und der Aufruf ist eine VORAUSSETZUNG, keine Annehmlichkeit.
    //
    // Gemessen am 12.09.2026 im Simulator, und der Befund war ueberraschend deutlich: Als
    // vPilot kurz die Verbindung verlor, loeste der Server die Zuordnung und lieferte kein
    // `soll` mehr. Die Bruegge VERGASS das Objekt daraufhin -- der Baer im Simulator blieb
    // aber stehen. Beim Wiederverbinden kam dasselbe Objekt erneut im `soll` an und wurde
    // ein zweites Mal gesetzt. Nachweisbar an zwei Zahlen: `seit_s` fing wieder bei null an,
    // und die gemeldete Hoehe wechselte von 1384,9 auf 1379,2 ft.
    //
    // FOLGE OHNE DIESEN AUFRUF: Jeder Verbindungsabriss verdoppelt die gesetzten Objekte.
    // Fuer den FriesenKieker hiesse das, dass ein Pilot mit wackliger Leitung Tiere doppelt
    // und dreifach zaehlt -- und niemand saehe dem Ergebnis an, dass es falsch ist. Genau
    // deshalb steht der Aufruf wieder hier, obwohl er ein Import mehr ist.
    //
    // Der Verdacht gegen ihn war uebrigens falsch: Dass Fassung 1.1.0 nicht lud, lag an einem
    // UTF-8-BOM in manifest.json und layout.json (s. paket.ps1). Auch die nachweislich
    // laufende 1.0.1 lud mit diesem BOM nicht mehr -- der Code war nie das Problem.
    //
    // BLEIBT ZU PRUEFEN: p42-util-campout-mp benutzt AIRemoveObject und laeuft, allerdings
    // laut Log mit der ALTEN SimConnect-Fassung ("The version of simconnect used by the
    // module CampOutModule.wasm cannot be found. It will use the last version used in
    // MSFS2020."), waehrend dieses Modul gegen das 2024er SDK gebaut wird. Sollte das Modul
    // mit diesem Aufruf nicht mehr laden, ist DAS die Erklaerung -- und der Ausweg waere
    // `SetDataOnSimObject` (das Objekt weit wegsetzen), selbst wieder ein neuer Import und
    // deshalb einzeln zu messen.
    if (o.objekt_id != 0) {
        SimConnect_AIRemoveObject(g_sim, o.objekt_id, REQ_ERZEUGEN + i);
    }
    std::memset(&o, 0, sizeof(o));
}

// Alles wegraeumen -- bei Netzausfall nach gilt_bis_s, beim Flugwechsel, beim Herunterfahren.
static void alles_abraeumen() {
    for (int i = 0; i < SOLL_MAX; ++i) {
        if (g_soll[i].belegt) objekt_entfernen(i);
    }
}

static void soll_abgleichen(const char* json) {
    // Erst alles als "nicht mehr gefordert" markieren -- was in der Antwort steht, wird
    // gleich wieder gesetzt. Was uebrig bleibt, faellt weg.
    for (int i = 0; i < SOLL_MAX; ++i) g_soll[i].in_soll = false;

    const char* e = json_array(json, "soll");
    while (e) {
        char id[40];
        if (!json_text_in(e, "id", id, sizeof(id)) || id[0] == '\0') { e = json_naechstes(e); continue; }

        int i = soll_platz(id);
        if (i < 0) { e = json_naechstes(e); continue; }   // voll -- der Server erfaehrt es
                                                          // daran, dass das Objekt in `steht`
                                                          // fehlt
        SollObjekt& o = g_soll[i];
        if (!o.belegt) {
            std::memset(&o, 0, sizeof(o));
            std::snprintf(o.id, sizeof(o.id), "%s", id);
            o.belegt = true;
            o.seit_s = g_sekunden;
        }
        json_text_in(e, "art", o.art, sizeof(o.art));
        o.lat  = json_zahl_in(e, "lat", o.lat);
        o.lon  = json_zahl_in(e, "lon", o.lon);
        o.kurs = json_zahl_in(e, "kurs", 0.0);
        bool hat = false;
        double h = json_zahl_in(e, "erwartete_hoehe_ft", 0.0, &hat);
        o.hat_hoehe = hat;
        o.erwartete_hoehe_ft = h;
        o.in_soll = true;

        e = json_naechstes(e);
    }

    for (int i = 0; i < SOLL_MAX; ++i) {
        SollObjekt& o = g_soll[i];
        if (!o.belegt) continue;

        if (!o.in_soll) {              // nicht mehr gefordert
            objekt_entfernen(i);
            continue;
        }
        if (o.fehler[0]) continue;     // abgelehnt -- NICHT jede Sekunde erneut versuchen.
                                       // Der Server entscheidet, wann es wieder losgeht:
                                       // Er nimmt die id aus `soll` und schickt sie neu.
        if (!o.erzeugt_gerufen) {
            objekt_erzeugen(i);
            continue;
        }
        // Verschwunden? Dann neu erzeugen -- das ist der gemessene Fall (MSFS 2020 liess
        // zweimal denselben Aufruf verschieden ausgehen).
        if (o.objekt_id != 0 && g_sekunden > o.letzte_meldung_s + 10) {
            o.objekt_id = 0;
            o.erzeugt_gerufen = false;
            objekt_erzeugen(i);
        }
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

    // Wie lange der Sollzustand ohne neue Auskunft gilt. Ohne diese Zahl entschiede jede der
    // drei Umsetzungen selbst, was bei Netzausfall geschieht -- und fuer eine Baake waere
    // "stehen bleiben" eine Station, die nie verschwindet.
    double gilt = json_zahl(json, "gilt_bis_s", (double)g_gilt_bis_s);
    if (gilt < 0.0) gilt = 0.0;
    g_gilt_bis_s = (DWORD)gilt;
    g_letzte_antwort_s = g_sekunden;

    soll_abgleichen(json);
}

// Die Antwort kommt per CALLBACK -- und nur dort.
//
// Zwei Anlaeufe stecken in dieser Aufteilung, beide am 11.09.2026 im Live-Lauf gemessen:
//
//   1. Callback mit `if (fehler != 0) return;` -- der zweite Parameter heisst im Header
//      `errorCode`, traegt aber den HTTP-STATUS. Damit wurde JEDE Antwort verworfen, auch
//      die erfolgreiche. Die Bruegge sendete weiter und nahm nie zur Kenntnis, was zurueckkam.
//
//   2. Kein Callback, dafuer den Zustand jede Sekunde abfragen. Scheitert aus einem Grund,
//      der im Header steht: DATA_READY ist "available only during this frame" -- bei 60 fps
//      also rund 17 ms. Eine Abfrage im Sekundentakt verpasst ihn systematisch.
//
// Der Callback liest also, und die Zustandsabfrage ist nur noch WAECHTER: Sie raeumt eine
// Anfrage weg, deren Callback ausbleibt. Ohne sie haengt eine einzige verlorene Anfrage die
// Bruegge fuer den Rest der Sitzung auf -- auch das ist passiert, und von aussen sah es aus
// wie ein Modul, das gar nicht geladen wurde.
static void anfrage_fertig(FsNetworkRequestId id, int status, void*) {
    if (id != g_laufend) return;
    g_laufend = 0;
    g_laufend_seit = 0;

    if (status == 426) {
        // Protokollfassung zu alt: aufraeumen und anhalten. Weiterzureden hiesse, in einem
        // Vertrag zu reden, den auf der anderen Seite niemand mehr liest.
        g_takt_s = 900;
        return;
    }
    if (status == 429) {
        g_takt_s = (g_takt_s * 2 > 60) ? 60 : g_takt_s * 2;   // Rate-Limit
        return;
    }
    // 0 gilt mit, falls die Laufzeit doch ein Fehlerkennzeichen liefert statt eines Status.
    if (!(status == 0 || (status >= 200 && status < 300))) return;

    unsigned long n = fsNetworkHttpRequestGetDataSize(id);
    unsigned char* daten = fsNetworkHttpRequestGetData(id);
    if (!daten || n == 0) return;
    static char kopie[4096];
    unsigned long m = (n < sizeof(kopie) - 1) ? n : sizeof(kopie) - 1;
    std::memcpy(kopie, daten, m);
    kopie[m] = '\0';
    antwort_lesen(kopie);
}

// Der Waechter. Er liest NICHTS -- dafuer ist der Callback da -- er raeumt nur auf.
static void anfrage_bewachen() {
    if (g_laufend == 0) return;
    if (++g_laufend_seit <= 30) return;
    fsNetworkHttpCancelRequest(g_laufend);
    g_laufend = 0;
    g_laufend_seit = 0;
}

static void melden() {
    if (g_laufend != 0) return;            // eine Anfrage reicht; die nächste wartet
    static char puffer[MELDUNG_PUFFER];
    meldung_bauen(puffer, sizeof(puffer));

    static char* kopfzeilen[1];
    static char kopf[] = "Content-Type: application/json";
    kopfzeilen[0] = kopf;

    FsNetworkHttpRequestParam p{};
    p.postField = puffer;
    p.headerOptions = kopfzeilen;
    p.headerOptionsSize = 1;
    p.data = (unsigned char*)puffer;
    p.dataSize = (unsigned int)std::strlen(puffer);

    g_laufend = fsNetworkHttpRequestPost(BRUEGGE_URL, &p, anfrage_fertig, nullptr);
    g_laufend_seit = 0;
    g_spur_anzahl = 0;                     // was mitging, ist mitgegangen
}

// ---------------------------------------------------------------------------------------
// Der Takt
// ---------------------------------------------------------------------------------------

static void sekunde() {
    ++g_sekunden;
    kennung_pruefen();
    anfrage_bewachen();
    if (!g_lage_gueltig) return;

    // Ein SPRUNG ist kein Flug. Nach dem Start liefert der Simulator erst 0/90, dann Seattle,
    // dann den geladenen Flug -- und jeder dieser Werte sieht für sich vernünftig aus. Eine
    // Liste bekannter Fehlorte deckt immer nur die ab, die schon aufgefallen sind; der Sprung
    // verrät den Ladevorgang, ohne dass man einen einzigen Ort kennen muss.
    if (g_vor_gueltig) {
        double dlat = g_lage.lat - g_vor_lat;
        double dlon = g_lage.lon - g_vor_lon;
        if (dlat > SPRUNG_GRAD || dlat < -SPRUNG_GRAD ||
            dlon > SPRUNG_GRAD || dlon < -SPRUNG_GRAD) {
            g_spur_anzahl = 0;
            g_vor_lat = g_lage.lat;
            g_vor_lon = g_lage.lon;
            g_seit_meldung = 0;
            return;                        // dieser Punkt geht NICHT hinauf
        }
    }
    g_vor_lat = g_lage.lat;
    g_vor_lon = g_lage.lon;
    g_vor_gueltig = true;

    // Der Punkt wandert in die Spur. Bei Takt 1 s geht er sofort mit hinauf; bei gedrosseltem
    // Takt sammelt sich hier der Zwischenweg.
    if (g_spur_anzahl < SPUR_MAX) {
        SpurPunkt& s = g_spur[g_spur_anzahl++];
        s.alter_s = 0.0;                   // wird beim Absenden gesetzt
        s.lat = g_lage.lat;
        s.lon = g_lage.lon;
        s.alt_msl_ft = g_lage.alt_msl_ft;
        s.gs_kt = g_lage.gs_kt;
        s.kurs = g_lage.kurs;
    }
    // Alle vorhandenen Punkte altern um eine Sekunde.
    for (int i = 0; i < g_spur_anzahl; ++i) g_spur[i].alter_s += 1.0;

    // Kommt laenger keine Antwort, faellt der Sollzustand. Ohne das bliebe bei einem
    // Netzausfall stehen, was der Server laengst zurueckgenommen hat -- fuer eine Baake
    // hiesse das eine Station, die nie verschwindet.
    if (g_gilt_bis_s > 0 && g_letzte_antwort_s > 0 &&
        g_sekunden > g_letzte_antwort_s + g_gilt_bis_s) {
        alles_abraeumen();
        g_letzte_antwort_s = 0;      // nur EINMAL abraeumen, nicht jede Sekunde erneut
    }

    if (++g_seit_meldung >= (DWORD)g_takt_s) {
        g_seit_meldung = 0;
        melden();
    }
}

// ---------------------------------------------------------------------------------------
// SimConnect
// ---------------------------------------------------------------------------------------

void CALLBACK dispatch(SIMCONNECT_RECV* pData, DWORD, void*) {
    switch (pData->dwID) {
    case SIMCONNECT_RECV_ID_EVENT: {
        auto* e = (SIMCONNECT_RECV_EVENT*)pData;
        if (e->uEventID == EV_SIMSTART || e->uEventID == EV_FLUGGELADEN) {
            // Eine neue Welt. Alles Gesammelte gehört zur alten und wird verworfen.
            g_welt_da = true;
            g_sekunden = 0;
            g_spur_anzahl = 0;
            g_vor_gueltig = false;
            g_lage_gueltig = false;
            // Eine neue Welt. Die gesetzten Objekte ueberleben den Wechsel zwar (gemessen
            // 11.09.2026), gehoeren aber zur alten Lage des Piloten -- der Server schickt
            // beim naechsten Takt, was HIER stehen soll.
            alles_abraeumen();
            break;
        }
        if (e->uEventID == EV_SEKUNDE && g_welt_da) sekunde();
        break;
    }
    case SIMCONNECT_RECV_ID_SIMOBJECT_DATA: {
        auto* d = (SIMCONNECT_RECV_SIMOBJECT_DATA*)pData;
        if (d->dwRequestID == REQ_LAGE) {
            std::memcpy(&g_lage, &d->dwData, sizeof(Lage));
            g_lage_gueltig = true;
            break;
        }
        // Meldet eines der gesetzten Objekte? Festgehalten wird die SEKUNDE der letzten
        // Meldung -- der Abstand zu jetzt sagt, seit wann es schweigt, und das ist die
        // eigentliche Frage. Eine vergebene Objekt-ID ist nur die Bestaetigung, dass der
        // Auftrag angekommen ist, nicht dass dort etwas STEHT.
        if (d->dwRequestID >= REQ_OBJEKT && d->dwRequestID < REQ_OBJEKT + SOLL_MAX) {
            int i = (int)(d->dwRequestID - REQ_OBJEKT);
            if (g_soll[i].belegt) {
                Lage* ol = (Lage*)&d->dwData;
                g_soll[i].hoehe_ft = ol->alt_msl_ft;
                g_soll[i].letzte_meldung_s = g_sekunden;
            }
        }
        break;
    }

    case SIMCONNECT_RECV_ID_ASSIGNED_OBJECT_ID: {
        auto* z = (SIMCONNECT_RECV_ASSIGNED_OBJECT_ID*)pData;
        int i = (int)(z->dwRequestID - REQ_ERZEUGEN);
        if (i >= 0 && i < SOLL_MAX && g_soll[i].belegt) {
            g_soll[i].objekt_id = z->dwObjectID;
            g_soll[i].letzte_meldung_s = g_sekunden;
            g_soll[i].seit_s = g_sekunden;
            // Ab jetzt hinsehen: Lebt das Objekt noch, und auf welcher Hoehe steht es?
            // Die Hoehe ist der einzige Weg, auf dem der Server erfaehrt, ob die Stelle
            // taugt -- FriesenSpy hat kein Gelaendemodell.
            SimConnect_RequestDataOnSimObject(g_sim, REQ_OBJEKT + i, DEF_LAGE,
                                              z->dwObjectID, SIMCONNECT_PERIOD_SECOND);
        }
        break;
    }

    case SIMCONNECT_RECV_ID_EXCEPTION: {
        auto* ex = (SIMCONNECT_RECV_EXCEPTION*)pData;
        // Die Exception traegt die Anfrage-Nummer im SendID-Feld, das sich ohne
        // SimConnect_GetLastSentPacketID nicht zuordnen laesst. Statt zu raten, welches
        // Objekt gemeint ist, wird der letzte Erzeugungsversuch markiert -- er ist der
        // wahrscheinliche Verursacher, und der Server erfaehrt ueber `steht`, dass es
        // schiefging.
        for (int i = SOLL_MAX - 1; i >= 0; --i) {
            if (g_soll[i].belegt && g_soll[i].erzeugt_gerufen && g_soll[i].objekt_id == 0
                && !g_soll[i].fehler[0]) {
                std::snprintf(g_soll[i].fehler, sizeof(g_soll[i].fehler),
                              "EXCEPTION_%lu", (unsigned long)ex->dwException);
                break;
            }
        }
        break;
    }
    default:
        break;
    }
}

extern "C" MSFS_CALLBACK void module_init(void) {
    if (SimConnect_Open(&g_sim, "FriesenBruegge", nullptr, 0, 0, 0) != S_OK) return;

    kennung_laden_oder_erzeugen();

    // Die Datendefinition GENAU EINMAL. Und mit IDs, die sich mit nichts anderem im Modul
    // überschneiden: SIMCONNECT_DATA_DEFINITION_ID ist ein gemeinsamer Nummernraum mit den
    // ClientData-Definitionen, und eine Kollision dort endet mit UNRECOGNIZED_ID an einer
    // Stelle, die völlig unverdächtig aussieht (gemessen 11.09.2026).
    SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "PLANE LATITUDE", "degrees");
    SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "PLANE LONGITUDE", "degrees");
    SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "PLANE ALTITUDE", "feet");
    SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "PLANE ALT ABOVE GROUND", "feet");
    SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "GROUND VELOCITY", "knots");
    SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "PLANE HEADING DEGREES TRUE", "degrees");
    SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "SIM ON GROUND", "bool");
    SimConnect_AddToDataDefinition(g_sim, DEF_LAGE, "VERTICAL SPEED", "feet per minute");

    SimConnect_RequestDataOnSimObject(g_sim, REQ_LAGE, DEF_LAGE,
                                      SIMCONNECT_OBJECT_ID_USER, SIMCONNECT_PERIOD_SECOND);

    // "SimStart" feuert, sobald die Simulation läuft -- im Hauptmenü und während des Ladens
    // ist sie gestoppt. "FlightLoaded" feuert zusätzlich bei jedem Flugwechsel.
    SimConnect_SubscribeToSystemEvent(g_sim, EV_SEKUNDE, "1sec");
    SimConnect_SubscribeToSystemEvent(g_sim, EV_SIMSTART, "SimStart");
    SimConnect_SubscribeToSystemEvent(g_sim, EV_FLUGGELADEN, "FlightLoaded");

    SimConnect_CallDispatch(g_sim, dispatch, nullptr);
}

extern "C" MSFS_CALLBACK void module_deinit(void) {
    // Aufraeumen, bevor die Verbindung faellt. SimConnect raeumt die Objekte beim Close
    // ohnehin weg (gemessen: EXCEPTION 3 in der Nachprobe), aber sich darauf zu verlassen
    // hiesse, eine Zusicherung anzunehmen, die nirgends steht.
    alles_abraeumen();
    if (g_sim) {
        SimConnect_Close(g_sim);
        g_sim = 0;
    }
}
