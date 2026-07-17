from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from ._skeleton import DazSkeleton


class DazPose:
    """A snapshot of a figure's complete pose state.

    Stores bone rotations (Euler XYZ degrees), geometry morph values, and
    node-level numeric properties.  Sparse by default — zero values are omitted
    so the object stays compact for morph-heavy figures.

    Typical workflow::

        from dazpy import DazScene, DazPose

        scene = DazScene()
        figure = scene.find_skeleton_by_label("Genesis 9")

        neutral = DazPose.capture(figure)
        neutral.save("neutral.json")

        smile = DazPose.load("smile.json")
        neutral.lerp(smile, t=0.5).apply(figure)

    JSON schema (same as ``character_state.py`` output)::

        {
          "figure": "Genesis 9",
          "bones":  {"hip": [0, 2.3, 0], "rForeArm": [0, 0, -45]},
          "morphs": {"PHMSmileFull": 0.8},
          "props":  {"facs_ctrl_SmileFullFace": 0.5}
        }

    Args:
        figure: The label of the figure this pose belongs to.
        bones:  Bone name → ``[x, y, z]`` Euler angles in degrees.
        morphs: Morph name → blend value (typically 0–1).
        props:  Node property name → numeric value.
    """

    def __init__(
        self,
        figure: str,
        bones: dict[str, list[float]],
        morphs: dict[str, float],
        props: dict[str, float],
    ) -> None:
        self.figure = figure
        self.bones = bones
        self.morphs = morphs
        self.props = props

    # ── construction ──────────────────────────────────────────────────────────

    @classmethod
    def capture(cls, skeleton: "DazSkeleton") -> "DazPose":
        """Capture the current pose of *skeleton* in a single HTTP call.

        Records all non-zero bone rotations, morph values, and node-level
        numeric properties.  Zero values are omitted (sparse storage); they are
        implied as 0.0 during :meth:`lerp` and :meth:`apply_full`.

        Args:
            skeleton: The figure to capture.

        Returns:
            A new :class:`DazPose`.

        Raises:
            ~dazpy.exceptions.NodeNotFoundError: If the skeleton is not found.
        """
        lookup = ScriptBuilder.skeleton_lookup(skeleton._identifier)
        script = f"""(function(){{
            {lookup}
            if (!_skel) return null;

            var bones = {{}};
            var all = _skel.getAllBones();
            for (var i = 0; i < all.length; i++) {{
                var b = all[i];
                var x = b.getXRotControl().getValue();
                var y = b.getYRotControl().getValue();
                var z = b.getZRotControl().getValue();
                if (Math.abs(x) > 0.0001 || Math.abs(y) > 0.0001 || Math.abs(z) > 0.0001)
                    bones[b.getName()] = [x, y, z];
            }}

            // Morphs can themselves be ERC targets (e.g. a master "Character"
            // dial that fans out to dozens of shape morphs via DzERCLink),
            // so read raw values here for the same reason as props below.
            var morphs = {{}};
            var obj = _skel.getObject();
            if (obj) {{
                for (var i = 0; i < obj.getNumModifiers(); i++) {{
                    var m = obj.getModifier(i);
                    if (m.className() === "DzMorph") {{
                        var ch = m.getValueChannel();
                        var v = (typeof ch.getRawValue === "function") ? ch.getRawValue() : ch.getValue();
                        if (Math.abs(v) > 0.0001) morphs[m.getName()] = v;
                    }}
                }}
            }}

            // Read the property's own dial setting rather than getValue()'s
            // post-ERC computed total. Properties driven by DzERCLink
            // controllers (e.g. a "Scale" dial fed by dozens of linked
            // morphs) return a getValue() that already includes every
            // controller's contribution; capturing that and writing it back
            // via setValue() on apply() would re-add the same contributions
            // on top, inflating the property a little more on every
            // capture/apply cycle. getRawValue() reads only the property's
            // own baseline and round-trips correctly regardless of ERC links.
            var props = {{}};
            for (var i = 0; i < _skel.getNumProperties(); i++) {{
                var p = _skel.getProperty(i);
                if (p && p.getValue) {{
                    var v = (typeof p.getRawValue === "function") ? p.getRawValue() : p.getValue();
                    if (typeof v === "number" && Math.abs(v) > 0.0001)
                        props[p.getName()] = v;
                }}
            }}

            return {{bones: bones, morphs: morphs, props: props}};
        }})()"""

        result = skeleton._client.execute(script).value
        if result is None:
            from .exceptions import NodeNotFoundError
            raise NodeNotFoundError(f"Skeleton not found: {skeleton._identifier.value!r}")

        return cls(
            figure=skeleton._identifier.value,
            bones=result["bones"],
            morphs=result["morphs"],
            props=result["props"],
        )

    @classmethod
    def load(cls, path: str | Path) -> "DazPose":
        """Load a pose from a JSON file.

        Accepts files produced by :meth:`save` and by the ``character_state.py``
        example script.

        Args:
            path: Path to the JSON file.

        Returns:
            A new :class:`DazPose`.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            figure=data.get("figure", ""),
            bones=data.get("bones", {}),
            morphs=data.get("morphs", {}),
            props=data.get("props", {}),
        )

    # ── serialisation ─────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Write this pose to a JSON file.

        Args:
            path: Destination path.  Parent directories must exist.
        """
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def to_dict(self) -> dict:
        """Return the pose as a plain dict (same schema as the JSON file)."""
        return {
            "figure": self.figure,
            "bones":  self.bones,
            "morphs": self.morphs,
            "props":  self.props,
        }

    # ── interpolation ─────────────────────────────────────────────────────────

    def lerp(self, other: "DazPose", t: float) -> "DazPose":
        """Linearly interpolate between this pose and *other*.

        Missing keys in either pose are treated as zero.  The result uses the
        figure label from *self*.

        This is a pure-Python operation — no HTTP round-trip.

        Args:
            other: The target pose (``t=1.0`` yields an exact copy of *other*).
            t: Blend factor.  0.0 = this pose, 1.0 = *other*.  Values outside
               [0, 1] extrapolate.

        Returns:
            A new :class:`DazPose` at the interpolated position.
        """
        def _l(a: float, b: float) -> float:
            return a + (b - a) * t

        bones = {
            k: [
                _l(self.bones.get(k, _ZERO3)[i], other.bones.get(k, _ZERO3)[i])
                for i in range(3)
            ]
            for k in set(self.bones) | set(other.bones)
        }
        morphs = {
            k: _l(self.morphs.get(k, 0.0), other.morphs.get(k, 0.0))
            for k in set(self.morphs) | set(other.morphs)
        }
        props = {
            k: _l(self.props.get(k, 0.0), other.props.get(k, 0.0))
            for k in set(self.props) | set(other.props)
        }
        return DazPose(figure=self.figure, bones=bones, morphs=morphs, props=props)

    # ── apply ─────────────────────────────────────────────────────────────────

    def apply(self, skeleton: "DazSkeleton") -> None:
        """Apply this pose to *skeleton* in a single HTTP call.

        Only channels present in the pose are changed.  Bones and morphs not
        stored in the pose are left at their current values.  Use
        :meth:`apply_full` when you need a clean, authoritative reset to exactly
        this pose.

        Args:
            skeleton: The figure to pose.
        """
        lookup = ScriptBuilder.skeleton_lookup(skeleton._identifier)
        bones_json  = json.dumps({k: [round(v, 6) for v in xyz] for k, xyz in self.bones.items()})
        morphs_json = json.dumps({k: round(v, 6) for k, v in self.morphs.items()})
        props_json  = json.dumps({k: round(v, 6) for k, v in self.props.items()})

        script = f"""(function(){{
            {lookup}
            if (!_skel) return false;
            var _bones  = {bones_json};
            var _morphs = {morphs_json};
            var _props  = {props_json};

            var all = _skel.getAllBones();
            for (var i = 0; i < all.length; i++) {{
                var b = all[i];
                var xyz = _bones[b.getName()];
                if (xyz !== undefined) {{
                    b.getXRotControl().setValue(xyz[0]);
                    b.getYRotControl().setValue(xyz[1]);
                    b.getZRotControl().setValue(xyz[2]);
                }}
            }}

            // Write back to the raw dial slot, mirroring capture()'s use of
            // getRawValue() -- see the comment there for why setValue()
            // would double-apply ERC-controller contributions on properties
            // like morphs or a "Scale" dial that are DzERCLink targets.
            var obj = _skel.getObject();
            if (obj) {{
                for (var i = 0; i < obj.getNumModifiers(); i++) {{
                    var m = obj.getModifier(i);
                    if (m.className() === "DzMorph") {{
                        var v = _morphs[m.getName()];
                        if (v !== undefined) {{
                            var ch = m.getValueChannel();
                            if (typeof ch.setRawValue === "function") {{ ch.setRawValue(v); }}
                            else {{ ch.setValue(v); }}
                        }}
                    }}
                }}
            }}

            for (var i = 0; i < _skel.getNumProperties(); i++) {{
                var p = _skel.getProperty(i);
                if (p && p.setValue) {{
                    var v = _props[p.getName()];
                    if (v !== undefined) {{
                        if (typeof p.setRawValue === "function") {{ p.setRawValue(v); }}
                        else {{ p.setValue(v); }}
                    }}
                }}
            }}

            return true;
        }})()"""

        skeleton._client.execute(script)

    def apply_full(self, skeleton: "DazSkeleton") -> None:
        """Apply this pose and zero every channel not present in the pose.

        Unlike :meth:`apply`, every bone rotation, morph, and node property on
        the skeleton is explicitly set — channels absent from the pose are driven
        to zero.  Use this to restore a known baseline cleanly.

        Args:
            skeleton: The figure to pose.
        """
        lookup = ScriptBuilder.skeleton_lookup(skeleton._identifier)
        bones_json  = json.dumps({k: [round(v, 6) for v in xyz] for k, xyz in self.bones.items()})
        morphs_json = json.dumps({k: round(v, 6) for k, v in self.morphs.items()})
        props_json  = json.dumps({k: round(v, 6) for k, v in self.props.items()})

        script = f"""(function(){{
            {lookup}
            if (!_skel) return false;
            var _bones  = {bones_json};
            var _morphs = {morphs_json};
            var _props  = {props_json};

            var all = _skel.getAllBones();
            for (var i = 0; i < all.length; i++) {{
                var b = all[i];
                var xyz = _bones[b.getName()];
                if (xyz !== undefined) {{
                    b.getXRotControl().setValue(xyz[0]);
                    b.getYRotControl().setValue(xyz[1]);
                    b.getZRotControl().setValue(xyz[2]);
                }} else {{
                    b.getXRotControl().setValue(0);
                    b.getYRotControl().setValue(0);
                    b.getZRotControl().setValue(0);
                }}
            }}

            // Write back to the raw dial slot -- see the comment in
            // capture() for why setValue() would double-apply ERC-controller
            // contributions on properties like morphs or a "Scale" dial that
            // are DzERCLink targets.
            var obj = _skel.getObject();
            if (obj) {{
                for (var i = 0; i < obj.getNumModifiers(); i++) {{
                    var m = obj.getModifier(i);
                    if (m.className() === "DzMorph") {{
                        var v = _morphs[m.getName()];
                        var _v = (v !== undefined) ? v : 0;
                        var ch = m.getValueChannel();
                        if (typeof ch.setRawValue === "function") {{ ch.setRawValue(_v); }}
                        else {{ ch.setValue(_v); }}
                    }}
                }}
            }}

            for (var i = 0; i < _skel.getNumProperties(); i++) {{
                var p = _skel.getProperty(i);
                if (p && p.setValue) {{
                    var v = _props[p.getName()];
                    var _v = (v !== undefined) ? v : 0;
                    if (typeof p.setRawValue === "function") {{ p.setRawValue(_v); }}
                    else {{ p.setValue(_v); }}
                }}
            }}

            return true;
        }})()"""

        skeleton._client.execute(script)

    # ── dunder ────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"DazPose(figure={self.figure!r}, "
            f"bones={len(self.bones)}, morphs={len(self.morphs)}, props={len(self.props)})"
        )


_ZERO3 = [0.0, 0.0, 0.0]
