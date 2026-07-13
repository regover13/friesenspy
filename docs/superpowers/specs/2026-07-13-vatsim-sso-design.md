# VATSIM-SSO für FriesenSpy — Design (Alternative zur Forum-SSO)

> **Status:** Entwurf / Abwägung · **Datum:** 2026-07-13 · **Autor:** Tobias (+ Claude)
> Schwester-Dokument zu `2026-07-13-forum-sso-design.md`. Gleiches Ziel (Login für
> FriesenSpy), aber **andere Identitätsquelle:** statt des FriesenFlieger-Forums der
> offizielle VATSIM-Login („VATSIM Connect"). Dieses Dokument beschreibt, was dafür nötig
> wäre — und ob es sich lohnt.

## 1. Was ist VATSIM Connect?

VATSIM Connect ist das **zentrale OAuth2-SSO von VATSIM**: Mitglieder melden sich mit ihrem
VATSIM-Account bei Dritt-Diensten an, das Passwort bleibt bei VATSIM. Es ist der Standard,
den vACCs, vSOAs und Dritt-Tools (Booking-Systeme, ACARS, Roster) nutzen.

- **Flow:** OAuth2 **Authorization Code** (mit `client_id` + `client_secret`).
- **Endpunkte** (auf `auth.vatsim.net`): `/oauth/authorize`, `/oauth/token`, User-Endpoint
  `/api/user`.
- **Scopes:** `full_name`, `email`, `vatsim_details` (Ratings/Division/Subdivision),
  `country`. Die **CID** wird als Basis-Identität immer geliefert.
- **Sandbox** zum Testen vor Produktivbetrieb.

## 2. Was liefert das für FriesenSpy?

Nach Login kennt FriesenSpy den Piloten **nativ über seine CID** — genau der Schlüssel,
über den FriesenSpy Flüge/Statistik/Kutter ohnehin führt. Die Verknüpfung Account→CID ist
also nicht nur „vorhanden", sondern **ist** die Identität. Dazu Name und (mit Scope) Rating.

## 3. Architektur (Standard-OAuth2)

```
Pilot ─(1)─▶ FriesenSpy „Mit VATSIM anmelden"
                │ Redirect mit client_id, redirect_uri, scope, state
                ▼
      auth.vatsim.net/oauth/authorize   ← Login + Zustimmung passieren HIER bei VATSIM
                │ (2) Redirect zurück mit ?code=…&state=…
                ▼
      FriesenSpy /auth/vatsim/callback
                │ (3) POST /oauth/token  (code + client_id + client_secret)  → access_token
                │ (4) GET /api/user  (Bearer access_token)  → { cid, name, rating, … }
                ▼
      FriesenSpy legt EIGENE Session an (wie gehabt) ─▶ App offen
```

Das ist ein **ausgetretener Standard-Pfad** — jede OAuth2-Client-Bibliothek kann das; kein
selbstgebautes Token-Format nötig (anders als bei der Forum-Bridge).

## 4. Was ist dafür nötig?

1. **Organisation bei VATSIM registrieren** — Login auf `auth.vatsim.net`, unter
   *Organisation verwalten* (`auth.vatsim.net/manage`) eine Organisation anlegen.
2. **Freigabe abwarten** — die Genehmigung ist **nicht sofort** und kann dauern (manueller
   VATSIM-Prozess). Das ist eine **externe Abhängigkeit**, die wir nicht steuern.
3. **OAuth2-Client anlegen** — nach Freigabe `client_id` + `client_secret` erzeugen,
   **Redirect-URI** registrieren (`https://friesenspy.devprops.de/auth/vatsim/callback`),
   Scopes wählen (mind. Basis-CID + `full_name`; `vatsim_details` für Rating optional).
4. **Secrets** — `client_id`/`client_secret` in FriesenSpys `config.env` (gitignoriert).
5. **FriesenSpy-Auth-Modul** — OAuth2-Client (`/auth/vatsim/login`, `/auth/vatsim/callback`),
   Gate, Logout. Analog zur Forum-Variante, nur mit Standard-OAuth2 statt eigener Bridge.

### 4.1 Zur „Subdomain"-Frage (Ralfs Hinweis)

Ralf vermutete, der Dienst müsse eine **Subdomain von friesenflieger.de** sein. Technisch
verlangt OAuth2 das **nicht** — die Redirect-URI muss nur eine von uns kontrollierte,
registrierte HTTPS-URL sein; `friesenspy.devprops.de` genügt. Möglich ist, dass VATSIM bei
der **Org-Registrierung** Angaben zu Verein/Homepage erwartet und ein Auftritt unter
`friesenflieger.de` die Freigabe *optisch* erleichtert. → **Vor Registrierung kurz prüfen**,
aber kein harter Blocker. (Ein Umzug auf z. B. `spy.friesenflieger.de` wäre separat machbar,
ist aber unabhängig von der SSO-Technik.)

## 5. Der Haken — und die ehrliche Antwort auf „tun wir uns einen Gefallen?"

**VATSIM Connect identifiziert *jedes* VATSIM-Mitglied weltweit — es beschränkt den Zugang
NICHT auf FriesenFlieger.** Ein erfolgreicher VATSIM-Login sagt nur „dies ist ein gültiger
VATSIM-Pilot", nicht „dies ist ein FriesenFlieger-Mitglied". Für die **Zugangsschranke
(nur Mitglieder)** — eines der drei Kernziele — bräuchte man **zusätzlich** eine
Mitglieder-Positivliste. Und die einzige Quelle dafür ist… die Vereins-/Forums-Mitgliederliste.

Daraus folgt die zentrale Einordnung:

| Kriterium | Forum-SSO (phpBB-Bridge) | VATSIM-SSO (Connect) |
|-----------|--------------------------|----------------------|
| **Zugangsschranke „nur Mitglieder"** | ✅ automatisch (Forum-Login = Mitgliedschaft) | ❌ nicht allein — braucht extra Mitglieder-Allowlist |
| **Identifikation über CID** | ✅ CID kommt aus Forum-Profil | ✅ CID **ist** die Identität (nativ) |
| **Admin-Ableitung** | ✅ aus Forum-Gruppe | ⚠️ VATSIM kennt keine Vereinsrollen → extra Liste nötig |
| **Passwort-Schutz** | ✅ bleibt im Forum | ✅ bleibt bei VATSIM |
| **Externe Abhängigkeit** | keine (eigener Server) | **VATSIM-Freigabe + Dienstverfügbarkeit** |
| **Registrierung/Freigabe** | entfällt | Org anmelden, Freigabe nicht sofort |
| **Umsetzungsaufwand** | 1 Bridge-Datei + FS-Modul | Org-Antrag + Standard-OAuth2-Modul |
| **Reichweite** | nur FriesenFlieger | jeder VATSIM-Pilot (Fluch *und* Segen) |

## 6. Empfehlung

Für die **hier gesetzten Ziele** (Zugangsschranke *nur für Mitglieder* + Identifikation +
Admin) ist die **Forum-SSO die passendere und in sich geschlossene Lösung**: sie liefert die
Mitglieder-Schranke geschenkt, die CID gleich mit, und hängt an keiner externen Freigabe.

**VATSIM Connect lohnt sich, wenn** ein anderes Ziel in den Vordergrund rückt:
- FriesenSpy soll **für alle VATSIM-Piloten** offen einloggbar sein (z. B. öffentliche
  Event-Anmeldung über Vereinsgrenzen hinweg), oder
- man will **bewusst unabhängig vom Forum** sein.

**Hybrid denkbar (später):** VATSIM Connect für die Identität (CID nativ, sauberer Standard)
**plus** Forums-/Mitgliederliste als Positivliste für die Schranke. Das ist aber mehr Technik
als jede Einzellösung und nur sinnvoll, wenn man beides wirklich braucht.

**Fazit zur Ausgangsfrage:** Für „nur Mitglieder rein + wer ist wer + wer ist Admin" tun wir
uns mit VATSIM-SSO allein **keinen** Gefallen — es löst die Schranke nicht und bringt eine
externe Freigabe-Abhängigkeit. Es bleibt die stärkere Option, falls FriesenSpy irgendwann
VATSIM-weit offen sein soll.

## 7. Quellen

- VATSIM Connect / OAuth2 — https://vatsim.dev/services/connect/
- Connect API (Scopes, User-Endpoint) — https://vatsim.dev/api/connect-api/vatsim-connect-api/
- Org-/Client-Verwaltung — https://auth.vatsim.net/manage
