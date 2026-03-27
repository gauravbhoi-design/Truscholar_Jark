#!/usr/bin/env node

import React, { useState, useEffect } from "react";
import { render, Box, Text, useInput, useApp } from "ink";
import Spinner from "ink-spinner";
import TextInput from "ink-text-input";
import meow from "meow";

const cli = meow(
  `
  Usage
    $ copilot <query>

  Options
    --api-url   Backend API URL (default: http://localhost:8000/api/v1)
    --token     API auth token (default: dev_local)

  Examples
    $ copilot "Why is my deployment failing?"
    $ copilot "Review PR owner/repo#42"
    $ copilot --api-url https://copilot.example.com/api/v1
`,
  {
    importMeta: import.meta,
    flags: {
      apiUrl: { type: "string", default: "http://localhost:8000/api/v1" },
      token: { type: "string", default: "dev_local" },
    },
  },
);

interface AgentResponse {
  message: string;
  agents_used: string[];
  cost_usd: number;
  status: string;
}

function App({
  initialQuery,
  apiUrl,
  token,
}: {
  initialQuery: string;
  apiUrl: string;
  token: string;
}) {
  const { exit } = useApp();
  const [query, setQuery] = useState(initialQuery);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<AgentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useInput((input, key) => {
    if (key.escape || (key.ctrl && input === "c")) {
      exit();
    }
  });

  useEffect(() => {
    if (query) {
      runQuery(query);
    }
  }, []);

  async function runQuery(q: string) {
    setLoading(true);
    setError(null);
    setResponse(null);

    try {
      const resp = await fetch(`${apiUrl}/agent/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ query: q }),
      });

      if (!resp.ok) throw new Error(`API error: ${resp.status}`);
      const data: AgentResponse = await resp.json();
      setResponse(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(value: string) {
    if (value.trim()) {
      setQuery(value.trim());
      setInput("");
      runQuery(value.trim());
    }
  }

  return (
    <Box flexDirection="column" padding={1}>
      <Box marginBottom={1}>
        <Text bold color="blue">
          DevOps Co-Pilot
        </Text>
        <Text color="gray"> v1.0.0</Text>
      </Box>

      {loading && (
        <Box>
          <Text color="yellow">
            <Spinner type="dots" />
          </Text>
          <Text> Analyzing...</Text>
        </Box>
      )}

      {error && (
        <Box>
          <Text color="red">Error: {error}</Text>
        </Box>
      )}

      {response && (
        <Box flexDirection="column" marginBottom={1}>
          <Box marginBottom={1}>
            <Text dimColor>
              Agents: {response.agents_used.join(", ")} | Cost: $
              {response.cost_usd.toFixed(4)} | Status: {response.status}
            </Text>
          </Box>
          <Text>{response.message}</Text>
        </Box>
      )}

      {!loading && (
        <Box>
          <Text color="green">&gt; </Text>
          <TextInput
            value={input}
            onChange={setInput}
            onSubmit={handleSubmit}
            placeholder="Ask a DevOps question..."
          />
        </Box>
      )}
    </Box>
  );
}

const initialQuery = cli.input.join(" ");
render(
  <App
    initialQuery={initialQuery}
    apiUrl={cli.flags.apiUrl}
    token={cli.flags.token}
  />,
);
