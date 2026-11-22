export { DazClient } from "./client.js";
export type {
  DazClientOptions,
  RetryOptions,
  RenderSubmitOptions,
  CapabilityRoute,
  Artifact,
  ArtifactList,
  DownloadArtifactOptions,
  ServerCapabilities,
  RequestStatus,
  CancelResponse,
  StreamOptions,
} from "./client.js";
export { parseSseStream, FINAL_REQUEST_STATUSES } from "./client.js";

export type { ExecutionResult } from "./result.js";

export {
  AsyncExecutionError,
  AuthenticationError,
  BatchLimitExceededError,
  ConcurrencyLimitError,
  ConnectionError,
  DazBusyError,
  DazError,
  DazTimeoutError,
  MaterialError,
  NodeNotFoundError,
  RenderError,
  ArtifactError,
  ScriptError,
  ScriptRuntimeError,
  ScriptSyntaxError,
  StudioBusyError,
} from "./exceptions.js";

export { ScriptBuilder } from "./scriptBuilder.js";

export { Batch, BatchFuture, buildOperationsScript, DEFAULT_MAX_OPERATIONS, DEFAULT_MAX_SCRIPT_LENGTH } from "./batch.js";
export type { BatchOptions } from "./batch.js";

export { executeLong } from "./polling.js";
export type { ExecuteLongOptions } from "./polling.js";

export { AxisRemap, BoundingBox, Quat, Vec3, Y_UP_TO_Z_UP } from "./math3.js";

export { DazElement } from "./element.js";
export { DazProperty } from "./property.js";
export { DazNode, type NodeIdentifier } from "./node.js";
export { DazBone } from "./bone.js";
export { DazCamera } from "./camera.js";
export { DazLight } from "./light.js";
export { DazSkeleton } from "./skeleton.js";
export { DazMaterial } from "./material.js";
export { DazModifier } from "./modifier.js";
export { DazMorph } from "./morph.js";
export { DazDForce } from "./dforce.js";
export { DazScene } from "./scene.js";
export { DazGeometry } from "./geometry.js";
export { DazViewport } from "./viewport.js";
export { DazTimeline } from "./timeline.js";

export { UndoGroup, withUndo } from "./undo.js";

export { DazRenderSettings } from "./render.js";
export type { Canvas, RenderOptions, RenderOutcome } from "./render.js";

export { render, renderVariants } from "./renderApi.js";
export type {
  FigureMorphs,
  RenderBaseSpec,
  RenderCallOptions,
  RenderResult,
  RenderVariantSpec,
  RenderVariantsOptions,
} from "./renderApi.js";

// ── Phase 4: capture/restore and domain helpers ────────────────────────────

export { DazPose } from "./pose.js";
export type { DazPoseDict } from "./pose.js";

export { DazSceneState } from "./sceneState.js";
export type { ApplyOptions, ApplyResult, CaptureOptions, DazSceneStateDict, SkippedNode } from "./sceneState.js";

export { DazAnimation } from "./animation.js";
export type { AnimationFrame, DazAnimationDict } from "./animation.js";

export { sphericalOffset, lookAtEuler, resolveTarget } from "./shotGeometry.js";

export { applyPose, resetTransforms, zeroFigure } from "./poses.js";
export type { ZeroFigureOptions } from "./poses.js";

export { applyIrayMaterial, applyTextureMap, getSurfaceProperty, setSurfaceProperty } from "./materials.js";
export type { IrayMaterial, SurfaceProperty, TextureMap } from "./materials.js";

export { applyHdriEnvironment, applyThreePointLightSetup, setLightColor } from "./lighting.js";
export type { HDRIEnvironment, LightSpec, ThreePointLightRig, ThreePointLightSetup } from "./lighting.js";

export { applyAnimatedShot, applyFrameSubject, applyOrbitCamera, applyStaticShot } from "./cinematics.js";
export type {
  CameraKeyframe,
  CameraTargetOptions,
  CinematicAnimatedShot,
  CinematicStaticShot,
  FrameSubject,
  OrbitCamera,
} from "./cinematics.js";

export { watchSceneEvents, waitForSceneEvent } from "./sceneEvents.js";
export type { SceneEvent } from "./sceneEvents.js";

export { MIN_SERVER_VERSION, parseVersion, evaluateServerVersion } from "./version.js";
export type { VersionCheck } from "./version.js";

// ── Phase 5A: interaction rig profiles + plan data model ───────────────────

export {
  ANCHOR_SURFACE_RADIUS,
  AxisLimit,
  BoneChain,
  BoneProfile,
  FigureRigProfile,
  InteractionAnchor,
  ResolvedInteractionTarget,
  addVec3,
  averageVec3,
  buildRigProfile,
  buildRigProfilesFromSnapshot,
  clamp,
  defaultAxisLimitsForBone,
  detectFigureFamily,
  dotVec3,
  EFFECTOR_REACH_FALLBACK,
  lengthVec3,
  lookupRigProfile,
  looksLikeHelper,
  looksLikeTwist,
  midpointVec3,
  scaleVec3,
  sideFromName,
  subVec3,
} from "./rigProfile.js";
export type {
  AnchorRole,
  AnchorTargetLike,
  AxisLimitDict,
  AxisName,
  BoneChainDict,
  BoneProfileDict,
  ChainRole,
  ChainSide,
  FigureRigProfileDict,
  InteractionAnchorDict,
  ResolvedInteractionTargetDict,
  RigMetadataSource,
  RigSceneSource,
  RigSkeletonSource,
  Rotation3,
  Vector3,
} from "./rigProfile.js";

export {
  BalanceTarget,
  ContactTarget,
  FootTarget,
  HandTarget,
  InteractionPlan,
  InteractionPosePatch,
  InteractionRecipe,
  LookAtTarget,
  PoseTarget,
  PreparedInteractionRecipe,
  PreparedInteractionResult,
  SolveOptions,
  ValidationIssue,
  prepareInteractionRecipe,
  resolveInteractionTarget,
} from "./interactionPlan.js";
export type {
  AlignLimbTargetsOptions,
  AnchorTargetDict,
  InteractionApplyOptions,
  BalanceTargetDict,
  ContactTargetDict,
  InteractionConstraint,
  InteractionPlanDict,
  InteractionPosePatchDict,
  InteractionRecipeDict,
  LookAtTargetDict,
  PoseTargetDict,
  RecipeKind,
  SolveBackend,
  SolveOptionsDict,
  ValidationIssueDict,
} from "./interactionPlan.js";

// ── Phase 5B: IK solver ─────────────────────────────────────────────────────

export {
  LimbAlignmentResult,
  alignFootTarget,
  alignHandTarget,
  alignSingleLimbTarget,
  alignmentChainNames,
  dampedLeastSquaresStep,
  invert3x3,
  mul3x3Vec,
  rotationWithAxisLimits,
} from "./interactionSolve.js";
export type {
  AlignAnchorOptions,
  AlignOptions,
  AlignableSkeleton,
  JacobianSource,
  LimbAlignmentResultDict,
  Matrix3,
} from "./interactionSolve.js";

// Compile-time check: the live classes satisfy the structural sources the
// interaction modules accept (they never import skeleton.ts/scene.ts).
type AssertTrue<T extends true> = T;
export type _DazSkeletonIsRigSkeletonSource = AssertTrue<
  import("./skeleton.js").DazSkeleton extends import("./rigProfile.js").RigSkeletonSource ? true : false
>;
export type _DazSceneIsRigSceneSource = AssertTrue<
  import("./scene.js").DazScene extends import("./rigProfile.js").RigSceneSource ? true : false
>;
