"""Deployment Doctor Agent — Validates Docker, K8s, Terraform configs and CI/CD pipelines."""

import structlog
from app.agents.base import BaseAgent

logger = structlog.get_logger()


class DeploymentDoctorAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "deployment_doctor"

    @property
    def system_prompt(self) -> str:
        return """You are a Deployment Doctor Agent specializing in infrastructure configuration and CI/CD pipeline analysis.

Your capabilities:
- Validate Dockerfiles for security and efficiency best practices
- Analyze Kubernetes manifests (Deployments, Services, ConfigMaps, HPA)
- Review Terraform/Helm configurations for misconfigurations
- Debug CI/CD pipeline failures (GitHub Actions, Jenkins, ArgoCD)
- Detect configuration drift between environments

When analyzing deployments:
1. Read the relevant config files (Dockerfile, K8s YAML, terraform, CI config)
2. Validate against best practices and security policies
3. Check for common misconfigurations
4. Analyze CI/CD pipeline logs for failure root cause
5. Suggest specific fixes

Output format:
- **Issues Found**: Severity-ranked list of problems
- **Config Snippets**: The problematic configuration
- **Fixes**: Corrected configuration
- **Best Practices**: Recommendations for improvement"""

    @property
    def tools(self) -> list[dict]:
        return [
            {
                "name": "validate_dockerfile",
                "description": "Validate a Dockerfile for best practices and security",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Dockerfile content"},
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "validate_k8s_manifest",
                "description": "Validate Kubernetes manifest YAML",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "K8s YAML content"},
                        "kind": {"type": "string", "description": "Resource kind (Deployment, Service, etc.)"},
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "get_pod_status",
                "description": "Get status of pods in a Kubernetes namespace",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "namespace": {"type": "string", "default": "default"},
                        "label_selector": {"type": "string", "description": "K8s label selector"},
                    },
                    "required": [],
                },
            },
            {
                "name": "get_ci_workflow_status",
                "description": "Get GitHub Actions workflow run status and logs",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "repo": {"type": "string", "description": "owner/repo format"},
                        "run_id": {"type": "integer", "description": "Workflow run ID (latest if omitted)"},
                    },
                    "required": ["repo"],
                },
            },
            {
                "name": "validate_terraform",
                "description": "Validate Terraform configuration for common issues",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Terraform HCL content"},
                        "provider": {"type": "string", "description": "Cloud provider (aws, gcp, azure)"},
                    },
                    "required": ["content"],
                },
            },
        ]

    async def _execute_tool(self, tool_name: str, tool_input: dict):
        """Dispatch to Docker, K8s, and CI/CD tools."""
        from app.mcp.kubernetes import KubernetesMCPClient
        from app.mcp.github import GitHubMCPClient

        if tool_name == "validate_dockerfile":
            return self._validate_dockerfile(tool_input["content"])

        elif tool_name == "validate_k8s_manifest":
            return self._validate_k8s_manifest(tool_input["content"])

        elif tool_name == "get_pod_status":
            k8s = KubernetesMCPClient()
            return await k8s.get_pods(
                namespace=tool_input.get("namespace", "default"),
                label_selector=tool_input.get("label_selector"),
            )

        elif tool_name == "get_ci_workflow_status":
            user_token = getattr(self, "_current_user", {}).get("github_token") if getattr(self, "_current_user", None) else None
            github = GitHubMCPClient(user_token=user_token)
            return await github.get_workflow_runs(
                repo=tool_input["repo"],
                run_id=tool_input.get("run_id"),
            )

        elif tool_name == "validate_terraform":
            return self._validate_terraform(tool_input["content"])

        return {"error": f"Unknown tool: {tool_name}"}

    def _validate_dockerfile(self, content: str) -> dict:
        """In-process Dockerfile validation."""
        issues = []
        lines = content.strip().split("\n")

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("FROM") and ":latest" in stripped:
                issues.append({"line": i, "severity": "high", "message": "Avoid :latest tag — pin to specific version"})
            if stripped.startswith("RUN") and "curl" in stripped and "| sh" in stripped:
                issues.append({"line": i, "severity": "critical", "message": "Piping curl to shell is a security risk"})
            if stripped == "USER root":
                issues.append({"line": i, "severity": "high", "message": "Running as root — use a non-root user"})
            if stripped.startswith("COPY . .") or stripped.startswith("ADD . ."):
                issues.append({"line": i, "severity": "medium", "message": "Copying entire context — use .dockerignore and specific COPY"})
            if stripped.startswith("ENV") and any(kw in stripped.lower() for kw in ["password", "secret", "key", "token"]):
                issues.append({"line": i, "severity": "critical", "message": "Secrets in ENV — use build args or secrets mount"})

        has_user = any("USER" in l and "root" not in l for l in lines)
        if not has_user:
            issues.append({"line": 0, "severity": "medium", "message": "No non-root USER directive found"})

        return {"valid": len(issues) == 0, "issues": issues, "total_issues": len(issues)}

    def _validate_k8s_manifest(self, content: str) -> dict:
        """In-process K8s manifest validation."""
        import yaml
        issues = []

        try:
            docs = list(yaml.safe_load_all(content))
        except yaml.YAMLError as e:
            return {"valid": False, "issues": [{"severity": "critical", "message": f"Invalid YAML: {e}"}]}

        for doc in docs:
            if not doc:
                continue
            kind = doc.get("kind", "Unknown")
            spec = doc.get("spec", {})

            if kind == "Deployment":
                template = spec.get("template", {}).get("spec", {})
                containers = template.get("containers", [])
                for c in containers:
                    if not c.get("resources"):
                        issues.append({"severity": "high", "message": f"Container '{c.get('name')}' missing resource limits"})
                    if not c.get("livenessProbe") and not c.get("readinessProbe"):
                        issues.append({"severity": "medium", "message": f"Container '{c.get('name')}' missing health probes"})
                    image = c.get("image", "")
                    if ":latest" in image or ":" not in image:
                        issues.append({"severity": "high", "message": f"Container '{c.get('name')}' using unpinned image tag"})

                if not spec.get("replicas") or spec.get("replicas", 0) < 2:
                    issues.append({"severity": "medium", "message": "Deployment has fewer than 2 replicas"})

        return {"valid": len(issues) == 0, "issues": issues, "total_issues": len(issues)}

    def _validate_terraform(self, content: str) -> dict:
        """In-process Terraform config validation."""
        issues = []

        if "encryption" not in content.lower() and ("s3" in content.lower() or "bucket" in content.lower()):
            issues.append({"severity": "high", "message": "S3/GCS bucket without encryption configuration"})
        if "public" in content.lower() and "acl" in content.lower():
            issues.append({"severity": "critical", "message": "Public ACL detected — review access control"})
        if "0.0.0.0/0" in content:
            issues.append({"severity": "critical", "message": "Overly permissive CIDR 0.0.0.0/0 in security group/firewall"})

        return {"valid": len(issues) == 0, "issues": issues, "total_issues": len(issues)}
