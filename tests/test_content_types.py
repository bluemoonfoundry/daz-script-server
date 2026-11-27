"""Unit tests for content-type names and matching."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy._content_types import (FRIENDLY_TYPES, file_type_matches, is_known_type, type_matches,
                                  type_prefixes)


class ContentTypeTests(unittest.TestCase):
    def test_friendly_hair(self):
        self.assertTrue(type_matches("hair", "Follower/Hair"))
        self.assertTrue(type_matches("hair", "Follower/Hair/Accessory"))

    def test_prefix_boundary(self):
        self.assertFalse(type_matches("Follower/Hat", "Follower/Hatband"))

    def test_raw_type(self):
        self.assertTrue(type_matches("Follower/Wardrobe/Dress", "Follower/Wardrobe/Dress"))

    def test_empty_never_matches(self):
        self.assertFalse(type_matches("wardrobe", ""))
        self.assertFalse(type_matches("wardrobe", None))

    def test_table_matches_ds4_probe(self):
        # spec 6.3 as corrected by the DS4 live probe (spec 15.3)
        self.assertEqual(FRIENDLY_TYPES["top"], ("Follower/Wardrobe/Shirt", "Follower/Wardrobe/Outerwear/Top"))
        self.assertEqual(FRIENDLY_TYPES["bottom"], ("Follower/Wardrobe/Pant", "Follower/Wardrobe/Skirt",
                                                    "Follower/Wardrobe/Outerwear/Bottom"))
        self.assertEqual(FRIENDLY_TYPES["shoes"], ("Follower/Wardrobe/Footwear", "Follower/Wardrobe/Shoes"))
        self.assertEqual(FRIENDLY_TYPES["hat"], ("Follower/Wardrobe/Headwear",))
        self.assertEqual(FRIENDLY_TYPES["hair"], ("Follower/Hair",))
        self.assertEqual(FRIENDLY_TYPES["dress"], ("Follower/Wardrobe/Dress",))
        self.assertEqual(FRIENDLY_TYPES["outerwear"], ("Follower/Wardrobe/Outerwear",))
        self.assertEqual(FRIENDLY_TYPES["accessory"], ("Follower/Accessory",))
        self.assertEqual(FRIENDLY_TYPES["wardrobe"], ("Follower/Wardrobe",))

    def test_real_node_types(self):
        # node types seen on the Detective Outfit (DS4 probe)
        self.assertTrue(type_matches("shoes", "Follower/Wardrobe/Footwear"))
        self.assertTrue(type_matches("bottom", "Follower/Wardrobe/Pant"))
        self.assertTrue(type_matches("top", "Follower/Wardrobe/Shirt"))
        self.assertTrue(type_matches("outerwear", "Follower/Wardrobe/Outerwear"))
        self.assertTrue(type_matches("hat", "Follower/Wardrobe/Headwear"))
        self.assertFalse(type_matches("hat", "Follower/Accessory/Head/Eyes"))
        self.assertFalse(type_matches("bottom", "Follower/Wardrobe/Pants"))

    def test_nodes_never_match_wearables_preset_type(self):
        self.assertFalse(type_matches("wardrobe", "Preset/Wearables"))

    def test_file_type_accepts_wearables_preset_for_wardrobe_names(self):
        for t in ("wardrobe", "top", "bottom", "dress", "outerwear", "shoes", "hat",
                  "Follower/Wardrobe", "Follower/Wardrobe/Shirt"):
            self.assertTrue(file_type_matches(t, "Preset/Wearables"), t)
        for t in ("hair", "accessory", "Follower/Hair", "Follower"):
            self.assertFalse(file_type_matches(t, "Preset/Wearables"), t)
        self.assertTrue(file_type_matches("hair", "Follower/Hair"))
        self.assertFalse(file_type_matches("wardrobe", "Preset/Materials/MDL"))
        self.assertFalse(file_type_matches("wardrobe", None))

    def test_unknown_friendly(self):
        self.assertFalse(is_known_type("hairs"))
        self.assertTrue(is_known_type("hair"))
        self.assertTrue(is_known_type("Follower/Hair"))

    def test_raw_prefixes(self):
        self.assertEqual(type_prefixes("Follower/Hair"), ("Follower/Hair",))

    def test_table_complete(self):
        self.assertEqual(set(FRIENDLY_TYPES), {
            "hair", "top", "bottom", "dress", "outerwear", "shoes",
            "hat", "accessory", "wardrobe"})


if __name__ == "__main__":
    unittest.main()
