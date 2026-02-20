from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import AzureChatOpenAI

from a2a_types import (
    AgentCard, AgentCapabilities, AgentSkill,
    Artifact, DataPart, Message, Task, TaskState, TaskStatus, TextPart,
)
from config import Config
from server_base import A2AServerBase

DATA_DIR = Path(__file__).resolve().parent / "data"
CALENDAR_FILE = DATA_DIR / "calendar.json"


# ---------------------------------------------------------------------------
# Helpers (unchanged logic)
# ---------------------------------------------------------------------------

def _load() -> list[dict[str, Any]]:
    return json.loads(CALENDAR_FILE.read_text(encoding="utf-8"))


def _save(events: list[dict[str, Any]]) -> None:
    CALENDAR_FILE.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")


def _to_minutes(t: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _find_conflicts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return pairs of overlapping events on the same date."""
    conflicts = []
    dated = [e for e in events if e.get("start") and e.get("end")]
    for i, a in enumerate(dated):
        for b in dated[i + 1:]:
            if a.get("date") != b.get("date"):
                continue
            a_start, a_end = _to_minutes(a["start"]), _to_minutes(a["end"])
            b_start, b_end = _to_minutes(b["start"]), _to_minutes(b["end"])
            if a_start < b_end and b_start < a_end:
                conflicts.append({"event_a": a, "event_b": b})
    return conflicts


# ---------------------------------------------------------------------------
# Tools (LLM-callable)
# ---------------------------------------------------------------------------

@tool
def get_calendar_events(day: str) -> str:
    """
    Fetch calendar events for a given day.
    Args:
        day: A date string in YYYY-MM-DD format, or the literal string 'TODAY'.
    Returns JSON with 'day' and 'events' list.
    """
    events = _load()
    filtered = [e for e in events if e.get("date") in {day, "TODAY"}]
    return json.dumps({"day": day, "events": filtered}, ensure_ascii=False)


@tool
def update_event_timing(event_id: str, new_start: str, new_end: str) -> str:
    """
    Reschedule a calendar event to a new start and end time.
    Args:
        event_id:  The event's id field (e.g. 'E001').
        new_start: New start time in HH:MM format (e.g. '15:00').
        new_end:   New end time in HH:MM format (e.g. '16:00').
    Returns JSON confirming the old and new times, or an error message.
    """
    events = _load()
    for event in events:
        if str(event.get("id", "")).upper() == event_id.upper():
            old_start, old_end = event.get("start"), event.get("end")
            event["start"] = new_start
            event["end"] = new_end
            _save(events)
            return json.dumps({
                "event_id": event_id,
                "old_start": old_start, "old_end": old_end,
                "new_start": new_start, "new_end": new_end,
                "event": event,
            }, ensure_ascii=False)
    return json.dumps({"error": f"Event {event_id} not found."})


@tool
def detect_conflicts() -> str:
    """
    Detect overlapping/conflicting calendar events.
    Returns JSON with 'conflict_count' and a list of 'conflicts'
    (each conflict has 'event_a' and 'event_b').
    """
    events = _load()
    conflicts = _find_conflicts(events)
    return json.dumps({
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }, ensure_ascii=False)


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
    )


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are CalendarAgent, a focused assistant that manages a local calendar.

AVAILABLE TOOLS:
- get_calendar_events(day): Fetch events for a date (YYYY-MM-DD or 'TODAY').
- update_event_timing(event_id, new_start, new_end): Reschedule an event. \
Times must be HH:MM format.
- detect_conflicts(): Find overlapping calendar events.

RULES:
- Always use a tool to answer — never guess from memory.
- For any read request, call get_calendar_events.
- For any update/move/reschedule request, call update_event_timing.
- For any conflict/overlap/clash question, call detect_conflicts.
- Return only factual, concise results. No extra commentary or suggestions.
- After calling a tool, summarise the result in 1–3 lines.
"""

_TOOLS = [get_calendar_events, update_event_timing, detect_conflicts]


# ---------------------------------------------------------------------------
# Agent Server
# ---------------------------------------------------------------------------

class CalendarAgentServer(A2AServerBase):
    PORT = 8001
    AGENT_CARD = AgentCard(
        name="CalendarAgent",
        description=(
            "Read and write calendar events. "
            "Supports: get events, update event timing, detect/resolve conflicts."
        ),
        url="http://localhost:8001",
        capabilities=AgentCapabilities(),
        skills=[
            AgentSkill(
                id="get_calendar",
                name="Get Calendar Events",
                description="Fetch events for a date (YYYY-MM-DD or TODAY).",
                tags=["calendar", "read"],
                examples=["What's on my calendar for 2025-07-21?"],
            ),
            AgentSkill(
                id="update_event",
                name="Update Event Timing",
                description="Change start/end time of a calendar event by event id.",
                tags=["calendar", "write"],
                examples=["Move event E001 to 15:00-16:00"],
            ),
            AgentSkill(
                id="detect_conflicts",
                name="Detect Scheduling Conflicts",
                description="Find overlapping calendar events.",
                tags=["calendar", "conflict"],
                examples=["Do I have any conflicts today?"],
            ),
        ],
    )

    def handle_task(self, task: Task, user_message: Message) -> Task:
        # Extract plain text from the incoming A2A message
        user_text = " ".join(
            p.text for p in user_message.parts if isinstance(p, TextPart)
        ).strip()

        # Build & invoke the LLM agent
        llm = _build_llm()
        agent = create_agent(llm, tools=_TOOLS, system_prompt=_SYSTEM_PROMPT, name="calendar_agent")

        result = agent.invoke({"messages": [HumanMessage(content=user_text)]})
        messages = result.get("messages", [])
        last = messages[-1] if messages else None
        answer = (last.content if isinstance(last, AIMessage) else str(getattr(last, "content", last))) if last else "No response from CalendarAgent."

        # Pack result into A2A task
        task.artifacts = [
            Artifact(
                name="calendar_result",
                parts=[DataPart(data={"answer": answer})],
            )
        ]
        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message.agent_text(answer),
        )
        return task


if __name__ == "__main__":
    CalendarAgentServer().run()