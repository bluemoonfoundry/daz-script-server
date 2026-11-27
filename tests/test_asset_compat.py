import unittest

from dazpy._asset_ref import AssetRef
from dazpy._asset_resolve import ResolvedAsset
from dazpy._asset_compat import (CompatInfo, base_of_asset, check_compat, compat_script,
                                 is_compatible, read_compat)
from tests.recipe_fakes import scripted_client


def asset(path, product=None):
    return ResolvedAsset(AssetRef(path=path), path, None, product, None, None, "path")


class CompatTests(unittest.TestCase):
    def test_descendant_base_compatible(self):
        self.assertTrue(is_compatible("/Genesis 9/Female", ("/Genesis 9",)))
        self.assertTrue(is_compatible("/genesis 9/", ("/Genesis 9",)))

    def test_other_generation_incompatible(self):
        self.assertFalse(is_compatible("/Genesis 9", ("/Genesis 8/Female",)))
        self.assertFalse(is_compatible("/Genesis 90", ("/Genesis 9",)))

    def test_check_compat_errors_and_warnings(self):
        items = {"actors.abby.wearing.hair": asset("/h.duf", "G8 Hair"),
                 "actors.abby.presets[0]": asset("/s.duf")}
        info = {"/h.duf": CompatInfo("/h.duf", ("/Genesis 8/Female",), True),
                "/s.duf": CompatInfo("/s.duf", (), False)}
        errors, warnings = check_compat("/Genesis 9/Female", items, info)
        self.assertEqual([(e.path, e.code) for e in errors],
                         [("actors.abby.wearing.hair", "incompatible_asset")])
        self.assertEqual(errors[0].message,
                         "G8 Hair is made for /Genesis 8/Female; actor 'abby' is /Genesis 9/Female")
        self.assertEqual([(w.path, w.code) for w in warnings],
                         [("actors.abby.presets[0]", "compatibility_unknown")])

    def test_unknown_target_base_warns_for_all(self):
        info = {"/h.duf": CompatInfo("/h.duf", ("/Genesis 9",), True)}
        errors, warnings = check_compat(None, {"actors.a.wearing.h": asset("/h.duf")}, info)
        self.assertEqual((errors, [w.code for w in warnings]), ([], ["compatibility_unknown"]))

    def test_compat_script_reads_metadata_only(self):
        s = compat_script(["C:/x.duf"])
        self.assertIn("findAssetsForFile", s)
        for banned in ("openFile", "loadScene", "mergeFile"):
            self.assertNotIn(banned, s)

    def test_read_compat_and_base_of_asset(self):
        payload = {"/a.duf": {"bases": ["/Genesis 9"], "known": True, "provides": "/Genesis 9"},
                   "/b.duf": {"bases": [], "known": False, "provides": None}}
        client = scripted_client(("recipe:compat", lambda s: payload))
        got = read_compat(client, ["/a.duf", "/b.duf"])
        self.assertEqual(got["/a.duf"], CompatInfo("/a.duf", ("/Genesis 9",), True, "/Genesis 9"))
        self.assertIsNone(got["/b.duf"].provides)
        self.assertFalse(got["/b.duf"].known)
        self.assertEqual(base_of_asset(client, "/a.duf"), "/Genesis 9")
        self.assertIsNone(base_of_asset(client, "/b.duf"))


if __name__ == "__main__":
    unittest.main()
