"""
usd_fix_agent.py - Fix-Proposer for the usd_script_agent pipeline.

Unlike fix_agent.py (which mutates a structured SceneSpecSchema scene_config --
a shape usd_script_agent-produced files never have), this operates directly on
the raw USDA text of the file that was actually validated, plus the real
Isaac Sim validation_result.json. It asks an LLM to diagnose each violation
against the actual prims/camera keyframes in the file and return a corrected
full USDA stage, a plain-language summary, and a structured fix list.

There is deliberately no deterministic fallback here: diagnosing why a specific
frustum ray escaped requires real reasoning over the file's actual geometry,
which a fixed template can't approximate the way usd_script_agent's initial
generation can.
"""

import json
import os
from typing import Any, NamedTuple

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from modules.offset_agent.deep_agent import DEFAULT_MODEL, OPENROUTER_BASE_URL
from modules.offset_agent.usd_script_agent import (
    USDScriptError,
    _validate_usda_content,
    _write_usd_file,
)

# Reasoning over a full existing stage (up to ~45KB seen this session) plus
# producing a corrected full copy takes longer than a from-scratch generation --
# usd_script_agent's own MODEL_TIMEOUT_SECONDS (35s) is tuned for that shorter task.
FIX_MODEL_TIMEOUT_SECONDS = 90

USD_FIX_AGENT_PROMPT = """
You are a senior OpenUSD previz fixer for a film-set validation pipeline.

You are given:
1. The full current USDA stage text for a film set.
2. A validation_result JSON from a REAL Isaac Sim PhysX run: {status, violations:
   [{frame, corner, prim}], camera_collisions: [{frame, colliding_with}]}.

Violation semantics:
- A violations entry with prim=null means a sampled camera-frustum ray at that
  frame/corner index escaped into empty space -- nothing solid is there. Fix by
  ADDING geometry (a wall, a ceiling panel, or extending an existing prim's
  scale) at roughly the position that ray would travel through, or by pulling
  the camera's keyframe eye/target closer to the dressed set so the ray no
  longer escapes.
- A violations entry WITH a prim path means the ray hit a prim explicitly
  tagged `is_off_set = 1` (a marker for "outside the intended set") -- the
  camera can see past the set into a marked void. Fix the same way: block the
  gap with geometry, or reframe the camera.
- A camera_collisions entry means the camera rig's own body (not its view) is
  physically embedded in the named prim(s) at that frame -- fix by moving that
  camera's keyframe eye position away from the listed prim, in its
  xformOp:transform.timeSamples matrix.

Your task:
- Diagnose the likely real-world cause per violation by examining the actual
  prim names, transforms, and camera keyframes in the given USDA text.
- Make the MINIMAL edit(s) needed: prefer resizing/repositioning an existing
  prim or nudging a camera keyframe over adding whole new prims, unless
  nothing existing can plausibly cover the gap.
- Every solid prim you add or resize must carry
  `prepend apiSchemas = ["PhysicsCollisionAPI"]` in its prim declaration (see
  existing prims in the input for the exact syntax), or PhysX will not be able
  to register it as a fix on re-validation.
- Preserve everything else in the stage exactly as given where you are not
  making a deliberate fix -- do not rewrite unrelated prims, do not
  rename/reorder prims, do not drop set dressing, lights, or cameras that
  are not implicated in a violation.
- Do not use `xformOp:rotateXYZ` on cameras; camera orientation must stay a
  look-at `xformOp:transform.timeSamples` matrix, matching what's already in
  the file.

Call report_usd_fix_tool exactly once with:
- fixed_usda: the COMPLETE corrected USDA stage text (starting from
  `#usda 1.0`), not a diff/patch.
- summary: 2-4 plain-language sentences for a director/DP -- what was wrong,
  what you changed.
- fixes: a JSON list of {"fix_type": one of "add_wall" | "add_ceiling" |
  "extend_geometry" | "reposition_camera" | "add_collision", "target_id": the
  frame/prim/camera name involved, "rationale": one sentence}.

Return a short final message after the tool call.
"""


class UsdFixResult(NamedTuple):
    summary: str
    fixes: list[dict[str, Any]]
    fixed_path: str
    fixed_content: str
    source: str


def propose_usd_fix(
    *,
    usda_content: str,
    validation_result: dict[str, Any],
    output_filename: str = "fixed_set.usda",
) -> UsdFixResult:
    if not os.getenv("OPENROUTER_API_KEY"):
        raise USDScriptError(
            "USD fix agent requires OPENROUTER_API_KEY -- there is no deterministic "
            "fallback for reasoning about a validation result."
        )

    # A single direct tool-calling completion, not a `deepagents` planning
    # loop -- that architecture made this take 15-20+ sequential LLM round
    # trips for what only ever needed one tool call (see the matching note
    # in usd_script_agent.py's _generate_script_with_deep_agent).
    llm = ChatOpenAI(
        model=DEFAULT_MODEL,
        openai_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openai_api_base=OPENROUTER_BASE_URL,
        temperature=0.1,
        # The fixed_usda argument is the ENTIRE corrected stage text, larger
        # than a script that merely produces one -- without an explicit cap
        # the response gets cut off mid-tool-call for anything but the
        # smallest stages (see the matching note in usd_script_agent.py's
        # _call_script_tool, which hit exactly this failure mode).
        max_tokens=24000,
        timeout=FIX_MODEL_TIMEOUT_SECONDS,
        max_retries=1,
        default_headers={
            "HTTP-Referer": "https://offset-previz.hackathon",
            "X-Title": "Offset USD Fix Agent",
        },
    )

    @tool
    def report_usd_fix_tool(fixed_usda: str, summary: str, fixes: list[dict]) -> str:
        """Report the corrected USDA stage, a plain-language summary, and the fixes made."""
        return "USD fix captured."

    # Forced, not just offered -- see the matching note in
    # usd_script_agent.py's _generate_script_with_deep_agent.
    llm_with_tool = llm.bind_tools([report_usd_fix_tool], tool_choice="report_usd_fix_tool")
    human_content = (
        "Current USDA stage:\n```usda\n" + usda_content + "\n```\n\n"
        "validation_result.json:\n```json\n" + json.dumps(validation_result, indent=2) + "\n```"
    )
    response = llm_with_tool.invoke([
        {"role": "system", "content": USD_FIX_AGENT_PROMPT},
        {"role": "user", "content": human_content},
    ])

    fixed_usda = None
    summary = ""
    fixes: list[dict[str, Any]] = []
    for tool_call in response.tool_calls or []:
        if tool_call.get("name") == "report_usd_fix_tool":
            args = tool_call.get("args", {})
            if isinstance(args.get("fixed_usda"), str) and args["fixed_usda"].strip():
                fixed_usda = args["fixed_usda"]
                summary = args.get("summary") or ""
                fixes = args.get("fixes") or []
                break
    if not fixed_usda:
        raise USDScriptError("USD fix agent did not call the report tool.")

    _validate_usda_content(fixed_usda)

    fixed_path = _write_usd_file(fixed_usda, output_filename)
    return UsdFixResult(
        summary=summary,
        fixes=fixes,
        fixed_path=fixed_path,
        fixed_content=fixed_usda,
        source="llm-deepagent",
    )
