import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import {
  applyAnimatedShot,
  applyFrameSubject,
  applyOrbitCamera,
  applyStaticShot,
} from "../../src/cinematics.js";
import { DazCamera } from "../../src/camera.js";
import { Vec3 } from "../../src/math3.js";
import { DazScene } from "../../src/scene.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stubSequence(results: unknown[]) {
  let i = 0;
  const fetchMock = vi.fn().mockImplementation(() => {
    const value = results[Math.min(i, results.length - 1)];
    i += 1;
    return Promise.resolve(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
function scriptOf(fetchMock: ReturnType<typeof vi.fn>, callIndex: number): string {
  return JSON.parse(fetchMock.mock.calls[callIndex][1].body as string).script;
}

describe("applyStaticShot", () => {
  it("creates a camera, positions it, aims at lookAt, and applies optics in order", async () => {
    const fetchMock = stubSequence(["Cam1", undefined, undefined, undefined, undefined]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const cam = await applyStaticShot(scene, { position: new Vec3(1, 2, 3), lookAt: new Vec3(0, 0, 0), focalLength: 85 });
    expect(cam).toBeInstanceOf(DazCamera);
    expect(scriptOf(fetchMock, 0)).toContain("new DzBasicCamera()");
    expect(scriptOf(fetchMock, 1)).toContain("new DzVec3(1, 2, 3)");
    expect(scriptOf(fetchMock, 2)).toContain("_node.aimAt(new DzVec3(0, 0, 0));");
    expect(scriptOf(fetchMock, 3)).toContain("_node.focalLength = 85;");
    expect(scriptOf(fetchMock, 4)).toContain("Depth of Field");
  });

  it("uses explicit rotation when lookAt is not set", async () => {
    const fetchMock = stubSequence(["Cam1", undefined, undefined, undefined, undefined]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await applyStaticShot(scene, { position: new Vec3(0, 0, 0), rotation: [10, 20, 30] });
    expect(scriptOf(fetchMock, 2)).toContain("getXRotControl().setValue(10)");
  });

  it("reuses an existing camera instead of creating one when `camera` is given", async () => {
    const fetchMock = stubSequence([undefined, undefined, undefined]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const existing = new DazCamera(new DazClient({ token: "" }), { value: "ExistingCam", kind: "name" });
    const cam = await applyStaticShot(scene, { position: new Vec3(0, 0, 0) }, { camera: existing });
    expect(cam).toBe(existing);
    expect(scriptOf(fetchMock, 0)).toContain('Scene.findNode("ExistingCam")');
  });
});

describe("applyOrbitCamera", () => {
  it("throws before any HTTP call when frameEnd < frameStart", async () => {
    const fetchMock = stubSequence([undefined]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(applyOrbitCamera(scene, { target: new Vec3(0, 0, 0), radius: 100, frameStart: 10, frameEnd: 5 })).rejects.toThrow(
      "OrbitCamera.frameEnd (5) must be >= frameStart (10)",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("widens the anim range, then sweeps position/aim per frame", async () => {
    const fetchMock = stubSequence(["Cam1", undefined, undefined, undefined, undefined, undefined, undefined, undefined, undefined]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await applyOrbitCamera(scene, { target: new Vec3(0, 0, 0), radius: 100, frameStart: 0, frameEnd: 1, targetOffsetCm: 0 });
    expect(scriptOf(fetchMock, 0)).toContain("new DzBasicCamera()");
    expect(scriptOf(fetchMock, 1)).toContain("Scene.setAnimRange");
    expect(scriptOf(fetchMock, 2)).toContain("_node.focalLength = 50;");
    // per-frame: setFrame, setPosition, aimAt -- x2 frames
    expect(scriptOf(fetchMock, 3)).toContain("Scene.setFrame(0);");
    expect(scriptOf(fetchMock, 6)).toContain("Scene.setFrame(1);");
  });
});

describe("applyFrameSubject", () => {
  it("throws on an invalid shotType", async () => {
    const fetchMock = stubSequence([undefined]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(applyFrameSubject(scene, { subject: new Vec3(0, 0, 0), shotType: "bogus" as never })).rejects.toThrow(
      "Invalid FrameSubject.shotType",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("places the camera at the shot-type's preset distance and default target offset", async () => {
    const fetchMock = stubSequence(["Cam1", undefined, undefined, undefined]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await applyFrameSubject(scene, { subject: new Vec3(0, 0, 0), shotType: "close_up" });
    const posScript = scriptOf(fetchMock, 1);
    // close_up distance=60, offset=45, azimuth=0, elevation=10 -> position derived via sphericalOffset
    expect(posScript).toContain("new DzVec3(");
    expect(scriptOf(fetchMock, 3)).toContain("_node.focalLength = 50;");
  });
});

describe("applyAnimatedShot", () => {
  it("throws when fewer than two keyframes are given", async () => {
    const fetchMock = stubSequence([undefined]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(
      applyAnimatedShot(scene, { keyframes: [{ frame: 0, position: new Vec3(0, 0, 0) }] }),
    ).rejects.toThrow("needs at least two waypoints");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("throws when frame numbers are not strictly ascending", async () => {
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(
      applyAnimatedShot(scene, {
        keyframes: [
          { frame: 5, position: new Vec3(0, 0, 0) },
          { frame: 2, position: new Vec3(1, 0, 0) },
        ],
      }),
    ).rejects.toThrow("strictly ascending, unique frame numbers");
  });

  it("throws when only some keyframes specify an orientation", async () => {
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(
      applyAnimatedShot(scene, {
        keyframes: [
          { frame: 0, position: new Vec3(0, 0, 0), rotation: [0, 0, 0] },
          { frame: 1, position: new Vec3(1, 0, 0) },
        ],
      }),
    ).rejects.toThrow("must either all specify an orientation");
  });

  it("clears position keys always, and rotation keys only when oriented, then writes each waypoint", async () => {
    const fetchMock = stubSequence(["Cam1", undefined, undefined, undefined, undefined, undefined, undefined]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await applyAnimatedShot(scene, {
      keyframes: [
        { frame: 0, position: new Vec3(0, 0, 0), rotation: [0, 0, 0] },
        { frame: 10, position: new Vec3(1, 0, 0), rotation: [0, 90, 0] },
      ],
    });
    // createCamera, setFocalLength, setDepthOfField, clearPositionKeys, clearRotationKeys,
    // setPositionAtFrame+setRotationAtFrame x2 = 9 calls
    expect(fetchMock.mock.calls.length).toBe(9);
  });

  it("does not clear rotation keys when no keyframe specifies an orientation", async () => {
    const fetchMock = stubSequence(["Cam1", undefined, undefined, undefined, undefined, undefined]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await applyAnimatedShot(scene, {
      keyframes: [
        { frame: 0, position: new Vec3(0, 0, 0) },
        { frame: 10, position: new Vec3(1, 0, 0) },
      ],
    });
    // createCamera, setFocalLength, setDepthOfField, clearPositionKeys, setPositionAtFrame x2 = 6 calls (no clearRotationKeys)
    expect(fetchMock.mock.calls.length).toBe(6);
  });
});
