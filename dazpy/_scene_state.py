from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ._pose import DazPose
from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from ._scene import DazScene

_TRANSFORM_KEYS = ["XTranslate", "YTranslate", "ZTranslate", "XRotate", "YRotate", "ZRotate", "Scale"]
_LIGHT_EXTRA_KEYS = ["Flux", "Shadow Softness", "Spread Angle"]

# Shared JS snippet: read a property's own dial value rather than getValue()'s
# post-ERC computed total, for the same reason DazPose/DazProperty.raw_value
# do -- see DazPose.capture()'s docstring/comments for the full explanation.
_RAW_READ_JS = 'function _raw(p) { return (typeof p.getRawValue === "function") ? p.getRawValue() : p.getValue(); }'
_RAW_WRITE_JS = (
    'function _rawSet(p, v) { '
    'if (typeof p.setRawValue === "function") { p.setRawValue(v); } else { p.setValue(v); } }'
)


class DazSceneState:
    """A full snapshot of scene state, suitable for a save/restore checkpoint.

    Captures every skeleton's complete pose (bone rotations, morphs, and
    node-level properties -- see :class:`~dazpy.DazPose`) plus transform and
    a handful of key properties for every camera and light in the scene.
    Everything is captured and restored via each property's raw (pre-ERC)
    value, so repeated capture/apply cycles are idempotent even for
    properties driven by ``DzERCLink`` controllers (e.g. a "Scale" dial fed
    by dozens of linked morphs) -- see :class:`~dazpy.DazPose` and
    :attr:`~dazpy.DazProperty.raw_value` for why this matters.

    Skeletons, cameras, and lights are all keyed by their internal name
    (not display label), since labels are user-editable and not guaranteed
    unique.

    Typical workflow::

        from dazpy import DazScene, DazSceneState

        scene = DazScene()
        checkpoint = DazSceneState.capture(scene)
        ...  # experimental changes
        checkpoint.apply(scene)
    """

    def __init__(
        self,
        skeleton_poses: dict[str, DazPose],
        camera_transforms: dict[str, dict[str, float]],
        light_transforms: dict[str, dict[str, float]],
        light_extra: dict[str, dict[str, float]],
    ) -> None:
        self.skeleton_poses = skeleton_poses
        self.camera_transforms = camera_transforms
        self.light_transforms = light_transforms
        self.light_extra = light_extra

    # ── construction ──────────────────────────────────────────────────────────

    @classmethod
    def capture(cls, scene: "DazScene") -> "DazSceneState":
        """Capture the current state of every skeleton, camera, and light in *scene*.

        Args:
            scene: The scene to capture.

        Returns:
            A new :class:`DazSceneState`.
        """
        skeleton_poses = {
            skel._identifier.value: DazPose.capture(skel) for skel in scene.skeletons()
        }

        cam_script = ScriptBuilder.iife(f"""
            var _keys = {json.dumps(_TRANSFORM_KEYS)};
            {_RAW_READ_JS}
            function _captureTransforms(node) {{
                var t = {{}};
                for (var i = 0; i < _keys.length; i++) {{
                    var p = node.findProperty(_keys[i]);
                    if (p) t[_keys[i]] = _raw(p);
                }}
                return t;
            }}
            var result = {{}};
            for (var i = 0; i < Scene.getNumCameras(); i++) {{
                var c = Scene.getCamera(i);
                result[c.getName()] = _captureTransforms(c);
            }}
            return result;
        """)
        camera_transforms = scene._client.execute(cam_script).value or {}

        light_script = ScriptBuilder.iife(f"""
            var _keys = {json.dumps(_TRANSFORM_KEYS)};
            var _extraKeys = {json.dumps(_LIGHT_EXTRA_KEYS)};
            {_RAW_READ_JS}
            function _captureTransforms(node) {{
                var t = {{}};
                for (var i = 0; i < _keys.length; i++) {{
                    var p = node.findProperty(_keys[i]);
                    if (p) t[_keys[i]] = _raw(p);
                }}
                return t;
            }}
            var transforms = {{}};
            var extra = {{}};
            for (var i = 0; i < Scene.getNumLights(); i++) {{
                var l = Scene.getLight(i);
                var name = l.getName();
                transforms[name] = _captureTransforms(l);
                var e = {{}};
                for (var k = 0; k < _extraKeys.length; k++) {{
                    var p = l.findProperty(_extraKeys[k]);
                    if (p) e[_extraKeys[k]] = _raw(p);
                }}
                extra[name] = e;
            }}
            return {{transforms: transforms, extra: extra}};
        """)
        light_result = scene._client.execute(light_script).value or {}

        return cls(
            skeleton_poses=skeleton_poses,
            camera_transforms=camera_transforms,
            light_transforms=light_result.get("transforms", {}),
            light_extra=light_result.get("extra", {}),
        )

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return this snapshot as a plain, JSON-serialisable dict."""
        return {
            "skeletons": {name: pose.to_dict() for name, pose in self.skeleton_poses.items()},
            "cameras": self.camera_transforms,
            "lights": {"transforms": self.light_transforms, "extra": self.light_extra},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DazSceneState":
        """Reconstruct a snapshot from :meth:`to_dict`'s output."""
        skeletons = {
            name: DazPose(figure=name, bones=p.get("bones", {}), morphs=p.get("morphs", {}), props=p.get("props", {}))
            for name, p in data.get("skeletons", {}).items()
        }
        lights = data.get("lights", {})
        return cls(
            skeleton_poses=skeletons,
            camera_transforms=data.get("cameras", {}),
            light_transforms=lights.get("transforms", {}),
            light_extra=lights.get("extra", {}),
        )

    # ── apply ─────────────────────────────────────────────────────────────────

    def apply(self, scene: "DazScene") -> dict:
        """Apply this snapshot's skeleton poses, camera transforms, and light
        properties back onto *scene* in a small, fixed number of HTTP calls.

        Nodes that no longer exist in the scene are skipped and reported in
        ``errors`` rather than raising -- matching the behaviour of the
        registered-script checkpoint this class replaces.

        Args:
            scene: The scene to restore state into.

        Returns:
            ``{"restored": [name, ...], "errors": [message, ...]}``.
        """
        restored: list[str] = []
        errors: list[str] = []

        for name, pose in self.skeleton_poses.items():
            try:
                skel = scene.find_skeleton(name)
            except Exception:
                errors.append(f"Skeleton not found: {name}")
                continue
            pose.apply_full(skel)
            restored.append(name)

        restore_script = ScriptBuilder.iife(f"""
            var _camTransforms = {json.dumps(self.camera_transforms)};
            var _lightTransforms = {json.dumps(self.light_transforms)};
            var _lightExtra = {json.dumps(self.light_extra)};
            {_RAW_WRITE_JS}
            function _applyTransforms(node, transforms) {{
                for (var key in transforms) {{
                    var p = node.findProperty(key);
                    if (p) _rawSet(p, transforms[key]);
                }}
            }}
            var restored = [];
            var errors = [];

            for (var name in _camTransforms) {{
                var c = Scene.findNode(name);
                if (!c) {{ errors.push("Camera not found: " + name); continue; }}
                _applyTransforms(c, _camTransforms[name]);
                restored.push(name);
            }}

            for (var lname in _lightTransforms) {{
                var l = Scene.findNode(lname);
                if (!l) {{ errors.push("Light not found: " + lname); continue; }}
                _applyTransforms(l, _lightTransforms[lname]);
                var extra = _lightExtra[lname] || {{}};
                for (var ek in extra) {{
                    var ep = l.findProperty(ek);
                    if (ep) _rawSet(ep, extra[ek]);
                }}
                restored.push(lname);
            }}

            return {{restored: restored, errors: errors}};
        """)
        node_result = scene._client.execute(restore_script).value or {"restored": [], "errors": []}
        restored.extend(node_result.get("restored", []))
        errors.extend(node_result.get("errors", []))

        return {"restored": restored, "errors": errors}

    # ── dunder ────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"DazSceneState(skeletons={len(self.skeleton_poses)}, "
            f"cameras={len(self.camera_transforms)}, lights={len(self.light_transforms)})"
        )
