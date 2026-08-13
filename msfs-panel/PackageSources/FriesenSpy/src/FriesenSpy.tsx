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
   * TERMINATE statt SLEEP (Live-Test-Fund 13.08.2026): Mit SLEEP bleibt die App beim
   * Schliessen des Tablets samt geladenem iframe im Speicher -- die Seite wurde dadurch NIE
   * neu geladen, auch nicht nach einem Deploy. Der Nutzer musste den kompletten Sim
   * beenden, um eine neue Version zu sehen, und mehrere "live getestete" Fixes wurden in
   * Wahrheit nie geladen. TERMINATE zerstoert die App beim Verlassen
   * (s. efb_api/dist/AppLifecycle.d.ts), sodass ein Schliessen/Oeffnen des Tablets die
   * Seite frisch holt. Kosten: das Panel laedt beim Oeffnen jedes Mal neu -- akzeptabel,
   * weil die Seite ohnehin ihren Zustand aus der URL (#tab=...) wiederherstellt.
   */
  public SuspendMode = AppSuspendMode.TERMINATE;

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
