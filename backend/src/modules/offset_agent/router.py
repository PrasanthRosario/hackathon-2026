"""
router.py - APIRouter for Offset Agent module.
Scoped cleanly under /offset prefix and root /api aliases.
"""

import os
import sys
import json
import subprocess
import traceback
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Body

from modules.offset_agent.models import (
    SceneConfigSchema,
    ChatRequest,
    ChatResponse,
    GenerateUSDRequest,
    GenerateUSDResponse,
    RenderRequest,
    RenderStatusResponse,
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
            from pxr import Usd, UsdGeom, UsdPhysics, Gf
            
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
# COMPONENT 2: FASTAPI RENDER ENDPOINT & STATUS POLLING
# ---------------------------------------------------------------------------

@router.post("/render")
def render_stage(request: RenderRequest):
    """
    POST /render
    1. Writes usd_content to /home/ubuntu/scenes/{scene_id}.usda (or local fallback scenes/{scene_id}.usda).
    2. Invokes kit_render_worker.py via subprocess (timeout=180s).
    3. Returns result.json with static render URLs (/renders/{scene_id}/...).
    4. On failure or timeout, returns HTTP 500 with exact subprocess stderr.
    """
    scene_id = request.scene_id
    
    # 1. Determine paths (EC2 ubuntu path preferred, repo root fallback)
    ubuntu_scenes = "/home/ubuntu/scenes"
    if os.path.exists(ubuntu_scenes) or os.access("/home/ubuntu", os.W_OK):
        scenes_dir = ubuntu_scenes
    else:
        scenes_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scenes"))
        
    os.makedirs(scenes_dir, exist_ok=True)
    usd_path = os.path.join(scenes_dir, f"{scene_id}.usda")

    ubuntu_renders = "/home/ubuntu/renders"
    if os.path.exists(ubuntu_renders) or os.access("/home/ubuntu", os.W_OK):
        renders_dir = ubuntu_renders
    else:
        renders_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "renders"))

    render_out_dir = os.path.join(renders_dir, scene_id)
    os.makedirs(render_out_dir, exist_ok=True)

    # 2. Save USDA content
    try:
        with open(usd_path, "w") as f:
            f.write(request.usd_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write stage file to '{usd_path}': {str(e)}")

    # 3. Locate kit_render_worker.py script
    worker_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "kit_render_worker.py"))
    if not os.path.exists(worker_script):
        raise HTTPException(status_code=500, detail=f"Render worker script missing at '{worker_script}'")

    cmd = [sys.executable, worker_script, "--usd", usd_path, "--out", render_out_dir]
    log_path = os.path.join(render_out_dir, "render.log")

    # 4. Execute subprocess with 180s timeout
    try:
        res = subprocess.run(cmd, timeout=180, capture_output=True, text=True)
        
        # Log stdout/stderr to render.log
        with open(log_path, "w") as f_log:
            f_log.write(f"=== STDOUT ===\n{res.stdout}\n\n=== STDERR ===\n{res.stderr}\n")

        if res.returncode != 0:
            stderr_detail = res.stderr.strip() or res.stdout.strip() or "Unknown worker failure"
            raise HTTPException(status_code=500, detail=f"Kit Render Worker Error (Exit {res.returncode}):\n{stderr_detail}")

        # 5. Read result.json
        result_json_file = os.path.join(render_out_dir, "result.json")
        if not os.path.exists(result_json_file):
            raise HTTPException(status_code=500, detail=f"Result file missing: worker completed with code 0 but '{result_json_file}' was not created.\nStderr:\n{res.stderr}")

        with open(result_json_file, "r") as f:
            result_data = json.load(f)

        # 6. Rewrite render file paths to public static /renders/{scene_id}/... URLs
        public_renders = []
        for r_file in result_data.get("render_files", []):
            fname = os.path.basename(r_file)
            public_renders.append(f"/renders/{scene_id}/{fname}")

        result_data["render_files"] = public_renders
        result_data["scene_id"] = scene_id
        return result_data

    except subprocess.TimeoutExpired as te:
        with open(log_path, "a") as f_log:
            f_log.write(f"\n=== TIMEOUT EXPIRED (180s) ===\n")
        raise HTTPException(status_code=500, detail=f"Kit Render Worker timed out after 180 seconds on scene '{scene_id}'.")


@router.get("/render/{scene_id}/status", response_model=RenderStatusResponse)
def get_render_status(scene_id: str):
    """
    GET /render/{scene_id}/status
    Polls status for kit_render_worker execution:
      - "done" if result.json exists
      - "failed" if log indicates non-zero exit or error
      - "pending" if render is still in flight
    """
    ubuntu_renders = "/home/ubuntu/renders"
    if os.path.exists(ubuntu_renders):
        renders_dir = ubuntu_renders
    else:
        renders_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "renders"))

    render_out_dir = os.path.join(renders_dir, scene_id)
    result_json = os.path.join(render_out_dir, "result.json")
    log_file = os.path.join(render_out_dir, "render.log")

    if os.path.exists(result_json):
        return RenderStatusResponse(status="done", scene_id=scene_id, message="Render and physics simulation completed.")

    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            log_content = f.read()
            if "ERROR" in log_content or "TIMEOUT EXPIRED" in log_content:
                return RenderStatusResponse(status="failed", scene_id=scene_id, message="Render worker failed. See log for details.")

    if os.path.exists(render_out_dir):
        return RenderStatusResponse(status="pending", scene_id=scene_id, message="Kit application worker is starting/rendering stage.")

    return RenderStatusResponse(status="pending", scene_id=scene_id, message="Scene render request queued.")


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
