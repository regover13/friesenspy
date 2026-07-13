<?php
/**
 * ============================================================================
 *  FriesenSpy Board-Login-Bridge für phpBB 3.3
 * ============================================================================
 *
 *  WAS MACHT DIESE DATEI?
 *  Sie erlaubt es dem Live-Tracker "FriesenSpy" (auf einem anderen Server),
 *  seine Besucher über den FriesenFlieger-Forum-Login anzumelden — ohne dass
 *  das Forum-Passwort jemals an FriesenSpy übertragen wird.
 *
 *  ABLAUF IN 3 SCHRITTEN:
 *    1. FriesenSpy schickt den Besucher hierher (mit ?redirect=... & ?state=...).
 *    2. Diese Datei fragt phpBB: "Ist dieser Besucher eingeloggt, und wer ist er?"
 *       - Nein  -> phpBBs normale Login-Seite anzeigen, danach zurück hierher.
 *       - Ja    -> ein kurzes, digital signiertes "Ausweis-Token" bauen.
 *    3. Der Besucher wird zurück zu FriesenSpy geschickt, das Token im Anhang.
 *       FriesenSpy prüft die Signatur und weiß dann sicher, wer angemeldet ist.
 *
 *  WICHTIG / SICHERHEIT:
 *    - Diese Datei LIEST nur (Login-Status, Profilfelder: CID + Rufzeichen, Gruppe). Sie
 *      schreibt NICHTS ins Forum und verändert phpBB nicht. Löschen = alles wie vorher.
 *    - Das Geheimnis ($SSO_SECRET) steht direkt unten drin. Das ist sicher,
 *      weil PHP auf dem Server AUSGEFÜHRT und nie als Quelltext ausgeliefert
 *      wird — genau wie das DB-Passwort in phpBBs eigener config.php.
 *    - Diese Datei mit echtem Secret NICHT öffentlich weitergeben/committen.
 *
 *  INSTALLATION:
 *    - Datei nach /var/www/bb_friesen/sso.php kopieren.
 *    - Unten im EINSTELLUNGEN-Block die vier Werte anpassen (v. a. $SSO_SECRET).
 * ============================================================================
 */

// ===================== EINSTELLUNGEN — diese 4 Werte anpassen =====================

// (1) Gemeinsames Geheimnis. MUSS Zeichen für Zeichen identisch zu SSO_SECRET in
//     FriesenSpys config.env sein. Langer Zufallsstring, z. B. mit `openssl rand -hex 32`.
$SSO_SECRET = 'HIER-LANGES-GEHEIMNIS-EINSETZEN';

// (2) Einzige erlaubte Rücksprung-Adresse (muss FORUM_SSO_CALLBACK in FriesenSpy entsprechen).
//     Schützt davor, dass jemand das Token an eine fremde Seite umleiten lässt.
$CALLBACK   = 'https://friesenspy.devprops.de/auth/forum/callback';

// (3) Schlüssel des Profilfelds mit der VATSIM-CID ("VatSim-ID"). Bereits bestätigt.
$CID_FIELD  = 'pf_phpbb_vatsimid';

// (4) Forum-Gruppen-ID, deren Mitglieder in FriesenSpy Admin-Rechte bekommen (Gruppe "Events").
$ADMIN_GID  = 8;

// (5) Profilfelder mit dem/den FRS-Rufzeichen. Alle nicht-leeren Werte kommen (großgeschrieben,
//     dedupliziert) als Liste `cs` ins Token — FriesenSpy nutzt sie, um Mitglieder eindeutig
//     ihrem TeamSpeak-Callsign zuzuordnen (Benachrichtigungs-Sichtbarkeit). Rein lesend.
$CS_FIELDS  = array('pf_phpbb_callsign', 'pf_phpbb_last_cs', 'pf_phpbb_alt_cs');

// =================================================================================


// --- phpBB laden ------------------------------------------------------------
// Diese Datei liegt IM Forum-Verzeichnis, deshalb können wir phpBBs Kern einbinden.
// `IN_PHPBB` ist eine Pflicht-Konstante, sonst verweigert phpBB das Laden.
define('IN_PHPBB', true);
// WICHTIG: relativer Pfad './' (nicht __DIR__)! phpBB baut aus $phpbb_root_path ALLE URLs
// (CSS/JS/Formular-Action). Ein absoluter Dateisystempfad zerlegt das Layout und führt zu
// falschen Links wie /var/www/.../ucp.php. Das Skript liegt im Docroot -> './' ist korrekt.
$phpbb_root_path = './';
$phpEx = 'php';
include($phpbb_root_path . 'common.' . $phpEx);                    // phpBB-Grundgerüst
include($phpbb_root_path . 'includes/functions_user.' . $phpEx);  // liefert group_memberships()

// Aktuelle Sitzung starten -> danach steht in $user->data, wer (falls überhaupt) eingeloggt ist.
$user->session_begin();
$auth->acl($user->data);
$user->setup();


// --- Eingaben von FriesenSpy prüfen -----------------------------------------
// FriesenSpy hängt zwei Werte an die URL:
//   redirect = wohin das Token zurückgeschickt werden soll
//   state    = eine Zufallsmarke, die FriesenSpy beim Rücksprung wiedererkennt (CSRF-Schutz)
// WICHTIG: phpBB verbietet den direkten Zugriff auf $_GET/$_POST/$_SERVER ("deactivated
// super globals"). Eingaben deshalb IMMER über die Request-Klasse ($request) lesen.
$redirect = $request->variable('redirect', '');
$state    = $request->variable('state', '');

// Sicherheitsriegel: Wir leiten NUR an die eine, fest hinterlegte Adresse zurück.
// (hash_equals vergleicht zeitkonstant — kein Rateln über Antwortzeiten.)
if (!hash_equals($CALLBACK, $redirect)) {
    http_response_code(400);
    exit('bad redirect');
}


// --- Nicht eingeloggt? -> phpBBs Login zeigen -------------------------------
// ANONYMOUS ist phpBBs Kennung für "nicht angemeldet". In dem Fall zeigt phpBB
// sein normales Login-Formular; nach erfolgreichem Login kommt der Besucher
// automatisch wieder auf genau diese Seite (dieselbe URL) zurück.
if ((int) $user->data['user_id'] === ANONYMOUS) {
    // Nach dem Login zurück auf genau diese URL (mit redirect+state). $request->server()
    // statt $_SERVER (deactivated super globals).
    login_box($request->server('REQUEST_URI'));
    exit;
}

// Ab hier ist sicher: Der Besucher IST im Forum eingeloggt.
$uid = (int) $user->data['user_id'];


// --- Daten des eingeloggten Nutzers einsammeln ------------------------------

// VATSIM-CID direkt aus der Profilfeld-Tabelle lesen (robust; die Manager-API liefert je nach
// phpBB-Version verschachtelte Strukturen). $CID_FIELD ist der Spaltenname (aus der Config,
// kein Nutzer-Input -> unbedenklich). Leer, falls nicht gepflegt.
// In derselben Zeile lesen wir auch die FRS-Rufzeichen-Felder (Spaltennamen aus der Config,
// kein Nutzer-Input -> unbedenklich). Aliasse fs_cs0/fs_cs1/... je Feld.
$cid = '';
$cs  = array();
$cs_cols = '';
foreach ($CS_FIELDS as $i => $f) {
    $cs_cols .= ', ' . $f . ' AS fs_cs' . $i;
}
$sql = 'SELECT ' . $CID_FIELD . ' AS fs_cid' . $cs_cols . '
    FROM ' . PROFILE_FIELDS_DATA_TABLE . '
    WHERE user_id = ' . (int) $uid;
$res = $db->sql_query($sql);
$row = $db->sql_fetchrow($res);
$db->sql_freeresult($res);
if ($row) {
    $cid = (string) $row['fs_cid'];
    // Nicht-leere, getrimmte, großgeschriebene, deduplizierte Rufzeichen sammeln.
    foreach ($CS_FIELDS as $i => $f) {
        $v = strtoupper(trim((string) $row['fs_cs' . $i]));
        if ($v !== '' && !in_array($v, $cs, true)) {
            $cs[] = $v;
        }
    }
}

// Admin-Flag: Ist der Nutzer Mitglied der Gruppe "Events"? -> dann in FriesenSpy Admin.
// group_memberships() gibt die Treffer zurück; leer = kein Mitglied.
$is_admin = !empty(group_memberships((int) $ADMIN_GID, $uid, false));


// --- Signiertes "Ausweis-Token" bauen ---------------------------------------
// Inhalt (payload): wer ist es, CID, Admin-ja/nein, Zeitstempel, Einmal-Zufallswert.
//   typ  = "sso"  -> markiert dies als Forum->FriesenSpy-Token (Verwechslungsschutz).
//   iat  = Ausstellungszeit -> FriesenSpy akzeptiert das Token nur ~60 Sekunden lang.
//   nonce= Einmalwert -> FriesenSpy lässt jedes Token nur EINMAL gelten (Replay-Schutz).
$payload = array(
    'typ'      => 'sso',
    'sub'      => $uid,
    'name'     => (string) $user->data['username'],
    'cid'      => $cid,
    'cs'       => $cs,                 // Liste der FRS-Rufzeichen (kann leer sein)
    'is_admin' => (bool) $is_admin,
    'iat'      => time(),
    'nonce'    => bin2hex(random_bytes(16)),
);

// Payload als JSON -> URL-sicheres Base64 (das ist der Teil, der signiert wird).
$json = json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
$payload_b64 = rtrim(strtr(base64_encode($json), '+/', '-_'), '=');

// Signatur: HMAC-SHA256 über den Base64-Text mit dem gemeinsamen Geheimnis.
// Nur wer $SSO_SECRET kennt (Forum + FriesenSpy), kann eine gültige Signatur erzeugen.
$sig = hash_hmac('sha256', $payload_b64, $SSO_SECRET);

// Token = "<payload>.<signatur>". Zurück zu FriesenSpy, state unverändert mitgeben.
header('Location: ' . $CALLBACK . '?token=' . $payload_b64 . '.' . $sig
    . '&state=' . rawurlencode($state));
exit;
