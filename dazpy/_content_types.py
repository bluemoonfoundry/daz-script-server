"""Content-type names and matching for fitted items (scene recipe v2).

FRIENDLY_TYPES is plain data; prefixes may be corrected by live probing.
"""

from __future__ import annotations

from typing import Mapping, Optional

FRIENDLY_TYPES: Mapping[str, "tuple[str, ...]"] = {
    "hair": ("Follower/Hair",),
    "top": ("Follower/Wardrobe/Top",),
    "bottom": ("Follower/Wardrobe/Pants", "Follower/Wardrobe/Skirt"),
    "dress": ("Follower/Wardrobe/Dress",),
    "outerwear": ("Follower/Wardrobe/Outerwear",),
    "shoes": ("Follower/Wardrobe/Shoe",),
    "hat": ("Follower/Wardrobe/Hat", "Follower/Accessory/Head"),
    "accessory": ("Follower/Accessory",),
    "wardrobe": ("Follower/Wardrobe",),
}


def type_prefixes(t: str) -> "tuple[str, ...]":
    """Friendly name -> its prefixes; anything else is a raw prefix."""
    return tuple(FRIENDLY_TYPES.get(t, (t,)))


def type_matches(t: str, presentation_type: Optional[str]) -> bool:
    """True if presentation_type equals or lies under a prefix of t ("/" boundary)."""
    if not presentation_type:
        return False
    for p in type_prefixes(t):
        if presentation_type == p or presentation_type.startswith(p + "/"):
            return True
    return False


def is_known_type(t: str) -> bool:
    return t in FRIENDLY_TYPES or "/" in t
