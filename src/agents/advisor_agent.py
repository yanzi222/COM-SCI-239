"""
Advisor Agent — Orchestrator (a2a-sdk v1.2.3, mcp v2.3.0).

Architecture (matches CS239 tutorial pattern exactly):

  Student
    │  natural language
    ▼
  Advisor Agent (LLM: SiliconFlow Qwen3)
    │  MCP / stdio  ──► student_db MCP server (subprocess)
    │                    get_student_record, get_course_info,
    │                    check_candidacy, check_funding_status
    │
    │  A2A / JSONRPC ──► Policy Checker Agent (port 9001)
    │                    evaluate_petition (deterministic rules)
    │
    ▼
  Student (final response)

Key difference from tutorial: the LLM's tool calls go through a *live MCP
subprocess*, not inline Python. The tool schemas are discovered dynamically
via list_tools(), and results come back over stdio — identical to how
movie_night/client.py talks to the snack/movie MCP server.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from a2a.client import create_client
from a2a.helpers import new_text_message
from a2a.types import SendMessageRequest
import a2a.types.a2a_pb2 as _pb

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

POLICY_CHECKER_URL = os.environ.get("POLICY_CHECKER_URL", "http://127.0.0.1:9001")
SILICONFLOW_BASE_URL = os.environ.get(
    "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"
)
SILICONFLOW_MODEL = os.environ.get("SILICONFLOW_MODEL", "Qwen/Qwen3-8B")
# Path to the student_db MCP server module
_HERE = Path(__file__).parent.parent  # src/
MCP_SERVER_MODULE = "src.tools.student_db"
MCP_SERVER_CWD = str(_HERE.parent)    # project root

PROHIBITED_FIELDS = {
    "visa_status", "visa_category", "immigration_hold",
    "financial_aid_amount", "aid_package_details",
    "student_name", "student_email", "student_phone",
}

# ---------------------------------------------------------------------------
# delegate_to_policy_checker — a REAL tool (not a text trigger).
# Adding it to the tool list means any OpenAI-compatible LLM (Qwen3, Llama,
# Claude, etc.) invokes delegation via structured tool_use JSON, so the
# exact phrase "ACTION: delegate_to_policy_checker" is never needed.
# ---------------------------------------------------------------------------

DELEGATE_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "delegate_to_policy_checker",
        "description": (
            "Send a sanitized petition to the Policy Checker Agent for a policy decision. "
            "Call this ONCE after gathering all needed student/course data. "
            "Do NOT include visa_status, immigration_hold, financial_aid_amount, "
            "student_name, or student_email. "
            "Returns {decision, rationale, conditions, triggered_rule}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "petition_type": {
                    "type": "string",
                    "enum": ["course_add", "course_drop", "extension", "loa", "graduation"],
                    "description": "Type of petition.",
                },
                "gpa": {"type": "number", "description": "Student GPA."},
                "units_completed": {"type": "integer"},
                "standing": {
                    "type": "string",
                    "enum": ["good", "warning", "probation"],
                },
                "extension_count_this_term": {
                    "type": "integer",
                    "description": "Extensions already used this term (extension petitions only).",
                },
                "funding_category": {
                    "type": "string",
                    "enum": ["fellowship", "ra", "ta", "self", "unknown"],
                    "description": "Required for LOA petitions.",
                },
                "course_id": {
                    "type": "string",
                    "description": "Required for course_add / course_drop only. Omit for extensions.",
                },
                "reason_category": {
                    "type": "string",
                    "enum": ["medical", "personal", "academic", "other"],
                },
                "candidacy_status": {
                    "type": "object",
                    "description": "Required for LOA and graduation.",
                    "properties": {
                        "advanced": {"type": "boolean"},
                        "year_in_program": {"type": "integer"},
                    },
                },
                "graduation_data": {
                    "type": "object",
                    "description": "Required for graduation clearance.",
                    "properties": {
                        "required_units": {"type": "integer"},
                        "dissertation_filed": {"type": "boolean"},
                        "committee_approved": {"type": "boolean"},
                        "outstanding_incompletes": {"type": "integer"},
                    },
                },
            },
            "required": ["petition_type", "gpa", "units_completed", "standing", "reason_category"],
        },
    },
}

# ---------------------------------------------------------------------------
# MCP session: start the student_db server as a subprocess, discover tools
# ---------------------------------------------------------------------------

@asynccontextmanager
async def mcp_session():
    """
    Start student_db.py as a stdio MCP subprocess and yield a live ClientSession.
    Identical pattern to movie_night/client.py in the tutorial.
    """
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", MCP_SERVER_MODULE],
        cwd=MCP_SERVER_CWD,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def discover_tools(session: ClientSession) -> list[dict]:
    """
    Call list_tools() and convert to OpenAI function-tool format.
    The LLM sees real schemas generated from type annotations and docstrings
    by the MCP server — not hand-written JSON.
    """
    listed = (await session.list_tools()).tools
    openai_tools = []
    for t in listed:
        schema = t.input_schema or {"type": "object", "properties": {}}
        openai_tools.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": schema,
            },
        })
    return openai_tools


async def call_mcp_tool(session: ClientSession, name: str, args: dict) -> dict:
    """Call a tool on the live MCP server and return the result as a dict."""
    result = await session.call_tool(name, args)
    if result.is_error:
        return {"error": str(result.content)}
    if result.structured_content:
        return result.structured_content
    return json.loads(result.content[0].text)

# ---------------------------------------------------------------------------
# Sanitization (enforced in code, not just in the prompt)
# ---------------------------------------------------------------------------

def sanitize_for_policy(data: dict) -> dict:
    """Strip prohibited fields before sending to Policy Checker."""
    sanitized = {k: v for k, v in data.items() if k not in PROHIBITED_FIELDS}
    removed = PROHIBITED_FIELDS & set(data.keys())
    if removed:
        print(f"  [SANITIZE] Stripped prohibited fields: {removed}")
    return sanitized

# ---------------------------------------------------------------------------
# A2A call to Policy Checker (a2a-sdk v1.2.3)
# ---------------------------------------------------------------------------

async def call_policy_checker(payload: dict) -> dict:
    """Sanitize and forward a petition to the Policy Checker via A2A."""
    safe = sanitize_for_policy(payload)
    req = SendMessageRequest(
        message=new_text_message(json.dumps(safe), role=_pb.Role.ROLE_USER)
    )
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            client = await create_client(
                POLICY_CHECKER_URL,
                resolver_http_kwargs={"timeout": 10.0},
            )
            result_text = None
            async for event in client.send_message(req):
                which = event.WhichOneof("payload")
                # Non-streaming: full task in first 'task' event
                if which == "task":
                    for artifact in event.task.artifacts:
                        for part in artifact.parts:
                            if part.WhichOneof("content") == "text":
                                result_text = part.text
                                break
                        if result_text:
                            break
                # Streaming fallback
                elif which == "artifact_update":
                    for part in event.artifact_update.artifact.parts:
                        if part.WhichOneof("content") == "text":
                            result_text = part.text
                            break
                if result_text:
                    break
        if result_text:
            return json.loads(result_text)
        return {"decision": "denied", "rationale": "No artifact from Policy Checker.",
                "conditions": [], "triggered_rule": "POLICY-EMPTY"}
    except Exception as e:
        return {"decision": "denied", "rationale": f"A2A error: {e}",
                "conditions": [], "triggered_rule": "POLICY-COMM-ERROR"}

# ---------------------------------------------------------------------------
# Trace recorder
# ---------------------------------------------------------------------------

@dataclass
class AgentTrace:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    student_id: str = ""
    student_request: str = ""
    steps: list[dict] = field(default_factory=list)
    final_response: str = ""
    started_at: float = field(default_factory=time.time)

    def log(self, role: str, content: Any, step_type: str = "message") -> None:
        self.steps.append({
            "step": len(self.steps) + 1,
            "type": step_type,
            "role": role,
            "content": content,
            "t": round(time.time() - self.started_at, 3),
        })

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "student_id": self.student_id,
            "student_request": self.student_request,
            "agent": "AdvisorAgent",
            "mcp_server": MCP_SERVER_MODULE,
            "a2a_policy_checker": POLICY_CHECKER_URL,
            "started_at": self.started_at,
            "steps": self.steps,
            "final_response": self.final_response,
        }

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the Graduate Student Affairs Advisor Agent at a university.
You help graduate students with: course add/drop petitions, deadline extensions,
leave of absence (LOA) requests, and graduation clearance checks.

## Workflow — follow in order
1. Call get_student_record with the student's ID.
2. Call additional tools only when actually needed:
   - get_course_info(course_id) → course_add or course_drop only; skip if no course named
   - check_funding_status(student_id) → LOA petitions only
   - check_candidacy(student_id) → graduation clearance only
3. Call delegate_to_policy_checker ONCE with the gathered data.
4. Write a clear, empathetic final response based on the decision.

## Hard rules
- Call delegate_to_policy_checker EXACTLY ONCE per session.
- NEVER call the same tool with the same arguments more than twice.
- NEVER include visa_status, immigration_hold, financial_aid_amount,
  student_name, or student_email in the delegation payload.
- NEVER fabricate academic data — use only what tools return.
- For extension requests: do NOT call get_course_info (course is irrelevant to policy)."""

def _repair_json(s: str) -> str:
    s = s.strip()

    def _close_opens(t):
        valid_endings = {'"', '}', ']', 'e', 'l', 'n',
                         '0','1','2','3','4','5','6','7','8','9'}
        while t and t[-1] not in valid_endings:
            t = t[:-1]
        opens = []
        in_str = esc = False
        for ch in t:
            if esc: esc = False; continue
            if ch == '\\' and in_str: esc = True; continue
            if ch == '"': in_str = not in_str; continue
            if not in_str:
                if ch in ('{', '['): opens.append(ch)
                elif ch == '}' and opens and opens[-1] == '{': opens.pop()
                elif ch == ']' and opens and opens[-1] == '[': opens.pop()
        for ch in reversed(opens):
            t += '}' if ch == '{' else ']'
        return t

    def _last_top_level_comma(t):
        depth = 0
        in_str = esc = False
        last = -1
        for i, ch in enumerate(t):
            if esc: esc = False; continue
            if ch == '\\' and in_str: esc = True; continue
            if ch == '"': in_str = not in_str; continue
            if not in_str:
                if ch in ('{', '['): depth += 1
                elif ch in ('}', ']'): depth -= 1
                elif ch == ',' and depth == 1: last = i
        return last

    candidate = _close_opens(s)
    try:
        json.loads(candidate)
        return candidate
    except json.JSONDecodeError:
        pass

    last_comma = _last_top_level_comma(s)
    if last_comma > 0:
        candidate2 = s[:last_comma] + '}'
        try:
            json.loads(candidate2)
            return candidate2
        except json.JSONDecodeError:
            pass

    return candidate
# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------

async def run_advisor(
    student_id: str,
    student_request: str,
    verbose: bool = True,
) -> AgentTrace:
    """
    Run one Advisor Agent session end-to-end:
      - Starts student_db MCP server as a subprocess
      - Discovers tool schemas via list_tools()
      - Runs LLM agentic loop (tool calls go through real MCP)
      - Delegates policy evaluation via A2A
      - Returns complete trace
    """
    trace = AgentTrace(student_id=student_id, student_request=student_request)
    trace.log("student", student_request, "user_request")

    api_key = os.environ.get("SILICONFLOW_API_KEY")
    if not api_key:
        raise RuntimeError("SILICONFLOW_API_KEY is required to run the live Advisor Agent.")

    llm = OpenAI(api_key=api_key, base_url=SILICONFLOW_BASE_URL)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Student ID: {student_id}\n\nRequest: {student_request}"}
    ]

    if verbose:
        print(f"\n{'='*62}")
        print(f"Advisor Agent — session {trace.session_id}")
        print(f"Student {student_id}: {student_request}")
        print('='*62)

    async with mcp_session() as mcp:
        # Discover MCP tool schemas from the live subprocess
        mcp_tools = await discover_tools(mcp)
        mcp_tool_names = {t["function"]["name"] for t in mcp_tools}
        # FIX 1: combine MCP tools + delegation tool into one list for the LLM.
        # delegate_to_policy_checker is now a structured tool call, not a text trigger.
        all_tools = mcp_tools + [DELEGATE_TOOL]

        if verbose:
            print(f"[MCP] Connected to {MCP_SERVER_MODULE}")
            print(f"[MCP] Tools discovered: {sorted(mcp_tool_names)}")
            trace.log("mcp_connect", {
                "server": MCP_SERVER_MODULE,
                "transport": "MCP / stdio",
                "tools_discovered": sorted(mcp_tool_names),
                "delegate_tool": "delegate_to_policy_checker (OpenAI tool_use)",
            }, "mcp_connect")

        delegated = False
        # Issue 3 fix: track ALL calls (not just consecutive) to catch
        # alternating loops like A→B→A→B. Cap any single tool at 3 total calls.
        total_call_counts: dict[str, int] = {}
        # Also keep the consecutive-repeat guard for fast failure on stuck tools.
        last_call: tuple[str, str] | None = None
        repeat_count = 0

        for _turn in range(20):
            response = llm.chat.completions.create(
                model=SILICONFLOW_MODEL,
                max_tokens=2048,
                tools=all_tools,
                messages=messages,
            )

            assistant_message = response.choices[0].message
            assistant_text = assistant_message.content or ""
            tool_calls = assistant_message.tool_calls or []

            if assistant_text:
                trace.log("advisor", assistant_text, "thought")
                if verbose:
                    print(f"\n[Advisor think]\n{assistant_text}")

            # --- Handle tool calls ---
            if tool_calls:
                messages.append(assistant_message.model_dump(exclude_none=True))

                for tool_call in tool_calls:
                    tool_name = tool_call.function.name
                    raw_args = tool_call.function.arguments or "{}"
                    try:
                        tool_input = json.loads(raw_args)
                    except json.JSONDecodeError:
                        repaired = _repair_json(raw_args)
                        try:
                            tool_input = json.loads(repaired)
                            if verbose:
                                print(f"\n[JSON REPAIR] Fixed truncated args for {tool_name}")
                        except json.JSONDecodeError:
                            tool_input = {}
                            if verbose:
                                print(f"\n[JSON REPAIR] Could not fix args for {tool_name}, using {{}}")
                    if not isinstance(tool_input, dict):
                        tool_input = {}

                    # Issue 3 fix: track total calls per tool (catches alternating loops)
                    total_call_counts[tool_name] = total_call_counts.get(tool_name, 0) + 1
                    # Also track consecutive repeats for fast failure
                    call_key = (tool_name, json.dumps(tool_input, sort_keys=True))
                    if call_key == last_call:
                        repeat_count += 1
                    else:
                        last_call = call_key
                        repeat_count = 1

                    if repeat_count > 2 or total_call_counts[tool_name] > 3:
                        tool_result = {
                            "error": (
                                f"{tool_name} was already called with these exact arguments. "
                                "Do not repeat. Proceed with the data you already have."
                            )
                        }
                        if verbose:
                            print(f"\n[GUARD] Blocked repeated: {tool_name}({tool_input})")

                    # FIX 2: delegation is now handled as a tool call — result is
                    # injected as tool_result so the LLM writes its final response
                    # in the next turn naturally, without a separate user message.
                    elif tool_name == "delegate_to_policy_checker":
                        if delegated:
                            tool_result = {"error": "Already delegated once. Do not call again."}
                        else:
                            prohibited_removed = list(PROHIBITED_FIELDS & set(tool_input.keys()))
                            trace.log("advisor→policy_checker", {
                                "to": POLICY_CHECKER_URL,
                                "protocol": "A2A / JSONRPC",
                                "payload": sanitize_for_policy(tool_input),
                                "prohibited_fields_stripped": prohibited_removed,
                            }, "a2a_send")
                            if verbose:
                                print(f"\n[A2A → Policy Checker]\n{json.dumps(sanitize_for_policy(tool_input), indent=2)}")

                            tool_result = await call_policy_checker(tool_input)
                            delegated = True

                            trace.log("policy_checker→advisor", tool_result, "a2a_receive")
                            if verbose:
                                print(f"\n[A2A ← Policy Checker]\n{json.dumps(tool_result, indent=2)}")

                    elif tool_name in mcp_tool_names:
                        # Real MCP call over stdio subprocess
                        tool_result = await call_mcp_tool(mcp, tool_name, tool_input)
                        trace.log("advisor", {
                            "tool": tool_name, "input": tool_input, "via": "MCP / stdio"
                        }, "tool_call")
                        trace.log("tool_result", {
                            "tool": tool_name, "result": tool_result
                        }, "tool_result")
                        if verbose:
                            print(f"\n[MCP] {tool_name}({json.dumps(tool_input)}) → {json.dumps(tool_result)}")
                    else:
                        tool_result = {"error": f"Unknown tool: {tool_name}"}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(tool_result),
                    })
                continue  # back to next LLM turn

            # --- No tool calls this turn ---
            if response.choices[0].finish_reason in ("stop", "end"):
                # Issue 2 fix: if the LLM stopped WITHOUT having delegated,
                # it produced a premature plain-text answer. Force it to delegate.
                if not delegated and assistant_text:
                    messages.append({"role": "assistant", "content": assistant_text})
                    messages.append({
                        "role": "user",
                        "content": (
                            "You have not yet called delegate_to_policy_checker. "
                            "Please call it now with the student data you have gathered."
                        ),
                    })
                    if verbose:
                        print("\n[GUARD] Premature stop before delegation — nudging LLM to delegate.")
                    continue  # back into the loop to force delegation

                if assistant_text:
                    messages.append({"role": "assistant", "content": assistant_text})
                    trace.final_response = assistant_text
                    trace.log("advisor", assistant_text, "final_response")
                    if verbose:
                        print(f"\n[Final response to student]\n{assistant_text}")
                break

        # FIX 4: fallback — synthesise final_response if max_turns hit without one.
        # This ensures final_response is never left empty in the trace.
        if not trace.final_response:
            last_decision = next(
                (s["content"] for s in reversed(trace.steps) if s["type"] == "a2a_receive"),
                None,
            )
            if last_decision:
                trace.final_response = (
                    f"[Synthesised — max turns reached]\n"
                    f"Decision: {last_decision.get('decision')}. "
                    f"{last_decision.get('rationale')} "
                    f"Conditions: {last_decision.get('conditions', [])}"
                )
            else:
                trace.final_response = (
                    "[Max turns reached without a policy decision. "
                    "Please contact the graduate office directly.]"
                )
            trace.log("advisor", trace.final_response, "final_response_fallback")
            if verbose:
                print(f"\n[Fallback response]\n{trace.final_response}")

    return trace
