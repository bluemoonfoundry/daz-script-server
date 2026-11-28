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


class PresetTypeTests(unittest.TestCase):
    """Final review I7: presets that are figures, wearables or props are refused."""

    def test_script_reports_content_type(self):
        self.assertIn("contentType", compat_script(["/a.duf"]))
        c = scripted_client(("recipe:compat", {"/a.duf": {"bases": ["/Genesis 9"], "known": True,
                                                          "provides": None, "type": "Actor/Character"}}))
        self.assertEqual(read_compat(c, ["/a.duf"])["/a.duf"].type, "Actor/Character")

    def test_refused_and_allowed_types(self):
        from dazpy._asset_compat import check_preset_types
        types = {"/fig.duf": "Actor/Character", "/actor.duf": "Actor", "/hair.duf": "Follower/Hair",
                 "/outfit.duf": "Preset/Wearables", "/prop.duf": "Prop/Furniture",
                 "/shape.duf": "Preset/Character", "/mat.duf": "Preset/Materials/MDL",
                 "/none.duf": ""}
        items = {f"actors.abby.presets[{i}]": asset(p) for i, p in enumerate(types)}
        info = {p: CompatInfo(p, ("/Genesis 9",), True, None, t or None) for p, t in types.items()}
        errors, warnings = check_preset_types(items, info)
        self.assertEqual([(e.path, e.code) for e in errors],
                         [(f"actors.abby.presets[{i}]", "invalid_asset_ref") for i in range(5)])
        self.assertIn("wearing", errors[2].message)
        self.assertEqual([(w.path, w.code) for w in warnings],
                         [("actors.abby.presets[7]", "compatibility_unknown")])

    def test_finder_type_used_when_database_has_none(self):
        from dazpy._asset_compat import check_preset_types
        a = ResolvedAsset(AssetRef(find="x"), "/f.duf", None, None, None, "Actor/Character", "studio")
        errors, _ = check_preset_types({"actors.abby.presets[0]": a},
                                       {"/f.duf": CompatInfo("/f.duf", (), False)})
        self.assertEqual([e.code for e in errors], ["invalid_asset_ref"])


if __name__ == "__main__":
    unittest.main()
