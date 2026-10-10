"""Policy Advisor: answers employees' policy and compliance questions with clause citations (RAG).

Retrieve -> generate -> verify:
  1. retrieve the most relevant clauses from the knowledge base (BM25, or hybrid with embeddings);
  2. with an LLM, a LangChain LCEL chain (prompt | model | parser) writes a short answer that cites clause ids;
  3. the answer is accepted only if every cited clause was actually retrieved, at least one is cited, and every
     number in it appears in the retrieved text; otherwise (or offline) an extractive answer quotes the clauses.
"""
from __future__ import annotations

import re

from ..knowledge import kb, tokenize
from ..llm import GATEWAY, numbers_grounded

ADVISOR_SYSTEM = ("You are the Policy Advisor for Meridian Precision Components' procurement team. You answer "
                  "employees' questions about the procurement policy and Indian compliance rules using only the "
                  "extracts provided. You are precise, plain-spoken and you always cite clause ids.")
ADVISOR_HUMAN = ("Question: {question}\n\nExtracts (clause id, title, text):\n{context}\n\n"
                 "Answer in at most 120 words. Put the clause id in square brackets after each point, for example "
                 "[POL-4.2]. Use only these extracts and do not add numbers that are not in them. If the extracts do "
                 "not answer the question, say that the policy does not cover it and who to ask.")
CITE_RE = re.compile(r"\[((?:POL|REG)-[A-Z]*-?\d+(?:\.\d+)?)\]")


def _chain():
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    prompt = ChatPromptTemplate.from_messages([("system", ADVISOR_SYSTEM), ("human", ADVISOR_HUMAN)])
    return prompt | GATEWAY.chat_model() | StrOutputParser()


def _extractive(question: str, hits: list[dict]) -> str:
    """Offline answer: the most relevant sentence of each of the top clauses, quoted with their ids."""
    if not hits:
        return "The procurement policy does not cover this question. Please ask the Procurement Head."
    q = set(tokenize(question))
    parts = []
    for h in hits[:2]:
        if h is not hits[0] and h["score"] < 0.4 * hits[0]["score"]:
            break
        sentences = re.split(r"(?<=[.!?])\s+", h["text"].strip())
        best = max(range(len(sentences)), key=lambda i: (len(q & set(tokenize(sentences[i]))), -i))
        parts.append(f"{h['title']} [{h['clause']}]: {sentences[best]}")
    return " ".join(parts)


def ask_policy(question: str, k: int = 4) -> dict:
    hits = kb().retrieve(question, k=k)
    retrieved = [{"clause": h["clause"], "title": h["title"], "source": h["source"], "score": h["score"]} for h in hits]
    fallback = _extractive(question, hits)
    out = {"question": question, "retrieval": kb().mode, "retrieved": retrieved}
    if not (GATEWAY.online and hits) or GATEWAY.disabled_reason:
        return {**out, "answer": fallback, "citations": CITE_RE.findall(fallback), "source": "extractive (offline)",
                "guardrail": "n/a" if not GATEWAY.online else f"LLM error: {GATEWAY.disabled_reason}"}
    context = "\n\n".join(f"[{h['clause']}] {h['title']}\n{h['text']}" for h in hits)
    try:
        answer = GATEWAY._invoke(lambda: _chain().invoke({"question": question, "context": context}))
    except Exception as exc:
        why = GATEWAY.disabled_reason or type(exc).__name__
        return {**out, "answer": fallback, "citations": CITE_RE.findall(fallback), "source": "extractive (offline)",
                "guardrail": f"LLM error: {why}"}
    cites = CITE_RE.findall(answer)
    allowed = {h["clause"] for h in hits}
    problems = []
    if not cites:
        problems.append("no clause cited")
    if set(cites) - allowed:
        problems.append(f"cited clauses not retrieved {sorted(set(cites) - allowed)}")
    ok, bad = numbers_grounded(answer, {"context": context})
    if not ok:
        problems.append(f"ungrounded figures {bad[:3]}")
    if problems:
        return {**out, "answer": fallback, "citations": CITE_RE.findall(fallback), "source": "extractive (offline)",
                "guardrail": "rejected LLM answer: " + "; ".join(problems), "rejected_text": answer}
    return {**out, "answer": answer.strip(), "citations": sorted(set(cites)), "source": GATEWAY.label, "guardrail": "passed"}
