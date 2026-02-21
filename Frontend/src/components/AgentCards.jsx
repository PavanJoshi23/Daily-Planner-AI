import React from "react";

// Maps agent card id → display label shown when running
const RUNNING_LABELS = {
  planner: "🧠 Thinking…",
  calendar: "📅 Fetching…",
  tasks: "✅ Fetching…",
  context: "📧 Scanning…",
};

function StatusDot({ status, running }) {
  if (running) {
    return <span className="statusDot statusDotRunning" />;
  }
  const cls =
    status === "online"
      ? "statusDot statusDotOnline"
      : status === "offline"
        ? "statusDot statusDotOffline"
        : "statusDot statusDotUnknown";
  return <span className={cls} />;
}

export default function AgentCards({ agents, onRefresh, refreshing, activeAgent }) {
  return (
    <div className="agentHeader">
      <div className="agentHeaderTop">
        <div className="agentHeaderTitle">Planner A2A Agent Cards</div>
        <div className="agentHeaderActions" />
      </div>

      <div className="agentCardsRow">
        {agents.map((a) => {
          const running = a.id === activeAgent;
          return (
            <div
              className={`agentCard${running ? " agentCardRunning" : ""}`}
              key={a.id}
            >
              <div className="agentCardTop">
                <div className="agentCardName">
                  <StatusDot status={a.status} running={running} />
                  <span>{a.name}</span>
                </div>
                {running && (
                  <span className="agentRunningLabel">
                    {RUNNING_LABELS[a.id] ?? "Running…"}
                  </span>
                )}
              </div>
              <div className="agentCardDesc">{a.description}</div>
              {a.skills?.length ? (
                <div className="agentCardSkills">
                  {a.skills.slice(0, 4).map((s) => (
                    <span className="chip" key={s.id}>
                      {s.name}
                    </span>
                  ))}
                  {a.skills.length > 4 ? (
                    <span className="chip chipMuted">+{a.skills.length - 4}</span>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
