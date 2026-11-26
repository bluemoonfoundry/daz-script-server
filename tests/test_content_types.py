"""Unit tests for content-type names and matching."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dazpy._content_types import FRIENDLY_TYPES, is_known_type, type_matches, type_prefixes


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

    def test_bottom_two_prefixes(self):
        self.assertTrue(type_matches("bottom", "Follower/Wardrobe/Skirt"))
        self.assertTrue(type_matches("bottom", "Follower/Wardrobe/Pants"))
        self.assertEqual(len(type_prefixes("bottom")), 2)

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
