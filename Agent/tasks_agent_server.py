from __future__ import annotations

import json
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
TASKS_FILE = DATA_DIR / "tasks.json"

PRIORITY_LEVELS = {"low", "medium", "high", "critical"}
RELATIVE_DUE = {"today": "TODAY", "tomorrow": "TOMORROW", "eod": "EOD"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load() -> list[dict[str, Any]]:
    return json.loads(TASKS_FILE.read_text(encoding="utf-8"))


def _save(tasks: list[dict[str, Any]]) -> None:
    TASKS_FILE.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tools (LLM-callable)
# ---------------------------------------------------------------------------

@tool
def get_tasks() -> str:
    """
    Fetch the full to-do list.
    Returns JSON with a 'tasks' list containing all tasks and their details.
    """
    tasks = _load()
    return json.dumps({"tasks": tasks}, ensure_ascii=False)


@tool
def update_task_priority(task_id: str, priority: str) -> str:
    """
    Change the priority of a task.
    Args:
        task_id:  The task's id (e.g. 'T001').
        priority: One of: low, medium, high, critical.
    Returns JSON confirming the priority change, or an error message.
    """
    priority = priority.lower().strip()
    if priority not in PRIORITY_LEVELS:
        return json.dumps({"error": f"Invalid priority '{priority}'. Must be one of: {sorted(PRIORITY_LEVELS)}."})

    tasks = _load()
    for t in tasks:
        if str(t.get("id", "")).upper() == task_id.upper():
            old_priority = t.get("priority", "unset")
            t["priority"] = priority
            _save(tasks)
            return json.dumps({
                "task_id": task_id,
                "old_priority": old_priority,
                "new_priority": priority,
                "task": t,
            }, ensure_ascii=False)
    return json.dumps({"error": f"Task {task_id} not found."})


@tool
def update_task_due_date(task_id: str, due: str) -> str:
    """
    Change the due date of a task.
    Args:
        task_id: The task's id (e.g. 'T001').
        due: One of TODAY / TOMORROW / EOD, or an absolute date YYYY-MM-DD.
    Returns JSON confirming the due-date change, or an error message.
    """
    due = due.strip().upper()
    # Normalise relative keywords
    if due == "TODAY" or due == "TOMORROW" or due == "EOD":
        pass  # already normalised
    elif re.match(r"\d{4}-\d{2}-\d{2}", due):
        pass  # absolute date — keep as-is
    else:
        return json.dumps({"error": f"Unrecognised due value '{due}'. Use TODAY/TOMORROW/EOD or YYYY-MM-DD."})

    tasks = _load()
    for t in tasks:
        if str(t.get("id", "")).upper() == task_id.upper():
            old_due = t.get("due")
            t["due"] = due
            _save(tasks)
            return json.dumps({
                "task_id": task_id,
                "old_due": old_due,
                "new_due": due,
                "task": t,
            }, ensure_ascii=False)
    return json.dumps({"error": f"Task {task_id} not found."})


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
You are TasksAgent, a focused assistant that manages a local to-do list.

AVAILABLE TOOLS:
- get_tasks(): Fetch all tasks with their id, title, priority, due date, and estimate.
- update_task_priority(task_id, priority): Change a task's priority. \
  Valid priorities: low, medium, high, critical.
- update_task_due_date(task_id, due): Change a task's due date. \
  Accepts TODAY, TOMORROW, EOD, or YYYY-MM-DD.

RULES:
- Always use a tool to answer — never guess from memory.
- For listing/reading tasks, call get_tasks.
- For priority-change requests (set priority, mark urgent, escalate, bump), call update_task_priority.
- For due-date/deadline changes, call update_task_due_date.
- Return only factual, concise results. No extra commentary or suggestions.
- After calling a tool, summarise the result in 1–3 lines.
"""

_TOOLS = [get_tasks, update_task_priority, update_task_due_date]

# Singleton — built once per process
_AGENT = None


def _get_agent():
    global _AGENT
    if _AGENT is None:
        _AGENT = create_agent(_build_llm(), tools=_TOOLS, system_prompt=_SYSTEM_PROMPT, name="tasks_agent")
    return _AGENT

# ---------------------------------------------------------------------------
# Agent Server
# ---------------------------------------------------------------------------

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
        user_text = " ".join(
            p.text for p in user_message.parts if isinstance(p, TextPart)
        ).strip()

        agent = _get_agent()
        result = agent.invoke({"messages": [HumanMessage(content=user_text)]})
        messages = result.get("messages", [])
        last = messages[-1] if messages else None
        answer = (last.content if isinstance(last, AIMessage) else str(getattr(last, "content", last))) if last else "No response from TasksAgent."

        # Pack result into A2A task
        task.artifacts = [
            Artifact(
                name="tasks_result",
                parts=[DataPart(data={"answer": answer})],
            )
        ]
        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message.agent_text(answer),
        )
        return task


if __name__ == "__main__":
    TasksAgentServer().run()