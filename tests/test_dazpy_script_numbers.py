"""Non-finite numbers must never reach generated DazScript (yau7.6.5).

``str(float("nan"))`` is ``nan``, which DazScript reads as an undefined
identifier (ReferenceError), and ``inf`` likewise. ``NaN``/``Infinity`` are
valid JS but would silently write garbage into the scene. Every numeric
interpolation goes through ``ScriptBuilder.js_num``, which raises
``ValueError`` client-side before any request is sent.
"""

import math
from unittest.mock import MagicMock

import pytest

from dazpy import DazClient
from dazpy._camera import DazCamera
from dazpy._material import DazMaterial
from dazpy._morph import DazMorph
from dazpy._node import DazNode, NodeIdentifier
from dazpy._property import DazProperty
from dazpy._render import DazRenderSettings
from dazpy._result import ExecutionResult
from dazpy._script_builder import ScriptBuilder

NON_FINITE = [math.nan, math.inf, -math.inf]
NON_FINITE_IDS = ["nan", "inf", "-inf"]


@pytest.mark.parametrize("value,expected", [
    (0, "0.0"), (3, "3.0"), (-2, "-2.0"), (1.5, "1.5"), (-0.25, "-0.25"),
    (1e-7, "1e-07"), ("2.5", "2.5"),
])
def test_js_num_formats_finite_numbers(value, expected):
    assert ScriptBuilder.js_num(value) == expected


@pytest.mark.parametrize("value", NON_FINITE, ids=NON_FINITE_IDS)
def test_js_num_rejects_non_finite(value):
    with pytest.raises(ValueError, match="finite"):
        ScriptBuilder.js_num(value)


@pytest.mark.parametrize("value", NON_FINITE, ids=NON_FINITE_IDS)
def test_serialize_arg_rejects_non_finite(value):
    with pytest.raises(ValueError):
        ScriptBuilder.serialize_arg(value)
    with pytest.raises(ValueError):
        ScriptBuilder.serialize_arg([1.0, value])


def test_serialize_arg_keeps_finite_values():
    assert ScriptBuilder.serialize_arg(True) == "true"
    assert ScriptBuilder.serialize_arg(7) == "7"
    assert ScriptBuilder.serialize_arg(0.5) == "0.5"
    assert ScriptBuilder.serialize_arg("a") == '"a"'
    assert ScriptBuilder.serialize_arg([1, 2.5]) == "[1, 2.5]"


def _client():
    client = MagicMock(spec=DazClient)
    client.execute.return_value = ExecutionResult(value=None, output=[], request_id="t")
    return client


def _node(client):
    return DazNode(client, NodeIdentifier("Genesis 9"))


def _camera(client):
    return DazCamera(client, NodeIdentifier("Camera 1"))


# Each entry writes `v` (the bad number) through one public setter.
SETTERS = {
    "node.set_position": lambda c, v: _node(c).set_position(0, v, 0),
    "node.set_scale": lambda c, v: _node(c).set_scale(1, 1, v),
    "node.set_rotation": lambda c, v: _node(c).set_rotation(v, 0, 0),
    "node.set_position_at_frame": lambda c, v: _node(c).set_position_at_frame(0, 0, 0, v),
    "node.set_rotation_at_frame": lambda c, v: _node(c).set_rotation_at_frame(0, 0, v, 0),
    "camera.focal_length": lambda c, v: setattr(_camera(c), "focal_length", v),
    "camera.aim_at": lambda c, v: _camera(c).aim_at(v, 0, 0),
    "morph.value": lambda c, v: setattr(DazMorph(c, "m"), "value", v),
    "material.opacity": lambda c, v: setattr(DazMaterial(c, "m"), "opacity", v),
    "material.smoothing_angle": lambda c, v: setattr(DazMaterial(c, "m"), "smoothing_angle", v),
    "property.value": lambda c, v: setattr(DazProperty(c, "o", "p"), "value", v),
    "property.set_key": lambda c, v: DazProperty(c, "o", "p").set_key(0.0, v),
    "property.set_key_time": lambda c, v: DazProperty(c, "o", "p").set_key(v, 1.0),
    "render.gamma": lambda c, v: setattr(DazRenderSettings(c), "gamma", v),
}


@pytest.mark.parametrize("value", NON_FINITE, ids=NON_FINITE_IDS)
@pytest.mark.parametrize("name", sorted(SETTERS))
def test_setter_rejects_non_finite_without_a_request(name, value):
    client = _client()
    with pytest.raises(ValueError):
        SETTERS[name](client, value)
    client.execute.assert_not_called()


@pytest.mark.parametrize("name", sorted(SETTERS))
def test_setter_still_sends_finite_values(name):
    client = _client()
    SETTERS[name](client, 0.5)
    assert client.execute.called
    script = client.execute.call_args[0][0]
    assert "nan" not in script.lower().replace("_nan", "")


# ── yau7.6.10: JSON payloads embedded in scripts ───────────────────────────
# json.dumps writes nan/inf as NaN/Infinity, which is valid JS, so no error
# would surface: the garbage would just be written into the scene.

from dazpy._pose import DazPose
from dazpy._skeleton import DazSkeleton


def test_to_js_matches_json_dumps_for_finite_values():
    import json
    for value in ["a\"b", 1, 2.5, [1, {"k": [0.5, None, True]}], {"x": "y"}]:
        assert ScriptBuilder.to_js(value) == json.dumps(value)


@pytest.mark.parametrize("value", NON_FINITE, ids=NON_FINITE_IDS)
def test_to_js_rejects_non_finite_anywhere(value):
    for payload in [value, [value], {"a": {"b": [1, value]}}]:
        with pytest.raises(ValueError, match="finite"):
            ScriptBuilder.to_js(payload)


def _skeleton(client):
    return DazSkeleton(client, NodeIdentifier("Genesis 9"))


PAYLOAD_WRITERS = {
    "node.set_numeric_candidates":
        lambda c, v: _node(c).set_numeric_candidates([(["Smile"], v)]),
    "node.set_dforce_influence_weights.default":
        lambda c, v: _node(c).set_dforce_influence_weights(default=v),
    "node.set_dforce_influence_weights.override":
        lambda c, v: _node(c).set_dforce_influence_weights(overrides={3: v}),
    "pose.apply.bone":
        lambda c, v: DazPose("Genesis 9", {"lHand": [0, v, 0]}, {}, {}).apply(_skeleton(c)),
    "pose.apply.morph":
        lambda c, v: DazPose("Genesis 9", {}, {"Smile": v}, {}).apply(_skeleton(c)),
    "pose.apply_full.prop":
        lambda c, v: DazPose("Genesis 9", {}, {}, {"XTranslate": v}).apply_full(_skeleton(c)),
}


@pytest.mark.parametrize("value", NON_FINITE, ids=NON_FINITE_IDS)
@pytest.mark.parametrize("name", sorted(PAYLOAD_WRITERS))
def test_payload_writer_rejects_non_finite_without_a_request(name, value):
    client = _client()
    with pytest.raises(ValueError):
        PAYLOAD_WRITERS[name](client, value)
    client.execute.assert_not_called()


def test_script_modules_do_not_use_json_dumps():
    """Script-building code must use ScriptBuilder.to_js (allow_nan=False)."""
    import pathlib
    import re
    allowed = {"_script_builder.py", "_recipe_store.py"}  # builder itself; on-disk records
    root = pathlib.Path(__file__).resolve().parent.parent / "dazpy"
    offenders = [
        f"{p.name}:{i}"
        for p in sorted(root.glob("*.py")) if p.name not in allowed
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\bjson\.dumps\(", line)
    ]
    assert offenders == [], f"use ScriptBuilder.to_js instead of json.dumps: {offenders}"
