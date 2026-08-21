# Run inside Isaac Sim's Script Editor — needs omni.* modules.

import omni.kit.app
import omni.physx
import omni.usd
import omni.timeline
from pxr import Usd, UsdGeom, Gf
import math

stage = omni.usd.get_context().get_stage()
camera_prim = stage.GetPrimAtPath("/World/MainCamera")
cam_schema = UsdGeom.Camera(camera_prim)
xformable = UsdGeom.Xformable(camera_prim)
timeline = omni.timeline.get_timeline_interface()
physx_query = omni.physx.get_physx_scene_query_interface()

def get_frustum_corner_dirs(cam_schema):
    """4 rays, in camera-local space, through the far-plane corners."""
    focal = cam_schema.GetFocalLengthAttr().Get()
    h_ap = cam_schema.GetHorizontalApertureAttr().Get()
    v_ap = cam_schema.GetVerticalApertureAttr().Get()
    near, far = cam_schema.GetClippingRangeAttr().Get()

    half_w = far * (h_ap / 2.0) / focal
    half_h = far * (v_ap / 2.0) / focal

    corners = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            # camera looks down local -Z
            local_pt = Gf.Vec3d(sx * half_w, sy * half_h, -far)
            corners.append(local_pt.GetNormalized())
    return corners, far

def check_shot(current_frame):
    world_m = xformable.ComputeLocalToWorldTransform(Usd.TimeCode(current_frame))
    eye = world_m.ExtractTranslation()
    local_dirs, far = get_frustum_corner_dirs(cam_schema)

    results = []
    for local_dir in local_dirs:
        world_dir = world_m.TransformDir(local_dir).GetNormalized()
        hit = physx_query.raycast_closest(tuple(eye), tuple(world_dir), far)
        if hit["hit"]:
            hit_prim = stage.GetPrimAtPath(str(hit["rigidBody"]))
            is_off_set = hit_prim.HasAttribute("is_off_set") and hit_prim.GetAttribute("is_off_set").Get()
            results.append({"hit": True, "off_set": is_off_set, "prim": str(hit_prim.GetPath())})
        else:
            # ray escaped without hitting anything within far clip — also a flag
            results.append({"hit": False, "off_set": True, "prim": None})
    return results

def on_update(event):
    current_frame = timeline.get_current_time() * stage.GetTimeCodesPerSecond()
    results = check_shot(current_frame)
    flagged = any(r["off_set"] for r in results)
    if flagged:
        print(f"Frame {current_frame:.0f}: FLAG — frustum edge sees off-set ({results})")

update_stream = omni.kit.app.get_app().get_update_event_stream()
subscription = update_stream.create_subscription_to_pop(on_update)