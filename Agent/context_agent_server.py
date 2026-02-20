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
EMAILS_FILE = DATA_DIR / "emails.json"

URGENCY_KEYWORDS = {"urgent", "asap", "eod", "today"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_emails() -> list[dict[str, Any]]:
    return json.loads(EMAILS_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Tools (LLM-callable)
# ---------------------------------------------------------------------------

@tool
def get_inbox_emails() -> str:
    """
    Return all emails in the simulated inbox.
    Returns JSON with 'email_count' and an 'emails' list containing
    each email's subject, body, sender, and linked task_id if any.
    """
    emails = _load_emails()
    return json.dumps({"email_count": len(emails), "emails": emails}, ensure_ascii=False)


@tool
def get_urgency_context() -> str:
    """
    Scan the inbox for urgency signals and surface task IDs that need prioritisation.
    Urgency keywords searched: 'urgent', 'asap', 'eod', 'today'.
    Returns JSON with 'email_count', 'urgent_task_ids' list, and 'reasons' list.
    """
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

    return json.dumps({
        "email_count": len(emails),
        "urgent_task_ids": sorted(urgent_task_ids),
        "reasons": reasons,
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
You are ContextAgent, a focused assistant that reads a simulated email inbox
to surface urgency signals relevant to the user's task list.

AVAILABLE TOOLS:
- get_inbox_emails(): Return all emails in the inbox with subject, body, sender, task_id.
- get_urgency_context(): Scan emails for urgency keywords (urgent/asap/eod/today) \
and return which task IDs need immediate attention, with reasons.

RULES:
- Always use a tool to answer — never guess from memory.
- If the user wants to see emails / inbox / list emails, call get_inbox_emails.
- If the user asks about urgency, priorities from emails, or task signals, call get_urgency_context.
- Return only factual, concise results. No extra commentary or suggestions.
- After calling a tool, summarise the result in 1–3 lines.
"""

_TOOLS = [get_inbox_emails, get_urgency_context]


# ---------------------------------------------------------------------------
# Agent Server
# ---------------------------------------------------------------------------

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
            ),
        ],
    )

    def handle_task(self, task: Task, user_message: Message) -> Task:
        # Extract plain text from the incoming A2A message
        user_text = " ".join(
            getattr(p, "text", "") for p in getattr(user_message, "parts", [])
        ).strip()

        # Build & invoke the LLM agent
        llm = _build_llm()
        agent = create_agent(llm, tools=_TOOLS, system_prompt=_SYSTEM_PROMPT, name="context_agent")

        result = agent.invoke({"messages": [HumanMessage(content=user_text)]})
        messages = result.get("messages", [])
        last = messages[-1] if messages else None
        answer = (last.content if isinstance(last, AIMessage) else str(getattr(last, "content", last))) if last else "No response from ContextAgent."

        # Pack result into A2A task
        task.artifacts = [
            Artifact(
                name="context_result",
                parts=[DataPart(data={"answer": answer})],
            )
        ]
        task.status = TaskStatus(
            state=TaskState.COMPLETED,
            message=Message.agent_text(answer),
        )
        return task


if __name__ == "__main__":
    ContextAgentServer().run()