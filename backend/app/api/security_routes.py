"""Security API endpoints — pentest report upload, findings, summaries, trends.

Mounted at /api/v1/security/* in main.py.
"""

import json

import structlog
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.api.auth import get_current_user
from app.services.pentest_store import (
    get_findings,
    get_reports,
    get_security_summary,
    get_severity_trend,
    get_tool_breakdown,
    store_scan_report,
)
from app.mcp.pentest import check_health as kali_health, run_repo_scan

logger = structlog.get_logger()

router = APIRouter(prefix="/security", tags=["security"])


# ─── Ingest (automated — from CI/CD or scan agents) ───────────────────

@router.post("/ingest")
async def ingest_scan_results(
    body: dict,
    user: dict = Depends(get_current_user),
):
    """Ingest structured scan results from automated pipelines.

    Accepts JSON in the format returned by the pentest MCP tools
    (nmap, nikto, zap, trivy, etc.) or SARIF/Trivy JSON from CI/CD.

    Body: {
      "project": "my-app",
      "tool": "nmap",
      "scan_type": "infra",
      "target": "10.0.0.1",
      "findings": [...]
    }
    """
    project = body.get("project", "default")
    tool = body.get("tool", "unknown")
    scan_type = body.get("scan_type", "unknown")
    target = body.get("target", "unknown")
    findings = body.get("findings", [])

    report_id = store_scan_report(
        project=project,
        tool=tool,
        scan_type=scan_type,
        target=target,
        findings=findings,
        user_id=user.get("sub", user.get("login", "")),
        metadata=body.get("metadata"),
    )

    return {
        "status": "ingested",
        "report_id": report_id,
        "finding_count": len(findings),
    }


# ─── Upload (manual — pentest report file) ────────────────────────────

@router.post("/pentest/upload")
async def upload_pentest_report(
    file: UploadFile = File(...),
    project: str = Form("default"),
    scan_type: str = Form("web"),
    user: dict = Depends(get_current_user),
):
    """Upload a pentest report file (JSON or CSV).

    The file is parsed and findings are stored in MongoDB.
    Supported formats: JSON (array of findings), CSV.
    """
    content = await file.read()
    filename = file.filename or "upload"

    findings = []

    if filename.endswith(".json"):
        try:
            data = json.loads(content)
            if isinstance(data, list):
                findings = data
            elif isinstance(data, dict):
                findings = data.get("findings", data.get("vulnerabilities", [data]))
        except json.JSONDecodeError:
            return {"error": "Invalid JSON file"}

    elif filename.endswith(".csv"):
        import csv
        import io
        reader = csv.DictReader(io.StringIO(content.decode(errors="replace")))
        for row in reader:
            findings.append({
                "id": row.get("id", f"csv-{len(findings)}"),
                "title": row.get("title", row.get("vulnerability", "Unknown")),
                "severity": row.get("severity", "MEDIUM").upper(),
                "cvss_score": float(row.get("cvss_score", row.get("cvss", "5.0"))),
                "affected_asset": row.get("affected_asset", row.get("asset", "unknown")),
                "status": row.get("status", "open"),
                "cve_id": row.get("cve_id", row.get("cve", "")),
                "remediation_notes": row.get("remediation_notes", row.get("remediation", "")),
            })
    else:
        return {"error": f"Unsupported file format: {filename}. Use .json or .csv"}

    report_id = store_scan_report(
        project=project,
        tool="manual_upload",
        scan_type=scan_type,
        target=filename,
        findings=findings,
        user_id=user.get("sub", user.get("login", "")),
        metadata={"original_filename": filename, "file_size": len(content)},
    )

    return {
        "status": "uploaded",
        "report_id": report_id,
        "finding_count": len(findings),
        "filename": filename,
    }


# ─── Dashboard Data Endpoints ─────────────────────────────────────────

@router.get("/summary")
async def security_summary(
    project: str | None = Query(None),
    _user: dict = Depends(get_current_user),
):
    """Security posture overview — severity counts, health score, MTTR."""
    return get_security_summary(project=project)


@router.get("/findings")
async def security_findings(
    project: str | None = Query(None),
    severity: str | None = Query(None),
    status: str | None = Query(None),
    tool: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    _user: dict = Depends(get_current_user),
):
    """Paginated findings list with filters."""
    return get_findings(
        project=project,
        severity=severity,
        status=status,
        tool=tool,
        limit=limit,
        offset=offset,
    )


@router.get("/trends")
async def security_trends(
    project: str | None = Query(None),
    days: int = Query(90, le=365),
    _user: dict = Depends(get_current_user),
):
    """Time-series severity trend data for charting."""
    return get_severity_trend(project=project, days=days)


@router.get("/reports")
async def security_reports(
    project: str | None = Query(None),
    limit: int = Query(20, le=100),
    _user: dict = Depends(get_current_user),
):
    """List recent scan reports."""
    return get_reports(project=project, limit=limit)


@router.get("/tools")
async def security_tools_breakdown(
    project: str | None = Query(None),
    _user: dict = Depends(get_current_user),
):
    """Finding counts grouped by scanner tool."""
    return get_tool_breakdown(project=project)


# ─── Repo Scan (trigger from Pentest tab) ─────────────────────────────

@router.post("/scan/repo")
async def trigger_repo_scan(
    body: dict,
    user: dict = Depends(get_current_user),
):
    """Trigger a Trivy scan on a GitHub repository.

    Body: { "repo_url": "https://github.com/org/repo", "branch": "main" }
    """
    repo_url = body.get("repo_url", "")
    branch = body.get("branch", "main")

    if not repo_url:
        return {"error": "repo_url is required"}

    github_token = user.get("github_token")

    result = await run_repo_scan(
        repo_url=repo_url,
        branch=branch,
        github_token=github_token,
    )

    # Auto-ingest findings into MongoDB
    repo_name = repo_url.rstrip("/").split("/")[-1] if "/" in repo_url else repo_url
    report_id = store_scan_report(
        project=repo_name,
        tool="trivy",
        scan_type="repo",
        target=f"{repo_url}@{branch}",
        findings=result.get("findings", []),
        user_id=user.get("sub", user.get("login", "")),
        metadata={"repo_url": repo_url, "branch": branch},
    )

    return {
        **result,
        "report_id": report_id,
    }


# ─── Kali Scanner Health ──────────────────────────────────────────────

@router.get("/scanner/health")
async def scanner_health(_user: dict = Depends(get_current_user)):
    """Check if the Kali scanner container is running and tools available."""
    try:
        return await kali_health()
    except Exception as e:
        return {"status": "offline", "error": str(e)}
