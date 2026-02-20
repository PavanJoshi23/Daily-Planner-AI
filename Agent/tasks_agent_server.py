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
TASKS_FILE = DATA_DIR / "tasks.json"

PRIORITY_LEVELS = {"low", "medium", "high", "critical"}
RELATIVE_DUE = {"today": "TODAY", "tomorrow": "TOMORROW", "eod": "EOD"}


def _load() -> list[dict[str, Any]]:
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))


def _save(tasks: list[dict[str, Any]]) -> None:
    TASKS_FILE.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")


class TasksAgentServer(A2AServerBase):
    PORT = 8002
    AGENT_CARD = AgentCard(
        name="TasksAgent",
        description="Read and manage the to-do list. Supports: get tasks, update priority, update due date.",
        url="http://localhost:8002",
        capabilities=AgentCapabilities(),
        skills=[
            AgentSkill(
                id="get_tasks",
                name="Get To-Do List",
                description="Fetch all tasks.",
                tags=["tasks", "read"],
                examples=["What are my tasks?"],
            ),
            AgentSkill(
                id="update_priority",
                name="Update Task Priority",
                description="Set priority (low/medium/high/critical) of a task by id.",
                tags=["tasks", "write"],
                examples=["Set task T001 to high priority"],
            ),
            AgentSkill(
                id="update_due",
                name="Update Task Due Date",
                description="Set due date of a task by id (TODAY/TOMORROW/EOD or YYYY-MM-DD).",
                tags=["tasks", "write"],
                examples=["Change task T004 due to TOMORROW", "Set task T009 due to 2026-02-20"],
            ),
        ],
    )

    def handle_task(self, task: Task, user_message: Message) -> Task:
        text = " ".join(p.text for p in user_message.parts if isinstance(p, TextPart)).lower()

        # Route due-date updates first, because common phrasing ("set task ...") overlaps
        # with priority update intents.
        if any(w in text for w in ("due", "deadline", "date")) or re.search(r"\b\d{4}-\d{2}-\d{2}\b", text):
            return self._handle_update_due(task, text)
        if any(w in text for w in ("priority", "mark", "escalate", "urgent", "bump")):
            return self._handle_update_priority(task, text)
        return self._handle_get(task)

    # ------------------------------------------------------------------

    def _handle_get(self, task: Task) -> Task:
        tasks = _load()
        task.artifacts = [Artifact(name="task_list", parts=[DataPart(data={"tasks": tasks})])]
        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message.agent_text(f"Retrieved {len(tasks)} task(s)."),
        )
        return task

    def _handle_update_priority(self, task: Task, text: str) -> Task:
        """
        Expects: task_id (e.g. T001) and a priority level word.
        Example: "set task T001 to high priority"
        """
        tasks = _load()

        # Find task id  (letter + digits, e.g. T001)
        tid_match = re.search(r"\b([a-z]\d{3,})\b", text, re.IGNORECASE)
        task_id = tid_match.group(1).upper() if tid_match else None

        # Find priority level
        priority = next((p for p in PRIORITY_LEVELS if p in text), None)

        if not task_id or not priority:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message.agent_text(
                    f"Could not parse priority update. Provide task_id and priority level "
                    f"(low/medium/high/critical). Got id={task_id}, priority={priority}."
                ),
            )
            return task

        updated = False
        for t in tasks:
            if str(t.get("id", "")).upper() == task_id:
                old_priority = t.get("priority", "unset")
                t["priority"] = priority
                updated = True
                _save(tasks)
                task.artifacts = [
                    Artifact(
                        name="updated_task",
                        parts=[DataPart(data={
                            "task_id": task_id,
                            "old_priority": old_priority,
                            "new_priority": priority,
                            "task": t,
                        })],
                    )
                ]
                task.status = TaskStatus(
                    state=TaskState.COMPLETED,
                    message=Message.agent_text(
                        f"Task {task_id} priority changed from '{old_priority}' to '{priority}'."
                    ),
                )
                break

        if not updated:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message.agent_text(f"Task {task_id} not found."),
            )
        return task

    def _handle_update_due(self, task: Task, text: str) -> Task:
        """
        Update the due date for a task.
        Accepts:
          - Relative: today/tomorrow/eod (case-insensitive)
          - Absolute: YYYY-MM-DD
        Example:
          "Change task T004 due to tomorrow"
          "Set task T009 due to 2026-02-20"
        """
        tasks = _load()

        tid_match = re.search(r"\b([a-z]\d{3,})\b", text, re.IGNORECASE)
        task_id = tid_match.group(1).upper() if tid_match else None

        # Absolute date wins if present
        date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if date_match:
            due = date_match.group(1)
        else:
            # Normalize common relative forms
            if "end of day" in text or "eod" in text:
                due = "EOD"
            elif "tomorrow" in text:
                due = "TOMORROW"
            elif "today" in text:
                due = "TODAY"
            else:
                # Allow explicit tokens like "due to TODAY"
                tok = next((k for k in RELATIVE_DUE.keys() if k in text), None)
                due = RELATIVE_DUE.get(tok) if tok else None

        if not task_id or not due:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message.agent_text(
                    "Could not parse due date update. Provide a task id and a due date "
                    "(TODAY/TOMORROW/EOD or YYYY-MM-DD). "
                    f"Got id={task_id}, due={due}."
                ),
            )
            return task

        updated = False
        for t in tasks:
            if str(t.get("id", "")).upper() == task_id:
                old_due = t.get("due")
                t["due"] = due
                updated = True
                _save(tasks)
                task.artifacts = [
                    Artifact(
                        name="updated_task_due",
                        parts=[DataPart(data={
                            "task_id": task_id,
                            "old_due": old_due,
                            "new_due": due,
                            "task": t,
                        })],
                    )
                ]
                task.status = TaskStatus(
                    state=TaskState.COMPLETED,
                    message=Message.agent_text(
                        f"Task {task_id} due date changed from '{old_due}' to '{due}'."
                    ),
                )
                break

        if not updated:
            task.status = TaskStatus(
                state=TaskState.FAILED,
                message=Message.agent_text(f"Task {task_id} not found."),
            )
        return task


if __name__ == "__main__":
    TasksAgentServer().run()