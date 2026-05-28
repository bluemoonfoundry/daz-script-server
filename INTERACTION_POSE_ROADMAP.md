# Interaction Posing Roadmap

This branch is building a DAZ-aware interaction posing stack in stages. The
first step is a stable adapter layer that understands DAZ bone naming,
rotation-order quirks, and canonical interaction anchors.

## Current focus

1. Build rig profiles from live DAZ skeletons.
2. Normalize major interaction anchors:
   - pelvis
   - spine/chest
   - neck/head
   - shoulders, elbows, hands
   - knees, feet
3. Preserve DAZ-specific metadata:
   - local Euler rotations
   - local positions
   - rotation order
   - twist/helper detection
   - conservative axis limits

## Next phases

1. Add target primitives for hands, feet, head, and pelvis.
2. Add contact anchors for props and other characters.
3. Add a solver backend that consumes the normalized profile.
4. Layer in collision/contact refinement for seating, touch, kissing, and fight choreography.

## Why this order

DAZ figures do not behave like generic robot arms. The solver needs a stable
adapter that maps the rig into canonical control points before any serious
IK/contact work can be reliable.
