# dazpy.poses — ApplyPose / ResetTransforms / ZeroFigure (design)

## Context

GitHub issue #31 ("AsyncIO Support, Type-Safe Models, Domain Submodules, and
Coordinate Math") proposes packaging common DazScript macros into first-class
Python submodules, including `dazpy.poses` with `ApplyPose`,
`ResetTransforms`, and `ZeroFigure`. Tracked as beads issue
`daz-script-server-p1af`.

Unlike `dazpy.lighting` (which needed new DazScript to compute rig placement),
all three functions here are thin convenience wrappers over existing
primitives: `DazPose.apply`/`apply_full` (`dazpy/_pose.py`) already implement
sparse and full pose application, and `DazNode` (`dazpy/_node.py`) already has
`set_local_position`/`set_local_rotation`. The value of this submodule is
purely ergonomic — one obvious call instead of assembling `DazPose` objects or
knowing which primitive combination produces "zero this figure" or "reset
this node."

## Goals

- `ApplyPose`: apply a pose (from a file or an already-loaded `DazPose`) to a
  skeleton in one call, without the caller needing to know about
  `DazPose.load`.
- `ZeroFigure`: drive every bone rotation and morph on a figure to zero,
  without touching the figure's root transform.
- `ResetTransforms`: reset any node's local position/rotation to the origin
  and scale to 1.0 — usable on cameras, props, or figure roots alike.

## Non-goals

- Blending/interpolating from a figure's current pose (`DazPose.lerp` already
  covers this for callers who want it explicitly).
- Any new DazScript surface beyond one small `DazNode` primitive gap (see
  below) — everything else composes existing methods.

## Primitive gap: `DazNode.set_scale`

`DazNode` currently exposes `scale`/`general_scale` as read-only properties
but has no scale setter, unlike `set_local_position`/`set_local_rotation`.
`ResetTransforms` needs to reset scale to 1.0, so this design adds:

```python
def set_scale(self, x: float, y: float, z: float) -> None:
    """Set per-axis local scale (does not affect the general/uniform scale dial)."""
```

in `dazpy/_node.py`, following the exact pattern of `set_local_position`
(one `_node.getXScaleControl().setValue(...)` call per axis via
`ScriptBuilder.node_body`). This is a primitive addition, not part of
`poses.py` itself.

## Data model / behavior

New file: `dazpy/poses.py`. No dataclasses needed — these are plain
functions, since there's no multi-field configuration object to justify one
(unlike `LightSpec`/`ThreePointLightSetup`).

```python
def apply_pose(skeleton: DazSkeleton, pose: DazPose | str | Path) -> None:
    """Apply *pose* to *skeleton*. If *pose* is a path, loads it first."""
    if isinstance(pose, (str, Path)):
        pose = DazPose.load(pose)
    pose.apply(skeleton)
```

```python
def zero_figure(skeleton: DazSkeleton, *, include_props: bool = True) -> None:
    """Drive every bone rotation and morph on *skeleton* to zero.

    Does not touch the figure's root position/rotation/scale — use
    ResetTransforms for that. When include_props is True (default), node-level
    numeric properties are also zeroed (matches DazPose.apply_full's existing
    all-channels behavior). When False, only bones and morphs are zeroed.
    """
```

Implementation: builds an empty `DazPose(figure=<skeleton identifier>,
bones={}, morphs={}, props={})` and calls `apply_full(skeleton)`, whose
existing semantics already drive every bone/morph/prop not present in the
pose to zero. When `include_props=False`, this function instead calls
`skeleton.set_bone_rotations({...})` / `skeleton.set_morph_values({...})`
directly with all-zero values for every bone/morph name (read via
`skeleton.bones()` / `skeleton.morph_values()`), skipping node properties
entirely — this avoids adding a `props`-skipping mode to `DazPose.apply_full`
itself, which would complicate a primitive used elsewhere.

```python
def reset_transforms(node: DazNode) -> None:
    """Reset *node*'s local position and rotation to zero, and scale to 1.0."""
    node.set_local_position(0.0, 0.0, 0.0)
    node.set_local_rotation(0.0, 0.0, 0.0)
    node.set_scale(1.0, 1.0, 1.0)
```

Naming: GH #31 names these in PascalCase (`ApplyPose`, `ResetTransforms`,
`ZeroFigure`), but every existing function in this codebase
(`apply_three_point_light_setup`, `apply_hdri_environment`) uses
`snake_case`. This design follows the codebase convention:
`apply_pose`, `zero_figure`, `reset_transforms`.

## API surface / exports

Add to `dazpy/__init__.py`:

```python
from .poses import apply_pose, reset_transforms, zero_figure
```

And the corresponding `__all__` entries.

## Testing

In `tests/test_dazpy.py` (mock-client style, matching existing conventions):

- `apply_pose`:
  - Given a `DazPose` instance, delegates directly to `pose.apply(skeleton)`
    (no load call).
  - Given a string/`Path`, loads via `DazPose.load` first, then applies the
    loaded pose.
- `zero_figure`:
  - `include_props=True` (default): applies a pose with empty
    bones/morphs/props via `apply_full`, confirming the resulting DazScript
    zeroes bone rotations/morphs/props and leaves the root node transform
    alone.
  - `include_props=False`: reads bone/morph names, then confirms
    `set_bone_rotations`/`set_morph_values` are called with all-zero values
    for every known bone/morph and that no node-property write is issued.
- `reset_transforms`: confirms `set_local_position(0,0,0)`,
  `set_local_rotation(0,0,0)`, and `set_scale(1,1,1)` are all called on the
  passed node.
- `DazNode.set_scale`: direct unit test in the `_node.py` test module
  alongside `set_local_position`/`set_local_rotation`, asserting the emitted
  DazScript sets all three scale-axis controls.

## Open questions / follow-ups

None — `dazpy.cinematics` and `dazpy.materials` remain separate future slices
of `daz-script-server-p1af`.
