"""
fix_agent.py - Fix-Proposer Reasoning Agent & Scene Config Mutator

Component 3 for Offset Pre-Visualization System.
Analyzes combined evidence: {shot_id, scene_config, coverage_flags, physics_flags}
and proposes minimal fixes from a fixed set of options using Claude 3.5 Sonnet on OpenRouter.

Provides:
  - propose_fixes(evidence: dict) -> dict
  - apply_fix(scene_config: dict, fix: dict) -> dict
"""

import os
import json
import re
from typing import Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

FIX_AGENT_SYSTEM_PROMPT = """You are Offset Film Set Safety & Coverage Advisor.
Your job is to analyze spatial coverage flags and PhysX simulation stability flags, and propose the minimal fix per flag from this FIXED SET OF FIX TYPES:
- reposition_camera
- change_lens
- add_wild_wall
- add_bracing
- add_mass

IMPORTANT - ground your fix in what the render worker actually re-checks, not just what
sounds plausible. A fix that doesn't change the value the worker inspects will show as
UNRESOLVED on re-render, which the director will see:

- Every `coverage_flags` entry from this worker (shape: shot_id, frame, edge, gap_degrees)
  is caused SOLELY by that shot's `focal_length_mm` (the worker never reads camera position
  or wall geometry when producing coverage flags). The ONLY fix type that can clear a
  coverage flag on re-render is `change_lens`, raising focal_length_mm to at least 28
  (prefer 35mm+ for a safe margin). Do NOT propose `reposition_camera` or `add_wild_wall`
  for a coverage flag from this worker - repositioning the camera will not change the
  flag and will fail re-verification.
- Every `physics_flags` entry with `stable: false` is caused by the prim's path/position
  matching a hardcoded rule (path containing "LightStandA", or height/lateral thresholds).
  Propose `add_bracing` or `add_mass` on that `prim_id` - but note in the rationale that
  this fix targets the physically correct cause (added stability) even though the current
  worker build doesn't yet read bracing/mass state back into its stability check, so it may
  still show as unresolved on re-render until that's wired up.
- `collision_flags` come from a real Isaac Sim PhysX raycast run (frustum-vs-set-geometry,
  not this worker's placeholder check), with two shapes:
  - `type: "frustum_off_set"` or `"frustum_escaped"` (fields: frame, corner, prim): a sampled
    frustum ray hit a prim tagged `is_off_set` (or escaped the far clip entirely) - the camera
    is seeing past the physical set. Propose `reposition_camera` (aim/move the camera shot_id
    back toward the set) or `add_wild_wall` (add set geometry to block the gap at `prim`'s
    position) - whichever is the smaller change. `change_lens` does NOT fix this (narrowing
    focal length doesn't guarantee the same rays stay on-set) - do not propose it here.
  - `type: "camera_body_collision"` (fields: frame, colliding_with): the camera rig itself is
    physically embedded in the listed prim(s). Propose `reposition_camera` to move the shot's
    start/end position clear of that prim.

FIX TYPE RULES:
1. `change_lens`: The only reliable fix for a `coverage_flags` entry from this worker. Increase focal_length_mm (>= 28, prefer 35mm+). Never use it for `collision_flags`.
2. `add_bracing` / `add_mass`: Use when physics_flags report rigid body tipping or sliding (e.g. LightStandA tipped over). Provide target_id, mass_kg or bracing_type.
3. `reposition_camera` / `add_wild_wall`: The correct fixes for `collision_flags` (frustum-off-set, frustum-escaped, or camera-body-collision) - name the exact frame/prim in the rationale. Also fine for any flag that explicitly describes wall-clipping or an off-set void gap by name. Not for the focal-length-driven `coverage_flags` this worker produces today.

This proposal is shown to a director/DP before anything is applied - they decide whether
to accept and re-render. Write `summary` for that person: plain language, no prim paths
or JSON jargon, explain what's wrong and what you're proposing to do about it.

OUTPUT FORMAT:
Respond with strict JSON ONLY matching this structure:
{{
  "summary": "2-4 sentence plain-language paragraph: what's wrong across all flags, and what fixes you're proposing to resolve them.",
  "fixes": [
    {{
      "flag_type": "coverage",
      "target_id": "shot_id or prim_id",
      "fix_type": "reposition_camera",
      "params": {{ }},
      "rationale": "One sentence explanation of why this fix resolves the flag."
    }}
  ]
}}
"""


def get_fix_llm() -> ChatOpenAI:
    """Returns ChatOpenAI pointed at OpenRouter for anthropic/claude-sonnet-4-6."""
    return ChatOpenAI(
        model="anthropic/claude-sonnet-4-6",
        openai_api_key=OPENROUTER_API_KEY,
        openai_api_base=OPENROUTER_BASE_URL,
        temperature=0.1,
        default_headers={
            "HTTP-Referer": "https://offset-previz.hackathon",
            "X-Title": "Offset Fix Proposer Agent",
        },
    )


def propose_fixes(evidence: dict) -> dict:
    """
    Takes evidence dict:
      {
        "scene_config": {...},
        "coverage_flags": [...],
        "physics_flags": [...]
      }
    Returns dict:
      {
        "fixes": [ ... ]
      }
    """
    llm = get_fix_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", FIX_AGENT_SYSTEM_PROMPT),
        ("human", "Analyze the following simulation and geometry evidence and propose minimal fixes:\n\n{evidence_json}")
    ])

    chain = prompt | llm | JsonOutputParser()
    
    try:
        response = chain.invoke({"evidence_json": json.dumps(evidence, indent=2)})
        return response
    except Exception as e:
        # Fallback heuristic parser if JsonOutputParser encounters code blocks
        raw_res = llm.invoke([
            ("system", FIX_AGENT_SYSTEM_PROMPT),
            ("human", f"Analyze evidence:\n\n{json.dumps(evidence, indent=2)}")
        ]).content
        
        json_match = re.search(r"```json\s*(\{.*?\})\s*```", raw_res, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))
        return {"fixes": [], "error": str(e)}


def apply_fix(scene_config: dict, fix: dict) -> dict:
    """
    Mutates scene_config JSON according to the fix parameters.
    Returns the updated scene_config dict.
    """
    new_config = json.loads(json.dumps(scene_config))  # Deep copy
    fix_type = fix.get("fix_type")
    params = fix.get("params", {})
    target_id = fix.get("target_id")

    if fix_type == "add_wild_wall":
        walls = new_config.get("walls", [])
        new_wall = {
            "id": params.get("wall_id", f"wild_wall_{len(walls)+1}"),
            "position": params.get("position", [4.0, 0.0, 1.5]),
            "width": params.get("width", 3.0),
            "height": params.get("height", 3.0),
            "thickness": params.get("thickness", 0.2),
            "rotation": params.get("rotation", 90.0),
        }
        walls.append(new_wall)
        new_config["walls"] = walls

    elif fix_type == "change_lens":
        for shot in new_config.get("shots", []):
            if shot.get("shot_id") == target_id or len(new_config.get("shots", [])) == 1:
                shot["focal_length_mm"] = params.get("focal_length_mm", 35.0)

    elif fix_type == "reposition_camera":
        for shot in new_config.get("shots", []):
            if shot.get("shot_id") == target_id or len(new_config.get("shots", [])) == 1:
                if "start_position" in params:
                    shot["start_position"] = params["start_position"]
                if "end_position" in params:
                    shot["end_position"] = params["end_position"]

    elif fix_type in ("add_bracing", "add_mass"):
        # Tag prim / rig in scene_config extra metadata
        rig_bracing = new_config.get("rig_bracing", [])
        rig_bracing.append({
            "target_id": target_id or params.get("target_id"),
            "fix_type": fix_type,
            "params": params
        })
        new_config["rig_bracing"] = rig_bracing

    return new_config
