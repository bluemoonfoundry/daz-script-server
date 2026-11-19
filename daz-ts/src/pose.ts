/**
 * A snapshot of a figure's complete pose state. Mirrors dazpy's `_pose.py`.
 */

import * as fs from "node:fs";
import { NodeNotFoundError } from "./exceptions.js";
import type { RetryOptions } from "./client.js";
import { ScriptBuilder } from "./scriptBuilder.js";
import type { DazSkeleton } from "./skeleton.js";

const ZERO3: [number, number, number] = [0, 0, 0];

function round6(v: number): number {
  return Math.round(v * 1e6) / 1e6;
}

/** Plain-object schema matching {@link DazPose.toDict}/{@link DazPose.fromDict} and the pose JSON file format. */
export interface DazPoseDict {
  figure: string;
  bones: Record<string, [number, number, number]>;
  morphs: Record<string, number>;
  props: Record<string, number>;
}

/**
 * A snapshot of a figure's complete pose state.
 *
 * Stores bone rotations (Euler XYZ degrees), geometry morph values, and
 * node-level numeric properties. Sparse by default -- zero values are
 * omitted so the object stays compact for morph-heavy figures.
 *
 * Typical workflow:
 * ```ts
 * const scene = new DazScene();
 * const figure = await scene.findSkeletonByLabel("Genesis 9");
 *
 * const neutral = await DazPose.capture(figure);
 * neutral.save("neutral.json");
 *
 * const smile = DazPose.load("smile.json");
 * await neutral.lerp(smile, 0.5).apply(figure);
 * ```
 */
export class DazPose {
  readonly figure: string;
  readonly bones: Record<string, [number, number, number]>;
  readonly morphs: Record<string, number>;
  readonly props: Record<string, number>;

  constructor(
    figure: string,
    bones: Record<string, [number, number, number]>,
    morphs: Record<string, number>,
    props: Record<string, number>,
  ) {
    this.figure = figure;
    this.bones = bones;
    this.morphs = morphs;
    this.props = props;
  }

  // ── construction ──────────────────────────────────────────────────────

  /**
   * Capture the current pose of `skeleton` in a single HTTP call.
   *
   * Records all non-zero bone rotations, morph values, and node-level
   * numeric properties. Zero values are omitted (sparse storage); they are
   * implied as 0.0 during {@link lerp} and {@link applyFull}.
   *
   * @throws NodeNotFoundError If the skeleton is not found.
   */
  static async capture(skeleton: DazSkeleton): Promise<DazPose> {
    const lookup = ScriptBuilder.skeletonLookup(skeleton.identifier);
    const script = ScriptBuilder.iife(`
            ${lookup}
            if (!_skel) return null;

            // Bone rotation controls can themselves be ERC targets (e.g.
            // auto-follow bend/twist ratios common on Genesis figures, where
            // one bone's rotation is driven off another's), so read raw
            // values here for the same reason as morphs/props below.
            var bones = {};
            var all = _skel.getAllBones();
            for (var i = 0; i < all.length; i++) {
                var b = all[i];
                var xc = b.getXRotControl(), yc = b.getYRotControl(), zc = b.getZRotControl();
                var x = (typeof xc.getRawValue === "function") ? xc.getRawValue() : xc.getValue();
                var y = (typeof yc.getRawValue === "function") ? yc.getRawValue() : yc.getValue();
                var z = (typeof zc.getRawValue === "function") ? zc.getRawValue() : zc.getValue();
                if (Math.abs(x) > 0.0001 || Math.abs(y) > 0.0001 || Math.abs(z) > 0.0001)
                    bones[b.getName()] = [x, y, z];
            }

            // Morphs can themselves be ERC targets (e.g. a master "Character"
            // dial that fans out to dozens of shape morphs via DzERCLink),
            // so read raw values here for the same reason as props below.
            var morphs = {};
            var obj = _skel.getObject();
            if (obj) {
                for (var i = 0; i < obj.getNumModifiers(); i++) {
                    var m = obj.getModifier(i);
                    if (m.className() === "DzMorph") {
                        var ch = m.getValueChannel();
                        var v = (typeof ch.getRawValue === "function") ? ch.getRawValue() : ch.getValue();
                        if (Math.abs(v) > 0.0001) morphs[m.getName()] = v;
                    }
                }
            }

            // Read the property's own dial setting rather than getValue()'s
            // post-ERC computed total. Properties driven by DzERCLink
            // controllers (e.g. a "Scale" dial fed by dozens of linked
            // morphs) return a getValue() that already includes every
            // controller's contribution; capturing that and writing it back
            // via setValue() on apply() would re-add the same contributions
            // on top, inflating the property a little more on every
            // capture/apply cycle. getRawValue() reads only the property's
            // own baseline and round-trips correctly regardless of ERC links.
            var props = {};
            for (var i = 0; i < _skel.getNumProperties(); i++) {
                var p = _skel.getProperty(i);
                if (p && p.getValue) {
                    var v = (typeof p.getRawValue === "function") ? p.getRawValue() : p.getValue();
                    if (typeof v === "number" && Math.abs(v) > 0.0001)
                        props[p.getName()] = v;
                }
            }

            return {bones: bones, morphs: morphs, props: props};
        `);

    const result = (await skeleton.getClient().execute(script)).value as {
      bones: Record<string, [number, number, number]>;
      morphs: Record<string, number>;
      props: Record<string, number>;
    } | null;
    if (result === null) {
      throw new NodeNotFoundError(`Skeleton not found: ${JSON.stringify(skeleton.identifier.value)}`);
    }

    return new DazPose(skeleton.identifier.value, result.bones, result.morphs, result.props);
  }

  /** Load a pose from a JSON file. Accepts files produced by {@link save}. */
  static load(path: string): DazPose {
    const data = JSON.parse(fs.readFileSync(path, "utf-8")) as Partial<DazPoseDict>;
    return new DazPose(data.figure ?? "", data.bones ?? {}, data.morphs ?? {}, data.props ?? {});
  }

  // ── serialisation ─────────────────────────────────────────────────────

  /** Write this pose to a JSON file. Parent directories must exist. */
  save(path: string): void {
    fs.writeFileSync(path, JSON.stringify(this.toDict(), null, 2), "utf-8");
  }

  /** Return the pose as a plain dict (same schema as the JSON file). */
  toDict(): DazPoseDict {
    return { figure: this.figure, bones: this.bones, morphs: this.morphs, props: this.props };
  }

  static fromDict(data: Partial<DazPoseDict>): DazPose {
    return new DazPose(data.figure ?? "", data.bones ?? {}, data.morphs ?? {}, data.props ?? {});
  }

  // ── interpolation ─────────────────────────────────────────────────────

  /**
   * Linearly interpolate between this pose and `other`. Missing keys in
   * either pose are treated as zero. The result uses the figure label from
   * `this`. Pure -- no HTTP round-trip.
   *
   * @param t Blend factor. 0.0 = this pose, 1.0 = `other`. Values outside
   * [0, 1] extrapolate.
   */
  lerp(other: DazPose, t: number): DazPose {
    const l = (a: number, b: number) => a + (b - a) * t;

    const bones: Record<string, [number, number, number]> = {};
    for (const k of new Set([...Object.keys(this.bones), ...Object.keys(other.bones)])) {
      const a = this.bones[k] ?? ZERO3;
      const b = other.bones[k] ?? ZERO3;
      bones[k] = [l(a[0], b[0]), l(a[1], b[1]), l(a[2], b[2])];
    }
    const morphs: Record<string, number> = {};
    for (const k of new Set([...Object.keys(this.morphs), ...Object.keys(other.morphs)])) {
      morphs[k] = l(this.morphs[k] ?? 0.0, other.morphs[k] ?? 0.0);
    }
    const props: Record<string, number> = {};
    for (const k of new Set([...Object.keys(this.props), ...Object.keys(other.props)])) {
      props[k] = l(this.props[k] ?? 0.0, other.props[k] ?? 0.0);
    }
    return new DazPose(this.figure, bones, morphs, props);
  }

  // ── apply ─────────────────────────────────────────────────────────────

  /**
   * Apply this pose to `skeleton` in a single HTTP call.
   *
   * Only channels present in the pose are changed. Bones and morphs not
   * stored in the pose are left at their current values. Use
   * {@link applyFull} when you need a clean, authoritative reset to exactly
   * this pose.
   */
  async apply(skeleton: DazSkeleton, opts: RetryOptions = {}): Promise<void> {
    const { retryOnBusy = true, maxWait = 30.0 } = opts;
    const lookup = ScriptBuilder.skeletonLookup(skeleton.identifier);
    const bonesJson = JSON.stringify(
      Object.fromEntries(Object.entries(this.bones).map(([k, xyz]) => [k, xyz.map(round6)])),
    );
    const morphsJson = JSON.stringify(Object.fromEntries(Object.entries(this.morphs).map(([k, v]) => [k, round6(v)])));
    const propsJson = JSON.stringify(Object.fromEntries(Object.entries(this.props).map(([k, v]) => [k, round6(v)])));

    const script = ScriptBuilder.iife(`
            ${lookup}
            if (!_skel) return false;
            var _bones  = ${bonesJson};
            var _morphs = ${morphsJson};
            var _props  = ${propsJson};

            var all = _skel.getAllBones();
            for (var i = 0; i < all.length; i++) {
                var b = all[i];
                var xyz = _bones[b.getName()];
                if (xyz !== undefined) {
                    var xc = b.getXRotControl(), yc = b.getYRotControl(), zc = b.getZRotControl();
                    if (typeof xc.setRawValue === "function") { xc.setRawValue(xyz[0]); } else { xc.setValue(xyz[0]); }
                    if (typeof yc.setRawValue === "function") { yc.setRawValue(xyz[1]); } else { yc.setValue(xyz[1]); }
                    if (typeof zc.setRawValue === "function") { zc.setRawValue(xyz[2]); } else { zc.setValue(xyz[2]); }
                }
            }

            // Write back to the raw dial slot, mirroring capture()'s use of
            // getRawValue() -- see the comment there for why setValue()
            // would double-apply ERC-controller contributions on properties
            // like morphs or a "Scale" dial that are DzERCLink targets.
            var obj = _skel.getObject();
            if (obj) {
                for (var i = 0; i < obj.getNumModifiers(); i++) {
                    var m = obj.getModifier(i);
                    if (m.className() === "DzMorph") {
                        var v = _morphs[m.getName()];
                        if (v !== undefined) {
                            var ch = m.getValueChannel();
                            if (typeof ch.setRawValue === "function") { ch.setRawValue(v); }
                            else { ch.setValue(v); }
                        }
                    }
                }
            }

            for (var i = 0; i < _skel.getNumProperties(); i++) {
                var p = _skel.getProperty(i);
                if (p && p.setValue) {
                    var v = _props[p.getName()];
                    if (v !== undefined) {
                        if (typeof p.setRawValue === "function") { p.setRawValue(v); }
                        else { p.setValue(v); }
                    }
                }
            }

            return true;
        `);

    await skeleton.getClient().execute(script, undefined, { retryOnBusy, maxWait });
  }

  /**
   * Apply this pose and zero every channel not present in the pose.
   *
   * Unlike {@link apply}, every bone rotation, morph, and node property on
   * the skeleton is explicitly set -- channels absent from the pose are
   * driven to zero. Use this to restore a known baseline cleanly.
   */
  async applyFull(skeleton: DazSkeleton, opts: RetryOptions = {}): Promise<void> {
    const { retryOnBusy = true, maxWait = 30.0 } = opts;
    const lookup = ScriptBuilder.skeletonLookup(skeleton.identifier);
    const bonesJson = JSON.stringify(
      Object.fromEntries(Object.entries(this.bones).map(([k, xyz]) => [k, xyz.map(round6)])),
    );
    const morphsJson = JSON.stringify(Object.fromEntries(Object.entries(this.morphs).map(([k, v]) => [k, round6(v)])));
    const propsJson = JSON.stringify(Object.fromEntries(Object.entries(this.props).map(([k, v]) => [k, round6(v)])));

    const script = ScriptBuilder.iife(`
            ${lookup}
            if (!_skel) return false;
            var _bones  = ${bonesJson};
            var _morphs = ${morphsJson};
            var _props  = ${propsJson};

            var all = _skel.getAllBones();
            for (var i = 0; i < all.length; i++) {
                var b = all[i];
                var xyz = _bones[b.getName()] || [0, 0, 0];
                var xc = b.getXRotControl(), yc = b.getYRotControl(), zc = b.getZRotControl();
                if (typeof xc.setRawValue === "function") { xc.setRawValue(xyz[0]); } else { xc.setValue(xyz[0]); }
                if (typeof yc.setRawValue === "function") { yc.setRawValue(xyz[1]); } else { yc.setValue(xyz[1]); }
                if (typeof zc.setRawValue === "function") { zc.setRawValue(xyz[2]); } else { zc.setValue(xyz[2]); }
            }

            // Write back to the raw dial slot -- see the comment in
            // capture() for why setValue() would double-apply ERC-controller
            // contributions on properties like morphs or a "Scale" dial that
            // are DzERCLink targets.
            var obj = _skel.getObject();
            if (obj) {
                for (var i = 0; i < obj.getNumModifiers(); i++) {
                    var m = obj.getModifier(i);
                    if (m.className() === "DzMorph") {
                        var v = _morphs[m.getName()];
                        var _v = (v !== undefined) ? v : 0;
                        var ch = m.getValueChannel();
                        if (typeof ch.setRawValue === "function") { ch.setRawValue(_v); }
                        else { ch.setValue(_v); }
                    }
                }
            }

            for (var i = 0; i < _skel.getNumProperties(); i++) {
                var p = _skel.getProperty(i);
                if (p && p.setValue) {
                    var v = _props[p.getName()];
                    var _v = (v !== undefined) ? v : 0;
                    if (typeof p.setRawValue === "function") { p.setRawValue(_v); }
                    else { p.setValue(_v); }
                }
            }

            return true;
        `);

    await skeleton.getClient().execute(script, undefined, { retryOnBusy, maxWait });
  }

  // ── dunder ────────────────────────────────────────────────────────────

  toString(): string {
    return (
      `DazPose(figure=${JSON.stringify(this.figure)}, ` +
      `bones=${Object.keys(this.bones).length}, morphs=${Object.keys(this.morphs).length}, props=${Object.keys(this.props).length})`
    );
  }
}
