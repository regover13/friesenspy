# Forum-SSO für FriesenSpy — Design

> **Status:** Richtung bestätigt — Umsetzung terminlich offen · **Datum:** 2026-07-13 · **Autor:** Tobias (+ Claude)
> Zweck dieses Dokuments: den geplanten Single-Sign-On zwischen dem FriesenFlieger-Forum
> und dem Live-Tracker FriesenSpy beschreiben.
>
> **Abstimmung mit Micha (Forum-Admin):** grundsätzlich einverstanden, solange nichts *in*
> die Forensoftware eingebaut wird, sondern separat auf dem Server läuft (gegen die
> Nutzerdatenbank laufen dort ohnehin schon Tools für die Mitgliederverwaltung). Genau das
> beschreibt der gewählte Ansatz. Umsetzung wartet nur auf einen freien Abend bei Micha.

## 1. Ziel

FriesenSpy (`friesenspy.devprops.de`) soll **hinter den Login des FriesenFlieger-Forums**
(`board.friesenflieger.de`) gestellt werden. Konkret:

1. **Zugangsschranke** — die App ist nur für eingeloggte Forum-Mitglieder sichtbar.
2. **Identifikation** — FriesenSpy weiß, *wer* eingeloggt ist (Forum-Account), und kann die
   Ansicht personalisieren (z. B. „meine Flüge / mein Kutter-Beitrag").
3. **Admin-Ablösung** — die heutige Anmeldung über *ein* geteiltes Admin-Passwort wird
   ersetzt: Admin-Rechte ergeben sich aus dem Forum-Status (Gruppe).

**Kernanforderung (vom Nutzer festgelegt):** Das Forum-Passwort darf **niemals** durch
FriesenSpy laufen. → „echtes" SSO per Weiterleitung, nicht Passwort-Eingabe in der App.

## 2. Ausgangslage

- **FriesenSpy** hat heute *keinen* Nutzer-Login — nur ein Admin-Cookie (HMAC über ein
  einzelnes Passwort, `app/auth.py`). Es gibt bisher kein Konzept „eingeloggter Nutzer".
- **Forum:** phpBB **3.3.17**, PHP **8.4.6**, nginx, eigener VPS (217.160.242.47),
  Docroot `/var/www/bb_friesen`, Core unter `…/phpbb/`. HTTPS aktiv.
- Die beiden Dienste laufen auf **getrennten VPS** und unter **getrennten Domains**
  (`board.friesenflieger.de` vs. `friesenspy.devprops.de`).
- **Das Forum kennt die VATSIM-CID bereits** — sie ist je Mitglied im Profil hinterlegt
  (phpBB-Profilfeld). Die Zuordnung Forum-Account → CID muss also *nicht* neu aufgebaut
  werden; `sso.php` kann sie direkt mitliefern.
- Auf dem Forum-Server laufen bereits **eigenständige Tools gegen die Nutzerdatenbank**
  (automatische Mitgliederverwaltung). Ein weiteres, sauber getrenntes Server-Tool ist damit
  ein etabliertes, akzeptiertes Muster — kein Sonderfall.

## 3. Warum dieser Weg (verworfene Alternativen)

| Variante | Idee | Warum verworfen |
|----------|------|-----------------|
| **A — Passwort durch FriesenSpy** | Pilot tippt Forum-Name+Passwort in FriesenSpy, App prüft gegen Forum-DB oder reicht Login durch | Passwort läuft durch zweite App (Vertrauen/Sicherheit); phpBB-Hashes/Login-Formulare können brechen. **Nutzer will das nicht.** |
| **C1 — fertige OAuth/OIDC-Provider-Extension** | phpBB gibt selbst Tokens für Fremd-Apps aus | Existiert für phpBB praktisch nicht gepflegt („years old, unmaintained, incomplete" laut phpBB-Community). phpBB kann OAuth nur als *Client* (Login *mit* Google/Discord). |
| **C3 — externer IdP (Keycloak/Authentik)** | Vollwertiger Identity-Provider vor phpBB | Überdimensioniert für einen Vereins-Tracker; braucht DB-Zugriff + eigenen Betrieb. |
| **Stilles Cookie-Sharing** | Eine Session-Cookie für beide | Unmöglich — verschiedene Domains. |

**Gewählt: C2 — eine kleine, selbstgebaute SSO-Bridge auf der Forum-Domain.** Sie nutzt
phpBBs *echte* Session (kein DB-Direktzugriff, keine Passwort-Hashes, keine bruchgefährdeten
phpBB-Interna) und übersteht phpBB-3.3.x-Updates problemlos.

## 4. Architektur (Redirect-SSO, „OpenID-Connect-light")

```
Pilot ─(1)─▶ FriesenSpy  „Mit Forum anmelden"
                │ Redirect
                ▼
      board.friesenflieger.de/sso.php?redirect=<callback>&state=<zufall>
                │  bindet phpBB common.php ein → kennt die Login-Session
       ┌────────┴─────────┐
   nicht eingeloggt   eingeloggt
       │                  │ baut signiertes Token:
   phpBB-Login         {user_id, username, is_admin, iat, nonce}
   greift, dann          HMAC-SHA256 mit gemeinsamem SSO_SECRET
   zurück                │
                (2) Redirect ▼
      FriesenSpy  GET /auth/forum/callback?token=…&state=…
                │ prüft: Signatur ✔ · state ✔ · iat frisch (≤60 s) ✔ · nonce einmalig ✔
                ▼
      FriesenSpy legt EIGENE Session an (signiertes Cookie) ─(3)─▶ App offen
```

### 4.1 Komponenten

| Ort | Neue Komponente | Aufgabe | Umfang |
|-----|-----------------|---------|--------|
| **Forum** | `/var/www/bb_friesen/sso.php` | phpBB-`common.php` einbinden, Login-Status lesen, signiertes Token bauen, zu FriesenSpy zurückleiten. **Ändert nichts an phpBB.** | 1 kleine PHP-Datei |
| **FriesenSpy** | `GET /auth/forum/login` | erzeugt `state`, leitet zu `sso.php` weiter | Teil eines neuen Auth-Moduls |
| **FriesenSpy** | `GET /auth/forum/callback` | Token verifizieren, FriesenSpy-Session-Cookie setzen | dito |
| **FriesenSpy** | Gate + `logout` | nicht eingeloggt → Login-Redirect; Abmelden löscht FriesenSpy-Session | dito |

Das FriesenSpy-Auth-Modul baut auf dem bestehenden Cookie-Muster in `app/auth.py`
(HMAC-signiertes Cookie, kein Server-Session-Store) auf.

### 4.2 Token-Format

Kompaktes, signiertes Token (JWT **oder** `base64url(payload).hmac` — Detail der Umsetzung):

```json
{ "sub": "<phpbb_user_id>", "name": "<username>", "cid": "<vatsim_cid>",
  "is_admin": true, "iat": 1752400000, "nonce": "<zufall-einmalig>" }
```
signiert mit **HMAC-SHA256** über ein gemeinsames `SSO_SECRET`. Die `cid` stammt direkt aus
dem VATSIM-CID-Profilfeld des Forums — dadurch ist der eingeloggte Nutzer sofort mit seinen
FriesenSpy-Flügen/Kutter-Beiträgen verknüpft, ohne Zutun des Piloten.

### 4.3 Sicherheit

- **`SSO_SECRET`** — langer Zufalls-String, nur in der jeweiligen Server-Config auf beiden
  Seiten (Forum + FriesenSpy), **niemals in git**.
- **Kurzlebig:** Token nur ≤ 60 s ab `iat` gültig.
- **Replay-Schutz:** `nonce` wird von FriesenSpy einmalig verbraucht (kurze Merkliste).
- **CSRF-Schutz:** `state` wird von FriesenSpy gesetzt und beim Callback geprüft.
- **Transport:** ausschließlich HTTPS; `redirect`-Ziel gegen feste Whitelist (nur FriesenSpy).
- Das Forum-Passwort verlässt das Forum **nie**; FriesenSpy sieht nur Name, ID, Admin-Flag.

## 5. Entscheidungen (geklärt)

1. **Wer ist Admin?** → Mitglieder der Forum-Gruppe **„Events" (`g=8`)**. `sso.php` setzt
   `is_admin=true`, wenn der Nutzer in Gruppe 8 ist (Prüfung per phpBB-`group_memberships`).
2. **Forum-Account ↔ VATSIM-CID** → geklärt. Profilfeld heißt **„VatSim-ID"**; `sso.php`
   liest es über den phpBB-Profilfeld-Manager aus (Feldname statt hartkodiertem `field_ident`,
   damit robust). CID landet automatisch im Token.
3. **Alt-Admin-Passwort** → **behalten** (Break-glass). Nötig, weil der Board-Login
   *einschaltbar* sein soll: bei ausgeschaltetem Board-Login und als Notzugang bei Forum-
   Ausfall bleibt das bisherige Admin-Passwort der Weg hinein.
4. **Session-Dauer / Logout** → an die **Forum-Session koppeln**: Wer sich im Forum abmeldet,
   soll auch in FriesenSpy nicht mehr drin sein. FriesenSpy-Session daher **kurz** halten und
   still über `sso.php` nachvalidieren (siehe 6.2). **Logout-Button in FriesenSpy meldet nur
   FriesenSpy ab** (das Forum bleibt eingeloggt).

## 6. Admin-Schalter „Board-Login" (einschaltbar)

Der Forum-Login ist in FriesenSpy **an-/abschaltbar** — die Aktivierung liegt vollständig in
FriesenSpy, nicht am Forum.

- Neue App-Einstellung `forum_login_enabled` (bool) in `app_settings`, Schalter im Admin-Tab
  (analog zur bestehenden Banner-/Einstellungsverwaltung).
- **AUS (Default):** heutiges Verhalten — App öffentlich, Admin über Passwort. `sso.php` wird
  nie aufgerufen und liegt inert im Forum-Docroot.
- **EIN:** Gate aktiv — Besucher müssen sich per Forum anmelden; Admin = Gruppe „Events";
  das Admin-Passwort funktioniert weiter als Break-glass.
- Folge fürs Ausrollen: Datei einmal kopieren, dann **gefahrlos testen** (Schalter an → prüfen
  → bei Problemen sofort wieder aus). Kein Big-Bang.

### 6.2 Forum-Session spiegeln (zu Entscheidung #4)

Ein *sofortiges* Spiegeln des Forum-Logouts ist domainübergreifend nur über den Browser
möglich (FriesenSpy kann die Forum-Session nicht serverseitig einsehen). Pragmatisch:
FriesenSpy-Session kurz halten (z. B. 30–60 min); läuft sie ab, **still per Redirect über
`sso.php` nachvalidieren** — ist der Nutzer im Forum noch eingeloggt, ist das nahtlos (kein
Passwort); ist er dort ausgeloggt, landet er auf der Forum-Login-Seite und ist damit auch aus
FriesenSpy effektiv ausgesperrt. Kompromiss: die Aussperrung greift verzögert (Länge des
Nachvalidierungs-Intervalls), nicht in derselben Sekunde. **Zur Abnahme:** Intervall ok?

## 7. Nicht-Ziele (YAGNI)

- Keine OAuth/OIDC-Vollimplementierung, kein externer IdP.
- Kein Schreiben ins Forum, keine phpBB-Extension, kein phpBB-Core-Patch.
- Kein DB-Direktzugriff auf die Forum-Datenbank.
- Keine Passwort-Verarbeitung in FriesenSpy.

## 8. Änderungen auf FriesenFlieger.de (Forum-Seite)

Bewusst minimal-invasiv. **Nichts** davon fasst phpBB selbst an — alles liegt *neben* dem
Forum und ist jederzeit spurlos entfernbar (Datei löschen → Zustand wie vorher).

1. **Datei `sso.php`** im Docroot `/var/www/bb_friesen/` ablegen (per SSH). Sie
   - bindet phpBBs `common.php` ein und startet die Session (`$user->session_begin()`),
     um den aktuell eingeloggten Nutzer zu lesen (`user_id`, `username`, Gruppen);
   - liest das **VATSIM-CID-Profilfeld** des Nutzers aus;
   - leitet **nicht eingeloggte** Besucher auf phpBBs normale Login-Seite (`ucp.php?mode=login`)
     mit Rücksprung auf sich selbst — den Login macht also phpBB, nicht wir;
   - baut für eingeloggte Nutzer das signierte Token (Abschnitt 4.2) und leitet zum
     FriesenSpy-Callback zurück; das `redirect`-Ziel wird gegen eine feste Whitelist geprüft.
2. **Kleine Config-Datei** (z. B. `/var/www/bb_friesen/sso_config.php`, außerhalb der
   Web-Auslieferung lesbar) mit dem gemeinsamen `SSO_SECRET`. **Nicht** in git, **nicht** in
   phpBBs `config.php`.
3. **Nichts weiter** — Gruppe „Events" (`g=8`) und Profilfeld „VatSim-ID" existieren bereits,
   werden nur *gelesen*. (Den internen `field_ident` liest `sso.php` dynamisch über den
   Feld-Namen; ein einmaliger rein lesender Blick zur Bestätigung schadet nicht, ist aber
   nicht zwingend.)

**Ausdrücklich nicht nötig:** keine phpBB-Extension, kein Core-Patch, kein Hook, kein
Datenbank-Schema-Eingriff, kein Eingriff ins manuelle Update-Prozedere des Forums.

### 8.1 Auf FriesenSpy-Seite (zur Vollständigkeit)

- Neues Auth-Modul (analog `app/auth.py`): `/auth/forum/login` (Redirect zum Forum),
  `/auth/forum/callback` (Token prüfen → eigene Session), `logout`.
- Admin-Schalter `forum_login_enabled` in `app_settings` + Umschalter im Admin-Tab.
- Gate (nur wenn Schalter EIN): nicht eingeloggte Anfragen → Login-Redirect.
- `SSO_SECRET` in FriesenSpys `config.env` (bereits gitignoriert).

## 9. Wie invasiv ist `sso.php`? (Einschätzung für den Forum-Admin)

Konkret, damit Micha den Umfang beurteilen kann — die Datei ist **klein (~70–90 Zeilen)** und
nutzt ausschließlich phpBBs **öffentliche, dokumentierte API**. Sie **liest** nur (Session,
Profilfeld, Gruppen) und **schreibt nirgends** ins Forum. Umriss:

```php
<?php
define('IN_PHPBB', true);
$phpbb_root_path = __DIR__ . '/';
$phpEx = 'php';
include($phpbb_root_path . 'common.' . $phpEx);
include($phpbb_root_path . 'includes/functions_user.' . $phpEx);

$user->session_begin();               // aktuelle Login-Session lesen
$auth->acl($user->data);
$user->setup();

$secret   = require __DIR__ . '/sso_config.php';   // SSO_SECRET
$allowed  = 'https://friesenspy.devprops.de/auth/forum/callback';
$redirect = (string)($_GET['redirect'] ?? '');
$state    = (string)($_GET['state'] ?? '');
if ($redirect !== $allowed) { http_response_code(400); exit('bad redirect'); }

if ((int)$user->data['user_id'] === ANONYMOUS) {   // nicht eingeloggt → phpBB-Login
    login_box(htmlspecialchars_decode($_SERVER['REQUEST_URI']));
    exit;
}

// CID aus Profilfeld "VatSim-ID"
$pf   = $phpbb_container->get('profilefields.manager');
$data = $pf->grab_profile_fields_data((int)$user->data['user_id']);
$cid  = $data[$user->data['user_id']]['pf_vatsim_id']['value'] ?? '';   // Feldname bestätigen

// Admin = Mitglied der Gruppe "Events" (g=8)
$is_admin = !empty(group_memberships(8, (int)$user->data['user_id']));

$payload = rtrim(strtr(base64_encode(json_encode([
    'sub' => (int)$user->data['user_id'],
    'name'=> $user->data['username'],
    'cid' => $cid,
    'is_admin' => (bool)$is_admin,
    'iat' => time(),
    'nonce' => bin2hex(random_bytes(16)),
])), '+/', '-_'), '=');
$sig = hash_hmac('sha256', $payload, $secret);
header('Location: ' . $allowed . '?token=' . $payload . '.' . $sig . '&state=' . rawurlencode($state));
```

**Invasivitäts-Fazit:**
- **Footprint:** 1 Datei + 1 winzige Secret-Datei im Docroot. Keine DB-Migration, kein Hook,
  kein Autoload-Eintrag, kein Composer-Paket.
- **Berührt phpBB nur lesend** über stabile 3.3.x-API (`common.php`, `session_begin`,
  `profilefields.manager`, `group_memberships`). Überlebt 3.3.x-Punkt-Updates. Ein
  4.0-Major-Upgrade bräuchte ggf. eine kleine Anpassung an *dieser einen* Datei.
- **Entfernbar:** Datei löschen → Forum exakt wie vorher.
- **Inert bis genutzt:** reagiert nur auf Aufrufe mit gültigem `redirect`; und FriesenSpy ruft
  sie nur, wenn der Board-Login-Schalter an ist.
- **Kein voller Abend:** das Ablegen + Testen ist überschaubar; der Löwenanteil der Arbeit
  liegt auf der FriesenSpy-Seite, nicht bei Micha.
