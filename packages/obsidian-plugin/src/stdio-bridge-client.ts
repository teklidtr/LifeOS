import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { dirname, resolve } from "node:path";
import { createInterface, type Interface as ReadlineInterface } from "node:readline";

import {
  type BridgeClient,
  type BridgeError,
  type HandshakeResult,
  type LifeOSSettings,
  PROTOCOL_VERSION,
} from "./protocol.js";

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
}

interface JsonRpcResponse {
  jsonrpc: "2.0";
  id?: string | number | null;
  method?: string;
  params?: Record<string, unknown>;
  result?: unknown;
  error?: BridgeError;
}

export class BridgeRpcError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly data: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "BridgeRpcError";
  }
}

export class StdioBridgeClient implements BridgeClient {
  private child?: ChildProcessWithoutNullStreams;
  private lines?: ReadlineInterface;
  private sequence = 0;
  private pending = new Map<string, PendingRequest>();
  private listeners = new Set<(method: string, params: Record<string, unknown>) => void>();
  private recentStderr = "";
  private stopping = false;

  async start(settings: LifeOSSettings): Promise<HandshakeResult> {
    if (this.child) throw new Error("The LifeOS bridge is already running.");

    const pythonPath = settings.pythonPath.trim();
    const actorId = settings.actorId.trim();
    const configPath = resolve(settings.configPath.trim());
    if (!pythonPath) throw new Error("Choose a trusted Python executable in LifeOS Settings.");
    if (!actorId) throw new Error("Set a local actor ID in LifeOS Settings.");
    if (!settings.configPath.trim()) throw new Error("Choose lifeos.yml in LifeOS Settings.");

    const child = spawn(
      pythonPath,
      ["-m", "lifeos.bridge", "--config", configPath, "--actor-id", actorId],
      {
        cwd: dirname(configPath),
        env: process.env,
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      },
    );
    this.child = child;
    this.stopping = false;
    this.recentStderr = "";

    this.lines = createInterface({ input: child.stdout });
    this.lines.on("line", (line) => this.handleLine(line));
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk: string) => {
      this.recentStderr = `${this.recentStderr}${chunk}`.slice(-4096);
    });
    child.once("exit", (code, signal) => this.handleExit(code, signal));

    try {
      await new Promise<void>((accept, reject) => {
        child.once("spawn", accept);
        child.once("error", reject);
      });
      return await this.call<HandshakeResult>("system.handshake", {
        protocol: PROTOCOL_VERSION,
        client_version: "0.2.0",
      });
    } catch (error) {
      this.cleanupChild(child);
      if (!child.killed) child.kill();
      throw error;
    }
  }

  call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    const child = this.child;
    if (!child || child.stdin.destroyed || !child.stdin.writable) {
      return Promise.reject(new Error("The LifeOS bridge is not running."));
    }

    const id = `obsidian-${++this.sequence}`;
    const frame = JSON.stringify({ jsonrpc: "2.0", id, method, params });
    return new Promise<T>((accept, reject) => {
      this.pending.set(id, {
        resolve: (value) => accept(value as T),
        reject,
      });
      child.stdin.write(`${frame}\n`, "utf8", (error) => {
        if (!error) return;
        this.pending.delete(id);
        reject(error);
      });
    });
  }

  onNotification(
    listener: (method: string, params: Record<string, unknown>) => void,
  ): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  async stop(): Promise<void> {
    const child = this.child;
    if (!child) return;
    this.stopping = true;

    try {
      await Promise.race([
        this.call("system.shutdown", {}),
        new Promise((_, reject) => setTimeout(() => reject(new Error("Shutdown timed out.")), 1000)),
      ]);
    } catch {
      if (!child.killed) child.kill();
    }

    if (this.child === child) {
      await Promise.race([
        new Promise<void>((accept) => child.once("exit", () => accept())),
        new Promise<void>((accept) => setTimeout(accept, 1000)),
      ]);
    }
    if (this.child === child) {
      if (!child.killed) child.kill();
      this.cleanupChild(child);
    }
  }

  private handleLine(line: string): void {
    let frame: JsonRpcResponse;
    try {
      frame = JSON.parse(line) as JsonRpcResponse;
    } catch {
      this.failPending(new Error("The LifeOS bridge returned malformed JSON."));
      return;
    }
    if (frame.jsonrpc !== "2.0") return;

    if (frame.method && frame.id === undefined) {
      for (const listener of this.listeners) listener(frame.method, frame.params ?? {});
      return;
    }

    if (frame.id === undefined || frame.id === null) return;
    const id = String(frame.id);
    const pending = this.pending.get(id);
    if (!pending) return;
    this.pending.delete(id);
    if (frame.error) {
      pending.reject(new BridgeRpcError(frame.error.code, frame.error.message, frame.error.data));
    } else {
      pending.resolve(frame.result);
    }
  }

  private handleExit(code: number | null, signal: NodeJS.Signals | null): void {
    const child = this.child;
    if (!child) return;
    const detail = this.recentStderr.trim();
    const reason = this.stopping
      ? "The LifeOS bridge stopped."
      : `The LifeOS bridge exited${code === null ? "" : ` with code ${code}`}${signal ? ` (${signal})` : ""}.`;
    const message = detail ? `${reason} ${detail}` : reason;
    this.failPending(new Error(message));
    if (!this.stopping) {
      for (const listener of this.listeners) {
        listener("system.bridge_stopped", { detail: message });
      }
    }
    this.cleanupChild(child);
  }

  private failPending(error: Error): void {
    for (const request of this.pending.values()) request.reject(error);
    this.pending.clear();
  }

  private cleanupChild(child: ChildProcessWithoutNullStreams): void {
    if (this.child !== child) return;
    this.lines?.close();
    this.lines = undefined;
    this.child = undefined;
    this.stopping = false;
  }
}
