# Rückmeldung an die Server-Sitzung — die MSFS-Seite ist gebaut und ausgeliefert

**Stand: 15.09.2026, 20:00 Uhr.** Geschrieben von der lokalen Windows-Sitzung, als Antwort auf
[`uebergabe-msfs-build.md`](uebergabe-msfs-build.md). Sie konnte alles außer einem: an den
Server. Dafür ist diese Datei da.

**Ausgeliefert** (`/opt/friesenspy/data/efb/`, sha256 lokal = Server gegengeprüft):

| Datei | Fassung | war |
|---|---|---|
| `friesenbruegge.zip` | **1.11.0** | 1.10.0 |
| `friesenspy-efb.zip` | **2.3.0** | 2.2.0 |

---

## ⚠ ZUERST: der Verdacht aus deiner Übergabe war falsch

**Kein BOM.** `layout.json` und `manifest.json` beginnen beide mit `7B 0D 0A 20` (`{\r\n␣`).

**Und die drei Build-Fallen waren es auch nicht.** Das ließ sich ohne Simulator klären — sie
stehen alle in der Import- und Exporttabelle der fertigen `.wasm`:

| Falle | Befund am installierten Modul |
|---|---|
| `/GS-` fehlt | kein `__stack_chk_*` unter den 21 Importen ✅ |
| `--export-table` fehlt | `__indirect_function_table` exportiert ✅ |
| `--allow-undefined` fehlt | alle SimConnect-Funktionen als `env::`-Importe da ✅ |

Dazu: 64 Einträge in der `layout.json`, **null** Größenabweichungen gegen die Platte. Das
Paket war formal einwandfrei.

**Die Ursache stand derweil in Issue #38, bestätigt und ungenutzt.** `g_takt_s` überlebte den
Weltwechsel: `dispatch` setzte `g_sekunden`, `g_spur_anzahl`, `g_vor_gueltig` und
`g_lage_gueltig` zurück — den Takt als einzigen nicht. Wer einmal auf 900 s gedrosselt war,
kam nur über einen **Neustart des Simulators** zurück.

> **Für die nächste Suche:** Dein Ausschluss „Aus-Takt (900 s) schuld? nein — 88 Minuten sind
> sechsmal 900 s" trug nicht. Gemessen wurde mit `--since 3m`; bei 900 s Takt liegt die Chance,
> in drei Minuten eine Anfrage zu sehen, bei 20 %. Ein Nullbefund im kurzen Fenster schließt
> einen langen Takt nicht aus.

---

## 1. ⚠ Was du beim nächsten Protokollsprung wissen musst

**Ein `426` wirkt jetzt dauerhaft.** Neu ist `g_vertrag_tot`: Nach einer abgelehnten
Protokollfassung setzt die Brügge ihren Takt auf 900 s — und **ein Weltwechsel holt sie da
nicht mehr heraus**, im Gegensatz zu jeder anderen Drosselung.

Das ist Absicht (Nutzerentscheidung): In einem Vertrag, den die Gegenseite gekündigt hat,
soll sie nicht nach jedem Flugwechsel wieder anfangen zu reden. Es heißt aber:

> **Die Regel „Server ZUERST" aus der MESSLISTE gilt schärfer als bisher.** Wer beim Deploy
> ein `426` einfängt, ist für die restliche Sitzung weg. Vorher half wenigstens ein
> Flugwechsel.

Jede andere Drosselung — auch dein `_BRUEGGE_TAKT_AUS_S` — fällt beim Weltwechsel auf 1 s
zurück, und die nächste Antwort setzt sie sofort wieder, falls der Schalter noch auf „aus"
steht. Der Ausschalter bleibt also wirksam, ist aber keine Einbahnstraße mehr.

## 2. Die Brügge sagt jetzt, was mit ihr los ist

Sie war das einzige Modul im Simulator ohne eine Zeile im Log. **Das ist der eigentliche
Ertrag dieser Sitzung** — nicht der Takt-Fix. Was jetzt in der DevMode-Konsole steht und was
es dir sagt:

| Zeile | heißt |
|---|---|
| `Fassung 1.11.0 (msfs2024) startet -- verbinde mit SimConnect...` | das Modul lebt (steht **vor** dem `SimConnect_Open`, überlebt also auch einen Absturz darin) |
| `SimConnect verbunden.` | … und hat die Verbindung |
| `bereit -- Takt 1 s, Kennung …, meldet an …` | vollständig hochgelaufen |
| `Der Server setzt den Takt von X s auf Y s.` | **deine** Vorgabe, nur beim Wechsel geloggt |
| `Der Server lehnt ab (HTTP N). Die Bruegge meldet weiter.` | nur beim Wechsel — eine anhaltende Ablehnung flutet nicht |
| `Der Server nimmt wieder an (vorher HTTP N).` | Erholung |
| `Neue Welt -- Takt von X s zurueck auf 1 s.` | der #38-Fix greift |
| `Keine Antwort binnen 30 s -- Anfrage verworfen` | der Wächter hat angeschlagen |
| `Der Server lehnt die Protokollfassung ab (426) …` | toter Vertrag, s. Punkt 1 |

**Die wiederkehrenden hängen bewusst an einer Änderung** (`g_letzter_status`, `!= g_takt_s`).
Im Sekundentakt wären es sonst 3600 Zeilen je Stunde, und ein geflutetes Log ist wertlos für
genau den Fall, für den es gebaut wurde. `tests/test_bruegge_quelltext.py` bindet das.

**Aus dem Kontrollstart** — dieselbe Sitzung, in der vorher 88 Minuten nichts zu sehen war:

```
[FriesenBruegge] bereit -- Takt 1 s, Kennung (noch keine), meldet an …
[FriesenBruegge] Der Server setzt den Takt von 1 s auf 10 s.      ← _BRUEGGE_TAKT_OHNE_VATSIM_S
[FriesenBruegge] Der Server lehnt ab (HTTP 502). Die Bruegge meldet weiter.   ← dein Deploy
[FriesenBruegge] Der Server nimmt wieder an (vorher HTTP 502).
[FriesenBruegge] Neue Welt -- Takt von 10 s zurueck auf 1 s.      ← der Fix, im Echtbetrieb
[FriesenBruegge] Der Server setzt den Takt von 10 s auf 3 s.      ← _BRUEGGE_TAKT_UNERKANNT_S
```

Deine Taktvorgaben sind damit **von der Clientseite aus lesbar**. Das war vorher unmöglich und
ist beim nächsten „sie meldet nicht" die erste Frage, die sich in Sekunden beantworten lässt.

## 3. ⚠ Die Feldnamen sind Vertrag — beide Seiten oder keine

`alt_agl_ft`, `vs_ft_min`, `am_boden`. Eine Umstellung auf die kürzeren der Kniebrett-Nutzlast
(`agl`/`vs`/`gnd`) war angefangen und ist **zurückgenommen** worden, weil du deine Hälfte um
18:44 bereits gepusht hattest (`f9f5e37`).

Sachlich wären die kurzen Namen besser: Die Begründung im Panel-Kommentar („die Seite reicht
sie unverändert an den Server weiter") stimmt nicht — die Brügge meldet an einen **anderen**
Endpunkt in einem **anderen** Format, die Seite muss also ohnehin übersetzen. Das ist jetzt
aber der Preis für eine Änderung an zwei ausgelieferten Seiten, und der lohnt nicht. **Falls
du sie je anfasst: beide gleichzeitig.**

Dein Fund, dass es **drei** Stellen waren und nicht die zwei aus meinem Koordinationseintrag,
ist notiert — der Eintrag ist geradegerückt.

## 4. Was NICHT baubar war (bitte nicht erneut beauftragen)

Punkt 2 deiner Übergabe verlangte, `SimConnect_Open` „im Sekundentakt erneut zu versuchen".
**Das geht nicht**, und zwar aus einem Grund, der sich nicht umgehen lässt:

Ein reines WASM-Modul hat seinen einzigen Taktgeber über SimConnect selbst (`EV_SEKUNDE`).
Scheitert `SimConnect_Open`, gibt es keine Schleife mehr, in der ein zweiter Versuch
stattfinden könnte. Nachgesehen am 15.09.2026 in allen 21 Headern unter
`C:\MSFS 2024 SDK\WASM\include\MSFS`: **keiner** bietet einen Frame- oder Timer-Callback für
Module; `MSFS_Events.h` kennt nur Key-Events.

Ein `sleep` zwischen den Versuchen scheidet ebenfalls aus — es blockierte den
Simulator-Thread mitten im Ladevorgang und zöge mit `poll_oneoff` einen wasi-Import herein,
den die MSFS-Laufzeit womöglich nicht kennt. Das ist dieselbe Mechanik, mit der
`__stack_chk_fail` das Modul vor dem Start tötet.

Gebaut sind deshalb drei Sofortversuche — und vor allem die Logzeile. Vorher war ein
gescheitertes `Open` von einem nie geladenen Modul nicht zu unterscheiden.

## 5. Neu: der Bau prüft sich selbst

`friesenbruegge/msfs/wasm_pruefen.py`, von `bauen.ps1` aufgerufen. Es liest Import- und
Exporttabelle der fertigen `.wasm` und **bricht den Bau ab**, statt ein totes Modul abzulegen.

Gegengeprüft gegen absichtlich falsch gebaute Module: ohne `/GS-` erscheint
`env::__stack_chk_fail`, ohne `--export-table` fehlt die Tabelle, beide werden gemeldet — und
der gute Bau löst keinen Fehlalarm aus.

> ⚠ **Der vierte Fall ist kein Flag.** Zieht neuer Code einen wasi-Import herein, den die
> Laufzeit nicht kennt, stirbt das Modul wie bei Falle 1. Deshalb listet das Skript **alle**
> Importe; sie mit denen des letzten grünen Baus zu vergleichen, ist die eigentliche Prüfung.
> Die neuen Logausgaben kamen so ohne einen einzigen zusätzlichen Import durch — 21 vorher,
> 21 nachher.

## 6. Was offen ist — und für dich zu tun wäre

1. **Issue #38 schließen.** Die Ursache ist behoben und im Echtbetrieb belegt (s. Punkt 2).
   Von hier aus ging das nicht: `gh` hat in dieser Sitzung `HTTP 401: Bad credentials`.
2. **Den Rangwechsel messen.** Ob dein `f9f5e37` greift, ist serverseitig zu sehen — kommt
   `agl` in den Meldungen an, und wechselt der Rang auf 3? Am Client ist es nur indirekt
   sichtbar: Ein `Der Server setzt den Takt von 3 s auf 5 s` heißt
   `_BRUEGGE_TAKT_MIT_KNIEBRETT_S`, also dass du das eigene Kniebrett melden siehst.
3. **Ein Changelog-Eintrag fehlt.** `app/CHANGELOG.json` steht auf 14.49.3; weder deine
   Rangfolge noch die beiden neuen Pakete stehen drin. Die Mitglieder erfahren sonst nirgends,
   dass sie etwas herunterladen sollten — und genau daran hängt der Nutzen: Ohne das Paket
   2.3.0 bleibt jeder auf Rang 2.

   Die Datei gehört dir (`app/`, und während deiner Suite ohnehin tabu). Drei Dinge dabei:
   **`"highlight": false`** (stehende Regel, die rote Marke vergibt ausschließlich der
   Nutzer), die Schreibweise **„FriesenBrügge"** statt nur „Brügge" (der Eintrag speist das
   Banner), und die Hauptnummer bleibt, solange sich im Frontend außerhalb des Admin nichts
   Sichtbares ändert.

   `docs/api.md` ist dagegen **erledigt** — du hast die Felder, die Nutzlast und die
   Rangfolge-Tabelle bereits nachgezogen (Zeilen 2249, 2421, 2513). Hier war nichts offen.

## 7. Was diese Sitzung NICHT angefasst hat

- **`app/`** — durchgehend, wie abgesprochen. Nur gelesen (`main.py:1158`, `index.html:9021`),
  um die Empfängerseite zu verstehen.
- **`friesenbruegge/PROTOKOLL.md`** — der Vertrag ist unverändert. Die Fassungsnummer des
  Protokolls steigt nicht; 1.11.0 ist eine reine Paketfassung.
- **`app/CHANGELOG.json`** — gehört dir, und während deiner Suite ohnehin tabu.

Geändert wurden: `friesenbruegge/msfs/{bruegge.cpp,bauen.ps1,wasm_pruefen.py}`,
`friesenbruegge/{MESSLISTE.md,friesenbruegge.zip}`, `msfs-panel/PackageSources/…`,
`tests/{test_bruegge_quelltext.py,test_vr_panel.py}`, `COORDINATION.md`, `docs/`.

**Acht Regressionstests**, jeder einzeln gegen den entfernten Fix gegengeprüft. **Zwei waren
beim ersten Anlauf blind** und sind verschärft worden: einer fand die Fehlschlag-Meldungen
statt der Startzeile, der andere die Feldnamen im Kommentar statt im Code. Volle Suite grün.
