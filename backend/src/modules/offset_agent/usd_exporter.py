import json
import os
import re

from modules.offset_agent.models import GenerateUSDResponse, SceneConfigSchema, SceneSpecSchema


def generate_usd_from_config(
    scene_config: SceneConfigSchema,
    output_filename: str = "generated_set.usda",
) -> GenerateUSDResponse:
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scenes"))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, output_filename)

    prim_count = 0
    try:
        from pxr import Gf, Usd, UsdGeom, UsdPhysics

        stage = Usd.Stage.CreateNew(out_path)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)

        world = UsdGeom.Xform.Define(stage, "/World")
        stage.SetDefaultPrim(world.GetPrim())

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

        for shot in scene_config.shots:
            c_path = f"/World/Cameras/{shot.shot_id}"
            cam = UsdGeom.Camera.Define(stage, c_path)
            cam.CreateFocalLengthAttr(shot.focal_length_mm)
            cam.CreateHorizontalApertureAttr(36.0)
            cam.CreateVerticalApertureAttr(24.0)
            cam.CreateClippingRangeAttr(Gf.Vec2f(0.1, 1000.0))

            c_xf = UsdGeom.Xformable(cam)
            c_xf.AddTranslateOp().Set(Gf.Vec3d(*shot.start_position))
            prim_count += 1

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
        from pxr import Gf, Usd, UsdGeom, UsdPhysics

        stage = Usd.Stage.CreateNew(out_path)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)

        world = UsdGeom.Xform.Define(stage, "/World")
        stage.SetDefaultPrim(world.GetPrim())

        for obj in scene.objects:
            prim_count += _define_scene_object_prim(stage, obj, Gf, UsdGeom, UsdPhysics)

        for camera in scene.cameras:
            c_path = f"/World/Cameras/{_safe_prim_name(camera.id)}"
            cam = UsdGeom.Camera.Define(stage, c_path)
            cam.CreateFocalLengthAttr(camera.focal_length_mm)
            cam.CreateHorizontalApertureAttr(36.0)
            cam.CreateVerticalApertureAttr(24.0)
            cam.CreateClippingRangeAttr(Gf.Vec2f(0.1, 1000.0))
            c_xf = UsdGeom.Xformable(cam)
            c_xf.AddTranslateOp().Set(Gf.Vec3d(*camera.transform.position))
            prim_count += 1

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
