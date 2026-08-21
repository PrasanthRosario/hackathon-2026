"""
make_set.py

Procedurally builds a small USD "film set" — a single room with walls,
props, a light stand/rig, an actor mark, and a handful of candidate
camera positions — for a pre-visualisation shot-validation POC.

Deliberately includes a couple of planted problems (a light stand
poking into frame, a camera clipping through a wall) so the
validation/agent loop has something real to catch during the demo.

Usage:
    pip install usd-core
    python3 make_set.py
    # writes set.usda in the current directory

Requires no GPU. Tested with usd-core on macOS (Apple Silicon + Intel)
and Linux, Python 3.10/3.11 recommended (3.13 can be flaky for USD).
"""

from pxr import Usd, UsdGeom, Gf, Sdf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def add_cube(stage: Usd.Stage, path: str, size: float, translate, color=None):
    """Define a Cube prim at `path`, sized and positioned. Returns the prim."""
    cube = UsdGeom.Cube.Define(stage, path)
    cube.GetSizeAttr().Set(size)
    xf = UsdGeom.Xformable(cube)
    xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
    if color:
        cube.GetDisplayColorAttr().Set([Gf.Vec3f(*color)])
    return cube.GetPrim()


def add_cylinder(stage: Usd.Stage, path: str, radius: float, height: float,
                  translate, color=None):
    """Define a Cylinder prim (used for light stands / rigs). Returns the prim."""
    cyl = UsdGeom.Cylinder.Define(stage, path)
    cyl.GetRadiusAttr().Set(radius)
    cyl.GetHeightAttr().Set(height)
    xf = UsdGeom.Xformable(cyl)
    xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
    if color:
        cyl.GetDisplayColorAttr().Set([Gf.Vec3f(*color)])
    return cyl.GetPrim()


def add_camera(stage: Usd.Stage, path: str, translate, look_at,
                focal_length=35.0, h_aperture=24.0, v_aperture=18.0):
    """
    Define a Camera prim with a simple 'point at a target' orientation.
    Good enough for frustum math — not a full film-rig rig, just real
    enough that focal length / aperture actually mean something.
    """
    cam = UsdGeom.Camera.Define(stage, path)
    cam.GetFocalLengthAttr().Set(focal_length)
    cam.GetHorizontalApertureAttr().Set(h_aperture)
    cam.GetVerticalApertureAttr().Set(v_aperture)

    pos = Gf.Vec3d(*translate)
    target = Gf.Vec3d(*look_at)
    forward = (target - pos)
    if forward.GetLength() < 1e-6:
        forward = Gf.Vec3d(0, 1, 0)
    forward = forward.GetNormalized()

    world_up = Gf.Vec3d(0, 0, 1)
    right = Gf.Cross(forward, world_up)
    if right.GetLength() < 1e-6:
        right = Gf.Vec3d(1, 0, 0)
    right = right.GetNormalized()
    up = Gf.Cross(right, forward).GetNormalized()

    # USD cameras look down -Z in their local space, +Y up.
    rot_matrix = Gf.Matrix4d(
        right[0], right[1], right[2], 0,
        up[0], up[1], up[2], 0,
        -forward[0], -forward[1], -forward[2], 0,
        0, 0, 0, 1,
    )
    xform_matrix = rot_matrix * Gf.Matrix4d().SetTranslate(pos)

    xf = UsdGeom.Xformable(cam)
    xf.AddTransformOp().Set(xform_matrix)
    return cam.GetPrim()


# ---------------------------------------------------------------------------
# Build the set
# ---------------------------------------------------------------------------

def build_set(out_path: str = "set.usda") -> Usd.Stage:
    stage = Usd.Stage.CreateNew(out_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())

    # --- Room: an 8m x 6m x 3.2m interior box (floor + 4 walls) ---------
    room = UsdGeom.Xform.Define(stage, "/World/Room")

    wall_h = 3.2
    wall_t = 0.2
    room_w, room_d = 8.0, 6.0

    add_cube(stage, "/World/Room/Floor", 1.0, (0, 0, -0.05))
    xf = UsdGeom.Xformable(UsdGeom.Cube(stage.GetPrimAtPath("/World/Room/Floor")))
    xf.AddScaleOp().Set(Gf.Vec3d(room_w, room_d, 0.1))

    def wall(name, translate, scale):
        cube = UsdGeom.Cube.Define(stage, f"/World/Room/{name}")
        cube.GetSizeAttr().Set(1.0)
        xf = UsdGeom.Xformable(cube)
        xf.AddTranslateOp().Set(Gf.Vec3d(*translate))
        xf.AddScaleOp().Set(Gf.Vec3d(*scale))
        cube.GetDisplayColorAttr().Set([Gf.Vec3f(0.75, 0.75, 0.72)])
        return cube.GetPrim()

    wall("WallNorth", (0, room_d / 2, wall_h / 2), (room_w, wall_t, wall_h))
    wall("WallSouth", (0, -room_d / 2, wall_h / 2), (room_w, wall_t, wall_h))
    wall("WallEast", (room_w / 2, 0, wall_h / 2), (wall_t, room_d, wall_h))
    wall("WallWest", (-room_w / 2, 0, wall_h / 2), (wall_t, room_d, wall_h))

    # --- Props: set dressing standing in for furniture/crates ----------
    props = UsdGeom.Xform.Define(stage, "/World/Props")
    add_cube(stage, "/World/Props/TableA", 1.0, (-1.5, 0.5, 0.4),
              color=(0.4, 0.28, 0.16))
    add_cube(stage, "/World/Props/CrateA", 0.6, (2.0, -1.0, 0.3),
              color=(0.55, 0.4, 0.2))
    add_cube(stage, "/World/Props/CrateB", 0.6, (2.6, -1.0, 0.3),
              color=(0.55, 0.4, 0.2))
    add_cube(stage, "/World/Props/Shelf", 1.0, (-3.5, -2.0, 0.9),
              color=(0.3, 0.3, 0.3))

    # --- Actor mark: where talent stands for blocking/eyeline checks ---
    add_cube(stage, "/World/ActorMarkA", 0.15, (0, 0, 0.9),
              color=(0.9, 0.1, 0.1))

    # --- Rig: a light stand — PLANTED PROBLEM: tall enough to intrude
    #     on frame from CamWide (see below). This is the flaw the
    #     validation loop should catch. -----------------------------
    UsdGeom.Xform.Define(stage, "/World/Rig")
    add_cylinder(stage, "/World/Rig/LightStandA", 0.05, 2.6, (0.5, 1.6, 1.3),
                  color=(0.1, 0.1, 0.1))

    # --- Cameras: candidate shot positions ------------------------------
    UsdGeom.Xform.Define(stage, "/World/Cameras")
    # CamMedium: clean medium shot on the actor mark, no issues.
    add_camera(stage, "/World/Cameras/CamMedium",
               translate=(-3.0, 0.5, 1.6), look_at=(0, 0, 0.9),
               focal_length=50.0)

    # CamWide: wide establishing shot — PLANTED PROBLEM: LightStandA
    # sits inside this frustum near the edge, and the crate pair
    # sits close enough to the camera's back-left to be worth a
    # clearance check on any dolly move.
    add_camera(stage, "/World/Cameras/CamWide",
               translate=(-3.6, -2.4, 1.6), look_at=(0.5, 0.5, 0.9),
               focal_length=24.0)

    # CamCloseup: tight shot, positioned close enough to clip the
    # west wall if a dolly-in move isn't checked — PLANTED PROBLEM.
    add_camera(stage, "/World/Cameras/CamCloseup",
               translate=(-3.85, 0.1, 1.5), look_at=(0, 0.1, 1.0),
               focal_length=85.0)

    stage.GetRootLayer().Save()
    return stage


if __name__ == "__main__":
    stage = build_set("set.usda")
    print(f"Wrote {stage.GetRootLayer().realPath}")
    print("\nScene contents:")
    for prim in stage.Traverse():
        print(f"  {prim.GetPath()}  ({prim.GetTypeName()})")