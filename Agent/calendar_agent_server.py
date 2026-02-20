from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from a2a_types import (
    AgentCard, AgentCapabilities, AgentSkill,
    Artifact, DataPart, Message, Task, TaskState, TaskStatus, TextPart,
)
from server_base import A2AServerBase

DATA_DIR = Path(__file__).resolve().parent / "data"
CALENDAR_FILE = DATA_DIR / "calendar.json"


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
            if a_start < b_end and b_start < a_end:          # overlap
                conflicts.append({"event_a": a, "event_b": b})
    return conflicts


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

    # ------------------------------------------------------------------
    # Intent dispatch
    # ------------------------------------------------------------------

    def handle_task(self, task: Task, user_message: Message) -> Task:
        text = " ".join(p.text for p in user_message.parts if isinstance(p, TextPart)).lower()

        if "update" in text or "move" in text or "reschedule" in text or "change" in text:
            return self._handle_update(task, text)
        if "conflict" in text or "overlap" in text or "clash" in text:
            return self._handle_conflicts(task)
        return self._handle_get(task, text)

    # ------------------------------------------------------------------
    # GET events
    # ------------------------------------------------------------------

    def _handle_get(self, task: Task, text: str) -> Task:
        day = "TODAY"
        for token in text.split():
            token = token.strip(".,?!")
            if re.match(r"\d{4}-\d{2}-\d{2}", token):
                day = token
                break

        events = _load()
        filtered = [e for e in events if e.get("date") in {day, "TODAY"}]
        task.artifacts = [Artifact(name="calendar_events", parts=[DataPart(data={"day": day, "events": filtered})])]
        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message.agent_text(f"Found {len(filtered)} event(s) for {day}."),
        )
        return task

    # ------------------------------------------------------------------
    # UPDATE event timing
    # ------------------------------------------------------------------

    def _handle_update(self, task: Task, text: str) -> Task:
        """
        Expects tokens like: event_id=E001 start=15:00 end=16:00
        or natural: move E001 to 15:00-16:00
        """
        events = _load()

        # Parse event id
        eid_match = re.search(r"\b([a-z]\d{3,})\b", text, re.IGNORECASE)
        event_id = eid_match.group(1).upper() if eid_match else None

        # Parse times (HH:MM patterns)
        times = re.findall(r"\b(\d{1,2}:\d{2})\b", text)

        if not event_id or len(times) < 2:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message.agent_text(
                    f"Could not parse update request. Provide event_id and start/end times. "
                    f"Got id={event_id}, times={times}"
                ),
            )
            return task

        new_start, new_end = times[0], times[1]
        updated = False
        for event in events:
            if str(event.get("id", "")).upper() == event_id:
                old_start, old_end = event.get("start"), event.get("end")
                event["start"] = new_start
                event["end"] = new_end
                updated = True
                _save(events)
                task.artifacts = [
                    Artifact(
                        name="updated_event",
                        parts=[DataPart(data={
                            "event_id": event_id,
                            "old_start": old_start, "old_end": old_end,
                            "new_start": new_start, "new_end": new_end,
                            "event": event,
                        })],
                    )
                ]
                task.status = TaskStatus(
                    state=TaskState.COMPLETED,
                    message=Message.agent_text(
                        f"Event {event_id} rescheduled from {old_start}-{old_end} to {new_start}-{new_end}."
                    ),
                )
                break

        if not updated:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message.agent_text(f"Event {event_id} not found."),
            )
        return task

    # ------------------------------------------------------------------
    # DETECT conflicts
    # ------------------------------------------------------------------

    def _handle_conflicts(self, task: Task) -> Task:
        events = _load()
        conflicts = _find_conflicts(events)
        task.artifacts = [
            Artifact(
                name="conflicts",
                parts=[DataPart(data={"conflict_count": len(conflicts), "conflicts": conflicts})],
            )
        ]
        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message.agent_text(
                f"Found {len(conflicts)} conflict(s)." if conflicts else "No scheduling conflicts found."
            ),
        )
        return task


if __name__ == "__main__":
    CalendarAgentServer().run()