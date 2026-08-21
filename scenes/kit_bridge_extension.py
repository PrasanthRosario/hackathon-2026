"""
kit_bridge_extension.py

Fully self-contained -- paste this whole file into Isaac Sim's Script
Editor and run it. No imports from generate_podcast_room.py or any
other project file; every function it needs lives in this one file.

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
from pxr import Usd, UsdGeom, UsdPhysics, Sdf, Gf
import json
import os

COMMANDS_DIR = "/home/ubuntu/bridge/commands"
RESULTS_DIR = "/home/ubuntu/bridge/results"
os.makedirs(COMMANDS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)


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
    xformable.AddTransformOp().Set(look_at_matrix(eye, target, world_up))


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


def get_frustum_corner_dirs(cam_schema):
    focal = cam_schema.GetFocalLengthAttr().Get()
    h_ap = cam_schema.GetHorizontalApertureAttr().Get()
    v_ap = cam_schema.GetVerticalApertureAttr().Get()
    near, far = cam_schema.GetClippingRangeAttr().Get()
    half_w = far * (h_ap / 2.0) / focal
    half_h = far * (v_ap / 2.0) / focal
    dirs = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            local_pt = Gf.Vec3d(sx * half_w, sy * half_h, -far)
            dirs.append(local_pt.GetNormalized())
    return dirs, far


# =======================================================================
# Scene building -- inlined, no external module
# =======================================================================

def make_box(stage, name, size, center, parent, color=None, collider=True):
    path = f"{parent}/{name}"
    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr(1.0)
    xf = UsdGeom.Xformable(cube)
    xf.AddTranslateOp().Set(Gf.Vec3d(*center))
    xf.AddScaleOp().Set(Gf.Vec3f(*size))
    if color:
        cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    if collider:
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
    return cube


def make_cyl(stage, name, parent, radius, height, center, color=None, collider=False):
    path = f"{parent}/{name}"
    cyl = UsdGeom.Cylinder.Define(stage, path)
    cyl.CreateRadiusAttr(radius)
    cyl.CreateHeightAttr(height)
    cyl.CreateAxisAttr(UsdGeom.Tokens.z)
    UsdGeom.Xformable(cyl).AddTranslateOp().Set(Gf.Vec3d(*center))
    if color:
        cyl.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    if collider:
        UsdPhysics.CollisionAPI.Apply(cyl.GetPrim())
    return cyl


def build_podcast_room(stage, room_w=6.0, room_d=5.0, room_h=2.7, gap_w=1.1):
    """Rebuilds the room shell + desk + off-set void on the given stage."""
    world = stage.GetPrimAtPath("/World")
    if not world:
        world = UsdGeom.Xform.Define(stage, "/World")
        stage.SetDefaultPrim(world.GetPrim())

    wall_t = 0.1
    boundary_path = "/World/SetBoundary"
    boundary = UsdGeom.Xform.Define(stage, boundary_path)
    boundary.GetPrim().CreateAttribute("is_set_boundary", Sdf.ValueTypeNames.Bool).Set(True)

    concrete = (0.55, 0.55, 0.55)
    make_box(stage, "Floor", (room_w, room_d, wall_t), (0, 0, -wall_t / 2), boundary_path, color=concrete)
    make_box(stage, "Wall_North", (room_w, wall_t, room_h), (0, room_d / 2, room_h / 2), boundary_path, color=concrete)
    make_box(stage, "Wall_South", (room_w, wall_t, room_h), (0, -room_d / 2, room_h / 2), boundary_path, color=concrete)
    make_box(stage, "Wall_West", (wall_t, room_d, room_h), (-room_w / 2, 0, room_h / 2), boundary_path, color=concrete)

    seg_d = (room_d - gap_w) / 2
    make_box(stage, "Wall_East_A", (wall_t, seg_d, room_h), (room_w / 2, gap_w / 2 + seg_d / 2, room_h / 2), boundary_path, color=concrete)
    make_box(stage, "Wall_East_B", (wall_t, seg_d, room_h), (room_w / 2, -(gap_w / 2 + seg_d / 2), room_h / 2), boundary_path, color=concrete)

    void_path = "/World/Backstage_Void"
    void = UsdGeom.Xform.Define(stage, void_path)
    void.GetPrim().CreateAttribute("is_off_set", Sdf.ValueTypeNames.Bool).Set(True)
    make_box(stage, "VoidPlane", (4.0, gap_w, room_h), (room_w / 2 + 2.0, 0, room_h / 2),
             void_path, color=(0.9, 0.1, 0.1), collider=False)

    desk_w, desk_d, desk_h, desk_top_t = 1.6, 0.7, 0.75, 0.05
    desk_x, desk_y = 0, 0.6
    make_box(stage, "Desk_Top", (desk_w, desk_d, desk_top_t), (desk_x, desk_y, desk_h),
             "/World/SetDressing", color=(0.35, 0.22, 0.12))

    camera_path = "/World/MainCamera"
    if not stage.GetPrimAtPath(camera_path):
        camera = UsdGeom.Camera.Define(stage, camera_path)
        camera.CreateFocalLengthAttr(35.0)
        camera.CreateHorizontalApertureAttr(36.0)
        camera.CreateVerticalApertureAttr(24.0)
        camera.CreateClippingRangeAttr(Gf.Vec2f(0.1, 8.0))
        point_camera_at(camera.GetPrim(), (0, desk_y - desk_d / 2 - 1.3, 1.35), (0, desk_y, 1.15))

    return {"room_w": room_w, "room_d": room_d, "room_h": room_h, "desk_center": [desk_x, desk_y, desk_h]}


# =======================================================================
# Bridge actions
# =======================================================================

def action_build_scene(params):
    stage = omni.usd.get_context().get_stage()
    info = build_podcast_room(
        stage,
        room_w=params.get("room_w", 6.0),
        room_d=params.get("room_d", 5.0),
        room_h=params.get("room_h", 2.7),
        gap_w=params.get("gap_w", 1.1),
    )
    stage.GetRootLayer().Save()
    return {"status": "ok", "scene_info": info}


def action_move_camera(params):
    stage = omni.usd.get_context().get_stage()
    camera_prim = stage.GetPrimAtPath(params.get("camera_path", "/World/MainCamera"))
    point_camera_at(camera_prim, params["eye"], params["target"])
    return {"status": "ok"}


def action_run_validation(params):
    stage = omni.usd.get_context().get_stage()
    camera_prim = stage.GetPrimAtPath(params.get("camera_path", "/World/MainCamera"))
    cam_schema = UsdGeom.Camera(camera_prim)
    xformable = UsdGeom.Xformable(camera_prim)
    physx_query = omni.physx.get_physx_scene_query_interface()

    start, end = stage.GetStartTimeCode(), stage.GetEndTimeCode()
    num_samples = max(int(end - start) + 1, 1)
    violations = []

    for i in range(num_samples):
        frame = start + i
        world_m = xformable.ComputeLocalToWorldTransform(Usd.TimeCode(frame))
        eye = world_m.ExtractTranslation()
        corner_dirs, far = get_frustum_corner_dirs(cam_schema)
        for corner_index, local_dir in enumerate(corner_dirs):
            world_dir = world_m.TransformDir(local_dir).GetNormalized()
            hit = physx_query.raycast_closest(tuple(eye), tuple(world_dir), far)
            if hit["hit"]:
                hit_prim = stage.GetPrimAtPath(str(hit["rigidBody"]))
                if hit_prim.HasAttribute("is_off_set") and hit_prim.GetAttribute("is_off_set").Get():
                    violations.append({"frame": frame, "corner": corner_index, "prim": str(hit_prim.GetPath())})
            else:
                violations.append({"frame": frame, "corner": corner_index, "prim": None})

    return {"status": "FLAGGED" if violations else "OK", "violations": violations}


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