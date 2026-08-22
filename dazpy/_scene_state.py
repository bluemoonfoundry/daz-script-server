from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from .exceptions import DazBusyError
from ._pose import _ZERO3, DazPose
from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from ._scene import DazScene

_TRANSFORM_KEYS = ["XTranslate", "YTranslate", "ZTranslate", "XRotate", "YRotate", "ZRotate", "Scale"]
_LIGHT_EXTRA_KEYS = ["Flux", "Shadow Softness", "Spread Angle"]
_DEFAULT_VERIFY_TOLERANCE = 0.05
_DEFAULT_MAX_VERIFY_RETRIES = 2
_FOLLOW_TARGET_RETRY_MAX_WAIT = 30.0


def _retry_on_busy(fn, max_wait: float = _FOLLOW_TARGET_RETRY_MAX_WAIT):
    """Run *fn* (a zero-arg callable), retrying with backoff on DazBusyError.

    follow_target()/fit_to()/unfit() (unlike DazPose.apply_full(), which
    takes its own retry_on_busy param) don't expose retry-on-busy directly,
    but apply()'s follow-target restoration pass makes several of these
    calls back-to-back per skeleton on top of the pose-restore/verify calls
    already made for every skeleton in the scene -- under that load a
    single skeleton's follow-target fix can transiently hit StudioBusyError
    even though the overall restore succeeds for every other skeleton. This
    mirrors DazClient._with_busy_retry's backoff without depending on it.
    """
    deadline = time.monotonic() + max_wait
    backoff = 1.0
    while True:
        try:
            return fn()
        except DazBusyError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(backoff, remaining))
            backoff = min(backoff + 1.0, 5.0)


def _pose_mismatches(expected: DazPose, actual: DazPose, tolerance: float) -> list[str]:
    """Return a description of every channel where *actual* does not match
    *expected* within *tolerance*, or an empty list if they match.

    Missing keys in either pose are treated as zero, matching the sparse
    (zero-omitted) storage :class:`DazPose` uses.
    """
    mismatches: list[str] = []

    for key in set(expected.bones) | set(actual.bones):
        exp = expected.bones.get(key, _ZERO3)
        act = actual.bones.get(key, _ZERO3)
        if any(abs(e - a) > tolerance for e, a in zip(exp, act)):
            mismatches.append(f"bone {key} (expected {exp}, got {act})")

    for key in set(expected.morphs) | set(actual.morphs):
        exp_v = expected.morphs.get(key, 0.0)
        act_v = actual.morphs.get(key, 0.0)
        if abs(exp_v - act_v) > tolerance:
            mismatches.append(f"morph {key} (expected {exp_v}, got {act_v})")

    for key in set(expected.props) | set(actual.props):
        exp_v = expected.props.get(key, 0.0)
        act_v = actual.props.get(key, 0.0)
        if abs(exp_v - act_v) > tolerance:
            mismatches.append(f"prop {key} (expected {exp_v}, got {act_v})")

    return mismatches

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
        follow_targets: dict[str, str | None] | None = None,
    ) -> None:
        self.skeleton_poses = skeleton_poses
        self.camera_transforms = camera_transforms
        self.light_transforms = light_transforms
        self.light_extra = light_extra
        # Each skeleton's conform/fit-to relationship (by target skeleton
        # name, or None if unfitted), captured and restored independently
        # of DazPose's generic bones/morphs/props. DazPose.apply_full()
        # writes back every property on a skeleton, including the internal
        # "FID_<name>" property DAZ Studio uses to persist a conforming
        # item's fit registration -- rewriting that property (even to the
        # exact value captured) desyncs the live getFollowTarget() pointer
        # without raising any error. See daz-script-server-jz0e: a
        # dedicated capture/restore pass via the real
        # getFollowTarget()/setFollowTarget() API is the only reliable fix.
        self.follow_targets = follow_targets or {}

    # ── construction ──────────────────────────────────────────────────────────

    @classmethod
    def capture(cls, scene: "DazScene") -> "DazSceneState":
        """Capture the current state of every skeleton, camera, and light in *scene*.

        Args:
            scene: The scene to capture.

        Returns:
            A new :class:`DazSceneState`.
        """
        skeleton_poses: dict[str, DazPose] = {}
        follow_targets: dict[str, str | None] = {}
        for skel in scene.skeletons():
            name = skel._identifier.value
            skeleton_poses[name] = DazPose.capture(skel)
            target = skel.follow_target()
            follow_targets[name] = target._identifier.value if target is not None else None

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
            follow_targets=follow_targets,
        )

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return this snapshot as a plain, JSON-serialisable dict."""
        return {
            "skeletons": {name: pose.to_dict() for name, pose in self.skeleton_poses.items()},
            "cameras": self.camera_transforms,
            "lights": {"transforms": self.light_transforms, "extra": self.light_extra},
            "follow_targets": self.follow_targets,
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
            follow_targets=data.get("follow_targets", {}),
        )

    # ── apply ─────────────────────────────────────────────────────────────────

    def apply(
        self,
        scene: "DazScene",
        *,
        max_verify_retries: int = _DEFAULT_MAX_VERIFY_RETRIES,
        verify_tolerance: float = _DEFAULT_VERIFY_TOLERANCE,
    ) -> dict:
        """Apply this snapshot's skeleton poses, camera transforms, and light
        properties back onto *scene* in a small, fixed number of HTTP calls.

        Nodes that no longer exist in the scene are skipped and reported in
        ``errors`` rather than raising -- matching the behaviour of the
        registered-script checkpoint this class replaces.

        Each skeleton restore is independently verified: after
        ``pose.apply_full(skel)`` returns, a fresh :meth:`DazPose.capture` is
        taken and compared against the checkpoint. This guards against
        ``apply_full()`` reporting success for a restore DAZ Studio's
        single-threaded main loop only partially executed under contention
        (see dpi-mxq) -- the HTTP call can return normally even though some
        bone/morph/prop writes never happened. A skeleton whose read-back
        doesn't match is retried (re-running ``apply_full`` and re-verifying)
        up to *max_verify_retries* times before being reported in ``errors``
        instead of ``restored``, so callers never trust an unverified result.

        Args:
            scene: The scene to restore state into.
            max_verify_retries: How many additional ``apply_full`` attempts to
                make for a skeleton whose read-back doesn't verify, before
                giving up on it.
            verify_tolerance: Per-channel tolerance (degrees for bones, raw
                value units for morphs/props) allowed between the checkpoint
                and the read-back before it's considered a mismatch.

        Returns:
            ``{"restored": [name, ...], "errors": [message, ...]}``.
        """
        restored: list[str] = []
        errors: list[str] = []
        resolved_skeletons: dict[str, "DazSkeleton"] = {}  # noqa: F821

        for name, pose in self.skeleton_poses.items():
            try:
                skel = scene.find_skeleton(name)
                resolved_skeletons[name] = skel
            except Exception:
                errors.append(f"Skeleton not found: {name}")
                continue

            attempt = 0
            failed = False
            mismatches: list[str] = []
            while True:
                try:
                    pose.apply_full(skel)
                except Exception as exc:
                    errors.append(f"Failed to restore skeleton {name}: {exc}")
                    failed = True
                    break

                try:
                    actual = DazPose.capture(skel)
                except Exception as exc:
                    errors.append(f"Failed to verify restore of skeleton {name}: {exc}")
                    failed = True
                    break

                mismatches = _pose_mismatches(pose, actual, verify_tolerance)
                if not mismatches or attempt >= max_verify_retries:
                    break
                attempt += 1

            if failed:
                continue
            if mismatches:
                errors.append(
                    f"Restore of skeleton {name} did not verify after "
                    f"{attempt + 1} attempt(s): {'; '.join(mismatches)}"
                )
                continue
            restored.append(name)

        # Restore each successfully-restored skeleton's conform/fit-to
        # relationship explicitly via the real getFollowTarget()/
        # setFollowTarget() API -- apply_full() above already wrote back
        # this skeleton's own "FID_*" property as part of its generic
        # props restore, but doing so does not reliably re-resolve the
        # live follow-target pointer (see daz-script-server-jz0e). Only
        # touches skeletons whose current follow-target doesn't already
        # match what was captured, to avoid redundant calls.
        for name in restored:
            skel = resolved_skeletons[name]
            target_name = self.follow_targets.get(name)
            try:
                current = _retry_on_busy(skel.follow_target)
                current_name = current._identifier.value if current is not None else None
                if current_name == target_name:
                    continue
                if target_name is None:
                    _retry_on_busy(skel.unfit)
                else:
                    target_skel = resolved_skeletons.get(target_name) or scene.find_skeleton(target_name)
                    _retry_on_busy(lambda: skel.fit_to(target_skel))
            except Exception as exc:
                errors.append(f"Failed to restore follow-target for skeleton {name}: {exc}")

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
        node_result = scene._client.execute(
            restore_script, retry_on_busy=True, max_wait=_FOLLOW_TARGET_RETRY_MAX_WAIT
        ).value or {"restored": [], "errors": []}
        restored.extend(node_result.get("restored", []))
        errors.extend(node_result.get("errors", []))

        return {"restored": restored, "errors": errors}

    # ── dunder ────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"DazSceneState(skeletons={len(self.skeleton_poses)}, "
            f"cameras={len(self.camera_transforms)}, lights={len(self.light_transforms)})"
        )
