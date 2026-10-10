"""Shared case state passed between agents in the LangGraph workflow."""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class P2PState(TypedDict, total=False):
    case_id: str
    scenario: dict            # raw inputs: requisition, quotes, GRN, invoice, history
    requisition: dict         # intake agent
    policy: dict              # policy & compliance agent
    sourcing: dict            # CrewAI sourcing crew
    approval: dict            # human-in-the-loop decision
    po: dict                  # buyer agent
    ap: dict                  # accounts payable agent
    tax: dict                 # GST & TDS agent
    resolution: dict          # exception resolver
    treasury: dict            # treasury agent
    memo: dict                # finance controller
    status: str
    trace: Annotated[list[dict[str, Any]], operator.add]   # one report per agent step (audit trail)
