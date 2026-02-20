"""
Official A2A (Agent-to-Agent) protocol types.
Spec: https://google.github.io/A2A/specification/
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Agent Card  (served at /.well-known/agent.json)
# ---------------------------------------------------------------------------

class AgentCapabilities(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False
    stateTransitionHistory: bool = False


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    inputModes: list[str] = ["text"]
    outputModes: list[str] = ["text"]
    tags: list[str] = []
    examples: list[str] = []


class AgentCard(BaseModel):
    name: str
    description: str
    url: str                          # base URL of this agent
    version: str = "1.0.0"
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = []
    defaultInputMode: str = "text"
    defaultOutputMode: str = "text"


# ---------------------------------------------------------------------------
# Task / Message / Part  (core A2A data model)
# ---------------------------------------------------------------------------

class TaskState(str, Enum):
    SUBMITTED    = "submitted"
    WORKING      = "working"
    INPUT_NEEDED = "input-required"
    COMPLETED    = "completed"
    FAILED       = "failed"
    CANCELED     = "canceled"


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class DataPart(BaseModel):
    type: Literal["data"] = "data"
    data: dict[str, Any]
    mimeType: str = "application/json"


Part = TextPart | DataPart


class Message(BaseModel):
    role: Literal["user", "agent"]
    parts: list[Part]

    @staticmethod
    def user_text(text: str) -> "Message":
        return Message(role="user", parts=[TextPart(text=text)])

    @staticmethod
    def agent_text(text: str) -> "Message":
        return Message(role="agent", parts=[TextPart(text=text)])


class TaskStatus(BaseModel):
    state: TaskState
    message: Message | None = None


class Artifact(BaseModel):
    name: str | None = None
    parts: list[Part] = []
    index: int = 0


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sessionId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus = Field(
        default_factory=lambda: TaskStatus(state=TaskState.SUBMITTED)
    )
    history: list[Message] = []
    artifacts: list[Artifact] = []
    metadata: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 envelope
# ---------------------------------------------------------------------------

class JSONRPCRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    method: str
    params: dict[str, Any] = {}


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Any = None


class JSONRPCResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: Any = None
    error: JSONRPCError | None = None


# ---------------------------------------------------------------------------
# tasks/send  params & result
# ---------------------------------------------------------------------------

class TaskSendParams(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sessionId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: Message
    metadata: dict[str, Any] = {}