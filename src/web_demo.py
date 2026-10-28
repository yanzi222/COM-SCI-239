"""
web_demo.py — Phase 1/2 Web Demo for CS239 Graduate Student Affairs System.

A FastAPI + Server-Sent Events web UI that makes the two-agent interaction
visible in real time:

  Browser → FastAPI → Advisor Agent (LLM + MCP)
                           └─ A2A ──► Policy Checker Agent

Run:
    # Terminal 1: start Policy Checker A2A service
    python -m src.agents.policy_agent --port 9001

    # Terminal 2: start web demo
    python -m src.web_demo

    Open http://127.0.0.1:8000 in a browser.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, StreamingResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

# Make sure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# HTML — single-file UI (no external build step)
# ---------------------------------------------------------------------------

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CS239 Graduate Advisor — Multi-Agent Demo</title>
<style>
:root {
  --bg: #0f1117; --surface: #1a1d27; --border: #2a2d3a;
  --blue: #4f8ef7; --green: #3ecf8e; --yellow: #f5a623;
  --red: #e05c5c; --purple: #a78bfa; --gray: #8892a4;
  --text: #e2e8f0; --text-dim: #64748b;
  --mcp-color: #3ecf8e; --a2a-color: #4f8ef7; --policy-color: #a78bfa;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: 'Inter', system-ui, sans-serif;
  display: flex; flex-direction: column; height: 100vh; overflow: hidden; }

/* ── Header ── */
header { background: var(--surface); border-bottom: 1px solid var(--border);
  padding: 12px 24px; display: flex; align-items: center; gap: 16px; flex-shrink: 0; }
header h1 { font-size: 15px; font-weight: 600; }
header p  { font-size: 12px; color: var(--gray); }
.badge { padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge-mcp    { background: rgba(62,207,142,.15); color: var(--mcp-color); }
.badge-a2a    { background: rgba(79,142,247,.15);  color: var(--a2a-color); }
.badge-policy { background: rgba(167,139,250,.15); color: var(--policy-color); }

/* ── Main layout ── */
main { display: flex; flex: 1; overflow: hidden; }

/* ── Left panel: architecture diagram + scenario picker ── */
.left { width: 280px; border-right: 1px solid var(--border); display: flex;
  flex-direction: column; overflow-y: auto; flex-shrink: 0; background: var(--surface); }
.panel-title { font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .08em; color: var(--gray); padding: 16px 16px 8px; }

/* Architecture diagram */
.arch { padding: 0 16px 16px; }
.arch-box { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px;
  margin-bottom: 8px; font-size: 12px; position: relative; }
.arch-box.student  { border-color: var(--yellow); }
.arch-box.advisor  { border-color: var(--blue); }
.arch-box.mcp-srv  { border-color: var(--mcp-color); }
.arch-box.policy   { border-color: var(--policy-color); }
.arch-label { font-weight: 600; margin-bottom: 2px; }
.arch-sub   { color: var(--gray); font-size: 11px; }
.arch-arrow { text-align: center; font-size: 11px; color: var(--gray); margin: 2px 0; }
.arch-proto { font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 3px; }
.proto-mcp  { background: rgba(62,207,142,.2); color: var(--mcp-color); }
.proto-a2a  { background: rgba(79,142,247,.2);  color: var(--a2a-color); }

/* Scenario buttons */
.scenarios { padding: 0 16px 16px; display: flex; flex-direction: column; gap: 8px; }
.scenario-btn { background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 12px; text-align: left; cursor: pointer; transition: all .15s;
  color: var(--text); font-size: 12px; }
.scenario-btn:hover  { border-color: var(--blue); background: rgba(79,142,247,.08); }
.scenario-btn.active { border-color: var(--blue); background: rgba(79,142,247,.12); }
.scenario-btn .s-title { font-weight: 600; margin-bottom: 3px; }
.scenario-btn .s-student { color: var(--gray); font-size: 11px; }
.scenario-btn .s-badge { margin-top: 4px; display: inline-block; }

/* Custom request */
.custom-area { padding: 0 16px 16px; }
.custom-area textarea { width: 100%; background: var(--bg); border: 1px solid var(--border);
  border-radius: 6px; color: var(--text); font-size: 12px; padding: 8px;
  resize: vertical; min-height: 80px; font-family: inherit; }
.custom-area input { width: 100%; background: var(--bg); border: 1px solid var(--border);
  border-radius: 6px; color: var(--text); font-size: 12px; padding: 7px 8px;
  font-family: inherit; margin-bottom: 6px; }
.run-btn { width: 100%; padding: 9px; background: var(--blue); color: #fff;
  border: none; border-radius: 6px; font-weight: 600; font-size: 13px;
  cursor: pointer; transition: opacity .15s; }
.run-btn:disabled { opacity: .5; cursor: default; }

/* ── Right panel: trace viewer ── */
.right { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

/* Step timeline */
.trace-area { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 8px; }
.step-card { border-radius: 8px; padding: 10px 14px; border: 1px solid transparent;
  font-size: 13px; animation: fadeIn .2s ease; }
@keyframes fadeIn { from { opacity:0; transform:translateY(4px); } to { opacity:1; transform:translateY(0); } }

.step-card.user_request  { border-color: var(--yellow); background: rgba(245,166,35,.07); }
.step-card.mcp_connect   { border-color: var(--mcp-color); background: rgba(62,207,142,.06); }
.step-card.tool_call     { border-color: var(--mcp-color); background: rgba(62,207,142,.05); }
.step-card.tool_result   { border-color: #2a3a30; background: rgba(62,207,142,.03); }
.step-card.thought       { border-color: var(--border); background: rgba(255,255,255,.02); }
.step-card.a2a_send      { border-color: var(--a2a-color); background: rgba(79,142,247,.08); }
.step-card.a2a_receive   { border-color: var(--policy-color); background: rgba(167,139,250,.08); }
.step-card.final_response { border-color: var(--green); background: rgba(62,207,142,.08); }
.step-card.final_response_fallback { border-color: var(--yellow); background: rgba(245,166,35,.06); }
.step-card.error         { border-color: var(--red); background: rgba(224,92,92,.07); }

.step-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.step-num  { font-size: 10px; color: var(--gray); min-width: 24px; }
.step-icon { font-size: 14px; }
.step-role { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing:.05em; }
.step-time { font-size: 10px; color: var(--gray); margin-left: auto; }
.step-body { font-size: 12px; color: var(--text); line-height: 1.6; }
.step-body pre { background: rgba(0,0,0,.3); border-radius: 4px; padding: 8px;
  overflow-x: auto; font-size: 11px; margin-top: 6px; white-space: pre-wrap; }
.step-body .tag { display: inline-block; padding: 1px 6px; border-radius: 3px;
  font-size: 10px; font-weight: 700; margin-right: 4px; }
.tag-approved { background: rgba(62,207,142,.2); color: var(--green); }
.tag-denied   { background: rgba(224,92,92,.2);  color: var(--red); }
.tag-conditional { background: rgba(245,166,35,.2); color: var(--yellow); }
.tag-dgs      { background: rgba(167,139,250,.2); color: var(--purple); }

/* Final answer box */
.answer-box { border-top: 1px solid var(--border); padding: 16px; flex-shrink: 0;
  background: var(--surface); min-height: 80px; }
.answer-box h3 { font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing:.08em; color: var(--gray); margin-bottom: 8px; }
.answer-box p { font-size: 13px; line-height: 1.7; color: var(--text); }
.spinner { display: inline-block; width: 12px; height: 12px; border: 2px solid var(--border);
  border-top-color: var(--blue); border-radius: 50%; animation: spin .7s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>

<header>
  <div>
    <h1>🎓 Graduate Student Affairs — Multi-Agent System</h1>
    <p>CS239 Phase 1 Demo &nbsp;·&nbsp; Two communicating agents with distinct roles</p>
  </div>
  <span class="badge badge-mcp">MCP / stdio</span>
  <span class="badge badge-a2a">A2A / JSONRPC</span>
  <span class="badge badge-policy">Policy Engine</span>
</header>

<main>
<!-- Left panel -->
<div class="left">
  <div class="panel-title">System Architecture</div>
  <div class="arch">
    <div class="arch-box student">
      <div class="arch-label">🧑‍🎓 Student (you)</div>
      <div class="arch-sub">Natural language request</div>
    </div>
    <div class="arch-arrow">↕ HTTP/SSE</div>
    <div class="arch-box advisor">
      <div class="arch-label">🤖 Advisor Agent</div>
      <div class="arch-sub">LLM · Qwen3 via SiliconFlow</div>
    </div>
    <div class="arch-arrow">↕ <span class="arch-proto proto-mcp">MCP/stdio</span></div>
    <div class="arch-box mcp-srv">
      <div class="arch-label">🗄️ student_db</div>
      <div class="arch-sub">MCP subprocess · 4 tools</div>
    </div>
    <div class="arch-arrow">↕ <span class="arch-proto proto-a2a">A2A/JSONRPC</span></div>
    <div class="arch-box policy">
      <div class="arch-label">⚖️ Policy Checker</div>
      <div class="arch-sub">Deterministic rules · port 9001</div>
    </div>
  </div>

  <div class="panel-title">Scenarios</div>
  <div class="scenarios" id="scenarios">
    <button class="scenario-btn" data-idx="0" onclick="runScenario(0)">
      <div class="s-title">📚 Late Course Add</div>
      <div class="s-student">S001 · GPA 3.8 · Medical reason</div>
      <span class="badge badge-mcp s-badge">POLICY-PETITION-004</span>
    </button>
    <button class="scenario-btn" data-idx="1" onclick="runScenario(1)">
      <div class="s-title">⏰ Deadline Extension</div>
      <div class="s-student">S003 · Probation · 3rd extension</div>
      <span class="badge badge-policy s-badge">POLICY-EXT-001</span>
    </button>
    <button class="scenario-btn" data-idx="2" onclick="runScenario(2)">
      <div class="s-title">✈️ Leave of Absence</div>
      <div class="s-student">S002 · RA-funded · Visa stripped</div>
      <span class="badge badge-a2a s-badge">POLICY-LOA-003</span>
    </button>
  </div>

  <div class="panel-title">Custom Request</div>
  <div class="custom-area">
    <input id="custom-sid" placeholder="Student ID (e.g. S001)" value="S001">
    <textarea id="custom-req" placeholder="Type a request…">I need to add CS229 late due to a medical issue.</textarea>
    <button class="run-btn" id="run-btn" onclick="runCustom()">▶ Run Agent</button>
  </div>
</div>

<!-- Right panel -->
<div class="right">
  <div class="trace-area" id="trace"></div>
  <div class="answer-box">
    <h3>Final Response to Student</h3>
    <p id="final-answer" style="color:var(--gray)">Run a scenario to see the agent's response.</p>
  </div>
</div>
</main>

<script>
const SCENARIOS = [
  { student_id: 'S001',
    request: 'Hi, I need to add CS229 (Machine Learning) late. I missed the enrollment deadline because I was hospitalized for a week. My student ID is S001.' },
  { student_id: 'S003',
    request: "I need another deadline extension for my assignment. I've been struggling this term. My student ID is S003." },
  { student_id: 'S002',
    request: 'I need to take a leave of absence next quarter for personal reasons. My student ID is S002.' },
];

const ICONS = {
  user_request: '🧑‍🎓', mcp_connect: '🔌', tool_call: '🔧', tool_result: '📦',
  thought: '💭', a2a_send: '📤', a2a_receive: '📥',
  final_response: '✅', final_response_fallback: '⚠️', error: '❌',
};
const ROLE_LABELS = {
  student: 'Student', advisor: 'Advisor Agent', mcp_connect: 'MCP Connect',
  tool_result: 'MCP Result', 'advisor→policy_checker': 'A2A → Policy Checker',
  'policy_checker→advisor': 'A2A ← Policy Checker',
};

let running = false;

function setRunning(v) {
  running = v;
  document.getElementById('run-btn').disabled = v;
  document.querySelectorAll('.scenario-btn').forEach(b => b.disabled = v);
}

function clearTrace() {
  document.getElementById('trace').innerHTML = '';
  document.getElementById('final-answer').textContent = 'Running…';
  document.getElementById('final-answer').style.color = 'var(--gray)';
}

function decisionTag(decision) {
  const map = { approved:'tag-approved', denied:'tag-denied',
    conditional:'tag-conditional', needs_dgs_review:'tag-dgs' };
  const label = { approved:'APPROVED', denied:'DENIED',
    conditional:'CONDITIONAL', needs_dgs_review:'NEEDS DGS REVIEW' };
  const cls = map[decision] || 'tag-dgs';
  return `<span class="tag ${cls}">${label[decision] || decision.toUpperCase()}</span>`;
}

function renderContent(type, content) {
  if (typeof content === 'string') return `<div>${content}</div>`;
  if (type === 'mcp_connect') {
    return `<div>Connected to <strong>${content.server}</strong> · Transport: <strong>${content.transport || 'MCP/stdio'}</strong></div>
      <div style="margin-top:4px;color:var(--gray)">Tools discovered: ${(content.tools_discovered||[]).join(', ')}</div>
      ${content.delegate_tool ? `<div style="margin-top:2px;color:var(--gray)">+ ${content.delegate_tool}</div>` : ''}`;
  }
  if (type === 'tool_call') {
    return `<div><strong>${content.tool}</strong>(${JSON.stringify(content.input)}) <em style="color:var(--gray);font-size:11px">via ${content.via||'MCP/stdio'}</em></div>`;
  }
  if (type === 'tool_result') {
    const val = content.result || content;
    return `<div><strong>${content.tool}</strong></div><pre>${JSON.stringify(val, null, 2)}</pre>`;
  }
  if (type === 'a2a_send') {
    const stripped = content.prohibited_fields_stripped || [];
    return `<div>→ <strong>${content.to || content.protocol}</strong></div>
      ${stripped.length ? `<div style="color:var(--yellow);margin-top:3px">🔒 Stripped: ${stripped.join(', ')}</div>` : ''}
      <pre>${JSON.stringify(content.payload, null, 2)}</pre>`;
  }
  if (type === 'a2a_receive') {
    const d = content;
    return `<div>${decisionTag(d.decision)} <strong>${d.triggered_rule || ''}</strong></div>
      <div style="margin-top:4px">${d.rationale || ''}</div>
      ${(d.conditions||[]).length ? `<ul style="margin-top:4px;padding-left:16px">${d.conditions.map(c=>`<li style="font-size:11px;color:var(--gray)">${c}</li>`).join('')}</ul>` : ''}`;
  }
  return `<pre>${JSON.stringify(content, null, 2)}</pre>`;
}

function addStep(step) {
  const area = document.getElementById('trace');
  const card = document.createElement('div');
  card.className = `step-card ${step.type}`;
  const icon = ICONS[step.type] || '•';
  const roleLabel = ROLE_LABELS[step.role] || step.role;
  const t = step.t != null ? `${step.t.toFixed(1)}s` : '';
  card.innerHTML = `
    <div class="step-header">
      <span class="step-num">#${step.step}</span>
      <span class="step-icon">${icon}</span>
      <span class="step-role">${roleLabel}</span>
      <span class="step-time">${t}</span>
    </div>
    <div class="step-body">${renderContent(step.type, step.content)}</div>`;
  area.appendChild(card);
  area.scrollTop = area.scrollHeight;
}

function addStatus(msg) {
  const area = document.getElementById('trace');
  const el = document.createElement('div');
  el.id = 'status-spinner';
  el.style.cssText = 'display:flex;align-items:center;gap:8px;color:var(--gray);font-size:12px;padding:4px 0';
  el.innerHTML = `<span class="spinner"></span> ${msg}`;
  area.appendChild(el);
  area.scrollTop = area.scrollHeight;
}

function removeStatus() {
  const el = document.getElementById('status-spinner');
  if (el) el.remove();
}

async function runRequest(student_id, request) {
  if (running) return;
  setRunning(true);
  clearTrace();

  const res = await fetch('/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ student_id, request }),
  });

  if (!res.ok || !res.body) {
    document.getElementById('final-answer').textContent = 'Server error — is the demo running?';
    setRunning(false);
    return;
  }

  addStatus('Starting MCP subprocess…');
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop();
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const raw = line.slice(6).trim();
      if (!raw) continue;
      try {
        const msg = JSON.parse(raw);
        removeStatus();
        if (msg.type === 'step') {
          addStep(msg.step);
          if (msg.step.type === 'a2a_send') addStatus('Waiting for Policy Checker…');
          else if (msg.step.type === 'tool_call') addStatus(`Calling ${msg.step.content.tool}…`);
        } else if (msg.type === 'done') {
          const fa = document.getElementById('final-answer');
          fa.textContent = msg.final_response || '(no response)';
          fa.style.color = 'var(--text)';
        } else if (msg.type === 'error') {
          document.getElementById('final-answer').textContent = '⚠ ' + msg.message;
        }
      } catch {}
    }
  }

  removeStatus();
  setRunning(false);
}

function runScenario(idx) {
  document.querySelectorAll('.scenario-btn').forEach((b,i) =>
    b.classList.toggle('active', i === idx));
  const s = SCENARIOS[idx];
  runRequest(s.student_id, s.request);
}

function runCustom() {
  const sid = document.getElementById('custom-sid').value.trim() || 'S001';
  const req = document.getElementById('custom-req').value.trim();
  if (!req) return;
  document.querySelectorAll('.scenario-btn').forEach(b => b.classList.remove('active'));
  runRequest(sid, req);
}
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# SSE streaming endpoint
# ---------------------------------------------------------------------------

async def sse_run(student_id: str, request: str) -> AsyncIterator[str]:
    """Run the advisor agent and stream each trace step as an SSE event."""

    def emit(obj: dict) -> str:
        return f"data: {json.dumps(obj)}\n\n"

    # Import here to pick up any env patches before the session starts
    from src.agents.advisor_agent import (
        mcp_session, discover_tools, call_mcp_tool,
        call_policy_checker, sanitize_for_policy,
        PROHIBITED_FIELDS, DELEGATE_TOOL, SILICONFLOW_MODEL,
        POLICY_CHECKER_URL, MCP_SERVER_MODULE,
    )
    from openai import OpenAI

    api_key = os.environ.get("SILICONFLOW_API_KEY")
    if not api_key:
        yield emit({"type": "error", "message": "SILICONFLOW_API_KEY not set."})
        return

    llm = OpenAI(api_key=api_key, base_url=os.environ.get(
        "SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"))

    from src.agents.advisor_agent import SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Student ID: {student_id}\n\nRequest: {request}"},
    ]

    step_num = [0]
    t0 = time.time()

    def make_step(type_, role, content):
        step_num[0] += 1
        return {
            "step": step_num[0], "type": type_, "role": role,
            "content": content, "t": round(time.time() - t0, 2),
        }

    def send_step(type_, role, content):
        return emit({"type": "step", "step": make_step(type_, role, content)})

    yield send_step("user_request", "student", request)

    try:
        async with mcp_session() as mcp:
            mcp_tools = await discover_tools(mcp)
            mcp_tool_names = {t["function"]["name"] for t in mcp_tools}
            all_tools = mcp_tools + [DELEGATE_TOOL]

            yield send_step("mcp_connect", "mcp_connect", {
                "server": MCP_SERVER_MODULE,
                "transport": "MCP / stdio",
                "tools_discovered": sorted(mcp_tool_names),
                "delegate_tool": "delegate_to_policy_checker (OpenAI tool_use)",
            })

            delegated = False
            total_call_counts: dict = {}
            last_call = None
            repeat_count = 0
            final_response = ""

            for _turn in range(20):
                response = llm.chat.completions.create(
                    model=SILICONFLOW_MODEL,
                    max_tokens=2048,
                    tools=all_tools,
                    messages=messages,
                )
                msg = response.choices[0].message
                text = msg.content or ""
                tool_calls = msg.tool_calls or []

                if text and not tool_calls:
                    yield send_step("thought", "advisor", text)

                if tool_calls:
                    messages.append(msg.model_dump(exclude_none=True))
                    for tc in tool_calls:
                        name = tc.function.name
                        from src.agents.advisor_agent import _repair_json
                        raw_args = tc.function.arguments or "{}"
                        try:
                            inp = json.loads(raw_args)
                        except json.JSONDecodeError:
                            try:
                                inp = json.loads(_repair_json(raw_args))
                            except json.JSONDecodeError:
                                inp = {}

                        total_call_counts[name] = total_call_counts.get(name, 0) + 1
                        ck = (name, json.dumps(inp, sort_keys=True))
                        repeat_count = repeat_count + 1 if ck == last_call else 1
                        last_call = ck

                        if repeat_count > 2 or total_call_counts[name] > 3:
                            result = {"error": f"{name} called too many times. Proceed with existing data."}
                        elif name == "delegate_to_policy_checker":
                            if delegated:
                                result = {"error": "Already delegated. Do not call again."}
                            else:
                                stripped = list(PROHIBITED_FIELDS & set(inp.keys()))
                                yield send_step("a2a_send", "advisor→policy_checker", {
                                    "to": POLICY_CHECKER_URL,
                                    "protocol": "A2A / JSONRPC",
                                    "payload": sanitize_for_policy(inp),
                                    "prohibited_fields_stripped": stripped,
                                })
                                result = await call_policy_checker(inp)
                                delegated = True
                                yield send_step("a2a_receive", "policy_checker→advisor", result)
                        elif name in mcp_tool_names:
                            yield send_step("tool_call", "advisor", {
                                "tool": name, "input": inp, "via": "MCP / stdio"})
                            result = await call_mcp_tool(mcp, name, inp)
                            yield send_step("tool_result", "tool_result", {
                                "tool": name, "result": result})
                        else:
                            result = {"error": f"Unknown tool: {name}"}

                        messages.append({"role": "tool", "tool_call_id": tc.id,
                                         "content": json.dumps(result)})
                    continue

                if response.choices[0].finish_reason in ("stop", "end"):
                    if not delegated and text:
                        messages.append({"role": "assistant", "content": text})
                        messages.append({"role": "user", "content":
                            "You have not yet called delegate_to_policy_checker. Please call it now."})
                        continue
                    if text:
                        messages.append({"role": "assistant", "content": text})
                        final_response = text
                        yield send_step("final_response", "advisor", text)
                    break

            if not final_response:
                last_dec = next((s["content"] for s in
                    [make_step("x","x",None)]  # dummy
                    if False), None)
                # Synthesise from steps already yielded — find last a2a_receive
                final_response = "[Max turns reached. Please contact the graduate office.]"
                yield send_step("final_response_fallback", "advisor", final_response)

            yield emit({"type": "done", "final_response": final_response})

    except Exception as exc:
        yield emit({"type": "error", "message": str(exc)})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

async def homepage(request: Request) -> HTMLResponse:
    return HTMLResponse(HTML)


async def run_endpoint(request: Request) -> StreamingResponse:
    body = await request.json()
    student_id = body.get("student_id", "S001")
    req_text = body.get("request", "")

    async def event_stream():
        async for chunk in sse_run(student_id, req_text):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app = Starlette(routes=[
    Route("/", homepage),
    Route("/run", run_endpoint, methods=["POST"]),
])


if __name__ == "__main__":
    port = int(os.environ.get("WEB_PORT", "8000"))
    print(f"\n{'='*55}")
    print("CS239 Graduate Advisor — Web Demo")
    print(f"{'='*55}")
    print(f"Open: http://127.0.0.1:{port}")
    print(f"Requires: SILICONFLOW_API_KEY, Policy Checker on :9001")
    print(f"Start Policy Checker first:")
    print(f"  python -m src.agents.policy_agent --port 9001")
    print(f"{'='*55}\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
