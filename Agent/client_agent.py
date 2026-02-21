"""
Orchestrator Agent  —  Daily Planner AI
========================================
Architecture:
  Planner Orchestrator  (this file)
      ├── ask_calendar_agent(instruction)  →  CalendarAgent  :8001
      ├── ask_tasks_agent(instruction)     →  TasksAgent     :8002
      └── ask_context_agent(instruction)   →  ContextAgent   :8003

The orchestrator sends natural-language instructions to specialised sub-agents.
Each sub-agent owns its domain: it decides which of its own tools to call and
returns a concise answer.  The orchestrator synthesises the answers and plans.

HITL (Human-in-the-Loop):
  Write instructions are intercepted *before* reaching the sub-agent.
  LangGraph's interrupt() pauses the graph and asks the user for approval.
  On approval, the instruction is forwarded; on rejection, nothing changes.
"""

from __future__ import annotations

import re

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import AzureChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command, interrupt

from a2a_client import A2AClient
from a2a_types import Message
from config import Config


# ---------------------------------------------------------------------------
# Sub-agent clients  (one per domain)
# ---------------------------------------------------------------------------

_CALENDAR = A2AClient("http://localhost:8001")
_TASKS    = A2AClient("http://localhost:8002")
_CONTEXT  = A2AClient("http://localhost:8003")

# Shared checkpointer  — persists graph state for HITL resume
_CHECKPOINTER = MemorySaver()

# Singleton agent cache
_AGENT = None


# ---------------------------------------------------------------------------
# Write-instruction detection
# ---------------------------------------------------------------------------

_WRITE_PATTERNS = re.compile(
    r"\b(move|reschedule|update|change|set|mark|bump|escalate|cancel|delete|remove)\b",
    re.IGNORECASE,
)

def _is_write(instruction: str) -> bool:
    """Heuristic: does this instruction modify data?"""
    return bool(_WRITE_PATTERNS.search(instruction))


def _call_agent(client: A2AClient, instruction: str) -> str:
    """Send instruction to a sub-agent and return its plain-text answer."""
    task = client.send_task(Message.user_text(instruction))
    data = A2AClient.extract_data(task) or {}
    return data.get("answer") or str(task.status.message or "No response.")


# ---------------------------------------------------------------------------
# Delegation tools  (3 tools instead of 8 fine-grained ones)
# ---------------------------------------------------------------------------

@tool
def ask_calendar_agent(instruction: str) -> str:
    """
    Delegate a calendar request to the CalendarAgent.

    CalendarAgent owns: reading events, rescheduling / moving events,
    detecting and resolving scheduling conflicts.

    Use natural language, e.g.:
      "Get events for 2026-03-01"
      "Move event E001 to 15:00–16:00"
      "Are there any conflicts today?"

    Write actions (move, reschedule, update) require human approval first.
    """
    if _is_write(instruction):
        approved = interrupt({
            "tool": "ask_calendar_agent",
            "summary": f"CalendarAgent will: **{instruction}**",
            "args": {"instruction": instruction},
        })
        if not approved:
            return "Action cancelled by user. No calendar changes were made."

    return _call_agent(_CALENDAR, instruction)


@tool
def ask_tasks_agent(instruction: str) -> str:
    """
    Delegate a task-management request to the TasksAgent.

    TasksAgent owns: listing tasks, changing priority,
    changing due dates / deadlines.

    Use natural language, e.g.:
      "List all tasks"
      "Set task T001 to critical priority"
      "Change T003 due date to TOMORROW"

    Write actions (set, change, update) require human approval first.
    """
    if _is_write(instruction):
        approved = interrupt({
            "tool": "ask_tasks_agent",
            "summary": f"TasksAgent will: **{instruction}**",
            "args": {"instruction": instruction},
        })
        if not approved:
            return "Action cancelled by user. No task changes were made."

    return _call_agent(_TASKS, instruction)


@tool
def ask_context_agent(instruction: str) -> str:
    """
    Delegate a context / email analysis request to the ContextAgent.

    ContextAgent owns: reading inbox emails, detecting urgency signals,
    surfacing which tasks are referenced by urgent emails.

    Use natural language, e.g.:
      "Show my inbox"
      "Are there any urgent emails?"
      "Which tasks need attention based on emails?"

    This agent is read-only — no approval required.
    """
    return _call_agent(_CONTEXT, instruction)


# ---------------------------------------------------------------------------
# System prompt  — orchestrator level only
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are the Daily Planner Orchestrator.

Your job: understand the user's request and delegate to the right specialist agent.
You do NOT handle data directly — you route and synthesise.

════════════════════════════════════════════════════
SPECIALIST AGENTS  (use exactly one or more per turn)
════════════════════════════════════════════════════

  ask_calendar_agent(instruction)
      → Calendar events, scheduling, conflict detection & resolution
        Examples: "Get events for TODAY", "Move E001 to 15:00–16:00", "Any conflicts?"

  ask_tasks_agent(instruction)
      → To-do list, priorities, due dates
        Examples: "List all tasks", "Set T001 to critical", "Change T004 due to TOMORROW"

  ask_context_agent(instruction)
      → Email inbox, urgency signals
        Examples: "Show inbox", "Which tasks are flagged urgent by emails?"

════════════════════════════════════════════════════
WRITE ACTIONS & HUMAN-IN-THE-LOOP
════════════════════════════════════════════════════
Write actions (move, reschedule, set priority, change due date) are intercepted
automatically before reaching the sub-agent.  The user will see an approval card.
If approved, the instruction is forwarded.  If rejected, nothing changes.
You do NOT need to ask for permission yourself — just call the tool.

════════════════════════════════════════════════════
RESPONSE MODES — pick the right one
════════════════════════════════════════════════════

MODE 1 — DIRECT ANSWER
  Use for simple factual questions ("What tasks do I have?").
  Call the relevant agent, reply concisely. No tables unless helpful. Max 15 lines.

MODE 2 — CHANGE OUTCOME
  Use after a write action was approved or rejected.
  Report the sub-agent's result in 2–3 lines.
    ✅ Approved: "✅ **E001** rescheduled to 15:00–16:00."
    🚫 Rejected: "🚫 No changes were made."

MODE 3 — FULL DAILY PLAN
  Use ONLY when the user explicitly asks to plan / schedule / agenda their day.
  Call all three agents to gather context, then produce:

  ✅ **PLAN COMPLETE**

  ### Quick summary
  - **Calendar**: X meetings, N conflicts
  - **Top priority**: **T001** (due **TODAY**)
  - **Changes made**: list / none

  ### Today's agenda
  HH:MM–HH:MM | **ID**   | Title
  ...

  ### Key notes (max 3 bullets)

════════════════════════════════════════════════════
GLOBAL RULES
════════════════════════════════════════════════════
- Bold IDs: **T001**, **E001**.
- Bold relative dates: **TODAY**, **TOMORROW**, **EOD**.
- Never invent data — always call the relevant agent first.
- Never add unsolicited follow-up offers.
"""


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------

def _build_llm() -> AzureChatOpenAI:
    Config.validate_azure()
    return AzureChatOpenAI(
        azure_deployment=Config.INFERENCE_MODEL,
        openai_api_version=Config.OPENAI_API_VERSION,
        azure_endpoint=Config.OPENAI_API_URL,
        api_key=Config.OPENAI_API_KEY,
        temperature=1,
        streaming=True,
    )


# ---------------------------------------------------------------------------
# Agent  (singleton — MemorySaver persists HITL state across HTTP requests)
# ---------------------------------------------------------------------------

_TOOLS = [ask_calendar_agent, ask_tasks_agent, ask_context_agent]


def build_orchestrator(verbose: bool = False):
    """Return the (cached) orchestrator LangGraph agent."""
    global _AGENT
    if _AGENT is not None:
        return _AGENT

    # Discover sub-agents on first build
    for client in (_CALENDAR, _TASKS, _CONTEXT):
        try:
            card = client.fetch_agent_card()
            print(f"  ✓ {card.name} @ {card.url}")
        except Exception as exc:
            print(f"  ✗ Could not reach {client.base_url}: {exc}")

    _AGENT = create_agent(
        _build_llm(),
        tools=_TOOLS,
        system_prompt=_SYSTEM_PROMPT,
        checkpointer=_CHECKPOINTER,
        debug=verbose,
        name="planner_orchestrator",
    )
    return _AGENT


# ---------------------------------------------------------------------------
# Tool → agent-card ID mapping  (for activity events)
# ---------------------------------------------------------------------------

_TOOL_TO_AGENT: dict[str, str] = {
    "ask_calendar_agent": "calendar",
    "ask_tasks_agent":    "tasks",
    "ask_context_agent":  "context",
}

# ---------------------------------------------------------------------------
# Public helpers used by planner_agent_server.py
# ---------------------------------------------------------------------------

from collections.abc import Callable

def _emit(on_event: Callable | None, agent_id: str, status: str) -> None:
    """Fire an activity event if a listener is registered."""
    if on_event:
        on_event({"agent": agent_id, "status": status})


def _stream_graph(
    agent,
    inputs,
    config: dict,
    on_event: Callable | None,
) -> dict:
    """
    Run the LangGraph agent via stream(stream_mode="updates").

    Each chunk is a dict { node_name: state_update }.
    We inspect node names and tool calls to emit activity events:
      - "agent" node  → orchestrator LLM is thinking  → emit planner:running
      - "tools" node  → a delegation tool is executing:
          ask_calendar_agent → emit calendar:running
          ask_tasks_agent    → emit tasks:running
          ask_context_agent  → emit context:running

    Returns the final merged state dict (same shape as invoke()).
    """
    _emit(on_event, "planner", "running")

    final: dict = {}
    for chunk in agent.stream(inputs, config=config, stream_mode="updates"):
        for node_name, update in chunk.items():

            if node_name == "agent":
                # LLM reasoning step — orchestrator is thinking
                _emit(on_event, "planner", "running")

            elif node_name == "tools":
                # A tool finished — figure out which sub-agent was called
                for msg in update.get("messages", []):
                    tool_name = getattr(msg, "name", "") or ""
                    agent_id = _TOOL_TO_AGENT.get(tool_name)
                    if agent_id:
                        _emit(on_event, agent_id, "running")

            # Merge updates so we can read final state after the loop
            if isinstance(update, dict):
                for k, v in update.items():
                    final[k] = v

        # Capture __interrupt__ which lives at the top-level chunk
        if "__interrupt__" in chunk:
            final["__interrupt__"] = chunk["__interrupt__"]

    _emit(on_event, "planner", "idle")
    return final


def run_planner(
    user_text: str,
    thread_id: str,
    on_event: Callable | None = None,
    verbose: bool = False,
) -> dict:
    """
    Send a new user message to the orchestrator for this thread.

    Args:
        on_event: Optional callback fired with {"agent": str, "status": str}
                  during execution for real-time activity tracking.
    Returns:
        { "reply": str, "hitl": dict | None, "interrupted": bool }
    """
    agent = build_orchestrator(verbose=verbose)
    config = {"configurable": {"thread_id": thread_id}}
    result = _stream_graph(
        agent,
        {"messages": [HumanMessage(content=user_text)]},
        config,
        on_event,
    )
    hitl = _extract_hitl(result)
    return {
        "reply": _last_ai_reply(result),
        "hitl": hitl,
        "interrupted": hitl is not None,
    }


def resume_planner(
    approved: bool,
    thread_id: str,
    on_event: Callable | None = None,
    verbose: bool = False,
) -> dict:
    """
    Resume an interrupt()-paused graph with the user's approval decision.

    Args:
        approved:  True → forward instruction to sub-agent. False → cancel.
        thread_id: Must match the thread that was interrupted.
        on_event:  Optional activity callback.
    Returns:
        { "reply": str, "hitl": dict | None, "interrupted": bool }
    """
    agent = build_orchestrator(verbose=verbose)
    config = {"configurable": {"thread_id": thread_id}}
    result = _stream_graph(agent, Command(resume=approved), config, on_event)
    hitl = _extract_hitl(result)
    return {
        "reply": _last_ai_reply(result),
        "hitl": hitl,
        "interrupted": hitl is not None,
    }


def _extract_hitl(result: dict) -> dict | None:
    for intr in result.get("__interrupt__", ()):
        v = getattr(intr, "value", None)
        if isinstance(v, dict) and "tool" in v:
            return v
    return None


def _last_ai_reply(result: dict) -> str:
    messages = result.get("messages", [])
    last = messages[-1] if messages else None
    if isinstance(last, AIMessage):
        return last.content or ""
    return ""