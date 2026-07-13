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
   Dieses `is_admin` schaltet in FriesenSpy das **Admin-Panel** frei (`require_admin` akzeptiert
   eine `fs_user`-Session mit `is_admin`) — Events-Mitglieder brauchen **kein** Passwort mehr.
2. **Forum-Account ↔ VATSIM-CID** → geklärt. Profilfeld „VatSim-ID", bestätigt (2026-07-13,
   rein lesend): `field_ident = phpbb_vatsimid` → Schlüssel **`pf_phpbb_vatsimid`**; `sso.php`
   liest ihn über den phpBB-Profilfeld-Manager aus. CID landet automatisch im Token.
3. **Alt-Admin-Passwort** → **behalten, aber nur als Fallback** (Break-glass): greift, wenn
   **keine** Events-Gruppe erkannt wird (Board-Login aus, Forum-Ausfall, Nicht-Events-Admin).
   Ist eine Events-`fs_user`-Session da, ist kein Passwort nötig (siehe #1).
4. **Session-Dauer / Logout** → FriesenSpy-Session **20 min** (`USER_SESSION_MAX_AGE_SEC=1200`).
   Ein sofortiges Spiegeln des Forum-Logouts geht domainübergreifend nicht; nach spätestens
   20 min (bzw. beim nächsten Ablauf) greift der Forum-Logout, weil die Neu-Anmeldung dann über
   `sso.php` läuft und dort kein Login mehr besteht. **Kein Abmelden-Button** in FriesenSpy
   (Nutzer-Entscheidung) — bei aktivem Board-Login würde er ohnehin sofort per SSO
   wieder anmelden; „richtig raus" = Forum-Logout.

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

### 6.2 Session-Verhalten (umgesetzt)

FriesenSpy-Session **20 min** (`USER_SESSION_MAX_AGE_SEC=1200`), mit zwei Verfeinerungen, damit
aktive Nutzer nicht ständig rausfliegen und lapsende Sessions sich selbst heilen:

- **Sliding-Session:** `GET /api/me` erneuert bei gültigem Login das `fs_user`-Cookie mit
  frischem 20-min-Ablauf. Die SPA pingt `/api/me` alle **5 min** → ein offener Tab bleibt
  eingeloggt, ohne 20-min-Unterbrechung.
- **Auto-Reauth:** meldet `/api/me` „nicht mehr eingeloggt", NACHDEM man eingeloggt war
  (Session/Forum-Login weg), leitet die SPA **still** über `/auth/forum/login` neu an — bei
  noch aktivem Forum-Login praktisch unsichtbar, sonst landet man auf der Forum-Anmeldung.

**Forum-Logout-Spiegelung:** Ein sofortiges Spiegeln geht domainübergreifend nicht. Für einen
**aktiven** Tab hält Sliding die Session am Leben (Forum-Logout wirkt erst, wenn der Tab
untätig/geschlossen ist und die 20 min ablaufen). Für **untätige/geschlossene** Tabs greift der
Forum-Logout nach spätestens 20 min (Ablauf → Auto-Reauth → Forum kein Login mehr). Bewusster
Kompromiss zugunsten von „bleibt eingeloggt, solange man aktiv ist".

### 6.3 Name-Chip & Admin-Login-Link (umgesetzt)

- **Name-Chip** (oben rechts) erscheint nur, wenn der Board-Login **aktiv** ist — `/api/me`
  liefert `board_login_active`; ein altes `fs_user`-Cookie zählt bei ausgeschaltetem Schalter
  nicht (kein Name auf der öffentlichen App). **Kein Abmelden-Button.**
- **„Mit Forum anmelden"-Link** auf der Admin-Login-Seite (`/admin`): erscheint nur bei aktivem
  Board-Login (Frontend liest `board_login_active` aus `/api/me`, das allowlisted ist) und führt
  auf `/auth/forum/login`. Events-Mitglieder kommen so ohne Passwort ins Admin-Panel.

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
2. **Vier Werte im Kopf von `sso.php`** anpassen (`$SSO_SECRET`, `$CALLBACK`, `$CID_FIELD`,
   `$ADMIN_GID`). Das Secret steht direkt in der Datei — sicher, weil PHP ausgeführt und nicht
   als Quelltext ausgeliefert wird (wie phpBBs `config.php`). Keine zweite Datei. Die Datei mit
   echtem Secret **nicht** committen/öffentlich weitergeben.
3. **Nichts weiter** — Gruppe „Events" (`g=8`) und Profilfeld „VatSim-ID" existieren bereits,
   werden nur *gelesen*. (Den internen `field_ident` liest `sso.php` dynamisch über den
   Feld-Namen; ein einmaliger rein lesender Blick zur Bestätigung schadet nicht, ist aber
   nicht zwingend.)

**Ausdrücklich nicht nötig:** keine phpBB-Extension, kein Core-Patch, kein Hook, kein
Datenbank-Schema-Eingriff, kein Eingriff ins manuelle Update-Prozedere des Forums.

### 8.1 Auf FriesenSpy-Seite (umgesetzt)

- **Token-Primitiven** `app/forum_sso.py` (HMAC, `typ`-Trennung, iat/exp/nonce).
- **Endpoints** (`app/main.py`): `GET /auth/forum/login` (state-Cookie + Redirect zum Forum),
  `GET /auth/forum/callback` (Token prüfen → `fs_user`-Session), `GET /auth/forum/logout`,
  `GET /api/me` (Login-Status + `board_login_active`; **Sliding**: erneuert das Cookie).
- **Gate-Middleware** (nur wenn Schalter EIN): nicht eingeloggte Anfragen → Login-Redirect
  (HTML) bzw. 401 (API). Allowlist inkl. `/auth/`, `/static/`, `/admin`, `/api/admin/`,
  `/api/me`, `/widget`, Badge-PNGs, Rechtstexte. **Break-glass-Cookie** `fs_admin_site` (path=/).
- **Admin-Schalter** `forum_login_enabled` in `app_settings` + Umschalter im Admin-Tab.
- **Admin-Ablösung:** `require_admin` akzeptiert eine `fs_user`-Session mit `is_admin`
  (Events-Gruppe) → kein Passwort nötig; `ADMIN_PASSWORD` nur noch Fallback. Admin-Login-Seite
  zeigt einen **„Mit Forum anmelden"-Link** (bei aktivem Board-Login).
- **Frontend:** Name-Chip nur bei aktivem Board-Login, kein Abmelden-Button; SPA pingt `/api/me`
  alle 5 min (Sliding) und macht **Auto-Reauth** bei Session-Verlust.
- `SSO_SECRET`/`FORUM_SSO_URL`/`FORUM_SSO_CALLBACK`/`USER_SESSION_MAX_AGE_SEC` in `config.env`
  (gitignoriert). Version **v9.0.0**.

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

$secret   = $SSO_SECRET;   // aus dem EINSTELLUNGEN-Block oben in derselben Datei
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
$cid  = $data[$user->data['user_id']]['pf_phpbb_vatsimid']['value'] ?? '';   // „VatSim-ID", bestätigt

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
