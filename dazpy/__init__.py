"""dazpy — Python SDK for the DAZ Studio Script Server.

Connect to a running DAZ Studio instance, execute DazScript code, and
manipulate the scene through a type-safe Python API.

Typical usage::

    from dazpy import DazClient, DazScene

    client = DazClient()           # connects to 127.0.0.1:18811
    scene  = DazScene(client)
    figure = scene.find_skeleton_by_label("Genesis 9")
    figure.find_bone("r_forearm").set_local_rotation(0, 0, 45)
"""

__version__ = "2.5.0"

from ._client import DazClient
from ._scene import DazScene
from ._node import DazNode, NodeIdentifier
from ._skeleton import DazSkeleton
from ._bone import DazBone
from ._camera import DazCamera
from ._light import DazLight
from ._material import DazMaterial
from ._modifier import DazModifier
from ._morph import DazMorph
from ._geometry import DazGeometry
from ._render import DazRenderSettings
from ._viewport import DazViewport
from ._timeline import DazTimeline
from ._property import DazProperty
from ._element import DazElement
from ._batch import Batch, BatchFuture
from ._interaction import (
    AxisLimit,
    BalanceTarget,
    BoneChain,
    BoneProfile,
    AnchorTarget,
    ContactTarget,
    FigureRigProfile,
    InteractionAnchor,
    InteractionPlan,
    InteractionRecipe,
    InteractionPosePatch,
    LimbAlignmentResult,
    PreparedInteractionRecipe,
    PreparedInteractionResult,
    FootTarget,
    LookAtTarget,
    HandTarget,
    PoseTarget,
    ResolvedInteractionTarget,
    SolveOptions,
    ValidationIssue,
    build_rig_profile,
    build_rig_profiles_from_snapshot,
    build_fight_recipe,
    build_kiss_recipe,
    build_sit_recipe,
    build_touch_recipe,
    align_foot_target,
    align_hand_target,
    default_axis_limits_for_bone,
    align_single_limb_target,
    apply_interaction_recipe_to_scene,
    prepare_interaction_recipe,
    resolve_interaction_target,
)
from ._undo import UndoGroup
from ._pose import DazPose
from ._animation import DazAnimation
from .math3 import Vec3, Quat, BoundingBox
from ._result import ExecutionResult
from ._polling import execute_long
from ._render_api import (
    FigureMorphs,
    RenderVariant,
    RenderBase,
    RenderResult,
    render,
    render_variants,
)
from .exceptions import RenderError
from . import exceptions

__all__ = [
    "DazClient",
    "DazScene",
    "DazNode",
    "NodeIdentifier",
    "DazSkeleton",
    "DazBone",
    "DazCamera",
    "DazLight",
    "DazMaterial",
    "DazModifier",
    "DazMorph",
    "DazGeometry",
    "DazRenderSettings",
    "DazViewport",
    "DazTimeline",
    "DazProperty",
    "DazElement",
    "Batch",
    "BatchFuture",
    "AxisLimit",
    "BalanceTarget",
    "BoneChain",
    "BoneProfile",
    "AnchorTarget",
    "ContactTarget",
    "FigureRigProfile",
    "InteractionAnchor",
    "InteractionPlan",
    "InteractionRecipe",
    "InteractionPosePatch",
    "LimbAlignmentResult",
    "PreparedInteractionRecipe",
    "PreparedInteractionResult",
    "FootTarget",
    "LookAtTarget",
    "HandTarget",
    "PoseTarget",
    "ResolvedInteractionTarget",
    "SolveOptions",
    "ValidationIssue",
    "build_rig_profile",
    "build_rig_profiles_from_snapshot",
    "build_fight_recipe",
    "build_kiss_recipe",
    "build_sit_recipe",
    "build_touch_recipe",
    "align_foot_target",
    "align_hand_target",
    "default_axis_limits_for_bone",
    "align_single_limb_target",
    "apply_interaction_recipe_to_scene",
    "prepare_interaction_recipe",
    "resolve_interaction_target",
    "UndoGroup",
    "DazPose",
    "DazAnimation",
    "Vec3",
    "Quat",
    "BoundingBox",
    "ExecutionResult",
    "execute_long",
    "FigureMorphs",
    "RenderVariant",
    "RenderBase",
    "RenderResult",
    "RenderError",
    "render",
    "render_variants",
    "exceptions",
]
