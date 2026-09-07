import type { DazClient } from "./client.js";
import { DazBone } from "./bone.js";
import { NodeNotFoundError } from "./exceptions.js";
import { DazNode, type NodeIdentifier } from "./node.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Proxy for a `DzSkeleton` (a rigged figure such as Genesis 9). Extends
 * `DazNode` with bone-access helpers.
 *
 * This file covers bone lookup and bulk bone/morph state (Phase 2 Task 10);
 * a later task (Task 11) adds pose-evaluation/baking methods to this same
 * class.
 */
export class DazSkeleton extends DazNode {
  constructor(client: DazClient, identifier: NodeIdentifier);
  constructor(client: DazClient, identifier: NodeIdentifier, locator: string);
  constructor(client: DazClient, identifier: NodeIdentifier, locator?: string) {
    if (locator !== undefined) {
      super(client, identifier, locator);
    } else {
      super(client, identifier);
    }
  }

  // ---------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------

  /**
   * Wrap `body` in an IIFE that resolves this skeleton via
   * `Scene.getSkeletonList()` (bound to `_node`), not `Scene.findNode()` —
   * `findNode()` returns a plain `DzNode` lacking `DzSkeleton` methods like
   * `findBone()`.
   */
  private skeletonScript(body: string): string {
    return ScriptBuilder.iife(`${ScriptBuilder.skeletonLookupAsNode(this.identifier)}\nif (!_node) return null;\n${body}`);
  }

  /** Build a locator that resolves a bone through this specific skeleton (keeps same-named figures distinct). */
  private boneLocator(boneName: string): string {
    const lookup = ScriptBuilder.skeletonLookup(this.identifier);
    return `(function(){${lookup}return _skel?_skel.findBone(${ScriptBuilder.escapeString(boneName)}):null;})()`;
  }

  // ---------------------------------------------------------------------
  // Bone lookup
  // ---------------------------------------------------------------------

  /** Return all bones in this skeleton. */
  async bones(): Promise<DazBone[]> {
    const names =
      ((await this.client.execute(
        this.skeletonScript(
          "var bones = _node.getAllBones(); var names = []; for (var i = 0; i < bones.length; i++) { names.push(bones[i].getName()); } return names;",
        ),
      )).value as string[]) ?? [];
    return names.map((n) => DazBone.fromLocator(this.client, this.boneLocator(n), n));
  }

  /** Bulk metadata for every bone in one HTTP call (name/label/parentName/rotationOrder/localPosition/worldPosition/localEuler). */
  async boneMetadata(): Promise<Array<Record<string, unknown>>> {
    const script = this.skeletonScript(`
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
        `);
    return ((await this.client.execute(script)).value as Array<Record<string, unknown>>) ?? [];
  }

  /** Find a bone by internal name (naming conventions differ by figure generation — see {@link bones}). */
  async findBone(name: string): Promise<DazBone> {
    const script = this.skeletonScript(
      `var b = _node.findBone(${ScriptBuilder.escapeString(name)}); return b ? b.getName() : null;`,
    );
    const result = (await this.client.execute(script)).value as string | null;
    if (result === null) {
      throw new NodeNotFoundError(
        `Bone not found: ${JSON.stringify(name)}. ` +
          `Bone naming differs by figure generation — e.g. Genesis 9 uses ` +
          `'r_forearm', Genesis 3/8 uses 'rForearmBend', Genesis 1/2 uses 'rForeArm'. ` +
          `Call figure.bones() to list every bone name for this figure.`,
      );
    }
    return DazBone.fromLocator(this.client, this.boneLocator(result), result);
  }

  /** Find a bone by its user-visible label. */
  async findBoneByLabel(label: string): Promise<DazBone> {
    const script = this.skeletonScript(
      `var b = _node.findBoneByLabel(${ScriptBuilder.escapeString(label)}); return b ? b.getName() : null;`,
    );
    const result = (await this.client.execute(script)).value as string | null;
    if (result === null) {
      throw new NodeNotFoundError(`Bone with label not found: ${JSON.stringify(label)}`);
    }
    return DazBone.fromLocator(this.client, this.boneLocator(result), result);
  }

  async numBones(): Promise<number> {
    return ((await this.client.execute(this.skeletonScript("return _node.getAllBones().length;"))).value as number) ?? 0;
  }

  // ---------------------------------------------------------------------
  // Bulk bone state
  // ---------------------------------------------------------------------

  /** Euler rotations (degrees) for every bone in one HTTP call. */
  async boneRotations(): Promise<Record<string, [number, number, number]>> {
    const script = this.skeletonScript(`
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
        `);
    const raw = ((await this.client.execute(script)).value as Record<string, number[]>) ?? {};
    const out: Record<string, [number, number, number]> = {};
    for (const [name, v] of Object.entries(raw)) {
      out[name] = [v[0], v[1], v[2]];
    }
    return out;
  }

  /** Local-space quaternion rotations for every bone in one HTTP call — avoids per-bone Euler rotation-order ambiguity. */
  async boneRotationsQuat(): Promise<Record<string, { x: number; y: number; z: number; w: number }>> {
    const script = this.skeletonScript(`
            var _bones = _node.getAllBones();
            var _result = {};
            for (var i = 0; i < _bones.length; i++) {
                var _b = _bones[i];
                var _r = _b.getLocalRot();
                _result[_b.getName()] = {x: _r.x, y: _r.y, z: _r.z, w: _r.w};
            }
            return _result;
        `);
    return ((await this.client.execute(script)).value as Record<string, { x: number; y: number; z: number; w: number }>) ?? {};
  }

  /** Set Euler rotations for any subset of bones in one HTTP call; bones not named are left unchanged. */
  async setBoneRotations(data: Record<string, [number, number, number]>): Promise<void> {
    const dataJson = JSON.stringify(data);
    const script = this.skeletonScript(`
            var _data = ${dataJson};
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
        `);
    await this.client.execute(script);
  }

  /**
   * Set bone rotations, morph values, and/or node properties in one call.
   * Each argument is independently optional and uses plain `setValue()`
   * writes (same as {@link setBoneRotations}/{@link setMorphValues}) — `props`
   * is NOT routed through any ERC-avoidance logic, so on ERC-driven node
   * properties this can double-apply a controller contribution the same
   * way `DazElement.setProperty` already can.
   */
  async setState(opts: {
    bones?: Record<string, [number, number, number]>;
    morphs?: Record<string, number>;
    props?: Record<string, unknown>;
  }): Promise<void> {
    const lines: string[] = [];
    if (opts.bones) {
      lines.push(`
                var _bonesData = ${JSON.stringify(opts.bones)};
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
            `);
    }
    if (opts.morphs) {
      lines.push(`
                var _morphsData = ${JSON.stringify(opts.morphs)};
                var _obj = _node.getObject();
                if (_obj) {
                    for (var j = 0; j < _obj.getNumModifiers(); j++) {
                        var _m = _obj.getModifier(j);
                        if (_m.className() === "DzMorph" && _morphsData.hasOwnProperty(_m.getName())) {
                            _m.getValueChannel().setValue(_morphsData[_m.getName()]);
                        }
                    }
                }
            `);
    }
    if (opts.props) {
      lines.push(`
                var _propsData = ${JSON.stringify(opts.props)};
                for (var k = 0; k < _node.getNumProperties(); k++) {
                    var _p = _node.getProperty(k);
                    var _pl = _p.getLabel();
                    if (_propsData.hasOwnProperty(_pl)) {
                        _p.setValue(_propsData[_pl]);
                    }
                }
            `);
    }
    if (lines.length === 0) return;
    await this.client.execute(this.skeletonScript(lines.join("\n")));
  }

  // ---------------------------------------------------------------------
  // Bulk morph state
  // ---------------------------------------------------------------------

  /** Current value of every `DzMorph` modifier in one HTTP call; `nonzeroOnly` excludes values with `|v| <= 0.0001`. */
  async morphValues(nonzeroOnly = false): Promise<Record<string, number>> {
    const nzJs = nonzeroOnly ? "true" : "false";
    const script = this.skeletonScript(`
            var _obj = _node.getObject();
            if (!_obj) return {};
            var _result = {};
            var _nz = ${nzJs};
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
        `);
    return ((await this.client.execute(script)).value as Record<string, number>) ?? {};
  }

  /** Set the value of any subset of morphs in one HTTP call; morphs not named are left unchanged. */
  async setMorphValues(data: Record<string, number>): Promise<void> {
    const dataJson = JSON.stringify(data);
    const script = this.skeletonScript(`
            var _data = ${dataJson};
            var _obj = _node.getObject();
            if (!_obj) return null;
            for (var i = 0; i < _obj.getNumModifiers(); i++) {
                var _m = _obj.getModifier(i);
                if (_m.className() === "DzMorph" && _data.hasOwnProperty(_m.getName())) {
                    _m.getValueChannel().setValue(_data[_m.getName()]);
                }
            }
        `);
    await this.client.execute(script);
  }
}
