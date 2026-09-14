// Gerade so viel JSON, wie das Brügge-Protokoll braucht -- und keine Zeile mehr.
//
// WARUM VON HAND und nicht mit einer Bibliothek: Die MSFS-WASM-Toolchain ist zweimal auf
// unerwartete Weise gestolpert (`__stack_chk_fail` fehlt in der Laufzeit, `--export-table`
// wird gebraucht, sobald ein Callback übergeben wird) -- beide Male sah es von außen aus wie
// ein Modul, das einfach nichts tut. Eine fremde Abhängigkeit in diese Kette zu hängen, kostet
// bei jedem Fehlschlag die Frage, ob es an ihr liegt. Fassung 1 des Protokolls ist klein
// genug, dass das hier überschaubar bleibt.
//
// WAS DAS HIER NICHT IST: ein JSON-Parser. Es liest gezielt die vier Felder, die in der
// Antwort stehen können, und zwar in der Annahme, dass der Server wohlgeformtes JSON ohne
// Verschachtelungsüberraschungen schickt -- er ist kein fremder Dienst, sondern unser eigener.
// Wer das Protokoll erweitert, erweitert hier mit; wer echtes JSON braucht, nimmt eine
// Bibliothek und trägt die Toolchain-Frage.

#pragma once

#include <cstdio>
#include <cstring>
#include <cstdlib>

// ---------------------------------------------------------------------------------------
// Schreiben
// ---------------------------------------------------------------------------------------

// ---------------------------------------------------------------------------------------
// Zahlen ohne Locale
// ---------------------------------------------------------------------------------------
//
// `snprintf("%.*f")` und `strtod` fragen beide LC_NUMERIC. Setzt irgendwer im Prozess
// `setlocale(LC_ALL, "")` -- X-Plane selbst oder ein beliebiges anderes Plugin, und zwar
// prozessweit --, dann meldet die Brügge bei einem deutschen Piloten `52,123` statt
// `52.123`, und der Server antwortet 400. Schlimmer noch beim Lesen: `strtod` liest aus
// `"lat": 53.5` dann eine 53, aus `1.5E2` eine 1. Gemessen am 13.09.2026 unter
// `de_DE.UTF-8` (`xplane/pruefen/json_locale.cpp`).
//
// In MSFS fällt das nicht auf -- die WASM-Sandbox kennt nur "C". Es ist ein reiner
// POSIX-Fund, und er trifft ausgerechnet die Piloten, für die die zweite Brügge gebaut wird.
//
// Ganzzahlformate (`%lld`) sind nicht betroffen; nur sie werden hier noch benutzt.

inline void zahl_nach_text(char* aus, size_t n, double wert, int stellen) {
    if (n == 0) return;
    if (stellen < 0) stellen = 0;
    if (stellen > 9) stellen = 9;

    // NaN, Unendlich und alles jenseits von long long: JSON kennt dafür keine Schreibweise.
    // Eine 0 ist falsch, aber gültig -- abgehacktes JSON wäre schlimmer.
    if (!(wert > -1e15 && wert < 1e15)) { std::snprintf(aus, n, "0"); return; }

    static const long long ZEHN[10] = {1LL, 10LL, 100LL, 1000LL, 10000LL, 100000LL,
                                       1000000LL, 10000000LL, 100000000LL, 1000000000LL};
    bool minus = wert < 0.0;
    if (minus) wert = -wert;

    long long faktor = ZEHN[stellen];
    long long ganz = (long long)wert;
    long long nach = (long long)((wert - (double)ganz) * (double)faktor + 0.5);
    if (nach >= faktor) { nach -= faktor; ganz += 1; }      // 1.999999 mit 3 Stellen -> 2.000

    char tmp[64];
    int pos = 0;
    if (minus && (ganz != 0 || nach != 0)) tmp[pos++] = '-';   // kein "-0.00000"
    pos += std::snprintf(tmp + pos, sizeof(tmp) - (size_t)pos, "%lld", ganz);
    if (stellen > 0) {
        tmp[pos++] = '.';
        pos += std::snprintf(tmp + pos, sizeof(tmp) - (size_t)pos, "%0*lld", stellen, nach);
    }
    tmp[pos] = '\0';
    std::snprintf(aus, n, "%s", tmp);
}

// Liest `[+-]ddd[.ddd][eE[+-]ddd]`. `ende` zeigt danach auf das erste nicht verbrauchte
// Zeichen -- wie bei `strtod`, damit die Aufrufer unverändert bleiben. Bleibt `ende` auf dem
// Anfang stehen, stand dort keine Zahl.
//
// Die Genauigkeit ist geringer als bei `strtod` (Ziffern werden aufmultipliziert statt
// exakt skaliert). Für fünf Nachkommastellen einer Koordinate -- rund einen Meter -- liegt
// der Unterschied weit jenseits dessen, was hier je zählt.
inline double text_nach_zahl(const char* p, const char** ende) {
    const char* anfang = p;
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') ++p;

    bool minus = false;
    if (*p == '+' || *p == '-') { minus = (*p == '-'); ++p; }

    bool ziffer = false;
    double wert = 0.0;
    while (*p >= '0' && *p <= '9') { wert = wert * 10.0 + (*p - '0'); ++p; ziffer = true; }
    if (*p == '.') {
        ++p;
        double teiler = 1.0;
        while (*p >= '0' && *p <= '9') {
            wert = wert * 10.0 + (*p - '0'); teiler *= 10.0; ++p; ziffer = true;
        }
        wert /= teiler;
    }
    if (!ziffer) { if (ende) *ende = anfang; return 0.0; }

    if (*p == 'e' || *p == 'E') {
        const char* merk = p;                    // ein 'e' ohne Ziffern gehört nicht dazu
        ++p;
        bool eminus = false;
        if (*p == '+' || *p == '-') { eminus = (*p == '-'); ++p; }
        if (*p >= '0' && *p <= '9') {
            int ex = 0;
            while (*p >= '0' && *p <= '9' && ex < 400) { ex = ex * 10 + (*p - '0'); ++p; }
            double f = 1.0;
            for (int i = 0; i < ex; ++i) f *= 10.0;
            if (eminus) wert /= f; else wert *= f;
        } else {
            p = merk;
        }
    }

    if (ende) *ende = p;
    return minus ? -wert : wert;
}

// Ein Puffer, der sich nicht überschreiben lässt. Läuft er voll, bleibt der Inhalt gültiges
// JSON bis zur letzten vollständigen Ergänzung -- gemeldet wird das über `voll()`, und der
// Aufrufer entscheidet. Stillschweigend abzuschneiden wäre schlimmer: Der Server bekäme
// abgehacktes JSON und antwortete mit 400, ohne dass die Brügge wüsste warum.
class JsonSchreiber {
public:
    JsonSchreiber(char* puffer, size_t groesse)
        : p_(puffer), gross_(groesse), pos_(0), voll_(false) {
        if (gross_) p_[0] = '\0';
    }

    void roh(const char* text) {
        size_t n = std::strlen(text);
        if (pos_ + n + 1 > gross_) { voll_ = true; return; }
        std::memcpy(p_ + pos_, text, n);
        pos_ += n;
        p_[pos_] = '\0';
    }

    void zahl(double wert, int stellen = 5) {
        char tmp[48];
        zahl_nach_text(tmp, sizeof(tmp), wert, stellen);
        roh(tmp);
    }

    void ganzzahl(long wert) {
        char tmp[32];
        std::snprintf(tmp, sizeof(tmp), "%ld", wert);
        roh(tmp);
    }

    // Text mit Maskierung. Nur die Zeichen, die in unseren Werten überhaupt vorkommen
    // können -- Kennungen sind Hexziffern, Simulator-Namen sind Kleinbuchstaben. Ein
    // Anführungszeichen oder Backslash darin wäre bereits ein Fehler anderswo, aber
    // ungefiltert durchzulassen hiesse, ihn in ein kaputtes Protokoll zu verwandeln.
    void text(const char* wert) {
        roh("\"");
        for (const char* c = wert; *c; ++c) {
            if (*c == '"') roh("\\\"");
            else if (*c == '\\') roh("\\\\");
            else if (*c >= 0 && *c < 0x20) continue;   // Steuerzeichen fallen weg
            else { char z[2] = { *c, '\0' }; roh(z); }
        }
        roh("\"");
    }

    void feld(const char* name) { roh("\""); roh(name); roh("\":"); }
    void komma() { roh(","); }

    const char* inhalt() const { return p_; }
    size_t laenge() const { return pos_; }
    bool voll() const { return voll_; }

private:
    char* p_;
    size_t gross_;
    size_t pos_;
    bool voll_;
};

// ---------------------------------------------------------------------------------------
// Lesen
// ---------------------------------------------------------------------------------------

// Sucht "name": und liefert die Zahl dahinter. `vorgabe`, wenn das Feld fehlt oder keine
// Zahl trägt -- eine fehlende Angabe ist kein Fehler, sondern heisst "wie bisher".
inline double json_zahl(const char* json, const char* name, double vorgabe) {
    char muster[64];
    std::snprintf(muster, sizeof(muster), "\"%s\"", name);
    const char* p = std::strstr(json, muster);
    if (!p) return vorgabe;
    p = std::strchr(p, ':');
    if (!p) return vorgabe;
    ++p;
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') ++p;
    const char* ende = nullptr;
    double wert = text_nach_zahl(p, &ende);
    return (ende == p) ? vorgabe : wert;
}

// Der Anfang des Arrays hinter "name": -- also das Zeichen NACH der oeffnenden Klammer.
// ``nullptr``, wenn es das Feld nicht gibt.
inline const char* json_array(const char* json, const char* name) {
    char muster[64];
    std::snprintf(muster, sizeof(muster), "\"%s\"", name);
    const char* p = std::strstr(json, muster);
    if (!p) return nullptr;
    p = std::strchr(p, '[');
    return p ? p + 1 : nullptr;
}

// Vom Anfang eines Array-Elements zum naechsten.
//
// Zaehlt Klammern mit, statt nach dem naechsten Komma zu suchen: Ein Komma steht auch INNEN
// in jedem Objekt, und wer danach sucht, findet die Feldtrenner statt der Elementgrenzen.
// Anfuehrungszeichen werden uebersprungen, damit ein Komma in einer Zeichenkette nicht zaehlt.
//
// ``nullptr`` am Ende des Arrays.
inline const char* json_naechstes(const char* p) {
    if (!p) return nullptr;
    int tiefe = 0;
    bool in_text = false;
    for (; *p; ++p) {
        if (in_text) {
            if (*p == '\\' && p[1]) { ++p; continue; }   // maskiertes Zeichen ueberspringen
            if (*p == '"') in_text = false;
            continue;
        }
        if (*p == '"') { in_text = true; continue; }
        if (*p == '{' || *p == '[') { ++tiefe; continue; }
        if (*p == '}' || *p == ']') {
            if (tiefe == 0) return nullptr;               // Array zu Ende
            --tiefe;
            continue;
        }
        if (*p == ',' && tiefe == 0) {
            ++p;
            while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') ++p;
            return p;
        }
    }
    return nullptr;
}

// Ein Textfeld aus EINEM Element lesen -- also nur bis zu dessen Ende suchen.
//
// Ohne diese Begrenzung faende ein Feldname das Vorkommen im NAECHSTEN Element, sobald er im
// eigenen fehlt: Aus einem Objekt ohne "kurs" wuerde stillschweigend der Kurs des folgenden.
inline bool json_text_in(const char* element, const char* name,
                         char* ziel, size_t ziel_gross) {
    if (!element || !ziel || ziel_gross == 0) return false;
    ziel[0] = '\0';
    const char* ende = json_naechstes(element);
    char muster[64];
    std::snprintf(muster, sizeof(muster), "\"%s\"", name);
    const char* p = std::strstr(element, muster);
    if (!p || (ende && p >= ende)) return false;
    p = std::strchr(p, ':');
    if (!p) return false;
    ++p;
    while (*p == ' ' || *p == '\t') ++p;
    if (*p != '"') return false;
    ++p;
    size_t n = 0;
    while (*p && *p != '"' && n + 1 < ziel_gross) {
        if (*p == '\\' && p[1]) ++p;
        ziel[n++] = *p++;
    }
    ziel[n] = '\0';
    return true;
}

// Eine Zahl aus EINEM Element. ``gefunden`` sagt, ob das Feld ueberhaupt da war -- der
// Unterschied zaehlt: ``erwartete_hoehe_ft: null`` heisst "nimm die Oberflaeche", ein
// fehlendes Feld dagegen ist ein Protokollbruch.
inline double json_zahl_in(const char* element, const char* name, double vorgabe,
                           bool* gefunden = nullptr) {
    if (gefunden) *gefunden = false;
    if (!element) return vorgabe;
    const char* ende = json_naechstes(element);
    char muster[64];
    std::snprintf(muster, sizeof(muster), "\"%s\"", name);
    const char* p = std::strstr(element, muster);
    if (!p || (ende && p >= ende)) return vorgabe;
    p = std::strchr(p, ':');
    if (!p) return vorgabe;
    ++p;
    while (*p == ' ' || *p == '\t') ++p;
    if (std::strncmp(p, "null", 4) == 0) return vorgabe;   // ausdruecklich "kein Wert"
    const char* zeiger_ende = nullptr;
    double wert = text_nach_zahl(p, &zeiger_ende);
    if (zeiger_ende == p) return vorgabe;
    if (gefunden) *gefunden = true;
    return wert;
}

// Steht hinter "name": ein LEERES Array? Das ist in Fassung 1 der Regelfall für `soll`, und
// die Unterscheidung "leer" gegen "fehlt" zählt: Ein fehlendes `soll` wäre ein Protokollbruch,
// ein leeres heisst schlicht "hier soll nichts stehen".
inline bool json_array_leer(const char* json, const char* name, bool* gefunden) {
    char muster[64];
    std::snprintf(muster, sizeof(muster), "\"%s\"", name);
    const char* p = std::strstr(json, muster);
    if (gefunden) *gefunden = (p != nullptr);
    if (!p) return true;
    p = std::strchr(p, '[');
    if (!p) return true;
    ++p;
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') ++p;
    return *p == ']';
}

// ---------------------------------------------------------------------------------------
// Das Artenwoerterbuch (Protokollfassung 2, 14.09.2026)
// ---------------------------------------------------------------------------------------
//
// Die Antwort traegt neben `soll` ein Woerterbuch mit DYNAMISCHEN Schluesseln:
//
//     "arten": { "rauch_signalrot": ["FrsRauch_Signalrot"], "tier_gross": ["BlackBear", …] }
//
// Das ist die einzige Stelle im Protokoll, an der ein Feldname nicht vorher feststeht --
// deshalb eine eigene Funktion statt eines weiteren `json_*_in`.
//
// ⚠ GESUCHT WIRD NUR INNERHALB VON `arten`, und das ist keine Vorsicht auf Verdacht:
// "rauch_signalrot" steht in derselben Antwort AUCH als Wert von `art` in jedem
// `soll`-Eintrag. Ohne die Begrenzung faende `strstr` je nach Reihenfolge das falsche
// Vorkommen und liefe von dort in ein Array, das einem anderen Feld gehoert.

// Das Ende des Objekts, das bei `anfang` (dem Zeichen NACH der oeffnenden Klammer) beginnt.
// Zaehlt Klammern mit und ueberspringt Zeichenketten, damit eine Klammer in einem Titel
// nicht zaehlt. ``nullptr``, wenn die Klammer nie geschlossen wird.
inline const char* json_objekt_ende(const char* anfang) {
    if (!anfang) return nullptr;
    int tiefe = 0;
    bool in_text = false;
    for (const char* p = anfang; *p; ++p) {
        if (in_text) {
            if (*p == '\\' && p[1]) { ++p; continue; }
            if (*p == '"') in_text = false;
            continue;
        }
        if (*p == '"') { in_text = true; continue; }
        if (*p == '{' || *p == '[') { ++tiefe; continue; }
        if (*p == '}' || *p == ']') {
            if (tiefe == 0) return p;
            --tiefe;
        }
    }
    return nullptr;
}

// Den n-ten Titel der Art `art` aus dem Woerterbuch `arten`. ``false``, wenn es die Art
// nicht gibt ODER die Liste kuerzer ist -- der Aufrufer unterscheidet beides ueber
// `json_art_bekannt`.
//
// Die Reihenfolge IST der Rang: Scheitert Titel 0, nimmt die Bruegge Titel 1.
inline bool json_titel_fuer(const char* json, const char* art, int n,
                            char* ziel, size_t ziel_gross) {
    if (!json || !art || !ziel || ziel_gross == 0 || n < 0) return false;
    ziel[0] = '\0';

    const char* w = std::strstr(json, "\"arten\"");
    if (!w) return false;
    w = std::strchr(w, '{');
    if (!w) return false;
    ++w;
    const char* w_ende = json_objekt_ende(w);
    if (!w_ende) return false;

    char muster[64];
    std::snprintf(muster, sizeof(muster), "\"%s\"", art);
    const char* p = std::strstr(w, muster);
    if (!p || p >= w_ende) return false;
    p = std::strchr(p, '[');
    if (!p || p >= w_ende) return false;
    const char* liste_ende = json_objekt_ende(p + 1);
    ++p;

    // Zum n-ten Element vorruecken. Elemente sind Zeichenketten; gezaehlt wird ueber die
    // oeffnenden Anfuehrungszeichen, Maskierungen uebersprungen.
    int gesehen = 0;
    while (p && *p && (!liste_ende || p < liste_ende)) {
        while (*p && *p != '"' && (!liste_ende || p < liste_ende)) ++p;
        if (!*p || (liste_ende && p >= liste_ende)) return false;
        ++p;                                     // hinter das oeffnende Anfuehrungszeichen
        if (gesehen == n) {
            size_t k = 0;
            while (*p && *p != '"' && k + 1 < ziel_gross) {
                if (*p == '\\' && p[1]) ++p;
                ziel[k++] = *p++;
            }
            ziel[k] = '\0';
            return k > 0;
        }
        while (*p && *p != '"') { if (*p == '\\' && p[1]) ++p; ++p; }
        if (!*p) return false;
        ++p;                                     // hinter das schliessende
        ++gesehen;
    }
    return false;
}

// Steht die Art ueberhaupt im Woerterbuch? Der Unterschied zaehlt: Eine unbekannte Art ist
// ein anderer Befund als eine Art, deren Titel allesamt scheiterten -- dort fehlen die
// Modelle im Simulator, hier war die Anforderung falsch.
inline bool json_art_bekannt(const char* json, const char* art) {
    char eins[8];
    if (json_titel_fuer(json, art, 0, eins, sizeof(eins))) return true;
    // Auch eine LEERE Liste heisst "Art bekannt, aber kein Titel" -- das soll nicht als
    // GATTUNG_UNBEKANNT durchgehen.
    if (!json || !art) return false;
    const char* w = std::strstr(json, "\"arten\"");
    if (!w) return false;
    w = std::strchr(w, '{');
    if (!w) return false;
    const char* w_ende = json_objekt_ende(w + 1);
    char muster[64];
    std::snprintf(muster, sizeof(muster), "\"%s\"", art);
    const char* p = std::strstr(w + 1, muster);
    return p && w_ende && p < w_ende;
}
