import { BridgeClient, ConnectionState, HandshakeResult, LifeOSSettings, PROTOCOL_VERSION, RUNTIME_SCHEMA_VERSION } from "./protocol.js";

export type ConnectionListener = (state: ConnectionState, detail?: string) => void;

export class ConnectionManager {
  private state: ConnectionState = "stopped";
  private handshake?: HandshakeResult;
  private listeners = new Set<ConnectionListener>();
  private unsubscribe?: () => void;

  constructor(private readonly client: BridgeClient, private readonly invalidated: () => void) {}

  get current(): ConnectionState { return this.state; }
  get capabilities(): readonly string[] { return this.handshake?.capabilities ?? []; }

  subscribe(listener: ConnectionListener): () => void {
    this.listeners.add(listener);
    listener(this.state);
    return () => this.listeners.delete(listener);
  }

  private setState(state: ConnectionState, detail?: string): void {
    this.state = state;
    for (const listener of this.listeners) listener(state, detail);
  }

  async start(settings: LifeOSSettings): Promise<void> {
    if (this.state === "starting" || this.state === "connected") return;
    this.setState("starting");
    try {
      const handshake = await this.client.start(settings);
      if (handshake.protocol.split(".")[0] !== PROTOCOL_VERSION.split(".")[0]) {
        this.setState("incompatible", `Engine protocol ${handshake.protocol} is incompatible.`);
        await this.client.stop();
        return;
      }
      if (handshake.runtime_schema !== RUNTIME_SCHEMA_VERSION) {
        this.setState("incompatible", `Engine runtime schema ${handshake.runtime_schema} is incompatible.`);
        await this.client.stop();
        return;
      }
      this.handshake = handshake;
      this.unsubscribe = this.client.onNotification((method) => {
        if (method === "vault.changed" || method === "attention.changed") this.invalidated();
      });
      this.setState("connected");
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Bridge could not start.";
      this.setState("unavailable", detail);
    }
  }

  markCrashed(detail = "The LifeOS engine stopped unexpectedly."): void {
    if (this.state !== "stopped") this.setState("unavailable", detail);
  }

  async stop(): Promise<void> {
    this.unsubscribe?.();
    this.unsubscribe = undefined;
    await this.client.stop();
    this.handshake = undefined;
    this.setState("stopped");
  }
}
