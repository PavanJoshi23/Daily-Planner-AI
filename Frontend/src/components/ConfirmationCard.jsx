import React, { useState } from "react";
import { resumePlanner } from "../api/planner.js";
import { CONFIG } from "../config.js";

/**
 * ConfirmationCard
 *
 * Rendered inline in the chat thread when the agent is paused at a
 * LangGraph interrupt() inside a write tool.
 *
 * Props:
 *   hitl       { summary, tool, args }
 *   thread_id  string — LangGraph thread to resume
 *   onOutcome  (outcomePayload) => void — called with the /resume response
 */
export default function ConfirmationCard({ hitl, thread_id, onOutcome }) {
    const [status, setStatus] = useState("pending"); // "pending" | "loading" | "done"
    const [outcomeText, setOutcomeText] = useState("");

    async function handleDecision(approved) {
        setStatus("loading");
        try {
            const result = await resumePlanner(CONFIG.plannerApiBase, { thread_id, approved });
            const msg = approved
                ? `✅ Action executed. ${result.reply || ""}`
                : `🚫 Action cancelled. No changes were made.`;
            setOutcomeText(msg.trim());
            setStatus("done");
            onOutcome?.(result);
        } catch (err) {
            const msg = `❌ Resume failed: ${err.message}`;
            setOutcomeText(msg);
            setStatus("done");
            onOutcome?.({ reply: msg, hitl: null, interrupted: false });
        }
    }

    if (status === "done") {
        return (
            <div className="hitlCard hitlCardDone">
                <span className="hitlDoneText">{outcomeText}</span>
            </div>
        );
    }

    return (
        <div className="hitlCard">
            <div className="hitlHeader">
                <span className="hitlBell">🔔</span>
                <span className="hitlTitle">Action Awaiting Approval</span>
                <span className="hitlBadge">LangGraph interrupt()</span>
            </div>

            <div className="hitlSummary">{hitl.summary}</div>

            <div className="hitlMeta">
                <span className="hitlMetaLabel">Tool:</span>
                <code className="hitlMetaValue">{hitl.tool}</code>
                <span className="hitlMetaLabel" style={{ marginLeft: "1rem" }}>Args:</span>
                <code className="hitlMetaValue">{JSON.stringify(hitl.args)}</code>
            </div>

            <div className="hitlActions">
                <button
                    className="hitlBtn hitlBtnApprove"
                    onClick={() => handleDecision(true)}
                    disabled={status === "loading"}
                    type="button"
                >
                    {status === "loading" ? "⏳ Resuming…" : "✅ Approve"}
                </button>
                <button
                    className="hitlBtn hitlBtnReject"
                    onClick={() => handleDecision(false)}
                    disabled={status === "loading"}
                    type="button"
                >
                    ❌ Reject
                </button>
            </div>
        </div>
    );
}
