export async function checkPlannerHealth(plannerApiBase) {
  const baseUrl = plannerApiBase.replace(/\/$/, "");
  const resp = await fetch(`${baseUrl}/health`);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Planner health failed (${resp.status}): ${text}`);
  }
  return await resp.json();
}

