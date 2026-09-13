// Belegt, dass json.h Zahlen unabhaengig von der Locale schreibt und liest.
//
// Der Grund steht in der Spec (Abschnitt 7): Setzt irgendwer im Prozess
// setlocale(LC_ALL, ""), schreibt "%.*f" bei einem deutschen Piloten 52,123 statt 52.123 --
// der Server antwortet 400 -- und strtod liest "53.5" als 53.
#include <clocale>
#include <cmath>
#include <cstdio>
#include <cstring>
#include "../../json.h"

static int fehler = 0;

static void gleich(const char* was, const char* ist, const char* soll) {
    if (std::strcmp(ist, soll) != 0) {
        std::printf("  FEHLER %s:\n    ist  \"%s\"\n    soll \"%s\"\n", was, ist, soll);
        ++fehler;
    } else {
        std::printf("  ok  %s\n", was);
    }
}

static void nahe(const char* was, double ist, double soll) {
    if (std::fabs(ist - soll) > 1e-9) {
        std::printf("  FEHLER %s: %.12g statt %.12g\n", was, ist, soll);
        ++fehler;
    } else {
        std::printf("  ok  %s\n", was);
    }
}

static void durchlauf(const char* wie) {
    std::printf("Locale: %s\n", wie);

    char puffer[256];
    JsonSchreiber s(puffer, sizeof(puffer));
    s.roh("{");
    s.feld("lat"); s.zahl(52.12345); s.komma();
    s.feld("lon"); s.zahl(-7.5, 5); s.komma();
    s.feld("null"); s.zahl(0.0, 1); s.komma();
    s.feld("rund"); s.zahl(1.999999, 3);
    s.roh("}");
    gleich("geschrieben", puffer,
           "{\"lat\":52.12345,\"lon\":-7.50000,\"null\":0.0,\"rund\":2.000}");

    // Gelesen wird, was der Server schickt -- Python schreibt kleine Zahlen als 1e-05.
    const char* antwort = "{\"takt\":1,\"lat\":53.5,\"lon\":-0.25,\"klein\":1e-05,"
                          "\"gross\":1.5E2,\"fehlt\":null}";
    nahe("lat",   json_zahl(antwort, "lat",   -1), 53.5);
    nahe("lon",   json_zahl(antwort, "lon",   -1), -0.25);
    nahe("klein", json_zahl(antwort, "klein", -1), 1e-05);
    nahe("gross", json_zahl(antwort, "gross", -1), 150.0);
    nahe("vorgabe bei null",  json_zahl(antwort, "fehlt",  42), 42);
    nahe("vorgabe bei fehlt", json_zahl(antwort, "gibtsnicht", 7), 7);
}

int main() {
    durchlauf("C (Vorgabe)");
    std::printf("\n");
    if (std::setlocale(LC_ALL, "de_DE.UTF-8")) {
        durchlauf("de_DE.UTF-8");
    } else {
        std::printf("  FEHLER: de_DE.UTF-8 nicht verfuegbar -- der Test prueft dann nichts.\n");
        ++fehler;
    }
    std::printf(fehler ? "\n%d Fehler\n" : "\nalles gut\n", fehler);
    return fehler ? 1 : 0;
}
