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
  constructor(client: DazClient, identifier: NodeIdentifier) {
    super(client, identifier);
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

  // ---------------------------------------------------------------------
  // Pose evaluation
  // ---------------------------------------------------------------------

  /**
   * Apply candidate rotations, read effector world positions, then restore —
   * the figure is left in its original state after this call.
   */
  async evaluatePose(
    rotations: Record<string, [number, number, number]>,
    effectorBoneNames: string[],
  ): Promise<Record<string, [number, number, number]>> {
    const rotationsJson = JSON.stringify(rotations);
    const effectorsJson = ScriptBuilder.serializeArg(effectorBoneNames);
    const script = this.skeletonScript(`
            var _data = ${rotationsJson};
            var _effNames = ${effectorsJson};
            var _allBones = _node.getAllBones();

            var _originals = {};
            for (var i = 0; i < _allBones.length; i++) {
                var _b = _allBones[i]; var _n = _b.getName();
                if (_data.hasOwnProperty(_n)) {
                    _originals[_n] = [
                        _b.getXRotControl().getValue(),
                        _b.getYRotControl().getValue(),
                        _b.getZRotControl().getValue()
                    ];
                    var _r = _data[_n];
                    _b.getXRotControl().setValue(_r[0]);
                    _b.getYRotControl().setValue(_r[1]);
                    _b.getZRotControl().setValue(_r[2]);
                }
            }

            var _result = {};
            var _effSet = {};
            for (var j = 0; j < _effNames.length; j++) { _effSet[_effNames[j]] = true; }
            for (var i = 0; i < _allBones.length; i++) {
                var _b = _allBones[i]; var _n = _b.getName();
                if (_effSet.hasOwnProperty(_n)) {
                    var _p = _b.getWSPos();
                    _result[_n] = [_p.x, _p.y, _p.z];
                }
            }

            for (var i = 0; i < _allBones.length; i++) {
                var _b = _allBones[i]; var _n = _b.getName();
                if (_originals.hasOwnProperty(_n)) {
                    var _r = _originals[_n];
                    _b.getXRotControl().setValue(_r[0]);
                    _b.getYRotControl().setValue(_r[1]);
                    _b.getZRotControl().setValue(_r[2]);
                }
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

  /**
   * Compute the IK Jacobian for a bone chain server-side in one HTTP call:
   * perturbs each (bone, axis) pair by `stepDegrees`, reads the effector
   * world position, and restores the original rotation. The figure is left
   * unchanged. Returns `null` if the effector bone cannot be found.
   */
  async evaluatePoseJacobian(
    chainBoneNames: string[],
    effectorBoneName: string,
    stepDegrees = 1.0,
  ): Promise<{ basePosition: [number, number, number]; columns: Array<[number, number, number]> } | null> {
    const chainJson = ScriptBuilder.serializeArg(chainBoneNames);
    const effectorJson = ScriptBuilder.escapeString(effectorBoneName);
    const script = this.skeletonScript(`
            var _chain = ${chainJson};
            var _effName = ${effectorJson};
            var _step = ${ScriptBuilder.serializeArg(stepDegrees)};

            var _allBones = _node.getAllBones();
            var _boneMap = {};
            for (var i = 0; i < _allBones.length; i++) {
                _boneMap[_allBones[i].getName()] = _allBones[i];
            }

            var _eff = _boneMap[_effName];
            if (!_eff) return null;

            var _bp = _eff.getWSPos();
            var _base = [_bp.x, _bp.y, _bp.z];

            var _columns = [];
            for (var c = 0; c < _chain.length; c++) {
                var _b = _boneMap[_chain[c]];
                if (!_b) {
                    _columns.push([0,0,0]); _columns.push([0,0,0]); _columns.push([0,0,0]);
                    continue;
                }
                var _ctrls = [_b.getXRotControl(), _b.getYRotControl(), _b.getZRotControl()];
                for (var axis = 0; axis < 3; axis++) {
                    var _ctrl = _ctrls[axis];
                    var _orig = _ctrl.getValue();
                    _ctrl.setValue(_orig + _step);
                    var _tp = _eff.getWSPos();
                    _ctrl.setValue(_orig);
                    _columns.push([
                        (_tp.x - _base[0]) / _step,
                        (_tp.y - _base[1]) / _step,
                        (_tp.z - _base[2]) / _step
                    ]);
                }
            }
            return {base_position: _base, columns: _columns};
        `);
    const result = (await this.client.execute(script)).value as
      | { base_position: [number, number, number]; columns: Array<[number, number, number]> }
      | null;
    if (result === null) return null;
    return { basePosition: result.base_position, columns: result.columns };
  }

  // ---------------------------------------------------------------------
  // Keyframe baking
  // ---------------------------------------------------------------------

  /** Bake bone rotation keyframes for every frame in the range via `insertKey`. The original frame is restored before returning. */
  async bakeBoneRotations(opts: { start?: number; end?: number; boneNames?: string[] } = {}): Promise<{
    framesBaked: number;
    bonesBaked: number;
  }> {
    const startJs = opts.start !== undefined ? ScriptBuilder.serializeArg(opts.start) : "null";
    const endJs = opts.end !== undefined ? ScriptBuilder.serializeArg(opts.end) : "null";
    const boneFilterJs = opts.boneNames !== undefined ? JSON.stringify(Object.fromEntries(opts.boneNames.map((n) => [n, true]))) : "null";
    const script = this.skeletonScript(`
            var _step    = Scene.getTimeStep();
            var _pr      = Scene.getPlayRange();
            var _prStart = Math.round(_pr.start / _step);
            var _prEnd   = Math.round(_pr.end   / _step);
            var _bkStart = (${startJs} !== null) ? ${startJs} : _prStart;
            var _bkEnd   = (${endJs}   !== null) ? ${endJs}   : _prEnd;
            var _filter  = ${boneFilterJs};

            var _all = _node.getAllBones();
            var _bones = [];
            for (var i = 0; i < _all.length; i++) {
                if (_filter === null || _filter.hasOwnProperty(_all[i].getName()))
                    _bones.push(_all[i]);
            }

            var _origFrame = Scene.getFrame();
            for (var f = _bkStart; f <= _bkEnd; f++) {
                Scene.setFrame(f);
                var _t = f * _step;
                for (var i = 0; i < _bones.length; i++) {
                    var _b = _bones[i];
                    _b.getXRotControl().insertKey(_t, _b.getXRotControl().getValue());
                    _b.getYRotControl().insertKey(_t, _b.getYRotControl().getValue());
                    _b.getZRotControl().insertKey(_t, _b.getZRotControl().getValue());
                }
            }
            Scene.setFrame(_origFrame);
            return {frames_baked: _bkEnd - _bkStart + 1, bones_baked: _bones.length};
        `);
    const result = (await this.client.execute(script)).value as { frames_baked: number; bones_baked: number } | null;
    return { framesBaked: result?.frames_baked ?? 0, bonesBaked: result?.bones_baked ?? 0 };
  }

  /** Bake morph channel keyframes for every frame in the range via `insertKey`. The original frame is restored before returning. */
  async bakeMorphs(opts: { start?: number; end?: number; morphNames?: string[] } = {}): Promise<{
    framesBaked: number;
    morphsBaked: number;
  }> {
    const startJs = opts.start !== undefined ? ScriptBuilder.serializeArg(opts.start) : "null";
    const endJs = opts.end !== undefined ? ScriptBuilder.serializeArg(opts.end) : "null";
    const morphFilterJs =
      opts.morphNames !== undefined ? JSON.stringify(Object.fromEntries(opts.morphNames.map((n) => [n, true]))) : "null";
    const script = this.skeletonScript(`
            var _step    = Scene.getTimeStep();
            var _pr      = Scene.getPlayRange();
            var _prStart = Math.round(_pr.start / _step);
            var _prEnd   = Math.round(_pr.end   / _step);
            var _bkStart = (${startJs} !== null) ? ${startJs} : _prStart;
            var _bkEnd   = (${endJs}   !== null) ? ${endJs}   : _prEnd;
            var _filter  = ${morphFilterJs};

            var _obj = _node.getObject();
            if (!_obj) return {frames_baked: 0, morphs_baked: 0};
            var _channels = [];
            for (var i = 0; i < _obj.getNumModifiers(); i++) {
                var _m = _obj.getModifier(i);
                if (_m.className() === "DzMorph" &&
                    (_filter === null || _filter.hasOwnProperty(_m.getName())))
                    _channels.push(_m.getValueChannel());
            }

            var _origFrame = Scene.getFrame();
            for (var f = _bkStart; f <= _bkEnd; f++) {
                Scene.setFrame(f);
                var _t = f * _step;
                for (var i = 0; i < _channels.length; i++) {
                    _channels[i].insertKey(_t, _channels[i].getValue());
                }
            }
            Scene.setFrame(_origFrame);
            return {frames_baked: _bkEnd - _bkStart + 1, morphs_baked: _channels.length};
        `);
    const result = (await this.client.execute(script)).value as { frames_baked: number; morphs_baked: number } | null;
    return { framesBaked: result?.frames_baked ?? 0, morphsBaked: result?.morphs_baked ?? 0 };
  }

  /** Bake bone rotations and optionally morphs in a single HTTP call (scrubs the timeline once instead of twice). */
  async bake(
    opts: {
      start?: number;
      end?: number;
      boneNames?: string[];
      includeMorphs?: boolean;
      morphNames?: string[];
    } = {},
  ): Promise<{ framesBaked: number; bonesBaked: number; morphsBaked: number }> {
    const startJs = opts.start !== undefined ? ScriptBuilder.serializeArg(opts.start) : "null";
    const endJs = opts.end !== undefined ? ScriptBuilder.serializeArg(opts.end) : "null";
    const boneFilterJs = opts.boneNames !== undefined ? JSON.stringify(Object.fromEntries(opts.boneNames.map((n) => [n, true]))) : "null";
    const morphFilterJs =
      opts.morphNames !== undefined ? JSON.stringify(Object.fromEntries(opts.morphNames.map((n) => [n, true]))) : "null";
    const withMorphsJs = opts.includeMorphs ? "true" : "false";
    const script = this.skeletonScript(`
            var _step    = Scene.getTimeStep();
            var _pr      = Scene.getPlayRange();
            var _prStart = Math.round(_pr.start / _step);
            var _prEnd   = Math.round(_pr.end   / _step);
            var _bkStart    = (${startJs} !== null) ? ${startJs} : _prStart;
            var _bkEnd      = (${endJs}   !== null) ? ${endJs}   : _prEnd;
            var _boneFilter = ${boneFilterJs};
            var _mFilter    = ${morphFilterJs};
            var _withMorphs = ${withMorphsJs};

            var _all = _node.getAllBones();
            var _bones = [];
            for (var i = 0; i < _all.length; i++) {
                if (_boneFilter === null || _boneFilter.hasOwnProperty(_all[i].getName()))
                    _bones.push(_all[i]);
            }

            var _mChannels = [];
            if (_withMorphs) {
                var _obj = _node.getObject();
                if (_obj) {
                    for (var i = 0; i < _obj.getNumModifiers(); i++) {
                        var _m = _obj.getModifier(i);
                        if (_m.className() === "DzMorph" &&
                            (_mFilter === null || _mFilter.hasOwnProperty(_m.getName())))
                            _mChannels.push(_m.getValueChannel());
                    }
                }
            }

            var _origFrame = Scene.getFrame();
            for (var f = _bkStart; f <= _bkEnd; f++) {
                Scene.setFrame(f);
                var _t = f * _step;
                for (var i = 0; i < _bones.length; i++) {
                    var _b = _bones[i];
                    _b.getXRotControl().insertKey(_t, _b.getXRotControl().getValue());
                    _b.getYRotControl().insertKey(_t, _b.getYRotControl().getValue());
                    _b.getZRotControl().insertKey(_t, _b.getZRotControl().getValue());
                }
                for (var i = 0; i < _mChannels.length; i++) {
                    _mChannels[i].insertKey(_t, _mChannels[i].getValue());
                }
            }
            Scene.setFrame(_origFrame);
            return {
                frames_baked: _bkEnd - _bkStart + 1,
                bones_baked:  _bones.length,
                morphs_baked: _mChannels.length
            };
        `);
    const result = (await this.client.execute(script)).value as
      | { frames_baked: number; bones_baked: number; morphs_baked: number }
      | null;
    return {
      framesBaked: result?.frames_baked ?? 0,
      bonesBaked: result?.bones_baked ?? 0,
      morphsBaked: result?.morphs_baked ?? 0,
    };
  }

  // ---------------------------------------------------------------------
  // Zeroing
  // ---------------------------------------------------------------------

  /**
   * Drive every bone rotation to 0 and every non-zero `DzMorph` to 0, in one
   * DazScript evaluation. Used by `poses.ts`'s `zeroFigure()` default
   * (`includeProps: false`) path -- does not touch node-level properties or
   * the figure root transform.
   */
  async zeroBonesAndMorphs(): Promise<void> {
    const script = this.skeletonScript(`
            var _bones = _node.getAllBones();
            for (var i = 0; i < _bones.length; i++) {
                var _b = _bones[i];
                _b.getXRotControl().setValue(0);
                _b.getYRotControl().setValue(0);
                _b.getZRotControl().setValue(0);
            }
            var _obj = _node.getObject();
            if (_obj) {
                for (var j = 0; j < _obj.getNumModifiers(); j++) {
                    var _m = _obj.getModifier(j);
                    if (_m.className() === "DzMorph") {
                        var _ch = _m.getValueChannel();
                        if (Math.abs(_ch.getValue()) > 0.0001) {
                            _ch.setValue(0);
                        }
                    }
                }
            }
        `);
    await this.client.execute(script);
  }

  // ---------------------------------------------------------------------
  // Follow target
  // ---------------------------------------------------------------------

  /**
   * The IK follow-target skeleton, or `null` if not set.
   * @remarks Aligning a limb *toward* a target ({@link DazSkeleton}'s Python
   * counterpart's `hand_to_target`/`foot_to_target`) requires the Jacobian
   * IK solver in `_interaction.py`, ported in Phase 5 (`daz-script-server-sf7y`) —
   * not available in this phase.
   */
  async followTarget(): Promise<DazSkeleton | null> {
    const name = (await this.client.execute(this.skeletonScript("var t = _node.getFollowTarget(); return t ? t.getName() : null;")))
      .value as string | null;
    if (name === null) return null;
    return new DazSkeleton(this.client, { value: name, kind: "name" });
  }
}
