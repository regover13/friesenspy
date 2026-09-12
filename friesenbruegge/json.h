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
        std::snprintf(tmp, sizeof(tmp), "%.*f", stellen, wert);
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
    char* ende = nullptr;
    double wert = std::strtod(p, &ende);
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
    char* zeiger_ende = nullptr;
    double wert = std::strtod(p, &zeiger_ende);
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
