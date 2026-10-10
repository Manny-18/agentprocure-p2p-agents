"""Helpers every agent uses to record what it did (tools, findings, decision, rationale)."""
from __future__ import annotations

import time
from contextlib import contextmanager

from .personas import PERSONAS


class StepRecorder:
    """Collects tool calls during one agent step and produces a uniform audit record."""

    def __init__(self, agent_key: str):
        self.agent_key = agent_key
        self.persona = PERSONAS[agent_key]
        self.tools: list[dict] = []
        self.t0 = time.perf_counter()

    def tool(self, name: str, inputs: dict, output, summary: str):
        self.tools.append({"tool": name, "input": inputs, "summary": summary})
        return output

    def report(self, *, decision: str, findings: list[dict] | None = None, rationale: dict | None = None,
               highlights: list[str] | None = None, extra: dict | None = None) -> dict:
        return {
            "agent": self.agent_key,
            "title": self.persona["title"],
            "framework": self.persona["framework"],
            "mandate": self.persona["mandate"],
            "tools": self.tools,
            "findings": findings or [],
            "decision": decision,
            "highlights": highlights or [],
            "rationale": (rationale or {}).get("text", ""),
            "rationale_source": (rationale or {}).get("source", "offline-template"),
            "guardrail": (rationale or {}).get("guardrail", "n/a"),
            "elapsed_ms": round((time.perf_counter() - self.t0) * 1000, 1),
            **(extra or {}),
        }


def severity_counts(findings: list[dict]) -> dict:
    out: dict[str, int] = {}
    for f in findings:
        out[f["severity"]] = out.get(f["severity"], 0) + 1
    return out
