from __future__ import annotations

import traceback
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from client_agent import run_planner


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    verbose: bool = False


class ChatResponse(BaseModel):
    reply: str
    error: str | None = None


def build_app() -> FastAPI:
    app = FastAPI(title="PlannerOrchestrator")
    app.add_middleware(
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

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/")
    async def root() -> dict[str, Any]:
        return {"ok": True, "service": "PlannerOrchestrator", "chatPath": "/chat"}

    async def _chat(req: ChatRequest) -> JSONResponse:
        try:
            reply = run_planner(req.message, verbose=req.verbose)
            return JSONResponse(ChatResponse(reply=reply).model_dump())
        except Exception as exc:
            traceback.print_exc()
            return JSONResponse(
                ChatResponse(reply="", error=str(exc)).model_dump(),
                status_code=500,
            )

    # Accept both with/without trailing slash, and also allow POST / for simple clients.
    @app.post("/chat")
    async def chat(req: ChatRequest) -> JSONResponse:
        return await _chat(req)

    @app.post("/chat/")
    async def chat_slash(req: ChatRequest) -> JSONResponse:
        return await _chat(req)

    @app.post("/")
    async def chat_root(req: ChatRequest) -> JSONResponse:
        return await _chat(req)

    return app


def run() -> None:
    uvicorn.run(build_app(), host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()

