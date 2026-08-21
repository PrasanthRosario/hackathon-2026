import ast
import os
import re
import subprocess
import sys
import tempfile
from typing import Any

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from modules.offset_agent.deep_agent import (
    DEFAULT_MODEL,
    MODEL_TIMEOUT_SECONDS,
    OPENROUTER_BASE_URL,
)
from modules.offset_agent.models import ChatMessage

USD_SCRIPT_AGENT_PROMPT = """
You are a USD script author for a film set previsualization app.

Your task:
- Convert the user's scene request into a small Python script.
- The script must generate valid ASCII USDA text.
- The script must either assign a string variable named USD_CONTENT or call write_usda(usd_text).
- Do not use imports, open(), file paths, subprocesses, network, eval, exec, or external packages.
- Keep the script deterministic and self-contained.
- Use Z-up, meters, and simple USD primitives: Xform, Cube, Cylinder, Sphere, Camera, DistantLight.
- Include a defaultPrim named World.
- Include displayColor on visible prims when useful.

Use the write_usd_python_script_tool exactly once with the complete Python script.
Return a short final message after the tool call.
"""


class USDScriptError(RuntimeError):
    pass


def generate_usd_file_from_prompt(
    *,
    prompt: str,
    messages: list[ChatMessage],
    output_filename: str = "agent_generated.usda",
) -> tuple[str, str]:
    script = _fallback_usd_script(prompt)
    if os.getenv("OPENROUTER_API_KEY") and not _has_fast_template(prompt):
        try:
            script = _generate_script_with_deep_agent(prompt, messages)
        except Exception:  # noqa: BLE001 - model/tool failures should fall back to deterministic USDA.
            script = _fallback_usd_script(prompt)

    usd_content = _run_usd_script(script)
    out_path = _write_usd_file(usd_content, output_filename)
    return out_path, script


def _generate_script_with_deep_agent(prompt: str, messages: list[ChatMessage]) -> str:
    captured: dict[str, str] = {}

    @tool
    def write_usd_python_script_tool(script: str) -> str:
        """Save the Python script that produces USDA text."""
        captured["script"] = script
        return "Python USD script captured."

    agent = _get_usd_script_agent(write_usd_python_script_tool)
    conversation = [
        {
            "role": "user",
            "content": message.content,
        }
        for message in messages
        if message.role == "user"
    ]
    conversation.append({"role": "user", "content": prompt})
    result = agent.invoke({"messages": conversation})
    script = captured.get("script") or _extract_script_from_tool_calls(result)
    if not script:
        raise USDScriptError("USD script agent did not call the script tool.")
    return script


def _get_usd_script_agent(script_tool):
    from deepagents import create_deep_agent

    llm = ChatOpenAI(
        model=DEFAULT_MODEL,
        openai_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openai_api_base=OPENROUTER_BASE_URL,
        temperature=0.1,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=1,
        default_headers={
            "HTTP-Referer": "https://offset-previz.hackathon",
            "X-Title": "Offset USD Script Generator",
        },
    )
    return create_deep_agent(
        model=llm,
        tools=[script_tool],
        system_prompt=USD_SCRIPT_AGENT_PROMPT,
    )


def _extract_script_from_tool_calls(result: dict[str, Any]) -> str | None:
    for message in reversed(result.get("messages", [])):
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls is None and isinstance(message, dict):
            tool_calls = message.get("tool_calls")
        for tool_call in tool_calls or []:
            function_data = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            args = tool_call.get("args") if isinstance(tool_call, dict) else None
            args = args or function_data.get("arguments")
            if isinstance(args, str):
                import json

                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    continue
            if isinstance(args, dict) and isinstance(args.get("script"), str):
                return args["script"]
    return None


def _run_usd_script(script: str) -> str:
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
    _validate_usda_content(usd_content)
    return usd_content


def _runner_source(script_path: str) -> str:
    return f"""
namespace = {{}}
usd_output = []

def write_usda(content):
    usd_output.append(str(content))

safe_builtins = {{
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "str": str,
}}

with open({script_path!r}, "r", encoding="utf-8") as handle:
    code = compile(handle.read(), {script_path!r}, "exec")
exec(code, {{"__builtins__": safe_builtins, "write_usda": write_usda}}, namespace)
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


def _validate_usda_content(content: str) -> None:
    if len(content.encode("utf-8")) > 512_000:
        raise USDScriptError("Generated USD is too large for this demo endpoint.")
    required_tokens = ["#usda", "def Xform \"World\""]
    if not all(token in content for token in required_tokens):
        raise USDScriptError("Generated content is not a valid minimal USDA stage.")


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


def _fallback_usd_script(prompt: str) -> str:
    lower_prompt = prompt.lower()
    if "church" in lower_prompt:
        return _church_usd_script()
    if "cooking" in lower_prompt or "kitchen" in lower_prompt:
        return _cooking_usd_script()
    if "podcast" in lower_prompt:
        return _podcast_usd_script()
    return _generic_room_usd_script()


def _has_fast_template(prompt: str) -> bool:
    lower_prompt = prompt.lower()
    return any(token in lower_prompt for token in ["church", "cooking", "kitchen", "podcast"])


def _generic_room_usd_script() -> str:
    return '''USD_CONTENT = """#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "World"
{
    def Cube "Floor"
    {
        double size = 1
        double3 xformOp:scale = (6, 5, 0.08)
        double3 xformOp:translate = (0, 0, -0.04)
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
        color3f[] primvars:displayColor = [(0.45, 0.48, 0.5)]
    }
    def Cube "BackWall"
    {
        double size = 1
        double3 xformOp:scale = (6, 0.16, 3)
        double3 xformOp:translate = (0, 2.5, 1.5)
        uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
        color3f[] primvars:displayColor = [(0.78, 0.74, 0.68)]
    }
    def Camera "Camera"
    {
        float focalLength = 35
        double3 xformOp:translate = (0, -5, 2)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
}
"""'''


def _podcast_usd_script() -> str:
    return '''USD_CONTENT = """#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "World"
{
    def Cube "Floor" { double size = 1 double3 xformOp:scale = (5, 4, 0.08) double3 xformOp:translate = (0, 0, -0.04) uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"] color3f[] primvars:displayColor = [(0.12, 0.16, 0.22)] }
    def Cube "BackWall" { double size = 1 double3 xformOp:scale = (5, 0.16, 2.8) double3 xformOp:translate = (0, 2, 1.4) uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"] color3f[] primvars:displayColor = [(0.75, 0.75, 0.78)] }
    def Cube "PodcastTable" { double size = 1 double3 xformOp:scale = (1.6, 0.8, 0.16) double3 xformOp:translate = (0, 0, 0.75) uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"] color3f[] primvars:displayColor = [(0.42, 0.25, 0.13)] }
    def Camera "WideCamera" { float focalLength = 35 double3 xformOp:translate = (0, -4, 1.6) uniform token[] xformOpOrder = ["xformOp:translate"] }
}
"""'''


def _cooking_usd_script() -> str:
    return '''USD_CONTENT = """#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "World"
{
    def Cube "Floor" { double size = 1 double3 xformOp:scale = (8, 6, 0.08) double3 xformOp:translate = (0, 0, -0.04) uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"] color3f[] primvars:displayColor = [(0.65, 0.43, 0.24)] }
    def Cube "BackWall" { double size = 1 double3 xformOp:scale = (8, 0.16, 3) double3 xformOp:translate = (0, 3, 1.5) uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"] color3f[] primvars:displayColor = [(0.9, 0.86, 0.78)] }
    def Cube "LeftWall" { double size = 1 double3 xformOp:scale = (0.16, 6, 3) double3 xformOp:translate = (-4, 0, 1.5) uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"] color3f[] primvars:displayColor = [(0.86, 0.82, 0.74)] }
    def Cube "KitchenIsland" { double size = 1 double3 xformOp:scale = (2.2, 1.05, 0.9) double3 xformOp:translate = (0, 0.15, 0.45) uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"] color3f[] primvars:displayColor = [(0.9, 0.88, 0.82)] }
    def Cube "BackCounter" { double size = 1 double3 xformOp:scale = (3.2, 0.62, 0.9) double3 xformOp:translate = (0, 2.35, 0.45) uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"] color3f[] primvars:displayColor = [(0.08, 0.08, 0.08)] }
    def Cube "OverheadCabinet" { double size = 1 double3 xformOp:scale = (2.6, 0.32, 0.62) double3 xformOp:translate = (0, 2.9, 2.25) uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"] color3f[] primvars:displayColor = [(0.75, 0.66, 0.55)] }
    def Camera "MasterCamera" { float focalLength = 35 double3 xformOp:translate = (0, -4.2, 1.55) uniform token[] xformOpOrder = ["xformOp:translate"] }
}
"""'''


def _church_usd_script() -> str:
    return '''USD_CONTENT = """#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "World"
{
    def Cube "Courtyard" { double size = 1 double3 xformOp:scale = (24, 26, 0.08) double3 xformOp:translate = (0, 1, -0.04) uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"] color3f[] primvars:displayColor = [(0.25, 0.35, 0.22)] }
    def Cube "ChurchBody" { double size = 1 double3 xformOp:scale = (7, 9, 5.5) double3 xformOp:translate = (0, 7, 2.75) uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"] color3f[] primvars:displayColor = [(0.55, 0.53, 0.5)] }
    def Cube "HeroWhite" { double size = 1 double3 xformOp:scale = (0.45, 0.28, 1.75) double3 xformOp:translate = (0, -2.2, 0.875) uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"] color3f[] primvars:displayColor = [(1, 1, 1)] }
    def Camera "WideCamera" { float focalLength = 28 double3 xformOp:translate = (0, -16, 5.2) uniform token[] xformOpOrder = ["xformOp:translate"] }
}
"""'''
