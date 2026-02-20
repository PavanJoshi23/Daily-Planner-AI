"""
Base class for all A2A server agents.
Subclass it, implement `handle_task`, declare `AGENT_CARD`.
"""
from __future__ import annotations

import traceback
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from a2a_types import (
    AgentCard,
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCError,
    Task,
    TaskSendParams,
    TaskState,
    TaskStatus,
    Message,
)


class A2AServerBase:
    AGENT_CARD: AgentCard          # must be set by subclass
    PORT: int                      # must be set by subclass

    def __init__(self) -> None:
        self.app = FastAPI(title=self.AGENT_CARD.name)
        # Dev-friendly CORS so a local React frontend can call the agent servers.
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self._register_routes()

    # ------------------------------------------------------------------
    # Override in subclasses
    # ------------------------------------------------------------------

    def handle_task(self, task: Task, user_message: Message) -> Task:
        """Process the task and return the updated Task with COMPLETED status."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Route registration
    # ------------------------------------------------------------------

    def _register_routes(self) -> None:

        @self.app.get("/.well-known/agent.json")
        async def agent_card() -> JSONResponse:
            return JSONResponse(self.AGENT_CARD.model_dump())

        @self.app.post("/")
        async def jsonrpc_endpoint(request: Request) -> JSONResponse:
            body: dict[str, Any] = await request.json()
            rpc_req = JSONRPCRequest(**body)

            if rpc_req.method == "tasks/send":
                return JSONResponse(self._handle_tasks_send(rpc_req).model_dump())

            return JSONResponse(
                JSONRPCResponse(
                    id=rpc_req.id,
                    error=JSONRPCError(code=-32601, message=f"Method not found: {rpc_req.method}"),
                ).model_dump()
            )

    def _handle_tasks_send(self, rpc_req: JSONRPCRequest) -> JSONRPCResponse:
        try:
            params = TaskSendParams(**rpc_req.params)
            task = Task(
                id=params.id,
                sessionId=params.sessionId,
                status=TaskStatus(state=TaskState.WORKING),
                history=[params.message],
                metadata=params.metadata,
            )
            completed_task = self.handle_task(task, params.message)
            return JSONRPCResponse(id=rpc_req.id, result=completed_task.model_dump())

        except Exception as exc:
            traceback.print_exc()
            return JSONRPCResponse(
                id=rpc_req.id,
                error=JSONRPCError(code=-32000, message=str(exc)),
            )

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        uvicorn.run(self.app, host="0.0.0.0", port=self.PORT)