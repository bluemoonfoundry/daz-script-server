import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazSkeleton } from "../../src/skeleton.js";
import { DazBone } from "../../src/bone.js";
import { NodeNotFoundError } from "../../src/exceptions.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stub(value: unknown) {
  const fetchMock = vi
    .fn()
    .mockImplementation(() =>
      Promise.resolve(jsonResponse({ success: true, result: value, output: [], request_id: "r", duration_ms: 0 })),
    );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
function scriptOf(fetchMock: ReturnType<typeof vi.fn>, callIndex = 0): string {
  return JSON.parse(fetchMock.mock.calls[callIndex][1].body as string).script;
}

const skeletonLookupAsNode =
  'var _node=null,_skels=Scene.getSkeletonList();for(var _i=0;_i<_skels.length;_i++){if(_skels[_i].getName() === "Genesis9"){_node=_skels[_i];break;}}';
const skeletonLookup =
  'var _skel=null,_skels=Scene.getSkeletonList();for(var _i=0;_i<_skels.length;_i++){if(_skels[_i].getName() === "Genesis9"){_skel=_skels[_i];break;}}';

function skeletonScript(body: string): string {
  return `(function(){\n${skeletonLookupAsNode}\nif (!_node) return null;\n${body}\n})()`;
}

function boneLocator(boneName: string): string {
  return `(function(){${skeletonLookup}return _skel?_skel.findBone(${JSON.stringify(boneName)}):null;})()`;
}

describe("DazSkeleton bone lookup", () => {
  it("bones() looks up the skeleton via getSkeletonList(), not Scene.findNode(), and returns typed DazBones", async () => {
    const fetchMock = stub(["hip", "chest"]);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const bones = await skel.bones();
    expect(bones).toHaveLength(2);
    expect(bones[0]).toBeInstanceOf(DazBone);
    expect(bones[1]).toBeInstanceOf(DazBone);
    expect(scriptOf(fetchMock)).toBe(
      skeletonScript(
        "var bones = _node.getAllBones(); var names = []; for (var i = 0; i < bones.length; i++) { names.push(bones[i].getName()); } return names;",
      ),
    );
  });

  it("bones() returns [] when the skeleton lookup returns null", async () => {
    const fetchMock = stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const bones = await skel.bones();
    expect(bones).toEqual([]);
    void fetchMock;
  });

  it("boneMetadata() generates the exact bulk-metadata script and returns the raw result array", async () => {
    const metadata = [{ name: "hip", label: "Hip" }];
    const fetchMock = stub(metadata);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const result = await skel.boneMetadata();
    expect(result).toEqual(metadata);
    expect(scriptOf(fetchMock)).toBe(
      skeletonScript(`
            var bones = _node.getAllBones();
            var result = [];
            for (var i = 0; i < bones.length; i++) {
                var b = bones[i];
                var parent = b.getNodeParent();
                var parent_name = null;
                if (parent && parent.className && parent.className() === "DzBone") {
                    parent_name = parent.getName();
                }
                var pos = b.getLocalPos();
                var wpos = b.getWSPos();
                result.push({
                    name: b.getName(),
                    label: b.getLabel(),
                    parent_name: parent_name,
                    rotation_order: b.getRotationOrder(),
                    local_position: {x: pos.x, y: pos.y, z: pos.z},
                    world_position: {x: wpos.x, y: wpos.y, z: wpos.z},
                    local_euler: {
                        x: b.getXRotControl().getValue(),
                        y: b.getYRotControl().getValue(),
                        z: b.getZRotControl().getValue()
                    }
                });
            }
            return result;
        `),
    );
  });

  it("boneMetadata() returns [] when the script result is null", async () => {
    stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await skel.boneMetadata()).toEqual([]);
  });

  it("findBone resolves a matching bone name to a typed DazBone bound through this skeleton", async () => {
    const fetchMock = stub("l_forearm");
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const bone = await skel.findBone("l_forearm");
    expect(bone).toBeInstanceOf(DazBone);
    expect(scriptOf(fetchMock)).toBe(
      skeletonScript('var b = _node.findBone("l_forearm"); return b ? b.getName() : null;'),
    );
  });

  it("findBone rejects with NodeNotFoundError including a naming-convention hint", async () => {
    stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await expect(skel.findBone("bogus")).rejects.toBeInstanceOf(NodeNotFoundError);
    await expect(skel.findBone("bogus")).rejects.toThrow(
      'Bone not found: "bogus". Bone naming differs by figure generation — e.g. Genesis 9 uses \'r_forearm\', Genesis 3/8 uses \'rForearmBend\', Genesis 1/2 uses \'rForeArm\'. Call figure.bones() to list every bone name for this figure.',
    );
  });

  it("findBoneByLabel resolves a matching bone label to a typed DazBone", async () => {
    const fetchMock = stub("l_forearm");
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const bone = await skel.findBoneByLabel("Left Forearm");
    expect(bone).toBeInstanceOf(DazBone);
    expect(scriptOf(fetchMock)).toBe(
      skeletonScript('var b = _node.findBoneByLabel("Left Forearm"); return b ? b.getName() : null;'),
    );
  });

  it("findBoneByLabel rejects with NodeNotFoundError when no bone matches the label", async () => {
    stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await expect(skel.findBoneByLabel("Nonexistent")).rejects.toBeInstanceOf(NodeNotFoundError);
    await expect(skel.findBoneByLabel("Nonexistent")).rejects.toThrow('Bone with label not found: "Nonexistent"');
  });

  it("numBones() generates the exact count script and defaults to 0", async () => {
    const fetchMock = stub(42);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await skel.numBones()).toBe(42);
    expect(scriptOf(fetchMock)).toBe(skeletonScript("return _node.getAllBones().length;"));

    stub(null);
    expect(await skel.numBones()).toBe(0);
  });
});

describe("DazSkeleton bulk bone state", () => {
  it("boneRotations() generates the exact script and normalizes results to 3-tuples", async () => {
    const fetchMock = stub({ hip: [1, 2, 3, 99] });
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const result = await skel.boneRotations();
    expect(result).toEqual({ hip: [1, 2, 3] });
    expect(scriptOf(fetchMock)).toBe(
      skeletonScript(`
            var _bones = _node.getAllBones();
            var _result = {};
            for (var i = 0; i < _bones.length; i++) {
                var _b = _bones[i];
                _result[_b.getName()] = [
                    _b.getXRotControl().getValue(),
                    _b.getYRotControl().getValue(),
                    _b.getZRotControl().getValue()
                ];
            }
            return _result;
        `),
    );
  });

  it("boneRotations() defaults to {} when the script result is null", async () => {
    stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await skel.boneRotations()).toEqual({});
  });

  it("boneRotationsQuat() generates the exact script", async () => {
    const quatResult = { hip: { x: 0, y: 0, z: 0, w: 1 } };
    const fetchMock = stub(quatResult);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await skel.boneRotationsQuat()).toEqual(quatResult);
    expect(scriptOf(fetchMock)).toBe(
      skeletonScript(`
            var _bones = _node.getAllBones();
            var _result = {};
            for (var i = 0; i < _bones.length; i++) {
                var _b = _bones[i];
                var _r = _b.getLocalRot();
                _result[_b.getName()] = {x: _r.x, y: _r.y, z: _r.z, w: _r.w};
            }
            return _result;
        `),
    );
  });

  it("boneRotationsQuat() defaults to {} when the script result is null", async () => {
    stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await skel.boneRotationsQuat()).toEqual({});
  });

  it("setBoneRotations writes only the named bones' rotation controls", async () => {
    const fetchMock = stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await skel.setBoneRotations({ r_forearm: [10, 0, 0] });
    expect(scriptOf(fetchMock)).toBe(
      skeletonScript(`
            var _data = {"r_forearm":[10,0,0]};
            var _bones = _node.getAllBones();
            for (var i = 0; i < _bones.length; i++) {
                var _b = _bones[i];
                var _n = _b.getName();
                if (_data.hasOwnProperty(_n)) {
                    var _r = _data[_n];
                    _b.getXRotControl().setValue(_r[0]);
                    _b.getYRotControl().setValue(_r[1]);
                    _b.getZRotControl().setValue(_r[2]);
                }
            }
        `),
    );
  });

  it("setState with all three opts generates the exact combined script", async () => {
    const fetchMock = stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await skel.setState({
      bones: { hip: [1, 2, 3] },
      morphs: { SmileFull: 0.5 },
      props: { Visible: true },
    });
    const boneLines = `
                var _bonesData = {"hip":[1,2,3]};
                var _allBones = _node.getAllBones();
                for (var i = 0; i < _allBones.length; i++) {
                    var _b = _allBones[i];
                    var _bn = _b.getName();
                    if (_bonesData.hasOwnProperty(_bn)) {
                        var _r = _bonesData[_bn];
                        _b.getXRotControl().setValue(_r[0]);
                        _b.getYRotControl().setValue(_r[1]);
                        _b.getZRotControl().setValue(_r[2]);
                    }
                }
            `;
    const morphLines = `
                var _morphsData = {"SmileFull":0.5};
                var _obj = _node.getObject();
                if (_obj) {
                    for (var j = 0; j < _obj.getNumModifiers(); j++) {
                        var _m = _obj.getModifier(j);
                        if (_m.className() === "DzMorph" && _morphsData.hasOwnProperty(_m.getName())) {
                            _m.getValueChannel().setValue(_morphsData[_m.getName()]);
                        }
                    }
                }
            `;
    const propLines = `
                var _propsData = {"Visible":true};
                for (var k = 0; k < _node.getNumProperties(); k++) {
                    var _p = _node.getProperty(k);
                    var _pl = _p.getLabel();
                    if (_propsData.hasOwnProperty(_pl)) {
                        _p.setValue(_propsData[_pl]);
                    }
                }
            `;
    expect(scriptOf(fetchMock)).toBe(skeletonScript([boneLines, morphLines, propLines].join("\n")));
  });

  it("setState with no opts makes no HTTP call", async () => {
    const fetchMock = stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await skel.setState({});
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("setState with only bones generates only the bones block", async () => {
    const fetchMock = stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await skel.setState({ bones: { hip: [1, 2, 3] } });
    const boneLines = `
                var _bonesData = {"hip":[1,2,3]};
                var _allBones = _node.getAllBones();
                for (var i = 0; i < _allBones.length; i++) {
                    var _b = _allBones[i];
                    var _bn = _b.getName();
                    if (_bonesData.hasOwnProperty(_bn)) {
                        var _r = _bonesData[_bn];
                        _b.getXRotControl().setValue(_r[0]);
                        _b.getYRotControl().setValue(_r[1]);
                        _b.getZRotControl().setValue(_r[2]);
                    }
                }
            `;
    expect(scriptOf(fetchMock)).toBe(skeletonScript(boneLines));
  });
});

describe("DazSkeleton bulk morph state", () => {
  it("morphValues(false) generates the exact script with _nz = false", async () => {
    const fetchMock = stub({ SmileFull: 0.8, Frown: 0 });
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const result = await skel.morphValues();
    expect(result).toEqual({ SmileFull: 0.8, Frown: 0 });
    expect(scriptOf(fetchMock)).toBe(
      skeletonScript(`
            var _obj = _node.getObject();
            if (!_obj) return {};
            var _result = {};
            var _nz = false;
            for (var i = 0; i < _obj.getNumModifiers(); i++) {
                var _m = _obj.getModifier(i);
                if (_m.className() === "DzMorph") {
                    var _v = _m.getValueChannel().getValue();
                    if (!_nz || Math.abs(_v) > 0.0001) {
                        _result[_m.getName()] = _v;
                    }
                }
            }
            return _result;
        `),
    );
  });

  it("morphValues(true) filters to |value| > 0.0001 via the _nz flag", async () => {
    const fetchMock = stub({ SmileFull: 0.8 });
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await skel.morphValues(true);
    expect(scriptOf(fetchMock)).toBe(
      skeletonScript(`
            var _obj = _node.getObject();
            if (!_obj) return {};
            var _result = {};
            var _nz = true;
            for (var i = 0; i < _obj.getNumModifiers(); i++) {
                var _m = _obj.getModifier(i);
                if (_m.className() === "DzMorph") {
                    var _v = _m.getValueChannel().getValue();
                    if (!_nz || Math.abs(_v) > 0.0001) {
                        _result[_m.getName()] = _v;
                    }
                }
            }
            return _result;
        `),
    );
  });

  it("morphValues() defaults to {} when the script result is null", async () => {
    stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await skel.morphValues()).toEqual({});
  });

  it("setMorphValues writes only the named morphs' value channels", async () => {
    const fetchMock = stub(null);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await skel.setMorphValues({ SmileFull: 0.9 });
    expect(scriptOf(fetchMock)).toBe(
      skeletonScript(`
            var _data = {"SmileFull":0.9};
            var _obj = _node.getObject();
            if (!_obj) return null;
            for (var i = 0; i < _obj.getNumModifiers(); i++) {
                var _m = _obj.getModifier(i);
                if (_m.className() === "DzMorph" && _data.hasOwnProperty(_m.getName())) {
                    _m.getValueChannel().setValue(_data[_m.getName()]);
                }
            }
        `),
    );
  });
});

describe("DazSkeleton bone locator disambiguates same-named figures", () => {
  it("bones() binds each returned DazBone to a locator scoped to this skeleton's lookup, not Scene.findNode", async () => {
    const fetchMock = stub(["hip"]);
    const skel = new DazSkeleton(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const [bone] = await skel.bones();
    // Exercise the bone's own generated script to confirm its locator is the
    // skeleton-scoped boneLocator(), not a plain Scene.findNode() lookup.
    const boneFetch = stub([0, 0, 0]);
    await bone.localEuler();
    const expectedLocator = boneLocator("hip");
    expect(scriptOf(boneFetch)).toBe(
      `(function(){\nvar _node = ${expectedLocator};\nif (!_node) return null;\nreturn [_node.getXRotControl().getValue(), _node.getYRotControl().getValue(), _node.getZRotControl().getValue()];\n})()`,
    );
    void fetchMock;
  });
});
