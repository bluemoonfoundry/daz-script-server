import type { DazClient } from "./client.js";
import { DazElement } from "./element.js";
import { ScriptRuntimeError } from "./exceptions.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/** Identifies a scene node by name or label. */
export interface NodeIdentifier {
  /** The name or label string used to look up the node. */
  value: string;
  /** `"name"` uses `Scene.findNode()`; `"label"` uses `Scene.findNodeByLabel()`. */
  kind: "name" | "label";
}

/**
 * Proxy for a `DzNode` in the active DAZ Studio scene. Provides access to
 * transforms, hierarchy, visibility, materials, modifiers, and geometry.
 * Instances are typically obtained from {@link DazScene} rather than
 * constructed directly. All reads may resolve to `null` if the node no
 * longer exists in the scene.
 *
 * This class is built across two tasks: this file covers transforms,
 * visibility, and hierarchy (Phase 2 Task 3); a later task (Task 6) adds
 * modifiers/materials/fitting methods to this same class.
 */
export class DazNode extends DazElement {
  readonly identifier: NodeIdentifier;

  constructor(client: DazClient, identifier: NodeIdentifier) {
    super(client, ScriptBuilder.findNodeExpr(identifier));
    this.identifier = identifier;
  }

  /** Wrap `body` in the standard `_node` null-checked IIFE for this node's identifier. */
  protected nodeScript(body: string): string {
    return ScriptBuilder.nodeBody(this.identifier, body);
  }

  // ---------------------------------------------------------------------
  // Identity
  // ---------------------------------------------------------------------

  /** User-visible display label shown in the Scene panel (read/write). */
  async label(): Promise<string | null> {
    return (await this.client.execute(this.nodeScript("return _node.getLabel();"))).value as string | null;
  }

  async setLabel(value: string): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setLabel(${ScriptBuilder.escapeString(value)});`));
  }

  /** Internal node name used to look up the node (read-only). */
  async name(): Promise<string | null> {
    return (await this.client.execute(this.nodeScript("return _node.getName();"))).value as string | null;
  }

  // ---------------------------------------------------------------------
  // Transforms
  // ---------------------------------------------------------------------

  /** World-space position as `{x, y, z}` (read-only; use {@link setPosition} to change). */
  async position(): Promise<{ x: number; y: number; z: number } | null> {
    return (await this.client.execute(this.nodeScript("var p = _node.getWSPos(); return {x: p.x, y: p.y, z: p.z};")))
      .value as { x: number; y: number; z: number } | null;
  }

  async setPosition(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setWSPos(new DzVec3(${x}, ${y}, ${z}));`));
  }

  /** World-space rotation as `{x, y, z, w}` quaternion (read-only; use {@link setRotation} for Euler degrees). */
  async rotation(): Promise<{ x: number; y: number; z: number; w: number } | null> {
    return (
      await this.client.execute(this.nodeScript("var r = _node.getWSRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};"))
    ).value as { x: number; y: number; z: number; w: number } | null;
  }

  /** Uniform scale factor (read-only). */
  async generalScale(): Promise<number | null> {
    return (await this.client.execute(this.nodeScript("return _node.getScaleControl().getValue();"))).value as
      | number
      | null;
  }

  /** Per-axis and uniform scale as `{x, y, z, general}` (read-only; use {@link setScale} to change per-axis values). */
  async scale(): Promise<{ x: number; y: number; z: number; general: number } | null> {
    return (
      await this.client.execute(
        this.nodeScript(
          "return {x: _node.getXScaleControl().getValue(), y: _node.getYScaleControl().getValue(), z: _node.getZScaleControl().getValue(), general: _node.getScaleControl().getValue()};",
        ),
      )
    ).value as { x: number; y: number; z: number; general: number } | null;
  }

  /** Set per-axis local scale (does not affect the general/uniform scale dial; see {@link generalScale}). */
  async setScale(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `_node.getXScaleControl().setValue(${x}); _node.getYScaleControl().setValue(${y}); _node.getZScaleControl().setValue(${z});`,
      ),
    );
  }

  /** Set any combination of local position/rotation(Euler degrees)/scale in one round trip; omitted components are left untouched. */
  async setTransform(opts: {
    position?: [number, number, number];
    rotation?: [number, number, number];
    scale?: [number, number, number];
  }): Promise<void> {
    const lines: string[] = [];
    if (opts.position !== undefined) {
      const [x, y, z] = opts.position;
      lines.push(`_node.setLocalPos(new DzVec3(${x}, ${y}, ${z}));`);
    }
    if (opts.rotation !== undefined) {
      const [x, y, z] = opts.rotation;
      lines.push(
        `_node.getXRotControl().setValue(${x}); _node.getYRotControl().setValue(${y}); _node.getZRotControl().setValue(${z});`,
      );
    }
    if (opts.scale !== undefined) {
      const [x, y, z] = opts.scale;
      lines.push(
        `_node.getXScaleControl().setValue(${x}); _node.getYScaleControl().setValue(${y}); _node.getZScaleControl().setValue(${z});`,
      );
    }
    if (lines.length === 0) return;
    await this.client.execute(this.nodeScript(lines.join("\n")));
  }

  /** Set the world-space rotation using Euler angles in degrees. */
  async setRotation(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `_node.getXRotControl().setValue(${x}); _node.getYRotControl().setValue(${y}); _node.getZRotControl().setValue(${z});`,
      ),
    );
  }

  // ---------------------------------------------------------------------
  // Keyframes
  // ---------------------------------------------------------------------

  /** Write a real position keyframe at timeline `frame` (converted to ticks via `Scene.getTimeStep()`). */
  async setPositionAtFrame(frame: number, x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `var _tm = ${Math.trunc(frame)} * Scene.getTimeStep(); _node.setWSPos(_tm, new DzVec3(${x}, ${y}, ${z}));`,
      ),
    );
  }

  /** Write a real Euler rotation keyframe at timeline `frame`. See {@link setPositionAtFrame} for the tick conversion. */
  async setRotationAtFrame(frame: number, x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `var _tm = ${Math.trunc(frame)} * Scene.getTimeStep(); ` +
          `_node.getXRotControl().setDoubleValue(_tm, ${x}); ` +
          `_node.getYRotControl().setDoubleValue(_tm, ${y}); ` +
          `_node.getZRotControl().setDoubleValue(_tm, ${z});`,
      ),
    );
  }

  /** Remove all keyframes from this node's X/Y/Z position controls (call before a fresh {@link setPositionAtFrame} curve). */
  async clearPositionKeys(): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        "_node.getXPosControl().deleteAllKeys(); _node.getYPosControl().deleteAllKeys(); _node.getZPosControl().deleteAllKeys();",
      ),
    );
  }

  /** Remove all keyframes from this node's X/Y/Z rotation controls. See {@link clearPositionKeys}. */
  async clearRotationKeys(): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        "_node.getXRotControl().deleteAllKeys(); _node.getYRotControl().deleteAllKeys(); _node.getZRotControl().deleteAllKeys();",
      ),
    );
  }

  // ---------------------------------------------------------------------
  // Local-space transforms
  // ---------------------------------------------------------------------

  /** Local-space position as `{x, y, z}` (read-only). */
  async localPosition(): Promise<{ x: number; y: number; z: number } | null> {
    return (await this.client.execute(this.nodeScript("var p = _node.getLocalPos(); return {x: p.x, y: p.y, z: p.z};")))
      .value as { x: number; y: number; z: number } | null;
  }

  async setLocalPosition(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setLocalPos(new DzVec3(${x}, ${y}, ${z}));`));
  }

  /** Local-space rotation as `(x, y, z)` Euler degrees; exact inverse of {@link setLocalRotation}. */
  async localEuler(): Promise<[number, number, number] | null> {
    const result = (await this.client.execute(
      this.nodeScript(
        "return [_node.getXRotControl().getValue(), _node.getYRotControl().getValue(), _node.getZRotControl().getValue()];",
      ),
    )).value as number[] | null;
    if (result === null) return null;
    return [result[0], result[1], result[2]];
  }

  /** Local-space rotation as `{x, y, z, w}` quaternion (read-only). */
  async localRotation(): Promise<{ x: number; y: number; z: number; w: number } | null> {
    return (
      await this.client.execute(this.nodeScript("var r = _node.getLocalRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};"))
    ).value as { x: number; y: number; z: number; w: number } | null;
  }

  async setLocalRotation(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `_node.getXRotControl().setValue(${x}); _node.getYRotControl().setValue(${y}); _node.getZRotControl().setValue(${z});`,
      ),
    );
  }

  // ---------------------------------------------------------------------
  // Visibility
  // ---------------------------------------------------------------------

  /** General visibility flag, affecting both viewport and render unless overridden per-channel (read/write). */
  async visible(): Promise<boolean | null> {
    return (await this.client.execute(this.nodeScript("return _node.isVisible();"))).value as boolean | null;
  }

  async setVisible(value: boolean): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setVisible(${value ? "true" : "false"});`));
  }

  async isVisibleInRender(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isVisibleInRender();"))).value);
  }

  async setVisibleInRender(on: boolean): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setVisibleInRender(${on ? "true" : "false"});`));
  }

  async isVisibleInViewport(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isVisibleInViewport();"))).value);
  }

  async setVisibleInViewport(on: boolean): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setVisibleInViewport(${on ? "true" : "false"});`));
  }

  // ---------------------------------------------------------------------
  // Selection / scene state
  // ---------------------------------------------------------------------

  async isSelected(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isSelected();"))).value);
  }

  async select(on = true): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.select(${on ? "true" : "false"});`));
  }

  async isInScene(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isInScene();"))).value);
  }

  /** `true` if this node has no parent (top-level node). */
  async isRoot(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isRootNode();"))).value);
  }

  // ---------------------------------------------------------------------
  // Hierarchy
  // ---------------------------------------------------------------------

  /** Parent node in the scene hierarchy, or `null` for root nodes. */
  async parent(): Promise<DazNode | null> {
    const name = (
      await this.client.execute(this.nodeScript("var p = _node.getNodeParent(); return p ? p.getName() : null;"))
    ).value as string | null;
    if (name === null) return null;
    return new DazNode(this.client, { value: name, kind: "name" });
  }

  /** Direct child nodes. */
  async children(): Promise<DazNode[]> {
    const names =
      ((
        await this.client.execute(
          this.nodeScript(
            "var names = []; for (var i = 0; i < _node.getNumNodeChildren(); i++) { names.push(_node.getNodeChild(i).getName()); } return names;",
          ),
        )
      ).value as string[]) ?? [];
    return names.map((n) => new DazNode(this.client, { value: n, kind: "name" }));
  }

  /** Remove this node from the scene entirely. @returns `true` if found and removed. */
  async delete(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return Scene.removeNode(_node);"))).value);
  }

  /**
   * Move this node to a new position in the scene hierarchy via the
   * `removeNodeChild`/`addNodeChild` pattern.
   * @param preserveWorldTransform When `true` (default), keeps world-space transform, adjusting local transform to compensate.
   */
  async reparent(newParent: DazNode, opts: { preserveWorldTransform?: boolean } = {}): Promise<void> {
    const { preserveWorldTransform = true } = opts;
    const parentExpr = ScriptBuilder.findNodeExpr(newParent.identifier);
    const inPlace = preserveWorldTransform ? "true" : "false";
    const result = (
      await this.client.execute(
        this.nodeScript(`
            var _newParent = ${parentExpr};
            if (!_newParent) return "new parent not found";
            var _oldParent = _node.getNodeParent();
            if (_oldParent) _oldParent.removeNodeChild(_node, ${inPlace});
            var _err = _newParent.addNodeChild(_node, ${inPlace});
            var _errNum = _err ? _err.valueOf() : 0;
            return _errNum !== 0 ? ("DzError code " + _errNum) : null;
            `),
      )
    ).value as string | null;
    if (result) {
      throw new ScriptRuntimeError(`reparent failed: ${result}`);
    }
  }
}
