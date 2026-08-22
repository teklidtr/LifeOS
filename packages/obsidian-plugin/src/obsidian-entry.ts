import { join } from "node:path";

import {
  FileSystemAdapter,
  getAllTags,
  ItemView,
  MarkdownView,
  Plugin,
  PluginSettingTab,
  Setting,
  TFile,
  type WorkspaceLeaf,
} from "obsidian";

import {
  LifeOSPlugin as LifeOSController,
  type ObsidianHost,
} from "./index.js";
import type { LifeOSSettings } from "./protocol.js";
import { StdioBridgeClient } from "./stdio-bridge-client.js";

const VIEW_DETAILS: Record<string, { title: string; icon: string }> = {
  [LifeOSController.VIEW_TYPE]: { title: "LifeOS Today", icon: "layout-dashboard" },
  [LifeOSController.COPILOT_VIEW_TYPE]: { title: "Goal-to-Plan Copilot", icon: "route" },
  [LifeOSController.REVIEW_VIEW_TYPE]: { title: "LifeOS Reviews", icon: "clipboard-check" },
  [LifeOSController.KNOWLEDGE_CONVERSATION_VIEW_TYPE]: { title: "Knowledge Conversation", icon: "messages-square" },
  [LifeOSController.EXPERIMENT_VIEW_TYPE]: { title: "Personal Experiments", icon: "flask-conical" },
  [LifeOSController.RICH_CAPTURE_VIEW_TYPE]: { title: "Rich Capture", icon: "camera" },
};

function defaultSettings(plugin: Plugin): LifeOSSettings {
  const adapter = plugin.app.vault.adapter;
  const vaultRoot = adapter instanceof FileSystemAdapter ? adapter.getBasePath() : "";
  return {
    configPath: vaultRoot ? join(vaultRoot, "lifeos.yml") : "lifeos.yml",
    pythonPath: "python3",
    actorId: "obsidian-local",
    startOnLoad: true,
    diagnostics: "normal",
  };
}

class LifeOSItemView extends ItemView {
  constructor(
    leaf: WorkspaceLeaf,
    private readonly type: string,
    private readonly model: unknown,
  ) {
    super(leaf);
  }

  getViewType(): string {
    return this.type;
  }

  getDisplayText(): string {
    return VIEW_DETAILS[this.type]?.title ?? "LifeOS";
  }

  getIcon(): string {
    return VIEW_DETAILS[this.type]?.icon ?? "layout-dashboard";
  }

  async onOpen(): Promise<void> {
    this.render();
  }

  private render(): void {
    this.contentEl.empty();
    this.contentEl.addClass("lifeos-view");
    this.contentEl.createEl("h2", { text: this.getDisplayText() });

    const state = this.readState();
    this.contentEl.createEl("p", {
      cls: `lifeos-state lifeos-state-${state.kind}`,
      text: state.detail,
    });
    if (state.action) {
      const button = this.contentEl.createEl("button", { text: state.action.label });
      button.addEventListener("click", state.action.run);
    }
  }

  private readState(): {
    kind: string;
    detail: string;
    action?: { label: string; run: () => void };
  } {
    if (!this.model || typeof this.model !== "object" || !("state" in this.model)) {
      return { kind: "ready", detail: "The LifeOS workspace is ready." };
    }
    const state = (this.model as { state?: unknown }).state;
    if (!state || typeof state !== "object") {
      return { kind: "ready", detail: "The LifeOS workspace is ready." };
    }
    const record = state as Record<string, unknown>;
    const kind = typeof record.kind === "string"
      ? record.kind
      : typeof record.stage === "string"
        ? record.stage
        : "ready";
    const detail = typeof record.detail === "string"
      ? record.detail
      : kind === "loading"
        ? "Connecting to the local LifeOS engine…"
        : "Connected to the local LifeOS engine.";
    const action = record.action;
    return {
      kind,
      detail,
      action: action && typeof action === "object"
        && typeof (action as { label?: unknown }).label === "string"
        && typeof (action as { run?: unknown }).run === "function"
        ? action as { label: string; run: () => void }
        : undefined,
    };
  }
}

class ObsidianHostAdapter implements ObsidianHost {
  constructor(private readonly plugin: LifeOSObsidianPlugin) {}

  addRibbonIcon(icon: string, title: string, callback: () => void): () => void {
    const element = this.plugin.addRibbonIcon(icon, title, callback);
    return () => element.remove();
  }

  addCommand(id: string, name: string, callback: () => void): () => void {
    this.plugin.addCommand({ id, name, callback });
    // Obsidian owns command cleanup with the plugin lifecycle.
    return () => {};
  }

  registerView(type: string, factory: () => unknown): () => void {
    this.plugin.registerView(type, (leaf) => new LifeOSItemView(leaf, type, factory()));
    return () => {
      void this.plugin.app.workspace.detachLeavesOfType(type);
    };
  }

  openView(type: string): void {
    void this.openViewAsync(type);
  }

  async saveSettings(settings: LifeOSSettings): Promise<void> {
    await this.plugin.saveSettings(settings);
  }

  getActiveFilePath(): string | undefined {
    return this.plugin.app.workspace.getActiveFile()?.path;
  }

  getSelectedText(): string | undefined {
    return this.plugin.app.workspace.getActiveViewOfType(MarkdownView)?.editor.getSelection();
  }

  getActiveFolderPath(): string | undefined {
    return this.plugin.app.workspace.getActiveFile()?.parent?.path;
  }

  getActiveTag(): string | undefined {
    const file = this.plugin.app.workspace.getActiveFile();
    if (!file) return undefined;
    const cache = this.plugin.app.metadataCache.getFileCache(file);
    return cache ? getAllTags(cache)?.[0] : undefined;
  }

  openFilePath(path: string): void {
    const file = this.plugin.app.vault.getAbstractFileByPath(path);
    if (file instanceof TFile) void this.plugin.app.workspace.getLeaf(false).openFile(file);
  }

  private async openViewAsync(type: string): Promise<void> {
    let leaf = this.plugin.app.workspace.getLeavesOfType(type)[0];
    if (!leaf) {
      leaf = this.plugin.app.workspace.getRightLeaf(false)
        ?? this.plugin.app.workspace.getLeaf("tab");
      await leaf.setViewState({ type, active: true });
    }
    await this.plugin.app.workspace.revealLeaf(leaf);
  }
}

class LifeOSSettingTab extends PluginSettingTab {
  constructor(private readonly lifeos: LifeOSObsidianPlugin) {
    super(lifeos.app, lifeos);
  }

  getSettingDefinitions(): [] {
    return [];
  }

  getControlValue(key: string): unknown {
    return this.lifeos.settings[key as keyof LifeOSSettings];
  }

  async setControlValue(key: string, value: unknown): Promise<void> {
    (this.lifeos.settings as unknown as Record<string, unknown>)[key] = value;
    await this.lifeos.saveSettings(this.lifeos.settings);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "LifeOS Settings" });

    new Setting(containerEl)
      .setName("Configuration file")
      .setDesc("Absolute path to this vault's lifeos.yml.")
      .addText((text) => text
        .setPlaceholder("/path/to/vault/lifeos.yml")
        .setValue(this.lifeos.settings.configPath)
        .onChange(async (value) => {
          this.lifeos.settings.configPath = value.trim();
          await this.lifeos.saveSettings(this.lifeos.settings);
        }));

    new Setting(containerEl)
      .setName("Python executable")
      .setDesc("Trusted Python executable where the local LifeOS repository is installed.")
      .addText((text) => text
        .setPlaceholder("/path/to/lifeos/.venv/bin/python")
        .setValue(this.lifeos.settings.pythonPath)
        .onChange(async (value) => {
          this.lifeos.settings.pythonPath = value.trim();
          await this.lifeos.saveSettings(this.lifeos.settings);
        }));

    new Setting(containerEl)
      .setName("Actor ID")
      .setDesc("Local identity recorded by bridge operations.")
      .addText((text) => text
        .setValue(this.lifeos.settings.actorId)
        .onChange(async (value) => {
          this.lifeos.settings.actorId = value.trim();
          await this.lifeos.saveSettings(this.lifeos.settings);
        }));

    new Setting(containerEl)
      .setName("Start on load")
      .setDesc("Start the vault-scoped LifeOS bridge when Obsidian opens.")
      .addToggle((toggle) => toggle
        .setValue(this.lifeos.settings.startOnLoad)
        .onChange(async (value) => {
          this.lifeos.settings.startOnLoad = value;
          await this.lifeos.saveSettings(this.lifeos.settings);
        }));

    new Setting(containerEl)
      .setName("Diagnostic detail")
      .addDropdown((dropdown) => dropdown
        .addOption("quiet", "Quiet")
        .addOption("normal", "Normal")
        .addOption("verbose", "Verbose")
        .setValue(this.lifeos.settings.diagnostics)
        .onChange(async (value) => {
          this.lifeos.settings.diagnostics = value as LifeOSSettings["diagnostics"];
          await this.lifeos.saveSettings(this.lifeos.settings);
        }));

    new Setting(containerEl)
      .setName("Bridge connection")
      .setDesc("Apply the current settings and restart the local bridge.")
      .addButton((button) => button
        .setButtonText("Restart bridge")
        .onClick(async () => this.lifeos.restartBridge()));
  }
}

export default class LifeOSObsidianPlugin extends Plugin {
  settings: LifeOSSettings = defaultSettings(this);
  private controller?: LifeOSController;

  async onload(): Promise<void> {
    const saved = await this.loadData() as Partial<LifeOSSettings> | null;
    this.settings = { ...defaultSettings(this), ...(saved ?? {}) };
    this.addSettingTab(new LifeOSSettingTab(this));

    const host = new ObsidianHostAdapter(this);
    this.controller = new LifeOSController(host, new StdioBridgeClient(), this.settings);
    await this.controller.load();
  }

  async onunload(): Promise<void> {
    await this.controller?.unload();
    this.controller = undefined;
  }

  async saveSettings(settings: LifeOSSettings): Promise<void> {
    this.settings = settings;
    await this.saveData(settings);
  }

  async restartBridge(): Promise<void> {
    if (!this.controller) return;
    await this.controller.connection.stop();
    await this.controller.connection.start(this.settings);
  }
}
