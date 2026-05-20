from __future__ import annotations

from ._element import DazElement
from ._node import NodeIdentifier
from ._script_builder import ScriptBuilder


class DazGeometry(DazElement):
    """Proxy for the ``DzGeometry`` of a node's current shape.

    Provides chunked access to vertices, faces, normals, UV sets, and face /
    material groups.  Use :class:`~dazpy.DazNode` or construct directly::

        from dazpy import DazClient, DazGeometry, NodeIdentifier

        geo = DazGeometry(DazClient(), NodeIdentifier("Genesis9"))
        verts = geo.vertex_positions_all()

    Args:
        client: The :class:`~dazpy.DazClient` for remote calls.
        identifier: Identifies the scene node whose geometry to access.
    """

    def __init__(self, client: "DazClient", identifier: NodeIdentifier):  # noqa: F821
        locator = (
            f"(function(){{"
            f"var n = {ScriptBuilder.find_node_expr(identifier)};"
            f"if (!n) return null;"
            f"var obj = n.getObject();"
            f"if (!obj) return null;"
            f"var sh = obj.getCurrentShape();"
            f"return sh ? sh.getGeometry() : null;"
            f"}})()"
        )
        super().__init__(client, locator)
        object.__setattr__(self, "_identifier", identifier)

    @property
    def vertex_count(self) -> int | None:
        """Total number of vertices in the mesh (read-only)."""
        script = ScriptBuilder.iife(
            f"var g = {self._locator}; return g ? g.getNumVertices() : null;"
        )
        return self._client.execute(script).value

    @property
    def facet_count(self) -> int | None:
        """Total number of faces (triangles + quads, read-only)."""
        script = ScriptBuilder.iife(
            f"var g = {self._locator}; return g ? g.getNumFacets() : null;"
        )
        return self._client.execute(script).value

    def vertex_positions(self, start: int = 0, count: int = 5000) -> dict:
        """Fetch a chunk of vertex positions.

        Args:
            start: Zero-based index of the first vertex to return.
            count: Maximum number of vertices to return in this chunk.

        Returns:
            ``{"total": int, "start": int, "count": int, "vertices": [[x, y, z], ...]}``
        """
        script = ScriptBuilder.iife(f"""
            var g = {self._locator};
            if (!g) return null;
            var total = g.getNumVertices();
            var end = Math.min({start} + {count}, total);
            var verts = [];
            for (var i = {start}; i < end; i++) {{
                var v = g.getVertex(i);
                verts.push([v.x, v.y, v.z]);
            }}
            return {{total: total, start: {start}, count: verts.length, vertices: verts}};
        """)
        return self._client.execute(script).value or {}

    def vertex_positions_all(self, chunk_size: int = 5000) -> list[list[float]]:
        """Return all vertex positions, automatically paginating by *chunk_size*.

        Args:
            chunk_size: Number of vertices fetched per network round-trip.

        Returns:
            List of ``[x, y, z]`` coordinates for every vertex.
        """
        first = self.vertex_positions(0, chunk_size)
        total = first.get("total", 0)
        all_verts = list(first.get("vertices", []))
        offset = len(all_verts)
        while offset < total:
            chunk = self.vertex_positions(offset, chunk_size)
            all_verts.extend(chunk.get("vertices", []))
            offset += len(chunk.get("vertices", []) or [])
            if not chunk.get("vertices"):
                break
        return all_verts

    # ── Section 7a ────────────────────────────────────────────────────────────

    def face_vertex_indices(self, start: int = 0, count: int = 1000) -> dict:
        """Chunked access to facet vertex indices. Returns {total, start, facets: [[v0,v1,v2(,v3)], ...]}."""
        script = ScriptBuilder.iife(f"""
            var g = {self._locator};
            if (!g) return null;
            var total = g.getNumFacets();
            var end = Math.min({start} + {count}, total);
            var facets = [];
            for (var i = {start}; i < end; i++) {{
                var f = g.getFacet(i);
                if (f.isQuad()) {{
                    facets.push([f.vertIdx1, f.vertIdx2, f.vertIdx3, f.vertIdx4]);
                }} else {{
                    facets.push([f.vertIdx1, f.vertIdx2, f.vertIdx3]);
                }}
            }}
            return {{total: total, start: {start}, facets: facets}};
        """)
        return self._client.execute(script).value or {}

    def normals(self, start: int = 0, count: int = 5000) -> dict:
        """Chunked access to face normals. Returns {total, start, normals: [[x,y,z], ...]}."""
        script = ScriptBuilder.iife(f"""
            var g = {self._locator};
            if (!g) return null;
            var total = g.getNumNormals ? g.getNumNormals() : 0;
            var end = Math.min({start} + {count}, total);
            var norms = [];
            for (var i = {start}; i < end; i++) {{
                var n = g.getNormal(i);
                norms.push([n.x, n.y, n.z]);
            }}
            return {{total: total, start: {start}, normals: norms}};
        """)
        return self._client.execute(script).value or {}

    @property
    def uv_set_count(self) -> int | None:
        """Number of UV sets on this mesh (read-only)."""
        script = ScriptBuilder.iife(
            f"var g = {self._locator}; return g ? g.getNumUVSets() : null;"
        )
        return self._client.execute(script).value

    def uv_positions(self, uv_set: int = 0, start: int = 0, count: int = 5000) -> dict:
        """Chunked access to UV coordinates. Returns {total, start, uvs: [[u,v], ...]}."""
        script = ScriptBuilder.iife(f"""
            var g = {self._locator};
            if (!g) return null;
            var uvMap = ({uv_set} === 0) ? g.getUVs() : g.getUVSet({uv_set});
            if (!uvMap) return null;
            var total = uvMap.getNumValues();
            var end = Math.min({start} + {count}, total);
            var uvs = [];
            for (var i = {start}; i < end; i++) {{
                var p = uvMap.getPnt2Vec(i);
                uvs.push([p.x, p.y]);
            }}
            return {{total: total, start: {start}, uvs: uvs}};
        """)
        return self._client.execute(script).value or {}

    # ── Section 7b ────────────────────────────────────────────────────────────

    def face_group_names(self) -> list[str]:
        script = ScriptBuilder.iife(f"""
            var g = {self._locator};
            if (!g || !g.getNumFaceGroups) return [];
            var n = g.getNumFaceGroups();
            var names = [];
            for (var i = 0; i < n; i++) {{
                var grp = g.getFaceGroup(i);
                names.push(grp ? grp.getName() : null);
            }}
            return names;
        """)
        return self._client.execute(script).value or []

    def material_group_names(self) -> list[str]:
        script = ScriptBuilder.iife(f"""
            var g = {self._locator};
            if (!g || !g.getNumMaterialGroups) return [];
            var n = g.getNumMaterialGroups();
            var names = [];
            for (var i = 0; i < n; i++) {{
                var grp = g.getMaterialGroup(i);
                names.push(grp ? grp.getName() : null);
            }}
            return names;
        """)
        return self._client.execute(script).value or []

    @property
    def subdivision_level(self) -> int | None:
        """Current subdivision level (0 = base mesh, read-only)."""
        script = ScriptBuilder.iife(
            f"var g = {self._locator};"
            f"return (g && g.getCurrentSubDivisionLevel) ? g.getCurrentSubDivisionLevel() : null;"
        )
        return self._client.execute(script).value

    # ── Section 7c: posed (world-space) positions ─────────────────────────────

    def vertex_positions_posed(self, start: int = 0, count: int = 5000) -> dict:
        """Fetch a chunk of fully-deformed world-space vertex positions.

        Uses ``DzObject.getCachedGeom()`` which returns the final mesh after
        morph deformations *and* skeleton skinning have been applied, in
        world-space coordinates.  Use :meth:`vertex_positions_posed_all` to
        retrieve all vertices automatically.

        Returns:
            ``{"total": int, "start": int, "count": int, "vertices": [[x, y, z], ...]}``
        """
        script = ScriptBuilder.iife(f"""
            var n = {ScriptBuilder.find_node_expr(self._identifier)};
            if (!n) return null;
            var obj = n.getObject();
            if (!obj) return null;
            obj.forceCacheUpdate(n, false);
            var cached = obj.getCachedGeom();
            if (!cached) return null;
            var total = cached.getNumVertices();
            var end = Math.min({start} + {count}, total);
            var verts = [];
            for (var i = {start}; i < end; i++) {{
                var v = cached.getVertex(i);
                verts.push([v.x, v.y, v.z]);
            }}
            return {{total: total, start: {start}, count: verts.length, vertices: verts}};
        """)
        return self._client.execute(script).value or {}

    def vertex_positions_posed_all(self, chunk_size: int = 5000) -> list[list[float]]:
        """Return all world-space posed+morphed vertex positions.

        The first call triggers :meth:`vertex_positions_posed` which forces a
        cache update; subsequent chunks reuse the same cached geometry.

        Returns:
            List of ``[x, y, z]`` world-space coordinates for every vertex,
            after skeleton skinning and morph deformations.
        """
        first = self.vertex_positions_posed(0, chunk_size)
        total = first.get("total", 0)
        all_verts = list(first.get("vertices", []))
        offset = len(all_verts)
        while offset < total:
            chunk = self.vertex_positions_posed(offset, chunk_size)
            all_verts.extend(chunk.get("vertices", []))
            offset += len(chunk.get("vertices", []) or [])
            if not chunk.get("vertices"):
                break
        return all_verts

    @property
    def tris_count(self) -> int | None:
        """Number of triangular faces (read-only)."""
        script = ScriptBuilder.iife(
            f"var g = {self._locator}; return (g && g.getNumTris) ? g.getNumTris() : null;"
        )
        return self._client.execute(script).value

    @property
    def quads_count(self) -> int | None:
        """Number of quad faces (read-only)."""
        script = ScriptBuilder.iife(
            f"var g = {self._locator}; return (g && g.getNumQuads) ? g.getNumQuads() : null;"
        )
        return self._client.execute(script).value
