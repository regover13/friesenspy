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

class FriesenSpyView extends AppView<RequiredProps<AppViewProps, "bus">> {
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
      // NotificationManager.getManager statt des geerbten `notificationManager`-Getters: der
      // wirft, wenn die Shell ihn nicht in die Props gelegt hat. getManager liefert dasselbe
      // Singleton (statisches INSTANCE, s. efb_api/dist/index.js:6937) und kann nicht fehlen.
      //
      // Bleibend statt fluechtig: Im Flug schaut man nicht dauernd aufs Tablet, und eine
      // permanente Meldung bleibt auf der Benachrichtigungs-Seite der EFB nachlesbar.
      NotificationManager.getManager(this.props.bus).addNotification(
        createPermanentNotification(titel, text, 8000, "info"),
      );
      // Zustellung bestaetigen. Erst diese Antwort (nicht schon das pong) berechtigt die Seite,
      // ihre eigene Ersatzanzeige wegzulassen -- sonst sieht der Nutzer im Fehlerfall NICHTS.
      if (antwort) {
        antwort.postMessage({ quelle: "friesenspy-shell", art: "notify-ok" }, "*");
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
        <iframe class="friesenspy-frame" src={buildPanelUrl()} />
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
    return <FriesenSpyView bus={this.bus} />;
  }
}

Efb.use(FriesenSpy);
