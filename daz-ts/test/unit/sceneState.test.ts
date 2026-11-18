import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazError } from "../../src/exceptions.js";
import { DazPose } from "../../src/pose.js";
import { DazScene } from "../../src/scene.js";
import { DazSceneState } from "../../src/sceneState.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());

/** Stub fetch with one result per call, in order. Extra calls repeat the last result. */
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

describe("DazSceneState.capture", () => {
  it("captures skeleton poses, follow targets, camera transforms, and light transforms/extra", async () => {
    const fetchMock = stubSequence([
      ["Genesis9"], // scene.skeletons() -> names
      { bones: { hip: [1, 0, 0] }, morphs: {}, props: {} }, // DazPose.capture
      "SkelParent", // skel.followTarget() -> name
      { CameraMain: { XTranslate: 5 } }, // camera transforms
      { transforms: { Spot1: { XTranslate: 1 } }, extra: { Spot1: { Flux: 100 } } }, // light transforms/extra
    ]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const state = await DazSceneState.capture(scene);

    expect(Object.keys(state.skeletonPoses)).toEqual(["Genesis9"]);
    expect(state.skeletonPoses.Genesis9).toBeInstanceOf(DazPose);
    expect(state.skeletonPoses.Genesis9.bones).toEqual({ hip: [1, 0, 0] });
    expect(state.followTargets).toEqual({ Genesis9: "SkelParent" });
    expect(state.cameraTransforms).toEqual({ CameraMain: { XTranslate: 5 } });
    expect(state.lightTransforms).toEqual({ Spot1: { XTranslate: 1 } });
    expect(state.lightExtra).toEqual({ Spot1: { Flux: 100 } });

    const camScript = scriptOf(fetchMock, 3);
    expect(camScript).toContain('var _keys = ["XTranslate","YTranslate","ZTranslate","XRotate","YRotate","ZRotate","Scale"];');
    expect(camScript).toContain("Scene.getNumCameras()");
    expect(camScript).toContain("getRawValue");

    const lightScript = scriptOf(fetchMock, 4);
    expect(lightScript).toContain('var _extraKeys = ["Flux","Shadow Softness","Spread Angle"];');
    expect(lightScript).toContain("Scene.getNumLights()");
  });

  it("captures a null follow target as null", async () => {
    stubSequence([[], null, null, {}, { transforms: {}, extra: {} }]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const state = await DazSceneState.capture(scene);
    expect(state.followTargets).toEqual({});
    expect(state.skeletonPoses).toEqual({});
  });
});

describe("DazSceneState.toDict / fromDict", () => {
  it("round-trips through toDict/fromDict", () => {
    const state = new DazSceneState(
      { Genesis9: new DazPose("Genesis9", { hip: [1, 0, 0] }, {}, {}) },
      { CameraMain: { XTranslate: 5 } },
      { Spot1: { XTranslate: 1 } },
      { Spot1: { Flux: 100 } },
      { Genesis9: null },
    );
    const dict = state.toDict();
    expect(dict.skeletons.Genesis9.bones).toEqual({ hip: [1, 0, 0] });
    expect(dict.follow_targets).toEqual({ Genesis9: null });

    const restored = DazSceneState.fromDict(dict);
    expect(restored.skeletonPoses.Genesis9.bones).toEqual({ hip: [1, 0, 0] });
    expect(restored.cameraTransforms).toEqual({ CameraMain: { XTranslate: 5 } });
    expect(restored.followTargets).toEqual({ Genesis9: null });
  });

  it("fromDict defaults every field for an empty object", () => {
    const restored = DazSceneState.fromDict({});
    expect(restored.skeletonPoses).toEqual({});
    expect(restored.cameraTransforms).toEqual({});
    expect(restored.lightTransforms).toEqual({});
    expect(restored.lightExtra).toEqual({});
    expect(restored.followTargets).toEqual({});
  });
});

describe("DazSceneState.apply", () => {
  it("skips skeletons not found in the scene and reports them in skipped and errors, without throwing", async () => {
    const state = new DazSceneState({ Missing: new DazPose("Missing", {}, {}, {}) }, {}, {}, {}, {});
    stubSequence([
      false, // findSkeleton "Missing" lookup, attempt 1/3
      false, // attempt 2/3
      false, // attempt 3/3
      [], // hint script: no skeletons
      { restored: [], errors: [] }, // node restore script
    ]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await state.apply(scene);
    expect(result.restored).toEqual([]);
    expect(result.skipped).toEqual([{ kind: "skeleton", name: "Missing", reason: "not_found" }]);
    expect(result.errors).toEqual(["Skeleton not found: Missing"]);
    expect(result.complete).toBe(false);
    expect(result.backup).toBeNull();
  });

  it("treats a lookup failure other than NodeNotFoundError as an error, not a skip", async () => {
    const state = new DazSceneState({ Genesis9: new DazPose("Genesis9", {}, {}, {}) }, {}, {}, {}, {});
    let call = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => {
        call += 1;
        if (call === 1) {
          // findSkeleton lookup: server-side script failure
          return Promise.resolve(
            jsonResponse({ success: false, error: "ReferenceError: boom", output: [], request_id: "r" }),
          );
        }
        return Promise.resolve(
          jsonResponse({ success: true, result: { restored: [], errors: [] }, output: [], request_id: "r", duration_ms: 0 }),
        );
      }),
    );
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await state.apply(scene);
    expect(result.skipped).toEqual([]);
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0]).toMatch(/^Failed to look up skeleton Genesis9: /);
    expect(result.complete).toBe(false);
  });

  it("reports cameras and lights deleted between capture and restore as skipped", async () => {
    const state = new DazSceneState(
      {},
      { CamGone: { XTranslate: 1 }, CamKept: { XTranslate: 2 } },
      { LightGone: { XTranslate: 3 } },
      {},
      {},
    );
    const fetchMock = stubSequence([
      {
        restored: ["CamKept"],
        skipped: [
          { kind: "camera", name: "CamGone", reason: "not_found" },
          { kind: "light", name: "LightGone", reason: "not_found" },
        ],
        errors: ["Camera not found: CamGone", "Light not found: LightGone"],
      },
    ]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await state.apply(scene);

    expect(result.restored).toEqual(["CamKept"]);
    expect(result.skipped).toEqual([
      { kind: "camera", name: "CamGone", reason: "not_found" },
      { kind: "light", name: "LightGone", reason: "not_found" },
    ]);
    expect(result.errors).toEqual(["Camera not found: CamGone", "Light not found: LightGone"]);
    expect(result.complete).toBe(false);

    const script = scriptOf(fetchMock, 0);
    expect(script).toContain('skipped.push({kind: "camera", name: name, reason: "not_found"});');
    expect(script).toContain('skipped.push({kind: "light", name: lname, reason: "not_found"});');
    expect(script).toContain("return {restored: restored, skipped: skipped, errors: errors};");
  });

  it("skips a follow target whose target figure was deleted, keeping the skeleton restored", async () => {
    const pose = new DazPose("Follower", {}, {}, {});
    const state = new DazSceneState({ Follower: pose }, {}, {}, {}, { Follower: "Base" });
    stubSequence([
      true, // findSkeleton("Follower") lookup succeeds
      true, // applyFull
      { bones: {}, morphs: {}, props: {} }, // capture: matches
      null, // skel.followTarget() -> currently unfollowed
      false, // findSkeleton("Base") lookup, attempt 1/3
      false, // attempt 2/3
      false, // attempt 3/3
      [], // hint script: no skeletons
      { restored: [], errors: [] }, // node restore script
    ]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await state.apply(scene);
    expect(result.restored).toEqual(["Follower"]);
    expect(result.skipped).toEqual([{ kind: "follow_target", name: "Follower", reason: "not_found" }]);
    expect(result.errors).toEqual(["Follow-target Base of skeleton Follower not found; fit not restored"]);
    expect(result.complete).toBe(false);
  });

  it("restores a found skeleton whose read-back matches on the first attempt, then restores camera/light transforms", async () => {
    const pose = new DazPose("Genesis9", { hip: [1, 0, 0] }, {}, {});
    const state = new DazSceneState({ Genesis9: pose }, { CameraMain: { XTranslate: 5 } }, {}, {}, { Genesis9: null });
    const fetchMock = stubSequence([
      true, // findSkeleton lookup succeeds
      true, // applyFull
      { bones: { hip: [1, 0, 0] }, morphs: {}, props: {} }, // DazPose.capture verify -- matches
      null, // skel.followTarget() -> already null, matches targetName null -> skip restore
      { restored: ["CameraMain"], errors: [] }, // node restore script
    ]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await state.apply(scene);
    expect(result.restored).toEqual(["Genesis9", "CameraMain"]);
    expect(result.errors).toEqual([]);
    expect(result.skipped).toEqual([]);
    expect(result.complete).toBe(true);
    void fetchMock;
  });

  it("retries applyFull up to maxVerifyRetries when the read-back doesn't verify, then reports an error", async () => {
    const pose = new DazPose("Genesis9", { hip: [10, 0, 0] }, {}, {});
    const state = new DazSceneState({ Genesis9: pose }, {}, {}, {}, {});
    stubSequence([
      true, // findSkeleton lookup succeeds
      true, // applyFull attempt 0
      { bones: { hip: [0, 0, 0] }, morphs: {}, props: {} }, // capture: mismatch
      true, // applyFull attempt 1
      { bones: { hip: [0, 0, 0] }, morphs: {}, props: {} }, // capture: still mismatch (maxVerifyRetries=1 -> stop)
      { restored: [], errors: [] }, // node restore script
    ]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await state.apply(scene, { maxVerifyRetries: 1 });
    expect(result.restored).toEqual([]);
    expect(result.errors).toHaveLength(1);
    expect(result.errors[0]).toContain("did not verify after 2 attempt(s)");
    expect(result.errors[0]).toContain("bone hip");
  });

  it("restores a mismatched follow-target via fitTo when a captured target differs from the current one", async () => {
    const pose = new DazPose("Follower", {}, {}, {});
    const state = new DazSceneState({ Follower: pose }, {}, {}, {}, { Follower: "Base" });
    stubSequence([
      true, // findSkeleton("Follower") lookup succeeds
      true, // applyFull
      { bones: {}, morphs: {}, props: {} }, // capture: matches (empty pose)
      null, // skel.followTarget() -> currently unfollowed
      true, // findSkeleton("Base") lookup succeeds (target not in resolvedSkeletons)
      "setFollowTarget", // skel.fitTo(targetSkel)
      { restored: [], errors: [] }, // node restore script
    ]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await state.apply(scene);
    expect(result.restored).toEqual(["Follower"]);
    expect(result.errors).toEqual([]);
  });
});

describe("DazSceneState.toString", () => {
  it("summarizes skeleton/camera/light counts", () => {
    const state = new DazSceneState(
      { Genesis9: new DazPose("Genesis9", {}, {}, {}) },
      { CameraMain: {} },
      { Spot1: {}, Spot2: {} },
      {},
      {},
    );
    expect(state.toString()).toBe("DazSceneState(skeletons=1, cameras=1, lights=2)");
  });
});

describe("DazSceneState backup", () => {
  function routeFetch(saveCopyResponse: Response) {
    const results: unknown[] = [[], {}, { transforms: {}, extra: {} }]; // skeletons(), cameras, lights
    let i = 0;
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/scene/save-copy")) {
        return Promise.resolve(saveCopyResponse);
      }
      const value = results[Math.min(i, results.length - 1)];
      i += 1;
      return Promise.resolve(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("capture without backupPath does not save a copy", async () => {
    const fetchMock = routeFetch(jsonResponse({ success: true }));
    const state = await DazSceneState.capture(new DazScene(new DazClient({ token: "" })));
    expect(state.backup).toBeNull();
    expect(fetchMock.mock.calls.some(([url]) => (url as string).endsWith("/scene/save-copy"))).toBe(false);
  });

  it("capture with backupPath saves a copy before capturing anything", async () => {
    const saved = { success: true, path: "C:/backups/before.duf", method: "copy" };
    const fetchMock = routeFetch(jsonResponse(saved));
    const state = await DazSceneState.capture(new DazScene(new DazClient({ token: "" })), {
      backupPath: "C:/backups/before.duf",
    });
    expect(state.backup).toEqual(saved);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/scene/save-copy");
    expect(JSON.parse(init.body as string)).toEqual({ path: "C:/backups/before.duf" });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("capture throws and captures nothing if the backup fails", async () => {
    const fetchMock = routeFetch(
      new Response(JSON.stringify({ success: false, error: "disk full" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await expect(
      DazSceneState.capture(new DazScene(new DazClient({ token: "" })), { backupPath: "C:/b.duf" }),
    ).rejects.toBeInstanceOf(DazError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("backup round-trips through toDict/fromDict and is reported by apply", async () => {
    const saved = { success: true, path: "C:/b.duf" };
    const state = new DazSceneState({}, {}, {}, {}, {}, saved);
    const restored = DazSceneState.fromDict(JSON.parse(JSON.stringify(state.toDict())));
    expect(restored.backup).toEqual(saved);

    stubSequence([{ restored: [], errors: [] }]);
    const result = await restored.apply(new DazScene(new DazClient({ token: "" })));
    expect(result.backup).toEqual(saved);
    expect(result.complete).toBe(true);
  });
});
