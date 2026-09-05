import { BridgeClient } from "./protocol.js";

export const SEMANTIC_CAPABILITY_SCHEMA_VERSION = 1 as const;

export type CapabilityVisibility = "explore" | "internal";
export type CapabilityMaturity = "stable" | "beta" | "experimental";
export type CapabilityBackingKind = "bridge_method" | "workflow" | "data_source";
export type CapabilityEntryPointKind =
  | "obsidian_command"
  | "obsidian_view"
  | "cli"
  | "mcp_tool"
  | "workflow";

export interface CapabilityBackingReference {
  kind: CapabilityBackingKind;
  ref: string;
}

export interface CapabilityEntryPoint {
  kind: CapabilityEntryPointKind;
  target: string;
  label: string | null;
}

export interface SemanticCapability {
  id: string;
  name: string;
  description: string;
  category: string;
  visibility: CapabilityVisibility;
  maturity: CapabilityMaturity;
  requirements: string[];
  backing: CapabilityBackingReference[];
  entry_points: CapabilityEntryPoint[];
  example_prompts: string[];
}

export interface CapabilityListResponse {
  semantic_capability_schema: number;
  capabilities: SemanticCapability[];
}

export type ExploreWorkspaceStage =
  | "idle"
  | "loading"
  | "ready"
  | "empty"
  | "bridge-unavailable"
  | "malformed"
  | "error";

export interface ExploreWorkspaceState {
  stage: ExploreWorkspaceStage;
  capabilities: SemanticCapability[];
  query: string;
  category: string;
  selectedCapabilityId?: string;
  detail: string;
  statusAnnouncement: string;
  busy: boolean;
}

export interface CapabilityGroup {
  category: string;
  capabilities: SemanticCapability[];
}

type Listener = (state: ExploreWorkspaceState) => void;
type BridgeFailure = { code?: string; message?: string };
type EntryPointDispatcher = (entryPoint: CapabilityEntryPoint) => void;
type ClipboardWriter = (text: string) => Promise<void>;
type Reconnector = () => Promise<void>;

const VISIBILITIES = new Set<CapabilityVisibility>(["explore", "internal"]);
const MATURITIES = new Set<CapabilityMaturity>(["stable", "beta", "experimental"]);
const BACKING_KINDS = new Set<CapabilityBackingKind>(["bridge_method", "workflow", "data_source"]);
const ENTRY_POINT_KINDS = new Set<CapabilityEntryPointKind>([
  "obsidian_command",
  "obsidian_view",
  "cli",
  "mcp_tool",
  "workflow",
]);

export class ExplorePayloadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ExplorePayloadError";
  }
}

function record(value: unknown, field: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ExplorePayloadError(`${field} must be an object.`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new ExplorePayloadError(`${field} must be a non-empty string.`);
  }
  return value;
}

function stringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value)) throw new ExplorePayloadError(`${field} must be an array.`);
  return value.map((item, index) => text(item, `${field}[${index}]`));
}

function parseBacking(value: unknown, index: number): CapabilityBackingReference {
  const item = record(value, `backing[${index}]`);
  const kind = text(item.kind, `backing[${index}].kind`);
  if (!BACKING_KINDS.has(kind as CapabilityBackingKind)) {
    throw new ExplorePayloadError(`backing[${index}].kind is unsupported.`);
  }
  return {
    kind: kind as CapabilityBackingKind,
    ref: text(item.ref, `backing[${index}].ref`),
  };
}

function parseEntryPoint(value: unknown, index: number): CapabilityEntryPoint {
  const item = record(value, `entry_points[${index}]`);
  const kind = text(item.kind, `entry_points[${index}].kind`);
  if (!ENTRY_POINT_KINDS.has(kind as CapabilityEntryPointKind)) {
    throw new ExplorePayloadError(`entry_points[${index}].kind is unsupported.`);
  }
  if (item.label !== null && item.label !== undefined && typeof item.label !== "string") {
    throw new ExplorePayloadError(`entry_points[${index}].label must be a string or null.`);
  }
  return {
    kind: kind as CapabilityEntryPointKind,
    target: text(item.target, `entry_points[${index}].target`),
    label: typeof item.label === "string" && item.label.trim() ? item.label : null,
  };
}

function parseCapability(value: unknown, index: number): SemanticCapability {
  const item = record(value, `capabilities[${index}]`);
  const visibility = text(item.visibility, `capabilities[${index}].visibility`);
  if (!VISIBILITIES.has(visibility as CapabilityVisibility)) {
    throw new ExplorePayloadError(`capabilities[${index}].visibility is unsupported.`);
  }
  const maturity = text(item.maturity, `capabilities[${index}].maturity`);
  if (!MATURITIES.has(maturity as CapabilityMaturity)) {
    throw new ExplorePayloadError(`capabilities[${index}].maturity is unsupported.`);
  }
  if (!Array.isArray(item.backing) || item.backing.length === 0) {
    throw new ExplorePayloadError(`capabilities[${index}].backing must contain implementation references.`);
  }
  if (!Array.isArray(item.entry_points)) {
    throw new ExplorePayloadError(`capabilities[${index}].entry_points must be an array.`);
  }
  return {
    id: text(item.id, `capabilities[${index}].id`),
    name: text(item.name, `capabilities[${index}].name`),
    description: text(item.description, `capabilities[${index}].description`),
    category: text(item.category, `capabilities[${index}].category`),
    visibility: visibility as CapabilityVisibility,
    maturity: maturity as CapabilityMaturity,
    requirements: stringArray(item.requirements, `capabilities[${index}].requirements`),
    backing: item.backing.map(parseBacking),
    entry_points: item.entry_points.map(parseEntryPoint),
    example_prompts: stringArray(item.example_prompts, `capabilities[${index}].example_prompts`),
  };
}

export function parseCapabilityListResponse(value: unknown): CapabilityListResponse {
  const payload = record(value, "capability.list response");
  if (payload.semantic_capability_schema !== SEMANTIC_CAPABILITY_SCHEMA_VERSION) {
    throw new ExplorePayloadError(
      `Unsupported semantic capability schema: ${String(payload.semantic_capability_schema)}.`,
    );
  }
  if (!Array.isArray(payload.capabilities)) {
    throw new ExplorePayloadError("capabilities must be an array.");
  }
  const capabilities = payload.capabilities.map(parseCapability);
  const ids = new Set<string>();
  for (const capability of capabilities) {
    if (ids.has(capability.id)) {
      throw new ExplorePayloadError(`Duplicate capability ID: ${capability.id}.`);
    }
    ids.add(capability.id);
  }
  return {
    semantic_capability_schema: SEMANTIC_CAPABILITY_SCHEMA_VERSION,
    capabilities,
  };
}

function failureMessage(error: unknown): string {
  const failure = error as BridgeFailure;
  return failure.message ?? (error instanceof Error ? error.message : String(error));
}

function isBridgeUnavailable(error: unknown): boolean {
  const failure = error as BridgeFailure;
  return failure.code === "bridge_unavailable"
    || failure.code === "connection_closed"
    || /bridge|python|process|connection/i.test(failureMessage(error));
}

function capabilityMatches(capability: SemanticCapability, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return true;
  return [
    capability.name,
    capability.description,
    capability.category,
    capability.id,
    ...capability.requirements,
  ].some((value) => value.toLocaleLowerCase().includes(needle));
}

function compareCapabilities(left: SemanticCapability, right: SemanticCapability): number {
  return left.name.localeCompare(right.name) || left.id.localeCompare(right.id);
}

export class ExploreWorkspaceController {
  state: ExploreWorkspaceState = {
    stage: "idle",
    capabilities: [],
    query: "",
    category: "all",
    detail: "Explore is ready to load the LifeOS capability registry.",
    statusAnnouncement: "Explore is ready.",
    busy: false,
  };

  private readonly listeners = new Set<Listener>();

  constructor(
    private readonly client: BridgeClient,
    private readonly dispatchEntryPoint: EntryPointDispatcher = () => undefined,
    private readonly writeClipboard: ClipboardWriter = async () => undefined,
    private readonly reconnectBridge: Reconnector = async () => undefined,
  ) {}

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  get categories(): string[] {
    return [...new Set(this.state.capabilities.map((capability) => capability.category))]
      .sort((left, right) => left.localeCompare(right));
  }

  get visibleCapabilities(): SemanticCapability[] {
    return this.filteredCapabilities(this.state.query, this.state.category);
  }

  get groupedCapabilities(): CapabilityGroup[] {
    const groups = new Map<string, SemanticCapability[]>();
    for (const capability of this.visibleCapabilities) {
      const group = groups.get(capability.category) ?? [];
      group.push(capability);
      groups.set(capability.category, group);
    }
    return [...groups.entries()]
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([category, capabilities]) => ({
        category,
        capabilities: capabilities.sort(compareCapabilities),
      }));
  }

  get selected(): SemanticCapability | undefined {
    return this.state.capabilities.find(
      (capability) => capability.id === this.state.selectedCapabilityId,
    );
  }

  async load(): Promise<SemanticCapability[] | undefined> {
    this.setState({
      ...this.state,
      stage: "loading",
      busy: true,
      detail: "Loading the Python-owned LifeOS capability registry.",
      statusAnnouncement: "Loading LifeOS capabilities.",
    });
    try {
      const response = await this.client.call<unknown>("capability.list", {});
      const payload = parseCapabilityListResponse(response);
      const capabilities = payload.capabilities.filter(
        (capability) => capability.visibility === "explore",
      );
      this.acceptCapabilities(capabilities);
      return capabilities;
    } catch (error) {
      const malformed = error instanceof ExplorePayloadError;
      const unavailable = !malformed && isBridgeUnavailable(error);
      const detail = malformed
        ? `LifeOS returned capability metadata this plugin cannot safely render: ${error.message}`
        : failureMessage(error);
      this.setState({
        ...this.state,
        stage: malformed ? "malformed" : unavailable ? "bridge-unavailable" : "error",
        capabilities: [],
        selectedCapabilityId: undefined,
        busy: false,
        detail,
        statusAnnouncement: detail,
      });
      return undefined;
    }
  }

  async reconnect(): Promise<void> {
    this.setState({
      ...this.state,
      stage: "loading",
      busy: true,
      detail: "Reconnecting to the local LifeOS engine.",
      statusAnnouncement: "Reconnecting to LifeOS.",
    });
    try {
      await this.reconnectBridge();
      await this.load();
    } catch (error) {
      const detail = failureMessage(error);
      this.setState({
        ...this.state,
        stage: "bridge-unavailable",
        capabilities: [],
        selectedCapabilityId: undefined,
        busy: false,
        detail,
        statusAnnouncement: detail,
      });
    }
  }

  setQuery(query: string): void {
    this.updateFilters(query, this.state.category);
  }

  setCategory(category: string): void {
    const normalized = category === "all" || this.categories.includes(category) ? category : "all";
    this.updateFilters(this.state.query, normalized);
  }

  select(capabilityId: string): void {
    const capability = this.state.capabilities.find((candidate) => candidate.id === capabilityId);
    if (!capability) return;
    this.setState({
      ...this.state,
      selectedCapabilityId: capabilityId,
      statusAnnouncement: `${capability.name} selected.`,
    });
  }

  activateEntryPoint(entryPoint: CapabilityEntryPoint): boolean {
    const selected = this.selected;
    if (!selected) return false;
    const declared = selected.entry_points.some(
      (candidate) => candidate.kind === entryPoint.kind && candidate.target === entryPoint.target,
    );
    if (!declared || !["obsidian_command", "obsidian_view"].includes(entryPoint.kind)) return false;
    try {
      this.dispatchEntryPoint(entryPoint);
      this.setState({
        ...this.state,
        statusAnnouncement: `${entryPoint.label ?? selected.name} opened through its existing LifeOS entry point.`,
      });
      return true;
    } catch (error) {
      this.setState({
        ...this.state,
        statusAnnouncement: `Could not open that LifeOS entry point: ${failureMessage(error)}`,
      });
      return false;
    }
  }

  async copyExamplePrompt(prompt: string): Promise<boolean> {
    if (!this.selected?.example_prompts.includes(prompt)) return false;
    try {
      await this.writeClipboard(prompt);
      this.setState({
        ...this.state,
        statusAnnouncement: "Example prompt copied. It was not submitted or run.",
      });
      return true;
    } catch (error) {
      this.setState({
        ...this.state,
        statusAnnouncement: `Could not copy the example prompt: ${failureMessage(error)}`,
      });
      return false;
    }
  }

  private acceptCapabilities(capabilities: SemanticCapability[]): void {
    const ordered = [...capabilities].sort(
      (left, right) => left.category.localeCompare(right.category) || compareCapabilities(left, right),
    );
    const stage: ExploreWorkspaceStage = ordered.length > 0 ? "ready" : "empty";
    const detail = ordered.length > 0
      ? `${ordered.length} implemented LifeOS capabilities are available to explore.`
      : "The registry is available, but it currently contains no Explore-visible capabilities.";
    this.setState({
      stage,
      capabilities: ordered,
      query: "",
      category: "all",
      selectedCapabilityId: ordered[0]?.id,
      detail,
      statusAnnouncement: detail,
      busy: false,
    });
  }

  private updateFilters(query: string, category: string): void {
    const visible = this.filteredCapabilities(query, category);
    const selectedStillVisible = visible.some(
      (capability) => capability.id === this.state.selectedCapabilityId,
    );
    this.setState({
      ...this.state,
      query,
      category,
      selectedCapabilityId: selectedStillVisible
        ? this.state.selectedCapabilityId
        : visible[0]?.id,
      statusAnnouncement: `${visible.length} capabilities match the current Explore filters.`,
    });
  }

  private filteredCapabilities(query: string, category: string): SemanticCapability[] {
    return this.state.capabilities.filter(
      (capability) => (category === "all" || capability.category === category)
        && capabilityMatches(capability, query),
    );
  }

  private setState(state: ExploreWorkspaceState): void {
    this.state = state;
    for (const listener of this.listeners) listener(state);
  }
}
