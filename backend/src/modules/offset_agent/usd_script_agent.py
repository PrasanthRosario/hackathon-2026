import ast
import os
import re
import subprocess
import sys
import tempfile
import traceback
from typing import NamedTuple

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from modules.offset_agent.deep_agent import (
    DEFAULT_MODEL,
    MODEL_TIMEOUT_SECONDS,
    OPENROUTER_BASE_URL,
)
from modules.offset_agent.models import ChatMessage

USD_SCRIPT_AGENT_PROMPT = """
You are a senior OpenUSD blockout script author for a film set previsualization app.

CRITICAL: the Python script you write runs in a bare sandbox with NO modules available at
all -- not pxr, not Usd, not UsdGeom, nothing. You are NOT authoring USD through the real
OpenUSD Python API (no `Usd.Stage.CreateNew(...)`, no `UsdGeom.Xform.Define(...)`, no
`from pxr import ...` of any kind -- that will be rejected before it even runs). Instead you
are hand-writing the raw ASCII USDA TEXT yourself, one line at a time, as plain Python
strings, and either assigning the whole thing to a variable named USD_CONTENT or calling
write_usda(the_text). This is the ONLY interface available. A minimal correct script looks
exactly like this shape (adapt content, keep the mechanism identical):

    parts = []
    def add(line):
        parts.append(line)
    add("#usda 1.0")
    add("(")
    add('    defaultPrim = "World"')
    add("    metersPerUnit = 1")
    add('    upAxis = "Z"')
    add(")")
    add("")
    add('def Xform "World"')
    add("{")
    add('    def Cube "Floor" (')
    add('        prepend apiSchemas = ["PhysicsCollisionAPI"]')
    add("    )")
    add("    {")
    add("        double size = 1")
    add("        double3 xformOp:scale = (4, 4, 0.1)")
    add("        double3 xformOp:translate = (0, 0, -0.05)")
    add('        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]')
    add("        color3f[] primvars:displayColor = [(0.5, 0.5, 0.5)]")
    add("    }")
    add("}")
    USD_CONTENT = "\\n".join(parts) + "\\n"

Your task:
- Convert the user's scene request into a small Python script that emits a valid ASCII USDA stage
  using ONLY plain string-building like the example above -- no OpenUSD API calls of any kind.
- The script must either assign a string variable named USD_CONTENT or call write_usda(usd_text).
- Do not use imports, open(), file paths, subprocesses, network, eval, exec, or external packages --
  not even `pxr`. Every primitive is authored as literal USDA text via string concatenation/f-strings.
- Keep the script deterministic and self-contained.
- Use Z-up, meters, and simple USD primitives: Xform, Cube, Cylinder, Cone, Sphere, Camera, DistantLight, DomeLight.
- Include a defaultPrim named World.
- Include displayColor on every visible primitive.
- Every Cube prim must include `double size = 1` before scale/translate so authored dimensions are predictable.
- Prefer rich primitive assemblies over vague single cubes:
  - People are made from legs, torso, head, and arms. The hero should be white when requested.
  - Trees are made from trunk cylinders plus cone/sphere foliage.
  - Buildings should have multiple readable parts such as body, roof, tower, doors, windows, steps.
  - Studio/podcast rooms should include floor, two or three walls, table, seats, microphones, light stands, camera, and practical lights.
  - Cooking show sets should be open-front studio sets: floor, back wall, one partial side wall, island/counter, appliances,
    set dressing, lights, and cameras. Do not create a full ceiling or fully enclosing side walls unless the user asks.
  - Open-world scenes should use a large ground plane, no enclosing room walls unless requested, and multiple scattered actors/props.
- Organize the stage under semantic groups such as /World/Architecture, /World/Crowd, /World/Trees,
  /World/SetDressing, /World/Lights, and /World/Cameras.
- Add at least two useful cameras for staged scenes: one medium-wide camera and one detail camera.
- At least one camera must be animated for Omniverse playback. Use root metadata `startTimeCode = 0`,
  `endTimeCode = 96`, `timeCodesPerSecond = 24`, and a `matrix4d xformOp:transform.timeSamples`
  block on the animated Camera. Do not use `xformOp:rotateXYZ` for cameras.
- Aim cameras with a real look-at transform matrix, not a blind translate-only camera. A good cooking/studio wide shot
  should sit around 5-7m back at human height, aimed at the island/table, with a 35-45mm lens. Avoid ultra-wide,
  wall-filling views that flatten or hide the set.
- Keep scale realistic in meters and place primitives above the ground plane. Avoid default 1m cubes at the origin.
- The generated USDA should be useful in a generic frontend USD viewer, so do not rely on renderer-specific extensions.
- Every solid primitive that should physically block the camera or a person (floor, walls, counters, furniture,
  props, vehicles) must carry `prepend apiSchemas = ["PhysicsCollisionAPI"]` in its prim declaration, e.g.
  `def Cube "Floor" (\n    prepend apiSchemas = ["PhysicsCollisionAPI"]\n)\n{ ... }`. Without this, PhysX has
  nothing to raycast against and every camera frustum check reports the shot as escaping into empty space, even
  when the rendered frame looks fully dressed. Purely decorative, non-blocking details (small props on a table,
  thin foliage) may skip it.

Use the write_usd_python_script_tool exactly once with the complete Python script.
Return a short final message after the tool call.
"""


class USDScriptError(RuntimeError):
    pass


class USDGenerationResult(NamedTuple):
    path: str
    script: str
    source: str


def generate_usd_file_from_prompt(
    *,
    prompt: str,
    messages: list[ChatMessage],
    output_filename: str = "agent_generated.usda",
) -> USDGenerationResult:
    script = ""
    source = "deterministic-fallback"
    if os.getenv("OPENROUTER_API_KEY"):
        try:
            script = _generate_script_with_deep_agent(prompt, messages)
            source = "llm-deepagent"
        except Exception:  # noqa: BLE001 - model/tool failures should fall back to deterministic USDA.
            print(f"[usd_script_agent] LLM script generation failed for prompt {prompt!r}, falling back to deterministic template:")
            traceback.print_exc()
            script = _fallback_usd_script(prompt)
    else:
        script = _fallback_usd_script(prompt)

    try:
        usd_content = _run_usd_script(script, prompt=prompt)
    except Exception as first_error:
        if source != "llm-deepagent":
            raise
        # One bounded repair attempt before giving up on the LLM path entirely --
        # tells the model exactly what broke (usually: it reached for the real
        # pxr/Usd API instead of hand-writing USDA text, which the sandbox
        # rejects) and asks for a corrected script. Exactly one retry, not a
        # loop, so this can't turn into the same runaway-round-trips problem
        # the old deep-agent architecture had.
        try:
            print(f"[usd_script_agent] LLM script failed validation for prompt {prompt!r} ({first_error}); attempting one repair round-trip:")
            script = _repair_script_with_llm(prompt, script, first_error)
            usd_content = _run_usd_script(script, prompt=prompt)
        except Exception:
            print(f"[usd_script_agent] LLM repair attempt also failed for prompt {prompt!r}, falling back to deterministic template:")
            traceback.print_exc()
            source = "deterministic-fallback"
            script = _fallback_usd_script(prompt)
            usd_content = _run_usd_script(script, prompt=prompt)
    out_path = _write_usd_file(usd_content, output_filename)
    return USDGenerationResult(path=out_path, script=script, source=source)


def _generate_script_with_deep_agent(prompt: str, messages: list[ChatMessage]) -> str:
    """
    Despite the name (kept for the calling convention elsewhere in this file),
    this is now a single direct tool-calling completion, NOT a `deepagents`
    planning loop. `create_deep_agent` builds a full multi-step ReAct/planning
    graph meant for open-ended agentic tasks; for "convert this prompt into
    one Python script and call one tool with it", that architecture was
    making 15-20+ sequential LLM round trips per request (each individually
    fast, but the whole chain taking minutes and sometimes never terminating
    within any request's realistic budget) -- which is why the LLM path
    looked broken and every real prompt silently rode on the deterministic
    fallback. Binding the tool directly and doing one .invoke() gets the same
    single-tool-call outcome the prompt already asks for, in one LLM call.
    """
    conversation = [{"role": "system", "content": USD_SCRIPT_AGENT_PROMPT}]
    conversation += [
        {"role": "user", "content": message.content}
        for message in messages
        if message.role == "user"
    ]
    conversation.append({"role": "user", "content": prompt})
    return _call_script_tool(conversation, prompt)


def _repair_script_with_llm(prompt: str, broken_script: str, error: Exception) -> str:
    """One bounded follow-up call: shows the model its own broken script plus
    the exact error, and asks for a corrected one. Not a loop -- called at
    most once per request, from generate_usd_file_from_prompt above."""
    conversation = [
        {"role": "system", "content": USD_SCRIPT_AGENT_PROMPT},
        {"role": "user", "content": prompt},
        {
            "role": "user",
            "content": (
                f"Your previous script for this request failed with this error:\n{error}\n\n"
                f"Previous script:\n```python\n{broken_script}\n```\n\n"
                "Fix it and call the tool again with a corrected COMPLETE script. Remember: "
                "no imports, no pxr/Usd API calls of any kind -- build the USDA text as plain "
                "strings via add()/write_usda() exactly as instructed, matching the example shape."
            ),
        },
    ]
    return _call_script_tool(conversation, prompt)


def _call_script_tool(conversation: list[dict], prompt: str) -> str:
    llm = ChatOpenAI(
        model=DEFAULT_MODEL,
        openai_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openai_api_base=OPENROUTER_BASE_URL,
        temperature=0.1,
        # Without an explicit cap, the client's default max output tokens is far
        # too small for a several-hundred-line script -- the response was
        # getting cut off mid-tool-call, arriving with an empty `args: {}`
        # and finish_reason "error", which looked identical to "didn't call
        # the tool". 16000 comfortably covers every script seen this session
        # (largest content so far was ~45KB of USDA text, roughly 12k tokens).
        max_tokens=16000,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=1,
        default_headers={
            "HTTP-Referer": "https://offset-previz.hackathon",
            "X-Title": "Offset USD Script Generator",
        },
    )

    @tool
    def write_usd_python_script_tool(script: str) -> str:
        """Save the Python script that produces USDA text."""
        return "Python USD script captured."

    # tool_choice is required, not just offered -- without it, the model can
    # (and for some prompts did) just reply in plain text instead of calling
    # the tool, which we'd have no script to run and would look identical to
    # a real failure. Forcing this specific tool removes that failure mode.
    llm_with_tool = llm.bind_tools([write_usd_python_script_tool], tool_choice="write_usd_python_script_tool")
    response = llm_with_tool.invoke(conversation)
    for tool_call in response.tool_calls or []:
        if tool_call.get("name") == "write_usd_python_script_tool":
            script = tool_call.get("args", {}).get("script")
            if isinstance(script, str) and script.strip():
                return script
    print(
        f"[usd_script_agent] no usable tool call in response for prompt {prompt!r}. "
        f"response.tool_calls={response.tool_calls!r} response.content={response.content!r} "
        f"response_metadata={getattr(response, 'response_metadata', None)!r}"
    )
    raise USDScriptError("USD script agent did not call the script tool.")


def _run_usd_script(script: str, prompt: str | None = None) -> str:
    _validate_script_ast(script)
    with tempfile.TemporaryDirectory(prefix="offset-usd-script-") as temp_dir:
        script_path = os.path.join(temp_dir, "generate_usd.py")
        runner_path = os.path.join(temp_dir, "runner.py")
        with open(script_path, "w", encoding="utf-8") as file:
            file.write(script)
        with open(runner_path, "w", encoding="utf-8") as file:
            file.write(_runner_source(script_path))
        result = subprocess.run(
            [sys.executable, runner_path],
            cwd=temp_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise USDScriptError(result.stderr or "USD script execution failed.")
        usd_content = result.stdout
    _validate_usda_content(usd_content, prompt=prompt)
    return usd_content


def _runner_source(script_path: str) -> str:
    return f"""
usd_output = []

def write_usda(content):
    usd_output.append(str(content))

safe_builtins = {{
    "float": float,
    "int": int,
    "abs": abs,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "str": str,
    "tuple": tuple,
}}
namespace = {{"__builtins__": safe_builtins, "write_usda": write_usda}}

with open({script_path!r}, "r", encoding="utf-8") as handle:
    code = compile(handle.read(), {script_path!r}, "exec")
exec(code, namespace, namespace)
content = namespace.get("USD_CONTENT")
if content is None and usd_output:
    content = usd_output[-1]
if not isinstance(content, str) or not content.strip():
    raise RuntimeError("Script must assign USD_CONTENT or call write_usda with USDA text.")
print(content, end="")
"""


def _validate_script_ast(script: str) -> None:
    tree = ast.parse(script)
    blocked_calls = {"eval", "exec", "open", "compile", "input", "__import__"}
    blocked_nodes = (ast.Import, ast.ImportFrom, ast.With, ast.AsyncWith, ast.Lambda)

    for node in ast.walk(tree):
        if isinstance(node, blocked_nodes):
            raise USDScriptError("Generated script uses a blocked Python construct.")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise USDScriptError("Generated script uses blocked dunder access.")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in blocked_calls:
            raise USDScriptError(f"Generated script calls blocked function {node.func.id}.")


def _validate_usda_content(content: str, prompt: str | None = None) -> None:
    if len(content.encode("utf-8")) > 512_000:
        raise USDScriptError("Generated USD is too large for this demo endpoint.")
    required_tokens = ["#usda", "def Xform \"World\""]
    if not all(token in content for token in required_tokens):
        raise USDScriptError("Generated content is not a valid minimal USDA stage.")
    inline_prim_pattern = r'def\s+\w+\s+"[^"]+"\s*\{[^\n{}]+\}'
    if re.search(inline_prim_pattern, content):
        raise USDScriptError("Generated content uses inline prim definitions that OpenUSD rejects.")
    if _camera_blocks_use_rotate_xyz(content):
        raise USDScriptError("Generated content uses rotateXYZ cameras instead of look-at transform matrices.")
    if _cube_blocks_without_unit_size(content):
        raise USDScriptError("Generated content has Cube prims without explicit double size = 1.")
    if prompt and _is_cooking_prompt(prompt):
        _validate_cooking_usda_content(content)


def _is_cooking_prompt(prompt: str) -> bool:
    lower_prompt = prompt.lower()
    return any(token in lower_prompt for token in ["cooking", "kitchen", "chef", "cookery"])


def _validate_cooking_usda_content(content: str) -> None:
    if re.search(r"\bCeiling\w*\b|\bSoffit\w*\b", content, re.IGNORECASE):
        raise USDScriptError("Cooking show USD should be open-front and avoid ceiling/soffit coverage.")

    camera_blocks = _extract_prim_blocks(content, "Camera")
    if not camera_blocks:
        raise USDScriptError("Cooking show USD needs at least one camera.")
    if any("xformOp:transform.timeSamples" not in block for block in camera_blocks):
        raise USDScriptError("Cooking show USD cameras must use animated transform timeSamples.")


def _camera_blocks_use_rotate_xyz(content: str) -> bool:
    for block in _extract_prim_blocks(content, "Camera"):
        if "xformOp:rotateXYZ" in block:
            return True
    return False


def _cube_blocks_without_unit_size(content: str) -> list[str]:
    bad_names = []
    for name, block in _extract_named_prim_blocks(content, "Cube"):
        if "double size = 1" not in block:
            bad_names.append(name)
    return bad_names


def _extract_prim_blocks(content: str, prim_type: str) -> list[str]:
    return [block for _name, block in _extract_named_prim_blocks(content, prim_type)]


def _extract_named_prim_blocks(content: str, prim_type: str) -> list[tuple[str, str]]:
    blocks = []
    # Optional (...) metadata block (e.g. `prepend apiSchemas = [...]`) can sit
    # between the quoted name and the opening brace once a prim carries collision.
    pattern = re.compile(rf'def\s+{prim_type}\s+"([^"]+)"\s*(?:\([^)]*\)\s*)?\{{')
    for match in pattern.finditer(content):
        start = match.start()
        brace_index = content.find("{", match.end() - 1)
        depth = 0
        for index in range(brace_index, len(content)):
            if content[index] == "{":
                depth += 1
            elif content[index] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append((match.group(1), content[start : index + 1]))
                    break
    return blocks


def _fallback_usd_script(prompt: str) -> str:
    lower_prompt = prompt.lower()
    if "church" in lower_prompt:
        return _church_usd_script()
    if "studio" in lower_prompt:
        return _studio_usd_script()
    if "cooking" in lower_prompt or "kitchen" in lower_prompt:
        return _cooking_usd_script()
    if "podcast" in lower_prompt:
        return _podcast_usd_script()
    return _generic_room_usd_script()


def _write_usd_file(content: str, output_filename: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", output_filename or "agent_generated.usda")
    if not safe_name.endswith(".usda"):
        safe_name = f"{safe_name}.usda"
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "scenes"))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, safe_name)
    with open(out_path, "w", encoding="utf-8") as file:
        file.write(content)
    return out_path


def _generic_room_usd_script() -> str:
    return '''parts = []

def add(line):
    parts.append(line)

def vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

def vec_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )

def vec_normalize(v):
    length = max((v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5, 0.0001)
    return (v[0] / length, v[1] / length, v[2] / length)

def look_at_matrix(eye, target):
    forward = vec_normalize(vec_sub(target, eye))
    right = vec_normalize(vec_cross(forward, (0, 0, 1)))
    up = vec_cross(right, forward)
    return (
        (right[0], right[1], right[2], 0),
        (up[0], up[1], up[2], 0),
        (-forward[0], -forward[1], -forward[2], 0),
        (eye[0], eye[1], eye[2], 1),
    )

def matrix_literal(matrix):
    rows = []
    for row in matrix:
        rows.append("(" + ", ".join([str(round(value, 6)) for value in row]) + ")")
    return "(" + ", ".join(rows) + ")"

def static_camera(name, focal_length, eye, target):
    add('    def Camera "' + name + '"')
    add("    {")
    add("        float focalLength = " + str(focal_length))
    add("        matrix4d xformOp:transform = " + matrix_literal(look_at_matrix(eye, target)))
    add('        uniform token[] xformOpOrder = ["xformOp:transform"]')
    add("    }")

add("#usda 1.0")
add("(")
add('    defaultPrim = "World"')
add("    metersPerUnit = 1")
add('    upAxis = "Z"')
add(")")
add("")
add('def Xform "World"')
add("{")
add('    def Cube "Floor" (')
add('        prepend apiSchemas = ["PhysicsCollisionAPI"]')
add("    )")
add("    {")
add("        double size = 1")
add("        double3 xformOp:scale = (6, 5, 0.08)")
add("        double3 xformOp:translate = (0, 0, -0.04)")
add('        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]')
add("        color3f[] primvars:displayColor = [(0.45, 0.48, 0.5)]")
add("    }")
add('    def Cube "BackWall" (')
add('        prepend apiSchemas = ["PhysicsCollisionAPI"]')
add("    )")
add("    {")
add("        double size = 1")
add("        double3 xformOp:scale = (6, 0.16, 3)")
add("        double3 xformOp:translate = (0, 2.5, 1.5)")
add('        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]')
add("        color3f[] primvars:displayColor = [(0.78, 0.74, 0.68)]")
add("    }")
static_camera("Camera", 35, (0, -5, 2), (0, 1.5, 1.2))
add("}")
USD_CONTENT = "\\n".join(parts) + "\\n"
'''


def _podcast_usd_script() -> str:
    return '''parts = []

def add(line):
    parts.append(line)

def cube(path, name, size, pos, color):
    add(f'        def Cube "{name}" (')
    add('            prepend apiSchemas = ["PhysicsCollisionAPI"]')
    add('        )')
    add('        {')
    add('            double size = 1')
    add(f'            double3 xformOp:scale = ({size[0]}, {size[1]}, {size[2]})')
    add(f'            double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})')
    add('            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]')
    add(f'            color3f[] primvars:displayColor = [({color[0]}, {color[1]}, {color[2]})]')
    add('        }')

def cyl(name, radius, height, pos, color):
    add(f'        def Cylinder "{name}" (')
    add('            prepend apiSchemas = ["PhysicsCollisionAPI"]')
    add('        )')
    add('        {')
    add(f'            double radius = {radius}')
    add(f'            double height = {height}')
    add('            uniform token axis = "Z"')
    add(f'            double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})')
    add('            uniform token[] xformOpOrder = ["xformOp:translate"]')
    add(f'            color3f[] primvars:displayColor = [({color[0]}, {color[1]}, {color[2]})]')
    add('        }')

def sphere(name, radius, pos, color):
    add(f'        def Sphere "{name}" (')
    add('            prepend apiSchemas = ["PhysicsCollisionAPI"]')
    add('        )')
    add('        {')
    add(f'            double radius = {radius}')
    add(f'            double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})')
    add('            uniform token[] xformOpOrder = ["xformOp:translate"]')
    add(f'            color3f[] primvars:displayColor = [({color[0]}, {color[1]}, {color[2]})]')
    add('        }')

def person(prefix, x, y, shirt):
    cyl(prefix + "_Leg_L", 0.06, 0.7, (x - 0.08, y, 0.35), shirt)
    cyl(prefix + "_Leg_R", 0.06, 0.7, (x + 0.08, y, 0.35), shirt)
    cyl(prefix + "_Torso", 0.14, 0.52, (x, y, 0.96), shirt)
    sphere(prefix + "_Head", 0.11, (x, y, 1.35), (0.76, 0.58, 0.46))
    cyl(prefix + "_Arm_L", 0.04, 0.45, (x - 0.22, y + 0.08, 0.98), shirt)
    cyl(prefix + "_Arm_R", 0.04, 0.45, (x + 0.22, y + 0.08, 0.98), shirt)

def vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

def vec_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )

def vec_normalize(v):
    length = max((v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5, 0.0001)
    return (v[0] / length, v[1] / length, v[2] / length)

def look_at_matrix(eye, target):
    forward = vec_normalize(vec_sub(target, eye))
    right = vec_normalize(vec_cross(forward, (0, 0, 1)))
    up = vec_cross(right, forward)
    return (
        (right[0], right[1], right[2], 0),
        (up[0], up[1], up[2], 0),
        (-forward[0], -forward[1], -forward[2], 0),
        (eye[0], eye[1], eye[2], 1),
    )

def matrix_literal(matrix):
    rows = []
    for row in matrix:
        rows.append("(" + ", ".join([str(round(value, 6)) for value in row]) + ")")
    return "(" + ", ".join(rows) + ")"

def static_camera(name, focal_length, eye, target):
    add('        def Camera "' + name + '"')
    add("        {")
    add("            float focalLength = " + str(focal_length))
    add("            matrix4d xformOp:transform = " + matrix_literal(look_at_matrix(eye, target)))
    add('            uniform token[] xformOpOrder = ["xformOp:transform"]')
    add("        }")

add('#usda 1.0')
add('(')
add('    defaultPrim = "World"')
add('    metersPerUnit = 1')
add('    upAxis = "Z"')
add(')')
add('')
add('def Xform "World"')
add('{')
add('    def Xform "Architecture"')
add('    {')
cube("/World/Architecture", "Floor", (4.2, 3.5, 0.08), (0, 0, -0.04), (0.12, 0.14, 0.17))
cube("/World/Architecture", "BackWall", (4.2, 0.12, 2.8), (0, 1.75, 1.4), (0.72, 0.72, 0.76))
cube("/World/Architecture", "LeftWall", (0.12, 3.5, 2.8), (-2.1, 0, 1.4), (0.62, 0.66, 0.68))
cube("/World/Architecture", "RightWall", (0.12, 3.5, 2.8), (2.1, 0, 1.4), (0.62, 0.66, 0.68))
cube("/World/Architecture", "AcousticPanel_A", (0.7, 0.04, 1.2), (-0.9, 1.68, 1.45), (0.12, 0.2, 0.32))
cube("/World/Architecture", "AcousticPanel_B", (0.7, 0.04, 1.2), (0.0, 1.68, 1.45), (0.55, 0.25, 0.18))
cube("/World/Architecture", "AcousticPanel_C", (0.7, 0.04, 1.2), (0.9, 1.68, 1.45), (0.18, 0.34, 0.28))
add('    }')
add('    def Xform "SetDressing"')
add('    {')
cube("/World/SetDressing", "PodcastTableTop", (1.5, 0.75, 0.12), (0, 0.15, 0.74), (0.42, 0.26, 0.14))
for lx in [-0.65, 0.65]:
    for ly in [-0.25, 0.55]:
        cyl("TableLeg_" + str(lx).replace("-", "n").replace(".", "p") + "_" + str(ly).replace("-", "n").replace(".", "p"), 0.035, 0.68, (lx, ly, 0.34), (0.04, 0.04, 0.04))
for i, x in [(0, -0.75), (1, 0.75)]:
    cube("/World/SetDressing", "ChairSeat_" + str(i), (0.45, 0.42, 0.08), (x, -0.65, 0.44), (0.05, 0.05, 0.06))
    cube("/World/SetDressing", "ChairBack_" + str(i), (0.45, 0.08, 0.55), (x, -0.88, 0.72), (0.05, 0.05, 0.06))
    cyl("MicStand_" + str(i), 0.018, 0.55, (x * 0.55, -0.05, 1.02), (0.02, 0.02, 0.02))
    cyl("Microphone_" + str(i), 0.055, 0.18, (x * 0.55, 0.02, 1.27), (0.01, 0.01, 0.012))
person("Host", -0.75, -0.62, (0.2, 0.32, 0.55))
person("Guest", 0.75, -0.62, (0.48, 0.22, 0.16))
cube("/World/SetDressing", "CameraBody", (0.22, 0.18, 0.14), (0, -2.0, 1.25), (0.01, 0.01, 0.012))
cyl("CameraTripod", 0.025, 1.1, (0, -2.0, 0.55), (0.02, 0.02, 0.02))
add('    }')
add('    def Xform "Lights"')
add('    {')
add('        def DistantLight "KeyLight"')
add('        {')
add('            float intensity = 4500')
add('            color3f color = (1, 0.92, 0.78)')
add('        }')
add('    }')
add('    def Xform "Cameras"')
add('    {')
static_camera("WideCamera", 35, (0, -3.8, 1.55), (0, -0.3, 1.05))
add('    }')
add('}')
USD_CONTENT = "\\n".join(parts) + "\\n"
'''


def _studio_usd_script() -> str:
    return _podcast_usd_script()


def _cooking_usd_script() -> str:
    return '''parts = []

def add(line):
    parts.append(line)

def cube(name, size, pos, color, indent="        "):
    add(indent + f'def Cube "{name}" (')
    add(indent + '    prepend apiSchemas = ["PhysicsCollisionAPI"]')
    add(indent + ")")
    add(indent + "{")
    add(indent + "    double size = 1")
    add(indent + f"    double3 xformOp:scale = ({size[0]}, {size[1]}, {size[2]})")
    add(indent + f"    double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})")
    add(indent + '    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]')
    add(indent + f"    color3f[] primvars:displayColor = [({color[0]}, {color[1]}, {color[2]})]")
    add(indent + "}")

def cyl(name, radius, height, pos, color, indent="        "):
    add(indent + f'def Cylinder "{name}" (')
    add(indent + '    prepend apiSchemas = ["PhysicsCollisionAPI"]')
    add(indent + ")")
    add(indent + "{")
    add(indent + f"    double radius = {radius}")
    add(indent + f"    double height = {height}")
    add(indent + '    uniform token axis = "Z"')
    add(indent + f"    double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})")
    add(indent + '    uniform token[] xformOpOrder = ["xformOp:translate"]')
    add(indent + f"    color3f[] primvars:displayColor = [({color[0]}, {color[1]}, {color[2]})]")
    add(indent + "}")

def sphere(name, radius, pos, color, indent="        "):
    add(indent + f'def Sphere "{name}" (')
    add(indent + '    prepend apiSchemas = ["PhysicsCollisionAPI"]')
    add(indent + ")")
    add(indent + "{")
    add(indent + f"    double radius = {radius}")
    add(indent + f"    double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})")
    add(indent + '    uniform token[] xformOpOrder = ["xformOp:translate"]')
    add(indent + f"    color3f[] primvars:displayColor = [({color[0]}, {color[1]}, {color[2]})]")
    add(indent + "}")

def vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

def vec_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )

def vec_normalize(v):
    length = max((v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5, 0.0001)
    return (v[0] / length, v[1] / length, v[2] / length)

def look_at_matrix(eye, target):
    forward = vec_normalize(vec_sub(target, eye))
    right = vec_normalize(vec_cross(forward, (0, 0, 1)))
    up = vec_cross(right, forward)
    return (
        (right[0], right[1], right[2], 0),
        (up[0], up[1], up[2], 0),
        (-forward[0], -forward[1], -forward[2], 0),
        (eye[0], eye[1], eye[2], 1),
    )

def matrix_literal(matrix):
    rows = []
    for row in matrix:
        rows.append("(" + ", ".join([str(round(value, 6)) for value in row]) + ")")
    return "(" + ", ".join(rows) + ")"

def animated_camera(name, focal_length, keyframes):
    add('        def Camera "' + name + '"')
    add("        {")
    add("            float focalLength = " + str(focal_length))
    add("            float horizontalAperture = 36")
    add("            float verticalAperture = 24")
    add("            float2 clippingRange = (0.1, 80)")
    add("            matrix4d xformOp:transform.timeSamples = {")
    for index, keyframe in enumerate(keyframes):
        time_code, eye, target = keyframe
        suffix = "," if index < len(keyframes) - 1 else ""
        add("                " + str(time_code) + ": " + matrix_literal(look_at_matrix(eye, target)) + suffix)
    add("            }")
    add('            uniform token[] xformOpOrder = ["xformOp:transform"]')
    add("        }")

def person(prefix, x, y, shirt):
    cyl(prefix + "_Leg_L", 0.06, 0.76, (x - 0.08, y, 0.38), shirt)
    cyl(prefix + "_Leg_R", 0.06, 0.76, (x + 0.08, y, 0.38), shirt)
    cyl(prefix + "_Torso", 0.14, 0.55, (x, y, 1.03), shirt)
    sphere(prefix + "_Head", 0.11, (x, y, 1.43), (0.76, 0.58, 0.46))
    cyl(prefix + "_Arm_L", 0.04, 0.45, (x - 0.22, y + 0.06, 1.03), shirt)
    cyl(prefix + "_Arm_R", 0.04, 0.45, (x + 0.22, y + 0.06, 1.03), shirt)

add("#usda 1.0")
add("(")
add('    defaultPrim = "World"')
add("    metersPerUnit = 1")
add('    upAxis = "Z"')
add("    startTimeCode = 0")
add("    endTimeCode = 96")
add("    timeCodesPerSecond = 24")
add(")")
add("")
add('def Xform "World"')
add("{")
add('    def Xform "Architecture"')
add("    {")
cube("Floor", (8.0, 6.0, 0.08), (0, 0, -0.04), (0.55, 0.34, 0.18))
cube("BackWall", (8.0, 0.14, 3.0), (0, 3.0, 1.5), (0.88, 0.84, 0.76))
cube("LeftReturnWall", (0.14, 3.4, 3.0), (-4.0, 1.3, 1.5), (0.82, 0.78, 0.7))
cube("TileBacksplash", (5.0, 0.05, 0.8), (0, 2.91, 1.35), (0.78, 0.82, 0.8))
cube("Window", (1.2, 0.04, 0.85), (-2.7, 2.9, 1.85), (0.42, 0.62, 0.72))
add("    }")
add('    def Xform "KitchenSet"')
add("    {")
cube("MainIsland_Base", (2.6, 1.15, 0.82), (0, 0.05, 0.41), (0.83, 0.8, 0.72))
cube("MainIsland_Countertop", (2.8, 1.25, 0.12), (0, 0.05, 0.88), (0.92, 0.9, 0.86))
cube("BackCounter_Base", (4.1, 0.62, 0.78), (0, 2.45, 0.39), (0.16, 0.14, 0.12))
cube("BackCounter_Top", (4.3, 0.7, 0.12), (0, 2.45, 0.84), (0.05, 0.05, 0.055))
cube("RangeOven", (0.85, 0.58, 0.72), (-1.15, 2.08, 0.38), (0.1, 0.1, 0.11))
cube("RangeHood", (1.05, 0.45, 0.35), (-1.15, 2.75, 2.05), (0.7, 0.72, 0.72))
cube("Sink", (0.75, 0.38, 0.08), (1.15, 2.08, 0.92), (0.55, 0.62, 0.66))
for i, x in enumerate([-1.25, 0, 1.25]):
    cube("OverheadCabinet_" + str(i), (1.0, 0.35, 0.62), (x, 2.82, 2.24), (0.62, 0.46, 0.32))
for i, x in enumerate([-0.8, 0.0, 0.8]):
    cyl("BarStool_Post_" + str(i), 0.04, 0.7, (x, -1.05, 0.35), (0.04, 0.04, 0.04))
    cyl("BarStool_Seat_" + str(i), 0.18, 0.08, (x, -1.05, 0.73), (0.28, 0.16, 0.08))
for i, x in enumerate([-0.85, -0.25, 0.35, 0.95]):
    cyl("IngredientJar_" + str(i), 0.08, 0.18, (x, 0.0, 1.04), (0.7, 0.38 + i * 0.08, 0.18))
cube("CuttingBoard", (0.5, 0.32, 0.035), (-0.3, -0.28, 0.98), (0.55, 0.32, 0.16))
sphere("MixingBowl", 0.18, (0.45, -0.25, 1.05), (0.75, 0.78, 0.8))
add("    }")
add('    def Xform "Talent"')
add("    {")
person("Chef", 0.0, -0.55, (0.92, 0.92, 0.88))
person("GuestTaster", 1.25, -1.15, (0.18, 0.36, 0.58))
add("    }")
add('    def Xform "Lighting"')
add("    {")
add('        def DistantLight "KeyLight"')
add("        {")
add("            float intensity = 4200")
add("            color3f color = (1, 0.94, 0.84)")
add("        }")
add('        def DomeLight "SoftFill"')
add("        {")
add("            float intensity = 550")
add("            color3f color = (0.75, 0.82, 0.92)")
add("        }")
cube("Softbox_Left", (0.08, 0.7, 0.5), (-2.7, -1.9, 1.8), (1.0, 0.92, 0.78))
cube("Softbox_Right", (0.08, 0.7, 0.5), (2.7, -1.7, 1.7), (0.8, 0.9, 1.0))
add("    }")
add('    def Xform "Cameras"')
add("    {")
animated_camera("MasterDollyCamera", 42, [
    (0, (0, -6.4, 1.55), (0, 0.25, 1.05)),
    (48, (-0.85, -5.25, 1.5), (0, 0.2, 1.05)),
    (96, (-1.35, -4.35, 1.45), (-0.15, 0.05, 1.05)),
])
animated_camera("FoodDetailCamera", 70, [
    (0, (1.75, -2.1, 1.25), (0.15, -0.15, 1.0)),
    (96, (1.25, -1.55, 1.18), (0.15, -0.15, 1.0)),
])
add("    }")
add("}")
USD_CONTENT = "\\n".join(parts) + "\\n"
'''


def _church_usd_script() -> str:
    return '''parts = []

def add(line):
    parts.append(line)

def safe(value):
    return str(value).replace("-", "n").replace(".", "p")

def cube(name, size, pos, color, indent="        "):
    add(indent + f'def Cube "{name}" (')
    add(indent + '    prepend apiSchemas = ["PhysicsCollisionAPI"]')
    add(indent + ")")
    add(indent + "{")
    add(indent + "    double size = 1")
    add(indent + f"    double3 xformOp:scale = ({size[0]}, {size[1]}, {size[2]})")
    add(indent + f"    double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})")
    add(indent + '    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]')
    add(indent + f"    color3f[] primvars:displayColor = [({color[0]}, {color[1]}, {color[2]})]")
    add(indent + "}")

def cyl(name, radius, height, pos, color, indent="        "):
    add(indent + f'def Cylinder "{name}" (')
    add(indent + '    prepend apiSchemas = ["PhysicsCollisionAPI"]')
    add(indent + ")")
    add(indent + "{")
    add(indent + f"    double radius = {radius}")
    add(indent + f"    double height = {height}")
    add(indent + '    uniform token axis = "Z"')
    add(indent + f"    double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})")
    add(indent + '    uniform token[] xformOpOrder = ["xformOp:translate"]')
    add(indent + f"    color3f[] primvars:displayColor = [({color[0]}, {color[1]}, {color[2]})]")
    add(indent + "}")

def cone(name, radius, height, pos, color, indent="        "):
    add(indent + f'def Cone "{name}" (')
    add(indent + '    prepend apiSchemas = ["PhysicsCollisionAPI"]')
    add(indent + ")")
    add(indent + "{")
    add(indent + f"    double radius = {radius}")
    add(indent + f"    double height = {height}")
    add(indent + '    uniform token axis = "Z"')
    add(indent + f"    double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})")
    add(indent + '    uniform token[] xformOpOrder = ["xformOp:translate"]')
    add(indent + f"    color3f[] primvars:displayColor = [({color[0]}, {color[1]}, {color[2]})]")
    add(indent + "}")

def sphere(name, radius, pos, color, indent="        "):
    add(indent + f'def Sphere "{name}" (')
    add(indent + '    prepend apiSchemas = ["PhysicsCollisionAPI"]')
    add(indent + ")")
    add(indent + "{")
    add(indent + f"    double radius = {radius}")
    add(indent + f"    double3 xformOp:translate = ({pos[0]}, {pos[1]}, {pos[2]})")
    add(indent + '    uniform token[] xformOpOrder = ["xformOp:translate"]')
    add(indent + f"    color3f[] primvars:displayColor = [({color[0]}, {color[1]}, {color[2]})]")
    add(indent + "}")

def person(name, x, y, shirt, hero=False):
    color = (0.96, 0.96, 0.92) if hero else shirt
    cyl(name + "_Leg_L", 0.07, 0.82, (x - 0.08, y, 0.41), color)
    cyl(name + "_Leg_R", 0.07, 0.82, (x + 0.08, y, 0.41), color)
    cyl(name + "_Torso", 0.15, 0.58, (x, y, 1.11), color)
    sphere(name + "_Head", 0.12, (x, y, 1.52), (0.76, 0.58, 0.46))
    cyl(name + "_Arm_L", 0.045, 0.48, (x - 0.22, y, 1.08), color)
    cyl(name + "_Arm_R", 0.045, 0.48, (x + 0.22, y, 1.08), color)

def tree(name, x, y, scale):
    cyl(name + "_Trunk", 0.12 * scale, 2.0 * scale, (x, y, 1.0 * scale), (0.28, 0.17, 0.08))
    cone(name + "_Foliage", 0.8 * scale, 1.7 * scale, (x, y, 2.65 * scale), (0.16, 0.36, 0.13))

def vec_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])

def vec_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )

def vec_normalize(v):
    length = max((v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5, 0.0001)
    return (v[0] / length, v[1] / length, v[2] / length)

def look_at_matrix(eye, target):
    forward = vec_normalize(vec_sub(target, eye))
    right = vec_normalize(vec_cross(forward, (0, 0, 1)))
    up = vec_cross(right, forward)
    return (
        (right[0], right[1], right[2], 0),
        (up[0], up[1], up[2], 0),
        (-forward[0], -forward[1], -forward[2], 0),
        (eye[0], eye[1], eye[2], 1),
    )

def matrix_literal(matrix):
    rows = []
    for row in matrix:
        rows.append("(" + ", ".join([str(round(value, 6)) for value in row]) + ")")
    return "(" + ", ".join(rows) + ")"

def static_camera(name, focal_length, eye, target):
    add('        def Camera "' + name + '"')
    add("        {")
    add("            float focalLength = " + str(focal_length))
    add("            matrix4d xformOp:transform = " + matrix_literal(look_at_matrix(eye, target)))
    add('            uniform token[] xformOpOrder = ["xformOp:transform"]')
    add("        }")

add("#usda 1.0")
add("(")
add('    defaultPrim = "World"')
add("    metersPerUnit = 1")
add('    upAxis = "Z"')
add(")")
add("")
add('def Xform "World"')
add("{")
cube("Ground", (30, 28, 0.08), (0, 0, -0.04), (0.42, 0.39, 0.34), indent="    ")
add('    def Xform "Architecture"')
add("    {")
cube("ChurchNave", (6.2, 10.0, 5.0), (0, 7, 2.5), (0.56, 0.54, 0.5))
cube("ChurchTower", (1.7, 1.7, 6.2), (0, 1.2, 3.1), (0.5, 0.49, 0.46))
cone("Steeple", 0.9, 2.4, (0, 1.2, 7.4), (0.22, 0.18, 0.16))
cube("RoofA", (6.8, 10.4, 0.18), (-1.2, 7, 5.35), (0.22, 0.18, 0.16))
cube("RoofB", (6.8, 10.4, 0.18), (1.2, 7, 5.35), (0.22, 0.18, 0.16))
cube("MainDoor", (1.2, 0.12, 2.0), (0, 1.92, 1.0), (0.16, 0.08, 0.035))
cube("Steps", (2.8, 1.2, 0.25), (0, 0.9, 0.12), (0.62, 0.6, 0.56))
sphere("RoseWindow", 0.45, (0, 1.78, 3.7), (0.9, 0.76, 0.28))
add("    }")
add('    def Xform "Crowd"')
add("    {")
person("HeroWhite", 0, -2.0, (1, 1, 1), hero=True)
positions = [(-3.5, -5.0), (-1.8, -4.2), (2.3, -4.5), (4.1, -2.7), (-4.8, -1.4), (3.2, 0.2), (-2.6, 0.8), (1.5, -6.2), (5.5, -5.8), (-5.4, -6.4), (0.9, -0.8), (-1.2, -1.0)]
colors = [(0.75, 0.2, 0.18), (0.16, 0.48, 0.68), (0.65, 0.55, 0.18), (0.44, 0.28, 0.62), (0.2, 0.55, 0.32), (0.8, 0.45, 0.28)]
for i in range(len(positions)):
    p = positions[i]
    person("Extra_" + str(i), p[0], p[1], colors[i % len(colors)])
add("    }")
add('    def Xform "Trees"')
add("    {")
tree_positions = [(-8, -7, 1.0), (8, -7, 1.1), (-9, 1, 0.9), (8.5, 2.2, 1.0), (-6, 6, 1.2), (6, 8, 1.0), (-3, -5.3, 0.9), (3.2, -5.1, 0.95)]
for i in range(len(tree_positions)):
    t = tree_positions[i]
    tree("Tree_" + str(i), t[0], t[1], t[2])
add("    }")
add('    def Xform "Vehicles"')
add("    {")
cube("Car_A_Body", (2.0, 0.95, 0.45), (-6, -3.2, 0.28), (0.55, 0.08, 0.08))
cube("Car_A_Cabin", (1.1, 0.82, 0.38), (-6, -3.2, 0.72), (0.65, 0.12, 0.12))
cube("Car_B_Body", (2.0, 0.95, 0.45), (6.2, -2.4, 0.28), (0.08, 0.16, 0.45))
cube("Car_B_Cabin", (1.1, 0.82, 0.38), (6.2, -2.4, 0.72), (0.12, 0.22, 0.58))
add("    }")
add('    def Xform "Lights"')
add("    {")
add('        def DistantLight "Sun"')
add("        {")
add("            float intensity = 3500")
add("            color3f color = (1, 0.94, 0.82)")
add("        }")
add('        def DomeLight "Sky"')
add("        {")
add("            float intensity = 900")
add("            color3f color = (0.72, 0.8, 0.95)")
add("        }")
add("    }")
add('    def Xform "Cameras"')
add("    {")
static_camera("WideCam", 18, (0, -14, 5.2), (0, 2, 2))
static_camera("HeroFollowCam", 35, (-5, -5.5, 1.7), (0, -2.0, 1.2))
add("    }")
add("}")
USD_CONTENT = "\\n".join(parts) + "\\n"
'''
