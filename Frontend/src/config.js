export const CONFIG = {
  plannerApiBase: import.meta.env.VITE_PLANNER_API_BASE || "http://localhost:8000",
  calendarAgentBase:
    import.meta.env.VITE_CALENDAR_AGENT_BASE || "http://localhost:8001",
  tasksAgentBase: import.meta.env.VITE_TASKS_AGENT_BASE || "http://localhost:8002",
  contextAgentBase:
    import.meta.env.VITE_CONTEXT_AGENT_BASE || "http://localhost:8003"
};

