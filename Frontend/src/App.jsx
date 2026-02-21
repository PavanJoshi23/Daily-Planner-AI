import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CONFIG } from "./config";
import AgentCards from "./components/AgentCards.jsx";
import MarkdownMessage from "./components/MarkdownMessage.jsx";
import ConfirmationCard from "./components/ConfirmationCard.jsx";
import { chatWithPlanner, resumePlanner } from "./api/planner.js";
import { checkPlannerHealth } from "./api/health.js";
import { fetchAgentCard } from "./api/a2a.js";

// ---------------------------------------------------------------------------
// Session / thread ID  (persisted in localStorage)
// ---------------------------------------------------------------------------

function useThreadId() {
  const [threadId] = useState(() => {
    try {
      const v = localStorage.getItem("a2a_thread_id");
      if (v) return v;
      const next = globalThis.crypto?.randomUUID
        ? globalThis.crypto.randomUUID()
        : String(Date.now());
      localStorage.setItem("a2a_thread_id", next);
      return next;
    } catch {
      return globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : String(Date.now());
    }
  });
  return threadId;
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const threadId = useThreadId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [input, setInput] = useState("Plan my day for today.");
  const [activeAgent, setActiveAgent] = useState(null); // which agent card is pulsing
  const [messages, setMessages] = useState(() => [
    {
      id: "sys-1",
      role: "assistant",
      content: "Good Time to Start the Day!",
    },
  ]);

  const canSend = useMemo(() => input.trim().length > 0 && !busy, [input, busy]);
  const bottomRef = useRef(null);

  // ── Agent cards ──────────────────────────────────────────────────────────
  const [refreshingAgents, setRefreshingAgents] = useState(false);
  const baseAgents = useMemo(
    () => [
      {
        id: "planner",
        name: "Planner (Orchestrator)",
        url: CONFIG.plannerApiBase,
        description: "Main planner chat API (server-side LLM orchestration).",
        status: "unknown",
        skills: [],
      },
      { id: "calendar", name: "CalendarAgent", url: CONFIG.calendarAgentBase, description: "Loads agent card…", status: "unknown", skills: [] },
      { id: "tasks", name: "TasksAgent", url: CONFIG.tasksAgentBase, description: "Loads agent card…", status: "unknown", skills: [] },
      { id: "context", name: "ContextAgent", url: CONFIG.contextAgentBase, description: "Loads agent card…", status: "unknown", skills: [] },
    ],
    []
  );

  const [agents, setAgents] = useState(() => baseAgents);

  const refreshAgents = useCallback(async () => {
    setRefreshingAgents(true);
    try {
      const next = baseAgents.map((a) => ({ ...a }));
      try {
        await checkPlannerHealth(CONFIG.plannerApiBase);
        const idx = next.findIndex((a) => a.id === "planner");
        if (idx >= 0) next[idx] = { ...next[idx], status: "online" };
      } catch {
        const idx = next.findIndex((a) => a.id === "planner");
        if (idx >= 0) next[idx] = { ...next[idx], status: "offline" };
      }
      for (const id of ["calendar", "tasks", "context"]) {
        const idx = next.findIndex((a) => a.id === id);
        const base = id === "calendar" ? CONFIG.calendarAgentBase : id === "tasks" ? CONFIG.tasksAgentBase : CONFIG.contextAgentBase;
        try {
          const card = await fetchAgentCard(base);
          next[idx] = { ...next[idx], name: card?.name || next[idx].name, url: card?.url || next[idx].url, description: card?.description || next[idx].description, skills: card?.skills || [], status: "online" };
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

  // ── Agent activity tracking via SSE ─────────────────────────────────────

  /**
   * Open an SSE connection and wait for it to be ESTABLISHED (onopen)
   * before resolving. This guarantees the backend queue exists before
   * /chat fires its first event — preventing the planner event being dropped.
   * Resolves with a cleanup function that closes the source.
   */
  function openActivityStream() {
    return new Promise((resolve) => {
      const url = `${CONFIG.plannerApiBase}/activity/${threadId}`;
      const es = new EventSource(url);

      es.onopen = () => {
        // Connection is live — return a cleanup handle
        resolve(() => { setActiveAgent(null); es.close(); });
      };

      es.onmessage = (e) => {
        try {
          const { agent, status } = JSON.parse(e.data);
          setActiveAgent(status === "running" ? agent : null);
        } catch {
          // ignore malformed events
        }
      };

      es.onerror = () => {
        setActiveAgent(null);
        es.close();
        // resolve anyway so chat isn't blocked indefinitely
        resolve(() => { });
      };
    });
  }

  // ── Send user message ────────────────────────────────────────────────────

  async function onSend() {
    const text = input.trim();
    if (!text || busy) return;

    setError("");
    setBusy(true);
    setInput("");

    const userMsg = { id: `u-${Date.now()}`, role: "user", content: text };
    setMessages((m) => [...m, userMsg]);

    // Wait for SSE connection to be live BEFORE calling /chat
    // so the "planner:running" event is never dropped.
    const closeStream = await openActivityStream();
    try {
      const payload = await chatWithPlanner(CONFIG.plannerApiBase, {
        message: text,
        thread_id: threadId,
        verbose: false,
      });
      _handlePayload(payload);
    } catch (e) {
      setError(String(e?.message || e));
      setMessages((m) => [
        ...m,
        { id: `aerr-${Date.now()}`, role: "assistant", content: "I couldn't complete that request. Check the error above and try again." },
      ]);
    } finally {
      closeStream();
      setBusy(false);
    }
  }

  // ── Handle any planner API response (chat or resume) ────────────────────

  function _handlePayload(payload) {
    if (payload.hitl && payload.interrupted) {
      // Graph is paused — inject a HITL confirmation card into the chat thread
      setMessages((m) => [
        ...m,
        ...(payload.reply ? [{ id: `a-${Date.now()}`, role: "assistant", content: payload.reply }] : []),
        {
          id: `hitl-${Date.now()}`,
          role: "hitl",
          hitl: payload.hitl,
          thread_id: threadId,
        },
      ]);
    } else {
      // Normal reply
      setMessages((m) => [
        ...m,
        { id: `a-${Date.now()}`, role: "assistant", content: payload.reply || "(empty reply)" },
      ]);
    }
  }

  // ── Called by ConfirmationCard after user clicks Approve / Reject ────────

  function onHitlOutcome(resumePayload) {
    // resumePayload is the full /resume response: { reply, hitl, interrupted }
    _handlePayload(resumePayload);
  }

  // ── Render ────────────────────────────────────────────────────────────────

  function avatarEmoji(role) {
    if (role === "user") return "🙂";
    if (role === "hitl") return "⚡";
    return "🤖";
  }

  return (
    <div className="appShell">
      <AgentCards agents={agents} onRefresh={refreshAgents} refreshing={refreshingAgents} activeAgent={activeAgent} />

      <main className="main">
        {error ? <div className="errorBox">{error}</div> : null}

        <section className="chatPanel">
          <div className="chatMessages">
            {messages.map((m) => {
              const isUser = m.role === "user";
              const isHitl = m.role === "hitl";

              return (
                <div
                  key={m.id}
                  className={isUser ? "chatRow chatRowUser" : "chatRow chatRowAssistant"}
                >
                  <div className="chatAvatar" title={isUser ? "Human" : isHitl ? "HITL" : "Agent"}>
                    {avatarEmoji(m.role)}
                  </div>
                  <div className={isUser ? "chatBubble chatBubbleUser" : "chatBubble"}>
                    {isUser ? (
                      m.content
                    ) : isHitl ? (
                      <ConfirmationCard
                        hitl={m.hitl}
                        thread_id={m.thread_id}
                        onOutcome={onHitlOutcome}
                      />
                    ) : (
                      <MarkdownMessage content={m.content} />
                    )}
                  </div>
                </div>
              );
            })}
            {busy ? (
              <div className="chatRow chatRowAssistant">
                <div className="chatAvatar" title="Agent">{avatarEmoji("assistant")}</div>
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
                <path d="M3 11.8 21 3l-8.8 18-2.2-7-7-2.2Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                <path d="M21 3 10 14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </section>
      </main>
    </div>
  );
}
