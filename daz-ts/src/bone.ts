import type { DazClient } from "./client.js";
import { DazNode, type NodeIdentifier } from "./node.js";
import { ScriptBuilder } from "./scriptBuilder.js";

/**
 * Proxy for a `DzBone` (a single joint within a {@link DazSkeleton}).
 * Extends `DazNode` with bone-specific rotation helpers.
 */
export class DazBone extends DazNode {
  /**
   * Construct from a standard scene node lookup by identifier.
   */
  constructor(client: DazClient, identifier: NodeIdentifier);
  /**
   * Construct from a pre-built skeleton-relative locator (used by {@link fromLocator}).
   * The identifier's value provides the bone's name.
   */
  constructor(client: DazClient, identifier: NodeIdentifier, locator: string);
  constructor(client: DazClient, identifier: NodeIdentifier, locator?: string) {
    if (locator !== undefined) {
      super(client, identifier, locator);
    } else {
      super(client, identifier);
    }
  }

  /** Construct a `DazBone` from a pre-built skeleton-relative locator (see `DazSkeleton`'s bone lookup). */
  static fromLocator(client: DazClient, locator: string, name: string): DazBone {
    return new DazBone(client, { value: name, kind: "name" }, locator);
  }

  private nb(body: string): string {
    return ScriptBuilder.nodeBodyFromLocator(this.locator, body);
  }

  /** Local-space rotation as `(x, y, z)` Euler degrees; exact inverse of {@link setLocalRotation}. */
  async localEuler(): Promise<[number, number, number] | null> {
    const result = (await this.client.execute(
      this.nb(
        "return [_node.getXRotControl().getValue(), _node.getYRotControl().getValue(), _node.getZRotControl().getValue()];",
      ),
    )).value as number[] | null;
    if (result === null) return null;
    return [result[0], result[1], result[2]];
  }

  /** Local-space rotation as `{x, y, z, w}` quaternion (read-only). */
  async localRotation(): Promise<{ x: number; y: number; z: number; w: number } | null> {
    return (await this.client.execute(this.nb("var r = _node.getLocalRot(); return {x: r.x, y: r.y, z: r.z, w: r.w};")))
      .value as { x: number; y: number; z: number; w: number } | null;
  }

  async setLocalRotation(x: number, y: number, z: number): Promise<void> {
    await this.client.execute(
      this.nb(
        `_node.getXRotControl().setValue(${ScriptBuilder.serializeArg(x)}); _node.getYRotControl().setValue(${ScriptBuilder.serializeArg(y)}); _node.getZRotControl().setValue(${ScriptBuilder.serializeArg(z)});`,
      ),
    );
  }

  /** Local-space position as `{x, y, z}` (read-only). */
  async localPosition(): Promise<{ x: number; y: number; z: number } | null> {
    return (await this.client.execute(this.nb("var p = _node.getLocalPos(); return {x: p.x, y: p.y, z: p.z};")))
      .value as { x: number; y: number; z: number } | null;
  }

  /** Rotation order string (e.g. `"XYZ"`), or `null`. */
  async rotationOrder(): Promise<string | null> {
    return (await this.client.execute(this.nb("return _node.getRotationOrder();"))) .value as string | null;
  }

  /** The parent skeleton, or `null`. */
  async getSkeleton(): Promise<import("./skeleton.js").DazSkeleton | null> {
    const name = (await this.client.execute(this.nb("var s = _node.getSkeleton(); return s ? s.getName() : null;")))
      .value as string | null;
    if (name === null) return null;
    const { DazSkeleton } = await import("./skeleton.js");
    return new DazSkeleton(this.client, { value: name, kind: "name" });
  }
}
