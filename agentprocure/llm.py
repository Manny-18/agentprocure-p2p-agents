"""Provider-agnostic LLM access with an offline mode and a numeric-grounding guardrail.

Design rule: every number an agent reports comes from a deterministic tool. The LLM only
explains, prioritises and drafts. If an LLM response contains a figure that is not present in
the tool facts, the response is rejected and the agent falls back to its offline template.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from . import config

LANGCHAIN_PROVIDER = {"gemini": "google_genai", "openai": "openai", "anthropic": "anthropic", "ollama": "ollama"}


class LLMGateway:
    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = (provider or config.LLM_PROVIDER).lower()
        self.model = model or config.LLM_MODEL or config.DEFAULT_MODELS.get(self.provider, "")
        self._chat = None
        self.calls = 0
        self.rejections = 0
        self.retries = 0
        self._last_call = 0.0

    @property
    def online(self) -> bool:
        return self.provider in LANGCHAIN_PROVIDER

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}" if self.online else "offline (deterministic expert templates)"

    def chat_model(self):
        if self._chat is None:
            from langchain.chat_models import init_chat_model
            self._chat = init_chat_model(self.model, model_provider=LANGCHAIN_PROVIDER[self.provider],
                                         temperature=config.LLM_TEMPERATURE)
        return self._chat

    def _invoke(self, call):
        """Run one model call with pacing (free-tier requests-per-minute) and retries on rate limits."""
        for attempt in range(config.LLM_MAX_RETRIES + 1):
            wait = config.LLM_MIN_INTERVAL_S - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()
            self.calls += 1
            try:
                return call()
            except Exception as exc:
                if attempt < config.LLM_MAX_RETRIES and is_rate_limit(exc):
                    self.retries += 1
                    time.sleep(config.LLM_RETRY_WAIT_S * (attempt + 1))
                    continue
                raise

    def narrate(self, *, persona: str, task: str, facts: dict, fallback: str, max_words: int = 140) -> dict:
        """Ask the LLM to explain the facts in the persona's voice; enforce grounding."""
        if not self.online:
            return {"text": fallback, "source": "offline-template", "guardrail": "n/a"}
        prompt = (f"{task}\n\nFACTS (JSON, computed by validated tools - the only numbers you may use):\n"
                  f"{json.dumps(facts, default=str)[:6000]}\n\n"
                  f"Rules: at most {max_words} words; plain business English for an Indian finance audience; "
                  "use Rs and lakh/crore where natural; do NOT introduce any number, date, rate or name that is not in FACTS; "
                  "if something is unknown say so.")
        t0 = time.time()
        try:
            msg = self._invoke(lambda: self.chat_model().invoke([("system", persona), ("user", prompt)]))
            text = msg.content if isinstance(msg.content, str) else " ".join(
                part.get("text", "") for part in msg.content if isinstance(part, dict))
        except Exception as exc:  # network, quota, auth
            return {"text": fallback, "source": "offline-template", "guardrail": f"LLM error: {type(exc).__name__}"}
        ok, bad = numbers_grounded(text, facts)
        if not ok:
            self.rejections += 1
            return {"text": fallback, "source": "offline-template",
                    "guardrail": f"rejected LLM text: ungrounded figures {bad[:5]}", "rejected_text": text}
        return {"text": text.strip(), "source": self.label, "guardrail": "passed", "latency_s": round(time.time() - t0, 2)}

    def extract(self, *, persona: str, text: str, schema) -> Any | None:
        """Structured extraction (e.g. free-text purchase request -> requisition)."""
        if not self.online:
            return None
        try:
            return self._invoke(lambda: self.chat_model().with_structured_output(schema).invoke([("system", persona), ("user", text)]))
        except Exception:
            return None


def is_rate_limit(exc: Exception) -> bool:
    """True for quota / rate-limit errors from any provider (HTTP 429, RESOURCE_EXHAUSTED, RateLimitError)."""
    text = f"{type(exc).__name__} {exc}".lower()
    return any(k in text for k in ("ratelimit", "rate limit", "rate_limit", "429", "resource_exhausted", "resourceexhausted", "quota"))


# ---------------------------------------------------------------- guardrail
_NUM = re.compile(r"(?<![A-Za-z0-9-])(\d[\d,]*(?:\.\d+)?)\s*(lakh|lakhs|crore|cr|%)?", re.I)


def _fact_numbers(obj) -> list[float]:
    found: list[float] = []
    if isinstance(obj, bool):
        return found
    if isinstance(obj, (int, float)):
        found.append(float(obj))
    elif isinstance(obj, str):
        for m in _NUM.finditer(obj):
            try:
                found.append(float(m.group(1).replace(",", "")))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            found += _fact_numbers(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            found += _fact_numbers(v)
    return found


def numbers_grounded(text: str, facts: dict) -> tuple[bool, list[str]]:
    """Every material number in `text` must match a number in `facts` (within 1%, after
    converting lakh/crore). Small integers (<= 31) and years are ignored."""
    pool = _fact_numbers(facts)
    bad = []
    for m in _NUM.finditer(text):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        if unit in ("lakh", "lakhs"):
            val *= 1e5
        elif unit in ("crore", "cr"):
            val *= 1e7
        if unit != "%" and (val <= 31 or 2000 <= val <= 2100):
            continue
        candidates = [val, val / 100] if unit == "%" else [val]
        if not any(abs(c - f) <= max(0.01 if c < 1 else 1.0, abs(f) * 0.01) for c in candidates for f in pool):
            bad.append(m.group(0).strip())
    return (not bad), bad


GATEWAY = LLMGateway()
