"""
chains.py - LangChain chains & Agent Tool Bindings via OpenRouter.
Scoped within offset_agent module.

Model Routing Rules:
- HaikuChain (~anthropic/claude-haiku-latest): Clarifying questions (1-2 targeted questions at a time).
- SonnetExtractChain (anthropic/claude-sonnet-4-6): Structured JSON extraction & tool calling.
- SonnetFixChain (anthropic/claude-sonnet-4-6): Reasoning and fix proposals for physics/coverage flags.
- OpusEscalationChain (anthropic/claude-opus-5): Optional escalation chain.
"""

import os
import json
import re
from typing import Dict, Any, Tuple, Optional
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from modules.offset_agent.tools import OFFSET_AGENT_TOOLS

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Model identifiers mapped to OpenRouter compatible strings
MODEL_MAP = {
    "haiku": "~anthropic/claude-haiku-latest",
    "sonnet": "anthropic/claude-sonnet-4-6",
    "opus": "anthropic/claude-opus-5",
    "anthropic.claude-haiku-4-5-20251001-v1:0": "~anthropic/claude-haiku-latest",
    "anthropic.claude-sonnet-4-6": "anthropic/claude-sonnet-4-6",
    "anthropic.claude-opus-5": "anthropic/claude-opus-5",
}


def get_llm(model_key: str = "haiku", temperature: float = 0.2) -> ChatOpenAI:
    """Returns a ChatOpenAI instance configured for OpenRouter."""
    model_name = MODEL_MAP.get(model_key, MODEL_MAP["haiku"])
    return ChatOpenAI(
        model=model_name,
        openai_api_key=OPENROUTER_API_KEY,
        openai_api_base=OPENROUTER_BASE_URL,
        temperature=temperature,
        default_headers={
            "HTTP-Referer": "https://offset-previz.hackathon",
            "X-Title": "Offset Film Previz Validation Tool",
        },
    )


def get_agent_with_tools(model_key: str = "sonnet", temperature: float = 0.1):
    """
    Returns an LLM instance with bound Offset Agent Tools:
    - generate_usd_tool
    - check_coverage_tool
    - check_physics_tool
    """
    llm = get_llm(model_key=model_key, temperature=temperature)
    return llm.bind_tools(OFFSET_AGENT_TOOLS)


# ---------------------------------------------------------------------------
# 1. Haiku Chain: Clarifying Questions Agent
# ---------------------------------------------------------------------------
HAIKU_SYSTEM_PROMPT = """You are Offset Assistant, a film set pre-visualization expert for NVIDIA Omniverse.
Your job is to talk to director/DP users about their set requirements in natural language.

RULES FOR CLARIFYING QUESTIONS:
1. Review the user's description of their set and identify what key spatial data is present or missing.
   Required Data:
   - Room / Wall layout (wall count, dimensions in meters, height, open gaps)
   - Floor dimensions (width x depth in meters)
   - Camera shot list (focal length in mm, start and end dolly coordinates, duration in seconds)
   - Lighting / Rigging if mentioned

2. ASK TARGETED FOLLOW-UP QUESTIONS:
   - Ask ONLY ONE OR TWO questions at a time. Never dump a wall of questions.
   - Be concise, friendly, and practical (like a seasoned gaffer or virtual production supervisor).
   - If key information is missing, ask for reasonable defaults or quick clarifying numbers.

3. IF ENOUGH DETAIL IS ALREADY GATHERED:
   - Briefly state that you have all the necessary parameters to generate the set and ask if they are ready for scene extraction.
"""


def run_haiku_clarifying(messages: list, current_config: Optional[dict] = None) -> str:
    """Runs the Haiku chain to ask 1-2 clarifying questions."""
    llm = get_llm("haiku", temperature=0.3)
    
    formatted_messages = [SystemMessage(content=HAIKU_SYSTEM_PROMPT)]
    for msg in messages:
        if msg["role"] == "user":
            formatted_messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            formatted_messages.append(AIMessage(content=msg["content"]))
            
    if current_config:
        formatted_messages.append(
            SystemMessage(content=f"Current draft config: {json.dumps(current_config)}")
        )
        
    response = llm.invoke(formatted_messages)
    return response.content.strip()


# ---------------------------------------------------------------------------
# 2. Sonnet Chain: Structured JSON Extraction Agent with Tool Binding
# ---------------------------------------------------------------------------
SONNET_EXTRACT_SYSTEM_PROMPT = """You are Offset Technical Parser, an expert CAD & Virtual Production compiler.
Your task is to extract a strictly valid JSON scene configuration matching the required schema from the user's film set conversation.

REQUIRED JSON SHAPE:
{
  "walls": [
    {
      "id": "wall_1",
      "position": [0.0, 3.0, 1.5],
      "width": 8.0,
      "height": 3.0,
      "thickness": 0.2,
      "rotation": 0.0
    }
  ],
  "floor": {
    "width": 8.0,
    "depth": 6.0
  },
  "shots": [
    {
      "shot_id": "shot_1",
      "focal_length_mm": 35.0,
      "start_position": [-3.0, -2.0, 1.6],
      "end_position": [1.0, 0.0, 1.6],
      "duration_seconds": 5.0
    }
  ]
}

COORDINATE SYSTEM:
- Z is UP (meters).
- Origin [0, 0, 0] is on the center floor surface.
- Room defaults if unstated: 8m wide (X), 6m deep (Y), 3m high (Z).
- Standard 3-wall bedroom set example:
  * North wall: position [0, 3.0, 1.5], width 8.0, rotation 0.0
  * West wall: position [-4.0, 0, 1.5], width 6.0, rotation 90.0
  * East wall: position [4.0, 0, 1.5], width 6.0, rotation 90.0

Respond ONLY with valid JSON inside a ```json``` code block, followed by a human-friendly markdown summary explanation card.
"""


def run_sonnet_extraction(messages: list) -> Tuple[Optional[dict], str]:
    """Runs Sonnet chain to extract structured JSON scene config and human readable summary."""
    llm = get_llm("sonnet", temperature=0.1)
    
    formatted_messages = [SystemMessage(content=SONNET_EXTRACT_SYSTEM_PROMPT)]
    conversation_text = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in messages])
    formatted_messages.append(
        HumanMessage(content=f"Extract the complete set config from this dialogue:\n\n{conversation_text}")
    )
    
    response = llm.invoke(formatted_messages).content
    
    # Extract JSON code block
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)
    config = None
    if json_match:
        try:
            config = json.loads(json_match.group(1))
        except Exception as e:
            print("Failed to parse extracted JSON:", e)
            
    summary = re.sub(r"```json.*?```", "", response, flags=re.DOTALL).strip()
    return config, summary


# ---------------------------------------------------------------------------
# 3. Sonnet Fix Chain: Reasoning on Physics / Coverage Issues
# ---------------------------------------------------------------------------
SONNET_FIX_SYSTEM_PROMPT = """You are Offset Scene Optimizer.
You are given a film set JSON configuration and a list of physical/camera violation flags (e.g. wall clipping, light stand intrusion, camera out-of-bounds, target occlusion).

Your job is to:
1. Explain the root cause of the violation in director-friendly terminology.
2. Propose concrete numeric adjustments to wall positions, camera focal lengths, or dolly paths to fix the issue.
3. Return the updated JSON configuration.
"""


def run_sonnet_fix_proposal(current_config: dict, issues: list) -> Tuple[dict, str]:
    """Runs Sonnet fix reasoning chain on physics/coverage issues."""
    llm = get_llm("sonnet", temperature=0.2)
    
    prompt = f"""Current Scene Config:
{json.dumps(current_config, indent=2)}

Detected Issues:
{json.dumps(issues, indent=2)}

Propose a fix with corrected parameters and return the modified JSON inside ```json``` code block."""

    response = llm.invoke([SystemMessage(content=SONNET_FIX_SYSTEM_PROMPT), HumanMessage(content=prompt)]).content
    
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL)
    updated_config = current_config
    if json_match:
        try:
            updated_config = json.loads(json_match.group(1))
        except Exception as e:
            print("Failed to parse fix JSON:", e)
            
    explanation = re.sub(r"```json.*?```", "", response, flags=re.DOTALL).strip()
    return updated_config, explanation


# ---------------------------------------------------------------------------
# 4. Opus Chain: Optional Escalation Path
# ---------------------------------------------------------------------------
def run_opus_escalation(prompt_text: str) -> str:
    """Escalation path to Opus model for complex layout reasoning."""
    llm = get_llm("opus", temperature=0.2)
    response = llm.invoke([
        SystemMessage(content="You are Offset Lead Architectural Supervisor. Resolve complex film set spatial dilemmas."),
        HumanMessage(content=prompt_text)
    ])
    return response.content
