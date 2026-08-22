"""
models.py - Pydantic data schemas for Offset pre-visualization tool.
Scoped within offset_agent module.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class WallSchema(BaseModel):
    id: str = Field(..., description="Unique identifier for the wall (e.g., 'wall_north')")
    position: tuple[float, float, float] = Field(
        ..., description="[x, y, z] center position in meters (Z-up)"
    )
    width: float = Field(..., description="Width along the wall span in meters")
    height: float = Field(..., description="Height of wall in meters")
    thickness: float = Field(0.2, description="Thickness of wall in meters")
    rotation: float = Field(0.0, description="Rotation around Z-axis in degrees")


class FloorSchema(BaseModel):
    width: float = Field(8.0, description="Total width along X axis in meters")
    depth: float = Field(6.0, description="Total depth along Y axis in meters")


class ShotSchema(BaseModel):
    shot_id: str = Field(..., description="Shot identifier (e.g., 'shot_1_establishing')")
    focal_length_mm: float = Field(35.0, description="Lens focal length in mm")
    start_position: tuple[float, float, float] = Field(
        ..., description="Camera starting world coordinate [x, y, z]"
    )
    end_position: tuple[float, float, float] = Field(
        ..., description="Camera ending world coordinate [x, y, z]"
    )
    duration_seconds: float = Field(5.0, description="Duration of dolly move in seconds")


class SceneConfigSchema(BaseModel):
    walls: list[WallSchema] = Field(default_factory=list)
    floor: FloorSchema = Field(default_factory=FloorSchema)
    shots: list[ShotSchema] = Field(default_factory=list)


class GeometrySchema(BaseModel):
    type: Literal["box", "cylinder", "sphere", "plane"] = "box"
    size: tuple[float, float, float] = (1.0, 1.0, 1.0)
    radius: float | None = None
    height: float | None = None


class TransformSchema(BaseModel):
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)


class MaterialSchema(BaseModel):
    color: str = "#b8bcc2"
    roughness: float = 0.7
    metalness: float = 0.0


class PhysicsSchema(BaseModel):
    collidable: bool = True
    body_type: Literal["static", "dynamic", "kinematic"] = "static"
    mass: float | None = None


class SceneObjectSchema(BaseModel):
    id: str
    name: str
    kind: str
    geometry: GeometrySchema = Field(default_factory=GeometrySchema)
    transform: TransformSchema = Field(default_factory=TransformSchema)
    material: MaterialSchema = Field(default_factory=MaterialSchema)
    physics: PhysicsSchema = Field(default_factory=PhysicsSchema)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SceneLightSchema(BaseModel):
    id: str
    kind: Literal["point", "directional", "spot", "area"] = "point"
    transform: TransformSchema = Field(default_factory=TransformSchema)
    color: str = "#ffffff"
    intensity: float = 1.0


class CameraSchema(BaseModel):
    id: str
    focal_length_mm: float = 35.0
    transform: TransformSchema = Field(default_factory=TransformSchema)
    look_at: tuple[float, float, float] = (0.0, 0.0, 1.2)
    duration_seconds: float | None = None


class ValidationRuleSchema(BaseModel):
    id: str
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)


class SceneSpecSchema(BaseModel):
    scene_id: str = "active_scene"
    name: str = "Untitled Film Set"
    units: Literal["meters"] = "meters"
    up_axis: Literal["Z"] = "Z"
    objects: list[SceneObjectSchema] = Field(default_factory=list)
    cameras: list[CameraSchema] = Field(default_factory=list)
    lights: list[SceneLightSchema] = Field(default_factory=list)
    validation_rules: list[ValidationRuleSchema] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SceneOperationSchema(BaseModel):
    type: Literal["add_object", "update_object", "delete_object", "add_camera", "update_camera", "add_light"]
    id: str | None = None
    object: SceneObjectSchema | None = None
    camera: CameraSchema | None = None
    light: SceneLightSchema | None = None
    patch: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: str  # 'user' | 'assistant' | 'system'
    content: str
    model_used: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    current_config: SceneConfigSchema | None = None
    current_scene: SceneSpecSchema | None = None
    model_preference: str | None = None  # 'auto' | 'haiku' | 'sonnet' | 'opus'


class ChatResponse(BaseModel):
    message: str
    model_used: str
    ready_for_confirmation: bool = False
    scene_config: SceneConfigSchema | None = None
    scene: SceneSpecSchema | None = None
    operations: list[SceneOperationSchema] = Field(default_factory=list)
    readable_summary: str | None = None
    missing_fields: list[str] = Field(default_factory=list)


class GenerateUSDRequest(BaseModel):
    scene_config: SceneConfigSchema
    scene: SceneSpecSchema | None = None
    output_filename: str | None = "generated_set.usda"


class GenerateUSDResponse(BaseModel):
    status: str
    usd_path: str
    prim_count: int
    message: str
    usd_content: str | None = None


class RenderRequest(BaseModel):
    usd_content: str = Field(..., description="USDA raw text string content")
    scene_id: str = Field(..., description="Unique scene identifier")


class RenderStatusResponse(BaseModel):
    status: str  # "pending" | "done" | "failed"
    scene_id: str
    message: str | None = None


class ProposeFixRequest(BaseModel):
    scene_config: SceneConfigSchema
    coverage_flags: list[dict[str, Any]] = Field(default_factory=list)
    physics_flags: list[dict[str, Any]] = Field(default_factory=list)
    collision_flags: list[dict[str, Any]] = Field(default_factory=list)
    shot_id: str | None = None


class ProposeFixResponse(BaseModel):
    status: str
    summary: str | None = Field(
        None,
        description="Director-friendly paragraph explaining the issues and the reasoning behind the proposed fixes.",
    )
    fixes: list[dict[str, Any]] = Field(default_factory=list)
    updated_scene_config: SceneConfigSchema
    model_used: str


class UsdCameraInfo(BaseModel):
    path: str = Field(..., description="Full USD prim path, e.g. '/World/Cameras/WideCam'")
    name: str = Field(..., description="Prim name only, e.g. 'WideCam'")


class ListUsdCamerasRequest(BaseModel):
    usda_path: str = Field(..., description="Absolute path on this machine to the .usda/.usd file to inspect")


class ListUsdCamerasResponse(BaseModel):
    usda_path: str
    cameras: list[UsdCameraInfo] = Field(default_factory=list, description="Every Camera prim actually found in the stage -- empty if the USD has none")


class ValidateUSDRequest(BaseModel):
    """
    Runs a real headless Isaac Sim pass (scenes/standalone_render_and_validate.py)
    against an arbitrary .usda file already sitting on this machine.
    """
    usda_path: str = Field(..., description="Absolute path on this machine to the .usda/.usd file to render + validate")
    scene_id: str | None = Field(None, description="Identifier for the output folder under renders/; auto-generated from the filename if omitted")
    camera: str = Field("/World/MainCamera", description="Camera prim path to render/validate through")
    frames: str = Field("all", description="'all' for every frame in the stage's time range, a comma list like '0,36,72', or '' for start+end only")
    fps: float = Field(24.0, description="Playback frame rate for the stitched video")
    renderer: str = Field("RayTracedLighting", description="RayTracedLighting (fast) or PathTracing (slower, needs a higher warmup)")
    warmup: int = Field(20, description="App update ticks before each capture. RayTracedLighting converges quickly (~20 is plenty); raise substantially (e.g. 150) only for PathTracing")


class ValidateUSDResponse(BaseModel):
    status: str
    scene_id: str
    usda_path: str
    render_files: list[str] = Field(default_factory=list, description="Presigned S3 GET URLs for each captured frame (local copies are deleted after upload)")
    video_file: str | None = Field(None, description="Presigned S3 GET URL for the stitched MP4 (local copy is deleted after upload)")
    frame_count: int = 0
    validation_result: dict[str, Any] = Field(default_factory=dict, description="Contents of validation_result.json: {status, violations, camera_collisions}")
    s3_bucket: str | None = Field(None, description="S3 bucket the outputs were uploaded to")
    s3_prefix: str | None = Field(None, description="S3 key prefix (folder) the outputs live under, e.g. '{scene_id}/'")
    collision_flags: list[dict[str, Any]] = Field(default_factory=list, description="validation_result's violations/camera_collisions flattened into the flat shape /propose-fix expects")


class ValidateUSDJobResponse(BaseModel):
    """Immediate ack returned by POST /validate-usd -- the real work runs in a background thread."""
    status: Literal["queued"] = "queued"
    scene_id: str
    message: str


class ValidateUSDStatusResponse(BaseModel):
    """GET /validate-usd/{scene_id}/status -- polls the job's sidecar file on disk."""
    status: Literal["queued", "running", "done", "failed", "not_found"]
    scene_id: str
    message: str | None = None
    current_frame: int | None = Field(None, description="Last 'captured frame N' seen in the run's log, while running")
    elapsed_seconds: float | None = None
    error: str | None = None
    result: ValidateUSDResponse | None = Field(None, description="Populated only when status == 'done'")


class IngestKitOutputRequest(BaseModel):
    """
    Ingests a pre-existing Omniverse Kit render/capture (produced by running the
    real Kit app directly, outside kit_render_worker.py) into the same
    renders/{scene_id}/result.json shape the rest of the pipeline expects.
    """
    scene_id: str = Field(..., description="Unique scene identifier for the output folder under renders/")
    source_dir: str = Field(..., description="Absolute path on this machine where the Kit output (PNGs and/or video) lives")
    coverage_flags: list[dict[str, Any]] = Field(default_factory=list)
    physics_flags: list[dict[str, Any]] = Field(default_factory=list)
    collision_flags: list[dict[str, Any]] = Field(default_factory=list)


class USDScriptChatRequest(BaseModel):
    prompt: str
    messages: list[ChatMessage] = Field(default_factory=list)
    output_filename: str | None = "agent_generated.usda"
