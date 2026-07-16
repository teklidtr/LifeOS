import { ConnectionManager } from "./connection.js";
import { BridgeClient, LifeOSSettings } from "./protocol.js";
import { loadingState, ViewState } from "./ui-state.js";
import { GoalPlanWorkspaceController, WorkspaceOrigin } from "./goal-plan-workspace.js";
import { ReviewWorkspaceController, ReviewWorkspaceOrigin } from "./review-workspace.js";
import { KnowledgeConversationOrigin, KnowledgeConversationWorkspaceController } from "./knowledge-conversation-workspace.js";
import { emptyScope } from "./knowledge-conversation.js";
import { ExperimentWorkspaceController, ExperimentWorkspaceOrigin } from "./experiment-workspace.js";
import { RichCaptureOrigin, RichCaptureWorkspaceController } from "./rich-capture-workspace.js";
import { CaptureType } from "./rich-capture.js";

export interface ObsidianHost {
  addRibbonIcon(icon: string, title: string, callback: () => void): () => void;
  addCommand(id: string, name: string, callback: () => void): () => void;
  registerView(type: string, factory: () => unknown): () => void;
  openView(type: string): void;
  saveSettings(settings: LifeOSSettings): Promise<void>;
  getActiveFilePath?(): string | undefined;
  getSelectedText?(): string | undefined;
  getActiveFolderPath?(): string | undefined;
  getActiveTag?(): string | undefined;
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

export class KnowledgeConversationWorkspaceView {
  refreshCount = 0;
  constructor(readonly controller: KnowledgeConversationWorkspaceController) {}
  refresh(): void { this.refreshCount += 1; }
}

export class ReviewWorkspaceView {
  refreshCount = 0;
  constructor(readonly controller: ReviewWorkspaceController) {}
  refresh(): void { this.refreshCount += 1; }
}

export class ExperimentWorkspaceView {
  refreshCount = 0;
  constructor(readonly controller: ExperimentWorkspaceController) {}
  refresh(): void { this.refreshCount += 1; }
}

export class RichCaptureWorkspaceView {
  refreshCount = 0;
  constructor(readonly controller: RichCaptureWorkspaceController) {}
  refresh(): void { this.refreshCount += 1; }
}

export class LifeOSPlugin {
  static readonly VIEW_TYPE = "lifeos-today";
  static readonly COPILOT_VIEW_TYPE = "lifeos-goal-plan";
  static readonly REVIEW_VIEW_TYPE = "lifeos-reviews";
  static readonly KNOWLEDGE_CONVERSATION_VIEW_TYPE = "lifeos-knowledge-conversation";
  static readonly EXPERIMENT_VIEW_TYPE = "lifeos-experiments";
  static readonly RICH_CAPTURE_VIEW_TYPE = "lifeos-rich-capture";
  readonly view = new LifeOSView();
  readonly copilot: GoalPlanWorkspaceController;
  readonly copilotView: GoalPlanWorkspaceView;
  readonly reviews: ReviewWorkspaceController;
  readonly reviewView: ReviewWorkspaceView;
  readonly knowledgeConversations: KnowledgeConversationWorkspaceController;
  readonly knowledgeConversationView: KnowledgeConversationWorkspaceView;
  readonly experiments: ExperimentWorkspaceController;
  readonly experimentView: ExperimentWorkspaceView;
  readonly richCaptures: RichCaptureWorkspaceController;
  readonly richCaptureView: RichCaptureWorkspaceView;
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
    this.knowledgeConversations = new KnowledgeConversationWorkspaceController(client, (path) => this.host.openFilePath?.(path));
    this.knowledgeConversationView = new KnowledgeConversationWorkspaceView(this.knowledgeConversations);
    this.experiments = new ExperimentWorkspaceController(client, (path) => this.host.openFilePath?.(path));
    this.experimentView = new ExperimentWorkspaceView(this.experiments);
    this.richCaptures = new RichCaptureWorkspaceController(client, (path) => this.host.openFilePath?.(path));
    this.richCaptureView = new RichCaptureWorkspaceView(this.richCaptures);
  }

  async load(): Promise<void> {
    this.disposers.push(this.host.registerView(LifeOSPlugin.VIEW_TYPE, () => this.view));
    this.disposers.push(this.host.registerView(LifeOSPlugin.COPILOT_VIEW_TYPE, () => this.copilotView));
    this.disposers.push(this.host.registerView(LifeOSPlugin.REVIEW_VIEW_TYPE, () => this.reviewView));
    this.disposers.push(this.host.registerView(LifeOSPlugin.KNOWLEDGE_CONVERSATION_VIEW_TYPE, () => this.knowledgeConversationView));
    this.disposers.push(this.host.registerView(LifeOSPlugin.EXPERIMENT_VIEW_TYPE, () => this.experimentView));
    this.disposers.push(this.host.registerView(LifeOSPlugin.RICH_CAPTURE_VIEW_TYPE, () => this.richCaptureView));
    this.disposers.push(this.host.addRibbonIcon("layout-dashboard", "Open LifeOS", () => this.openToday()));
    this.disposers.push(this.host.addRibbonIcon("messages-square", "Open Knowledge Conversation", () => this.openKnowledgeConversation("ribbon")));
    this.disposers.push(this.host.addRibbonIcon("flask-conical", "Open Personal Experiments", () => this.openExperiments("ribbon")));
    this.disposers.push(this.host.addRibbonIcon("camera", "Open Rich Capture", () => this.openRichCapture("ribbon")));
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
    this.disposers.push(this.host.addCommand("lifeos-open-knowledge-conversation", "Open Knowledge Conversation", () => this.openKnowledgeConversation("command-palette")));
    this.disposers.push(this.host.addCommand("lifeos-ask-active-note", "Ask About Active Note", () => {
      const path = this.host.getActiveFilePath?.();
      this.openKnowledgeConversation("active-note", path ? { paths: [path] } : {});
    }));
    this.disposers.push(this.host.addCommand("lifeos-ask-selection", "Ask About Selected Text", () => {
      const path = this.host.getActiveFilePath?.(); const query = this.host.getSelectedText?.() ?? "";
      this.openKnowledgeConversation("selection", path ? { paths: [path] } : {}, query);
    }));
    this.disposers.push(this.host.addCommand("lifeos-ask-folder", "Ask Within Active Folder", () => {
      const folder = this.host.getActiveFolderPath?.();
      this.openKnowledgeConversation("folder", folder ? { folders: [folder] } : {});
    }));
    this.disposers.push(this.host.addCommand("lifeos-ask-tag", "Ask Within Active Tag", () => {
      const tag = this.host.getActiveTag?.();
      this.openKnowledgeConversation("tag", tag ? { tags: [tag] } : {});
    }));
    this.disposers.push(this.host.addCommand("lifeos-open-experiments", "Open Personal Experiments", () => this.openExperiments("command-palette")));
    this.disposers.push(this.host.addCommand("lifeos-create-experiment", "Create Personal Experiment", () => {
      const path = this.host.getActiveFilePath?.();
      this.openExperiments(this.experimentOrigin(path), path);
    }));
    this.disposers.push(this.host.addCommand("lifeos-open-active-experiment", "Open Active Experiment Workspace", () => {
      const path = this.host.getActiveFilePath?.();
      this.openExperiments("active-note", path);
      if (path?.startsWith("experiments/") && path.endsWith(".md")) void this.experiments.load(path, "active-note");
    }));
    this.disposers.push(this.host.addCommand("lifeos-open-experiment-history", "Open Experiment History", () => {
      this.openExperiments("history"); void this.experiments.loadHistory();
    }));
    this.disposers.push(this.host.addCommand("lifeos-open-rich-capture", "Open Rich Capture", () => this.openRichCapture("command-palette")));
    this.disposers.push(this.host.addCommand("lifeos-quick-capture-meal", "Quick Capture Meal", () => this.openRichCapture("command-palette", "meal")));
    this.disposers.push(this.host.addCommand("lifeos-quick-capture-exercise", "Quick Capture Exercise", () => this.openRichCapture("command-palette", "exercise")));
    this.disposers.push(this.host.addCommand("lifeos-capture-selection", "Capture Selected Text", () => {
      const path = this.host.getActiveFilePath?.();
      this.openRichCapture("selection", "attachment", this.host.getSelectedText?.() ?? "", path);
    }));
    this.disposers.push(this.host.addCommand("lifeos-open-active-capture", "Open Active Rich Capture", () => {
      const path = this.host.getActiveFilePath?.();
      this.openRichCapture("active-note", "attachment", "", path);
      if (path?.startsWith("captures/") && path.endsWith(".md")) void this.richCaptures.load(path, "active-note");
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


  openKnowledgeConversation(origin: KnowledgeConversationOrigin, scope: Record<string, unknown> = {}, query = ""): void {
    this.knowledgeConversations.prepare(origin, { ...emptyScope(), ...scope }, query);
    this.host.openView(LifeOSPlugin.KNOWLEDGE_CONVERSATION_VIEW_TYPE);
  }

  openReviews(origin: ReviewWorkspaceOrigin): void {
    this.reviews.state = { ...this.reviews.state, origin, focusTarget: "review-workspace-title" };
    this.host.openView(LifeOSPlugin.REVIEW_VIEW_TYPE);
  }

  openExperiments(origin: ExperimentWorkspaceOrigin, sourcePath?: string): void {
    this.experiments.prepare(origin, sourcePath);
    this.host.openView(LifeOSPlugin.EXPERIMENT_VIEW_TYPE);
  }

  openRichCapture(origin: RichCaptureOrigin, captureType: CaptureType = "attachment", description = "", sourcePath?: string): void {
    this.richCaptures.prepare(origin, captureType, description, sourcePath);
    this.host.openView(LifeOSPlugin.RICH_CAPTURE_VIEW_TYPE);
  }

  private experimentOrigin(path?: string): ExperimentWorkspaceOrigin {
    if (!path) return "command-palette";
    if (path.startsWith("goals/")) return "goal";
    if (path.startsWith("plans/")) return "plan";
    if (path.startsWith("tasks/")) return "task";
    if (path.startsWith("captures/")) return "capture";
    if (path.startsWith("reviews/daily/")) return "daily-review";
    if (path.startsWith("reviews/weekly/")) return "weekly-review";
    if (path.startsWith("conversations/")) return "knowledge-conversation";
    if (path.startsWith("experiments/")) return "active-note";
    return "command-palette";
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
export * from "./knowledge-conversation.js";
export * from "./knowledge-conversation-workspace.js";
export * from "./experiment.js";
export * from "./experiment-workspace.js";
export * from "./rich-capture.js";
export * from "./rich-capture-workspace.js";
