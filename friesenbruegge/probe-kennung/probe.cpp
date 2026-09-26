// Probe: Hält eine Datei im \work-Ordner des Pakets einen Neustart von MSFS 2020 und 2024?
//
// Übergabe und Ablauf: UEBERGABE.md in diesem Ordner.
//
// Das Modul zählt seine eigenen Starts in einer Datei. Steht nach einem vollständigen
// Neustart des Simulators „Start Nr. 2“ im Log, hat die Datei überlebt. Steht wieder
// „Start Nr. 1“, wurde sie nicht gefunden.
//
// ⚠ NUR gewöhnliche C-Dateifunktionen (fopen/fread/fwrite/fclose) -- ausdrücklich NICHT die
// Datei-API aus MSFS_IO.h (fsIOOpen & Co.). Die gibt es nur im 2024er SDK, und genau an ihr
// ist die Ablage am 16.09.2026 gescheitert (s. Kopf von ../msfs/bruegge.cpp, "EIN MODUL").
// Ob MSFS 2020 die wasi-Importe annimmt, die fopen hereinzieht, ist die eigentliche Frage.
//
// Drei Schreibweisen des Pfads, weil nirgends belegt ist, welche MSFS erwartet. Die frühere
// Brügge benutzte "\\work\\friesenbruegge.kennung" -- aber mit fsIOOpen, nicht mit fopen.

#include <MSFS/MSFS.h>

#include <cstdio>
#include <cstdarg>
#include <cstring>
#include <cstdlib>
#include <cerrno>

// Dasselbe Muster wie in ../msfs/bruegge.cpp: stderr, ungepuffert, sofort geleert.
static void log_zeile(const char* format, ...) {
    char zeile[256];
    va_list rest;
    va_start(rest, format);
    std::vsnprintf(zeile, sizeof(zeile), format, rest);
    va_end(rest);
    std::fprintf(stderr, "[FriesenProbe] %s\n", zeile);
    std::fflush(stderr);
}

static const char* const PFADE[] = {
    "\\work\\probe_starts.txt",
    "/work/probe_starts.txt",
    "work/probe_starts.txt",
};

static void pfad_pruefen(const char* pfad) {
    int bisher = 0;
    FILE* f = std::fopen(pfad, "rb");
    if (f) {
        char puffer[32] = {0};
        size_t n = std::fread(puffer, 1, sizeof(puffer) - 1, f);
        std::fclose(f);
        bisher = std::atoi(puffer);
        log_zeile("%s: gelesen '%s' (%u Bytes)", pfad, puffer, (unsigned)n);
    } else {
        log_zeile("%s: nicht lesbar, errno=%d (%s)", pfad, errno, std::strerror(errno));
    }

    f = std::fopen(pfad, "wb");
    if (!f) {
        log_zeile("%s: NICHT SCHREIBBAR, errno=%d (%s)", pfad, errno, std::strerror(errno));
        return;
    }
    char neu[32];
    std::snprintf(neu, sizeof(neu), "%d", bisher + 1);
    size_t geschrieben = std::fwrite(neu, 1, std::strlen(neu), f);
    int zu = std::fclose(f);
    log_zeile("%s: Start Nr. %d geschrieben (%u Bytes, fclose=%d)", pfad, bisher + 1,
              (unsigned)geschrieben, zu);
}

extern "C" MSFS_CALLBACK void module_init(void) {
    log_zeile("module_init -- Probe fuer die Ablage im \\work-Ordner");
    for (const char* pfad : PFADE) {
        pfad_pruefen(pfad);
    }
}

extern "C" MSFS_CALLBACK void module_deinit(void) {
    log_zeile("module_deinit");
}
