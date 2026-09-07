import { DazCamera } from "./camera.js";
import { DazClient } from "./client.js";
import { NodeNotFoundError } from "./exceptions.js";
import { DazLight } from "./light.js";
import { DazNode, type NodeIdentifier } from "./node.js";
import { ScriptBuilder } from "./scriptBuilder.js";
import { DazSkeleton } from "./skeleton.js";

const LIGHT_TYPE_CLASSES: Record<string, string> = {
  spot: "DzSpotLight",
  point: "DzPointLight",
  distant: "DzDistantLight",
};

function sleep(seconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
}

/**
 * High-level proxy for the active DAZ Studio scene (`Scene` global) — the
 * primary entry point for inspecting and manipulating the scene.
 *
 * This file covers node/camera/light/skeleton factories and selection
 * (Phase 2 Task 12); later tasks (13-14) add bulk scene snapshots and
 * I/O/playback/undo/dForce methods to this same class.
 */
export class DazScene {
  private readonly client: DazClient;

  constructor(client?: DazClient) {
    this.client = client ?? new DazClient();
  }

  // ---------------------------------------------------------------------
  // Node factories
  // ---------------------------------------------------------------------

  /** All top-level and child nodes in the scene, typed via `inherits()` (DazSkeleton/DazCamera/DazLight/DazNode), scene-panel order. */
  async nodes(): Promise<DazNode[]> {
    const script = ScriptBuilder.iife(`
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
        `);
    const items = ((await this.client.execute(script)).value as Array<{ name: string; className: string }>) ?? [];
    return items.map((item) => {
      const identifier: NodeIdentifier = { value: item.name, kind: "name" };
      if (item.className === "DzSkeleton") return new DazSkeleton(this.client, identifier);
      if (item.className === "DzCamera") return new DazCamera(this.client, identifier);
      if (item.className === "DzLight") return new DazLight(this.client, identifier);
      return new DazNode(this.client, identifier);
    });
  }

  /** Find a scene node by internal name. */
  async findNode(name: string): Promise<DazNode> {
    const exists = ScriptBuilder.iife(`return !!Scene.findNode(${ScriptBuilder.escapeString(name)});`);
    if (!(await this.client.execute(exists)).value) {
      throw new NodeNotFoundError(`Node not found: ${JSON.stringify(name)}`);
    }
    return new DazNode(this.client, { value: name, kind: "name" });
  }

  /** Find a scene node by its user-visible label. Anchored to the internal *name*, so it stays stable if the label later changes. */
  async findNodeByLabel(label: string): Promise<DazNode> {
    const exists = ScriptBuilder.iife(`return !!Scene.findNodeByLabel(${ScriptBuilder.escapeString(label)});`);
    if (!(await this.client.execute(exists)).value) {
      throw new NodeNotFoundError(`Node with label not found: ${JSON.stringify(label)}`);
    }
    return new DazNode(this.client, { value: label, kind: "label" });
  }

  async numNodes(): Promise<number> {
    return ((await this.client.execute(ScriptBuilder.iife("return Scene.getNumNodes();"))).value as number) ?? 0;
  }

  // ---------------------------------------------------------------------
  // Camera factories
  // ---------------------------------------------------------------------

  async cameras(): Promise<DazCamera[]> {
    const script = ScriptBuilder.iife(
      "var names = []; for (var i = 0; i < Scene.getNumCameras(); i++) { names.push(Scene.getCamera(i).getName()); } return names;",
    );
    const names = ((await this.client.execute(script)).value as string[]) ?? [];
    return names.map((n) => new DazCamera(this.client, { value: n, kind: "name" }));
  }

  /** Find a camera by its user-visible label (same value accepted by `render()`'s `camera` parameter in Phase 3). */
  async findCameraByLabel(label: string): Promise<DazCamera> {
    const exists = ScriptBuilder.iife(`return !!Scene.findCameraByLabel(${ScriptBuilder.escapeString(label)});`);
    if (!(await this.client.execute(exists)).value) {
      throw new NodeNotFoundError(`Camera with label not found: ${JSON.stringify(label)}`);
    }
    return new DazCamera(this.client, { value: label, kind: "label" });
  }

  /** Create a new basic camera node and add it to the scene. `name` omitted → DAZ Studio assigns its default (de-duplicated) name. */
  async createCamera(name?: string): Promise<DazCamera> {
    const nameExpr = name !== undefined ? ScriptBuilder.escapeString(name) : "null";
    const script = ScriptBuilder.iife(`
            var cam = new DzBasicCamera();
            if (${nameExpr} !== null) cam.setName(${nameExpr});
            Scene.addNode(cam);
            return cam.getName();
        `);
    const createdName = (await this.client.execute(script)).value as string;
    return new DazCamera(this.client, { value: createdName, kind: "name" });
  }

  // ---------------------------------------------------------------------
  // Light factories
  // ---------------------------------------------------------------------

  async lights(): Promise<DazLight[]> {
    const script = ScriptBuilder.iife(
      "var names = []; for (var i = 0; i < Scene.getNumLights(); i++) { names.push(Scene.getLight(i).getName()); } return names;",
    );
    const names = ((await this.client.execute(script)).value as string[]) ?? [];
    return names.map((n) => new DazLight(this.client, { value: n, kind: "name" }));
  }

  /** Create a new light node (`"spot"`/`"point"`/`"distant"`) and add it to the scene. */
  async createLight(lightType: "spot" | "point" | "distant", name?: string): Promise<DazLight> {
    const className = LIGHT_TYPE_CLASSES[lightType];
    if (className === undefined) {
      throw new Error(`Unknown light_type ${JSON.stringify(lightType)}; expected one of ${JSON.stringify(Object.keys(LIGHT_TYPE_CLASSES).sort())}`);
    }
    const nameExpr = name !== undefined ? ScriptBuilder.escapeString(name) : "null";
    const script = ScriptBuilder.iife(`
            var light = new ${className}();
            if (${nameExpr} !== null) light.setName(${nameExpr});
            Scene.addNode(light);
            return light.getName();
        `);
    const createdName = (await this.client.execute(script)).value as string;
    return new DazLight(this.client, { value: createdName, kind: "name" });
  }

  async findLightByLabel(label: string): Promise<DazLight> {
    const exists = ScriptBuilder.iife(`return !!Scene.findLightByLabel(${ScriptBuilder.escapeString(label)});`);
    if (!(await this.client.execute(exists)).value) {
      throw new NodeNotFoundError(`Light with label not found: ${JSON.stringify(label)}`);
    }
    return new DazLight(this.client, { value: label, kind: "label" });
  }

  // ---------------------------------------------------------------------
  // Skeleton factories
  // ---------------------------------------------------------------------

  async skeletons(): Promise<DazSkeleton[]> {
    const script = ScriptBuilder.iife(
      "var names = []; var skels = Scene.getSkeletonList(); for (var i = 0; i < skels.length; i++) { names.push(skels[i].getName()); } return names;",
    );
    const names = ((await this.client.execute(script)).value as string[]) ?? [];
    return names.map((n) => new DazSkeleton(this.client, { value: n, kind: "name" }));
  }

  /**
   * Find a skeleton by internal name, retrying `Scene.getSkeletonList()` up
   * to `retryAttempts` times (default 3, `retryDelay * attemptNumber`
   * seconds apart, default base 0.15s) — `getSkeletonList()` has been
   * observed to transiently omit a present skeleton under main-thread load
   * (daz-script-server-xtkd); a momentary miss is retried rather than
   * immediately raised. Pass `retryAttempts: 1` to disable retrying.
   */
  async findSkeleton(name: string, opts: { retryAttempts?: number; retryDelay?: number } = {}): Promise<DazSkeleton> {
    const { retryAttempts = 3, retryDelay = 0.15 } = opts;
    const lookup = ScriptBuilder.iife(`
            var skels = Scene.getSkeletonList();
            for (var i = 0; i < skels.length; i++) {
                if (skels[i].getName() === ${ScriptBuilder.escapeString(name)}) return true;
            }
            return false;
        `);
    let found = false;
    for (let attempt = 0; attempt < retryAttempts; attempt++) {
      if ((await this.client.execute(lookup)).value) {
        found = true;
        break;
      }
      if (attempt < retryAttempts - 1) {
        await sleep(retryDelay * (attempt + 1));
      }
    }
    if (!found) {
      const hint = ScriptBuilder.iife(`
                var info = [];
                var skels = Scene.getSkeletonList();
                for (var i = 0; i < skels.length; i++) {
                    info.push(skels[i].getName() + "|" + skels[i].getLabel());
                }
                return info;
            `);
      const pairs = ((await this.client.execute(hint)).value as string[]) ?? [];
      if (pairs.length > 0) {
        const available = pairs
          .map((entry) => {
            const [n, l] = entry.split("|");
            return `${JSON.stringify(n)} (label: ${JSON.stringify(l)})`;
          })
          .join(", ");
        throw new NodeNotFoundError(
          `Skeleton not found: ${JSON.stringify(name)}. Available skeletons: ${available}. ` +
            `Tip: use findSkeletonByLabel() to search by the Scene-panel label.`,
        );
      }
      throw new NodeNotFoundError(`Skeleton not found: ${JSON.stringify(name)} (no skeletons in scene).`);
    }
    return new DazSkeleton(this.client, { value: name, kind: "name" });
  }

  /** Find a skeleton by its user-visible label. Kept as `kind: "label"` — same-asset figures share an internal name, so name-based lookup would collapse distinct figures into one. */
  async findSkeletonByLabel(label: string): Promise<DazSkeleton> {
    const exists = ScriptBuilder.iife(`return !!Scene.findSkeletonByLabel(${ScriptBuilder.escapeString(label)});`);
    if (!(await this.client.execute(exists)).value) {
      throw new NodeNotFoundError(`Skeleton with label not found: ${JSON.stringify(label)}`);
    }
    return new DazSkeleton(this.client, { value: label, kind: "label" });
  }

  async numSkeletons(): Promise<number> {
    return ((await this.client.execute(ScriptBuilder.iife("return Scene.getNumSkeletons();"))).value as number) ?? 0;
  }

  // ---------------------------------------------------------------------
  // Selection
  // ---------------------------------------------------------------------

  async selectedNodes(): Promise<DazNode[]> {
    const script = ScriptBuilder.iife(`
            var nodes = Scene.getSelectedNodeList();
            var names = [];
            for (var i = 0; i < nodes.length; i++) {
                names.push(nodes[i].getName());
            }
            return names;
        `);
    const names = ((await this.client.execute(script)).value as string[]) ?? [];
    return names.map((n) => new DazNode(this.client, { value: n, kind: "name" }));
  }

  async primarySelection(): Promise<DazNode | null> {
    const name = (await this.client.execute(ScriptBuilder.iife("var n = Scene.getPrimarySelection(); return n ? n.getName() : null;")))
      .value as string | null;
    if (name === null) return null;
    return new DazNode(this.client, { value: name, kind: "name" });
  }

  async setPrimarySelection(node: DazNode): Promise<void> {
    const findExpr = ScriptBuilder.findNodeExpr(node.identifier);
    await this.client.execute(ScriptBuilder.iife(`Scene.setPrimarySelection(${findExpr});`));
  }

  async selectAll(on = true): Promise<void> {
    await this.client.execute(ScriptBuilder.iife(`Scene.selectAllNodes(${ScriptBuilder.serializeArg(on)});`));
  }

  // ---------------------------------------------------------------------
  // Bulk scene snapshots
  // ---------------------------------------------------------------------

  /**
   * Full skeleton and bone metadata for the scene in one HTTP call.
   * @param skeletonLabels Optional subset of skeleton names/labels to include; omit to return every skeleton.
   */
  async sceneSnapshot(skeletonLabels?: string[]): Promise<Array<Record<string, unknown>>> {
    const filterJs = skeletonLabels !== undefined ? JSON.stringify(skeletonLabels) : "null";
    const script = ScriptBuilder.iife(`
            var _filter = ${filterJs};
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
        `);
    return ((await this.client.execute(script)).value as Array<Record<string, unknown>>) ?? [];
  }

  /** World-space transforms (`name`/`label`/`position`/`rotation`/`visible`) for every node, in one HTTP call. */
  async allNodeTransforms(): Promise<Array<Record<string, unknown>>> {
    const script = ScriptBuilder.iife(`
            var result = [];
            for (var i = 0; i < Scene.getNumNodes(); i++) {
                var n = Scene.getNode(i);
                var pos = n.getWSPos();
                var rot = n.getWSRot();
                result.push({
                    name: n.getName(),
                    label: n.getLabel(),
                    position: [pos.x, pos.y, pos.z],
                    rotation: [rot.x, rot.y, rot.z],
                    visible: n.isVisible()
                });
            }
            return result;
        `);
    return ((await this.client.execute(script)).value as Array<Record<string, unknown>>) ?? [];
  }

  /** Full scene hierarchy as nested `{name, label, children}` dicts, one entry per root-level node. */
  async nodeTree(): Promise<Array<Record<string, unknown>>> {
    const script = ScriptBuilder.iife(`
            function nodeToDict(n) {
                var children = [];
                for (var i = 0; i < n.getNumNodeChildren(); i++) {
                    children.push(nodeToDict(n.getNodeChild(i)));
                }
                return {name: n.getName(), label: n.getLabel(), children: children};
            }
            var roots = [];
            for (var i = 0; i < Scene.getNumNodes(); i++) {
                var n = Scene.getNode(i);
                if (!n.getNodeParent()) roots.push(nodeToDict(n));
            }
            return roots;
        `);
    return ((await this.client.execute(script)).value as Array<Record<string, unknown>>) ?? [];
  }

  /**
   * Descendant tree rooted at a single node (searched by label first, then internal name), with an optional recursion-depth limit.
   * @throws NodeNotFoundError if `root` cannot be found.
   */
  async nodeHierarchy(opts: { root?: string; maxDepth?: number } = {}): Promise<{
    node: string;
    hierarchy: Record<string, unknown> | null;
    totalDescendants: number;
  }> {
    const rootJson = JSON.stringify(opts.root ?? null);
    const depthJs = opts.maxDepth ? String(Math.trunc(opts.maxDepth)) : "0";
    const script = ScriptBuilder.iife(`
            var _rootLabel = ${rootJson};
            var _node = Scene.findNodeByLabel(_rootLabel);
            if (!_node) _node = Scene.findNode(_rootLabel);
            if (!_node) return null;

            var _maxDepth = ${depthJs};
            var _totalDescendants = 0;

            function _build(n, depth) {
                if (_maxDepth > 0 && depth >= _maxDepth) return null;
                var info = {label: n.getLabel(), name: n.getName(), type: n.className()};
                var children = [];
                for (var i = 0; i < n.getNumNodeChildren(); i++) {
                    _totalDescendants++;
                    var childInfo = _build(n.getNodeChild(i), depth + 1);
                    if (childInfo) children.push(childInfo);
                }
                if (children.length > 0) info.children = children;
                return info;
            }

            var hierarchy = _build(_node, 0);
            return {node: _node.getLabel(), hierarchy: hierarchy, total_descendants: _totalDescendants};
        `);
    const result = (await this.client.execute(script)).value as
      | { node: string; hierarchy: Record<string, unknown> | null; total_descendants: number }
      | null;
    if (result === null) {
      throw new NodeNotFoundError(`Node not found: ${JSON.stringify(opts.root)}`);
    }
    return { node: result.node, hierarchy: result.hierarchy, totalDescendants: result.total_descendants };
  }

  /** Lightweight top-level snapshot: root-level figures, cameras, lights, scene file, and primary selection. Follower figures (parented under another figure) are excluded from `figures`. */
  async overview(): Promise<Record<string, unknown>> {
    const script = ScriptBuilder.iife(`
            var figures = [];
            for (var i = 0; i < Scene.getNumSkeletons(); i++) {
                var s = Scene.getSkeleton(i);
                var parent = s.getNodeParent();
                if (parent && parent.inherits("DzFigure")) continue;
                figures.push({name: s.getName(), label: s.getLabel(), type: s.className()});
            }
            var cameras = [];
            for (var i = 0; i < Scene.getNumCameras(); i++) {
                var c = Scene.getCamera(i);
                cameras.push({name: c.getName(), label: c.getLabel()});
            }
            var lights = [];
            for (var i = 0; i < Scene.getNumLights(); i++) {
                var l = Scene.getLight(i);
                lights.push({name: l.getName(), label: l.getLabel(), type: l.className()});
            }
            var sel = Scene.getPrimarySelection();
            return {
                scene_file: Scene.getFilename(),
                selected_node: sel ? sel.getLabel() : null,
                figures: figures,
                cameras: cameras,
                lights: lights,
                total_nodes: Scene.getNumNodes()
            };
        `);
    return (
      (await this.client.execute(script)).value as Record<string, unknown> | null
    ) ?? { scene_file: "", selected_node: null, figures: [], cameras: [], lights: [], total_nodes: 0 };
  }
}
