"""
Thin HTTP client that speaks the A2A JSON-RPC protocol.
Used by the orchestrator to call server agents.
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx

from a2a_types import (
    AgentCard,
    JSONRPCRequest,
    JSONRPCResponse,
    Message,
    Task,
    TaskSendParams,
    TaskState,
)


class A2AClient:
    def __init__(self, agent_url: str, timeout: float = 120.0) -> None:
        self.base_url = agent_url.rstrip("/")
        self.timeout = timeout
        self._card: AgentCard | None = None

    # ------------------------------------------------------------------
    # Agent Card discovery
    # ------------------------------------------------------------------

    def fetch_agent_card(self) -> AgentCard:
        """Discover the remote agent's capabilities."""
        resp = httpx.get(
            f"{self.base_url}/.well-known/agent.json", timeout=self.timeout
        )
        resp.raise_for_status()
        self._card = AgentCard(**resp.json())
        return self._card

    @property
    def agent_card(self) -> AgentCard | None:
        return self._card

    # ------------------------------------------------------------------
    # tasks/send
    # ------------------------------------------------------------------

    def send_task(
        self,
        message: Message,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Task:
        """
        Send a task to the remote agent and return the completed Task.
        Raises on RPC-level errors.
        """
        params = TaskSendParams(
            id=str(uuid.uuid4()),
            sessionId=session_id or str(uuid.uuid4()),
            message=message,
            metadata=metadata or {},
        )
        rpc_request = JSONRPCRequest(method="tasks/send", params=params.model_dump())

        resp = httpx.post(
            self.base_url,
            json=rpc_request.model_dump(),
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()

        rpc_response = JSONRPCResponse(**resp.json())
        if rpc_response.error:
            raise RuntimeError(
                f"A2A error {rpc_response.error.code}: {rpc_response.error.message}"
            )

        task = Task(**rpc_response.result)
        if task.status.state not in {TaskState.COMPLETED, TaskState.INPUT_NEEDED}:
            raise RuntimeError(f"Unexpected task state: {task.status.state}")

        return task

    # ------------------------------------------------------------------
    # Helper: extract first data artifact payload
    # ------------------------------------------------------------------

    @staticmethod
    def extract_data(task: Task) -> dict[str, Any] | None:
        from a2a_types import DataPart
        for artifact in task.artifacts:
            for part in artifact.parts:
                if isinstance(part, DataPart):
                    return part.data
        return None