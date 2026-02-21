/**
 * Planner API helpers
 *
 * All calls require a `thread_id` so the backend LangGraph checkpointer
 * can persist and resume the correct graph state for HITL flows.
 */

/**
 * Send a new user message to the planner.
 * Returns: { reply, hitl, interrupted, error }
 *   hitl: { summary, tool, args } | null
 */
export async function chatWithPlanner(plannerApiBase, { message, thread_id, verbose = false }) {
  const baseUrl = plannerApiBase.replace(/\/$/, "");
  const resp = await fetch(`${baseUrl}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, thread_id, verbose }),
  });
  const payload = await resp.json().catch(async () => ({ raw: await resp.text() }));
  if (!resp.ok) {
    throw new Error(`Planner API error (${resp.status}): ${JSON.stringify(payload)}`);
  }
  if (payload?.error) {
    throw new Error(payload.error);
  }
  return payload; // { reply, hitl, interrupted }
}

/**
 * Resume a LangGraph graph that is paused at an interrupt().
 * `approved` — true to execute the pending action, false to cancel.
 * Returns same shape as chatWithPlanner.
 */
export async function resumePlanner(plannerApiBase, { thread_id, approved }) {
  const baseUrl = plannerApiBase.replace(/\/$/, "");
  const resp = await fetch(`${baseUrl}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id, approved }),
  });
  const payload = await resp.json().catch(async () => ({ raw: await resp.text() }));
  if (!resp.ok) {
    throw new Error(`Resume API error (${resp.status}): ${JSON.stringify(payload)}`);
  }
  if (payload?.error) {
    throw new Error(payload.error);
  }
  return payload; // { reply, hitl, interrupted }
}
