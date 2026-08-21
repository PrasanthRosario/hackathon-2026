from copy import deepcopy
from typing import Any

from modules.offset_agent.models import (
    CameraSchema,
    FloorSchema,
    SceneConfigSchema,
    SceneObjectSchema,
    SceneOperationSchema,
    SceneSpecSchema,
    ShotSchema,
    WallSchema,
)


def default_scene_spec() -> SceneSpecSchema:
    return SceneSpecSchema(
        name="Untitled Film Set",
        objects=[
            SceneObjectSchema(
                id="floor",
                name="Floor",
                kind="floor",
                geometry={"type": "box", "size": (8.0, 6.0, 0.1)},
                transform={"position": (0.0, 0.0, -0.05)},
                material={"color": "#c2c4c7", "roughness": 0.8},
                tags=["set_boundary"],
            )
        ],
        lights=[
            {
                "id": "key_light",
                "kind": "point",
                "transform": {"position": (-2.5, -2.0, 2.8)},
                "color": "#ffffff",
                "intensity": 1.2,
            }
        ],
    )


def scene_config_to_spec(config: SceneConfigSchema | None) -> SceneSpecSchema:
    if config is None:
        return default_scene_spec()

    objects = [
        SceneObjectSchema(
            id="floor",
            name="Floor",
            kind="floor",
            geometry={"type": "box", "size": (config.floor.width, config.floor.depth, 0.1)},
            transform={"position": (0.0, 0.0, -0.05)},
            material={"color": "#c2c4c7", "roughness": 0.8},
            tags=["set_boundary"],
        )
    ]
    for wall in config.walls:
        objects.append(
            SceneObjectSchema(
                id=wall.id,
                name=wall.id.replace("_", " ").title(),
                kind="wall",
                geometry={"type": "box", "size": (wall.width, wall.thickness, wall.height)},
                transform={
                    "position": wall.position,
                    "rotation": (0.0, 0.0, wall.rotation),
                },
                material={"color": "#b8b2aa", "roughness": 0.85},
                tags=["set_boundary", "wall"],
            )
        )

    cameras = [
        CameraSchema(
            id=shot.shot_id,
            focal_length_mm=shot.focal_length_mm,
            transform={"position": shot.start_position},
            look_at=shot.end_position,
            duration_seconds=shot.duration_seconds,
        )
        for shot in config.shots
    ]

    return SceneSpecSchema(name="Film Set", objects=objects, cameras=cameras)


def scene_spec_to_config(scene: SceneSpecSchema) -> SceneConfigSchema:
    floor_object = next((obj for obj in scene.objects if obj.kind == "floor"), None)
    floor_size = floor_object.geometry.size if floor_object else (8.0, 6.0, 0.1)
    walls = []

    for obj in scene.objects:
        if obj.kind != "wall":
            continue
        size_x, size_y, size_z = obj.geometry.size
        width = size_x
        thickness = size_y
        rotation = obj.transform.rotation[2]
        if size_x < size_y and rotation == 0:
            width = size_y
            thickness = size_x
            rotation = 90.0
        walls.append(
            WallSchema(
                id=obj.id,
                position=obj.transform.position,
                width=width,
                height=size_z,
                thickness=thickness,
                rotation=rotation,
            )
        )

    shots = [
        ShotSchema(
            shot_id=camera.id,
            focal_length_mm=camera.focal_length_mm,
            start_position=camera.transform.position,
            end_position=camera.look_at,
            duration_seconds=camera.duration_seconds or 5.0,
        )
        for camera in scene.cameras
    ]

    return SceneConfigSchema(
        floor=FloorSchema(width=floor_size[0], depth=floor_size[1]),
        walls=walls,
        shots=shots,
    )


def apply_scene_operations(
    scene: SceneSpecSchema,
    operations: list[SceneOperationSchema],
) -> SceneSpecSchema:
    next_scene = deepcopy(scene)

    for operation in operations:
        if operation.type == "add_object" and operation.object:
            next_scene.objects = [obj for obj in next_scene.objects if obj.id != operation.object.id]
            next_scene.objects.append(operation.object)
        elif operation.type == "update_object" and operation.id:
            _patch_item(next_scene.objects, operation.id, operation.patch)
        elif operation.type == "delete_object" and operation.id:
            next_scene.objects = [obj for obj in next_scene.objects if obj.id != operation.id]
        elif operation.type == "add_camera" and operation.camera:
            next_scene.cameras = [cam for cam in next_scene.cameras if cam.id != operation.camera.id]
            next_scene.cameras.append(operation.camera)
        elif operation.type == "update_camera" and operation.id:
            _patch_item(next_scene.cameras, operation.id, operation.patch)
        elif operation.type == "add_light" and operation.light:
            next_scene.lights = [light for light in next_scene.lights if light.id != operation.light.id]
            next_scene.lights.append(operation.light)

    next_scene.objects = [_normalize_preview_object(obj) for obj in next_scene.objects]
    return next_scene


def validate_scene(scene: SceneSpecSchema) -> list[str]:
    issues: list[str] = []

    if not any(obj.kind == "floor" for obj in scene.objects):
        issues.append("Scene needs a floor object for orientation and physics grounding.")
    if len([obj for obj in scene.objects if obj.kind == "wall"]) == 0 and not _is_open_world_scene(scene):
        issues.append("Scene has no walls yet.")
    for camera in scene.cameras:
        if camera.focal_length_mm < 14:
            issues.append(f"{camera.id} uses an extremely wide focal length.")
    return issues


def summarize_scene(scene: SceneSpecSchema) -> str:
    walls = len([obj for obj in scene.objects if obj.kind == "wall"])
    props = len([obj for obj in scene.objects if obj.kind not in {"floor", "wall"}])
    return (
        f"{scene.name}: {len(scene.objects)} objects, {walls} walls, "
        f"{props} props, {len(scene.cameras)} cameras, {len(scene.lights)} lights."
    )


def _patch_item(items: list[Any], item_id: str, patch: dict[str, Any]) -> None:
    for index, item in enumerate(items):
        if item.id != item_id:
            continue
        data = item.model_dump()
        for path, value in patch.items():
            _set_nested_value(data, path.split("."), value)
        items[index] = item.__class__(**data)
        return


def _set_nested_value(data: dict[str, Any], path: list[str], value: Any) -> None:
    target = data
    for key in path[:-1]:
        target = target.setdefault(key, {})
    target[path[-1]] = value


def _is_open_world_scene(scene: SceneSpecSchema) -> bool:
    semantic_text = " ".join(
        [
            scene.name,
            str(scene.metadata),
            *[
                f"{obj.id} {obj.name} {obj.kind} {' '.join(obj.tags)}"
                for obj in scene.objects
            ],
        ]
    ).lower()
    return any(token in semantic_text for token in ["open_world", "open world", "courtyard", "church"])


def _normalize_preview_object(obj: SceneObjectSchema) -> SceneObjectSchema:
    semantic_name = f"{obj.id} {obj.name} {obj.kind} {' '.join(obj.tags)}".lower()
    has_default_geometry = obj.geometry.size == (1.0, 1.0, 1.0)
    has_default_position = obj.transform.position == (0.0, 0.0, 0.0)

    if "hero" in semantic_name:
        return _with_preview_defaults(
            obj,
            kind="hero",
            geometry={"type": "box", "size": (0.45, 0.28, 1.75)},
            transform={"position": (0.0, -1.5, 0.875)},
            material={"color": "#ffffff", "roughness": 0.55},
            tags=["person", "hero", "actor_mark"],
            use_geometry=has_default_geometry,
            use_position=has_default_position,
        )

    if any(token in semantic_name for token in ["person", "crowd", "extra", "actor", "villager", "pedestrian"]):
        return _with_preview_defaults(
            obj,
            kind="person",
            geometry={"type": "box", "size": (0.42, 0.28, 1.65)},
            transform={"position": (0.0, 0.0, 0.825)},
            material={"roughness": 0.7},
            tags=["person", "crowd"],
            use_geometry=has_default_geometry,
            use_position=has_default_position,
        )

    if any(token in semantic_name for token in ["tree", "oak", "palm", "foliage"]):
        return _with_preview_defaults(
            obj,
            kind="tree",
            geometry={"type": "cylinder", "size": (0.35, 0.35, 2.1), "radius": 0.35, "height": 2.1},
            transform={"position": (0.0, 0.0, 1.05)},
            material={"color": "#2f7d42", "roughness": 0.85},
            tags=["tree", "foliage", "set_dressing"],
            use_geometry=has_default_geometry,
            use_position=has_default_position,
        )

    if any(token in semantic_name for token in ["church", "chapel", "cathedral"]):
        return _with_preview_defaults(
            obj,
            kind="church",
            geometry={"type": "box", "size": (7.0, 9.0, 5.5)},
            transform={"position": (0.0, 7.0, 2.75)},
            material={"color": "#8c8782", "roughness": 0.85},
            tags=["architecture", "church", "landmark"],
            use_geometry=has_default_geometry,
            use_position=has_default_position,
        )

    if "desk" in semantic_name or "table" in semantic_name:
        return _with_preview_defaults(
            obj,
            kind="table",
            geometry={"type": "box", "size": (1.4, 0.7, 0.12)},
            transform={"position": (0.0, 0.25, 0.75)},
            material={"color": "#6f4528", "roughness": 0.58},
            tags=["furniture", "podcast"],
            use_geometry=has_default_geometry,
            use_position=has_default_position,
        )

    if "chair" in semantic_name:
        x = -0.75 if any(token in semantic_name for token in ["host", "left"]) else 0.75
        return _with_preview_defaults(
            obj,
            kind="chair",
            geometry={"type": "box", "size": (0.55, 0.55, 0.9)},
            transform={"position": (x, -0.65, 0.45)},
            material={"color": "#394a5f", "roughness": 0.72},
            tags=["furniture", "seating"],
            use_geometry=has_default_geometry,
            use_position=has_default_position,
        )

    if "mic" in semantic_name or "microphone" in semantic_name:
        x = -0.45 if "host" in semantic_name else 0.45
        return _with_preview_defaults(
            obj,
            kind="microphone",
            geometry={"type": "cylinder", "size": (0.05, 0.05, 0.35), "radius": 0.05, "height": 0.35},
            transform={"position": (x, 0.05, 1.02)},
            material={"color": "#17191f", "roughness": 0.35, "metalness": 0.35},
            tags=["prop", "audio"],
            use_geometry=has_default_geometry,
            use_position=has_default_position,
        )

    if "book" in semantic_name or "shelf" in semantic_name:
        return _with_preview_defaults(
            obj,
            kind="shelf",
            geometry={"type": "box", "size": (0.85, 0.28, 1.65)},
            transform={"position": (-1.45, 1.45, 0.825)},
            material={"color": "#6b4f3a", "roughness": 0.65},
            tags=["set_dressing"],
            use_geometry=has_default_geometry,
            use_position=has_default_position,
        )

    if "plant" in semantic_name:
        return _with_preview_defaults(
            obj,
            kind="plant",
            geometry={"type": "cylinder", "size": (0.22, 0.22, 0.7), "radius": 0.22, "height": 0.7},
            transform={"position": (1.45, 1.25, 0.35)},
            material={"color": "#2f855a", "roughness": 0.8},
            tags=["set_dressing"],
            use_geometry=has_default_geometry,
            use_position=has_default_position,
        )

    if "ceiling" in semantic_name:
        return _with_preview_defaults(
            obj,
            kind="ceiling",
            geometry={"type": "box", "size": (4.0, 3.5, 0.08)},
            transform={"position": (0.0, 0.0, 2.8)},
            material={"color": "#dedbd7", "roughness": 0.8},
            tags=["set_boundary"],
            use_geometry=has_default_geometry,
            use_position=has_default_position,
        )

    return obj


def _with_preview_defaults(
    obj: SceneObjectSchema,
    *,
    kind: str,
    geometry: dict[str, Any],
    transform: dict[str, Any],
    material: dict[str, Any],
    tags: list[str],
    use_geometry: bool,
    use_position: bool,
) -> SceneObjectSchema:
    data = obj.model_dump()
    data["kind"] = kind
    data["tags"] = sorted(set(data.get("tags", [])) | set(tags))
    if use_geometry:
        data["geometry"] = {**data["geometry"], **geometry}
    if use_position:
        data["transform"] = {**data["transform"], **transform}
    data["material"] = {**data["material"], **material}
    return SceneObjectSchema(**data)
