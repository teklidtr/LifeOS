export const COPILOT_SCHEMA_VERSION = 1 as const;

export type GoalHorizon = "open" | "weeks" | "months" | "quarter" | "year" | "multi-year";
export type GoalReadiness = "unknown" | "clarifying" | "ready" | "parked" | "not-applicable";
export type MilestoneWave = "current" | "next" | "later";
export type PlanningResponseKind = "answered" | "skipped" | "unknown" | "not-relevant";

export interface CopilotGoalRecord {
  schema_version: number;
  goal_id: string;
  title: string;
  status: string;
  path: string;
  content_hash: string;
  description?: string;
  horizon?: GoalHorizon;
  why?: string;
  desired_change?: string;
  constraints: string[];
  non_goals: string[];
  review_cadence?: string;
  readiness?: GoalReadiness;
  active_plan_refs: string[];
}

export interface CopilotMilestone {
  milestone_id: string;
  title: string;
  outcome: string;
  status: string;
  wave: MilestoneWave;
  target_date?: string;
  depends_on: string[];
}

export interface CopilotNearTermAction {
  task_id: string;
  title: string;
  status: string;
  duration?: number;
  energy?: "low" | "medium" | "high";
  motivation?: "low" | "medium" | "high";
  mode?: string;
  due?: string;
  blocked_by: string[];
  milestone_id?: string;
  rationale?: string;
  source_refs: string[];
}

export interface CopilotPlanRecord {
  schema_version: number;
  plan_id: string;
  title: string;
  status: string;
  path: string;
  content_hash: string;
  goal_ref?: string;
  desired_outcome?: string;
  success_evidence: string[];
  boundaries: string[];
  assumptions: string[];
  review_date?: string;
  milestones: CopilotMilestone[];
  tasks: CopilotNearTermAction[];
  rolling_wave_depth?: number;
  supersedes?: string;
  superseded_by?: string;
}

export interface CopilotPlanningAnswer {
  question_id: string;
  response_kind: PlanningResponseKind;
  value?: string;
}

export interface CopilotPlanningSession {
  schema_version: number;
  session_id: string;
  goal_ref: string;
  goal_hash: string;
  status: "draft" | "clarifying" | "ready" | "option-review" | "proposal-created" | "parked" | "abandoned" | "closed";
  answers: CopilotPlanningAnswer[];
  selected_context_refs: string[];
  excluded_context_refs: string[];
  decisions: Array<{ decision_id: string; kind: string; label: string; rationale?: string }>;
  selected_option_id?: string;
  proposal_ids: string[];
  source_revision: number;
}
