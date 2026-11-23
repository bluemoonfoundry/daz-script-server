/** Recording fakes for DazScene/DazCamera, shared by the shot unit tests. */

import type { DazCamera } from "../src/camera.js";
import type { DazScene } from "../src/scene.js";

/** Records every method call as `[name, ...args]`. */
export class FakeCamera {
  calls: unknown[][] = [];
  constructor() {
    return new Proxy(this, {
      get(target, prop, receiver) {
        if (prop in target || typeof prop === "symbol" || prop === "then") return Reflect.get(target, prop, receiver);
        return async (...args: unknown[]) => {
          target.calls.push([prop, ...args]);
        };
      },
    });
  }
}

export class FakeScene {
  created: Array<[string | undefined, FakeCamera]> = [];
  animRanges: Array<[number, number]> = [];
  frames: number[] = [];
  async createCamera(name?: string): Promise<FakeCamera> {
    const cam = new FakeCamera();
    this.created.push([name, cam]);
    return cam;
  }
  async setAnimRange(start: number, end: number): Promise<void> {
    this.animRanges.push([start, end]);
  }
  async setFrame(frame: number): Promise<void> {
    this.frames.push(frame);
  }
}

export const asScene = (s: FakeScene) => s as unknown as DazScene;
export const asCamera = (c: FakeCamera) => c as unknown as DazCamera;
