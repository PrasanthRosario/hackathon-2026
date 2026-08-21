"""
generate_studio_room.py

A more atmospheric podcast studio, styled after the reference photos:
dark ceiling grid, warm/cool linear lighting, colorful accent wall
panels, hanging greenery, and a backdrop screen -- built with real
USD materials (UsdShade + UsdPreviewSurface), not just flat display
colors, so it renders properly under Isaac Sim's RTX path tracer.

Includes a seated mannequin stand-in for the host. This is a
blockout, not a realistic human -- see the note at the bottom of
this file for how to swap in a real character asset later.

Produces studio_room.usda.
"""

from pxr import Usd, UsdGeom, UsdShade, UsdLux, UsdPhysics, Sdf, Gf


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


# =======================================================================
# Geometry helpers
# =======================================================================

def make_box(stage, name, size, center, parent, material=None, collider=True):
    cube = UsdGeom.Cube.Define(stage, f"{parent}/{name}")
    cube.CreateSizeAttr(1.0)
    xf = UsdGeom.Xformable(cube)
    xf.AddTranslateOp().Set(Gf.Vec3d(*center))
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


def make_sphere(stage, name, parent, radius, center, material=None):
    sph = UsdGeom.Sphere.Define(stage, f"{parent}/{name}")
    sph.CreateRadiusAttr(radius)
    UsdGeom.Xformable(sph).AddTranslateOp().Set(Gf.Vec3d(*center))
    if material:
        bind(sph.GetPrim(), material)
    return sph


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
    """keyframes: list of (time_seconds, eye, target) tuples. Bakes a
    real USD time-sampled move so there's more than one frame for
    per-frame shot validation to actually check."""
    stage.SetTimeCodesPerSecond(fps)
    stage.SetStartTimeCode(keyframes[0][0] * fps)
    stage.SetEndTimeCode(keyframes[-1][0] * fps)

    xf = UsdGeom.Xformable(camera_prim)
    xf.ClearXformOpOrder()
    op = xf.AddTransformOp()
    for t_sec, eye, target in keyframes:
        op.Set(look_at_matrix(eye, target), Usd.TimeCode(t_sec * fps))


# =======================================================================
# Mannequin stand-in for the host -- a bounding-shape blockout, not a
# realistic figure. Good enough for frustum/framing validation and for
# checking the shot composes correctly; swap for a real character
# asset (see note at bottom) if you need it to actually look human.
# =======================================================================

def build_mannequin(stage, parent, seat_pos, skin_mat, shirt_mat):
    x, y, seat_h = seat_pos
    hip_z = seat_h + 0.05
    torso_h = 0.5
    make_cyl(stage, "Torso", parent, 0.16, torso_h, (x, y, hip_z + torso_h / 2), material=shirt_mat)
    neck_z = hip_z + torso_h
    make_cyl(stage, "Neck", parent, 0.05, 0.06, (x, y, neck_z + 0.03), material=skin_mat)
    make_sphere(stage, "Head", parent, 0.11, (x, y, neck_z + 0.17), material=skin_mat)
    # Upper legs, seated (horizontal-ish)
    for side, sign in [("L", -1), ("R", 1)]:
        make_cyl(stage, f"Thigh_{side}", parent, 0.09, 0.42, (x + sign * 0.11, y - 0.15, hip_z),
                 material=shirt_mat, rotate_xyz=(90, 0, 0))
        make_cyl(stage, f"Shin_{side}", parent, 0.07, 0.42, (x + sign * 0.11, y - 0.36, hip_z - 0.21),
                 material=shirt_mat)
    # Arms, resting toward desk
    for side, sign in [("L", -1), ("R", 1)]:
        make_cyl(stage, f"UpperArm_{side}", parent, 0.055, 0.28, (x + sign * 0.21, y, hip_z + torso_h - 0.1),
                 material=shirt_mat, rotate_xyz=(15, 0, 0))
        make_cyl(stage, f"Forearm_{side}", parent, 0.045, 0.26, (x + sign * 0.21, y + 0.2, hip_z + torso_h - 0.28),
                 material=skin_mat, rotate_xyz=(75, 0, 0))


# =======================================================================
# Build
# =======================================================================

def build_room(stage_path="studio_room.usda", mode="good"):
    """mode: "good" (framed on host), "bad" (aimed off-set into the
    void -- for the frustum/off-set check), or "camera_stuck" (eye
    ends up embedded inside a wall -- for the camera-body collision
    check, isolated from the off-set check by keeping the target on
    the host)."""
    stage = Usd.Stage.CreateNew(stage_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())

    # --- Materials, styled after the reference photos -------------------
    mat_ceiling = make_material(stage, "Ceiling", (0.05, 0.05, 0.06), roughness=0.8)
    mat_floor = make_material(stage, "Floor", (0.5, 0.48, 0.45), roughness=0.5)
    mat_wall_dark = make_material(stage, "WallDark", (0.08, 0.08, 0.09), roughness=0.7)
    mat_wall_pink = make_material(stage, "WallPink", (0.85, 0.55, 0.6), roughness=0.9)
    mat_wall_yellow = make_material(stage, "WallYellow", (0.85, 0.75, 0.35), roughness=0.9)
    mat_wall_blue = make_material(stage, "WallBlue", (0.45, 0.6, 0.75), roughness=0.9)
    mat_wall_green = make_material(stage, "WallGreen", (0.5, 0.65, 0.5), roughness=0.9)
    mat_light_warm = make_material(stage, "LightWarm", (1.0, 0.9, 0.7), emissive=(3.0, 2.6, 1.8))
    mat_light_red = make_material(stage, "LightRed", (1.0, 0.2, 0.2), emissive=(4.0, 0.3, 0.3))
    mat_wood = make_material(stage, "Wood", (0.35, 0.22, 0.12), roughness=0.4)
    mat_metal_black = make_material(stage, "MetalBlack", (0.05, 0.05, 0.05), roughness=0.3, metallic=0.6)
    mat_leaf = make_material(stage, "Leaf", (0.15, 0.4, 0.15), roughness=0.8)
    mat_screen = make_material(stage, "Screen", (0.02, 0.02, 0.03), emissive=(0.1, 0.15, 0.25), roughness=0.2)
    mat_skin = make_material(stage, "Skin", (0.75, 0.57, 0.47), roughness=0.6)
    mat_shirt = make_material(stage, "Shirt", (0.25, 0.3, 0.45), roughness=0.7)

    # --- Room shell -------------------------------------------------------
    room_w, room_d, room_h = 6.5, 5.5, 2.9
    wall_t, gap_w = 0.1, 1.1
    boundary_path = "/World/SetBoundary"
    boundary = UsdGeom.Xform.Define(stage, boundary_path)
    boundary.GetPrim().CreateAttribute("is_set_boundary", Sdf.ValueTypeNames.Bool).Set(True)

    make_box(stage, "Floor", (room_w, room_d, wall_t), (0, 0, -wall_t / 2), boundary_path, material=mat_floor)
    make_box(stage, "Ceiling", (room_w, room_d, 0.08), (0, 0, room_h + 0.04), boundary_path, material=mat_ceiling, collider=False)
    make_box(stage, "Wall_North", (room_w, wall_t, room_h), (0, room_d / 2, room_h / 2), boundary_path, material=mat_wall_dark)
    make_box(stage, "Wall_West", (wall_t, room_d, room_h), (-room_w / 2, 0, room_h / 2), boundary_path, material=mat_wall_dark)

    seg_d = (room_d - gap_w) / 2
    make_box(stage, "Wall_East_A", (wall_t, seg_d, room_h), (room_w / 2, gap_w / 2 + seg_d / 2, room_h / 2), boundary_path, material=mat_wall_dark)
    make_box(stage, "Wall_East_B", (wall_t, seg_d, room_h), (room_w / 2, -(gap_w / 2 + seg_d / 2), room_h / 2), boundary_path, material=mat_wall_dark)

    # South wall: colorful accent panels, like the reference photo's
    # pink/yellow/blue/green wall blocks
    panel_w = room_w / 4
    for i, mat in enumerate([mat_wall_pink, mat_wall_yellow, mat_wall_blue, mat_wall_green]):
        px = -room_w / 2 + panel_w * (i + 0.5)
        make_box(stage, f"Wall_South_Panel_{i}", (panel_w, wall_t, room_h), (px, -room_d / 2, room_h / 2),
                 boundary_path, material=mat)

    void_path = "/World/Backstage_Void"
    void = UsdGeom.Xform.Define(stage, void_path)
    void.GetPrim().CreateAttribute("is_off_set", Sdf.ValueTypeNames.Bool).Set(True)
    make_box(stage, "VoidPlane", (4.0, gap_w, room_h), (room_w / 2 + 2.0, 0, room_h / 2),
             void_path, material=None, collider=False)

    # --- Ceiling grid + linear lights (dark grid, warm + red strips) ------
    dress = "/World/SetDressing"
    for gx in range(-2, 3):
        safe_name = f"CeilGrid_X{gx}".replace("-", "n")
        make_box(stage, safe_name, (0.04, room_d - 0.4, 0.03), (gx * 1.1, 0, room_h - 0.02),
                 dress, material=mat_metal_black, collider=False)
    for i in range(3):
        lx = -1.5 + i * 1.5
        make_box(stage, f"LightStrip_{i}", (1.2, 0.06, 0.03), (lx, 0.8, room_h - 0.03),
                 dress, material=mat_light_warm, collider=False)
        make_box(stage, f"LightAccentRed_{i}", (1.2, 0.03, 0.02), (lx, 1.0, room_h - 0.05),
                 dress, material=mat_light_red, collider=False)

    # --- Hanging plants (sphere clusters on thin "vine" cylinders) --------
    for px, py in [(-2.0, 1.5), (2.0, 1.8), (0.0, -1.5)]:
        make_cyl(stage, f"Vine_{px}_{py}".replace("-", "n").replace(".", "p"), dress, 0.01, 0.4,
                 (px, py, room_h - 0.25), material=mat_metal_black, collider=False)
        for j in range(4):
            import random
            random.seed(hash((px, py, j)) % 1000)
            ox, oy = random.uniform(-0.15, 0.15), random.uniform(-0.15, 0.15)
            make_sphere(stage, f"Leaf_{px}_{py}_{j}".replace("-", "n").replace(".", "p"), dress,
                        0.08, (px + ox, py + oy, room_h - 0.45 - j * 0.05), material=mat_leaf)

    # --- Desk, chair, backdrop screen --------------------------------------
    desk_w, desk_d, desk_h, desk_top_t = 1.7, 0.7, 0.75, 0.05
    desk_x, desk_y = 0, 0.6
    make_box(stage, "Desk_Top", (desk_w, desk_d, desk_top_t), (desk_x, desk_y, desk_h), dress, material=mat_wood)
    for lx, ly in [(-desk_w/2+0.08, desk_y-desk_d/2+0.08), (desk_w/2-0.08, desk_y-desk_d/2+0.08),
                   (-desk_w/2+0.08, desk_y+desk_d/2-0.08), (desk_w/2-0.08, desk_y+desk_d/2-0.08)]:
        make_cyl(stage, f"DeskLeg_{lx:.2f}_{ly:.2f}".replace("-", "n").replace(".", "p"), dress,
                 0.03, desk_h - desk_top_t, (lx, ly, (desk_h - desk_top_t)/2), material=mat_metal_black)

    make_box(stage, "BackdropScreen", (1.4, 0.05, 0.8), (0, room_d/2 - wall_t - 0.03, 1.6),
             dress, material=mat_screen, collider=False)

    seat_y = desk_y - desk_d / 2 - 0.55
    seat_h = 0.45
    make_box(stage, "Chair_Seat", (0.45, 0.45, 0.06), (0, seat_y, seat_h), dress, material=mat_metal_black)
    make_box(stage, "Chair_Back", (0.45, 0.06, 0.5), (0, seat_y - 0.2, seat_h + 0.28), dress, material=mat_metal_black)
    make_cyl(stage, "Chair_Post", dress, 0.04, seat_h, (0, seat_y, seat_h/2), material=mat_metal_black)

    build_mannequin(stage, dress, (0, seat_y, seat_h + 0.06), mat_skin, mat_shirt)

    # --- Real lights (not just emissive materials) -------------------------
    # Emissive materials glow, but don't illuminate anything around them.
    # Actual light prims are what create shadows, bounce light, and the
    # soft falloff that reads as "lit" rather than "flat."
    lights_path = "/World/Lights"
    UsdGeom.Xform.Define(stage, lights_path)

    # Soft overall fill, like bounced ambient light in the reference photos.
    dome = UsdLux.DomeLight.Define(stage, f"{lights_path}/Dome")
    dome.CreateIntensityAttr(400.0)
    dome.CreateColorAttr(Gf.Vec3f(0.7, 0.75, 0.85))  # cool ambient, matches the dark ceiling mood

    # Key light: soft box above/in front of the host, like the ring light
    # in the reference photos.
    key = UsdLux.RectLight.Define(stage, f"{lights_path}/Key")
    key.CreateIntensityAttr(8000.0)
    key.CreateWidthAttr(0.5)
    key.CreateHeightAttr(0.5)
    key.CreateColorAttr(Gf.Vec3f(1.0, 0.95, 0.85))  # warm
    UsdGeom.Xformable(key).AddTranslateOp().Set(Gf.Vec3d(0, seat_y - 1.0, 1.9))
    UsdGeom.Xformable(key).AddRotateXYZOp().Set(Gf.Vec3f(-40, 0, 0))

    # Rim/accent light from behind, picking up the red ceiling accent color.
    rim = UsdLux.RectLight.Define(stage, f"{lights_path}/Rim")
    rim.CreateIntensityAttr(4000.0)
    rim.CreateWidthAttr(1.2)
    rim.CreateHeightAttr(0.1)
    rim.CreateColorAttr(Gf.Vec3f(1.0, 0.3, 0.3))
    UsdGeom.Xformable(rim).AddTranslateOp().Set(Gf.Vec3d(0, room_d/2 - 0.3, room_h - 0.1))
    UsdGeom.Xformable(rim).AddRotateXYZOp().Set(Gf.Vec3f(90, 0, 0))

    # Fill light from the colorful accent wall side, bouncing some of that
    # pastel color into the scene.
    fill = UsdLux.RectLight.Define(stage, f"{lights_path}/Fill")
    fill.CreateIntensityAttr(1500.0)
    fill.CreateWidthAttr(2.0)
    fill.CreateHeightAttr(1.0)
    fill.CreateColorAttr(Gf.Vec3f(0.8, 0.7, 0.75))
    UsdGeom.Xformable(fill).AddTranslateOp().Set(Gf.Vec3d(0, -room_d/2 + 0.2, 1.5))
    UsdGeom.Xformable(fill).AddRotateXYZOp().Set(Gf.Vec3f(90, 0, 0))


    # --- Camera, aimed at the host's head height ---------------------------
    camera = UsdGeom.Camera.Define(stage, "/World/MainCamera")
    camera.CreateFocalLengthAttr(35.0)
    camera.CreateHorizontalApertureAttr(36.0)
    camera.CreateVerticalApertureAttr(24.0)
    camera.CreateClippingRangeAttr(Gf.Vec2f(0.1, 8.0))
    head_target = (0, seat_y, seat_h + 0.55)  # head height of the seated mannequin

    if mode == "bad":
        # Same room, same camera path -- but the dolly ends up aimed
        # through the off-set door gap into the backstage void instead
        # of the host, so run_validation should flip to FLAGGED.
        void_target = (room_w / 2 + 2.0, 0, room_h / 2)
        animate_camera_move(stage, camera.GetPrim(), [
            (0.0, (0, seat_y - 1.9, 1.6), head_target),  # starts on the host
            (3.0, (0, seat_y - 1.3, 1.4), void_target),  # swings into the void
        ])
    elif mode == "camera_stuck":
        # Target stays on the host the whole time (frustum/off-set
        # check should stay OK) but the dolly overshoots into
        # Wall_West -- isolates the camera-body collision check from
        # the off-set check so you can confirm they fire independently.
        wall_west_center = (-room_w / 2, 0, room_h / 2)
        animate_camera_move(stage, camera.GetPrim(), [
            (0.0, (0, seat_y - 1.9, 1.6), head_target),      # wide establishing
            (3.0, wall_west_center, head_target),             # overshoots into the wall
        ])
    else:
        animate_camera_move(stage, camera.GetPrim(), [
            (0.0, (0, seat_y - 1.9, 1.6), head_target),   # wide establishing
            (3.0, (0, seat_y - 1.3, 1.4), head_target),   # dolly-in to host
        ])

    stage.GetRootLayer().Save()
    print(f"Saved {stage_path}")
    return stage


if __name__ == "__main__":
    build_room("studio_room.usda", mode="good")
    build_room("studio_room_bad_shot.usda", mode="bad")
    build_room("studio_room_camera_stuck.usda", mode="camera_stuck")

# -----------------------------------------------------------------------
# To get an actually realistic person instead of this mannequin:
# import a real character asset (e.g. an Omniverse "People" asset, or a
# Mixamo character exported to USD/FBX and converted) and reference it
# in as a prim under /World/SetDressing, positioned at the same seat_y /
# seat_h coordinates used above -- everything else (camera aim, frustum
# validation) stays identical since it targets a position, not this
# specific geometry.
# -----------------------------------------------------------------------
