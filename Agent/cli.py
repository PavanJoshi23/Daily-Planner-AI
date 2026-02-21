"""
Interactive CLI for the A2A Daily Planner  (with LangGraph Human-in-the-Loop support).

Usage:
    python cli.py           # normal mode
    python cli.py --debug   # shows agent thought/action traces
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid

import requests
from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from client_agent import build_orchestrator, run_planner, resume_planner

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

console = Console()

_PLANNER_BASE = "http://localhost:8000"

# ---------------------------------------------------------------------------
# Built-in slash-commands
# ---------------------------------------------------------------------------

SLASH_COMMANDS: dict[str, str] = {
    "/help":    "Show this help message",
    "/history": "Show conversation history for this session",
    "/clear":   "Clear the screen",
    "/quit":    "Exit the planner",
    "/exit":    "Exit the planner",
}

EXAMPLE_PROMPTS = [
    "Plan my day for today",
    "Do I have any scheduling conflicts?",
    "Move event E001 to 15:00-16:00",
    "Set task T002 to high priority",
    "What tasks are urgent based on my emails?",
    "Reschedule any conflicts and give me a clean agenda",
]


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _banner() -> None:
    console.print()
    console.print(Panel.fit(
        "[bold cyan]🗓  A2A Daily Planner[/bold cyan]\n"
        "[dim]Agent-to-Agent · Plan · Act · Observe · ✋ Human-in-the-Loop[/dim]",
        border_style="cyan",
        padding=(1, 4),
    ))
    console.print()


def _help_panel() -> None:
    cmd_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    cmd_table.add_column("Command", style="bold yellow")
    cmd_table.add_column("Description", style="dim")
    for cmd, desc in SLASH_COMMANDS.items():
        cmd_table.add_row(cmd, desc)

    ex_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    ex_table.add_column("Example prompts", style="bold green")
    for ex in EXAMPLE_PROMPTS:
        ex_table.add_row(f'"{ex}"')

    console.print(Panel(
        Columns([cmd_table, ex_table], equal=True, expand=True),
        title="[bold]Help[/bold]",
        border_style="yellow",
        padding=(1, 2),
    ))
    console.print()


def _history_panel(history: list[dict[str, str]]) -> None:
    if not history:
        console.print("[dim]No history yet.[/dim]\n")
        return
    table = Table(box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("You", style="bold cyan", ratio=2)
    table.add_column("Agent", style="white", ratio=5)
    for i, turn in enumerate(history, 1):
        table.add_row(
            str(i),
            turn["user"][:80] + ("…" if len(turn["user"]) > 80 else ""),
            turn["agent"][:120] + ("…" if len(turn["agent"]) > 120 else ""),
        )
    console.print(Panel(table, title="[bold]Session History[/bold]", border_style="blue"))
    console.print()


def _thinking_spinner(label: str = "Agent is thinking…") -> Live:
    spinner = Spinner("dots2", text=f"[dim]{label}[/dim]", style="cyan")
    return Live(spinner, console=console, refresh_per_second=12, transient=True)


import re
from rich.syntax import Syntax

def _render_response(text: str, elapsed: float) -> None:
    mermaid_pattern = re.compile(r"```mermaid\s*(.*?)```", re.DOTALL)
    mermaid_blocks = mermaid_pattern.findall(text)
    clean_text = mermaid_pattern.sub("[see diagram below]", text).strip()

    console.print()
    console.print(Panel(
        Markdown(clean_text),
        title="[bold green]🤖 Agent[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))

    for i, block in enumerate(mermaid_blocks, 1):
        console.print(Panel(
            Syntax(block.strip(), "markdown", theme="monokai", word_wrap=True),
            title=f"[bold cyan]📊 Diagram {i} — copy into mermaid.live to render[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))

    console.print(f"  [dim]⏱  {elapsed:.1f}s[/dim]\n", justify="right")


def _render_error(msg: str) -> None:
    console.print(Panel(
        f"[red]{msg}[/red]",
        title="[bold red]Error[/bold red]",
        border_style="red",
    ))
    console.print()


def _status_bar() -> Text:
    t = Text()
    t.append("  ✋ Human-in-the-Loop ", style="bold cyan")
    t.append("ACTIVE  ", style="bold cyan")
    t.append("│  Type [bold]/help[/bold] for commands  │  [bold]/quit[/bold] to exit")
    return t


# ---------------------------------------------------------------------------
# Human-in-the-Loop flow helpers  (via /resume HTTP endpoint)
# ---------------------------------------------------------------------------

def _handle_hitl(hitl: dict, thread_id: str) -> tuple[str, str]:
    """
    Display the HITL approval panel and send the decision to /resume.
    Returns (agent_reply_after_resume, outcome_label).
    """
    console.print()
    console.print(Panel(
        f"[bold yellow]⏳ Action awaiting your approval[/bold yellow]\n\n"
        f"  {hitl['summary']}\n\n"
        f"[dim]Tool:[/dim] {hitl['tool']}  "
        f"[dim]Args:[/dim] {json.dumps(hitl['args'])}",
        title="[bold yellow]🔔 Human-in-the-Loop  (LangGraph interrupt)[/bold yellow]",
        border_style="yellow",
        padding=(1, 2),
    ))

    while True:
        choice = Prompt.ask(
            "  [bold yellow]Approve or Reject?[/bold yellow]  [dim](A/R)[/dim]",
            choices=["A", "a", "R", "r"],
            show_choices=False,
        ).strip().upper()

        approved = (choice == "A")

        try:
            with _thinking_spinner("Resuming agent…"):
                resp = requests.post(
                    f"{_PLANNER_BASE}/resume",
                    json={"thread_id": thread_id, "approved": approved},
                    timeout=120,
                )
                resp.raise_for_status()
                payload = resp.json()

            reply = payload.get("reply", "")

            if approved:
                outcome = "✅ Approved and executed."
                console.print(Panel(
                    "[green]✅ Action approved — agent is resuming…[/green]",
                    border_style="green", padding=(0, 2),
                ))
            else:
                outcome = "🚫 Action cancelled."
                console.print(Panel(
                    "[dim]🚫 Action cancelled. No changes were made.[/dim]",
                    border_style="dim", padding=(0, 2),
                ))

            return reply, outcome

        except Exception as exc:
            _render_error(f"Resume failed: {exc}")
            return "", f"❌ Error: {exc}"


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

def repl() -> None:
    _banner()

    # Each CLI session gets a unique thread_id so LangGraph checkpoints correctly
    thread_id = str(uuid.uuid4())
    console.print(f"  [dim]Session thread: {thread_id[:8]}…[/dim]")
    console.print()

    history: list[dict[str, str]] = []
    console.print(_status_bar())
    console.print()

    while True:
        try:
            user_input = Prompt.ask("[bold cyan]You[/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd in ("/quit", "/exit"):
            console.print("[dim]Goodbye![/dim]")
            break

        if cmd == "/clear":
            console.clear()
            _banner()
            console.print(_status_bar())
            console.print()
            continue

        if cmd == "/help":
            _help_panel()
            continue

        if cmd == "/history":
            _history_panel(history)
            continue

        # ---- Agent call via HTTP ----
        start = time.perf_counter()
        agent_reply = ""
        hitl_outcome = ""

        try:
            with _thinking_spinner():
                resp = requests.post(
                    f"{_PLANNER_BASE}/chat",
                    json={"message": user_input, "thread_id": thread_id, "verbose": False},
                    timeout=120,
                )
                resp.raise_for_status()
                payload = resp.json()

            agent_reply = payload.get("reply", "")
            hitl_data = payload.get("hitl")

            # ── HITL pause handling ─────────────────────────────────────
            # A single turn can chain multiple write tools; loop until no more interrupts
            while hitl_data:
                after_reply, hitl_outcome = _handle_hitl(hitl_data, thread_id)
                if after_reply:
                    agent_reply = after_reply
                # Check if resume triggered another interrupt
                hitl_data = payload.get("hitl") if not after_reply else None
                # (after_reply payload from /resume already consumed above)
                break   # _handle_hitl already called /resume which returned next payload

        except Exception as exc:
            _render_error(str(exc))
            continue

        elapsed = time.perf_counter() - start

        if agent_reply:
            _render_response(agent_reply, elapsed)

        history.append({
            "user": user_input,
            "agent": (agent_reply or "") + (" " + hitl_outcome if hitl_outcome else ""),
        })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A2A Daily Planner CLI")
    parser.parse_args()      # kept for forward compatibility
    repl()