import { ConnectionManager } from "./connection.js";
import { BridgeClient, LifeOSSettings } from "./protocol.js";
import { loadingState, ViewState } from "./ui-state.js";
import { GoalPlanWorkspaceController, WorkspaceOrigin } from "./goal-plan-workspace.js";
import { ReviewWorkspaceController, ReviewWorkspaceOrigin } from "./review-workspace.js";

export interface ObsidianHost {
  addRibbonIcon(icon: string, title: string, callback: () => void): () => void;
  addCommand(id: string, name: string, callback: () => void): () => void;
  registerView(type: string, factory: () => unknown): () => void;
  openView(type: string): void;
  saveSettings(settings: LifeOSSettings): Promise<void>;
  getActiveFilePath?(): string | undefined;
  openFilePath?(path: string): void;
}

export class LifeOSView {
  state: ViewState = loadingState();
  refreshCount = 0;
  refresh(): void { this.refreshCount += 1; }
}

export class GoalPlanWorkspaceView {
  refreshCount = 0;
  constructor(readonly controller: GoalPlanWorkspaceController) {}
  refresh(): void { this.refreshCount += 1; }
}

export class ReviewWorkspaceView {
  refreshCount = 0;
  constructor(readonly controller: ReviewWorkspaceController) {}
  refresh(): void { this.refreshCount += 1; }
}

export class LifeOSPlugin {
  static readonly VIEW_TYPE = "lifeos-today";
  static readonly COPILOT_VIEW_TYPE = "lifeos-goal-plan";
  static readonly REVIEW_VIEW_TYPE = "lifeos-reviews";
  readonly view = new LifeOSView();
  readonly copilot: GoalPlanWorkspaceController;
  readonly copilotView: GoalPlanWorkspaceView;
  readonly reviews: ReviewWorkspaceController;
  readonly reviewView: ReviewWorkspaceView;
  readonly connection: ConnectionManager;
  private disposers: Array<() => void> = [];

  constructor(
    private readonly host: ObsidianHost,
    client: BridgeClient,
    readonly settings: LifeOSSettings,
  ) {
    this.connection = new ConnectionManager(client, () => this.view.refresh());
    this.copilot = new GoalPlanWorkspaceController(client);
    this.copilotView = new GoalPlanWorkspaceView(this.copilot);
    this.reviews = new ReviewWorkspaceController(client, (path) => this.host.openFilePath?.(path));
    this.reviewView = new ReviewWorkspaceView(this.reviews);
  }

  async load(): Promise<void> {
    this.disposers.push(this.host.registerView(LifeOSPlugin.VIEW_TYPE, () => this.view));
    this.disposers.push(this.host.registerView(LifeOSPlugin.COPILOT_VIEW_TYPE, () => this.copilotView));
    this.disposers.push(this.host.registerView(LifeOSPlugin.REVIEW_VIEW_TYPE, () => this.reviewView));
    this.disposers.push(this.host.addRibbonIcon("layout-dashboard", "Open LifeOS", () => this.openToday()));
    this.disposers.push(this.host.addCommand("lifeos-open-today", "Open LifeOS Today", () => this.openToday()));
    this.disposers.push(this.host.addCommand("lifeos-open-goal-plan", "Open Goal-to-Plan Copilot", () => this.openGoalPlan("command-palette")));
    this.disposers.push(this.host.addCommand("lifeos-plan-active-goal", "Plan from Active Goal Note", () => {
      const path = this.host.getActiveFilePath?.();
      this.openGoalPlan("goal-note");
      if (path?.startsWith("goals/") && path.endsWith(".md")) {
        const sessionId = `session-${path.replace(/[^a-z0-9]+/gi, "-").toLowerCase().replace(/^-|-$/g, "")}`;
        void this.copilot.startFromGoal(path, sessionId, "goal-note");
      }
    }));
    this.disposers.push(this.host.addCommand("lifeos-plan-from-capture", "Continue Quick Capture into Goal Planning", () => this.openGoalPlan("quick-capture")));
    this.disposers.push(this.host.addCommand("lifeos-plan-from-review", "Open Goal Planning from Review", () => this.openGoalPlan("goal-review")));
    this.disposers.push(this.host.addCommand("lifeos-open-daily-review", "Open Today's Review", () => {
      const context = this.reviewContext(); this.openReviews("today");
      void this.reviews.openDaily(context.day, context.timezone, context.now, context.hour < 17 ? "morning" : "evening", "today");
    }));
    this.disposers.push(this.host.addCommand("lifeos-open-weekly-review", "Open This Week's Review", () => {
      const context = this.reviewContext(); this.openReviews("week");
      void this.reviews.openWeekly(context.day, context.timezone, context.now, "week");
    }));
    this.disposers.push(this.host.addCommand("lifeos-open-active-review", "Open Active Review Artifact", () => {
      const path = this.host.getActiveFilePath?.(); this.openReviews("active-note");
      if (path?.startsWith("reviews/") && path.endsWith(".md")) void this.reviews.openExisting({ path }, new Date().toISOString(), "active-note");
    }));
    this.disposers.push(this.host.addCommand("lifeos-open-review-history", "Open Review History", () => {
      this.openReviews("history"); void this.reviews.loadHistory();
    }));
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

  openGoalPlan(origin: WorkspaceOrigin): void {
    this.copilot.state = { ...this.copilot.state, origin, focusTarget: "workspace-title" };
    this.host.openView(LifeOSPlugin.COPILOT_VIEW_TYPE);
  }

  openReviews(origin: ReviewWorkspaceOrigin): void {
    this.reviews.state = { ...this.reviews.state, origin, focusTarget: "review-workspace-title" };
    this.host.openView(LifeOSPlugin.REVIEW_VIEW_TYPE);
  }

  private reviewContext(): { day: string; now: string; timezone: string; hour: number } {
    const now = new Date();
    return {
      day: now.toISOString().slice(0, 10),
      now: now.toISOString(),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      hour: now.getHours(),
    };
  }

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
export * from "./goal-plan.js";
export * from "./goal-plan-workspace.js";

export * from "./review-artifact.js";
export * from "./review-workspace.js";
