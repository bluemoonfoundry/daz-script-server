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
    await this.client.execute(ScriptBuilder.iife(`Scene.selectAllNodes(${on ? "true" : "false"});`));
  }
}
