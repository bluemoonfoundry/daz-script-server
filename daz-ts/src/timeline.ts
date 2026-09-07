import type { DazClient } from "./client.js";
import { DazClient as DazClientImpl } from "./client.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Timeline and playback control for the active scene. A thin wrapper
 * around the `Scene` playback API — `DazScene` offers the same frame/range
 * methods; use `DazTimeline` when a focused, dedicated object is preferred.
 */
export class DazTimeline {
  private readonly client: DazClient;

  constructor(client?: DazClient) {
    this.client = client ?? new DazClientImpl();
  }

  /** Current timeline frame (read/write). */
  async frame(): Promise<number | null> {
    return (await this.client.execute(ScriptBuilder.iife("return Scene.getFrame();"))).value as number | null;
  }

  async setFrame(value: number): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`Scene.setFrame(${ScriptBuilder.serializeArg(Math.trunc(value))});`));
  }

  /** Current time in DAZ ticks (use {@link frame} for frame-based access). */
  async time(): Promise<number | null> {
    return (await this.client.execute(ScriptBuilder.iife("return Scene.getTime().valueOf();"))).value as number | null;
  }

  /** Number of DAZ ticks per frame (read-only). */
  async timeStep(): Promise<number | null> {
    return (await this.client.execute(ScriptBuilder.iife("return Scene.getTimeStep();"))).value as number | null;
  }

  /** Animation range as `{start, end}` in frames (read-only). */
  async frameRange(): Promise<{ start: number; end: number } | null> {
    const script = ScriptBuilder.iife(
      "return { start: Scene.getAnimRange().start, end: Scene.getAnimRange().end };",
    );
    return (await this.client.execute(script)).value as { start: number; end: number } | null;
  }

  async play(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife("Scene.play();"));
  }

  async pause(): Promise<void> {
    await this.client.execute(ScriptBuilder.iife("Scene.stop();"));
  }
}
