# Die Brügge auf macOS und Linux — Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das X-Plane-Plugin `FriesenBruegge.xpl` läuft zusätzlich auf macOS (Universal) und
Linux, gebaut aus einem Quelltext in GitHub Actions, ausgeliefert als ein ZIP mit allen drei
Plattformen.

**Architecture:** Windows behält WinHTTP; POSIX bekommt libcurl, das in `XPluginStart` per
`dlopen` geholt wird. Netz- und Threadschicht wandern in eine eigene Datei ohne XPLM-Bezug,
damit sie sich ohne Simulator messen lassen. Thread, Wecker und Zeit laufen künftig auf der
C++-Standardbibliothek — auf allen drei Plattformen gemeinsam.

**Tech Stack:** C++17, X-Plane SDK 4.3.0 (XPSDK430), libcurl (per `dlopen`), WinHTTP (Windows),
GitHub Actions (`windows-latest`, `macos-latest`, `ubuntu-22.04`), pytest für die
Quelltext-Tests.

**Spec:** `docs/superpowers/specs/2026-09-13-bruegge-posix-design.md`

## Global Constraints

- **Kein XPLM-Aufruf im Netzthread.** Das SDK ist nicht threadsicher; der Thread sieht nur
  `char`-Puffer.
- **`CURLOPT_NOSIGNAL 1L` ist Pflicht** — ohne sie beendet ein `SIGPIPE` den X-Plane-Prozess.
- **Jede `long`-Option an `curl_easy_setopt` bekommt ein `long`-Literal** (`15L`, nicht `15`),
  jedes `curl_easy_getinfo`-Ziel ist ein `long`. Sonst bricht es auf arm64-macOS.
- **Funktionszeiger auf `curl_easy_setopt`/`curl_easy_getinfo` werden variadisch deklariert.**
- **`dlopen`/`dlsym` nur in `XPluginStart`**, nie im Netzthread.
- **Suchreihenfolge:** macOS `/usr/lib/libcurl.4.dylib` vor `libcurl.4.dylib`; Linux
  `libcurl.so.4` vor `libcurl-gnutls.so.4`. Auf macOS **kein** `access()`-Vorabtest.
- **Keine locale-abhängige Zahlenein-/ausgabe** in `json.h` (kein `%f`, kein `strtod`).
- **X-Plane-Mindestversionen:** macOS 10.15 (x86_64) bzw. 11.0 (arm64), Linux gebaut auf
  `ubuntu-22.04`, **ohne** `-static-libstdc++`.
- **Plattformordner:** `win_x64`, `mac_x64` (auch für Apple Silicon), `lin_x64`.
- **`fassung.json` bleibt auf Pfadtiefe ≤ 1 im ZIP** (`_efb_package_version`, `app/main.py:627`).
- **Brügge-Fassung:** `1.1.0`. FriesenSpy: MINOR unter 14.x, `"highlight": false`.
- **Kein automatischer Upload** aus der CI. Hochgeladen wird von Hand, nach dem Kontrollstart.
- **Sprache:** Quelltext-Kommentare, Logzeilen und Doku auf Deutsch, wie im übrigen Ordner.

---

## Dateien

| Datei | Zuständigkeit |
|---|---|
| `friesenbruegge/json.h` | **ändern** — locale-freies Schreiben und Lesen von Zahlen |
| `friesenbruegge/xplane/netz.h` | **neu** — Netz- und Threadschicht, beide Plattformen, **ohne XPLM-Bezug** |
| `friesenbruegge/xplane/bruegge.cpp` | **ändern** — bindet `netz.h` ein, `XPLM_USE_NATIVE_PATHS`, Fassung 1.1.0 |
| `friesenbruegge/xplane/LIESMICH.txt` | **neu** — Vorlage, zieht aus `paket.ps1` um |
| `friesenbruegge/xplane/pruefen/json_locale.cpp` | **neu** — belegt, dass Zahlen locale-fest sind |
| `friesenbruegge/xplane/pruefen/netz_pruefen.cpp` | **neu** — fährt `netz.h` ohne Simulator |
| `friesenbruegge/xplane/pruefen/laden.c` | **neu** — `dlopen`-Rauchtest für die gebaute `.xpl` |
| `friesenbruegge/xplane/pruefen/pruefen.sh` | **neu** — ruft alles der Reihe nach auf |
| `tests/test_bruegge_quelltext.py` | **neu** — pytest bewacht die Fallstricke dauerhaft |
| `.github/workflows/bruegge-xplane.yml` | **neu** — vier Jobs, ein ZIP als Artefakt |
| `friesenbruegge/xplane/paket.ps1` | **ändern** — behält nur `-Hochladen` |
| `app/static/efb.html` | **ändern** — Plattformhinweis am X-Plane-Kasten |
| `app/CHANGELOG.json` | **ändern** — ein MINOR-Eintrag |

---

## Task 1: `json.h` rechnet ohne Locale

**Files:**
- Modify: `friesenbruegge/json.h:44-55` (`zahl`), `:92-104` (`json_zahl`), `:181-198` (`json_zahl_in`)
- Create: `friesenbruegge/xplane/pruefen/json_locale.cpp`

**Interfaces:**
- Consumes: nichts
- Produces: `zahl_nach_text(char* aus, size_t n, double wert, int stellen)` und
  `text_nach_zahl(const char* p, const char** ende)` als freie `inline`-Funktionen in `json.h`,
  oberhalb von `class JsonSchreiber`. `JsonSchreiber::zahl` und beide Lesefunktionen rufen sie.

> **Warum zuerst:** `json.h` wird von der MSFS- **und** der X-Plane-Brügge geteilt. Wer später
> anfängt, baut auf einer Datei auf, die sich noch ändert.

- [ ] **Step 1: Die deutsche Locale auf dem Prüfrechner bereitstellen**

Ohne sie kann der Test nicht beweisen, worum es geht — `setlocale` gäbe `nullptr` zurück und
der Test liefe grün, ohne etwas zu prüfen.

```bash
locale -a | grep -q '^de_DE.utf8$' || sudo locale-gen de_DE.UTF-8
locale -a | grep '^de_DE'
```

Erwartet: `de_DE.utf8`

- [ ] **Step 2: Den fehlschlagenden Test schreiben**

`friesenbruegge/xplane/pruefen/json_locale.cpp`:

```cpp
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
        std::printf("  FEHLER %s: \"%s\" statt \"%s\"\n", was, ist, soll);
        ++fehler;
    }
}

static void nahe(const char* was, double ist, double soll) {
    if (std::fabs(ist - soll) > 1e-9) {
        std::printf("  FEHLER %s: %.12g statt %.12g\n", was, ist, soll);
        ++fehler;
    }
}

static void durchlauf(const char* wie) {
    std::printf("Locale: %s\n", wie);

    char puffer[256];
    JsonSchreiber s(puffer, sizeof(puffer));
    s.roh("{");
    s.name("lat"); s.zahl(52.12345); s.komma();
    s.name("lon"); s.zahl(-7.5, 5); s.komma();
    s.name("null"); s.zahl(0.0, 1); s.komma();
    s.name("rund"); s.zahl(1.999999, 3);
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
    if (std::setlocale(LC_ALL, "de_DE.UTF-8")) {
        durchlauf("de_DE.UTF-8");
    } else {
        std::printf("  FEHLER: de_DE.UTF-8 nicht verfuegbar -- der Test prueft dann nichts.\n");
        ++fehler;
    }
    std::printf(fehler ? "\n%d Fehler\n" : "\nalles gut\n", fehler);
    return fehler ? 1 : 0;
}
```

- [ ] **Step 3: Den Test laufen lassen und scheitern sehen**

```bash
cd ~/projects/friesenspy/friesenbruegge/xplane/pruefen
g++ -std=c++17 -O1 -o json_locale json_locale.cpp && ./json_locale
```

Erwartet: Der Durchlauf `C` ist grün, der Durchlauf `de_DE.UTF-8` meldet
`FEHLER geschrieben: "{"lat":52,12345,…"` und `FEHLER lat: 53 statt 53.5`.
**Genau das ist der Fehler, der einen deutschen Piloten getroffen hätte.**

- [ ] **Step 4: Die beiden Rechenwege in `json.h` einbauen**

Direkt über `class JsonSchreiber` einfügen:

```cpp
// ---------------------------------------------------------------------------------------
// Zahlen ohne Locale
// ---------------------------------------------------------------------------------------
//
// `snprintf("%.*f")` und `strtod` fragen beide LC_NUMERIC. Setzt irgendwer im Prozess
// setlocale(LC_ALL, "") -- X-Plane selbst oder ein anderes Plugin, prozessweit --, dann
// schreibt die Bruegge bei einem deutschen Piloten 52,123 und der Server antwortet 400.
// Ganzzahlformate (%lld) sind davon nicht betroffen; nur sie werden hier benutzt.

inline void zahl_nach_text(char* aus, size_t n, double wert, int stellen) {
    if (n == 0) return;
    if (stellen < 0) stellen = 0;
    if (stellen > 9) stellen = 9;

    // NaN, Unendlich und alles jenseits von long long: JSON kennt dafuer keine Schreibweise.
    // Eine 0 ist falsch, aber gueltig -- abgehacktes JSON waere schlimmer.
    if (!(wert > -1e15 && wert < 1e15)) { std::snprintf(aus, n, "0"); return; }

    static const long long ZEHN[10] = {1LL, 10LL, 100LL, 1000LL, 10000LL, 100000LL,
                                       1000000LL, 10000000LL, 100000000LL, 1000000000LL};
    bool minus = wert < 0.0;
    if (minus) wert = -wert;

    long long faktor = ZEHN[stellen];
    long long ganz = (long long)wert;
    long long nach = (long long)((wert - (double)ganz) * (double)faktor + 0.5);
    if (nach >= faktor) { nach -= faktor; ganz += 1; }        // 1.9999 mit 3 Stellen -> 2.000

    char tmp[64];
    int pos = 0;
    if (minus && (ganz != 0 || nach != 0)) tmp[pos++] = '-';   // kein "-0.00000"
    pos += std::snprintf(tmp + pos, sizeof(tmp) - pos, "%lld", ganz);
    if (stellen > 0) {
        tmp[pos++] = '.';
        pos += std::snprintf(tmp + pos, sizeof(tmp) - pos, "%0*lld", stellen, nach);
    }
    tmp[pos] = '\0';
    std::snprintf(aus, n, "%s", tmp);
}

// Liest [+-]ddd[.ddd][eE[+-]ddd]. `ende` zeigt danach auf das erste nicht verbrauchte
// Zeichen -- wie bei strtod, damit die Aufrufer unveraendert bleiben. Bleibt `ende` auf dem
// Anfang stehen, stand dort keine Zahl.
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
        const char* merk = p;                  // ein 'e' ohne Ziffern gehoert nicht dazu
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
```

- [ ] **Step 5: Die drei Aufrufstellen umstellen**

`JsonSchreiber::zahl` (Zeile 45):

```cpp
    void zahl(double wert, int stellen = 5) {
        char tmp[48];
        zahl_nach_text(tmp, sizeof(tmp), wert, stellen);
        roh(tmp);
    }
```

In `json_zahl` und `json_zahl_in` je den `strtod`-Block ersetzen:

```cpp
    const char* ende = nullptr;
    double wert = text_nach_zahl(p, &ende);
    return (ende == p) ? vorgabe : wert;
```

⚠ In `json_zahl_in` heißt die Variable `zeiger_ende` — **beide Vorkommen** anpassen, und
`char*` wird zu `const char*`.

- [ ] **Step 6: Test laufen lassen, beide Durchläufe müssen grün sein**

```bash
cd ~/projects/friesenspy/friesenbruegge/xplane/pruefen
g++ -std=c++17 -O1 -o json_locale json_locale.cpp && ./json_locale
```

Erwartet: `alles gut`, Rückgabewert 0.

- [ ] **Step 7: Gegenprobe, dass nichts anderes kaputtging**

`json.h` wird auch von der MSFS-Brügge benutzt. Der Übersetzungstest genügt hier, geflogen
wird sie in diesem Plan nicht:

```bash
cd ~/projects/friesenspy/friesenbruegge
g++ -std=c++17 -fsyntax-only -x c++ json.h && echo "json.h uebersetzt"
```

- [ ] **Step 8: Committen**

```bash
cd ~/projects/friesenspy
git add friesenbruegge/json.h friesenbruegge/xplane/pruefen/json_locale.cpp
git commit -m "json.h rechnet ohne Locale -- sonst meldet ein deutscher Pilot 52,123"
```

---

## Task 2: `XPLM_USE_NATIVE_PATHS`, und ein Test, der es bewacht

**Files:**
- Modify: `friesenbruegge/xplane/bruegge.cpp` (in `XPluginStart`, vor Zeile 1120)
- Create: `tests/test_bruegge_quelltext.py`

**Interfaces:**
- Consumes: nichts
- Produces: `tests/test_bruegge_quelltext.py` mit der Hilfsfunktion
  `quelltext(name: str) -> str` (liest eine Datei aus `friesenbruegge/` **ohne Kommentare**);
  spätere Tasks hängen weitere Tests an dieselbe Datei.

> **Warum ein Quelltext-Test:** Für C++ gibt es hier keine Suite, und die Fallstricke dieses
> Plans sind allesamt „eine Zeile fehlt". Das Repo prüft an anderer Stelle bereits Quelldateien
> als Text (`test_kutter_eventloop.py` durchsucht `app/main.py`). Wichtig dabei: **an den Code
> binden, nicht an Kommentare** — deshalb entfernt `quelltext()` sie vorher.

- [ ] **Step 1: Den fehlschlagenden Test schreiben**

`tests/test_bruegge_quelltext.py`:

```python
"""Prueft den C++-Quelltext der Bruegge auf die Fallstricke aus
`docs/superpowers/specs/2026-09-13-bruegge-posix-design.md`.

Fuer C++ gibt es hier keine Testsuite, und jeder dieser Funde ist "eine Zeile fehlt" --
genau das laesst sich als Text pruefen. Kommentare werden vorher entfernt: Sonst findet
die Suche die Erklaerung statt der Anweisung.
"""
import re
from pathlib import Path

BRUEGGE = Path(__file__).resolve().parent.parent / "friesenbruegge"


def quelltext(name: str) -> str:
    """Dateiinhalt ohne // - und /* */ - Kommentare."""
    roh = (BRUEGGE / name).read_text(encoding="utf-8")
    ohne_block = re.sub(r"/\*.*?\*/", " ", roh, flags=re.S)
    return re.sub(r"//[^\n]*", "", ohne_block)


def test_native_paths_ist_eingeschaltet():
    """Ohne diese Zeile liefert XPLMGetSystemPath auf macOS HFS-Pfade mit Doppelpunkten.
    Dann findet die Bruegge ihre .url-Datei nie -- der Pruefserver-Weg waere auf dem Mac tot."""
    q = quelltext("xplane/bruegge.cpp")
    assert 'XPLMEnableFeature("XPLM_USE_NATIVE_PATHS", 1)' in q


def test_native_paths_steht_vor_jedem_pfadzugriff():
    """Die Reihenfolge ist der ganze Punkt: nach dem ersten fopen waere die Zeile wirkungslos."""
    q = quelltext("xplane/bruegge.cpp")
    feature = q.index('XPLMEnableFeature("XPLM_USE_NATIVE_PATHS"')
    for aufruf in ("ziel_laden()", "kennung_laden_oder_erzeugen()"):
        assert feature < q.index(aufruf), f"{aufruf} laeuft vor XPLMEnableFeature"


def test_json_h_rechnet_ohne_locale():
    """%f und strtod fragen LC_NUMERIC. Ein deutscher Pilot meldete sonst 52,123."""
    q = quelltext("json.h")
    assert "strtod" not in q
    assert '"%.*f"' not in q
```

- [ ] **Step 2: Laufen lassen und scheitern sehen**

```bash
cd ~/projects/friesenspy
/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_bruegge_quelltext.py -v
```

Erwartet: die beiden `native_paths`-Tests FAILEN, `test_json_h_rechnet_ohne_locale` ist grün
(Task 1 hat es erledigt).

- [ ] **Step 3: Die Zeile einbauen**

In `XPluginStart`, **vor** `ziel_laden()` (Zeile 1120):

```cpp
    // Ohne diese Zeile liefert XPLMGetSystemPath auf macOS einen klassischen HFS-Pfad mit
    // Doppelpunkten ("Macintosh HD:Applications:X-Plane 12:"), den fopen nicht oeffnet --
    // die .url-Datei fuer den Pruefserver waere dort unauffindbar. Unter Windows dreht sie
    // die Schraegstriche von \ auf /; fopen traegt beides.
    XPLMEnableFeature("XPLM_USE_NATIVE_PATHS", 1);
```

- [ ] **Step 4: Test laufen lassen**

```bash
/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_bruegge_quelltext.py -v
```

Erwartet: 3 passed.

- [ ] **Step 5: Committen**

```bash
git add tests/test_bruegge_quelltext.py friesenbruegge/xplane/bruegge.cpp
git commit -m "XPLM_USE_NATIVE_PATHS -- ohne sie ist der Pruefserver-Weg auf dem Mac tot"
```

---

## Task 3: Netz- und Threadschicht in `netz.h` herauslösen

**Files:**
- Create: `friesenbruegge/xplane/netz.h`
- Modify: `friesenbruegge/xplane/bruegge.cpp` (Zeilen 52–53, 78, 90–91, 405–630 entfernen bzw. ersetzen)

**Interfaces:**
- Consumes: `json.h` (unverändert)
- Produces — **die vollständige Schnittstelle, an die sich Task 4 und 5 halten:**

```cpp
// netz.h
struct NetzMeldung { char text[16384]; long code; bool zu_gross; };

bool netz_bereit(char* fehler, size_t n);   // laedt libcurl (POSIX) / prueft (Windows)
void netz_ziel(const char* host, unsigned port, const char* pfad, bool sicher,
               const char* volle_url);
void netz_start();                          // startet den Thread
void netz_senden(const char* json);         // Puffer fuellen, Thread wecken
bool netz_antwort(NetzMeldung* aus);        // true, wenn eine neue Antwort vorliegt
void netz_ende();                           // wecken, joinen, aufraeumen
```

> **Warum eine eigene Datei:** Abschnitt 10 der Spec. Ohne sie lässt sich die Netz- und
> Threadschicht nicht ohne X-Plane übersetzen — und damit vor der Auslieferung **gar nicht**
> messen. `netz.h` enthält **keinen einzigen** XPLM-Bezug; Logzeilen gibt sie über einen
> Rückruf heraus, den `bruegge.cpp` setzt und aus dem **Hauptthread** abholt.

- [ ] **Step 1: Den Test schreiben, der die Trennung erzwingt**

An `tests/test_bruegge_quelltext.py` anhängen:

```python
def test_netz_h_kennt_kein_xplm():
    """netz.h muss ohne das SDK uebersetzbar bleiben -- sonst ist es ohne Simulator nicht
    messbar, und genau das ist der einzige Test, den macOS und Linux vor dem Piloten kriegen."""
    q = quelltext("xplane/netz.h")
    assert "XPLM" not in q


def test_netzthread_meldet_nicht_selbst_ins_log():
    """Das SDK ist nicht threadsicher. Eine XPLMDebugString-Zeile im Netzthread reicht fuer
    einen Absturz, den niemand reproduziert."""
    q = quelltext("xplane/netz.h")
    assert "XPLMDebugString" not in q
```

- [ ] **Step 2: Laufen lassen und scheitern sehen**

```bash
/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_bruegge_quelltext.py -v
```

Erwartet: beide neuen Tests FAILEN mit `FileNotFoundError` — `netz.h` gibt es noch nicht.

- [ ] **Step 3: `netz.h` anlegen und den Windows-Code unverändert hineinziehen**

Verschoben werden aus `bruegge.cpp`: `#include <windows.h>`/`<winhttp.h>` (52–53), das
`#pragma comment` (78), `BRUEGGE_HOST`/`BRUEGGE_PFAD` als `L"…"` (90–91), die Globals
(435–438, 417–420) und die Funktionen `netz_schliessen`, `netz_oeffnen`, `netz_lauf`,
`netz_senden` (507–630).

**Noch nichts umbauen.** Dieser Schritt ist reines Verschieben; die Windows-Fassung muss danach
zeichengleich dasselbe tun. Der Kopf der Datei:

```cpp
#pragma once
// Netz und Nebenlaeufigkeit der FriesenBruegge -- OHNE jeden Bezug auf das X-Plane-SDK.
//
// Diese Trennung ist kein Selbstzweck: Sie ist die Bedingung dafuer, dass sich die Schicht
// ohne Simulator uebersetzen und messen laesst (pruefen/netz_pruefen.cpp). Fuer macOS und
// Linux ist das der einzige Test, den es vor dem ersten Piloten gibt.
//
// Logzeilen gehen NICHT von hier ins Log: Das SDK ist nicht threadsicher. Sie landen in
// einem Puffer, den bruegge.cpp aus dem Hauptthread abholt.
```

Die Logzeilen des Netzthreads gehen in einen Ringpuffer:

```cpp
// Bis zu acht Zeilen; wer mehr erzeugt, verliert die aeltesten. Ein Netzthread, der
// schneller meldet, als die Flugschleife abholt, hat ohnehin ein anderes Problem.
void netz_log_abholen(void (*ausgeben)(const char*));
```

- [ ] **Step 4: Übersetzen — `netz.h` allein, ohne SDK**

```bash
cd ~/projects/friesenspy/friesenbruegge/xplane
g++ -std=c++17 -fsyntax-only -x c++ netz.h 2>&1 | head -20
```

Erwartet unter Linux: Fehler wegen `windows.h` — **das ist an dieser Stelle richtig**, die
POSIX-Seite kommt erst in Task 5. Der Test aus Step 1 prüft nur, dass kein XPLM darin steht.

- [ ] **Step 5: Tests laufen lassen**

```bash
/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_bruegge_quelltext.py -v
```

Erwartet: 5 passed.

- [ ] **Step 6: Committen**

```bash
git add friesenbruegge/xplane/netz.h friesenbruegge/xplane/bruegge.cpp tests/test_bruegge_quelltext.py
git commit -m "Netz und Thread in netz.h -- ohne SDK-Bezug, sonst ist nichts messbar"
```

---

## Task 4: Thread, Wecker und Zeit auf die Standardbibliothek

**Files:**
- Modify: `friesenbruegge/xplane/netz.h` (Thread-Teil), `friesenbruegge/xplane/bruegge.cpp`
  (`kennung_erzeugen`, `XPluginStop`)
- Create: `friesenbruegge/xplane/pruefen/netz_pruefen.cpp` (erster Teil)

**Interfaces:**
- Consumes: die Schnittstelle aus Task 3
- Produces: `netz_start()`, `netz_ende()` und `netz_senden()` verhalten sich auf allen drei
  Plattformen gleich; `netz_ende()` kehrt garantiert zurück, ohne `std::terminate`.

> **Die drei Ausgleiche aus Spec Abschnitt 5.** Alle drei betreffen auch Windows, also die
> geflogene Fassung.

- [ ] **Step 1: Den Test schreiben, der den verlorenen Weckruf sichtbar macht**

`friesenbruegge/xplane/pruefen/netz_pruefen.cpp`, erster Teil:

```cpp
// Faehrt die Thread- und Netzschicht ohne Simulator.
//
// Teil 1 (dieser Task) prueft die Nebenlaeufigkeit: Ein Weckruf darf nicht verlorengehen,
// und netz_ende() muss zurueckkehren, auch wenn gerade niemand wartet.
#include <chrono>
#include <cstdio>
#include <cstring>
#include <thread>
#include "../netz.h"

static int fehler = 0;

static void pruefe(const char* was, bool gut) {
    std::printf("  %-46s %s\n", was, gut ? "ok" : "FEHLER");
    if (!gut) ++fehler;
}

// Der verlorene Weckruf: senden, BEVOR der Thread ueberhaupt schlafen geht. Ein Win32-Event
// merkt sich das; eine condition_variable nicht. Ohne Praedikat im wait() bliebe die
// Meldung liegen und netz_ende() haenge im join.
static void weckruf_vor_dem_warten() {
    char fehlertext[256] = {0};
    if (!netz_bereit(fehlertext, sizeof(fehlertext))) {
        std::printf("  netz_bereit: %s\n", fehlertext);
        ++fehler;
        return;
    }
    netz_ziel("127.0.0.1", 8099, "/api/bruegge/melden", false,
              "http://127.0.0.1:8099/api/bruegge/melden");
    netz_start();
    netz_senden("{\"kennung\":\"pruef\"}");

    auto anfang = std::chrono::steady_clock::now();
    netz_ende();
    auto dauer = std::chrono::steady_clock::now() - anfang;
    pruefe("netz_ende kehrt binnen 20 s zurueck",
           std::chrono::duration_cast<std::chrono::seconds>(dauer).count() < 20);
}

int main() {
    std::printf("Teil 1 -- Nebenlaeufigkeit\n");
    weckruf_vor_dem_warten();
    std::printf(fehler ? "\n%d Fehler\n" : "\nalles gut\n", fehler);
    return fehler ? 1 : 0;
}
```

- [ ] **Step 2: Laufen lassen und scheitern sehen**

```bash
cd ~/projects/friesenspy/friesenbruegge/xplane/pruefen
g++ -std=c++17 -pthread -o netz_pruefen netz_pruefen.cpp 2>&1 | head -5
```

Erwartet: Übersetzung schlägt fehl (`windows.h` fehlt). **Das ist der erwartete Zustand** —
Task 5 liefert die POSIX-Seite. Der Test wird am Ende von Task 5 zum ersten Mal grün.

- [ ] **Step 3: Die Thread-Schicht umbauen**

In `netz.h`, plattformunabhängig:

```cpp
#include <atomic>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <thread>

static std::unique_ptr<std::thread> g_netz_thread;   // Zeiger, NICHT global by value:
                                                     // ein joinable Thread im Destruktor
                                                     // einer entladenen Bibliothek ruft
                                                     // std::terminate -- X-Plane stirbt
                                                     // beim Beenden.
static std::mutex              g_schloss;
static std::condition_variable g_wecker;
static bool                    g_ausgang_voll = false;
static std::atomic<bool>       g_netz_ende{false};
```

Der Wartepunkt bekommt ein **Prädikat** — das ist der Ausgleich für den verlorenen Weckruf:

```cpp
    std::unique_lock<std::mutex> sperre(g_schloss);
    g_wecker.wait(sperre, [] { return g_ausgang_voll || g_netz_ende.load(); });
```

Wecken immer **unter dem Schloss**, erst danach `notify`:

```cpp
void netz_senden(const char* text) {
    {
        std::lock_guard<std::mutex> sperre(g_schloss);
        std::snprintf(g_ausgang, sizeof(g_ausgang), "%s", text);
        g_ausgang_voll = true;
    }
    g_wecker.notify_one();
}

void netz_ende() {
    {
        std::lock_guard<std::mutex> sperre(g_schloss);
        g_netz_ende.store(true);
    }
    g_wecker.notify_all();
    if (g_netz_thread && g_netz_thread->joinable()) g_netz_thread->join();
    g_netz_thread.reset();
    netz_schliessen();
}
```

⚠ **`join()` statt `WaitForSingleObject(…, 20000)`:** Die alte Fassung gab nach 20 s auf,
`join()` wartet unbegrenzt. Die Obergrenze ist damit `CURLOPT_TIMEOUT` (15 s) plus
Namensauflösung. `detach()` wäre die Alternative und scheidet aus: X-Plane entlädt das Plugin
nach `XPluginStop`, und ein Thread, der dann noch in Plugin-Code steht, stürzt beim Rücksprung ab.

- [ ] **Step 4: `kennung_erzeugen` plattformfrei machen**

In `bruegge.cpp` (Zeilen 214–218):

```cpp
static void kennung_erzeugen() {
    // Eindeutig muss sie sein, nicht unvorhersagbar.
#if defined(_WIN32)
    unsigned long long a = (unsigned long long)_getpid();
#else
    unsigned long long a = (unsigned long long)getpid();
#endif
    unsigned long long b = (unsigned long long)
        std::chrono::steady_clock::now().time_since_epoch().count();
    unsigned long long c = (unsigned long long)(uintptr_t)&g_soll[0];
    std::snprintf(g_kennung, sizeof(g_kennung), "%08llx%08llx",
                  (a ^ (c >> 8)) & 0xFFFFFFFFull, (b ^ (c << 4)) & 0xFFFFFFFFull);
}
```

Dazu oben: `#include <chrono>` und `#if defined(_WIN32) #include <process.h> #else #include <unistd.h> #endif`.

- [ ] **Step 5: Test anhängen, der die Win32-Reste bewacht**

An `tests/test_bruegge_quelltext.py`:

```python
WIN32_RESTE = ("CreateThread", "CRITICAL_SECTION", "EnterCriticalSection",
               "WaitForSingleObject", "SetEvent", "GetTickCount64", "GetCurrentProcessId")


def test_keine_win32_nebenlaeufigkeit_mehr():
    """Thread, Wecker und Zeit laufen auf der Standardbibliothek -- auf ALLEN drei
    Plattformen, sonst pflegen wir zwei Thread-Schichten und pruefen nur eine."""
    for datei in ("xplane/netz.h", "xplane/bruegge.cpp"):
        q = quelltext(datei)
        for name in WIN32_RESTE:
            assert name not in q, f"{name} steht noch in {datei}"


def test_wait_hat_ein_praedikat():
    """Eine condition_variable merkt sich keinen Weckruf. Ohne Praedikat geht die Meldung
    verloren, der Thread schlaeft ewig und netz_ende haengt im join."""
    q = quelltext("xplane/netz.h")
    assert "g_wecker.wait(" in q
    stelle = q.index("g_wecker.wait(")
    assert "[" in q[stelle:stelle + 120], "wait() ohne Praedikat"


def test_thread_wird_nicht_global_gehalten():
    """Ein globaler std::thread, der beim Entladen noch joinable ist, ruft std::terminate."""
    q = quelltext("xplane/netz.h")
    assert "std::unique_ptr<std::thread>" in q
```

- [ ] **Step 6: Tests laufen lassen**

```bash
/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_bruegge_quelltext.py -v
```

Erwartet: 8 passed.

- [ ] **Step 7: Committen**

```bash
git add friesenbruegge/xplane/netz.h friesenbruegge/xplane/bruegge.cpp \
        friesenbruegge/xplane/pruefen/netz_pruefen.cpp tests/test_bruegge_quelltext.py
git commit -m "Thread und Wecker auf die Standardbibliothek -- mit den drei Ausgleichen"
```

---

## Task 5: Die POSIX-Netzschicht mit libcurl

**Files:**
- Modify: `friesenbruegge/xplane/netz.h`
- Modify: `friesenbruegge/xplane/bruegge.cpp` (`XPluginStart` ruft `netz_bereit` vor `netz_start`)

**Interfaces:**
- Consumes: die Schnittstelle aus Task 3, die Thread-Schicht aus Task 4
- Produces: `netz_bereit()` liefert unter POSIX `false` mit Text, wenn libcurl fehlt; `netz.h`
  übersetzt auf Linux und macOS ohne SDK.

- [ ] **Step 1: Die Header-Voraussetzung schaffen**

`curl/curl.h` fehlt auf dieser Maschine. Der Header wird gebraucht, damit Konstanten und die
variadische Signatur aus **einer** Quelle kommen statt abgeschriebener Zahlen — gelinkt wird
trotzdem nicht gegen libcurl.

```bash
sudo apt-get install -y libcurl4-openssl-dev
ls -l /usr/include/x86_64-linux-gnu/curl/curl.h
```

- [ ] **Step 2: Den zweiten Teil des Prüfprogramms schreiben**

An `netz_pruefen.cpp` anhängen (vor `main`) und in `main` aufrufen:

```cpp
// Teil 2 -- die Netzschicht gegen den ECHTEN Endpunkt. Ohne VATSIM antwortet der Server mit
// HTTP 200 und leerem soll; als Beleg fuer TLS, Zertifikatsspeicher und JSON genuegt das.
static void gegen_den_echten_server() {
    char fehlertext[256] = {0};
    pruefe("libcurl gefunden", netz_bereit(fehlertext, sizeof(fehlertext)));
    netz_ziel("friesenspy.devprops.de", 443, "/api/bruegge/melden", true,
              "https://friesenspy.devprops.de/api/bruegge/melden");
    netz_start();

    netz_senden("{\"kennung\":\"pruefpruefpruef01\",\"fassung\":\"1.1.0\","
                "\"simulator\":\"xplane12\",\"lage\":{\"lat\":53.7,\"lon\":7.15,"
                "\"alt_ft\":1200.0,\"kurs\":90.0,\"gs_kt\":95.0},\"steht\":[]}");

    NetzMeldung m{};
    bool kam = false;
    for (int i = 0; i < 200 && !kam; ++i) {           // bis 20 s
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        kam = netz_antwort(&m);
    }
    pruefe("Antwort kam an", kam);
    pruefe("HTTP 200 -- das JSON ist gueltig", kam && m.code == 200);
    pruefe("Antwort passte in den Puffer", kam && !m.zu_gross);
    if (kam) std::printf("    Antwort: %.120s\n", m.text);
    netz_ende();
}
```

- [ ] **Step 3: Laufen lassen und scheitern sehen**

```bash
cd ~/projects/friesenspy/friesenbruegge/xplane/pruefen
g++ -std=c++17 -pthread -o netz_pruefen netz_pruefen.cpp -ldl 2>&1 | head -5
```

Erwartet: Übersetzungsfehler — die POSIX-Seite fehlt noch.

- [ ] **Step 4: Die POSIX-Netzschicht einbauen**

In `netz.h`, hinter dem Windows-Block:

```cpp
#else   // ---------------- POSIX: macOS und Linux ----------------

#include <curl/curl.h>
#include <dlfcn.h>

// Geholt wird zur Laufzeit. Ein Plugin mit unaufloesbarem Symbol wird von X-Plane gar nicht
// erst geladen -- der Pilot saehe nur eine Zeile in einem riesigen Log.txt. So startet die
// Bruegge, findet libcurl nicht und SAGT es.
//
// ⚠ setopt und getinfo sind VARIADISCH und muessen auch so deklariert werden: Apple uebergibt
// variadische Argumente auf arm64 ueber den Stack statt in Registern. Als gewoehnliche
// Funktion deklariert ginge es auf Intel zufaellig gut und braeche auf Apple Silicon.
using curl_init_fn    = CURL*     (*)();
using curl_setopt_fn  = CURLcode  (*)(CURL*, CURLoption, ...);
using curl_perform_fn = CURLcode  (*)(CURL*);
using curl_getinfo_fn = CURLcode  (*)(CURL*, CURLINFO, ...);
using curl_cleanup_fn = void      (*)(CURL*);
using curl_slist_add_fn  = curl_slist* (*)(curl_slist*, const char*);
using curl_slist_frei_fn = void        (*)(curl_slist*);
using curl_version_fn = char*     (*)();

static void*            g_curl_lib = nullptr;
static curl_init_fn     c_init     = nullptr;
static curl_setopt_fn   c_setopt   = nullptr;
static curl_perform_fn  c_perform  = nullptr;
static curl_getinfo_fn  c_getinfo  = nullptr;
static curl_cleanup_fn  c_cleanup  = nullptr;
static curl_slist_add_fn  c_slist_add  = nullptr;
static curl_slist_frei_fn c_slist_frei = nullptr;
static curl_version_fn  c_version  = nullptr;

// ⚠ Reihenfolge: der volle Pfad zuerst. Ein nackter Name durchsucht auf macOS die
// Fallback-Pfade -- auf einem Intel-Mac mit Homebrew gewaenne dessen curl mit eigenem
// OpenSSL statt Apples Bibliothek mit Keychain-Vertrauen.
// ⚠ Und KEIN access()-Vorabtest: Seit Big Sur liegen Systembibliotheken im dyld-Cache,
// nicht als Datei. access() schlaegt fehl, dlopen gelingt.
static const char* const CURL_NAMEN[] = {
#if defined(__APPLE__)
    "/usr/lib/libcurl.4.dylib", "libcurl.4.dylib",
#else
    "libcurl.so.4", "libcurl-gnutls.so.4",
#endif
    nullptr
};

bool netz_bereit(char* fehler, size_t n) {
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
    c_init       = (curl_init_fn)      dlsym(g_curl_lib, "curl_easy_init");
    c_setopt     = (curl_setopt_fn)    dlsym(g_curl_lib, "curl_easy_setopt");
    c_perform    = (curl_perform_fn)   dlsym(g_curl_lib, "curl_easy_perform");
    c_getinfo    = (curl_getinfo_fn)   dlsym(g_curl_lib, "curl_easy_getinfo");
    c_cleanup    = (curl_cleanup_fn)   dlsym(g_curl_lib, "curl_easy_cleanup");
    c_slist_add  = (curl_slist_add_fn) dlsym(g_curl_lib, "curl_slist_append");
    c_slist_frei = (curl_slist_frei_fn)dlsym(g_curl_lib, "curl_slist_free_all");
    c_version    = (curl_version_fn)   dlsym(g_curl_lib, "curl_version");
    if (!c_init || !c_setopt || !c_perform || !c_getinfo || !c_cleanup ||
        !c_slist_add || !c_slist_frei) {
        std::snprintf(fehler, n, "libcurl gefunden, aber unvollstaendig.");
        return false;
    }
    // Welche Fassung wirklich antwortet, ist nicht selbstverstaendlich: dlopen kann eine
    // bereits von X-Plane geladene Kopie derselben SONAME liefern.
    std::snprintf(fehler, n, "libcurl: %s", c_version ? c_version() : "unbekannt");
    return true;
}
```

Der Sendeweg im Thread:

```cpp
    CURL* h = c_init();
    curl_slist* kopf = c_slist_add(nullptr, "Content-Type: application/json");
    // libcurl schickt sonst "Expect: 100-continue" und wartet auf die Zwischenantwort --
    // ein zusaetzlicher Umlauf je Meldung, im Sekundentakt spuerbar.
    kopf = c_slist_add(kopf, "Expect:");

    c_setopt(h, CURLOPT_URL, g_url);
    c_setopt(h, CURLOPT_HTTPHEADER, kopf);
    c_setopt(h, CURLOPT_POSTFIELDS, sendepuffer);
    c_setopt(h, CURLOPT_USERAGENT, "FriesenBruegge/" BRUEGGE_VERSION);
    // ⚠ PFLICHT: Ohne NOSIGNAL laesst libcurl bei gekappter Verbindung ein SIGPIPE zu --
    // und das beendet den PROZESS, also X-Plane, nicht nur das Plugin.
    c_setopt(h, CURLOPT_NOSIGNAL,       1L);
    c_setopt(h, CURLOPT_CONNECTTIMEOUT, 10L);
    c_setopt(h, CURLOPT_TIMEOUT,        15L);
    c_setopt(h, CURLOPT_WRITEFUNCTION,  netz_schreiben);
    c_setopt(h, CURLOPT_WRITEDATA,      &ziel);

    CURLcode r = c_perform(h);
    long code = 0;                       // ⚠ long, nicht int -- getinfo ist variadisch
    if (r == CURLE_OK) c_getinfo(h, CURLINFO_RESPONSE_CODE, &code);
```

⚠ **Jedes `long`-Literal mit `L`.** Ein `int` belegt 4 Byte in einem 8-Byte-Fach; libcurl liest
`va_arg(…, long)` und bekommt oben Müll. Auf x86-64 klappt es zufällig.

Der Schreib-Rückruf verwirft bei Überlauf **ganz**, statt halb zu lesen:

```cpp
static size_t netz_schreiben(char* stueck, size_t gr, size_t n, void* nutzer) {
    auto* z = (NetzMeldung*)nutzer;
    size_t kommt = gr * n;
    if (z->laenge + kommt >= sizeof(z->text)) { z->zu_gross = true; return 0; }
    std::memcpy(z->text + z->laenge, stueck, kommt);
    z->laenge += kommt;
    z->text[z->laenge] = '\0';
    return kommt;
}
```

- [ ] **Step 5: `XPluginStart` ruft `netz_bereit` vor `netz_start`**

```cpp
    char netztext[256] = {0};
    if (!netz_bereit(netztext, sizeof(netztext))) {
        logzeile(netztext);          // im Hauptthread -- hier ist XPLM erlaubt
    } else {
        logzeile(netztext);          // "libcurl: 8.5.0"
        netz_start();
    }
```

- [ ] **Step 6: Übersetzen und laufen lassen**

```bash
cd ~/projects/friesenspy/friesenbruegge/xplane/pruefen
g++ -std=c++17 -pthread -o netz_pruefen netz_pruefen.cpp -ldl && ./netz_pruefen
```

Erwartet: Teil 1 und Teil 2 grün, `HTTP 200`, Antwort mit `"takt"`.

- [ ] **Step 7: Die Fallstricke als Test verankern**

An `tests/test_bruegge_quelltext.py`:

```python
def test_nosignal_ist_gesetzt():
    """Ohne NOSIGNAL beendet ein SIGPIPE den X-Plane-Prozess, nicht nur das Plugin."""
    q = quelltext("xplane/netz.h")
    assert "CURLOPT_NOSIGNAL" in q


def test_long_optionen_tragen_ein_L():
    """Ein int belegt 4 Byte in einem 8-Byte-Fach; libcurl liest va_arg(long).
    Auf x86-64 klappt das zufaellig, auf arm64-macOS nicht."""
    q = quelltext("xplane/netz.h")
    for option in ("CURLOPT_NOSIGNAL", "CURLOPT_CONNECTTIMEOUT", "CURLOPT_TIMEOUT"):
        stelle = q.index(option)
        zeile = q[stelle:q.index("\n", stelle)]
        assert re.search(r",\s*\d+L\s*\)", zeile), f"{option} ohne L-Suffix: {zeile.strip()}"


def test_setopt_zeiger_ist_variadisch():
    """Apple uebergibt variadische Argumente auf arm64 ueber den Stack."""
    q = quelltext("xplane/netz.h")
    assert "(CURL*, CURLoption, ...)" in q
    assert "(CURL*, CURLINFO, ...)" in q


def test_kein_access_vorabtest_auf_die_bibliothek():
    """Seit Big Sur liegen Systembibliotheken im dyld-Cache, nicht als Datei."""
    q = quelltext("xplane/netz.h")
    assert "access(" not in q


def test_voller_pfad_vor_nacktem_namen():
    """Sonst gewinnt auf einem Intel-Mac das Homebrew-curl statt Apples Bibliothek."""
    q = quelltext("xplane/netz.h")
    assert q.index('"/usr/lib/libcurl.4.dylib"') < q.index('"libcurl.4.dylib"')


def test_dlopen_nicht_im_netzthread():
    """dlopen gehoert in XPluginStart: Der Fehlschlag muss ins Log, und das darf der
    Netzthread nicht (SDK nicht threadsicher)."""
    q = quelltext("xplane/bruegge.cpp")
    assert "netz_bereit(" in q
    assert q.index("netz_bereit(") < q.index("netz_start()")
```

- [ ] **Step 8: Alle Tests laufen lassen**

```bash
/home/claude/.venv-friesenspy/bin/python -m pytest tests/test_bruegge_quelltext.py -v
```

Erwartet: 14 passed.

- [ ] **Step 9: Committen**

```bash
git add friesenbruegge/xplane/netz.h friesenbruegge/xplane/bruegge.cpp \
        friesenbruegge/xplane/pruefen/netz_pruefen.cpp tests/test_bruegge_quelltext.py
git commit -m "POSIX-Netzschicht: libcurl per dlopen, NOSIGNAL, L-Suffixe, variadische Zeiger"
```

---

## Task 6: Der vollständige Prüflauf auf dem VPS

**Files:**
- Create: `friesenbruegge/xplane/pruefen/laden.c`, `friesenbruegge/xplane/pruefen/pruefen.sh`
- Modify: `friesenbruegge/xplane/pruefen/netz_pruefen.cpp` (Teil 3 und 4)

**Interfaces:**
- Consumes: alles aus Task 1–5
- Produces: `pruefen.sh` — ein Aufruf, der alles der Reihe nach misst und mit 0 endet, wenn
  alles gut ist. Die Ausgabe gehört in den Commit-Text der Auslieferung.

- [ ] **Step 1: Das SDK holen**

```bash
mkdir -p /tmp/xpsdk && cd /tmp/xpsdk
[ -d SDK ] || { curl -sSL -o sdk.zip \
  https://developer.x-plane.com/wp-content/plugins/code-sample-generation/sdk_zip_files/XPSDK430.zip \
  && unzip -q sdk.zip; }
ls SDK/CHeaders/XPLM/XPLMPlugin.h
```

- [ ] **Step 2: Teil 3 — gegen `pruefserver.py`**

An `netz_pruefen.cpp`:

```cpp
// Teil 3 -- gegen den Pruefserver (http, OHNE TLS). Das ist der Weg, den ein Mac-Pilot
// spaeter geht; er belegt Objekte und Abraeumen, aber ausdruecklich NICHT die TLS-Schicht.
static void gegen_den_pruefserver() {
    char fehlertext[256] = {0};
    netz_bereit(fehlertext, sizeof(fehlertext));
    netz_ziel("127.0.0.1", 8099, "/api/bruegge/melden", false,
              "http://127.0.0.1:8099/api/bruegge/melden");
    netz_start();
    netz_senden("{\"kennung\":\"pruefpruefpruef01\",\"fassung\":\"1.1.0\","
                "\"simulator\":\"xplane12\",\"lage\":{\"lat\":53.7,\"lon\":7.15},"
                "\"steht\":[]}");
    NetzMeldung m{};
    bool kam = false;
    for (int i = 0; i < 100 && !kam; ++i) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        kam = netz_antwort(&m);
    }
    pruefe("Pruefserver antwortet", kam && m.code == 200);
    pruefe("soll kam mit", kam && std::strstr(m.text, "soll") != nullptr);
    netz_ende();
}
```

- [ ] **Step 3: Teil 4 — der Abbruchtest für `CURLOPT_NOSIGNAL`**

```cpp
// Teil 4 -- der Server kappt mitten im Takt. OHNE CURLOPT_NOSIGNAL endet an dieser Stelle
// der PROZESS mit SIGPIPE, und dieses Programm gibt gar nichts mehr aus. Dass wir hier
// ueberhaupt eine Zeile lesen, IST das Ergebnis.
static void server_kappt_die_verbindung() {
    // Ein Horcher, der die Verbindung nach dem Annehmen sofort schliesst, laeuft nebenher
    // aus pruefen.sh (python3 -c ... auf Port 8098).
    char fehlertext[256] = {0};
    netz_bereit(fehlertext, sizeof(fehlertext));
    netz_ziel("127.0.0.1", 8098, "/api/bruegge/melden", false,
              "http://127.0.0.1:8098/api/bruegge/melden");
    netz_start();
    for (int i = 0; i < 5; ++i) {
        netz_senden("{\"kennung\":\"pruefpruefpruef01\",\"steht\":[]}");
        std::this_thread::sleep_for(std::chrono::milliseconds(300));
    }
    netz_ende();
    pruefe("Prozess lebt nach fuenf gekappten Verbindungen", true);
}
```

- [ ] **Step 4: Den `dlopen`-Rauchtest schreiben**

`friesenbruegge/xplane/pruefen/laden.c`:

```c
/* Laedt die gebaute .xpl und sucht XPluginStart. Die XPLM-Symbole bleiben dabei
 * unaufgeloest -- genau wie in X-Plane, das sie erst beim Laden bereitstellt.
 * Das ist der einzige Ladetest, den die Linux-Fassung vor dem ersten Piloten bekommt. */
#include <dlfcn.h>
#include <stdio.h>

int main(int argc, char** argv) {
    if (argc < 2) { fprintf(stderr, "Aufruf: laden <datei.xpl>\n"); return 2; }
    void* h = dlopen(argv[1], RTLD_LAZY | RTLD_LOCAL);
    if (!h) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
    void* s = dlsym(h, "XPluginStart");
    printf("XPluginStart: %s\n", s ? "gefunden" : "FEHLT");
    dlclose(h);
    return s ? 0 : 1;
}
```

- [ ] **Step 5: `pruefen.sh` schreiben**

```bash
#!/usr/bin/env bash
# Alles, was sich ohne Simulator ueber die Bruegge sagen laesst -- in einem Aufruf.
#
# Was dieser Lauf NICHT kann, steht in der Spec, Abschnitt 12: arm64-Aufrufkonvention,
# dyld-Namensaufloesung, Secure Transport, Deployment-Target, Gatekeeper und alles,
# was X-Plane braucht. Diese Maschine ist x86-64 mit OpenSSL.
set -euo pipefail
hier="$(cd "$(dirname "$0")" && pwd)"
sdk="${XPSDK:-/tmp/xpsdk/SDK}"
cd "$hier"

echo "== 1. Zahlen ohne Locale =="
g++ -std=c++17 -O1 -o json_locale json_locale.cpp && ./json_locale

echo "== 2. Die .xpl bauen (wie ubuntu-22.04 in der CI) =="
g++ -std=c++17 -shared -fPIC -fvisibility=hidden -pthread -DLIN=1 \
    -DXPLM200=1 -DXPLM210=1 -DXPLM300=1 -DXPLM301=1 -DXPLM400=1 -DXPLM410=1 \
    -I"$sdk/CHeaders/XPLM" -I"$sdk/CHeaders/Widgets" \
    -o FriesenBruegge.xpl ../bruegge.cpp -ldl

echo "== 3. Was das Binary verlangt und exportiert =="
nm -D --defined-only FriesenBruegge.xpl | grep -c XPlugin   # muss 5 sein
readelf -d FriesenBruegge.xpl | grep NEEDED                 # KEIN libcurl
objdump -T FriesenBruegge.xpl | grep -oE 'GLIBC(XX)?_[0-9.]+' | sort -Vu | tail -3

echo "== 4. Ladetest =="
gcc -o laden laden.c -ldl && ./laden ./FriesenBruegge.xpl

echo "== 5. Pruefserver im Hintergrund =="
python3 ../../pruefserver.py & pruef=$!
python3 -c "
import socket
s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR,1)
s.bind(('127.0.0.1',8098)); s.listen(8)
while True:
    k,_=s.accept(); k.close()      # sofort kappen -- der SIGPIPE-Test
" & kapper=$!
trap 'kill $pruef $kapper 2>/dev/null || true' EXIT
sleep 1

echo "== 6. Netz- und Threadschicht =="
g++ -std=c++17 -pthread -o netz_pruefen netz_pruefen.cpp -ldl && ./netz_pruefen

echo ""
echo "Alles durchgelaufen. Ungeprueft bleibt, was in Spec-Abschnitt 12 steht."
```

- [ ] **Step 6: Ausführbar machen und laufen lassen**

```bash
chmod +x friesenbruegge/xplane/pruefen/pruefen.sh
./friesenbruegge/xplane/pruefen/pruefen.sh
```

Erwartet: alle sechs Abschnitte ohne Fehler; `nm`-Zähler `5`, `readelf` ohne libcurl,
höchste Symbolversion sichtbar, `XPluginStart: gefunden`, Teil 1–4 grün.

- [ ] **Step 7: Committen**

```bash
git add friesenbruegge/xplane/pruefen/
git commit -m "Pruefen ohne Simulator: Bau, Ladetest, TLS, Pruefserver, SIGPIPE"
```

---

## Task 7: Der Workflow, das Paket, die Anleitung

**Files:**
- Create: `.github/workflows/bruegge-xplane.yml`, `friesenbruegge/xplane/LIESMICH.txt`
- Modify: `friesenbruegge/xplane/paket.ps1` (nur noch `-Hochladen`)
- Delete: `friesenbruegge/friesenbruegge-xplane.zip`

**Interfaces:**
- Consumes: die drei Bauwege aus Task 5 und 6
- Produces: ein Artefakt `friesenbruegge-xplane` mit `friesenbruegge-xplane.zip` darin

- [ ] **Step 1: `LIESMICH.txt` aus `paket.ps1` herausziehen**

Text aus `paket.ps1:48-87` übernehmen, `$fassung` durch `@FASSUNG@` ersetzen (der Workflow
setzt sie ein), und den Abschnitt „NUR WINDOWS" austauschen:

```
WELCHE PLATTFORMEN
  Windows   geflogen am 13.09.2026
  macOS     gebaut, aber NIE GESTARTET -- Rueckmeldung ausdruecklich erwuenscht
  Linux     gebaut, aber NIE GESTARTET -- Rueckmeldung ausdruecklich erwuenscht

  Auf dem Mac einmal noetig, weil das Plugin nicht signiert ist:
      xattr -dr com.apple.quarantine "<X-Plane 12>/Resources/plugins/FriesenBruegge"

  Hinter einem systemweit eingerichteten Proxy verhaelt sich die Mac- und Linux-Fassung
  anders als die unter Windows: Sie liest nur die Umgebungsvariable https_proxy.
```

- [ ] **Step 2: Den Workflow schreiben**

`.github/workflows/bruegge-xplane.yml` — vier Jobs. Die Kernaufrufe:

```yaml
name: Bruegge X-Plane bauen
on: workflow_dispatch

env:
  SDK_URL: https://developer.x-plane.com/wp-content/plugins/code-sample-generation/sdk_zip_files/XPSDK430.zip
  XPLM_DEFS: -DXPLM200=1 -DXPLM210=1 -DXPLM300=1 -DXPLM301=1 -DXPLM400=1 -DXPLM410=1

jobs:
  linux:
    runs-on: ubuntu-22.04     # NICHT latest: die libstdc++ von 24.04 zieht GLIBC_2.38 nach
    steps:
      - uses: actions/checkout@v4
      - run: sudo apt-get update && sudo apt-get install -y libcurl4-openssl-dev
      - run: curl -sSL -o sdk.zip "$SDK_URL" && unzip -q sdk.zip
      - run: |
          g++ -std=c++17 -shared -fPIC -fvisibility=hidden -pthread -O2 \
              -DLIN=1 $XPLM_DEFS \
              -I SDK/CHeaders/XPLM -I SDK/CHeaders/Widgets \
              -o FriesenBruegge.xpl friesenbruegge/xplane/bruegge.cpp -ldl
      - run: |
          echo "== verlangt =="; readelf -d FriesenBruegge.xpl | grep NEEDED
          objdump -T FriesenBruegge.xpl | grep -oE 'GLIBC(XX)?_[0-9.]+' | sort -Vu | tail -3
          test "$(nm -D --defined-only FriesenBruegge.xpl | grep -c XPlugin)" = 5
      - uses: actions/upload-artifact@v4
        with: { name: lin_x64, path: FriesenBruegge.xpl }

  macos:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - run: curl -sSL -o sdk.zip "$SDK_URL" && unzip -q sdk.zip
      # Zwei Laeufe: X-Plane 12 verlangt macOS 10.15, Apple Silicon gibt es erst ab 11.0 --
      # ein einziger Aufruf kann nur EIN Deployment-Target tragen.
      - run: |
          for paar in "x86_64 10.15" "arm64 11.0"; do
            set -- $paar
            clang++ -std=c++17 -dynamiclib -fvisibility=hidden -O2 \
              -arch "$1" -mmacosx-version-min="$2" \
              -DAPL=1 $XPLM_DEFS \
              -I SDK/CHeaders/XPLM -I SDK/CHeaders/Widgets \
              -F SDK/Libraries/Mac -framework XPLM \
              -o "bruegge-$1.xpl" friesenbruegge/xplane/bruegge.cpp
          done
          lipo -create -output FriesenBruegge.xpl bruegge-x86_64.xpl bruegge-arm64.xpl
          lipo -info FriesenBruegge.xpl
          otool -l FriesenBruegge.xpl | grep -A3 LC_BUILD_VERSION | head -20
      - uses: actions/upload-artifact@v4
        with: { name: mac_x64, path: FriesenBruegge.xpl }

  windows:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: ilammy/msvc-dev-cmd@v1        # sonst liegt cl.exe nicht im Pfad
      - run: curl -sSL -o sdk.zip "$env:SDK_URL"; Expand-Archive sdk.zip .
      - run: |
          cl.exe /nologo /LD /EHsc /O2 /MT /utf-8 /std:c++17 `
            /DIBM=1 /DWIN32 /D_CRT_SECURE_NO_WARNINGS `
            /DXPLM200=1 /DXPLM210=1 /DXPLM300=1 /DXPLM301=1 /DXPLM400=1 /DXPLM410=1 `
            /I SDK\CHeaders\XPLM /I SDK\CHeaders\Widgets `
            friesenbruegge\xplane\bruegge.cpp `
            /link /OUT:FriesenBruegge.xpl SDK\Libraries\Win\XPLM_64.lib winhttp.lib
      - uses: actions/upload-artifact@v4
        with: { name: win_x64, path: FriesenBruegge.xpl }

  paket:
    needs: [linux, macos, windows]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with: { path: teile }
      - run: |
          F=$(grep -oP '#define\s+BRUEGGE_VERSION\s+"\K[0-9.]+' friesenbruegge/xplane/bruegge.cpp)
          echo "Fassung $F"
          for p in win_x64 mac_x64 lin_x64; do
            mkdir -p FriesenBruegge/$p
            cp "teile/$p/FriesenBruegge.xpl" "FriesenBruegge/$p/"
          done
          # fassung.json bleibt auf dieser Ebene: _efb_package_version (app/main.py:627)
          # findet sie nur bei Pfadtiefe <= 1.
          printf '{\n  "package_version": "%s",\n  "simulator": "xplane12",\n  "creator": "devprops"\n}\n' \
            "$F" > FriesenBruegge/fassung.json
          sed "s/@FASSUNG@/$F/g" friesenbruegge/xplane/LIESMICH.txt > FriesenBruegge/LIESMICH.txt
          zip -qr friesenbruegge-xplane.zip FriesenBruegge
          unzip -l friesenbruegge-xplane.zip
      - uses: actions/upload-artifact@v4
        with: { name: friesenbruegge-xplane, path: friesenbruegge-xplane.zip }
```

- [ ] **Step 3: `paket.ps1` auf den Upload reduzieren**

Schnüren und Textbausteine entfernen; übrig bleibt der `scp`-Teil mit dem Hinweis, dass die
Datei aus dem CI-Artefakt kommt.

- [ ] **Step 4: Das eingecheckte ZIP entfernen**

```bash
git rm friesenbruegge/friesenbruegge-xplane.zip
```

Begründung für den Commit-Text: Es wäre ab jetzt eine zweite Wahrheit neben dem Artefakt.

- [ ] **Step 5: Den Workflow von Hand auslösen und das Ergebnis ansehen**

```bash
gh workflow run bruegge-xplane.yml
sleep 30 && gh run list --workflow=bruegge-xplane.yml --limit 1
```

Erwartet: alle vier Jobs grün; im `paket`-Log stehen drei `.xpl` und `fassung.json` auf der
richtigen Ebene; im `macos`-Log zeigt `lipo -info` beide Architekturen und
`LC_BUILD_VERSION` die gesetzten Mindestversionen.

- [ ] **Step 6: Committen**

```bash
git add .github/workflows/bruegge-xplane.yml friesenbruegge/xplane/LIESMICH.txt \
        friesenbruegge/xplane/paket.ps1
git commit -m "Das Paket entsteht in der CI -- drei Plattformen aus einem Commit"
```

---

## Task 8: Download-Seite, Changelog, Doku

**Files:**
- Modify: `app/static/efb.html` (X-Plane-Kasten), `app/CHANGELOG.json`,
  `friesenbruegge/PROTOKOLL.md` (Abschnitt 9 Fassungen), `README.md` (Sim-Brügge-Absatz),
  `COORDINATION.md`

**Interfaces:**
- Consumes: das Artefakt aus Task 7
- Produces: nichts, worauf Code aufbaut

- [ ] **Step 1: Den Hinweis auf die Download-Seite setzen**

Im X-Plane-Kasten in `app/static/efb.html`, sichtbar, nicht als Fußnote:

```html
<p class="hinweis">Windows ist erprobt. <strong>Die Fassungen für macOS und Linux sind
gebaut, aber noch nie gestartet</strong> — wer eine davon ausprobiert, sagt bitte Bescheid,
ob sie läuft.</p>
```

- [ ] **Step 2: Changelog-Eintrag**

⚠ **Erst schreiben, wenn keine Suite läuft** (`CLAUDE.md`): `version.py` liest die Datei beim
Import, `test_load_changelog_matches_module_constant` liest sie erneut.

```json
{
  "version": "14.35.0",
  "date": "2026-09-13",
  "highlight": false,
  "title": "Die FriesenBrügge gibt es jetzt auch für Mac und Linux",
  "items": [
    "🍏 Das X-Plane-Paket enthält ab sofort alle drei Plattformen in einer Datei — der Simulator sucht sich selbst heraus, was zu ihm passt. Einbauen ist derselbe Handgriff wie vorher.",
    "🧪 Ehrlich gesagt: Windows ist erprobt, Mac und Linux sind gebaut, aber noch nie gestartet worden. Wer eine der beiden ausprobiert, sagt bitte Bescheid — dann wird aus „müsste gehen“ ein „geht“.",
    "🔒 Auf dem Mac ist einmalig ein Befehl im Terminal nötig, weil das Plugin nicht signiert ist; er steht in der Anleitung im Paket.",
    "🧮 Nebenbei ein Fehler beseitigt, den es nur außerhalb von Windows gegeben hätte: Die Brügge hätte ihre Koordinaten bei einem deutsch eingestellten System mit Komma gemeldet — und der Server hätte jede Meldung abgelehnt."
  ]
}
```

- [ ] **Step 3: `PROTOKOLL.md` Abschnitt 9 ergänzen**

Eine Zeile: Fassung 1.1.0 — dieselbe Protokollfassung, drei Plattformen; `hoehe_gemessen`
unverändert.

- [ ] **Step 4: README-Absatz nachziehen**

Im Abschnitt „Sim-Brügge" den Satz über die Plattformen ersetzen: ein Paket, drei Ordner,
Windows erprobt, Mac und Linux ungetestet.

- [ ] **Step 5: Die ganze Suite laufen lassen**

```bash
cd ~/projects/friesenspy
/home/claude/.venv-friesenspy/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Erwartet: alle grün (vorher 2497, dazu die 14 neuen Quelltext-Tests).

- [ ] **Step 6: Committen und deployen**

```bash
git add -A && git commit -m "v14.35.0: Die FriesenBruegge fuer Mac und Linux"
git push origin main
```

- [ ] **Step 7: Kontrollstart durch den Nutzer erbitten — VOR dem Upload**

Das Artefakt aus Task 7 wird **nicht** hochgeladen, bevor der Nutzer unter Windows bestätigt hat:

| Zu sehen im `Log.txt` | Warum |
|---|---|
| `[FriesenBruegge] Fassung 1.1.0 geladen.` | der CI-Build lädt überhaupt |
| `Kennung gelesen: fb0225a72bb734be` | `XPLM_USE_NATIVE_PATHS` hat die Pfade nicht zerschossen |
| eine ankommende Meldung im Admin | die umgebaute Thread-Schicht trägt |
| einmal der Weg über `friesenbruegge.url` zum Prüfserver | die zweite Datei, die an den Pfaden hängt |

Erst danach:

```bash
scp friesenbruegge-xplane.zip server:/opt/friesenspy/data/efb/
```

---

## Selbstprüfung gegen die Spec

| Spec-Abschnitt | Task |
|---|---|
| 3 Windows-Anteile (pragma, Literale, wchar_t, ziel_laden, getpid) | 3, 4 |
| 4 Netzschicht, dlopen in XPluginStart, Suchreihenfolge, NOSIGNAL, Expect, L-Suffixe, variadisch | 5 |
| 5 Thread: Prädikat, join, kein globaler Thread | 4 |
| 6 `XPLM_USE_NATIVE_PATHS` | 2 |
| 7 Locale | 1 |
| 8 Workflow, zwei Mac-Läufe, ubuntu-22.04, Symbolversionen | 7 |
| 9 Paket, `fassung.json`-Tiefe, LIESMICH-Umzug, xattr, Proxy | 7 |
| 10 `netz.h` herauslösen | 3 |
| 11 Prüflauf ohne Simulator | 6 |
| 12 Was der Test nicht kann | 6 (im Kopf von `pruefen.sh`), 8 (Hinweis auf der Seite) |
| 13 Versionierung | 7 (Brügge 1.1.0), 8 (v14.35.0) |
| 14 Kontrollstart, Risiken | 8 |

**Offen und bewusst nicht im Plan:** die Groß-/Kleinschreibung der Objektpfade unter Linux
(Spec 14, letzte Zeile). Sie lässt sich erst prüfen, wenn jemand X-Plane auf Linux startet —
und sie betrifft nicht das Laden des Plugins, sondern einzelne Gattungen. Gehört in die Bitte
an den ersten Linux-Piloten.
