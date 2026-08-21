"""
web_backend_client.py

Lives in your external web app's backend (not in Kit). This is the
function your agent's tool-calling loop invokes when the LLM decides
to call "run_validation" or "move_camera" as a tool.

Requires COMMANDS_DIR / RESULTS_DIR to point at the same shared folder
kit_bridge_extension.py is watching -- e.g. a folder on the same AWS
instance if your web backend runs there too, or synced via a shared
mount if it runs elsewhere.
"""
import json
import os
import time
import uuid

COMMANDS_DIR = "/home/ubuntu/bridge/commands"
RESULTS_DIR = "/home/ubuntu/bridge/results"


def call_kit(action, params=None, timeout=15.0):
    os.makedirs(COMMANDS_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    cmd_id = str(uuid.uuid4())
    cmd_path = os.path.join(COMMANDS_DIR, f"{cmd_id}.json")
    with open(cmd_path, "w") as f:
        json.dump({"id": cmd_id, "action": action, "params": params or {}}, f)

    result_path = os.path.join(RESULTS_DIR, f"{cmd_id}.json")
    start = time.time()
    while time.time() - start < timeout:
        if os.path.exists(result_path):
            with open(result_path) as f:
                result = json.load(f)
            os.remove(result_path)
            return result
        time.sleep(0.05)

    raise TimeoutError(f"Kit did not respond to '{action}' within {timeout}s")


# --- Example: what your agent's tool-calling loop does with this -----
if __name__ == "__main__":
    # Load a scene first. "scene": "scene1" / "scene2" are shorthands
    # for the two checked-in demo files (see SCENE_PATHS in
    # kit_bridge_extension.py). A dynamically-generated scene skips the
    # shorthand and passes its own file directly:
    #   call_kit("build_scene", {"usda_path": "/path/to/generated.usda"})
    print("=== build_scene: scene1 ===")
    result = call_kit("build_scene", {"scene": "scene1"})
    print("build_scene result:", result)

    # GOOD SHOT: camera on the desk, framed on-set. Small move, subtle
    # on screen -- useful for confirming OK stays OK, not for a demo.
    print("=== good shot: framed on desk ===")
    result = call_kit("move_camera", {
        "eye": [0, -1.05, 1.35],
        "target": [0, 0.6, 1.15],
    })
    print("move_camera result:", result)
    result = call_kit("run_validation")
    print("run_validation result:", result)

    # BAD SHOT: same camera, swung ~180 degrees to point through the
    # off-set door gap into the backstage void instead of the desk.
    # This is a big, unmistakable reframe on screen (not a nudge), and
    # it flips run_validation from OK to FLAGGED -- good for a demo.
    print("=== bad shot: swung into backstage void ===")
    result = call_kit("move_camera", {
        "eye": [0, -1.05, 1.35],
        "target": [5.0, 0, 1.35],
    })
    print("move_camera result:", result)
    result = call_kit("run_validation")
    print("run_validation result:", result)