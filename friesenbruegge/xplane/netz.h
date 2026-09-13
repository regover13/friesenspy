#pragma once
// ---------------------------------------------------------------------------------------
// Netz und Nebenläufigkeit der FriesenBrügge -- OHNE jeden Bezug auf das X-Plane-SDK
// ---------------------------------------------------------------------------------------
//
// Diese Trennung ist kein Aufräumen: Sie ist die Bedingung dafür, dass sich die Schicht ohne
// Simulator übersetzen und messen lässt (`pruefen/netz_pruefen.cpp`). Für macOS und Linux ist
// das der einzige Test, den es vor dem ersten Piloten überhaupt gibt.
//
// ⚠ KEIN XPLM-AUFRUF HIER DRIN, auch nicht indirekt. Das SDK ist nicht threadsicher -- eine
// einzige XPLMDebugString-Zeile aus dem Netzthread reicht für einen Absturz, den niemand
// reproduziert. Was ins Log soll, geht über `netz_log` in einen Ringpuffer, den
// `bruegge.cpp` aus der Flugschleife -- also dem Hauptthread -- abholt.
//
// Die Plattformen teilen sich alles bis auf EINE Funktion: `netz_einmal_senden`. Windows
// füllt sie mit WinHTTP (belegt, geflogen am 13.09.2026), macOS und Linux mit libcurl.
//
// Warum libcurl für beide POSIX-Systeme: Sie bringen es beide mit und binden dabei ihren
// eigenen Zertifikatsspeicher an -- Linux OpenSSL, macOS die Keychain. Eine eigene
// TLS-Bibliothek mitzuliefern wäre die Alternative gewesen, und zwar je System eine andere.
//
// Warum zur Laufzeit geholt (`dlopen`) statt gelinkt: Ein Plugin mit unauflösbarem Symbol
// wird von X-Plane gar nicht erst geladen. Der Pilot sähe eine Zeile in einem riesigen
// Log.txt und sonst nichts. So startet die Brügge, findet libcurl nicht und SAGT es.

#include <atomic>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <thread>

#define MELDUNG_PUFFER 8192
#define ANTWORT_PUFFER 16384

// Was von einem Sendeversuch zurückkommt.
struct NetzMeldung {
    char   text[ANTWORT_PUFFER];
    size_t laenge;
    long   code;        // HTTP-Status, 0 = gar nicht angekommen
    bool   zu_gross;    // Antwort passte nicht in den Puffer -- sie wird VERWORFEN
};

// ---------------------------------------------------------------------------------------
// Logzeilen aus dem Netzthread
// ---------------------------------------------------------------------------------------
//
// Acht Plätze. Wer mehr erzeugt, verliert die neuesten -- ein Netzthread, der schneller
// meldet, als die Flugschleife abholt, hat ohnehin ein anderes Problem als das Log.

static std::mutex g_log_schloss;
static char       g_log[8][256];
static int        g_log_anzahl = 0;

inline void netz_log(const char* zeile) {
    std::lock_guard<std::mutex> sperre(g_log_schloss);
    if (g_log_anzahl < 8) {
        std::snprintf(g_log[g_log_anzahl], sizeof(g_log[0]), "%s", zeile);
        ++g_log_anzahl;
    }
}

// Aus dem HAUPTTHREAD aufrufen -- `ausgeben` darf XPLM benutzen, `netz_log` nicht.
inline void netz_log_abholen(void (*ausgeben)(const char*)) {
    char kopie[8][256];
    int n = 0;
    {
        std::lock_guard<std::mutex> sperre(g_log_schloss);
        n = g_log_anzahl;
        for (int i = 0; i < n; ++i) std::memcpy(kopie[i], g_log[i], sizeof(kopie[0]));
        g_log_anzahl = 0;
    }
    for (int i = 0; i < n; ++i) ausgeben(kopie[i]);
}

// ---------------------------------------------------------------------------------------
// Das Ziel
// ---------------------------------------------------------------------------------------
//
// Wird EINMAL vor dem Threadstart gesetzt und danach nur noch gelesen -- deshalb ohne
// Schloss, obwohl der Netzthread mitliest.

static char     g_ziel_host[160]  = "friesenspy.devprops.de";
static char     g_ziel_rumpf[256] = "/api/bruegge/melden";
static unsigned g_ziel_port       = 443;
static bool     g_ziel_sicher     = true;
static char     g_ziel_url[512]   = "https://friesenspy.devprops.de/api/bruegge/melden";

// ---------------------------------------------------------------------------------------
// Gemeinsame Nebenläufigkeit
// ---------------------------------------------------------------------------------------

static std::unique_ptr<std::thread> g_netz_thread;   // ⚠ Zeiger, NICHT global by value:
                                                     // ein joinable std::thread, der beim
                                                     // Entladen der Bibliothek zerstört
                                                     // wird, ruft std::terminate -- und
                                                     // X-Plane stürbe beim Beenden.
static std::mutex              g_schloss;
static std::condition_variable g_wecker;
static std::atomic<bool>       g_netz_ende{false};

static char        g_ausgang[MELDUNG_PUFFER];
static bool        g_ausgang_voll = false;
static NetzMeldung g_eingang{};
static bool        g_eingang_voll = false;

// ---------------------------------------------------------------------------------------
#if defined(_WIN32)
// ---------------------------------------------------------------------------------------

#define WIN32_LEAN_AND_MEAN 1
#include <windows.h>
#include <winhttp.h>
#pragma comment(lib, "winhttp.lib")

static HINTERNET g_sitzung = nullptr;
static HINTERNET g_verbindung = nullptr;
static wchar_t   g_host_w[160] = L"friesenspy.devprops.de";
static wchar_t   g_pfad_w[256] = L"/api/bruegge/melden";

inline bool netz_bereit(char* fehler, size_t n) {
    std::snprintf(fehler, n, "Netz: WinHTTP");
    return true;                                  // gehört zum System, kann nicht fehlen
}

inline void netz_schliessen() {
    if (g_verbindung) { WinHttpCloseHandle(g_verbindung); g_verbindung = nullptr; }
    if (g_sitzung)    { WinHttpCloseHandle(g_sitzung);    g_sitzung = nullptr; }
}

// Sitzung und Verbindung werden EINMAL geöffnet und behalten -- so läuft die zweite Meldung
// über dieselbe TLS-Verbindung wie die erste. Bei Sekundentakt ist das der Unterschied
// zwischen einem Handshake je Meldung und einem je Sitzung.
inline bool netz_oeffnen() {
    if (g_verbindung) return true;
    netz_schliessen();

    g_sitzung = WinHttpOpen(L"FriesenBruegge", WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,
                            WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!g_sitzung) return false;
    // Auflösen, Verbinden, Senden, Empfangen. Die 15 s beim Empfangen sind die Obergrenze,
    // an der die Brügge eine Meldung aufgibt -- der Wächter im Takt räumt sie danach weg.
    WinHttpSetTimeouts(g_sitzung, 10000, 10000, 15000, 15000);

    g_verbindung = WinHttpConnect(g_sitzung, g_host_w, (INTERNET_PORT)g_ziel_port, 0);
    if (!g_verbindung) { netz_schliessen(); return false; }
    return true;
}

inline void netz_ziel_uebernehmen() {
    // Nach wchar_t umsetzen -- WinHTTP will Weitzeichen. Reines ASCII genügt hier; ein
    // Rechnername mit Umlauten wäre ohnehin ein Fall für Punycode.
    size_t i = 0;
    for (; g_ziel_host[i] && i < 159; ++i) g_host_w[i] = (wchar_t)(unsigned char)g_ziel_host[i];
    g_host_w[i] = L'\0';
    size_t r = 0;
    for (; g_ziel_rumpf[r] && r < 255; ++r) g_pfad_w[r] = (wchar_t)(unsigned char)g_ziel_rumpf[r];
    g_pfad_w[r] = L'\0';
    netz_schliessen();
}

inline void netz_einmal_senden(const char* text, NetzMeldung* aus) {
    if (!netz_oeffnen()) return;

    HINTERNET anf = WinHttpOpenRequest(g_verbindung, L"POST", g_pfad_w, nullptr,
                                       WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES,
                                       g_ziel_sicher ? WINHTTP_FLAG_SECURE : 0);
    if (!anf) { netz_schliessen(); return; }

    DWORD laenge = (DWORD)std::strlen(text);
    BOOL ok = WinHttpSendRequest(anf, L"Content-Type: application/json\r\n",
                                 (DWORD)-1L, (LPVOID)text, laenge, laenge, 0);
    if (ok) ok = WinHttpReceiveResponse(anf, nullptr);
    if (ok) {
        DWORD code = 0, n = sizeof(code);
        if (WinHttpQueryHeaders(anf, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                                WINHTTP_HEADER_NAME_BY_INDEX, &code, &n,
                                WINHTTP_NO_HEADER_INDEX)) {
            aus->code = (long)code;
        }
        DWORD da = 0;
        while (WinHttpQueryDataAvailable(anf, &da) && da > 0) {
            size_t platz = sizeof(aus->text) - 1 - aus->laenge;
            if (platz == 0) {
                // Die Antwort ist grösser als der Puffer. Sie wird GAR NICHT ausgewertet --
                // ein halb gelesener Sollzustand räumte alles ab, was hinter der
                // Schnittstelle stand, und setzte es beim nächsten Takt neu. Das wäre ein
                // Flackern, dessen Ursache niemand fände.
                aus->zu_gross = true;
                break;
            }
            DWORD nimm = (da < platz) ? da : (DWORD)platz;
            DWORD tat = 0;
            if (!WinHttpReadData(anf, aus->text + aus->laenge, nimm, &tat) || tat == 0) break;
            aus->laenge += tat;
        }
        aus->text[aus->laenge] = '\0';
    } else {
        netz_schliessen();          // Verbindung hin -- beim nächsten Mal neu aufbauen
    }
    WinHttpCloseHandle(anf);
}

// ---------------------------------------------------------------------------------------
#else   // POSIX: macOS und Linux
// ---------------------------------------------------------------------------------------

#include <curl/curl.h>
#include <dlfcn.h>

// ⚠ setopt und getinfo sind VARIADISCH und müssen auch so deklariert werden: Apple übergibt
// variadische Argumente auf arm64 über den Stack statt in Registern. Als gewöhnliche
// Funktion deklariert ginge es auf Intel zufällig gut und bräche auf Apple Silicon.
using curl_init_fn       = CURL*       (*)();
using curl_setopt_fn     = CURLcode    (*)(CURL*, CURLoption, ...);
using curl_perform_fn    = CURLcode    (*)(CURL*);
using curl_getinfo_fn    = CURLcode    (*)(CURL*, CURLINFO, ...);
using curl_cleanup_fn    = void        (*)(CURL*);
using curl_slist_add_fn  = curl_slist* (*)(curl_slist*, const char*);
using curl_slist_frei_fn = void        (*)(curl_slist*);
using curl_version_fn    = char*       (*)();

static void*             g_curl_lib   = nullptr;
static curl_init_fn      c_init       = nullptr;
static curl_setopt_fn    c_setopt     = nullptr;
static curl_perform_fn   c_perform    = nullptr;
static curl_getinfo_fn   c_getinfo    = nullptr;
static curl_cleanup_fn   c_cleanup    = nullptr;
static curl_slist_add_fn c_slist_add  = nullptr;
static curl_slist_frei_fn c_slist_frei = nullptr;
static curl_version_fn   c_version    = nullptr;

static CURL*       g_curl = nullptr;
static curl_slist* g_kopf = nullptr;

// ⚠ Reihenfolge: der volle Pfad ZUERST. Ein nackter Name durchsucht auf macOS die
// Fallback-Pfade -- auf einem Intel-Mac mit Homebrew gewänne dessen curl mit eigenem
// OpenSSL statt Apples Bibliothek, die der Keychain vertraut. Genau darauf beruft sich
// aber die Entscheidung, keine eigene TLS-Bibliothek mitzuliefern.
static const char* const CURL_NAMEN[] = {
#if defined(__APPLE__)
    "/usr/lib/libcurl.4.dylib", "libcurl.4.dylib",
#else
    "libcurl.so.4", "libcurl-gnutls.so.4",
#endif
    nullptr
};

// ⚠ Wird aus XPluginStart gerufen, NICHT aus dem Netzthread: Der Fehlschlag muss ins Log,
// und das darf der Netzthread nicht.
// ⚠ Und KEIN access()-Vorabtest auf die Datei: Seit Big Sur liegen Systembibliotheken im
// dyld-Cache statt einzeln auf der Platte. access() schlüge fehl, dlopen gelingt.
inline bool netz_bereit(char* fehler, size_t n) {
    if (g_curl_lib) return true;
    for (int i = 0; CURL_NAMEN[i]; ++i) {
        g_curl_lib = dlopen(CURL_NAMEN[i], RTLD_LAZY | RTLD_LOCAL);
        if (g_curl_lib) break;
    }
    if (!g_curl_lib) {
        std::snprintf(fehler, n, "libcurl nicht gefunden (%s) -- keine Meldungen moeglich.",
                      CURL_NAMEN[0]);
        return false;
    }
    c_init       = (curl_init_fn)       dlsym(g_curl_lib, "curl_easy_init");
    c_setopt     = (curl_setopt_fn)     dlsym(g_curl_lib, "curl_easy_setopt");
    c_perform    = (curl_perform_fn)    dlsym(g_curl_lib, "curl_easy_perform");
    c_getinfo    = (curl_getinfo_fn)    dlsym(g_curl_lib, "curl_easy_getinfo");
    c_cleanup    = (curl_cleanup_fn)    dlsym(g_curl_lib, "curl_easy_cleanup");
    c_slist_add  = (curl_slist_add_fn)  dlsym(g_curl_lib, "curl_slist_append");
    c_slist_frei = (curl_slist_frei_fn) dlsym(g_curl_lib, "curl_slist_free_all");
    c_version    = (curl_version_fn)    dlsym(g_curl_lib, "curl_version");
    if (!c_init || !c_setopt || !c_perform || !c_getinfo || !c_cleanup ||
        !c_slist_add || !c_slist_frei) {
        std::snprintf(fehler, n, "libcurl gefunden, aber unvollstaendig -- keine Meldungen.");
        return false;
    }
    // Welche Fassung wirklich antwortet, ist nicht selbstverständlich: dlopen kann eine
    // bereits von X-Plane geladene Kopie derselben SONAME liefern.
    std::snprintf(fehler, n, "Netz: %s", c_version ? c_version() : "libcurl (Fassung unbekannt)");
    return true;
}

inline void netz_schliessen() {
    if (g_kopf) { c_slist_frei(g_kopf); g_kopf = nullptr; }
    if (g_curl) { c_cleanup(g_curl);    g_curl = nullptr; }
}

inline void netz_ziel_uebernehmen() { netz_schliessen(); }

static size_t netz_schreiben(char* stueck, size_t gr, size_t n, void* nutzer) {
    NetzMeldung* z = (NetzMeldung*)nutzer;
    size_t kommt = gr * n;
    if (z->laenge + kommt >= sizeof(z->text)) { z->zu_gross = true; return 0; }
    std::memcpy(z->text + z->laenge, stueck, kommt);
    z->laenge += kommt;
    z->text[z->laenge] = '\0';
    return kommt;
}

inline bool netz_oeffnen() {
    if (g_curl) return true;
    if (!c_init) return false;
    g_curl = c_init();
    if (!g_curl) return false;

    g_kopf = c_slist_add(nullptr, "Content-Type: application/json");
    // Ohne diese Zeile schickt libcurl bei grösseren Rümpfen "Expect: 100-continue" und
    // wartet auf die Zwischenantwort -- ein zusätzlicher Umlauf je Meldung, bei Sekundentakt
    // spürbar. WinHTTP tut das nicht, die Windows-Fassung kennt das Problem also nicht.
    g_kopf = c_slist_add(g_kopf, "Expect:");

    c_setopt(g_curl, CURLOPT_HTTPHEADER,     g_kopf);
    c_setopt(g_curl, CURLOPT_USERAGENT,      "FriesenBruegge");
    c_setopt(g_curl, CURLOPT_WRITEFUNCTION,  netz_schreiben);
    // NOSIGNAL: gesetzt, weil es nichts kostet -- nicht, weil der Schaden belegt wäre.
    //
    // Die Begründung lautete zunächst: "Ohne NOSIGNAL lässt libcurl bei einer gekappten
    // Verbindung ein SIGPIPE zu, und das beendet den Prozess, also X-Plane." Das ließ sich
    // am 13.09.2026 auf Linux (libcurl 8.5.0/OpenSSL) in ZWEI Aufbauten NICHT nachstellen:
    // weder bei einer Gegenstelle, die sofort schließt, noch bei einer, die erst antwortet
    // und die Keep-alive-Verbindung dann hart abbricht. Beide Male lief der Prozess mit und
    // ohne die Option unverändert weiter. libcurl sendet auf Linux offenbar mit MSG_NOSIGNAL.
    //
    // Die Option bleibt trotzdem: Sie deckt auch den Resolver-Pfad (SIGALRM bei Zeitüberlauf)
    // und macOS, wo der TLS- und Auflöse-Weg ein anderer ist -- und dort ist ungemessen.
    // ⚠ Wer sie entfernen will, misst erst auf einem Mac.
    // ⚠ Jede long-Option braucht ein L: Ein int belegt 4 Byte in einem 8-Byte-Fach, und
    // libcurl liest va_arg(long). Auf x86-64 klappt das zufällig, auf arm64-macOS nicht.
    c_setopt(g_curl, CURLOPT_NOSIGNAL,       1L);
    c_setopt(g_curl, CURLOPT_CONNECTTIMEOUT, 10L);
    c_setopt(g_curl, CURLOPT_TIMEOUT,        15L);
    return true;
}

inline void netz_einmal_senden(const char* text, NetzMeldung* aus) {
    if (!netz_oeffnen()) return;

    c_setopt(g_curl, CURLOPT_URL,        g_ziel_url);
    c_setopt(g_curl, CURLOPT_POSTFIELDS, text);
    c_setopt(g_curl, CURLOPT_WRITEDATA,  aus);

    CURLcode r = c_perform(g_curl);
    if (r == CURLE_OK) {
        long code = 0;                   // ⚠ long, nicht int -- getinfo ist variadisch
        c_getinfo(g_curl, CURLINFO_RESPONSE_CODE, &code);
        aus->code = code;
    } else if (aus->zu_gross) {
        // Der Schreib-Rückruf hat abgebrochen, weil die Antwort nicht passte. Das ist kein
        // Netzfehler -- die Meldung ging hinaus, nur die Antwort ist unbrauchbar.
        long code = 0;
        c_getinfo(g_curl, CURLINFO_RESPONSE_CODE, &code);
        aus->code = code;
    } else {
        netz_schliessen();               // Verbindung hin -- beim nächsten Mal neu aufbauen
    }
}

#endif
// ---------------------------------------------------------------------------------------
// Wieder gemeinsam
// ---------------------------------------------------------------------------------------

inline void netz_ziel(const char* host, unsigned port, const char* rumpf, bool sicher) {
    std::snprintf(g_ziel_host,  sizeof(g_ziel_host),  "%s", host);
    std::snprintf(g_ziel_rumpf, sizeof(g_ziel_rumpf), "%s", rumpf);
    g_ziel_port   = port;
    g_ziel_sicher = sicher;
    std::snprintf(g_ziel_url, sizeof(g_ziel_url), "%s://%s:%u%s",
                  sicher ? "https" : "http", host, port, rumpf);
    netz_ziel_uebernehmen();
}

inline void netz_lauf() {
    static char sendepuffer[MELDUNG_PUFFER];

    while (true) {
        {
            std::unique_lock<std::mutex> sperre(g_schloss);
            // ⚠ Das Prädikat ist nicht Zierde: Ein Win32-Event MERKT sich ein SetEvent, auch
            // wenn gerade niemand wartet -- eine condition_variable nicht. Ohne Prädikat
            // ginge ein Weckruf verloren, der Thread schliefe für immer, und netz_ende()
            // hinge im join. Genau diesen Fall misst pruefen/netz_pruefen.cpp, Teil 1.
            g_wecker.wait(sperre, [] { return g_ausgang_voll || g_netz_ende.load(); });
            if (g_netz_ende.load()) break;
            std::memcpy(sendepuffer, g_ausgang, sizeof(sendepuffer));
            g_ausgang_voll = false;
        }

        NetzMeldung m{};
        netz_einmal_senden(sendepuffer, &m);

        {
            std::lock_guard<std::mutex> sperre(g_schloss);
            g_eingang = m;
            g_eingang_voll = true;
        }
    }

    netz_schliessen();
}

inline void netz_start() {
    g_netz_ende.store(false);
    g_netz_thread.reset(new std::thread(netz_lauf));
}

inline void netz_senden(const char* text) {
    {
        std::lock_guard<std::mutex> sperre(g_schloss);
        std::snprintf(g_ausgang, sizeof(g_ausgang), "%s", text);
        g_ausgang_voll = true;
    }
    g_wecker.notify_one();
}

// true, wenn seit dem letzten Aufruf eine Antwort eingetroffen ist.
inline bool netz_antwort(NetzMeldung* aus) {
    std::lock_guard<std::mutex> sperre(g_schloss);
    if (!g_eingang_voll) return false;
    *aus = g_eingang;
    g_eingang_voll = false;
    return true;
}

// ⚠ `join()` statt der früheren 20-Sekunden-Schranke (`WaitForSingleObject(…, 20000)`):
// std::thread kennt kein Warten mit Zeitgrenze. Die Obergrenze ist damit CURLOPT_TIMEOUT
// (15 s) plus Namensauflösung. `detach()` wäre die Alternative und scheidet aus -- X-Plane
// entlädt das Plugin nach XPluginStop, und ein Thread, der dann noch in Plugin-Code steht,
// stürzt beim Rücksprung ab.
inline void netz_ende() {
    {
        std::lock_guard<std::mutex> sperre(g_schloss);
        g_netz_ende.store(true);
    }
    g_wecker.notify_all();
    if (g_netz_thread && g_netz_thread->joinable()) g_netz_thread->join();
    g_netz_thread.reset();
}
