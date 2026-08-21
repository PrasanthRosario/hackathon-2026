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
    model_preference: Optional[str] = None  # 'auto' | 'haiku' | 'sonnet' | 'opus'


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
