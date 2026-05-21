from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from ._skeleton import DazSkeleton
    from ._pose import DazPose


class DazAnimation:
    """A captured animation clip: bone rotations (and optionally morphs) for every
    frame in the play range.

    Created with :meth:`capture`; saved/loaded with :meth:`save` / :meth:`load`.

    Bones are stored as a parallel-list encoding — a single ordered ``bones``
    list of names, and per-frame ``rotations`` arrays aligned to that index —
    so payload size grows with bones × frames rather than with a full dict per
    frame.

    Typical workflow::

        from dazpy import DazScene, DazAnimation

        scene  = DazScene()
        figure = scene.find_skeleton_by_label("Genesis 9")

        anim = DazAnimation.capture(figure, include_morphs=True)
        anim.save("walk.json")

    JSON schema (same as the ``animation_frame_dump.py`` output)::

        {
          "figure": "Genesis 9",
          "frame_range": {"start": 0, "end": 90},
          "bones": ["hip", "rForeArm", ...],
          "frames": [
            {"frame": 0, "rotations": [[x,y,z], ...], "morphs": {"PHMSmile": 0.5}},
            ...
          ]
        }

    Args:
        figure:       The label of the figure.
        frame_range:  ``{"start": int, "end": int}`` in frames.
        bones:        Ordered list of bone names matching ``rotations`` columns.
        frames:       Per-frame data; each entry has ``"frame"``, ``"rotations"``,
                      and ``"morphs"`` keys.
    """

    def __init__(
        self,
        figure: str,
        frame_range: dict,
        bones: list[str],
        frames: list[dict],
    ) -> None:
        self.figure = figure
        self.frame_range = frame_range
        self.bones = bones
        self.frames = frames

    # ── construction ──────────────────────────────────────────────────────────

    @classmethod
    def capture(cls, skeleton: "DazSkeleton", include_morphs: bool = False) -> "DazAnimation":
        """Capture the full animation of *skeleton* in a single HTTP call.

        Scrubs every frame in the scene's play range server-side (no Python
        round-trip per frame).  The timeline is restored to its original frame
        before the call returns.

        When *include_morphs* is ``True``, the script first identifies which
        geometry morphs and node-level properties actually vary across the
        timeline (channels that are keyed but static are excluded), then
        records their values per frame.

        Args:
            skeleton:       The figure to capture.
            include_morphs: Also capture animated morph and property channels.

        Returns:
            A new :class:`DazAnimation`.

        Raises:
            ~dazpy.exceptions.NodeNotFoundError: If the skeleton is not found.
        """
        lookup = ScriptBuilder.skeleton_lookup(skeleton._identifier)
        include_morphs_js = "true" if include_morphs else "false"

        script = f"""(function(){{
            {lookup}
            if (!_skel) return null;

            var _origFrame = Scene.getFrame();

            var allBones = _skel.getAllBones();
            var boneNames = [];
            for (var i = 0; i < allBones.length; i++) boneNames.push(allBones[i].getName());

            // Detect channels whose values actually vary across the timeline.
            // Channels that are keyed but hold a constant value are excluded —
            // they add payload without contributing animation data.
            function isVaryingMorph(ch) {{
                var n = ch.getNumKeys();
                if (n < 2) return false;
                var first = ch.getKeyValue(0);
                for (var k = 1; k < n; k++) {{
                    if (Math.abs(ch.getKeyValue(k) - first) > 0.0001) return true;
                }}
                return false;
            }}

            var animatedChannels = [];
            if ({include_morphs_js}) {{
                var obj = _skel.getObject();
                if (obj) {{
                    for (var i = 0; i < obj.getNumModifiers(); i++) {{
                        var m = obj.getModifier(i);
                        if (m.className() === "DzMorph" && isVaryingMorph(m.getValueChannel()))
                            animatedChannels.push([m.getName(), m.getValueChannel()]);
                    }}
                }}
                for (var i = 0; i < _skel.getNumProperties(); i++) {{
                    var p = _skel.getProperty(i);
                    if (p && p.getNumKeys && isVaryingMorph(p))
                        animatedChannels.push([p.getName(), p]);
                }}
            }}

            var step  = Scene.getTimeStep();
            var range = Scene.getPlayRange();
            var start = Math.round(range.start / step);
            var end   = Math.round(range.end   / step);

            var frames = [];
            for (var f = start; f <= end; f++) {{
                Scene.setFrame(f);

                var rotations = [];
                for (var i = 0; i < allBones.length; i++) {{
                    var b = allBones[i];
                    rotations.push([
                        b.getXRotControl().getValue(),
                        b.getYRotControl().getValue(),
                        b.getZRotControl().getValue()
                    ]);
                }}

                var morphs = {{}};
                for (var i = 0; i < animatedChannels.length; i++) {{
                    var v = animatedChannels[i][1].getValue();
                    if (Math.abs(v) > 0.0001) morphs[animatedChannels[i][0]] = v;
                }}

                frames.push({{frame: f, rotations: rotations, morphs: morphs}});
            }}

            Scene.setFrame(_origFrame);

            return {{
                figure:      _skel.getLabel(),
                frame_range: {{start: start, end: end}},
                bones:       boneNames,
                frames:      frames
            }};
        }})()"""

        result = skeleton._client.execute(script).value
        if result is None:
            from .exceptions import NodeNotFoundError
            raise NodeNotFoundError(f"Skeleton not found: {skeleton._identifier.value!r}")

        return cls(
            figure=result["figure"],
            frame_range=result["frame_range"],
            bones=result["bones"],
            frames=result["frames"],
        )

    @classmethod
    def load(cls, path: str | Path) -> "DazAnimation":
        """Load an animation from a JSON file.

        Accepts files produced by :meth:`save` and by the original
        ``animation_frame_dump.py`` example script.

        Args:
            path: Path to the JSON file.

        Returns:
            A new :class:`DazAnimation`.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            figure=data.get("figure", ""),
            frame_range=data.get("frame_range", {"start": 0, "end": 0}),
            bones=data.get("bones", []),
            frames=data.get("frames", []),
        )

    # ── serialisation ─────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        """Write this animation to a JSON file.

        Args:
            path: Destination path.  Parent directories must exist.
        """
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def to_dict(self) -> dict:
        """Return the animation as a plain dict (same schema as the JSON file)."""
        return {
            "figure":      self.figure,
            "frame_range": self.frame_range,
            "bones":       self.bones,
            "frames":      self.frames,
        }

    # ── clip operations ───────────────────────────────────────────────────────

    def clip(self, start: int, end: int) -> "DazAnimation":
        """Return a new animation containing only frames in [start, end].

        *start* and *end* are scene frame numbers (the ``"frame"`` value stored
        in each frame, not Python list indices).  Both endpoints are inclusive.

        Args:
            start: First scene frame to include.
            end:   Last scene frame to include.

        Returns:
            A new :class:`DazAnimation` with the same bones but a subset of frames.
        """
        frames = [f for f in self.frames if start <= f["frame"] <= end]
        new_start = frames[0]["frame"] if frames else start
        new_end   = frames[-1]["frame"] if frames else end
        return DazAnimation(
            figure=self.figure,
            frame_range={"start": new_start, "end": new_end},
            bones=self.bones,
            frames=frames,
        )

    def blend(self, other: "DazAnimation", t: float) -> "DazAnimation":
        """Blend this animation with *other* frame by frame.

        Each frame's bone rotations and morph values are linearly interpolated
        between *self* (``t=0``) and *other* (``t=1``).  This is a pure-Python
        operation — no HTTP round-trip.

        If the two clips have different frame counts, the result is truncated to
        the shorter clip.  Frame numbers are taken from *self*.

        Args:
            other: The target animation.
            t:     Blend factor — 0.0 = self, 1.0 = other.

        Returns:
            A new :class:`DazAnimation` at the interpolated position.

        Raises:
            ValueError: If *self* and *other* have different bone lists.
        """
        if self.bones != other.bones:
            raise ValueError(
                f"Cannot blend animations with different bone lists "
                f"({len(self.bones)} vs {len(other.bones)} bones)"
            )
        s = 1.0 - t
        frames = []
        for fa, fb in zip(self.frames, other.frames):
            rotations = [
                [fa["rotations"][i][j] * s + fb["rotations"][i][j] * t for j in range(3)]
                for i in range(len(self.bones))
            ]
            all_keys = set(fa["morphs"]) | set(fb["morphs"])
            morphs = {}
            for k in all_keys:
                v = fa["morphs"].get(k, 0.0) * s + fb["morphs"].get(k, 0.0) * t
                if abs(v) > 1e-9:
                    morphs[k] = v
            frames.append({"frame": fa["frame"], "rotations": rotations, "morphs": morphs})
        new_end = frames[-1]["frame"] if frames else self.frame_range["start"]
        return DazAnimation(
            figure=self.figure,
            frame_range={"start": self.frame_range["start"], "end": new_end},
            bones=self.bones,
            frames=frames,
        )

    def as_pose(self, frame_index: int = 0) -> "DazPose":
        """Extract a single frame as a :class:`~dazpy.DazPose`.

        Bone rotations are stored sparsely — only bones with at least one
        non-zero component are included.  Morph values are copied as-is.

        This is a pure-Python operation — no HTTP round-trip.

        Args:
            frame_index: 0-based index into :attr:`frames`.

        Returns:
            A new :class:`~dazpy.DazPose`.
        """
        from ._pose import DazPose
        frame = self.frames[frame_index]
        bones = {
            name: list(rot)
            for name, rot in zip(self.bones, frame["rotations"])
            if any(abs(v) > 1e-9 for v in rot)
        }
        return DazPose(
            figure=self.figure,
            bones=bones,
            morphs=dict(frame["morphs"]),
            props={},
        )

    def apply(self, skeleton: "DazSkeleton", frame_index: int = 0) -> None:
        """Apply a single frame of this animation to *skeleton*.

        Equivalent to ``anim.as_pose(frame_index).apply(skeleton)`` — one HTTP
        call that sets only the channels present in the frame.

        Args:
            skeleton:    The figure to pose.
            frame_index: 0-based index into :attr:`frames`.  Defaults to 0.
        """
        self.as_pose(frame_index).apply(skeleton)

    def append(self, other: "DazAnimation") -> "DazAnimation":
        """Concatenate *other* immediately after this animation.

        The other clip's frame numbers are shifted so it starts on the frame
        following this animation's last frame.  The figure label and bone list
        are taken from *self*.

        This is a pure-Python operation — no HTTP round-trip.

        Args:
            other: The animation to append.

        Returns:
            A new :class:`DazAnimation` containing all frames from both clips.

        Raises:
            ValueError: If *self* and *other* have different bone lists.
        """
        if self.bones != other.bones:
            raise ValueError(
                f"Cannot append animations with different bone lists "
                f"({len(self.bones)} vs {len(other.bones)} bones)"
            )
        if not self.frames:
            return DazAnimation(self.figure, dict(other.frame_range), list(other.bones), list(other.frames))
        offset = self.frame_range["end"] + 1 - other.frame_range["start"]
        other_frames = [
            {"frame": f["frame"] + offset, "rotations": f["rotations"], "morphs": f["morphs"]}
            for f in other.frames
        ]
        frames = list(self.frames) + other_frames
        return DazAnimation(
            figure=self.figure,
            frame_range={"start": self.frame_range["start"], "end": frames[-1]["frame"]},
            bones=self.bones,
            frames=frames,
        )

    # ── convenience ───────────────────────────────────────────────────────────

    @property
    def frame_count(self) -> int:
        """Number of captured frames."""
        return len(self.frames)

    @property
    def bone_count(self) -> int:
        """Number of bones in the skeleton at capture time."""
        return len(self.bones)

    def __len__(self) -> int:
        return len(self.frames)

    def __getitem__(self, index: int) -> dict:
        """Return the frame dict at *index* (0-based Python index)."""
        return self.frames[index]

    def __repr__(self) -> str:
        fr = self.frame_range
        return (
            f"DazAnimation(figure={self.figure!r}, "
            f"frames={self.frame_count}, bones={self.bone_count}, "
            f"range={fr.get('start')}–{fr.get('end')})"
        )
