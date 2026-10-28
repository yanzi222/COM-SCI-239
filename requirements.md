# Requirements — Graduate Student Affairs Multi-Agent System

## Project Overview

A two-agent application that assists graduate students with academic administration:
course petitions, deadline extensions, leave of absence requests, and graduation
clearance checks.

**Course:** CS239 — Multi-Agent Frameworks  
**Domain:** Academic Administration / Graduate Student Affairs  
**Phase:** 1 — Prototype (no safety-enforcing framework)

---

## System Description

### Agents

| Agent | Role | Responsibilities |
|---|---|---|
| **Advisor Agent** | Student-facing orchestrator | Receives student requests, queries student records, drafts responses, delegates policy checks |
| **Policy Checker Agent** | Rule enforcement | Evaluates requests against institutional policy rules, returns approve/deny/conditional decisions |

### Communication Pattern

```
Student → Advisor Agent → (A2A) → Policy Checker Agent
                        ←                              ←
Student ← Advisor Agent (final response with rationale)
```

The Advisor Agent is the only agent that communicates directly with the student.
The Policy Checker Agent is an internal service — students cannot reach it directly.

---

## What the Application Does

1. **Course Petition** — Student requests to add/drop/swap a course after the deadline.
   - Advisor queries student's enrollment history and GPA.
   - Advisor forwards petition + student standing to Policy Checker.
   - Policy Checker returns: approved / denied / conditional (e.g., requires instructor signature).

2. **Deadline Extension** — Student requests an extension on an assignment or exam.
   - Advisor verifies the student has no prior extensions this term.
   - Advisor forwards request, prior extension count, and reason category to Policy Checker.
   - Policy Checker approves up to one extension per term automatically; subsequent ones require DGS approval.

3. **Leave of Absence (LOA)** — Student requests a leave of absence.
   - Advisor checks funding status, visa status category, and time-to-degree.
   - Advisor forwards a sanitized summary (no visa details) to Policy Checker.
   - Policy Checker checks leave eligibility rules and funding hold requirements.

4. **Graduation Clearance** — Student requests graduation clearance check.
   - Advisor pulls requirement completion data.
   - Advisor forwards completion checklist to Policy Checker.
   - Policy Checker returns: cleared / not cleared with missing items listed.

---

## What the Application Must Never Do

| # | Prohibition |
|---|---|
| 1 | **Never approve** a petition that violates Academic Senate policy, regardless of how a request is framed. |
| 2 | **Never share** a student's visa status, immigration hold details, or financial aid specifics with the Policy Checker Agent. |
| 3 | **Never share** one student's academic record with another student's session. |
| 4 | **Never allow** the student to directly invoke or override the Policy Checker Agent. |
| 5 | **Never fabricate** academic records, GPA values, or completion status. |
| 6 | **Never grant** more than one automatic deadline extension per student per term without DGS review. |
| 7 | **Never process** a graduation clearance unless the student has been formally advanced to candidacy. |
| 8 | **Never retain** personally identifiable student data across sessions (stateless by design in Phase 1). |

---

## Tools (MCP)

| Tool | Agent | Description |
|---|---|---|
| `get_student_record` | Advisor | Returns GPA, units, standing, extension count for a given student ID |
| `get_course_info` | Advisor | Returns course metadata: capacity, instructor, prerequisites |
| `check_candidacy` | Advisor | Returns whether student has passed qualifying exam and been advanced |
| `check_funding_status` | Advisor | Returns whether student is on fellowship, RA, TA, or self-funded (no dollar amounts) |
| `evaluate_petition` | Policy Checker | Core rule engine: takes petition type + sanitized facts, returns decision |
| `check_graduation_requirements` | Policy Checker | Checks completion checklist against degree requirements |

---

## Technology Stack

- **Language:** Python 3.11+
- **Agent communication:** A2A SDK (`a2a-sdk`) — same pattern as the CS239 tutorial
- **Tool protocol:** MCP (`mcp` SDK) — local stdio server
- **LLM backend:** SiliconFlow OpenAI-compatible API (Qwen/Qwen3-8B by default)
- **Framework:** Custom async agent loop (no Rakazo required for Phase 1)
- **Traces:** JSON (A2A task format) + Markdown summaries

---

## Repository Layout

```
CS239_GradAdvisor_<YourName>/
├── requirements.md          ← this file
├── policies.md
├── requirements.txt
├── README.md
├── src/
│   ├── agents/
│   │   ├── advisor_agent.py     # Orchestrator + student interface
│   │   └── policy_agent.py      # A2A service: rule-based policy checker
│   ├── tools/
│   │   ├── student_db.py        # Fictional student record MCP tools
│   │   └── policy_rules.py      # Deterministic policy evaluation logic
│   └── run_demo.py              # CLI runner: sends a request, prints trace
└── traces/
    ├── README.md
    ├── trace_01_course_petition.json
    ├── trace_02_deadline_extension.json
    └── trace_03_loa_request.json
```
