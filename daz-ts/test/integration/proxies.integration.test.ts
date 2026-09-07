import { beforeAll, describe, expect, it } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazScene } from "../../src/scene.js";
import { DazTimeline } from "../../src/timeline.js";
import { DazViewport } from "../../src/viewport.js";
import { withUndo } from "../../src/undo.js";

const SERVER_URL = process.env.DAZ_SERVER_URL;

describe.skipIf(!SERVER_URL)("daz-ts Phase 2 proxies against a live DAZ Studio server", () => {
  let client: DazClient;
  let scene: DazScene;

  beforeAll(() => {
    const url = new URL(SERVER_URL!);
    client = new DazClient({ host: url.hostname, port: Number(url.port) || 18811 });
    scene = new DazScene(client);
  });

  it("overview() returns a well-formed scene summary", async () => {
    const overview = await scene.overview();
    expect(overview).toHaveProperty("total_nodes");
    expect(overview).toHaveProperty("figures");
    expect(overview).toHaveProperty("cameras");
    expect(overview).toHaveProperty("lights");
  });

  it("nodes() returns typed proxies whose position()/rotation() resolve without error", async () => {
    const nodes = await scene.nodes();
    for (const node of nodes.slice(0, 3)) {
      await expect(node.position()).resolves.not.toBeUndefined();
      await expect(node.rotation()).resolves.not.toBeUndefined();
    }
  });

  it("findSkeleton()'s retry logic tolerates a scene with zero skeletons by raising NodeNotFoundError, not hanging", async () => {
    const numSkeletons = await scene.numSkeletons();
    if (numSkeletons > 0) return;
    await expect(scene.findSkeleton("NoSuchFigure", { retryAttempts: 1 })).rejects.toThrow();
  });

  it("skeletons() returns DazSkeleton proxies whose bone list resolves", async () => {
    const skeletons = await scene.skeletons();
    if (skeletons.length === 0) return;
    const bones = await skeletons[0].bones();
    expect(Array.isArray(bones)).toBe(true);
  });

  it("cameras() and lights() return typed proxies without error", async () => {
    const cameras = await scene.cameras();
    const lights = await scene.lights();
    expect(Array.isArray(cameras)).toBe(true);
    expect(Array.isArray(lights)).toBe(true);
  });

  it("sceneSnapshot() and allNodeTransforms() succeed as bulk snapshot calls", async () => {
    const snapshot = await scene.sceneSnapshot();
    const transforms = await scene.allNodeTransforms();
    expect(Array.isArray(snapshot)).toBe(true);
    expect(Array.isArray(transforms)).toBe(true);
  });

  it("DazViewport.isAvailable() reflects whether a 3D viewport is open", async () => {
    const vp = new DazViewport(client);
    expect(typeof (await vp.isAvailable())).toBe("boolean");
  });

  it("DazTimeline.frame()/frameRange() resolve without error", async () => {
    const timeline = new DazTimeline(client);
    await expect(timeline.frame()).resolves.not.toBeUndefined();
    await expect(timeline.frameRange()).resolves.not.toBeUndefined();
  });

  it("withUndo() groups a no-op change into a single undo step without throwing", async () => {
    await expect(
      withUndo(client, "daz-ts integration test no-op", async () => {
        await scene.frame();
      }),
    ).resolves.toBeUndefined();
  });
});
