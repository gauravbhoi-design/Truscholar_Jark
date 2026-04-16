"""Kali Scan Agent — FastAPI service running inside the Kali Docker container.

Exposes HTTP endpoints for each security tool. The backend API calls these
over the Docker network (http://kali-scanner:8585) instead of `docker exec`.

This works in Docker Compose, Kubernetes, and Cloud Run.
"""

import asyncio
import json
import os
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Kali Scan Agent", version="1.0.0")

WORKDIR = "/opt/scan-agent/workdir"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run(cmd: str, timeout: int = 300) -> str:
    """Run a shell command and return stdout."""
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=WORKDIR,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise HTTPException(504, f"Scan timed out after {timeout}s")

    return stdout.decode(errors="replace")


# ─── Health ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    tools = {}
    for tool in ["nmap", "nikto", "sslscan", "subfinder", "trivy", "testssl.sh"]:
        tools[tool] = shutil.which(tool) is not None
    return {"status": "healthy", "tools": tools}


# ─── Nmap ──────────────────────────────────────────────────────────────

class NmapRequest(BaseModel):
    target: str
    ports: str = "-"
    scan_type: str = "-sV"


@app.post("/scan/nmap")
async def scan_nmap(req: NmapRequest):
    port_flag = f"-p {req.ports}" if req.ports != "-" else ""
    cmd = f"nmap {req.scan_type} {port_flag} -oX - --no-stylesheet {req.target}"
    xml_out = await _run(cmd, timeout=600)

    findings = []
    try:
        root = ET.fromstring(xml_out)
        for host in root.findall("host"):
            addr_el = host.find("address")
            addr = addr_el.get("addr", req.target) if addr_el is not None else req.target

            for port_el in host.findall(".//port"):
                portid = port_el.get("portid", "?")
                protocol = port_el.get("protocol", "tcp")

                state_el = port_el.find("state")
                state = state_el.get("state", "unknown") if state_el is not None else "unknown"

                service_el = port_el.find("service")
                service_name = service_el.get("name", "unknown") if service_el is not None else "unknown"
                product = service_el.get("product", "") if service_el is not None else ""
                version = service_el.get("version", "") if service_el is not None else ""

                if state == "open":
                    severity = "HIGH" if portid in ("21", "23", "3389", "5900") else "MEDIUM"
                    findings.append({
                        "id": f"nmap-{addr}-{protocol}-{portid}",
                        "title": f"Open port {portid}/{protocol} ({service_name})",
                        "severity": severity,
                        "cvss_score": 7.0 if severity == "HIGH" else 4.0,
                        "affected_asset": addr,
                        "status": "open",
                        "discovered_at": _now(),
                        "details": {
                            "port": int(portid), "protocol": protocol,
                            "service": service_name, "product": product, "version": version,
                        },
                    })
    except ET.ParseError:
        pass

    return {"tool": "nmap", "scan_type": "infra", "target": req.target,
            "finding_count": len(findings), "findings": findings, "scanned_at": _now()}


# ─── Nikto ─────────────────────────────────────────────────────────────

class NiktoRequest(BaseModel):
    target: str
    port: int = 80
    ssl: bool = False


@app.post("/scan/nikto")
async def scan_nikto(req: NiktoRequest):
    ssl_flag = "-ssl" if req.ssl else ""
    cmd = f"nikto -h {req.target} -p {req.port} {ssl_flag} -Format json -output -"
    raw = await _run(cmd, timeout=600)

    findings = []
    try:
        data = json.loads(raw)
        for vuln in data.get("vulnerabilities", []):
            osvdb = vuln.get("OSVDB", "0")
            findings.append({
                "id": f"nikto-{req.target}-{osvdb}",
                "title": vuln.get("msg", "Web vulnerability"),
                "severity": "HIGH" if int(osvdb) > 0 else "MEDIUM",
                "cvss_score": 6.5,
                "affected_asset": f"{req.target}:{req.port}",
                "status": "open",
                "discovered_at": _now(),
                "details": {"osvdb": osvdb, "method": vuln.get("method", "GET"), "url": vuln.get("url", "/")},
            })
    except (json.JSONDecodeError, KeyError):
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("+ ") and "OSVDB" in line:
                findings.append({
                    "id": f"nikto-{req.target}-{len(findings)}",
                    "title": line[2:], "severity": "MEDIUM", "cvss_score": 5.0,
                    "affected_asset": f"{req.target}:{req.port}", "status": "open", "discovered_at": _now(),
                })

    return {"tool": "nikto", "scan_type": "web", "target": f"{req.target}:{req.port}",
            "finding_count": len(findings), "findings": findings, "scanned_at": _now()}


# ─── ZAP Baseline ─────────────────────────────────────────────────────

class ZapRequest(BaseModel):
    target_url: str


@app.post("/scan/zap")
async def scan_zap(req: ZapRequest):
    out_path = f"{WORKDIR}/zap-report.json"
    cmd = f"zap-baseline.py -t {req.target_url} -J {out_path} -I 2>/dev/null; cat {out_path} 2>/dev/null || echo '{{}}'"
    raw = await _run(cmd, timeout=900)

    findings = []
    try:
        data = json.loads(raw)
        for site in data.get("site", []):
            for alert in site.get("alerts", []):
                risk = alert.get("riskdesc", "Medium").split(" ")[0].upper()
                sev_map = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW", "INFORMATIONAL": "LOW"}
                severity = sev_map.get(risk, "MEDIUM")
                cvss_map = {"HIGH": 7.5, "MEDIUM": 5.0, "LOW": 2.5}
                findings.append({
                    "id": f"zap-{alert.get('pluginid', '0')}",
                    "title": alert.get("alert", "ZAP Finding"),
                    "severity": severity,
                    "cvss_score": cvss_map.get(severity, 5.0),
                    "cve_id": alert.get("cweid", ""),
                    "affected_asset": req.target_url,
                    "status": "open",
                    "discovered_at": _now(),
                    "remediation_notes": alert.get("solution", ""),
                    "details": {
                        "risk": risk, "description": alert.get("desc", "")[:500],
                        "instance_count": len(alert.get("instances", [])),
                    },
                })
    except (json.JSONDecodeError, KeyError):
        pass

    return {"tool": "zap", "scan_type": "web", "target": req.target_url,
            "finding_count": len(findings), "findings": findings, "scanned_at": _now()}


# ─── SSLScan ──────────────────────────────────────────────────────────

class SslscanRequest(BaseModel):
    target: str


@app.post("/scan/sslscan")
async def scan_sslscan(req: SslscanRequest):
    cmd = f"sslscan --xml=- {req.target}"
    xml_out = await _run(cmd, timeout=120)

    findings = []
    try:
        root = ET.fromstring(xml_out)
        for test in root.findall(".//ssltest"):
            host = test.get("host", req.target)
            for cipher in test.findall(".//cipher"):
                sslversion = cipher.get("sslversion", "")
                if sslversion in ("SSLv2", "SSLv3", "TLSv1.0", "TLSv1.1"):
                    findings.append({
                        "id": f"ssl-weak-{host}-{sslversion}",
                        "title": f"Weak protocol enabled: {sslversion}",
                        "severity": "HIGH", "cvss_score": 7.4, "affected_asset": host,
                        "status": "open", "discovered_at": _now(),
                        "details": {"protocol": sslversion, "cipher": cipher.get("cipher", "")},
                    })
            for cert in test.findall(".//certificate"):
                not_after = cert.findtext("not-valid-after", "")
                if not_after:
                    findings.append({
                        "id": f"ssl-cert-{host}", "title": f"Certificate expires: {not_after}",
                        "severity": "MEDIUM", "cvss_score": 4.0, "affected_asset": host,
                        "status": "open", "discovered_at": _now(),
                        "details": {"subject": cert.findtext("subject", ""), "not_after": not_after},
                    })
    except ET.ParseError:
        pass

    return {"tool": "sslscan", "scan_type": "infra", "target": req.target,
            "finding_count": len(findings), "findings": findings, "scanned_at": _now()}


# ─── Subfinder ────────────────────────────────────────────────────────

class SubfinderRequest(BaseModel):
    domain: str


@app.post("/scan/subfinder")
async def scan_subfinder(req: SubfinderRequest):
    cmd = f"subfinder -d {req.domain} -silent -json"
    raw = await _run(cmd, timeout=120)

    subdomains = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            subdomains.append(data.get("host", line))
        except json.JSONDecodeError:
            if "." in line:
                subdomains.append(line)

    subdomains = sorted(set(subdomains))
    findings = [{
        "id": f"subfinder-{req.domain}-{sub}", "title": f"Subdomain: {sub}",
        "severity": "LOW", "cvss_score": 2.0, "affected_asset": req.domain,
        "status": "open", "discovered_at": _now(), "details": {"subdomain": sub},
    } for sub in subdomains]

    return {"tool": "subfinder", "scan_type": "infra", "target": req.domain,
            "finding_count": len(findings), "findings": findings,
            "subdomains": subdomains, "scanned_at": _now()}


# ─── Trivy ────────────────────────────────────────────────────────────

class TrivyRequest(BaseModel):
    target: str
    scan_type: str = "image"  # "image" or "fs" or "repo"


@app.post("/scan/trivy")
async def scan_trivy(req: TrivyRequest):
    cmd = f"trivy {req.scan_type} --format json --quiet {req.target}"
    raw = await _run(cmd, timeout=600)

    findings = []
    try:
        data = json.loads(raw)
        for result in data.get("Results", []):
            pkg_target = result.get("Target", req.target)
            for vuln in result.get("Vulnerabilities", []):
                cvss_score = 0.0
                for source_data in vuln.get("CVSS", {}).values():
                    s = source_data.get("V3Score", 0.0)
                    if s > cvss_score:
                        cvss_score = s
                findings.append({
                    "id": f"trivy-{vuln.get('VulnerabilityID', '')}",
                    "title": f"{vuln.get('VulnerabilityID', 'CVE')}: {vuln.get('Title', vuln.get('PkgName', ''))}",
                    "severity": vuln.get("Severity", "UNKNOWN").upper(),
                    "cvss_score": cvss_score,
                    "cve_id": vuln.get("VulnerabilityID", ""),
                    "affected_asset": f"{pkg_target} ({vuln.get('PkgName', '')}:{vuln.get('InstalledVersion', '')})",
                    "status": "open", "discovered_at": _now(),
                    "remediation_notes": f"Upgrade to {vuln.get('FixedVersion', 'N/A')}",
                    "details": {
                        "package": vuln.get("PkgName", ""),
                        "installed_version": vuln.get("InstalledVersion", ""),
                        "fixed_version": vuln.get("FixedVersion", ""),
                    },
                })
    except (json.JSONDecodeError, KeyError):
        pass

    return {"tool": "trivy", "scan_type": "container", "target": req.target,
            "finding_count": len(findings), "findings": findings, "scanned_at": _now()}


# ─── Testssl ──────────────────────────────────────────────────────────

class TestsslRequest(BaseModel):
    target: str


@app.post("/scan/testssl")
async def scan_testssl(req: TestsslRequest):
    out_path = f"{WORKDIR}/testssl.json"
    cmd = f"testssl --jsonfile {out_path} --quiet {req.target} 2>/dev/null; cat {out_path} 2>/dev/null || echo '[]'"
    raw = await _run(cmd, timeout=300)

    findings = []
    try:
        entries = json.loads(raw)
        if isinstance(entries, list):
            for entry in entries:
                sev = entry.get("severity", "INFO").upper()
                if sev in ("CRITICAL", "HIGH", "MEDIUM", "WARN"):
                    sev_map = {"CRITICAL": "CRITICAL", "HIGH": "HIGH", "MEDIUM": "MEDIUM", "WARN": "MEDIUM"}
                    mapped = sev_map.get(sev, "MEDIUM")
                    findings.append({
                        "id": f"testssl-{entry.get('id', '')}",
                        "title": f"{entry.get('id', 'TLS')}: {entry.get('finding', '')}",
                        "severity": mapped,
                        "cvss_score": {"CRITICAL": 9.0, "HIGH": 7.0, "MEDIUM": 5.0}.get(mapped, 5.0),
                        "affected_asset": req.target, "status": "open", "discovered_at": _now(),
                        "details": {"test_id": entry.get("id", ""), "finding": entry.get("finding", "")},
                    })
    except (json.JSONDecodeError, KeyError):
        pass

    return {"tool": "testssl", "scan_type": "infra", "target": req.target,
            "finding_count": len(findings), "findings": findings, "scanned_at": _now()}


# ─── Git Repo Clone + Trivy FS Scan ──────────────────────────────────

class RepoScanRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    github_token: Optional[str] = None


@app.post("/scan/repo")
async def scan_repo(req: RepoScanRequest):
    """Clone a Git repo and run Trivy filesystem scan on it."""
    repo_dir = f"{WORKDIR}/repo-scan"

    # Clean up any previous clone
    await _run(f"rm -rf {repo_dir}", timeout=10)

    # Build clone URL with token if provided
    clone_url = req.repo_url
    if req.github_token and "github.com" in clone_url:
        clone_url = clone_url.replace("https://", f"https://x-access-token:{req.github_token}@")

    # Clone the repo
    clone_cmd = f"git clone --depth 1 --branch {req.branch} {clone_url} {repo_dir} 2>&1"
    clone_out = await _run(clone_cmd, timeout=120)

    if not os.path.isdir(repo_dir):
        return {"tool": "trivy", "scan_type": "repo", "target": req.repo_url,
                "finding_count": 0, "findings": [],
                "error": f"Clone failed: {clone_out[:500]}", "scanned_at": _now()}

    # Run Trivy filesystem scan
    cmd = f"trivy fs --format json --quiet {repo_dir}"
    raw = await _run(cmd, timeout=600)

    findings = []
    try:
        data = json.loads(raw)
        for result in data.get("Results", []):
            pkg_target = result.get("Target", req.repo_url)
            for vuln in result.get("Vulnerabilities", []):
                cvss_score = 0.0
                for source_data in vuln.get("CVSS", {}).values():
                    s = source_data.get("V3Score", 0.0)
                    if s > cvss_score:
                        cvss_score = s
                findings.append({
                    "id": f"trivy-{vuln.get('VulnerabilityID', '')}",
                    "title": f"{vuln.get('VulnerabilityID', 'CVE')}: {vuln.get('Title', vuln.get('PkgName', ''))}",
                    "severity": vuln.get("Severity", "UNKNOWN").upper(),
                    "cvss_score": cvss_score,
                    "cve_id": vuln.get("VulnerabilityID", ""),
                    "affected_asset": f"{req.repo_url}:{req.branch} ({vuln.get('PkgName', '')})",
                    "status": "open", "discovered_at": _now(),
                    "remediation_notes": f"Upgrade to {vuln.get('FixedVersion', 'N/A')}",
                    "details": {
                        "package": vuln.get("PkgName", ""),
                        "installed_version": vuln.get("InstalledVersion", ""),
                        "fixed_version": vuln.get("FixedVersion", ""),
                        "repo": req.repo_url,
                        "branch": req.branch,
                    },
                })
    except (json.JSONDecodeError, KeyError):
        pass

    # Cleanup
    await _run(f"rm -rf {repo_dir}", timeout=10)

    return {"tool": "trivy", "scan_type": "repo", "target": f"{req.repo_url}@{req.branch}",
            "finding_count": len(findings), "findings": findings, "scanned_at": _now(),
            "repo": req.repo_url, "branch": req.branch}
