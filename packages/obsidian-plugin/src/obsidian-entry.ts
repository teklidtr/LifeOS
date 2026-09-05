import { join } from "node:path";

import {
  App,
  FileSystemAdapter,
  getAllTags,
  ItemView,
  MarkdownRenderer,
  MarkdownView,
  Modal,
  Plugin,
  PluginSettingTab,
  Setting,
  TFile,
  type WorkspaceLeaf,
} from "obsidian";

import {
  type ConfirmationChallenge,
  formatProposalTimestamp,
  groupProposalsByStatus,
  LifeOSPlugin as LifeOSController,
  type ObsidianHost,
  type ProposalAction,
  type ProposalInspection,
  parseProposalDiff,
  proposalActionsForStatus,
  type ProposalWorkspaceController,
} from "./index.js";
import { LifeOSExploreItemView } from "./explore-obsidian-view.js";
import { LifeOSPersonalModelItemView } from "./personal-model-obsidian-view.js";
import type { LifeOSSettings } from "./protocol.js";
import { StdioBridgeClient } from "./stdio-bridge-client.js";

const VIEW_DETAILS: Record<string, { title: string; icon: string }> = {
  [LifeOSController.VIEW_TYPE]: { title: "LifeOS Today", icon: "layout-dashboard" },
  [LifeOSController.COPILOT_VIEW_TYPE]: { title: "Goal-to-Plan Copilot", icon: "route" },
  [LifeOSController.REVIEW_VIEW_TYPE]: { title: "LifeOS Reviews", icon: "clipboard-check" },
  [LifeOSController.KNOWLEDGE_CONVERSATION_VIEW_TYPE]: { title: "Knowledge Conversation", icon: "messages-square" },
  [LifeOSController.EXPERIMENT_VIEW_TYPE]: { title: "Personal Experiments", icon: "flask-conical" },
  [LifeOSController.RICH_CAPTURE_VIEW_TYPE]: { title: "Rich Capture", icon: "camera" },
  [LifeOSController.PERSONAL_MODEL_VIEW_TYPE]: { title: "Personal Model", icon: "brain-circuit" },
  [LifeOSController.PROPOSAL_VIEW_TYPE]: { title: "LifeOS Proposals", icon: "file-check-2" },
  [LifeOSController.EXPLORE_VIEW_TYPE]: { title: "LifeOS Explore", icon: "compass" },
};

const ACTION_LABELS: Record<ProposalAction, string> = {
  accept: "Accept changes",
  submit: "Submit",
  approve: "Approve",
  apply: "Apply",
  reject: "Reject",
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

class LifeOSProposalItemView extends ItemView {
  private unsubscribe?: () => void;

  constructor(
    leaf: WorkspaceLeaf,
    private readonly controller: ProposalWorkspaceController,
  ) {
    super(leaf);
  }

  getViewType(): string {
    return LifeOSController.PROPOSAL_VIEW_TYPE;
  }

  getDisplayText(): string {
    return VIEW_DETAILS[LifeOSController.PROPOSAL_VIEW_TYPE]?.title ?? "LifeOS Proposals";
  }

  getIcon(): string {
    return VIEW_DETAILS[LifeOSController.PROPOSAL_VIEW_TYPE]?.icon ?? "file-check-2";
  }

  async onOpen(): Promise<void> {
    this.unsubscribe = this.controller.subscribe(() => this.render());
    await this.controller.load();
  }

  async onClose(): Promise<void> {
    this.unsubscribe?.();
    this.unsubscribe = undefined;
  }

  private render(): void {
    const state = this.controller.state;
    this.contentEl.empty();
    this.contentEl.addClass("lifeos-view", "lifeos-proposals");

    const heading = this.contentEl.createDiv({ cls: "lifeos-proposals__heading" });
    heading.createEl("h2", { text: this.getDisplayText() });
    const refresh = heading.createEl("button", { text: "Refresh" });
    refresh.disabled = state.busy !== undefined;
    refresh.addEventListener("click", () => { void this.controller.load(); });

    const status = this.contentEl.createEl("p", {
      cls: `lifeos-state lifeos-state-${state.kind}`,
      text: state.announcement ?? state.detail,
    });
    status.setAttr("role", "status");
    status.setAttr("aria-live", "polite");

    if (state.kind === "error") {
      const retry = this.contentEl.createEl("button", { text: "Retry" });
      retry.addEventListener("click", () => { void this.controller.load(); });
    }
    this.renderOwnershipRecovery();
    if (state.proposals.length === 0) return;

    const workspace = this.contentEl.createDiv({ cls: "lifeos-proposals__workspace" });
    const list = workspace.createEl("nav", {
      cls: "lifeos-proposals__list",
      attr: { "aria-label": "Proposals by lifecycle status" },
    });
    for (const group of groupProposalsByStatus(state.proposals)) {
      const section = list.createEl("section");
      section.createEl("h3", {
        text: `${group.status[0]?.toUpperCase() ?? ""}${group.status.slice(1)} (${group.proposals.length})`,
      });
      for (const proposal of group.proposals) {
        const button = section.createEl("button", {
          cls: "lifeos-proposals__proposal",
          text: proposal.title || proposal.proposal_id,
          attr: {
            "aria-current": state.selected?.proposal_id === proposal.proposal_id ? "true" : "false",
          },
        });
        button.createEl("small", { text: proposal.proposal_id });
        button.createEl("small", {
          cls: "lifeos-proposals__created-at",
          text: `Created ${formatProposalTimestamp(proposal.created_at)}`,
        });
        button.disabled = state.busy !== undefined;
        button.addEventListener("click", () => { void this.controller.select(proposal.proposal_id); });
      }
    }

    const detail = workspace.createEl("article", { cls: "lifeos-proposals__detail" });
    const selected = state.selected;
    if (!selected) {
      detail.createEl("p", { text: "Select a proposal to inspect it." });
      return;
    }
    this.renderInspection(detail, selected);
  }

  private renderOwnershipRecovery(): void {
    const state = this.controller.state;
    if (state.orphanedOwnership.length === 0) return;

    const recovery = this.contentEl.createEl("section", {
      cls: "lifeos-proposals__ownership-recovery",
    });
    recovery.createEl("h3", { text: "Ownership recovery" });
    recovery.createEl("p", {
      text: "These generated targets are missing, but their durable ownership records remain. Refresh and ingestion do not remove those records.",
    });
    for (const orphan of state.orphanedOwnership) {
      const card = recovery.createEl("article", {
        cls: "lifeos-proposals__ownership-card",
      });
      card.createEl("h4", { text: orphan.target_path });
      card.createEl("p", { text: orphan.diagnostic });
      const metadata = card.createEl("dl", { cls: "lifeos-proposals__metadata" });
      this.renderMetadata(metadata, "SHA-256", orphan.content_hash);
      this.renderMetadata(
        metadata,
        "Generator",
        `${orphan.generator_id} ${orphan.generator_version}`,
      );
      this.renderMetadata(metadata, "Created", formatProposalTimestamp(orphan.created_at));
      this.renderMetadata(metadata, "Updated", formatProposalTimestamp(orphan.updated_at));

      const controls = card.createDiv({ cls: "lifeos-proposals__actions" });
      const restore = controls.createEl("button", { text: "Restore instructions" });
      restore.disabled = state.busy !== undefined;
      restore.addEventListener("click", () => {
        this.controller.showRestoreInstructions(orphan.target_path);
      });
      const release = controls.createEl("button", { text: "Create release proposal" });
      release.addClass("mod-warning");
      release.disabled = state.busy !== undefined;
      release.addEventListener("click", () => {
        void this.controller.createOwnershipReleaseProposal(orphan.target_path);
      });

      if (state.restoreTargetPath === orphan.target_path) {
        card.createEl("p", {
          cls: "lifeos-proposals__restore-instructions",
          text: orphan.restore_instructions,
        });
      }
    }
  }

  private renderInspection(container: HTMLElement, inspection: ProposalInspection): void {
    container.createEl("h3", { text: inspection.title || inspection.proposal_id });
    container.createEl("p", { text: inspection.description || "No description supplied." });

    const metadata = container.createEl("dl", { cls: "lifeos-proposals__metadata" });
    this.renderMetadata(metadata, "Proposal ID", inspection.proposal_id);
    this.renderMetadata(metadata, "Status", inspection.status);
    this.renderMetadata(
      metadata,
      "Created",
      formatProposalTimestamp(inspection.created_at),
    );
    this.renderMetadata(metadata, "Review digest", inspection.review_digest);

    const actions = proposalActionsForStatus(inspection.status);
    if (actions.length > 0) {
      const controls = container.createDiv({ cls: "lifeos-proposals__actions" });
      controls.setAttr("aria-label", "Proposal lifecycle actions");
      for (const action of actions) {
        const button = controls.createEl("button", { text: ACTION_LABELS[action] });
        if (action === "accept") button.addClass("mod-cta");
        if (action === "reject") button.addClass("mod-warning");
        button.disabled = this.controller.state.busy !== undefined;
        button.addEventListener("click", () => { void this.controller.execute(action); });
      }
    } else {
      container.createEl("p", {
        cls: "lifeos-proposals__terminal-state",
        text: `This proposal is ${inspection.status}; no lifecycle action is available.`,
      });
    }

    container.createEl("h4", { text: "Proposal body" });
    const body = container.createDiv({ cls: "lifeos-proposals__body markdown-rendered" });
    if (inspection.body.trim()) {
      void MarkdownRenderer.render(this.app, inspection.body, body, "", this);
    } else {
      body.createEl("p", { text: "No proposal body supplied." });
    }

    container.createEl("h4", { text: "Related sources" });
    this.renderStringList(container, inspection.related_sources, "No related sources recorded.");

    container.createEl("h4", { text: "Changes" });
    if (inspection.operations.length === 0) {
      container.createEl("p", { text: "No operations recorded." });
    } else {
      inspection.operations.forEach((operation, index) => {
        const operationContainer = container.createEl("section", {
          cls: "lifeos-proposals__operation",
        });
        operationContainer.createEl("h5", {
          text: `Operation ${index + 1} · ${operation.operation_type}`,
        });
        const target = operationContainer.createEl("p", {
          cls: "lifeos-proposals__operation-target",
          text: "Target: ",
        });
        target.createEl("code", { text: operation.target_path });

        if (operation.preview_source === "legacy_live") {
          operationContainer.createEl("p", {
            cls: "lifeos-proposals__diff-warning",
            text: "Legacy live preview: this proposal predates immutable review snapshots. Later vault changes may make this diff unavailable.",
          });
        }

        if (operation.preview_error) {
          operationContainer.createEl("p", {
            cls: "lifeos-proposals__diff-error",
            text: operation.preview_error,
          });
          return;
        }

        const lines = parseProposalDiff(operation.unified_diff);
        if (lines.length === 0) {
          operationContainer.createEl("p", { text: "No textual changes." });
          return;
        }

        const diff = operationContainer.createDiv({ cls: "lifeos-proposals__diff" });
        diff.setAttr("role", "table");
        diff.setAttr("aria-label", `Diff for ${operation.target_path}`);
        for (const line of lines) {
          const row = diff.createDiv({
            cls: `lifeos-proposals__diff-line lifeos-proposals__diff-line--${line.kind}`,
          });
          row.setAttr("role", "row");
          row.createEl("span", {
            cls: "lifeos-proposals__diff-number",
            text: line.oldLine?.toString() ?? "",
          }).setAttr("aria-hidden", "true");
          row.createEl("span", {
            cls: "lifeos-proposals__diff-number",
            text: line.newLine?.toString() ?? "",
          }).setAttr("aria-hidden", "true");
          row.createEl("code", {
            cls: "lifeos-proposals__diff-code",
            text: line.text || " ",
          });
        }
      });
    }

    container.createEl("h4", { text: "Validation findings" });
    this.renderStringList(container, inspection.findings, "No validation findings.");
  }

  private renderMetadata(container: HTMLElement, label: string, value: string): void {
    container.createEl("dt", { text: label });
    container.createEl("dd", { text: value || "Not available" });
  }

  private renderStringList(container: HTMLElement, values: string[], emptyText: string): void {
    if (values.length === 0) {
      container.createEl("p", { text: emptyText });
      return;
    }
    const list = container.createEl("ul");
    for (const value of values) list.createEl("li", { text: value });
  }
}

class ProposalConfirmationModal extends Modal {
  private settled = false;

  constructor(
    app: App,
    private readonly challenge: ConfirmationChallenge,
    private readonly inspection: ProposalInspection,
    private readonly resolve: (confirmed: boolean) => void,
  ) {
    super(app);
  }

  onOpen(): void {
    const action = ACTION_LABELS[this.challenge.action];
    this.setTitle(
      this.challenge.action === "accept" ? "Accept and apply changes?" : `${action} proposal?`,
    );
    this.contentEl.createEl("p", {
      text: this.challenge.action === "accept"
        ? `Accept and apply “${this.inspection.title || this.inspection.proposal_id}”.`
        : `${action} “${this.inspection.title || this.inspection.proposal_id}”.`,
    });
    this.contentEl.createEl("p", {
      text: this.challenge.action === "accept"
        ? "One confirmation accepts this exact review and applies it. LifeOS still checks every lifecycle transition, the review digest, and current target hashes."
        : this.challenge.action === "apply"
        ? "Applying changes modifies canonical vault content."
        : "This action changes the proposal lifecycle state.",
    });
    this.contentEl.createEl("p", {
      cls: "lifeos-proposals__confirmation-digest",
      text: `Reviewed digest: ${this.challenge.review_digest}`,
    });

    const controls = this.contentEl.createDiv({ cls: "modal-button-container" });
    const cancel = controls.createEl("button", { text: "Cancel" });
    cancel.addEventListener("click", () => this.finish(false));
    const confirm = controls.createEl("button", {
      text: this.challenge.action === "accept" ? action : `${action} proposal`,
    });
    confirm.addClass(
      this.challenge.action === "accept" || this.challenge.action === "approve"
        ? "mod-cta"
        : "mod-warning",
    );
    confirm.addEventListener("click", () => this.finish(true));
    confirm.focus();
  }

  onClose(): void {
    this.contentEl.empty();
    if (!this.settled) this.finish(false, false);
  }

  private finish(confirmed: boolean, close = true): void {
    if (this.settled) return;
    this.settled = true;
    this.resolve(confirmed);
    if (close) this.close();
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
    this.plugin.registerView(type, (leaf) => {
      const model = factory();
      if (type === LifeOSController.PERSONAL_MODEL_VIEW_TYPE) {
        const personalModelView = model as {
          controller: import("./personal-model-workspace.js").PersonalModelWorkspaceController;
        };
        return new LifeOSPersonalModelItemView(leaf, personalModelView.controller);
      }
      if (type === LifeOSController.PROPOSAL_VIEW_TYPE) {
        const proposalView = model as { controller: ProposalWorkspaceController };
        return new LifeOSProposalItemView(leaf, proposalView.controller);
      }
      if (type === LifeOSController.EXPLORE_VIEW_TYPE) {
        const exploreView = model as {
          controller: import("./explore.js").ExploreWorkspaceController;
        };
        return new LifeOSExploreItemView(leaf, exploreView.controller);
      }
      return new LifeOSItemView(leaf, type, model);
    });
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

  executeCommand(id: string): void {
    this.plugin.app.commands.executeCommandById(id);
  }

  async copyText(text: string): Promise<void> {
    await navigator.clipboard.writeText(text);
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

  confirmProposal(
    challenge: ConfirmationChallenge,
    inspection: ProposalInspection,
  ): Promise<boolean> {
    return new Promise((resolve) => {
      new ProposalConfirmationModal(this.plugin.app, challenge, inspection, resolve).open();
    });
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
