"""
Policy Checker Agent — A2A service (a2a-sdk v1.2.3).

Receives sanitized petition summaries from the Advisor Agent and returns
structured policy decisions. Deterministic rule engine — no LLM.
Not reachable by students directly.
"""
from __future__ import annotations
import argparse
import json
import uvicorn
from a2a.helpers import (
    get_message_text,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.types import (
    AgentCard, AgentCapabilities, AgentInterface, AgentSkill, TaskState,
)
from starlette.applications import Starlette

from src.tools.policy_rules import (
    evaluate_course_petition,
    evaluate_extension_request,
    evaluate_loa_request,
    check_graduation_requirements,
    PolicyDecision,
)

# ---------------------------------------------------------------------------
# Validation: reject payloads with prohibited fields
# ---------------------------------------------------------------------------

PROHIBITED_FIELDS = {
    "visa_status", "visa_category", "immigration_hold",
    "financial_aid_amount", "aid_package_details",
    "student_name", "student_email", "student_phone",
}


def _assert_sanitized(payload: dict) -> None:
    found = PROHIBITED_FIELDS & set(payload.keys())
    if found:
        raise ValueError(
            f"POLICY VIOLATION: prohibited fields present in payload: {found}"
        )


# ---------------------------------------------------------------------------
# Petition dispatcher
# ---------------------------------------------------------------------------

def dispatch_petition(payload: dict) -> PolicyDecision:
    _assert_sanitized(payload)
    petition_type = payload.get("petition_type")

    if petition_type in ("course_add", "course_drop"):
        return evaluate_course_petition(
            petition_type=petition_type,
            gpa=float(payload.get("gpa", 0.0)),
            units_completed=int(payload.get("units_completed", 0)),
            standing=payload.get("standing", "good"),
            course_id=payload.get("course_id", ""),
            reason_category=payload.get("reason_category", "other"),
        )
    elif petition_type == "extension":
        return evaluate_extension_request(
            extension_count_this_term=int(payload.get("extension_count_this_term", 0)),
            reason_category=payload.get("reason_category", "other"),
            standing=payload.get("standing", "good"),
        )
    elif petition_type == "loa":
        candidacy = payload.get("candidacy_status", {})
        return evaluate_loa_request(
            funding_category=payload.get("funding_category", "unknown"),
            standing=payload.get("standing", "good"),
            year_in_program=int(candidacy.get("year_in_program", payload.get("year_in_program", 1))),
            reason_category=payload.get("reason_category", "other"),
        )
    elif petition_type == "graduation":
        grad = payload.get("graduation_data", {})
        return check_graduation_requirements(
            advanced_to_candidacy=bool(payload.get("advanced_to_candidacy", False)),
            units_completed=int(payload.get("units_completed", 0)),
            required_units=int(grad.get("required_units", 72)),
            dissertation_filed=bool(grad.get("dissertation_filed", False)),
            committee_approved=bool(grad.get("committee_approved", False)),
            outstanding_incompletes=int(grad.get("outstanding_incompletes", 0)),
        )
    else:
        from src.tools.policy_rules import PolicyDecision as PD
        return PD(
            decision="denied",
            rationale=f"Unknown petition type: '{petition_type}'.",
            triggered_rule="POLICY-UNKNOWN",
        )


# ---------------------------------------------------------------------------
# A2A Executor (v1.2.3 API)
# ---------------------------------------------------------------------------

class PolicyCheckerExecutor(AgentExecutor):

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Create task and updater
        task = context.current_task or new_task_from_user_message(context.message)
        if context.current_task is None:
            await event_queue.enqueue_event(task)

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task.id,
            context_id=task.context_id,
        )

        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            message=new_text_message("Policy Checker: evaluating petition."),
        )

        try:
            raw = get_message_text(context.message)
            payload = json.loads(raw)
            decision = dispatch_petition(payload)
            result = {
                "decision": decision.decision,
                "rationale": decision.rationale,
                "conditions": decision.conditions,
                "triggered_rule": decision.triggered_rule,
            }
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            result = {
                "decision": "denied",
                "rationale": f"Policy Checker error: {exc}",
                "conditions": [],
                "triggered_rule": "POLICY-ERROR",
            }

        await updater.add_artifact(
            parts=[new_text_part(text=json.dumps(result), media_type="application/json")]
        )
        await updater.update_status(
            TaskState.TASK_STATE_COMPLETED,
            message=new_text_message("Policy evaluation complete."),
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation not supported.")


# ---------------------------------------------------------------------------
# A2A App factory
# ---------------------------------------------------------------------------

def make_app(port: int) -> Starlette:
    card = AgentCard(
        name="Graduate Affairs Policy Checker",
        description=(
            "Evaluates sanitized graduate petitions against institutional policy rules. "
            "Internal service — not student-facing."
        ),
        version="1.0.0",
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(
            protocol_binding="JSONRPC",
            url=f"http://127.0.0.1:{port}/",
            protocol_version="1.0",
        )],
        skills=[
            AgentSkill(id="evaluate-course-petition", name="Evaluate course add/drop petition",
                       description="Apply Academic Senate rules to a late add or drop.", tags=["petition"]),
            AgentSkill(id="evaluate-extension", name="Evaluate deadline extension request",
                       description="Apply term extension limit policy.", tags=["extension"]),
            AgentSkill(id="evaluate-loa", name="Evaluate leave of absence request",
                       description="Apply LOA eligibility rules.", tags=["loa"]),
            AgentSkill(id="check-graduation", name="Check graduation clearance",
                       description="Verify all requirements are met.", tags=["graduation"]),
        ],
    )
    handler = DefaultRequestHandler(
        agent_executor=PolicyCheckerExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    return Starlette(routes=(
        create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/")
    ))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Policy Checker A2A service")
    parser.add_argument("--port", type=int, default=9001)
    args = parser.parse_args()
    print(f"Starting Policy Checker A2A service on port {args.port}...")
    uvicorn.run(make_app(args.port), host="127.0.0.1", port=args.port, log_level="info")
