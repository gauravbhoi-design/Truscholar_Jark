"""Base agent class using Claude Agent SDK patterns via Vertex AI."""

import os
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import anthropic
import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()


def _summarize_tool_input(tool_input: dict) -> dict:
    """Create a safe summary of tool input for display (truncate large values)."""
    summary = {}
    for k, v in tool_input.items():
        if isinstance(v, str) and len(v) > 100:
            summary[k] = v[:100] + "..."
        else:
            summary[k] = v
    return summary


# ─── Shared CLI fallback tool ──────────────────────────────────────────────
#
# Every agent gets this `run_shell` tool in addition to its specialized
# MCP tools. Claude picks naturally — same pattern as Claude Code's Bash
# tool sitting alongside Read/Edit/Grep. The system prompt prefix below
# tells the agent to prefer specialized tools when they fit.

RUN_SHELL_TOOL: dict = {
    "name": "run_shell",
    "description": (
        "Run a shell command (gh, gcloud, kubectl, git, jq, curl, etc.) when "
        "no specialized tool covers the operation. Use this for ad-hoc CLI "
        "tasks: complex `gcloud` queries, `gh pr` flows, multi-step git "
        "operations, exploring filesystem, etc. Commands run in a sandboxed "
        "subprocess with an allowlist, timeout, and output truncation. The "
        "session has a persistent working directory — `cd subdir` followed "
        "by `ls` runs `ls` inside `subdir`. Always prefer a specialized "
        "MCP tool when one exists; only fall back to run_shell when nothing "
        "specialized fits the request."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute. One command per call.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait for the command. Default 30, max 120.",
                "default": 30,
            },
            "cwd": {
                "type": "string",
                "description": "Optional working directory override for this single call. If omitted, uses the session's tracked workdir.",
            },
        },
        "required": ["command"],
    },
}


TOOL_SELECTION_PROMPT = """\
## Tool selection

You have two kinds of tools available:

1. **Specialized tools** (named like `query_gcp_logs`, `list_repos`,
   `check_ecs_service`, etc.) — structured operations with typed inputs
   and JSON outputs. They are deterministic, fast, and pre-validated.
   Use these whenever one fits the task at hand.

2. **`run_shell`** — a general-purpose CLI fallback. Use it for ad-hoc
   commands when no specialized tool covers the operation: `gh pr` flows,
   complex `gcloud` queries, `kubectl` exploration, multi-step `git`
   sequences, filesystem inspection, etc.

Rules:
- Prefer the specialized tool when one fits — it's faster and more reliable.
- Fall back to `run_shell` only when nothing specialized matches the need.
- Run one shell command per call, then read the output before deciding the
  next step. Don't chain unrelated operations with `&&` — make multiple calls.
- The session has a persistent working directory: `cd subdir` in one call
  affects the next call's `ls`.

## Output formatting

When displaying file or folder structures, ALWAYS render them as ASCII
trees inside a ```tree fenced code block using Unicode box-drawing
characters. Never output flat JSON file lists or plain comma-separated
paths to the user. Example:

```tree
project/
├── src/
│   ├── components/
│   │   ├── Header.tsx
│   │   └── Footer.tsx
│   └── utils/
│       └── helpers.ts
├── package.json
└── README.md
```
"""


def _create_client() -> anthropic.AsyncAnthropic:
    """Create the appropriate Anthropic client (Vertex AI or direct API)."""
    if settings.use_vertex_ai:
        # Set GCP credentials for Vertex AI
        if settings.gcp_credentials_path and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.gcp_credentials_path

        from anthropic import AsyncAnthropicVertex

        logger.info(
            "Using Vertex AI",
            project=settings.gcp_project_id,
            region=settings.vertex_region,
            model=settings.claude_model,
        )
        return AsyncAnthropicVertex(  # type: ignore[return-value]
            project_id=settings.gcp_project_id,
            region=settings.vertex_region,
        )
    else:
        return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


class BaseAgent(ABC):
    """Base class for all specialized agents in the DevOps Co-Pilot.

    Each agent is a Claude Agent SDK subagent with:
    - Its own system prompt and tools
    - Structured JSON output
    - Cost tracking via token usage
    - Hook support for safety gates
    - A shared `run_shell` CLI fallback alongside its specialized MCP tools

    Uses Claude Opus 4.6 via GCP Vertex AI by default.

    Subclasses should override `mcp_tools` (not `tools`) to declare their
    specialized MCP tools. The base class composes those with the shared
    `run_shell` tool unless `enable_cli = False`.
    """

    # Set to False on a subclass to remove the CLI fallback (e.g. if the
    # agent should be confined to structured tools only).
    enable_cli: bool = True

    def __init__(self):
        self.client = _create_client()
        self.model = settings.claude_model
        self.max_tokens = settings.claude_max_tokens

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent identifier."""

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """System prompt defining agent behavior. The base class
        automatically prepends a tool-selection guidance block."""

    @property
    def mcp_tools(self) -> list[dict]:
        """Specialized MCP tool schemas for this agent. Override in subclasses.

        These are merged with the shared `run_shell` tool by `tools`.
        Older subclasses that override `tools` directly still work — the
        base class only injects `run_shell` if it isn't already present.
        """
        return []

    @property
    def tools(self) -> list[dict]:
        """Final tool list passed to the Claude API.

        Composes `mcp_tools` + `run_shell` (when `enable_cli`). Subclasses
        that override `tools` for legacy reasons keep working — the base
        only injects `run_shell` if no entry with that name exists.
        """
        tools_list = list(self.mcp_tools)
        if self.enable_cli and not any(t.get("name") == "run_shell" for t in tools_list):
            tools_list.append(RUN_SHELL_TOOL)
        return tools_list

    @property
    def effective_system_prompt(self) -> str:
        """System prompt sent to Claude — agent's prompt + tool-selection guidance."""
        base = self.system_prompt
        if self.enable_cli:
            return f"{base}\n\n{TOOL_SELECTION_PROMPT}"
        return base

    async def execute(self, query: str, context: dict | None = None, user: dict | None = None) -> dict:
        """Execute the agent with a query and return structured result."""
        start = time.monotonic()
        self._current_user = user

        messages = self._build_messages(query, context)

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.effective_system_prompt,
                messages=messages,
                tools=self.tools if self.tools else anthropic.NOT_GIVEN,
            )

            elapsed_ms = int((time.monotonic() - start) * 1000)
            cost_usd = self._calculate_cost(response.usage)
            input_tokens = int(getattr(response.usage, "input_tokens", 0) or 0)
            output_tokens = int(getattr(response.usage, "output_tokens", 0) or 0)

            all_tool_calls = []
            text_content = ""
            max_iterations = 10  # Safety limit to prevent infinite loops

            # Agentic loop: keep running until Claude stops requesting tools
            for _ in range(max_iterations):
                tool_calls = []

                for block in response.content:
                    if block.type == "text":
                        text_content += block.text
                    elif block.type == "tool_use":
                        tool_calls.append({
                            "tool": block.name,
                            "input": block.input,
                            "id": block.id,
                        })

                all_tool_calls.extend(tool_calls)

                # If no tool calls or stop reason isn't tool_use, we're done
                if not tool_calls or response.stop_reason != "tool_use":
                    break

                # Execute tools and continue the conversation
                tool_results = await self._process_tool_calls(tool_calls)
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=self.effective_system_prompt,
                    messages=messages,
                    tools=self.tools if self.tools else anthropic.NOT_GIVEN,
                )
                cost_usd += self._calculate_cost(response.usage)
                input_tokens += int(getattr(response.usage, "input_tokens", 0) or 0)
                output_tokens += int(getattr(response.usage, "output_tokens", 0) or 0)

            logger.info(
                "Agent executed",
                agent=self.name,
                elapsed_ms=elapsed_ms,
                cost_usd=cost_usd,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tool_calls=len(tool_calls),
            )

            return {
                "agent": self.name,
                "response": text_content,
                "tool_calls": all_tool_calls,
                "cost_usd": cost_usd,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "model": self.model,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            logger.error("Agent execution failed", agent=self.name, error=str(e))
            return {
                "agent": self.name,
                "response": f"Error: {str(e)}",
                "tool_calls": [],
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "model": self.model,
                "elapsed_ms": int((time.monotonic() - start) * 1000),
            }

    async def execute_with_events(
        self, query: str, context: dict | None = None, user: dict | None = None
    ) -> AsyncIterator[dict]:
        """Execute the agent and yield real-time events for each step."""
        start = time.monotonic()
        self._current_user = user
        messages = self._build_messages(query, context)

        yield {"type": "agent_thinking", "agent": self.name, "data": {"message": "Analyzing request..."}}

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.effective_system_prompt,
                messages=messages,
                tools=self.tools if self.tools else anthropic.NOT_GIVEN,
            )

            cost_usd = self._calculate_cost(response.usage)
            all_tool_calls = []
            text_content = ""
            max_iterations = 10
            iteration = 0

            for _ in range(max_iterations):
                iteration += 1
                tool_calls = []

                for block in response.content:
                    if block.type == "text":
                        text_content += block.text
                        yield {"type": "agent_text", "agent": self.name, "data": {"text": block.text}}
                    elif block.type == "tool_use":
                        tool_calls.append({
                            "tool": block.name,
                            "input": block.input,
                            "id": block.id,
                        })

                all_tool_calls.extend(tool_calls)

                if not tool_calls or response.stop_reason != "tool_use":
                    break

                # Emit tool call events
                for tc in tool_calls:
                    yield {
                        "type": "tool_call",
                        "agent": self.name,
                        "data": {
                            "tool": tc["tool"],
                            "input": _summarize_tool_input(tc["input"]),
                            "iteration": iteration,
                        },
                    }

                # Execute tools
                tool_results = await self._process_tool_calls(tool_calls)

                # Emit tool result events
                for tc, tr in zip(tool_calls, tool_results):
                    result_preview = str(tr.get("content", ""))[:200]
                    is_error = "error" in result_preview.lower() or "Error" in result_preview
                    yield {
                        "type": "tool_result",
                        "agent": self.name,
                        "data": {
                            "tool": tc["tool"],
                            "success": not is_error,
                            "preview": result_preview,
                            "iteration": iteration,
                        },
                    }

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

                yield {"type": "agent_thinking", "agent": self.name, "data": {"message": f"Processing results (step {iteration})..."}}

                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=self.effective_system_prompt,
                    messages=messages,
                    tools=self.tools if self.tools else anthropic.NOT_GIVEN,
                )
                cost_usd += self._calculate_cost(response.usage)

            elapsed_ms = int((time.monotonic() - start) * 1000)

            yield {
                "type": "agent_done",
                "agent": self.name,
                "data": {
                    "cost_usd": cost_usd,
                    "elapsed_ms": elapsed_ms,
                    "tool_calls_count": len(all_tool_calls),
                },
            }

            # Final return value (collected by orchestrator)
            yield {
                "type": "agent_result",
                "agent": self.name,
                "data": {
                    "agent": self.name,
                    "response": text_content,
                    "tool_calls": all_tool_calls,
                    "cost_usd": cost_usd,
                    "elapsed_ms": elapsed_ms,
                },
            }

        except Exception as e:
            logger.error("Agent execution failed", agent=self.name, error=str(e))
            elapsed_ms = int((time.monotonic() - start) * 1000)
            yield {
                "type": "agent_error",
                "agent": self.name,
                "data": {"error": str(e), "elapsed_ms": elapsed_ms},
            }
            yield {
                "type": "agent_result",
                "agent": self.name,
                "data": {
                    "agent": self.name,
                    "response": f"Error: {str(e)}",
                    "tool_calls": [],
                    "cost_usd": 0.0,
                    "elapsed_ms": elapsed_ms,
                },
            }

    async def generate_plan(self, query: str, context: dict | None = None, user: dict | None = None) -> dict:
        """Generate an execution plan WITHOUT executing any tools.

        Returns a list of planned steps (tool calls) for user approval.
        """
        start = time.monotonic()
        self._current_user = user

        plan_system = self.system_prompt + """

IMPORTANT: You are in PLAN MODE. Do NOT execute actions directly.
Instead, analyze the request and return a JSON plan with steps the user must approve before execution.

Return ONLY valid JSON in this format:
{
  "summary": "Brief description of what this plan will do",
  "steps": [
    {
      "order": 1,
      "title": "Short title for this step",
      "description": "What this step does and why",
      "tool_name": "the_tool_to_call",
      "tool_input": {"param1": "value1"}
    }
  ]
}

Be specific with tool_input values — use real parameter values from the user's query and context.
Each step should map to exactly one tool call."""

        messages = self._build_messages(query, context)

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=plan_system,
                messages=messages,
            )

            cost_usd = self._calculate_cost(response.usage)
            text = "".join(b.text for b in response.content if b.type == "text")

            # Parse the JSON plan from the response
            import json
            json_str = text
            if "```" in text:
                json_str = text.split("```")[1].strip()
                if json_str.startswith("json"):
                    json_str = json_str[4:].strip()

            plan_data = json.loads(json_str)

            elapsed_ms = int((time.monotonic() - start) * 1000)

            return {
                "agent": self.name,
                "summary": plan_data.get("summary", ""),
                "steps": [
                    {
                        "order": s.get("order", i + 1),
                        "title": s["title"],
                        "description": s["description"],
                        "agent_name": self.name,
                        "tool_name": s["tool_name"],
                        "tool_input": s["tool_input"],
                    }
                    for i, s in enumerate(plan_data.get("steps", []))
                ],
                "cost_usd": cost_usd,
                "elapsed_ms": elapsed_ms,
            }

        except Exception as e:
            logger.error("Plan generation failed", agent=self.name, error=str(e))
            return {
                "agent": self.name,
                "summary": f"Failed to generate plan: {str(e)}",
                "steps": [],
                "cost_usd": 0.0,
                "elapsed_ms": int((time.monotonic() - start) * 1000),
            }

    async def execute_single_step(self, tool_name: str, tool_input: dict, user: dict | None = None) -> dict:
        """Execute a single pre-approved plan step."""
        self._current_user = user
        start = time.monotonic()
        try:
            result = await self._execute_tool(tool_name, tool_input)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            is_error = "error" in str(result).lower()[:200]
            return {
                "success": not is_error,
                "result": result,
                "elapsed_ms": elapsed_ms,
            }
        except Exception as e:
            return {
                "success": False,
                "result": {"error": str(e)},
                "elapsed_ms": int((time.monotonic() - start) * 1000),
            }

    def _build_messages(self, query: str, context: dict | None) -> list[dict]:
        """Build the message list for the API call."""
        content = query
        if context:
            context_str = "\n".join(f"- {k}: {v}" for k, v in context.items())
            content = f"Context:\n{context_str}\n\nQuery: {query}"

        return [{"role": "user", "content": content}]

    async def _process_tool_calls(self, tool_calls: list[dict]) -> list[dict]:
        """Process tool calls and return results. Override for custom tool handling."""
        results = []
        for tc in tool_calls:
            try:
                result = await self._execute_tool(tc["tool"], tc["input"])
            except Exception as e:
                logger.warning("Tool call failed", tool=tc["tool"], agent=self.name, error=str(e))
                result = {"error": str(e)}
            results.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": str(result),
            })
        return results

    async def _execute_tool(self, tool_name: str, tool_input: dict) -> Any:
        """Execute a single tool. Subclasses override and chain to super()
        for unknown tools so the shared `run_shell` dispatch keeps working.
        """
        if tool_name == "run_shell":
            return await self._run_shell(tool_input)

        logger.warning("Unhandled tool call", tool=tool_name, agent=self.name)
        return {"error": f"Tool '{tool_name}' not implemented"}

    async def _run_shell(self, tool_input: dict) -> dict:
        """Execute a shell command via the shared TerminalMCPClient.

        Pulls the requesting user's GitHub + GCP credentials out of the
        per-call user dict so commands authenticate as them, not as the
        backend service account. Session-scoped workdir is keyed off
        `agent_name + user_sub` so two parallel sessions don't collide.
        """
        from app.mcp.terminal import TerminalMCPClient

        user = getattr(self, "_current_user", None) or {}

        session_id = f"{self.name}:{user.get('sub') or user.get('login') or 'anon'}"

        terminal = TerminalMCPClient(
            gcp_access_token=user.get("gcp_access_token"),
            github_token=user.get("github_token"),
            gcp_project_id=user.get("gcp_project_id") or settings.gcp_project_id,
            session_id=session_id,
        )

        return await terminal.execute(
            command=tool_input["command"],
            cwd=tool_input.get("cwd"),
            timeout=min(int(tool_input.get("timeout", 30)), 120),
        )

    def _calculate_cost(self, usage) -> float:
        """Calculate API cost from token usage.

        Opus 4.6 pricing via Vertex AI:
        - Input: $15 / 1M tokens
        - Output: $75 / 1M tokens
        """
        input_cost = (usage.input_tokens / 1_000_000) * 15.0
        output_cost = (usage.output_tokens / 1_000_000) * 75.0
        return round(input_cost + output_cost, 6)
