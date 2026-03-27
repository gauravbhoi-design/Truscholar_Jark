import * as vscode from "vscode";

let chatPanel: vscode.WebviewPanel | undefined;

export function activate(context: vscode.ExtensionContext) {
  const config = vscode.workspace.getConfiguration("devopsCopilot");
  const apiUrl = config.get<string>("apiUrl", "http://localhost:8000/api/v1");

  // ─── Ask Command ──────────────────────────────────────────────────
  context.subscriptions.push(
    vscode.commands.registerCommand("devops-copilot.ask", async () => {
      const query = await vscode.window.showInputBox({
        prompt: "Ask the DevOps Co-Pilot",
        placeHolder: "e.g., Why is my deployment failing?",
      });
      if (!query) return;

      await runQuery(query, apiUrl, config);
    }),
  );

  // ─── Analyze Current File ─────────────────────────────────────────
  context.subscriptions.push(
    vscode.commands.registerCommand("devops-copilot.analyzeFile", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        vscode.window.showWarningMessage("No file open to analyze");
        return;
      }

      const fileName = editor.document.fileName;
      const content = editor.document.getText();
      const language = editor.document.languageId;

      let queryType = "Analyze this code for issues";
      if (fileName.includes("Dockerfile")) queryType = "Validate this Dockerfile";
      else if (fileName.endsWith(".yaml") || fileName.endsWith(".yml"))
        queryType = "Validate this Kubernetes/config YAML";
      else if (fileName.endsWith(".tf")) queryType = "Review this Terraform config";

      const query = `${queryType}:\n\nFile: ${fileName}\nLanguage: ${language}\n\n\`\`\`${language}\n${content.slice(0, 8000)}\n\`\`\``;

      await runQuery(query, apiUrl, config);
    }),
  );

  // ─── Review PR ─────────────────────────────────────────────────────
  context.subscriptions.push(
    vscode.commands.registerCommand("devops-copilot.reviewPR", async () => {
      const prUrl = await vscode.window.showInputBox({
        prompt: "Enter PR URL or number",
        placeHolder: "e.g., owner/repo#123",
      });
      if (!prUrl) return;

      await runQuery(`Review this pull request: ${prUrl}`, apiUrl, config);
    }),
  );

  // ─── Debug Deployment ──────────────────────────────────────────────
  context.subscriptions.push(
    vscode.commands.registerCommand("devops-copilot.debugDeployment", async () => {
      const service = await vscode.window.showInputBox({
        prompt: "Enter service or deployment name",
        placeHolder: "e.g., api-server in namespace production",
      });
      if (!service) return;

      await runQuery(
        `Debug deployment issue for: ${service}. Check pod status, recent logs, and deployment events.`,
        apiUrl,
        config,
      );
    }),
  );
}

async function runQuery(
  query: string,
  apiUrl: string,
  config: vscode.WorkspaceConfiguration,
): Promise<void> {
  const token = config.get<string>("apiToken", "dev_local");

  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "DevOps Co-Pilot", cancellable: false },
    async (progress) => {
      progress.report({ message: "Analyzing..." });

      try {
        const resp = await fetch(`${apiUrl}/agent/query`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ query }),
        });

        if (!resp.ok) throw new Error(`API error: ${resp.status}`);

        const data = (await resp.json()) as {
          message: string;
          agents_used: string[];
          cost_usd: number;
        };

        // Show result in output channel
        const channel = vscode.window.createOutputChannel("DevOps Co-Pilot");
        channel.clear();
        channel.appendLine(`Query: ${query.slice(0, 200)}`);
        channel.appendLine(`Agents: ${data.agents_used.join(", ")}`);
        channel.appendLine(`Cost: $${data.cost_usd.toFixed(4)}`);
        channel.appendLine("─".repeat(60));
        channel.appendLine(data.message);
        channel.show();
      } catch (error) {
        vscode.window.showErrorMessage(
          `DevOps Co-Pilot: ${error instanceof Error ? error.message : "Request failed"}`,
        );
      }
    },
  );
}

export function deactivate() {
  chatPanel?.dispose();
}
