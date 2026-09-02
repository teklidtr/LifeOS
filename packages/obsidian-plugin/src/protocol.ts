export const PROTOCOL_VERSION = "1.0" as const;
export const RUNTIME_SCHEMA_VERSION = 1 as const;

export type ConnectionState =
  | "starting"
  | "connected"
  | "degraded"
  | "incompatible"
  | "unavailable"
  | "stopped";

export interface BridgeError {
  code: string;
  message: string;
  data: Record<string, unknown>;
}

export interface HandshakeResult {
  protocol: string;
  engine_version: string;
  runtime_schema: number;
  capabilities: string[];
  actor_id: string;
}

export type RequestCancellationOutcome =
  | "cancelled-before-start"
  | "cancellation-requested"
  | "already-requested"
  | "already-completed"
  | "unknown-request"
  | "not-cancellable";

export interface RequestCancellationResult {
  request_id: string;
  outcome: RequestCancellationOutcome;
  accepted: boolean;
}

export interface CancelableBridgeRequest<T> {
  requestId: string;
  result: Promise<T>;
  cancel(): Promise<RequestCancellationResult>;
}

export interface BridgeClient {
  start(settings: LifeOSSettings): Promise<HandshakeResult>;
  call<T>(method: string, params: Record<string, unknown>): Promise<T>;
  callCancelable?<T>(
    method: string,
    params: Record<string, unknown>,
  ): CancelableBridgeRequest<T>;
  onNotification(listener: (method: string, params: Record<string, unknown>) => void): () => void;
  stop(): Promise<void>;
}

export interface LifeOSSettings {
  configPath: string;
  pythonPath: string;
  actorId: string;
  startOnLoad: boolean;
  diagnostics: "quiet" | "normal" | "verbose";
}
