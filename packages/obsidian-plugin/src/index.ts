import { ConnectionManager } from "./connection.js";
import { BridgeClient, LifeOSSettings } from "./protocol.js";
import { loadingState, ViewState } from "./ui-state.js";

export interface ObsidianHost {
  addRibbonIcon(icon: string, title: string, callback: () => void): () => void;
  addCommand(id: string, name: string, callback: () => void): () => void;
  registerView(type: string, factory: () => LifeOSView): () => void;
  openView(type: string): void;
  saveSettings(settings: LifeOSSettings): Promise<void>;
}

export class LifeOSView {
  state: ViewState = loadingState();
  refreshCount = 0;
  refresh(): void { this.refreshCount += 1; }
}

export class LifeOSPlugin {
  static readonly VIEW_TYPE = "lifeos-today";
  readonly view = new LifeOSView();
  readonly connection: ConnectionManager;
  private disposers: Array<() => void> = [];

  constructor(
    private readonly host: ObsidianHost,
    client: BridgeClient,
    readonly settings: LifeOSSettings,
  ) {
    this.connection = new ConnectionManager(client, () => this.view.refresh());
  }

  async load(): Promise<void> {
    this.disposers.push(this.host.registerView(LifeOSPlugin.VIEW_TYPE, () => this.view));
    this.disposers.push(this.host.addRibbonIcon("layout-dashboard", "Open LifeOS", () => this.openToday()));
    this.disposers.push(this.host.addCommand("lifeos-open-today", "Open LifeOS Today", () => this.openToday()));
    this.disposers.push(this.connection.subscribe((state, detail) => {
      this.view.state = state === "connected"
        ? { kind: "ready", title: "LifeOS", detail: "Connected" }
        : state === "incompatible"
          ? { kind: "blocked", title: "Incompatible LifeOS versions", detail: detail ?? "Update the plugin or engine." }
          : state === "unavailable"
            ? { kind: "error", title: "LifeOS is unavailable", detail: detail ?? "Check Python and the configuration path.", action: { label: "Retry", run: () => { void this.connection.start(this.settings); } } }
            : loadingState();
    }));
    if (this.settings.startOnLoad) await this.connection.start(this.settings);
  }

  openToday(): void { this.host.openView(LifeOSPlugin.VIEW_TYPE); }

  async unload(): Promise<void> {
    for (const dispose of this.disposers.splice(0).reverse()) dispose();
    await this.connection.stop();
  }
}

export * from "./connection.js";
export * from "./protocol.js";
export * from "./ui-state.js";
export * from "./today.js";
export * from "./capture.js";
export * from "./outcomes.js";
export * from "./attention.js";
export * from "./study-session.js";
export * from "./reviews.js";
export * from "./proposals.js";
export * from "./scheduler.js";
export * from "./feedback.js";
