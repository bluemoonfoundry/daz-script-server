import type { DazClient } from "./client.js";
import { DazElement } from "./element.js";
import { BoundingBox, Vec3 } from "./math3.js";
import type { NodeIdentifier } from "./node.js";
import { ScriptBuilder } from "./scriptBuilder.js";

type BBoxDict = { min: { x: number; y: number; z: number }; max: { x: number; y: number; z: number } };

/** Chunked access to vertices, faces, normals, UV sets, and face/material groups for a node's current shape's geometry. */
export class DazGeometry extends DazElement {
  private readonly nodeExpr: string;

  constructor(client: DazClient, identifier: NodeIdentifier) {
    const nodeExpr = ScriptBuilder.findNodeExpr(identifier);
    const locator =
      `(function(){` +
      `var n = ${nodeExpr};` +
      `if (!n) return null;` +
      `var obj = n.getObject();` +
      `if (!obj) return null;` +
      `var sh = obj.getCurrentShape();` +
      `return sh ? sh.getGeometry() : null;` +
      `})()`;
    super(client, locator);
    this.nodeExpr = nodeExpr;
  }

  // ---------------------------------------------------------------------
  // Vertex / facet counts
  // ---------------------------------------------------------------------

  /** Total number of vertices in the mesh (read-only). */
  async vertexCount(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var g = ${this.locator}; return g ? g.getNumVertices() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  /** Total number of faces (triangles + quads, read-only). */
  async facetCount(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var g = ${this.locator}; return g ? g.getNumFacets() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  // ---------------------------------------------------------------------
  // Chunked vertex access
  // ---------------------------------------------------------------------

  /** One chunk of vertex positions. `start`/`count` default to `0`/`5000`. */
  async vertexPositions(start = 0, count = 5000): Promise<{ total: number; start: number; count: number; vertices: number[][] }> {
    const startJs = ScriptBuilder.serializeArg(start);
    const countJs = ScriptBuilder.serializeArg(count);
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g) return null;
            var total = g.getNumVertices();
            var end = Math.min(${startJs} + ${countJs}, total);
            var verts = [];
            for (var i = ${startJs}; i < end; i++) {
                var v = g.getVertex(i);
                verts.push([v.x, v.y, v.z]);
            }
            return {total: total, start: ${startJs}, count: verts.length, vertices: verts};
        `);
    return ((await this.client.execute(script)).value as { total: number; start: number; count: number; vertices: number[][] }) ?? {
      total: 0,
      start,
      count: 0,
      vertices: [],
    };
  }

  /** Every vertex position, auto-paginating by `chunkSize` (default `5000`). */
  async vertexPositionsAll(chunkSize = 5000): Promise<number[][]> {
    const all: number[][] = [];
    let offset = 0;
    let total = Infinity;
    while (offset < total) {
      const chunk = await this.vertexPositions(offset, chunkSize);
      total = chunk.total;
      if (chunk.vertices.length === 0) break;
      all.push(...chunk.vertices);
      offset += chunk.vertices.length;
    }
    return all;
  }

  // ---------------------------------------------------------------------
  // Faces / normals / UVs
  // ---------------------------------------------------------------------

  /** One chunk of face vertex indices; each entry is `[v0,v1,v2]` (tri) or `[v0,v1,v2,v3]` (quad). `start`/`count` default `0`/`1000`. */
  async faceVertexIndices(start = 0, count = 1000): Promise<{ total: number; start: number; facets: number[][] }> {
    const startJs = ScriptBuilder.serializeArg(start);
    const countJs = ScriptBuilder.serializeArg(count);
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g) return null;
            var total = g.getNumFacets();
            var end = Math.min(${startJs} + ${countJs}, total);
            var facets = [];
            for (var i = ${startJs}; i < end; i++) {
                var f = g.getFacet(i);
                if (f.isQuad()) {
                    facets.push([f.vertIdx1, f.vertIdx2, f.vertIdx3, f.vertIdx4]);
                } else {
                    facets.push([f.vertIdx1, f.vertIdx2, f.vertIdx3]);
                }
            }
            return {total: total, start: ${startJs}, facets: facets};
        `);
    return ((await this.client.execute(script)).value as { total: number; start: number; facets: number[][] }) ?? {
      total: 0,
      start,
      facets: [],
    };
  }

  /** Every face's vertex indices, auto-paginating by `chunkSize` (default `1000`). */
  async faceVertexIndicesAll(chunkSize = 1000): Promise<number[][]> {
    const all: number[][] = [];
    let offset = 0;
    let total = Infinity;
    while (offset < total) {
      const chunk = await this.faceVertexIndices(offset, chunkSize);
      total = chunk.total;
      if (chunk.facets.length === 0) break;
      all.push(...chunk.facets);
      offset += chunk.facets.length;
    }
    return all;
  }

  /** One chunk of face normals. `start`/`count` default `0`/`5000`. */
  async normals(start = 0, count = 5000): Promise<{ total: number; start: number; normals: number[][] }> {
    const startJs = ScriptBuilder.serializeArg(start);
    const countJs = ScriptBuilder.serializeArg(count);
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g) return null;
            var total = g.getNumNormals ? g.getNumNormals() : 0;
            var end = Math.min(${startJs} + ${countJs}, total);
            var norms = [];
            for (var i = ${startJs}; i < end; i++) {
                var n = g.getNormal(i);
                norms.push([n.x, n.y, n.z]);
            }
            return {total: total, start: ${startJs}, normals: norms};
        `);
    return ((await this.client.execute(script)).value as { total: number; start: number; normals: number[][] }) ?? {
      total: 0,
      start,
      normals: [],
    };
  }

  /** Every face normal, auto-paginating by `chunkSize` (default `5000`). */
  async normalsAll(chunkSize = 5000): Promise<number[][]> {
    const all: number[][] = [];
    let offset = 0;
    let total = Infinity;
    while (offset < total) {
      const chunk = await this.normals(offset, chunkSize);
      total = chunk.total;
      if (chunk.normals.length === 0) break;
      all.push(...chunk.normals);
      offset += chunk.normals.length;
    }
    return all;
  }

  /** Number of UV sets on this mesh (read-only). */
  async uvSetCount(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var g = ${this.locator}; return g ? g.getNumUVSets() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  /** One chunk of UV coordinates for `uvSet` (default `0`, the primary set uses `g.getUVs()` rather than `g.getUVSet(0)`). */
  async uvPositions(uvSet = 0, start = 0, count = 5000): Promise<{ total: number; start: number; uvs: number[][] }> {
    const uvSetJs = ScriptBuilder.serializeArg(uvSet);
    const startJs = ScriptBuilder.serializeArg(start);
    const countJs = ScriptBuilder.serializeArg(count);
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g) return null;
            var uvMap = (${uvSetJs} === 0) ? g.getUVs() : g.getUVSet(${uvSetJs});
            if (!uvMap) return null;
            var total = uvMap.getNumValues();
            var end = Math.min(${startJs} + ${countJs}, total);
            var uvs = [];
            for (var i = ${startJs}; i < end; i++) {
                var p = uvMap.getPnt2Vec(i);
                uvs.push([p.x, p.y]);
            }
            return {total: total, start: ${startJs}, uvs: uvs};
        `);
    return ((await this.client.execute(script)).value as { total: number; start: number; uvs: number[][] }) ?? {
      total: 0,
      start,
      uvs: [],
    };
  }

  /** Every UV coordinate for `uvSet`, auto-paginating by `chunkSize` (default `5000`). */
  async uvPositionsAll(uvSet = 0, chunkSize = 5000): Promise<number[][]> {
    const all: number[][] = [];
    let offset = 0;
    let total = Infinity;
    while (offset < total) {
      const chunk = await this.uvPositions(uvSet, offset, chunkSize);
      total = chunk.total;
      if (chunk.uvs.length === 0) break;
      all.push(...chunk.uvs);
      offset += chunk.uvs.length;
    }
    return all;
  }

  // ---------------------------------------------------------------------
  // Groups
  // ---------------------------------------------------------------------

  async faceGroupNames(): Promise<Array<string | null>> {
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g || !g.getNumFaceGroups) return [];
            var n = g.getNumFaceGroups();
            var names = [];
            for (var i = 0; i < n; i++) {
                var grp = g.getFaceGroup(i);
                names.push(grp ? grp.getName() : null);
            }
            return names;
        `);
    return ((await this.client.execute(script)).value as Array<string | null>) ?? [];
  }

  async materialGroupNames(): Promise<Array<string | null>> {
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g || !g.getNumMaterialGroups) return [];
            var n = g.getNumMaterialGroups();
            var names = [];
            for (var i = 0; i < n; i++) {
                var grp = g.getMaterialGroup(i);
                names.push(grp ? grp.getName() : null);
            }
            return names;
        `);
    return ((await this.client.execute(script)).value as Array<string | null>) ?? [];
  }

  /** Face indices belonging to the named face group, or `[]` if it doesn't exist. */
  async faceGroupFaces(name: string): Promise<number[]> {
    const nameJs = ScriptBuilder.escapeString(name);
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g || !g.getNumFaceGroups) return [];
            for (var i = 0; i < g.getNumFaceGroups(); i++) {
                var grp = g.getFaceGroup(i);
                if (grp && grp.getName() === ${nameJs}) {
                    var idx = [];
                    for (var j = 0; j < grp.count(); j++) idx.push(grp.getIndexAt(j));
                    return idx;
                }
            }
            return [];
        `);
    return ((await this.client.execute(script)).value as number[]) ?? [];
  }

  /** Face indices belonging to the named material group, or `[]` if it doesn't exist. */
  async materialGroupFaces(name: string): Promise<number[]> {
    const nameJs = ScriptBuilder.escapeString(name);
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g || !g.getNumMaterialGroups) return [];
            for (var i = 0; i < g.getNumMaterialGroups(); i++) {
                var grp = g.getMaterialGroup(i);
                if (grp && grp.getName() === ${nameJs}) {
                    var idx = [];
                    for (var j = 0; j < grp.count(); j++) idx.push(grp.getIndexAt(j));
                    return idx;
                }
            }
            return [];
        `);
    return ((await this.client.execute(script)).value as number[]) ?? [];
  }

  // ---------------------------------------------------------------------
  // Subdivision / tris / quads / mesh info
  // ---------------------------------------------------------------------

  /** Current subdivision level (`0` = base mesh, read-only). */
  async subdivisionLevel(): Promise<number | null> {
    const script = ScriptBuilder.iife(
      `var g = ${this.locator}; return (g && g.getCurrentSubDivisionLevel) ? g.getCurrentSubDivisionLevel() : null;`,
    );
    return (await this.client.execute(script)).value as number | null;
  }

  async trisCount(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var g = ${this.locator}; return (g && g.getNumTris) ? g.getNumTris() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  async quadsCount(): Promise<number | null> {
    const script = ScriptBuilder.iife(`var g = ${this.locator}; return (g && g.getNumQuads) ? g.getNumQuads() : null;`);
    return (await this.client.execute(script)).value as number | null;
  }

  /** All mesh metadata (vertex/facet/tri/quad counts, subdivision level, UV set count, group names) in a single HTTP call, instead of 7+ separate reads. */
  async meshInfo(): Promise<Record<string, unknown> | null> {
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g) return null;
            var fgNames = [];
            if (g.getNumFaceGroups) {
                for (var i = 0; i < g.getNumFaceGroups(); i++) {
                    var fg = g.getFaceGroup(i);
                    fgNames.push(fg ? fg.getName() : null);
                }
            }
            var mgNames = [];
            if (g.getNumMaterialGroups) {
                for (var i = 0; i < g.getNumMaterialGroups(); i++) {
                    var mg = g.getMaterialGroup(i);
                    mgNames.push(mg ? mg.getName() : null);
                }
            }
            return {
                vertex_count:         g.getNumVertices(),
                facet_count:          g.getNumFacets(),
                tris_count:           g.getNumTris           ? g.getNumTris()                  : null,
                quads_count:          g.getNumQuads          ? g.getNumQuads()                 : null,
                subdivision_level:    g.getCurrentSubDivisionLevel ? g.getCurrentSubDivisionLevel() : null,
                uv_set_count:         g.getNumUVSets         ? g.getNumUVSets()                : null,
                face_group_names:     fgNames,
                material_group_names: mgNames
            };
        `);
    return (await this.client.execute(script)).value as Record<string, unknown> | null;
  }

  // ---------------------------------------------------------------------
  // Bounding box
  // ---------------------------------------------------------------------

  /** Axis-aligned bounding box of the base mesh, computed server-side in one HTTP call. `null` if unavailable or empty. */
  async boundingBox(): Promise<BoundingBox | null> {
    const script = ScriptBuilder.iife(`
            var g = ${this.locator};
            if (!g || g.getNumVertices() === 0) return null;
            var v = g.getVertex(0);
            var mnX = v.x, mnY = v.y, mnZ = v.z;
            var mxX = v.x, mxY = v.y, mxZ = v.z;
            var n = g.getNumVertices();
            for (var i = 1; i < n; i++) {
                v = g.getVertex(i);
                if (v.x < mnX) mnX = v.x; else if (v.x > mxX) mxX = v.x;
                if (v.y < mnY) mnY = v.y; else if (v.y > mxY) mxY = v.y;
                if (v.z < mnZ) mnZ = v.z; else if (v.z > mxZ) mxZ = v.z;
            }
            return {min: {x:mnX, y:mnY, z:mnZ}, max: {x:mxX, y:mxY, z:mxZ}};
        `);
    const result = (await this.client.execute(script)).value as BBoxDict | null;
    if (result === null) return null;
    return BoundingBox.fromDict(result);
  }

  /** AABB of the world-space posed-and-morphed mesh (after forcing a cache update), in one HTTP call. */
  async boundingBoxPosed(): Promise<BoundingBox | null> {
    const script = ScriptBuilder.iife(`
            var _nd = ${this.nodeExpr};
            if (!_nd) return null;
            var obj = _nd.getObject();
            if (!obj) return null;
            obj.forceCacheUpdate(_nd, false);
            var g = obj.getCachedGeom();
            if (!g || g.getNumVertices() === 0) return null;
            var v = g.getVertex(0);
            var mnX = v.x, mnY = v.y, mnZ = v.z;
            var mxX = v.x, mxY = v.y, mxZ = v.z;
            var n = g.getNumVertices();
            for (var i = 1; i < n; i++) {
                v = g.getVertex(i);
                if (v.x < mnX) mnX = v.x; else if (v.x > mxX) mxX = v.x;
                if (v.y < mnY) mnY = v.y; else if (v.y > mxY) mxY = v.y;
                if (v.z < mnZ) mnZ = v.z; else if (v.z > mxZ) mxZ = v.z;
            }
            return {min: {x:mnX, y:mnY, z:mnZ}, max: {x:mxX, y:mxY, z:mxZ}};
        `);
    const result = (await this.client.execute(script)).value as BBoxDict | null;
    if (result === null) return null;
    return BoundingBox.fromDict(result);
  }

  // ---------------------------------------------------------------------
  // Posed (world-space) vertex positions
  // ---------------------------------------------------------------------

  /** One chunk of fully-deformed world-space vertex positions (post morph-and-skinning), via `DzObject.getCachedGeom()`. */
  async vertexPositionsPosed(
    start = 0,
    count = 5000,
  ): Promise<{ total: number; start: number; count: number; vertices: number[][] }> {
    const startJs = ScriptBuilder.serializeArg(start);
    const countJs = ScriptBuilder.serializeArg(count);
    const script = ScriptBuilder.iife(`
            var n = ${this.nodeExpr};
            if (!n) return null;
            var obj = n.getObject();
            if (!obj) return null;
            obj.forceCacheUpdate(n, false);
            var cached = obj.getCachedGeom();
            if (!cached) return null;
            var total = cached.getNumVertices();
            var end = Math.min(${startJs} + ${countJs}, total);
            var verts = [];
            for (var i = ${startJs}; i < end; i++) {
                var v = cached.getVertex(i);
                verts.push([v.x, v.y, v.z]);
            }
            return {total: total, start: ${startJs}, count: verts.length, vertices: verts};
        `);
    return ((await this.client.execute(script)).value as {
      total: number;
      start: number;
      count: number;
      vertices: number[][];
    }) ?? { total: 0, start, count: 0, vertices: [] };
  }

  /** Every world-space posed+morphed vertex position, auto-paginating by `chunkSize` (default `5000`). */
  async vertexPositionsPosedAll(chunkSize = 5000): Promise<number[][]> {
    const all: number[][] = [];
    let offset = 0;
    let total = Infinity;
    while (offset < total) {
      const chunk = await this.vertexPositionsPosed(offset, chunkSize);
      total = chunk.total;
      if (chunk.vertices.length === 0) break;
      all.push(...chunk.vertices);
      offset += chunk.vertices.length;
    }
    return all;
  }

  // ---------------------------------------------------------------------
  // Static helpers (pure functions, no HTTP)
  // ---------------------------------------------------------------------

  /**
   * Convert face index arrays (tris or quads) to all-triangles. Quads split
   * along the 0->2 diagonal (`[v0,v1,v2,v3]` -> `[v0,v1,v2]` + `[v0,v2,v3]`).
   * Faces with any other vertex count are silently skipped. Pure function — no HTTP round-trip.
   */
  static triangulate(faces: number[][]): number[][] {
    const result: number[][] = [];
    for (const f of faces) {
      if (f.length === 3) {
        result.push([...f]);
      } else if (f.length === 4) {
        result.push([f[0], f[1], f[2]]);
        result.push([f[0], f[2], f[3]]);
      }
    }
    return result;
  }

  /** Wrap `[[x,y,z], ...]` vertex data as {@link Vec3} instances. Pure function — no HTTP round-trip. */
  static asVec3(vertices: number[][]): Vec3[] {
    return vertices.map((v) => Vec3.fromList(v));
  }
}
