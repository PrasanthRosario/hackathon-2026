"""
isaac_sim_live_validate.py

Paste this into Isaac Sim's Script Editor (Window > Script Editor) and
run it, then press Play on the timeline.

Unlike the earlier version, this one prints a result EITHER way:
- while playing, per frame: "Frame X: OK" or "Frame X: FLAG ..."
- at the end of the run: one summary verdict, SHOT OK or SHOT FLAGGED

Needs the omni.* modules -- only available inside Isaac Sim's own
Python environment, not a plain local Python install.
"""

import omni.kit.app
import omni.physx
import omni.usd
import omni.timeline
from pxr import Usd, UsdGeom, Gf

stage = omni.usd.get_context().get_stage()
camera_prim = stage.GetPrimAtPath("/World/MainCamera")
cam_schema = UsdGeom.Camera(camera_prim)
xformable = UsdGeom.Xformable(camera_prim)
timeline = omni.timeline.get_timeline_interface()
physx_query = omni.physx.get_physx_scene_query_interface()

# Tracks whether we've already printed the final summary for this
# play-through, and every frame that came back flagged.
_run_state = {"reported_end": False, "violations": []}


def get_frustum_corner_dirs(cam_schema):
    """4 rays, in camera-local space, through the far-plane corners."""
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


def check_shot(current_frame):
    world_m = xformable.ComputeLocalToWorldTransform(Usd.TimeCode(current_frame))
    eye = world_m.ExtractTranslation()
    corner_dirs, far = get_frustum_corner_dirs(cam_schema)

    results = []
    for corner_index, local_dir in enumerate(corner_dirs):
        world_dir = world_m.TransformDir(local_dir).GetNormalized()
        hit = physx_query.raycast_closest(tuple(eye), tuple(world_dir), far)
        if hit["hit"]:
            hit_prim = stage.GetPrimAtPath(str(hit["rigidBody"]))
            is_off_set = hit_prim.HasAttribute("is_off_set") and hit_prim.GetAttribute("is_off_set").Get()
            results.append({
                "corner": corner_index, "hit": True,
                "off_set": bool(is_off_set), "prim": str(hit_prim.GetPath()),
            })
        else:
            # ray escaped without hitting anything within the far clip -- also a flag
            results.append({"corner": corner_index, "hit": False, "off_set": True, "prim": None})
    return results


def on_update(event):
    if not timeline.is_playing():
        return

    stage = omni.usd.get_context().get_stage()
    if not stage:
        return

    current_frame = timeline.get_current_time() * timeline.get_time_codes_per_second()
    results = check_shot(current_frame)
    flagged_corners = [r for r in results if r["off_set"]]

    if flagged_corners:
        print(f"Frame {current_frame:.0f}: FLAG -- {flagged_corners}")
        _run_state["violations"].append((round(current_frame, 1), flagged_corners))
        _run_state["reported_end"] = False
    else:
        print(f"Frame {current_frame:.0f}: OK")

    # Print one summary the moment playback reaches the end of the timeline.
    if current_frame >= stage.GetEndTimeCode() and not _run_state["reported_end"]:
        print("=" * 50)
        if _run_state["violations"]:
            print(f"SHOT FLAGGED -- {len(_run_state['violations'])} frame(s) violated:")
            for frame, corners in _run_state["violations"]:
                print(f"  frame {frame}: {corners}")
        else:
            print("SHOT OK -- full playthrough, no violations.")
        print("=" * 50)
        _run_state["reported_end"] = True
        _run_state["violations"] = []  # reset for the next play-through


# Subscribe. Keep `subscription` alive for the life of the session --
# if this variable gets garbage collected, the callback silently stops
# firing with no error.
update_stream = omni.kit.app.get_app().get_update_event_stream()
subscription = update_stream.create_subscription_to_pop(on_update)

print("Live shot validation active. Press Play to run it.")