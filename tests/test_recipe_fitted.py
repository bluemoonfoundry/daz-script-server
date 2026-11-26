import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._recipe_fitted import figures_script, read_figures
from dazpy._result import ExecutionResult
from recipe_fakes import rec


def _client(figures):
    c = MagicMock()
    c.execute.return_value = ExecutionResult(value={"figures": figures})
    return c


def _fig(name, label, items=(), record=None, base=None):
    return {"name": name, "label": label, "record": record, "compat_base": base,
            "items": list(items)}


class FittedTests(unittest.TestCase):
    def test_read_figures_by_label(self):
        item = {"name": "Hair1", "label": "Hair", "type": "Follower/Hair",
                "source_path": "/data/hair.dsf", "record": rec("r1", "actors.abby.wearing.hair").to_json(),
                "foreign": ["Cap"]}
        c = _client([_fig("Genesis9", "Abby", [item], base="/data/g9.dsf")])
        out = read_figures(c, ["Abby", "Nobody"], [])
        fig = out["Abby"][0]
        self.assertEqual(fig.compat_base, "/data/g9.dsf")
        it = fig.items[0]
        self.assertEqual((it.type, it.source_path, it.foreign_children),
                         ("Follower/Hair", "/data/hair.dsf", ("Cap",)))
        self.assertEqual(it.record.path, "actors.abby.wearing.hair")
        self.assertEqual(out["Nobody"], [])

    def test_two_figures_same_label_ambiguous(self):
        c = _client([_fig("Genesis9", "Abby"), _fig("Genesis9 1", "Abby")])
        self.assertEqual(len(read_figures(c, ["Abby"], [])["Abby"]), 2)

    def test_owned_by_name(self):
        c = _client([_fig("Genesis9 1", "Renamed")])
        out = read_figures(c, [], ["Genesis9 1"])
        self.assertEqual(out["Genesis9 1"][0].label, "Renamed")

    def test_figures_script_case_sensitive(self):
        s = figures_script(["Abby"], ["G9"])
        self.assertIn("getLabel() === label", s)
        self.assertIn('"Abby"', s)
        for bad in ("loadScene", "selectNode", "setSelectedNode", "mergeFile", "openFile"):
            self.assertNotIn(bad, s)


if __name__ == "__main__":
    unittest.main()
