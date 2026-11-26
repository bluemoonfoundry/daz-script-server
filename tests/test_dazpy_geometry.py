"""dazpy unit tests: geometry script generation and DZGF geometry-frame parsing.

Mock-based; no server or DAZ Studio required.
Shared fakes live in tests/dazpy_fakes.py.
"""

import json
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy import GeometryFrames, parse_geometry_frames
from dazpy._node import NodeIdentifier
from dazpy._client import DazClient
from dazpy import exceptions
from dazpy_fakes import mock_client


def _dzgf(frames, verts, bones, indices=None, version=1, magic=b"DZGF"):
    """Build a DZGF payload: verts[f][v] / bones[f][b] are (x, y, z) tuples."""
    import struct
    n_verts = len(verts[0]) if verts else 0
    n_bones = len(bones[0]) if bones else 0
    out = struct.pack("<4s7I", magic, version, len(frames), n_verts, n_bones,
                      1 if indices is not None else 0, 0, 0)
    out += struct.pack(f"<{len(frames)}i", *frames)
    if indices is not None:
        out += struct.pack(f"<{len(indices)}I", *indices)
    for per_frame in verts:
        for p in per_frame:
            out += struct.pack("<3f", *p)
    for per_frame in bones:
        for p in per_frame:
            out += struct.pack("<3f", *p)
    return out


class TestGeometryFrames(unittest.TestCase):
    """POST /geometry/frames client + DZGF parser (5d6f.25)."""

    VERTS = [[(0.0, 1.0, 2.0), (3.0, 4.0, 5.0)], [(0.5, 1.5, 2.5), (3.5, 4.5, 5.5)]]
    BONES = [[(10.0, 20.0, 30.0)], [(11.0, 21.0, 31.0)]]

    def _client(self, content=b"", status_code=200, json_data=None):
        client = DazClient(token="")
        client._session.close()
        client._session = MagicMock()
        response = MagicMock(status_code=status_code, headers={})
        response.content = content
        response.json.return_value = json_data or {}
        response.text = json.dumps(json_data or {})
        client._session.post.return_value = response
        return client

    def test_export_sends_minimal_payload_and_parses(self):
        client = self._client(_dzgf([0, 10], self.VERTS, self.BONES))
        gf = client.export_geometry_frames([0, 10], bones=["lHand"])
        call = client._session.post.call_args
        self.assertEqual(call.args[0], "http://127.0.0.1:18811/geometry/frames")
        self.assertEqual(call.kwargs["json"], {"frames": [0, 10], "bones": ["lHand"]})
        self.assertEqual(call.kwargs["timeout"], 30.0)
        self.assertIsInstance(gf, GeometryFrames)
        self.assertEqual(gf.frames, [0, 10])
        self.assertEqual(gf.num_frames, 2)
        self.assertEqual(gf.num_vertices, 2)
        self.assertIsNone(gf.indices)
        self.assertEqual(gf.frame(10), [(0.5, 1.5, 2.5), (3.5, 4.5, 5.5)])
        self.assertEqual(gf.bone("lHand"), [(10.0, 20.0, 30.0), (11.0, 21.0, 31.0)])

    def test_export_full_payload_and_timeout(self):
        client = self._client(_dzgf([5], [[(1.0, 2.0, 3.0)]], [[]], indices=[42]))
        gf = client.export_geometry_frames(
            (5,), node="Genesis 9", indices=[42], surfaces=["Face"],
            resolution="current", scene_update=False, timeout=120)
        call = client._session.post.call_args
        self.assertEqual(call.kwargs["json"], {
            "frames": [5], "node": "Genesis 9", "indices": [42], "surfaces": ["Face"],
            "resolution": "current", "sceneUpdate": False})
        self.assertEqual(call.kwargs["timeout"], 120)
        self.assertEqual(gf.indices, [42])
        self.assertEqual(gf.bones, [[]])

    def test_export_rejects_bad_arguments_without_request(self):
        client = self._client()
        with self.assertRaises(ValueError):
            client.export_geometry_frames([])
        with self.assertRaises(ValueError):
            client.export_geometry_frames([0], resolution="high")
        client._session.post.assert_not_called()

    def test_export_server_error_raises(self):
        body = {"success": False, "error_code": "BAD_REQUEST", "error": "figure not found",
                "retryable": False}
        client = self._client(status_code=400, json_data=body)
        with self.assertRaises(exceptions.ServerResponseError) as ctx:
            client.export_geometry_frames([0], node="Nobody")
        self.assertIn("figure not found", str(ctx.exception))

    def test_parse_rejects_malformed_payloads(self):
        good = _dzgf([0, 10], self.VERTS, self.BONES)
        cases = {
            "short": good[:10],
            "truncated": good[:-4],
            "magic": _dzgf([0], [[(0.0, 0.0, 0.0)]], [[]], magic=b"XXXX"),
            "version": _dzgf([0], [[(0.0, 0.0, 0.0)]], [[]], version=2),
        }
        for name, data in cases.items():
            with self.subTest(name), self.assertRaises(exceptions.ServerResponseError):
                parse_geometry_frames(data)
        with self.assertRaises(exceptions.ServerResponseError):
            parse_geometry_frames(good, bone_names=["a", "b"])

    def test_lookup_errors(self):
        gf = parse_geometry_frames(_dzgf([0, 10], self.VERTS, self.BONES), ["lHand"])
        with self.assertRaises(KeyError):
            gf.frame(3)
        with self.assertRaises(KeyError):
            gf.bone("rHand")


class TestDazGeometryScriptGeneration(unittest.TestCase):
    def _geo(self, return_value=None):
        from dazpy._geometry import DazGeometry
        client = mock_client(return_value)
        geo = DazGeometry(client, NodeIdentifier("Genesis9"))
        return geo, client

    def test_face_vertex_indices_uses_getFacet(self):
        geo, client = self._geo({"total": 100, "start": 0, "facets": [[0, 1, 2]]})
        result = geo.face_vertex_indices(start=0, count=10)
        self.assertIn("facets", result)
        script = client.execute.call_args[0][0]
        self.assertIn("getFacet", script)
        self.assertIn("vertIdx1", script)
        self.assertIn("isQuad", script)

    def test_face_vertex_indices_quad_has_four_indices(self):
        geo, client = self._geo({"total": 10, "start": 0, "facets": [[0, 1, 2, 3]]})
        result = geo.face_vertex_indices(start=0, count=5)
        self.assertEqual(result["facets"][0], [0, 1, 2, 3])

    def test_normals_uses_getNormal(self):
        geo, client = self._geo({"total": 50, "start": 0, "normals": [[0.0, 1.0, 0.0]]})
        result = geo.normals(start=0, count=10)
        self.assertIn("normals", result)
        script = client.execute.call_args[0][0]
        self.assertIn("getNormal", script)
        self.assertIn("getNumNormals", script)

    def test_uv_set_count_uses_getNumUVSets(self):
        geo, client = self._geo(2)
        count = geo.uv_set_count
        self.assertEqual(count, 2)
        script = client.execute.call_args[0][0]
        self.assertIn("getNumUVSets", script)

    def test_uv_positions_default_uses_getUVs(self):
        geo, client = self._geo({"total": 100, "start": 0, "uvs": [[0.5, 0.5]]})
        result = geo.uv_positions(uv_set=0, start=0, count=10)
        self.assertIn("uvs", result)
        script = client.execute.call_args[0][0]
        self.assertIn("getUVs", script)
        self.assertIn("getPnt2Vec", script)

    def test_uv_positions_nonzero_uses_getUVSet(self):
        geo, client = self._geo({"total": 100, "start": 0, "uvs": []})
        geo.uv_positions(uv_set=1)
        script = client.execute.call_args[0][0]
        self.assertIn("getUVSet", script)

    def test_face_group_names_uses_getFaceGroup(self):
        geo, client = self._geo(["Body", "Head"])
        names = geo.face_group_names()
        self.assertEqual(names, ["Body", "Head"])
        script = client.execute.call_args[0][0]
        self.assertIn("getFaceGroup", script)
        self.assertIn("getName", script)

    def test_material_group_names_uses_getMaterialGroup(self):
        geo, client = self._geo(["Skin", "Eyes"])
        names = geo.material_group_names()
        self.assertEqual(names, ["Skin", "Eyes"])
        script = client.execute.call_args[0][0]
        self.assertIn("getMaterialGroup", script)
        self.assertIn("getName", script)

    def test_subdivision_level_uses_getCurrentSubDivisionLevel(self):
        geo, client = self._geo(0)
        lvl = geo.subdivision_level
        self.assertEqual(lvl, 0)
        script = client.execute.call_args[0][0]
        self.assertIn("getCurrentSubDivisionLevel", script)

    def test_tris_count_uses_getNumTris(self):
        geo, client = self._geo(1500)
        count = geo.tris_count
        self.assertEqual(count, 1500)
        script = client.execute.call_args[0][0]
        self.assertIn("getNumTris", script)

    def test_quads_count_uses_getNumQuads(self):
        geo, client = self._geo(8000)
        count = geo.quads_count
        self.assertEqual(count, 8000)
        script = client.execute.call_args[0][0]
        self.assertIn("getNumQuads", script)

    # ── mesh_info ─────────────────────────────────────────────────────────────

    def test_mesh_info_single_call(self):
        payload = {
            "vertex_count": 100, "facet_count": 50,
            "tris_count": 10, "quads_count": 40,
            "subdivision_level": 0, "uv_set_count": 1,
            "face_group_names": ["Body"], "material_group_names": ["Skin"],
        }
        geo, client = self._geo(payload)
        info = geo.mesh_info()
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(info["vertex_count"], 100)
        self.assertEqual(info["face_group_names"], ["Body"])

    def test_mesh_info_script_queries_all_counts(self):
        geo, client = self._geo(None)
        geo.mesh_info()
        script = client.execute.call_args[0][0]
        for token in ("getNumVertices", "getNumFacets", "getNumTris",
                      "getNumQuads", "getCurrentSubDivisionLevel",
                      "getNumUVSets", "getNumFaceGroups", "getNumMaterialGroups"):
            self.assertIn(token, script, msg=f"missing {token}")

    def test_mesh_info_returns_none_when_no_geometry(self):
        geo, client = self._geo(None)
        self.assertIsNone(geo.mesh_info())

    # ── bounding_box ──────────────────────────────────────────────────────────

    def test_bounding_box_returns_bounding_box_instance(self):
        from dazpy import BoundingBox
        payload = {"min": {"x": -1.0, "y": 0.0, "z": -1.0},
                   "max": {"x":  1.0, "y": 2.0, "z":  1.0}}
        geo, client = self._geo(payload)
        bb = geo.bounding_box()
        self.assertIsInstance(bb, BoundingBox)
        self.assertAlmostEqual(bb.min.x, -1.0)
        self.assertAlmostEqual(bb.max.y,  2.0)

    def test_bounding_box_single_call(self):
        payload = {"min": {"x": 0, "y": 0, "z": 0}, "max": {"x": 1, "y": 1, "z": 1}}
        geo, client = self._geo(payload)
        geo.bounding_box()
        self.assertEqual(client.execute.call_count, 1)

    def test_bounding_box_script_iterates_vertices(self):
        geo, client = self._geo(None)
        geo.bounding_box()
        script = client.execute.call_args[0][0]
        self.assertIn("getNumVertices", script)
        self.assertIn("getVertex", script)

    def test_bounding_box_returns_none_when_no_geometry(self):
        geo, client = self._geo(None)
        self.assertIsNone(geo.bounding_box())

    def test_bounding_box_posed_uses_getCachedGeom(self):
        geo, client = self._geo(None)
        geo.bounding_box_posed()
        script = client.execute.call_args[0][0]
        self.assertIn("getCachedGeom", script)
        self.assertIn("forceCacheUpdate", script)

    def test_bounding_box_posed_returns_bounding_box(self):
        from dazpy import BoundingBox
        payload = {"min": {"x": -2, "y": 0, "z": -2}, "max": {"x": 2, "y": 3, "z": 2}}
        geo, client = self._geo(payload)
        bb = geo.bounding_box_posed()
        self.assertIsInstance(bb, BoundingBox)
        self.assertAlmostEqual(bb.max.y, 3.0)

    def test_bounding_box_posed_returns_none_when_no_geometry(self):
        geo, client = self._geo(None)
        self.assertIsNone(geo.bounding_box_posed())

    # ── paginated _all() wrappers ─────────────────────────────────────────────

    def test_face_vertex_indices_all_single_page(self):
        payload = {"total": 2, "start": 0, "facets": [[0, 1, 2], [0, 2, 3]]}
        geo, client = self._geo(payload)
        result = geo.face_vertex_indices_all()
        self.assertEqual(result, [[0, 1, 2], [0, 2, 3]])

    def test_face_vertex_indices_all_paginates(self):
        from dazpy._result import ExecutionResult
        geo, _ = self._geo()
        # Two pages: 2 faces total, chunk_size=1
        responses = [
            {"total": 2, "start": 0, "facets": [[0, 1, 2]]},
            {"total": 2, "start": 1, "facets": [[0, 2, 3]]},
        ]
        geo._client.execute.side_effect = [
            ExecutionResult(value=r, output=[], request_id="x") for r in responses
        ]
        result = geo.face_vertex_indices_all(chunk_size=1)
        self.assertEqual(len(result), 2)

    def test_normals_all_single_page(self):
        payload = {"total": 2, "start": 0, "normals": [[0, 1, 0], [0, -1, 0]]}
        geo, client = self._geo(payload)
        result = geo.normals_all()
        self.assertEqual(len(result), 2)

    def test_normals_all_paginates(self):
        responses = [
            {"total": 2, "start": 0, "normals": [[0, 1, 0]]},
            {"total": 2, "start": 1, "normals": [[0, -1, 0]]},
        ]
        from dazpy._result import ExecutionResult
        geo, _ = self._geo()
        geo._client.execute.side_effect = [
            ExecutionResult(value=r, output=[], request_id="x") for r in responses
        ]
        result = geo.normals_all(chunk_size=1)
        self.assertEqual(len(result), 2)

    def test_uv_positions_all_single_page(self):
        payload = {"total": 3, "start": 0, "uvs": [[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]]}
        geo, client = self._geo(payload)
        result = geo.uv_positions_all()
        self.assertEqual(len(result), 3)

    def test_uv_positions_all_paginates(self):
        responses = [
            {"total": 2, "start": 0, "uvs": [[0.0, 0.0]]},
            {"total": 2, "start": 1, "uvs": [[1.0, 1.0]]},
        ]
        from dazpy._result import ExecutionResult
        geo, _ = self._geo()
        geo._client.execute.side_effect = [
            ExecutionResult(value=r, output=[], request_id="x") for r in responses
        ]
        result = geo.uv_positions_all(chunk_size=1)
        self.assertEqual(len(result), 2)

    # ── group membership ──────────────────────────────────────────────────────

    def test_face_group_faces_single_call(self):
        geo, client = self._geo([0, 1, 4, 7])
        result = geo.face_group_faces("Body")
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result, [0, 1, 4, 7])

    def test_face_group_faces_script_uses_group_name(self):
        geo, client = self._geo([])
        geo.face_group_faces("Head")
        script = client.execute.call_args[0][0]
        self.assertIn("Head", script)
        self.assertIn("getFaceGroup", script)
        self.assertIn("getIndexAt", script)

    def test_face_group_faces_returns_empty_when_not_found(self):
        geo, client = self._geo(None)
        self.assertEqual(geo.face_group_faces("Missing"), [])

    def test_material_group_faces_single_call(self):
        geo, client = self._geo([2, 3, 5])
        result = geo.material_group_faces("Skin")
        self.assertEqual(client.execute.call_count, 1)
        self.assertEqual(result, [2, 3, 5])

    def test_material_group_faces_script_uses_group_name(self):
        geo, client = self._geo([])
        geo.material_group_faces("Eyes")
        script = client.execute.call_args[0][0]
        self.assertIn("Eyes", script)
        self.assertIn("getMaterialGroup", script)
        self.assertIn("getIndexAt", script)

    def test_material_group_faces_returns_empty_when_not_found(self):
        geo, client = self._geo(None)
        self.assertEqual(geo.material_group_faces("Missing"), [])

    # ── triangulate ───────────────────────────────────────────────────────────

    def test_triangulate_tri_passthrough(self):
        from dazpy._geometry import DazGeometry
        faces = [[0, 1, 2], [3, 4, 5]]
        result = DazGeometry.triangulate(faces)
        self.assertEqual(result, [[0, 1, 2], [3, 4, 5]])

    def test_triangulate_quad_splits_to_two_tris(self):
        from dazpy._geometry import DazGeometry
        result = DazGeometry.triangulate([[0, 1, 2, 3]])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], [0, 1, 2])
        self.assertEqual(result[1], [0, 2, 3])

    def test_triangulate_mixed_faces(self):
        from dazpy._geometry import DazGeometry
        faces = [[0, 1, 2], [0, 1, 2, 3]]
        result = DazGeometry.triangulate(faces)
        self.assertEqual(len(result), 3)

    def test_triangulate_unknown_face_size_skipped(self):
        from dazpy._geometry import DazGeometry
        result = DazGeometry.triangulate([[0, 1]])  # 2-vertex "face"
        self.assertEqual(result, [])

    def test_triangulate_empty_input(self):
        from dazpy._geometry import DazGeometry
        self.assertEqual(DazGeometry.triangulate([]), [])

    # ── as_vec3 ───────────────────────────────────────────────────────────────

    def test_as_vec3_returns_vec3_instances(self):
        from dazpy import Vec3
        from dazpy._geometry import DazGeometry
        verts = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        result = DazGeometry.as_vec3(verts)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], Vec3)

    def test_as_vec3_preserves_coordinates(self):
        from dazpy._geometry import DazGeometry
        result = DazGeometry.as_vec3([[1.5, 2.5, 3.5]])
        self.assertAlmostEqual(result[0].x, 1.5)
        self.assertAlmostEqual(result[0].y, 2.5)
        self.assertAlmostEqual(result[0].z, 3.5)

    def test_as_vec3_empty_input(self):
        from dazpy._geometry import DazGeometry
        self.assertEqual(DazGeometry.as_vec3([]), [])


if __name__ == "__main__":
    unittest.main()
