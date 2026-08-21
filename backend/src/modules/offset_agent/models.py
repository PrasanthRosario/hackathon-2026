"""
models.py - Pydantic data schemas for Offset pre-visualization tool.
Scoped within offset_agent module.
"""

from typing import List, Optional, Tuple, Dict, Any
from pydantic import BaseModel, Field


class WallSchema(BaseModel):
    id: str = Field(..., description="Unique identifier for the wall (e.g., 'wall_north')")
    position: Tuple[float, float, float] = Field(
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
    start_position: Tuple[float, float, float] = Field(
        ..., description="Camera starting world coordinate [x, y, z]"
    )
    end_position: Tuple[float, float, float] = Field(
        ..., description="Camera ending world coordinate [x, y, z]"
    )
    duration_seconds: float = Field(5.0, description="Duration of dolly move in seconds")


class SceneConfigSchema(BaseModel):
    walls: List[WallSchema] = Field(default_factory=list)
    floor: FloorSchema = Field(default_factory=FloorSchema)
    shots: List[ShotSchema] = Field(default_factory=list)


class ChatMessage(BaseModel):
    role: str  # 'user' | 'assistant' | 'system'
    content: str
    model_used: Optional[str] = None


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    current_config: Optional[SceneConfigSchema] = None
    model_preference: Optional[str] = None


class ChatResponse(BaseModel):
    message: str
    model_used: str
    ready_for_confirmation: bool = False
    scene_config: Optional[SceneConfigSchema] = None
    readable_summary: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list)


class GenerateUSDRequest(BaseModel):
    scene_config: SceneConfigSchema
    output_filename: Optional[str] = "generated_set.usda"


class GenerateUSDResponse(BaseModel):
    status: str
    usd_path: str
    prim_count: int
    message: str
    usd_content: Optional[str] = None


class RenderRequest(BaseModel):
    usd_content: str = Field(..., description="USDA raw text string content")
    scene_id: str = Field(..., description="Unique scene identifier")


class RenderStatusResponse(BaseModel):
    status: str  # "pending" | "done" | "failed"
    scene_id: str
    message: Optional[str] = None


class ProposeFixRequest(BaseModel):
    scene_config: SceneConfigSchema
    coverage_flags: List[Dict[str, Any]] = Field(default_factory=list)
    physics_flags: List[Dict[str, Any]] = Field(default_factory=list)
    collision_flags: List[Dict[str, Any]] = Field(default_factory=list)
    shot_id: Optional[str] = None


class ProposeFixResponse(BaseModel):
    status: str
    summary: Optional[str] = Field(None, description="Director-friendly paragraph explaining the issues and the reasoning behind the proposed fixes.")
    fixes: List[Dict[str, Any]] = Field(default_factory=list)
    updated_scene_config: SceneConfigSchema
    model_used: str


class ValidateUSDRequest(BaseModel):
    """
    Runs a real headless Isaac Sim pass (scenes/standalone_render_and_validate.py)
    against an arbitrary .usda file already sitting on this machine.
    """
    usda_path: str = Field(..., description="Absolute path on this machine to the .usda/.usd file to render + validate")
    scene_id: Optional[str] = Field(None, description="Identifier for the output folder under renders/; auto-generated from the filename if omitted")
    camera: str = Field("/World/MainCamera", description="Camera prim path to render/validate through")
    frames: str = Field("all", description="'all' for every frame in the stage's time range, a comma list like '0,36,72', or '' for start+end only")
    fps: float = Field(24.0, description="Playback frame rate for the stitched video")
    renderer: str = Field("RayTracedLighting", description="RayTracedLighting (fast) or PathTracing (slower, needs a higher warmup)")
    warmup: int = Field(20, description="App update ticks before each capture. RayTracedLighting converges quickly (~20 is plenty); raise substantially (e.g. 150) only for PathTracing")


class ValidateUSDResponse(BaseModel):
    status: str
    scene_id: str
    usda_path: str
    render_files: List[str] = Field(default_factory=list, description="Public /renders/{scene_id}/... URLs for each captured frame")
    video_file: Optional[str] = Field(None, description="Public /renders/{scene_id}/... URL for the stitched MP4")
    frame_count: int = 0
    validation_result: Dict[str, Any] = Field(default_factory=dict, description="Contents of validation_result.json: {status, violations, camera_collisions}")


class IngestKitOutputRequest(BaseModel):
    """
    Ingests a pre-existing Omniverse Kit render/capture (produced by running the
    real Kit app directly, outside kit_render_worker.py) into the same
    renders/{scene_id}/result.json shape the rest of the pipeline expects.
    """
    scene_id: str = Field(..., description="Unique scene identifier for the output folder under renders/")
    source_dir: str = Field(..., description="Absolute path on this machine where the Kit output (PNGs and/or video) lives")
    coverage_flags: List[Dict[str, Any]] = Field(default_factory=list)
    physics_flags: List[Dict[str, Any]] = Field(default_factory=list)
    collision_flags: List[Dict[str, Any]] = Field(default_factory=list)
