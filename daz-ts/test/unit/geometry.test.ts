import { afterEach, describe, expect, it, vi } from "vitest";
import { DazClient } from "../../src/client.js";
import { DazGeometry } from "../../src/geometry.js";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}
afterEach(() => vi.unstubAllGlobals());
function stubSeq(...values: unknown[]) {
  const fetchMock = vi.fn();
  for (const v of values) fetchMock.mockResolvedValueOnce(jsonResponse({ success: true, result: v, output: [], request_id: "r", duration_ms: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const LOCATOR =
  '(function(){var n = Scene.findNode("Genesis9");if (!n) return null;var obj = n.getObject();if (!obj) return null;var sh = obj.getCurrentShape();return sh ? sh.getGeometry() : null;})()';
const NODE_EXPR = 'Scene.findNode("Genesis9")';

function scriptOf(fetchMock: ReturnType<typeof vi.fn>, callIndex = 0): string {
  return JSON.parse(fetchMock.mock.calls[callIndex][1].body as string).script;
}

describe("DazGeometry counts and chunked vertex access", () => {
  it("vertexCount() exact script", async () => {
    const fetchMock = stubSeq(5000);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.vertexCount()).toBe(5000);
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\nvar g = ${LOCATOR}; return g ? g.getNumVertices() : null;\n})()`,
    );
  });

  it("facetCount() exact script", async () => {
    const fetchMock = stubSeq(9998);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.facetCount()).toBe(9998);
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\nvar g = ${LOCATOR}; return g ? g.getNumFacets() : null;\n})()`,
    );
  });

  it("vertexPositions() default start/count exact script", async () => {
    const fetchMock = stubSeq({ total: 0, start: 0, count: 0, vertices: [] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await geo.vertexPositions();
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var g = ${LOCATOR};\n` +
        `            if (!g) return null;\n` +
        `            var total = g.getNumVertices();\n` +
        `            var end = Math.min(0 + 5000, total);\n` +
        `            var verts = [];\n` +
        `            for (var i = 0; i < end; i++) {\n` +
        `                var v = g.getVertex(i);\n` +
        `                verts.push([v.x, v.y, v.z]);\n` +
        `            }\n` +
        `            return {total: total, start: 0, count: verts.length, vertices: verts};\n` +
        `        \n})()`,
    );
  });

  it("vertexPositions(start, count) interpolates explicit numeric args via ScriptBuilder.serializeArg", async () => {
    const fetchMock = stubSeq({ total: 100, start: 10, count: 20, vertices: [] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await geo.vertexPositions(10, 20);
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var g = ${LOCATOR};\n` +
        `            if (!g) return null;\n` +
        `            var total = g.getNumVertices();\n` +
        `            var end = Math.min(10 + 20, total);\n` +
        `            var verts = [];\n` +
        `            for (var i = 10; i < end; i++) {\n` +
        `                var v = g.getVertex(i);\n` +
        `                verts.push([v.x, v.y, v.z]);\n` +
        `            }\n` +
        `            return {total: total, start: 10, count: verts.length, vertices: verts};\n` +
        `        \n})()`,
    );
  });

  it("vertexPositions() falls back to zeroed result when execute returns null", async () => {
    const fetchMock = stubSeq(null);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.vertexPositions(3, 7)).toEqual({ total: 0, start: 3, count: 0, vertices: [] });
    void fetchMock;
  });

  it("vertexPositionsAll paginates until it has consumed the reported total", async () => {
    stubSeq(
      { total: 3, start: 0, count: 2, vertices: [[0, 0, 0], [1, 1, 1]] },
      { total: 3, start: 2, count: 1, vertices: [[2, 2, 2]] },
    );
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const all = await geo.vertexPositionsAll(2);
    expect(all).toEqual([[0, 0, 0], [1, 1, 1], [2, 2, 2]]);
  });

  it("vertexPositionsAll stops early if a chunk returns no vertices, even under the reported total", async () => {
    stubSeq({ total: 10, start: 0, count: 0, vertices: [] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.vertexPositionsAll(5)).toEqual([]);
  });
});

describe("DazGeometry faces/normals/UVs/groups", () => {
  it("faceVertexIndices returns a quad as [v0,v1,v2,v3] and a tri as [v0,v1,v2]", async () => {
    stubSeq({ total: 2, start: 0, facets: [[0, 1, 2, 3], [4, 5, 6]] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const result = await geo.faceVertexIndices(0, 1000);
    expect(result.facets).toEqual([[0, 1, 2, 3], [4, 5, 6]]);
  });

  it("faceVertexIndices() default start/count exact script", async () => {
    const fetchMock = stubSeq({ total: 0, start: 0, facets: [] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await geo.faceVertexIndices();
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var g = ${LOCATOR};\n` +
        `            if (!g) return null;\n` +
        `            var total = g.getNumFacets();\n` +
        `            var end = Math.min(0 + 1000, total);\n` +
        `            var facets = [];\n` +
        `            for (var i = 0; i < end; i++) {\n` +
        `                var f = g.getFacet(i);\n` +
        `                if (f.isQuad()) {\n` +
        `                    facets.push([f.vertIdx1, f.vertIdx2, f.vertIdx3, f.vertIdx4]);\n` +
        `                } else {\n` +
        `                    facets.push([f.vertIdx1, f.vertIdx2, f.vertIdx3]);\n` +
        `                }\n` +
        `            }\n` +
        `            return {total: total, start: 0, facets: facets};\n` +
        `        \n})()`,
    );
  });

  it("faceVertexIndicesAll paginates until it has consumed the reported total", async () => {
    stubSeq(
      { total: 3, start: 0, facets: [[0, 1, 2], [3, 4, 5]] },
      { total: 3, start: 2, facets: [[6, 7, 8]] },
    );
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const all = await geo.faceVertexIndicesAll(2);
    expect(all).toEqual([[0, 1, 2], [3, 4, 5], [6, 7, 8]]);
  });

  it("normals() default start/count exact script", async () => {
    const fetchMock = stubSeq({ total: 0, start: 0, normals: [] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await geo.normals();
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var g = ${LOCATOR};\n` +
        `            if (!g) return null;\n` +
        `            var total = g.getNumNormals ? g.getNumNormals() : 0;\n` +
        `            var end = Math.min(0 + 5000, total);\n` +
        `            var norms = [];\n` +
        `            for (var i = 0; i < end; i++) {\n` +
        `                var n = g.getNormal(i);\n` +
        `                norms.push([n.x, n.y, n.z]);\n` +
        `            }\n` +
        `            return {total: total, start: 0, normals: norms};\n` +
        `        \n})()`,
    );
  });

  it("normalsAll paginates until it has consumed the reported total", async () => {
    stubSeq(
      { total: 3, start: 0, normals: [[0, 0, 1], [0, 1, 0]] },
      { total: 3, start: 2, normals: [[1, 0, 0]] },
    );
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const all = await geo.normalsAll(2);
    expect(all).toEqual([[0, 0, 1], [0, 1, 0], [1, 0, 0]]);
  });

  it("uvSetCount() exact script", async () => {
    const fetchMock = stubSeq(2);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.uvSetCount()).toBe(2);
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\nvar g = ${LOCATOR}; return g ? g.getNumUVSets() : null;\n})()`,
    );
  });

  it("uvPositions() default args exact script (uses g.getUVs() rather than g.getUVSet(0))", async () => {
    const fetchMock = stubSeq({ total: 0, start: 0, uvs: [] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await geo.uvPositions();
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var g = ${LOCATOR};\n` +
        `            if (!g) return null;\n` +
        `            var uvMap = (0 === 0) ? g.getUVs() : g.getUVSet(0);\n` +
        `            if (!uvMap) return null;\n` +
        `            var total = uvMap.getNumValues();\n` +
        `            var end = Math.min(0 + 5000, total);\n` +
        `            var uvs = [];\n` +
        `            for (var i = 0; i < end; i++) {\n` +
        `                var p = uvMap.getPnt2Vec(i);\n` +
        `                uvs.push([p.x, p.y]);\n` +
        `            }\n` +
        `            return {total: total, start: 0, uvs: uvs};\n` +
        `        \n})()`,
    );
  });

  it("uvPositions(uvSet) with a non-zero set uses g.getUVSet(uvSet)", async () => {
    const fetchMock = stubSeq({ total: 0, start: 0, uvs: [] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await geo.uvPositions(1, 0, 5000);
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var g = ${LOCATOR};\n` +
        `            if (!g) return null;\n` +
        `            var uvMap = (1 === 0) ? g.getUVs() : g.getUVSet(1);\n` +
        `            if (!uvMap) return null;\n` +
        `            var total = uvMap.getNumValues();\n` +
        `            var end = Math.min(0 + 5000, total);\n` +
        `            var uvs = [];\n` +
        `            for (var i = 0; i < end; i++) {\n` +
        `                var p = uvMap.getPnt2Vec(i);\n` +
        `                uvs.push([p.x, p.y]);\n` +
        `            }\n` +
        `            return {total: total, start: 0, uvs: uvs};\n` +
        `        \n})()`,
    );
  });

  it("uvPositionsAll paginates until it has consumed the reported total", async () => {
    stubSeq(
      { total: 3, start: 0, uvs: [[0, 0], [1, 0]] },
      { total: 3, start: 2, uvs: [[1, 1]] },
    );
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const all = await geo.uvPositionsAll(0, 2);
    expect(all).toEqual([[0, 0], [1, 0], [1, 1]]);
  });

  it("faceGroupNames() exact script", async () => {
    const fetchMock = stubSeq(["lFoot", "rFoot"]);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.faceGroupNames()).toEqual(["lFoot", "rFoot"]);
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var g = ${LOCATOR};\n` +
        `            if (!g || !g.getNumFaceGroups) return [];\n` +
        `            var n = g.getNumFaceGroups();\n` +
        `            var names = [];\n` +
        `            for (var i = 0; i < n; i++) {\n` +
        `                var grp = g.getFaceGroup(i);\n` +
        `                names.push(grp ? grp.getName() : null);\n` +
        `            }\n` +
        `            return names;\n` +
        `        \n})()`,
    );
  });

  it("materialGroupNames() exact script", async () => {
    const fetchMock = stubSeq(["Skin", "Eyes"]);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.materialGroupNames()).toEqual(["Skin", "Eyes"]);
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var g = ${LOCATOR};\n` +
        `            if (!g || !g.getNumMaterialGroups) return [];\n` +
        `            var n = g.getNumMaterialGroups();\n` +
        `            var names = [];\n` +
        `            for (var i = 0; i < n; i++) {\n` +
        `                var grp = g.getMaterialGroup(i);\n` +
        `                names.push(grp ? grp.getName() : null);\n` +
        `            }\n` +
        `            return names;\n` +
        `        \n})()`,
    );
  });

  it("faceGroupFaces returns [] when the named group does not exist", async () => {
    stubSeq([]);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.faceGroupFaces("Missing")).toEqual([]);
  });

  it("faceGroupFaces() exact script escapes the name via ScriptBuilder.escapeString", async () => {
    const fetchMock = stubSeq([1, 2, 3]);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await geo.faceGroupFaces('lFoot "special"');
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var g = ${LOCATOR};\n` +
        `            if (!g || !g.getNumFaceGroups) return [];\n` +
        `            for (var i = 0; i < g.getNumFaceGroups(); i++) {\n` +
        `                var grp = g.getFaceGroup(i);\n` +
        `                if (grp && grp.getName() === "lFoot \\"special\\"") {\n` +
        `                    var idx = [];\n` +
        `                    for (var j = 0; j < grp.count(); j++) idx.push(grp.getIndexAt(j));\n` +
        `                    return idx;\n` +
        `                }\n` +
        `            }\n` +
        `            return [];\n` +
        `        \n})()`,
    );
  });

  it("materialGroupFaces() exact script escapes the name via ScriptBuilder.escapeString", async () => {
    const fetchMock = stubSeq([4, 5]);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await geo.materialGroupFaces("Skin");
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var g = ${LOCATOR};\n` +
        `            if (!g || !g.getNumMaterialGroups) return [];\n` +
        `            for (var i = 0; i < g.getNumMaterialGroups(); i++) {\n` +
        `                var grp = g.getMaterialGroup(i);\n` +
        `                if (grp && grp.getName() === "Skin") {\n` +
        `                    var idx = [];\n` +
        `                    for (var j = 0; j < grp.count(); j++) idx.push(grp.getIndexAt(j));\n` +
        `                    return idx;\n` +
        `                }\n` +
        `            }\n` +
        `            return [];\n` +
        `        \n})()`,
    );
  });
});

describe("DazGeometry subdivision / tris / quads / meshInfo", () => {
  it("subdivisionLevel() exact script", async () => {
    const fetchMock = stubSeq(1);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.subdivisionLevel()).toBe(1);
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\nvar g = ${LOCATOR}; return (g && g.getCurrentSubDivisionLevel) ? g.getCurrentSubDivisionLevel() : null;\n})()`,
    );
  });

  it("trisCount() exact script", async () => {
    const fetchMock = stubSeq(100);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.trisCount()).toBe(100);
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\nvar g = ${LOCATOR}; return (g && g.getNumTris) ? g.getNumTris() : null;\n})()`,
    );
  });

  it("quadsCount() exact script", async () => {
    const fetchMock = stubSeq(50);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.quadsCount()).toBe(50);
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\nvar g = ${LOCATOR}; return (g && g.getNumQuads) ? g.getNumQuads() : null;\n})()`,
    );
  });

  it("meshInfo() exact script", async () => {
    const fetchMock = stubSeq({ vertex_count: 1, facet_count: 2 });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await geo.meshInfo();
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var g = ${LOCATOR};\n` +
        `            if (!g) return null;\n` +
        `            var fgNames = [];\n` +
        `            if (g.getNumFaceGroups) {\n` +
        `                for (var i = 0; i < g.getNumFaceGroups(); i++) {\n` +
        `                    var fg = g.getFaceGroup(i);\n` +
        `                    fgNames.push(fg ? fg.getName() : null);\n` +
        `                }\n` +
        `            }\n` +
        `            var mgNames = [];\n` +
        `            if (g.getNumMaterialGroups) {\n` +
        `                for (var i = 0; i < g.getNumMaterialGroups(); i++) {\n` +
        `                    var mg = g.getMaterialGroup(i);\n` +
        `                    mgNames.push(mg ? mg.getName() : null);\n` +
        `                }\n` +
        `            }\n` +
        `            return {\n` +
        `                vertex_count:         g.getNumVertices(),\n` +
        `                facet_count:          g.getNumFacets(),\n` +
        `                tris_count:           g.getNumTris           ? g.getNumTris()                  : null,\n` +
        `                quads_count:          g.getNumQuads          ? g.getNumQuads()                 : null,\n` +
        `                subdivision_level:    g.getCurrentSubDivisionLevel ? g.getCurrentSubDivisionLevel() : null,\n` +
        `                uv_set_count:         g.getNumUVSets         ? g.getNumUVSets()                : null,\n` +
        `                face_group_names:     fgNames,\n` +
        `                material_group_names: mgNames\n` +
        `            };\n` +
        `        \n})()`,
    );
  });
});

describe("DazGeometry bounding boxes", () => {
  it("boundingBox() exact script and maps result via BoundingBox.fromDict", async () => {
    const fetchMock = stubSeq({ min: { x: -1, y: -2, z: -3 }, max: { x: 1, y: 2, z: 3 } });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const bbox = await geo.boundingBox();
    expect(bbox?.min).toEqual({ x: -1, y: -2, z: -3 });
    expect(bbox?.max).toEqual({ x: 1, y: 2, z: 3 });
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var g = ${LOCATOR};\n` +
        `            if (!g || g.getNumVertices() === 0) return null;\n` +
        `            var v = g.getVertex(0);\n` +
        `            var mnX = v.x, mnY = v.y, mnZ = v.z;\n` +
        `            var mxX = v.x, mxY = v.y, mxZ = v.z;\n` +
        `            var n = g.getNumVertices();\n` +
        `            for (var i = 1; i < n; i++) {\n` +
        `                v = g.getVertex(i);\n` +
        `                if (v.x < mnX) mnX = v.x; else if (v.x > mxX) mxX = v.x;\n` +
        `                if (v.y < mnY) mnY = v.y; else if (v.y > mxY) mxY = v.y;\n` +
        `                if (v.z < mnZ) mnZ = v.z; else if (v.z > mxZ) mxZ = v.z;\n` +
        `            }\n` +
        `            return {min: {x:mnX, y:mnY, z:mnZ}, max: {x:mxX, y:mxY, z:mxZ}};\n` +
        `        \n})()`,
    );
  });

  it("boundingBox() returns null when the script result is null", async () => {
    stubSeq(null);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.boundingBox()).toBeNull();
  });

  it("boundingBoxPosed() exact script uses nodeExpr + forceCacheUpdate + getCachedGeom", async () => {
    const fetchMock = stubSeq({ min: { x: 0, y: 0, z: 0 }, max: { x: 1, y: 1, z: 1 } });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const bbox = await geo.boundingBoxPosed();
    expect(bbox?.max).toEqual({ x: 1, y: 1, z: 1 });
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var _nd = ${NODE_EXPR};\n` +
        `            if (!_nd) return null;\n` +
        `            var obj = _nd.getObject();\n` +
        `            if (!obj) return null;\n` +
        `            obj.forceCacheUpdate(_nd, false);\n` +
        `            var g = obj.getCachedGeom();\n` +
        `            if (!g || g.getNumVertices() === 0) return null;\n` +
        `            var v = g.getVertex(0);\n` +
        `            var mnX = v.x, mnY = v.y, mnZ = v.z;\n` +
        `            var mxX = v.x, mxY = v.y, mxZ = v.z;\n` +
        `            var n = g.getNumVertices();\n` +
        `            for (var i = 1; i < n; i++) {\n` +
        `                v = g.getVertex(i);\n` +
        `                if (v.x < mnX) mnX = v.x; else if (v.x > mxX) mxX = v.x;\n` +
        `                if (v.y < mnY) mnY = v.y; else if (v.y > mxY) mxY = v.y;\n` +
        `                if (v.z < mnZ) mnZ = v.z; else if (v.z > mxZ) mxZ = v.z;\n` +
        `            }\n` +
        `            return {min: {x:mnX, y:mnY, z:mnZ}, max: {x:mxX, y:mxY, z:mxZ}};\n` +
        `        \n})()`,
    );
  });
});

describe("DazGeometry posed vertex positions", () => {
  it("vertexPositionsPosed() default start/count exact script", async () => {
    const fetchMock = stubSeq({ total: 0, start: 0, count: 0, vertices: [] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    await geo.vertexPositionsPosed();
    expect(scriptOf(fetchMock)).toBe(
      `(function(){\n` +
        `\n            var n = ${NODE_EXPR};\n` +
        `            if (!n) return null;\n` +
        `            var obj = n.getObject();\n` +
        `            if (!obj) return null;\n` +
        `            obj.forceCacheUpdate(n, false);\n` +
        `            var cached = obj.getCachedGeom();\n` +
        `            if (!cached) return null;\n` +
        `            var total = cached.getNumVertices();\n` +
        `            var end = Math.min(0 + 5000, total);\n` +
        `            var verts = [];\n` +
        `            for (var i = 0; i < end; i++) {\n` +
        `                var v = cached.getVertex(i);\n` +
        `                verts.push([v.x, v.y, v.z]);\n` +
        `            }\n` +
        `            return {total: total, start: 0, count: verts.length, vertices: verts};\n` +
        `        \n})()`,
    );
  });

  it("vertexPositionsPosed() falls back to zeroed result when execute returns null", async () => {
    stubSeq(null);
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.vertexPositionsPosed(4, 8)).toEqual({ total: 0, start: 4, count: 0, vertices: [] });
  });

  it("vertexPositionsPosedAll paginates until it has consumed the reported total", async () => {
    stubSeq(
      { total: 3, start: 0, count: 2, vertices: [[0, 0, 0], [1, 1, 1]] },
      { total: 3, start: 2, count: 1, vertices: [[2, 2, 2]] },
    );
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    const all = await geo.vertexPositionsPosedAll(2);
    expect(all).toEqual([[0, 0, 0], [1, 1, 1], [2, 2, 2]]);
  });

  it("vertexPositionsPosedAll stops early if a chunk returns no vertices, even under the reported total", async () => {
    stubSeq({ total: 10, start: 0, count: 0, vertices: [] });
    const geo = new DazGeometry(new DazClient({ token: "" }), { value: "Genesis9", kind: "name" });
    expect(await geo.vertexPositionsPosedAll(5)).toEqual([]);
  });
});

describe("DazGeometry.triangulate / .asVec3 (pure functions, no HTTP)", () => {
  it("triangulate splits quads along the 0-2 diagonal and passes triangles through unchanged", () => {
    expect(DazGeometry.triangulate([[0, 1, 2, 3], [4, 5, 6]])).toEqual([
      [0, 1, 2],
      [0, 2, 3],
      [4, 5, 6],
    ]);
  });

  it("triangulate silently skips faces with any other vertex count", () => {
    expect(DazGeometry.triangulate([[0, 1]])).toEqual([]);
  });

  it("asVec3 wraps [x,y,z] arrays as Vec3 instances", () => {
    const vecs = DazGeometry.asVec3([[1, 2, 3]]);
    expect(vecs[0]).toEqual({ x: 1, y: 2, z: 3 });
  });
});
