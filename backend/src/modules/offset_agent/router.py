"""
router.py - APIRouter for Offset Agent module.
Scoped cleanly under /offset prefix and root /api aliases.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from typing import Annotated, Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from modules.offset_agent import fix_agent, usd_fix_agent
from modules.offset_agent.deep_agent import run_offset_agent
from modules.offset_agent.models import (
    ChatRequest,
    ChatResponse,
    GenerateUSDRequest,
    GenerateUSDResponse,
    IngestKitOutputRequest,
    ListUsdCamerasRequest,
    ListUsdCamerasResponse,
    ProposeFixRequest,
    ProposeFixResponse,
    RenderRequest,
    RenderStatusResponse,
    SceneConfigSchema,
    USDScriptChatRequest,
    UsdCameraInfo,
    UsdFixRequest,
    UsdFixResponse,
    ValidateUSDJobResponse,
    ValidateUSDRequest,
    ValidateUSDResponse,
    ValidateUSDStatusResponse,
)
from modules.offset_agent.usd_exporter import generate_usd_from_config, generate_usd_from_scene
from modules.offset_agent.usd_script_agent import USDScriptError, generate_usd_file_from_prompt

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

# Where /validate-usd uploads its render output. Credentials come from the
# EC2 instance role (no keys needed) -- region is explicit because this box
# has no ~/.aws/config or AWS_REGION env var set.
S3_RENDERS_BUCKET = os.environ.get("S3_RENDERS_BUCKET", "s3-offframe-renders")
AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))


def _upload_dir_to_s3_and_clear(local_dir: str, bucket: str, prefix: str, url_expiry_seconds: int = 86400) -> dict[str, str]:
    """
    Uploads every file directly inside local_dir to s3://bucket/prefix/<filename>,
    and ONLY on full success deletes local_dir -- if any upload fails, nothing
    local is removed, so a bucket/permissions problem never loses render output.
    Returns {filename: presigned_get_url}.

    Raises plain RuntimeError (not HTTPException) -- this runs inside the
    /validate-usd background thread, not a request handler, so there's no
    response to raise an HTTPException into.
    """
    s3 = boto3.client("s3", region_name=AWS_REGION)
    filenames = [f for f in os.listdir(local_dir) if os.path.isfile(os.path.join(local_dir, f))]

    urls: dict[str, str] = {}
    try:
        for filename in filenames:
            key = f"{prefix}{filename}"
            s3.upload_file(os.path.join(local_dir, filename), bucket, key)
            urls[filename] = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=url_expiry_seconds,
            )
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"S3 upload to 's3://{bucket}/{prefix}' failed: {e!s}")

    shutil.rmtree(local_dir)
    return urls


def _resolve_renders_dir() -> str:
    """EC2 ubuntu path preferred, repo root fallback. Shared by /render, /render/status, /ingest-kit-output."""
    ubuntu_renders = "/home/ubuntu/renders"
    if os.path.exists(ubuntu_renders) or os.access("/home/ubuntu", os.W_OK):
        return ubuntu_renders
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "renders"))


def _violations_to_collision_flags(validation_result: dict) -> list[dict]:
    """
    Flattens standalone_render_and_validate.py's validation_result.json shape
    ({status, violations: [{frame, corner, prim}], camera_collisions: [{frame, colliding_with}]})
    into the flat collision_flags shape fix_agent.py / /propose-fix / the UI
    already expect: {type, frame, corner?, prim?, colliding_with?}.
    """
    collision_flags: list[dict] = []
    for v in validation_result.get("violations", []):
        collision_flags.append({
            "type": "frustum_off_set" if v.get("prim") else "frustum_escaped",
            "frame": v.get("frame"),
            "corner": v.get("corner"),
            "prim": v.get("prim"),
        })
    for c in validation_result.get("camera_collisions", []):
        collision_flags.append({
            "type": "camera_body_collision",
            "frame": c.get("frame"),
            "colliding_with": c.get("colliding_with"),
        })
    return collision_flags


def _validate_jobs_dir() -> str:
    d = os.path.join(_resolve_renders_dir(), "_validate_jobs")
    os.makedirs(d, exist_ok=True)
    return d


def _write_job_status(scene_id: str, data: dict) -> None:
    """Atomic write (tmp file + os.replace) so a concurrent GET status never reads a torn file."""
    path = os.path.join(_validate_jobs_dir(), f"{scene_id}.json")
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def _read_job_status(scene_id: str) -> dict | None:
    path = os.path.join(_validate_jobs_dir(), f"{scene_id}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _tail_file(path: str, n: int = 40) -> str:
    try:
        with open(path, "r") as f:
            return "".join(f.readlines()[-n:])
    except OSError:
        return ""


def _run_validate_job(
    usda_path: str, scene_id: str, out_dir: str,
    camera: str, frames: str, fps: float, renderer: str, warmup: int,
) -> None:
    """
    The actual Isaac Sim render+validate+stitch+S3-upload pipeline, run in a
    background thread by POST /validate-usd. Never raises -- every failure
    path is captured into the job's sidecar status file (via _fail below)
    since there's no HTTP request left to raise an HTTPException into.
    """
    log_path = os.path.join(out_dir, "validate.log")
    started_at = time.time()

    def _fail(error: str, log_tail: str = "") -> None:
        _write_job_status(scene_id, {
            "status": "failed",
            "scene_id": scene_id,
            "error": error,
            "log_tail": log_tail,
            "started_at": started_at,
            "finished_at": time.time(),
        })

    _write_job_status(scene_id, {
        "status": "running",
        "scene_id": scene_id,
        "usda_path": usda_path,
        "started_at": started_at,
    })

    cmd = [
        ISAAC_SIM_PYTHON, STANDALONE_VALIDATE_SCRIPT,
        "--usd", usda_path,
        "--out", out_dir,
        "--camera", camera,
        "--frames", frames,
        "--warmup", str(warmup),
        "--renderer", renderer,
    ]

    # Popen + a real (unbuffered) file handle, not subprocess.run(capture_output=True),
    # so validate.log fills in live as Isaac Sim prints "captured frame N" -- this is
    # what lets GET .../status report progress while the job is still running.
    # PYTHONUNBUFFERED=1 is required because the script's own print() calls would
    # otherwise sit in Python's block-buffered stdout until the process exits.
    try:
        with open(log_path, "w") as log_file:
            proc = subprocess.Popen(
                cmd, stdout=log_file, stderr=subprocess.STDOUT, text=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            try:
                returncode = proc.wait(timeout=900)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                _fail(f"standalone_render_and_validate.py timed out after 900s for '{usda_path}'.", _tail_file(log_path))
                return
    except OSError as e:
        _fail(f"Failed to launch standalone_render_and_validate.py: {e!s}")
        return

    if returncode != 0:
        _fail(f"standalone_render_and_validate.py failed (exit {returncode}).", _tail_file(log_path))
        return

    validation_json_path = os.path.join(out_dir, "validation_result.json")
    if not os.path.exists(validation_json_path):
        _fail(f"Run completed with exit 0 but '{validation_json_path}' was not written.", _tail_file(log_path))
        return
    with open(validation_json_path, "r") as f:
        validation_result = json.load(f)

    frame_files = sorted(glob.glob(os.path.join(out_dir, "rgb_*.png")))
    if not frame_files:
        _fail(f"No rendered frames found in '{out_dir}' after a successful run.", _tail_file(log_path))
        return

    video_path = os.path.join(out_dir, f"{scene_id}.mp4")
    video_cmd = [
        sys.executable, FRAMES_TO_VIDEO_SCRIPT,
        "--frames_dir", out_dir,
        "--fps", str(fps),
        "--out", video_path,
    ]
    video_res = subprocess.run(video_cmd, timeout=120, capture_output=True, text=True, check=False)
    if video_res.returncode != 0 or not os.path.exists(video_path):
        stderr_detail = video_res.stderr.strip() or video_res.stdout.strip() or "Unknown ffmpeg failure"
        _fail(f"frames_to_video.py failed (exit {video_res.returncode}): {stderr_detail}")
        return

    frame_count = len(frame_files)
    video_filename = os.path.basename(video_path)
    collision_flags = _violations_to_collision_flags(validation_result)
    s3_prefix = f"{scene_id}/"

    try:
        presigned_urls = _upload_dir_to_s3_and_clear(out_dir, S3_RENDERS_BUCKET, s3_prefix)
    except RuntimeError as e:
        # out_dir is left intact on failure (rmtree only runs on full success),
        # so nothing local is lost even though the job is marked failed.
        _fail(str(e))
        return

    _write_job_status(scene_id, {
        "status": "done",
        "scene_id": scene_id,
        "usda_path": usda_path,
        "render_files": [presigned_urls[os.path.basename(p)] for p in frame_files],
        "video_file": presigned_urls.get(video_filename),
        "frame_count": frame_count,
        "validation_result": validation_result,
        "collision_flags": collision_flags,
        "s3_bucket": S3_RENDERS_BUCKET,
        "s3_prefix": s3_prefix,
        "started_at": started_at,
        "finished_at": time.time(),
    })


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
            headers={
                "X-Offset-USD-Source": generation.source,
                # Exposes the server-side path so the frontend can point
                # /validate-usd and /list-usd-cameras at this exact file
                # (previously only the downloadable blob was returned, with no
                # way for the caller to reference it server-side afterward).
                "X-Offset-USD-Path": generation.path,
            },
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
    # write on a real Isaac Sim run. Flatten it into the same flat collision_flags
    # shape the UI and fix_agent already expect, so a real Isaac Sim collision run
    # reaches both the render tab and the fix reasoning in one ingest call, without
    # requiring the operator to hand-copy JSON.
    collision_flags = list(request.collision_flags)
    if not collision_flags:
        validation_path = os.path.join(source_dir, "validation_result.json")
        if os.path.exists(validation_path):
            try:
                with open(validation_path, "r") as f:
                    validation_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                validation_data = {}
            collision_flags = _violations_to_collision_flags(validation_data)

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


@router.post("/list-usd-cameras", response_model=ListUsdCamerasResponse)
def list_usd_cameras(request: ListUsdCamerasRequest):
    """
    POST /list-usd-cameras
    Opens a .usda/.usd file with plain pxr.Usd (no Isaac Sim/Kit needed -- this
    is pure USD introspection, not a render) and returns every Camera prim it
    actually contains. Some USD files have no camera at all -- e.g. an
    externally-authored stage, or one built by a path that skipped adding
    one -- so the UI should not assume "/World/MainCamera" exists; this is
    what lets the Validate & Simulate camera picker reflect the real file
    instead of guessing from the (possibly stale/unrelated) in-memory scene.
    """
    usda_path = os.path.abspath(request.usda_path)
    if not os.path.isfile(usda_path):
        raise HTTPException(status_code=400, detail=f"usda_path '{usda_path}' does not exist.")

    try:
        from pxr import Usd, UsdGeom
    except ImportError:
        raise HTTPException(status_code=500, detail="pxr (usd-core) is not installed on this backend.")

    try:
        stage = Usd.Stage.Open(usda_path)
    except Exception as e:  # noqa: BLE001 - API boundary maps any pxr parse failure to HTTP 400.
        raise HTTPException(status_code=400, detail=f"Failed to open USD stage '{usda_path}': {e!s}")
    if stage is None:
        raise HTTPException(status_code=400, detail=f"Failed to open USD stage '{usda_path}' (Usd.Stage.Open returned None).")

    cameras = [
        UsdCameraInfo(path=str(prim.GetPath()), name=prim.GetName())
        for prim in stage.Traverse()
        if prim.IsA(UsdGeom.Camera)
    ]

    return ListUsdCamerasResponse(usda_path=usda_path, cameras=cameras)


@router.post("/validate-usd", response_model=ValidateUSDJobResponse)
def validate_usd_stage(request: ValidateUSDRequest):
    """
    POST /validate-usd
    Kicks off scenes/standalone_render_and_validate.py against a .usda file
    already on this machine, in a background thread, and returns immediately.

    This is a REAL headless Isaac Sim run (RTX render through --camera + the
    same PhysX-based shot validator the live bridge uses), which can
    legitimately take minutes (a cold shader cache on first run alone costs
    ~100s; see ARCHITECTURE.md) -- far too long to hold an HTTP request open.
    Poll GET /validate-usd/{scene_id}/status for progress and the final result.

    Deliberately a plain daemon thread, not FastAPI's BackgroundTasks: those
    share the same request threadpool, and a 15-20 minute job would starve
    every other synchronous endpoint on this server. This repo has no task
    queue (Celery/RQ) and doesn't need one yet -- a thread plus a filesystem
    sidecar (see _run_validate_job / _write_job_status) is the minimal
    increment consistent with the rest of this router's "no DB, just files"
    convention (mirrors /render + /render/{scene_id}/status).
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

    _write_job_status(scene_id, {
        "status": "queued",
        "scene_id": scene_id,
        "usda_path": usda_path,
        "started_at": time.time(),
    })

    threading.Thread(
        target=_run_validate_job,
        args=(usda_path, scene_id, out_dir, request.camera, request.frames, request.fps, request.renderer, request.warmup),
        daemon=True,
    ).start()

    return ValidateUSDJobResponse(
        scene_id=scene_id,
        message=f"Validation job started; poll GET /validate-usd/{scene_id}/status for progress.",
    )


@router.get("/validate-usd/{scene_id}/status", response_model=ValidateUSDStatusResponse)
def get_validate_usd_status(scene_id: str):
    """
    GET /validate-usd/{scene_id}/status
    Polls the job's sidecar file under renders/_validate_jobs/{scene_id}.json --
    kept separate from renders/{scene_id}/ because that directory is deleted
    once the run's output is uploaded to S3, so it can't be the "done" source
    of truth the way /render/{scene_id}/status uses renders/{scene_id}/result.json.
    """
    job = _read_job_status(scene_id)
    if job is None:
        return ValidateUSDStatusResponse(status="not_found", scene_id=scene_id, message="No validate-usd job found for this scene_id.")

    status = job.get("status", "not_found")
    started_at = job.get("started_at")
    elapsed_seconds = (time.time() - started_at) if started_at else None

    if status == "done":
        return ValidateUSDStatusResponse(
            status="done",
            scene_id=scene_id,
            elapsed_seconds=elapsed_seconds,
            result=ValidateUSDResponse(
                status="SUCCESS",
                scene_id=scene_id,
                usda_path=job.get("usda_path", ""),
                render_files=job.get("render_files", []),
                video_file=job.get("video_file"),
                frame_count=job.get("frame_count", 0),
                validation_result=job.get("validation_result", {}),
                s3_bucket=job.get("s3_bucket"),
                s3_prefix=job.get("s3_prefix"),
                collision_flags=job.get("collision_flags", []),
            ),
        )

    if status == "failed":
        return ValidateUSDStatusResponse(
            status="failed",
            scene_id=scene_id,
            elapsed_seconds=elapsed_seconds,
            error=job.get("error"),
            message=job.get("log_tail"),
        )

    # queued / running -- surface the last "captured frame N" line seen so far.
    # validate.log fills in live (see _run_validate_job's Popen + PYTHONUNBUFFERED),
    # so this reflects real progress, not just a stale post-completion dump.
    current_frame = None
    log_path = os.path.join(_resolve_renders_dir(), scene_id, "validate.log")
    if os.path.exists(log_path):
        matches = re.findall(r"captured frame (\d+)", _tail_file(log_path, 200))
        if matches:
            current_frame = int(matches[-1])

    return ValidateUSDStatusResponse(
        status=status,
        scene_id=scene_id,
        current_frame=current_frame,
        elapsed_seconds=elapsed_seconds,
        message="Isaac Sim validation in progress." if status == "running" else "Validation job queued.",
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


@router.post("/propose-usd-fix", response_model=UsdFixResponse)
def propose_usd_fix_endpoint(request: UsdFixRequest):
    """
    Fix-proposer for the usd_script_agent pipeline: reasons directly over the
    actual .usda text that was validated plus the real validation_result.json
    from /validate-usd, and returns a corrected .usda file on disk (not a
    mutated scene_config -- see /propose-fix above for that older, separate
    flow). The caller re-submits fixed_usda_path to /validate-usd to verify.
    """
    if not os.path.isfile(request.usda_path):
        raise HTTPException(status_code=404, detail=f"usda_path not found: {request.usda_path}")

    with open(request.usda_path, "r") as f:
        usda_content = f.read()

    try:
        result = usd_fix_agent.propose_usd_fix(
            usda_content=usda_content,
            validation_result=request.validation_result,
            output_filename=request.output_filename,
        )
    except USDScriptError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001 - API boundary maps model/provider failures.
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"USD fix proposal failed: {e!s}")

    return UsdFixResponse(
        status="SUCCESS",
        summary=result.summary,
        fixes=result.fixes,
        fixed_usda_path=result.fixed_path,
        fixed_usda_content=result.fixed_content,
        model_used=result.source,
    )
