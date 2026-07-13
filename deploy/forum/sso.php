<?php
/**
 * FriesenSpy Board-Login-Bridge für phpBB 3.3.
 *
 * Liegt im Forum-Docroot (/var/www/bb_friesen/). Liest NUR die phpBB-Session, das
 * VATSIM-CID-Profilfeld und die Gruppen-Mitgliedschaft — schreibt NIE ins Forum.
 * Kein phpBB-Patch, keine Extension. Löschen = Zustand wie vorher.
 *
 * Ablauf: nicht eingeloggt -> phpBBs eigene Login-Seite (danach zurück hierher).
 * Eingeloggt -> signiertes Kurz-Token (HMAC-SHA256 über base64url(payload)) an FriesenSpy.
 */
define('IN_PHPBB', true);
$phpbb_root_path = __DIR__ . '/';
$phpEx = 'php';
include($phpbb_root_path . 'common.' . $phpEx);
include($phpbb_root_path . 'includes/functions_user.' . $phpEx);

$cfg = require __DIR__ . '/sso_config.php';

$user->session_begin();
$auth->acl($user->data);
$user->setup();

// Rücksprung-Ziel gegen Whitelist prüfen (kein offener Redirect).
$redirect = isset($_GET['redirect']) ? (string) $_GET['redirect'] : '';
$state    = isset($_GET['state']) ? (string) $_GET['state'] : '';
if (!hash_equals($cfg['callback'], $redirect)) {
    http_response_code(400);
    exit('bad redirect');
}

// Nicht eingeloggt -> phpBBs Login-Seite, danach zurück auf genau diese URL.
if ((int) $user->data['user_id'] === ANONYMOUS) {
    login_box(build_url(array('redirect')) . '&redirect=' . urlencode($_SERVER['REQUEST_URI']));
    exit;
}

$uid = (int) $user->data['user_id'];

// VATSIM-CID aus dem Profilfeld lesen (Schlüssel pf_phpbb_vatsimid, aus der Config).
$cid = '';
try {
    $pf   = $phpbb_container->get('profilefields.manager');
    $data = $pf->grab_profile_fields_data($uid);
    if (isset($data[$uid][$cfg['cid_field']]['value'])) {
        $cid = (string) $data[$uid][$cfg['cid_field']]['value'];
    }
} catch (\Exception $e) {
    $cid = '';
}

// Admin = Mitglied der Gruppe „Events".
$is_admin = !empty(group_memberships((int) $cfg['admin_gid'], $uid, false));

// Signiertes Kurz-Token bauen. typ="sso" trennt es strikt vom FriesenSpy-Session-Token.
$payload = array(
    'typ'      => 'sso',
    'sub'      => $uid,
    'name'     => (string) $user->data['username'],
    'cid'      => $cid,
    'is_admin' => (bool) $is_admin,
    'iat'      => time(),
    'nonce'    => bin2hex(random_bytes(16)),
);
$json = json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
$payload_b64 = rtrim(strtr(base64_encode($json), '+/', '-_'), '=');
$sig = hash_hmac('sha256', $payload_b64, $cfg['sso_secret']);

header('Location: ' . $cfg['callback'] . '?token=' . $payload_b64 . '.' . $sig
    . '&state=' . rawurlencode($state));
exit;
