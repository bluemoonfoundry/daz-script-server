"""DAZ Studio Script Server example: export the live scene to a Pixar USD file.

PURPOSE
-------
This script is a demonstration of what the DAZ Studio Script Server makes
possible.  It connects to a running DAZ Studio instance, interrogates the
live scene entirely through the server's HTTP API, and writes a Pixar USD
file — all without touching DAZ Studio's UI, loading extra plugins, or
modifying the scene itself.

It is an *example*, not a production-grade DAZ-to-Blender pipeline.
Real production pipelines would need proper multi-material support, subdivision
baking, dForce simulation capture, and so on.  The goal here is to show that
the script server gives you enough access to drive non-trivial third-party
toolchains from plain Python.

WHAT IT EXPORTS
---------------
For every visible scene node with geometry the script writes:
  - Fully posed mesh vertices  (skeleton skinning + morphs already applied,
    fetched via DzObject.getCachedGeom())
  - Polygon topology  (face vertex counts and indices)
  - Primary UV set
  - A UsdPreviewSurface material with diffuse colour or texture
  - Strand-based hair  (DzGraftingFigureShape with no facets is detected and
    exported as linear UsdGeom.BasisCurves)
  - Cameras  (focal length, sensor size, clipping range)
  - Lights  (distant, rect, sphere with intensity and colour)

With --morphs the script additionally exports active shape morphs as UsdSkel
blend shapes, which can be applied in Blender with the companion
*_apply_morphs.py script.  Note: blend shapes export the T-pose base mesh
(not the skeleton-posed mesh) so they are best used for morph animation in
Blender rather than as a static posed export.

ENVIRONMENT SETUP
-----------------
1. DAZ Studio must be running with the DazScriptServer plugin loaded and its
   HTTP server active (default: 127.0.0.1:18811).  You can verify it is
   responding with:

       curl http://127.0.0.1:18811/health

2. Install the Python dependencies in a virtual environment:

       python -m venv .venv
       .venv\\Scripts\\activate          # Windows
       # source .venv/bin/activate     # macOS / Linux
       pip install usd-core requests

   usd-core provides the pxr bindings (UsdGeom, UsdSkel, UsdShade, etc.).
   requests is used by dazpy to communicate with the script server.

3. Install or develop-install the dazpy SDK (from the repo root):

       pip install -e .

4. Open a scene in DAZ Studio, then run this script from the repo root or
   from the docs/examples directory:

       python docs/examples/export/scene_to_usd.py --out scene.usda

VIEWING THE OUTPUT
------------------
Any of the following tools can open the exported .usda file:

  usdview scene.usda          # Pixar's reference viewer (included in usd-core)
  Blender                     # File > Import > Universal Scene Description
  NVIDIA Omniverse / USD Composer

KNOWN LIMITATIONS
-----------------
  - Subdivision surfaces are exported at the current subdivision level only;
    the subdiv creases and level are not written to USD.
  - Only the primary UV set is exported.
  - Per-face material regions are collapsed to a single material per node.
  - dForce simulated cloth/hair is captured as a static snapshot of the
    current simulation state.

Usage:
    python scene_to_usd.py --out scene.usda
    python scene_to_usd.py --out scene.usdc --frame 30
    python scene_to_usd.py --out scene.usda --render-visible-only
    python scene_to_usd.py --out scene.usda --morphs
"""

import argparse
import json
import math
import re

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade, UsdSkel

from dazpy import DazCamera, DazClient, DazGeometry, DazLight, DazScene, NodeIdentifier

# ── helpers ───────────────────────────────────────────────────────────────────

_BAD_CHAR = re.compile(r"[^A-Za-z0-9_]")


def _usd_name(raw: str) -> str:
    name = _BAD_CHAR.sub("_", raw)
    if name and name[0].isdigit():
        name = "_" + name
    return name or "_node"


def _fetch_all_faces(geom: DazGeometry) -> list[list[int]]:
    total = geom.facet_count or 0
    faces: list[list[int]] = []
    offset = 0
    while offset < total:
        chunk = geom.face_vertex_indices(offset, 1000)
        batch = chunk.get("facets", [])
        if not batch:
            break
        faces.extend(batch)
        offset += len(batch)
    return faces


def _fetch_all_uvs(geom: DazGeometry) -> list[list[float]]:
    uvs: list[list[float]] = []
    offset = 0
    while True:
        chunk = geom.uv_positions(0, offset, 5000)
        batch = chunk.get("uvs", [])
        if not batch:
            break
        uvs.extend(batch)
        offset += len(batch)
        if offset >= chunk.get("total", 0):
            break
    return uvs


def _compute_base_verts(
    morphed: list[list[float]],
    morph_data: list[dict],
) -> list[list[float]]:
    """Subtract weighted morph contributions to recover the unmorphed T-pose base."""
    base = [list(v) for v in morphed]
    for morph in morph_data:
        w = morph["weight"]
        for idx, off in zip(morph["indices"], morph["offsets"]):
            base[idx][0] -= off[0] * w
            base[idx][1] -= off[1] * w
            base[idx][2] -= off[2] * w
    return base


def _write_mesh(stage: Usd.Stage, mesh_path: str, geom: DazGeometry, points: list | None = None) -> None:
    mesh = UsdGeom.Mesh.Define(stage, Sdf.Path(mesh_path))

    verts = points if points is not None else geom.vertex_positions_all()
    mesh.GetPointsAttr().Set([Gf.Vec3f(*v) for v in verts])

    faces = _fetch_all_faces(geom)
    mesh.GetFaceVertexCountsAttr().Set([len(f) for f in faces])
    mesh.GetFaceVertexIndicesAttr().Set([idx for f in faces for idx in f])

    # Primary UV set — stored as per-UV-index values.  UV count may differ
    # from vertex count at seams, so we tag as faceVarying and rely on DAZ's
    # UV ordering aligning with the face-vertex stream for a first approximation.
    if geom.uv_set_count:
        uvs = _fetch_all_uvs(geom)
        if uvs:
            primvar = UsdGeom.PrimvarsAPI(mesh).CreatePrimvar(
                "st",
                Sdf.ValueTypeNames.Float2Array,
                UsdGeom.Tokens.vertex,
            )
            primvar.Set([Gf.Vec2f(u, v) for u, v in uvs])


def _write_material(
    stage: Usd.Stage,
    mat_root: str,
    node: "DazNode",  # noqa: F821
    mesh_path: str,
) -> None:
    """Bind a UsdPreviewSurface material to the mesh prim at *mesh_path*."""
    try:
        mats = node.materials()
    except Exception:
        return
    if not mats:
        return

    mat0 = mats[0]
    diffuse = mat0.diffuse_color
    color_map = mat0.color_map()

    material = UsdShade.Material.Define(stage, Sdf.Path(mat_root))
    shader = UsdShade.Shader.Define(stage, Sdf.Path(mat_root + "/Surface"))
    shader.CreateIdAttr("UsdPreviewSurface")

    diffuse_input = shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f)

    if color_map:
        tex = UsdShade.Shader.Define(stage, Sdf.Path(mat_root + "/DiffuseTex"))
        tex.CreateIdAttr("UsdUVTexture")
        tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(color_map)
        tex_out = tex.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
        diffuse_input.ConnectToSource(tex.ConnectableAPI(), "rgb")
    elif diffuse:
        diffuse_input.Set(
            Gf.Vec3f(diffuse["r"] / 255.0, diffuse["g"] / 255.0, diffuse["b"] / 255.0)
        )

    material.CreateSurfaceOutput().ConnectToSource(
        shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
    )

    mesh_prim = stage.GetPrimAtPath(Sdf.Path(mesh_path))
    if mesh_prim:
        UsdShade.MaterialBindingAPI.Apply(mesh_prim).Bind(material)


def _fetch_active_morphs(client: DazClient, node_name: str) -> list[dict]:
    """Return [{name, weight}] for every non-zero DzMorph on the node's object."""
    script = f"""(function(){{
        var n = Scene.findNode({json.dumps(node_name)});
        if (!n) return [];
        var obj = n.getObject();
        if (!obj) return [];
        var result = [];
        for (var i = 0; i < obj.getNumModifiers(); i++) {{
            var m = obj.getModifier(i);
            if (m.className() !== "DzMorph") continue;
            var w = m.getValueChannel().getValue();
            if (Math.abs(w) > 0.0001) result.push({{name: m.getName(), weight: w}});
        }}
        return result;
    }})()"""
    return client.execute(script).value or []


def _fetch_morph_deltas(client: DazClient, node_name: str, morph_name: str) -> dict | None:
    """Return {indices: [...], offsets: [[x,y,z], ...]} for one morph, or None."""
    script = f"""(function(){{
        var n = Scene.findNode({json.dumps(node_name)});
        if (!n) return null;
        var obj = n.getObject();
        if (!obj) return null;
        var m = obj.findModifier({json.dumps(morph_name)});
        if (!m || m.className() !== "DzMorph") return null;
        var deltas = m.getDeltas();
        deltas.loadDeltas();
        if (!deltas.hasDeltas()) return null;
        var count = deltas.getNumDeltas();
        var indices = [];
        var offsets = [];
        for (var i = 0; i < count; i++) {{
            indices.push(deltas.getDeltaIndex(i));
            var d = deltas.getDeltaVec(i);
            offsets.push([d.x, d.y, d.z]);
        }}
        return {{indices: indices, offsets: offsets}};
    }})()"""
    return client.execute(script).value


def _write_blend_shapes(
    stage: Usd.Stage,
    root_path: str,
    mesh_path: str,
    morph_data: list[dict],
) -> int:
    """Write UsdSkel blend shape prims and bind them to the mesh.

    morph_data entries must have keys: name, weight, indices, offsets.
    Returns count of blend shapes written.
    """
    skel = UsdSkel.Skeleton.Define(stage, Sdf.Path(root_path + "/Skel"))
    # Storm requires at least one joint with transforms to evaluate a SkelRoot
    skel.CreateJointsAttr(["root"])
    skel.CreateBindTransformsAttr([Gf.Matrix4d(1)])
    skel.CreateRestTransformsAttr([Gf.Matrix4f(1)])

    anim = UsdSkel.Animation.Define(stage, Sdf.Path(root_path + "/Anim"))
    anim.CreateJointsAttr(["root"])
    anim.CreateTranslationsAttr([Gf.Vec3f(0, 0, 0)])
    anim.CreateRotationsAttr([Gf.Quatf(1, 0, 0, 0)])
    anim.CreateScalesAttr([Gf.Vec3h(1, 1, 1)])

    bs_usd_names: list[str] = []
    bs_paths: list[Sdf.Path] = []
    bs_weights: list[float] = []

    for morph in morph_data:
        usd_bs_name = _usd_name(morph["name"])
        bs_path = Sdf.Path(f"{root_path}/BlendShapes/{usd_bs_name}")

        bs = UsdSkel.BlendShape.Define(stage, bs_path)
        bs.CreatePointIndicesAttr(morph["indices"])
        bs.CreateOffsetsAttr([Gf.Vec3f(*o) for o in morph["offsets"]])

        bs_usd_names.append(usd_bs_name)
        bs_paths.append(bs_path)
        bs_weights.append(float(morph["weight"]))

    if not bs_usd_names:
        return 0

    # animationSource lives on the Skeleton, not the mesh (UsdSkel spec)
    skel_binding = UsdSkel.BindingAPI.Apply(skel.GetPrim())
    skel_binding.CreateAnimationSourceRel().SetTargets([Sdf.Path(root_path + "/Anim")])

    # Mesh binding: points at the skeleton and lists blend shape targets
    mesh_prim = stage.GetPrimAtPath(Sdf.Path(mesh_path))
    mesh_binding = UsdSkel.BindingAPI.Apply(mesh_prim)
    mesh_binding.CreateSkeletonRel().SetTargets([Sdf.Path(root_path + "/Skel")])
    mesh_binding.CreateBlendShapesAttr(bs_usd_names)
    mesh_binding.CreateBlendShapeTargetsRel().SetTargets(bs_paths)

    # Storm only activates UsdSkel evaluation (including blend shapes) when the
    # mesh has joint skinning primvars. Add identity weights binding every vertex
    # to the root joint — no geometric change, but unlocks blend shape evaluation.
    pvars = UsdGeom.PrimvarsAPI(mesh_prim)
    n_verts = len(UsdGeom.Mesh(mesh_prim).GetPointsAttr().Get() or [])
    ji = pvars.CreatePrimvar("skel:jointIndices", Sdf.ValueTypeNames.IntArray, UsdGeom.Tokens.vertex)
    ji.Set([0] * n_verts)
    ji.SetElementSize(1)
    jw = pvars.CreatePrimvar("skel:jointWeights", Sdf.ValueTypeNames.FloatArray, UsdGeom.Tokens.vertex)
    jw.Set([1.0] * n_verts)
    jw.SetElementSize(1)

    # Time-sample weights at both 0 and 1 — Blender evaluates at its start
    # frame (typically 1) and may ignore the default-value attribute
    anim.CreateBlendShapesAttr(bs_usd_names)
    weights_attr = anim.CreateBlendShapeWeightsAttr()
    weights_attr.Set(bs_weights)                      # default
    weights_attr.Set(bs_weights, Usd.TimeCode(0))     # frame 0
    weights_attr.Set(bs_weights, Usd.TimeCode(1))     # frame 1 (Blender default start)

    return len(bs_usd_names)


def _detect_strand_length(points: list[list[float]]) -> int:
    """Return the number of vertices per strand by finding the first large gap."""
    sample = points[:min(200, len(points))]
    dists = [
        math.sqrt(sum((sample[i][j] - sample[i + 1][j]) ** 2 for j in range(3)))
        for i in range(len(sample) - 1)
    ]
    if not dists:
        return len(points)
    median_d = sorted(dists)[len(dists) // 2]
    threshold = median_d * 5.0
    for i, d in enumerate(dists):
        if d > threshold:
            return i + 1
    return len(points)


def _write_curves(
    stage: Usd.Stage,
    curves_path: str,
    points: list[list[float]],
    strand_len: int,
) -> int:
    """Write strand hair as linear UsdGeom.BasisCurves. Returns number of strands written."""
    n_strands = len(points) // strand_len
    if n_strands == 0:
        return 0
    pts = points[:n_strands * strand_len]
    curves = UsdGeom.BasisCurves.Define(stage, Sdf.Path(curves_path))
    curves.GetTypeAttr().Set(UsdGeom.Tokens.linear)
    curves.GetPointsAttr().Set([Gf.Vec3f(*p) for p in pts])
    curves.GetCurveVertexCountsAttr().Set([strand_len] * n_strands)
    curves.GetWidthsAttr().Set([0.05])  # 0.5 mm constant width
    curves.SetWidthsInterpolation(UsdGeom.Tokens.constant)
    return n_strands


def _apply_transform(xformable: UsdGeom.Xformable, node: "DazNode") -> None:  # noqa: F821
    pos = node.position or {"x": 0.0, "y": 0.0, "z": 0.0}
    rot = node.rotation or {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
    xformable.AddTranslateOp().Set(Gf.Vec3d(pos["x"], pos["y"], pos["z"]))
    xformable.AddOrientOp().Set(
        Gf.Quatf(rot["w"], Gf.Vec3f(rot["x"], rot["y"], rot["z"]))
    )


def _write_camera(stage: Usd.Stage, prim_path: str, cam: DazCamera) -> None:
    usd_cam = UsdGeom.Camera.Define(stage, Sdf.Path(prim_path))
    _apply_transform(usd_cam, cam)

    focal = cam.focal_length
    if focal is not None:
        usd_cam.GetFocalLengthAttr().Set(float(focal))

    sensor_w = cam.frame_width
    if sensor_w is not None:
        usd_cam.GetHorizontalApertureAttr().Set(float(sensor_w))
        # Derive vertical aperture from the render aspect ratio
        aw = cam.aspect_width or 1.0
        ah = cam.aspect_height or 1.0
        usd_cam.GetVerticalApertureAttr().Set(float(sensor_w * ah / aw))

    near = cam.near_clipping_plane
    far  = cam.far_clipping_plane
    if near is not None and far is not None:
        usd_cam.GetClippingRangeAttr().Set(Gf.Vec2f(float(near), float(far)))


def _write_light(stage: Usd.Stage, prim_path: str, light: DazLight) -> None:
    if light.is_directional():
        usd_light = UsdLux.DistantLight.Define(stage, Sdf.Path(prim_path))
    elif light.is_area_light():
        usd_light = UsdLux.RectLight.Define(stage, Sdf.Path(prim_path))
    else:
        usd_light = UsdLux.SphereLight.Define(stage, Sdf.Path(prim_path))

    _apply_transform(usd_light, light)

    intensity = light.intensity
    if intensity is not None:
        usd_light.CreateIntensityAttr(float(intensity))

    color = light.color
    if color:
        usd_light.CreateColorAttr(
            Gf.Vec3f(color["r"] / 255.0, color["g"] / 255.0, color["b"] / 255.0)
        )


def _write_morph_script(script_path: str, node_weights: dict[str, dict[str, float]]) -> None:
    """Write a Blender Python script that applies shape key weights after USD import.

    Searches all mesh objects for matching shape key names rather than matching
    by object name, which avoids Blender's .001/.002 rename behaviour.
    The same morph dial value is shared across all DAZ nodes that reference it,
    so a flat name->weight lookup is correct.
    """
    # Flatten to {shape_key_name: weight}. Same key may appear across nodes
    # but always carries the same weight (one DAZ dial), so last write is fine.
    flat: dict[str, float] = {}
    for weights in node_weights.values():
        flat.update(weights)

    lines = [
        '"""Run in Blender\'s Script Editor after importing the USD file.',
        "Select Scripting workspace -> Open this file -> Run Script.",
        '"""',
        "import bpy",
        "",
        "_WEIGHTS = {",
    ]
    for k, v in flat.items():
        lines.append(f"    {k!r}: {v},")
    lines += [
        "}",
        "",
        "hits = 0",
        "for obj in bpy.data.objects:",
        "    if not (obj.data and hasattr(obj.data, 'shape_keys') and obj.data.shape_keys):",
        "        continue",
        "    for key_name, value in _WEIGHTS.items():",
        "        kb = obj.data.shape_keys.key_blocks.get(key_name)",
        "        if kb:",
        "            kb.value = value",
        "            hits += 1",
        "print(f'Applied {hits} shape key weight(s) across scene')",
    ]
    with open(script_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ── main export ───────────────────────────────────────────────────────────────


def export_live_scene(out_path: str, frame: int | None, render_visible_only: bool, with_morphs: bool = False) -> None:
    client = DazClient()
    scene = DazScene(client)

    original_frame = scene.frame()
    if frame is not None:
        scene.set_frame(frame)

    stage = Usd.Stage.CreateNew(out_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 0.01)  # DAZ uses centimetres
    UsdGeom.Xform.Define(stage, "/Scene")
    UsdGeom.Scope.Define(stage, "/Scene/Materials")

    used_names: dict[str, int] = {}

    def _alloc_key(raw: str) -> str:
        base = _usd_name(raw)
        n = used_names.get(base, 0)
        used_names[base] = n + 1
        return base if n == 0 else f"{base}_{n}"

    meshes_written = cameras_written = lights_written = skipped = 0
    # {usd_key: {shape_key_name: weight}} — collected for companion Blender script
    blender_weights: dict[str, dict[str, float]] = {}

    for node in scene.nodes():
        if node.name is None:
            skipped += 1
            continue

        if render_visible_only and not node.is_visible_in_render():
            skipped += 1
            continue

        geom = DazGeometry(client, NodeIdentifier(node.name))
        if not geom.vertex_count:
            skipped += 1
            continue

        usd_key    = _alloc_key(node.label or node.name)
        xform_path = f"/Scene/{usd_key}"
        mesh_path  = f"{xform_path}/{usd_key}"
        mat_path   = f"/Scene/Materials/{usd_key}"

        label = node.label or node.name

        if geom.facet_count == 0:
            # No polygon faces — treat as strand-based hair (DzGraftingFigureShape).
            # Export world-space cached positions as linear BasisCurves.
            posed_verts = geom.vertex_positions_posed_all()
            if not posed_verts:
                skipped += 1
                continue
            strand_len = _detect_strand_length(posed_verts)
            xform = UsdGeom.Xform.Define(stage, Sdf.Path(xform_path))
            n_strands = _write_curves(stage, mesh_path, posed_verts, strand_len)
            print(f"  {label}: {n_strands} hair strands ({strand_len} verts each)")
            meshes_written += 1
            continue

        morph_data: list[dict] = []
        if with_morphs:
            morph_list = _fetch_active_morphs(client, node.name)
            if morph_list:
                print(f"  {label}: fetching {len(morph_list)} blend shape(s)...")
                for m in morph_list:
                    deltas = _fetch_morph_deltas(client, node.name, m["name"])
                    if deltas is not None:
                        morph_data.append({**m, **deltas})

        if morph_data:
            xform = UsdSkel.Root.Define(stage, Sdf.Path(xform_path))
            # Blend-shape export: base mesh must be T-pose so blend shapes apply
            # cleanly.  Node transform applied because positions are object-space.
            _apply_transform(xform, node)
            morphed_verts = geom.vertex_positions_all()
            base_verts = _compute_base_verts(morphed_verts, morph_data)
            _write_mesh(stage, mesh_path, geom, points=base_verts)
        else:
            xform = UsdGeom.Xform.Define(stage, Sdf.Path(xform_path))
            # Posed export: getCachedGeom() returns world-space vertices that
            # include skeleton skinning + morphs, so the Xform stays at identity.
            posed_verts = geom.vertex_positions_posed_all()
            _write_mesh(stage, mesh_path, geom, points=posed_verts if posed_verts else None)

        _write_material(stage, mat_path, node, mesh_path)

        if morph_data:
            n_bs = _write_blend_shapes(stage, xform_path, mesh_path, morph_data)
            print(f"  {label}: wrote {n_bs} blend shape(s)")
            blender_weights[usd_key] = {
                _usd_name(m["name"]): m["weight"] for m in morph_data
            }

        meshes_written += 1

    for cam in scene.cameras():
        if cam.name is None:
            continue
        usd_key = _alloc_key(cam.label or cam.name)
        _write_camera(stage, f"/Scene/{usd_key}", cam)
        cameras_written += 1

    for light in scene.lights():
        if light.name is None:
            continue
        usd_key = _alloc_key(light.label or light.name)
        _write_light(stage, f"/Scene/{usd_key}", light)
        lights_written += 1

    if frame is not None:
        scene.set_frame(original_frame)

    stage.Save()
    print(
        f"Wrote {meshes_written} mesh(es), {cameras_written} camera(s), "
        f"{lights_written} light(s), skipped {skipped} → {out_path}"
    )

    if blender_weights:
        import os
        base, _ = os.path.splitext(out_path)
        script_path = base + "_apply_morphs.py"
        _write_morph_script(script_path, blender_weights)
        print(f"Blender morph script → {script_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--out", default="scene.usda",
        help="Output path (.usda ASCII or .usdc binary, default: scene.usda)",
    )
    parser.add_argument(
        "--frame", type=int, default=None,
        help="Timeline frame to capture (default: whichever frame is current in DAZ Studio)",
    )
    parser.add_argument(
        "--render-visible-only", action="store_true",
        help="Skip nodes hidden from render output",
    )
    parser.add_argument(
        "--morphs", action="store_true",
        help="Export non-zero morphs as UsdSkel blend shapes (slow — fetches delta data per morph)",
    )
    args = parser.parse_args()
    export_live_scene(args.out, args.frame, args.render_visible_only, args.morphs)
