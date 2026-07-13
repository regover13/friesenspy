# FriesenSpy Board-Login-Bridge (`sso.php`) — Installation für den Forum-Admin

Diese **eine Datei** macht den phpBB-Forum-Login als SSO für FriesenSpy nutzbar. Sie liegt
**neben phpBB** im Docroot und **verändert das Forum nicht** (kein Patch, keine Extension, nur
Lesen von Session/Profil/Gruppe). Löschen = Zustand exakt wie vorher.

> **Du bekommst die fertige `sso.php` mit eingetragenem Secret separat von Tobias.**
> Das Secret muss identisch zu `SSO_SECRET` in FriesenSpys `config.env` sein — steht in der
> Datei, die du erhältst, bereits drin. Du musst sie nur ablegen und die Rechte setzen.

> **v2 (Callsign):** Die Bridge liest jetzt zusätzlich die Profilfelder `pf_phpbb_callsign`,
> `pf_phpbb_last_cs` und `pf_phpbb_alt_cs` (FRS-Rufzeichen) und legt sie ins Login-Token —
> weiterhin **rein lesend**, kein Schreibzugriff. FriesenSpy nutzt sie, um Mitglieder eindeutig
> ihrem TeamSpeak-Callsign zuzuordnen. Fehlt eines der Felder, funktioniert alles weiter (das
> Rufzeichen bleibt dann nur leer). Update = einfach die neue Datei über die alte legen.

## Warum 640 (wichtig)

phpBB läuft als Benutzer `www-data`, der Mitglied der Gruppe `www-bb_friesen` ist. Damit
`www-data` die Datei **lesen** kann, aber sie **nicht welt-lesbar** ist (sie enthält das
Secret — wie phpBBs eigene `config.php`), gehört sie Gruppe `www-bb_friesen` mit Rechten `640`.

## Schritte (auf dem Forum-Server, Shell-Zugang mit Gruppe `www-bb_friesen` oder root)

```bash
# 1) Datei ins Home hochladen (von deinem Rechner):
scp sso.php <user>@<forum-server>:~/sso.php

# 2) An ihren Platz verschieben:
mv ~/sso.php /var/www/bb_friesen/sso.php

# 3) Gruppe + Rechte setzen (nicht welt-lesbar, www-data liest über die Gruppe):
chgrp www-bb_friesen /var/www/bb_friesen/sso.php
chmod 640          /var/www/bb_friesen/sso.php

# 4) Ergebnis prüfen — sollte so aussehen: -rw-r----- ... www-bb_friesen ...
ls -l /var/www/bb_friesen/sso.php

# 5) PHP-Syntax prüfen — muss "No syntax errors detected" liefern:
php -l /var/www/bb_friesen/sso.php
```

## Funktionstest (im Browser, als eingeloggtes Forum-Mitglied)

```
https://board.friesenflieger.de/sso.php?redirect=https://friesenspy.devprops.de/auth/forum/callback&state=test
```

- **Nicht eingeloggt:** phpBBs normale Anmeldeseite erscheint (mit korrektem Layout) → nach
  Login geht es weiter.
- **Eingeloggt:** leitet sofort zurück auf `…/auth/forum/callback?token=…&state=test`.
  (Bei `state=test` zeigt FriesenSpy danach „Ungültiger SSO-Status" — das ist **korrekt**, weil
  der manuelle Aufruf den echten Login-Schritt überspringt. Der echte Weg über FriesenSpy
  funktioniert.)

## Scharfschalten

Erst wenn die Datei liegt: **Tobias** schaltet in FriesenSpy (Admin-Tab → „Board-Login") den
Schalter **an**. Ab dann ist die App nur noch für eingeloggte Forum-Mitglieder sichtbar;
Mitglieder der Gruppe **„Events"** sind automatisch FriesenSpy-Admin.

## Entfernen / Rückbau

```bash
rm /var/www/bb_friesen/sso.php
```
→ Forum exakt wie vorher. In FriesenSpy den Schalter ausschalten.

## Sicherheit (kurz)

- Das Forum-Passwort verlässt das Forum nie; der Login passiert in phpBB.
- Das Token ist ≤ 60 s gültig, trägt einen Einmal-`nonce` (Replay-Schutz), ist mit dem Secret
  HMAC-signiert und mit `typ:"sso"` typgebunden; das `redirect`-Ziel wird gegen eine feste
  Whitelist geprüft.
- `sso.php` **mit echtem Secret niemals** öffentlich weitergeben oder in git committen (die
  Vorlage im Repo enthält nur einen Platzhalter).
- **Vertrauensanker (bei FriesenFlieger erfüllt):** Das VATSIM-CID-Profilfeld
  (`pf_phpbb_vatsimid`) ist die alleinige Identitätsquelle für FriesenSpy. Es ist hier **fest bei
  der Registrierung verknüpft und für Mitglieder nicht selbst änderbar** (`field_show_on_reg=1`,
  `field_show_profile=0`, bestätigt 2026-07-13) — niemand kann also eine fremde CID eintragen.
  Wer diese Bridge auf einem ANDEREN Forum einsetzt, muss sicherstellen, dass das CID-Feld
  ebenfalls nicht frei editierbar ist (sonst ließen sich fremde Benachrichtigungs-Einstellungen
  setzen).
