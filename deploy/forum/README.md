# FriesenSpy Board-Login-Bridge (`sso.php`)

Diese **eine Datei** macht den phpBB-Forum-Login als SSO für FriesenSpy nutzbar. Sie wird
**neben phpBB** abgelegt und **verändert das Forum nicht** (kein Patch, keine Extension, nur
Lesen).

## Installation (durch den Forum-Admin)

1. `sso.php` in den Forum-Docroot kopieren: `/var/www/bb_friesen/sso.php`.
2. Oben im **EINSTELLUNGEN-Block** die vier Werte anpassen:
   - `$SSO_SECRET`: langer Zufallsstring, **identisch** zu `SSO_SECRET` in FriesenSpys `config.env`.
   - `$CALLBACK`: `https://friesenspy.devprops.de/auth/forum/callback`.
   - `$CID_FIELD`: `pf_phpbb_vatsimid` (Profilfeld „VatSim-ID“ — bereits bestätigt, meist unverändert).
   - `$ADMIN_GID`: `8` (Gruppe „Events“).
3. Testen (als eingeloggtes Forum-Mitglied):
   `https://board.friesenflieger.de/sso.php?redirect=https://friesenspy.devprops.de/auth/forum/callback&state=test`
   → leitet mit `?token=…&state=test` zurück.
4. In FriesenSpy: Admin → **Board-Login** einschalten.

Das Secret steht direkt in `sso.php` — das ist sicher, weil PHP **ausgeführt** und nicht als
Quelltext ausgeliefert wird (genau wie in phpBBs eigener `config.php`). Deshalb: `sso.php`
**nicht** öffentlich weitergeben/committen, sobald das echte Secret drinsteht.

## Sicherheit

- Das Forum-Passwort verlässt das Forum nie; der Login passiert in phpBB.
- Das Token ist ≤ 60 s gültig, trägt einen Einmal-`nonce` (Replay-Schutz), ist mit
  `$SSO_SECRET` HMAC-signiert und mit `typ:"sso"` typgebunden. Das `redirect`-Ziel wird gegen
  die feste `$CALLBACK`-Whitelist geprüft.

## Entfernen

`sso.php` löschen → Forum ist exakt wie vorher. In FriesenSpy den Schalter ausschalten.
