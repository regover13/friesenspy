# 🌉 Die Brügge auf macOS und Linux · Design

**Datum:** 2026-09-13 · **Status:** vom Nutzer abgenommen (Weg A, ein ZIP, kein Apple-Konto),
**einmal adversarisch gegengeprüft** (Fable, 13.09.2026) · **Betrifft:**
`friesenbruegge/xplane/` · **Verwandt:** `friesenbruegge/PROTOKOLL.md`, `MESSLISTE.md`
Abschnitt „X-Plane 12"

> **Was hier entschieden ist, hat der Nutzer im Gespräch am 13.09.2026 entschieden:**
> ein einziges ZIP für alle drei Plattformen, das Auslieferungspaket entsteht in GitHub
> Actions, **kein Apple-Developer-Konto**. Alles Übrige sind Vorschläge mit Begründung.
>
> **Die Gegenprüfung hat diese Spec erheblich verändert.** Funde stehen an Ort und Stelle
> als **Fable-Fund**; Abschnitt 15 zählt auf, was dabei an der ersten Fassung falsch war.
> Zwei Messungen stammen aus einem Probebau auf dieser Maschine (Ubuntu 24.04) und sind
> unter `/tmp/bruegge-probe` wiederholbar.

---

## 1. Ziel

Die X-Plane-Brügge läuft heute nur auf Windows. In der Gruppe fliegen Leute mit **macOS**;
ob jemand Linux nutzt, ist unbekannt. Beide Plattformen brauchen denselben Umbau, deshalb
entstehen sie zusammen.

**Ausgeliefert wird mit dem ausdrücklichen Hinweis, dass Mac und Linux ungetestet sind.**
Das ist eine Nutzerentscheidung: Eine eigene Testinstallation kostet mehr, als der erste
Fehlerbericht aus der Gruppe wert wäre.

## 2. Ausgangslage — was belegt ist und was nicht

| | Stand |
|---|---|
| `xplane/bruegge.cpp` Fassung 1.0.0, Windows | **geflogen am 13.09.2026**, neun Punkte grün (`MESSLISTE.md`) |
| Netzschicht | WinHTTP, TLS gegen den Produktivserver, HTTP 200 belegt |
| `pruefserver.py` | neu, liefert `soll` ohne VATSIM — **spricht http, nicht https** |
| macOS, Linux | kein Quelltextzweig, kein Bauweg, nichts gemessen |

Die Windows-Fassung ist damit die Referenz, gegen die jede Abweichung zu deuten ist.

## 3. Wo Windows wirklich steckt

Die Bemerkung im Quelltext („wer macOS oder Linux nachrüstet, tauscht den `netz_*`-Block und
sonst nichts") **stimmt nicht.** Auch die erste Fassung dieser Spec hat den Anteil zu klein
geschätzt (**Fable-Fund**); vollständig ist er:

| Schicht | Was Windows-eigen ist | Zeilen |
|---|---|---|
| Netz | WinHTTP-Aufrufe, `#pragma comment(lib, …)` (78), `L"…"`-Literale (90–91), `wchar_t`/`INTERNET_PORT`-Globals (435–438), Umsetzung nach `wchar_t` in `ziel_laden` (490–499) | 78, 90–91, 435–438, 490–630 |
| Thread und Zeit | `CreateThread`, `CRITICAL_SECTION`, `SetEvent`/`WaitForSingleObject`, `volatile LONG`, `GetTickCount64`, `GetCurrentProcessId` | 216, 417–420, 532–623, 999–1007, 1117, 1155–1161 |
| Pfade | **eine fehlende Zeile**, s. Abschnitt 6 | 207, 447 |
| Zahlen | locale-abhängiges Lesen und Schreiben in `json.h`, s. Abschnitt 7 | `json.h` |

⚠ **`netz_lauf` steht in zwei dieser Zeilen und wird von beiden Umbauten berührt.** „Windows
behält WinHTTP unverändert" heißt deshalb genau: die WinHTTP-**Aufrufe** bleiben, die Funktion
drumherum nicht (**Fable-Fund**: die erste Fassung widersprach sich hier selbst).

**`ziel_laden` muss künftig beides liefern:** WinHTTP will Host, Port und Pfad getrennt,
libcurl will eine zusammengesetzte URL-Zeichenkette. Die Funktion zerlegt weiterhin und legt
zusätzlich die vollständige URL in einem `char`-Puffer ab.

**`getpid()` braucht `<unistd.h>`, Windows `<process.h>`/`_getpid`.** Das ist das einzige
`#ifdef` in der Zeitschicht und war in der ersten Fassung übersehen.

## 4. Netzschicht: libcurl, zur Laufzeit geholt

Windows behält WinHTTP — es ist belegt und braucht keine Fremdbibliothek. Für POSIX kommt
**libcurl** hinter dieselbe interne Schnittstelle (`netz_oeffnen`, `netz_senden`,
`netz_schliessen`, `netz_lauf`).

**Warum libcurl und nicht je System eine eigene Bibliothek:** Linux und macOS bringen es beide
mit und binden dabei ihren eigenen Zertifikatsspeicher an. Eine Implementierung genügt für
beide — der Grund, warum Linux mitgebaut wird, obwohl die Nachfrage unklar ist.

**Warum `dlopen` statt Linken:** Ein Plugin mit unauflösbarem Symbol wird von X-Plane gar nicht
geladen; der Pilot sieht eine Zeile in einem riesigen `Log.txt`. Zur Laufzeit geladen, startet
die Brügge, findet libcurl nicht und sagt es.

### ⚠ `dlopen` gehört in `XPluginStart`, nicht in den Netzthread

**Fable-Fund, und er betrifft eine Regel dieser Spec selbst.** Das Windows-Vorbild öffnet die
Verbindung in `netz_oeffnen()` (Zeile 515) — und das läuft **im Netzthread** (Zeile 554). Wer
libcurl analog dort lädt, muss den Fehlschlag auch dort melden: genau der `XPLMDebugString`-
Aufruf im Netzthread, den Abschnitt 5 verbietet.

Deshalb: **`dlopen` und alle `dlsym` in `XPluginStart`, vor dem Start des Threads.** Die
Funktionszeiger liegen in Statics; der Thread prüft nur noch `if (!curl_easy_init_fn) return;`.
Ins Log gehört dabei `curl_version()` — auf Linux kann `dlopen` eine bereits von X-Plane
geladene Kopie derselben SONAME liefern, und dann weiß sonst niemand, welche Fassung spricht.

### ⚠ Suchreihenfolge: erst der volle Pfad, dann der nackte Name

Ebenfalls **Fable-Fund**; die erste Fassung hatte es umgekehrt. Ein nackter Name durchsucht auf
macOS die Fallback-Pfade — auf einem Intel-Mac mit Homebrew gewinnt dann dessen curl mit
eigenem OpenSSL statt Apples Bibliothek mit Keychain-Vertrauen, auf das diese Spec sich beruft.

| System | Reihenfolge |
|---|---|
| macOS | `/usr/lib/libcurl.4.dylib`, dann `libcurl.4.dylib` |
| Linux | `libcurl.so.4`, dann `libcurl-gnutls.so.4` (Debian hat oft nur das) |

`libcurl.so` ohne Versionsnummer entfällt — die Datei gibt es nur mit dem `-dev`-Paket.

⚠ **Auf macOS nicht vorher prüfen, ob die Datei existiert.** Seit Big Sur liegen
Systembibliotheken im dyld-Cache statt einzeln auf der Platte. `access()` schlägt fehl,
`dlopen()` gelingt. Wer die Existenzprüfung vorschaltet, baut einen Nur-Mac-Fehler.

### ⚠ Zwei Fallstricke der variadischen Aufrufe

`curl_easy_setopt` und `curl_easy_getinfo` sind variadisch.

1. **Der Funktionszeiger muss variadisch deklariert sein** — `using setopt_fn = CURLcode
   (*)(CURL*, CURLoption, ...);`. Als gewöhnliche Funktion deklariert geht es auf x86-64
   zufällig gut und bricht auf **arm64-macOS**, weil Apple variadische Argumente dort über den
   Stack übergibt statt in Registern.
2. **Jeder `long`-Option ein `long`-Literal** (**Fable-Fund**, in der ersten Fassung fehlend):
   `curl_easy_setopt(h, CURLOPT_TIMEOUT, 15L)`, nicht `15`. Ein `int` belegt 4 Byte in einem
   8-Byte-Fach, libcurl liest `va_arg(…, long)` — die oberen vier Byte sind Müll. Auf x86-64
   klappt es zufällig, weil die Register 64 Bit breit sind. Dasselbe für
   `curl_easy_getinfo(CURLINFO_RESPONSE_CODE, &code)`: `code` muss `long` sein.

⚠ **Der VPS-Test aus Abschnitt 11 kann genau diesen Fehler prinzipiell nicht finden** — er
läuft auf x86-64. Siehe Abschnitt 12.

### Weitere Festlegungen

- **`CURLOPT_NOSIGNAL 1L` wird gesetzt** — aber die Begründung ist schwächer, als sie hier
  zunächst stand. **Fable-Fund, nachgemessen und teilweise widerlegt (13.09.2026):**
  Behauptet war, ohne die Option lasse libcurl bei einer gekappten Verbindung ein `SIGPIPE`
  zu, und das beende den X-Plane-Prozess. Auf Linux (libcurl 8.5.0/OpenSSL) ließ sich das in
  **zwei** Aufbauten nicht nachstellen — weder mit einer Gegenstelle, die sofort schließt,
  noch mit einer, die erst antwortet und die Keep-alive-Verbindung dann hart abbricht. Mit
  und ohne Option lief der Prozess unverändert weiter; libcurl sendet dort offenbar mit
  `MSG_NOSIGNAL`. Die Option bleibt gesetzt, weil sie nichts kostet und den Resolver-Pfad
  sowie macOS abdeckt, wo nichts gemessen ist. **Wer sie entfernen will, misst erst auf
  einem Mac.**
- **`Expect:` als leerer Header.** libcurl schickt bei größeren POST-Rümpfen
  `Expect: 100-continue` und wartet auf die Zwischenantwort — ein zusätzlicher Umlauf je
  Meldung, im Sekundentakt spürbar.
- **`curl/curl.h` wird eingebunden, aber nicht gegen libcurl gelinkt.** Der Header liefert
  Typen und Konstanten aus einer Quelle statt abgeschriebener Zahlen und sorgt dafür, dass der
  Compiler die variadische Signatur kennt. Auf `ubuntu-22.04` kostet das ein
  `libcurl4-openssl-dev`, auf `macos-latest` liegt der Header im SDK.
- **Ein `CURL*`-Handle wird angelegt und behalten**, wie WinHTTP Sitzung und Verbindung behält.
  Bei Sekundentakt ist das der Unterschied zwischen einem TLS-Handshake je Meldung und einem
  je Sitzung. Nachweis über `CURLINFO_NUM_CONNECTS` — ab der zweiten Meldung muss es 0 sein.
- **Zeitgrenzen wie bei WinHTTP:** `CURLOPT_CONNECTTIMEOUT 10L`, `CURLOPT_TIMEOUT 15L`.
- **Die Antwortgrenze bleibt `ANTWORT_PUFFER` (16384).** Läuft sie über, wird die Antwort
  **verworfen statt halb gelesen** und als `antwort_zu_gross` gemeldet — dieselbe Regel wie in
  der MSFS-Brügge, dort im Flug erarbeitet.
- **Kein `curl_global_init`** — nicht, weil es überflüssig wäre, sondern weil das Gegenstück
  `curl_global_cleanup` beim Entladen des Plugins nicht sicher zu rufen ist. (Die erste Fassung
  begründete es mit „X-Plane nutzt curl womöglich schon"; das trägt nicht, ein per `dlopen`
  geholtes libcurl teilt mit einem statisch eingebauten keinen Zustand. **Fable-Fund.**)
- **Proxy:** WinHTTP nutzte `AUTOMATIC_PROXY`, libcurl liest nur `https_proxy` aus der
  Umgebung. Ein Pilot hinter einem systemweit konfigurierten Proxy verhält sich auf dem Mac
  anders als unter Windows. Hingenommen, aber im `LIESMICH.txt` erwähnt.
- **Per `dlsym` geholt werden:** `curl_easy_init`, `curl_easy_setopt`, `curl_easy_perform`,
  `curl_easy_getinfo`, `curl_easy_cleanup`, `curl_slist_append`, `curl_slist_free_all`,
  `curl_version`.

## 5. Thread- und Zeitschicht: einheitlich auf die Standardbibliothek

`std::thread`, `std::mutex`, `std::condition_variable`, `std::atomic<bool>`, `std::chrono` und
`getpid()` ersetzen die Win32-Aufrufe — **für alle drei Plattformen gemeinsam**, nicht in
`#ifdef`-Zweigen.

⚠ **Das fasst die einzige geflogene Fassung an.** Die Alternative (Windows unberührt, POSIX in
eigenen Zweigen) hätte zwei Thread-Schichten zur Folge, von denen eine nie mitgeprüft wird.

### Drei Unterschiede, die dabei auszugleichen sind

Alle drei **Fable-Funde**, alle drei betreffen auch Windows:

1. **Verlorener Weckruf.** Ein Win32-Event *merkt sich* ein `SetEvent`, auch wenn gerade
   niemand wartet. Eine `condition_variable` merkt sich nichts. `netz_senden` (619) und
   `XPluginStop` (1159) wecken heute in Momenten, in denen der Thread noch in WinHTTP stecken
   kann — mit `notify` allein ginge der Weckruf verloren, der Thread schliefe für immer und
   `XPluginStop` hinge. **Zwingend:** `cv.wait(lock, []{ return g_ausgang_voll || g_netz_ende; })`,
   und `g_netz_ende` **unter dem Mutex** setzen, erst danach `notify`.
2. **Kein Warten mit Zeitgrenze.** Zeile 1161 wartet heute höchstens 20 s
   (`WaitForSingleObject(…, 20000)`) und gibt danach auf. `std::thread` kennt nur `join()`
   (unbegrenzt) oder `detach()`. `detach()` scheidet aus — X-Plane entlädt das Plugin nach
   `XPluginStop`, und ein Thread, der dann noch in Plugin-Code steht, stürzt beim Rücksprung
   ab. Also `join()`, dessen Obergrenze dann allein `CURLOPT_TIMEOUT` (15 s) plus
   Namensauflösung ist. Vertretbar — aber es ist ein *Versprechen*, wo heute eine *Aufgabe*
   steht, und gehört so ins Protokoll der Änderung.
3. **`std::terminate` beim Entladen.** Ein globales `static std::thread`, das beim Entladen der
   Bibliothek noch `joinable()` ist, ruft im Destruktor `std::terminate()` — X-Plane stirbt
   beim Beenden. Heute passiert in demselben Fall nichts Sichtbares. Deshalb: den Thread als
   Zeiger oder `std::optional` halten, in `XPluginStop` joinen und zurücksetzen.

**Was erhalten bleiben muss:** Kein XPLM-Aufruf im Netzthread. Das SDK ist nicht threadsicher —
eine einzige `XPLMDebugString`-Zeile an der falschen Stelle reicht für einen Absturz, den
niemand reproduziert. Der Netzthread sieht weiterhin nur `char`-Puffer.

## 6. ⚠ Eine fehlende Zeile, die vor allem den Mac trifft

`XPLMGetSystemPath` liefert ohne das Feature **`XPLM_USE_NATIVE_PATHS`** auf macOS einen
klassischen HFS-Pfad mit Doppelpunkten; `fopen` versteht ihn nicht. Der SDK-Header sagt
ausdrücklich: „All plugins should enable this feature on OS X." Betroffen sind beide Dateien,
die die Brügge kennt:

| Datei | Folge ohne die Zeile |
|---|---|
| `Output/preferences/friesenbruegge.url` | wird nie gefunden — **der Prüfserver-Weg funktioniert auf dem Mac gar nicht.** Das ist die ernste Folge |
| `Output/preferences/friesenbruegge.kennung` | wird nie gelesen und nie geschrieben: je Sitzung eine neue Kennung, also ein voller Positionsmatch je Start statt je Installation, und `vs_spitze` geht verloren |

⚠ **Korrektur an der ersten Fassung** (**Fable-Fund**): Dort stand, der Server sähe „eine Flut
neuer Brüggen". Das stimmt nicht — `bruegge_zuordnung_setzen` (`app/database.py:2602`) löscht
bei jeder Zuordnung alle anderen Kennungen derselben CID, es bleibt eine Zeile je Pilot. Der
Code führt den Neu-Match selbst als „kein Fehlerfall". Die Begründung für die Zeile ist also
die `.url`-Datei, nicht die Kennung.

```c
XPLMEnableFeature("XPLM_USE_NATIVE_PATHS", 1);
```

Gehört in `XPluginStart` **vor** `ziel_laden()` (1120) und `kennung_laden_oder_erzeugen()` (1124).

⚠ **Und sie ändert auch Windows** (**Fable-Fund**; die erste Fassung behauptete das Gegenteil):
Mit dem Feature liefert X-Plane dort Vorwärts- statt Rückwärts-Schrägstriche. `fopen` trägt
beides, aber es ist eine Änderung an der geflogenen Fassung — der Kontrollstart in Abschnitt 14
muss deshalb **beide Dateizugriffe** abdecken, nicht nur den Start.

## 7. ⚠ Das Dezimalzeichen — ein Risiko, das genau diese Gruppe trifft

**Fable-Fund, in der ersten Fassung gar nicht erkannt.** `json.h` schreibt Zahlen mit
`snprintf("%.*f")` und liest sie mit `strtod`. Beides hängt an `LC_NUMERIC`. Setzt im
X-Plane-Prozess irgendwer `setlocale(LC_ALL, "")` — X-Plane selbst oder ein beliebiges anderes
Plugin, prozessweit —, dann meldet die Brügge bei einem deutschen Piloten `52,123` statt
`52.123` (der Server antwortet 400) und liest `"lat": 53.5` als `53`.

Die MSFS-WASM-Sandbox und der MSVC-Prozess kennen das Problem nicht; **die Piloten dieser
Gruppe haben mit hoher Wahrscheinlichkeit `de_DE`.**

**Ob X-Plane 12 die Prozess-Locale setzt, ist nicht bekannt** — deshalb wird nicht darauf
gewettet. Vorgehen: `json.h` locale-frei machen (eigener Zahlenschreiber und -leser, rund
40 Zeilen). Der Weg über `uselocale(newlocale(LC_NUMERIC_MASK, "C", nullptr))` wäre kürzer,
wirkt aber **je Thread** — und die Flugschleife läuft im Hauptthread, der X-Plane gehört.

Das ist der einzige Punkt dieser Spec, der auch die **MSFS**-Brügge betreffen könnte, weil
`json.h` geteilt ist. Für WASM ist er ungefährlich; geändert wird die gemeinsame Datei
trotzdem, und die MSFS-Fassung ist danach neu zu bauen.

## 8. Bauen: `.github/workflows/bruegge-xplane.yml`

Ausgelöst von Hand (`workflow_dispatch`). Vier Jobs. Gemeinsam für alle: **`-std=c++17`
ausdrücklich** (die Vorgaben von g++ und clang unterscheiden sich).

| Job | Läufer | Wesentliche Angaben |
|---|---|---|
| `windows` | `windows-latest` | `cl.exe /LD /EHsc /O2 /MT /utf-8 /DIBM=1` + `XPLM_64.lib`, `winhttp.lib`. ⚠ `cl.exe` liegt nicht im Pfad — `ilammy/msvc-dev-cmd` oder vcvars davor |
| `macos` | `macos-latest` | **zwei Läufe und `lipo`**, s. unten |
| `linux` | **`ubuntu-22.04`** | `g++ -shared -fPIC -fvisibility=hidden -pthread -DLIN=1`, **ohne** XPLM-Bibliothek |
| `paket` | `ubuntu-latest` | schnürt, liest `BRUEGGE_VERSION` aus `bruegge.cpp` |

Das SDK (XPSDK430) wird je Job als ZIP geholt.

⚠ **Der Ordner heißt `mac_x64`, auch für Apple Silicon.** Der Name ist historisch; X-Plane
sucht dort und erwartet ein Universal Binary. Wer `mac_arm64` anlegt, baut einen Ordner, in den
nie jemand sieht.

### macOS: zwei Bauläufe, nicht einer

X-Plane 12 verlangt mindestens **macOS 10.15** — Apple Silicon gibt es aber erst ab **11.0**.
Ein einzelner Aufruf mit beiden `-arch` kann nur ein gemeinsames Deployment-Target tragen.
Deshalb getrennt bauen und zusammenfügen:

```
clang++ -arch x86_64 -mmacosx-version-min=10.15 …
clang++ -arch arm64  -mmacosx-version-min=11.0  …
lipo -create -output mac_x64/FriesenBruegge.xpl …
```

Dazu `-dynamiclib -fvisibility=hidden -DAPL=1 -F$SDK/Libraries/Mac -framework XPLM`.

⚠ **Ohne `-mmacosx-version-min` erbt das Binary die SDK-Version des Läufers** (auf
`macos-latest` also macOS 15) — ein Pilot auf macOS 13 sähe dann nur eine Zeile im `Log.txt`
(**Fable-Fund**; das dyld-Verhalten ist hier mangels Mac nicht nachgemessen, die Gegenmaßnahme
ist aber ohnehin Standard). Der Workflow gibt zur Kontrolle
`otool -l … | grep -A3 LC_BUILD_VERSION` aus.

### Linux: nicht die Bibliotheksfrage, sondern die glibc-Frage

**Fable-Fund, gemessen** auf Ubuntu 24.04 an einem Probe-Plugin mit `std::thread`:

| Bauweise | NEEDED | höchste Symbolversion |
|---|---|---|
| `g++ -shared -fPIC` | `libstdc++.so.6`, `libgcc_s.so.1`, `libc.so.6` | `GLIBCXX_3.4.30`, `GLIBC_2.4` |
| dazu `-static-libstdc++ -static-libgcc` | nur `libc.so.6` | **`GLIBC_2.38`** |

Der naheliegende „Kompatibilitäts-Fix" macht es also **schlechter**: Die statisch eingebundene
libstdc++ von 24.04 zieht `GLIBC_2.38` nach, und das Plugin lädt auf Ubuntu 22.04 (glibc 2.35)
gar nicht mehr. **Deshalb wird auf `ubuntu-22.04` gebaut**, ohne statisches Einbinden, und der
Workflow gibt die Anforderung sichtbar aus:

```
objdump -T lin_x64/FriesenBruegge.xpl | grep -oE 'GLIBC(XX)?_[0-9.]+' | sort -Vu | tail -3
```

⚠ **Zwei Fallen aus der Doku:** Das SDK-ZIP enthält `Libraries/Lin/XPLM_64.so`, obwohl die
README sagt, für Linux gebe es keine Link-Bibliotheken — **nicht verwenden**. Und Laminars
Bau-Artikel empfiehlt `-nodefaultlibs`; damit gebaut lädt ein Plugin mit `std::thread`
**nicht** (`undefined symbol: _ZTVN10__cxxabiv120__si_class_type_infoE`). Die Empfehlung
stammt aus der C-Zeit. Deshalb stehen die Flags hier vollständig.

**Symbol-Export braucht keine eigene Vorkehrung:** `XPLMDefs.h` definiert `PLUGIN_API` unter
C++ auf allen drei Plattformen passend (`extern "C"` plus `visibility("default")`). Im Probebau
bestätigt.

### Kein automatischer Upload

Die Regel aus `paket.ps1` bleibt: „Der Upload fällt nach draußen, und ein Paket, das gerade
erst gebaut wurde, ist noch nicht im Simulator geprüft." Das Artefakt wird von Hand
heruntergeladen und per `scp` abgelegt.

**`bauen.ps1` bleibt unverändert** als lokales Entwicklungswerkzeug. `paket.ps1` behält nur
seinen `-Hochladen`-Teil. **Das eingecheckte `friesenbruegge-xplane.zip` verschwindet aus dem
Repo** — es wäre sonst eine zweite Wahrheit neben dem CI-Artefakt.

## 9. Paket und Auslieferung

```
FriesenBruegge/
    win_x64/FriesenBruegge.xpl
    mac_x64/FriesenBruegge.xpl      (Universal: x86_64 + arm64)
    lin_x64/FriesenBruegge.xpl
    fassung.json
    LIESMICH.txt
```

⚠ **`fassung.json` muss auf dieser Ebene bleiben:** `_efb_package_version` (`app/main.py:627`)
findet die Datei nur bei Pfadtiefe ≤ 1 (**Fable-Fund**).

**Der `LIESMICH.txt`-Text und die `fassung.json`-Vorlage stehen heute nur in `paket.ps1`**
(Zeilen 48–87) und müssen umziehen, sonst gehen sie beim Umbau verloren (**Fable-Fund**).
Künftiger Ort: `xplane/LIESMICH.txt` als Vorlage, die Fassungsnummer setzt der Workflow ein.

Im Text ersetzt eine Tabelle den heutigen Abschnitt „NUR WINDOWS":

| Plattform | Stand |
|---|---|
| Windows | geflogen am 13.09.2026 |
| macOS | gebaut, **nie gestartet** — Rückmeldung erwünscht |
| Linux | gebaut, **nie gestartet** — Rückmeldung erwünscht |

Dazu für macOS die Zeile gegen das Quarantäne-Flag, das jede aus dem Netz geladene Datei trägt:

```
xattr -dr com.apple.quarantine "<X-Plane 12>/Resources/plugins/FriesenBruegge"
```

**Kein Apple-Developer-Konto** (Nutzerentscheidung). Notarisierung käme erst in Frage, wenn
belegt ist, dass das Plugin auf einem Mac überhaupt läuft.

Derselbe Hinweis steht auf der Kniebrett-Seite (`app/static/efb.html`) am X-Plane-Kasten.

## 10. Voraussetzung für den Test: der Netzblock wandert in eine eigene Datei

**Fable-Fund.** Abschnitt 11 will „dieselben `netz_*`-Quellen einbinden" — das geht nur, wenn
sie ohne die XPLM-Includes übersetzbar sind. Heute ist alles eine Datei. Deshalb:
`xplane/netz_posix.h` (oder `.cpp`) mit der POSIX-Netzschicht **und** der Thread-/Weckerlogik,
ohne einen einzigen XPLM-Bezug. `bruegge.cpp` bindet sie ein.

Das ist kein Selbstzweck: Es ist die Bedingung dafür, dass vor der Auslieferung überhaupt etwas
gemessen werden kann.

## 11. Was sich ohne Simulator belegen lässt

Auf dem VPS, vor jeder Auslieferung — **einschließlich der Thread-Schicht**, nicht nur des
Netzteils (**Fable-Fund**: sonst läuft der POSIX-Threadcode vor der Auslieferung nie):

1. **Der Linux-Bau selbst**, plus die Ausgaben, die etwas aussagen:
   `nm -D --defined-only` (nur die fünf `XPlugin*`-Namen, unmangled),
   `readelf -d | grep NEEDED` (**kein** libcurl), die Symbolversionen aus Abschnitt 8.
2. **Ein `dlopen`-Rauchtest:** ein winziges Programm lädt die `.xpl` mit `RTLD_LAZY` und findet
   `XPluginStart`, obwohl die XPLM-Symbole unaufgelöst bleiben. Das ist der einzige Ladetest,
   den Linux vor dem ersten Piloten bekommt.
3. **Gegen den echten Endpunkt** (`https://friesenspy.devprops.de/api/bruegge/melden`): TLS,
   Zertifikatsspeicher, JSON-Antwort, Puffergrenze. Ohne VATSIM kommt HTTP 200 mit leerem
   `soll` — als Beleg genügt das. Keep-alive über `CURLINFO_NUM_CONNECTS` (ab der zweiten
   Meldung 0).
4. **Gegen `pruefserver.py`** (http, ohne TLS) — der Weg, den ein Mac-Pilot später geht.
5. **Gegen einen Server, der die Verbindung mitten im Takt kappt** — der Test für
   `CURLOPT_NOSIGNAL`. Ohne die Option endet dabei der Prozess.

## 12. ⚠ Was dieser Test NICHT kann

**Fable-Fund; die erste Fassung hat diese Lücke als geprüft verbucht.** Der VPS ist x86-64 mit
libcurl/OpenSSL. Ungeprüft bleiben deshalb:

- **die arm64-Aufrufkonvention** — ausgerechnet der Fallstrick, den Abschnitt 4 selbst
  benennt, ist auf dem VPS unsichtbar
- **die dyld-Namensauflösung** und damit, welches libcurl auf einem Mac wirklich antwortet
- **ob Secure Transport der Let's-Encrypt-Kette traut**
- **das Deployment-Target** und **Gatekeeper**
- alles, was X-Plane braucht: Plugin-Laden, Datarefs, `XPLMInstance`, Terrain-Probe

Das ist auf allen drei Plattformen derselbe Quelltext und unter Windows belegt — aber
„derselbe Quelltext" ist ein Argument, keine Messung.

**Der Mac-Test muss deshalb zweiteilig sein**, und das gehört in die Bitte an den Piloten:

1. gegen `pruefserver.py` — belegt Objekte, Probe, Abräumen (**aber kein TLS**)
2. gegen den echten Server — belegt die portierte Netzschicht

Wer nur den ersten Teil macht, meldet „läuft" und hat libcurl gegen den Zertifikatsspeicher
nie angefasst.

## 13. Versionierung

- Brügge: **1.1.0** (`BRUEGGE_VERSION` in `xplane/bruegge.cpp`)
- FriesenSpy: **MINOR** unter 14.x, `"highlight": false`

## 14. Risiken und Kontrollen

| Risiko | Gegenmaßnahme |
|---|---|
| Der Thread-Umbau beschädigt die geflogene Windows-Fassung | **Kontrollstart durch den Nutzer** nach dem ersten CI-Paket: `Fassung 1.1.0 geladen`, **`Kennung gelesen` mit der bekannten `fb0225a72bb734be`**, einmal der `.url`-Weg zum Prüfserver, eine ankommende Meldung. Die ersten beiden decken Abschnitt 6 ab |
| `SIGPIPE` beendet X-Plane | `CURLOPT_NOSIGNAL` gesetzt. ⚠ Der Abbruchtest (11.5) belegt **nicht**, dass die Option nötig ist — ohne sie läuft es auf Linux genauso. Auf macOS ungemessen |
| Dezimalkomma | `json.h` locale-frei, Abschnitt 7 |
| libcurl fehlt auf einem Zielsystem | Klartextzeile im `Log.txt` statt eines Plugins, das nicht lädt |
| Plugin lädt auf älterem macOS nicht | Deployment-Target gesetzt, `otool`-Ausgabe im Workflow |
| Plugin lädt auf älterem Linux nicht | Bau auf `ubuntu-22.04`, Symbolversionen im Workflow sichtbar |
| **Objektpfade in anderer Schreibung** | Die Titeltabelle (`bruegge.cpp:297–327`) wurde auf Windows nachgesehen, wo Groß-/Kleinschreibung egal ist. Auf Linux muss `…/dynamic/OilPlatform.obj` zeichengenau stimmen, sonst fällt die Gattung still durch. Ob X-Plane dort schreibungsunabhängig auflöst, ist unbekannt — einmal gegen ein `ls` des Windows-Bestands prüfen (**Fable-Fund**) |
| Niemand testet Linux je | hingenommen — es fällt beim Bauen ohnehin ab |

## 15. Was an der ersten Fassung falsch war

Damit niemand die alte Begründung weiterträgt:

1. „Nur der `netz_*`-Block ist zu tauschen" — zu klein geschätzt, s. Abschnitt 3.
2. „Windows behält WinHTTP unverändert" widersprach dem Thread-Umbau; `netz_lauf` wird berührt.
3. „Der Server sieht eine Flut neuer Brüggen" — falsch, der Server räumt selbst auf.
4. „Auf Windows ändert die Zeile nichts" — falsch, `XPLM_USE_NATIVE_PATHS` dreht dort die
   Schrägstriche.
5. Der VPS-Test wurde als Beleg dargestellt, obwohl er den eigenen arm64-Fallstrick gar nicht
   finden kann.
6. `SIGPIPE`, Locale, Deployment-Target, glibc-Versionen, `Expect:`, die `long`-Literale, der
   Umzug von `LIESMICH.txt` und die Pfadtiefe von `fassung.json` fehlten vollständig.

**Und was bei der Umsetzung an DIESER Fassung noch fiel (13.09.2026):**

7. Der `SIGPIPE`-Tod ist auf Linux **nicht nachstellbar** (s. Abschnitt 4). Der Fund war
   plausibel und ist trotzdem kein Befund — die Option bleibt, die Behauptung geht.
8. Der Locale-Fehler ist **größer als beschrieben**: Betroffen war nicht nur das Schreiben,
   sondern auch jede gelesene Serverantwort (`53.5` wurde zu `53`, `1.5E2` zu `1`).
9. `JsonSchreiber` hat keine Methode `name()`, sondern `feld()` — im Plan geraten statt
   nachgesehen, fiel beim ersten Übersetzen auf.

## 16. Reihenfolge

1. `XPLM_USE_NATIVE_PATHS` (eine Zeile, betrifft alle drei)
2. `json.h` locale-frei (Abschnitt 7) — betrifft auch die MSFS-Brügge
3. Netz- und Threadschicht in `netz_posix.*` herauslösen (Abschnitt 10)
4. Thread- und Zeitschicht auf die Standardbibliothek, mit den drei Ausgleichen aus Abschnitt 5
5. POSIX-Netzschicht hinter die vorhandene Schnittstelle
6. Prüfprogramm auf dem VPS, Abschnitt 11 — **bevor** der Workflow entsteht
7. Workflow, Paket, `LIESMICH.txt`, Download-Seite
8. Kontrollstart Windows durch den Nutzer → erst danach hochladen
