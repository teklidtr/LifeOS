import { BridgeClient } from "./protocol.js";

export type ProposalAction = "submit" | "approve" | "apply" | "reject";

export interface ProposalOperationInspection {
  operation_id: string;
  operation_type: string;
  target_path: string;
  unified_diff: string;
  preview_error?: string | null;
}

export interface ProposalInspection {
  proposal_id: string;
  status: string;
  title: string;
  created_at: string;
  description: string;
  body: string;
  review_digest: string;
  operations: ProposalOperationInspection[];
  related_sources: string[];
  findings: string[];
}

export interface ConfirmationChallenge {
  token: string;
  proposal_id: string;
  action: ProposalAction;
  review_digest: string;
  expires_at: string;
}

export type ProposalConfirmation = (
  challenge: ConfirmationChallenge,
  inspection: ProposalInspection,
) => Promise<boolean>;

export type ProposalWorkspaceKind = "loading" | "empty" | "ready" | "error";

export interface ProposalWorkspaceState {
  kind: ProposalWorkspaceKind;
  detail: string;
  proposals: ProposalInspection[];
  selected?: ProposalInspection;
  busy?: "inspect" | ProposalAction;
  announcement?: string;
}

export type ProposalDiffLineKind =
  | "header"
  | "hunk"
  | "context"
  | "added"
  | "removed"
  | "note";

export interface ProposalDiffLine {
  kind: ProposalDiffLineKind;
  text: string;
  oldLine: number | null;
  newLine: number | null;
}

export const PROPOSAL_STATUS_ORDER = [
  "draft",
  "pending",
  "approved",
  "rejected",
  "applied",
  "stale",
] as const;

export function parseProposalDiff(unifiedDiff: string): ProposalDiffLine[] {
  let oldLine: number | null = null;
  let newLine: number | null = null;

  return unifiedDiff.split("\n").filter((line, index, lines) =>
    line.length > 0 || index < lines.length - 1
  ).map((text) => {
    if (text.startsWith("--- ") || text.startsWith("+++ ")) {
      return { kind: "header", text, oldLine: null, newLine: null };
    }

    if (text.startsWith("@@")) {
      const match = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(text);
      oldLine = match ? Number.parseInt(match[1]!, 10) : null;
      newLine = match ? Number.parseInt(match[2]!, 10) : null;
      return { kind: "hunk", text, oldLine: null, newLine: null };
    }

    if (text.startsWith("+")) {
      const result = { kind: "added" as const, text, oldLine: null, newLine };
      if (newLine !== null) newLine += 1;
      return result;
    }

    if (text.startsWith("-")) {
      const result = { kind: "removed" as const, text, oldLine, newLine: null };
      if (oldLine !== null) oldLine += 1;
      return result;
    }

    if (text.startsWith(" ")) {
      const result = { kind: "context" as const, text, oldLine, newLine };
      if (oldLine !== null) oldLine += 1;
      if (newLine !== null) newLine += 1;
      return result;
    }

    return { kind: "note", text, oldLine: null, newLine: null };
  });
}

export function proposalActionsForStatus(status: string): ProposalAction[] {
  if (status === "draft") return ["submit"];
  if (status === "pending") return ["approve", "reject"];
  if (status === "approved") return ["apply", "reject"];
  return [];
}

export function formatProposalTimestamp(
  timestamp: string,
  locale?: Intl.LocalesArgument,
  timeZone?: string,
): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return timestamp;
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    ...(timeZone ? { timeZone } : {}),
  }).format(parsed);
}

function timestampRank(timestamp: string): number {
  const rank = Date.parse(timestamp);
  return Number.isNaN(rank) ? Number.NEGATIVE_INFINITY : rank;
}

export function groupProposalsByStatus(
  proposals: readonly ProposalInspection[],
): Array<{ status: string; proposals: ProposalInspection[] }> {
  const groups = new Map<string, ProposalInspection[]>();
  for (const proposal of proposals) {
    const group = groups.get(proposal.status) ?? [];
    group.push(proposal);
    groups.set(proposal.status, group);
  }
  const known = new Map<string, number>(
    PROPOSAL_STATUS_ORDER.map((status, index) => [status, index]),
  );
  return [...groups.entries()]
    .sort(([left], [right]) => {
      const leftRank = known.get(left) ?? PROPOSAL_STATUS_ORDER.length;
      const rightRank = known.get(right) ?? PROPOSAL_STATUS_ORDER.length;
      return leftRank - rightRank || left.localeCompare(right);
    })
    .map(([status, items]) => ({
      status,
      proposals: [...items].sort((left, right) => {
        const newestFirst = timestampRank(right.created_at) - timestampRank(left.created_at);
        return newestFirst
          || left.title.localeCompare(right.title)
          || left.proposal_id.localeCompare(right.proposal_id);
      }),
    }));
}

export class ProposalController {
  inspected?: ProposalInspection;

  constructor(
    private readonly client: BridgeClient,
    private readonly confirm: ProposalConfirmation,
  ) {}

  list(): Promise<ProposalInspection[]> {
    return this.client.call("proposal.list", {});
  }

  async inspect(id: string): Promise<ProposalInspection> {
    const inspection = await this.client.call<ProposalInspection>("proposal.inspect", {
      proposal_id: id,
    });
    this.inspected = inspection;
    return inspection;
  }

  async execute(id: string, action: ProposalAction, reason?: string): Promise<unknown> {
    const inspection = await this.inspect(id);
    const challenge = await this.client.call<ConfirmationChallenge>("proposal.prepare", {
      proposal_id: id,
      action,
    });
    if (!(await this.confirm(challenge, inspection))) {
      throw new Error("Confirmation cancelled.");
    }
    const latest = await this.inspect(id);
    if (latest.review_digest !== challenge.review_digest) {
      throw new Error("Proposal changed after review.");
    }
    return this.client.call("proposal.execute", {
      proposal_id: id,
      action,
      token: challenge.token,
      reason,
    });
  }
}

export class ProposalWorkspaceController {
  state: ProposalWorkspaceState = {
    kind: "loading",
    detail: "Load proposals to begin review.",
    proposals: [],
  };

  private readonly proposalController: ProposalController;
  private listeners = new Set<() => void>();
  private loaded = false;

  constructor(client: BridgeClient, confirm: ProposalConfirmation) {
    this.proposalController = new ProposalController(client, confirm);
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    listener();
    return () => this.listeners.delete(listener);
  }

  async load(preferredProposalId?: string): Promise<void> {
    const selectedId = preferredProposalId ?? this.state.selected?.proposal_id;
    this.update({
      ...this.state,
      kind: "loading",
      detail: "Loading proposals…",
      busy: undefined,
      announcement: undefined,
    });
    try {
      const proposals = await this.proposalController.list();
      this.loaded = true;
      if (proposals.length === 0) {
        this.update({
          kind: "empty",
          detail: "No proposals are available for review.",
          proposals: [],
        });
        return;
      }
      const selected = proposals.find((proposal) => proposal.proposal_id === selectedId)
        ?? proposals[0];
      this.update({
        kind: "ready",
        detail: `${proposals.length} proposal${proposals.length === 1 ? "" : "s"} available.`,
        proposals,
        selected,
      });
    } catch (error) {
      this.fail("Could not load proposals.", error);
    }
  }

  async select(proposalId: string): Promise<void> {
    this.update({ ...this.state, busy: "inspect", announcement: "Loading proposal…" });
    try {
      const selected = await this.proposalController.inspect(proposalId);
      const proposals = this.state.proposals.map((proposal) =>
        proposal.proposal_id === selected.proposal_id ? selected : proposal
      );
      this.update({
        ...this.state,
        kind: "ready",
        proposals,
        selected,
        busy: undefined,
        announcement: `Proposal ${selected.proposal_id} loaded.`,
      });
    } catch (error) {
      this.fail("Could not inspect the proposal.", error);
    }
  }

  async execute(action: ProposalAction, reason?: string): Promise<void> {
    const selected = this.state.selected;
    if (!selected) throw new Error("Select a proposal before taking an action.");
    if (!proposalActionsForStatus(selected.status).includes(action)) {
      throw new Error(`Cannot ${action} a ${selected.status} proposal.`);
    }
    this.update({
      ...this.state,
      busy: action,
      announcement: `Waiting for confirmation to ${action} ${selected.proposal_id}.`,
    });
    try {
      await this.proposalController.execute(selected.proposal_id, action, reason);
      await this.load(selected.proposal_id);
      this.update({
        ...this.state,
        announcement: `Proposal ${selected.proposal_id} ${action} completed.`,
      });
    } catch (error) {
      if (error instanceof Error && error.message === "Confirmation cancelled.") {
        this.update({
          ...this.state,
          kind: "ready",
          busy: undefined,
          announcement: "Confirmation cancelled. No changes were made.",
        });
        return;
      }
      this.fail(`Could not ${action} the proposal.`, error);
    }
  }

  invalidate(): void {
    if (this.loaded && this.state.busy === undefined) void this.load();
  }

  private fail(detail: string, error: unknown): void {
    const message = error instanceof Error ? error.message : "Unexpected bridge error.";
    this.update({
      ...this.state,
      kind: "error",
      detail: `${detail} ${message}`,
      busy: undefined,
      announcement: `${detail} ${message}`,
    });
  }

  private update(state: ProposalWorkspaceState): void {
    this.state = state;
    for (const listener of this.listeners) listener();
  }
}

export class SystemController {
  constructor(private readonly client: BridgeClient) {}

  status(): Promise<unknown> {
    return this.client.call("system.status", {});
  }
}
