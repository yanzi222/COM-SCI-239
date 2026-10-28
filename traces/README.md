# Traces — Graduate Student Affairs Multi-Agent System

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
