# TruJark — Recent Changes

This document captures features, fixes, and operational changes added on top
of the system described in `TruJark_System_Overview.pdf`. Update this file
whenever a notable change ships.

---

## 2026-04-10 — Complete user tracking in the admin panel

### Highlights

- Click any user row in the admin panel to drill into their full activity:
  per-agent usage, per-tool usage (with MCP vs CLI split), connected
  services, recent conversations, recent tool calls, and a 30-day cost
  trend sparkline.
- New **Platform Activity** card at the top of the panel with DAU / WAU /
  MAU, top agents, top tools, and a 7-day cost sparkline so you can see
  at a glance how the app is being used.
- The user list now shows **login count** and **primary agent**, plus
  every existing field. The first user persistence change tracked
  `last_login_at` but didn't count logins — fixed.

### Backend additions

- [`backend/app/models/database.py`](../backend/app/models/database.py) —
  `User.login_count` (int, default 0).
- [`backend/app/main.py`](../backend/app/main.py) — startup migration adds
  the column via `ALTER TABLE … ADD COLUMN IF NOT EXISTS`.
- [`backend/app/api/auth.py`](../backend/app/api/auth.py) —
  `upsert_user_on_login` now `+= 1`s `login_count` on every fresh login
  (and seeds it to `1` on creation).
- [`backend/app/api/routes.py`](../backend/app/api/routes.py):
  - `GET /admin/users` enriched with `login_count` and `primary_agent`
    (computed from the agent that produced the most messages for each
    user). Single SQL query, no N+1.
  - **New** `GET /admin/users/{id}` — drill-down on one user. Returns:
    - `user` — full row including `login_count`, `auth0_sub`, etc.
    - `totals` — `total_cost_usd`, `tool_calls_total`, `tool_calls_cli`,
      `tool_calls_mcp`, `plan_count`, `conversation_cost_usd`,
      `plan_cost_usd`.
    - `per_agent` — list of `{ agent, message_count, cost_usd }`
      sorted by message count desc, computed from `messages` joined to
      that user's conversations.
    - `per_tool` — list of `{ tool, agent, call_count, avg_duration_ms,
      kind: "cli" | "mcp" }` from the audit log, with `kind` derived
      from whether the tool name is `run_shell` / `run_command`. Top 50.
    - `services` — every `cloud_credentials` row for the user (GCP /
      GitHub PAT / Zoho), with `is_active`, `connected_at`,
      `last_used_at`.
    - `github_app_installations` — installation rows linked to the user
      via `auth0_sub`.
    - `recent_conversations` — last 20 conversations with title,
      message count, cost.
    - `recent_audit_log` — last 30 tool calls with truncated input
      preview.
    - `cost_trend_30d` — daily buckets of `sum(message.cost_usd)` for
      the last 30 days.
  - **New** `GET /admin/activity` — platform-wide stats. Returns:
    - `dau`, `wau`, `mau` — distinct active users in the last 24h / 7d /
      30d, computed as `max(message_creators_in_window,
      logged_in_in_window)` to avoid an expensive UNION DISTINCT.
    - `total_users`, `new_users_30d`.
    - `top_agents` — top 5 agents by message count, with cost.
    - `top_tools` — top 10 tools from the audit log, with `kind` split.
    - `cost_trend_7d` — daily cost buckets for the last 7 days.

### Frontend additions

- [`frontend/src/components/dashboard/AdminPanel.tsx`](../frontend/src/components/dashboard/AdminPanel.tsx)
  rewritten with:
  - **`PlatformActivityCard`** — header card above the users table showing
    DAU/WAU/MAU, the 7-day cost total with a small SVG `Sparkline`, top
    agents (call count + cost), and top tools (call count + MCP/CLI icon).
  - **`UserDetailModal`** — full-screen modal opened by clicking any user
    row. Loads `GET /admin/users/{id}` and renders every field via
    `UserDetailContent`: header (avatar + login count + role + joined),
    a 4-card stat row (total spent, tool calls split, plans, last active),
    a 30-day sparkline, agent usage list, tool usage list, connected
    services, recent conversations, and the recent tool-call log.
  - The users table gained **Logins** and **Primary Agent** columns, and
    the whole row is now `cursor-pointer` — clicking opens the drill-down.
    The Role `<select>` stops propagation so changing a role doesn't
    accidentally open the modal.
  - `Sparkline` is a tiny inline SVG component (no chart library
    dependency) that renders a normalized line over an array of numbers.

### How an admin uses it

1. Open the Admin tab in the sidebar.
2. The **Platform Activity** card immediately shows DAU/WAU/MAU and the
   top agents/tools — that's the "is anyone using this and what for?"
   answer.
3. The **users table** lists everyone sorted by total cost. Each row
   shows logins, primary agent, conversation count, message count, and
   total cost.
4. **Click any row** → modal opens with the full per-user breakdown:
   - Cost over time (sparkline) — are they ramping up or trailing off?
   - Per-agent usage — is this user a Cloud Debugger heavy hitter or a
     Codebase Analyzer power user?
   - Per-tool usage — how often do they fall back to `run_shell` vs
     specialized MCP tools? (Useful for tuning agent prompts.)
   - Connected services — did they hook up GCP? Install the GitHub App?
   - Recent conversations & tool calls — what did they actually do
     last session?

### Caveats

- **DAU/WAU/MAU is approximate.** It's the max of (users with messages
  in window) and (users who logged in in window), not a true distinct
  union. The two sets overlap significantly so the numbers are within a
  few percent of the real figure, but if you need exact distinct counts
  push the query into a `UNION DISTINCT` (slower) or pre-aggregate into
  a daily activity table.
- **`primary_agent` is computed by message count**, not weighted by
  cost. A user who runs many cheap codebase scans will show
  Codebase Analyzer as their primary even if they spent more on a few
  expensive Cloud Debugger sessions.
- **The drill-down endpoint runs ~8 queries per request.** Fine for an
  occasional admin click, would need caching if you put it on a public
  URL or polled it from a dashboard.

---

## 2026-04-10 — Auto MCP/CLI tool selection for all agents

### Highlights

- Every agent now has a **shared `run_shell` CLI fallback** alongside its
  specialized MCP tools. Claude picks naturally — same pattern as Claude
  Code's `Bash` tool sitting alongside `Read`, `Edit`, and `Grep`.
- The API container now ships with **`gh`, `gcloud`, `kubectl`, `git`,
  `jq`** so CLI fallback actually works in production, not just locally.
- The shell sandbox now **injects the requesting user's GitHub PAT and GCP
  access token** so commands run as the user, not as the backend service
  account.
- Per-session **persistent working directory**: `cd subdir` in one tool
  call affects the next call's `ls` within the same agent session.

### Why this approach (vs the `feature/cli` branch)

The `feature/cli` branch took an all-CLI approach: a Docker-in-Docker
sandbox per task, gh/gcloud/kubectl as the only tools, no MCPs. That
works on a host with the Docker socket mounted but doesn't fit Cloud Run
(no DinD), and it discards all the typed MCP wrappers we already have
for AWS / GCP / GitHub / Datadog / Sentry / etc.

The approach implemented here keeps **both** paths and lets the agent
pick per-call:

1. **Specialized MCP tools** (`query_gcp_logs`, `list_compute_instances`,
   `check_ecs_service`, …) — fast, structured, deterministic.
2. **`run_shell` fallback** — open-ended `gh pr`, multi-step `gcloud`
   queries, ad-hoc `git` workflows. Sandboxed via subprocess with an
   allowlist, timeout, and output truncation.

Claude makes the choice based on (a) the specialized tool descriptions
and (b) a tool-selection guidance block automatically prepended to every
agent's system prompt. No router code, no manual dispatch.

### Files

- [`infra/docker/Dockerfile.api`](../infra/docker/Dockerfile.api) — adds
  `gh`, `gcloud`, `kubectl`, `git`, `jq`, `unzip` to the API container so
  agents have them at runtime in Cloud Run. Image grows by ~600 MB; the
  trade-off is that `run_shell` actually works in prod.
- [`backend/app/mcp/terminal.py`](../backend/app/mcp/terminal.py):
  - `gh`, `gsutil`, `python3`, `jq`, `pwd` added to `ALLOWED_COMMANDS`.
  - `TerminalMCPClient.__init__` now accepts `github_token`,
    `gcp_project_id`, and `session_id`.
  - `execute()` injects `GH_TOKEN` / `GITHUB_TOKEN` for `gh` and `git`
    commands, `CLOUDSDK_AUTH_ACCESS_TOKEN` for `gcloud` / `gsutil`, and
    `CLOUDSDK_CORE_PROJECT` when set. Returns `cwd` in the result dict so
    agents can see the effective working directory.
  - New `_resolve_session_cwd()` and `_track_cd()` give the client a
    persistent working directory keyed by `session_id`. `cd subdir` in
    one call carries over to the next call's commands. Implemented by
    parsing `cd …` segments locally — never re-executes.
  - `TerminalMCPClient.reset_session(session_id)` drops a session's
    workdir state when a task ends.
- [`backend/app/agents/base.py`](../backend/app/agents/base.py):
  - New `RUN_SHELL_TOOL` schema constant — the shared CLI fallback.
  - New `TOOL_SELECTION_PROMPT` block — appended to every agent's system
    prompt via `BaseAgent.effective_system_prompt`. It tells the agent
    to prefer specialized tools when one fits, fall back to `run_shell`
    only when nothing specialized matches, and run one shell command at
    a time so it can read the output before deciding the next step.
  - `BaseAgent` adds `enable_cli: bool = True` (set False on a subclass
    to remove the fallback for that agent), an overridable `mcp_tools`
    property that subclasses now use for their specialized tools, and a
    `tools` property that composes `mcp_tools + RUN_SHELL_TOOL` (only
    injecting the latter if not already present, so legacy overrides
    keep working).
  - `BaseAgent._execute_tool` now handles `run_shell` natively. New
    `_run_shell()` helper instantiates a `TerminalMCPClient` with the
    requesting user's `gcp_access_token`, `github_token`, and
    `gcp_project_id` from the per-call user dict, and a session id of
    `f"{agent.name}:{user.sub}"`.
  - All three `messages.create` call sites now use
    `effective_system_prompt` so the tool-selection guidance is applied
    in the streaming agent loop too.
- All specialized agents migrated to the new pattern:
  - [`backend/app/agents/cloud_debugger.py`](../backend/app/agents/cloud_debugger.py),
    [`codebase_analyzer.py`](../backend/app/agents/codebase_analyzer.py),
    [`commit_analyst.py`](../backend/app/agents/commit_analyst.py),
    [`deployment_doctor.py`](../backend/app/agents/deployment_doctor.py),
    [`engineering_metrics.py`](../backend/app/agents/engineering_metrics.py),
    [`performance.py`](../backend/app/agents/performance.py).
  - Each agent's `tools` property was renamed to `mcp_tools` so the
    base class can compose it with `run_shell`.
  - Each `_execute_tool` now chains to `super()._execute_tool(tool_name,
    tool_input)` for unknown tools instead of returning
    `{"error": "Unknown tool: …"}`. That's how `run_shell` reaches the
    base-class dispatch.
  - `cloud_debugger` keeps its existing `run_command` tool name as a
    legacy alias that now delegates to `_run_shell()`, so any pre-stored
    plans still work.

### How an agent uses it (worked example)

System prompt sent to Claude is the agent's prompt followed by:

```
## Tool selection

You have two kinds of tools available:

1. **Specialized tools** (named like `query_gcp_logs`, `list_repos`, …) —
   structured operations with typed inputs and JSON outputs. …
2. **`run_shell`** — a general-purpose CLI fallback. Use it for ad-hoc
   commands when no specialized tool covers the operation: `gh pr` flows,
   complex `gcloud` queries, `kubectl` exploration, …
```

Tools list passed to the API call is the agent's `mcp_tools` list with
`run_shell` appended. Claude picks per turn:

- "List enabled APIs in `acme-prod`" → calls `list_enabled_apis` (MCP).
- "Find the PR that introduced this regression" → calls `run_shell` with
  `gh pr list --state merged --search 'in:title regression' --limit 5`.
- "What's the current Cloud Run revision serving traffic?" → calls
  `run_shell` with `gcloud run services describe copilot-api …`.

### Constraints and trade-offs

- **`run_shell` is not multi-tenant isolated.** Commands run as the
  Cloud Run service user inside the API container, with hard limits
  (timeout, output size, allowlist) but no per-user sandbox. The user's
  authentication tokens are injected per call, so authorization is
  scoped to the requesting user, but a malicious agent prompt could
  still consume CPU/memory on the shared instance. For multi-tenant
  isolation we'd need a separate worker pool (Cloud Run Job per task or
  an external sandbox like E2B / Modal). Documented here so future
  scaling decisions are informed.
- **Per-session workdir is process-local** (a class-level dict on
  `TerminalMCPClient`). On a multi-instance Cloud Run rollout, two
  consecutive tool calls could land on different instances and lose the
  workdir state. Acceptable for now since Cloud Run sticky sessions are
  off by default; if it becomes a problem, push the workdir map into
  Redis (the `RedisService` already exists in `app/services/redis_service.py`).
- **Image size grows by ~600 MB** because `gcloud` is large. If this
  becomes a cold-start problem, we can split the API into a thin
  gateway + a worker image that has the CLIs.

---

## 2026-04-10 — GitHub App public readiness, admin panel, user persistence

### Highlights

- **Admin panel** in the dashboard with per-user activity and AI cost
  aggregates.
- **Users are now persisted to the database on login** (previously the JWT
  was the only record of who had signed in).
- **GitHub App is hardened for public installation** — installations are
  now linked to TruJark accounts via signed state tokens, the listing
  endpoint is scoped to the requesting user, and the webhook handler
  refuses unsigned requests outside development.

---

### 1. User persistence on login

Before this change, signing in only minted a JWT — no `users` row was ever
written, so cost and activity data couldn't be attributed to a person.

**Backend**

- [`backend/app/models/database.py`](../backend/app/models/database.py) — `User`
  model gained `login`, `avatar_url`, `last_login_at` (all nullable). The
  existing `auth0_sub` column is now indexed and used as the lookup key.
- [`backend/app/main.py`](../backend/app/main.py) — startup migration runs
  `ALTER TABLE … ADD COLUMN IF NOT EXISTS …` and `CREATE INDEX IF NOT EXISTS`
  for the new columns so existing production databases pick them up
  automatically on the next deploy.
- [`backend/app/api/auth.py`](../backend/app/api/auth.py):
  - `create_jwt_token(user_data, github_access_token, db_id, role)` now
    accepts and embeds `db_id` (the persisted `User.id` UUID) and `role`
    in the JWT. Routes that needed `user.get("db_id")` finally have it.
  - New `upsert_user_on_login(user_data, db)` — creates or updates the
    `User` row keyed by `auth0_sub` (= JWT `sub`, which is the GitHub user
    ID string for GitHub sign-ins or `google_<id>` for GCP sign-ins).
  - **The very first user to sign up is automatically promoted to admin**
    so the admin panel is reachable without manual DB poking.
  - `last_login_at` is stored as a naive UTC datetime to match the rest
    of the schema (the column is `TIMESTAMP WITHOUT TIME ZONE`).
- [`backend/app/api/github_oauth.py`](../backend/app/api/github_oauth.py) —
  both the GitHub OAuth callback and the GCP sign-in callback now call
  `upsert_user_on_login` before issuing the JWT, and pass `db_id` + `role`
  into `create_jwt_token`. `/auth/me` now also returns `db_id`.

**Migration notes**

- Cold start applies the schema changes automatically; no manual `psql`
  steps required for new columns.
- Conversations created **before** this change have random `user_id`
  UUIDs (because `db_id` was missing from the JWT). Their cost stays
  visible only in `/admin/stats`. Fresh sessions after deploy attribute
  cost correctly.
- If multiple users existed before this change and you want to promote
  someone to admin manually:
  ```sql
  UPDATE users SET role = 'admin' WHERE email = 'you@example.com';
  ```

---

### 2. Admin panel

A new dashboard tab — visible only when `role === "admin"` — that lists
every user with usage and cost aggregates and inline role management.

**Backend endpoints** in [`backend/app/api/routes.py`](../backend/app/api/routes.py):

- `GET /admin/users` — gated by `require_role(UserRole.ADMIN)`. Returns:
  ```json
  {
    "total_users": 12,
    "total_cost_usd": 4.8732,
    "users": [
      {
        "id": "uuid",
        "email": "...",
        "name": "...",
        "login": "github-handle",
        "avatar_url": "...",
        "role": "admin|engineer|viewer",
        "is_active": true,
        "created_at": "...",
        "last_login_at": "...",
        "last_active_at": "...",
        "conversation_count": 14,
        "message_count": 207,
        "plan_count": 3,
        "installation_count": 1,
        "total_cost_usd": 1.4203
      }
    ]
  }
  ```
  Implemented as a single SQL query joining `users` ↔ `conversations` ↔
  `messages`, with outer joins to `plans` and `github_app_installations`
  via `User.auth0_sub` (since those tables key on the string sub instead
  of the user UUID). `total_cost_usd` per user = `sum(Conversation.total_cost_usd)
  + sum(Plan.total_cost_usd)`. Sorted by cost descending.
- `PATCH /admin/users/{id}/role` — change a user's role to `admin`,
  `engineer`, or `viewer`. Includes a self-demotion guard so an admin
  cannot lock themselves out.

**Frontend** in [`frontend/src/components/dashboard/AdminPanel.tsx`](../frontend/src/components/dashboard/AdminPanel.tsx):

- Four summary cards: Total Users, Total Cost, Total Messages, Avg Cost / User.
- Search box filters by name, email, or GitHub login.
- Sortable user table with avatar, role dropdown (live PATCH on change),
  conversation count, message count, plan count, install count, total
  cost (USD), and last-active relative time.
- Refresh button, 403 detection, empty/error states.

**Wiring**

- [`frontend/src/components/dashboard/Sidebar.tsx`](../frontend/src/components/dashboard/Sidebar.tsx) —
  new `"admin"` tab type. The Sidebar accepts an `isAdmin` prop and only
  renders the Admin nav item (shield-check icon, between "Audit Log" and
  the footer) when true.
- [`frontend/src/components/dashboard/Dashboard.tsx`](../frontend/src/components/dashboard/Dashboard.tsx) —
  computes `isAdmin = user.role === "admin"`, passes it to Sidebar, and
  conditionally renders `<AdminPanel />`.

**How an admin reaches it**

1. Sign in (or sign out and back in if you had an old JWT minted before
   this change — JWTs do not auto-refresh).
2. The first signup is auto-admin; otherwise an existing admin promotes
   you, or run the SQL above.
3. The Admin tab appears in the left sidebar.

---

### 3. GitHub App — public installation readiness

The app was previously safe to use only for the owning account because:

- Installations had no link back to the TruJark user that initiated them.
- `GET /github-app/installations` returned every installation across every
  tenant.
- The webhook endpoint silently accepted unsigned requests if the secret
  was not configured.

These have all been fixed in [`backend/app/api/github_app.py`](../backend/app/api/github_app.py).

**State-token-based user linking**

- New helpers `_create_install_state_token(user_sub)` and
  `_decode_install_state_token(token)` produce/verify a short-lived
  (30 min) JWT signed with `jwt_secret`, carrying
  `purpose: "github_app_install"` and the user's `sub`.
- `GET /github-app/install` now requires authentication, mints a state
  token, and appends `?state=…` to the GitHub installation URL.
- `GET /github-app/setup` now reads the `state` query parameter, decodes
  it, and stamps `user_id` on the `GitHubAppInstallation` row. Missing
  or invalid state is allowed (e.g. installs from the GitHub Marketplace),
  but those installations stay unclaimed until a user manually links
  them. Already-claimed installations are never re-linked, preventing
  hijack via a freshly minted state token.

**Database**

- [`backend/app/models/database.py`](../backend/app/models/database.py) —
  `GitHubAppInstallation` gained a nullable, indexed `user_id` column
  (string, matches the JWT `sub`).
- [`backend/app/main.py`](../backend/app/main.py) — startup migration adds
  the column and index in production via `ALTER TABLE … ADD COLUMN IF NOT EXISTS`.

**Tenant scoping**

- `GET /github-app/installations` now requires authentication and
  filters to `user_id == current user`. Admins still see everything.

**Webhook hardening**

- `_verify_webhook_signature` now **hard-fails** outside `environment ==
  "development"` if `GITHUB_APP_WEBHOOK_SECRET` is not configured. In dev
  it still logs a warning and accepts unsigned requests, which keeps
  local testing easy.

**Frontend updates**

- [`frontend/src/components/dashboard/SettingsPanel.tsx`](../frontend/src/components/dashboard/SettingsPanel.tsx) —
  both `/github-app/install` and `/github-app/installations` calls now
  send the `Authorization` header.
- [`frontend/src/app/page.tsx`](../frontend/src/app/page.tsx) — the
  install button on the login page now redirects unauthenticated users
  through GitHub sign-in first, then to install, since installation must
  be linked to a TruJark account.

---

### 4. Operational checklist for going public on GitHub

The code changes above enable public installation, but a few one-time
GitHub-side and Cloud Run-side actions are still required:

1. **Make the GitHub App public.** This is a setting on
   `Settings → Developer settings → GitHub Apps → Truspark` — scroll to
   the bottom and click *Make public*. No code change can flip this.
2. **Set `GH_APP_WEBHOOK_SECRET`** in GitHub Actions secrets *and* paste
   the **same** value into `GitHub App settings → General → Webhook
   secret`. Both stores must agree byte-for-byte. The deploy workflow at
   [`.github/workflows/deploy-cloudrun.yml`](../.github/workflows/deploy-cloudrun.yml)
   maps `GH_APP_WEBHOOK_SECRET` to the `GITHUB_APP_WEBHOOK_SECRET`
   environment variable consumed by `Settings.github_app_webhook_secret`.
3. **Re-run the deploy workflow** so Cloud Run picks up any updated
   secret values:
   ```bash
   gh workflow run deploy-cloudrun.yml
   ```
4. **Setup URL in GitHub App settings** must be
   `https://<your-backend>/api/v1/github-app/setup`, with *Redirect on
   update* enabled so the `state` token round-trips on updates as well as
   first installs.
5. **Webhook URL** must be
   `https://<your-backend>/api/v1/github-app/webhook`.
6. **Recommended permission set** (minimum-necessary, scrutinized less by
   GitHub reviewers):
   - Repository: Metadata (mandatory), Contents (read), Pull requests
     (read), Issues (read), Actions (read), Checks (read), Deployments
     (read), Commit statuses (read).
   - Organization: Members (read).
   - Account/user: none — TruJark uses a separate GitHub OAuth flow for
     user-level scopes.
7. **Webhook events to subscribe to** (matches handlers in
   [`backend/app/api/github_app.py`](../backend/app/api/github_app.py)):
   `meta`, `push`, `pull_request`, `pull_request_review`,
   `pull_request_review_comment`, `issues`, `issue_comment`,
   `workflow_run`, `workflow_job`, `check_run`, `check_suite`,
   `deployment`, `deployment_status`, `release`, `create`, `delete`,
   `status`, `repository`, `member`.

---

### 5. Database schema deltas

Applied automatically on backend startup via
[`backend/app/main.py`](../backend/app/main.py):

```sql
ALTER TABLE github_app_installations
  ADD COLUMN IF NOT EXISTS user_id VARCHAR(255);
CREATE INDEX IF NOT EXISTS ix_github_app_installations_user_id
  ON github_app_installations (user_id);

ALTER TABLE users ADD COLUMN IF NOT EXISTS login VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500);
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS ix_users_auth0_sub ON users (auth0_sub);
CREATE INDEX IF NOT EXISTS ix_users_login ON users (login);
```

These migrations are idempotent and safe to re-run.

---

### 6. Bug fixes shipped alongside

- **GCP/GitHub login crash on first attempt.** `last_login_at` was being
  set to a `datetime.now(UTC)` (offset-aware), but the column is
  `TIMESTAMP WITHOUT TIME ZONE`, so asyncpg rejected the INSERT with
  `can't subtract offset-naive and offset-aware datetimes`. Fixed in
  [`backend/app/api/auth.py`](../backend/app/api/auth.py) by stripping
  `tzinfo` before persisting.

---

### Commits

- `e8e3588` — Add admin panel and harden GitHub App for public installs
- `e78e375` — Fix login crash: store naive UTC for users.last_login_at
