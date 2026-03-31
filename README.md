# AI DevOps Platform

An autonomous multi-agent DevOps orchestration platform powered by Claude AI. Four specialized agents — Code Reviewer, Test Runner, Log Monitor, Cloud Monitor — work together under a central orchestrator with persistent memory, real-time WebSocket updates, and a production dashboard.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│               Dashboard (React + Vite)              │
│  Repos · Services · 4 Agent Cards · Central Manager │
│                    · System Memory                  │
└──────────────────────┬──────────────────────────────┘
                       │ REST + WebSocket
┌──────────────────────▼──────────────────────────────┐
│              Backend (FastAPI + Orchestrator)        │
│  Task Queue · Agent Routing · Approval Gates        │
│  Memory System · SQLite Persistence                 │
├──────────┬──────────┬───────────┬───────────────────┤
│ Code     │ Test     │ Log       │ Cloud             │
│ Reviewer │ Runner   │ Monitor   │ Monitor           │
│ (Claude) │ (Claude) │ (Claude)  │ (Claude)          │
└──────────┴──────────┴───────────┴───────────────────┘
                       │ Docker API
┌──────────────────────▼──────────────────────────────┐
│          Worker Containers (per task)                │
│  gh · gcloud · git · kubectl · python · node        │
└─────────────────────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
    GitHub API     GCP APIs      Docker API
```

## Features

### Four Specialized Agents (each with 3 tabs)

| Agent | Report Tab | Plan Tab | Command Tab |
|-------|-----------|----------|-------------|
| **🔍 Code Reviewer** | Open PRs, issues, CI status, code coverage | Clone → analyze → fix → test → PR | "Review all PRs on my-repo" |
| **🧪 Test Runner** | Build status, test counts, failures, coverage | Clone → install → test → report | "Run pytest and show coverage" |
| **📊 Log Monitor** | Error counts, top errors, error rate, alerts | Fetch → filter → pattern → RCA | "Analyze error logs from last 6h" |
| **☁️ Cloud Monitor** | Services, CPU, memory, cost, uptime | List → check health → metrics | "Check GKE pod memory usage" |

### Central Manager
- All actions across all agents in one view
- Filter: All / Completed / Pending / Todo
- Approve/reject pending actions inline
- Tracks task_id linkage for drill-down

### System Memory (persistent, self-updating)
- **Repository State**: branch, tests, last deploy, health per repo
- **Services**: running services, metrics, regions
- **Infrastructure**: GCP project, clusters, containers
- **Credentials**: Connection status for GitHub, GCP, Claude, Docker
- **Findings**: Issues discovered by agents (severity-tagged)
- **Agent States**: Each agent's status, last activity, current task
- **Activity Log**: Timestamped log of everything that happens
- Updates automatically on every agent action

### Dashboard
- Left sidebar: Repos (from GitHub) + Services (from GCP) + Recent Tasks
- Center: 4 agent cards in 2×2 grid with live stats
- Right panel: Toggle between Central Manager and System Memory
- Global command bar for orchestrator-level commands
- Real-time WebSocket event feed
- Task detail modal with step-by-step execution view
- Approval gates with approve/reject buttons

## Quick Start

### 1. Prerequisites
- Docker & Docker Compose
- GitHub Personal Access Token
- Claude API access (Vertex AI or direct Anthropic API)

### 2. Setup

```bash
# Clone and configure
cd ai-devops-platform
cp .env.example .env
# Edit .env with your tokens

# If using GCP/Vertex AI, place your service account key:
cp your-key.json gcp-key.json
```

### 3. Run

```bash
# Build everything (including the worker image)
docker compose --profile build-only build

# Start the platform
docker compose up -d

# Open dashboard
open http://localhost:3000
```

### 4. Local Development (no Docker)

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## API Reference

### Dashboard
- `GET /api/dashboard` — Full state (repos, services, agents, actions, memory, stats)

### Tasks
- `POST /api/tasks` — Create task `{command, agent_type?, repo_id?, context?}`
- `GET /api/tasks` — List tasks `?limit=20&agent_type=code_reviewer`
- `GET /api/tasks/{id}` — Task detail with steps
- `POST /api/tasks/{id}/approve` — Approve/reject step `{step_id, approved, comment?}`
- `POST /api/tasks/{id}/cancel` — Cancel task
- `GET /api/tasks/{id}/report` — Download markdown report
- `GET /api/tasks/{id}/report/preview` — Preview report JSON

### Agents
- `GET /api/agents` — List all agents with status
- `GET /api/agents/{type}/report?repo_id=` — Agent report data
- `GET /api/agents/{type}/plan?repo_id=` — Agent execution plan
- `POST /api/agents/{type}/plan` — Generate plan `{command, repo_id?}`

### Actions (Central Manager)
- `GET /api/actions?limit=50&type=pending&agent_type=code_reviewer`
- `POST /api/actions/{id}/complete` — Mark complete
- `POST /api/actions/{id}/cancel` — Cancel action

### Memory
- `GET /api/memory` — Full memory state
- `GET /api/memory/logs?limit=30` — Activity log
- `GET /api/memory/findings?limit=20` — Agent findings
- `GET /api/memory/stats` — Aggregated stats

### WebSocket
- `ws://localhost:8000/ws` — Real-time events
  - Send: `{type: "create_task", command: "...", agent_type: "...", repo_id: "..."}`
  - Send: `{type: "approve", task_id: "...", step_id: "...", approved: true}`
  - Send: `{type: "get_dashboard"}`
  - Receive: `{event_type, task_id, agent_type, data, timestamp}`

### Health
- `GET /health` — System health check

## Project Structure

```
ai-devops-platform/
├── backend/
│   ├── agents/
│   │   ├── __init__.py          # Agent registry
│   │   ├── base.py              # Base agent class (LLM brain)
│   │   ├── code_reviewer.py     # Code review agent
│   │   ├── test_runner.py       # Test runner agent
│   │   ├── log_monitor.py       # Log monitoring agent
│   │   └── cloud_monitor.py     # Cloud infrastructure agent
│   ├── integrations/
│   │   ├── github_client.py     # GitHub API client
│   │   └── gcp_client.py        # GCP integration
│   ├── main.py                  # FastAPI app + all endpoints
│   ├── orchestrator.py          # Central orchestrator
│   ├── models.py                # Pydantic data models
│   ├── config.py                # Configuration
│   ├── database.py              # SQLite persistence
│   ├── memory.py                # System memory manager
│   ├── executor.py              # Docker container executor
│   ├── approval.py              # Approval gate logic
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── dashboard.jsx            # Complete React dashboard
│   ├── main.jsx                 # Entry point
│   ├── index.html               # Vite HTML
│   ├── vite.config.js           # Vite with API proxy
│   ├── package.json
│   └── Dockerfile
├── worker/
│   ├── Dockerfile               # Full toolchain (gh, gcloud, kubectl, etc.)
│   └── entrypoint.sh            # Auth setup script
├── docker-compose.yml
├── .env.example
└── README.md
```

## How It Works

1. **User sends command** via dashboard or API (e.g., "Review PRs on my-repo")
2. **Orchestrator routes** to the right agent based on keywords
3. **Agent brain** (Claude) analyzes the goal and decides the first command
4. **Worker container** executes the command (isolated Docker container per task)
5. **Result fed back** to agent brain → it decides the next command
6. **Approval gate** triggers for high-risk operations (push, deploy, delete)
7. **Memory updates** on every action — repo state, findings, agent status
8. **Dashboard reflects** everything in real-time via WebSocket
9. **Report generated** when agent completes — downloadable as markdown
10. **Central Manager** tracks all actions across all agents
