<?php
// Vorlage — echte Datei heißt sso_config.php, liegt NEBEN sso.php und ist NICHT in git.
return [
    // Muss identisch zu SSO_SECRET in FriesenSpys config.env sein (langer Zufallsstring):
    'sso_secret'   => 'HIER-LANGES-GEHEIMNIS-EINSETZEN',
    // Erlaubtes Rücksprung-Ziel (muss FORUM_SSO_CALLBACK in FriesenSpy entsprechen):
    'callback'     => 'https://friesenspy.devprops.de/auth/forum/callback',
    // Interner phpBB-Feldname des VATSIM-CID-Profilfelds „VatSim-ID"
    // (per `SELECT field_ident FROM phpbb_profile_fields;` bestätigen):
    'cid_field'    => 'pf_vatsim_id',
    // phpBB-Gruppen-ID, die FriesenSpy-Admin ergibt (Gruppe „Events"):
    'admin_gid'    => 8,
];
