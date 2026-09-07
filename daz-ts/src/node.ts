import type { DazClient } from "./client.js";
import { DazDForce } from "./dforce.js";
import { DazElement } from "./element.js";
import { NodeNotFoundError, ScriptRuntimeError } from "./exceptions.js";
import { DazMaterial } from "./material.js";
import { DazModifier } from "./modifier.js";
import { DazMorph } from "./morph.js";
import { DazProperty } from "./property.js";
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
    await this.client.execute(
      this.nodeScript(
        `_node.setWSPos(new DzVec3(${ScriptBuilder.serializeArg(x)}, ${ScriptBuilder.serializeArg(y)}, ${ScriptBuilder.serializeArg(z)}));`,
      ),
    );
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
        `_node.getXScaleControl().setValue(${ScriptBuilder.serializeArg(x)}); _node.getYScaleControl().setValue(${ScriptBuilder.serializeArg(y)}); _node.getZScaleControl().setValue(${ScriptBuilder.serializeArg(z)});`,
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
      lines.push(
        `_node.setLocalPos(new DzVec3(${ScriptBuilder.serializeArg(x)}, ${ScriptBuilder.serializeArg(y)}, ${ScriptBuilder.serializeArg(z)}));`,
      );
    }
    if (opts.rotation !== undefined) {
      const [x, y, z] = opts.rotation;
      lines.push(
        `_node.getXRotControl().setValue(${ScriptBuilder.serializeArg(x)}); _node.getYRotControl().setValue(${ScriptBuilder.serializeArg(y)}); _node.getZRotControl().setValue(${ScriptBuilder.serializeArg(z)});`,
      );
    }
    if (opts.scale !== undefined) {
      const [x, y, z] = opts.scale;
      lines.push(
        `_node.getXScaleControl().setValue(${ScriptBuilder.serializeArg(x)}); _node.getYScaleControl().setValue(${ScriptBuilder.serializeArg(y)}); _node.getZScaleControl().setValue(${ScriptBuilder.serializeArg(z)});`,
      );
    }
    if (lines.length === 0) return;
    await this.client.execute(this.nodeScript(lines.join("\n")));
  }

  /** Set the world-space rotation using Euler angles in degrees. */
  async setRotation(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `_node.getXRotControl().setValue(${ScriptBuilder.serializeArg(x)}); _node.getYRotControl().setValue(${ScriptBuilder.serializeArg(y)}); _node.getZRotControl().setValue(${ScriptBuilder.serializeArg(z)});`,
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
        `var _tm = ${ScriptBuilder.serializeArg(Math.trunc(frame))} * Scene.getTimeStep(); _node.setWSPos(_tm, new DzVec3(${ScriptBuilder.serializeArg(x)}, ${ScriptBuilder.serializeArg(y)}, ${ScriptBuilder.serializeArg(z)}));`,
      ),
    );
  }

  /** Write a real Euler rotation keyframe at timeline `frame`. See {@link setPositionAtFrame} for the tick conversion. */
  async setRotationAtFrame(frame: number, x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nodeScript(
        `var _tm = ${ScriptBuilder.serializeArg(Math.trunc(frame))} * Scene.getTimeStep(); ` +
          `_node.getXRotControl().setDoubleValue(_tm, ${ScriptBuilder.serializeArg(x)}); ` +
          `_node.getYRotControl().setDoubleValue(_tm, ${ScriptBuilder.serializeArg(y)}); ` +
          `_node.getZRotControl().setDoubleValue(_tm, ${ScriptBuilder.serializeArg(z)});`,
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
    await this.client.execute(
      this.nodeScript(
        `_node.setLocalPos(new DzVec3(${ScriptBuilder.serializeArg(x)}, ${ScriptBuilder.serializeArg(y)}, ${ScriptBuilder.serializeArg(z)}));`,
      ),
    );
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
        `_node.getXRotControl().setValue(${ScriptBuilder.serializeArg(x)}); _node.getYRotControl().setValue(${ScriptBuilder.serializeArg(y)}); _node.getZRotControl().setValue(${ScriptBuilder.serializeArg(z)});`,
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
    await this.client.execute(this.nodeScript(`_node.setVisible(${ScriptBuilder.serializeArg(value)});`));
  }

  async isVisibleInRender(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isVisibleInRender();"))).value);
  }

  async setVisibleInRender(on: boolean): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setVisibleInRender(${ScriptBuilder.serializeArg(on)});`));
  }

  async isVisibleInViewport(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isVisibleInViewport();"))).value);
  }

  async setVisibleInViewport(on: boolean): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.setVisibleInViewport(${ScriptBuilder.serializeArg(on)});`));
  }

  // ---------------------------------------------------------------------
  // Selection / scene state
  // ---------------------------------------------------------------------

  async isSelected(): Promise<boolean> {
    return Boolean((await this.client.execute(this.nodeScript("return _node.isSelected();"))).value);
  }

  async select(on = true): Promise<void> {
    await this.client.execute(this.nodeScript(`_node.select(${ScriptBuilder.serializeArg(on)});`));
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
    const inPlace = ScriptBuilder.serializeArg(preserveWorldTransform);
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

  // ---------------------------------------------------------------------
  // Modifiers / Materials / Fitting / Bounding box
  // ---------------------------------------------------------------------

  private modifierClassFor(className: string): typeof DazModifier {
    if (className === "DzMorph") return DazMorph;
    if (className === "DzDForceModifier") return DazDForce;
    return DazModifier;
  }

  private modifierLocator(modifierName: string): string {
    return (
      `(function(){` +
      ` var _o = ${this.locator};` +
      ` _o = _o ? _o.getObject() : null;` +
      ` return _o ? _o.findModifier(${ScriptBuilder.escapeString(modifierName)}) : null;` +
      `})()`
    );
  }

  /** Return all modifiers (morphs, constraints, etc.) on this node, typed via the DzMorph/DzDForceModifier dispatch table. */
  async modifiers(): Promise<DazModifier[]> {
    const items =
      ((await this.client.execute(
        this.nodeScript(`
            var obj = _node.getObject();
            if (!obj) return [];
            var mods = [];
            for (var i = 0; i < obj.getNumModifiers(); i++) {
                var m = obj.getModifier(i);
                mods.push({name: m.getName(), className: m.className()});
            }
            return mods;
            `),
      )).value as Array<{ name: string; className: string }>) ?? [];
    return items.map((item) => {
      const Cls = this.modifierClassFor(item.className);
      return new Cls(this.client, this.modifierLocator(item.name));
    });
  }

  /** Find a modifier by internal name. */
  async findModifier(name: string): Promise<DazModifier | null> {
    const result = (await this.client.execute(
      this.nodeScript(`
            var obj = _node.getObject();
            if (!obj) return null;
            var m = obj.findModifier(${ScriptBuilder.escapeString(name)});
            return m ? {name: m.getName(), className: m.className()} : null;
            `),
    )).value as { name: string; className: string } | null;
    if (result === null) return null;
    const Cls = this.modifierClassFor(result.className);
    return new Cls(this.client, this.modifierLocator(result.name));
  }

  /** Find a modifier by its user-visible label (the name shown in the DAZ UI), matching {@link findModifier}'s internal-name lookup on label instead. */
  async findModifierByLabel(label: string): Promise<DazModifier | null> {
    const result = (await this.client.execute(
      this.nodeScript(`
            var obj = _node.getObject();
            if (!obj) return null;
            for (var i = 0; i < obj.getNumModifiers(); i++) {
                var m = obj.getModifier(i);
                if (m.getLabel() === ${ScriptBuilder.escapeString(label)}) {
                    return {name: m.getName(), className: m.className()};
                }
            }
            return null;
            `),
    )).value as { name: string; className: string } | null;
    if (result === null) return null;
    const Cls = this.modifierClassFor(result.className);
    return new Cls(this.client, this.modifierLocator(result.name));
  }

  private materialLocator(materialName: string): string {
    return (
      `(function(){` +
      ` var _n = ${this.locator};` +
      ` if (!_n) return null;` +
      ` var _o = _n.getObject();` +
      ` if (!_o) return null;` +
      ` var _s = _o.getCurrentShape();` +
      ` return _s ? _s.findMaterial(${ScriptBuilder.escapeString(materialName)}) : null;` +
      `})()`
    );
  }

  /** Return all surface materials on this node's current shape. */
  async materials(): Promise<DazMaterial[]> {
    const names =
      ((await this.client.execute(
        this.nodeScript(`
            var obj = _node.getObject();
            if (!obj) return [];
            var shape = obj.getCurrentShape();
            if (!shape) return [];
            var names = [];
            for (var i = 0; i < shape.getNumMaterials(); i++) {
                names.push(shape.getMaterial(i).getName());
            }
            return names;
            `),
      )).value as string[]) ?? [];
    return names.map((n) => new DazMaterial(this.client, this.materialLocator(n)));
  }

  /** Find a surface material by name. */
  async findMaterial(name: string): Promise<DazMaterial | null> {
    const result = (await this.client.execute(
      this.nodeScript(`
            var obj = _node.getObject();
            if (!obj) return null;
            var shape = obj.getCurrentShape();
            if (!shape) return null;
            var m = shape.findMaterial(${ScriptBuilder.escapeString(name)});
            return m ? m.getName() : null;
            `),
    )).value as string | null;
    if (result === null) return null;
    return new DazMaterial(this.client, this.materialLocator(result));
  }

  /**
   * Find a node-level property by internal name via `DzNode::findProperty` —
   * covers pose controls/FACS dials that are not geometry modifiers and so
   * are invisible to {@link findModifier}.
   */
  async findProperty(name: string): Promise<DazProperty | null> {
    const locator = `(function(){var _n=${this.locator};return _n ? _n.findProperty(${ScriptBuilder.escapeString(
      name,
    )}) : null;})()`;
    const exists = (await this.client.execute(ScriptBuilder.iife(`return !!(${locator});`))).value;
    if (!exists) return null;
    return DazProperty.fromLocator(this.client, locator);
  }

  /** Like {@link findProperty} but matches `getLabel()` instead of `getName()`. */
  async findPropertyByLabel(label: string): Promise<DazProperty | null> {
    const locator = `(function(){var _n=${this.locator};return _n ? _n.findPropertyByLabel(${ScriptBuilder.escapeString(
      label,
    )}) : null;})()`;
    const exists = (await this.client.execute(ScriptBuilder.iife(`return !!(${locator});`))).value;
    if (!exists) return null;
    return DazProperty.fromLocator(this.client, locator);
  }

  /** Only the morph modifiers on this node (convenience filter over {@link modifiers}). */
  async morphs(): Promise<DazMorph[]> {
    return (await this.modifiers()).filter((m): m is DazMorph => m instanceof DazMorph);
  }

  /** Only the dForce simulation modifiers on this node (convenience filter over {@link modifiers}). */
  async dforceModifiers(): Promise<DazDForce[]> {
    return (await this.modifiers()).filter((m): m is DazDForce => m instanceof DazDForce);
  }

  /** World-space axis-aligned bounding box, or `null` if the node has no geometry. */
  async boundingBox(): Promise<{ min: { x: number; y: number; z: number }; max: { x: number; y: number; z: number } } | null> {
    const script = this.nodeScript(
      "var bb = _node.getWSBoundingBox(); return {min: {x: bb.min.x, y: bb.min.y, z: bb.min.z}, max: {x: bb.max.x, y: bb.max.y, z: bb.max.z}};",
    );
    return (await this.client.execute(script)).value as {
      min: { x: number; y: number; z: number };
      max: { x: number; y: number; z: number };
    } | null;
  }

  /**
   * Fit this clothing/hair/prop node to a base figure, preferring
   * `setFollowTarget`/`followSkeleton` (conforming items) and falling back
   * to parenting (plain props). @returns which DazScript API was used.
   */
  async fitTo(figure: DazNode): Promise<string> {
    const figureExpr = ScriptBuilder.findNodeExpr(figure.identifier);
    const result = (await this.client.execute(
      this.nodeScript(`
            var _figure = ${figureExpr};
            if (!_figure) return null;
            var _method;
            if (typeof _node.setFollowTarget === 'function') {
                _node.setFollowTarget(_figure);
                _method = "setFollowTarget";
            } else if (typeof _node.followSkeleton === 'function') {
                _node.followSkeleton(_figure);
                _method = "followSkeleton";
            } else {
                _figure.addNodeChild(_node, true);
                _method = "addNodeChild";
            }
            return _method;
            `),
    )).value as string | null;
    if (result === null) {
      throw new NodeNotFoundError("Could not fit node to figure: one of the nodes was not found.");
    }
    return result;
  }

  /** Remove this node's fitting relationship with its figure (follow-target and/or skeleton parenting). */
  async unfit(): Promise<{ previousFigure: string | null; actions: string[] }> {
    const script = this.nodeScript(`
            var _prevFigure = null;
            var _actions = [];
            if (typeof _node.getFollowTarget === 'function') {
                var _ft = _node.getFollowTarget();
                if (_ft) {
                    _prevFigure = _ft.getName();
                    if (typeof _node.setFollowTarget === 'function') {
                        _node.setFollowTarget(null);
                        _actions.push("cleared follow target");
                    }
                }
            }
            var _parent = _node.getNodeParent();
            if (_parent && _parent.inherits && _parent.inherits("DzSkeleton")) {
                _prevFigure = _prevFigure || _parent.getName();
                _parent.removeNodeChild(_node, true);
                _actions.push("detached from parent");
            }
            return {previous_figure: _prevFigure, actions: _actions};
        `);
    const result = (await this.client.execute(script)).value as
      | { previous_figure: string | null; actions: string[] }
      | null;
    return { previousFigure: result?.previous_figure ?? null, actions: result?.actions ?? [] };
  }

  /** Every clothing/hair/prop node fitted to this figure (following it, or directly parented to it). */
  async fittedItems(): Promise<DazNode[]> {
    const names =
      ((await this.client.execute(
        this.nodeScript(`
            var _fitted = [];
            var _numNodes = Scene.getNumNodes();
            for (var i = 0; i < _numNodes; i++) {
                var _n = Scene.getNode(i);
                if (!_n || _n === _node) continue;
                var _isFitted = false;
                if (typeof _n.getFollowTarget === 'function') {
                    var _ft = _n.getFollowTarget();
                    if (_ft && _ft.elementID === _node.elementID) _isFitted = true;
                }
                if (!_isFitted && typeof _n.getNodeParent === 'function') {
                    var _p = _n.getNodeParent();
                    if (_p && _p.elementID === _node.elementID) _isFitted = true;
                }
                if (_isFitted) _fitted.push(_n.getName());
            }
            return _fitted;
            `),
      )).value as string[]) ?? [];
    return names.map((n) => new DazNode(this.client, { value: n, kind: "name" }));
  }

  /** Total vertex count of this node's current geometry, or `null`. */
  async geometryVertexCount(): Promise<number | null> {
    const script = this.nodeScript(`
            var obj = _node.getObject();
            if (!obj) return null;
            var shape = obj.getCurrentShape();
            if (!shape) return null;
            var geo = shape.getGeometry();
            if (!geo) return null;
            return geo.getNumVertices();
        `);
    return (await this.client.execute(script)).value as number | null;
  }
}
