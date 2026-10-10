"""Configuration and master data loading."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass

DATA_DIR = Path(__file__).parent / "data"
SCENARIO_DIR = DATA_DIR / "scenarios"

# LLM_PROVIDER: offline | gemini | openai | anthropic | ollama
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "offline").strip().lower()
DEFAULT_MODELS = {
    "gemini": "gemini-flash-latest",   # free tier via Google AI Studio
    "openai": "gpt-5-mini",
    "anthropic": "claude-haiku-5-5",
    "ollama": "llama3.1",
}
LLM_MODEL = os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(LLM_PROVIDER, "")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
USE_CREWAI = os.getenv("USE_CREWAI", "true").lower() == "true"


@lru_cache
def load_json(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def company() -> dict:
    return load_json("company.json")


def vendors() -> dict:
    return load_json("vendors.json")["vendors"]


def hsn_rates() -> dict:
    return load_json("hsn_rates.json")["rates"]


def list_scenarios() -> list[dict]:
    out = []
    for p in sorted(SCENARIO_DIR.glob("*.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        out.append({"id": s["id"], "title": s["title"], "file": p.name})
    return out


def load_scenario(scenario_id: str) -> dict:
    for p in sorted(SCENARIO_DIR.glob("*.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        if s["id"].lower() == scenario_id.lower():
            return s
    raise KeyError(f"Unknown scenario {scenario_id}; available: {[s['id'] for s in list_scenarios()]}")
