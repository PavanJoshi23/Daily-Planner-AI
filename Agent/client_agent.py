from __future__ import annotations

import json

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import AzureChatOpenAI

from a2a_client import A2AClient
from a2a_types import Message
from config import Config

_CALENDAR_CLIENT = A2AClient("http://localhost:8001")
_TASKS_CLIENT    = A2AClient("http://localhost:8002")
_CONTEXT_CLIENT  = A2AClient("http://localhost:8003")


# ---------------------------------------------------------------------------
# READ tools
# ---------------------------------------------------------------------------

@tool
def get_calendar_events(day: str) -> str:
    """
    Fetch calendar events for a given day (YYYY-MM-DD or 'TODAY').
    Returns JSON with 'day' and 'events' list.
    """
    task = _CALENDAR_CLIENT.send_task(Message.user_text(f"Get calendar events for {day}"))
    return json.dumps(A2AClient.extract_data(task), ensure_ascii=False)


@tool
def get_tasks() -> str:
    """
    Fetch the full to-do list.
    Returns JSON with a 'tasks' list.
    """
    task = _TASKS_CLIENT.send_task(Message.user_text("Get all my tasks"))
    return json.dumps(A2AClient.extract_data(task), ensure_ascii=False)


@tool
def get_urgency_context() -> str:
    """
    Analyse emails for urgency signals.
    Returns JSON with 'urgent_task_ids' and 'reasons'.
    """
    task = _CONTEXT_CLIENT.send_task(Message.user_text("Analyse emails for urgency"))
    return json.dumps(A2AClient.extract_data(task), ensure_ascii=False)


@tool
def get_emails() -> str:
    """
    Fetch the simulated inbox emails.
    Returns JSON with an 'emails' list.
    """
    task = _CONTEXT_CLIENT.send_task(Message.user_text("Get all emails"))
    return json.dumps(A2AClient.extract_data(task), ensure_ascii=False)


@tool
def detect_conflicts() -> str:
    """
    Detect overlapping/conflicting calendar events.
    Returns JSON with 'conflict_count' and list of 'conflicts' (each has event_a, event_b).
    """
    task = _CALENDAR_CLIENT.send_task(Message.user_text("Detect scheduling conflicts"))
    return json.dumps(A2AClient.extract_data(task), ensure_ascii=False)


# ---------------------------------------------------------------------------
# WRITE tools
# ---------------------------------------------------------------------------

@tool
def update_calendar_event(event_id: str, new_start: str, new_end: str) -> str:
    """
    Reschedule a calendar event to a new start and end time.
    Args:
        event_id:  The event's id field (e.g. 'E001').
        new_start: New start time in HH:MM format (e.g. '15:00').
        new_end:   New end time in HH:MM format (e.g. '16:00').
    Returns JSON confirming the old and new times.
    """
    msg = f"Update event {event_id} move to {new_start}-{new_end}"
    task = _CALENDAR_CLIENT.send_task(Message.user_text(msg))
    return json.dumps(A2AClient.extract_data(task) or {"status": task.status.state}, ensure_ascii=False)


@tool
def set_task_priority(task_id: str, priority: str) -> str:
    """
    Change the priority of a task.
    Args:
        task_id:  The task's id (e.g. 'T001').
        priority: One of: low, medium, high, critical.
    Returns JSON confirming the priority change.
    """
    msg = f"Set task {task_id} to {priority} priority"
    task = _TASKS_CLIENT.send_task(Message.user_text(msg))
    return json.dumps(A2AClient.extract_data(task) or {"status": task.status.state}, ensure_ascii=False)


@tool
def set_task_due(task_id: str, due: str) -> str:
    """
    Change the due date of a task.
    Args:
        task_id: The task's id (e.g. 'T001').
        due: One of TODAY/TOMORROW/EOD or an absolute date YYYY-MM-DD.
    Returns JSON confirming the due-date change.
    """
    msg = f"Set task {task_id} due to {due}"
    task = _TASKS_CLIENT.send_task(Message.user_text(msg))
    return json.dumps(A2AClient.extract_data(task) or {"status": task.status.state}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Agent prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a Smart Daily Planner assistant. You follow a Plan → Act → Observe loop.

CAPABILITIES:
- Read calendar, tasks, urgency context.
- Read inbox emails (get_emails).
- Detect scheduling conflicts.
- Reschedule events (update_calendar_event).
- Change task priorities (set_task_priority).
- Change task due dates (set_task_due).

════════════════════════════════════════
RESPONSE MODE — pick the right one:
════════════════════════════════════════

## MODE 1 — DIRECT ANSWER
Use this when the user asks a simple factual question:
  "What are my tasks?", "What's on my calendar?", "Any urgent emails?"

Rules:
- Call only the tool(s) needed to answer.
- Reply in plain, concise prose or a short list.
- NO agenda table. NO "PLAN COMPLETE". NO next-action section.
- Max 15 lines.

Example for "What are my tasks for today?":

  You have **4 tasks** today:

  | ID | Title | Priority | Est. | Due |
  |----|-------|----------|------|-----|
  | **T001** | Draft weekly status report | 🔴 critical | 60m | TODAY |
  | **T003** | Investigate prod bug: login timeout | 🔴 critical | 90m | TODAY |
  | **T002** | Code review: PR #482 | 🟠 high | 45m | TODAY |
  | **T004** | Plan sprint work | 🟠 high | 40m | TOMORROW |

  **T001** and **T003** are flagged urgent by email. Start with **T003** (prod impact).

────────────────────────────────────────

## MODE 2 — CHANGE CONFIRMATION
Use when the user asks to change something:
  "Move E001 to 3pm", "Set T002 to critical"

Rules:
- Call the write tool, confirm what changed in 2–3 lines.
- NO full agenda unless the user also asks to re-plan.

Example:
  ✅ **E001** rescheduled: 09:30–10:00 → **15:00–15:30**
  No new conflicts detected.

────────────────────────────────────────

## MODE 3 — FULL DAILY PLAN
Use ONLY when the user explicitly asks to plan, schedule, or agenda their day:
  "Plan my day", "Build my agenda", "Schedule everything"

Use this structure whenever the user asks to plan their day:

✅ **PLAN COMPLETE**

### **Quick summary**
- **Calendar**: X meeting(s), **N conflicts**
- **Top priority**: **T001** (due **TODAY**)
- **Changes made**: none / list changes

### **Today's agenda (09:00–17:00, lunch 12:00–13:00)**
HH:MM–HH:MM | **ID**   | Title (duration, tag)
09:30–10:00  | —        | Daily Standup (**fixed**)
13:00–14:00  | **T001** | Weekly status report (60m, **critical**, due **TODAY**)

### **Key notes (max 3 bullets)**
- **Why this ordering**: ...
- **Buffers**: ...
- **Risk**: ...

### **Next action (pick 1)**
1) ...

════════════════════════════════════════

GLOBAL RULES (all modes):
- Bold task IDs (**T001**) and event IDs (**E001**) always.
- Bold deadlines: **TODAY**, **EOD**, **TOMORROW**.
- You can list the simulated inbox using the get_emails tool (it reads local emails.json).
- Never output a section that wasn't asked for.
- Never add "If you want I can..." follow-up offers unless the user asked an open question.
"""


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


_TOOLS = [
    get_calendar_events,
    get_tasks,
    get_urgency_context,
    get_emails,
    detect_conflicts,
    update_calendar_event,
    set_task_priority,
    set_task_due,
]


def build_orchestrator(verbose: bool = False):
    for client in (_CALENDAR_CLIENT, _TASKS_CLIENT, _CONTEXT_CLIENT):
        try:
            card = client.fetch_agent_card()
            print(f"  ✓ Discovered: {card.name} @ {card.url}")
        except Exception as exc:
            print(f"  ✗ Warning – could not fetch agent card from {client.base_url}: {exc}")

    llm = _build_llm()
    return create_agent(
        llm,
        tools=_TOOLS,
        system_prompt=_SYSTEM_PROMPT,
        debug=verbose,
        name="a2a_daily_planner",
    )


def run_planner(user_text: str, verbose: bool = False) -> str:
    agent = build_orchestrator(verbose=verbose)
    result = agent.invoke({"messages": [HumanMessage(content=user_text)]})
    messages = result.get("messages", [])
    if not messages:
        return ""
    last = messages[-1]
    if isinstance(last, AIMessage):
        return last.content or ""
    return str(getattr(last, "content", last))