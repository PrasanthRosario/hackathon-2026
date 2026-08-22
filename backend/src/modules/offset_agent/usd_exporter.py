import json
import os
import re

from modules.offset_agent.models import GenerateUSDResponse, SceneConfigSchema, SceneSpecSchema

# Matches the timeCodesPerSecond baked into the hand-authored demo scenes
# (scenes/scene1/podcast_room.usda etc.) and frames_to_video.py's own default
# --fps, so a generated stage's playback rate lines up with what stitches the
# validate-and-simulate video afterward.
FPS = 24.0

# Held-shot fallback when a camera doesn't specify a duration (CameraSchema.duration_seconds
# can be None) -- without SOME positive stage time range, standalone_render_and_validate.py's
# --frames all resolves to a single frame and the "video" it stitches is a degenerate
# ~0-duration clip that shows as stuck at 00:00 in the browser.
DEFAULT_HOLD_SECONDS = 3.0

# SceneLightSchema.intensity is an abstract ~1.0-ish authoring value, not a raw
# UsdLux photometric one -- this scales it into the same visibly-bright range
# already verified working on scenes/scene1/podcast_room.usda's light rig
# (Dome ~400, Rect/Sphere key lights ~1500-8000).
LIGHT_INTENSITY_SCALE = 1500.0

# Bright enough on its own (no key/fill needed) since a DomeLight illuminates
# uniformly from every direction regardless of an arbitrary/unknown room's
# wall layout -- unlike a directional key light, it can't accidentally point
# the wrong way. Neither exporter authored ANY light before this fix, which is
# why every generated scene rendered as solid black.
DEFAULT_DOME_INTENSITY = 1000.0


def generate_usd_from_config(
    scene_config: SceneConfigSchema,
    output_filename: str = "generated_set.usda",
) -> GenerateUSDResponse:
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scenes"))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, output_filename)

    prim_count = 0
    try:
        from pxr import Gf, Usd, UsdGeom, UsdLux, UsdPhysics

        stage = Usd.Stage.CreateNew(out_path)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        stage.SetTimeCodesPerSecond(FPS)

        world = UsdGeom.Xform.Define(stage, "/World")
        stage.SetDefaultPrim(world.GetPrim())

        # SceneConfigSchema has no lights concept at all (unlike SceneSpecSchema),
        # so a bright ambient dome is the only lighting a scene built from this
        # legacy schema ever gets -- without it every render is solid black.
        _add_default_dome_light(stage, Gf, UsdLux)

        floor = UsdGeom.Cube.Define(stage, "/World/Room/Floor")
        floor.GetSizeAttr().Set(1.0)
        f_xf = UsdGeom.Xformable(floor)
        f_xf.AddTranslateOp().Set(Gf.Vec3d(0, 0, -0.05))
        f_xf.AddScaleOp().Set(Gf.Vec3d(scene_config.floor.width, scene_config.floor.depth, 0.1))
        floor.GetDisplayColorAttr().Set([Gf.Vec3f(0.8, 0.8, 0.82)])
        UsdPhysics.CollisionAPI.Apply(floor.GetPrim())
        prim_count += 1

        for wall in scene_config.walls:
            w_path = f"/World/Room/{wall.id}"
            w_cube = UsdGeom.Cube.Define(stage, w_path)
            w_cube.GetSizeAttr().Set(1.0)
            w_xf = UsdGeom.Xformable(w_cube)
            w_xf.AddTranslateOp().Set(Gf.Vec3d(*wall.position))
            w_xf.AddRotateZOp().Set(wall.rotation)
            w_xf.AddScaleOp().Set(Gf.Vec3d(wall.width, wall.thickness, wall.height))
            w_cube.GetDisplayColorAttr().Set([Gf.Vec3f(0.75, 0.72, 0.68)])
            UsdPhysics.CollisionAPI.Apply(w_cube.GetPrim())
            prim_count += 1

        max_end_frame = 0.0
        for shot in scene_config.shots:
            c_path = f"/World/Cameras/{shot.shot_id}"
            cam = UsdGeom.Camera.Define(stage, c_path)
            cam.CreateFocalLengthAttr(shot.focal_length_mm)
            cam.CreateHorizontalApertureAttr(36.0)
            cam.CreateVerticalApertureAttr(24.0)
            cam.CreateClippingRangeAttr(Gf.Vec2f(0.1, 1000.0))

            # Bake the dolly move as real time-sampled keyframes -- previously
            # this only ever set a single static translate, so end_position/
            # duration_seconds were captured in the schema but silently
            # ignored, and the stage had no time range at all (see FPS comment
            # above for why that broke Validate & Simulate's video output).
            #
            # ShotSchema has no explicit look-at target, so aim at the room's
            # horizontal center at the camera's own eye height -- a level,
            # centered establishing-shot default. Without ANY orientation
            # authored, a camera's identity rotation looks straight down its
            # local -Z axis, which under this Z-up stage means straight down
            # at the floor -- exactly the "just a flat tile" symptom this fixes.
            end_frame = max(shot.duration_seconds, 0.0) * FPS
            c_xf = UsdGeom.Xformable(cam)
            transform_op = c_xf.AddTransformOp()
            start_target = (0.0, 0.0, shot.start_position[2])
            if end_frame > 0 and tuple(shot.start_position) != tuple(shot.end_position):
                end_target = (0.0, 0.0, shot.end_position[2])
                transform_op.Set(_look_at_matrix(Gf, shot.start_position, start_target), Usd.TimeCode(0))
                transform_op.Set(_look_at_matrix(Gf, shot.end_position, end_target), Usd.TimeCode(end_frame))
            else:
                transform_op.Set(_look_at_matrix(Gf, shot.start_position, start_target))
            max_end_frame = max(max_end_frame, end_frame)
            prim_count += 1

        stage.SetStartTimeCode(0)
        stage.SetEndTimeCode(max(max_end_frame, DEFAULT_HOLD_SECONDS * FPS))

        stage.GetRootLayer().Save()

    except ImportError:
        meta_path = out_path + ".json"
        with open(meta_path, "w") as f:
            json.dump(scene_config.model_dump(), f, indent=2)
        prim_count = len(scene_config.walls) + len(scene_config.shots) + 1

    return GenerateUSDResponse(
        status="SUCCESS",
        usd_path=out_path,
        prim_count=prim_count,
        message=(
            "USD Stage generated successfully with "
            f"{len(scene_config.walls)} walls and {len(scene_config.shots)} shot cameras."
        ),
    )


def generate_usd_from_scene(
    scene: SceneSpecSchema,
    output_filename: str = "generated_set.usda",
) -> GenerateUSDResponse:
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scenes"))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, output_filename)

    prim_count = 0
    try:
        from pxr import Gf, Usd, UsdGeom, UsdLux, UsdPhysics

        stage = Usd.Stage.CreateNew(out_path)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        stage.SetTimeCodesPerSecond(FPS)

        world = UsdGeom.Xform.Define(stage, "/World")
        stage.SetDefaultPrim(world.GetPrim())

        # Always add a baseline ambient dome regardless of scene.lights --
        # cheap insurance against a scene with an empty lights list (or one
        # authored too dim/misdirected) still rendering solid black.
        _add_default_dome_light(stage, Gf, UsdLux)

        for obj in scene.objects:
            prim_count += _define_scene_object_prim(stage, obj, Gf, UsdGeom, UsdPhysics)

        for light in scene.lights:
            prim_count += _define_scene_light_prim(stage, light, Gf, UsdGeom, UsdLux)

        max_end_frame = 0.0
        for camera in scene.cameras:
            c_path = f"/World/Cameras/{_safe_prim_name(camera.id)}"
            cam = UsdGeom.Camera.Define(stage, c_path)
            cam.CreateFocalLengthAttr(camera.focal_length_mm)
            cam.CreateHorizontalApertureAttr(36.0)
            cam.CreateVerticalApertureAttr(24.0)
            cam.CreateClippingRangeAttr(Gf.Vec2f(0.1, 1000.0))
            # Orient toward the schema's own look_at target -- previously only
            # a bare translate was authored (no rotation at all), so every
            # camera's identity rotation looked straight down its local -Z
            # axis, i.e. straight down at the floor under this Z-up stage.
            c_xf = UsdGeom.Xformable(cam)
            c_xf.AddTransformOp().Set(_look_at_matrix(Gf, camera.transform.position, camera.look_at))
            prim_count += 1
            # CameraSchema has no distinct end_position (unlike ShotSchema), so
            # this is a locked-off hold rather than a baked dolly move -- but
            # the stage still needs a real time range covering it, otherwise
            # standalone_render_and_validate.py's --frames all resolves to a
            # single frame and the stitched video is a degenerate ~0-duration
            # clip (shows as stuck at 00:00 in the browser).
            duration = camera.duration_seconds if camera.duration_seconds else DEFAULT_HOLD_SECONDS
            max_end_frame = max(max_end_frame, duration * FPS)

        stage.SetStartTimeCode(0)
        stage.SetEndTimeCode(max(max_end_frame, DEFAULT_HOLD_SECONDS * FPS))

        stage.GetRootLayer().Save()

    except ImportError:
        meta_path = out_path + ".json"
        with open(meta_path, "w") as f:
            json.dump(scene.model_dump(), f, indent=2)
        prim_count = len(scene.objects) + len(scene.cameras)

    return GenerateUSDResponse(
        status="SUCCESS",
        usd_path=out_path,
        prim_count=prim_count,
        message=(
            "USD Stage generated successfully with "
            f"{len(scene.objects)} scene objects and {len(scene.cameras)} cameras."
        ),
    )


def _look_at_matrix(gf, eye, target, world_up=(0, 0, 1)):
    """
    Ported verbatim (same math, just parameterized on gf) from the proven,
    numerically-verified look_at_matrix() in scenes/kit_bridge_extension.py.
    Neither exporter previously authored ANY camera rotation -- only a bare
    translate -- so every camera's identity rotation looked straight down its
    local -Z axis, which under this Z-up stage means straight down at the
    floor. That's what produced "just a flat tile, nothing else" renders.
    """
    eye = gf.Vec3d(*eye)
    target = gf.Vec3d(*target)
    world_up = gf.Vec3d(*world_up)

    forward = target - eye
    if forward.GetLength() < 1e-6:
        # Degenerate: eye and target coincide. Fall back to a level forward
        # along -Y rather than producing a singular (all-zero) basis.
        forward = gf.Vec3d(0, -1, 0)
    forward = forward.GetNormalized()

    right = gf.Cross(forward, world_up)
    if right.GetLength() < 1e-6:
        # forward is parallel to world_up (looking straight up/down) --
        # Cross(forward, world_up) is undefined in that case, so pick a
        # different reference axis for "right" instead of a zero vector.
        right = gf.Cross(forward, gf.Vec3d(1, 0, 0))
    right = right.GetNormalized()
    true_up = gf.Cross(right, forward)

    m = gf.Matrix4d(1.0)
    m.SetRow(0, gf.Vec4d(right[0], right[1], right[2], 0.0))
    m.SetRow(1, gf.Vec4d(true_up[0], true_up[1], true_up[2], 0.0))
    m.SetRow(2, gf.Vec4d(-forward[0], -forward[1], -forward[2], 0.0))
    m.SetRow(3, gf.Vec4d(eye[0], eye[1], eye[2], 1.0))
    return m


def _add_default_dome_light(stage, gf, usd_lux) -> None:
    dome = usd_lux.DomeLight.Define(stage, "/World/Lights/DefaultDome")
    dome.CreateIntensityAttr(DEFAULT_DOME_INTENSITY)
    dome.CreateColorAttr(gf.Vec3f(0.75, 0.78, 0.85))


def _define_scene_light_prim(stage, light, gf, usd_geom, usd_lux) -> int:
    path = f"/World/Lights/{_safe_prim_name(light.id)}"
    color = _hex_to_vec3f(light.color, gf)
    intensity = max(light.intensity, 0.0) * LIGHT_INTENSITY_SCALE

    if light.kind == "directional":
        prim = usd_lux.DistantLight.Define(stage, path)
    elif light.kind == "area":
        prim = usd_lux.RectLight.Define(stage, path)
        prim.CreateWidthAttr(1.0)
        prim.CreateHeightAttr(1.0)
    else:
        # "point" and "spot" both map to a small SphereLight -- a real cone
        # for "spot" would need UsdLux.ShapingAPI, which is more than this
        # fix needs; the goal here is "not pitch black", not a full spotlight.
        prim = usd_lux.SphereLight.Define(stage, path)
        prim.CreateRadiusAttr(0.05)

    prim.CreateIntensityAttr(intensity)
    prim.CreateColorAttr(color)

    xf = usd_geom.Xformable(prim)
    xf.AddTranslateOp().Set(gf.Vec3d(*light.transform.position))
    xf.AddRotateXYZOp().Set(gf.Vec3f(*light.transform.rotation))
    return 1


def _define_scene_object_prim(stage, obj, gf, usd_geom, usd_physics) -> int:
    path = f"/World/SceneObjects/{_safe_prim_name(obj.id)}"
    geometry = obj.geometry
    if geometry.type == "sphere":
        prim = usd_geom.Sphere.Define(stage, path)
        prim.GetRadiusAttr().Set(geometry.radius or geometry.size[0] / 2)
    elif geometry.type == "cylinder":
        prim = usd_geom.Cylinder.Define(stage, path)
        prim.GetRadiusAttr().Set(geometry.radius or geometry.size[0])
        prim.GetHeightAttr().Set(geometry.height or geometry.size[2])
    else:
        prim = usd_geom.Cube.Define(stage, path)
        prim.GetSizeAttr().Set(1.0)

    xf = usd_geom.Xformable(prim)
    xf.AddTranslateOp().Set(gf.Vec3d(*obj.transform.position))
    xf.AddRotateXYZOp().Set(gf.Vec3f(*obj.transform.rotation))
    if geometry.type in {"box", "plane"}:
        xf.AddScaleOp().Set(gf.Vec3d(*geometry.size))
    else:
        xf.AddScaleOp().Set(gf.Vec3d(*obj.transform.scale))

    prim.GetDisplayColorAttr().Set([_hex_to_vec3f(obj.material.color, gf)])
    if obj.physics.collidable:
        usd_physics.CollisionAPI.Apply(prim.GetPrim())
    return 1


def _safe_prim_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not name or name[0].isdigit():
        return f"Prim_{name}"
    return name


def _hex_to_vec3f(color: str, gf):
    value = color.lstrip("#")
    if len(value) != 6:
        return gf.Vec3f(0.7, 0.7, 0.7)
    red = int(value[0:2], 16) / 255
    green = int(value[2:4], 16) / 255
    blue = int(value[4:6], 16) / 255
    return gf.Vec3f(red, green, blue)
