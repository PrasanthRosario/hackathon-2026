from fastapi.testclient import TestClient

from main import app
from modules.offset_agent import usd_script_agent
from modules.offset_agent.deep_agent import (
    _coerce_scene_operations,
    _ensure_scene_completion,
    _ensure_visual_operations,
)
from modules.offset_agent.models import ChatMessage, SceneOperationSchema
from modules.offset_agent.scene_ops import (
    apply_scene_operations,
    default_scene_spec,
    scene_spec_to_config,
)
from modules.offset_agent.usd_script_agent import (
    _cooking_usd_script,
    _podcast_usd_script,
    _run_usd_script,
    _validate_usda_content,
)


def test_chat_endpoint_returns_scene_operations_without_remote_model(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "Create a cozy podcast studio with two hosts and a wide camera",
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_used"] == "local/deterministic-scene-agent"
    assert payload["ready_for_confirmation"] is True
    assert len(payload["operations"]) == 12
    assert payload["scene"]["name"] == "Podcast Studio"
    assert payload["scene_config"]["walls"]


def test_church_open_world_chat_uses_fast_scene_template(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "configured-but-not-needed")
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Hey, I want a scene in the church where there are lot of people "
                        "roaming here and there, I dont want a closed room, I want an open world, "
                        "there is a hero in white color and others are in random colours"
                    ),
                }
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    objects = payload["scene"]["objects"]
    assert payload["model_used"] == "local/deterministic-scene-agent"
    assert payload["ready_for_confirmation"] is True
    assert len([obj for obj in objects if obj["kind"] == "wall"]) == 0
    assert any(obj["kind"] == "church" for obj in objects)
    assert any(obj["kind"] == "hero" for obj in objects)
    assert len([obj for obj in objects if obj["kind"] == "person"]) >= 6
    assert len([obj for obj in objects if obj["kind"] == "tree"]) >= 4


def test_cooking_show_followup_uses_full_conversation_intent(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "configured-but-not-needed")
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "i'm planning to create a small film set for a cooking show",
                },
                {
                    "role": "assistant",
                    "content": "I can build a default cooking show set if you say go for it.",
                },
                {
                    "role": "user",
                    "content": "i would say go with your instinct",
                },
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    objects = payload["scene"]["objects"]
    assert payload["model_used"] == "local/deterministic-scene-agent"
    assert payload["ready_for_confirmation"] is True
    assert payload["scene"]["name"] == "Cooking Show Set"
    assert len([obj for obj in objects if obj["kind"] == "wall"]) >= 2
    assert any(obj["kind"] == "counter" for obj in objects)
    assert len(payload["scene"]["cameras"]) == 2


def test_chat_usd_file_endpoint_returns_downloadable_usda(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/chat-usd-file",
        json={
            "prompt": "Create a cooking show kitchen set",
            "messages": [],
            "output_filename": "test_agent_generated.usda",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("model/vnd.usda")
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["x-offset-usd-source"] == "deterministic-fallback"
    assert b"#usda" in response.content
    assert b'def Xform "World"' in response.content


def test_chat_usd_file_church_template_returns_rich_open_world_usda(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/chat-usd-file",
        json={
            "prompt": (
                "Create an open-world church courtyard with trees, people roaming around, "
                "a hero wearing white, and wide cameras"
            ),
            "messages": [],
            "output_filename": "church_open_world.usda",
        },
    )

    assert response.status_code == 200
    assert b'def Xform "Crowd"' in response.content
    assert b'def Xform "Trees"' in response.content
    assert b"HeroWhite" in response.content
    assert response.content.count(b"Extra_") >= 12
    assert response.content.count(b"Tree_") >= 8


def test_podcast_usd_template_avoids_inline_prim_blocks():
    usd_content = _run_usd_script(_podcast_usd_script())

    assert b'def DistantLight "KeyLight" { float intensity' not in usd_content.encode()
    assert b'def Camera "WideCamera" { float focalLength' not in usd_content.encode()
    assert 'def DistantLight "KeyLight"\n        {' in usd_content
    assert 'def Camera "WideCamera"\n        {' in usd_content


def test_cooking_usd_template_has_animated_open_camera_stage():
    usd_content = _run_usd_script(_cooking_usd_script())

    assert "startTimeCode = 0" in usd_content
    assert "endTimeCode = 96" in usd_content
    assert "timeCodesPerSecond = 24" in usd_content
    assert "MasterDollyCamera" in usd_content
    assert usd_content.count("xformOp:transform.timeSamples") >= 2
    assert "xformOp:rotateXYZ" not in usd_content
    assert "Ceiling" not in usd_content


def test_invalid_llm_usd_camera_and_cube_patterns_are_rejected():
    bad_content = """#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "World"
{
    def Cube "OversizedWall"
    {
        double3 xformOp:translate = (0, 4, 1.75)
        double3 xformOp:scale = (10, 0.15, 1.75)
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
    }
    def Camera "BadCamera"
    {
        float focalLength = 24
        double3 xformOp:translate = (0, -7.5, 1.6)
        float3 xformOp:rotateXYZ = (0, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
    }
}
"""

    try:
        _validate_usda_content(bad_content)
    except RuntimeError as exc:
        assert "rotateXYZ cameras" in str(exc) or "Cube prims" in str(exc)
    else:
        raise AssertionError("Expected invalid camera/cube USDA to be rejected.")


def test_chat_usd_file_uses_deepagent_when_openrouter_key_exists(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "configured")
    called = {"value": False}

    def fake_generate_script(prompt, messages):
        called["value"] = True
        return '''USD_CONTENT = """#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "World"
{
    def Cube "LLMGeneratedIsland"
    {
        double size = 1
        double3 xformOp:scale = (2, 1, 0.9)
        double3 xformOp:translate = (0, 0, 0.45)
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
        color3f[] primvars:displayColor = [(0.8, 0.75, 0.68)]
    }
}
"""'''

    monkeypatch.setattr(usd_script_agent, "_generate_script_with_deep_agent", fake_generate_script)
    client = TestClient(app)

    response = client.post(
        "/api/chat-usd-file",
        json={
            "prompt": "Create a simple gallery installation set",
            "messages": [],
            "output_filename": "llm_cooking.usda",
        },
    )

    assert response.status_code == 200
    assert called["value"] is True
    assert response.headers["x-offset-usd-source"] == "llm-deepagent"
    assert b"LLMGeneratedIsland" in response.content


def test_usd_script_runner_blocks_file_io():
    script = 'USD_CONTENT = open("/tmp/nope").read()'

    try:
        _run_usd_script(script)
    except RuntimeError as exc:
        assert "blocked function open" in str(exc)
    else:
        raise AssertionError("Expected generated script file I/O to be blocked.")


def test_malformed_operation_entries_are_ignored():
    operations = _coerce_scene_operations(
        [
            "not-json",
            {"type": "add_object", "id": "missing-object"},
            {
                "type": "add_object",
                "object": {
                    "id": "table",
                    "name": "Table",
                    "kind": "table",
                },
            },
        ]
    )

    assert len(operations) == 2
    assert operations[0].type == "add_object"
    assert operations[0].object is None
    assert operations[1].object.id == "table"


def test_scene_operations_bridge_to_legacy_scene_config():
    scene = default_scene_spec()
    operations = [
        SceneOperationSchema(
            type="add_object",
            object={
                "id": "wall_west",
                "name": "West Wall",
                "kind": "wall",
                "geometry": {"type": "box", "size": (0.1, 5.0, 2.7)},
                "transform": {"position": (-3.0, 0.0, 1.35)},
                "tags": ["wall"],
            },
        )
    ]

    updated_scene = apply_scene_operations(scene, operations)
    config = scene_spec_to_config(updated_scene)

    assert len(config.walls) == 1
    assert config.walls[0].id == "wall_west"
    assert config.walls[0].width == 5.0
    assert config.walls[0].thickness == 0.1
    assert config.walls[0].rotation == 90.0


def test_sparse_semantic_table_operation_gets_preview_geometry():
    scene = default_scene_spec()
    operations = [
        SceneOperationSchema(
            type="add_object",
            object={
                "id": "podcast_desk",
                "name": "Podcast Desk",
                "kind": "prop",
            },
        )
    ]

    updated_scene = apply_scene_operations(scene, operations)
    table = next(obj for obj in updated_scene.objects if obj.id == "podcast_desk")

    assert table.kind == "table"
    assert table.geometry.size == (1.4, 0.7, 0.12)
    assert table.transform.position == (0.0, 0.25, 0.75)
    assert table.material.color == "#6f4528"


def test_sparse_open_world_semantics_get_preview_geometry():
    scene = default_scene_spec()
    operations = [
        SceneOperationSchema(
            type="add_object",
            object={
                "id": "hero_marker",
                "name": "Hero in white",
                "kind": "prop",
            },
        ),
        SceneOperationSchema(
            type="add_object",
            object={
                "id": "crowd_extra_01",
                "name": "Background extra",
                "kind": "prop",
            },
        ),
        SceneOperationSchema(
            type="add_object",
            object={
                "id": "tree_left",
                "name": "Tree",
                "kind": "prop",
            },
        ),
        SceneOperationSchema(
            type="add_object",
            object={
                "id": "church_shell",
                "name": "Church",
                "kind": "prop",
            },
        ),
    ]

    updated_scene = apply_scene_operations(scene, operations)
    objects = {obj.id: obj for obj in updated_scene.objects}

    assert objects["hero_marker"].kind == "hero"
    assert objects["hero_marker"].material.color == "#ffffff"
    assert objects["crowd_extra_01"].kind == "person"
    assert objects["tree_left"].kind == "tree"
    assert objects["tree_left"].geometry.type == "cylinder"
    assert objects["church_shell"].kind == "church"
    assert objects["church_shell"].geometry.size == (7.0, 9.0, 5.5)


def test_visual_intent_without_model_operations_gets_repaired():
    operations, message = _ensure_visual_operations(
        [ChatMessage(role="user", content="can you place a table in the center")],
        default_scene_spec(),
        [],
    )

    assert message == "I added a visible podcast table at the center of the room."
    assert len(operations) == 1
    assert operations[0].object.id == "podcast_table"
    assert operations[0].object.kind == "table"


def test_visual_intent_with_ineffective_model_operation_gets_repaired():
    operations, message = _ensure_visual_operations(
        [ChatMessage(role="user", content="place a table in the center")],
        default_scene_spec(),
        [SceneOperationSchema(type="add_object", id="podcast_table")],
    )

    assert message == "I added a visible podcast table at the center of the room."
    assert len(operations) == 1
    assert operations[0].object.id == "podcast_table"


def test_three_wall_intent_without_model_operations_gets_repaired():
    operations, message = _ensure_visual_operations(
        [ChatMessage(role="user", content="first generate the three wall structure alone")],
        default_scene_spec(),
        [],
    )

    assert message == "I built a clean three-wall room structure with an open camera side."
    wall_operations = [
        operation
        for operation in operations
        if operation.object is not None and operation.object.kind == "wall"
    ]
    assert len(wall_operations) == 3


def test_podcast_scene_completion_adds_room_table_and_camera():
    operations, message = _ensure_scene_completion(
        [
            ChatMessage(
                role="user",
                content=(
                    "Hey, i'm planning to do a podcast in my house, i have a small room "
                    "and 1 guest, can you help me design the scene"
                ),
            )
        ],
        default_scene_spec(),
    )

    assert message == "I created a small podcast room preview with three walls, a central table, and a camera."
    wall_operations = [
        operation
        for operation in operations
        if operation.object is not None and operation.object.kind == "wall"
    ]
    assert len(wall_operations) == 3
    assert any(
        operation.object is not None and operation.object.kind == "table"
        for operation in operations
    )
    assert any(operation.camera is not None for operation in operations)


def test_church_open_world_completion_adds_semantic_assets():
    operations, message = _ensure_scene_completion(
        [
            ChatMessage(
                role="user",
                content=(
                    "Hey, I want a scene in the church where there are lot of people "
                    "roaming here and there, I do not want a closed room, I want an open world, "
                    "there is a hero in white color and others are in random colours"
                ),
            )
        ],
        default_scene_spec(),
    )

    assert message == (
        "I created an open church courtyard preview with a proper church form, trees, "
        "a white hero, crowd actors, and cameras."
    )
    object_operations = [operation.object for operation in operations if operation.object is not None]
    assert any(obj.kind == "church" for obj in object_operations)
    assert any(obj.kind == "hero" for obj in object_operations)
    assert len([obj for obj in object_operations if obj.kind == "person"]) >= 6
    assert len([obj for obj in object_operations if obj.kind == "tree"]) >= 4
    assert len([operation for operation in operations if operation.camera is not None]) == 2
