# CS239_GradAdvisor — Graduate Student Affairs Multi-Agent System

**Course:** CS239 — Multi-Agent Frameworks  
**Phase:** 1 (complete) · Phase 2 (web demo)  
**License:** MIT

Two communicating agents with distinct roles:

| Agent | Role | Implementation |
|---|---|---|
| **Advisor Agent** | Student-facing orchestrator | LLM (Qwen3 via SiliconFlow) + MCP tools |
| **Policy Checker Agent** | Rule enforcement | Deterministic A2A service, no LLM |

---

## Quick Start

```bash
pip install -r requirements.txt

# Terminal 1 — Policy Checker A2A service
python -m src.agents.policy_agent --port 9001

# Terminal 2 — Web demo (recommended for recording)
export SILICONFLOW_API_KEY=your_key
python -m src.web_demo
# Open http://127.0.0.1:8000

# OR: terminal CLI demo
python -m src.run_demo
```

---

## Architecture

```
Browser / Student
    │  HTTP + SSE (web_demo.py)
    ▼
Advisor Agent  (LLM: Qwen3-8B)
    ├─ MCP / stdio ──► src.tools.student_db  (4 tools)
    │                   get_student_record, get_course_info,
    │                   check_candidacy, check_funding_status
    └─ A2A / JSONRPC ──► Policy Checker Agent  (port 9001)
                          deterministic rule engine
```

**Key design:** `delegate_to_policy_checker` is a real OpenAI-format tool
in the LLM's tool list — not a text trigger. Works with any tool-calling LLM.

---

## Robustness Fixes (vs earlier version)

| Fix | Problem | Solution |
|---|---|---|
| 1 | Text-trigger never fires with Qwen3 | `delegate_to_policy_checker` as structured tool |
| 2 | LLM stops before delegating | Block `finish_reason=stop` until `delegated=True` |
| 3 | Alternating tool loops (A→B→A→B) | Per-tool total call cap (3) + consecutive cap (2) |
| 4 | `final_response` left empty | Fallback synthesises from last `a2a_receive` |

---

## Traces

Three complete live traces in `traces/` — all have `a2a_send`, `a2a_receive`,
and non-empty `final_response`.

| Trace | Scenario | Rule | Decision |
|---|---|---|---|
| `trace_01_course_petition.json` | S001 late add CS229, medical | `POLICY-PETITION-004` | approved |
| `trace_02_deadline_extension.json` | S003 3rd extension, probation | `POLICY-EXT-001` | needs_dgs_review |
| `trace_03_loa_request.json` | S002 LOA, RA-funded, visa stripped | `POLICY-LOA-003` | conditional |

---

## Privacy

`visa_status`, `immigration_hold`, `financial_aid_amount` are stripped from every
A2A payload before it leaves the Advisor Agent, enforced in `sanitize_for_policy()`.
The Policy Checker also validates incoming payloads and rejects prohibited fields.

See `policies.md` for full per-agent permission and isolation specification.
