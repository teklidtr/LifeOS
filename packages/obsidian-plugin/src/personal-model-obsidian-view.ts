import { ItemView, WorkspaceLeaf } from "obsidian";

import {
  nextPersonalModelView,
  PERSONAL_MODEL_ACTION_LABELS,
  PERSONAL_MODEL_VIEWS,
  PERSONAL_MODEL_VIEW_LABELS,
  PersonalModelAction,
  PersonalModelConfidence,
  PersonalModelItem,
  PersonalModelView,
} from "./personal-model.js";
import {
  PersonalModelWorkspaceController,
  PersonalModelWorkspaceState,
} from "./personal-model-workspace.js";

export const PERSONAL_MODEL_VIEW_TYPE = "lifeos-personal-model";

function now(): string {
  return new Date().toISOString();
}

function humanState(value: string): string {
  return value.replaceAll("_", " ").replaceAll("-", " ");
}

function setText(element: HTMLElement, text: string): void {
  element.setText(text);
}

export class LifeOSPersonalModelItemView extends ItemView {
  private unsubscribe?: () => void;

  constructor(
    leaf: WorkspaceLeaf,
    private readonly controller: PersonalModelWorkspaceController,
  ) {
    super(leaf);
  }

  getViewType(): string { return PERSONAL_MODEL_VIEW_TYPE; }
  getDisplayText(): string { return "Personal Model"; }
  getIcon(): string { return "brain-circuit"; }

  async onOpen(): Promise<void> {
    this.unsubscribe = this.controller.subscribe(() => this.render());
    this.render();
    await this.controller.load(now());
  }

  async onClose(): Promise<void> {
    this.unsubscribe?.();
    this.unsubscribe = undefined;
  }

  private render(): void {
    const root = this.contentEl;
    const state = this.controller.state;
    const shouldRestoreFocus = root.contains(root.ownerDocument.activeElement);
    root.empty();
    root.addClass("lifeos-personal-model");

    const header = root.createDiv({ cls: "lifeos-personal-model__header" });
    header.createEl("h2", {
      text: "Personal Model",
      attr: { id: "personal-model-workspace-title", tabindex: "-1" },
    });
    header.createEl("p", {
      text: "Evidence-backed working hypotheses. These are revisable context, not personality facts.",
      cls: "lifeos-personal-model__lede",
    });
    const headerActions = header.createDiv({ cls: "lifeos-personal-model__toolbar" });
    this.button(headerActions, "Refresh", "Refresh Personal Model without changing canonical Markdown", () => {
      void this.controller.load(now());
    });
    this.button(headerActions, "Rebuild derived state", "Rebuild disposable Personal Model state from canonical Markdown", () => {
      void this.controller.rebuild(now());
    });

    const status = root.createDiv({ cls: `lifeos-personal-model__status is-${state.stage}` });
    status.setAttr("id", "personal-model-status");
    status.setAttr("role", "status");
    status.setAttr("aria-live", "polite");
    status.setAttr("tabindex", "-1");
    status.createEl("strong", { text: humanState(state.stage) });
    if (state.detail) status.createEl("span", { text: ` ${state.detail}` });
    if (state.recovery) status.createEl("p", { text: state.recovery });

    if (state.stage === "missing-runtime" || state.stage === "blocked") {
      this.button(status, "Rebuild Personal Model", "Rebuild disposable Personal Model state", () => {
        void this.controller.rebuild(now());
      });
    }

    this.renderTrack(root, state);

    if (state.document) {
      this.renderTabs(root, state);

      if (state.stage === "empty") {
        const empty = root.createDiv({ cls: "lifeos-personal-model__empty" });
        empty.setAttr("id", "personal-model-empty");
        empty.setAttr("tabindex", "-1");
        empty.createEl("h3", { text: "No tracked hypotheses yet" });
        empty.createEl("p", {
          text: "Track a seed only when there is a working hypothesis worth revisiting. LifeOS will not invent a profile for you.",
        });
      } else {
        const layout = root.createDiv({ cls: "lifeos-personal-model__layout" });
        this.renderList(layout, state);
        this.renderDetail(layout, state);

        if (state.document.diagnostics.length) {
          const diagnostics = root.createEl("details", { cls: "lifeos-personal-model__diagnostics" });
          diagnostics.createEl("summary", { text: `${state.document.diagnostics.length} model diagnostics` });
          const list = diagnostics.createEl("ul");
          for (const diagnostic of state.document.diagnostics) {
            list.createEl("li", {
              text: `${diagnostic.source_path}:${diagnostic.line} · ${diagnostic.code} · ${diagnostic.message}`,
            });
          }
        }
      }
    }

    this.renderProposal(root, state);
    this.restoreFocus(state, shouldRestoreFocus);
  }

  private renderTrack(root: HTMLElement, state: PersonalModelWorkspaceState): void {
    const details = root.createEl("details", { cls: "lifeos-personal-model__track" });
    const summary = details.createEl("summary", { text: "Track a new seed hypothesis" });
    summary.setAttr("id", "personal-model-track");
    details.createEl("p", {
      text: "Tracking creates a proposal preview first. A seed is a question to revisit, not an adopted fact.",
    });
    const form = details.createEl("form", { cls: "lifeos-personal-model__form" });
    const id = this.textField(form, "Pattern ID", "personal-model-track-id", "lowercase-id");
    const path = this.textField(form, "Canonical path", "personal-model-track-path", "patterns/example.md");
    const title = this.textField(form, "Title", "personal-model-track-title", "Short human title");
    const description = this.textField(form, "Description", "personal-model-track-description", "What this hypothesis is about");
    const statement = this.textArea(form, "Working hypothesis", "personal-model-track-statement", "State the claim cautiously.");
    const confidence = this.confidenceField(form, "personal-model-track-confidence", "low");
    const reason = this.textArea(form, "Why track this now?", "personal-model-track-reason", "What makes this worth revisiting?");
    const submit = form.createEl("button", { text: PERSONAL_MODEL_ACTION_LABELS.track.label, attr: { type: "submit" } });
    submit.setAttr("aria-label", PERSONAL_MODEL_ACTION_LABELS.track.ariaLabel);
    submit.disabled = state.busy;
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void this.controller.preview({
        action: "track",
        targetPath: path.value,
        patternId: id.value,
        title: title.value,
        description: description.value,
        statement: statement.value,
        confidence: confidence.value as PersonalModelConfidence,
        transitionReason: reason.value,
        evidence: [],
      }, now());
    });
  }

  private renderTabs(root: HTMLElement, state: PersonalModelWorkspaceState): void {
    const tabs = root.createDiv({ cls: "lifeos-personal-model__tabs" });
    tabs.setAttr("role", "tablist");
    tabs.setAttr("aria-label", "Personal Model lifecycle views");
    for (const view of PERSONAL_MODEL_VIEWS) {
      const count = state.document?.groups[view].length ?? 0;
      const button = tabs.createEl("button", {
        text: `${PERSONAL_MODEL_VIEW_LABELS[view]} (${count})`,
        attr: {
          id: `personal-model-tab-${view}`,
          type: "button",
          role: "tab",
          "aria-selected": String(state.view === view),
          "aria-controls": "personal-model-list",
          tabindex: state.view === view ? "0" : "-1",
        },
      });
      button.addEventListener("click", () => this.controller.setView(view));
      button.addEventListener("keydown", (event) => this.onTabKeydown(event, view));
    }
  }

  private onTabKeydown(event: KeyboardEvent, view: PersonalModelView): void {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const target = nextPersonalModelView(
      view,
      event.key as "ArrowLeft" | "ArrowRight" | "Home" | "End",
    );
    this.controller.setView(target);
    this.contentEl.querySelector<HTMLElement>(`#personal-model-tab-${target}`)?.focus();
  }

  private renderList(layout: HTMLElement, state: PersonalModelWorkspaceState): void {
    const panel = layout.createEl("section", { cls: "lifeos-personal-model__list" });
    panel.setAttr("id", "personal-model-list");
    panel.setAttr("role", "tabpanel");
    panel.setAttr("aria-labelledby", `personal-model-tab-${state.view}`);
    panel.setAttr("tabindex", "-1");
    const items = this.controller.visibleItems;
    if (!items.length) {
      panel.createEl("p", { text: `No ${PERSONAL_MODEL_VIEW_LABELS[state.view].toLowerCase()} patterns.` });
      return;
    }
    for (const item of items) {
      const button = panel.createEl("button", {
        cls: `lifeos-personal-model__item${state.selectedPatternId === item.pattern_id ? " is-selected" : ""}`,
        attr: { type: "button", id: `personal-model-pattern-${item.pattern_id}` },
      });
      button.setAttr("aria-label", `Inspect ${item.title}. ${humanState(item.status)}, ${item.confidence} confidence, ${humanState(item.evidence_health)} evidence health.`);
      button.createEl("strong", { text: item.title });
      button.createEl("span", { text: item.statement });
      button.createEl("small", {
        text: `${humanState(item.status)} · ${item.confidence} confidence · ${humanState(item.evidence_health)} evidence`,
      });
      button.addEventListener("click", () => this.controller.select(item.pattern_id));
    }
  }

  private renderDetail(layout: HTMLElement, state: PersonalModelWorkspaceState): void {
    const item = this.controller.selected;
    const detail = layout.createEl("section", { cls: "lifeos-personal-model__detail" });
    detail.setAttr("aria-label", "Selected working hypothesis details");
    if (!item) {
      detail.createEl("p", { text: "Select a pattern to inspect its evidence." });
      return;
    }

    detail.createEl("h3", { text: item.title });
    detail.createEl("p", { text: item.statement, cls: "lifeos-personal-model__statement" });
    if (item.description) detail.createEl("p", { text: item.description });
    const facts = detail.createEl("dl", { cls: "lifeos-personal-model__facts" });
    this.fact(facts, "Status", humanState(item.status));
    this.fact(facts, "Confidence", item.confidence);
    this.fact(facts, "Evidence health", humanState(item.evidence_health));
    this.fact(facts, "Freshness", item.freshness_days == null ? "unknown" : `${item.freshness_days} days`);
    this.fact(facts, "Review recommendation", humanState(item.review_recommendation));
    if (item.review_due_at) this.fact(facts, "Review due", `${item.review_due ? "due · " : ""}${item.review_due_at}`);

    this.button(detail, "Open canonical pattern", `Open canonical pattern ${item.pattern_path}`, () => {
      this.controller.openCanonicalPattern();
    });

    this.renderReviewReasons(detail, item);
    this.renderEvidence(detail, item);
    this.renderRelated(detail, item);
    this.renderActions(detail, item, state);
  }

  private renderReviewReasons(detail: HTMLElement, item: PersonalModelItem): void {
    const section = detail.createEl("section", { cls: "lifeos-personal-model__review" });
    section.createEl("h4", { text: "Why this deserves attention" });
    const reasons = [
      ...item.review_reasons,
      ...item.review_trigger_reasons.map((reason) => `${reason.summary} (${reason.code})`),
    ];
    if (!reasons.length) {
      section.createEl("p", { text: "No current review trigger. Inspect evidence before deciding whether to change anything." });
      return;
    }
    const list = section.createEl("ul");
    for (const reason of [...new Set(reasons)]) list.createEl("li", { text: reason });
  }

  private renderEvidence(detail: HTMLElement, item: PersonalModelItem): void {
    const section = detail.createEl("section", { cls: "lifeos-personal-model__evidence" });
    section.createEl("h4", { text: "Reviewed evidence" });
    if (!item.evidence.length) {
      section.createEl("p", { text: "No reviewed evidence references are attached. Treat this as sparse working context." });
    }
    item.evidence.forEach((evidence, index) => {
      const diagnostic = item.evidence_diagnostics.find(
        (candidate) => candidate.reference.path === evidence.path
          && candidate.reference.content_hash === evidence.content_hash,
      );
      const card = section.createEl("article", { cls: "lifeos-personal-model__evidence-card" });
      card.createEl("strong", { text: humanState(evidence.role) });
      card.createEl("p", { text: `Reviewed: ${evidence.path}` });
      card.createEl("code", { text: evidence.content_hash });
      if (diagnostic) {
        card.createEl("p", { text: `Current state: ${humanState(diagnostic.state)}` });
        if (diagnostic.current_path && diagnostic.current_path !== evidence.path) {
          card.createEl("p", { text: `Current path: ${diagnostic.current_path}` });
        }
      }
      this.button(card, "Open source", `Open ${evidence.role} evidence ${diagnostic?.current_path ?? evidence.path}`, () => {
        this.controller.openEvidence(index);
      });
    });

    const changes = section.createEl("div", { cls: "lifeos-personal-model__changes" });
    changes.createEl("h5", { text: "Evidence changes since the reviewed version" });
    if (!item.evidence_changes.length) {
      changes.createEl("p", { text: "No reviewed source has moved, changed, disappeared, or become ambiguous in the current model." });
    } else {
      const list = changes.createEl("ul");
      for (const change of item.evidence_changes) {
        list.createEl("li", {
          text: `${humanState(change.role)} · ${change.reviewed_path} · ${humanState(change.state)}${change.current_path ? ` → ${change.current_path}` : ""}`,
        });
      }
    }
  }

  private renderRelated(detail: HTMLElement, item: PersonalModelItem): void {
    if (!item.related_paths.length) return;
    const section = detail.createEl("section", { cls: "lifeos-personal-model__related" });
    section.createEl("h4", { text: "Related reviews and experiments" });
    for (const related of item.related_paths) {
      this.button(section, `Open ${related.kind}`, `Open related ${related.kind} ${related.path}`, () => {
        this.controller.openRelated(related.path);
      });
      section.createEl("code", { text: related.path });
    }
  }

  private renderActions(
    detail: HTMLElement,
    item: PersonalModelItem,
    state: PersonalModelWorkspaceState,
  ): void {
    const actions = this.controller.availableActions();
    if (!actions.length) return;
    const section = detail.createEl("section", { cls: "lifeos-personal-model__actions" });
    section.setAttr("id", "personal-model-actions");
    section.setAttr("tabindex", "-1");
    section.createEl("h4", { text: "Proposal-backed actions" });
    section.createEl("p", {
      text: "Actions below only prepare a proposal preview. Evidence stays visible above so adoption and revision are inspectable decisions.",
    });
    const reason = this.textArea(section, "Reason", "personal-model-action-reason", "Why should this lifecycle change be proposed?");
    const revisedStatement = this.textArea(section, "Revised statement", "personal-model-revised-statement", item.statement);
    revisedStatement.value = item.statement;
    const confidence = this.confidenceField(section, "personal-model-revised-confidence", item.confidence);
    const buttons = section.createDiv({ cls: "lifeos-personal-model__action-buttons" });
    for (const action of actions) {
      const descriptor = PERSONAL_MODEL_ACTION_LABELS[action];
      const button = this.button(buttons, descriptor.label, descriptor.ariaLabel, () => {
        void this.previewAction(action, reason.value, revisedStatement.value, confidence.value as PersonalModelConfidence);
      });
      button.disabled = state.busy;
    }
  }

  private async previewAction(
    action: PersonalModelAction,
    transitionReason: string,
    statement: string,
    confidence: PersonalModelConfidence,
  ): Promise<void> {
    await this.controller.preview({
      action,
      transitionReason,
      statement: action === "revise" ? statement : undefined,
      confidence: action === "revise" ? confidence : undefined,
      reviewReasons: action === "contest" && transitionReason.trim() ? [transitionReason.trim()] : undefined,
    }, now());
  }

  private renderProposal(parent: HTMLElement, state: PersonalModelWorkspaceState): void {
    const preview = state.proposalPreview;
    if (!preview) return;
    const section = parent.createEl("section", { cls: "lifeos-personal-model__proposal" });
    section.setAttr("id", "personal-model-proposal-preview");
    section.setAttr("tabindex", "-1");
    section.createEl("h4", { text: "Proposal preview" });
    section.createEl("p", {
      text: `${humanState(preview.action)} · ${preview.from_status ?? "absent"} → ${preview.to_status} · ${preview.operation}`,
    });
    section.createEl("p", { text: preview.transition_reason });
    const candidate = section.createEl("pre");
    candidate.setAttr("aria-label", "Candidate canonical pattern Markdown");
    setText(candidate, preview.candidate_content);
    const controls = section.createDiv({ cls: "lifeos-personal-model__action-buttons" });
    const create = this.button(controls, "Create draft proposal", "Create a draft proposal from this exact preview", () => {
      void this.controller.createPreviewed();
    });
    create.disabled = state.busy;
    this.button(controls, "Cancel preview", "Close this preview without creating a proposal", () => {
      this.controller.clearProposalPreview();
    });

    if (state.proposalResult) {
      const created = section.createDiv({ cls: "lifeos-personal-model__proposal-created" });
      created.setAttr("id", "personal-model-proposal-created");
      created.setAttr("role", "status");
      created.setAttr("tabindex", "-1");
      created.createEl("strong", { text: `Draft ${state.proposalResult.proposal_id} created.` });
      created.createEl("p", {
        text: `Open Proposals from the command palette to inspect and accept it. ${state.proposalResult.proposal_path}`,
      });
    }
  }

  private restoreFocus(state: PersonalModelWorkspaceState, shouldRestoreFocus: boolean): void {
    if (!shouldRestoreFocus) return;
    const target = Array.from(this.contentEl.querySelectorAll<HTMLElement>("[id]"))
      .find((element) => element.id === state.focusTarget);
    target?.focus();
  }

  private fact(list: HTMLElement, label: string, value: string): void {
    list.createEl("dt", { text: label });
    list.createEl("dd", { text: value });
  }

  private textField(parent: HTMLElement, label: string, id: string, placeholder: string): HTMLInputElement {
    const wrapper = parent.createEl("label", { cls: "lifeos-personal-model__field" });
    wrapper.setAttr("for", id);
    wrapper.createEl("span", { text: label });
    return wrapper.createEl("input", { attr: { id, type: "text", placeholder } });
  }

  private textArea(parent: HTMLElement, label: string, id: string, placeholder: string): HTMLTextAreaElement {
    const wrapper = parent.createEl("label", { cls: "lifeos-personal-model__field" });
    wrapper.setAttr("for", id);
    wrapper.createEl("span", { text: label });
    return wrapper.createEl("textarea", { attr: { id, placeholder, rows: "3" } });
  }

  private confidenceField(
    parent: HTMLElement,
    id: string,
    initial: PersonalModelConfidence,
  ): HTMLSelectElement {
    const wrapper = parent.createEl("label", { cls: "lifeos-personal-model__field" });
    wrapper.setAttr("for", id);
    wrapper.createEl("span", { text: "Confidence" });
    const select = wrapper.createEl("select", { attr: { id } });
    for (const value of ["low", "medium", "high"] as const) {
      const option = select.createEl("option", { text: value, attr: { value } });
      option.selected = value === initial;
    }
    return select;
  }

  private button(
    parent: HTMLElement,
    label: string,
    ariaLabel: string,
    callback: () => void,
  ): HTMLButtonElement {
    const button = parent.createEl("button", { text: label, attr: { type: "button" } });
    button.setAttr("aria-label", ariaLabel);
    button.addEventListener("click", callback);
    return button;
  }
}
