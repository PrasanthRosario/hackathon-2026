"""
generate_room.py

Builds a minimal film-set "room" as a USD stage for the pre-viz shot
validation project. Produces room_set.usda, ready to open directly in
Isaac Sim / Omniverse, or to reference into a bigger stage.

Layout (meters, Z-up):
  - An 8m x 6m x 3m room: floor + 4 walls, grouped under /World/SetBoundary
  - A 2m gap in the east wall = where the physical set ends
  - A "Backstage_Void" plane just past the gap, tagged is_off_set = True,
    so your violation-detection logic has something concrete to test
    "does the frustum see off-set" against
  - Physics colliders (UsdPhysics.CollisionAPI) on floor + walls, so
    PhysX raycasting works immediately once loaded in Isaac Sim
  - A starter Camera prim ("MainCamera") inside the room with
    focal length / sensor / clipping already set

Run this with plain Python (needs `pip install usd-core`) to generate
the file, OR paste the build_room() body into Isaac Sim's Script Editor
to build it directly on the running stage instead of writing a file.
"""

from pxr import Usd, UsdGeom, UsdPhysics, Sdf, Gf


def build_room(stage_path="room_set.usda"):
    stage = Usd.Stage.CreateNew(stage_path)

    # --- Stage setup ---------------------------------------------------
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)   # Isaac Sim default: Z-up
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)         # 1 unit = 1 meter

    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())

    # --- Room dimensions -------------------------------------------------
    room_w = 8.0   # along X
    room_d = 6.0   # along Y
    room_h = 3.0   # along Z
    wall_t = 0.1   # wall thickness
    gap_w = 2.0    # width of the opening in the east wall ("off-set" gap)

    boundary = UsdGeom.Xform.Define(stage, "/World/SetBoundary")
    boundary.GetPrim().CreateAttribute(
        "is_set_boundary", Sdf.ValueTypeNames.Bool
    ).Set(True)

    def make_box(name, size, center, parent_path="/World/SetBoundary"):
        """Create a collider-enabled cube prim of given size (x,y,z) at center."""
        path = f"{parent_path}/{name}"
        cube = UsdGeom.Cube.Define(stage, path)
        cube.CreateSizeAttr(1.0)  # unit cube, scaled via xform below
        xform = UsdGeom.Xformable(cube)
        xform.AddTranslateOp().Set(Gf.Vec3d(*center))
        xform.AddScaleOp().Set(Gf.Vec3f(size[0] / 1.0, size[1] / 1.0, size[2] / 1.0))
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        return cube

    # Floor
    make_box("Floor", (room_w, room_d, wall_t), (0, 0, -wall_t / 2))

    # North / South walls (full length along X)
    make_box("Wall_North", (room_w, wall_t, room_h), (0, room_d / 2, room_h / 2))
    make_box("Wall_South", (room_w, wall_t, room_h), (0, -room_d / 2, room_h / 2))

    # West wall (full length along Y)
    make_box("Wall_West", (wall_t, room_d, room_h), (-room_w / 2, 0, room_h / 2))

    # East wall — split into two segments with a gap_w opening in the middle
    seg_d = (room_d - gap_w) / 2
    make_box(
        "Wall_East_A", (wall_t, seg_d, room_h),
        (room_w / 2, (gap_w / 2 + seg_d / 2), room_h / 2),
    )
    make_box(
        "Wall_East_B", (wall_t, seg_d, room_h),
        (room_w / 2, -(gap_w / 2 + seg_d / 2), room_h / 2),
    )

    # --- Backstage void: what's "off-set" beyond the gap -----------------
    void = UsdGeom.Xform.Define(stage, "/World/Backstage_Void")
    void.GetPrim().CreateAttribute(
        "is_off_set", Sdf.ValueTypeNames.Bool
    ).Set(True)
    void_plane = UsdGeom.Cube.Define(stage, "/World/Backstage_Void/VoidPlane")
    void_plane.CreateSizeAttr(1.0)
    vxform = UsdGeom.Xformable(void_plane)
    vxform.AddTranslateOp().Set(Gf.Vec3d(room_w / 2 + 3.0, 0, room_h / 2))
    vxform.AddScaleOp().Set(Gf.Vec3f(6.0, gap_w, room_h))
    void_plane.CreateDisplayColorAttr([Gf.Vec3f(0.9, 0.1, 0.1)])  # red = flag zone

    # --- Starter camera ----------------------------------------------------
    camera = UsdGeom.Camera.Define(stage, "/World/MainCamera")
    camera.CreateFocalLengthAttr(35.0)          # mm
    camera.CreateHorizontalApertureAttr(36.0)   # mm (full-frame sensor width)
    camera.CreateVerticalApertureAttr(24.0)     # mm
    camera.CreateClippingRangeAttr(Gf.Vec2f(0.1, 1000.0))
    cxform = UsdGeom.Xformable(camera)
    cxform.AddTranslateOp().Set(Gf.Vec3d(-2.5, 0, 1.6))  # inside the room, ~eye height
    # Point it toward room center / the gap, adjust in Isaac Sim as needed
    cxform.AddRotateXYZOp().Set(Gf.Vec3f(0, 0, 0))

    stage.GetRootLayer().Save()
    print(f"Saved {stage_path}")
    return stage


if __name__ == "__main__":
    build_room()
