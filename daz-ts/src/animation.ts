/**
 * A captured animation clip: bone rotations (and optionally morphs) for
 * every frame in the play range. Mirrors dazpy's `_animation.py`.
 */

import * as fs from "node:fs";
import { NodeNotFoundError } from "./exceptions.js";
import { DazPose } from "./pose.js";
import { ScriptBuilder } from "./scriptBuilder.js";
import type { DazSkeleton } from "./skeleton.js";

/** One captured timeline frame. */
export interface AnimationFrame {
  frame: number;
  rotations: Array<[number, number, number]>;
  morphs: Record<string, number>;
}

/** Plain-object schema matching {@link DazAnimation.toDict} and the animation JSON file format. */
export interface DazAnimationDict {
  figure: string;
  frame_range: { start: number; end: number };
  bones: string[];
  frames: AnimationFrame[];
}

/**
 * A captured animation clip: bone rotations (and optionally morphs) for
 * every frame in the play range.
 *
 * Created with {@link capture}; saved/loaded with {@link save}/{@link load}.
 *
 * Bones are stored as a parallel-list encoding -- a single ordered `bones`
 * list of names, and per-frame `rotations` arrays aligned to that index --
 * so payload size grows with bones x frames rather than with a full dict
 * per frame.
 *
 * Typical workflow:
 * ```ts
 * const scene = new DazScene();
 * const figure = await scene.findSkeletonByLabel("Genesis 9");
 *
 * const anim = await DazAnimation.capture(figure, true);
 * anim.save("walk.json");
 * ```
 */
export class DazAnimation {
  readonly figure: string;
  readonly frameRange: { start: number; end: number };
  readonly bones: string[];
  readonly frames: AnimationFrame[];

  constructor(figure: string, frameRange: { start: number; end: number }, bones: string[], frames: AnimationFrame[]) {
    this.figure = figure;
    this.frameRange = frameRange;
    this.bones = bones;
    this.frames = frames;
  }

  // ── construction ──────────────────────────────────────────────────────

  /**
   * Capture the full animation of `skeleton` in a single HTTP call.
   *
   * Scrubs every frame in the scene's play range server-side (no round-trip
   * per frame). The timeline is restored to its original frame before the
   * call returns.
   *
   * When `includeMorphs` is `true`, the script first identifies which
   * geometry morphs and node-level properties actually vary across the
   * timeline (channels that are keyed but static are excluded), then
   * records their values per frame.
   *
   * @throws NodeNotFoundError If the skeleton is not found.
   */
  static async capture(skeleton: DazSkeleton, includeMorphs = false): Promise<DazAnimation> {
    const lookup = ScriptBuilder.skeletonLookup(skeleton.identifier);
    const includeMorphsJs = includeMorphs ? "true" : "false";

    const script = ScriptBuilder.iife(`
            ${lookup}
            if (!_skel) return null;

            var _origFrame = Scene.getFrame();

            var allBones = _skel.getAllBones();
            var boneNames = [];
            for (var i = 0; i < allBones.length; i++) boneNames.push(allBones[i].getName());

            // Detect channels whose values actually vary across the timeline.
            // Channels that are keyed but hold a constant value are excluded --
            // they add payload without contributing animation data.
            function isVaryingMorph(ch) {
                var n = ch.getNumKeys();
                if (n < 2) return false;
                var first = ch.getKeyValue(0);
                for (var k = 1; k < n; k++) {
                    if (Math.abs(ch.getKeyValue(k) - first) > 0.0001) return true;
                }
                return false;
            }

            var animatedChannels = [];
            if (${includeMorphsJs}) {
                var obj = _skel.getObject();
                if (obj) {
                    for (var i = 0; i < obj.getNumModifiers(); i++) {
                        var m = obj.getModifier(i);
                        if (m.className() === "DzMorph" && isVaryingMorph(m.getValueChannel()))
                            animatedChannels.push([m.getName(), m.getValueChannel()]);
                    }
                }
                for (var i = 0; i < _skel.getNumProperties(); i++) {
                    var p = _skel.getProperty(i);
                    if (p && p.getNumKeys && isVaryingMorph(p))
                        animatedChannels.push([p.getName(), p]);
                }
            }

            var step  = Scene.getTimeStep();
            var range = Scene.getPlayRange();
            var start = Math.round(range.start / step);
            var end   = Math.round(range.end   / step);

            var frames = [];
            for (var f = start; f <= end; f++) {
                Scene.setFrame(f);

                var rotations = [];
                for (var i = 0; i < allBones.length; i++) {
                    var b = allBones[i];
                    rotations.push([
                        b.getXRotControl().getValue(),
                        b.getYRotControl().getValue(),
                        b.getZRotControl().getValue()
                    ]);
                }

                var morphs = {};
                for (var i = 0; i < animatedChannels.length; i++) {
                    var v = animatedChannels[i][1].getValue();
                    if (Math.abs(v) > 0.0001) morphs[animatedChannels[i][0]] = v;
                }

                frames.push({frame: f, rotations: rotations, morphs: morphs});
            }

            Scene.setFrame(_origFrame);

            return {
                figure:      _skel.getLabel(),
                frame_range: {start: start, end: end},
                bones:       boneNames,
                frames:      frames
            };
        `);

    const result = (await skeleton.getClient().execute(script)).value as {
      figure: string;
      frame_range: { start: number; end: number };
      bones: string[];
      frames: AnimationFrame[];
    } | null;
    if (result === null) {
      throw new NodeNotFoundError(`Skeleton not found: ${JSON.stringify(skeleton.identifier.value)}`);
    }

    return new DazAnimation(result.figure, result.frame_range, result.bones, result.frames);
  }

  /** Load an animation from a JSON file. Accepts files produced by {@link save}. */
  static load(path: string): DazAnimation {
    const data = JSON.parse(fs.readFileSync(path, "utf-8")) as Partial<DazAnimationDict>;
    return new DazAnimation(
      data.figure ?? "",
      data.frame_range ?? { start: 0, end: 0 },
      data.bones ?? [],
      data.frames ?? [],
    );
  }

  // ── serialisation ─────────────────────────────────────────────────────

  /** Write this animation to a JSON file. Parent directories must exist. */
  save(path: string): void {
    fs.writeFileSync(path, JSON.stringify(this.toDict(), null, 2), "utf-8");
  }

  /** Return the animation as a plain dict (same schema as the JSON file). */
  toDict(): DazAnimationDict {
    return { figure: this.figure, frame_range: this.frameRange, bones: this.bones, frames: this.frames };
  }

  // ── clip operations ───────────────────────────────────────────────────

  /**
   * Return a new animation containing only frames in [start, end].
   *
   * `start` and `end` are scene frame numbers (the `frame` value stored in
   * each frame, not array indices). Both endpoints are inclusive.
   */
  clip(start: number, end: number): DazAnimation {
    const frames = this.frames.filter((f) => start <= f.frame && f.frame <= end);
    const newStart = frames.length > 0 ? frames[0].frame : start;
    const newEnd = frames.length > 0 ? frames[frames.length - 1].frame : end;
    return new DazAnimation(this.figure, { start: newStart, end: newEnd }, this.bones, frames);
  }

  /**
   * Blend this animation with `other` frame by frame.
   *
   * Each frame's bone rotations and morph values are linearly interpolated
   * between `this` (`t=0`) and `other` (`t=1`). Pure -- no HTTP round-trip.
   *
   * If the two clips have different frame counts, the result is truncated
   * to the shorter clip. Frame numbers are taken from `this`.
   *
   * @throws Error If `this` and `other` have different bone lists.
   */
  blend(other: DazAnimation, t: number): DazAnimation {
    if (JSON.stringify(this.bones) !== JSON.stringify(other.bones)) {
      throw new Error(
        `Cannot blend animations with different bone lists (${this.bones.length} vs ${other.bones.length} bones)`,
      );
    }
    const s = 1.0 - t;
    const frames: AnimationFrame[] = [];
    const n = Math.min(this.frames.length, other.frames.length);
    for (let i = 0; i < n; i++) {
      const fa = this.frames[i];
      const fb = other.frames[i];
      const rotations: Array<[number, number, number]> = this.bones.map((_, bi) => [
        fa.rotations[bi][0] * s + fb.rotations[bi][0] * t,
        fa.rotations[bi][1] * s + fb.rotations[bi][1] * t,
        fa.rotations[bi][2] * s + fb.rotations[bi][2] * t,
      ]);
      const morphs: Record<string, number> = {};
      for (const k of new Set([...Object.keys(fa.morphs), ...Object.keys(fb.morphs)])) {
        const v = (fa.morphs[k] ?? 0.0) * s + (fb.morphs[k] ?? 0.0) * t;
        if (Math.abs(v) > 1e-9) morphs[k] = v;
      }
      frames.push({ frame: fa.frame, rotations, morphs });
    }
    const newEnd = frames.length > 0 ? frames[frames.length - 1].frame : this.frameRange.start;
    return new DazAnimation(this.figure, { start: this.frameRange.start, end: newEnd }, this.bones, frames);
  }

  /**
   * Extract a single frame as a {@link DazPose}.
   *
   * Bone rotations are stored sparsely -- only bones with at least one
   * non-zero component are included. Morph values are copied as-is. Pure --
   * no HTTP round-trip.
   *
   * @param frameIndex 0-based index into {@link frames}.
   */
  asPose(frameIndex = 0): DazPose {
    const frame = this.frames[frameIndex];
    const bones: Record<string, [number, number, number]> = {};
    this.bones.forEach((name, i) => {
      const rot = frame.rotations[i];
      if (rot.some((v) => Math.abs(v) > 1e-9)) {
        bones[name] = rot;
      }
    });
    return new DazPose(this.figure, bones, { ...frame.morphs }, {});
  }

  /**
   * Apply a single frame of this animation to `skeleton`.
   *
   * Equivalent to `(await anim.asPose(frameIndex)).apply(skeleton)` -- one
   * HTTP call that sets only the channels present in the frame.
   *
   * @param frameIndex 0-based index into {@link frames}. Defaults to 0.
   */
  async apply(skeleton: DazSkeleton, frameIndex = 0): Promise<void> {
    await this.asPose(frameIndex).apply(skeleton);
  }

  /**
   * Concatenate `other` immediately after this animation.
   *
   * The other clip's frame numbers are shifted so it starts on the frame
   * following this animation's last frame. The figure label and bone list
   * are taken from `this`. Pure -- no HTTP round-trip.
   *
   * @throws Error If `this` and `other` have different bone lists.
   */
  append(other: DazAnimation): DazAnimation {
    if (JSON.stringify(this.bones) !== JSON.stringify(other.bones)) {
      throw new Error(
        `Cannot append animations with different bone lists (${this.bones.length} vs ${other.bones.length} bones)`,
      );
    }
    if (this.frames.length === 0) {
      return new DazAnimation(this.figure, { ...other.frameRange }, [...other.bones], [...other.frames]);
    }
    const offset = this.frameRange.end + 1 - other.frameRange.start;
    const otherFrames: AnimationFrame[] = other.frames.map((f) => ({
      frame: f.frame + offset,
      rotations: f.rotations,
      morphs: f.morphs,
    }));
    const frames = [...this.frames, ...otherFrames];
    return new DazAnimation(
      this.figure,
      { start: this.frameRange.start, end: frames[frames.length - 1].frame },
      this.bones,
      frames,
    );
  }

  // ── convenience ───────────────────────────────────────────────────────

  /** Number of captured frames. */
  get frameCount(): number {
    return this.frames.length;
  }

  /** Number of bones in the skeleton at capture time. */
  get boneCount(): number {
    return this.bones.length;
  }

  // ── dunder ────────────────────────────────────────────────────────────

  toString(): string {
    return (
      `DazAnimation(figure=${JSON.stringify(this.figure)}, ` +
      `frames=${this.frameCount}, bones=${this.boneCount}, ` +
      `range=${this.frameRange.start}–${this.frameRange.end})`
    );
  }
}
