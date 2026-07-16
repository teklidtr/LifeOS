export type ViewStateKind = "loading" | "empty" | "ready" | "stale" | "blocked" | "error";

export interface ViewState {
  kind: ViewStateKind;
  title: string;
  detail: string;
  action?: { label: string; run: () => void };
}

export const loadingState = (detail = "Connecting to the local LifeOS engine…"): ViewState => ({
  kind: "loading",
  title: "LifeOS is starting",
  detail,
});

export const errorState = (title: string, detail: string, retry?: () => void): ViewState => ({
  kind: "error",
  title,
  detail,
  action: retry ? { label: "Retry", run: retry } : undefined,
});
