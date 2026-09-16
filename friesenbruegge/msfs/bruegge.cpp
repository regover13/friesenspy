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
//   - `OnGround=1` WIRKT aus WASM heraus (12.09.2026 gemessen, MSFS 2024): Vier von fünf
//     Gattungen setzen sauber auf, auch wenn die angeforderte Höhe 200 ft zu hoch liegt.
//     Nur `fahrzeug` scheitert -- dort ist der Titel der Verdächtige, nicht das Flag.
//     ⚠ Am 11.09.2026 stand hier das Gegenteil, gestützt auf drei Messungen -- aber alle
//     drei mit `Boat01` und am selben Ort (Wangerooge: 49 ft bei 5,3 ft Boden). Ein Modell,
//     ein Platz, und daraus wurde eine allgemeine Regel. Für MSFS 2020 ist es weiterhin
//     ungemessen.
//   - Und der eigentliche Ertrag davon: Ein aufgesetztes Objekt meldet seine TATSÄCHLICHE
//     Höhe zurück -- also die Geländehöhe am ZIELORT. Damit taugt es als Sonde (`auf_boden`
//     im Protokoll), und die Höhenfrage braucht weder ein Geländemodell noch einen Überflug.
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
#include <cstdarg>
#include <cstring>
#include <cstdlib>

#include "../json.h"

// ---------------------------------------------------------------------------------------
// Die Lebensäußerung
// ---------------------------------------------------------------------------------------
//
// Bis zum 15.09.2026 stand hier NICHTS -- die Brügge war das einzige Modul im Simulator
// ohne eine einzige Zeile im Log. Im Log des Nutzers meldeten sich CampOut, GoFish und Flow
// jeweils beim Verbinden; die Brügge schwieg, auch wenn sie lief. Deshalb hat die Suche nach
// dem Grund für 88 stumme Minuten Stunden gedauert statt Sekunden: Es gab kein Merkmal, an
// dem sich „läuft, meldet aber nicht" von „gar nicht geladen" unterscheiden ließ.
//
// ⚠ `stderr`, NICHT `printf`: stdout ist gepuffert, und ein Modul, das beim Verbinden
// scheitert, kommt nie an die Stelle, die den Puffer leeren würde -- ausgerechnet die
// wichtigste Zeile ginge verloren. `stderr` ist nach C-Standard ungepuffert; das `fflush`
// steht trotzdem da, weil „ungepuffert" für die MSFS-Laufzeit nirgends zugesichert ist.
//
// Der Zeile wird vom Simulator ohnehin `[bruegge.wasm]` vorangestellt. Das eigene Präfix
// steht daneben, damit eine herausgegriffene Zeile auch ohne den Modulnamen zuzuordnen ist --
// dasselbe Muster wie `[GF][INFO]` bei GoFish.
static void log_zeile(const char* format, ...) {
    char zeile[256];
    va_list rest;
    va_start(rest, format);
    std::vsnprintf(zeile, sizeof(zeile), format, rest);
    va_end(rest);
    std::fprintf(stderr, "[FriesenBruegge] %s\n", zeile);
    std::fflush(stderr);
}

// ---------------------------------------------------------------------------------------
// Feste Größen
// ---------------------------------------------------------------------------------------

#define BRUEGGE_VERSION   "1.12.0"
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
// ⚠⚠ AUCH DIESER PUFFER HAENGT AN SOLL_MAX -- die Meldung traegt `steht` JE OBJEKT.
//
// Ein `steht`-Eintrag ist rund 70 Bytes:
//     {"id":"kolonie-norderney-12","zustand":"steht","hoehe_ft":1388.2}
//
//     SOLL_MAX   steht-Teil   + Lage/Spur (~1,5 kB)   noetiger Puffer
//         32        2,2 kB           3,7 kB               8192  (traegt 2,2x)
//        200       14,0 kB          15,5 kB              32768  (traegt 2,1x)
//
// Der Antwortpuffer war der offensichtliche (s. ANTWORT_PUFFER); dieser hier ist der
// stillere, weil ein Ueberlauf nicht die Antwort abschneidet, sondern die eigene Meldung --
// und die landet dann als kaputtes JSON beim Server.
#define MELDUNG_PUFFER 32768

// Und soviel die ANTWORT des Servers.
//
// ⚠⚠ DIESE ZAHL HAENGT AN SOLL_MAX, UND EIN UEBERLAUF IST LAUTLOS (s. anfrage_fertig).
// Gemessen am 12.09.2026: **126 Bytes je `soll`-Eintrag**. Daraus die Rechnung:
//
//     SOLL_MAX   soll-Teil   + `arten` (bis 2 kB)   noetiger Puffer
//         32        4,0 kB          6,0 kB              16384  (traegt 2,7x)
//        200       25,2 kB         27,2 kB              49152  (traegt 1,8x)
//
// Der fruehere Wert 4096 lief bei 32 Objekten ueber -- lautlos, die Bruegge behielt ihren
// alten Stand und meldete nur `antwort_zu_gross`. Wer SOLL_MAX hebt, MUSS hier mitgehen.
#define ANTWORT_PUFFER 49152

// Soviele Objekte haelt die Bruegge gleichzeitig.
//
// Am 14.09.2026 von 32 auf 200 gehoben (Nutzer: "wir brauchen viel mehr!!!"). Fuer eine
// Kieker-Station mit verteilten Kolonien sind 32 zu wenig -- schon ein Vorfeld voller Tiere
// erreicht die Grenze.
//
// ⚠ WAS DAS KOSTET, und beides ist UNGEMESSEN:
//   * Speicher: `g_soll[200]` plus zwei Puffer zu 48 kB. In WASM tragbar, aber nicht nichts.
//   * Leistung im Simulator: Gemessen sind DREISSIG gleichzeitige Objekte (12.09.2026,
//     MESSLISTE Abschnitt 5d). 200 sind das Sechsfache und im Flug noch nie probiert.
//
// Der Nummernraum traegt es: REQ_ERZEUGEN 1000..1200, REQ_OBJEKT 2000..2200 -- die
// Bereiche beruehren sich nicht. Bei SOLL_MAX > 1000 waere das anders, und eine Kollision
// endet mit UNRECOGNIZED_ID an voellig unverdaechtiger Stelle (11.09.2026 gemessen).
#define SOLL_MAX 200

enum {
    EV_SEKUNDE   = 1,
    EV_SIMSTART  = 2,
    EV_FLUGGELADEN = 3,
    DEF_LAGE     = 10,
    // ⚠ EIGENE DEFINITION, NICHT IN DEF_LAGE MIT HINEIN. Die Lage-Struktur besteht aus
    // lauter `double`; ein String daneben zwingt zu Ausrichtungsannahmen, die SimConnect
    // nirgends zusichert. Zwei Definitionen kosten nichts und koennen nicht verrutschen.
    DEF_FLUGZEUG = 11,
    REQ_LAGE     = 20,
    REQ_FLUGZEUG = 21,
    // Je gesetztem Objekt eine eigene Anfrage-Nummer -- so bleibt zuzuordnen, welches Objekt
    // meldet. Der Abstand zu den uebrigen IDs ist Absicht: SIMCONNECT_DATA_DEFINITION_ID ist
    // ein gemeinsamer Nummernraum, und eine Kollision endet mit UNRECOGNIZED_ID an einer
    // Stelle, die voellig unverdaechtig aussieht (11.09.2026 gemessen).
    REQ_ERZEUGEN = 1000,      // 1000 .. 1000+SOLL_MAX
    REQ_OBJEKT   = 2000,      // 2000 .. 2000+SOLL_MAX

    // ⭐ EIN OBJEKT IN DER LUFT FESTHALTEN (1.12.0, 16.09.2026)
    //
    // `AICreateSimulatedObject` erzeugt ein SIMULIERTES Objekt -- auf ein Flugzeug wirkt
    // damit die Physik. Am 16.09.2026 gemessen: ein `HotAirBalloon Passengers`, auf 3000 ft
    // gesetzt, lag nach 15 s auf Gelaendehoehe; ein `Skyship600 Passenger` sank mit 780
    // ft/min und lag nach 115 s. Ein WINDRAD an derselben Stelle stand auf exakt 3000,0 ft
    // -- statische SimObjects haben keine Physik, Flugzeuge schon.
    //
    // Die drei Freeze-Ereignisse halten es fest. Dass sie auf ein Objekt aus
    // `AICreateSimulatedObject` ueberhaupt wirken, steht in keiner Doku und ist deshalb
    // VORHER extern gemessen worden (`probe-msfs/freeze_probe.py`, A/B mit zwei Ballons
    // nebeneinander): eingefroren 2999,7 ft ueber 20 s, frei nach 11 s am Boden. Erst
    // danach ist diese Zeile entstanden -- ein Fehlversuch haette hier einen Build und eine
    // Verteilung an 61 Piloten gekostet.
    //
    // ⚠⚠ ABER: EXTERN GEMESSEN IST NICHT AUS WASM GEMESSEN. Genau diese Luecke gibt es auf
    // dieser Codebasis schon einmal, zwanzig Zeilen weiter unten nachzulesen: `OnGround=1`
    // wirkt extern zuverlaessig und aus WASM heraus NICHT (11.09.2026). Die externe Messung
    // beweist hier also nur, dass der Simulator die Ereignisse auf ein solches Objekt
    // anwendet -- nicht, dass ein WASM-Modul sie senden darf. Solange das nicht im Flug mit
    // DIESEM Modul belegt ist, ist 1.12.0 ein Versuch und keine Zusage.
    EV_FREEZE_ALT  = 30,
    EV_FREEZE_LAGE = 31,
    EV_FREEZE_ORT  = 32,
};

// Ein Objekt, das dastehen soll -- und wie es ihm ergangen ist.
struct SollObjekt {
    char   id[40];
    char   art[24];
    double lat, lon, kurs, erwartete_hoehe_ft;
    bool   hat_hoehe;
    bool   auf_boden;         // OnGround=1 verlangt -- s. objekt_erzeugen

    bool   belegt;            // Platz in Benutzung
    bool   in_soll;           // steht in der aktuellen Antwort des Servers
    bool   erzeugt_gerufen;   // AICreateSimulatedObject ist raus
    DWORD  objekt_id;         // vom Simulator vergeben, 0 = noch keine
    DWORD  sende_id;          // Paketnummer des Erzeugungsaufrufs -- ordnet Exceptions zu
    int    titel_nr;          // welcher Titel der Art gerade versucht wird (s. titel_fuer)
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
// Der Titel des eigenen Flugzeugs -- das, was `AICreateSimulatedObject` annaehme.
//
// ⭐ WOZU: Die Standardflugzeuge von MSFS 2024 sind GESTREAMT. Ihre Pakete liegen als
// 256-kB-Platzhalter auf der Platte (`.fsarchive`), es gibt im ganzen Bestand KEINE einzige
// `aircraft.cfg`, und auch vPilots Modellscan findet nur Community-Pakete (gemessen
// 14.09.2026: 3823 Titel, davon 0 aus Official). Der Titel existiert nur im laufenden
// Simulator.
//
// Hier IST der laufende Simulator. Wer fliegt, meldet seinen Titel mit, und der Katalog
// fuellt sich aus den Simulatoren der Gruppe statt von einer Platte. Das ist zugleich die
// einzige Quelle, die ZUVERLAESSIG sagt, was ein anderer tatsaechlich hat -- dreimal an
// einem Tag wurde ein Objekt gesetzt, das nur auf einem Rechner existierte.
static char    g_flugzeug[256] = {0};
// ⚠⚠ EINMAL SENDEN GENUEGT NICHT -- das war ein Wettlauf, den ich selbst gebaut habe.
//
// Hier stand ein `bool`: Titel gelesen, einmal gesendet, fertig. Gemessen am 14.09.2026:
//
//     TITLE-Callback 331 mal, davon 0 leer, Titel=''
//
// Der Callback lieferte also sauber -- aber die EINE Meldung mit dem Titel ging hinaus,
// BEVOR der Server eine Zuordnung hatte. Ohne CID verwirft er alles, auch den Titel, und
// die Bruegge schickte ihn nie wieder.
//
// Die Zuordnung braucht ihre Zeit: Sie entsteht ueber das Positionsmatching, und dafuer muss
// der Pilot erst in `live_positions` stehen (VATSIM-Latenz bis 29 s). Der Titel steht schon
// in der ersten Sekunde fest. Die beiden treffen sich nur, wenn er WIEDERHOLT mitgeht.
//
// Deshalb ein Zaehler statt eines Schalters: Der Titel geht die ersten `FLUGZEUG_MELDUNGEN`
// Meldungen lang mit. Bei Sekundentakt sind das gut zwei Minuten -- laenger, als jede
// Zuordnung braucht, und danach kostet es nichts mehr. Ein Flugwechsel setzt ihn zurueck
// (s. den Callback).
#define FLUGZEUG_MELDUNGEN 150
static int     g_flugzeug_offen = 0;          // solange > 0, geht der Titel mit
// ⚠ NUR ZUR DIAGNOSE, und sie war noetig: Am 14.09.2026 kam der Titel nicht an, und aus der
// Ferne war nicht zu unterscheiden, ob der Callback gar nicht feuert oder ob er feuert und
// nichts liefert. Das sind zwei voellig verschiedene Fehler -- der eine sitzt in der
// Datendefinition, der andere im Lesen der Rohdaten.
static int     g_flugzeug_rufe = 0;           // wie oft der Callback kam
static int     g_flugzeug_leer = 0;           // ... und davon mit leerem Titel
static double  g_vor_lat = 0.0, g_vor_lon = 0.0;
static bool    g_vor_gueltig = false;

static SpurPunkt g_spur[SPUR_MAX];
static int       g_spur_anzahl = 0;

static char    g_kennung[40] = {0};
// Steht die Kennung endgueltig fest? Erst dann wird sie geschrieben -- vorher wuerde das
// Schreiben das eigene, asynchrone Lesen ueberholen (s. kennung_laden_oder_erzeugen).
static bool    g_kennung_fest = false;
static int     g_takt_s = 1;              // was der Server zuletzt vorgegeben hat
// Hat der Server die Protokollfassung abgelehnt (426)? Dann ist der Vertrag tot, und das
// bleibt er -- auch über einen Flugwechsel hinweg. Jede andere Drosselung darf eine neue
// Welt dagegen hinter sich lassen, s. den Weltwechsel in `dispatch`.
static bool    g_vertrag_tot = false;
// Der zuletzt GEMELDETE Ablehnungsgrund -- 0 heißt „der Server nimmt an". Er dient allein
// dem Log: Ohne ihn stünde jede Sekunde dieselbe Zeile darin.
static int     g_letzter_status = 0;
static DWORD   g_seit_meldung = 0;
static FsNetworkRequestId g_laufend = 0;  // 0 = keine Anfrage offen
static DWORD   g_gilt_bis_s = 300;        // wie lange `soll` ohne neue Auskunft gilt

// ⚠ HIER STAND EINE ERNEUERUNG FUER RAUCHOBJEKTE -- SIE WAR UEBERFLUESSIG.
//
// Die Annahme war: Unsere Rauchobjekte tragen ein `TimeEmission` von 60 s, also hoert der
// Emitter nach einer Minute auf, und ein Objekt, das laenger stehen soll, muesste
// regelmaessig neu gesetzt werden. Gebaut, eingebaut, Fassung erhoeht.
//
// GEMESSEN IST ES ANDERS (13.09.2026, im Sim): Eine Saeule stand DURCHGEHEND, weit laenger
// als eine Minute, und verschwand erst 60 s NACHDEM das Objekt geloescht wurde.
//
// Der Grund steht in der SDK-Doku, nur eine Ebene weiter, als ich gelesen hatte: Ein
// Effekt wird gespawnt, sobald FX_CODE WAHR WIRD. Unsere Bedingung ist dauerhaft wahr --
// laeuft ein Emitter aus, startet der Simulator ihn also einfach wieder. Erst wenn das
// Traegerobjekt weg ist, faellt dieser Neustart aus, und der zuletzt gestartete Emitter
// laeuft seine 60 s zu Ende.
//
// Damit macht `TimeEmission` von allein genau das Richtige: Solange das Objekt steht,
// brennt die Saeule; ist es abgeraeumt, ist nach spaetestens einer Minute Ruhe. Eine
// Erneuerung haette nur Last erzeugt und beim Neusetzen Flackern riskiert.
//
// Stehen geblieben ist aus 1.7.0 das, was sich bewaehrt hat: die eigenen FrsRauch-Titel.
static DWORD   g_letzte_antwort_s = 0;    // Sekunde der letzten angekommenen Antwort
static DWORD   g_laufend_seit = 0;        // Sekunden -- gegen haengende Anfragen
// Groesse einer Antwort, die nicht in ANTWORT_PUFFER passte. 0 = alles in Ordnung. Geht als
// `antwort_zu_gross` mit der naechsten Meldung hinaus, damit der Server ERFAEHRT, warum
// Objekte fehlen, statt es zu raten -- und die Zahl sagt ihm zugleich, wie weit er kuerzen
// muss.
static unsigned long g_antwort_zu_gross = 0;

// ---------------------------------------------------------------------------------------
// DIE LETZTE ANTWORT -- sie traegt seit Protokollfassung 2 die Titel (14.09.2026)
// ---------------------------------------------------------------------------------------
//
// Sie wird aufgehoben, weil der NACHRUECK-FALL sie spaeter noch braucht: Scheitert ein Titel,
// kommt die Exception erst Bilder danach an, lange nachdem `soll_abgleichen` durchgelaufen
// ist. Ohne die aufgehobene Antwort wuesste die Bruegge dann nicht mehr, welcher Titel als
// naechster dran waere.
//
// Die Kopie gab es ohnehin (sie stand als `static` im Callback) -- sie wird hier nur
// sichtbar gemacht. Kein zusaetzlicher Speicher.
//
// ⚠ Sie ist IMMER die zuletzt empfangene, nicht die, unter der ein Objekt entstanden ist.
// Das ist Absicht: Aendert der Server die Titelliste einer Art, gilt sofort die neue. Der
// Server ist die Wahrheit, nicht das Gedaechtnis der Bruegge.
static char    g_antwort[ANTWORT_PUFFER] = {0};

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
// ⚠⚠ HIER ERFAND DIE BRUEGGE IHRE KENNUNG SELBST -- UND ERFAND AUF JEDEM RECHNER DIESELBE.
//
//     unsigned long long a = (unsigned long long)(size_t)&g_sim;   // Adresse
//     unsigned long long b = (unsigned long long)std::rand();      // ohne srand()
//     unsigned long long c = (unsigned long long)(g_sekunden + 1) * 2654435761u;
//
// In einem WASM-Modul ist der Speicher linear und bei jedem Start identisch, `&g_sim` also
// ueberall dieselbe Zahl; `std::rand()` ohne `srand()` liefert ueberall dieselbe Folge; und
// `g_sekunden` ist beim Erzeugen null. JEDE Installation erzeugte `9e3711c100000000`.
//
// AM 14.09.2026 LIVE VORGEFUEHRT, zwei Piloten auf Wangerooge, 130 m auseinander:
//
//     Zuordnung  9e3711c100000000 -> 1642160 (FRS123)
//     gemeldet   53.787559/7.909491   <- das ist FRS49s Position
//     Verstoesse 0
//
// FRS123 stand auf der Karte exakt auf FRS49. Wer zuletzt meldete, bekam die Kennung -- und
// damit die Objekte, die fuer den anderen gesetzt waren.
//
// JETZT VERGIBT SIE DER SERVER, und die Bruegge erfindet gar nichts mehr.
//
// Der Weg ist derselbe wie im Kniebrett (`getOrCreateDeviceId`): einmal beschaffen, dauerhaft
// speichern, bei JEDER Meldung mitliefern. Nur die Quelle ist eine andere -- dort
// `crypto.getRandomValues` im Browser, hier `secrets.token_hex` auf dem Server. Und das ist
// nicht der zweitbeste Weg, sondern der bessere: Der Server SIEHT alle Kennungen.
// Eindeutigkeit ist fuer ihn eine Zusicherung, fuer jeden Client nur eine
// Wahrscheinlichkeit.
//
//   1. Erste Meldung ueberhaupt: ohne Kennung. Der Server matcht ueber die Position -- der
//      Pilot steht dabei, und im Stand ist die VATSIM-Latenz gegenstandslos (Zuordnungs-Spec
//      vom 16.08.2026). Die Zuordnung gelingt auf Meter.
//   2. Er antwortet mit `"kennung": "..."`.
//   3. Die Bruegge speichert sie und liefert sie ab jetzt bei jeder Meldung mit.
//   4. Nach einem Simulator-Neustart liest sie die Datei -- dieselbe Kennung, dieselbe
//      Zuordnung.
//
// Bis Schritt 2 meldet sie mit LEERER Kennung. Das ist kein Notbehelf: Der Server matcht
// dann voll, was er ohnehin kann, und genau das stand seit jeher im Kommentar unten.

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

#ifdef KENNUNG_HAELT
// ⚠⚠ GESCHLOSSEN WIRD ERST IM CALLBACK -- SONST BLEIBT DIE DATEI LEER.
//
// `fsIOWrite` ist ASYNCHRON (es nimmt einen `FsIOFileWriteCallback`, s. MSFS_IO.h Zeile 62).
// Hier stand `fsIOWrite(...); fsIOClose(w);` unmittelbar hintereinander -- das Schliessen
// ueberholte das Schreiben, und zurueck blieb eine Datei mit NULL BYTES.
//
// Am 14.09.2026 gemessen, nachdem die Kennung bei jedem Simulator-Start eine andere war:
//
//     -rw-r--r-- 1 Tobias 0  17:12:09  friesenbruegge.kennung
//
// Damit war der ganze Zweck der Speicherung dahin: Die Bruegge meldete bei jedem Start ohne
// Kennung, bekam eine neue vom Server, und in `bruegge_zuordnung` sammelten sich Karteileichen.
//
// Es ist DIESELBE Falle, die weiter unten schon einmal beschrieben ist (das Schreiben
// ueberholte dort das asynchrone LESEN). Ich hatte sie gelesen, verstanden -- und beim
// Schreiben nicht wiedererkannt.
static void kennung_geschrieben(FsIOFile datei, const char*, int, int, void*) {
    fsIOClose(datei);
}

// ⚠⚠ UND AUCH DAS OEFFNEN IST ASYNCHRON -- die ganze Kette, nicht nur das Schreiben.
//
// Der erste Anlauf legte das Schliessen in den Write-Callback und schrieb weiter direkt
// nach `fsIOOpen`. Die Datei blieb LEER (14.09.2026, 17:35:10, null Bytes) -- denn
// `fsIOOpen` nimmt ebenfalls einen Callback (`FsIOFileOpenCallback`, MSFS_IO.h Zeile 59),
// und der Rueckgabewert ist erst danach benutzbar.
//
// Richtig ist die vollstaendige Kette: oeffnen -> im Callback schreiben -> im naechsten
// Callback schliessen. Jede Abkuerzung darin kostet den Inhalt, und zwar lautlos: Die
// Datei entsteht, sie ist nur leer.
static void kennung_datei_offen(FsIOFile datei, void*) {
    if (datei == FS_IO_ERROR_FILE || g_kennung[0] == '\0') return;
    fsIOWrite(datei, g_kennung, 0, (int)std::strlen(g_kennung),
              kennung_geschrieben, nullptr);
}
#endif

static void kennung_schreiben() {
#ifdef KENNUNG_HAELT
    // `g_kennung` ist global und bleibt gueltig, bis die Callbacks kommen -- ein Puffer auf
    // dem Stapel waere hier ein Fehler.
    fsIOOpen(KENNUNG_DATEI,
             FsIOOpenFlag_WRONLY | FsIOOpenFlag_CREAT | FsIOOpenFlag_TRUNC,
             kennung_datei_offen, nullptr);
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
    // Erzeugt wird hier nichts mehr (s. oben). Bleibt `g_kennung` leer, meldet die Bruegge
    // ohne -- und bekommt vom Server eine zugeteilt.

    // ⚠ HIER STAND `kennung_schreiben()`, UND DAS WAR EIN WETTLAUF MIT DEM EIGENEN LESEN.
    //
    // Das Lesen oben laeuft asynchron, das Schreiben lief sofort -- und `FsIOOpenFlag_TRUNC`
    // leert die Datei. Wenn der Lese-Callback eintraf, war die gespeicherte Kennung laengst
    // ueberschrieben. Folge: Die Bruegge zog bei JEDEM Simulator-Start eine neue, obwohl sie
    // ausdruecklich dafuer gebaut ist, dieselbe zu behalten.
    //
    // Gemessen am 12.09.2026: drei Starts, drei Kennungen (9e371e61…, 9e3713f1…,
    // 9e3713d1…) -- und im Server drei Saetze `bruegge_steht`-Zeilen fuer dieselben Objekte,
    // weil dort (kennung, id) der Schluessel ist.
    //
    // Jetzt wird erst geschrieben, wenn feststeht, dass nichts Altes mehr kommt: entweder
    // sofort nach einem fehlgeschlagenen Lesen, oder nach KENNUNG_WARTE_S Sekunden
    // (s. `kennung_pruefen`). Das kostet nichts -- die Kennung geht ohnehin bei jeder
    // Meldung mit hinaus, sie muss nur nicht auf der Platte stehen.
}

// Sekunden seit Modulstart, nach denen eine erzeugte Kennung endgueltig gilt und geschrieben
// wird. Drei Sekunden sind reichlich fuer ein Dateilesen aus dem WASM-Sandkasten und immer
// noch weit vor der ersten Meldung, die auf `g_welt_da` wartet.
#define KENNUNG_WARTE_S 3

// Ist die Kennung aus der Datei inzwischen eingetroffen? Dann gilt sie -- sie ist die
// aeltere und damit die, die der Server schon kennt.
static void kennung_pruefen() {
#ifdef KENNUNG_HAELT
    // Ist die gespeicherte Kennung nach KENNUNG_WARTE_S nicht da, kommt sie nicht mehr --
    // dann gilt die erzeugte und wird jetzt (und nur jetzt) auf die Platte geschrieben.
    // Vorher zu schreiben hiesse, das eigene Lesen zu ueberholen (s. kennung_laden_oder_erzeugen).
    // Nach KENNUNG_WARTE_S ist klar, dass keine gespeicherte mehr kommt. Frueher wurde hier
    // die erfundene festgeschrieben; jetzt gibt es keine, und die Bruegge meldet so lange
    // ohne, bis der Server eine zuteilt (s. `kennung_uebernehmen`).
    if (!g_kennung_fest && g_sekunden >= KENNUNG_WARTE_S && g_kennung_gelesen[0] == '\0') {
        g_kennung_fest = true;
        if (g_kennung[0] != '\0') kennung_schreiben();
        return;
    }
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
        if (hex) {
            std::snprintf(g_kennung, sizeof(g_kennung), "%s", g_kennung_gelesen);
            // Sie steht ja schon in der Datei -- erneut zu schreiben waere sinnlos und
            // braechte nur die Gelegenheit, sie dabei zu zerstoeren.
            g_kennung_fest = true;
        }
    }
    g_kennung_gelesen[0] = '\0';
#endif
}

// ---------------------------------------------------------------------------------------
// Art -> Titel: DIE ZUORDNUNG KOMMT VOM SERVER (Protokollfassung 2, 14.09.2026)
// ---------------------------------------------------------------------------------------
//
// ⚠ HIER STAND `g_gattungen[]` -- 25 Arten, 71 Titel, rund 180 Zeilen. Entfernt, und das ist
// der Kern dieses Releases.
//
// Warum sie weg musste, steht in PROTOKOLL.md Zeile eins:
//
//     Die Bruegge ist dumm. Alle Klugheit bleibt auf dem Server.
//
// Eine Tabelle im Client widerspricht dem doppelt:
//
//   1. SIE KOSTET EIN RELEASE. Eine neue Art brauchte einen Windows-Build und eine
//      Verteilung an 61 Piloten. Zweimal bezahlt am 13.09.2026: FRS61s aeltere Bruegge
//      kannte `robbe` und `tier_wild` nicht und meldete GATTUNG_UNBEKANNT.
//   2. SIE HAT KEIN GEDAECHTNIS. Drei ihrer Titel -- `PolarBear`, `Bear_U_Maritimus`,
//      `deer_o_hemionus` -- scheitern seit dem 12.09.2026 nachweislich mit EXCEPTION_22.
//      Die Bruegge probierte sie bei jedem Fehlversuch durch. Der Server weiss es besser:
//      Sein Katalog fuehrt 2935 Titel, davon 1693 EINZELN im laufenden Simulator gesetzt.
//      Er kannte sogar einen Baeren, den diese Tabelle nicht kannte (`SyrianBear`).
//
// Was hier stand, ist nicht verloren -- es steht jetzt in `bruegge_katalog` auf dem Server,
// mit Pruefergebnis je Titel. Die Fundgeschichten (warum `ASO_Ambulance_Japan` in MSFS 2024
// fehlt, warum die Reihenfolge Absicht ist) stehen in `app/bruegge_arten.py` und OBJEKTE.md.
//
// Geblieben ist genau das Verhalten, das sich bewaehrt hat: mehrere Titel je Art, der Reihe
// nach probiert. Nur die Liste kommt jetzt von woanders.

// Den n-ten Titel einer Art -- aus der letzten Antwort des Servers. Gibt nullptr, wenn die
// Art unbekannt ist ODER die Liste erschoepft; der Aufrufer unterscheidet beides ueber
// `art_bekannt`.
static const char* titel_fuer(const char* art, int n) {
    static char puffer[128];   // X-Plane-Pfade sind lang; MSFS-Titel kurz
    if (!json_titel_fuer(g_antwort, art, n, puffer, sizeof(puffer))) return nullptr;
    return puffer;
}

// Kennt der Server diese Art ueberhaupt? Eine LEERE Titelliste zaehlt als bekannt -- das ist
// ein anderer Befund (der Server kennt die Art, hat aber fuer diesen Simulator nichts) als
// eine Art, die er gar nicht fuehrt.
static bool art_bekannt(const char* art) {
    return json_art_bekannt(g_antwort, art);
}


// ---------------------------------------------------------------------------------------
// Die Meldung bauen
// ---------------------------------------------------------------------------------------

static void meldung_bauen(char* puffer, size_t groesse) {
    JsonSchreiber j(puffer, groesse);
    j.roh("{");
    j.feld("protokoll");       j.ganzzahl(2);                 j.komma();
    j.feld("simulator");       j.text(SIMULATOR_NAME);        j.komma();
    j.feld("bruegge_version"); j.text(BRUEGGE_VERSION);       j.komma();

    // Nur wenn die letzte Antwort nicht in den Puffer passte -- sonst faellt das Feld weg.
    // Es steht hier und nicht in `steht`, weil es NICHT von einem einzelnen Objekt handelt,
    // sondern von der Antwort als ganzer: Die Bruegge hat den Sollzustand gar nicht erfahren.
    // Der Wert ist die tatsaechliche Groesse, damit der Server weiss, wie weit er kuerzen
    // muss, statt blind zu halbieren.
    if (g_antwort_zu_gross > 0) {
        j.feld("antwort_zu_gross"); j.ganzzahl((long)g_antwort_zu_gross); j.komma();
    }
    j.feld("kennung");         j.text(g_kennung);             j.komma();

    // ⭐ DER TITEL DES EIGENEN FLUGZEUGS -- einmal je Titel, nicht bei jeder Meldung.
    //
    // Er ist das, was `AICreateSimulatedObject` annaehme, und damit unmittelbar
    // verwertbar. Der Server traegt ihn in `bruegge_katalog` ein; so lernt der Bestand aus
    // jedem Flug, statt dass jemand Titel von einer Platte liest -- die gestreamten
    // Standardflugzeuge stehen dort naemlich gar nicht.
    //
    // Bei JEDER Meldung mitzuschicken waere Verschwendung: Ein Titel ist bis zu 256 Zeichen
    // lang, und er aendert sich nur beim Flugwechsel.
    if (g_flugzeug_offen > 0 && g_flugzeug[0] != '\0') {
        j.feld("flugzeug");    j.text(g_flugzeug);            j.komma();
        --g_flugzeug_offen;
    }
    // Die Diagnose dazu: 0 Rufe heisst, die Datendefinition greift gar nicht. Rufe ohne
    // Inhalt heissen, sie greift -- aber der Titel steht nicht dort, wo ich ihn lese.
    // Zwei Zahlen je Meldung, die den Unterschied sichtbar machen.
    j.feld("fz_rufe");  j.ganzzahl((long)g_flugzeug_rufe);  j.komma();
    j.feld("fz_leer");  j.ganzzahl((long)g_flugzeug_leer);  j.komma();

    // ⚠ HIER STAND `kann` -- entfernt mit Protokollfassung 2 (14.09.2026).
    //
    // Es zaehlte auf, welche Arten die Bruegge beherrscht, und wurde aus `g_gattungen[]`
    // erzeugt. Ohne diese Tabelle KANN SIE NICHTS MEHR BEHAUPTEN -- und das ist der Punkt:
    // Der Server schickt fuer den gemeldeten Simulator, was er hat, und erfaehrt aus `steht`,
    // was tatsaechlich stand. Belegt statt behauptet.
    //
    // Es kostet nichts: Ausgewertet hat der Server `kann` ohnehin nie. Und es beendet eine
    // Luege, die schon einmal auffiel -- bei Fassung 1.4.0 meldete das Modul, es koenne
    // `robbe` nicht, waehrend es sie setzen konnte.

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
    if (!art_bekannt(o.art)) {
        // Der Server hat zu dieser Art keine Titel mitgeschickt: nicht raten. Er erfaehrt es
        // ueber `steht` und kann etwas anderes anfordern -- oder die Stelle auslassen.
        //
        // Seit Protokollfassung 2 heisst das etwas anderes als vorher: Frueher hiess es "die
        // Bruegge kennt die Art nicht" (ein Fall fuer ein Client-Release), jetzt "der Server
        // hat sie nicht mitgeliefert" (ein Fall fuer den Admin). Der FEHLERCODE bleibt
        // trotzdem wortgleich -- ein aelterer Server soll ihn wiedererkennen.
        std::snprintf(o.fehler, sizeof(o.fehler), "GATTUNG_UNBEKANNT");
        o.erzeugt_gerufen = true;
        return;
    }
    const char* titel = titel_fuer(o.art, o.titel_nr);
    if (!titel) {
        // Die Art gibt es, aber KEIN Titel daraus liess sich setzen. Das ist ein anderer
        // Befund als eine unbekannte Art, und der Server soll ihn unterscheiden koennen:
        // hier fehlen die Modelle beim Piloten, dort war die Anforderung falsch.
        //
        // Der Server kann daraus lernen -- die Titel stehen in seinem Katalog, und er darf
        // sie auf `aus` setzen, statt sie weiter auszuliefern.
        std::snprintf(o.fehler, sizeof(o.fehler), "KEIN_TITEL_GING");
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
    pos.Airspeed  = 0;

    // OnGround: normalerweise 0, weil das Flag aus WASM heraus nicht aufsetzt (11.09.2026
    // ausgemessen: Altitude kommt unveraendert an, nur das Flag wird ignoriert -- extern
    // wirkt dasselbe Flag zuverlaessig).
    //
    // GEMESSEN WURDE DAS ABER NUR MIT `Boat01`, und ein Boot will womoeglich auf WASSER
    // aufsetzen. Ob ein Tier, ein Bauwerk oder ein Fahrzeug sich anders verhaelt, ist offen.
    // Deshalb kann der Server es je Objekt verlangen (`auf_boden` im Protokoll) -- fuer genau
    // eine Frage, die den Kieker traegt:
    //
    //   Setzt IRGENDEINE Gattung in WASM auf, so meldet sie danach ihre TATSAECHLICHE Hoehe
    //   zurueck -- und das ist die Gelaendehoehe am ZIELORT, ohne Hoehenmodell und ohne dass
    //   jemand hinfliegen muesste. Damit stuende eine Sonde zur Verfuegung: hinstellen,
    //   Hoehe ablesen, das eigentliche Objekt mit `erwartete_hoehe_ft` setzen.
    //
    // Dass die Rueckmeldung die tatsaechliche Lage traegt und nicht die angeforderte, ist
    // belegt: Mit OnGround=1 kam 49,0 ft zurueck, obwohl 0 bzw. 500 gesetzt waren.
    //
    // Die Idee stammt vom Nutzer (12.09.2026). Sie kostet hier drei Zeilen und beantwortet
    // eine Frage, an der sonst die ganze Hoehenrechnerei haengt.
    pos.OnGround  = o.auf_boden ? 1 : 0;

    HRESULT hr = SimConnect_AICreateSimulatedObject(g_sim, titel, pos, REQ_ERZEUGEN + i);

    // Die Paketnummer DIESES Aufrufs merken. Kommt spaeter eine Exception, nennt sie in
    // `dwSendID` genau diesen Wert -- damit ist zuzuordnen, WELCHES Objekt gescheitert ist,
    // statt es am letzten unbestaetigten Versuch zu raten (s. SIMCONNECT_RECV_ID_EXCEPTION).
    DWORD sende = 0;
    if (SimConnect_GetLastSentPacketID(g_sim, &sende) == S_OK) o.sende_id = sende;
    else                                                       o.sende_id = 0;

    o.erzeugt_gerufen = true;
    o.seit_s = g_sekunden;
    if (hr != S_OK) {
        std::snprintf(o.fehler, sizeof(o.fehler), "CREATE_HR_%08lX", (unsigned long)hr);
    }
}

// Ein Objekt in der Luft festhalten -- s. EV_FREEZE_ALT fuer die Messung dahinter.
//
// ⚠ NUR wenn es auch in der Luft steht (`!auf_boden` UND eine Hoehe dabei). Am Boden ist
// nichts festzuhalten, und ein Freeze dort wuerde nur verdecken, dass `OnGround` seine
// Arbeit tut. Die Regel stammt vom Nutzer (16.09.2026): *"einfrieren immer, wenn ein Objekt
// mit auf_boden=false und einer Hoehe gesetzt wird"*.
//
// ⚠ ALLE DREI, nicht nur die Hoehe. Ohne ATTITUDE kippt das Objekt, ohne
// LATITUDE_LONGITUDE treibt es im Wind ab -- beides sieht beim Hinsehen aus wie ein
// halber Erfolg und ist keiner.
//
// Der Server erfaehrt davon nichts und muss es auch nicht: Dass ein Flugzeugmodell in MSFS
// faellt und ein statisches Objekt nicht, ist Simulator-Wissen. Die Bruegge bleibt dumm,
// aber ihre eigenen Eigenheiten kennt sie selbst -- ein Protokollfeld dafuer waere eine
// Fassung mehr fuer etwas, das X-Plane gar nicht hat (dort ist ein Ballon ein statisches
// `.obj` und bleibt von allein haengen).
static void objekt_festhalten(int i) {
    SollObjekt& o = g_soll[i];
    if (o.auf_boden || !o.hat_hoehe || o.objekt_id == 0) return;
    static const DWORD ereignisse[] = { EV_FREEZE_ALT, EV_FREEZE_LAGE, EV_FREEZE_ORT };
    for (DWORD ev : ereignisse) {
        // `1` heisst einfrieren. Die `_SET`-Fassungen nehmen den Zustand als Wert -- die
        // `_TOGGLE`-Geschwister waeren nicht wiederholbar, und wiederholt wird hier: Ein
        // Objekt, das der Server verschiebt, entsteht neu und muss neu festgehalten werden.
        SimConnect_TransmitClientEvent(g_sim, o.objekt_id, ev, 1,
                                       SIMCONNECT_GROUP_PRIORITY_HIGHEST,
                                       SIMCONNECT_EVENT_FLAG_GROUPID_IS_PRIORITY);
    }
}

static void objekt_entfernen(int i) {
    SollObjekt& o = g_soll[i];

    // SimConnect_AIRemoveObject -- und der Aufruf ist eine VORAUSSETZUNG, keine Annehmlichkeit.
    //
    // Gemessen am 12.09.2026 mit `kieker_probe.py --boote-zaehlen`: Ein Boot angefordert (1
    // Boot, Objekt 149372931), aus `soll` genommen -- die Bruegge vergisst es, das Objekt
    // BLEIBT stehen --, dieselbe id erneut angefordert: **2 Boote**, 149372931 und 148946946,
    // an derselben Koordinate und in derselben Hoehe.
    //
    // Gezaehlt und nicht hingeschaut, und das war noetig: Derselbe Vorgang lief zuvor mit
    // einem Baeren, und der Blick aus dem Cockpit meldete EINEN. Zwei gleiche Modelle an
    // derselben Stelle sind nicht zu unterscheiden. Dieselbe Lehre wie am 11.09. beim
    // Boat01 -- der Simulator weiss es besser als das Auge.
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
            std::memset(&o, 0, sizeof(o));   // setzt auch titel_nr auf 0
            std::snprintf(o.id, sizeof(o.id), "%s", id);
            o.belegt = true;
            o.seit_s = g_sekunden;
        }
        // Die neuen Werte erst NEBEN die alten legen, nicht darueber -- sonst laesst sich
        // nicht mehr feststellen, ob sich etwas geaendert hat.
        char   n_art[24] = {0};
        json_text_in(e, "art", n_art, sizeof(n_art));
        double n_lat  = json_zahl_in(e, "lat", o.lat);
        double n_lon  = json_zahl_in(e, "lon", o.lon);
        double n_kurs = json_zahl_in(e, "kurs", 0.0);
        bool   hat = false;
        double n_hoehe = json_zahl_in(e, "erwartete_hoehe_ft", 0.0, &hat);
        // `auf_boden` traegt der Server als Zahl (0/1) -- json.h kennt keine Wahrheitswerte,
        // und eine zweite Lesefunktion nur hierfuer waere Aufwand ohne Ertrag.
        bool n_auf_boden = (json_zahl_in(e, "auf_boden", 0.0) > 0.5);

        // UMSETZEN: Aendert der Server Ort, Ausrichtung oder Gattung eines Objekts, das schon
        // dasteht, muss es weg und neu hin. Ein bereits erzeugtes Objekt laesst sich nicht
        // nachtraeglich verschieben -- `AICreateSimulatedObject` legt es an, danach steht es.
        //
        // Ohne diese Pruefung passierte GAR NICHTS: `erzeugt_gerufen` war true, also lief der
        // Erzeugungspfad nicht mehr, und die neue Koordinate wurde nur gemerkt. Der Server
        // sah `zustand: steht` und hielt das Objekt fuer umgesetzt -- es stand aber am alten
        // Ort. Gemessen am 12.09.2026: Ein Baer wurde um 5 m versetzt angefordert und ruehrte
        // sich nicht (`seit_s` lief unveraendert auf 1725 weiter, statt bei null neu zu
        // beginnen).
        //
        // Fuer den FriesenKieker waere das ein stiller Fehler der schlimmsten Sorte: Eine
        // verschobene Station meldet "steht", und alles sieht richtig aus. Nur ist sie
        // woanders.
        //
        // Die Schranke ist bewusst grob (rund 1 m in der Breite, 1 Grad im Kurs): Sie soll
        // eine ABSICHT des Servers erkennen, nicht Rundungsrauschen im JSON -- sonst wird ein
        // Objekt bei jeder Meldung neu gesetzt, und das ist genau das Flackern, das die
        // Sollzustands-Idee vermeiden soll.
        const double GRAD_1M = 0.000009;   // 1 m in Breitengrad
        bool versetzt = o.erzeugt_gerufen && (
            (o.lat - n_lat >  GRAD_1M) || (n_lat - o.lat >  GRAD_1M) ||
            (o.lon - n_lon >  GRAD_1M) || (n_lon - o.lon >  GRAD_1M) ||
            (o.kurs - n_kurs > 1.0)    || (n_kurs - o.kurs > 1.0)    ||
            (n_art[0] && std::strcmp(o.art, n_art) != 0) ||
            (o.auf_boden != n_auf_boden));

        std::snprintf(o.art, sizeof(o.art), "%s", n_art);
        o.lat = n_lat;
        o.lon = n_lon;
        o.kurs = n_kurs;
        o.hat_hoehe = hat;
        o.erwartete_hoehe_ft = n_hoehe;
        o.auf_boden = n_auf_boden;
        o.in_soll = true;

        if (versetzt) {
            // Wegnehmen und beim Durchlauf unten gleich neu erzeugen. `objekt_entfernen`
            // loescht den Platz komplett, deshalb die Angaben danach wieder eintragen.
            objekt_entfernen(i);
            std::snprintf(o.id,  sizeof(o.id),  "%s", id);
            std::snprintf(o.art, sizeof(o.art), "%s", n_art);
            o.belegt = true;
            o.in_soll = true;
            o.lat = n_lat;
            o.lon = n_lon;
            o.kurs = n_kurs;
            o.hat_hoehe = hat;
            o.erwartete_hoehe_ft = n_hoehe;
            o.auf_boden = n_auf_boden;
            o.seit_s = g_sekunden;
        }

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
            continue;
        }

    }
}

// ---------------------------------------------------------------------------------------
// Die Antwort lesen
// ---------------------------------------------------------------------------------------

// Eine vom Server zugeteilte Kennung entgegennehmen -- einmal, und dann nie wieder.
//
// ⚠ NUR WENN WIR NOCH KEINE HABEN. Der Server schickt das Feld ohnehin nur bei der Meldung
// mit, die es bekommen hat; die Pruefung hier ist die zweite Schranke. Eine bestehende
// Zuordnung darf keine neue Kennung bekommen -- das waere genau das Flackern, das die
// Zuordnungs-Spec vermeiden will ("Zuordnung halten, sobald sie steht").
static void kennung_uebernehmen(const char* json) {
    if (g_kennung[0] != '\0') return;

    // ⚠⚠ NICHT, SOLANGE DIE DATEI NOCH GELESEN WIRD -- sonst gewinnt der Server das Rennen
    // gegen die eigene Platte.
    //
    // Gemessen am 14.09.2026: Die Kennung wechselte bei JEDEM Start, obwohl die Datei
    // sauber geschrieben wurde (16 Bytes, richtiger Inhalt). Der Grund war die Reihenfolge.
    // `fsIOOpenRead` laeuft asynchron und braucht bis zu KENNUNG_WARTE_S; die erste Meldung
    // geht aber schon nach einer Sekunde hinaus. Der Server antwortete mit einer frischen
    // Kennung, die Bruegge uebernahm sie -- und der Lese-Callback kam ins Leere.
    //
    // `g_kennung_fest` wird erst gesetzt, wenn das Lesen abgeschlossen ODER abgelaufen ist
    // (s. kennung_pruefen). Vorher nehmen wir nichts entgegen. Die paar Sekunden ohne
    // Kennung kosten nur einen vollen Positionsmatch, und den kann der Server ohnehin --
    // genau dafuer ist er gebaut.
    //
    // Das ist der DRITTE Wettlauf derselben Bauart an dieser einen Funktion: erst das
    // Schreiben gegen das Lesen, dann das Schliessen gegen das Schreiben, jetzt der Server
    // gegen die Platte. Wer hier etwas aendert, frage sich zuerst, was gleichzeitig laeuft.
    if (!g_kennung_fest) return;
    char neu[40] = {0};
    if (!json_text_in(json, "kennung", neu, sizeof(neu))) return;
    size_t n = std::strlen(neu);
    // Dieselbe Pruefung wie beim Lesen aus der Datei, nur weiter gefasst: Der Server schickt
    // 16 Hexziffern (`secrets.token_hex(8)`), aber eine spaetere Laenge soll nicht scheitern.
    if (n < 8 || n >= sizeof(g_kennung)) return;
    for (size_t i = 0; i < n; ++i) {
        char c = neu[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return;
    }
    std::snprintf(g_kennung, sizeof(g_kennung), "%s", neu);
    g_kennung_fest = true;
    kennung_schreiben();
    // Kein Log: Die MSFS-Fassung hat keinen Ausgabeweg (anders als die X-Plane-Fassung mit
    // `logzeile`). Ob es geklappt hat, steht ohnehin dort, wo es zaehlt -- in der naechsten
    // Meldung, und damit in `bruegge_zuordnung` auf dem Server.
}

static void antwort_lesen(const char* json) {
    // ZUERST -- sie gilt schon fuer die naechste Meldung.
    kennung_uebernehmen(json);

    // Der Server bestimmt den Takt, nicht die Brügge. Er darf ihn je Meldung und je Pilot
    // verschieden setzen -- und über die Admin-Drossel für alle auf einmal ändern, ohne
    // Deploy und ohne dass ein Pilot etwas tun muss.
    double takt = json_zahl(json, "naechste_frage_in_s", (double)g_takt_s);
    if (takt < 1.0) takt = 1.0;
    if (takt > 900.0) takt = 900.0;
    // NUR bei Änderung ins Log -- im Regeltakt wären es 3600 Zeilen in der Stunde. Die
    // Änderung selbst ist dagegen genau die Auskunft, die am 15.09.2026 gefehlt hat: Eine
    // Drosselung auf 900 s sieht von außen aus wie ein totes Modul, und niemand konnte
    // sehen, dass der Server sie angeordnet hatte.
    if ((int)takt != g_takt_s) {
        log_zeile("Der Server setzt den Takt von %d s auf %d s.", g_takt_s, (int)takt);
    }
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
        if (!g_vertrag_tot) {
            log_zeile("Der Server lehnt die Protokollfassung ab (426). Die Bruegge haelt sich "
                      "zurueck (Takt 900 s) -- es hilft nur ein neues Paket.");
        }
        g_vertrag_tot = true;
        g_takt_s = 900;
        return;
    }
    if (status == 429) {
        g_takt_s = (g_takt_s * 2 > 60) ? 60 : g_takt_s * 2;   // Rate-Limit
        return;
    }
    // 0 gilt mit, falls die Laufzeit doch ein Fehlerkennzeichen liefert statt eines Status.
    if (!(status == 0 || (status >= 200 && status < 300))) {
        // Nur beim WECHSEL ins Log. Eine Ablehnung hält im Regeltakt sekundenlang an --
        // etwa solange der Pilot nicht auf VATSIM verbunden ist, was der Normalfall und
        // kein Fehler ist. Jede Sekunde eine Zeile wäre Rauschen; die eine Zeile beim
        // Wechsel sagt, ab wann der Server ablehnt und ab wann wieder nicht.
        if (status != g_letzter_status) {
            log_zeile("Der Server lehnt ab (HTTP %d). Die Bruegge meldet weiter.", status);
            g_letzter_status = status;
        }
        return;
    }
    if (g_letzter_status != 0) {
        log_zeile("Der Server nimmt wieder an (vorher HTTP %d).", g_letzter_status);
        g_letzter_status = 0;
    }

    unsigned long n = fsNetworkHttpRequestGetDataSize(id);
    unsigned char* daten = fsNetworkHttpRequestGetData(id);
    if (!daten || n == 0) return;
    // ANTWORT_PUFFER muss zu SOLL_MAX passen, sonst schneidet er stillschweigend ab.
    //
    // Gemessen am 12.09.2026: 30 Objekte ergeben eine Antwort von 3776 Bytes, also 126 Bytes
    // je Eintrag. Der Puffer stand auf 4096 -- bei 30 Objekten zu 92 % voll, bei SOLL_MAX = 32
    // uebergelaufen, und mit `erwartete_hoehe_ft` je Eintrag schon deutlich frueher. Die
    // Bruegge konnte also mehr anfordern, als sie lesen kann.
    //
    // Das Abschneiden war dabei voellig lautlos: Das JSON bricht mitten im Satz ab,
    // `json_array` findet die vorderen Eintraege, der Rest fehlt. Von aussen sieht es aus wie
    // Objekte, die der Simulator nicht setzen wollte.
    // `g_antwort` statt einer lokalen Kopie: Die Titel darin werden spaeter noch
    // gebraucht, wenn eine Exception das Nachruecken ausloest (s. dort).
    char* kopie = g_antwort;
    bool abgeschnitten = (n > sizeof(g_antwort) - 1);
    unsigned long m = abgeschnitten ? sizeof(g_antwort) - 1 : n;
    std::memcpy(kopie, daten, m);
    kopie[m] = '\0';

    // Passt die Antwort NICHT, wird sie gar nicht erst ausgewertet. Ein halb gelesener
    // Sollzustand ist schlimmer als ein unveraenderter: Er raeumte alles ab, was hinter der
    // Schnittstelle stand, und setzte es beim naechsten Takt neu -- ein Flackern, dessen
    // Ursache niemand faende. Stattdessen bleibt der letzte gueltige Stand stehen, und der
    // Server erfaehrt mit der naechsten Meldung davon.
    if (abgeschnitten) {
        g_antwort_zu_gross = n;
        return;
    }
    g_antwort_zu_gross = 0;
    antwort_lesen(kopie);
}

// Der Waechter. Er liest NICHTS -- dafuer ist der Callback da -- er raeumt nur auf.
static void anfrage_bewachen() {
    if (g_laufend == 0) return;
    if (++g_laufend_seit <= 30) return;
    // Der Wächter schlägt an -- eine Anfrage hat 30 s lang keine Antwort bekommen. Das
    // gehört ins Log, weil es die einzige Stelle ist, an der ein Netzproblem sichtbar wird:
    // Die Brügge redet danach einfach weiter, als wäre nichts gewesen.
    log_zeile("Keine Antwort binnen 30 s -- Anfrage verworfen, es geht weiter.");
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

            // ⚠ UND DER TAKT. Bis zum 15.09.2026 stand er als einziger NICHT in dieser
            // Liste, und das war die bestätigte Ursache von Issue #38: Wer einmal auf 900 s
            // gedrosselt war -- durch den Ausschalter im Admin --, kam nur über einen
            // NEUSTART DES SIMULATORS zurück. Der Schalter war damit eine Einbahnstraße:
            // Abschalten wirkte sofort, das Wiedereinschalten erfuhr die Brügge frühestens
            // eine Viertelstunde später, und wer dazwischen den Flug wechselte, fing wieder
            // von vorn an. Am 15.09.2026 wurden so 30 Minuten lang null Meldungen gemessen,
            // während das Kniebrett im selben Simulator 793 schickte.
            //
            // Eine neue Welt ist ein frischer Anfang -- die Brügge fragt sofort, und die
            // Antwort trägt den Takt, der jetzt gilt (`naechste_frage_in_s`). Sie umgeht
            // damit nichts: Steht der Schalter weiter auf „aus", ist sie nach EINER Meldung
            // wieder gedrosselt.
            //
            // Die Ausnahme ist der tote Vertrag. Ein `426` heißt, dass der Server diese
            // Fassung nicht mehr liest; das ändert kein Flugwechsel, und in einem Vertrag,
            // den die Gegenseite gekündigt hat, soll sie nicht wieder anfangen zu reden.
            if (!g_vertrag_tot && g_takt_s != 1) {
                log_zeile("Neue Welt -- Takt von %d s zurueck auf 1 s.", g_takt_s);
                g_takt_s = 1;
                g_seit_meldung = 0;
            }
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
        if (d->dwRequestID == REQ_FLUGZEUG) {
            const char* t = (const char*)&d->dwData;
            ++g_flugzeug_rufe;
            if (t[0] == 0) ++g_flugzeug_leer;
            // Nur wenn er sich geaendert hat -- sonst wuerde jede Sekunde neu gemeldet.
            if (t[0] != '\0' && std::strncmp(t, g_flugzeug, sizeof(g_flugzeug) - 1) != 0) {
                std::snprintf(g_flugzeug, sizeof(g_flugzeug), "%s", t);
                g_flugzeug_offen = FLUGZEUG_MELDUNGEN;   // neuer Titel -> wieder melden
            }
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
            // In der Luft? Dann festhalten, sonst faellt ein Flugzeugtitel herunter
            // (s. EV_FREEZE_ALT). HIER und nicht in `objekt_erzeugen`: Die Ereignisse
            // brauchen die Objekt-ID, und die gibt es erst in diesem Augenblick.
            objekt_festhalten(i);
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

        // Die Exception nennt in `dwSendID` das Paket, das sie ausgeloest hat -- und genau
        // dieser Wert wird beim Erzeugen mit `SimConnect_GetLastSentPacketID` gemerkt
        // (s. objekt_erzeugen). Damit ist die Zuordnung EXAKT statt geraten.
        //
        // VORHER WURDE GERATEN, und es ging schief (12.09.2026 im Simulator gemessen): Der
        // letzte unbestaetigte Erzeugungsversuch wurde markiert. Bei fuenf gleichzeitig
        // gesetzten Objekten kam eine Exception vom FAHRZEUG herein und landete beim BAEREN,
        // weil dessen Objekt-ID noch unterwegs war. Der Baer stand sichtbar im Gras, waehrend
        // die Bruegge ihn als "fehlgeschlagen / EXCEPTION_22" meldete.
        //
        // Das ist schlimmer als ein falsches Etikett: Ohne zugeordnete Objekt-ID kann die
        // Bruegge das Objekt NIE WIEDER ABRAEUMEN. Es steht bis zum Verbindungsende. Fuer den
        // Kieker hiesse das eine Station, die als gescheitert gilt, in Wahrheit dasteht und
        // sich nicht mehr entfernen laesst -- und der Server, der die Stelle daraufhin fuer
        // unbrauchbar haelt, setzt die naechste woanders hin. Zwei Stationen, eine davon
        // unsichtbar fuer alle Beteiligten.
        bool zugeordnet = false;
        for (int i = 0; i < SOLL_MAX; ++i) {
            if (!g_soll[i].belegt || g_soll[i].sende_id == 0
                || g_soll[i].sende_id != ex->dwSendID) continue;

            // Den NAECHSTEN Titel der Gattung versuchen, statt sofort aufzugeben. Ein Titel,
            // den dieser Simulator nicht kennt, ist kein Grund, die ganze Gattung fallen zu
            // lassen -- und genau das geschah mit `fahrzeug`, dessen einziger Name aus dem
            // 2020er Bestand stammte. Seit Fassung 2 kommt die Liste vom Server, und er
            // hat bereits aussortiert, was nachweislich scheitert -- das Nachruecken bleibt
            // trotzdem: Was beim einen Piloten fehlt (ein Community-Paket), hat der andere.
            if (titel_fuer(g_soll[i].art, g_soll[i].titel_nr + 1) != nullptr) {
                g_soll[i].titel_nr += 1;
                g_soll[i].erzeugt_gerufen = false;   // beim naechsten Abgleich neu versuchen
                g_soll[i].sende_id = 0;
                g_soll[i].fehler[0] = '\0';
            } else {
                // Liste erschoepft. Jetzt ist es ein echter Fehlschlag, und der Server soll
                // die ZULETZT gescheiterte Ausnahme sehen -- sie sagt am meisten darueber,
                // was der Simulator eigentlich bemaengelt.
                std::snprintf(g_soll[i].fehler, sizeof(g_soll[i].fehler),
                              "EXCEPTION_%lu", (unsigned long)ex->dwException);
            }
            zugeordnet = true;
            break;
        }

        // Passt die Exception zu keinem Erzeugungsversuch, gehoert sie woandershin (eine
        // Datendefinition, eine Lageabfrage) -- dann darf sie AUF KEINEN FALL einem Objekt
        // angehaengt werden. Lieber gar keine Meldung als eine falsche: Ein Objekt, das
        // grundlos als gescheitert gilt, wird vom Server nicht mehr angefordert.
        (void)zugeordnet;
        break;
    }
    default:
        break;
    }
}

extern "C" MSFS_CALLBACK void module_init(void) {
    log_zeile("Fassung %s (%s) startet -- verbinde mit SimConnect...",
              BRUEGGE_VERSION, SIMULATOR_NAME);

    // ⚠ MEHR ALS DIESE DREI VERSUCHE IST NICHT BAUBAR -- und das ist keine Bequemlichkeit.
    //
    // Die Übergabe vom 15.09.2026 verlangte „bei Fehlschlag im Sekundentakt erneut
    // versuchen". Dafür bräuchte es einen Taktgeber, und den hat ein reines WASM-Modul
    // ausschließlich über SimConnect selbst (`EV_SEKUNDE`): Scheitert `SimConnect_Open`,
    // gibt es keine Schleife mehr, in der ein zweiter Versuch stattfinden könnte.
    // Nachgesehen am 15.09.2026 im SDK (`C:\MSFS 2024 SDK\WASM\include\MSFS`):
    // `MSFS_Events.h` kennt nur Key-Events, einen Frame- oder Timer-Callback für Module
    // gibt es in keinem der 21 Header. Ein `sleep` zwischen den Versuchen scheidet
    // ebenfalls aus -- es blockierte den Simulator-Thread mitten im Ladevorgang und zöge
    // mit `poll_oneoff` einen wasi-Import herein, den die MSFS-Laufzeit womöglich nicht
    // kennt (genau die Falle, an der `__stack_chk_fail` das Modul vor dem Start tötet).
    //
    // Was bleibt, sind Sofortversuche gegen einen vorübergehenden Fehlschlag -- und vor
    // allem die Logzeile darunter. DIE ist der eigentliche Gewinn: Vorher war ein
    // gescheitertes `Open` von einem nie geladenen Modul nicht zu unterscheiden.
    bool verbunden = false;
    for (int versuch = 1; versuch <= 3 && !verbunden; ++versuch) {
        HRESULT hr = SimConnect_Open(&g_sim, "FriesenBruegge", nullptr, 0, 0, 0);
        if (hr == S_OK) {
            verbunden = true;
            if (versuch > 1) log_zeile("SimConnect verbunden (im %d. Versuch).", versuch);
            break;
        }
        log_zeile("SimConnect_Open fehlgeschlagen, Versuch %d von 3 (hr=0x%08lX).",
                  versuch, (unsigned long)hr);
    }
    if (!verbunden) {
        log_zeile("AUFGEGEBEN -- ohne SimConnect gibt es keinen Takt, in dem ein weiterer "
                  "Versuch stattfinden koennte. Die Bruegge bleibt diese Sitzung lang stumm; "
                  "es hilft nur ein Neustart des Simulators.");
        return;
    }
    log_zeile("SimConnect verbunden.");

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

    // Der Titel des eigenen Flugzeugs -- eine eigene Definition, s. DEF_FLUGZEUG.
    //
    // ⚠ `nullptr` ALS EINHEIT UND EIN AUSDRUECKLICHER DATENTYP: Ein String hat keine
    // Einheit, und ohne `SIMCONNECT_DATATYPE_STRING256` nimmt SimConnect `FLOAT64` an --
    // dann kommen acht Bytes Zeichen als Zahl zurueck.
    // ⚠ "Title", NICHT "TITLE". Das SDK-Beispiel `RequestData.cpp` schreibt es genau so
    // (Zeile 121), und am 14.09.2026 kam mit der Grossschreibung KEIN Wert an -- der
    // Callback feuerte nie, die Meldung blieb ohne `flugzeug`. Bei anderen SimVars ist die
    // Schreibweise gleichgueltig; bei dieser offenbar nicht.
    SimConnect_AddToDataDefinition(g_sim, DEF_FLUGZEUG, "Title", nullptr,
                                   SIMCONNECT_DATATYPE_STRING256);
    // SIMCONNECT_PERIOD_SECOND und nicht ONCE: Ein Flugwechsel aendert den Titel, und eine
    // einmalige Anfrage vor dem Laden liefert den des Menue-Flugzeugs. Die Meldung nach
    // aussen geht er die ersten FLUGZEUG_MELDUNGEN Meldungen mit (s. g_flugzeug_offen).
    SimConnect_RequestDataOnSimObject(g_sim, REQ_FLUGZEUG, DEF_FLUGZEUG,
                                      SIMCONNECT_OBJECT_ID_USER, SIMCONNECT_PERIOD_SECOND);

    // Die drei Freeze-Ereignisse anmelden -- EINMAL JE VERBINDUNG, nicht je Objekt.
    //
    // ⚠ Das ist kein Feinschliff, sondern ein Fehler, der in diesem Projekt schon einmal
    // gemacht wurde: In `kieker_probe.py` steckten Definition und Anfrage in einer Funktion,
    // die je Objekt lief -- bei 25 Objekten hatte dieselbe Definition danach 75 Eintraege,
    // und die gemessene Meldungsrate sagte nichts mehr ueber den Simulator aus. Eine
    // Zuordnung wird einmal angelegt und dann beliebig oft benutzt; genau dafuer ist die
    // Ereignis-ID da (`objekt_festhalten` sendet, meldet aber nicht an).
    SimConnect_MapClientEventToSimEvent(g_sim, EV_FREEZE_ALT,  "FREEZE_ALTITUDE_SET");
    SimConnect_MapClientEventToSimEvent(g_sim, EV_FREEZE_LAGE, "FREEZE_ATTITUDE_SET");
    SimConnect_MapClientEventToSimEvent(g_sim, EV_FREEZE_ORT,  "FREEZE_LATITUDE_LONGITUDE_SET");

    // "SimStart" feuert, sobald die Simulation läuft -- im Hauptmenü und während des Ladens
    // ist sie gestoppt. "FlightLoaded" feuert zusätzlich bei jedem Flugwechsel.
    SimConnect_SubscribeToSystemEvent(g_sim, EV_SEKUNDE, "1sec");
    SimConnect_SubscribeToSystemEvent(g_sim, EV_SIMSTART, "SimStart");
    SimConnect_SubscribeToSystemEvent(g_sim, EV_FLUGGELADEN, "FlightLoaded");

    SimConnect_CallDispatch(g_sim, dispatch, nullptr);

    // Die Zeile, an der sich „läuft" von „geladen, tut aber nichts" unterscheiden lässt.
    // Die Kennung geht mit, weil sie auf der Serverseite die Brügge benennt -- steht sie
    // hier, lässt sich eine Meldung im Container-Log ohne Umweg diesem Simulator zuordnen.
    log_zeile("bereit -- Takt %d s, Kennung %s, meldet an %s",
              g_takt_s, g_kennung[0] ? g_kennung : "(noch keine)", BRUEGGE_URL);
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
