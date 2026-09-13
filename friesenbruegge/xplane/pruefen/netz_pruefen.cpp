// Fährt die Netz- und Threadschicht der Brügge OHNE Simulator.
//
// Das ist für macOS und Linux der einzige Test vor dem ersten Piloten. Was er NICHT kann,
// steht in der Spec, Abschnitt 12 -- allen voran die arm64-Aufrufkonvention, denn diese
// Maschine ist x86-64.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <thread>
#include "../netz.h"

static int fehler = 0;

static void pruefe(const char* was, bool gut) {
    std::printf("  %-52s %s\n", was, gut ? "ok" : "FEHLER");
    if (!gut) ++fehler;
}

static void log_ausgeben(const char* zeile) { std::printf("    [log] %s\n", zeile); }

// Wartet bis zu `zehntel` Zehntelsekunden auf eine Antwort.
static bool warte_auf_antwort(NetzMeldung* m, int zehntel) {
    for (int i = 0; i < zehntel; ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        if (netz_antwort(m)) return true;
    }
    return false;
}

// --- Teil 1 -------------------------------------------------------------------------
// Der verlorene Weckruf: senden, BEVOR der Thread überhaupt schlafen geht. Ein Win32-Event
// merkt sich das, eine condition_variable nicht. Ohne Prädikat im wait() bliebe die Meldung
// liegen und netz_ende() hinge im join.
static void teil1_nebenlaeufigkeit() {
    std::printf("Teil 1 -- Nebenlaeufigkeit\n");
    char text[256] = {0};
    if (!netz_bereit(text, sizeof(text))) { pruefe(text, false); return; }
    std::printf("    %s\n", text);

    netz_ziel("127.0.0.1", 8099, "/api/bruegge/melden", false);
    netz_start();
    netz_senden("{\"kennung\":\"pruefpruefpruef01\",\"steht\":[]}");

    auto anfang = std::chrono::steady_clock::now();
    netz_ende();
    auto dauer = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::steady_clock::now() - anfang).count();
    std::printf("    netz_ende brauchte %llds\n", (long long)dauer);
    pruefe("netz_ende kehrt binnen 20 s zurueck", dauer < 20);
}

// --- Teil 2 -------------------------------------------------------------------------
// Gegen den ECHTEN Endpunkt: TLS, Zertifikatsspeicher, JSON, Puffergrenze. Ohne VATSIM
// antwortet der Server mit 200 und leerem soll -- als Beleg genügt das.
static void teil2_echter_server() {
    std::printf("\nTeil 2 -- gegen den echten Server (HTTPS)\n");
    netz_ziel("friesenspy.devprops.de", 443, "/api/bruegge/melden", true);
    netz_start();
    netz_senden("{\"kennung\":\"pruefpruefpruef01\",\"fassung\":\"1.1.0\","
                "\"simulator\":\"xplane12\",\"lage\":{\"lat\":53.7,\"lon\":7.15,"
                "\"alt_ft\":1200.0,\"kurs\":90.0,\"gs_kt\":95.0},\"steht\":[]}");

    NetzMeldung m{};
    bool kam = warte_auf_antwort(&m, 200);
    pruefe("Antwort kam an", kam);
    pruefe("HTTP 200 -- das JSON ist also gueltig", kam && m.code == 200);
    pruefe("Antwort passte in den Puffer", kam && !m.zu_gross);
    if (kam) std::printf("    Antwort: %.140s\n", m.text);

    // Zweite Meldung ueber dieselbe Verbindung -- so ist der Sekundentakt gedacht.
    netz_senden("{\"kennung\":\"pruefpruefpruef01\",\"fassung\":\"1.1.0\","
                "\"simulator\":\"xplane12\",\"lage\":{\"lat\":53.71,\"lon\":7.16},"
                "\"steht\":[]}");
    NetzMeldung m2{};
    bool kam2 = warte_auf_antwort(&m2, 200);
    pruefe("zweite Meldung kommt auch an", kam2 && m2.code == 200);
    netz_ende();
}

// --- Teil 3 -------------------------------------------------------------------------
// Gegen den Pruefserver (http, OHNE TLS) -- der Weg, den ein Mac-Pilot spaeter geht.
static void teil3_pruefserver() {
    std::printf("\nTeil 3 -- gegen pruefserver.py (HTTP, ohne TLS)\n");
    netz_ziel("127.0.0.1", 8099, "/api/bruegge/melden", false);
    netz_start();
    netz_senden("{\"kennung\":\"pruefpruefpruef01\",\"fassung\":\"1.1.0\","
                "\"simulator\":\"xplane12\",\"lage\":{\"lat\":53.7,\"lon\":7.15},"
                "\"steht\":[]}");
    NetzMeldung m{};
    bool kam = warte_auf_antwort(&m, 100);
    pruefe("Pruefserver antwortet mit 200", kam && m.code == 200);
    pruefe("soll steht in der Antwort", kam && std::strstr(m.text, "soll") != nullptr);
    if (kam) std::printf("    Antwort: %.140s\n", m.text);
    netz_ende();
}

// --- Teil 4 -------------------------------------------------------------------------
// Der Server kappt mitten im Takt.
//
// ⚠ Was dieser Teil belegt: dass ein Verbindungsabbruch den Lauf nicht beendet und die
// Brügge danach weitermeldet. Was er NICHT belegt: dass CURLOPT_NOSIGNAL dafür nötig ist.
// Die Gegenprobe ohne die Option lief am 13.09.2026 genauso durch (s. Kommentar in netz.h).
// Ein Test, der mit und ohne die geprüfte Zeile dasselbe sagt, prüft sie nicht.
static void teil4_verbindung_gekappt() {
    std::printf("\nTeil 4 -- der Server kappt die Verbindung (SIGPIPE)\n");
    netz_ziel("127.0.0.1", 8098, "/api/bruegge/melden", false);
    netz_start();
    for (int i = 0; i < 5; ++i) {
        netz_senden("{\"kennung\":\"pruefpruefpruef01\",\"steht\":[]}");
        NetzMeldung m{};
        warte_auf_antwort(&m, 20);
    }
    netz_ende();
    pruefe("Prozess lebt nach fuenf gekappten Verbindungen", true);
}

int main() {
    teil1_nebenlaeufigkeit();
    teil2_echter_server();
    teil3_pruefserver();
    teil4_verbindung_gekappt();
    netz_log_abholen(log_ausgeben);
    std::printf(fehler ? "\n%d Fehler\n" : "\nalles gut\n", fehler);
    return fehler ? 1 : 0;
}
