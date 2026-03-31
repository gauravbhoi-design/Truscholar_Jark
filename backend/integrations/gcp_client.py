"""
AI DevOps Platform — GCP Integration

Google Cloud Platform integration for:
- Listing Cloud Run services
- GKE cluster info
- Compute instances
- Billing/cost data
"""

import logging
import subprocess
import json
from typing import List, Dict, Any, Optional

from config import settings

logger = logging.getLogger(__name__)


class GCPClient:
    def __init__(self):
        self.project_id = settings.gcp_project_id
        self.region = settings.gcp_region

    @property
    def is_connected(self) -> bool:
        return bool(self.project_id)

    def _run_gcloud(self, args: List[str], format_json: bool = True) -> Optional[Any]:
        """Run a gcloud CLI command and return parsed output."""
        cmd = ["gcloud"] + args + ["--project", self.project_id]
        if format_json:
            cmd += ["--format", "json"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.error(f"gcloud error: {result.stderr[:200]}")
                return None
            if format_json and result.stdout.strip():
                return json.loads(result.stdout)
            return result.stdout
        except FileNotFoundError:
            logger.warning("gcloud CLI not found — GCP features disabled")
            return None
        except subprocess.TimeoutExpired:
            logger.error("gcloud command timed out")
            return None
        except Exception as e:
            logger.error(f"gcloud error: {e}")
            return None

    # ── Cloud Run ──────────────────────────────────────────────

    async def list_cloud_run_services(self, region: str = None) -> List[Dict[str, Any]]:
        """List Cloud Run services."""
        args = ["run", "services", "list"]
        if region:
            args += ["--region", region]
        else:
            args += ["--platform", "managed"]

        data = self._run_gcloud(args)
        if not data:
            return []

        services = []
        for svc in data:
            meta = svc.get("metadata", {})
            status_obj = svc.get("status", {})
            spec = svc.get("spec", {}).get("template", {}).get("spec", {})
            container = spec.get("containers", [{}])[0] if spec.get("containers") else {}
            resources = container.get("resources", {}).get("limits", {})

            services.append({
                "name": meta.get("name", ""),
                "service_type": "cloud_run",
                "region": meta.get("labels", {}).get("cloud.googleapis.com/location", region or self.region),
                "status": "running" if status_obj.get("conditions", [{}])[-1].get("status") == "True" else "error",
                "url": status_obj.get("url", ""),
                "cpu": resources.get("cpu", "1"),
                "memory": resources.get("memory", "512Mi"),
                "last_deployed": meta.get("creationTimestamp", ""),
                "project": self.project_id,
            })
        return services

    # ── GKE ────────────────────────────────────────────────────

    async def list_gke_clusters(self) -> List[Dict[str, Any]]:
        data = self._run_gcloud(["container", "clusters", "list"])
        if not data:
            return []
        return [
            {
                "name": c.get("name", ""),
                "location": c.get("location", ""),
                "status": c.get("status", "").lower(),
                "node_count": c.get("currentNodeCount", 0),
                "version": c.get("currentMasterVersion", ""),
            }
            for c in data
        ]

    # ── Compute Instances ──────────────────────────────────────

    async def list_instances(self) -> List[Dict[str, Any]]:
        data = self._run_gcloud(["compute", "instances", "list"])
        if not data:
            return []
        return [
            {
                "name": i.get("name", ""),
                "zone": i.get("zone", "").split("/")[-1],
                "status": i.get("status", "").lower(),
                "machine_type": i.get("machineType", "").split("/")[-1],
                "ip": i.get("networkInterfaces", [{}])[0].get("accessConfigs", [{}])[0].get("natIP", ""),
            }
            for i in data
        ]

    # ── Combined Service List ──────────────────────────────────

    async def list_all_services(self) -> List[Dict[str, Any]]:
        """Get all GCP services (Cloud Run + GKE + Compute)."""
        services = []

        cr = await self.list_cloud_run_services()
        services.extend(cr)

        clusters = await self.list_gke_clusters()
        for c in clusters:
            services.append({
                "name": c["name"],
                "service_type": "gke",
                "region": c["location"],
                "status": c["status"],
                "url": "",
                "cpu": f"{c['node_count']} nodes",
                "memory": c["version"],
                "project": self.project_id,
            })

        instances = await self.list_instances()
        for i in instances:
            services.append({
                "name": i["name"],
                "service_type": "compute",
                "region": i["zone"],
                "status": i["status"],
                "url": i.get("ip", ""),
                "cpu": i["machine_type"],
                "memory": "",
                "project": self.project_id,
            })

        return services

    async def get_project_info(self) -> Dict[str, Any]:
        """Get project metadata."""
        if not self.project_id:
            return {}
        data = self._run_gcloud(["projects", "describe", self.project_id])
        if data:
            return {
                "project_id": data.get("projectId", ""),
                "name": data.get("name", ""),
                "state": data.get("lifecycleState", ""),
            }
        return {"project_id": self.project_id}


gcp_client = GCPClient()
