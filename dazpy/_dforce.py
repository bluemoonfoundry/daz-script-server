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
