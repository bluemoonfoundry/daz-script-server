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

    # ── bulk metadata ─────────────────────────────────────────────────────────

    def mesh_info(self) -> dict | None:
        """Fetch all mesh metadata in a single HTTP call.

        Consolidates what would otherwise be 7+ separate property reads.

        Returns:
            ``{vertex_count, facet_count, tris_count, quads_count,
            subdivision_level, uv_set_count, face_group_names,
            material_group_names}`` or ``None`` if the geometry is unavailable.
        """
        script = ScriptBuilder.iife(f"""
            var g = {self._locator};
            if (!g) return null;
            var fgNames = [];
            if (g.getNumFaceGroups) {{
                for (var i = 0; i < g.getNumFaceGroups(); i++) {{
                    var fg = g.getFaceGroup(i);
                    fgNames.push(fg ? fg.getName() : null);
                }}
            }}
            var mgNames = [];
            if (g.getNumMaterialGroups) {{
                for (var i = 0; i < g.getNumMaterialGroups(); i++) {{
                    var mg = g.getMaterialGroup(i);
                    mgNames.push(mg ? mg.getName() : null);
                }}
            }}
            return {{
                vertex_count:         g.getNumVertices(),
                facet_count:          g.getNumFacets(),
                tris_count:           g.getNumTris           ? g.getNumTris()                  : null,
                quads_count:          g.getNumQuads          ? g.getNumQuads()                 : null,
                subdivision_level:    g.getCurrentSubDivisionLevel ? g.getCurrentSubDivisionLevel() : null,
                uv_set_count:         g.getNumUVSets         ? g.getNumUVSets()                : null,
                face_group_names:     fgNames,
                material_group_names: mgNames,
            }};
        """)
        return self._client.execute(script).value

    # ── bounding box ──────────────────────────────────────────────────────────

    def bounding_box(self) -> "BoundingBox | None":  # noqa: F821
        """Axis-aligned bounding box of the base mesh in one HTTP call.

        Iterates all vertices server-side, avoiding the need to transfer every
        position to Python just to compute an AABB.

        Returns:
            A :class:`~dazpy.math3.BoundingBox`, or ``None`` if the geometry
            is unavailable or empty.
        """
        script = ScriptBuilder.iife(f"""
            var g = {self._locator};
            if (!g || g.getNumVertices() === 0) return null;
            var v = g.getVertex(0);
            var mnX = v.x, mnY = v.y, mnZ = v.z;
            var mxX = v.x, mxY = v.y, mxZ = v.z;
            var n = g.getNumVertices();
            for (var i = 1; i < n; i++) {{
                v = g.getVertex(i);
                if (v.x < mnX) mnX = v.x; else if (v.x > mxX) mxX = v.x;
                if (v.y < mnY) mnY = v.y; else if (v.y > mxY) mxY = v.y;
                if (v.z < mnZ) mnZ = v.z; else if (v.z > mxZ) mxZ = v.z;
            }}
            return {{min: {{x:mnX, y:mnY, z:mnZ}}, max: {{x:mxX, y:mxY, z:mxZ}}}};
        """)
        result = self._client.execute(script).value
        if result is None:
            return None
        from .math3 import BoundingBox
        return BoundingBox.from_dict(result)

    def bounding_box_posed(self) -> "BoundingBox | None":  # noqa: F821
        """AABB of the world-space posed-and-morphed mesh in one HTTP call.

        Uses ``DzObject.getCachedGeom()`` after forcing a cache update, so the
        result reflects the current bone pose and all active morphs.

        Returns:
            A :class:`~dazpy.math3.BoundingBox` in world space, or ``None``.
        """
        script = ScriptBuilder.iife(f"""
            var _nd = {ScriptBuilder.find_node_expr(self._identifier)};
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
            for (var i = 1; i < n; i++) {{
                v = g.getVertex(i);
                if (v.x < mnX) mnX = v.x; else if (v.x > mxX) mxX = v.x;
                if (v.y < mnY) mnY = v.y; else if (v.y > mxY) mxY = v.y;
                if (v.z < mnZ) mnZ = v.z; else if (v.z > mxZ) mxZ = v.z;
            }}
            return {{min: {{x:mnX, y:mnY, z:mnZ}}, max: {{x:mxX, y:mxY, z:mxZ}}}};
        """)
        result = self._client.execute(script).value
        if result is None:
            return None
        from .math3 import BoundingBox
        return BoundingBox.from_dict(result)

    # ── paginated _all() wrappers ─────────────────────────────────────────────

    def face_vertex_indices_all(self, chunk_size: int = 1000) -> list[list[int]]:
        """Return all face vertex indices, paginating automatically.

        Args:
            chunk_size: Faces fetched per network round-trip.

        Returns:
            List of faces; each face is ``[v0, v1, v2]`` (tri) or
            ``[v0, v1, v2, v3]`` (quad).
        """
        first = self.face_vertex_indices(0, chunk_size)
        total = first.get("total", 0)
        all_faces = list(first.get("facets", []))
        offset = len(all_faces)
        while offset < total:
            chunk = self.face_vertex_indices(offset, chunk_size)
            batch = chunk.get("facets") or []
            if not batch:
                break
            all_faces.extend(batch)
            offset += len(batch)
        return all_faces

    def normals_all(self, chunk_size: int = 5000) -> list[list[float]]:
        """Return all face normals, paginating automatically.

        Args:
            chunk_size: Normals fetched per network round-trip.

        Returns:
            List of ``[x, y, z]`` unit normals.
        """
        first = self.normals(0, chunk_size)
        total = first.get("total", 0)
        all_norms = list(first.get("normals", []))
        offset = len(all_norms)
        while offset < total:
            chunk = self.normals(offset, chunk_size)
            batch = chunk.get("normals") or []
            if not batch:
                break
            all_norms.extend(batch)
            offset += len(batch)
        return all_norms

    def uv_positions_all(self, uv_set: int = 0, chunk_size: int = 5000) -> list[list[float]]:
        """Return all UV coordinates for *uv_set*, paginating automatically.

        Args:
            uv_set:     UV set index (0 = primary).
            chunk_size: UV pairs fetched per network round-trip.

        Returns:
            List of ``[u, v]`` pairs.
        """
        first = self.uv_positions(uv_set, 0, chunk_size)
        total = first.get("total", 0)
        all_uvs = list(first.get("uvs", []))
        offset = len(all_uvs)
        while offset < total:
            chunk = self.uv_positions(uv_set, offset, chunk_size)
            batch = chunk.get("uvs") or []
            if not batch:
                break
            all_uvs.extend(batch)
            offset += len(batch)
        return all_uvs

    # ── group membership ──────────────────────────────────────────────────────

    def face_group_faces(self, name: str) -> list[int]:
        """Return the face indices belonging to the named face group.

        Args:
            name: Face group name as returned by :meth:`face_group_names`.

        Returns:
            List of 0-based face indices, or ``[]`` if the group doesn't exist.
        """
        name_js = ScriptBuilder.escape_string(name)
        script = ScriptBuilder.iife(f"""
            var g = {self._locator};
            if (!g || !g.getNumFaceGroups) return [];
            for (var i = 0; i < g.getNumFaceGroups(); i++) {{
                var grp = g.getFaceGroup(i);
                if (grp && grp.getName() === {name_js}) {{
                    var idx = [];
                    for (var j = 0; j < grp.count(); j++) idx.push(grp.getIndexAt(j));
                    return idx;
                }}
            }}
            return [];
        """)
        return self._client.execute(script).value or []

    def material_group_faces(self, name: str) -> list[int]:
        """Return the face indices belonging to the named material group.

        Args:
            name: Material group name as returned by :meth:`material_group_names`.

        Returns:
            List of 0-based face indices, or ``[]`` if the group doesn't exist.
        """
        name_js = ScriptBuilder.escape_string(name)
        script = ScriptBuilder.iife(f"""
            var g = {self._locator};
            if (!g || !g.getNumMaterialGroups) return [];
            for (var i = 0; i < g.getNumMaterialGroups(); i++) {{
                var grp = g.getMaterialGroup(i);
                if (grp && grp.getName() === {name_js}) {{
                    var idx = [];
                    for (var j = 0; j < grp.count(); j++) idx.push(grp.getIndexAt(j));
                    return idx;
                }}
            }}
            return [];
        """)
        return self._client.execute(script).value or []

    # ── pure-Python mesh utilities ────────────────────────────────────────────

    @staticmethod
    def triangulate(faces: list) -> list[list[int]]:
        """Convert a list of face index arrays (tris or quads) to all-triangles.

        Quads are split along the 0→2 diagonal:
        ``[v0, v1, v2, v3]`` → ``[v0, v1, v2]`` + ``[v0, v2, v3]``.
        Triangles are passed through unchanged.  Faces with any other vertex
        count are silently skipped.

        This is a pure-Python operation — no HTTP round-trip.

        Args:
            faces: List of faces, each a list/tuple of vertex indices, as
                returned by :meth:`face_vertex_indices_all`.

        Returns:
            All-triangle face list.
        """
        result = []
        for f in faces:
            if len(f) == 3:
                result.append(list(f))
            elif len(f) == 4:
                result.append([f[0], f[1], f[2]])
                result.append([f[0], f[2], f[3]])
        return result

    @staticmethod
    def as_vec3(vertices: list) -> list:
        """Wrap ``[[x, y, z], ...]`` vertex data in :class:`~dazpy.math3.Vec3` objects.

        This is a pure-Python operation — no HTTP round-trip.

        Args:
            vertices: List of ``[x, y, z]`` arrays, as returned by
                :meth:`vertex_positions_all` or :meth:`vertex_positions_posed_all`.

        Returns:
            List of :class:`~dazpy.math3.Vec3`.
        """
        from .math3 import Vec3
        return [Vec3.from_list(v) for v in vertices]
