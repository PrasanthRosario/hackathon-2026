"""
generate_church_scene.py

An open-world courtyard scene: a church, a wandering crowd (random
colors, one hero in white), scattered trees and cars as obstacles,
and two cameras:

  WideCam   -- a static wide-angle establishing shot on the hero
  SideTrackCam -- a moving side-angle tracking shot that strafes past
                  the obstacles while continuously staying aimed at
                  the hero (real look-at math recomputed per keyframe,
                  not a fixed direction)

Fully self-contained, no external imports beyond pxr. Fixed random
seed so re-running gives the same layout (important for testing).

Produces church_scene.usda.
"""

import random
from pxr import Usd, UsdGeom, UsdShade, UsdLux, UsdPhysics, Sdf, Gf

random.seed(42)


# =======================================================================
# Materials
# =======================================================================

def make_material(stage, name, diffuse, emissive=None, roughness=0.6, metallic=0.0):
    path = f"/World/Materials/{name}"
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, f"{path}/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*diffuse))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(roughness)
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(metallic)
    if emissive:
        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*emissive))
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat


def bind(prim, material):
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)


def safe(name):
    return str(name).replace("-", "n").replace(".", "p")


# =======================================================================
# Geometry helpers
# =======================================================================

def make_box(stage, name, size, center, parent, material=None, collider=True, rotate_xyz=None):
    cube = UsdGeom.Cube.Define(stage, f"{parent}/{name}")
    cube.CreateSizeAttr(1.0)
    xf = UsdGeom.Xformable(cube)
    xf.AddTranslateOp().Set(Gf.Vec3d(*center))
    if rotate_xyz:
        xf.AddRotateXYZOp().Set(Gf.Vec3f(*rotate_xyz))
    xf.AddScaleOp().Set(Gf.Vec3f(*size))
    if material:
        bind(cube.GetPrim(), material)
    if collider:
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
    return cube


def make_cyl(stage, name, parent, radius, height, center, material=None, collider=False, rotate_xyz=None):
    cyl = UsdGeom.Cylinder.Define(stage, f"{parent}/{name}")
    cyl.CreateRadiusAttr(radius)
    cyl.CreateHeightAttr(height)
    cyl.CreateAxisAttr(UsdGeom.Tokens.z)
    xf = UsdGeom.Xformable(cyl)
    xf.AddTranslateOp().Set(Gf.Vec3d(*center))
    if rotate_xyz:
        xf.AddRotateXYZOp().Set(Gf.Vec3f(*rotate_xyz))
    if material:
        bind(cyl.GetPrim(), material)
    if collider:
        UsdPhysics.CollisionAPI.Apply(cyl.GetPrim())
    return cyl


def make_cone(stage, name, parent, radius, height, center, material=None, collider=False):
    cone = UsdGeom.Cone.Define(stage, f"{parent}/{name}")
    cone.CreateRadiusAttr(radius)
    cone.CreateHeightAttr(height)
    cone.CreateAxisAttr(UsdGeom.Tokens.z)
    UsdGeom.Xformable(cone).AddTranslateOp().Set(Gf.Vec3d(*center))
    if material:
        bind(cone.GetPrim(), material)
    if collider:
        UsdPhysics.CollisionAPI.Apply(cone.GetPrim())
    return cone


def make_sphere(stage, name, parent, radius, center, material=None):
    sph = UsdGeom.Sphere.Define(stage, f"{parent}/{name}")
    sph.CreateRadiusAttr(radius)
    UsdGeom.Xformable(sph).AddTranslateOp().Set(Gf.Vec3d(*center))
    if material:
        bind(sph.GetPrim(), material)
    return sph


# =======================================================================
# Camera math
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


def point_camera_at(camera_prim, eye, target):
    xf = UsdGeom.Xformable(camera_prim)
    xf.ClearXformOpOrder()
    xf.AddTransformOp().Set(look_at_matrix(eye, target))


def animate_camera_move(stage, camera_prim, keyframes, fps=24):
    """keyframes: list of (time_seconds, eye, target)."""
    xf = UsdGeom.Xformable(camera_prim)
    xf.ClearXformOpOrder()
    op = xf.AddTransformOp()
    for t_sec, eye, target in keyframes:
        op.Set(look_at_matrix(eye, target), Usd.TimeCode(t_sec * fps))


# =======================================================================
# People -- standing figures, one hero in white, rest in random colors
# =======================================================================

RANDOM_SHIRT_COLORS = [
    (0.75, 0.25, 0.25), (0.25, 0.45, 0.75), (0.35, 0.65, 0.35),
    (0.7, 0.55, 0.2), (0.5, 0.3, 0.6), (0.8, 0.6, 0.65), (0.3, 0.3, 0.35),
]


def build_standing_person(stage, parent, name, position, shirt_color, is_hero=False, skin_mat=None):
    x, y, ground_z = position
    person_path = f"{parent}/{name}"
    person = UsdGeom.Xform.Define(stage, person_path)
    if is_hero:
        person.GetPrim().CreateAttribute("is_hero", Sdf.ValueTypeNames.Bool).Set(True)

    shirt_mat = make_material(stage, f"Shirt_{name}", shirt_color, roughness=0.7)

    leg_h = 0.85
    torso_h = 0.55
    hip_z = ground_z + leg_h
    for side, sign in [("L", -1), ("R", 1)]:
        make_cyl(stage, f"Leg_{side}", person_path, 0.08, leg_h, (x + sign * 0.09, y, ground_z + leg_h / 2),
                 material=shirt_mat, collider=False)
    make_cyl(stage, "Torso", person_path, 0.16, torso_h, (x, y, hip_z + torso_h / 2),
             material=shirt_mat, collider=False)
    neck_z = hip_z + torso_h
    make_sphere(stage, "Head", person_path, 0.11, (x, y, neck_z + 0.14), material=skin_mat)
    for side, sign in [("L", -1), ("R", 1)]:
        make_cyl(stage, f"Arm_{side}", person_path, 0.055, 0.5, (x + sign * 0.22, y, hip_z + torso_h - 0.25),
                 material=shirt_mat, collider=False)

    return person, (x, y, neck_z + 0.14)  # returns head position, useful for camera targeting


# =======================================================================
# Scene pieces
# =======================================================================

def build_ground(stage, size=30.0):
    mat_ground = make_material(stage, "Ground", (0.45, 0.42, 0.38), roughness=0.9)
    make_box(stage, "Ground", (size, size, 0.1), (0, 0, -0.05), "/World", material=mat_ground)


def build_church(stage, mat_stone, mat_roof, mat_glow, origin=(0, 8, 0)):
    ox, oy, oz = origin
    church_path = "/World/Church"
    UsdGeom.Xform.Define(stage, church_path)

    nave_w, nave_d, nave_h = 6.0, 12.0, 5.0
    make_box(stage, "Nave", (nave_w, nave_d, nave_h), (ox, oy, oz + nave_h / 2), church_path, material=mat_stone)
    # Simple gabled roof: two slanted slabs meeting at a ridge
    make_box(stage, "RoofSlopeA", (nave_w * 0.75, nave_d + 0.4, 0.15), (ox, oy, oz + nave_h + 0.6),
             church_path, material=mat_roof, rotate_xyz=(25, 0, 0), collider=False)
    make_box(stage, "RoofSlopeB", (nave_w * 0.75, nave_d + 0.4, 0.15), (ox, oy, oz + nave_h + 0.6),
             church_path, material=mat_roof, rotate_xyz=(-25, 0, 0), collider=False)
    # Steeple
    tower_x = ox
    tower_y = oy - nave_d / 2 - 0.8
    make_box(stage, "Tower", (1.6, 1.6, 6.0), (tower_x, tower_y, oz + 3.0), church_path, material=mat_stone)
    make_cyl(stage, "SpireBase", church_path, 0.85, 0.3, (tower_x, tower_y, oz + 6.0), material=mat_roof, collider=False)
    make_cone(stage, "Spire", church_path, 0.85, 2.5, (tower_x, tower_y, oz + 7.5), material=mat_roof, collider=False)
    # A glowing rose window as a focal detail
    make_cyl(stage, "RoseWindow", church_path, 0.6, 0.1, (tower_x, tower_y - 0.85, oz + 3.5),
             material=mat_glow, collider=False, rotate_xyz=(90, 0, 0))

    return {"door_position": (ox, oy - nave_d / 2, oz)}


def scatter_trees(stage, n, exclude_zone, mat_trunk, mat_leaves, radius=13.0):
    for i in range(n):
        for _ in range(20):
            x = random.uniform(-radius, radius)
            y = random.uniform(-radius, radius)
            if _outside_exclude(x, y, exclude_zone):
                break
        trunk_h = random.uniform(1.8, 2.6)
        make_cyl(stage, f"Trunk_{i}", "/World/Trees", 0.12, trunk_h, (x, y, trunk_h / 2), material=mat_trunk)
        make_cone(stage, f"Foliage_{i}", "/World/Trees", 0.9, 1.8, (x, y, trunk_h + 0.9), material=mat_leaves)


def scatter_cars(stage, positions, mat_body_colors):
    for i, (x, y, rot) in enumerate(positions):
        car_path = "/World/Cars"
        color = mat_body_colors[i % len(mat_body_colors)]
        make_box(stage, f"CarBody_{i}", (2.0, 0.9, 0.5), (x, y, 0.35), car_path, material=color, rotate_xyz=(0, 0, rot))
        make_box(stage, f"CarCabin_{i}", (1.1, 0.85, 0.4), (x, y, 0.75), car_path, material=color, rotate_xyz=(0, 0, rot))
        for wx, wy in [(-0.7, -0.4), (0.7, -0.4), (-0.7, 0.4), (0.7, 0.4)]:
            rad = Gf.Vec3d(wx, wy, 0)
            rot_rad = rot * 3.14159 / 180.0
            rx = wx * (rot_rad and 1 or 1)  # keep simple: skip true rotation of wheel offsets for a blockout
            make_cyl(stage, f"Wheel_{i}_{safe(wx)}_{safe(wy)}", car_path, 0.22, 0.2,
                     (x + wx, y + wy, 0.22), material=None, collider=False, rotate_xyz=(90, 0, 0))


def _outside_exclude(x, y, exclude_zone):
    ex, ey, er = exclude_zone
    return ((x - ex) ** 2 + (y - ey) ** 2) ** 0.5 > er


def scatter_crowd(stage, n, hero_position, exclude_zone, mat_skin):
    heads = {}
    hero_path = "/World/Crowd/Hero"
    _, hero_head = build_standing_person(stage, "/World/Crowd", "Hero", hero_position, (0.95, 0.95, 0.92),
                                          is_hero=True, skin_mat=mat_skin)
    heads["hero"] = hero_head

    for i in range(n):
        for _ in range(20):
            x = random.uniform(-9, 9)
            y = random.uniform(-9, 9)
            if _outside_exclude(x, y, exclude_zone) and _outside_exclude(x, y, (hero_position[0], hero_position[1], 1.2)):
                break
        color = random.choice(RANDOM_SHIRT_COLORS)
        build_standing_person(stage, "/World/Crowd", f"Person_{i}", (x, y, 0), color, skin_mat=mat_skin)

    return heads


# =======================================================================
# Build
# =======================================================================

def build_scene(stage_path="church_scene.usda"):
    stage = Usd.Stage.CreateNew(stage_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdGeom.Xform.Define(stage, "/World/Trees")
    UsdGeom.Xform.Define(stage, "/World/Cars")
    UsdGeom.Xform.Define(stage, "/World/Crowd")

    mat_stone = make_material(stage, "Stone", (0.55, 0.52, 0.48), roughness=0.85)
    mat_roof = make_material(stage, "Roof", (0.25, 0.2, 0.18), roughness=0.6)
    mat_glow = make_material(stage, "RoseGlow", (0.6, 0.5, 0.2), emissive=(2.5, 1.8, 0.6))
    mat_trunk = make_material(stage, "Trunk", (0.3, 0.2, 0.12), roughness=0.9)
    mat_leaves = make_material(stage, "Leaves", (0.2, 0.4, 0.15), roughness=0.9)
    mat_skin = make_material(stage, "Skin", (0.75, 0.57, 0.47), roughness=0.6)
    car_colors = [make_material(stage, f"CarColor_{i}", c, roughness=0.3, metallic=0.5)
                  for i, c in enumerate([(0.7, 0.1, 0.1), (0.1, 0.2, 0.5), (0.15, 0.15, 0.15)])]

    build_ground(stage, size=30.0)
    church_info = build_church(stage, mat_stone, mat_roof, mat_glow)

    hero_position = (0, -2.0, 0)
    exclude_zone = (0, 8, 8.0)  # keep crowd/trees off the church footprint

    heads = scatter_crowd(stage, n=14, hero_position=hero_position, exclude_zone=exclude_zone, mat_skin=mat_skin)
    scatter_trees(stage, n=10, exclude_zone=exclude_zone, mat_trunk=mat_trunk, mat_leaves=mat_leaves)
    scatter_cars(stage, positions=[(-5, -6, 15), (5.5, -5, -20), (-6.5, -1, 90)], mat_body_colors=car_colors)

    # Deliberate obstacles directly along the side-tracking camera's path,
    # so it visibly weaves past something instead of an empty foreground.
    make_cyl(stage, "PathTree_Trunk_A", "/World/Trees", 0.14, 2.2, (-3.0, -5.0, 1.1), material=mat_trunk)
    make_cone(stage, "PathTree_Foliage_A", "/World/Trees", 1.0, 2.0, (-3.0, -5.0, 3.1), material=mat_leaves)
    make_cyl(stage, "PathTree_Trunk_B", "/World/Trees", 0.14, 2.2, (3.2, -5.0, 1.1), material=mat_trunk)
    make_cone(stage, "PathTree_Foliage_B", "/World/Trees", 1.0, 2.0, (3.2, -5.0, 3.1), material=mat_leaves)

    hero_head = heads["hero"]

    # --- Lighting -----------------------------------------------------
    lights_path = "/World/Lights"
    UsdGeom.Xform.Define(stage, lights_path)
    dome = UsdLux.DomeLight.Define(stage, f"{lights_path}/Sky")
    dome.CreateIntensityAttr(1200.0)
    dome.CreateColorAttr(Gf.Vec3f(0.85, 0.87, 0.95))
    sun = UsdLux.DistantLight.Define(stage, f"{lights_path}/Sun")
    sun.CreateIntensityAttr(3000.0)
    sun.CreateColorAttr(Gf.Vec3f(1.0, 0.95, 0.85))
    UsdGeom.Xformable(sun).AddRotateXYZOp().Set(Gf.Vec3f(-55, 25, 0))

    # --- WideCam: static wide-angle establishing shot on the hero ------
    wide_cam = UsdGeom.Camera.Define(stage, "/World/WideCam")
    wide_cam.CreateFocalLengthAttr(18.0)          # wide lens
    wide_cam.CreateHorizontalApertureAttr(36.0)
    wide_cam.CreateVerticalApertureAttr(24.0)
    wide_cam.CreateClippingRangeAttr(Gf.Vec2f(0.1, 40.0))
    point_camera_at(wide_cam.GetPrim(), (0, -12.0, 2.2), hero_head)

    # --- SideTrackCam: strafes sideways past the two path trees, always
    # re-aimed at the hero's head via real look-at math per keyframe -----
    side_cam = UsdGeom.Camera.Define(stage, "/World/SideTrackCam")
    side_cam.CreateFocalLengthAttr(35.0)
    side_cam.CreateHorizontalApertureAttr(36.0)
    side_cam.CreateVerticalApertureAttr(24.0)
    side_cam.CreateClippingRangeAttr(Gf.Vec2f(0.1, 40.0))
    animate_camera_move(stage, side_cam.GetPrim(), keyframes=[
        (0.0, (-7.0, -5.5, 1.6), hero_head),
        (2.0, (0.0,  -4.5, 1.6), hero_head),
        (4.0, (7.0,  -5.5, 1.6), hero_head),
    ])
    stage.SetTimeCodesPerSecond(24)
    stage.SetStartTimeCode(0)
    stage.SetEndTimeCode(96)

    stage.GetRootLayer().Save()
    print(f"Saved {stage_path}")
    return stage


if __name__ == "__main__":
    build_scene()
