import json

from langchain_core.tools import tool

from modules.offset_agent.models import SceneOperationSchema, SceneSpecSchema
from modules.offset_agent.scene_ops import (
    apply_scene_operations,
    scene_spec_to_config,
    summarize_scene,
    validate_scene,
)
from modules.offset_agent.usd_exporter import generate_usd_from_config


@tool
def apply_scene_operations_tool(scene_json: str, operations_json: str) -> str:
    """Apply structured scene operations to a SceneSpec JSON payload."""
    scene = SceneSpecSchema(**json.loads(scene_json))
    operations = [SceneOperationSchema(**item) for item in json.loads(operations_json)]
    updated_scene = apply_scene_operations(scene, operations)
    return json.dumps(
        {
            "scene": updated_scene.model_dump(),
            "issues": validate_scene(updated_scene),
            "summary": summarize_scene(updated_scene),
        }
    )


@tool
def validate_scene_tool(scene_json: str) -> str:
    """Validate a SceneSpec for basic set, camera, and export readiness issues."""
    scene = SceneSpecSchema(**json.loads(scene_json))
    return json.dumps({"issues": validate_scene(scene), "summary": summarize_scene(scene)})


@tool
def generate_usd_stage_tool(scene_json: str, output_filename: str = "generated_set.usda") -> str:
    """Generate an OpenUSD stage from a SceneSpec by converting it to the current USD config."""
    scene = SceneSpecSchema(**json.loads(scene_json))
    response = generate_usd_from_config(scene_spec_to_config(scene), output_filename)
    return response.model_dump_json()


OFFSET_AGENT_TOOLS = [
    apply_scene_operations_tool,
    validate_scene_tool,
    generate_usd_stage_tool,
]
