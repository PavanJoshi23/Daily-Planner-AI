import React from "react";

function StatusDot({ status }) {
  const cls =
    status === "online"
      ? "statusDot statusDotOnline"
      : status === "offline"
        ? "statusDot statusDotOffline"
        : "statusDot statusDotUnknown";
  return <span className={cls} />;
}

export default function AgentCards({ agents, onRefresh, refreshing }) {
  return (
    <div className="agentHeader">
      <div className="agentHeaderTop">
        <div className="agentHeaderTitle">Planner A2A Agent Cards</div>
        <div className="agentHeaderActions">
          {/* <button className="ghostBtn" type="button" onClick={onRefresh} disabled={refreshing}>
            {refreshing ? "Refreshing…" : "Refresh agents"}
          </button> */}
        </div>
      </div>

      <div className="agentCardsRow">
        {agents.map((a) => (
          <div className="agentCard" key={a.id}>
            <div className="agentCardTop">
              <div className="agentCardName">
                <StatusDot status={a.status} />
                <span>{a.name}</span>
              </div>
              {/* <div className="agentCardUrl">
                <code>{a.url}</code>
              </div> */}
            </div>
            <div className="agentCardDesc">{a.description}</div>
            {a.skills?.length ? (
              <div className="agentCardSkills">
                {a.skills.slice(0, 4).map((s) => (
                  <span className="chip" key={s.id}>
                    {s.name}
                  </span>
                ))}
                {a.skills.length > 4 ? <span className="chip chipMuted">+{a.skills.length - 4}</span> : null}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

