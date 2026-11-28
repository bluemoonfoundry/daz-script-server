"""Content-type names and matching for fitted items (scene recipe v2).

FRIENDLY_TYPES is spec section 6.3 as confirmed by the DS4 live probe against
Studio's own type list and real Genesis 9 content (spec 15.3).  DS6 pending.
"""

from __future__ import annotations

from collections.abc import Mapping

FRIENDLY_TYPES: Mapping[str, tuple[str, ...]] = {
    "hair": ("Follower/Hair",),
    "top": ("Follower/Wardrobe/Shirt", "Follower/Wardrobe/Outerwear/Top"),
    "bottom": ("Follower/Wardrobe/Pant", "Follower/Wardrobe/Skirt",
               "Follower/Wardrobe/Outerwear/Bottom"),
    "dress": ("Follower/Wardrobe/Dress",),
    "outerwear": ("Follower/Wardrobe/Outerwear",),
    "shoes": ("Follower/Wardrobe/Footwear", "Follower/Wardrobe/Shoes"),
    "hat": ("Follower/Wardrobe/Headwear",),
    "accessory": ("Follower/Accessory",),
    "wardrobe": ("Follower/Wardrobe",),
}

# The type of a wearables preset *file* (an outfit or garment preset).  It is
# never a node type: the nodes it loads carry their own Follower/Wardrobe/... types.
WEARABLES_PRESET_TYPE = "Preset/Wearables"
_WARDROBE = "Follower/Wardrobe"


def type_prefixes(t: str) -> tuple[str, ...]:
    """Friendly name -> its prefixes; anything else is a raw prefix."""
    return tuple(FRIENDLY_TYPES.get(t, (t,)))


def _under(prefix: str, root: str) -> bool:
    return prefix == root or prefix.startswith(root + "/")


def type_matches(t: str, presentation_type: str | None) -> bool:
    """True if presentation_type equals or lies under a prefix of t ("/" boundary).

    For scene nodes (``getPresentation().type``)."""
    if not presentation_type:
        return False
    return any(_under(presentation_type, p) for p in type_prefixes(t))


def file_type_matches(t: str, content_type: str | None) -> bool:
    """:func:`type_matches` for a content *file*'s CMS ``contentType``.

    A wearables preset file is ``Preset/Wearables`` whatever garments it loads
    (an outfit), so it matches only the wardrobe family: friendly ``wardrobe`` or
    raw ``Follower/Wardrobe`` (spec 6.3).  Narrow names (``hat``, ``top``, ...)
    never pick an outfit preset."""
    if type_matches(t, content_type):
        return True
    return content_type == WEARABLES_PRESET_TYPE and type_prefixes(t) == (_WARDROBE,)


def is_known_type(t: str) -> bool:
    return t in FRIENDLY_TYPES or "/" in t
