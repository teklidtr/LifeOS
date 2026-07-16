import { BridgeClient } from "./protocol.js";
import {
  ConversationArtifact,
  ConversationEvidence,
  ConversationProposalPreview,
  ConversationProposalResult,
  IndexHealth,
  RetrievalResponse,
  RetrievalScope,
  emptyScope,
} from "./knowledge-conversation.js";

export type KnowledgeConversationOrigin =
  | "ribbon" | "command-palette" | "active-note" | "selection" | "search-result"
  | "folder" | "tag" | "saved-scope" | "resume";
export type KnowledgeConversationStage =
  | "idle" | "loading" | "scope-review" | "ready" | "degraded" | "stale"
  | "no-results" | "timeout" | "malformed-response" | "unsupported-schema"
  | "unavailable-provider" | "error";

export interface ConversationListEntry extends ConversationArtifact {}
export interface KnowledgeConversationState {
  stage: KnowledgeConversationStage;
  origin: KnowledgeConversationOrigin;
  scope: RetrievalScope;
  query: string;
  evidence: ConversationEvidence[];
  conversation?: ConversationArtifact;
  conversations: ConversationListEntry[];
  indexHealth?: IndexHealth;
  proposalPreview?: ConversationProposalPreview;
  focusTarget: string;
  detail?: string;
  recovery?: string;
}

export interface ProposalInput {
  action: "create_capture" | "draft_note" | "append_section" | "suggest_links" | "research_questions"
    | "extract_claims" | "flashcard_candidates" | "mark_contradiction" | "mark_unresolved_question";
  targetPath: string;
  content: string;
  title?: string;
  turnId?: string;
}

function mapStage(value: string): KnowledgeConversationStage {
  if (value === "no-results") return "no-results";
  if (value === "timeout") return "timeout";
  if (value === "malformed-response") return "malformed-response";
  if (value === "unavailable-provider") return "unavailable-provider";
  if (value === "degraded") return "degraded";
  return "ready";
}

function errorState(current: KnowledgeConversationState, error: unknown): KnowledgeConversationState {
  const value = error as { code?: string; message?: string };
  const code = value.code ?? "unknown";
  const detail = value.message ?? String(error);
  if (["stale_artifact", "stale_write"].includes(code)) return {
    ...current, stage: "stale", detail, recovery: "Reload the canonical conversation before retrying.", focusTarget: "conversation-status",
  };
  if (["unsupported_schema", "unsupported_answer_schema", "incompatible_index"].includes(code)) return {
    ...current, stage: "unsupported-schema", detail, recovery: "Run migration or rebuild derived retrieval state.", focusTarget: "conversation-status",
  };
  if (code === "timeout") return { ...current, stage: "timeout", detail, recovery: "Retry or continue in evidence-only mode.", focusTarget: "conversation-status" };
  if (["malformed_response", "invalid_citation", "ungrounded_answer"].includes(code)) return {
    ...current, stage: "malformed-response", detail, recovery: "Inspect evidence and retry without accepting the malformed answer.", focusTarget: "conversation-status",
  };
  if (["unavailable_provider", "missing_index"].includes(code)) return {
    ...current, stage: "unavailable-provider", detail, recovery: "Use local lexical retrieval or rebuild the index.", focusTarget: "conversation-status",
  };
  return { ...current, stage: "error", detail, recovery: "Retry, rebuild the index, or open the Markdown artifact directly.", focusTarget: "conversation-status" };
}

export class KnowledgeConversationWorkspaceController {
  state: KnowledgeConversationState = {
    stage: "idle", origin: "command-palette", scope: emptyScope(), query: "", evidence: [],
    conversations: [], focusTarget: "knowledge-conversation-title",
  };

  constructor(private readonly client: BridgeClient, private readonly openPath: (path: string) => void = () => undefined) {}

  prepare(origin: KnowledgeConversationOrigin, scope: Partial<RetrievalScope> = {}, query = ""): void {
    this.state = {
      ...this.state,
      stage: "scope-review",
      origin,
      scope: { ...emptyScope(), ...scope },
      query,
      evidence: [],
      detail: "Review the retrieval scope before asking.",
      recovery: undefined,
      focusTarget: "retrieval-scope",
    };
  }

  async health(): Promise<IndexHealth> {
    try {
      const result = await this.client.call<IndexHealth>("retrieval.index.health", {});
      this.state = { ...this.state, indexHealth: result, stage: result.active_usable ? this.state.stage : "degraded", focusTarget: "index-health" };
      return result;
    } catch (error) { this.state = errorState(this.state, error); throw error; }
  }

  async rebuildIndex(resume = true): Promise<Record<string, unknown>> {
    this.state = { ...this.state, stage: "loading", focusTarget: "index-health", detail: "Rebuilding disposable retrieval data." };
    try {
      const result = await this.client.call<Record<string, unknown>>("retrieval.index.rebuild", { resume });
      await this.health();
      return result;
    } catch (error) { this.state = errorState(this.state, error); throw error; }
  }

  async inspectRetrieval(query = this.state.query): Promise<RetrievalResponse> {
    this.state = { ...this.state, stage: "loading", query, focusTarget: "retrieval-evidence" };
    try {
      const result = await this.client.call<RetrievalResponse>("retrieval.search", { query, scope: this.state.scope });
      this.state = {
        ...this.state,
        stage: mapStage(result.state),
        query,
        evidence: result.results.map((item) => ({
          evidence_id: item.evidence_id, path: item.path, heading: item.heading,
          start_line: item.start_line, end_line: item.end_line,
          source_hash: "", chunk_hash: "", excerpt: item.context_text,
          ranking: item.ranking, support: "direct", stale: false,
        })),
        detail: result.results.length ? undefined : "No matching evidence was found in the selected scope.",
        recovery: result.results.length ? undefined : "Broaden the scope, refine the query, or inspect exact search.",
        focusTarget: "retrieval-evidence",
      };
      return result;
    } catch (error) { this.state = errorState(this.state, error); throw error; }
  }

  async create(title: string, origin = this.state.origin): Promise<ConversationArtifact> {
    this.state = { ...this.state, stage: "loading", origin, focusTarget: "conversation-status" };
    try {
      const conversation = await this.client.call<ConversationArtifact>("conversation.create", { title, scope: this.state.scope });
      this.state = { ...this.state, stage: "ready", conversation, evidence: [], focusTarget: "conversation-query", detail: undefined, recovery: undefined };
      return conversation;
    } catch (error) { this.state = errorState(this.state, error); throw error; }
  }

  async list(includeArchived = true): Promise<ConversationListEntry[]> {
    try {
      const conversations = await this.client.call<ConversationListEntry[]>("conversation.list", { include_archived: includeArchived });
      this.state = { ...this.state, conversations, focusTarget: "conversation-history" };
      return conversations;
    } catch (error) { this.state = errorState(this.state, error); throw error; }
  }

  async resume(path: string): Promise<ConversationArtifact> {
    this.state = { ...this.state, stage: "loading", origin: "resume", focusTarget: "conversation-status" };
    try {
      const conversation = await this.client.call<ConversationArtifact>("conversation.load", { path });
      const turn = conversation.turns.at(-1);
      this.state = {
        ...this.state, stage: turn ? mapStage(turn.state) : "ready", conversation,
        scope: conversation.metadata.retrieval_scope, evidence: turn?.evidence ?? [],
        query: turn?.query ?? "", focusTarget: "conversation-query", detail: undefined, recovery: undefined,
      };
      return conversation;
    } catch (error) { this.state = errorState(this.state, error); throw error; }
  }

  async ask(query: string, evidenceOnly = false): Promise<ConversationArtifact> {
    const conversation = this.requireConversation();
    this.state = { ...this.state, stage: "loading", query, focusTarget: "conversation-answer" };
    try {
      const updated = await this.client.call<ConversationArtifact>("conversation.ask", {
        path: conversation.path, query, expected_hash: conversation.content_hash, evidence_only: evidenceOnly,
      });
      const turn = updated.turns.at(-1);
      this.state = {
        ...this.state, stage: mapStage(turn?.state ?? "ready"), conversation: updated,
        evidence: turn?.evidence ?? [], detail: turn?.explanation, recovery: undefined,
        focusTarget: turn?.evidence.length ? "conversation-evidence" : "conversation-answer",
      };
      return updated;
    } catch (error) { this.state = errorState(this.state, error); throw error; }
  }

  followUp(query: string, evidenceOnly = false): Promise<ConversationArtifact> { return this.ask(query, evidenceOnly); }

  async refineScope(scope: RetrievalScope): Promise<ConversationArtifact | undefined> {
    this.state = { ...this.state, scope, stage: "scope-review", focusTarget: "retrieval-scope" };
    if (!this.state.conversation) return undefined;
    try {
      const conversation = await this.client.call<ConversationArtifact>("conversation.scope.update", {
        path: this.state.conversation.path, expected_hash: this.state.conversation.content_hash, scope,
      });
      this.state = { ...this.state, conversation, stage: "ready" };
      return conversation;
    } catch (error) { this.state = errorState(this.state, error); throw error; }
  }

  pin(path: string, enabled = true): Promise<ConversationArtifact> { return this.sourceMutation("conversation.source.pin", path, enabled); }
  exclude(path: string, enabled = true): Promise<ConversationArtifact> { return this.sourceMutation("conversation.source.exclude", path, enabled); }

  async branch(turnId?: string, title?: string): Promise<ConversationArtifact> {
    const conversation = this.requireConversation();
    const sourceTurn = turnId ?? conversation.turns.at(-1)?.turn_id;
    if (!sourceTurn) throw new Error("A conversation turn is required to branch.");
    const branch = await this.client.call<ConversationArtifact>("conversation.branch", { path: conversation.path, turn_id: sourceTurn, title });
    this.state = { ...this.state, conversation: branch, stage: "ready", origin: "resume", focusTarget: "conversation-query" };
    return branch;
  }

  async rename(title: string): Promise<ConversationArtifact> {
    return this.artifactMutation("conversation.rename", { title });
  }
  async archive(): Promise<ConversationArtifact> { return this.artifactMutation("conversation.archive", {}); }

  async checkStale(): Promise<void> {
    const conversation = this.requireConversation();
    const turns = await this.client.call<ConversationArtifact["turns"]>("conversation.stale.check", { path: conversation.path });
    const stale = turns.some((turn) => turn.evidence.some((item) => item.stale));
    this.state = { ...this.state, conversation: { ...conversation, turns }, stage: stale ? "stale" : "ready", detail: stale ? "One or more cited passages changed after the answer was saved." : undefined, focusTarget: "conversation-evidence" };
  }

  async previewProposal(input: ProposalInput): Promise<ConversationProposalPreview> {
    const params = this.proposalParams(input);
    const preview = await this.client.call<ConversationProposalPreview>("conversation.proposal.preview", params);
    this.state = { ...this.state, proposalPreview: preview, focusTarget: "proposal-preview" };
    return preview;
  }

  async createProposal(input: ProposalInput): Promise<ConversationProposalResult> {
    const result = await this.client.call<ConversationProposalResult>("conversation.proposal.create", this.proposalParams(input));
    this.state = { ...this.state, proposalPreview: result.preview, focusTarget: "proposal-created" };
    return result;
  }

  openEvidence(item: ConversationEvidence): void { this.openPath(item.heading ? `${item.path}#${item.heading}` : item.path); }
  openConversation(): void { this.openPath(this.requireConversation().path); }

  keyboardActions(): Array<{ id: string; shortcut: string; label: string; ariaLabel: string }> {
    return [
      { id: "scope", shortcut: "S", label: "Scope", ariaLabel: "Inspect and refine retrieval scope" },
      { id: "ask", shortcut: "Enter", label: "Ask", ariaLabel: "Ask using the inspected evidence" },
      { id: "evidence", shortcut: "E", label: "Evidence", ariaLabel: "Move focus to retrieved evidence" },
      { id: "pin", shortcut: "P", label: "Pin", ariaLabel: "Pin the focused evidence source" },
      { id: "exclude", shortcut: "X", label: "Exclude", ariaLabel: "Exclude the focused evidence source" },
      { id: "branch", shortcut: "B", label: "Branch", ariaLabel: "Branch the saved knowledge conversation" },
      { id: "proposal", shortcut: "D", label: "Draft", ariaLabel: "Preview a proposal without applying it" },
    ];
  }

  private requireConversation(): ConversationArtifact {
    if (!this.state.conversation) throw new Error("Knowledge conversation is not loaded.");
    return this.state.conversation;
  }

  private async sourceMutation(method: string, sourcePath: string, enabled: boolean): Promise<ConversationArtifact> {
    const conversation = this.requireConversation();
    try {
      const updated = await this.client.call<ConversationArtifact>(method, {
        path: conversation.path, source_path: sourcePath, enabled, expected_hash: conversation.content_hash,
      });
      this.state = { ...this.state, conversation: updated, focusTarget: "conversation-evidence" };
      return updated;
    } catch (error) { this.state = errorState(this.state, error); throw error; }
  }

  private async artifactMutation(method: string, fields: Record<string, unknown>): Promise<ConversationArtifact> {
    const conversation = this.requireConversation();
    try {
      const updated = await this.client.call<ConversationArtifact>(method, {
        path: conversation.path, expected_hash: conversation.content_hash, ...fields,
      });
      this.state = { ...this.state, conversation: updated, stage: "ready", focusTarget: "conversation-status" };
      return updated;
    } catch (error) { this.state = errorState(this.state, error); throw error; }
  }

  private proposalParams(input: ProposalInput): Record<string, unknown> {
    const conversation = this.requireConversation();
    const turnId = input.turnId ?? conversation.turns.at(-1)?.turn_id;
    if (!turnId) throw new Error("A conversation turn is required to create a proposal.");
    return {
      conversation_path: conversation.path, turn_id: turnId, action: input.action,
      target_path: input.targetPath, content: input.content, title: input.title,
    };
  }
}
