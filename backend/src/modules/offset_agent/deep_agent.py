import json
import os
import re
from functools import lru_cache
from typing import Any

from langchain_openai import ChatOpenAI

from modules.offset_agent.models import (
    ChatMessage,
    ChatResponse,
    SceneOperationSchema,
    SceneSpecSchema,
)
from modules.offset_agent.prompts import OFFSET_DEEP_AGENT_PROMPT
from modules.offset_agent.scene_ops import (
    apply_scene_operations,
    default_scene_spec,
    scene_config_to_spec,
    scene_spec_to_config,
    summarize_scene,
    validate_scene,
)
from modules.offset_agent.tools import OFFSET_AGENT_TOOLS

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"
FALLBACK_MODEL = "local/deterministic-scene-agent"
MODEL_TIMEOUT_SECONDS = 35


def run_offset_agent(
    messages: list[ChatMessage],
    current_scene: SceneSpecSchema | None = None,
    current_config=None,
    model_preference: str | None = None,
) -> ChatResponse:
    scene = current_scene or scene_config_to_spec(current_config)
    # Only the LATEST message decides whether to (re-)trigger the hardcoded
    # template scaffold -- using the full conversation history here (as this
    # used to) means saying "cooking show" even once makes every later turn
    # in the same conversation permanently re-run the fixed template and
    # silently discard any follow-up edit request, since the phrase never
    # leaves the concatenated history.
    user_text = _latest_user_text(messages)
    if _is_church_open_world_intent(user_text) or _is_cooking_show_intent(user_text):
        return _run_deterministic_scene_agent(messages, scene)
    if not os.getenv("OPENROUTER_API_KEY"):
        return _run_deterministic_scene_agent(messages, scene)

    try:
        return _run_deep_agent(messages, scene, model_preference)
    except Exception as exc:  # noqa: BLE001 - preserve chat UX when the remote agent/provider fails.
        fallback = _run_deterministic_scene_agent(messages, scene)
        fallback.message = (
            "I could not reach the configured DeepAgent model, so I applied a local scene update "
            f"instead. Backend detail: {exc}"
        )
        return fallback


def _run_deep_agent(
    messages: list[ChatMessage],
    scene: SceneSpecSchema,
    model_preference: str | None,
) -> ChatResponse:
    agent = _get_agent(model_preference or DEFAULT_MODEL)
    agent_messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "Current SceneSpec JSON:\n"
                f"{scene.model_dump_json()}\n\n"
                "Use tools when you need to validate or transform the scene."
            ),
        }
    ]
    agent_messages.extend(
        {"role": message.role, "content": message.content}
        for message in messages
        if message.role in {"user", "assistant", "system"}
    )

    result = agent.invoke({"messages": agent_messages})
    final_content = _extract_final_content(result)
    payload = _parse_json_object(final_content)
    operations = _coerce_scene_operations(payload.get("operations", []))
    operations, repaired_message = _ensure_visual_operations(messages, scene, operations)
    tool_scene = _extract_scene_from_tool_calls(result)
    updated_scene = apply_scene_operations(tool_scene or scene, operations)
    completion_operations, completion_message = _ensure_scene_completion(messages, updated_scene)
    if completion_operations:
        operations.extend(completion_operations)
        updated_scene = apply_scene_operations(updated_scene, completion_operations)
        repaired_message = completion_message
    missing_fields = payload.get("missing_fields", [])
    issues = validate_scene(updated_scene)
    ready_for_confirmation = (
        bool(payload.get("ready_for_confirmation")) or bool(operations) or tool_scene is not None
    ) and not issues

    return ChatResponse(
        message=repaired_message or payload.get("message") or "I updated the scene.",
        model_used=model_preference or DEFAULT_MODEL,
        ready_for_confirmation=ready_for_confirmation,
        scene=updated_scene,
        scene_config=scene_spec_to_config(updated_scene),
        operations=operations,
        readable_summary=payload.get("readable_summary") or summarize_scene(updated_scene),
        missing_fields=missing_fields + issues,
    )


@lru_cache(maxsize=4)
def _get_agent(model_name: str):
    from deepagents import create_deep_agent

    llm = ChatOpenAI(
        model=model_name,
        openai_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openai_api_base=OPENROUTER_BASE_URL,
        temperature=0.2,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=1,
        default_headers={
            "HTTP-Referer": "https://offset-previz.hackathon",
            "X-Title": "Offset Film Previz Validation Tool",
        },
    )
    return create_deep_agent(
        model=llm,
        tools=OFFSET_AGENT_TOOLS,
        system_prompt=OFFSET_DEEP_AGENT_PROMPT,
    )


def _run_deterministic_scene_agent(
    messages: list[ChatMessage],
    scene: SceneSpecSchema | None = None,
) -> ChatResponse:
    scene = scene or default_scene_spec()
    latest = _latest_user_text(messages)
    operations: list[SceneOperationSchema] = []

    if "podcast" in latest or "studio" in latest:
        scene.name = "Podcast Studio"
        operations.extend(_podcast_room_operations())
        message = "I laid out a compact podcast studio with walls, a central table, chairs, microphones, acoustic panels, cameras, and practical lighting."
    elif "church" in latest:
        scene.name = "Open Church Courtyard"
        operations.extend(_church_open_world_operations(scene))
        message = "I built an open church courtyard with a hero in white, scattered crowd actors, trees, exterior lighting, and two camera options."
    elif _is_cooking_show_intent(latest):
        scene.name = "Cooking Show Set"
        operations.extend(_cooking_show_operations(scene))
        message = "I built a cooking show set with a warm kitchen corner, island, stools, overhead cabinet, lights, and two camera shots."
    elif "corridor" in latest:
        scene.name = "Corridor Set"
        operations.extend(_corridor_operations())
        message = "I created a simple corridor set with parallel walls and a tracking camera path."
    elif "bedroom" in latest:
        scene.name = "Bedroom Set"
        operations.extend(_bedroom_operations())
        message = "I created a three-wall bedroom-style set with a floor and two camera options."
    elif any(word in latest for word in ["confirm", "generate", "usd", "looks good"]):
        message = "The current scene is ready to export to USD."
    else:
        message = "Tell me the room type, rough dimensions, and camera style. I can start with a reasonable default if you say the set type."

    updated_scene = apply_scene_operations(scene, operations)
    issues = validate_scene(updated_scene)
    return ChatResponse(
        message=message,
        model_used=FALLBACK_MODEL,
        ready_for_confirmation=len(updated_scene.objects) > 1 and not issues,
        scene=updated_scene,
        scene_config=scene_spec_to_config(updated_scene),
        operations=operations,
        readable_summary=summarize_scene(updated_scene),
        missing_fields=issues,
    )


def _podcast_room_operations() -> list[SceneOperationSchema]:
    raw_operations: list[dict[str, Any]] = [
        _box_object("wall_north", "North Wall", "wall", [0, 2.5, 1.35], [6, 0.1, 2.7], "#b8bcc2"),
        _box_object("wall_south", "South Wall", "wall", [0, -2.5, 1.35], [6, 0.1, 2.7], "#b8bcc2"),
        _box_object("wall_west", "West Wall", "wall", [-3, 0, 1.35], [0.1, 5, 2.7], "#b8bcc2"),
        _box_object("podcast_table", "Podcast Table", "table", [0, 0, 0.75], [2.2, 0.9, 0.16], "#5b3a24"),
        _box_object("host_chair", "Host Chair", "chair", [-0.9, -0.85, 0.45], [0.6, 0.6, 0.9], "#394a5f"),
        _box_object("guest_chair", "Guest Chair", "chair", [0.9, -0.85, 0.45], [0.6, 0.6, 0.9], "#394a5f"),
        _cylinder_object("host_mic", "Host Microphone", [-0.55, -0.15, 1.05], 0.06, 0.45, "#181c20"),
        _cylinder_object("guest_mic", "Guest Microphone", [0.55, -0.15, 1.05], 0.06, 0.45, "#181c20"),
        _box_object("acoustic_panel_left", "Left Acoustic Panel", "acoustic_panel", [-1.1, 2.42, 1.35], [0.7, 0.05, 0.8], "#282d35"),
        _box_object("acoustic_panel_center", "Center Acoustic Panel", "acoustic_panel", [0, 2.42, 1.35], [0.7, 0.05, 0.8], "#282d35"),
        _box_object("acoustic_panel_right", "Right Acoustic Panel", "acoustic_panel", [1.1, 2.42, 1.35], [0.7, 0.05, 0.8], "#282d35"),
        {
            "type": "add_camera",
            "camera": {
                "id": "cam_wide",
                "focal_length_mm": 28,
                "transform": {"position": [0, -3.6, 1.55]},
                "look_at": [0, 0, 1.1],
                "duration_seconds": 5,
            },
        },
    ]
    return [SceneOperationSchema(**operation) for operation in raw_operations]


def _three_wall_structure_operations(
    scene: SceneSpecSchema,
    *,
    clear_props: bool = True,
) -> list[SceneOperationSchema]:
    raw_operations: list[dict[str, Any]] = [
        {
            "type": "add_object",
            "object": {
                "id": "floor",
                "name": "Small Room Floor",
                "kind": "floor",
                "geometry": {"type": "box", "size": [4.0, 3.5, 0.1]},
                "transform": {"position": [0.0, 0.0, -0.05]},
                "material": {"color": "#8B7355", "roughness": 0.9},
                "tags": ["set_boundary"],
            },
        },
        _box_object("wall_back", "Back Wall", "wall", [0, 1.75, 1.4], [4.0, 0.15, 2.8], "#D6CFC7"),
        _box_object("wall_left", "Left Wall", "wall", [-2.0, 0, 1.4], [0.15, 3.5, 2.8], "#D6CFC7"),
        _box_object("wall_right", "Right Wall", "wall", [2.0, 0, 1.4], [0.15, 3.5, 2.8], "#D6CFC7"),
        {
            "type": "add_camera",
            "camera": {
                "id": "main_camera",
                "focal_length_mm": 35,
                "transform": {"position": [0, -3.2, 1.5]},
                "look_at": [0, 0.4, 1.1],
                "duration_seconds": 5,
            },
        },
    ]
    if clear_props:
        raw_operations.extend(
            {"type": "delete_object", "id": obj.id}
            for obj in scene.objects
            if obj.kind not in {"floor", "wall"}
        )
    return [SceneOperationSchema(**operation) for operation in raw_operations]


def _table_operations() -> list[SceneOperationSchema]:
    return [
        SceneOperationSchema(
            **_box_object(
                "podcast_table",
                "Podcast Table",
                "table",
                [0.0, 0.25, 0.75],
                [1.4, 0.7, 0.12],
                "#6f4528",
            )
        )
    ]


def _chair_operations() -> list[SceneOperationSchema]:
    return [
        SceneOperationSchema(
            **_box_object(
                "host_chair",
                "Host Chair",
                "chair",
                [-0.75, -0.65, 0.45],
                [0.55, 0.55, 0.9],
                "#394a5f",
            )
        ),
        SceneOperationSchema(
            **_box_object(
                "guest_chair",
                "Guest Chair",
                "chair",
                [0.75, -0.65, 0.45],
                [0.55, 0.55, 0.9],
                "#394a5f",
            )
        ),
    ]


def _microphone_operations() -> list[SceneOperationSchema]:
    return [
        SceneOperationSchema(
            **_cylinder_object("host_mic", "Host Microphone", [-0.45, 0.05, 1.02], 0.05, 0.35, "#17191f")
        ),
        SceneOperationSchema(
            **_cylinder_object("guest_mic", "Guest Microphone", [0.45, 0.05, 1.02], 0.05, 0.35, "#17191f")
        ),
    ]


def _corridor_operations() -> list[SceneOperationSchema]:
    raw_operations = [
        _box_object("wall_north", "North Wall", "wall", [0, 2, 1.5], [12, 0.2, 3], "#b8bcc2"),
        _box_object("wall_south", "South Wall", "wall", [0, -2, 1.5], [12, 0.2, 3], "#b8bcc2"),
        _box_object("wall_west", "West Wall", "wall", [-6, 0, 1.5], [0.2, 4, 3], "#b8bcc2"),
        _box_object("wall_east", "East Wall", "wall", [6, 0, 1.5], [0.2, 4, 3], "#b8bcc2"),
        {
            "type": "add_camera",
            "camera": {
                "id": "cam_tracking",
                "focal_length_mm": 35,
                "transform": {"position": [-5, 0, 1.5]},
                "look_at": [5, 0, 1.5],
                "duration_seconds": 8,
            },
        },
    ]
    return [SceneOperationSchema(**operation) for operation in raw_operations]


def _bedroom_operations() -> list[SceneOperationSchema]:
    raw_operations = [
        _box_object("wall_north", "North Wall", "wall", [0, 3, 1.5], [8, 0.2, 3], "#b8bcc2"),
        _box_object("wall_west", "West Wall", "wall", [-4, 0, 1.5], [0.2, 6, 3], "#b8bcc2"),
        _box_object("wall_east", "East Wall", "wall", [4, 0, 1.5], [0.2, 6, 3], "#b8bcc2"),
        _box_object("bed", "Bed", "bed", [0.5, 0.8, 0.35], [2.2, 1.7, 0.45], "#6b7280"),
        {
            "type": "add_camera",
            "camera": {
                "id": "cam_establishing",
                "focal_length_mm": 24,
                "transform": {"position": [-3.5, -2.4, 1.6]},
                "look_at": [0.5, 0.5, 1.2],
                "duration_seconds": 5,
            },
        },
    ]
    return [SceneOperationSchema(**operation) for operation in raw_operations]


def _church_open_world_operations(scene: SceneSpecSchema) -> list[SceneOperationSchema]:
    people = [
        ("crowd_01", "Crowd Actor Red", [-4.8, -3.8, 0.825], "#c2413b"),
        ("crowd_02", "Crowd Actor Teal", [-2.9, -5.2, 0.825], "#0f766e"),
        ("crowd_03", "Crowd Actor Blue", [-1.0, -6.0, 0.825], "#0369a1"),
        ("crowd_04", "Crowd Actor Yellow", [2.1, -5.5, 0.825], "#ca8a04"),
        ("crowd_05", "Crowd Actor Purple", [4.2, -3.9, 0.825], "#7e3af2"),
        ("crowd_06", "Crowd Actor Green", [-5.2, 1.2, 0.825], "#15803d"),
        ("crowd_07", "Crowd Actor Coral", [5.0, 0.6, 0.825], "#e76f51"),
        ("crowd_08", "Crowd Actor Orange", [-2.0, 3.2, 0.825], "#d97706"),
        ("crowd_09", "Crowd Actor Violet", [3.1, 3.5, 0.825], "#9333ea"),
        ("crowd_10", "Crowd Actor Cyan", [0.7, -3.7, 0.825], "#0891b2"),
    ]
    trees = [
        ("tree_left_front", "Tree Left Front", [-7.0, -5.0, 1.05]),
        ("tree_right_front", "Tree Right Front", [7.1, -4.4, 1.05]),
        ("tree_left_mid", "Tree Left Mid", [-8.0, 2.8, 1.05]),
        ("tree_right_mid", "Tree Right Mid", [8.2, 2.2, 1.05]),
        ("tree_left_back", "Tree Left Back", [-6.4, 8.2, 1.05]),
        ("tree_right_back", "Tree Right Back", [6.5, 8.0, 1.05]),
    ]
    raw_operations: list[dict[str, Any]] = [
        {"type": "delete_object", "id": obj.id}
        for obj in scene.objects
        if obj.kind in {"wall", "ceiling"}
    ]
    raw_operations.extend(
        [
            _box_object("floor", "Open Courtyard Ground", "floor", [0, 1.0, -0.04], [24.0, 26.0, 0.08], "#465b3f"),
            _box_object("church_main", "Stone Church", "church", [0.0, 7.0, 2.75], [7.0, 9.0, 5.5], "#8c8782"),
            _box_object("hero_white", "Hero In White", "hero", [0.0, -2.2, 0.875], [0.45, 0.28, 1.75], "#ffffff"),
            {
                "type": "add_camera",
                "camera": {
                    "id": "cam_wide",
                    "focal_length_mm": 28,
                    "transform": {"position": [0.0, -16.0, 5.2]},
                    "look_at": [0.0, 4.5, 1.8],
                    "duration_seconds": 7,
                },
            },
            {
                "type": "add_camera",
                "camera": {
                    "id": "cam_hero_follow",
                    "focal_length_mm": 35,
                    "transform": {"position": [0.0, -6.5, 1.7]},
                    "look_at": [0.0, -2.0, 1.2],
                    "duration_seconds": 5,
                },
            },
            {
                "type": "add_light",
                "light": {
                    "id": "sun_key",
                    "kind": "directional",
                    "transform": {"position": [-8.0, -10.0, 12.0]},
                    "color": "#fff2d6",
                    "intensity": 2.4,
                },
            },
            {
                "type": "add_light",
                "light": {
                    "id": "sky_fill",
                    "kind": "point",
                    "transform": {"position": [0.0, -2.0, 9.0]},
                    "color": "#b9e6ff",
                    "intensity": 0.8,
                },
            },
        ]
    )
    raw_operations.extend(
        _box_object(object_id, name, "person", position, [0.42, 0.28, 1.65], color)
        for object_id, name, position, color in people
    )
    raw_operations.extend(
        _tree_object(object_id, name, position)
        for object_id, name, position in trees
    )
    return [SceneOperationSchema(**operation) for operation in raw_operations]


def _cooking_show_operations(scene: SceneSpecSchema) -> list[SceneOperationSchema]:
    raw_operations: list[dict[str, Any]] = [
        {"type": "delete_object", "id": obj.id}
        for obj in scene.objects
        if obj.kind not in {"floor"}
    ]
    raw_operations.extend(
        [
            _box_object("floor", "Hardwood Studio Floor", "floor", [0.0, 0.0, -0.05], [8.0, 6.0, 0.1], "#b9824c"),
            _box_object("wall_back", "Warm Back Wall", "wall", [0.0, 3.0, 1.5], [8.0, 0.16, 3.0], "#f1eadf"),
            _box_object("wall_left", "Left Return Wall", "wall", [-4.0, 0.0, 1.5], [0.16, 6.0, 3.0], "#efe4d5"),
            _box_object("kitchen_counter", "Dark Granite Kitchen Counter", "counter", [0.0, 2.35, 0.45], [3.2, 0.62, 0.9], "#2b2928"),
            _box_object("kitchen_island", "White Marble Cooking Island", "counter", [0.0, 0.15, 0.45], [2.2, 1.05, 0.9], "#e9e3d7"),
            _box_object("stool_left", "Walnut Bar Stool Left", "stool", [-0.7, -1.0, 0.42], [0.42, 0.42, 0.84], "#6b4126"),
            _box_object("stool_right", "Walnut Bar Stool Right", "stool", [0.7, -1.0, 0.42], [0.42, 0.42, 0.84], "#6b4126"),
            _box_object("overhead_cabinet", "Overhead Cabinet", "cabinet", [0.0, 2.9, 2.25], [2.6, 0.32, 0.62], "#d8cab8"),
            _box_object("range_hood", "Stainless Range Hood", "appliance", [0.0, 2.55, 1.65], [0.9, 0.45, 0.35], "#aab0b4"),
            _box_object("cutting_board", "Cutting Board", "prop", [-0.45, 0.08, 0.94], [0.55, 0.36, 0.04], "#c08a52"),
            _cylinder_object("saucepan", "Saucepan", [0.45, 0.08, 0.99], 0.18, 0.12, "#20242a"),
            {
                "type": "add_camera",
                "camera": {
                    "id": "cam_master",
                    "focal_length_mm": 35,
                    "transform": {"position": [0.0, -4.2, 1.55]},
                    "look_at": [0.0, 0.45, 1.1],
                    "duration_seconds": 6,
                },
            },
            {
                "type": "add_camera",
                "camera": {
                    "id": "cam_cooking_close",
                    "focal_length_mm": 55,
                    "transform": {"position": [2.1, -1.2, 1.35]},
                    "look_at": [0.15, 0.05, 0.95],
                    "duration_seconds": 4,
                },
            },
            {
                "type": "add_light",
                "light": {
                    "id": "kitchen_key",
                    "kind": "point",
                    "transform": {"position": [-2.5, -1.8, 2.9]},
                    "color": "#fff7ea",
                    "intensity": 1.5,
                },
            },
            {
                "type": "add_light",
                "light": {
                    "id": "island_spot",
                    "kind": "point",
                    "transform": {"position": [0.0, 0.1, 2.7]},
                    "color": "#ffffff",
                    "intensity": 1.1,
                },
            },
        ]
    )
    return [SceneOperationSchema(**operation) for operation in raw_operations]


def _box_object(
    object_id: str,
    name: str,
    kind: str,
    position: list[float],
    size: list[float],
    color: str,
) -> dict[str, Any]:
    return {
        "type": "add_object",
        "object": {
            "id": object_id,
            "name": name,
            "kind": kind,
            "geometry": {"type": "box", "size": size},
            "transform": {"position": position},
            "material": {"color": color},
            "tags": [kind],
        },
    }


def _cylinder_object(
    object_id: str,
    name: str,
    position: list[float],
    radius: float,
    height: float,
    color: str,
) -> dict[str, Any]:
    return {
        "type": "add_object",
        "object": {
            "id": object_id,
            "name": name,
            "kind": "microphone",
            "geometry": {"type": "cylinder", "size": [radius, radius, height], "radius": radius, "height": height},
            "transform": {"position": position},
            "material": {"color": color, "metalness": 0.35},
            "tags": ["prop", "audio"],
        },
    }


def _tree_object(
    object_id: str,
    name: str,
    position: list[float],
) -> dict[str, Any]:
    return {
        "type": "add_object",
        "object": {
            "id": object_id,
            "name": name,
            "kind": "tree",
            "geometry": {"type": "cylinder", "size": [0.35, 0.35, 2.1], "radius": 0.35, "height": 2.1},
            "transform": {"position": position},
            "material": {"color": "#2f7d42", "roughness": 0.85},
            "tags": ["tree", "foliage", "set_dressing", "open_world"],
        },
    }


def _ensure_visual_operations(
    messages: list[ChatMessage],
    scene: SceneSpecSchema,
    operations: list[SceneOperationSchema],
) -> tuple[list[SceneOperationSchema], str | None]:
    if any(_is_effective_operation(operation) for operation in operations):
        return operations, None

    latest = _latest_user_text(messages)
    fallback_operations = _fallback_operations_for_visual_intent(latest, scene)
    if not fallback_operations:
        return operations, None

    return fallback_operations, _fallback_message_for_operations(latest, fallback_operations)


def _ensure_scene_completion(
    messages: list[ChatMessage],
    scene: SceneSpecSchema,
) -> tuple[list[SceneOperationSchema], str | None]:
    latest = _latest_user_text(messages)
    if _is_church_open_world_intent(latest):
        operations = _church_open_world_completion_operations(scene)
        if not operations:
            return [], None
        return (
            operations,
            "I created an open church courtyard preview with a proper church form, trees, a white hero, crowd actors, and cameras.",
        )

    if _is_cooking_show_intent(latest):
        operations = _cooking_show_completion_operations(scene)
        if not operations:
            return [], None
        return (
            operations,
            "I created a cooking show set preview with walls, kitchen counters, island props, lights, and cameras.",
        )

    if "podcast" not in latest and "studio" not in latest:
        return [], None

    completion_operations: list[SceneOperationSchema] = []
    objects = scene.objects

    if len([obj for obj in objects if obj.kind == "wall"]) < 3:
        completion_operations.extend(_three_wall_structure_operations(scene, clear_props=False))
    if not any(obj.kind == "table" or "table" in obj.id or "desk" in obj.id for obj in objects):
        completion_operations.extend(_table_operations())
    if not scene.cameras:
        completion_operations.append(
            SceneOperationSchema(
                type="add_camera",
                camera={
                    "id": "main_camera",
                    "focal_length_mm": 35,
                    "transform": {"position": [0.0, -3.2, 1.5]},
                    "look_at": [0.0, 0.3, 1.1],
                    "duration_seconds": 5,
                },
            )
        )

    if not completion_operations:
        return [], None
    return (
        completion_operations,
        "I created a small podcast room preview with three walls, a central table, and a camera.",
    )


def _church_open_world_completion_operations(scene: SceneSpecSchema) -> list[SceneOperationSchema]:
    people_count = len([obj for obj in scene.objects if obj.kind in {"person", "hero"} or "person" in obj.tags])
    has_church = any(obj.kind == "church" or "church" in obj.tags for obj in scene.objects)
    has_hero = any(obj.kind == "hero" or "hero" in obj.tags or "hero" in obj.name.lower() for obj in scene.objects)
    tree_count = len([obj for obj in scene.objects if obj.kind == "tree" or "tree" in obj.tags])
    has_camera = bool(scene.cameras)
    has_walls = any(obj.kind == "wall" for obj in scene.objects)

    if has_church and has_hero and people_count >= 6 and tree_count >= 4 and has_camera and not has_walls:
        return []
    return _church_open_world_operations(scene)


def _cooking_show_completion_operations(scene: SceneSpecSchema) -> list[SceneOperationSchema]:
    objects = scene.objects
    has_walls = len([obj for obj in objects if obj.kind == "wall"]) >= 2
    has_counter = any(obj.kind in {"counter", "table"} or "counter" in obj.tags or "island" in obj.tags for obj in objects)
    has_camera = bool(scene.cameras)
    if has_walls and has_counter and has_camera:
        return []
    return _cooking_show_operations(scene)


def _is_effective_operation(operation: SceneOperationSchema) -> bool:
    if operation.type == "add_object":
        return operation.object is not None
    if operation.type == "add_camera":
        return operation.camera is not None
    if operation.type == "add_light":
        return operation.light is not None
    if operation.type == "delete_object":
        return bool(operation.id)
    if operation.type in {"update_object", "update_camera"}:
        return bool(operation.id and operation.patch)
    return False


def _latest_user_text(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content.lower()
    return ""


def _fallback_operations_for_visual_intent(
    latest: str,
    scene: SceneSpecSchema,
) -> list[SceneOperationSchema]:
    if not latest:
        return []
    if any(phrase in latest for phrase in ["three wall", "3 wall", "wall structure", "walls alone"]):
        return _three_wall_structure_operations(scene)
    if _is_church_open_world_intent(latest):
        return _church_open_world_operations(scene)
    if _is_cooking_show_intent(latest):
        return _cooking_show_operations(scene)
    if "table" in latest or "desk" in latest:
        return _table_operations()
    if "chair" in latest or "seat" in latest:
        return _chair_operations()
    if "mic" in latest or "microphone" in latest:
        return _microphone_operations()
    if "podcast" in latest or "studio" in latest:
        return _podcast_room_operations()
    if "corridor" in latest:
        return _corridor_operations()
    if "bedroom" in latest:
        return _bedroom_operations()
    return []


def _fallback_message_for_operations(
    latest: str,
    operations: list[SceneOperationSchema],
) -> str:
    if _is_church_open_world_intent(latest):
        return "I built an open church courtyard with a white hero, scattered crowd actors, trees, daylight, and two cameras."
    if _is_cooking_show_intent(latest):
        return "I built a cooking show kitchen set with visible walls, counters, an island, set dressing, lighting, and cameras."
    if "table" in latest or "desk" in latest:
        return "I added a visible podcast table at the center of the room."
    if any(phrase in latest for phrase in ["three wall", "3 wall", "wall structure", "walls alone"]):
        return "I built a clean three-wall room structure with an open camera side."
    if "chair" in latest or "seat" in latest:
        return "I added two podcast chairs around the table."
    if "mic" in latest or "microphone" in latest:
        return "I added two tabletop microphones for the podcast setup."
    if "podcast" in latest or "studio" in latest:
        return "I laid out a compact podcast studio with visible walls, furniture, microphones, panels, lighting, and camera."
    return f"I applied {len(operations)} scene operation(s) to the preview."


def _is_church_open_world_intent(latest: str) -> bool:
    return "church" in latest and any(
        token in latest
        for token in ["open", "open world", "people", "crowd", "roaming", "hero", "outside", "courtyard"]
    )


def _is_cooking_show_intent(text: str) -> bool:
    return any(token in text for token in ["cooking show", "cookery", "kitchen set", "cooking set"])


def _coerce_scene_operations(raw_operations: Any) -> list[SceneOperationSchema]:
    if not isinstance(raw_operations, list):
        return []

    operations: list[SceneOperationSchema] = []
    for raw_operation in raw_operations:
        operation = _coerce_scene_operation(raw_operation)
        if operation is not None:
            operations.append(operation)
    return operations


def _coerce_scene_operation(raw_operation: Any) -> SceneOperationSchema | None:
    operation_data = raw_operation
    if isinstance(operation_data, str):
        try:
            operation_data = json.loads(operation_data)
        except json.JSONDecodeError:
            return None
    if not isinstance(operation_data, dict):
        return None
    try:
        return SceneOperationSchema(**operation_data)
    except (TypeError, ValueError):
        return None


def _extract_scene_from_tool_calls(result: dict[str, Any]) -> SceneSpecSchema | None:
    for message in reversed(result.get("messages", [])):
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls is None and isinstance(message, dict):
            tool_calls = message.get("tool_calls")
        for tool_call in tool_calls or []:
            function_data = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            raw_args = tool_call.get("args") if isinstance(tool_call, dict) else None
            raw_args = raw_args or function_data.get("arguments")
            if not raw_args:
                continue
            args = raw_args
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    continue
            if not isinstance(args, dict) or "scene_json" not in args:
                continue
            scene = _coerce_scene_spec(args["scene_json"])
            if scene is not None:
                return scene
    return None


def _coerce_scene_spec(raw_scene: Any) -> SceneSpecSchema | None:
    if isinstance(raw_scene, str):
        try:
            raw_scene = json.loads(raw_scene)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw_scene, dict):
        return None
    try:
        return apply_scene_operations(SceneSpecSchema(**raw_scene), [])
    except (TypeError, ValueError):
        return None


def _extract_final_content(result: dict[str, Any]) -> str:
    messages = result.get("messages", [])
    if not messages:
        return "{}"

    for message in reversed(messages):
        content = _message_content(message)
        if '"operations"' in content or "```json" in content:
            return content

    content = _message_content(messages[-1])
    if not content:
        return "{}"
    return content


def _message_content(message: Any) -> str:
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content", "")
    if isinstance(content, list):
        return "\n".join(str(item) for item in content)
    return str(content)


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
    return {"message": text, "operations": [], "ready_for_confirmation": False}
