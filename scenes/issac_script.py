# Run this in Isaac Sim's Script Editor — needs the omni.* modules,
# which only exist inside the Isaac Sim / Kit Python environment.

import omni.kit.app
import omni.physx
from pxr import Usd, UsdGeom
import omni.usd

stage = omni.usd.get_context().get_stage()
camera_prim = stage.GetPrimAtPath("/World/MainCamera")
xformable = UsdGeom.Xformable(camera_prim)
timeline = omni.timeline.get_timeline_interface()
physx_query = omni.physx.get_physx_scene_query_interface()

def on_update(event):
    current_frame = timeline.get_current_time() * stage.GetTimeCodesPerSecond()
    world_transform = xformable.ComputeLocalToWorldTransform(Usd.TimeCode(current_frame))
    eye = world_transform.ExtractTranslation()

    # cast a ray from the camera along its forward direction (or through
    # each frustum corner, once your frustum math is wired in) and check
    # what it hits
    forward = -world_transform.GetRow3(2)  # local -Z in world space
    hit = physx_query.raycast_closest(
        tuple(eye), tuple(forward), 30.0
    )
    if hit["hit"]:
        hit_prim = stage.GetPrimAtPath(hit["rigidBody"])
        if hit_prim.HasAttribute("is_off_set"):
            print(f"Frame {current_frame}: shot sees off-set!")

# subscribe: this callback now fires every frame while the sim runs
update_stream = omni.kit.app.get_app().get_update_event_stream()
subscription = update_stream.create_subscription_to_pop(on_update)