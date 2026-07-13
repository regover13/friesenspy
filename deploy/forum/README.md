# FriesenSpy Board-Login-Bridge (`sso.php`)

Diese Datei macht den phpBB-Forum-Login als SSO für FriesenSpy nutzbar. Sie wird **neben
phpBB** abgelegt und **verändert das Forum nicht** (kein Patch, keine Extension, nur Lesen).

## Installation (durch den Forum-Admin)

1. `sso.php` in den Forum-Docroot kopieren: `/var/www/bb_friesen/sso.php`.
2. `sso_config.sample.php` → `sso_config.php` daneben kopieren und ausfüllen:
   - `sso_secret`: langer Zufallsstring, **identisch** zu `SSO_SECRET` in FriesenSpys `config.env`.
   - `callback`: `https://friesenspy.devprops.de/auth/forum/callback`.
   - `cid_field`: Schlüssel des Profilfelds „VatSim-ID" — bestätigt: `pf_phpbb_vatsimid`
     (field_ident `phpbb_vatsimid`).
   - `admin_gid`: `8` (Gruppe „Events").
3. Testen (als eingeloggtes Forum-Mitglied):
   `https://board.friesenflieger.de/sso.php?redirect=https://friesenspy.devprops.de/auth/forum/callback&state=test`
   → leitet mit `?token=…&state=test` zurück.
4. In FriesenSpy: Admin → **Board-Login** einschalten.

## Sicherheit

- Das Forum-Passwort verlässt das Forum nie; der Login passiert in phpBB.
- Das Token ist ≤ 60 s gültig, trägt einen Einmal-`nonce` (Replay-Schutz) und ist mit
  `sso_secret` HMAC-signiert. Das `redirect`-Ziel wird gegen die feste `callback`-Whitelist geprüft.
- `sso_config.php` (mit dem Secret) **niemals** in git; nur `sso_config.sample.php` ist eingecheckt.

## Entfernen

`sso.php` (und `sso_config.php`) löschen → Forum ist exakt wie vorher. In FriesenSpy den
Schalter ausschalten.
