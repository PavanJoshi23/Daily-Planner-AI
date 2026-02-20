"""
Start all three A2A server agents in separate processes.
Run this once before starting the client agent.

Usage:  python run_servers.py
"""
from __future__ import annotations

import argparse
import multiprocessing
import time


def _run_calendar():
    from calendar_agent_server import CalendarAgentServer
    CalendarAgentServer().run()


def _run_tasks():
    from tasks_agent_server import TasksAgentServer
    TasksAgentServer().run()


def _run_context():
    from context_agent_server import ContextAgentServer
    ContextAgentServer().run()

def _run_planner():
    from planner_agent_server import run
    run()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run A2A server agents")
    parser.add_argument(
        "--with-planner",
        action="store_true",
        help="Also start the PlannerOrchestrator API on http://localhost:8000",
    )
    args = parser.parse_args()

    processes = [
        multiprocessing.Process(target=_run_calendar, daemon=True),
        multiprocessing.Process(target=_run_tasks,    daemon=True),
        multiprocessing.Process(target=_run_context,  daemon=True),
    ]
    if args.with_planner:
        processes.insert(0, multiprocessing.Process(target=_run_planner, daemon=True))
    for p in processes:
        p.start()
        print(f"Started PID {p.pid}")

    print("\nAll A2A server agents running.")
    if args.with_planner:
        print("  PlannerAPI    → http://localhost:8000")
    print("  CalendarAgent → http://localhost:8001")
    print("  TasksAgent    → http://localhost:8002")
    print("  ContextAgent  → http://localhost:8003")
    print("\nPress Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for p in processes:
            p.terminate()