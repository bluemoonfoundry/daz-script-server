from __future__ import annotations

from ._modifier import DazModifier
from ._script_builder import ScriptBuilder


class DazDForce(DazModifier):
    """Proxy for a ``DzDForceModifier`` (cloth/hair dForce simulation modifier).

    Returned by :meth:`DazNode.modifiers`, :meth:`DazNode.find_modifier`,
    :meth:`DazNode.find_modifier_by_label`, and :meth:`DazNode.dforce_modifiers`
    when the underlying DAZ modifier is a ``DzDForceModifier``.

    Simulation tunables not covered by :attr:`freeze_simulation` (e.g.
    ``"Dynamics Strength"``, ``"Contraction-Expansion Ratio"``, the various
    stiffness weight maps) are still reachable through the inherited
    :meth:`~dazpy.DazElement.get_property` / :meth:`~dazpy.DazElement.set_property`,
    which look properties up by their Parameters-pane label.
    """

    @property
    def freeze_simulation(self) -> bool | None:
        """Whether the simulated result is frozen onto the mesh (read/write).

        Freezing detaches the mesh from the live dForce solve so it holds its
        current shape without needing to re-simulate — this is DAZ Studio's
        equivalent of "baking" a dForce result.
        """
        script = ScriptBuilder.iife(f"""
            var m = {self._locator};
            if (!m) return null;
            var p = m.findPropertyByLabel("Freeze Simulation");
            return p ? p.getValue() : null;
        """)
        return self._client.execute(script).value

    @freeze_simulation.setter
    def freeze_simulation(self, value: bool) -> None:
        flag = "true" if value else "false"
        script = ScriptBuilder.iife(f"""
            var m = {self._locator};
            if (!m) return;
            var p = m.findPropertyByLabel("Freeze Simulation");
            if (p) p.setValue({flag});
        """)
        self._client.execute(script)

    def freeze(self) -> None:
        """Bake the current simulated result onto the mesh (sets ``freeze_simulation`` on)."""
        self.freeze_simulation = True

    def unfreeze(self) -> None:
        """Release a frozen simulation so it resumes following the dForce solve."""
        self.freeze_simulation = False


# JS: locate the dForce modifier on _node (node, object or shape modifiers)
# and list every modifier for error messages. Needs `_node` in scope.
DFORCE_FIND_JS = """
    function _isDForce(mod) {
        if (!mod) return false;
        var cn = (mod.className ? mod.className() : "").toLowerCase();
        if (cn.indexOf("dforce") !== -1 || cn.indexOf("dynamics") !== -1) return true;
        return typeof mod.findProperty === "function" &&
               !!(mod.findProperty("Freeze Simulation") || mod.findProperty("Dynamics Strength"));
    }
    function _hosts() {
        var obj = (typeof _node.getObject === "function") ? _node.getObject() : null;
        var shape = obj && obj.getCurrentShape ? obj.getCurrentShape() : null;
        return [["node", _node], ["obj", obj], ["shape", shape]];
    }
    function _findDForce() {
        var hs = _hosts();
        for (var h = 0; h < hs.length; h++) {
            var host = hs[h][1];
            if (!host || typeof host.getNumModifiers !== "function") continue;
            for (var i = 0; i < host.getNumModifiers(); i++)
                if (_isDForce(host.getModifier(i))) return host.getModifier(i);
        }
        return null;
    }
    function _modifierNames() {
        var out = [], hs = _hosts();
        for (var h = 0; h < hs.length; h++) {
            var host = hs[h][1];
            if (!host || typeof host.getNumModifiers !== "function") continue;
            for (var i = 0; i < host.getNumModifiers(); i++) {
                var m = host.getModifier(i);
                out.push(hs[h][0] + ":" + (m && m.className ? m.className() : "unknown"));
            }
        }
        return out;
    }
"""

# JS: the dForce simulation-settings provider for a surface. Needs `_node`.
DFORCE_PROVIDER_JS = """
    function _provider(matName) {
        var obj = _node.getObject ? _node.getObject() : null;
        var shape = obj ? obj.getCurrentShape() : null;
        if (!shape) return {status: "no_shape"};
        if (typeof shape.findSimulationSettingsProvider !== "function") return {status: "unsupported"};
        if (!matName) {
            if (shape.getNumMaterials() === 0) return {status: "no_materials"};
            matName = shape.getMaterial(0).getName();
        }
        var prov = shape.findSimulationSettingsProvider(matName);
        if (!prov) {
            var names = [];
            if (typeof shape.getSimulationProviderNames === "function") {
                var pn = shape.getSimulationProviderNames();
                for (var i = 0; i < pn.length; i++) names.push(pn[i]);
            }
            return {status: "no_provider", material: matName, available: names};
        }
        return {status: "ok", material: matName, provider: prov};
    }
"""
