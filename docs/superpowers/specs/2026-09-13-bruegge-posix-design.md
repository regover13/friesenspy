# 🌉 Die Brügge auf macOS und Linux · Design

**Datum:** 2026-09-13 · **Status:** vom Nutzer abgenommen (Weg A, ein ZIP, kein Apple-Konto)
· **Betrifft:** `friesenbruegge/xplane/` · **Verwandt:** `friesenbruegge/PROTOKOLL.md`,
`MESSLISTE.md` Abschnitt „X-Plane 12"

> **Was hier entschieden ist, hat der Nutzer im Gespräch am 13.09.2026 entschieden:**
> ein einziges ZIP für alle drei Plattformen, das Auslieferungspaket entsteht in GitHub
> Actions, **kein Apple-Developer-Konto**. Alles Übrige sind Vorschläge mit Begründung.

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

## 3. Der Umbau hat drei Schichten

Die Bemerkung im Quelltext („wer macOS oder Linux nachrüstet, tauscht den `netz_*`-Block und
sonst nichts") **stimmt nicht ganz.** Windows steckt an drei Stellen:

| Schicht | Was Windows-eigen ist | Zeilen |
|---|---|---|
| Netz | WinHTTP, `wchar_t`-Umsetzung | 507–630 |
| Thread und Zeit | `CreateThread`, `CRITICAL_SECTION`, `SetEvent`/`WaitForSingleObject`, `volatile LONG`, `GetTickCount64`, `GetCurrentProcessId` | 216, 417–420, 532–623, 999–1007, 1117, 1155–1161 |
| Pfade | **eine fehlende Zeile**, s. Abschnitt 6 | 207, 447 |

## 4. Netzschicht: libcurl, zur Laufzeit geholt

Windows behält WinHTTP unverändert — es ist belegt, und es braucht keine Fremdbibliothek.
Für POSIX kommt **libcurl** hinter dieselbe interne Schnittstelle:

```c
static bool netz_oeffnen();          // Handle anlegen, wiederverwenden
static void netz_schliessen();       // Handle freigeben
static void netz_senden(const char*);// Puffer füllen, Netzthread wecken
static void netz_lauf();             // der Thread selbst
```

**Warum libcurl und nicht je System eine eigene Bibliothek:** Linux und macOS bringen es beide
mit, und beide binden dabei ihren eigenen Zertifikatsspeicher an (Linux OpenSSL, macOS
Secure Transport/LibreSSL gegen die Keychain). Damit ist **eine** Implementierung für beide
Plattformen genug — der Grund, warum Linux mitgebaut wird, obwohl die Nachfrage unklar ist.

**Warum `dlopen` statt Linken:** Ein Plugin mit einem nicht auflösbaren Symbol wird von
X-Plane gar nicht erst geladen — der Pilot sieht eine Zeile in einem 20 MB großen `Log.txt`.
Zur Laufzeit geladen, startet die Brügge, findet libcurl nicht und **sagt es**:

```
[FriesenBruegge] libcurl nicht gefunden (libcurl.so.4) -- keine Meldungen moeglich.
```

Gesucht wird `libcurl.so.4`, dann `libcurl.so` (Linux) bzw. `libcurl.4.dylib`, dann
`/usr/lib/libcurl.4.dylib` (macOS).

⚠ **Auf macOS nicht vorher prüfen, ob die Datei existiert.** Seit Big Sur liegen
Systembibliotheken nicht mehr einzeln auf der Platte, sondern im dyld-Cache. `access()` oder
`stat()` schlagen fehl, `dlopen()` gelingt trotzdem. Wer die Existenzprüfung vorschaltet,
baut einen Fehler, den es nur auf dem Mac gibt.

### ⚠ Der Fallstrick, der sonst erst auf einem Apple-Silicon-Mac auffällt

`curl_easy_setopt` und `curl_easy_getinfo` sind **variadisch**. Wer sie per `dlsym` holt und
den Zeiger als gewöhnliche Funktion deklariert, bekommt auf x86-64 zufällig das Richtige —
und auf **arm64 unter macOS das Falsche**, weil Apple variadische Argumente dort über den
Stack übergibt statt in Registern. Die Zeiger sind deshalb variadisch zu deklarieren:

```c
using setopt_fn = CURLcode (*)(CURL*, CURLoption, ...);
```

Dann erzeugt der Compiler die richtige Aufrufkonvention.

### Weitere Festlegungen

- **`curl/curl.h` wird eingebunden**, aber **nicht gegen libcurl gelinkt**. Der Header liefert
  Typen und Konstanten aus einer Quelle statt selbst abgeschriebener Zahlen; geladen wird
  weiterhin per `dlopen`. Auf `ubuntu-latest` kostet das ein `libcurl4-openssl-dev`, auf
  `macos-latest` liegt der Header im SDK.
- **Ein `CURL*`-Handle wird angelegt und behalten**, wie WinHTTP Sitzung und Verbindung behält.
  Bei Sekundentakt ist das der Unterschied zwischen einem TLS-Handshake je Meldung und einem
  je Sitzung.
- **Zeitgrenzen wie bei WinHTTP:** `CURLOPT_CONNECTTIMEOUT 10`, `CURLOPT_TIMEOUT 15`.
- **Die Antwortgrenze bleibt `ANTWORT_PUFFER` (16384).** Läuft sie über, wird die Antwort
  **verworfen statt halb gelesen** und als `antwort_zu_gross` gemeldet — dieselbe Regel wie in
  der MSFS-Brügge seit Fassung 1.1.x, dort im Flug erarbeitet.
- **Kein `curl_global_init` aus dem Plugin.** X-Plane selbst und andere Plugins nutzen curl
  womöglich bereits; `curl_easy_init` initialisiert bei Bedarf selbst.

## 5. Thread- und Zeitschicht: einheitlich auf die Standardbibliothek

`std::thread`, `std::mutex`, `std::condition_variable`, `std::atomic<bool>`, `std::chrono`
und `getpid()` ersetzen die Win32-Aufrufe — **für alle drei Plattformen gemeinsam**, nicht in
`#ifdef`-Zweigen.

⚠ **Das fasst die einzige geflogene Fassung an.** Der Alternativvorschlag (Windows unberührt
lassen, POSIX in eigenen Zweigen) hätte zwei Thread-Schichten zur Folge, von denen eine nie
mitgeprüft wird. `std::thread` bildet unter Windows ohnehin auf dieselbe Win32-API ab, und ein
Kontrollstart unter Windows ist nach dem ersten CI-Paket ohnehin vorgesehen (Abschnitt 9).

**Was dabei erhalten bleiben muss:** Kein XPLM-Aufruf im Netzthread. Das SDK ist nicht
threadsicher — eine einzige `XPLMDebugString`-Zeile an der falschen Stelle reicht für einen
Absturz, den niemand reproduziert. Der Netzthread sieht weiterhin nur `char`-Puffer.

## 6. ⚠ Eine fehlende Zeile, die nur auf dem Mac zuschlägt

`XPLMGetSystemPath` liefert ohne das Feature **`XPLM_USE_NATIVE_PATHS`** auf macOS einen
klassischen HFS-Pfad mit Doppelpunkten (`Macintosh HD:Applications:X-Plane 12:`). `fopen`
versteht ihn nicht. Betroffen wären beide Dateien, die die Brügge kennt:

| Datei | Folge ohne die Zeile |
|---|---|
| `Output/preferences/friesenbruegge.kennung` | wird nie gelesen **und nie geschrieben** — jeder Start erzeugt eine neue Kennung, der Server sieht eine Flut neuer Brüggen |
| `Output/preferences/friesenbruegge.url` | wird nie gefunden — **der Prüfserver-Weg funktioniert auf dem Mac gar nicht** |

Beides sähe für den Mac-Piloten nicht nach einem Pfadfehler aus, sondern nach „tut irgendwie
nichts". Deshalb gehört in `XPluginStart`, vor jeden Pfadzugriff:

```c
XPLMEnableFeature("XPLM_USE_NATIVE_PATHS", 1);
```

Auf Windows und Linux ändert die Zeile nichts — dort sind die Pfade ohnehin nativ.

## 7. Bauen: `.github/workflows/bruegge-xplane.yml`

Ausgelöst von Hand (`workflow_dispatch`). Vier Jobs:

| Job | Läufer | Aufruf | Ergebnis |
|---|---|---|---|
| `windows` | `windows-latest` | `cl.exe /LD /EHsc /O2 /MT /utf-8 /DIBM=1` + `XPLM_64.lib`, `winhttp.lib` | `win_x64/FriesenBruegge.xpl` |
| `macos` | `macos-latest` | `clang++ -dynamiclib -arch arm64 -arch x86_64 -DAPL=1` gegen `XPLM.framework` | `mac_x64/FriesenBruegge.xpl` |
| `linux` | `ubuntu-latest` | `g++ -shared -fPIC -DLIN=1`, **ohne** Bibliothek — X-Plane löst die XPLM-Symbole beim Laden auf | `lin_x64/FriesenBruegge.xpl` |
| `paket` | `ubuntu-latest` | schnürt, liest `BRUEGGE_VERSION` aus `bruegge.cpp` | ein ZIP als Artefakt |

Das SDK (XPSDK430) wird je Job als ZIP geholt; es enthält die Header für alle drei und
`XPLM.framework` als Universal Binary.

⚠ **Der Ordner heißt `mac_x64`, auch für Apple Silicon.** Der Name ist historisch; X-Plane
sucht dort weiterhin und erwartet darin ein Universal Binary mit beiden Architekturen. Wer
`mac_arm64` anlegt, baut einen Ordner, in den nie jemand sieht.

**Kein automatischer Upload.** Die Regel aus `paket.ps1` bleibt: „Der Upload fällt nach
draußen, und ein Paket, das gerade erst gebaut wurde, ist noch nicht im Simulator geprüft."
Das Artefakt wird von Hand heruntergeladen und per `scp` abgelegt.

**`bauen.ps1` bleibt unverändert** als lokales Entwicklungswerkzeug (bauen und direkt nach
`D:\X-Plane 12` legen). Was entfällt, ist `paket.ps1` als Erzeuger des Auslieferungs-ZIPs;
das Skript behält nur noch seinen `-Hochladen`-Teil (das `scp`-Ziel ist dort
dokumentiert) und verliert das Schnüren.

**Das eingecheckte `friesenbruegge-xplane.zip` (101 KB) verschwindet aus dem Repo** — es wäre
ab dann eine zweite Wahrheit neben dem CI-Artefakt.

## 8. Paket und Auslieferung

Ein ZIP mit allen drei Plattformordnern nebeneinander; X-Plane nimmt sich beim Start den
passenden. Der Pilot muss nicht wissen, was er hat.

```
FriesenBruegge/
    win_x64/FriesenBruegge.xpl
    mac_x64/FriesenBruegge.xpl
    lin_x64/FriesenBruegge.xpl
    fassung.json
    LIESMICH.txt
```

Im `LIESMICH.txt` ersetzt eine Tabelle den heutigen Abschnitt „NUR WINDOWS":

| Plattform | Stand |
|---|---|
| Windows | geflogen am 13.09.2026 |
| macOS | gebaut, **nie gestartet** — Rückmeldung erwünscht |
| Linux | gebaut, **nie gestartet** — Rückmeldung erwünscht |

Dazu für macOS die eine Zeile, die das Quarantäne-Flag entfernt, das jede aus dem Netz
geladene Datei trägt:

```
xattr -dr com.apple.quarantine "<X-Plane 12>/Resources/plugins/FriesenBruegge"
```

**Kein Apple-Developer-Konto** (Nutzerentscheidung). Notarisierung käme erst in Frage, wenn
belegt ist, dass das Plugin auf einem Mac überhaupt läuft — vorher wäre es ein Jahresabo für
ein ungetestetes Binary.

Derselbe Hinweis steht auf der Kniebrett-Seite (`app/static/efb.html`) am X-Plane-Kasten.

## 9. Was sich ohne Simulator belegen lässt

Auf dem VPS, vor jeder Auslieferung:

1. **Der Linux-Bau selbst** — `g++` übersetzt und linkt die Datei.
2. **Die POSIX-Netzschicht gegen den echten Endpunkt** (`https://friesenspy.devprops.de/api/bruegge/melden`).
   Das misst TLS, Zertifikatsspeicher, Keep-alive, JSON-Antwort und die Puffergrenze. Ohne
   VATSIM kommt HTTP 200 mit leerem `soll` zurück — als Beleg genügt das.
3. **Dieselbe Schicht gegen `pruefserver.py`** (http, ohne TLS) — der Weg, den ein Mac-Pilot
   später gehen wird.

Möglich ist das, weil der Netzthread bewusst nichts von X-Plane weiß und nur `char`-Puffer
sieht. Gebaut wird dafür ein kleines Testprogramm, das dieselben `netz_*`-Quellen einbindet.
**Es ist Prüfwerkzeug, kein Auslieferungsbestandteil.**

## 10. Was ungetestet bleibt

Alles, was X-Plane braucht: Plugin-Laden, Datarefs, `XPLMInstance`, Terrain-Probe,
Kennungsdatei. Das ist auf allen drei Plattformen **derselbe Quelltext** und unter Windows
belegt — aber „derselbe Quelltext" ist ein Argument, keine Messung.

**Der Mac-Test muss deshalb zweiteilig sein**, und das gehört in die Bitte an den Piloten:

1. gegen `pruefserver.py` — belegt Objekte, Probe, Abräumen (**aber kein TLS**)
2. gegen den echten Server — belegt die portierte Netzschicht

Wer nur den ersten Teil macht, meldet „läuft" und hat libcurl gegen den Zertifikatsspeicher
nie angefasst.

## 11. Versionierung

- Brügge: **1.1.0** (`BRUEGGE_VERSION` in `xplane/bruegge.cpp`)
- FriesenSpy: **MINOR** unter 14.x, `"highlight": false` — es ist kein Frontend-Schritt
  außerhalb des Admin-Bereichs, und der Haken steht ohnehin allein dem Nutzer zu

## 12. Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Der Thread-Umbau beschädigt die geflogene Windows-Fassung | Kontrollstart durch den Nutzer nach dem ersten CI-Paket: `[FriesenBruegge] Fassung 1.1.0 geladen.` im `Log.txt`, dazu eine Meldung, die ankommt |
| Der CI-Windows-Build ist nicht dasselbe Binary wie das geflogene | derselbe Quelltext, dieselbe Compiler-Generation; der Kontrollstart oben deckt es ab |
| libcurl fehlt auf einem Zielsystem | Klartextzeile im `Log.txt` statt eines Plugins, das nicht lädt |
| macOS-Pfade | Abschnitt 6 |
| Niemand testet Linux je | hingenommen — es fällt beim Bauen ohnehin ab |

## 13. Reihenfolge

1. `XPLM_USE_NATIVE_PATHS` (eine Zeile, wirkt sofort, betrifft alle)
2. Thread- und Zeitschicht auf die Standardbibliothek
3. POSIX-Netzschicht hinter die vorhandene Schnittstelle
4. Prüfprogramm auf dem VPS, Abschnitt 9
5. Workflow, Paket, `LIESMICH.txt`, Download-Seite
6. Kontrollstart Windows durch den Nutzer → erst danach hochladen
