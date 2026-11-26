import unittest

from dazpy._asset_finder import AssetCandidate, FinderUnavailable
from dazpy._asset_ref import AssetRef, ResolvedPin
from dazpy._asset_resolve import recipe_refs, resolve_refs
from dazpy._recipe_model import SceneRecipe
from tests.recipe_fakes import fake_resolve_client


def cand(path, product="P", sku="1", type="Follower/Hair", asset_id=None):
    return AssetCandidate(path, product, sku, asset_id, type)


class Finder:
    name = "studio"

    def __init__(self, search=(), files=(), unavailable=False):
        self._search, self._files, self.unavailable = list(search), list(files), unavailable
        self.searches = 0

    def search(self, phrase, *, type, limit=10):
        self.searches += 1
        if self.unavailable:
            raise FinderUnavailable("content_database_unavailable")
        return self._search

    def product_files(self, *, sku=None, product=None):
        if self.unavailable:
            raise FinderUnavailable("content_database_unavailable")
        return self._files


def run(refs, finder=None, found=None, prior=None):
    paths = {c.path: c.path for c in (finder._search + finder._files if finder else [])}
    paths.update(found or {})
    return resolve_refs(fake_resolve_client(paths), refs, finder or Finder(), prior)


class ResolveTests(unittest.TestCase):
    def test_path_ref(self):
        r = run([("a", AssetRef(path="/x.duf"))], found={"/x.duf": "C:/x.duf"})
        self.assertEqual(r.resolved["a"].path, "C:/x.duf")
        self.assertEqual(r.resolved["a"].finder, "path")
        self.assertFalse(r.errors)

    def test_path_missing_is_asset_not_found(self):
        r = run([("a", AssetRef(path="/x.duf"))])
        self.assertEqual([e.code for e in r.errors], ["asset_not_found"])
        self.assertEqual(r.errors[0].path, "a")

    def test_find_exact_name_beats_fuzzy(self):
        f = Finder(search=[cand("/a.duf", "Bunched Hair Updo"),
                           cand("/b.duf", "Bunched Hair Updo Texture Add-on"),
                           cand("/c.duf", "Bun Updo")])
        r = run([("a", AssetRef(find="Bunched Hair Updo"))], f)
        self.assertEqual(r.resolved["a"].path, "/a.duf")
        self.assertFalse(r.errors)

    def test_find_ambiguous_lists_candidates(self):
        f = Finder(search=[cand("/a.duf", "Updo One", "1"), cand("/b.duf", "Updo Two", "2")])
        r = run([("a", AssetRef(find="Updo"))], f)
        self.assertEqual(r.errors[0].code, "ambiguous_asset")
        self.assertEqual(len(r.errors[0].allowed), 2)
        self.assertIn("/b.duf", r.errors[0].allowed[1])

    def test_find_type_filter(self):
        f = Finder(search=[cand("/top.duf", "Updo", type="Follower/Wardrobe/Top"),
                           cand("/hair.duf", "Updo", type="Follower/Hair")])
        r = run([("a", AssetRef(find="Updo", type="hair"))], f)
        self.assertEqual(r.resolved["a"].path, "/hair.duf")
        self.assertFalse(r.errors)

    def test_sku_multi_file_needs_file(self):
        f = Finder(files=[cand("/P/Updo.duf"), cand("/P/Other.duf")])
        r = run([("a", AssetRef(sku="1"))], f)
        self.assertEqual(r.errors[0].code, "ambiguous_asset")
        r = run([("a", AssetRef(sku="1", file="updo.DUF"))], f)
        self.assertEqual(r.resolved["a"].path, "/P/Updo.duf")
        self.assertFalse(r.errors)

    def test_file_content_relative_vs_absolute(self):
        f = Finder(files=[cand("X:/Library/People/Genesis 9/Hair/Updo.duf"),
                          cand("X:/Library/People/Genesis 9/Hair/Other.duf")])
        for file in ("/People/Genesis 9/Hair/Updo.duf", r"\people\GENESIS 9\hair\updo.DUF"):
            r = run([("a", AssetRef(sku="1", file=file))], f)
            self.assertFalse(r.errors, file)
            self.assertTrue(r.resolved["a"].path.endswith("Updo.duf"))

    def test_file_partial_segment_does_not_match(self):
        f = Finder(files=[cand("X:/Library/Hair/Updo.duf")])
        r = run([("a", AssetRef(sku="1", file="pdo.duf"))], f)
        self.assertEqual(r.errors[0].code, "asset_not_found")

    def test_sku_no_files(self):
        r = run([("a", AssetRef(sku="1"))], Finder())
        self.assertEqual(r.errors[0].code, "asset_not_found")

    def test_pin_used_without_search(self):
        f = Finder()
        ref = AssetRef(find="Updo", resolved=ResolvedPin("/p.duf", sku="9"))
        r = run([("a", ref)], f, found={"/p.duf": "C:/p.duf"})
        self.assertEqual(f.searches, 0)
        self.assertEqual((r.resolved["a"].finder, r.resolved["a"].path), ("pin", "C:/p.duf"))

    def test_pin_mismatch_warns(self):
        ref = AssetRef(sku="1", resolved=ResolvedPin("/p.duf", sku="9"))
        r = run([("a", ref)], Finder(), found={"/p.duf": "/p.duf"})
        self.assertEqual([w.code for w in r.warnings], ["pin_mismatch"])
        self.assertEqual(r.resolved["a"].finder, "pin")

    def test_pin_missing_falls_back(self):
        f = Finder(search=[cand("/a.duf", "Updo")])
        ref = AssetRef(find="Updo", resolved=ResolvedPin("/gone.duf"))
        r = run([("a", ref)], f)
        self.assertEqual([w.code for w in r.warnings], ["pin_file_missing"])
        self.assertEqual(r.resolved["a"].path, "/a.duf")
        self.assertEqual(r.resolved["a"].finder, "studio")

    def test_record_reuse(self):
        ref = AssetRef(find="Updo")
        prior = {"a": {"requested": "x", "path": "/old.duf", "sku": "7"}}
        f = Finder(search=[cand("/new.duf", "Updo")])
        prior["a"]["requested"] = ref.to_dict()
        r = run([("a", ref)], f, found={"/old.duf": "/old.duf"}, prior=prior)
        self.assertEqual((r.resolved["a"].finder, r.resolved["a"].sku), ("record", "7"))
        self.assertEqual(f.searches, 0)
        prior["a"]["requested"] = AssetRef(find="Other").to_dict()
        r = run([("a", ref)], f, found={"/old.duf": "/old.duf"}, prior=prior)
        self.assertEqual(r.resolved["a"].path, "/new.duf")
        self.assertEqual(r.resolved["a"].finder, "studio")

    def test_finder_unavailable(self):
        r = run([("a", AssetRef(sku="1")), ("b", AssetRef(path="/x.duf"))],
                Finder(unavailable=True), found={"/x.duf": "/x.duf"})
        self.assertEqual([(e.path, e.code) for e in r.errors],
                         [("a", "content_database_unavailable")])
        self.assertIn("b", r.resolved)

    def test_to_dict(self):
        r = run([("a", AssetRef(path="/x.duf"))], found={"/x.duf": "/x.duf"})
        self.assertEqual(r.resolved["a"].to_dict()["requested"], "/x.duf")


class RecipeRefsTests(unittest.TestCase):
    def test_paths(self):
        rec = SceneRecipe.from_dict({
            "recipe_version": 2, "id": "r",
            "assets": {"fig": {"path": "/G9.duf"}},
            "actors": {"abby": {"asset": "fig", "presets": ["/p0.duf", {"find": "Glow"}],
                                "wearing": [{"add": {"find": "Updo"}, "key": "hair"},
                                            {"remove": "hair"}]}},
            "props": {"chair": {"asset": {"sku": "5"}}}})
        got = dict(recipe_refs(rec))
        self.assertEqual(set(got), {"actors.abby.asset", "actors.abby.presets[0]",
                                    "actors.abby.presets[1]", "actors.abby.wearing.hair",
                                    "props.chair.asset"})
        self.assertEqual(got["actors.abby.asset"].path, "/G9.duf")


if __name__ == "__main__":
    unittest.main()
