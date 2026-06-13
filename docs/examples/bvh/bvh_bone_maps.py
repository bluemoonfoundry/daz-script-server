"""DAZ Studio Script Server example: BVH bone-name to DAZ Studio internal bone-name mappings.

PURPOSE
-------
This module is part of the BVH motion-capture import example set.  It provides
the bone-name translation tables used by bvh_import.py to retarget mocap data
from standard BVH conventions to DAZ Studio's per-generation internal bone
names.

It is an *example*, not a complete retargeting library.  A production retarget
tool would cover fingers, facial bones, and every commercial rig variant.  The
goal here is to show that the script server architecture — Python owns the file
parsing and mapping logic, DAZ Studio applies the result per frame — only
requires knowing the internal bone names for each generation, which this module
catalogues.

WHAT IT DEMONSTRATES
--------------------
  - A two-tier translation architecture: BVH convention name -> canonical key,
    then canonical key -> DAZ internal bone name per generation
  - Coverage of CMU mocap database and Mixamo/Adobe auto-rigger conventions
  - Coverage of Genesis 1 through Genesis 9, including twist sub-bone handling
  - Utility functions: build_bvh_to_daz (flat direct mapping) and
    detect_convention (auto-detect from bone names in a BVH file)

Supported BVH conventions
  "cmu"    — CMU mocap database (http://mocap.cs.cmu.edu/)
  "mixamo" — Mixamo / Adobe auto-rigger output

Supported DAZ generations
  "genesis1"  — verified against published rig documentation
  "genesis2"  — verified against published rig documentation
  "genesis3"  — UNVERIFIED: run bvh_discover.py against a loaded figure
  "genesis8"  — UNVERIFIED: run bvh_discover.py against a loaded figure
  "genesis9"  — verified against live scene

ENVIRONMENT SETUP
-----------------
This module has no runtime dependencies beyond the Python standard library.
It is imported by bvh_import.py and bvh_discover.py, both of which require:

1. DAZ Studio must be running with the DazScriptServer plugin loaded and its
   HTTP server active (default: 127.0.0.1:18811).  You can verify it is
   responding with:

       curl http://127.0.0.1:18811/health

2. Install the Python dependencies in a virtual environment:

       python -m venv .venv
       .venv\\Scripts\\activate          # Windows
       # source .venv/bin/activate     # macOS / Linux
       pip install requests

3. Install or develop-install the dazpy SDK (from the repo root):

       pip install -e .

Usage:
    # Import from bvh_import.py or bvh_discover.py — not run directly.
    from bvh_bone_maps import build_bvh_to_daz, detect_convention
"""

# ── canonical joint set ────────────────────────────────────────────────────────
# Internal names that both tiers map through. None in either tier means
# "no counterpart — discard this rotation."

CANONICAL = [
    # Root
    "hips",
    "pelvis",
    # Spine — 4 slots; older rigs with fewer bones map extras to None
    "spine_1", "spine_2", "spine_3", "spine_4",
    # Head chain
    "neck_1", "neck_2",
    "head",
    # Left arm
    "left_collar",
    "left_upper_arm",
    "left_upper_arm_twist_1", "left_upper_arm_twist_2",
    "left_forearm",
    "left_forearm_twist_1", "left_forearm_twist_2",
    "left_hand",
    # Right arm
    "right_collar",
    "right_upper_arm",
    "right_upper_arm_twist_1", "right_upper_arm_twist_2",
    "right_forearm",
    "right_forearm_twist_1", "right_forearm_twist_2",
    "right_hand",
    # Left leg
    "left_thigh",
    "left_thigh_twist_1", "left_thigh_twist_2",
    "left_shin",
    "left_foot",
    "left_toe",
    # Right leg
    "right_thigh",
    "right_thigh_twist_1", "right_thigh_twist_2",
    "right_shin",
    "right_foot",
    "right_toe",
]

# ── Tier 1: BVH convention → canonical ────────────────────────────────────────

BVH_TO_CANONICAL: dict[str, dict[str, str]] = {

    # CMU mocap database
    # Hierarchy: Hips > LowerBack > Spine > Spine1 > Neck > Neck1 > Head
    # Some files omit LowerBack; the importer resolves missing bones gracefully.
    "cmu": {
        "Hips":          "hips",
        "LowerBack":     "spine_1",
        "Spine":         "spine_2",
        "Spine1":        "spine_3",
        "Neck":          "neck_1",
        "Neck1":         "neck_2",
        "Head":          "head",
        "LeftShoulder":  "left_collar",
        "LeftArm":       "left_upper_arm",
        "LeftForeArm":   "left_forearm",
        "LeftHand":      "left_hand",
        "RightShoulder": "right_collar",
        "RightArm":      "right_upper_arm",
        "RightForeArm":  "right_forearm",
        "RightHand":     "right_hand",
        "LeftUpLeg":     "left_thigh",
        "LeftLeg":       "left_shin",
        "LeftFoot":      "left_foot",
        "LeftToeBase":   "left_toe",
        "RightUpLeg":    "right_thigh",
        "RightLeg":      "right_shin",
        "RightFoot":     "right_foot",
        "RightToeBase":  "right_toe",
    },

    # Mixamo / Adobe auto-rigger
    # Bone names carry a "mixamorig:" prefix. Some exporters omit it; the
    # importer strips the prefix before lookup when auto-detecting the convention.
    "mixamo": {
        "mixamorig:Hips":          "hips",
        "mixamorig:Spine":         "spine_1",
        "mixamorig:Spine1":        "spine_2",
        "mixamorig:Spine2":        "spine_3",
        "mixamorig:Neck":          "neck_1",
        "mixamorig:Head":          "head",
        "mixamorig:LeftShoulder":  "left_collar",
        "mixamorig:LeftArm":       "left_upper_arm",
        "mixamorig:LeftForeArm":   "left_forearm",
        "mixamorig:LeftHand":      "left_hand",
        "mixamorig:RightShoulder": "right_collar",
        "mixamorig:RightArm":      "right_upper_arm",
        "mixamorig:RightForeArm":  "right_forearm",
        "mixamorig:RightHand":     "right_hand",
        "mixamorig:LeftUpLeg":     "left_thigh",
        "mixamorig:LeftLeg":       "left_shin",
        "mixamorig:LeftFoot":      "left_foot",
        "mixamorig:LeftToeBase":   "left_toe",
        "mixamorig:RightUpLeg":    "right_thigh",
        "mixamorig:RightLeg":      "right_shin",
        "mixamorig:RightFoot":     "right_foot",
        "mixamorig:RightToeBase":  "right_toe",
    },
}

# ── Tier 2: canonical → DAZ bone name per generation ──────────────────────────

CANONICAL_TO_DAZ: dict[str, dict[str, str | None]] = {

    # Genesis 1
    # Spine chain: hip > abdomen > chest
    # No twist sub-bones anywhere in the rig.
    "genesis1": {
        "hips":                    "hip",
        "pelvis":                  None,
        "spine_1":                 "abdomen",
        "spine_2":                 None,
        "spine_3":                 "chest",
        "spine_4":                 None,
        "neck_1":                  "neck",
        "neck_2":                  None,
        "head":                    "head",
        "left_collar":             "lCollar",
        "left_upper_arm":          "lShldr",
        "left_upper_arm_twist_1":  None,
        "left_upper_arm_twist_2":  None,
        "left_forearm":            "lForeArm",
        "left_forearm_twist_1":    None,
        "left_forearm_twist_2":    None,
        "left_hand":               "lHand",
        "right_collar":            "rCollar",
        "right_upper_arm":         "rShldr",
        "right_upper_arm_twist_1": None,
        "right_upper_arm_twist_2": None,
        "right_forearm":           "rForeArm",
        "right_forearm_twist_1":   None,
        "right_forearm_twist_2":   None,
        "right_hand":              "rHand",
        "left_thigh":              "lThigh",
        "left_thigh_twist_1":      None,
        "left_thigh_twist_2":      None,
        "left_shin":               "lShin",
        "left_foot":               "lFoot",
        "left_toe":                "lToe",
        "right_thigh":             "rThigh",
        "right_thigh_twist_1":     None,
        "right_thigh_twist_2":     None,
        "right_shin":              "rShin",
        "right_foot":              "rFoot",
        "right_toe":               "rToe",
    },

    # Genesis 2
    # Spine chain: hip > abdomen > abdomen2 > chest
    "genesis2": {
        "hips":                    "hip",
        "pelvis":                  None,
        "spine_1":                 "abdomen",
        "spine_2":                 "abdomen2",
        "spine_3":                 "chest",
        "spine_4":                 None,
        "neck_1":                  "neck",
        "neck_2":                  None,
        "head":                    "head",
        "left_collar":             "lCollar",
        "left_upper_arm":          "lShldr",
        "left_upper_arm_twist_1":  None,
        "left_upper_arm_twist_2":  None,
        "left_forearm":            "lForeArm",
        "left_forearm_twist_1":    None,
        "left_forearm_twist_2":    None,
        "left_hand":               "lHand",
        "right_collar":            "rCollar",
        "right_upper_arm":         "rShldr",
        "right_upper_arm_twist_1": None,
        "right_upper_arm_twist_2": None,
        "right_forearm":           "rForeArm",
        "right_forearm_twist_1":   None,
        "right_forearm_twist_2":   None,
        "right_hand":              "rHand",
        "left_thigh":              "lThigh",
        "left_thigh_twist_1":      None,
        "left_thigh_twist_2":      None,
        "left_shin":               "lShin",
        "left_foot":               "lFoot",
        "left_toe":                "lToe",
        "right_thigh":             "rThigh",
        "right_thigh_twist_1":     None,
        "right_thigh_twist_2":     None,
        "right_shin":              "rShin",
        "right_foot":              "rFoot",
        "right_toe":               "rToe",
    },

    # Genesis 3
    # Split-segment rig: each limb segment has a Bend bone and a Twist helper.
    # Spine: hip > abdomenLower > abdomenUpper > chestLower > chestUpper
    # UNVERIFIED — run bvh_discover.py against a loaded Genesis 3 figure to confirm.
    "genesis3": {
        "hips":                    "hip",
        "pelvis":                  None,
        "spine_1":                 "abdomenLower",
        "spine_2":                 "abdomenUpper",
        "spine_3":                 "chestLower",
        "spine_4":                 "chestUpper",
        "neck_1":                  "neckLower",
        "neck_2":                  "neckUpper",
        "head":                    "head",
        "left_collar":             "lCollar",
        "left_upper_arm":          "lShldrBend",
        "left_upper_arm_twist_1":  "lShldrTwist",
        "left_upper_arm_twist_2":  None,
        "left_forearm":            "lForearmBend",
        "left_forearm_twist_1":    "lForearmTwist",
        "left_forearm_twist_2":    None,
        "left_hand":               "lHand",
        "right_collar":            "rCollar",
        "right_upper_arm":         "rShldrBend",
        "right_upper_arm_twist_1": "rShldrTwist",
        "right_upper_arm_twist_2": None,
        "right_forearm":           "rForearmBend",
        "right_forearm_twist_1":   "rForearmTwist",
        "right_forearm_twist_2":   None,
        "right_hand":              "rHand",
        "left_thigh":              "lThighBend",
        "left_thigh_twist_1":      "lThighTwist",
        "left_thigh_twist_2":      None,
        "left_shin":               "lShin",
        "left_foot":               "lFoot",
        "left_toe":                "lToe",
        "right_thigh":             "rThighBend",
        "right_thigh_twist_1":     "rThighTwist",
        "right_thigh_twist_2":     None,
        "right_shin":              "rShin",
        "right_foot":              "rFoot",
        "right_toe":               "rToe",
    },

    # Genesis 8
    # Same internal rig naming as Genesis 3.
    # UNVERIFIED — run bvh_discover.py against a loaded Genesis 8 figure to confirm.
    "genesis8": {
        "hips":                    "hip",
        "pelvis":                  None,
        "spine_1":                 "abdomenLower",
        "spine_2":                 "abdomenUpper",
        "spine_3":                 "chestLower",
        "spine_4":                 "chestUpper",
        "neck_1":                  "neckLower",
        "neck_2":                  "neckUpper",
        "head":                    "head",
        "left_collar":             "lCollar",
        "left_upper_arm":          "lShldrBend",
        "left_upper_arm_twist_1":  "lShldrTwist",
        "left_upper_arm_twist_2":  None,
        "left_forearm":            "lForearmBend",
        "left_forearm_twist_1":    "lForearmTwist",
        "left_forearm_twist_2":    None,
        "left_hand":               "lHand",
        "right_collar":            "rCollar",
        "right_upper_arm":         "rShldrBend",
        "right_upper_arm_twist_1": "rShldrTwist",
        "right_upper_arm_twist_2": None,
        "right_forearm":           "rForearmBend",
        "right_forearm_twist_1":   "rForearmTwist",
        "right_forearm_twist_2":   None,
        "right_hand":              "rHand",
        "left_thigh":              "lThighBend",
        "left_thigh_twist_1":      "lThighTwist",
        "left_thigh_twist_2":      None,
        "left_shin":               "lShin",
        "left_foot":               "lFoot",
        "left_toe":                "lToe",
        "right_thigh":             "rThighBend",
        "right_thigh_twist_1":     "rThighTwist",
        "right_thigh_twist_2":     None,
        "right_shin":              "rShin",
        "right_foot":              "rFoot",
        "right_toe":               "rToe",
    },

    # Genesis 9
    # New lowercase snake_case naming. 4-segment spine, 2 twist helpers per limb.
    # Verified against live scene bone dump (anim.json).
    "genesis9": {
        "hips":                    "hip",
        "pelvis":                  "pelvis",
        "spine_1":                 "spine1",
        "spine_2":                 "spine2",
        "spine_3":                 "spine3",
        "spine_4":                 "spine4",
        "neck_1":                  "neck1",
        "neck_2":                  "neck2",
        "head":                    "head",
        "left_collar":             "l_shoulder",
        "left_upper_arm":          "l_upperarm",
        "left_upper_arm_twist_1":  "l_upperarmtwist1",
        "left_upper_arm_twist_2":  "l_upperarmtwist2",
        "left_forearm":            "l_forearm",
        "left_forearm_twist_1":    "l_forearmtwist1",
        "left_forearm_twist_2":    "l_forearmtwist2",
        "left_hand":               "l_hand",
        "right_collar":            "r_shoulder",
        "right_upper_arm":         "r_upperarm",
        "right_upper_arm_twist_1": "r_upperarmtwist1",
        "right_upper_arm_twist_2": "r_upperarmtwist2",
        "right_forearm":           "r_forearm",
        "right_forearm_twist_1":   "r_forearmtwist1",
        "right_forearm_twist_2":   "r_forearmtwist2",
        "right_hand":              "r_hand",
        "left_thigh":              "l_thigh",
        "left_thigh_twist_1":      "l_thightwist1",
        "left_thigh_twist_2":      "l_thightwist2",
        "left_shin":               "l_shin",
        "left_foot":               "l_foot",
        "left_toe":                "l_toes",
        "right_thigh":             "r_thigh",
        "right_thigh_twist_1":     "r_thightwist1",
        "right_thigh_twist_2":     "r_thightwist2",
        "right_shin":              "r_shin",
        "right_foot":              "r_foot",
        "right_toe":               "r_toes",
    },
}

# ── helpers ────────────────────────────────────────────────────────────────────

def build_bvh_to_daz(
    convention: str,
    generation: str,
) -> dict[str, str]:
    """Return a flat BVH-bone → DAZ-bone mapping for the given convention and generation.

    Entries where either tier resolves to None are omitted (those BVH bones have
    no target in DAZ and their rotations will be silently skipped).

    Args:
        convention: Key into BVH_TO_CANONICAL, e.g. ``"cmu"`` or ``"mixamo"``.
        generation: Key into CANONICAL_TO_DAZ, e.g. ``"genesis9"``.

    Returns:
        Dict mapping BVH bone name → DAZ internal bone name.

    Raises:
        KeyError: If convention or generation is not registered.
    """
    tier1 = BVH_TO_CANONICAL[convention]
    tier2 = CANONICAL_TO_DAZ[generation]
    result: dict[str, str] = {}
    for bvh_bone, canonical in tier1.items():
        daz_bone = tier2.get(canonical)
        if daz_bone is not None:
            result[bvh_bone] = daz_bone
    return result


def detect_convention(bone_names: list[str]) -> str | None:
    """Guess the BVH convention from a list of bone names in the file.

    Args:
        bone_names: All joint names found in the BVH HIERARCHY block.

    Returns:
        A convention key (``"cmu"``, ``"mixamo"``), or ``None`` if unrecognised.
    """
    name_set = set(bone_names)
    if any(n.startswith("mixamorig:") for n in name_set):
        return "mixamo"
    if {"Hips", "LeftArm", "RightArm"}.issubset(name_set):
        return "cmu"
    return None


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.parse_args()
    print("Available BVH conventions :", sorted(BVH_TO_CANONICAL))
    print("Available DAZ generations  :", sorted(CANONICAL_TO_DAZ))
    print()
    print("This module is intended to be imported by bvh_import.py and bvh_discover.py.")
    print("Run those scripts directly to apply BVH motion capture to a DAZ figure.")
