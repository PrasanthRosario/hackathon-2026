"""
kit_bridge_extension.py

Fully self-contained -- paste this whole file into Isaac Sim's Script
Editor and run it. It never imports a scene-generator script directly;
"build_scene" just opens whatever .usda file it's pointed at (see
SCENE_PATHS below), including ones the web app generates dynamically
at runtime with plain pxr (no omni.* needed). That keeps scene
authoring and the Kit-side bridge decoupled -- adding a new scene
never requires touching this file.

Watches a shared folder for commands from your external web app,
executes them against the real stage, writes results back.

Folder layout (adjust to a path both this process and your web
backend can read/write):

  bridge/commands/<uuid>.json   -- written by the web backend
  bridge/results/<uuid>.json    -- written by this script
"""

import omni.kit.app
import omni.usd
import omni.physx
import omni.timeline
from pxr import Usd, UsdGeom, Gf
import json
import os

COMMANDS_DIR = "/home/ubuntu/bridge/commands"
RESULTS_DIR = "/home/ubuntu/bridge/results"
os.makedirs(COMMANDS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# Scenes are authored as plain .usda files (built headlessly with pxr,
# no omni.* needed -- see generate_podcast_room.py / generate_studio_room.py)
# and dropped somewhere this process can read. Kit's job is just to open
# whichever one it's told to -- it doesn't need to know how any of them
# were built. These are shorthands for the two checked-in demo scenes;
# a dynamically generated scene just passes its own "usda_path" instead.
SCENE_PATHS = {
    "scene1": "/home/ubuntu/scenes/scene1/podcast_room.usda",
    "scene2": "/home/ubuntu/scenes/scene2/studio_room.usda",
}


# =======================================================================
# Camera math -- inlined, no external module
# =======================================================================

def look_at_matrix(eye, target, world_up=(0, 0, 1)):
    eye = Gf.Vec3d(*eye)
    target = Gf.Vec3d(*target)
    world_up = Gf.Vec3d(*world_up)

    forward = (target - eye).GetNormalized()
    right = Gf.Cross(forward, world_up).GetNormalized()
    true_up = Gf.Cross(right, forward)

    m = Gf.Matrix4d(1.0)
    m.SetRow(0, Gf.Vec4d(right[0], right[1], right[2], 0.0))
    m.SetRow(1, Gf.Vec4d(true_up[0], true_up[1], true_up[2], 0.0))
    m.SetRow(2, Gf.Vec4d(-forward[0], -forward[1], -forward[2], 0.0))
    m.SetRow(3, Gf.Vec4d(eye[0], eye[1], eye[2], 1.0))
    return m


def point_camera_at(camera_prim, eye, target, world_up=(0, 0, 1)):
    xformable = UsdGeom.Xformable(camera_prim)
    xformable.ClearXformOpOrder()
    op = xformable.AddTransformOp()
    attr = op.GetAttr()
    # A prior animate_camera_move() call may have left baked time
    # samples on this same attribute. A plain Set() below only writes
    # a *default* value -- while the timeline is playing within an
    # animated range, USD prefers the time-sampled value over the
    # default, so the old animation would silently keep winning.
    # Wipe any leftover samples so this static look-at actually sticks.
    for t in attr.GetTimeSamples():
        attr.ClearAtTime(Usd.TimeCode(t))
    op.Set(look_at_matrix(eye, target, world_up))


def animate_camera_move(stage, camera_prim, keyframes, fps=24):
    """keyframes: list of (time_seconds, eye, target) tuples."""
    stage.SetTimeCodesPerSecond(fps)
    stage.SetStartTimeCode(keyframes[0][0] * fps)
    stage.SetEndTimeCode(keyframes[-1][0] * fps)

    xformable = UsdGeom.Xformable(camera_prim)
    xformable.ClearXformOpOrder()
    op = xformable.AddTransformOp()
    for t_sec, eye, target in keyframes:
        op.Set(look_at_matrix(eye, target), Usd.TimeCode(t_sec * fps))


def get_frustum_sample_dirs(cam_schema, grid=5):
    """Rays in camera-local space sampled across the whole frame (a
    grid x grid lattice from -1..1 in both axes, including the
    center), not just the 4 far-plane corners. A gap in the set
    narrower than the corner-to-corner spread would never register
    against the old 4-corner-only sampling; a dense grid can't miss
    it that way."""
    focal = cam_schema.GetFocalLengthAttr().Get()
    h_ap = cam_schema.GetHorizontalApertureAttr().Get()
    v_ap = cam_schema.GetVerticalApertureAttr().Get()
    near, far = cam_schema.GetClippingRangeAttr().Get()
    half_w = far * (h_ap / 2.0) / focal
    half_h = far * (v_ap / 2.0) / focal
    dirs = []
    steps = [-1.0 + 2.0 * i / (grid - 1) for i in range(grid)]
    for sx in steps:
        for sy in steps:
            local_pt = Gf.Vec3d(sx * half_w, sy * half_h, -far)
            dirs.append(local_pt.GetNormalized())
    return dirs, far


# =======================================================================
# Bridge actions
# =======================================================================

def action_build_scene(params):
    """Opens a .usda as the live stage. "usda_path" takes any file --
    including one the web app just generated on the fly with plain pxr
    (no omni.* needed) and dropped somewhere this process can read.
    "scene": "scene1" / "scene2" is just a shorthand for the two
    checked-in demo files in SCENE_PATHS. Kit never needs to know how
    a scene was built, only where the file is."""
    usda_path = params.get("usda_path") or SCENE_PATHS.get(params.get("scene", ""))
    if not usda_path:
        return {"status": "error", "message": "pass 'usda_path' or a known 'scene' name"}
    if not os.path.isfile(usda_path):
        return {"status": "error", "message": f"usda not found: {usda_path}"}

    context = omni.usd.get_context()
    if not context.open_stage(usda_path):
        return {"status": "error", "message": f"failed to open stage: {usda_path}"}

    return {"status": "ok", "usda_path": usda_path}


def action_move_camera(params):
    stage = omni.usd.get_context().get_stage()
    camera_prim = stage.GetPrimAtPath(params.get("camera_path", "/World/MainCamera"))
    point_camera_at(camera_prim, params["eye"], params["target"])
    return {"status": "ok"}


def check_camera_body_collision(physx_query, eye, radius=0.15):
    """Sphere-overlap query at the camera's own position -- catches the
    rig itself being jammed inside a wall/desk/prop, which the outward
    frustum rays below can never detect (they start FROM the camera,
    so they can't see that the camera's own body is embedded in
    something). `radius` stands in for the physical bulk of a real
    camera + rig; tune it to whatever's realistic for your setup."""
    hit_paths = []

    def report_hit(hit):
        hit_paths.append(str(hit.rigid_body))
        return True  # keep collecting all overlaps, not just the first

    try:
        physx_query.overlap_sphere(radius, tuple(eye), report_hit, False)
    except TypeError:
        # Some Kit/PhysX versions take (pos, radius, ...) instead --
        # retry with the arguments swapped before giving up.
        physx_query.overlap_sphere(tuple(eye), radius, report_hit, False)

    return hit_paths


def action_run_validation(params):
    stage = omni.usd.get_context().get_stage()
    camera_prim = stage.GetPrimAtPath(params.get("camera_path", "/World/MainCamera"))
    cam_schema = UsdGeom.Camera(camera_prim)
    xformable = UsdGeom.Xformable(camera_prim)
    physx_query = omni.physx.get_physx_scene_query_interface()
    camera_radius = params.get("camera_radius", 0.15)

    start, end = stage.GetStartTimeCode(), stage.GetEndTimeCode()
    num_samples = max(int(end - start) + 1, 1)
    violations = []
    camera_collisions = []

    for i in range(num_samples):
        frame = start + i
        world_m = xformable.ComputeLocalToWorldTransform(Usd.TimeCode(frame))
        eye = world_m.ExtractTranslation()

        colliding_with = check_camera_body_collision(physx_query, eye, camera_radius)
        if colliding_with:
            camera_collisions.append({"frame": frame, "colliding_with": colliding_with})

        corner_dirs, far = get_frustum_sample_dirs(cam_schema)
        for corner_index, local_dir in enumerate(corner_dirs):
            world_dir = world_m.TransformDir(local_dir).GetNormalized()
            hit = physx_query.raycast_closest(tuple(eye), tuple(world_dir), far)
            if hit["hit"]:
                hit_prim = stage.GetPrimAtPath(str(hit["rigidBody"]))
                if hit_prim.HasAttribute("is_off_set") and hit_prim.GetAttribute("is_off_set").Get():
                    violations.append({"frame": frame, "corner": corner_index, "prim": str(hit_prim.GetPath())})
            else:
                violations.append({"frame": frame, "corner": corner_index, "prim": None})

    flagged = bool(violations) or bool(camera_collisions)
    return {
        "status": "FLAGGED" if flagged else "OK",
        "violations": violations,
        "camera_collisions": camera_collisions,
    }


ACTIONS = {
    "build_scene": action_build_scene,
    "move_camera": action_move_camera,
    "run_validation": action_run_validation,
}


# =======================================================================
# Polling loop
# =======================================================================

def check_bridge(event):
    if not os.path.isdir(COMMANDS_DIR):
        return
    for fname in os.listdir(COMMANDS_DIR):
        cmd_path = os.path.join(COMMANDS_DIR, fname)
        try:
            with open(cmd_path) as f:
                cmd = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        print(f"[bridge] picked up {fname}: action={cmd.get('action')} params={cmd.get('params', {})}")

        action_fn = ACTIONS.get(cmd["action"])
        if action_fn:
            try:
                result = action_fn(cmd.get("params", {}))
            except Exception as e:
                result = {"status": "error", "message": str(e)}
        else:
            result = {"status": "error", "message": f"unknown action: {cmd['action']}"}

        print(f"[bridge] result for {cmd.get('id')}: {result}")

        with open(os.path.join(RESULTS_DIR, f"{cmd['id']}.json"), "w") as f:
            json.dump(result, f)
        os.remove(cmd_path)


update_stream = omni.kit.app.get_app().get_update_event_stream()
bridge_subscription = update_stream.create_subscription_to_pop(check_bridge)
print("Bridge active -- watching", COMMANDS_DIR)