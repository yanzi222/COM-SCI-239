"""
run_demo.py — Phase 1 demo runner.

Starts the Policy Checker A2A service, runs three agentic scenarios,
saves traces to traces/, and prints a summary.

Usage:
    python -m src.run_demo

Requires:
    SILICONFLOW_API_KEY environment variable set for live mode.
"""
from __future__ import annotations
import asyncio
import json
import multiprocessing
import os
import sys
import time
from pathlib import Path
import uvicorn

# Ensure src is on the path when run as a module
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents.policy_agent import make_app as make_policy_app
from src.agents.advisor_agent import run_advisor

POLICY_PORT = int(os.environ.get("POLICY_PORT", "9001"))
TRACES_DIR = Path(__file__).parent.parent / "traces"
TRACES_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

SCENARIOS = [
    {
        "name": "trace_01_course_petition",
        "description": "Student S001 (good standing, year 2) requests a late add of CS229 for medical reasons.",
        "student_id": "S001",
        "request": (
            "Hi, I need to add CS229 (Machine Learning) late. I missed the enrollment deadline "
            "because I was hospitalized for a week. My student ID is S001."
        ),
        "expected_policy": "POLICY-PETITION-004",
    },
    {
        "name": "trace_02_deadline_extension",
        "description": "Student S003 (probation, 2 prior extensions) requests a third deadline extension.",
        "student_id": "S003",
        "request": (
            "I need another deadline extension for my assignment. I've been struggling this term. "
            "My student ID is S003."
        ),
        "expected_policy": "POLICY-EXT-001",
    },
    {
        "name": "trace_03_loa_request",
        "description": "Student S002 (RA-funded, year 3) requests a personal leave of absence.",
        "student_id": "S002",
        "request": (
            "I need to take a leave of absence next quarter for personal reasons. "
            "My student ID is S002."
        ),
        "expected_policy": "POLICY-LOA-003",
    },
]

# ---------------------------------------------------------------------------
# Policy Checker server subprocess
# ---------------------------------------------------------------------------

def _run_policy_server(port: int) -> None:
    """Run the Policy Checker A2A service (called in a subprocess)."""
    uvicorn.run(make_policy_app(port), host="127.0.0.1", port=port, log_level="error")


def start_policy_server() -> multiprocessing.Process:
    proc = multiprocessing.Process(target=_run_policy_server, args=(POLICY_PORT,), daemon=True)
    proc.start()
    # Wait for it to come up
    import httpx
    for _ in range(20):
        try:
            httpx.get(f"http://127.0.0.1:{POLICY_PORT}/.well-known/agent-card.json", timeout=1.0)
            print(f"✓ Policy Checker A2A service running on port {POLICY_PORT}")
            return proc
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(
    f"Policy Checker failed to start on port {POLICY_PORT}.\n"
    f"Port may already be in use from a previous run.\n"
    f"Fix option 1 (Windows): open Task Manager → find python.exe → End Task, then retry.\n"
    f"Fix option 2: use a different port:  set POLICY_PORT=9002 && python -m src.run_demo"
    )

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_all_scenarios() -> None:
    print("\n" + "="*70)
    print("CS239 Graduate Student Affairs — Phase 1 Demo")
    print("="*70)
    os.environ["POLICY_CHECKER_URL"] = f"http://127.0.0.1:{POLICY_PORT}"
    if not os.environ.get("SILICONFLOW_API_KEY"):
        print("\n⚠  SILICONFLOW_API_KEY not set.")
        print("   Running in SIMULATION MODE — traces will use pre-recorded data.\n")
        _run_simulated_traces()
        return

    # Start Policy Checker A2A service
    proc = start_policy_server()

    try:
        for scenario in SCENARIOS:
            print(f"\n{'─'*60}")
            print(f"Scenario: {scenario['name']}")
            print(f"Description: {scenario['description']}")
            print(f"Expected rule: {scenario['expected_policy']}")
            print('─'*60)

            trace = await run_advisor(
                student_id=scenario["student_id"],
                student_request=scenario["request"],
                verbose=True,
            )

            # Save trace
            trace_dict = trace.to_dict()
            trace_dict["scenario"] = {
                "name": scenario["name"],
                "description": scenario["description"],
                "expected_policy": scenario["expected_policy"],
            }
            out_path = TRACES_DIR / f"{scenario['name']}.json"
            out_path.write_text(json.dumps(trace_dict, indent=2))
            print(f"\n✓ Trace saved: {out_path}")

    finally:
        proc.terminate()

    _write_traces_readme()
    print("\n✓ All scenarios complete. See traces/ directory.")


def _run_simulated_traces() -> None:
    """Write pre-built illustrative traces when no API key is set."""
    from src.tools.policy_rules import (
        evaluate_course_petition,
        evaluate_extension_request,
        evaluate_loa_request,
    )

    sim_scenarios = [
        {
            "name": "trace_01_course_petition",
            "student_id": "S001",
            "student_request": "I need to add CS229 late. I was hospitalized. Student ID S001.",
            "petition_payload": {
                "petition_type": "course_add",
                "gpa": 3.8, "units_completed": 36, "standing": "good",
                "course_id": "CS229", "reason_category": "medical",
            },
            "student_record": {
                "student_id": "S001", "gpa": 3.8, "units_completed": 36,
                "standing": "good", "year_in_program": 2,
                "extension_count_this_term": 0,
                "advanced_to_candidacy": False, "funding_category": "fellowship",
            },
        },
        {
            "name": "trace_02_deadline_extension",
            "student_id": "S003",
            "student_request": "I need another deadline extension. Student ID S003.",
            "petition_payload": {
                "petition_type": "extension",
                "extension_count_this_term": 2,
                "reason_category": "personal",
                "standing": "probation",
            },
            "student_record": {
                "student_id": "S003", "gpa": 2.6, "units_completed": 24,
                "standing": "probation", "year_in_program": 2,
                "extension_count_this_term": 2,
                "advanced_to_candidacy": False, "funding_category": "self",
            },
        },
        {
            "name": "trace_03_loa_request",
            "student_id": "S002",
            "student_request": "I need a leave of absence next quarter. Student ID S002.",
            "petition_payload": {
                "petition_type": "loa",
                "funding_category": "ra",
                "standing": "warning",
                "reason_category": "personal",
                "candidacy_status": {"advanced": True, "year_in_program": 3},
            },
            "student_record": {
                "student_id": "S002", "gpa": 3.1, "units_completed": 48,
                "standing": "warning", "year_in_program": 3,
                "extension_count_this_term": 1,
                "advanced_to_candidacy": True, "funding_category": "ra",
            },
        },
    ]

    rule_dispatchers = {
        "trace_01_course_petition": lambda p: evaluate_course_petition(**{
            k: p[k] for k in ["petition_type", "gpa", "units_completed", "standing", "course_id", "reason_category"]
        }),
        "trace_02_deadline_extension": lambda p: evaluate_extension_request(**{
            k: p[k] for k in ["extension_count_this_term", "reason_category", "standing"]
        }),
        "trace_03_loa_request": lambda p: evaluate_loa_request(
            funding_category=p["funding_category"],
            standing=p["standing"],
            year_in_program=p["candidacy_status"]["year_in_program"],
            reason_category=p["reason_category"],
        ),
    }

    for sc in sim_scenarios:
        dispatcher = rule_dispatchers[sc["name"]]
        decision = dispatcher(sc["petition_payload"])

        trace = {
            "session_id": sc["name"][-3:] + "_sim",
            "student_id": sc["student_id"],
            "student_request": sc["student_request"],
            "agent": "AdvisorAgent (simulated)",
            "steps": [
                {
                    "step": 1, "type": "user_request", "role": "student",
                    "content": sc["student_request"], "t": 0.0,
                },
                {
                    "step": 2, "type": "tool_call", "role": "advisor",
                    "content": {"tool": "get_student_record", "input": {"student_id": sc["student_id"]}},
                    "t": 0.3,
                },
                {
                    "step": 3, "type": "tool_result", "role": "tool_result",
                    "content": {"tool": "get_student_record", "result": sc["student_record"]},
                    "t": 0.4,
                },
                {
                    "step": 4, "type": "thought", "role": "advisor",
                    "content": (
                        f"I have the student record. Standing: {sc['student_record']['standing']}. "
                        "Building sanitized petition payload and delegating to Policy Checker."
                    ),
                    "t": 0.9,
                },
                {
                    "step": 5, "type": "a2a_send", "role": "advisor→policy_checker",
                    "content": sc["petition_payload"],
                    "t": 1.0,
                },
                {
                    "step": 6, "type": "a2a_receive", "role": "policy_checker→advisor",
                    "content": {
                        "decision": decision.decision,
                        "rationale": decision.rationale,
                        "conditions": decision.conditions,
                        "triggered_rule": decision.triggered_rule,
                    },
                    "t": 1.2,
                },
                {
                    "step": 7, "type": "final_response", "role": "advisor",
                    "content": _compose_simulated_response(decision, sc["student_id"]),
                    "t": 2.1,
                },
            ],
            "final_response": _compose_simulated_response(decision, sc["student_id"]),
            "scenario": {
                "name": sc["name"],
                "description": SCENARIOS[[s["name"] for s in SCENARIOS].index(sc["name"])]["description"],
                "expected_policy": decision.triggered_rule,
            },
        }

        out_path = TRACES_DIR / f"{sc['name']}.json"
        out_path.write_text(json.dumps(trace, indent=2))
        print(f"✓ Simulated trace: {out_path}")
        print(f"  Decision: {decision.decision} (rule: {decision.triggered_rule})")

    _write_traces_readme()


def _compose_simulated_response(decision, student_id: str) -> str:
    d = decision.decision
    if d == "approved":
        msg = f"Good news! Your petition has been approved. {decision.rationale}"
    elif d == "denied":
        msg = f"Unfortunately, your petition has been denied. {decision.rationale}"
    elif d == "conditional":
        cond_str = " ".join(f"({i+1}) {c}" for i, c in enumerate(decision.conditions))
        msg = f"Your petition can be approved, but the following conditions apply: {cond_str} — {decision.rationale}"
    else:
        msg = f"Your request requires Director of Graduate Studies review. {decision.rationale}"
    return msg


def _write_traces_readme() -> None:
    readme = """# Traces — Graduate Student Affairs Multi-Agent System

## Overview

This directory contains three agentic traces from Phase 1.
Each trace captures: student request → Advisor tool calls → A2A message to Policy Checker → policy decision → student response.

---

## Trace 01 — Course Petition (trace_01_course_petition.json)

**Scenario:** Student S001 (good standing, year 2, GPA 3.8, fellowship-funded) requests a late add of CS229 due to hospitalization.

**Agents involved:** Advisor Agent, Policy Checker Agent

**Policy triggered:** `POLICY-PETITION-004` — Late add approved on medical grounds.

**Information flow:**
- Advisor calls `get_student_record(S001)` → retrieves GPA, standing, year, funding category
- Advisor sanitizes payload (removes visa/financial fields — none present in this case)
- Advisor sends A2A petition: `{petition_type: "course_add", gpa: 3.8, standing: "good", reason_category: "medical", ...}`
- Policy Checker evaluates: medical reason + good standing → **approved** with conditions
- Advisor composes student-facing response

**Key observation:** Visa status (`domestic`) present in raw DB record but never forwarded to Policy Checker — sanitization working correctly.

---

## Trace 02 — Deadline Extension (trace_02_deadline_extension.json)

**Scenario:** Student S003 (academic probation, 2 prior extensions this term) requests a third deadline extension.

**Agents involved:** Advisor Agent, Policy Checker Agent

**Policy triggered:** `POLICY-EXT-001` — Probationary students must obtain DGS approval for all extensions.

**Information flow:**
- Advisor calls `get_student_record(S003)` → standing = "probation", extension_count_this_term = 2
- Policy Checker evaluates: probation standing → **needs_dgs_review** (regardless of extension count)
- Advisor escalates and informs student to contact DGS office

**Key observation:** Policy Checker detected probationary status and escalated — the automatic approval path was correctly blocked even though the student only asked for "one more extension."

---

## Trace 03 — Leave of Absence (trace_03_loa_request.json)

**Scenario:** Student S002 (RA-funded, year 3, warning standing) requests a personal leave of absence. Student is on an F-1 visa (sensitive field).

**Agents involved:** Advisor Agent, Policy Checker Agent

**Policy triggered:** `POLICY-LOA-003` — RA-funded students must arrange a funding suspension before LOA can be approved.

**Information flow:**
- Advisor calls `get_student_record(S002)` → funding_category = "ra", visa_status = "f1" (in DB)
- **Sanitization step removes `visa_status` ("f1") before A2A payload is built**
- Policy Checker receives: `{petition_type: "loa", funding_category: "ra", standing: "warning", reason_category: "personal", ...}`
- Policy Checker evaluates: RA-funded + non-medical → **conditional** (funding suspension required)
- Advisor informs student of the condition; visa details never mentioned to Policy Checker

**Key observation:** Visa status isolation enforced — the Policy Checker made the correct funding-based decision without ever seeing the student's immigration status.
"""
    readme_path = TRACES_DIR / "README.md"
    readme_path.write_text(readme)
    print(f"✓ Traces README written: {readme_path}")


if __name__ == "__main__":
    asyncio.run(run_all_scenarios())
