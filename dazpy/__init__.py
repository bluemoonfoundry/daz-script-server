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

__version__ = "2.17.0"

from ._client import DazClient
from ._scene import (
    BatchPropertyResult,
    CameraInfo,
    ContentCategory,
    ContentFile,
    DazScene,
    LightInfo,
    ViewportCamera,
)
from ._morph_loader import MorphLoadResult
from ._node import (
    DazNode,
    FittedItem,
    MorphInfo,
    NodeIdentifier,
    NodeInfo,
    NumericCandidateMatch,
    NumericPropertyWrite,
    PropertyDetails,
)
from ._skeleton import BoneAim, DazSkeleton, LookAtResult
from ._bone import DazBone
from ._camera import DazCamera
from ._light import DazLight
from ._material import DazMaterial, MaterialInfo, MaterialProperty, MaterialPropertyWrite
from ._modifier import DazModifier
from ._morph import DazMorph
from ._dforce import DazDForce
from ._geometry import DazGeometry
from ._geometry_frames import GeometryFrames, parse_geometry_frames
from ._render import DazRenderSettings, Canvas, RenderOutcome
from ._viewport import DazViewport
from ._timeline import DazTimeline
from ._property import DazProperty
from ._element import DazElement
from ._batch import Batch, BatchFuture
from ._interaction import (
    AxisLimit,
    BalanceTarget,
    ANCHOR_SURFACE_RADIUS,
    EFFECTOR_REACH_FALLBACK,
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
    build_face_each_other_recipe,
    build_handshake_recipe,
    build_hug_recipe,
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
from ._scene_state import DazSceneState
from ._animation import DazAnimation
from .math3 import Vec3, Quat, BoundingBox, AxisRemap, Y_UP_TO_Z_UP
from .lighting import (
    LightSpec,
    ThreePointLightSetup,
    ThreePointLightRig,
    apply_three_point_light_setup,
    HDRIEnvironment,
    apply_hdri_environment,
    set_light_color,
)
from .poses import apply_pose, reset_transforms, zero_figure
from .materials import (
    IrayMaterial,
    TextureMap,
    SurfaceProperty,
    apply_iray_material,
    apply_texture_map,
    get_surface_property,
    set_surface_property,
)
from .cinematics import (
    CinematicStaticShot,
    OrbitCamera,
    FrameSubject,
    CameraKeyframe,
    CinematicAnimatedShot,
    apply_static_shot,
    apply_orbit_camera,
    apply_frame_subject,
    apply_animated_shot,
)
from . import shots
from . import shot_library
from .shots import Shot, CoveragePlan, apply_shot
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
from .exceptions import (
    AmbiguousNodeError,
    AsyncExecutionError,
    AuthenticationError,
    BatchLimitExceededError,
    ConcurrencyLimitError,
    ConnectionError as ConnectionError,  # re-export; not in __all__
    DazBusyError,
    DazError,
    MaterialError,
    NodeNotFoundError,
    PropertyNotFoundError,
    RecipeNotAppliedError,
    RecipeValidationError,
    RenderError,
    SceneCheckError,
    ScriptError,
    ScriptRuntimeError,
    ScriptSyntaxError,
    ServerResponseError,
    ServerVersionWarning,
    StudioBusyError,
    TimeoutError as TimeoutError,  # re-export; not in __all__
)
from ._scene_check import CheckFinding, CheckReport
from ._version import MIN_SERVER_VERSION, VersionCheck
from ._recipe_model import SceneRecipe
from ._recipe_validate import RecipeIssue, ValidationReport
from ._recipe_diff import Conflict, RecipePlan
from ._recipe_apply import ApplyResult
from .recipe import ObserveReport, ShotRender, pin
from ._asset_ref import AssetRef
from ._asset_finder import AssetFinder, ContentBrowserFinder, StudioFinder
from ._scene_events import SceneEvent, watch_scene_events, wait_for_scene_event
from . import exceptions

__all__ = [
    "shots",
    "shot_library",
    "Shot",
    "CoveragePlan",
    "apply_shot",
    "DazClient",
    "VersionCheck",
    "MIN_SERVER_VERSION",
    "GeometryFrames",
    "parse_geometry_frames",
    "DazScene",
    "DazNode",
    "NodeIdentifier",
    "NumericCandidateMatch",
    "NodeInfo",
    "FittedItem",
    "MorphInfo",
    "NumericPropertyWrite",
    "MaterialInfo",
    "MaterialProperty",
    "MaterialPropertyWrite",
    "ViewportCamera",
    "BoneAim",
    "LookAtResult",
    "BatchPropertyResult",
    "CameraInfo",
    "ContentCategory",
    "ContentFile",
    "MorphLoadResult",
    "LightInfo",
    "PropertyDetails",
    "DazSkeleton",
    "DazBone",
    "DazCamera",
    "DazLight",
    "DazMaterial",
    "DazModifier",
    "DazMorph",
    "DazDForce",
    "DazGeometry",
    "DazRenderSettings",
    "Canvas",
    "RenderOutcome",
    "DazViewport",
    "DazTimeline",
    "DazProperty",
    "DazElement",
    "Batch",
    "BatchFuture",
    "AxisLimit",
    "BalanceTarget",
    "ANCHOR_SURFACE_RADIUS",
    "EFFECTOR_REACH_FALLBACK",
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
    "build_face_each_other_recipe",
    "build_handshake_recipe",
    "build_hug_recipe",
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
    "DazSceneState",
    "DazAnimation",
    "Vec3",
    "Quat",
    "BoundingBox",
    "AxisRemap",
    "Y_UP_TO_Z_UP",
    "LightSpec",
    "ThreePointLightSetup",
    "ThreePointLightRig",
    "apply_three_point_light_setup",
    "HDRIEnvironment",
    "apply_hdri_environment",
    "set_light_color",
    "apply_pose",
    "reset_transforms",
    "zero_figure",
    "IrayMaterial",
    "TextureMap",
    "SurfaceProperty",
    "apply_iray_material",
    "apply_texture_map",
    "get_surface_property",
    "set_surface_property",
    "CinematicStaticShot",
    "OrbitCamera",
    "FrameSubject",
    "CameraKeyframe",
    "CinematicAnimatedShot",
    "apply_static_shot",
    "apply_orbit_camera",
    "apply_frame_subject",
    "apply_animated_shot",
    "ExecutionResult",
    "execute_long",
    "FigureMorphs",
    "RenderVariant",
    "RenderBase",
    "RenderResult",
    "SceneRecipe",
    "RecipeIssue",
    "ValidationReport",
    "RecipePlan",
    "Conflict",
    "ApplyResult",
    "ObserveReport",
    "ShotRender",
    "pin",
    "AssetRef",
    "AssetFinder",
    "StudioFinder",
    "ContentBrowserFinder",
    "CheckFinding",
    "CheckReport",
    "render",
    "render_variants",
    "SceneEvent",
    "watch_scene_events",
    "wait_for_scene_event",
    "exceptions",
    # Every dazpy exception. ConnectionError and TimeoutError are importable as
    # dazpy.<name> but stay out of __all__ so a star import never shadows the
    # builtins of the same name.
    "AmbiguousNodeError",
    "AsyncExecutionError",
    "AuthenticationError",
    "BatchLimitExceededError",
    "ConcurrencyLimitError",
    "DazBusyError",
    "DazError",
    "MaterialError",
    "NodeNotFoundError",
    "PropertyNotFoundError",
    "RecipeNotAppliedError",
    "RecipeValidationError",
    "RenderError",
    "SceneCheckError",
    "ScriptError",
    "ScriptRuntimeError",
    "ScriptSyntaxError",
    "ServerResponseError",
    "ServerVersionWarning",
    "StudioBusyError",
]
