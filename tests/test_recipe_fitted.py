import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dazpy._recipe_fitted import figures_script, read_figures, figure_labels_script, read_figure_labels
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
        self.assertIn('!node.inherits("DzFigure") || _follow(node)', s)
        for bad in ("loadScene", "selectNode", "setSelectedNode", "mergeFile", "openFile"):
            self.assertNotIn(bad, s)

    def test_figures_script_compares_node_wrappers_loosely(self):
        # DS4: two wrappers of one node are == but never === (spec 15.2), so a
        # strict follow-target comparison would report no fitted items at all.
        s = figures_script(["Abby"], [])
        self.assertIn("_follow(it) != fig", s)
        self.assertIn("it == fig", s)
        for strict in ("=== fig", "!== fig"):
            self.assertNotIn(strict, s)
        self.assertNotIn("Provisional", s)

    def test_read_figures_returns_fitted_items(self):
        items = [{"name": n, "label": l, "type": t, "source_path": u, "record": None, "foreign": []}
                 for n, l, t, u in (
                     ("Scalp_1085", "Kara Ponytail", "Follower/Hair",
                      "/data/DAZ%203D/Kara%20Ponytail/Kara%20Ponytail%20Scalp/Scalp_1085.dsf"),
                     ("WD_Hat_1022", "Detective Hat", "Follower/Wardrobe/Headwear",
                      "/data/Barbara_Brundon/Detective%20Outfit/Detective%20Hat/WD_Hat_1022.dsf"))]
        c = _client([_fig("Genesis9", "Abby", items, base="/Genesis 9/Base")])
        fig = read_figures(c, ["Abby"], [])["Abby"][0]
        self.assertEqual([(i.name, i.type) for i in fig.items],
                         [("Scalp_1085", "Follower/Hair"), ("WD_Hat_1022", "Follower/Wardrobe/Headwear")])
        self.assertEqual(fig.compat_base, "/Genesis 9/Base")


class FigureLabelTests(unittest.TestCase):
    def test_script_is_read_only_and_excludes_followers(self):
        js = figure_labels_script()
        self.assertIn("DzFigure", js)
        self.assertIn("getFollowTarget", js)
        for bad in ("removeNode", "addDataItem", "load("):
            self.assertNotIn(bad, js)

    def test_read_figure_labels(self):
        c = MagicMock()
        c.execute.return_value = ExecutionResult(value=["Abby", "Bob"])
        self.assertEqual(read_figure_labels(c), ["Abby", "Bob"])


if __name__ == "__main__":
    unittest.main()
