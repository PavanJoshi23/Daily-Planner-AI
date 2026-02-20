export async function chatWithPlanner(plannerApiBase, { message, verbose = false }) {
  const baseUrl = plannerApiBase.replace(/\/$/, "");
  const resp = await fetch(`${baseUrl}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, verbose })
  });
  const payload = await resp.json().catch(async () => ({ raw: await resp.text() }));
  if (!resp.ok) {
    throw new Error(`Planner API error (${resp.status}): ${JSON.stringify(payload)}`);
  }
  if (payload?.error) {
    throw new Error(payload.error);
  }
  return payload?.reply || "";
}

