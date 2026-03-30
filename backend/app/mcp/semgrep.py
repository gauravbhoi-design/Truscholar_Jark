"""Semgrep in-process tool — Static analysis and vulnerability scanning."""

import asyncio
import json
import subprocess
import tempfile

import structlog

logger = structlog.get_logger()


class SemgrepTool:
    """In-process Semgrep scanner for code analysis."""

    LANG_EXTENSIONS = {
        "python": ".py",
        "javascript": ".js",
        "typescript": ".ts",
        "go": ".go",
        "java": ".java",
        "ruby": ".rb",
        "rust": ".rs",
    }

    async def scan(
        self, code: str, language: str, ruleset: str = "p/default"
    ) -> dict:
        """Run Semgrep scan on code content."""

        def _run():
            ext = self.LANG_EXTENSIONS.get(language.lower(), ".txt")

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=ext, delete=True
            ) as f:
                f.write(code)
                f.flush()

                try:
                    result = subprocess.run(
                        [
                            "semgrep",
                            "--config", ruleset,
                            "--json",
                            "--quiet",
                            f.name,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )

                    if result.returncode not in (0, 1):  # 1 = findings found
                        return {"error": result.stderr[:500]}

                    output = json.loads(result.stdout) if result.stdout else {}
                    findings = output.get("results", [])

                    return {
                        "findings_count": len(findings),
                        "findings": [
                            {
                                "rule_id": f.get("check_id"),
                                "message": f.get("extra", {}).get("message", ""),
                                "severity": f.get("extra", {}).get("severity", "unknown"),
                                "line_start": f.get("start", {}).get("line"),
                                "line_end": f.get("end", {}).get("line"),
                                "code_snippet": f.get("extra", {}).get("lines", ""),
                            }
                            for f in findings[:25]
                        ],
                    }

                except FileNotFoundError:
                    return {
                        "error": "semgrep not installed",
                        "suggestion": "pip install semgrep",
                    }
                except subprocess.TimeoutExpired:
                    return {"error": "Semgrep scan timed out (30s)"}

        return await asyncio.to_thread(_run)
