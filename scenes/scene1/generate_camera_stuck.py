"""
generate_camera_stuck.py

No generator script was checked in for the original podcast_room.usda
(only the built file), so this opens that file directly and overwrites
just the camera's last keyframe -- swapping its eye position for a
point embedded inside Desk_Top, while keeping the target on the desk
(on-set). That isolates the camera-body collision check from the
off-set/frustum check: this shot should stay frustum-OK the whole
time, but flag a camera_collision on the last frame.

Run with the same venv used for scene2 (scenes/scene2/.venv), or any
plain `pip install usd-core` environment -- no omni.* needed.

Produces podcast_room_camera_stuck.usda alongside podcast_room.usda.
"""

from pxr import Usd, UsdGeom, Gf

SRC = "podcast_room.usda"
OUT = "podcast_room_camera_stuck.usda"

# Same math as generate_podcast_room.py / generate_studio_room.py.
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


def build():
    src = Usd.Stage.Open(SRC)
    fps = src.GetTimeCodesPerSecond()
    end_time = src.GetEndTimeCode()

    # Fresh copy on disk rather than mutating the original in place.
    src.GetRootLayer().Export(OUT)
    stage = Usd.Stage.Open(OUT)

    camera_prim = stage.GetPrimAtPath("/World/MainCamera")
    op = UsdGeom.Xformable(camera_prim).GetOrderedXformOps()[0]
    attr = op.GetAttr()

    desk_target = (0, 0.6, 1.15)   # same desk aim as the good shot
    desk_center = (0, 0.6, 0.75)   # Desk_Top's own translate

    # Only the final keyframe changes -- the dolly starts normally and
    # overshoots straight into the desk right at the end.
    attr.Set(look_at_matrix(desk_center, desk_target), Usd.TimeCode(end_time))

    stage.GetRootLayer().Save()
    print(f"Saved {OUT}")


if __name__ == "__main__":
    build()
