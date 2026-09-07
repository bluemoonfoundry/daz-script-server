import type { DazClient } from "./client.js";
import { DazNode, type NodeIdentifier } from "./node.js";

/**
 * Proxy for a `DzSkeleton` (a hierarchical structure of bones).
 * This stub will be extended in Task 10 with full skeleton-specific methods.
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
}
