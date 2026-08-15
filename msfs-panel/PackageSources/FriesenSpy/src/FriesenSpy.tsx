import {
  App,
  AppBootMode,
  AppInstallProps,
  AppSuspendMode,
  AppView,
  AppViewProps,
  createPermanentNotification,
  Efb,
  NotificationManager,
  RequiredProps,
  TVNode,
} from "@efb/efb-api";
import { DataStore, FSComponent, VNode } from "@microsoft/msfs-sdk";

import "./FriesenSpy.scss";

/**
 * BASE_URL ist eine globale Variable aus build.js, zeigt im gebauten Package
 * auf den eigenen dist-Ordner (fuer Assets wie das App-Icon).
 */
declare const BASE_URL: string;

const PANEL_URL = "https://friesenspy.devprops.de/panel";

/** Schluessel im MSFS-Datenspeicher, unter dem die Geraete-ID liegt. */
const DEVICE_KEY = "friesenspy_device";

/**
 * Zufaellige Geraete-ID erzeugen -- oder "" , wenn das nicht sicher moeglich ist.
 *
 * Die ID ist ein Zugangsschluessel: Wer sie hat, ist als der gebundene Nutzer angemeldet.
 * Deshalb NUR aus einem kryptographischen Zufallsgenerator. Ob `crypto.getRandomValues` in
 * Coherent GT vorhanden ist, ist nicht gesichert -- fehlt es, wird bewusst KEINE Ersatz-ID
 * aus Math.random/Zeitstempel gebaut: Die waere vorhersagbar und damit ein ratbarer
 * Dauerzugang. Lieber verzichtet das Panel auf die Bequemlichkeit und meldet sich wie bisher
 * normal an (buildPanelUrl faellt dann auf die schlichte Panel-Adresse zurueck).
 */
function makeDeviceId(): string {
  const c = (globalThis as { crypto?: { getRandomValues?: (a: Uint8Array) => Uint8Array } }).crypto;
  if (!c || typeof c.getRandomValues !== "function") {
    return "";
  }
  const bytes = c.getRandomValues(new Uint8Array(24));
  let out = "";
  for (let i = 0; i < bytes.length; i++) {
    out += bytes[i].toString(16).padStart(2, "0");
  }
  return out;
}

/**
 * Geraete-ID aus dem persistenten MSFS-Speicher holen, beim ersten Mal anlegen.
 *
 * `DataStore` kapselt `SetStoredData`/`GetStoredData` -- MSFS' eigene, plattenpersistente
 * Ablage. Genau deshalb ueberlebt die ID einen Simulator-Neustart, waehrend Cookies in
 * Coherent GT es nicht tun (der Grund fuer das staendige Neu-Anmelden).
 */
function getOrCreateDeviceId(): string {
  try {
    const vorhanden = DataStore.get<string>(DEVICE_KEY);
    if (typeof vorhanden === "string" && vorhanden.length >= 32) {
      return vorhanden;
    }
    const neu = makeDeviceId();
    DataStore.set(DEVICE_KEY, neu);
    return neu;
  } catch (e) {
    // Steht der Datenspeicher nicht zur Verfuegung, laeuft das Panel eben wie bisher mit
    // normaler Anmeldung weiter -- nie den Start des Panels daran scheitern lassen.
    return "";
  }
}

/**
 * Ziel-Adresse fuers iframe. Mit Geraete-ID ueber /auth/device (meldet automatisch an, wenn
 * das Geraet bereits gebunden ist), sonst direkt aufs Panel wie bisher.
 */
function buildPanelUrl(): string {
  const id = getOrCreateDeviceId();
  if (!id) return PANEL_URL;
  return "https://friesenspy.devprops.de/auth/device?device=" + encodeURIComponent(id)
    + "&next=" + encodeURIComponent("/panel");
}

/** Nachricht, die die eingebettete Seite an diese App schickt. */
interface PanelNachricht {
  quelle?: string;
  art?: string;
  titel?: string;
  text?: string;
  service?: string;
  an?: boolean;
  geparkt?: boolean;
}

/**
 * Wie oft die eigene Position in die Seite gereicht wird.
 *
 * Zweimal pro Sekunde ist der Punkt, an dem eine Karte fluessig wirkt, ohne dass es
 * Verschwendung waere: Die Seite zeichnet ihre Marker ohnehin nur im Sekundentakt neu, und
 * jeder SimVar-Zugriff kostet messbar Zeit (SDK-Doku: "calls to SimVar.GetSimVarValue()
 * incur a non-negligible performance cost"). Bei 60 Bildern/s waere das 120-mal mehr
 * Arbeit fuer dieselbe Anzeige.
 */
const POSITION_INTERVALL_MS = 500;

/** Nach so vielen Fehlgriffen in Folge gibt die Positionsabfrage auf. */
const POSITION_MAX_FEHLER = 5;

/**
 * Spaetestens nach dieser Zeit wird auch eine UNVERAENDERTE Position gemeldet.
 *
 * Das ist kein Feinschliff, sondern die Behebung eines handfesten Fehlers (Live-Test
 * 15.08.2026): Die App sendete nur bei Aenderung, die Seite verwarf eine Position aber nach
 * fuenf Sekunden als tot. Stand das Flugzeug still, kam nichts mehr -- und die Seite hielt
 * die Bruecke fuer abgerissen. Gemessen im Sim: `simAlterMs: 22990` bei `quelle: "keine"`,
 * also eine 23 Sekunden alte Position und beide Kartenknoepfe verschwunden.
 *
 * Zwei fuer sich vernuenftige Entscheidungen ergaben zusammen einen Fehler. Wer regelmaessig
 * gehoert werden will, muss regelmaessig etwas sagen: Ohne Lebenszeichen kann der Empfaenger
 * "frisch" gar nicht beurteilen. Die Aenderungspruefung bleibt trotzdem -- sie haelt die
 * Meldungen klein --, sie kann jetzt nur nicht mehr laenger als diese Spanne schweigen.
 */
const POSITION_HERZSCHLAG_MS = 2000;

/**
 * Wie oft der Verkehr aus dem Simulator geholt wird.
 *
 * Eine Sekunde ist nicht geschaetzt, sondern Asobos eigener Takt in seiner eigenen VFR-Karte
 * (`VfrTrafficManager.POLL_INTERVAL = 1000` im ausgelieferten `GameVFRMap.js`). Zwischen zwei
 * Abrufen rechnet die Seite die Positionen fort -- genau wie Asobos Karte es tut.
 */
const VERKEHR_INTERVALL_MS = 1000;

/**
 * So lange darf ein Abruf hoechstens dauern.
 *
 * `Coherent.call` kann haengen bleiben; das offizielle SDK laesst ihn deshalb gegen eine
 * Sekunde antreten (`Promise.race([Coherent.call(…), Wait.awaitDelay(1000)])`). Ohne diese
 * Grenze bliebe der Riegel gegen Doppelaufrufe im Fehlerfall fuer immer zu.
 */
const VERKEHR_WARTE_MAX_MS = 1000;

/**
 * `alt` kommt aus `GET_AIR_TRAFFIC` in METERN.
 *
 * Nirgends dokumentiert, aber im ausgelieferten Simulator nachzulesen: Das offizielle SDK
 * rechnet in `TrafficInstrument.createContact` mit
 * `UnitType.METER.convertTo(entry.alt, UnitType.FOOT)` um. Ohne diese Zeile stuende an einem
 * Airliner in FL350 die Zahl 10 668 -- und im Label FL107.
 */
const FUSS_JE_METER = 3.28084;

/** Hoechstens so viele Flugzeuge in die Seite reichen -- wie die Obergrenze in /api/traffic. */
const VERKEHR_MAX = 60;

/** Darueber ist der Wert kein Messfehler mehr, sondern Unsinn (SDK: MAX_VALID_GROUND_SPEED). */
const VERKEHR_MAX_GS_KT = 1500;

/**
 * Zeitkonstante der Glaettung, in Sekunden.
 *
 * `2 / Math.LN2` ist der Wert, den das offizielle SDK fuer genau diese Groesse ansetzt
 * (`TrafficContactClass.GROUND_SPEED_TIME_CONSTANT`). Die Rohdaten sind rauschig; ohne
 * Glaettung zappelt die Zahl im Label bei jedem Abruf um zweistellige Betraege.
 */
const VERKEHR_GLAETTUNG_S = 2 / Math.LN2;

/** Darunter gilt ein Flugzeug am Boden als stehend und wird nicht gezeichnet. */
const VERKEHR_STEHT_KT = 5;

/** Naeher und hoehengleicher als das ist kein fremdes Flugzeug -- das sind wir selbst. */
const VERKEHR_EIGEN_M = 150;
const VERKEHR_EIGEN_FT = 100;

/** Erdradius in Metern -- fuer die Entfernung zwischen zwei Meldungen. */
const ERDRADIUS_M = 6371000;

/** Meter je Seemeile -- fuer die Umrechnung der abgeleiteten Geschwindigkeit in Knoten. */
const METER_JE_NM = 1852;

/** Grosskreisentfernung in Metern. Dieselbe Formel wie app/geo.py, nur hier. */
function entfernungM(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const bog = Math.PI / 180;
  const dLat = (lat2 - lat1) * bog;
  const dLon = (lon2 - lon1) * bog;
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2)
    + Math.cos(lat1 * bog) * Math.cos(lat2 * bog) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  return 2 * ERDRADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** Ein Eintrag, wie ihn `GET_AIR_TRAFFIC` liefert. Alle Felder defensiv als optional. */
interface SimVerkehrRoh {
  uId?: number;
  name?: string;
  plane_model_icao?: string;
  lat?: number;
  lon?: number;
  alt?: number;
  heading?: number;
  isOnGround?: boolean;
}

/**
 * Ein Eintrag, wie ihn die Seite bekommt: fertig gerechnet, in Fuss und Knoten.
 *
 * Die Feldnamen sind genau die, die `_verkehrLabel` und `_verkehrPopup` in index.html
 * ohnehin lesen (`ac`, `cs`, `alt`, `gs`, `hdg`) -- deshalb kommt die Seite ohne
 * Uebersetzungsschicht aus und zeichnet beide Quellen ueber denselben Weg.
 */
interface SimVerkehrEintrag {
  id: number;
  lat: number;
  lon: number;
  alt: number;
  hdg: number;
  gs: number;
  ac: string;
  cs: string;
  gnd: boolean;
}

class FriesenSpyView extends AppView<RequiredProps<AppViewProps, "bus">> {
  /** Das eingebettete Fenster -- Empfaenger der Positionsmeldungen. */
  private readonly rahmenRef = FSComponent.createRef<HTMLIFrameElement>();

  private letztePositionMs = 0;
  private positionFehler = 0;
  private letzteMeldung = "";
  /** Wann zuletzt wirklich gesendet wurde (nicht nur geprueft) -- fuer den Herzschlag. */
  private letztesSendenMs = 0;

  /** Ist die Verkehrs-Ebene auf der Seite eingeschaltet? Gemeldet ueber den Rueckkanal. */
  private verkehrAn = false;
  /**
   * Will die Seite gerade auch die geparkten Flugzeuge sehen?
   *
   * Entschieden wird das auf der Seite (an der Zoomstufe), nicht hier -- das Panel kennt die
   * Karte nicht. Weit draussen bleiben Geparkte weg, weil sie sonst zwei Dinge verderben: Sie
   * stehen auf dem eigenen Platz und sind damit IMMER die naechsten, fressen also den
   * Entfernungs-Deckel von vorne auf und verdraengen genau den fliegenden Verkehr, um den es
   * geht. Beim Anflug dreht sich das um -- dort ist das belegte Vorfeld die Information.
   */
  private verkehrGeparkt = false;
  /** Riegel gegen Doppelaufrufe -- das offizielle SDK haelt an derselben Stelle `isBusy`. */
  private verkehrLaeuft = false;
  private letzterVerkehrMs = 0;
  private letzteVerkehrMeldung = "";
  private letztesVerkehrSendenMs = 0;
  /**
   * Letzte Meldung je uId -- die Grundlage der abgeleiteten Geschwindigkeit.
   *
   * `gs: null` heisst "noch nie gerechnet"; der erste Wert wird dann ungeglaettet
   * uebernommen, sonst kroche die Anzeige ueber mehrere Sekunden von 0 aus hoch.
   */
  private readonly verkehrSpur = new Map<
    number,
    { lat: number; lon: number; t: number; gs: number | null }
  >();
  /** Die zuletzt gemeldete eigene Position -- fuer Eigenfilter und Entfernungssortierung. */
  private eigenPos: { lat: number; lon: number; alt: number } | null = null;
  /**
   * Empfaenger fuer Nachrichten aus dem iframe. Als Feld gehalten, damit er in destroy()
   * wieder abgemeldet werden kann -- die App lebt mit AppSuspendMode.SLEEP lange.
   */
  private readonly onNachricht = (e: MessageEvent): void => {
    const d = (e && e.data) as PanelNachricht | undefined;
    if (!d || d.quelle !== "friesenspy") {
      return;
    }

    // Handshake: Die Seite fragt einmal nach, ob wir ihre Nachrichten ueberhaupt bekommen.
    // Ohne Antwort zeigt sie ihre Hinweise selbst an (und meldet den Befund an den Server).
    if (d.art === "ping") {
      const quelle = e.source as Window | null;
      if (quelle) {
        try {
          quelle.postMessage({ quelle: "friesenspy-shell", art: "pong" }, "*");
        } catch (_e) {
          // Antwortweg zu, Seite faellt auf ihre eigene Anzeige zurueck.
        }
      }
      return;
    }

    // Die Ebene ist aus? Dann wird gar nicht erst abgefragt. Ein Coherent.call je Sekunde,
    // dessen Ergebnis niemand zeichnet, ist Arbeit im Simulator ohne jeden Gegenwert.
    if (d.art === "verkehr-schalter") {
      this.verkehrAn = d.an === true;
      this.verkehrGeparkt = d.geparkt === true;
      if (!this.verkehrAn) {
        this.letzteVerkehrMeldung = "";
        this.verkehrSpur.clear();
      }
      return;
    }

    if (d.art !== "notify") {
      return;
    }
    const titel = d.titel || "FriesenSpy";
    const text = d.text || "";
    const antwort = e.source as Window | null;
    try {
      // NUR der von der Shell durchgereichte Manager taugt hier.
      //
      // `NotificationManager.getManager(bus)` sieht robuster aus (statisches Singleton, kann
      // nicht fehlen) und war im ersten Sim-Test genau deshalb der Fehler: `@efb/efb-api` wird
      // in unser Bundle EINKOMPILIERT (nur msfs-sdk/garminsdk sind extern, s. build.js). Unsere
      // Kopie der Klasse hat also ihre eigene statische INSTANCE -- getManager legt eine zweite
      // Verwaltung an, die niemand rendert. Ergebnis: kein Fehler, keine Anzeige, Glocke auf 0.
      const verwaltung = this.props.notificationManager;
      if (!verwaltung) {
        throw new Error("notificationManager fehlt in den Props");
      }

      // Bleibend statt fluechtig: Im Flug schaut man nicht dauernd aufs Tablet, und eine
      // permanente Meldung bleibt auf der Benachrichtigungs-Seite der EFB nachlesbar.
      verwaltung.addNotification(createPermanentNotification(titel, text, 8000, "info"));

      // Zustellung belegen statt behaupten: addNotification legt permanente Meldungen sofort in
      // `_storedNotifications`, was den Ungelesen-Zaehler hochsetzt (efb_api/dist/index.js:6975)
      // -- denselben, den die Glocke zeigt. Steht er auf 0, ist nichts angekommen, und die
      // Seite muss ihre eigene Anzeige behalten. Ein blosses "kein Fehler geworfen" hat im
      // ersten Sim-Test faelschlich Erfolg gemeldet.
      const ungelesen = verwaltung.unseenNotificationsCount.get();
      if (antwort) {
        antwort.postMessage(
          { quelle: "friesenspy-shell", art: "notify-ok", ungelesen: ungelesen },
          "*",
        );
      }
    } catch (err) {
      // Lieber still bleiben als die ganze App an einer Benachrichtigung scheitern lassen --
      // aber die Seite muss davon erfahren, sonst verschluckt das catch den einzigen Hinweis.
      if (antwort) {
        antwort.postMessage(
          { quelle: "friesenspy-shell", art: "notify-fehler", fehler: String(err) },
          "*",
        );
      }
    }
  };

  /**
   * Die eigene Position aus dem Simulator in die Seite reichen.
   *
   * Warum ueberhaupt: Die Seite kennt alle anderen Flugzeuge aus dem VATSIM-Datenstrom, aber
   * das EIGENE nur genauso -- also alle 15 Sekunden und nur, wenn man online verbunden ist.
   * Fuer eine Karte, die dem eigenen Flieger folgen und sich in Flugrichtung drehen soll, ist
   * das zu wenig. Der Sim weiss es besser -- und zwar nicht nur ueber das eigene Flugzeug:
   * Den fremden Verkehr liefert `GET_AIR_TRAFFIC` (s. `verkehrHolen`), auch den von vPilot
   * injizierten. DevSupport 4993 sagt dazu nein, ist fuer MSFS 2024 aber ueberholt -- am
   * 15.08.2026 gemessen, Sim 6 zu VATSIM 6 im selben Umkreis.
   *
   * Warum HIER und nicht in einem eigenen Timer: `onUpdate` ist die Schleife der EFB und
   * laeuft nur, solange die App sichtbar ist. Ein setInterval muesste erst muehsam
   * herausfinden, ob das Tablet ueberhaupt offen ist -- und liefe im Zweifel weiter, waehrend
   * niemand hinsieht. Asobo nennt genau diesen Weg (DevSupport 10986).
   *
   * Die Einheiten sind die aus Asobos eigenem VFR-Karten-Panel: "degree latitude" /
   * "degree longitude". Der SimVar-Name "PLANE HEADING DEGREES TRUE" ist irrefuehrend -- die
   * Variable liegt intern in Radiant, die JS-Schnittstelle rechnet auf die angeforderte
   * Einheit um, deshalb hier ausdruecklich "degrees".
   */
  private positionSenden(jetztMs: number): void {
    const ziel = this.rahmenRef.instance ? this.rahmenRef.instance.contentWindow : null;
    if (!ziel) {
      return;
    }
    try {
      const sv = (globalThis as { SimVar?: { GetSimVarValue(n: string, u: string): number } }).SimVar;
      if (!sv || typeof sv.GetSimVarValue !== "function") {
        this.positionFehler = POSITION_MAX_FEHLER;   // gibt es hier nicht, gar nicht erst weiter versuchen
        return;
      }
      const lat = sv.GetSimVarValue("PLANE LATITUDE", "degree latitude");
      const lon = sv.GetSimVarValue("PLANE LONGITUDE", "degree longitude");
      const hdg = sv.GetSimVarValue("PLANE HEADING DEGREES TRUE", "degrees");
      const gs = sv.GetSimVarValue("GROUND VELOCITY", "knots");
      // Hoehe ueber MSL fuer das Label am eigenen Flugzeug. Ohne sie stand dort im Sim gar
      // nichts (Live-Test 15.08.2026) -- die Seite kennt offline weder Hoehe noch Muster,
      // und die Hoehe ist der Wert, den man im Cockpit auf der Karte sehen will.
      // "PLANE ALTITUDE" in Fuss, dieselbe Einheit wie in Asobos eigenem VFR-Karten-Panel.
      const alt = sv.GetSimVarValue("PLANE ALTITUDE", "feet");

      // Beim Laden eines Fluges liefern die Variablen kurzzeitig Unsinn (0/0 mitten im
      // Atlantik oder NaN). So etwas weiterzureichen hiesse, die Karte an einen Ort zu
      // schieben, an dem niemand ist.
      if (!isFinite(lat) || !isFinite(lon) || (lat === 0 && lon === 0)) {
        return;
      }

      // Auch dann merken, wenn die Meldung gleich als unveraendert verworfen wird: Der
      // Verkehrsteil braucht die eigene Position in JEDEM Takt, nicht nur dann, wenn sich
      // etwas bewegt hat -- sonst faellt am stehenden Flugzeug die Entfernungssortierung aus.
      this.eigenPos = { lat: lat, lon: lon, alt: isFinite(alt) ? alt : 0 };

      // Unveraenderte Positionen werden uebersprungen -- aber NIE laenger als der Herzschlag.
      // Genau daran ist es beim ersten Live-Test gescheitert: Am Boden mit stehendem
      // Flugzeug schwieg die Bruecke ganz, und die Seite hielt sie fuer abgerissen
      // (s. POSITION_HERZSCHLAG_MS). Auf 5 Nachkommastellen gerundet sind das gut anderthalb
      // Meter -- feiner braucht es eine Karte nicht.
      const meldung = lat.toFixed(5) + "," + lon.toFixed(5) + "," + Math.round(hdg);
      const stillGenugLange = (jetztMs - this.letztesSendenMs) >= POSITION_HERZSCHLAG_MS;
      if (meldung === this.letzteMeldung && !stillGenugLange) {
        return;
      }
      this.letzteMeldung = meldung;
      this.letztesSendenMs = jetztMs;

      ziel.postMessage(
        {
          quelle: "friesenspy-shell", art: "position",
          lat: lat, lon: lon, hdg: hdg, gs: gs,
          // Nur senden, wenn die Variable etwas Brauchbares liefert -- die Seite behandelt
          // ein fehlendes Feld anders als eine echte Null (Flugzeug auf Meereshoehe).
          alt: isFinite(alt) ? alt : null,
        },
        "*",
      );
      this.positionFehler = 0;
    } catch (_e) {
      // Nie die App an der Positionsabfrage scheitern lassen -- sie ist eine Zugabe, nicht
      // die Hauptsache. Nach ein paar Fehlgriffen in Folge hoert sie von selbst auf, statt
      // in jedem Bild erneut in denselben Fehler zu laufen.
      this.positionFehler++;
    }
  }

  /**
   * Den Verkehr aus dem Simulator holen -- oder `null`, wenn das nicht geht.
   *
   * Der Wettlauf gegen eine Sekunde ist kein Feinschliff: `Coherent.call` kann haengen
   * bleiben, und der Riegel in `verkehrTakt` bliebe dann fuer immer zu. Das offizielle SDK
   * macht an derselben Stelle dasselbe.
   */
  private async verkehrHolen(): Promise<SimVerkehrRoh[] | null> {
    const c = (globalThis as { Coherent?: { call(n: string): Promise<unknown> } }).Coherent;
    if (!c || typeof c.call !== "function") {
      return null;
    }
    const abbruch = new Promise<null>((loesen) =>
      setTimeout(() => loesen(null), VERKEHR_WARTE_MAX_MS),
    );
    const daten = await Promise.race([c.call("GET_AIR_TRAFFIC"), abbruch]);
    return Array.isArray(daten) ? (daten as SimVerkehrRoh[]) : null;
  }

  /**
   * Ein Abruf je Sekunde, aber nie zwei gleichzeitig.
   *
   * Warum HIER und nicht in einem setInterval: `onUpdate` ist die Schleife der EFB und laeuft
   * nur, solange die App sichtbar ist -- derselbe Grund wie bei der Positionsmeldung.
   */
  private verkehrTakt(time: number): void {
    if (!this.verkehrAn || this.verkehrLaeuft) {
      return;
    }
    if (time - this.letzterVerkehrMs < VERKEHR_INTERVALL_MS) {
      return;
    }
    this.letzterVerkehrMs = time;
    this.verkehrLaeuft = true;
    const auf = (): void => {
      this.verkehrLaeuft = false;
    };
    void this.verkehrSenden(time).then(auf, auf);
  }

  /** Abrufen, aufbereiten, in die Seite reichen. */
  private async verkehrSenden(jetztMs: number): Promise<void> {
    const ziel = this.rahmenRef.instance ? this.rahmenRef.instance.contentWindow : null;
    if (!ziel) {
      return;
    }
    const roh = await this.verkehrHolen();
    if (roh === null) {
      return;
    }
    const liste = this.verkehrAufbereiten(roh, jetztMs);

    // Dieselbe Regel wie bei der Position, aus demselben Grund: Die Seite verwirft eine
    // Quelle, die schweigt. Bei bewegtem Verkehr aendert sich ohnehin jede Sekunde etwas --
    // der Herzschlag greift nur, wenn die Liste unveraendert (oder leer) bleibt.
    const meldung = JSON.stringify(liste);
    const stillGenugLange = (jetztMs - this.letztesVerkehrSendenMs) >= POSITION_HERZSCHLAG_MS;
    if (meldung === this.letzteVerkehrMeldung && !stillGenugLange) {
      return;
    }
    this.letzteVerkehrMeldung = meldung;
    this.letztesVerkehrSendenMs = jetztMs;

    ziel.postMessage({ quelle: "friesenspy-shell", art: "sim-verkehr", liste: liste }, "*");
  }

  /**
   * Grundgeschwindigkeit aus zwei aufeinanderfolgenden Positionen, in Knoten.
   *
   * `GET_AIR_TRAFFIC` liefert sie nicht -- beide Auswerter im Simulator rechnen sie selbst
   * aus. Geglaettet wird exponentiell mit der Zeitkonstante des SDK; unplausible Werte (ein
   * Sprung in den Rohdaten, ein neu geladenes Flugzeug) werden verworfen statt angezeigt.
   */
  private verkehrGsAbleiten(id: number, lat: number, lon: number, jetztMs: number): number {
    const vorher = this.verkehrSpur.get(id);
    let gs: number | null = null;
    if (vorher) {
      gs = vorher.gs;
      const dtS = (jetztMs - vorher.t) / 1000;
      if (dtS > 0) {
        const knoten = (entfernungM(vorher.lat, vorher.lon, lat, lon) / METER_JE_NM)
          / (dtS / 3600);
        if (isFinite(knoten) && knoten <= VERKEHR_MAX_GS_KT) {
          gs = vorher.gs === null
            ? knoten
            : vorher.gs + (1 - Math.exp(-dtS / VERKEHR_GLAETTUNG_S)) * (knoten - vorher.gs);
        }
      }
    }
    this.verkehrSpur.set(id, { lat: lat, lon: lon, t: jetztMs, gs: gs });
    return gs === null ? 0 : gs;
  }

  /**
   * Aus dem Rohsatz die Liste machen, die die Seite zeichnen kann.
   *
   * Die Reihenfolge ist nicht beliebig: Die Geschwindigkeit muss VOR dem Stehen-Filter
   * abgeleitet werden (sonst gibt es nichts zu pruefen), und die Spur muss auch fuer
   * herausgefilterte Flugzeuge fortgeschrieben werden -- sonst faengt die Ableitung bei einem
   * anrollenden Flugzeug jedes Mal von vorn an und es kaeme nie ueber die Schwelle.
   */
  private verkehrAufbereiten(roh: SimVerkehrRoh[], jetztMs: number): SimVerkehrEintrag[] {
    const eigen = this.eigenPos;
    const gesehen = new Set<number>();
    const mitAbstand: { d: number; e: SimVerkehrEintrag }[] = [];

    for (let i = 0; i < roh.length; i++) {
      const r = roh[i];
      const id = Number(r.uId);
      const lat = Number(r.lat);
      const lon = Number(r.lon);
      if (!isFinite(id) || !isFinite(lat) || !isFinite(lon) || (lat === 0 && lon === 0)) {
        continue;
      }
      gesehen.add(id);

      const altFt = Math.round(Number(r.alt) * FUSS_JE_METER) || 0;
      const gs = Math.round(this.verkehrGsAbleiten(id, lat, lon, jetztMs));
      const abstand = eigen ? entfernungM(eigen.lat, eigen.lon, lat, lon) : 0;

      // Wir selbst. Nach heutigem Stand steht das eigene Flugzeug gar nicht in der Liste --
      // aber falls doch, laege sein Symbol genau ueber dem eigenen.
      if (eigen && abstand < VERKEHR_EIGEN_M && Math.abs(altFt - eigen.alt) < VERKEHR_EIGEN_FT) {
        continue;
      }
      // Geparkte -- aber nur, solange die Seite sie nicht ausdruecklich haben will
      // (s. verkehrGeparkt). Rollende bleiben immer drin: am Platz sind sie das Wichtigste.
      if (!this.verkehrGeparkt && r.isOnGround === true && gs < VERKEHR_STEHT_KT) {
        continue;
      }

      mitAbstand.push({
        d: abstand,
        e: {
          id: id,
          lat: Number(lat.toFixed(5)),
          lon: Number(lon.toFixed(5)),
          alt: altFt,
          hdg: (((Math.round(Number(r.heading)) || 0) % 360) + 360) % 360,
          gs: gs,
          ac: String(r.plane_model_icao || ""),
          cs: String(r.name || ""),
          gnd: r.isOnGround === true,
        },
      });
    }

    // Wer nicht mehr gemeldet wird, fliegt aus der Spur -- sonst waechst sie ueber einen
    // langen Flug mit jedem Flugzeug, das je in Reichweite war, und die Geschwindigkeit eines
    // wiederkehrenden uId waere aus einer Stunde alten Daten gerechnet.
    this.verkehrSpur.forEach((_wert, id) => {
      if (!gesehen.has(id)) {
        this.verkehrSpur.delete(id);
      }
    });

    // Naehe entscheidet, nicht die Reihenfolge im Rohsatz -- dieselbe Regel wie in
    // /api/traffic. Ohne eigene Position bleibt die Reihenfolge, wie sie kam.
    mitAbstand.sort((a, b) => a.d - b.d);
    const out: SimVerkehrEintrag[] = [];
    for (let i = 0; i < mitAbstand.length && i < VERKEHR_MAX; i++) {
      out.push(mitAbstand[i].e);
    }
    return out;
  }

  /** @inheritdoc */
  public onUpdate(time: number): void {
    super.onUpdate(time);
    this.positionTakt(time);
    this.verkehrTakt(time);
  }

  private positionTakt(time: number): void {
    if (this.positionFehler >= POSITION_MAX_FEHLER) {
      return;
    }
    if (time - this.letztePositionMs < POSITION_INTERVALL_MS) {
      return;
    }
    this.letztePositionMs = time;
    this.positionSenden(time);
  }

  /** @inheritdoc */
  public onAfterRender(node: VNode): void {
    super.onAfterRender(node);
    window.addEventListener("message", this.onNachricht);
  }

  /** @inheritdoc */
  public destroy(): void {
    window.removeEventListener("message", this.onNachricht);
    super.destroy();
  }

  /**
   * Rendert direkt das eingebettete Panel, ohne AppViewService/Mehrseiten-
   * Navigation -- s. Design-Doku 2026-08-12: nur Web-Einbettung, keine eigene
   * Navigation. AppView.render() erlaubt das laut SDK-Sample-Kommentar
   * ausdruecklich ("can render anything").
   */
  public render(): VNode {
    return (
      <div class="friesenspy-app">
        <iframe ref={this.rahmenRef} class="friesenspy-frame" src={buildPanelUrl()} />
      </div>
    );
  }
}

class FriesenSpy extends App {
  public get name(): string {
    return FriesenSpy.name;
  }

  public get icon(): string {
    return `${BASE_URL}/Assets/app-icon.svg`;
  }

  public BootMode = AppBootMode.COLD;
  /**
   * SLEEP ist hier bewusst die richtige Wahl -- auch wenn sie das Testen unbequemer macht.
   *
   * Vorgeschichte (13.08.2026): Mit SLEEP bleibt die App beim Schliessen des Tablets samt
   * geladenem iframe im Speicher, die Seite wird also NIE neu geladen. Das hat waehrend der
   * Entwicklung viel Verwirrung gestiftet (mehrere "live getestete" Fixes hat das Panel nie
   * geladen). Der naheliegende Griff zu TERMINATE waere aber ein schlechter Tausch: Er
   * erkauft bequemes Testen damit, dass das Panel MITTEN IM FLUG bei jedem Aufklappen neu
   * laedt -- inklusive Verbindungsaufbau, verlorener Scroll-Position und ggf. neuem Login.
   * Das ist der weitaus haeufigere Fall und waere fuer den Nutzer der schlechtere.
   *
   * Stattdessen loest die Web-Seite das Problem dort, wo es hingehoert: Sie erkennt eine
   * neue Version selbst (Versionsvergleich gegen /api/frontend-config) und bietet im
   * Panel-Modus einen "Neu laden"-Knopf an. Im Flug passiert damit nichts, nach einem
   * Deploy genuegt ein Tipp -- und fuer die Fehlersuche reicht das ebenso.
   */
  public SuspendMode = AppSuspendMode.SLEEP;

  public async install(_props: AppInstallProps): Promise<void> {
    Efb.loadCss(`${BASE_URL}/FriesenSpy.css`);
    return Promise.resolve();
  }

  public get compatibleAircraftModels(): string[] | undefined {
    return undefined;
  }

  public render(): TVNode<FriesenSpyView> {
    // Der Benachrichtigungs-Verwalter MUSS von hier an die View gereicht werden: Die View
    // bekommt nur die Props, die hier im JSX stehen -- und die Instanz, die das Tablet
    // anzeigt, gibt es nur ueber diesen Weg (s. langer Kommentar in FriesenSpyView).
    // Der Getter wirft, wenn die Shell ihn nicht gesetzt hat; daran darf das Rendern der
    // ganzen App nicht scheitern.
    let verwaltung: NotificationManager | undefined;
    try {
      verwaltung = this.notificationManager;
    } catch (_e) {
      verwaltung = undefined;
    }
    return <FriesenSpyView bus={this.bus} notificationManager={verwaltung} />;
  }
}

Efb.use(FriesenSpy);
