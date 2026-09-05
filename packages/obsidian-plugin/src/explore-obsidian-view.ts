import { ItemView, type WorkspaceLeaf } from "obsidian";

import {
  type CapabilityEntryPoint,
  ExploreWorkspaceController,
  type SemanticCapability,
} from "./explore.js";

export class LifeOSExploreItemView extends ItemView {
  private unsubscribe?: () => void;

  constructor(
    leaf: WorkspaceLeaf,
    private readonly controller: ExploreWorkspaceController,
  ) {
    super(leaf);
  }

  getViewType(): string {
    return "lifeos-explore";
  }

  getDisplayText(): string {
    return "LifeOS Explore";
  }

  getIcon(): string {
    return "compass";
  }

  async onOpen(): Promise<void> {
    this.unsubscribe = this.controller.subscribe(() => this.render());
    this.render();
    await this.controller.load();
  }

  async onClose(): Promise<void> {
    this.unsubscribe?.();
    this.unsubscribe = undefined;
  }

  private render(): void {
    const state = this.controller.state;
    this.contentEl.empty();
    this.contentEl.addClass("lifeos-view", "lifeos-explore");

    const heading = this.contentEl.createDiv({ cls: "lifeos-explore__heading" });
    const title = heading.createDiv();
    title.createEl("h2", { text: this.getDisplayText() });
    title.createEl("p", {
      cls: "lifeos-explore__lede",
      text: "Browse abilities implemented by LifeOS and described by the Python-owned capability registry.",
    });
    const refresh = heading.createEl("button", { text: "Refresh" });
    refresh.disabled = state.busy;
    refresh.addEventListener("click", () => { void this.controller.load(); });

    const status = this.contentEl.createEl("p", {
      cls: `lifeos-state lifeos-state-${state.stage}`,
      text: state.statusAnnouncement || state.detail,
    });
    status.setAttr("role", "status");
    status.setAttr("aria-live", "polite");

    if (state.stage === "loading" || state.stage === "idle") return;

    if (state.stage === "bridge-unavailable") {
      this.renderRecovery(
        "LifeOS is unavailable",
        state.detail,
        "Reconnect",
        () => { void this.controller.reconnect(); },
      );
      return;
    }
    if (state.stage === "malformed") {
      this.renderRecovery(
        "Capability data could not be rendered safely",
        state.detail,
        "Retry",
        () => { void this.controller.load(); },
      );
      return;
    }
    if (state.stage === "error") {
      this.renderRecovery(
        "Explore could not load",
        state.detail,
        "Retry",
        () => { void this.controller.load(); },
      );
      return;
    }
    if (state.stage === "empty") {
      this.contentEl.createEl("p", {
        text: "The bridge returned no Explore-visible capabilities. Internal protocol methods are intentionally not shown here.",
      });
      return;
    }

    this.renderFilters();
    const groups = this.controller.groupedCapabilities;
    if (groups.length === 0) {
      this.contentEl.createEl("p", {
        cls: "lifeos-explore__no-results",
        text: "No capabilities match these filters. Try another search or category.",
      });
      return;
    }

    const workspace = this.contentEl.createDiv({ cls: "lifeos-explore__workspace" });
    const catalog = workspace.createEl("nav", {
      cls: "lifeos-explore__catalog",
      attr: { "aria-label": "LifeOS capabilities" },
    });
    for (const group of groups) {
      const section = catalog.createEl("section", { cls: "lifeos-explore__group" });
      section.createEl("h3", { text: group.category });
      for (const capability of group.capabilities) {
        this.renderCapabilityCard(section, capability);
      }
    }

    const detail = workspace.createEl("article", {
      cls: "lifeos-explore__detail",
      attr: { "aria-label": "Capability details" },
    });
    const selected = this.controller.selected;
    if (selected) this.renderCapabilityDetail(detail, selected);
    else detail.createEl("p", { text: "Select a capability to inspect its details." });
  }

  private renderRecovery(
    title: string,
    detail: string,
    actionLabel: string,
    action: () => void,
  ): void {
    const recovery = this.contentEl.createEl("section", { cls: "lifeos-explore__recovery" });
    recovery.createEl("h3", { text: title });
    recovery.createEl("p", { text: detail });
    const button = recovery.createEl("button", { text: actionLabel });
    button.addEventListener("click", action);
  }

  private renderFilters(): void {
    const filters = this.contentEl.createDiv({ cls: "lifeos-explore__filters" });
    const searchLabel = filters.createEl("label", { text: "Search capabilities" });
    const search = searchLabel.createEl("input", {
      attr: {
        type: "search",
        placeholder: "Name, description, category, requirement…",
        value: this.controller.state.query,
      },
    });
    let composing = false;
    let ignoreNextInput = false;
    const applySearch = () => {
      const selectionStart = search.selectionStart ?? search.value.length;
      const selectionEnd = search.selectionEnd ?? selectionStart;
      this.controller.setQuery(search.value);
      const replacement = this.contentEl.querySelector<HTMLInputElement>(
        ".lifeos-explore__filters input[type=\"search\"]",
      );
      replacement?.focus();
      replacement?.setSelectionRange(selectionStart, selectionEnd);
    };
    search.addEventListener("compositionstart", () => { composing = true; });
    search.addEventListener("compositionend", () => {
      composing = false;
      ignoreNextInput = true;
      applySearch();
    });
    search.addEventListener("input", (event) => {
      if (composing || (event as InputEvent).isComposing) return;
      if (ignoreNextInput) {
        ignoreNextInput = false;
        return;
      }
      applySearch();
    });

    const categoryLabel = filters.createEl("label", { text: "Category" });
    const category = categoryLabel.createEl("select");
    category.createEl("option", { text: "All categories", attr: { value: "all" } });
    for (const value of this.controller.categories) {
      category.createEl("option", { text: value, attr: { value } });
    }
    category.value = this.controller.state.category;
    category.addEventListener("change", () => this.controller.setCategory(category.value));
  }

  private renderCapabilityCard(container: HTMLElement, capability: SemanticCapability): void {
    const button = container.createEl("button", {
      cls: "lifeos-explore__card",
      attr: {
        "aria-current": this.controller.state.selectedCapabilityId === capability.id ? "true" : "false",
      },
    });
    const heading = button.createDiv({ cls: "lifeos-explore__card-heading" });
    heading.createEl("strong", { text: capability.name });
    heading.createEl("span", {
      cls: `lifeos-explore__maturity lifeos-explore__maturity--${capability.maturity}`,
      text: capability.maturity,
    });
    button.createEl("span", {
      cls: "lifeos-explore__card-description",
      text: capability.description,
    });
    if (capability.requirements.length > 0) {
      button.createEl("small", {
        text: `${capability.requirements.length} setup requirement${capability.requirements.length === 1 ? "" : "s"}`,
      });
    }
    button.addEventListener("click", () => this.controller.select(capability.id));
  }

  private renderCapabilityDetail(container: HTMLElement, capability: SemanticCapability): void {
    container.createEl("h3", { text: capability.name });
    container.createEl("p", { text: capability.description });

    const metadata = container.createEl("dl", { cls: "lifeos-explore__metadata" });
    this.renderMetadata(metadata, "Category", capability.category);
    this.renderMetadata(metadata, "Status", capability.maturity);
    this.renderMetadata(metadata, "Capability ID", capability.id);

    if (capability.requirements.length > 0) {
      container.createEl("h4", { text: "Requirements" });
      const requirements = container.createEl("ul");
      for (const requirement of capability.requirements) {
        requirements.createEl("li", { text: requirement });
      }
    }

    if (capability.entry_points.length > 0) {
      container.createEl("h4", { text: "Ways to use it" });
      const entryPoints = container.createDiv({ cls: "lifeos-explore__entry-points" });
      for (const entryPoint of capability.entry_points) {
        this.renderEntryPoint(entryPoints, entryPoint);
      }
    }

    if (capability.example_prompts.length > 0) {
      container.createEl("h4", { text: "Example prompts" });
      container.createEl("p", {
        cls: "lifeos-explore__prompt-note",
        text: "Prompts are teaching examples for LifeOS-backed workflows. Copying one never submits or runs it.",
      });
      for (const prompt of capability.example_prompts) {
        const row = container.createDiv({ cls: "lifeos-explore__prompt" });
        row.createEl("code", { text: prompt });
        const copy = row.createEl("button", { text: "Copy" });
        copy.setAttr("aria-label", `Copy example prompt for ${capability.name}`);
        copy.addEventListener("click", () => { void this.controller.copyExamplePrompt(prompt); });
      }
    }
  }

  private renderEntryPoint(container: HTMLElement, entryPoint: CapabilityEntryPoint): void {
    const label = entryPoint.label ?? entryPoint.target;
    if (entryPoint.kind === "obsidian_command" || entryPoint.kind === "obsidian_view") {
      const button = container.createEl("button", { text: label });
      button.addEventListener("click", () => this.controller.activateEntryPoint(entryPoint));
      return;
    }
    const item = container.createDiv({ cls: "lifeos-explore__external-entry-point" });
    item.createEl("strong", { text: label });
    item.createEl("small", { text: `${this.entryPointKindLabel(entryPoint.kind)} · ${entryPoint.target}` });
  }

  private entryPointKindLabel(kind: CapabilityEntryPoint["kind"]): string {
    switch (kind) {
      case "cli": return "CLI";
      case "mcp_tool": return "MCP tool";
      case "workflow": return "Workflow";
      case "obsidian_command": return "Obsidian command";
      case "obsidian_view": return "Obsidian view";
    }
  }

  private renderMetadata(container: HTMLElement, label: string, value: string): void {
    container.createEl("dt", { text: label });
    container.createEl("dd", { text: value });
  }
}
