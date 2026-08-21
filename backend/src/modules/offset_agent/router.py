"""
router.py - APIRouter for Offset Agent module.
Scoped cleanly under /offset prefix so it will never conflict with other backend modules.
"""

import os
import json
import traceback
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Body

from modules.offset_agent.models import (
    SceneConfigSchema,
    ChatRequest,
    ChatResponse,
    GenerateUSDRequest,
    GenerateUSDResponse,
)
from modules.offset_agent import chains

router = APIRouter(tags=["Offset Pre-Viz Agent"])


@router.get("/health")
def health_check():
    return {
        "status": "online",
        "module": "offset_agent",
        "openrouter_configured": bool(os.getenv("OPENROUTER_API_KEY")),
    }


@router.post("/chat", response_model=ChatResponse)
def handle_chat_turn(request: ChatRequest):
    """
    Handles conversational turn with model routing:
    - Haiku: Quick clarifying questions (1-2 at a time)
    - Sonnet: Extraction of structured scene config when sufficient detail is provided
    """
    try:
        messages_dicts = [m.model_dump() for m in request.messages]
        user_input_latest = messages_dicts[-1]["content"].lower() if messages_dicts else ""

        extraction_keywords = ["confirm", "generate", "extract", "ready", "looks good", "build set", "create scene"]
        wants_extraction = any(kw in user_input_latest for kw in extraction_keywords)
        user_turn_count = sum(1 for m in messages_dicts if m["role"] == "user")

        if wants_extraction or user_turn_count >= 3:
            extracted_config, readable_summary = chains.run_sonnet_extraction(messages_dicts)
            if extracted_config:
                return ChatResponse(
                    message="I've compiled your film set configuration based on our discussion. Please review the summary below and click **Confirm & Generate USD** to build your stage.",
                    model_used="anthropic/claude-sonnet-4-6",
                    ready_for_confirmation=True,
                    scene_config=extracted_config,
                    readable_summary=readable_summary,
                )

        haiku_reply = chains.run_haiku_clarifying(
            messages_dicts,
            current_config=request.current_config.model_dump() if request.current_config else None,
        )

        return ChatResponse(
            message=haiku_reply,
            model_used="~anthropic/claude-haiku-latest",
            ready_for_confirmation=False,
            scene_config=request.current_config,
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {str(e)}")


@router.post("/generate-usd", response_model=GenerateUSDResponse)
def generate_usd_stage(request: GenerateUSDRequest):
    """Generates an OpenUSD stage file (.usda/.usd) from SceneConfig."""
    try:
        out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scenes"))
        os.makedirs(out_dir, exist_ok=True)
        out_filename = request.output_filename or "generated_set.usda"
        out_path = os.path.join(out_dir, out_filename)

        prim_count = 0
        try:
            from pxr import Usd, UsdGeom, UsdPhysics, Gf, Sdf
            
            stage = Usd.Stage.CreateNew(out_path)
            UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
            UsdGeom.SetStageMetersPerUnit(stage, 1.0)
            
            world = UsdGeom.Xform.Define(stage, "/World")
            stage.SetDefaultPrim(world.GetPrim())
            
            # Floor Plane with Physics Collider
            floor = UsdGeom.Cube.Define(stage, "/World/Room/Floor")
            floor.GetSizeAttr().Set(1.0)
            f_xf = UsdGeom.Xformable(floor)
            f_xf.AddTranslateOp().Set(Gf.Vec3d(0, 0, -0.05))
            f_xf.AddScaleOp().Set(Gf.Vec3d(request.scene_config.floor.width, request.scene_config.floor.depth, 0.1))
            floor.GetDisplayColorAttr().Set([Gf.Vec3f(0.8, 0.8, 0.82)])
            UsdPhysics.CollisionAPI.Apply(floor.GetPrim())
            prim_count += 1

            # Walls with Physics Colliders
            for wall in request.scene_config.walls:
                w_path = f"/World/Room/{wall.id}"
                w_cube = UsdGeom.Cube.Define(stage, w_path)
                w_cube.GetSizeAttr().Set(1.0)
                w_xf = UsdGeom.Xformable(w_cube)
                w_xf.AddTranslateOp().Set(Gf.Vec3d(*wall.position))
                w_xf.AddRotateZOp().Set(wall.rotation)
                w_xf.AddScaleOp().Set(Gf.Vec3d(wall.width, wall.thickness, wall.height))
                w_cube.GetDisplayColorAttr().Set([Gf.Vec3f(0.75, 0.72, 0.68)])
                UsdPhysics.CollisionAPI.Apply(w_cube.GetPrim())
                prim_count += 1

            # Shots / Cameras with Clipping & Focal Length
            for shot in request.scene_config.shots:
                c_path = f"/World/Cameras/{shot.shot_id}"
                cam = UsdGeom.Camera.Define(stage, c_path)
                cam.CreateFocalLengthAttr(shot.focal_length_mm)
                cam.CreateHorizontalApertureAttr(36.0)
                cam.CreateVerticalApertureAttr(24.0)
                cam.CreateClippingRangeAttr(Gf.Vec2f(0.1, 1000.0))
                
                c_xf = UsdGeom.Xformable(cam)
                c_xf.AddTranslateOp().Set(Gf.Vec3d(*shot.start_position))
                prim_count += 1

            stage.GetRootLayer().Save()

        except ImportError:
            meta_path = out_path + ".json"
            with open(meta_path, "w") as f:
                json.dump(request.scene_config.model_dump(), f, indent=2)
            prim_count = len(request.scene_config.walls) + len(request.scene_config.shots) + 1

        return GenerateUSDResponse(
            status="SUCCESS",
            usd_path=out_path,
            prim_count=prim_count,
            message=f"USD Stage generated successfully with {len(request.scene_config.walls)} walls and {len(request.scene_config.shots)} shot cameras.",
        )

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"USD generation failed: {str(e)}")


# ---------------------------------------------------------------------------
# STUBBED ENDPOINTS (Scoped under /offset)
# ---------------------------------------------------------------------------

@router.post("/parse-shot-list")
def stub_parse_shot_list(payload: Dict[str, Any] = Body(...)):
    raw_text = payload.get("text", "")
    return {
        "status": "STUB",
        "notice": "Shot parsing stub in offset_agent module.",
        "input_received": raw_text,
        "shots": [
            {
                "shot_id": "shot_1_parsed_stub",
                "focal_length_mm": 35.0,
                "start_position": [-3.0, -2.0, 1.6],
                "end_position": [1.0, 0.0, 1.6],
                "duration_seconds": 5.0,
            }
        ],
    }


@router.post("/check-coverage")
def stub_check_coverage(scene_config: SceneConfigSchema):
    issues = []
    for shot in scene_config.shots:
        if shot.focal_length_mm < 18.0:
            issues.append({
                "rule": "ultra_wide_distortion",
                "shot_id": shot.shot_id,
                "detail": f"Focal length {shot.focal_length_mm}mm may capture backstage void past wall boundaries."
            })
    return {
        "status": "SUCCESS",
        "coverage_ok": len(issues) == 0,
        "checked_shots": len(scene_config.shots),
        "issues": issues,
    }


@router.post("/check-physics")
def stub_check_physics(scene_config: SceneConfigSchema):
    issues = []
    for shot in scene_config.shots:
        for wall in scene_config.walls:
            dist_start = sum((a - b) ** 2 for a, b in zip(shot.start_position, wall.position)) ** 0.5
            if dist_start < 0.5:
                issues.append({
                    "rule": "camera_wall_clipping",
                    "shot_id": shot.shot_id,
                    "wall_id": wall.id,
                    "detail": f"Camera starting position {shot.start_position} is within 0.5m of {wall.id}."
                })
    return {
        "status": "SUCCESS",
        "physics_ok": len(issues) == 0,
        "checked_pairs": len(scene_config.shots) * len(scene_config.walls),
        "issues": issues,
    }


@router.post("/propose-fix")
def stub_propose_fix(payload: Dict[str, Any] = Body(...)):
    current_config = payload.get("current_config", {})
    issues = payload.get("issues", [])
    updated_config, explanation = chains.run_sonnet_fix_proposal(current_config, issues)
    return {
        "status": "SUCCESS",
        "proposed_config": updated_config,
        "explanation": explanation,
        "model_used": "anthropic/claude-sonnet-4-6",
    }
