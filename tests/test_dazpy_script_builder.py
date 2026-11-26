"""dazpy unit tests: ScriptBuilder, injection safety, Batch and HTTP call-count budgets.

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

from dazpy._result import ExecutionResult
from dazpy._script_builder import ScriptBuilder
from dazpy._batch import Batch
from dazpy._node import NodeIdentifier
from dazpy._client import DazClient
from dazpy_fakes import mock_client


class TestScriptBuilder(unittest.TestCase):
    def test_escape_string_basic(self):
        self.assertEqual(ScriptBuilder.escape_string("hello"), '"hello"')

    def test_escape_string_quotes(self):
        result = ScriptBuilder.escape_string('say "hi"')
        self.assertIn('\\"', result)

    def test_escape_string_backslash(self):
        result = ScriptBuilder.escape_string("C:\\path\\file")
        self.assertIn("\\\\", result)

    def test_escape_string_newline(self):
        result = ScriptBuilder.escape_string("line1\nline2")
        self.assertIn("\\n", result)

    def test_escape_string_null_byte(self):
        result = ScriptBuilder.escape_string("null\x00byte")
        self.assertIn("\\u0000", result)

    def test_iife_wraps_body(self):
        result = ScriptBuilder.iife("return 42;")
        self.assertTrue(result.startswith("(function(){"))
        self.assertIn("return 42;", result)
        self.assertTrue(result.rstrip().endswith(")()"))

    def test_find_node_by_name(self):
        ident = NodeIdentifier("Genesis9", kind="name")
        expr = ScriptBuilder.find_node_expr(ident)
        self.assertIn('Scene.findNode(', expr)
        self.assertIn('"Genesis9"', expr)

    def test_find_node_by_label(self):
        ident = NodeIdentifier("Genesis 9", kind="label")
        expr = ScriptBuilder.find_node_expr(ident)
        self.assertIn('Scene.findNodeByLabel(', expr)
        self.assertIn('"Genesis 9"', expr)

    def test_serialize_arg_bool(self):
        self.assertEqual(ScriptBuilder.serialize_arg(True), "true")
        self.assertEqual(ScriptBuilder.serialize_arg(False), "false")

    def test_serialize_arg_int(self):
        self.assertEqual(ScriptBuilder.serialize_arg(42), "42")

    def test_serialize_arg_float(self):
        self.assertEqual(ScriptBuilder.serialize_arg(3.14), "3.14")

    def test_serialize_arg_string(self):
        self.assertEqual(ScriptBuilder.serialize_arg("hi"), '"hi"')

    def test_serialize_arg_dict(self):
        result = ScriptBuilder.serialize_arg({"x": 1})
        parsed = json.loads(result)
        self.assertEqual(parsed, {"x": 1})


class TestInjectionSafety(unittest.TestCase):
    """Adversarial strings must not break the generated script syntax."""

    ADVERSARIAL = [
        'say "hello"',
        "it's a test",
        "line1\nline2",
        "tab\there",
        "back\\slash",
        "null\x00byte",
        "</script>",
        "${injection}",
        "'; DROP TABLE nodes; --",
    ]

    def _script_is_valid_json_strings(self, value: str):
        """Ensure escape_string produces valid JSON."""
        escaped = ScriptBuilder.escape_string(value)
        parsed = json.loads(escaped)
        self.assertEqual(parsed, value)

    def test_all_adversarial_strings(self):
        for s in self.ADVERSARIAL:
            with self.subTest(s=s):
                self._script_is_valid_json_strings(s)


class TestBatch(unittest.TestCase):
    def test_batch_builds_single_script(self):
        client = mock_client({"_r0": 10, "_r1": 5})
        with Batch(client) as batch:
            f_count = batch.add(["var _r0 = Scene.getNumNodes();"])
            f_frame = batch.add(["var _r1 = Scene.getFrame();"])

        self.assertEqual(f_count.value, 10)
        self.assertEqual(f_frame.value, 5)
        client.execute.assert_called_once()

    def test_batch_script_contains_return_map(self):
        client = mock_client({"_r0": 42})
        batch = Batch(client)
        batch.add(["var _r0 = 42;"])
        batch.execute()
        script = client.execute.call_args[0][0]
        self.assertIn('"_r0"', script)
        self.assertIn("return", script)

    def test_future_raises_before_execute(self):
        client = mock_client({"_r0": 1})
        batch = Batch(client)
        future = batch.add(["var _r0 = 1;"])
        with self.assertRaises(RuntimeError):
            _ = future.value

    def test_empty_batch_no_call(self):
        client = mock_client(None)
        with Batch(client):
            pass
        client.execute.assert_not_called()


class TestCallCounts(unittest.TestCase):
    """Prove that the batch paths reduce HTTP call counts dramatically."""

    _BONE_META = [
        {"name": "hip",      "label": "Hip",        "parent_name": None,    "rotation_order": "YXZ",
         "local_position": {"x": 0, "y": 100, "z": 0}, "world_position": {"x": 0, "y": 100, "z": 0},
         "local_euler": {"x": 0, "y": 0, "z": 0}},
        {"name": "l_thigh",  "label": "LThigh",     "parent_name": "hip",   "rotation_order": "YXZ",
         "local_position": {"x": 10, "y": 80, "z": 0}, "world_position": {"x": 10, "y": 80, "z": 0},
         "local_euler": {"x": 0, "y": 0, "z": 0}},
        {"name": "l_shin",   "label": "LShin",      "parent_name": "l_thigh","rotation_order": "YXZ",
         "local_position": {"x": 10, "y": 50, "z": 0}, "world_position": {"x": 10, "y": 50, "z": 0},
         "local_euler": {"x": 0, "y": 0, "z": 0}},
        {"name": "l_foot",   "label": "LFoot",      "parent_name": "l_shin","rotation_order": "YXZ",
         "local_position": {"x": 10, "y": 10, "z": 0}, "world_position": {"x": 10, "y": 10, "z": 0},
         "local_euler": {"x": 0, "y": 0, "z": 0}},
    ]
    _BONE_ROTS = {b["name"]: [0.0, 0.0, 0.0] for b in _BONE_META}
    _JACOBIAN = {
        "base_position": [10.0, 10.0, 0.0],
        "columns": [[1, 0, 0], [0, 1, 0], [0, 0, 1]] * 4,
    }

    def _make_batch_skeleton(self, max_iterations=12):
        from dazpy._skeleton import DazSkeleton
        from dazpy._node import NodeIdentifier

        def _execute(script):
            if "getLabel" in script and "getAllBones" not in script:
                return ExecutionResult(value="Genesis 9", output=[], request_id="x")
            if "_columns" in script:
                return ExecutionResult(value=self._JACOBIAN, output=[], request_id="x")
            if "getLocalPos" in script:
                return ExecutionResult(value=self._BONE_META, output=[], request_id="x")
            # bone_rotations or set_bone_rotations — return rotations dict or None
            if "_result" in script:
                return ExecutionResult(value=self._BONE_ROTS, output=[], request_id="x")
            return ExecutionResult(value=None, output=[], request_id="x")

        client = MagicMock(spec=DazClient)
        client.execute.side_effect = _execute

        skel = DazSkeleton(client, NodeIdentifier("Genesis 9", kind="label"))
        return skel, client

    def test_align_hand_target_call_count_bounded(self):
        """align_hand_target must use ≤ 30 execute calls for 12 iterations."""
        skel, client = self._make_batch_skeleton()
        from dazpy import align_hand_target
        align_hand_target(skel, (50.0, 10.0, 0.0), source_anchor="l_foot", max_iterations=12)
        # Old per-bone approach: ~500 calls for a 4-bone chain, 12 iterations.
        # Batch approach: 1 (label) + 1 (bone_meta) + 1 (bone_rots) + 1 (init jac) + 12×2 = 28.
        self.assertLessEqual(client.execute.call_count, 30)

    def test_align_foot_target_call_count_bounded(self):
        """align_foot_target must use ≤ 30 execute calls for 12 iterations."""
        skel, client = self._make_batch_skeleton()
        from dazpy import align_foot_target
        align_foot_target(skel, (50.0, 10.0, 0.0), source_anchor="l_foot", max_iterations=12)
        self.assertLessEqual(client.execute.call_count, 30)

    def test_align_hand_target_iterations_proportional(self):
        """Call count scales linearly with max_iterations (2 calls/iter + O(1) setup)."""
        skel3, client3 = self._make_batch_skeleton()
        skel6, client6 = self._make_batch_skeleton()
        from dazpy import align_hand_target
        align_hand_target(skel3, (50.0, 10.0, 0.0), source_anchor="l_foot", max_iterations=3)
        align_hand_target(skel6, (50.0, 10.0, 0.0), source_anchor="l_foot", max_iterations=6)
        # Extra calls for 3 more iterations ≤ 7 (3 extra iters × 2 + rounding)
        delta = client6.execute.call_count - client3.execute.call_count
        self.assertLessEqual(delta, 7)

    def test_build_rig_profile_world_position_populated(self):
        """build_rig_profile populates world_position from bone_metadata()."""
        from dazpy import build_rig_profile
        skel, _ = self._make_batch_skeleton()
        profile = build_rig_profile(skel)
        foot = profile.bone("l_foot")
        self.assertIsNotNone(foot.world_position)
        self.assertEqual(foot.world_position, (10.0, 10.0, 0.0))

    def test_bone_metadata_includes_world_position(self):
        """bone_metadata() script must request getWSPos()."""
        skel, client = self._make_batch_skeleton()
        skel.bone_metadata()
        script = client.execute.call_args[0][0]
        self.assertIn("getWSPos", script)
        self.assertIn("world_position", script)

    def test_bone_metadata_rotation_order_stringified(self):
        skel, client = self._make_batch_skeleton()
        skel.bone_metadata()
        script = client.execute.call_args[0][0]
        self.assertIn("getRotationOrder().toString()", script)

    def test_bone_metadata_includes_rest_orientation_and_axis_limits(self):
        skel, client = self._make_batch_skeleton()
        skel.bone_metadata()
        script = client.execute.call_args[0][0]
        self.assertIn("getOrientation()", script)
        self.assertIn("rest_orientation", script)
        self.assertIn("axis_limits", script)
        self.assertIn("getMin()", script)
        self.assertIn("getMax()", script)


class TestBatchAddOperation(unittest.TestCase):
    def test_add_operation_resolves_without_caller_guessing_key(self):
        client = mock_client({"_r0": 42})
        from dazpy._batch import Batch
        batch = Batch(client)
        future = batch.add_operation(
            body_lines=["var x = 20 + 22;"],
            result_expression="x",
        )
        batch.execute()
        self.assertEqual(future.value, 42)
        script = client.execute.call_args[0][0]
        self.assertIn("var _r0 = x;", script)

    def test_shared_prelude_emitted_once_for_two_operations(self):
        client = mock_client({"_r0": 1, "_r1": 2})
        from dazpy._batch import Batch
        batch = Batch(client)
        batch.add_prelude("node:Fig", ["var _node_Fig = Scene.findNode('Fig');"])
        batch.add_operation(body_lines=[], result_expression="_node_Fig.getXRotControl().getValue()")
        batch.add_prelude("node:Fig", ["var _node_Fig = Scene.findNode('Fig');"])  # same key, second call
        batch.add_operation(body_lines=[], result_expression="_node_Fig.getYRotControl().getValue()")
        batch.execute()
        script = client.execute.call_args[0][0]
        self.assertEqual(script.count("Scene.findNode('Fig')"), 1)
        self.assertEqual(client.execute.call_count, 1)

    def test_read_after_write_order_preserved(self):
        client = mock_client({"_r0": None, "_r1": 99})
        from dazpy._batch import Batch
        batch = Batch(client)
        batch.add_operation(body_lines=["var _v = 99;"], result_expression="null")
        batch.add_operation(body_lines=[], result_expression="_v")
        batch.execute()
        script = client.execute.call_args[0][0]
        self.assertLess(script.index("var _v = 99;"), script.index("var _r1 = _v;"))

    def test_operation_count_limit_raises_before_execute(self):
        client = mock_client({})
        from dazpy._batch import Batch
        from dazpy.exceptions import BatchLimitExceededError
        batch = Batch(client, max_operations=2)
        batch.add_operation(body_lines=[], result_expression="1")
        batch.add_operation(body_lines=[], result_expression="2")
        with self.assertRaises(BatchLimitExceededError):
            batch.add_operation(body_lines=[], result_expression="3")
        client.execute.assert_not_called()

    def test_script_length_limit_raises_on_execute(self):
        client = mock_client({})
        from dazpy._batch import Batch
        from dazpy.exceptions import BatchLimitExceededError
        batch = Batch(client, max_script_length=50)
        batch.add_operation(body_lines=["var x = 1;" * 20], result_expression="x")
        with self.assertRaises(BatchLimitExceededError):
            batch.execute()
        client.execute.assert_not_called()

    def test_existing_raw_add_still_works_unmodified(self):
        # Regression guard: add_operation()/add_prelude() must not change add()'s behavior.
        client = mock_client({"_r0": 10, "_r1": 5})
        from dazpy._batch import Batch
        with Batch(client) as batch:
            f_count = batch.add(["var _r0 = Scene.getNumNodes();"])
            f_frame = batch.add(["var _r1 = Scene.getFrame();"])
        self.assertEqual(f_count.value, 10)
        self.assertEqual(f_frame.value, 5)
        client.execute.assert_called_once()


class TestCallCountBaseline(unittest.TestCase):
    """Pins down pre-batching call counts. Update these assertions in the
    same commit that fixes the corresponding helper in Task 2/3 — do not
    let this class silently mask a regression by staying loose."""

    def test_batch_add_issues_one_call_for_two_ops(self):
        client = mock_client({"_r0": 10, "_r1": 5})
        from dazpy._batch import Batch
        with Batch(client) as b:
            b.add(["var _r0 = Scene.getNumNodes();"])
            b.add(["var _r1 = Scene.getFrame();"])
        self.assertEqual(client.execute.call_count, 1)


if __name__ == "__main__":
    unittest.main()
