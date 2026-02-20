from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from a2a_types import (
    AgentCard, AgentCapabilities, AgentSkill,
    Artifact, DataPart, Message, Task, TaskState, TaskStatus,
)
from server_base import A2AServerBase

DATA_DIR = Path(__file__).resolve().parent / "data"
EMAILS_FILE = DATA_DIR / "emails.json"

URGENCY_KEYWORDS = {"urgent", "asap", "eod", "today"}


def _load_emails() -> list[dict[str, Any]]:
    return json.loads(EMAILS_FILE.read_text(encoding="utf-8"))


class ContextAgentServer(A2AServerBase):
    PORT = 8003
    AGENT_CARD = AgentCard(
        name="ContextAgent",
        description="Reads a simulated inbox and analyses emails to surface urgent task signals.",
        url="http://localhost:8003",
        capabilities=AgentCapabilities(),
        skills=[
            AgentSkill(
                id="get_emails",
                name="Get Inbox Emails",
                description="Return the current simulated inbox emails (from local emails.json).",
                inputModes=["text"],
                outputModes=["data"],
                tags=["context", "email", "read", "inbox"],
                examples=["List my emails", "Show my inbox"],
            ),
            AgentSkill(
                id="get_context",
                name="Get Urgency Context",
                description=(
                    "Scan email data for urgency signals and return "
                    "task IDs that need prioritisation."
                ),
                inputModes=["text"],
                outputModes=["data"],
                tags=["context", "email", "urgency"],
                examples=["Are there any urgent emails I should know about?"],
            )
        ],
    )

    def handle_task(self, task: Task, user_message: Message) -> Task:
        text = " ".join(
            getattr(p, "text", "") for p in getattr(user_message, "parts", [])  # Message parts are TextPart-like
        ).lower()

        # If the user asks to list/show emails, return inbox contents.
        if any(w in text for w in ("inbox", "email", "emails", "list", "show")) and not any(
            w in text for w in ("urgent", "urgency", "asap", "eod", "analyse", "analyze", "context", "signal")
        ):
            return self._handle_get_emails(task)

        # Default: urgency analysis
        return self._handle_urgency(task)

    def _handle_get_emails(self, task: Task) -> Task:
        emails = _load_emails()
        payload = {"email_count": len(emails), "emails": emails}
        task.artifacts = [Artifact(name="inbox_emails", parts=[DataPart(data=payload)])]
        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message.agent_text(f"Retrieved {len(emails)} email(s)."),
        )
        return task

    def _handle_urgency(self, task: Task) -> Task:
        emails = _load_emails()
        urgent_task_ids: set[str] = set()
        reasons: list[str] = []

        for email in emails:
            combined = (
                str(email.get("subject") or "") + "\n" + str(email.get("body") or "")
            ).lower()
            if any(kw in combined for kw in URGENCY_KEYWORDS):
                tid = email.get("task_id")
                if tid:
                    urgent_task_ids.add(str(tid))
                    reasons.append(
                        f"Email suggests urgency for task '{tid}': {email.get('subject')}"
                    )

        payload = {
            "email_count": len(emails),
            "urgent_task_ids": sorted(urgent_task_ids),
            "reasons": reasons,
        }

        task.artifacts = [
            Artifact(
                name="urgency_context",
                parts=[DataPart(data=payload)],
            )
        ]
        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message.agent_text(
                f"Analysed {len(emails)} email(s); "
                f"{len(urgent_task_ids)} urgent task(s) found."
            ),
        )
        return task


if __name__ == "__main__":
    ContextAgentServer().run()