import { BridgeClient } from "./protocol.js";
import {
  actionsForPersonalModelItem,
  PersonalModelAction,
  PersonalModelDocument,
  PersonalModelItem,
  PersonalModelProposalInput,
  PersonalModelProposalPreview,
  PersonalModelProposalResult,
  PersonalModelView,
} from "./personal-model.js";

export type PersonalModelWorkspaceStage =
  | "idle"
  | "loading"
  | "ready"
  | "empty"
  | "missing-runtime"
  | "rebuilding"
  | "stale"
  | "blocked"
  | "proposal-preview"
  | "proposal-created"
  | "error";

export interface PersonalModelWorkspaceState {
  stage: PersonalModelWorkspaceStage;
  view: PersonalModelView;
  document?: PersonalModelDocument;
  selectedPatternId?: string;
  proposalPreview?: PersonalModelProposalPreview;
  proposalResult?: PersonalModelProposalResult;
  detail?: string;
  recovery?: string;
  focusTarget: string;
  statusAnnouncement: string;
  busy: boolean;
}

type Listener = (state: PersonalModelWorkspaceState) => void;

type BridgeFailure = { code?: string; message?: string; data?: Record<string, unknown> };

function message(error: unknown): string {
  const failure = error as BridgeFailure;
  return failure.message ?? String(error);
}

function failureState(
  current: PersonalModelWorkspaceState,
  error: unknown,
): PersonalModelWorkspaceState {
  const failure = error as BridgeFailure;
  const detail = message(error);
  const common = {
    ...current,
    busy: false,
    detail,
    statusAnnouncement: detail,
    focusTarget: "personal-model-status",
    proposalPreview: undefined,
    proposalResult: undefined,
  };
  if (failure.code === "personal_model_rebuild_required") return {
    ...common,
    stage: "missing-runtime",
    recovery: "Rebuild disposable Personal Model state from canonical Markdown.",
  };
  if (["personal_model_recovery_required", "personal_model_rebuild_failed"].includes(failure.code ?? "")) return {
    ...common,
    stage: "blocked",
    recovery: "Rebuild derived state. Canonical pattern Markdown remains the authority.",
  };
  if (["stale_target", "stale_write"].includes(failure.code ?? "")) return {
    ...common,
    stage: "stale",
    recovery: "Refresh the workspace, re-read the pattern and evidence, then create a new preview.",
  };
  if (["personal_model_blocked", "authorization_denied"].includes(failure.code ?? "")) return {
    ...common,
    stage: "blocked",
    recovery: "Review the local retrieval policy or protected scope before retrying.",
  };
  return {
    ...common,
    stage: "error",
    recovery: "Retry the read-only refresh or open the canonical pattern Markdown directly.",
  };
}

export class PersonalModelWorkspaceController {
  state: PersonalModelWorkspaceState = {
    stage: "idle",
    view: "needs_review",
    focusTarget: "personal-model-workspace-title",
    statusAnnouncement: "Personal Model workspace is ready.",
    busy: false,
  };

  private listeners = new Set<Listener>();
  private lastProposalRequest?: Record<string, unknown>;

  constructor(
    private readonly client: BridgeClient,
    private readonly openPath: (path: string) => void = () => undefined,
  ) {}

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  get selected(): PersonalModelItem | undefined {
    const document = this.state.document;
    if (!document || !this.state.selectedPatternId) return undefined;
    return Object.values(document.groups)
      .flat()
      .find((item) => item.pattern_id === this.state.selectedPatternId);
  }

  get visibleItems(): PersonalModelItem[] {
    return this.state.document?.groups[this.state.view] ?? [];
  }

  async load(now?: string): Promise<PersonalModelDocument | undefined> {
    this.setState({
      ...this.state,
      stage: "loading",
      busy: true,
      detail: "Reading the current Personal Model and evidence state.",
      recovery: undefined,
      statusAnnouncement: "Loading Personal Model.",
      focusTarget: "personal-model-status",
      proposalPreview: undefined,
      proposalResult: undefined,
    });
    try {
      const document = await this.client.call<PersonalModelDocument>("personal-model.workspace.get", {
        now,
      });
      return this.acceptDocument(document, "Personal Model refreshed without changing canonical Markdown.");
    } catch (error) {
      this.setState(failureState(this.state, error));
      return undefined;
    }
  }

  async rebuild(now?: string): Promise<PersonalModelDocument | undefined> {
    this.setState({
      ...this.state,
      stage: "rebuilding",
      busy: true,
      detail: "Rebuilding disposable Personal Model state from canonical patterns.",
      recovery: undefined,
      statusAnnouncement: "Rebuilding Personal Model derived state.",
      focusTarget: "personal-model-status",
    });
    try {
      const document = await this.client.call<PersonalModelDocument>("personal-model.rebuild", {
        now,
      });
      return this.acceptDocument(document, "Personal Model derived state rebuilt from canonical Markdown.");
    } catch (error) {
      this.setState(failureState(this.state, error));
      return undefined;
    }
  }

  setView(view: PersonalModelView): void {
    const items = this.state.document?.groups[view] ?? [];
    this.setState({
      ...this.state,
      view,
      selectedPatternId: items[0]?.pattern_id,
      proposalPreview: undefined,
      proposalResult: undefined,
      focusTarget: `personal-model-tab-${view}`,
      statusAnnouncement: `${items.length} ${view.replace("_", " ")} patterns shown.`,
    });
  }

  select(patternId: string): void {
    const item = this.visibleItems.find((candidate) => candidate.pattern_id === patternId);
    if (!item) return;
    this.setState({
      ...this.state,
      selectedPatternId: patternId,
      proposalPreview: undefined,
      proposalResult: undefined,
      focusTarget: `personal-model-pattern-${patternId}`,
      statusAnnouncement: `${item.title} selected. Evidence and review state are visible.`,
    });
  }

  openCanonicalPattern(): void {
    const item = this.selected;
    if (item) this.openPath(item.pattern_path);
  }

  openEvidence(index: number): void {
    const item = this.selected;
    const evidence = item?.evidence[index];
    if (!evidence) return;
    const diagnostic = item?.evidence_diagnostics.find(
      (candidate) => candidate.reference.path === evidence.path
        && candidate.reference.content_hash === evidence.content_hash,
    );
    this.openPath(diagnostic?.current_path ?? evidence.path);
  }

  openRelated(path: string): void {
    if (this.selected?.related_paths.some((item) => item.path === path)) this.openPath(path);
  }

  availableActions(): PersonalModelAction[] {
    const item = this.selected;
    return item ? actionsForPersonalModelItem(item) : [];
  }

  async preview(input: PersonalModelProposalInput, now?: string): Promise<PersonalModelProposalPreview | undefined> {
    let request: Record<string, unknown>;
    try {
      request = this.bridgeRequest(input, now);
    } catch (error) {
      this.setState(failureState(this.state, error));
      return undefined;
    }
    this.setState({
      ...this.state,
      busy: true,
      detail: "Building a read-only proposal preview in Python.",
      recovery: undefined,
      statusAnnouncement: "Building proposal preview.",
      focusTarget: "personal-model-status",
      proposalPreview: undefined,
      proposalResult: undefined,
    });
    try {
      const result = await this.client.call<{ preview: PersonalModelProposalPreview }>(
        "personal-model.proposal.preview",
        request,
      );
      this.lastProposalRequest = request;
      this.setState({
        ...this.state,
        stage: "proposal-preview",
        busy: false,
        proposalPreview: result.preview,
        proposalResult: undefined,
        detail: "Review the exact candidate before creating a draft proposal.",
        recovery: undefined,
        statusAnnouncement: "Proposal preview ready. No canonical pattern was changed.",
        focusTarget: "personal-model-proposal-preview",
      });
      return result.preview;
    } catch (error) {
      this.lastProposalRequest = undefined;
      this.setState(failureState(this.state, error));
      return undefined;
    }
  }

  async createPreviewed(): Promise<PersonalModelProposalResult | undefined> {
    if (!this.state.proposalPreview || !this.lastProposalRequest) return undefined;
    this.setState({
      ...this.state,
      busy: true,
      detail: "Creating a draft proposal for the reviewed candidate.",
      statusAnnouncement: "Creating draft proposal.",
      focusTarget: "personal-model-status",
    });
    try {
      const result = await this.client.call<PersonalModelProposalResult>(
        "personal-model.proposal.create",
        this.lastProposalRequest,
      );
      this.setState({
        ...this.state,
        stage: "proposal-created",
        busy: false,
        proposalResult: result,
        detail: `Draft ${result.proposal_id} created. Canonical pattern Markdown is unchanged until proposal acceptance.`,
        recovery: undefined,
        statusAnnouncement: `Draft proposal ${result.proposal_id} created.`,
        focusTarget: "personal-model-proposal-created",
      });
      return result;
    } catch (error) {
      this.setState(failureState(this.state, error));
      return undefined;
    }
  }

  clearProposalPreview(): void {
    this.lastProposalRequest = undefined;
    this.setState({
      ...this.state,
      stage: this.state.document ? (this.itemCount(this.state.document) ? "ready" : "empty") : "idle",
      proposalPreview: undefined,
      proposalResult: undefined,
      detail: undefined,
      recovery: undefined,
      statusAnnouncement: "Proposal preview closed without creating a draft.",
      focusTarget: "personal-model-actions",
    });
  }

  private bridgeRequest(input: PersonalModelProposalInput, now?: string): Record<string, unknown> {
    const reason = input.transitionReason.trim();
    if (!reason) throw { code: "invalid_params", message: "A proposal reason is required." };
    if (input.action === "track") {
      const targetPath = input.targetPath?.trim();
      const patternId = input.patternId?.trim();
      const title = input.title?.trim();
      const statement = input.statement?.trim();
      if (!targetPath || !patternId || !title || !statement || !input.confidence) {
        throw { code: "invalid_params", message: "Track requires path, ID, title, statement and confidence." };
      }
      return {
        action: "track",
        target_path: targetPath,
        pattern_id: patternId,
        title,
        description: input.description ?? "",
        statement,
        confidence: input.confidence,
        origin: { kind: "manual" },
        evidence: input.evidence ?? [],
        transition_reason: reason,
        now,
      };
    }

    const item = this.selected;
    if (!item) throw { code: "invalid_params", message: "Select a pattern before creating this preview." };
    if (!actionsForPersonalModelItem(item).includes(input.action)) {
      throw { code: "invalid_transition", message: `${input.action} is not available for ${item.status} patterns.` };
    }
    return {
      action: input.action,
      target_path: item.pattern_path,
      expected_target_hash: item.pattern_content_hash,
      transition_reason: reason,
      statement: input.statement,
      confidence: input.confidence,
      evidence: input.evidence,
      review_reasons: input.reviewReasons,
      now,
    };
  }

  private acceptDocument(document: PersonalModelDocument, announcement: string): PersonalModelDocument {
    const count = this.itemCount(document);
    let view = this.state.view;
    if (document.groups[view].length === 0) {
      view = document.groups.needs_review.length
        ? "needs_review"
        : document.groups.active.length
          ? "active"
          : document.groups.seeds.length
            ? "seeds"
            : "archived";
    }
    const current = document.groups[view]
      .find((item) => item.pattern_id === this.state.selectedPatternId);
    const selectedPatternId = current?.pattern_id ?? document.groups[view][0]?.pattern_id;
    this.lastProposalRequest = undefined;
    this.setState({
      ...this.state,
      stage: count ? "ready" : "empty",
      busy: false,
      document,
      view,
      selectedPatternId,
      proposalPreview: undefined,
      proposalResult: undefined,
      detail: count ? undefined : "No personal patterns are tracked yet.",
      recovery: count ? undefined : "Track a seed hypothesis when there is something worth revisiting.",
      statusAnnouncement: count ? `${announcement} ${count} patterns available.` : "Personal Model is empty.",
      focusTarget: count ? "personal-model-list" : "personal-model-empty",
    });
    return document;
  }

  private itemCount(document: PersonalModelDocument): number {
    return Object.values(document.groups).reduce((total, items) => total + items.length, 0);
  }

  private setState(state: PersonalModelWorkspaceState): void {
    this.state = state;
    for (const listener of this.listeners) listener(state);
  }
}
