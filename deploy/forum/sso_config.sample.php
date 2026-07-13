<?php
// Vorlage — echte Datei heißt sso_config.php, liegt NEBEN sso.php und ist NICHT in git.
return [
    // Muss identisch zu SSO_SECRET in FriesenSpys config.env sein (langer Zufallsstring):
    'sso_secret'   => 'HIER-LANGES-GEHEIMNIS-EINSETZEN',
    // Erlaubtes Rücksprung-Ziel (muss FORUM_SSO_CALLBACK in FriesenSpy entsprechen):
    'callback'     => 'https://friesenspy.devprops.de/auth/forum/callback',
    // Schlüssel des VATSIM-CID-Profilfelds „VatSim-ID" im phpBB-Profilfeld-Manager.
    // Bestätigt am 2026-07-13: field_ident = phpbb_vatsimid → Schlüssel pf_phpbb_vatsimid.
    'cid_field'    => 'pf_phpbb_vatsimid',
    // phpBB-Gruppen-ID, die FriesenSpy-Admin ergibt (Gruppe „Events"):
    'admin_gid'    => 8,
];
