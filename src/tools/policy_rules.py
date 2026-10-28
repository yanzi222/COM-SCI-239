"""
Deterministic policy rule engine for the Graduate Student Affairs system.
These rules are intentionally hard-coded (no LLM) so the Policy Checker Agent
behaves predictably and is independently testable.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

DecisionType = Literal["approved", "denied", "conditional", "needs_dgs_review"]


@dataclass
class PolicyDecision:
    decision: DecisionType
    rationale: str
    conditions: list[str] = field(default_factory=list)
    triggered_rule: str = ""


# ---------------------------------------------------------------------------
# Rule 1: Course Petition (add / drop)
# ---------------------------------------------------------------------------

def evaluate_course_petition(
    petition_type: Literal["course_add", "course_drop"],
    gpa: float,
    units_completed: int,
    standing: str,
    course_id: str,
    reason_category: str,
) -> PolicyDecision:
    """
    Academic Senate add/drop policy (simplified):
    - Students on probation may not add courses after week 2 without DGS review.
    - Drop: allowed through week 10 with a W grade; after week 10 requires DGS.
    - Add: allowed with medical/academic reason and good/warning standing.
    - Students with < 8 units completed are in their first term and get more latitude.
    """
    if standing == "probation" and petition_type == "course_add":
        return PolicyDecision(
            decision="needs_dgs_review",
            rationale="Students on academic probation may not add courses without Director of Graduate Studies approval.",
            triggered_rule="POLICY-PETITION-001",
        )

    if petition_type == "course_drop":
        if reason_category in ("medical", "personal"):
            return PolicyDecision(
                decision="approved",
                rationale="Late drop approved: medical or personal reason with acceptable standing.",
                conditions=["A W grade will appear on the transcript."],
                triggered_rule="POLICY-PETITION-002",
            )
        return PolicyDecision(
            decision="conditional",
            rationale="Late drop requires instructor acknowledgment for non-medical/personal reasons.",
            conditions=["Provide instructor email confirmation.", "W grade will appear."],
            triggered_rule="POLICY-PETITION-003",
        )

    if petition_type == "course_add":
        if reason_category == "medical":
            return PolicyDecision(
                decision="approved",
                rationale="Late add approved on medical grounds.",
                conditions=["Attend all remaining sessions.", "Instructor must be notified."],
                triggered_rule="POLICY-PETITION-004",
            )
        if gpa >= 3.5 and standing == "good":
            return PolicyDecision(
                decision="approved",
                rationale="Late add approved: strong academic standing and satisfactory reason.",
                triggered_rule="POLICY-PETITION-005",
            )
        return PolicyDecision(
            decision="conditional",
            rationale="Late add requires instructor and advisor co-signature given current standing.",
            conditions=["Instructor must sign the petition.", "Advisor must countersign."],
            triggered_rule="POLICY-PETITION-006",
        )

    return PolicyDecision(
        decision="denied",
        rationale="Unrecognized petition type.",
        triggered_rule="POLICY-PETITION-000",
    )


# ---------------------------------------------------------------------------
# Rule 2: Deadline Extension
# ---------------------------------------------------------------------------

def evaluate_extension_request(
    extension_count_this_term: int,
    reason_category: str,
    standing: str,
) -> PolicyDecision:
    """
    Extension policy:
    - First extension per term: auto-approved for any reason.
    - Second extension per term: approved only for medical/personal.
    - Third+ extension per term: always requires DGS review.
    - Students on probation: all extensions require DGS review.
    """
    if standing == "probation":
        return PolicyDecision(
            decision="needs_dgs_review",
            rationale="Students on academic probation must obtain DGS approval for all extensions.",
            triggered_rule="POLICY-EXT-001",
        )

    if extension_count_this_term == 0:
        return PolicyDecision(
            decision="approved",
            rationale="First extension of the term — automatically approved per department policy.",
            triggered_rule="POLICY-EXT-002",
        )

    if extension_count_this_term == 1 and reason_category in ("medical", "personal"):
        return PolicyDecision(
            decision="approved",
            rationale="Second extension approved: medical or personal hardship documented.",
            conditions=["Supporting documentation must be submitted to the graduate office within 5 business days."],
            triggered_rule="POLICY-EXT-003",
        )

    if extension_count_this_term >= 1:
        return PolicyDecision(
            decision="needs_dgs_review",
            rationale=(
                f"Student has already used {extension_count_this_term} extension(s) this term. "
                "Further extensions require Director of Graduate Studies approval."
            ),
            triggered_rule="POLICY-EXT-004",
        )

    return PolicyDecision(
        decision="denied",
        rationale="Extension request does not meet any approved criteria.",
        triggered_rule="POLICY-EXT-000",
    )


# ---------------------------------------------------------------------------
# Rule 3: Leave of Absence
# ---------------------------------------------------------------------------

def evaluate_loa_request(
    funding_category: str,
    standing: str,
    year_in_program: int,
    reason_category: str,
) -> PolicyDecision:
    """
    LOA policy:
    - Funded students (fellowship/RA/TA) may only take leave if funding is formally suspended.
    - Medical leave: always conditionally approved pending documentation.
    - Personal leave: approved for years 1–5; year 6+ requires DGS review.
    - Students on probation: LOA does not reset probationary status.
    """
    if reason_category == "medical":
        conditions = ["Submit medical documentation to the graduate advisor within 10 days."]
        if funding_category in ("fellowship", "ra", "ta"):
            conditions.append("Coordinate with the graduate office to suspend funding for the leave period.")
        return PolicyDecision(
            decision="conditional",
            rationale="Medical leave of absence conditionally approved.",
            conditions=conditions,
            triggered_rule="POLICY-LOA-001",
        )

    if year_in_program > 5:
        return PolicyDecision(
            decision="needs_dgs_review",
            rationale="Leave of absence in year 6 or later requires DGS review due to time-to-degree concerns.",
            triggered_rule="POLICY-LOA-002",
        )

    if funding_category in ("fellowship", "ra", "ta") and reason_category != "medical":
        return PolicyDecision(
            decision="conditional",
            rationale="Funded students must arrange a funding suspension before LOA can be approved.",
            conditions=[
                "Contact the graduate office to initiate funding suspension.",
                "LOA will be approved once funding hold is confirmed.",
            ],
            triggered_rule="POLICY-LOA-003",
        )

    return PolicyDecision(
        decision="approved",
        rationale="Leave of absence approved. Re-enrollment requires a Return from Leave petition.",
        conditions=["Submit a Return from Leave petition at least 4 weeks before the intended return term."],
        triggered_rule="POLICY-LOA-004",
    )


# ---------------------------------------------------------------------------
# Rule 4: Graduation Clearance
# ---------------------------------------------------------------------------

def check_graduation_requirements(
    advanced_to_candidacy: bool,
    units_completed: int,
    required_units: int,
    dissertation_filed: bool,
    committee_approved: bool,
    outstanding_incompletes: int,
) -> PolicyDecision:
    """
    Graduation clearance policy:
    - Must be advanced to candidacy.
    - Must have completed required units.
    - Dissertation must be filed.
    - Committee approval required.
    - No outstanding Incomplete grades.
    """
    missing = []

    if not advanced_to_candidacy:
        missing.append("Student has not been advanced to candidacy (qualifying exam required).")
    if units_completed < required_units:
        missing.append(f"Missing {required_units - units_completed} units ({units_completed}/{required_units} completed).")
    if not dissertation_filed:
        missing.append("Dissertation has not been filed with the graduate division.")
    if not committee_approved:
        missing.append("Dissertation committee approval is pending.")
    if outstanding_incompletes > 0:
        missing.append(f"{outstanding_incompletes} outstanding Incomplete grade(s) must be resolved.")

    if missing:
        return PolicyDecision(
            decision="denied",
            rationale="Graduation clearance denied: requirements not met.",
            conditions=missing,
            triggered_rule="POLICY-GRAD-001",
        )

    return PolicyDecision(
        decision="approved",
        rationale="All graduation requirements met. Clearance granted.",
        triggered_rule="POLICY-GRAD-002",
    )
