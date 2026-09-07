import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazScene } from "../../src/scene.js";
import { DazSkeleton } from "../../src/skeleton.js";
import { DazCamera } from "../../src/camera.js";
import { DazLight } from "../../src/light.js";
import { DazNode } from "../../src/node.js";
import { NodeNotFoundError, ScriptRuntimeError } from "../../src/exceptions.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stubSeq(...values: unknown[]) {
  const fetchMock = vi.fn();
  for (const v of values) {
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: v, output: [], request_id: "r", duration_ms: 0 }));
  }
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
function scriptOf(fetchMock: ReturnType<typeof vi.fn>, callIndex = 0): string {
  return JSON.parse(fetchMock.mock.calls[callIndex][1].body as string).script;
}
function iife(body: string): string {
  return `(function(){\n${body}\n})()`;
}

describe("DazScene node/camera/light/skeleton factories", () => {
  it("nodes() classifies each entry using DazScript inherits(), returning typed proxies", async () => {
    const fetchMock = stubSeq([
      { name: "Genesis9", className: "DzSkeleton" },
      { name: "Camera", className: "DzCamera" },
      { name: "Light1", className: "DzLight" },
      { name: "Prop1", className: "DzNode" },
    ]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const nodes = await scene.nodes();
    expect(nodes[0]).toBeInstanceOf(DazSkeleton);
    expect(nodes[1]).toBeInstanceOf(DazCamera);
    expect(nodes[2]).toBeInstanceOf(DazLight);
    expect(nodes[3]).toBeInstanceOf(DazNode);
    expect(nodes[3]).not.toBeInstanceOf(DazSkeleton);
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var result = [];
            for (var i = 0; i < Scene.getNumNodes(); i++) {
                var n = Scene.getNode(i);
                var nodeType = "DzNode";
                if (n.inherits("DzSkeleton")) { nodeType = "DzSkeleton"; }
                else if (n.inherits("DzCamera")) { nodeType = "DzCamera"; }
                else if (n.inherits("DzLight")) { nodeType = "DzLight"; }
                result.push({name: n.getName(), className: nodeType});
            }
            return result;
        `),
    );
  });

  it("nodes() returns [] when the scene has no nodes", async () => {
    stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.nodes()).toEqual([]);
  });

  it("findNode rejects with NodeNotFoundError when Scene.findNode resolves to nothing", async () => {
    const fetchMock = stubSeq(false);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.findNode("Missing")).rejects.toBeInstanceOf(NodeNotFoundError);
    expect(scriptOf(fetchMock)).toBe(iife('return !!Scene.findNode("Missing");'));
  });

  it("findNode returns a name-keyed DazNode when found", async () => {
    const fetchMock = stubSeq(true);
    const scene = new DazScene(new DazClient({ token: "" }));
    const node = await scene.findNode("Prop1");
    expect(node).toBeInstanceOf(DazNode);
    expect(node.identifier).toEqual({ value: "Prop1", kind: "name" });
    expect(scriptOf(fetchMock)).toBe(iife('return !!Scene.findNode("Prop1");'));
  });

  it("findNodeByLabel keeps kind='label' on the returned proxy (does not resolve to internal name)", async () => {
    const fetchMock = stubSeq(true);
    const scene = new DazScene(new DazClient({ token: "" }));
    const node = await scene.findNodeByLabel("My Prop");
    expect(node.identifier).toEqual({ value: "My Prop", kind: "label" });
    expect(scriptOf(fetchMock)).toBe(iife('return !!Scene.findNodeByLabel("My Prop");'));
  });

  it("findNodeByLabel rejects with NodeNotFoundError when not found", async () => {
    stubSeq(false);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.findNodeByLabel("Missing")).rejects.toBeInstanceOf(NodeNotFoundError);
  });

  it("numNodes() generates the exact script and returns the count", async () => {
    const fetchMock = stubSeq(3);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.numNodes()).toBe(3);
    expect(scriptOf(fetchMock)).toBe(iife("return Scene.getNumNodes();"));
  });

  it("numNodes() defaults to 0 when the result is null", async () => {
    stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.numNodes()).toBe(0);
  });

  it("cameras() generates the exact script and returns typed DazCameras", async () => {
    const fetchMock = stubSeq(["Camera", "Camera 2"]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const cams = await scene.cameras();
    expect(cams).toHaveLength(2);
    expect(cams[0]).toBeInstanceOf(DazCamera);
    expect(cams[0].identifier).toEqual({ value: "Camera", kind: "name" });
    expect(scriptOf(fetchMock)).toBe(
      iife(
        "var names = []; for (var i = 0; i < Scene.getNumCameras(); i++) { names.push(Scene.getCamera(i).getName()); } return names;",
      ),
    );
  });

  it("lights() generates the exact script and returns typed DazLights", async () => {
    const fetchMock = stubSeq(["Light1"]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const lights = await scene.lights();
    expect(lights).toHaveLength(1);
    expect(lights[0]).toBeInstanceOf(DazLight);
    expect(scriptOf(fetchMock)).toBe(
      iife(
        "var names = []; for (var i = 0; i < Scene.getNumLights(); i++) { names.push(Scene.getLight(i).getName()); } return names;",
      ),
    );
  });

  it("findCameraByLabel keeps kind='label' and generates the exact existence-check script", async () => {
    const fetchMock = stubSeq(true);
    const scene = new DazScene(new DazClient({ token: "" }));
    const cam = await scene.findCameraByLabel("Camera 1");
    expect(cam.identifier).toEqual({ value: "Camera 1", kind: "label" });
    expect(scriptOf(fetchMock)).toBe(iife('return !!Scene.findCameraByLabel("Camera 1");'));
  });

  it("findCameraByLabel rejects with NodeNotFoundError when not found", async () => {
    stubSeq(false);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.findCameraByLabel("Missing")).rejects.toBeInstanceOf(NodeNotFoundError);
  });

  it("createCamera(name) generates the exact script and returns a name-keyed DazCamera", async () => {
    const fetchMock = stubSeq("MyCam");
    const scene = new DazScene(new DazClient({ token: "" }));
    const cam = await scene.createCamera("MyCam");
    expect(cam.identifier).toEqual({ value: "MyCam", kind: "name" });
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var cam = new DzBasicCamera();
            if ("MyCam" !== null) cam.setName("MyCam");
            Scene.addNode(cam);
            return cam.getName();
        `),
    );
  });

  it("createCamera() with no name uses the null literal for the name expression", async () => {
    const fetchMock = stubSeq("Camera");
    const scene = new DazScene(new DazClient({ token: "" }));
    const cam = await scene.createCamera();
    expect(cam.identifier).toEqual({ value: "Camera", kind: "name" });
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var cam = new DzBasicCamera();
            if (null !== null) cam.setName(null);
            Scene.addNode(cam);
            return cam.getName();
        `),
    );
  });

  it("createLight rejects unknown light types before making any HTTP call", async () => {
    const fetchMock = stubSeq();
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.createLight("halogen" as never)).rejects.toThrow(/Unknown light_type/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("createLight(spot, name) generates the exact script for the mapped DzScript class and returns a name-keyed DazLight", async () => {
    const fetchMock = stubSeq("MySpot");
    const scene = new DazScene(new DazClient({ token: "" }));
    const light = await scene.createLight("spot", "MySpot");
    expect(light).toBeInstanceOf(DazLight);
    expect(light.identifier).toEqual({ value: "MySpot", kind: "name" });
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var light = new DzSpotLight();
            if ("MySpot" !== null) light.setName("MySpot");
            Scene.addNode(light);
            return light.getName();
        `),
    );
  });

  it("createLight maps point/distant to their respective DzScript classes", async () => {
    const fetchMockPoint = stubSeq("Point1");
    const scenePoint = new DazScene(new DazClient({ token: "" }));
    await scenePoint.createLight("point");
    expect(scriptOf(fetchMockPoint)).toBe(
      iife(`
            var light = new DzPointLight();
            if (null !== null) light.setName(null);
            Scene.addNode(light);
            return light.getName();
        `),
    );

    const fetchMockDistant = stubSeq("Distant1");
    const sceneDistant = new DazScene(new DazClient({ token: "" }));
    await sceneDistant.createLight("distant");
    expect(scriptOf(fetchMockDistant)).toBe(
      iife(`
            var light = new DzDistantLight();
            if (null !== null) light.setName(null);
            Scene.addNode(light);
            return light.getName();
        `),
    );
  });

  it("findLightByLabel keeps kind='label' and generates the exact existence-check script", async () => {
    const fetchMock = stubSeq(true);
    const scene = new DazScene(new DazClient({ token: "" }));
    const light = await scene.findLightByLabel("Distant Light 1");
    expect(light.identifier).toEqual({ value: "Distant Light 1", kind: "label" });
    expect(scriptOf(fetchMock)).toBe(iife('return !!Scene.findLightByLabel("Distant Light 1");'));
  });

  it("findLightByLabel rejects with NodeNotFoundError when not found", async () => {
    stubSeq(false);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.findLightByLabel("Missing")).rejects.toBeInstanceOf(NodeNotFoundError);
  });

  it("skeletons() generates the exact script and returns typed DazSkeletons", async () => {
    const fetchMock = stubSeq(["Genesis9"]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const skels = await scene.skeletons();
    expect(skels).toHaveLength(1);
    expect(skels[0]).toBeInstanceOf(DazSkeleton);
    expect(scriptOf(fetchMock)).toBe(
      iife(
        "var names = []; var skels = Scene.getSkeletonList(); for (var i = 0; i < skels.length; i++) { names.push(skels[i].getName()); } return names;",
      ),
    );
  });

  it("findSkeleton succeeds on the first attempt without retrying or calling the hint script", async () => {
    const fetchMock = stubSeq(true);
    const scene = new DazScene(new DazClient({ token: "" }));
    const skel = await scene.findSkeleton("Genesis9", { retryAttempts: 3, retryDelay: 0 });
    expect(skel.identifier).toEqual({ value: "Genesis9", kind: "name" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var skels = Scene.getSkeletonList();
            for (var i = 0; i < skels.length; i++) {
                if (skels[i].getName() === "Genesis9") return true;
            }
            return false;
        `),
    );
  });

  it("findSkeleton retries getSkeletonList() up to retryAttempts times before raising NodeNotFoundError", async () => {
    const fetchMock = stubSeq(false, false, false, []);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.findSkeleton("Ghost", { retryAttempts: 3, retryDelay: 0 })).rejects.toBeInstanceOf(NodeNotFoundError);
    expect(fetchMock).toHaveBeenCalledTimes(4); // 3 lookup attempts + 1 hint call
    const lookupScript = iife(`
            var skels = Scene.getSkeletonList();
            for (var i = 0; i < skels.length; i++) {
                if (skels[i].getName() === "Ghost") return true;
            }
            return false;
        `);
    expect(scriptOf(fetchMock, 0)).toBe(lookupScript);
    expect(scriptOf(fetchMock, 1)).toBe(lookupScript);
    expect(scriptOf(fetchMock, 2)).toBe(lookupScript);
    expect(scriptOf(fetchMock, 3)).toBe(
      iife(`
                var info = [];
                var skels = Scene.getSkeletonList();
                for (var i = 0; i < skels.length; i++) {
                    info.push(skels[i].getName() + "|" + skels[i].getLabel());
                }
                return info;
            `),
    );
  });

  it("findSkeleton includes available skeletons (name + label) in the error message when the scene has skeletons", async () => {
    stubSeq(false, false, false, ["Genesis9|Genesis 9", "Genesis9|Genesis 9 (Twin)"]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.findSkeleton("Ghost", { retryAttempts: 3, retryDelay: 0 })).rejects.toThrow(
      'Skeleton not found: "Ghost". Available skeletons: "Genesis9" (label: "Genesis 9"), "Genesis9" (label: "Genesis 9 (Twin)"). Tip: use findSkeletonByLabel() to search by the Scene-panel label.',
    );
  });

  it("findSkeleton reports 'no skeletons in scene' when the hint call also returns empty", async () => {
    stubSeq(false, false, false, []);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.findSkeleton("Ghost", { retryAttempts: 3, retryDelay: 0 })).rejects.toThrow(
      'Skeleton not found: "Ghost" (no skeletons in scene).',
    );
  });

  it("findSkeleton defaults to retryAttempts=3 and retryDelay=0.15 when opts is omitted", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = stubSeq(false, false, true);
      const scene = new DazScene(new DazClient({ token: "" }));
      const promise = scene.findSkeleton("Genesis9");
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(150); // sleep(0.15 * 1)
      await vi.advanceTimersByTimeAsync(300); // sleep(0.15 * 2)
      const skel = await promise;
      expect(skel.identifier).toEqual({ value: "Genesis9", kind: "name" });
      expect(fetchMock).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("findSkeletonByLabel keeps kind='label' so same-named figures stay distinct", async () => {
    const fetchMock = stubSeq(true);
    const scene = new DazScene(new DazClient({ token: "" }));
    const skel = await scene.findSkeletonByLabel("Genesis 9");
    expect(skel.identifier).toEqual({ value: "Genesis 9", kind: "label" });
    expect(scriptOf(fetchMock)).toBe(iife('return !!Scene.findSkeletonByLabel("Genesis 9");'));
  });

  it("findSkeletonByLabel rejects with NodeNotFoundError when not found", async () => {
    stubSeq(false);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.findSkeletonByLabel("Missing")).rejects.toBeInstanceOf(NodeNotFoundError);
  });

  it("numSkeletons() generates the exact script and returns the count", async () => {
    const fetchMock = stubSeq(2);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.numSkeletons()).toBe(2);
    expect(scriptOf(fetchMock)).toBe(iife("return Scene.getNumSkeletons();"));
  });

  it("selectedNodes() generates the exact script and returns name-keyed DazNodes", async () => {
    const fetchMock = stubSeq(["Prop1", "Prop2"]);
    const scene = new DazScene(new DazClient({ token: "" }));
    const nodes = await scene.selectedNodes();
    expect(nodes).toHaveLength(2);
    expect(nodes[0]).toBeInstanceOf(DazNode);
    expect(nodes[0].identifier).toEqual({ value: "Prop1", kind: "name" });
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var nodes = Scene.getSelectedNodeList();
            var names = [];
            for (var i = 0; i < nodes.length; i++) {
                names.push(nodes[i].getName());
            }
            return names;
        `),
    );
  });

  it("primarySelection returns null when nothing is selected", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.primarySelection()).toBeNull();
    expect(scriptOf(fetchMock)).toBe(iife("var n = Scene.getPrimarySelection(); return n ? n.getName() : null;"));
  });

  it("primarySelection returns a name-keyed DazNode when something is selected", async () => {
    stubSeq("Genesis9");
    const scene = new DazScene(new DazClient({ token: "" }));
    const node = await scene.primarySelection();
    expect(node).toBeInstanceOf(DazNode);
    expect(node?.identifier).toEqual({ value: "Genesis9", kind: "name" });
  });

  it("setPrimarySelection(node) resolves the node via findNodeExpr and generates the exact script", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    const node = new DazNode(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await scene.setPrimarySelection(node);
    expect(scriptOf(fetchMock)).toBe(iife('Scene.setPrimarySelection(Scene.findNode("Genesis9"));'));
  });

  it("setPrimarySelection(node) uses findNodeByLabel when the node's identifier kind is 'label'", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    const node = new DazNode(new DazClient({ token: "" }), { value: "My Prop", kind: "label" });
    await scene.setPrimarySelection(node);
    expect(scriptOf(fetchMock)).toBe(iife('Scene.setPrimarySelection(Scene.findNodeByLabel("My Prop"));'));
  });

  it("selectAll() defaults to true and generates the exact script", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.selectAll();
    expect(scriptOf(fetchMock)).toBe(iife("Scene.selectAllNodes(true);"));
  });

  it("selectAll(false) generates the exact script", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.selectAll(false);
    expect(scriptOf(fetchMock)).toBe(iife("Scene.selectAllNodes(false);"));
  });
});

describe("DazScene bulk snapshots", () => {
  it("sceneSnapshot passes a JSON null filter when skeletonLabels is omitted", async () => {
    const fetchMock = stubSeq([]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.sceneSnapshot();
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var _filter = null;
            var _skels = Scene.getSkeletonList();
            var _result = [];
            for (var _s = 0; _s < _skels.length; _s++) {
                var _skel = _skels[_s];
                if (_filter !== null) {
                    var _found = false;
                    for (var _f = 0; _f < _filter.length; _f++) {
                        if (_filter[_f] === _skel.getName() || _filter[_f] === _skel.getLabel()) {
                            _found = true; break;
                        }
                    }
                    if (!_found) continue;
                }
                var _bones = _skel.getAllBones();
                var _boneList = [];
                for (var _i = 0; _i < _bones.length; _i++) {
                    var _b = _bones[_i];
                    var _parent = _b.getNodeParent();
                    var _parentName = null;
                    if (_parent && _parent.className && _parent.className() === "DzBone") {
                        _parentName = _parent.getName();
                    }
                    var _lpos = _b.getLocalPos();
                    var _wpos = _b.getWSPos();
                    _boneList.push({
                        name: _b.getName(),
                        label: _b.getLabel(),
                        parent_name: _parentName,
                        rotation_order: _b.getRotationOrder(),
                        local_position: {x: _lpos.x, y: _lpos.y, z: _lpos.z},
                        world_position: {x: _wpos.x, y: _wpos.y, z: _wpos.z},
                        local_euler: {
                            x: _b.getXRotControl().getValue(),
                            y: _b.getYRotControl().getValue(),
                            z: _b.getZRotControl().getValue()
                        }
                    });
                }
                _result.push({
                    name: _skel.getName(),
                    label: _skel.getLabel(),
                    bones: _boneList
                });
            }
            return _result;
        `),
    );
  });

  it("sceneSnapshot passes the label/name filter as a JSON array when provided", async () => {
    const fetchMock = stubSeq([]);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.sceneSnapshot(["Genesis 9"]);
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var _filter = ["Genesis 9"];
            var _skels = Scene.getSkeletonList();
            var _result = [];
            for (var _s = 0; _s < _skels.length; _s++) {
                var _skel = _skels[_s];
                if (_filter !== null) {
                    var _found = false;
                    for (var _f = 0; _f < _filter.length; _f++) {
                        if (_filter[_f] === _skel.getName() || _filter[_f] === _skel.getLabel()) {
                            _found = true; break;
                        }
                    }
                    if (!_found) continue;
                }
                var _bones = _skel.getAllBones();
                var _boneList = [];
                for (var _i = 0; _i < _bones.length; _i++) {
                    var _b = _bones[_i];
                    var _parent = _b.getNodeParent();
                    var _parentName = null;
                    if (_parent && _parent.className && _parent.className() === "DzBone") {
                        _parentName = _parent.getName();
                    }
                    var _lpos = _b.getLocalPos();
                    var _wpos = _b.getWSPos();
                    _boneList.push({
                        name: _b.getName(),
                        label: _b.getLabel(),
                        parent_name: _parentName,
                        rotation_order: _b.getRotationOrder(),
                        local_position: {x: _lpos.x, y: _lpos.y, z: _lpos.z},
                        world_position: {x: _wpos.x, y: _wpos.y, z: _wpos.z},
                        local_euler: {
                            x: _b.getXRotControl().getValue(),
                            y: _b.getYRotControl().getValue(),
                            z: _b.getZRotControl().getValue()
                        }
                    });
                }
                _result.push({
                    name: _skel.getName(),
                    label: _skel.getLabel(),
                    bones: _boneList
                });
            }
            return _result;
        `),
    );
  });

  it("nodeHierarchy raises NodeNotFoundError when the root cannot be found", async () => {
    stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.nodeHierarchy({ root: "Ghost" })).rejects.toBeInstanceOf(NodeNotFoundError);
  });

  it("nodeHierarchy maps total_descendants to totalDescendants", async () => {
    stubSeq({ node: "Genesis 9", hierarchy: { label: "Genesis 9", name: "Genesis9", type: "DzFigure" }, total_descendants: 5 });
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await scene.nodeHierarchy({ root: "Genesis 9", maxDepth: 2 });
    expect(result.totalDescendants).toBe(5);
  });

  it("overview() falls back to an empty-scene default when the server returns null", async () => {
    stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await scene.overview();
    expect(result).toEqual({ scene_file: "", selected_node: null, figures: [], cameras: [], lights: [], total_nodes: 0 });
  });
});

describe("DazScene I/O, playback, undo, dForce", () => {
  it("load() calls Scene.loadScene(path, 0) in merge mode", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.load("C:/scene.duf");
    expect(scriptOf(fetchMock)).toBe(iife('Scene.loadScene("C:/scene.duf", 0);'));
  });

  it("save() calls Scene.saveScene(path)", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.save("C:/scene.duf");
    expect(scriptOf(fetchMock)).toBe(iife('Scene.saveScene("C:/scene.duf");'));
  });

  it("saveCopy() delegates to DazClient.sceneSaveCopy via POST /scene/save-copy", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ ok: true, path: "C:/copy.duf", source: "copy", method: "copy" }));
    vi.stubGlobal("fetch", fetchMock);
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await scene.saveCopy("C:/copy.duf");
    expect(result).toEqual({ ok: true, path: "C:/copy.duf", source: "copy", method: "copy" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/scene/save-copy");
    expect(JSON.parse(init.body as string)).toEqual({ path: "C:/copy.duf" });
  });

  it("exportFbx() with defaults sets the documented default option overrides on DzFbxExporter", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.exportFbx("C:/out.fbx");
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var mgr = App.getExportMgr();
            var exp = mgr.findExporterByClassName("DzFbxExporter");
            if (!exp) return;
            var settings = new DzFileIOSettings();
            exp.getDefaultOptions(settings);
            settings.setBoolValue("IncludeSelectedOnly", false); settings.setBoolValue("IncludeFigures", true); settings.setBoolValue("IncludeProps", false); settings.setBoolValue("IncludeLights", false); settings.setBoolValue("IncludeCameras", false); settings.setBoolValue("IncludeAnimations", false); settings.setBoolValue("EmbedTextures", true); settings.setIntValue("RunSilent", 1);
            exp.writeFile("C:/out.fbx", settings);
        `),
    );
  });

  it("exportFbx() applies opts overrides (selectedOnly, includeProps) and additional raw options", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.exportFbx("C:/out.fbx", { selectedOnly: true, includeProps: true, options: { CustomFlag: 2.5 } });
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var mgr = App.getExportMgr();
            var exp = mgr.findExporterByClassName("DzFbxExporter");
            if (!exp) return;
            var settings = new DzFileIOSettings();
            exp.getDefaultOptions(settings);
            settings.setBoolValue("IncludeSelectedOnly", true); settings.setBoolValue("IncludeFigures", true); settings.setBoolValue("IncludeProps", true); settings.setBoolValue("IncludeLights", false); settings.setBoolValue("IncludeCameras", false); settings.setBoolValue("IncludeAnimations", false); settings.setBoolValue("EmbedTextures", true); settings.setFloatValue("CustomFlag", 2.5); settings.setIntValue("RunSilent", 1);
            exp.writeFile("C:/out.fbx", settings);
        `),
    );
  });

  it("exportObj() with defaults sets the documented default option overrides on DzObjExporter", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.exportObj("C:/out.obj");
    expect(scriptOf(fetchMock)).toBe(
      iife(`
            var mgr = App.getExportMgr();
            var exp = mgr.findExporterByClassName("DzObjExporter");
            if (!exp) return;
            var settings = new DzFileIOSettings();
            exp.getDefaultOptions(settings);
            settings.setBoolValue("SelectedOnly", false); settings.setBoolValue("IgnoreInvisible", true); settings.setBoolValue("WriteVN", false); settings.setBoolValue("CollectMaps", false); settings.setIntValue("RunSilent", 1);
            exp.writeFile("C:/out.obj", settings);
        `),
    );
  });

  it("filename() returns Scene.getFilename(), or '' when the server returns null", async () => {
    stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.filename()).toBe("");
  });

  it("filename() script and return value", async () => {
    const fetchMock = stubSeq("C:/scene.duf");
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.filename()).toBe("C:/scene.duf");
    expect(scriptOf(fetchMock)).toBe(iife("return Scene.getFilename();"));
  });

  it("needsSave() calls Scene.needsSave()", async () => {
    const fetchMock = stubSeq(true);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.needsSave()).toBe(true);
    expect(scriptOf(fetchMock)).toBe(iife("return Scene.needsSave();"));
  });

  it("playRange() converts DzTimeRange ticks to frames via getTimeStep()", async () => {
    const fetchMock = stubSeq({ start: 0, end: 90 });
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.playRange()).toEqual({ start: 0, end: 90 });
    expect(scriptOf(fetchMock)).toBe(
      iife(
        "var r = Scene.getPlayRange(); var step = Scene.getTimeStep(); return {start: Math.round(r.start / step), end: Math.round(r.end / step)};",
      ),
    );
  });

  it("playRange() falls back to {start: 0, end: 0} when the server returns null", async () => {
    stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.playRange()).toEqual({ start: 0, end: 0 });
  });

  it("setPlayRange multiplies frame numbers by Scene.getTimeStep()", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.setPlayRange(0, 30);
    expect(scriptOf(fetchMock)).toBe(
      iife("var step = Scene.getTimeStep();Scene.setPlayRange(new DzTimeRange(0 * step, 30 * step));"),
    );
  });

  it("setPlayRange truncates non-integer frame numbers", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.setPlayRange(1.9, 30.4);
    expect(scriptOf(fetchMock)).toBe(
      iife("var step = Scene.getTimeStep();Scene.setPlayRange(new DzTimeRange(1 * step, 30 * step));"),
    );
  });

  it("animRange() converts DzTimeRange ticks to frames via getTimeStep()", async () => {
    const fetchMock = stubSeq({ start: 0, end: 100 });
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.animRange()).toEqual({ start: 0, end: 100 });
    expect(scriptOf(fetchMock)).toBe(
      iife(
        "var r = Scene.getAnimRange(); var step = Scene.getTimeStep(); return {start: Math.round(r.start / step), end: Math.round(r.end / step)};",
      ),
    );
  });

  it("animRange() falls back to {start: 0, end: 0} when the server returns null", async () => {
    stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.animRange()).toEqual({ start: 0, end: 0 });
  });

  it("setAnimRange multiplies frame numbers by Scene.getTimeStep()", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.setAnimRange(10, 200);
    expect(scriptOf(fetchMock)).toBe(
      iife("var step = Scene.getTimeStep();Scene.setAnimRange(new DzTimeRange(10 * step, 200 * step));"),
    );
  });

  it("isPlaying() calls Scene.isPlaying()", async () => {
    const fetchMock = stubSeq(true);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.isPlaying()).toBe(true);
    expect(scriptOf(fetchMock)).toBe(iife("return Scene.isPlaying();"));
  });

  it("loopPlayback(true) calls Scene.loopPlayback(true)", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.loopPlayback(true);
    expect(scriptOf(fetchMock)).toBe(iife("Scene.loopPlayback(true);"));
  });

  it("loopPlayback(false) calls Scene.loopPlayback(false)", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.loopPlayback(false);
    expect(scriptOf(fetchMock)).toBe(iife("Scene.loopPlayback(false);"));
  });

  it("undoLast() calls App.getUndoStack().undo()", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.undoLast();
    expect(scriptOf(fetchMock)).toBe(iife("App.getUndoStack().undo();"));
  });

  it("redoLast() calls App.getUndoStack().redo()", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.redoLast();
    expect(scriptOf(fetchMock)).toBe(iife("App.getUndoStack().redo();"));
  });

  it("isSimulating() calls App.getSimulationMgr().isSimulating()", async () => {
    const fetchMock = stubSeq(true);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.isSimulating()).toBe(true);
    expect(scriptOf(fetchMock)).toBe(iife("return App.getSimulationMgr().isSimulating();"));
  });

  it("clearDforceSimulation() calls App.getSimulationMgr().clearSimulation()", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.clearDforceSimulation();
    expect(scriptOf(fetchMock)).toBe(iife("App.getSimulationMgr().clearSimulation();"));
  });

  it("frame() calls Scene.getFrame(), falling back to 0 when the server returns null", async () => {
    stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.frame()).toBe(0);
  });

  it("frame() script and return value", async () => {
    const fetchMock = stubSeq(12);
    const scene = new DazScene(new DazClient({ token: "" }));
    expect(await scene.frame()).toBe(12);
    expect(scriptOf(fetchMock)).toBe(iife("return Scene.getFrame();"));
  });

  it("setFrame() calls Scene.setFrame() with a truncated integer", async () => {
    const fetchMock = stubSeq(null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await scene.setFrame(24.7);
    expect(scriptOf(fetchMock)).toBe(iife("Scene.setFrame(24);"));
  });

  it("undo() delegates to withUndo, committing on success", async () => {
    const fetchMock = stubSeq(null, null);
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await scene.undo("Move figure", async () => "done");
    expect(result).toBe("done");
    expect(scriptOf(fetchMock, 0)).toBe(iife("beginUndo();"));
    expect(scriptOf(fetchMock, 1)).toBe(iife('acceptUndo("Move figure");'));
  });

  it("undo() cancels and rethrows when fn throws", async () => {
    const fetchMock = stubSeq(null, null);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(
      scene.undo("x", async () => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
    expect(scriptOf(fetchMock, 0)).toBe(iife("beginUndo();"));
    expect(scriptOf(fetchMock, 1)).toBe(iife("cancelUndo();"));
  });

  it("runDforceSimulation() with no nodes calls DzSimulationMgr.simulate() and resolves null on success", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse({ request_id: "job-1" }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: "completed", success: true, result: { error: null }, output: [], duration_ms: 0 }));
    vi.stubGlobal("fetch", fetchMock);
    const scene = new DazScene(new DazClient({ token: "" }));
    const result = await scene.runDforceSimulation();
    expect(result).toBeNull();
    const submitScript = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(submitScript).toBe(
      iife(`
                var mgr = App.getSimulationMgr();
                var err = mgr.simulate();
                return {"error": err ? String(err) : null};
            `),
    );
  });

  it("runDforceSimulation(nodes) calls customSimulate() on the active engine with the resolved node expressions", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse({ request_id: "job-2" }));
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: "completed", success: true, result: { error: null }, output: [], duration_ms: 0 }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new DazClient({ token: "" });
    const scene = new DazScene(client);
    const node1 = new DazNode(client, { value: "Genesis9", kind: "name" });
    const node2 = new DazNode(client, { value: "Genesis9 2", kind: "label" });
    const result = await scene.runDforceSimulation([node1, node2]);
    expect(result).toBeNull();
    const submitScript = JSON.parse(fetchMock.mock.calls[0][1].body as string).script;
    expect(submitScript).toBe(
      iife(`
                var mgr = App.getSimulationMgr();
                var engine = mgr.getActiveSimulationEngine();
                if (!engine) return {"error": "no_active_engine"};
                var err = engine.customSimulate([Scene.findNode("Genesis9"),Scene.findNodeByLabel("Genesis9 2")]);
                return {"error": err ? String(err) : null};
            `),
    );
  });

  it("runDforceSimulation() throws ScriptRuntimeError when the simulation engine reports an error", async () => {
    const fetchMock = vi.fn();
    fetchMock.mockResolvedValueOnce(jsonResponse({ request_id: "job-3" }));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ status: "completed", success: true, result: { error: "cloth collision failure" }, output: [], duration_ms: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const scene = new DazScene(new DazClient({ token: "" }));
    await expect(scene.runDforceSimulation()).rejects.toThrow(ScriptRuntimeError);
  });

  it("runDforceSimulation(wait: false) submits async and returns the requestId without polling", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ request_id: "job-4" }));
    vi.stubGlobal("fetch", fetchMock);
    const scene = new DazScene(new DazClient({ token: "" }));
    const requestId = await scene.runDforceSimulation(undefined, { wait: false });
    expect(requestId).toBe("job-4");
    expect(fetchMock.mock.calls.length).toBe(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:18811/execute/async");
    const submitScript = JSON.parse(init.body as string).script;
    expect(submitScript).toBe(
      iife(`
                var mgr = App.getSimulationMgr();
                var err = mgr.simulate();
                return {"error": err ? String(err) : null};
            `),
    );
  });
});
