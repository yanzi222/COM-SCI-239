# Policies — Graduate Student Affairs Multi-Agent System

## Overview

This document specifies the permission, capability, lifecycle, information flow,
and information isolation boundaries for each agent in the system.

---

## 1. Agent Inventory

| Agent | ID | Type | Trust Level |
|---|---|---|---|
| Advisor Agent | `advisor` | Orchestrator / LLM | High (internal) |
| Policy Checker Agent | `policy_checker` | A2A service / deterministic | High (internal) |
| Student (user) | `student` | External principal | Untrusted |

---

## 2. Permission Policies

### 2.1 Advisor Agent Permissions

| Permission | Granted | Rationale |
|---|---|---|
| Read student academic record (GPA, units, standing) | ✅ Yes | Required to assess petitions |
| Read student extension history (count only) | ✅ Yes | Required for extension policy |
| Read candidacy status | ✅ Yes | Required for graduation clearance |
| Read funding status category (fellowship/RA/TA/self) | ✅ Yes | Required for LOA eligibility |
| Read visa or immigration hold details | ❌ No | Privacy — not needed for decisions |
| Read financial aid dollar amounts | ❌ No | Privacy — category only is sufficient |
| Read another student's record | ❌ No | Session isolation |
| Write or modify any student record | ❌ No | Read-only access |
| Send messages to Policy Checker | ✅ Yes | Core inter-agent communication |
| Receive messages from students | ✅ Yes | Student-facing interface |
| Override a Policy Checker denial | ❌ No | Policy Checker decisions are final for automatic cases |
| Call `evaluate_petition` directly (bypassing A2A) | ❌ No | All policy calls must go through the A2A boundary |

### 2.2 Policy Checker Agent Permissions

| Permission | Granted | Rationale |
|---|---|---|
| Receive sanitized petition summaries from Advisor | ✅ Yes | Core input |
| Call `evaluate_petition` rule engine | ✅ Yes | Core function |
| Call `check_graduation_requirements` | ✅ Yes | Core function |
| Initiate contact with students | ❌ No | Not student-facing |
| Access raw student records | ❌ No | Receives only sanitized summaries from Advisor |
| Access visa, immigration, or financial aid data | ❌ No | Explicitly excluded by Advisor's information filter |
| Modify its own rules | ❌ No | Rules are static (Phase 1) |
| Approve graduation clearance without candidacy confirmation | ❌ No | Hard gate |

### 2.3 Student Permissions

| Permission | Granted | Notes |
|---|---|---|
| Send requests to Advisor Agent | ✅ Yes | Natural language |
| Receive decisions and rationale | ✅ Yes | |
| Invoke Policy Checker directly | ❌ No | Invisible to student |
| Override a policy decision | ❌ No | Must go through official DGS channel |
| Request another student's data | ❌ No | Session isolation |

---

## 3. Capability Policies

### 3.1 Advisor Agent Capabilities

| Capability | Description |
|---|---|
| `understand_request` | Parse student's natural language request into a structured petition type and facts |
| `query_student_record` | Call `get_student_record` MCP tool with authenticated student ID |
| `query_course_info` | Call `get_course_info` MCP tool |
| `sanitize_for_policy` | Remove visa, immigration, and financial detail before forwarding to Policy Checker |
| `delegate_to_policy_checker` | Send an A2A task to the Policy Checker with a sanitized petition summary |
| `compose_response` | Combine the Policy Checker decision with context to write the student-facing reply |
| `escalate_to_dgs` | Flag a case for human Director of Graduate Studies review (produces a notice, not a decision) |

### 3.2 Policy Checker Agent Capabilities

| Capability | Description |
|---|---|
| `evaluate_course_petition` | Apply Academic Senate add/drop rules to a course petition |
| `evaluate_extension_request` | Apply term extension limit rules |
| `evaluate_loa_request` | Apply leave eligibility rules |
| `check_graduation_requirements` | Cross-check student completion against degree requirements |
| `return_decision` | Return structured `{decision, rationale, conditions}` via A2A |

---

## 4. Lifecycle and Ordering Policies

### 4.1 Request Lifecycle (all petition types)

```
1. Student submits request (natural language) → Advisor Agent
2. Advisor Agent identifies student (session-level authentication, Phase 1: student_id param)
3. Advisor Agent queries relevant MCP tools (student record, course info, etc.)
4. Advisor Agent sanitizes data (removes visa/financial detail)
5. Advisor Agent creates A2A task and sends to Policy Checker
6. Policy Checker evaluates and returns decision
7. Advisor Agent composes student-facing response
8. Session ends; no state persisted
```

### 4.2 Prerequisite Gates

| Step | Prerequisite |
|---|---|
| Query student record | Student ID must be provided in the request |
| Send to Policy Checker | Sanitization step must have completed |
| Approve graduation clearance | `check_candidacy` must return `advanced=True` |
| Grant automatic extension | Extension count for the term must be retrieved first |
| Process LOA | Funding status category must be retrieved first |

### 4.3 Ordering Invariant

The Advisor Agent **must not** send a message to the Policy Checker before completing
sanitization. Sanitization is enforced in `sanitize_for_policy()` which raises an error
if any prohibited fields (`visa_status`, `immigration_hold`, `aid_amount`) are present
in the payload.

---

## 5. Information Flow Policies

### 5.1 Allowed Information Flows

```
Student → Advisor:  free-form request text
Student record DB → Advisor:  GPA, units, standing, extension_count, candidacy_status, funding_category
Advisor → Policy Checker:  petition_type, gpa, units, standing, extension_count, course_id, reason_category
Policy Checker → Advisor:  decision ("approved"|"denied"|"conditional"|"needs_dgs_review"), rationale, conditions[]
Advisor → Student:  decision summary, rationale, next steps
```

### 5.2 Prohibited Information Flows

```
Student record DB → Policy Checker:  NEVER (must pass through Advisor's sanitization)
Advisor → Policy Checker:  visa_status, immigration_hold, aid_amount, student_name, student_email
Policy Checker → Student:  NEVER (Policy Checker is not student-facing)
Student A record → Student B session:  NEVER (session isolation)
```

### 5.3 Sanitization Specification

Before Advisor sends to Policy Checker, the following fields must be **removed**
and must **never appear** in the A2A message payload:

- `visa_status` / `visa_category` / `immigration_hold`
- `financial_aid_amount` / `aid_package_details`
- `student_name` / `student_email` / `student_phone`
- Full GPA transcript (only aggregate GPA float is passed)

The following fields are **allowed** in the sanitized payload:

- `petition_type`: one of `{course_add, course_drop, extension, loa, graduation}`
- `gpa`: float (aggregate, e.g. `3.7`)
- `units_completed`: int
- `standing`: one of `{good, warning, probation}`
- `extension_count_this_term`: int (0–N)
- `funding_category`: one of `{fellowship, ra, ta, self, unknown}`
- `course_id`: string (if applicable)
- `reason_category`: one of `{medical, personal, academic, other}`
- `candidacy_status`: `{advanced: bool, year_in_program: int}`

---

## 6. Information Isolation Boundaries

### 6.1 Session Isolation

Each invocation of the Advisor Agent is a **separate session**.
No student data from session S1 is accessible in session S2.
The system is stateless by design in Phase 1; the student record tools simulate
a read-only database query per call.

### 6.2 Agent Boundary

The Policy Checker Agent is deployed as a separate A2A service process.
It has no import of or reference to the Advisor Agent's state or student data store.
Its only input is the structured JSON payload sent over A2A.

### 6.3 Tool Isolation

MCP tools are scoped per agent:

| Tool | Accessible By |
|---|---|
| `get_student_record` | Advisor only |
| `get_course_info` | Advisor only |
| `check_candidacy` | Advisor only |
| `check_funding_status` | Advisor only |
| `evaluate_petition` | Policy Checker only |
| `check_graduation_requirements` | Policy Checker only |

---

## 7. Phase 1 Limitations (to be addressed in Phase 2)

| Limitation | Risk | Phase 2 Mitigation |
|---|---|---|
| Policy is enforced by Advisor Agent's prompt, not a hard barrier | LLM could be prompted to skip sanitization | Interpose a code-level sanitization check before every A2A send |
| Student identity is a passed parameter, not authenticated | Student could claim any ID | Add session token / authentication layer |
| Policy Checker rules are deterministic scripts | Edge cases not covered by rules fall back silently | Add coverage tests and a "no rule matched → escalate" path |
| No audit log | No forensic trail | Add immutable append-only log of all A2A messages |
