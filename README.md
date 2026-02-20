# Planner A2A (Agent-to-Agent) + React Frontend

This repo contains:

- `Agent/`: Python A2A agents (FastAPI JSON-RPC) + the planner orchestrator (LangChain + Azure OpenAI).
- `Frontend/`: React (Vite) UI to chat with the planner and directly call each A2A agent.

## Backend (Python)

### 1) Start the A2A agent servers (+ optional planner API)

From the repo root:

```bash
python Agent/run_servers.py --with-planner
```

This starts:

- Planner API: `http://localhost:8000` (`POST /chat` or `POST /`)
- CalendarAgent: `http://localhost:8001` (A2A JSON-RPC `POST /`)
- TasksAgent: `http://localhost:8002` (A2A JSON-RPC `POST /`)
- ContextAgent: `http://localhost:8003` (A2A JSON-RPC `POST /`)

### 2) Azure OpenAI env vars (required for planner chat)

The planner orchestrator needs these env vars (see `Agent/config.py`):

- `INFERENCE_MODEL`
- `OPENAI_API_VERSION`
- `OPENAI_API_URL`
- `OPENAI_API_KEY`

If you only use the “Direct Agent Call” tabs in the UI, you can skip Azure setup.

## Frontend (React)

From the repo root:

```bash
cd Frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### Optional: configure API URLs

You can override defaults with a `Frontend/.env` file:

```bash
VITE_PLANNER_API_BASE=http://localhost:8000
```
