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

class FriesenSpyView extends AppView<RequiredProps<AppViewProps, "bus">> {
  /** Das eingebettete Fenster -- Empfaenger der Positionsmeldungen. */
  private readonly rahmenRef = FSComponent.createRef<HTMLIFrameElement>();

  private letztePositionMs = 0;
  private positionFehler = 0;
  private letzteMeldung = "";
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
   * das zu wenig. Der Sim weiss es besser, und zwar nur ueber das eigene Flugzeug: Fremder
   * Verkehr ist ueber `GET_AIR_TRAFFIC` nicht zu bekommen (kein Multiplayer-Verkehr,
   * DevSupport 3794; in der Luft erzeugte AI-Objekte fehlen, DevSupport 4993).
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
  private positionSenden(): void {
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

      // Beim Laden eines Fluges liefern die Variablen kurzzeitig Unsinn (0/0 mitten im
      // Atlantik oder NaN). So etwas weiterzureichen hiesse, die Karte an einen Ort zu
      // schieben, an dem niemand ist.
      if (!isFinite(lat) || !isFinite(lon) || (lat === 0 && lon === 0)) {
        return;
      }

      // Nur senden, wenn sich wirklich etwas geaendert hat. Auf 5 Nachkommastellen gerundet
      // sind das gut anderthalb Meter -- feiner braucht es eine Karte nicht, und am Boden
      // mit stehendem Motor schweigt die Bruecke damit ganz.
      const meldung = lat.toFixed(5) + "," + lon.toFixed(5) + "," + Math.round(hdg);
      if (meldung === this.letzteMeldung) {
        return;
      }
      this.letzteMeldung = meldung;

      ziel.postMessage(
        { quelle: "friesenspy-shell", art: "position", lat: lat, lon: lon, hdg: hdg, gs: gs },
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

  /** @inheritdoc */
  public onUpdate(time: number): void {
    super.onUpdate(time);
    if (this.positionFehler >= POSITION_MAX_FEHLER) {
      return;
    }
    if (time - this.letztePositionMs < POSITION_INTERVALL_MS) {
      return;
    }
    this.letztePositionMs = time;
    this.positionSenden();
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
