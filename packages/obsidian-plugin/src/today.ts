import { BridgeClient } from "./protocol.js";

export interface DashboardSection<T = unknown> {
  state: "ready" | "empty" | "stale" | "blocked" | "corrupt" | "unavailable";
  data: T;
  code?: string;
  detail?: string;
}

export interface TodayInputs {
  day: string;
  available_minutes: number;
  study_minutes: number;
  energy: "low" | "medium" | "high";
  motivation: "low" | "medium" | "high";
  mode?: string;
  adaptive_mode?: "off" | "shadow" | "active";
}

export interface TodayDashboardModel {
  day: string;
  journal: DashboardSection;
  planning: DashboardSection;
  study: DashboardSection;
  experiments: DashboardSection;
  inbox: DashboardSection;
  proposals: DashboardSection;
  attention: DashboardSection;
  diagnostics: DashboardSection;
  revision: string;
}

export class TodayDashboardController {
  model?: TodayDashboardModel;
  inputs: TodayInputs;
  scrollTop = 0;
  private generation = 0;

  constructor(private readonly client: BridgeClient, day: string) {
    this.inputs = { day, available_minutes: 120, study_minutes: 20, energy: "medium", motivation: "medium" };
  }

  async refresh(changes: Partial<TodayInputs> = {}): Promise<TodayDashboardModel> {
    this.inputs = { ...this.inputs, ...changes };
    const generation = ++this.generation;
    const model = await this.client.call<TodayDashboardModel>("today.get", this.inputs as unknown as Record<string, unknown>);
    if (generation === this.generation) this.model = model;
    return model;
  }

  shouldRefresh(path: string): boolean {
    return /^(journal|plans|flashcards|experiments|raw|proposals)\//.test(path);
  }

  sourceLink(path: string, heading?: string): string {
    return heading ? `${path}#${heading}` : path;
  }
}
