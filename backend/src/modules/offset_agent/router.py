"""
router.py - APIRouter for Offset Agent module.
Scoped cleanly under /offset prefix and root /api aliases.
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import traceback
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from modules.offset_agent import fix_agent
from modules.offset_agent.deep_agent import run_offset_agent
from modules.offset_agent.models import (
    ChatRequest,
    ChatResponse,
    GenerateUSDRequest,
    GenerateUSDResponse,
    IngestKitOutputRequest,
    ProposeFixRequest,
    ProposeFixResponse,
    RenderRequest,
    RenderStatusResponse,
    SceneConfigSchema,
    USDScriptChatRequest,
    ValidateUSDRequest,
    ValidateUSDResponse,
)
from modules.offset_agent.usd_exporter import generate_usd_from_config, generate_usd_from_scene
from modules.offset_agent.usd_script_agent import generate_usd_file_from_prompt

router = APIRouter(tags=["Offset Pre-Viz Agent"])
JsonBody = Annotated[dict[str, Any], Body(...)]

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
VIDEO_EXTS = {".mp4", ".mov", ".webm"}

# scenes/standalone_render_and_validate.py needs Isaac Sim's own Python
# (./python.sh) -- omni.* is not importable from a plain python3/uv venv.
# Override with the ISAAC_SIM_PYTHON env var if it lives somewhere else on
# this box.
ISAAC_SIM_PYTHON = os.environ.get("ISAAC_SIM_PYTHON", os.path.expanduser("~/IsaacSim/python.sh"))
_SCENES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scenes"))
STANDALONE_VALIDATE_SCRIPT = os.path.join(_SCENES_DIR, "standalone_render_and_validate.py")
FRAMES_TO_VIDEO_SCRIPT = os.path.join(_SCENES_DIR, "frames_to_video.py")


def _resolve_renders_dir() -> str:
    """EC2 ubuntu path preferred, repo root fallback. Shared by /render, /render/status, /ingest-kit-output."""
    ubuntu_renders = "/home/ubuntu/renders"
    if os.path.exists(ubuntu_renders) or os.access("/home/ubuntu", os.W_OK):
        return ubuntu_renders
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "renders"))


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
    Handles conversational scene design through the Offset DeepAgent flow.
    """
    try:
        return run_offset_agent(
            messages=request.messages,
            current_scene=request.current_scene,
            current_config=request.current_config,
            model_preference=request.model_preference,
        )
    except Exception as e:  # noqa: BLE001 - API boundary maps agent failures to HTTP 500.
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {e!s}")


@router.post("/generate-usd", response_model=GenerateUSDResponse)
def generate_usd_stage(request: GenerateUSDRequest):
    """Generates an OpenUSD stage file (.usda/.usd) from SceneConfig."""
    try:
        output_filename = request.output_filename or "generated_set.usda"
        if request.scene:
            response = generate_usd_from_scene(
                scene=request.scene,
                output_filename=output_filename,
            )
        else:
            response = generate_usd_from_config(
                scene_config=request.scene_config,
                output_filename=output_filename,
            )

        if os.path.exists(response.usd_path):
            with open(response.usd_path) as file:
                response.usd_content = file.read()
        return response

    except Exception as e:  # noqa: BLE001 - API boundary maps exporter failures to HTTP 500.
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"USD generation failed: {e!s}")


@router.post("/chat-usd-file")
def generate_usd_file_from_chat(request: USDScriptChatRequest):
    """Generate a downloadable USDA file directly from a prompt-authored Python script."""
    try:
        output_filename = request.output_filename or "agent_generated.usda"
        generation = generate_usd_file_from_prompt(
            prompt=request.prompt,
            messages=request.messages,
            output_filename=output_filename,
        )
        return FileResponse(
            generation.path,
            media_type="model/vnd.usda",
            filename=output_filename if output_filename.endswith(".usda") else f"{output_filename}.usda",
            headers={"X-Offset-USD-Source": generation.source},
        )
    except Exception as e:  # noqa: BLE001 - API boundary maps generator failures to HTTP 500.
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"USD script generation failed: {e!s}")


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

    renders_dir = _resolve_renders_dir()
    render_out_dir = os.path.join(renders_dir, scene_id)
    os.makedirs(render_out_dir, exist_ok=True)

    # 2. Save USDA content
    try:
        with open(usd_path, "w") as f:
            f.write(request.usd_content)
    except Exception as e:  # noqa: BLE001 - API boundary reports filesystem write failures.
        raise HTTPException(status_code=500, detail=f"Failed to write stage file to '{usd_path}': {e!s}")

    # 3. Locate kit_render_worker.py script
    worker_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "kit_render_worker.py"))
    if not os.path.exists(worker_script):
        raise HTTPException(status_code=500, detail=f"Render worker script missing at '{worker_script}'")

    cmd = [sys.executable, worker_script, "--usd", usd_path, "--out", render_out_dir]
    log_path = os.path.join(render_out_dir, "render.log")

    # 4. Execute subprocess with 180s timeout
    try:
        res = subprocess.run(cmd, timeout=180, capture_output=True, text=True, check=False)
        
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

    except subprocess.TimeoutExpired:
        with open(log_path, "a") as f_log:
            f_log.write("\n=== TIMEOUT EXPIRED (180s) ===\n")
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
    renders_dir = _resolve_renders_dir()
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


@router.post("/ingest-kit-output")
def ingest_kit_output(request: IngestKitOutputRequest):
    """
    Ingests a pre-existing Omniverse Kit render/capture (e.g. produced by running
    the real Kit app directly on this box, outside kit_render_worker.py) into the
    same renders/{scene_id}/result.json shape the rest of the pipeline expects, so
    it shows up in the Kit Render Result tab exactly like a subprocess-driven render.

    Point source_dir at wherever the capture lives (a folder of PNG frames, an MP4
    from Kit's Movie Capture extension, or both) and this copies/links the files
    into renders/{scene_id}/ and writes a matching result.json.
    """
    source_dir = os.path.abspath(request.source_dir)
    if not os.path.isdir(source_dir):
        raise HTTPException(status_code=400, detail=f"source_dir '{source_dir}' does not exist or is not a directory.")

    render_out_dir = os.path.join(_resolve_renders_dir(), request.scene_id)
    os.makedirs(render_out_dir, exist_ok=True)

    image_files, video_files = [], []
    for entry in sorted(os.listdir(source_dir)):
        src_path = os.path.join(source_dir, entry)
        if not os.path.isfile(src_path):
            continue
        ext = os.path.splitext(entry)[1].lower()
        if ext not in IMAGE_EXTS and ext not in VIDEO_EXTS:
            continue

        dest_path = os.path.join(render_out_dir, entry)
        if os.path.lexists(dest_path):
            os.remove(dest_path)
        try:
            os.symlink(src_path, dest_path)
        except OSError:
            shutil.copy2(src_path, dest_path)

        public_url = f"/renders/{request.scene_id}/{entry}"
        (image_files if ext in IMAGE_EXTS else video_files).append(public_url)

    if not image_files and not video_files:
        raise HTTPException(
            status_code=400,
            detail=f"No image/video files found in '{source_dir}' (looked for {sorted(IMAGE_EXTS | VIDEO_EXTS)}).",
        )

    # If explicit collision_flags weren't passed in the request, look for a
    # validation_result.json sitting alongside the renders -- this is what
    # kit_bridge_extension.py's action_run_validation / standalone_render_and_validate.py
    # write on a real Isaac Sim run: {status, violations: [{frame, corner, prim}],
    # camera_collisions: [{frame, colliding_with}]}. Flatten it into the same
    # flat collision_flags shape the UI and fix_agent already expect, so a real
    # Isaac Sim collision run reaches both the render tab and the fix reasoning
    # in one ingest call, without requiring the operator to hand-copy JSON.
    collision_flags = list(request.collision_flags)
    if not collision_flags:
        validation_path = os.path.join(source_dir, "validation_result.json")
        if os.path.exists(validation_path):
            try:
                with open(validation_path, "r") as f:
                    validation_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                validation_data = {}

            for v in validation_data.get("violations", []):
                collision_flags.append({
                    "type": "frustum_off_set" if v.get("prim") else "frustum_escaped",
                    "frame": v.get("frame"),
                    "corner": v.get("corner"),
                    "prim": v.get("prim"),
                })
            for c in validation_data.get("camera_collisions", []):
                collision_flags.append({
                    "type": "camera_body_collision",
                    "frame": c.get("frame"),
                    "colliding_with": c.get("colliding_with"),
                })

    result_data = {
        "status": "SUCCESS",
        "source": "kit_ingested",
        "source_dir": source_dir,
        "scene_id": request.scene_id,
        "render_files": image_files,
        "video_files": video_files,
        "coverage_flags": request.coverage_flags,
        "physics_flags": request.physics_flags,
        "collision_flags": collision_flags,
    }

    with open(os.path.join(render_out_dir, "result.json"), "w") as f:
        json.dump(result_data, f, indent=2)

    return result_data


@router.post("/validate-usd", response_model=ValidateUSDResponse)
def validate_usd_stage(request: ValidateUSDRequest):
    """
    POST /validate-usd
    Runs scenes/standalone_render_and_validate.py against a .usda file already
    on this machine via Isaac Sim's own Python (real headless SimulationApp,
    not the kit_render_worker.py placeholder path): opens the stage, renders
    the requested frames of --camera through RTX, runs the same PhysX-based
    shot validator the live bridge uses (action_run_validation), stitches the
    resulting rgb_*.png sequence into an MP4 via frames_to_video.py, and
    returns render/video URLs plus the validation result.

    Synchronous -- this blocks for the duration of the Isaac Sim subprocess,
    which can legitimately take minutes (a cold shader cache on first run
    alone costs ~100s; see ARCHITECTURE.md). warmup=20 is enough for
    RayTracedLighting -- only raise it substantially for PathTracing.
    """
    usda_path = os.path.abspath(request.usda_path)
    if not os.path.isfile(usda_path):
        raise HTTPException(status_code=400, detail=f"usda_path '{usda_path}' does not exist.")

    if not os.path.exists(ISAAC_SIM_PYTHON):
        raise HTTPException(
            status_code=500,
            detail=f"Isaac Sim python.sh not found at '{ISAAC_SIM_PYTHON}'. Set the ISAAC_SIM_PYTHON env var if it lives elsewhere on this box.",
        )
    if not os.path.exists(STANDALONE_VALIDATE_SCRIPT):
        raise HTTPException(status_code=500, detail=f"Missing script: '{STANDALONE_VALIDATE_SCRIPT}'")

    scene_id = request.scene_id or f"{os.path.splitext(os.path.basename(usda_path))[0]}_{uuid.uuid4().hex[:8]}"
    out_dir = os.path.join(_resolve_renders_dir(), scene_id)
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, "validate.log")

    cmd = [
        ISAAC_SIM_PYTHON, STANDALONE_VALIDATE_SCRIPT,
        "--usd", usda_path,
        "--out", out_dir,
        "--camera", request.camera,
        "--frames", request.frames,
        "--warmup", str(request.warmup),
        "--renderer", request.renderer,
    ]
    try:
        res = subprocess.run(cmd, timeout=900, capture_output=True, text=True, check=False)
        with open(log_path, "w") as f_log:
            f_log.write(f"=== STDOUT ===\n{res.stdout}\n\n=== STDERR ===\n{res.stderr}\n")
        if res.returncode != 0:
            stderr_detail = res.stderr.strip() or res.stdout.strip() or "Unknown worker failure"
            raise HTTPException(status_code=500, detail=f"standalone_render_and_validate.py failed (exit {res.returncode}):\n{stderr_detail}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail=f"standalone_render_and_validate.py timed out after 900s for '{usda_path}'. See '{log_path}'.")

    validation_json_path = os.path.join(out_dir, "validation_result.json")
    if not os.path.exists(validation_json_path):
        raise HTTPException(status_code=500, detail=f"Run completed with exit 0 but '{validation_json_path}' was not written. See '{log_path}'.")
    with open(validation_json_path, "r") as f:
        validation_result = json.load(f)

    frame_files = sorted(glob.glob(os.path.join(out_dir, "rgb_*.png")))
    if not frame_files:
        raise HTTPException(status_code=500, detail=f"No rendered frames found in '{out_dir}' after a successful run. See '{log_path}'.")

    video_path = os.path.join(out_dir, f"{scene_id}.mp4")
    video_cmd = [
        sys.executable, FRAMES_TO_VIDEO_SCRIPT,
        "--frames_dir", out_dir,
        "--fps", str(request.fps),
        "--out", video_path,
    ]
    video_res = subprocess.run(video_cmd, timeout=120, capture_output=True, text=True, check=False)
    if video_res.returncode != 0 or not os.path.exists(video_path):
        stderr_detail = video_res.stderr.strip() or video_res.stdout.strip() or "Unknown ffmpeg failure"
        raise HTTPException(status_code=500, detail=f"frames_to_video.py failed (exit {video_res.returncode}):\n{stderr_detail}")

    return ValidateUSDResponse(
        status="SUCCESS",
        scene_id=scene_id,
        usda_path=usda_path,
        render_files=[f"/renders/{scene_id}/{os.path.basename(p)}" for p in frame_files],
        video_file=f"/renders/{scene_id}/{os.path.basename(video_path)}",
        frame_count=len(frame_files),
        validation_result=validation_result,
    )


# ---------------------------------------------------------------------------
# STUBBED ENDPOINTS (Scoped under /offset)
# ---------------------------------------------------------------------------

@router.post("/parse-shot-list")
def stub_parse_shot_list(payload: JsonBody):
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


@router.post("/propose-fix", response_model=ProposeFixResponse)
def propose_fix(request: ProposeFixRequest):
    """
    Fix-proposer loop (Component F).
    Takes {scene_config, coverage_flags, physics_flags} evidence from a Kit render
    (see POST /render), asks fix_agent to propose fixes from the fixed set of fix
    types, and mutates scene_config via fix_agent.apply_fix for each proposed fix.
    The caller is expected to re-submit the returned updated_scene_config to
    /generate-usd -> /render to verify the fix actually resolved the flags.
    """
    evidence = {
        "shot_id": request.shot_id,
        "scene_config": request.scene_config.model_dump(),
        "coverage_flags": request.coverage_flags,
        "physics_flags": request.physics_flags,
        "collision_flags": request.collision_flags,
    }

    try:
        result = fix_agent.propose_fixes(evidence)
    except Exception as e:  # noqa: BLE001 - API boundary maps model/provider failures.
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Fix proposal failed: {e!s}")

    fixes = result.get("fixes", []) if isinstance(result, dict) else []

    updated_config = request.scene_config.model_dump()
    for fix in fixes:
        updated_config = fix_agent.apply_fix(updated_config, fix)

    return ProposeFixResponse(
        status="SUCCESS",
        summary=result.get("summary") if isinstance(result, dict) else None,
        fixes=fixes,
        updated_scene_config=updated_config,
        model_used="anthropic/claude-sonnet-4-6",
    )
