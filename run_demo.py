"""Command-line demo of the AgentProcure multi-agent P2P system.

Examples
  python run_demo.py                       # all scenarios, auto-approve, offline
  python run_demo.py -s S2 --interactive   # you play the approver at the LangGraph interrupt
  python run_demo.py -s S1 --reject        # approver rejects -> case closes
  python run_demo.py --graph               # print the LangGraph workflow as Mermaid
  LLM_PROVIDER=gemini GOOGLE_API_KEY=... python run_demo.py -s S1   # real LLM narration + CrewAI crew
"""
from __future__ import annotations

import argparse
import json
import sys

from agentprocure import config
from agentprocure.graph import mermaid, pending_approval, resume_case, start_case
from agentprocure.llm import GATEWAY
from agentprocure.rules.common import inr

try:
    from rich.console import Console
    from rich.markup import escape
    from rich.panel import Panel
    from rich.table import Table
    console = Console()
except ImportError:  # rich ships with CrewAI; plain print otherwise
    console = None

    def escape(text):
        return text


MONEY_KPIS = {"po_value_incl_gst", "approved_payable", "disputed_amount_protected", "tds_withheld", "itc_claimable",
              "negotiation_value_this_order", "negotiation_value_annual", "msme_interest_accrued"}


def say(text: str = "", style: str | None = None):
    if console:
        console.print(text, style=style, highlight=False)
    else:
        print(text)


def show_step(t: dict):
    e = lambda x: escape(str(x))  # agent text can contain [brackets]; never read them as rich markup
    head = f"[bold]{e(t['title'])}[/bold]  [dim]({e(t['framework'])}, {t['elapsed_ms']} ms)[/dim]"
    body = [f"[cyan]Decision:[/cyan] {e(t['decision'])}"]
    for tool in t["tools"]:
        body.append(f"  [green]tool[/green] {e(tool['tool'])}: {e(tool['summary'])}")
    for f in t["findings"]:
        color = {"BLOCK": "red", "HOLD": "yellow", "HIGH": "red", "WARN": "yellow"}.get(f["severity"], "white")
        body.append(f"  [{color}]{f['severity']}[/{color}] {e(f['code'])}: {e(f['detail'])}")
    for c in t.get("crew", []):
        body.append(f"  [magenta]{e(c['title'])}[/magenta]: {e(c['output'])}")
    body.append(f"[dim]Why ({e(t['rationale_source'])}; guardrail: {e(t['guardrail'])}):[/dim] {e(t['rationale'])}")
    if console:
        console.print(Panel("\n".join(body), title=head, title_align="left", border_style="blue"))
    else:
        print(f"\n== {t['title']} ==\n" + "\n".join(body))


def run(scenario_id: str, interactive: bool, reject: bool) -> dict:
    sc = config.load_scenario(scenario_id)
    say(f"\n{'=' * 100}\n{sc['id']}: {sc['title']}\n{sc['story']}", "bold")
    case_id, result = start_case(sc, f"{sc['id']}-demo")
    pack = pending_approval(result)
    if pack:
        for t in result["trace"]:
            show_step(t)
        say(f"\n>>> HUMAN APPROVAL NEEDED ({escape(pack['approver_role'])}): {escape(pack['question'])}", "bold yellow")
        for w in pack["warnings"]:
            say(f"    warning: {escape(w)}", "yellow")
        if interactive:
            ans = input("    approve? [y/n] ").strip().lower()
            comment = input("    comment (optional): ").strip()
            decision = {"decision": "approve" if ans.startswith("y") else "reject", "comment": comment}
        else:
            decision = ({"decision": "reject", "comment": "Rejected in demo: defer to next quarter."} if reject
                        else {"decision": "approve", "comment": "Approved as recommended (demo)."})
            say(f"    -> {decision['decision'].upper()} (demo mode)", "yellow")
        shown = len(result["trace"])
        result = resume_case(case_id, decision)
        for t in result["trace"][shown:]:
            show_step(t)
    else:
        for t in result["trace"]:
            show_step(t)
    memo = result["memo"]
    say(f"\nFINAL STATUS: {memo['status']}", "bold green" if memo["status"].startswith("COMPLETED") else "bold red")
    if console:
        table = Table(title="Case KPIs", show_header=True)
        table.add_column("KPI")
        table.add_column("Value", justify="right")
        for k, v in memo["kpis"].items():
            if v is None:
                continue
            money = k in MONEY_KPIS
            table.add_row(k.replace("_", " "), inr(v) if money else str(v))
        console.print(table)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="AgentProcure: domain-expert AI agents for Procure-to-Pay")
    ap.add_argument("-s", "--scenario", default="all", help="S1..S4 or 'all'")
    ap.add_argument("--interactive", action="store_true", help="answer the approval yourself")
    ap.add_argument("--reject", action="store_true", help="approver rejects (demo)")
    ap.add_argument("--graph", action="store_true", help="print the LangGraph workflow as Mermaid and exit")
    ap.add_argument("--json", help="write full case results to this JSON file")
    args = ap.parse_args(argv)
    if args.graph:
        print(mermaid())
        return 0
    say(f"AgentProcure | LLM: {GATEWAY.label} | CrewAI: {'on' if config.USE_CREWAI else 'off'} | as-of {config.company()['as_of']}", "dim")
    ids = [s["id"] for s in config.list_scenarios()] if args.scenario == "all" else [args.scenario]
    results = {i: run(i, args.interactive, args.reject) for i in ids}
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({i: {k: v for k, v in r.items() if k != "__interrupt__"} for i, r in results.items()}, fh, indent=2, default=str)
        say(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
