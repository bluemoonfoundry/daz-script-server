from __future__ import annotations

import json

from ._node import DazNode, NodeIdentifier
from ._script_builder import ScriptBuilder


class DazSkeleton(DazNode):
    """Proxy for a ``DzSkeleton`` (a rigged figure such as Genesis 9).

    Extends :class:`~dazpy.DazNode` with bone-access helpers.
    """

    def _skeleton_body(self, body: str) -> str:
        # Scene.findNode() returns DzNode which lacks DzSkeleton methods like
        # findBone(). Retrieve a properly typed DzSkeleton by iterating
        # getSkeletonList(), which is the only proven-typed accessor in the API.
        kind = self._identifier.kind
        value = json.dumps(self._identifier.value)
        if kind == "label":
            match = f"_skels[_i].getLabel() === {value}"
        else:
            match = f"_skels[_i].getName() === {value}"
        lookup = (
            f"var _node = null;"
            f" var _skels = Scene.getSkeletonList();"
            f" for (var _i = 0; _i < _skels.length; _i++) {{"
            f" if ({match}) {{ _node = _skels[_i]; break; }} }}"
        )
        return ScriptBuilder.iife(f"{lookup}\nif (!_node) return null;\n{body}")

    def _bone_locator(self, bone_name: str) -> str:
        """Build a JS locator that resolves a bone through this specific skeleton.

        Uses the skeleton list rather than Scene.findNode() so that two figures
        with the same internal name (e.g. two Genesis 9 figures) are kept distinct.
        """
        kind = self._identifier.kind
        value = json.dumps(self._identifier.value)
        match = (
            f"_skels[_i].getLabel() === {value}"
            if kind == "label"
            else f"_skels[_i].getName() === {value}"
        )
        return (
            f"(function(){{"
            f"var _skel=null,_skels=Scene.getSkeletonList();"
            f"for(var _i=0;_i<_skels.length;_i++){{if({match}){{_skel=_skels[_i];break;}}}}"
            f"return _skel?_skel.findBone({json.dumps(bone_name)}):null;"
            f"}})()"
        )

    def bones(self) -> list["DazBone"]:  # noqa: F821
        """Return all bones in this skeleton."""
        from ._bone import DazBone
        script = self._skeleton_body(
            """
            var bones = _node.getAllBones();
            var names = [];
            for (var i = 0; i < bones.length; i++) {
                names.push(bones[i].getName());
            }
            return names;
            """
        )
        names = self._client.execute(script).value or []
        return [DazBone._from_locator(self._client, self._bone_locator(n), n) for n in names]

    def find_bone(self, name: str) -> "DazBone":  # noqa: F821
        """Find a bone by its internal name.

        Args:
            name: The ``getName()`` string of the bone (e.g. ``"rForeArm"``).

        Returns:
            A :class:`~dazpy.DazBone` proxy.

        Raises:
            NodeNotFoundError: If no bone with that name exists.
        """
        from ._bone import DazBone
        from .exceptions import NodeNotFoundError
        script = self._skeleton_body(
            f"var b = _node.findBone({ScriptBuilder.escape_string(name)}); return b ? b.getName() : null;"
        )
        result = self._client.execute(script).value
        if result is None:
            raise NodeNotFoundError(f"Bone not found: {name!r}")
        return DazBone._from_locator(self._client, self._bone_locator(result), result)

    def find_bone_by_label(self, label: str) -> "DazBone":  # noqa: F821
        """Find a bone by its user-visible label.

        Args:
            label: The ``getLabel()`` string of the bone.

        Returns:
            A :class:`~dazpy.DazBone` proxy.

        Raises:
            NodeNotFoundError: If no bone with that label exists.
        """
        from ._bone import DazBone
        from .exceptions import NodeNotFoundError
        script = self._skeleton_body(
            f"var b = _node.findBoneByLabel({ScriptBuilder.escape_string(label)}); return b ? b.getName() : null;"
        )
        result = self._client.execute(script).value
        if result is None:
            raise NodeNotFoundError(f"Bone with label not found: {label!r}")
        return DazBone._from_locator(self._client, self._bone_locator(result), result)

    def num_bones(self) -> int:
        """Return the total number of bones in this skeleton."""
        script = self._skeleton_body("return _node.getAllBones().length;")
        return self._client.execute(script).value or 0

    def bone_rotations(self) -> dict[str, tuple[float, float, float]]:
        """Return Euler rotations for every bone in one HTTP call.

        Equivalent to calling :attr:`~dazpy.DazBone.local_euler` on every bone
        returned by :meth:`bones`, but rounds-trips only once.

        Returns:
            ``{bone_name: (x, y, z)}`` in degrees for every bone.
        """
        script = self._skeleton_body("""
            var _bones = _node.getAllBones();
            var _result = {};
            for (var i = 0; i < _bones.length; i++) {
                var _b = _bones[i];
                _result[_b.getName()] = [
                    _b.getXRotControl().getValue(),
                    _b.getYRotControl().getValue(),
                    _b.getZRotControl().getValue()
                ];
            }
            return _result;
        """)
        raw = self._client.execute(script).value or {}
        return {name: (v[0], v[1], v[2]) for name, v in raw.items()}

    def set_bone_rotations(self, data: dict[str, tuple | list]) -> None:
        """Set Euler rotations for any subset of bones in one HTTP call.

        Only the bones named in *data* are modified; all others are unchanged.
        Equivalent to calling :meth:`~dazpy.DazBone.set_local_rotation` per
        bone, but rounds-trips only once.

        Args:
            data: ``{bone_name: (x, y, z)}`` or ``{bone_name: [x, y, z]}``,
                  angles in degrees.  Bones not in this dict are left as-is.
        """
        data_json = json.dumps({k: list(v) for k, v in data.items()})
        script = self._skeleton_body(f"""
            var _data = {data_json};
            var _bones = _node.getAllBones();
            for (var i = 0; i < _bones.length; i++) {{
                var _b = _bones[i];
                var _n = _b.getName();
                if (_data.hasOwnProperty(_n)) {{
                    var _r = _data[_n];
                    _b.getXRotControl().setValue(_r[0]);
                    _b.getYRotControl().setValue(_r[1]);
                    _b.getZRotControl().setValue(_r[2]);
                }}
            }}
        """)
        self._client.execute(script)

    def morph_values(self, nonzero_only: bool = False) -> dict[str, float]:
        """Return the current value of every DzMorph modifier in one HTTP call.

        Args:
            nonzero_only: When ``True``, exclude morphs whose value is
                effectively zero (``abs(v) <= 0.0001``).  Useful for sparse logging.

        Returns:
            ``{morph_name: float}`` for all (or non-zero) morphs.
        """
        nz_js = "true" if nonzero_only else "false"
        script = self._skeleton_body(f"""
            var _obj = _node.getObject();
            if (!_obj) return {{}};
            var _result = {{}};
            var _nz = {nz_js};
            for (var i = 0; i < _obj.getNumModifiers(); i++) {{
                var _m = _obj.getModifier(i);
                if (_m.className() === "DzMorph") {{
                    var _v = _m.getValueChannel().getValue();
                    if (!_nz || Math.abs(_v) > 0.0001) {{
                        _result[_m.getName()] = _v;
                    }}
                }}
            }}
            return _result;
        """)
        return self._client.execute(script).value or {}

    def set_morph_values(self, data: dict[str, float]) -> None:
        """Set the value of any subset of morphs in one HTTP call.

        Only morphs named in *data* are modified; all others are unchanged.

        Args:
            data: ``{morph_name: float}`` mapping.  Morphs not in this dict
                  are left at their current value.
        """
        data_json = json.dumps(data)
        script = self._skeleton_body(f"""
            var _data = {data_json};
            var _obj = _node.getObject();
            if (!_obj) return null;
            for (var i = 0; i < _obj.getNumModifiers(); i++) {{
                var _m = _obj.getModifier(i);
                if (_m.className() === "DzMorph" && _data.hasOwnProperty(_m.getName())) {{
                    _m.getValueChannel().setValue(_data[_m.getName()]);
                }}
            }}
        """)
        self._client.execute(script)

    # ── keyframe baking ───────────────────────────────────────────────────────

    def bake_bone_rotations(
        self,
        start: int | None = None,
        end: int | None = None,
        bone_names: list[str] | None = None,
    ) -> dict:
        """Bake bone rotation keyframes for every frame in the range.

        Scrubs the timeline server-side.  For each frame, the current evaluated
        X/Y/Z rotation of every bone (including IK, constraints, and driven keys)
        is stamped as an explicit keyframe via ``insertKey``.  After baking, the
        animation plays back without requiring any of the original drivers.

        The original frame is restored before the call returns.

        Args:
            start:      First frame to bake.  ``None`` → play-range start.
            end:        Last frame to bake.  ``None`` → play-range end.
            bone_names: Subset of bone names to bake.  ``None`` → all bones.

        Returns:
            ``{"frames_baked": int, "bones_baked": int}``

        Raises:
            ~dazpy.exceptions.NodeNotFoundError: If the skeleton is not found.
        """
        start_js      = str(start) if start is not None else "null"
        end_js        = str(end)   if end   is not None else "null"
        bone_filter_js = json.dumps({n: True for n in bone_names}) if bone_names is not None else "null"

        script = self._skeleton_body(f"""
            var _step    = Scene.getTimeStep();
            var _pr      = Scene.getPlayRange();
            var _prStart = Math.round(_pr.start / _step);
            var _prEnd   = Math.round(_pr.end   / _step);
            var _bkStart = ({start_js} !== null) ? {start_js} : _prStart;
            var _bkEnd   = ({end_js}   !== null) ? {end_js}   : _prEnd;
            var _filter  = {bone_filter_js};

            var _all = _node.getAllBones();
            var _bones = [];
            for (var i = 0; i < _all.length; i++) {{
                if (_filter === null || _filter.hasOwnProperty(_all[i].getName()))
                    _bones.push(_all[i]);
            }}

            var _origFrame = Scene.getFrame();
            for (var f = _bkStart; f <= _bkEnd; f++) {{
                Scene.setFrame(f);
                var _t = f * _step;
                for (var i = 0; i < _bones.length; i++) {{
                    var _b = _bones[i];
                    _b.getXRotControl().insertKey(_t, _b.getXRotControl().getValue());
                    _b.getYRotControl().insertKey(_t, _b.getYRotControl().getValue());
                    _b.getZRotControl().insertKey(_t, _b.getZRotControl().getValue());
                }}
            }}
            Scene.setFrame(_origFrame);
            return {{frames_baked: _bkEnd - _bkStart + 1, bones_baked: _bones.length}};
        """)
        return self._client.execute(script).value or {}

    def bake_morphs(
        self,
        start: int | None = None,
        end: int | None = None,
        morph_names: list[str] | None = None,
    ) -> dict:
        """Bake morph channel keyframes for every frame in the range.

        For each frame, the current value of every ``DzMorph`` modifier is
        stamped as an explicit keyframe via ``insertKey``.

        The original frame is restored before the call returns.

        Args:
            start:       First frame to bake.  ``None`` → play-range start.
            end:         Last frame to bake.  ``None`` → play-range end.
            morph_names: Subset of morph names to bake.  ``None`` → all morphs.

        Returns:
            ``{"frames_baked": int, "morphs_baked": int}``
        """
        start_js       = str(start) if start is not None else "null"
        end_js         = str(end)   if end   is not None else "null"
        morph_filter_js = json.dumps({n: True for n in morph_names}) if morph_names is not None else "null"

        script = self._skeleton_body(f"""
            var _step    = Scene.getTimeStep();
            var _pr      = Scene.getPlayRange();
            var _prStart = Math.round(_pr.start / _step);
            var _prEnd   = Math.round(_pr.end   / _step);
            var _bkStart = ({start_js} !== null) ? {start_js} : _prStart;
            var _bkEnd   = ({end_js}   !== null) ? {end_js}   : _prEnd;
            var _filter  = {morph_filter_js};

            var _obj = _node.getObject();
            if (!_obj) return {{frames_baked: 0, morphs_baked: 0}};
            var _channels = [];
            for (var i = 0; i < _obj.getNumModifiers(); i++) {{
                var _m = _obj.getModifier(i);
                if (_m.className() === "DzMorph" &&
                    (_filter === null || _filter.hasOwnProperty(_m.getName())))
                    _channels.push(_m.getValueChannel());
            }}

            var _origFrame = Scene.getFrame();
            for (var f = _bkStart; f <= _bkEnd; f++) {{
                Scene.setFrame(f);
                var _t = f * _step;
                for (var i = 0; i < _channels.length; i++) {{
                    _channels[i].insertKey(_t, _channels[i].getValue());
                }}
            }}
            Scene.setFrame(_origFrame);
            return {{frames_baked: _bkEnd - _bkStart + 1, morphs_baked: _channels.length}};
        """)
        return self._client.execute(script).value or {}

    def bake(
        self,
        start: int | None = None,
        end: int | None = None,
        bone_names: list[str] | None = None,
        include_morphs: bool = False,
        morph_names: list[str] | None = None,
    ) -> dict:
        """Bake bone rotations and optionally morphs in a single HTTP call.

        Combines :meth:`bake_bone_rotations` and :meth:`bake_morphs` into one
        server-side loop so the timeline is only scrubbed once.

        Args:
            start:          First frame to bake.  ``None`` → play-range start.
            end:            Last frame to bake.  ``None`` → play-range end.
            bone_names:     Bones to bake.  ``None`` → all bones.
            include_morphs: Also bake ``DzMorph`` channels.
            morph_names:    Morphs to bake (only used when *include_morphs* is
                            ``True``).  ``None`` → all morphs.

        Returns:
            ``{"frames_baked": int, "bones_baked": int, "morphs_baked": int}``
        """
        start_js        = str(start) if start is not None else "null"
        end_js          = str(end)   if end   is not None else "null"
        bone_filter_js  = json.dumps({n: True for n in bone_names})  if bone_names  is not None else "null"
        morph_filter_js = json.dumps({n: True for n in morph_names}) if morph_names is not None else "null"
        with_morphs_js  = "true" if include_morphs else "false"

        script = self._skeleton_body(f"""
            var _step    = Scene.getTimeStep();
            var _pr      = Scene.getPlayRange();
            var _prStart = Math.round(_pr.start / _step);
            var _prEnd   = Math.round(_pr.end   / _step);
            var _bkStart    = ({start_js} !== null) ? {start_js} : _prStart;
            var _bkEnd      = ({end_js}   !== null) ? {end_js}   : _prEnd;
            var _boneFilter = {bone_filter_js};
            var _mFilter    = {morph_filter_js};
            var _withMorphs = {with_morphs_js};

            var _all = _node.getAllBones();
            var _bones = [];
            for (var i = 0; i < _all.length; i++) {{
                if (_boneFilter === null || _boneFilter.hasOwnProperty(_all[i].getName()))
                    _bones.push(_all[i]);
            }}

            var _mChannels = [];
            if (_withMorphs) {{
                var _obj = _node.getObject();
                if (_obj) {{
                    for (var i = 0; i < _obj.getNumModifiers(); i++) {{
                        var _m = _obj.getModifier(i);
                        if (_m.className() === "DzMorph" &&
                            (_mFilter === null || _mFilter.hasOwnProperty(_m.getName())))
                            _mChannels.push(_m.getValueChannel());
                    }}
                }}
            }}

            var _origFrame = Scene.getFrame();
            for (var f = _bkStart; f <= _bkEnd; f++) {{
                Scene.setFrame(f);
                var _t = f * _step;
                for (var i = 0; i < _bones.length; i++) {{
                    var _b = _bones[i];
                    _b.getXRotControl().insertKey(_t, _b.getXRotControl().getValue());
                    _b.getYRotControl().insertKey(_t, _b.getYRotControl().getValue());
                    _b.getZRotControl().insertKey(_t, _b.getZRotControl().getValue());
                }}
                for (var i = 0; i < _mChannels.length; i++) {{
                    _mChannels[i].insertKey(_t, _mChannels[i].getValue());
                }}
            }}
            Scene.setFrame(_origFrame);
            return {{
                frames_baked: _bkEnd - _bkStart + 1,
                bones_baked:  _bones.length,
                morphs_baked: _mChannels.length,
            }};
        """)
        return self._client.execute(script).value or {}

    def follow_target(self) -> "DazSkeleton | None":
        """Return the IK follow-target skeleton, or ``None`` if not set."""
        script = self._skeleton_body(
            "var t = _node.getFollowTarget(); return t ? t.getName() : null;"
        )
        name = self._client.execute(script).value
        if name is None:
            return None
        return DazSkeleton(self._client, NodeIdentifier(name))
