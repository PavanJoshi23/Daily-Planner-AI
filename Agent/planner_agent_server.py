"""
Planner Orchestrator FastAPI Server
=====================================
Endpoints:
  POST /chat              — new user message (returns reply + optional HITL payload)
  POST /resume            — resume a HITL-paused graph (approve / reject)
  GET  /activity/{tid}   — SSE stream of agent activity events for a thread
  GET  /health            — health check
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import traceback
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from client_agent import run_planner, resume_planner


# ---------------------------------------------------------------------------
# Per-thread activity queues  (used by SSE endpoint)
# SSE consumer creates a queue; /chat puts events into it.
# Sentinel value None signals end-of-stream.
# ---------------------------------------------------------------------------

_activity: dict[str, queue.Queue] = {}
_activity_lock = threading.Lock()


def _get_queue(thread_id: str) -> queue.Queue | None:
    with _activity_lock:
        return _activity.get(thread_id)


def _make_queue(thread_id: str) -> queue.Queue:
    """Return the existing queue for this thread, creating one only if absent."""
    with _activity_lock:
        if thread_id not in _activity:
            _activity[thread_id] = queue.Queue(maxsize=64)
        return _activity[thread_id]


def _remove_queue(thread_id: str) -> None:
    with _activity_lock:
        _activity.pop(thread_id, None)


def _push(thread_id: str, event: dict) -> None:
    """Push an activity event to the SSE queue for this thread (non-blocking)."""
    q = _get_queue(thread_id)
    if q:
        try:
            q.put_nowait(event)
        except queue.Full:
            pass  # drop if reader is too slow


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    thread_id: str = Field(..., min_length=1)
    verbose: bool = False


class HitlPayload(BaseModel):
    summary: str
    tool: str
    args: dict


class ChatResponse(BaseModel):
    reply: str
    hitl: HitlPayload | None = None
    interrupted: bool = False
    error: str | None = None


class ResumeRequest(BaseModel):
    thread_id: str = Field(..., min_length=1)
    approved: bool


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

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

    # ── Health ──────────────────────────────────────────────────────────────

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/")
    async def root() -> dict[str, Any]:
        return {"ok": True, "service": "PlannerOrchestrator"}

    # ── Activity SSE stream ─────────────────────────────────────────────────

    @app.get("/activity/{thread_id}")
    async def activity_stream(thread_id: str) -> StreamingResponse:
        """
        Server-Sent Events endpoint.  Opens a queue for this thread,
        streams events while /chat or /resume is running, then closes.

        Event format:  data: {"agent": "planner|calendar|tasks|context", "status": "running|idle"}
        """
        q = _make_queue(thread_id)
        loop = asyncio.get_event_loop()

        async def generate():
            try:
                while True:
                    # Non-blocking read with async yield to avoid blocking event loop
                    try:
                        event = await loop.run_in_executor(
                            None, lambda: q.get(timeout=60)
                        )
                    except queue.Empty:
                        break  # timeout — client should reconnect if needed

                    if event is None:  # sentinel: end of stream
                        break

                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                _remove_queue(thread_id)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # disable nginx buffering
            },
        )

    # ── /chat ───────────────────────────────────────────────────────────────

    async def _run_in_thread(fn, *args, **kwargs):
        """Run a blocking function in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    def _build_response(result: dict) -> JSONResponse:
        hitl = HitlPayload(**result["hitl"]) if result.get("hitl") else None
        return JSONResponse(ChatResponse(
            reply=result["reply"],
            hitl=hitl,
            interrupted=result["interrupted"],
        ).model_dump())

    @app.post("/chat")
    async def chat(req: ChatRequest) -> JSONResponse:
        try:
            # Create the queue eagerly so events are buffered even if the
            # SSE /activity/ connection arrives slightly after /chat starts.
            _make_queue(req.thread_id)
            on_event = lambda ev: _push(req.thread_id, ev)
            result = await _run_in_thread(
                run_planner, req.message, req.thread_id,
                on_event=on_event, verbose=req.verbose,
            )
            # Signal end-of-stream so SSE loop closes
            _push(req.thread_id, None)
            return _build_response(result)
        except Exception as exc:
            traceback.print_exc()
            _push(req.thread_id, None)
            return JSONResponse(
                ChatResponse(reply="", error=str(exc)).model_dump(),
                status_code=500,
            )


    @app.post("/chat/")
    async def chat_slash(req: ChatRequest) -> JSONResponse:
        return await chat(req)

    # ── /resume ─────────────────────────────────────────────────────────────

    @app.post("/resume")
    async def resume(req: ResumeRequest) -> JSONResponse:
        try:
            on_event = lambda ev: _push(req.thread_id, ev)
            result = await _run_in_thread(
                resume_planner, req.approved, req.thread_id,
                on_event=on_event,
            )
            _push(req.thread_id, None)
            return _build_response(result)
        except Exception as exc:
            traceback.print_exc()
            _push(req.thread_id, None)
            return JSONResponse(
                ChatResponse(reply="", error=str(exc)).model_dump(),
                status_code=500,
            )

    return app


def run() -> None:
    uvicorn.run(build_app(), host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()
