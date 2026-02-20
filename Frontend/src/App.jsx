import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CONFIG } from "./config";
import AgentCards from "./components/AgentCards.jsx";
import MarkdownMessage from "./components/MarkdownMessage.jsx";
import { chatWithPlanner } from "./api/planner.js";
import { checkPlannerHealth } from "./api/health.js";
import { fetchAgentCard } from "./api/a2a.js";

function useSessionId() {
  const [sessionId] = useState(() => {
    try {
      const v = localStorage.getItem("a2a_session_id");
      if (v) return v;
      const next = globalThis.crypto?.randomUUID
        ? globalThis.crypto.randomUUID()
        : String(Date.now());
      localStorage.setItem("a2a_session_id", next);
      return next;
    } catch {
      return globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : String(Date.now());
    }
  });
  return sessionId;
}

export default function App() {
  const sessionId = useSessionId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [input, setInput] = useState("Plan my day for today.");
  const [messages, setMessages] = useState(() => [
    {
      id: "sys-1",
      role: "assistant",
      content:
        "Good Time to Start the Day!"
    }
  ]);

  const canSend = useMemo(() => input.trim().length > 0 && !busy, [input, busy]);
  const bottomRef = useRef(null);

  const [refreshingAgents, setRefreshingAgents] = useState(false);
  const baseAgents = useMemo(
    () => [
      {
        id: "planner",
        name: "Planner (Orchestrator)",
        url: CONFIG.plannerApiBase,
        description: "Main planner chat API (server-side LLM orchestration).",
        status: "unknown",
        skills: []
      },
      {
        id: "calendar",
        name: "CalendarAgent",
        url: CONFIG.calendarAgentBase,
        description: "Loads agent card…",
        status: "unknown",
        skills: []
      },
      {
        id: "tasks",
        name: "TasksAgent",
        url: CONFIG.tasksAgentBase,
        description: "Loads agent card…",
        status: "unknown",
        skills: []
      },
      {
        id: "context",
        name: "ContextAgent",
        url: CONFIG.contextAgentBase,
        description: "Loads agent card…",
        status: "unknown",
        skills: []
      }
    ],
    []
  );

  const [agents, setAgents] = useState(() => baseAgents);

  const refreshAgents = useCallback(async () => {
    setRefreshingAgents(true);
    try {
      // Always refresh from a clean baseline derived from config.
      const next = baseAgents.map((a) => ({ ...a }));

      // Planner health
      try {
        await checkPlannerHealth(CONFIG.plannerApiBase);
        const idx = next.findIndex((a) => a.id === "planner");
        if (idx >= 0) next[idx] = { ...next[idx], status: "online" };
      } catch {
        const idx = next.findIndex((a) => a.id === "planner");
        if (idx >= 0) next[idx] = { ...next[idx], status: "offline" };
      }

      // A2A agent cards
      for (const id of ["calendar", "tasks", "context"]) {
        const idx = next.findIndex((a) => a.id === id);
        const base =
          id === "calendar"
            ? CONFIG.calendarAgentBase
            : id === "tasks"
              ? CONFIG.tasksAgentBase
              : CONFIG.contextAgentBase;
        try {
          const card = await fetchAgentCard(base);
          next[idx] = {
            ...next[idx],
            name: card?.name || next[idx].name,
            url: card?.url || next[idx].url,
            description: card?.description || next[idx].description,
            skills: card?.skills || [],
            status: "online"
          };
        } catch {
          next[idx] = { ...next[idx], status: "offline" };
        }
      }

      setAgents(next);
    } finally {
      setRefreshingAgents(false);
    }
  }, [baseAgents]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, busy]);

  useEffect(() => {
    refreshAgents();
  }, [refreshAgents]);

  async function onSend() {
    const text = input.trim();
    if (!text || busy) return;

    setError("");
    setBusy(true);
    setInput("");

    const userMsg = { id: `u-${Date.now()}`, role: "user", content: text };
    setMessages((m) => [...m, userMsg]);

    try {
      const reply = await chatWithPlanner(CONFIG.plannerApiBase, {
        message: text,
        verbose: false
      });
      const agentMsg = { id: `a-${Date.now()}`, role: "assistant", content: reply || "(empty reply)" };
      setMessages((m) => [...m, agentMsg]);
    } catch (e) {
      setError(String(e?.message || e));
      const agentMsg = {
        id: `aerr-${Date.now()}`,
        role: "assistant",
        content: "I couldn't complete that request. Check the error above and try again."
      };
      setMessages((m) => [...m, agentMsg]);
    } finally {
      setBusy(false);
    }
  }

  function avatarEmoji(role) {
    return role === "user" ? "🙂" : "🤖";
  }

  return (
    <div className="appShell">
      <AgentCards agents={agents} onRefresh={refreshAgents} refreshing={refreshingAgents} />

      <main className="main">
        {error ? <div className="errorBox">{error}</div> : null}

        <section className="chatPanel">
          <div className="chatMessages">
            {messages.map((m) => (
              <div
                key={m.id}
                className={m.role === "user" ? "chatRow chatRowUser" : "chatRow chatRowAssistant"}
              >
                <div className="chatAvatar" title={m.role === "user" ? "Human" : "Agent"}>
                  {avatarEmoji(m.role)}
                </div>
                <div className={m.role === "user" ? "chatBubble chatBubbleUser" : "chatBubble"}>
                  {m.role === "user" ? m.content : <MarkdownMessage content={m.content} />}
                </div>
              </div>
            ))}
            {busy ? (
              <div className="chatRow chatRowAssistant">
                <div className="chatAvatar" title="Agent">
                  {avatarEmoji("assistant")}
                </div>
                <div className="chatBubble chatBubbleTyping">Thinking…</div>
              </div>
            ) : null}
            <div ref={bottomRef} />
          </div>

          <div className="chatComposer">
            <textarea
              className="chatInput"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              rows={2}
              placeholder="Message Planner…"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onSend();
                }
              }}
            />
            <button
              className="chatSend"
              disabled={!canSend}
              onClick={onSend}
              type="button"
              aria-label="Send message"
              title="Send"
            >
              <svg width="25" height="25" viewBox="0 0 24 24" fill="none">
                <path
                  d="M3 11.8 21 3l-8.8 18-2.2-7-7-2.2Z"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinejoin="round"
                />
                <path
                  d="M21 3 10 14"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
          {/* <div className="chatHint">
            Session <code>{sessionId.slice(0, 8)}…</code> · Press <code>Enter</code> to send,{" "}
            <code>Shift+Enter</code> for a new line.
          </div> */}
        </section>
      </main>
    </div>
  );
}

