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
    # Called when the LLM decides the director wants the camera moved
    result = call_kit("move_camera", {
        "eye": [0, -1.2, 1.35],
        "target": [0, 0.6, 1.15],
    })
    print("move_camera result:", result)

    # Called right after, to check the new shot
    result = call_kit("run_validation")
    print("run_validation result:", result)