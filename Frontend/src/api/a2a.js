function newId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return String(Date.now()) + "-" + String(Math.random()).slice(2);
}

export async function fetchAgentCard(agentBaseUrl) {
  const resp = await fetch(`${agentBaseUrl.replace(/\/$/, "")}/.well-known/agent.json`);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Agent card fetch failed (${resp.status}): ${text}`);
  }
  return await resp.json();
}

export async function sendTask(agentBaseUrl, { sessionId, messageText, metadata = {} }) {
  const baseUrl = agentBaseUrl.replace(/\/$/, "");

  const rpcRequest = {
    jsonrpc: "2.0",
    id: newId(),
    method: "tasks/send",
    params: {
      id: newId(),
      sessionId: sessionId || newId(),
      message: {
        role: "user",
        parts: [{ type: "text", text: messageText }]
      },
      metadata
    }
  };

  const resp = await fetch(baseUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(rpcRequest)
  });
  const payload = await resp.json().catch(async () => ({ raw: await resp.text() }));
  if (!resp.ok) {
    throw new Error(`Agent call failed (${resp.status}): ${JSON.stringify(payload)}`);
  }
  if (payload?.error) {
    throw new Error(`A2A error ${payload.error.code}: ${payload.error.message}`);
  }
  return payload?.result;
}

export function extractFirstDataArtifact(task) {
  const artifacts = task?.artifacts || [];
  for (const a of artifacts) {
    const parts = a?.parts || [];
    for (const p of parts) {
      if (p?.type === "data") return p?.data;
    }
  }
  return null;
}

