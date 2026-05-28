# Interaction Pose Roadmap

This roadmap covers the next major capability gap for the project: interactive
posing for one or more DAZ figures in contact with props or with each other.

The goal is not just to place an arm or foot somewhere. The goal is to make
poses that remain stable under DAZ Studio's rigging rules, bone naming
conventions, joint limits, and per-figure quirks.

## Strategic Choice

The best long-term approach is:

1. Build a DAZ-specific solver layer in Python.
2. Use `SciPy` as the first production optimization engine.
3. Design the solver so it can later be backed by `Pinocchio` for more advanced
   multi-body contact and collision work.
4. Treat `IKPy` only as a rapid prototype/reference tool for simple chain IK.

Why this path:

- `SciPy` is the most flexible way to express DAZ posing as a bounded
  nonlinear least-squares problem.
- DAZ interaction posing is not a single chain problem. It needs targets,
  orientation, posture priors, joint limits, soft contacts, and sometimes
  coupled optimization across two figures.
- `Pinocchio` has the right long-term shape for articulated bodies, inverse
  kinematics, contact dynamics, and collision-aware workflows.
- `IKPy` is fine for narrow prototypes, but it is too limited to be the core of
  a complete interaction system.

## DAZ-Specific Constraints We Must Model

The solver must be built around DAZ's actual control model, not a generic robot
assumption.

- Bone rotations are driven by local axis controls, not arbitrary quaternion
  assignment.
- Rotation order matters.
- Genesis generations differ in bone names, twist-bone layouts, and helper
  chains.
- Some joints are intended to stay mostly stable unless the pose truly needs
  them.
- A solution can be mathematically valid but still look wrong if it violates
  DAZ rig conventions or preferred joint shapes.

The adapter layer should therefore expose:

- Bone names and labels
- Joint limits
- Preferred rest pose
- Rotation order
- Axis conventions
- Chain membership
- Twist/helper bone metadata
- Figure generation metadata

## Core Architecture

### 1. Scene Adapter

This is the bridge between DAZ Studio and the solver.

Responsibilities:

- Read skeletons, bones, morphs, and posed geometry from `dazpy`
- Map DAZ figures to solver-friendly chains
- Cache bone transforms and joint metadata
- Push solved bone rotations back into DAZ

This layer should be built on top of the current `dazpy` APIs rather than
replacing them.

### 2. Constraint Model

The solver should work from a set of explicit constraints rather than ad hoc
hard-coded scripts.

Constraint types to support:

- Position target
- Orientation target
- Look-at target
- Parent-relative target
- Joint limit constraint
- Pose prior / rest-pose regularization
- Contact constraint
- Soft collision / penetration penalty
- Symmetry or coordination constraint
- Multi-figure relationship constraint

### 3. Solver Backends

Keep the problem backend-agnostic.

Recommended backend order:

1. `SciPy` bounded least squares for the first production version
2. `Pinocchio` for advanced articulated-body and collision-aware expansion
3. Optional `IKPy` adapter for fast proof-of-concept chain solving

### 4. Result Application

The solver should output a pose package that can be applied directly to DAZ:

- Per-bone Euler rotations in DAZ's expected rotation order
- Optional morph adjustments
- Optional pelvis or root translation adjustments
- Optional timeline keyframes for animation workflows

## Recommended API Shape

The long-term public API should look something like this:

```python
solution = solve_interaction_pose(
    scene=scene,
    actors=[hero, partner],
    constraints=[
        HandContact(...),
        SeatContact(...),
        LookAt(...),
    ],
    options=SolveOptions(...)
)

solution.apply()
```

Supporting concepts:

- `PoseConstraint`
- `TargetFrame`
- `ContactSurface`
- `BoneChain`
- `JointLimit`
- `SolveOptions`
- `SolveResult`

## Work Phases

### Phase 0: Rig Introspection and Ground Truth

Goal: make the solver aware of what each DAZ figure can actually do.

Tasks:

- Extract bone hierarchy, labels, and local axes for common figure families
- Capture joint limits and preferred ranges
- Identify twist bones and helper bones
- Build test scenes for Genesis 8, 8.1, and 9
- Record how rotation order differs across rigs

Exit criteria:

- We can describe a figure as a solver-ready chain model
- We can round-trip a pose without breaking the rig

### Phase 1: Single-Chain IK

Goal: solve one limb or one control chain at a time.

Initial capabilities:

- Hand to target
- Foot to target
- Head orientation / look-at
- Simple torso adjustment
- Soft joint-limit penalties

Exit criteria:

- A hand can reliably reach a point without exploding the rest of the pose
- The solution respects DAZ joint limits and keeps natural-looking bends

### Phase 2: Contact With Props

Goal: put figures into stable interaction with objects.

Examples:

- Sit on a chair
- Lean on a wall
- Rest a hand on a table
- Hold a prop

What this phase adds:

- Multi-point support
- Root/pelvis offset handling
- Contact normal alignment
- Pose stabilization against slipping
- Basic body-to-prop clearance checks

Exit criteria:

- A seated pose stays seated when solved repeatedly
- Contact points do not visibly drift between refinement passes

### Phase 3: Two-Character Interaction

Goal: solve two figures together as a coupled system.

Examples:

- Hand on shoulder
- Hug
- Kiss
- Push
- Hold wrists

What this phase adds:

- Coupled optimization across two skeletons
- Mutual collision avoidance
- Shared target frames
- Contact continuity between actors

Exit criteria:

- One actor can place a hand on another actor without clipping badly
- Head and torso relationships remain stable across repeated solves

### Phase 4: High-Contact Actions

Goal: support more dynamic posing and fight choreography.

Examples:

- Punches that land on a target
- Kicks that make contact
- Grabs, shoves, blocks, and recoil

What this phase adds:

- Contact timing
- Pre-contact, contact, and recovery phases
- Penetration resistance
- Optional impulse-like offsets for impact styling

Exit criteria:

- We can author a short action sequence as a series of solved key poses
- The sequence reads clearly in renders and baked animation

### Phase 5: Advanced Contact and Dynamics

Goal: push beyond static posing into more physically informed interaction.

Potential additions:

- Collision-aware optimization
- Multi-body contact solving
- Secondary motion approximation
- Physics-assisted recovery after impact
- Better handling of intertwined limbs and close-body contact

This is the phase where `Pinocchio` becomes especially valuable if we decide to
lean into full articulated-body tooling.

## DAZ Quirk Handling Rules

These should be treated as non-negotiable design rules.

- Solve in local joint coordinates, then map to DAZ controls.
- Never assume all figures share the same bone names.
- Never assume a skeleton can be treated as a single generic chain.
- Preserve twist-bone behavior unless the current interaction needs it.
- Keep a rest-pose prior in every solve to prevent unnatural contortions.
- Use soft penalties for contact and collision, not only hard equality.
- Keep the root or pelvis under explicit control for seated and two-actor poses.
- Support both label-based and internal-name-based bone lookup.

## Testing Strategy

We should test in layers.

### Unit tests

- Bone-chain mapping
- Joint-limit conversion
- Rotation-order conversion
- Residual construction
- Pose serialization

### Integration tests

- Single-figure reach target
- Sit pose on a simple chair proxy
- Hand-to-shoulder contact
- Two-figure proximity solve

### Visual validation

- Render the solve result
- Inspect posed geometry for obvious clipping
- Compare before/after frames for stability

## Proposed Milestone Order

1. Add the solver abstraction and data model.
2. Implement figure introspection and DAZ rig adapters.
3. Ship single-chain IK with DAZ-safe joint handling.
4. Add contact-aware prop posing.
5. Add two-figure interaction solving.
6. Add action sequencing and bake-to-animation support.
7. Evaluate whether `Pinocchio` should become the primary long-term backend for
   contact-rich scenarios.

## Definition of Done

The feature is ready when all of the following are true:

- A user can place a figure in a prop interaction pose from Python.
- A user can solve two characters into a stable contact pose.
- The solver respects DAZ joint limits and rotation conventions.
- The result can be baked into animation or rendered directly.
- The architecture can support future collision-aware and multi-body work
  without a rewrite.

