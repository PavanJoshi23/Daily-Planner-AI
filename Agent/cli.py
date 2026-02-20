"""
Interactive CLI for the A2A Daily Planner.

Usage:
    python cli.py           # normal mode
    python cli.py --debug   # shows agent thought/action traces
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Iterator

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

from client_agent import build_orchestrator

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

console = Console()

# ---------------------------------------------------------------------------
# Built-in slash-commands (handled before the agent sees them)
# ---------------------------------------------------------------------------

SLASH_COMMANDS: dict[str, str] = {
    "/help":    "Show this help message",
    "/history": "Show conversation history for this session",
    "/clear":   "Clear the screen",
    "/debug":   "Toggle verbose agent tracing on/off",
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
        "[dim]Agent-to-Agent · Plan · Act · Observe[/dim]",
        border_style="cyan",
        padding=(1, 4),
    ))
    console.print()


def _help_panel() -> None:
    # Commands table
    cmd_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    cmd_table.add_column("Command", style="bold yellow")
    cmd_table.add_column("Description", style="dim")
    for cmd, desc in SLASH_COMMANDS.items():
        cmd_table.add_row(cmd, desc)

    # Examples table
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
    """
    Render agent response.
    - Mermaid fences → extracted into their own labelled panel
    - Everything else → Markdown panel
    """
    # ── Split out mermaid blocks ──────────────────────────────────────────
    mermaid_pattern = re.compile(r"```mermaid\s*(.*?)```", re.DOTALL)
    mermaid_blocks = mermaid_pattern.findall(text)
    clean_text = mermaid_pattern.sub("[see diagram below]", text).strip()

    # ── Main response panel ───────────────────────────────────────────────
    console.print()
    console.print(Panel(
        Markdown(clean_text),
        title="[bold green]🤖 Agent[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))

    # ── Mermaid diagram panels ────────────────────────────────────────────
    for i, block in enumerate(mermaid_blocks, 1):
        console.print(Panel(
            Syntax(block.strip(), "markdown", theme="monokai", word_wrap=True),
            title=f"[bold cyan]📊 Diagram {i} — copy into mermaid.live to render[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))

    # ── Footer ────────────────────────────────────────────────────────────
    console.print(f"  [dim]⏱  {elapsed:.1f}s[/dim]\n", justify="right")


def _render_error(msg: str) -> None:
    console.print(Panel(
        f"[red]{msg}[/red]",
        title="[bold red]Error[/bold red]",
        border_style="red",
    ))
    console.print()


def _status_bar(debug: bool) -> Text:
    t = Text()
    t.append("  DEBUG ", style="bold yellow" if debug else "dim")
    t.append("ON  " if debug else "OFF  ", style="bold yellow" if debug else "dim")
    t.append("│  Type [bold]/help[/bold] for commands  │  [bold]/quit[/bold] to exit")
    return t


# ---------------------------------------------------------------------------
# Orchestrator lifecycle — build once, reuse
# ---------------------------------------------------------------------------

def _init_orchestrator(debug: bool) -> object:
    console.print(Rule("[dim]Connecting to A2A server agents…[/dim]", style="dim"))
    console.print()
    executor = build_orchestrator(verbose=debug)
    console.print()
    console.print(Rule("[dim]Ready[/dim]", style="dim"))
    console.print()
    return executor


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

def repl(debug: bool = False) -> None:
    _banner()

    try:
        executor = _init_orchestrator(debug)
    except Exception as exc:
        _render_error(
            f"Failed to connect to agent servers.\n\n"
            f"Make sure `run_servers.py` is running first.\n\nDetails: {exc}"
        )
        sys.exit(1)

    history: list[dict[str, str]] = []
    console.print(_status_bar(debug))
    console.print()

    while True:
        # ---- Prompt ----
        try:
            user_input = Prompt.ask("[bold cyan]You[/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        # ---- Slash commands ----
        cmd = user_input.lower()

        if cmd in ("/quit", "/exit"):
            console.print("[dim]Goodbye![/dim]")
            break

        if cmd == "/clear":
            console.clear()
            _banner()
            console.print(_status_bar(debug))
            console.print()
            continue

        if cmd == "/help":
            _help_panel()
            continue

        if cmd == "/history":
            _history_panel(history)
            continue

        if cmd == "/debug":
            debug = not debug
            # Rebuild with new verbose flag
            console.print(f"[yellow]Debug tracing {'ON' if debug else 'OFF'}[/yellow]")
            executor = _init_orchestrator(debug)
            console.print(_status_bar(debug))
            console.print()
            continue

        # ---- Agent call ----
        start = time.perf_counter()
        agent_reply = ""

        try:
            if debug:
                # In debug mode, show tool-call trace derived from returned messages
                console.print(Rule("[dim yellow]Agent Trace[/dim yellow]", style="dim yellow"))
                result = executor.invoke({"messages": [HumanMessage(content=user_input)]})
                msgs = result.get("messages", [])
                for m in msgs:
                    if isinstance(m, HumanMessage):
                        continue
                    if isinstance(m, ToolMessage):
                        console.print(f"[yellow]Tool[/yellow] {m.name}: {m.content}")
                        continue
                    if isinstance(m, AIMessage):
                        if m.content:
                            console.print(f"[cyan]AI[/cyan]: {m.content}")
                        tool_calls = getattr(m, "tool_calls", None)
                        if tool_calls:
                            console.print(f"[yellow]AI tool_calls[/yellow]: {tool_calls}")
                        continue
                    # Fallback
                    console.print(str(m))

                agent_reply = ""
                if msgs and isinstance(msgs[-1], AIMessage):
                    agent_reply = msgs[-1].content or ""
                console.print(Rule("[dim yellow]End Trace[/dim yellow]", style="dim yellow"))
            else:
                with _thinking_spinner():
                    result = executor.invoke({"messages": [HumanMessage(content=user_input)]})
                msgs = result.get("messages", [])
                agent_reply = msgs[-1].content if msgs and isinstance(msgs[-1], AIMessage) else ""

        except Exception as exc:
            _render_error(str(exc))
            continue

        elapsed = time.perf_counter() - start

        _render_response(agent_reply, elapsed)

        # Elapsed time footer
        console.print(
            f"  [dim]⏱  {elapsed:.1f}s[/dim]",
            justify="right",
        )
        console.print()

        # Save to history
        history.append({"user": user_input, "agent": agent_reply})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A2A Daily Planner CLI")
    parser.add_argument("--debug", action="store_true", help="Show agent thought/action traces")
    args = parser.parse_args()
    repl(debug=args.debug)