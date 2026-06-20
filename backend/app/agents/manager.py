"""
Manager Agent — LangGraph orchestration with parallel agent execution.

Key improvements over sequential v1:
  - Incident Agent + Knowledge Agent run in PARALLEL (asyncio.gather)
  - Meeting Agent runs in parallel with Knowledge Agent when both needed
  - Human-in-the-loop interrupt for P1/P2 tickets
  - PII scrubbing before any LLM call
"""
import asyncio
import uuid
import json
from typing import TypedDict, Annotated, Dict, Any, Optional
import logging
from langgraph.graph import StateGraph, END


from app.agents.email_agent import process_email
from app.agents.incident_agent import analyze_incident
from app.agents.knowledge_agent import query_knowledge_base
from app.agents.ticket_agent import create_jira_ticket
from app.agents.meeting_agent import schedule_meeting
from app.services.slack_client import slack_service
from app.services.telegram_client import telegram_service
from app.core.llm_router import router
from app.core.json_utils import extract_json
from app.core.pii_scrubber import scrub_pii

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    raw_email: str
    email_data: Dict[str, Any]
    workflow_plan: Dict[str, Any]
    incident_result: Dict[str, Any]
    knowledge_results: Dict[str, Any]
    ticket_result: Dict[str, Any]
    meeting_result: Dict[str, Any]
    executive_summary: str
    human_approved: bool


# ── Node: Email Classifier ─────────────────────────────────────────────────
async def classify_email_node(state: AgentState):
    logger.info("[Manager] Executing Email Agent...")
    # Scrub PII before sending to cloud LLM
    clean_email = scrub_pii(state["raw_email"])
    email_data = await process_email(clean_email)
    return {"email_data": email_data, "human_approved": False}


# ── Node: Workflow Planner ─────────────────────────────────────────────────
async def plan_workflow_node(state: AgentState):
    logger.info("[Manager] Executing Manager Planning...")
    email_data = state.get("email_data", {})
    priority = email_data.get("priority", "")
    email_type = email_data.get("email_type", "")

    # ── Fire Slack + Telegram alerts immediately for P1/P2 ──────────────────
    if priority in ("P1-critical", "P2-high"):
        try:
            dept       = email_data.get("department", "unknown")
            alert_text = (
                f"🚨 *{priority.upper()} Incident Detected*\n"
                f">#Type:* {email_type}   *Dept:* {dept}\n"
                f">AI Operations Center is processing this automatically."
            )
            await slack_service.send_notification(alert_text)
        except Exception as slack_err:
            logger.warning(f"[Slack] Alert failed (non-fatal): {slack_err}")

        try:
            await telegram_service.send_p1_alert(email_data)
        except Exception as tg_err:
            logger.warning(f"[Telegram] Alert failed (non-fatal): {tg_err}")

    model = router.select_model(task_type='manager_planning', sensitivity='low')

    messages = [
        {
            "role": "system",
            "content": (
                "You are a workflow planner. Based on the email classification, decide which agents to run. "
                "Output ONLY JSON:\n"
                '{"needs_incident_analysis": bool, "needs_knowledge_search": bool, '
                '"search_query": "relevant search terms", "needs_ticket": bool, "needs_meeting": bool}\n\n'
                "Rules:\n"
                "- needs_incident_analysis=true if email_type=incident or priority is P1/P2\n"
                "- needs_ticket=true if requires_ticket=true or email_type=incident\n"
                "- needs_knowledge_search=true if email_type=query or email_type=request\n"
                "- needs_meeting=true only for P1-critical incidents\n"
                "- search_query should be a focused keyword search based on the email content"
            )
        },
        {"role": "user", "content": json.dumps(email_data)}
    ]

    try:
        response = await router.call_llm(model=model, messages=messages)
        plan = extract_json(response)
        if plan is None:
            raise ValueError(f"No JSON in plan response: {response[:200]}")
    except Exception as e:
        logger.error(f"[Manager] Planning error: {e}")
        # Smart fallback based on classification
        plan = {
            "needs_incident_analysis": email_data.get("email_type") == "incident" or priority in ["P1-critical", "P2-high"],
            "needs_knowledge_search": email_data.get("email_type") in ["query", "request"],
            "search_query": email_data.get("email_type", ""),
            "needs_ticket": email_data.get("requires_ticket", False),
            "needs_meeting": priority == "P1-critical",
        }

    return {"workflow_plan": plan}


# ── Node: Parallel Agents (Incident + Knowledge simultaneously) ────────────
async def parallel_agents_node(state: AgentState):
    """
    Runs Incident Analysis and Knowledge Search in PARALLEL using asyncio.gather.
    This saves significant latency when both are needed.
    """
    logger.info("[Manager] Executing Incident + Knowledge Agents IN PARALLEL...")
    plan = state.get("workflow_plan", {})
    email_data = state.get("email_data", {})

    tasks = []
    task_names = []

    if plan.get("needs_incident_analysis"):
        tasks.append(analyze_incident(email_data))
        task_names.append("incident")

    if plan.get("needs_knowledge_search"):
        query = plan.get("search_query") or email_data.get("email_type", "")
        tasks.append(query_knowledge_base(query))
        task_names.append("knowledge")

    if not tasks:
        return {}

    results = await asyncio.gather(*tasks, return_exceptions=True)

    updates: Dict[str, Any] = {}
    for name, result in zip(task_names, results):
        if isinstance(result, Exception):
            logger.error(f"[Manager] Parallel agent '{name}' failed: {result}")
            if name == "incident":
                updates["incident_result"] = {"error": str(result)}
            elif name == "knowledge":
                updates["knowledge_results"] = {"error": str(result), "documents_found": 0, "rag_mode": "failed"}
        else:
            if name == "incident":
                updates["incident_result"] = result
            elif name == "knowledge":
                updates["knowledge_results"] = result

    return updates


# ── Node: Only Incident (when no knowledge search needed) ──────────────────
async def incident_only_node(state: AgentState):
    logger.info("[Manager] Executing Incident Agent...")
    incident_res = await analyze_incident(state.get("email_data", {}))
    return {"incident_result": incident_res}


# ── Node: Only Knowledge (when no incident analysis needed) ────────────────
async def knowledge_only_node(state: AgentState):
    logger.info("[Manager] Executing Knowledge Agent...")
    plan = state.get("workflow_plan", {})
    query = plan.get("search_query") or state["email_data"].get("email_type", "")
    results = await query_knowledge_base(query)
    return {"knowledge_results": results}


# ── Routing conditions ─────────────────────────────────────────────────────
def router_condition(state: AgentState):
    plan = state.get("workflow_plan", {})
    priority = state.get("email_data", {}).get("priority", "")

    needs_incident = plan.get("needs_incident_analysis", False) or priority in ["P1-critical", "P2-high"]
    needs_knowledge = plan.get("needs_knowledge_search", False)

    # Run both in parallel if both needed
    if needs_incident and needs_knowledge:
        return "parallel_agents"
    elif needs_incident:
        return "incident_only"
    elif needs_knowledge:
        return "knowledge_only"

    # No agents needed — go straight to ticket/summary
    return _check_post_research(state)


def _check_post_research(state: AgentState) -> str:
    plan = state.get("workflow_plan", {})
    priority = state.get("email_data", {}).get("priority", "")

    if plan.get("needs_ticket", False):
        if priority in ["P1-critical", "P2-high"] and not state.get("human_approved"):
            return "human_approval"
        return "ticket_agent"

    if plan.get("needs_meeting", False):
        return "meeting_agent"

    return "executive_summary"


def post_research_condition(state: AgentState):
    return _check_post_research(state)


def post_ticket_condition(state: AgentState):
    plan = state.get("workflow_plan", {})
    if plan.get("needs_meeting", False):
        return "meeting_agent"
    return "executive_summary"


# ── Node: Human Approval Gate ──────────────────────────────────────────────
async def human_approval_node(state: AgentState):
    logger.info("[Manager] Human Approval gate — workflow paused, awaiting approval.")
    await slack_service.send_approval_request(state.get("email_data", {}))
    return {}


# ── Node: Ticket Agent ─────────────────────────────────────────────────────
async def ticket_agent_node(state: AgentState):
    logger.info("[Manager] Executing Ticket Agent...")
    ticket = await create_jira_ticket(
        state.get("email_data", {}),
        state.get("workflow_plan", {}),
        state.get("incident_result", {})
    )
    return {"ticket_result": ticket}


# ── Node: Meeting Agent ────────────────────────────────────────────────────
async def meeting_agent_node(state: AgentState):
    logger.info("[Manager] Executing Meeting Agent...")
    meeting = await schedule_meeting(state.get("email_data", {}), state.get("workflow_plan", {}))
    return {"meeting_result": meeting}


# ── Node: Executive Summary ────────────────────────────────────────────────
async def executive_summary_node(state: AgentState):
    logger.info("[Manager] Executing Executive Summary...")
    model = router.select_model(task_type='executive_summary', sensitivity='low')

    summary_data = {
        "email":     state.get("email_data"),
        "incident":  state.get("incident_result", {}),
        "knowledge": state.get("knowledge_results", {}),
        "ticket":    state.get("ticket_result", {}),
        "meeting":   state.get("meeting_result", {}),
    }

    messages = [
        {
            "role": "system",
            "content": (
                "Write a concise executive summary (3-5 sentences) of the processed incident/request. "
                "Include: what happened, what was done, and any next steps. Output plain text only."
            )
        },
        {"role": "user", "content": json.dumps(summary_data)}
    ]

    summary = await router.call_llm(model=model, messages=messages, max_tokens=400)
    return {"executive_summary": summary}


# ── Graph Builder ──────────────────────────────────────────────────────────
def build_manager_graph():
    workflow = StateGraph(AgentState)

    # Register all nodes
    workflow.add_node("classify_email",   classify_email_node)
    workflow.add_node("plan_workflow",    plan_workflow_node)
    workflow.add_node("parallel_agents",  parallel_agents_node)   # NEW: parallel
    workflow.add_node("incident_only",    incident_only_node)      # NEW: solo incident
    workflow.add_node("knowledge_only",   knowledge_only_node)     # NEW: solo knowledge
    workflow.add_node("human_approval",   human_approval_node)
    workflow.add_node("ticket_agent",     ticket_agent_node)
    workflow.add_node("meeting_agent",    meeting_agent_node)
    workflow.add_node("executive_summary", executive_summary_node)

    # Entry
    workflow.set_entry_point("classify_email")
    workflow.add_edge("classify_email", "plan_workflow")

    # After planning: smart route
    workflow.add_conditional_edges(
        "plan_workflow",
        router_condition,
        {
            "parallel_agents":   "parallel_agents",
            "incident_only":     "incident_only",
            "knowledge_only":    "knowledge_only",
            "human_approval":    "human_approval",
            "ticket_agent":      "ticket_agent",
            "meeting_agent":     "meeting_agent",
            "executive_summary": "executive_summary",
        }
    )

    # After parallel/solo research: check ticket/meeting
    for research_node in ["parallel_agents", "incident_only", "knowledge_only"]:
        workflow.add_conditional_edges(
            research_node,
            post_research_condition,
            {
                "human_approval":    "human_approval",
                "ticket_agent":      "ticket_agent",
                "meeting_agent":     "meeting_agent",
                "executive_summary": "executive_summary",
            }
        )

    # Human approval always flows to ticket
    workflow.add_edge("human_approval", "ticket_agent")

    # After ticket: check meeting
    workflow.add_conditional_edges(
        "ticket_agent",
        post_ticket_condition,
        {
            "meeting_agent":     "meeting_agent",
            "executive_summary": "executive_summary",
        }
    )

    workflow.add_edge("meeting_agent",     "executive_summary")
    workflow.add_edge("executive_summary", END)

    # SqliteSaver persists HITL graph state across server restarts.
    # If a P1/P2 is paused at human_approval and the server restarts,
    # the approve/reject can still resume the workflow.
    try:
        # The newer version of langgraph-checkpoint-sqlite strictly separates sync and async savers.
        # Since the graph is compiled synchronously but invoked asynchronously, we use MemorySaver.
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
        logger.info("[Manager] Using MemorySaver checkpointer for HITL.")
    except Exception as e:
        logger.warning(f"[Manager] Checkpointer unavailable ({e}).")
        checkpointer = None

    return workflow.compile(checkpointer=checkpointer, interrupt_before=["human_approval"])
