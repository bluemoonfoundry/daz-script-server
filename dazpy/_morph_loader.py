"""Morph Loader Pro (``DzMorphLoader``): build a morph on a node from an OBJ.

Used by :meth:`dazpy.DazNode.load_morph`. The loader runs silently
(``RunSilent``); option names follow the Morph Loader Pro dialog.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ._script_builder import ScriptBuilder

if TYPE_CHECKING:
    from ._node import DazNode


@dataclass(frozen=True)
class MorphLoadResult:
    """Outcome of :meth:`DazNode.load_morph`.

    Attributes:
        morph_name: The morph the loader created (it may differ from the
            requested name with ``overwrite_mode="MakeUnique"``).
        control_property: Label of the controlling property, when one was set.
        log: The loader's report (errors and warnings by default).
    """

    morph_name: str
    control_property: str | None
    log: str


_LOADER_JS = """
    if (typeof DzMorphLoader !== "function")
        return {status: "error", message: "DzMorphLoader is not available (enable the Morph Loader Pro plugin)"};
    var LOAD_MODES = {EntireFigure: 0, SelectedNodes: 1, PrimaryNode: 2, SingleSkinFigure: 3,
                      SingleSkinFigureFromGraft: 4};
    var MIRROR = {DoNotMirror: 0, XSwap: 1, XPosToNeg: 2, XNegToPos: 3, YSwap: 4, YPosToNeg: 5,
                  YNegToPos: 6, ZSwap: 7, ZPosToNeg: 8, ZNegToPos: 9};
    var OVERWRITE = {MakeUnique: 0, DeltasAndERCLinks: 1, DeltasOnly: 2};
    var SUBD = {Catmark: 0, FacetOrder: 1, ZBrushCage: 2, MudboxCage: 3};
    var ERC = {ERCDeltaAdd: 0, ERCDivideInto: 1, ERCDivideBy: 2, ERCMultiply: 3, ERCSubtract: 4,
               ERCAdd: 5, ERCKeyed: 6};
    function pick(table, name, label) {
        if (!table.hasOwnProperty(name)) {
            var valid = []; for (var k in table) if (table.hasOwnProperty(k)) valid.push(k);
            throw new Error("Unknown " + label + ": " + name + ". Valid: " + valid.join(", "));
        }
        return table[name];
    }
    function has(k) { return o[k] !== undefined && o[k] !== null; }
    try {
        var loader = new DzMorphLoader();
        loader.setFilename(o.objPath);
        if (has("morphName")) loader.setMorphName(String(o.morphName));
        if (!loader.setLoadMode(pick(LOAD_MODES, o.loadMode, "loadMode"), _node))
            return {status: "error", message: "setLoadMode failed for mode " + o.loadMode};
        loader.setOverwriteExisting(pick(OVERWRITE, o.overwriteMode, "overwriteMode"));
        loader.setMorphMirroring(pick(MIRROR, o.mirroring, "mirroring"));
        if (has("preserveExistingDeltas")) loader.setPreserveExistingDeltas(!!o.preserveExistingDeltas);
        if (has("cleanUpOrphans")) loader.setCleanUpOrphans(!!o.cleanUpOrphans);
        if (has("deltaTolerance")) loader.setDeltaTolerance(o.deltaTolerance);
        if (has("subdivision")) loader.setMorphSubdivision(!!o.subdivision);
        if (has("subdivisionMapping")) loader.setSubdivisionMapping(pick(SUBD, o.subdivisionMapping, "subdivisionMapping"));
        if (has("subdivisionMinResolution")) loader.setSubdivisionMinResolution(o.subdivisionMinResolution);
        if (has("subdivisionMaxResolution")) loader.setSubdivisionMaxResolution(o.subdivisionMaxResolution);
        if (has("subdivisionBuiltResolution")) loader.setSubdivisionBuiltResolution(o.subdivisionBuiltResolution);
        if (has("subdivisionSmoothCage")) loader.setSubdivisionSmoothCage(!!o.subdivisionSmoothCage);
        if (has("attenuateStrength")) loader.setAttenuateStrength(o.attenuateStrength);
        if (has("attenuateEdgeStrength")) loader.setAttenuateEdgeStrength(o.attenuateEdgeStrength);
        if (has("attenuateMapPath")) loader.setAttenuateMapPath(String(o.attenuateMapPath));
        if (has("propertyGroupPath")) loader.setPropertyGroupPath(String(o.propertyGroupPath));
        if (has("hideSecondaryProperties")) loader.setHideSecondaryProperties(!!o.hideSecondaryProperties);
        if (o.reverseDeformations) {
            loader.setReverseDeformations(true);
            if (has("reverseDeformationsPosePath")) loader.setReverseDeformationsPose(String(o.reverseDeformationsPosePath));
            if (!loader.applyReverseDeformationsPose())
                return {status: "error", message: "applyReverseDeformationsPose() failed: check the pose path"};
        }
        var controlLabel = null;
        if (has("controlPropertyName")) {
            var cnode = _control || _node;
            var cp = cnode.findProperty(o.controlPropertyName) || cnode.findPropertyByLabel(o.controlPropertyName);
            if (!cp) return {status: "error", message: "Control property not found: " + o.controlPropertyName};
            if (!cp.inherits("DzNumericProperty"))
                return {status: "error", message: "Control property is not numeric: " + o.controlPropertyName};
            loader.setCreateControlProperty(true);
            loader.setControlNode(cnode);
            loader.setControlProperty(cp);
            controlLabel = cp.getLabel();
            if (has("controlPropertyCustomLabel")) {
                loader.setControlPropertyUseCustomLabel(true);
                loader.setControlPropertyCustomLabel(String(o.controlPropertyCustomLabel));
            }
            if (has("controlPropertyErcType")) loader.setControlPropertyERCType(pick(ERC, o.controlPropertyErcType, "controlPropertyErcType"));
            if (has("controlPropertyErcCustomValue")) {
                loader.setControlPropertyERCUseCustomValue(true);
                loader.setControlPropertyERCCustomValue(o.controlPropertyErcCustomValue);
            }
        }
        var settings = new DzFileIOSettings();
        settings.setFloatValue("Scale", o.scale);
        settings.setIntValue("RunSilent", 1);
        var log = loader.createMorph(settings, _node, !!o.onlyErrorsOrWarnings, true);
        return {status: "ok", morph: loader.getMorphName(), control: controlLabel, log: log || ""};
    } catch (e) {
        return {status: "error", message: String(e.message || e)};
    }
"""


def load_morph(node: "DazNode", obj_path: str, *, control_node: "DazNode | None" = None,
               **options: Any) -> MorphLoadResult:
    """See :meth:`dazpy.DazNode.load_morph`."""
    from .exceptions import DazError, NodeNotFoundError
    camel = {"".join(w.capitalize() if i else w for i, w in enumerate(k.split("_"))): v
             for k, v in options.items()}
    payload = {"objPath": obj_path, "loadMode": "EntireFigure", "overwriteMode": "MakeUnique",
               "mirroring": "DoNotMirror", "scale": 1.0, "onlyErrorsOrWarnings": True, **camel}
    control = control_node._locator if control_node is not None else "null"
    script = ScriptBuilder.node_body_from_locator(
        node._locator, f"var o = {ScriptBuilder.to_js(payload)}; var _control = {control};" + _LOADER_JS)
    raw = node._client.execute(script).value
    if raw is None:
        raise NodeNotFoundError(f"Node not found: {node._identifier.value!r}")
    if raw["status"] != "ok":
        raise DazError(f"Morph Loader Pro: {raw.get('message')}")
    return MorphLoadResult(raw["morph"], raw.get("control"), raw.get("log", ""))
