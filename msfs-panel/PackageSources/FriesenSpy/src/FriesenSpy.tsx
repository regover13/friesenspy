import {
  App,
  AppBootMode,
  AppInstallProps,
  AppSuspendMode,
  AppView,
  AppViewProps,
  Efb,
  RequiredProps,
  TVNode,
} from "@efb/efb-api";
import { FSComponent, VNode } from "@microsoft/msfs-sdk";

import "./FriesenSpy.scss";

/**
 * BASE_URL ist eine globale Variable aus build.js, zeigt im gebauten Package
 * auf den eigenen dist-Ordner (fuer Assets wie das App-Icon).
 */
declare const BASE_URL: string;

const PANEL_URL = "https://friesenspy.devprops.de/panel";

class FriesenSpyView extends AppView<RequiredProps<AppViewProps, "bus">> {
  /**
   * Rendert direkt das eingebettete Panel, ohne AppViewService/Mehrseiten-
   * Navigation -- s. Design-Doku 2026-08-12: nur Web-Einbettung, keine eigene
   * Navigation. AppView.render() erlaubt das laut SDK-Sample-Kommentar
   * ausdruecklich ("can render anything").
   */
  public render(): VNode {
    return (
      <div class="friesenspy-app">
        <iframe class="friesenspy-frame" src={PANEL_URL} />
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
