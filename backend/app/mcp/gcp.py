"""GCP MCP Client — Cloud Logging, Cloud Monitoring integration.

Supports two modes:
1. System credentials (service account) — for Vertex AI, admin tasks
2. Per-user OAuth credentials — for accessing USER's GCP project
"""

from datetime import UTC

import structlog

logger = structlog.get_logger()


class GCPMCPClient:
    """MCP-compatible client for GCP cloud operations.

    Args:
        user_access_token: OAuth2 access token from user's GCP connection.
                          If provided, uses user's project. Otherwise falls back
                          to system service account.
        project_id: Override the GCP project ID. If not set, uses settings default.
    """

    def __init__(self, user_access_token: str | None = None, project_id: str | None = None):
        from app.config import get_settings
        self.settings = get_settings()
        self._user_token = user_access_token
        self._project_id = project_id or self.settings.gcp_project_id

    def _get_logging_client(self):
        """Create a Cloud Logging client with appropriate credentials."""
        from google.cloud import logging as cloud_logging

        if self._user_token:
            from google.oauth2.credentials import Credentials
            creds = Credentials(token=self._user_token)
            return cloud_logging.Client(project=self._project_id, credentials=creds)
        else:
            return cloud_logging.Client(project=self._project_id)

    def _get_monitoring_client(self):
        """Create a Cloud Monitoring client with appropriate credentials."""
        from google.cloud import monitoring_v3

        if self._user_token:
            from google.oauth2.credentials import Credentials
            creds = Credentials(token=self._user_token)
            return monitoring_v3.MetricServiceClient(credentials=creds)
        else:
            return monitoring_v3.MetricServiceClient()

    async def query_logs(
        self, project_id: str, filter_query: str, hours_back: int = 24
    ) -> dict:
        """Query GCP Cloud Logging."""
        import asyncio
        from datetime import datetime, timedelta

        # Use the project_id from the tool call, or fall back to configured one
        target_project = project_id or self._project_id

        def _query():
            try:
                client = self._get_logging_client()
                end_time = datetime.now(UTC)
                start_time = end_time - timedelta(hours=hours_back)

                full_filter = (
                    f'timestamp >= "{start_time.isoformat()}" '
                    f'AND timestamp <= "{end_time.isoformat()}" '
                    f"AND {filter_query}"
                )

                entries = list(client.list_entries(
                    resource_names=[f"projects/{target_project}"],
                    filter_=full_filter,
                    max_results=50,
                ))
                return {
                    "project_id": target_project,
                    "events_found": len(entries),
                    "events": [
                        {
                            "timestamp": str(e.timestamp),
                            "severity": e.severity,
                            "message": str(e.payload)[:500],
                            "resource": str(e.resource.type) if e.resource else "",
                        }
                        for e in entries
                    ],
                }
            except ImportError:
                return {
                    "error": "google-cloud-logging not installed",
                    "project_id": target_project,
                    "suggestion": "pip install google-cloud-logging",
                }
            except Exception as e:
                return {"error": str(e), "project_id": target_project}

        return await asyncio.to_thread(_query)

    async def get_metrics(self, resource_id: str, metric_names: list[str]) -> dict:
        """Get GCP Cloud Monitoring metrics."""
        import asyncio

        def _get():
            try:
                from datetime import datetime, timedelta

                from google.cloud import monitoring_v3
                from google.protobuf.timestamp_pb2 import Timestamp

                client = self._get_monitoring_client()
                project_name = f"projects/{self._project_id}"

                now = datetime.now(UTC)
                results = {}

                for metric in metric_names:
                    interval = monitoring_v3.TimeInterval(
                        end_time=Timestamp(seconds=int(now.timestamp())),
                        start_time=Timestamp(seconds=int((now - timedelta(hours=1)).timestamp())),
                    )
                    try:
                        time_series = client.list_time_series(
                            request={
                                "name": project_name,
                                "filter": f'metric.type = "compute.googleapis.com/instance/{metric}"'
                                          f' AND resource.labels.instance_id = "{resource_id}"',
                                "interval": interval,
                            }
                        )
                        points = []
                        for ts in time_series:
                            for point in ts.points:
                                points.append(point.value.double_value)

                        results[metric] = {
                            "datapoints": len(points),
                            "avg": round(sum(points) / max(len(points), 1), 2),
                            "max": max(points, default=0),
                        }
                    except Exception as e:
                        results[metric] = {"error": str(e)}

                return {"resource_id": resource_id, "metrics": results}

            except ImportError:
                return {"error": "google-cloud-monitoring not installed"}

        return await asyncio.to_thread(_get)

    def _api_get(self, url: str, params: dict | None = None) -> dict:
        """Make an authenticated GET request to a GCP REST API."""
        import httpx
        if not self._user_token:
            return {"error": "User GCP token required. Please connect your GCP project in Settings."}
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {self._user_token}"},
            params=params or {},
            timeout=15,
        )
        if resp.status_code == 403:
            return {"error": f"Permission denied. Enable the required API and grant roles. Status: {resp.status_code}"}
        if resp.status_code != 200:
            return {"error": f"API error {resp.status_code}: {resp.text[:200]}"}
        return resp.json()

    async def list_enabled_apis(self, project_id: str | None = None) -> dict:
        """List all enabled APIs/services in the GCP project."""
        import asyncio
        target = project_id or self._project_id

        def _list():
            url = f"https://serviceusage.googleapis.com/v1/projects/{target}/services"
            result = self._api_get(url, {"filter": "state:ENABLED", "pageSize": "200"})
            if "error" in result:
                return result
            services = [
                {
                    "name": s.get("config", {}).get("title", s["name"].split("/")[-1]),
                    "service_id": s["name"].split("/")[-1],
                    "state": s.get("state", ""),
                }
                for s in result.get("services", [])
            ]
            return {"project_id": target, "enabled_services": len(services), "services": services}

        return await asyncio.to_thread(_list)

    async def list_compute_instances(self, project_id: str | None = None) -> dict:
        """List Compute Engine VM instances across all zones."""
        import asyncio
        target = project_id or self._project_id

        def _list():
            url = f"https://compute.googleapis.com/compute/v1/projects/{target}/aggregated/instances"
            result = self._api_get(url)
            if "error" in result:
                return result
            instances = []
            for zone_data in result.get("items", {}).values():
                for inst in zone_data.get("instances", []):
                    instances.append({
                        "name": inst["name"],
                        "zone": inst.get("zone", "").split("/")[-1],
                        "status": inst.get("status", ""),
                        "machine_type": inst.get("machineType", "").split("/")[-1],
                        "created": inst.get("creationTimestamp", ""),
                    })
            return {"project_id": target, "total_instances": len(instances), "instances": instances}

        return await asyncio.to_thread(_list)

    async def list_cloud_run_services(self, project_id: str | None = None, region: str = "-") -> dict:
        """List Cloud Run services."""
        import asyncio
        target = project_id or self._project_id

        def _list():
            url = f"https://run.googleapis.com/v2/projects/{target}/locations/{region}/services"
            result = self._api_get(url)
            if "error" in result:
                return result
            services = [
                {
                    "name": s.get("name", "").split("/")[-1],
                    "uri": s.get("uri", ""),
                    "region": s.get("name", "").split("/")[3] if "/" in s.get("name", "") else "",
                    "ingress": s.get("ingress", ""),
                    "last_modifier": s.get("lastModifier", ""),
                    "create_time": s.get("createTime", ""),
                    "update_time": s.get("updateTime", ""),
                }
                for s in result.get("services", [])
            ]
            return {"project_id": target, "total_services": len(services), "services": services}

        return await asyncio.to_thread(_list)

    async def list_gke_clusters(self, project_id: str | None = None) -> dict:
        """List GKE (Kubernetes Engine) clusters."""
        import asyncio
        target = project_id or self._project_id

        def _list():
            url = f"https://container.googleapis.com/v1/projects/{target}/locations/-/clusters"
            result = self._api_get(url)
            if "error" in result:
                return result
            clusters = [
                {
                    "name": c["name"],
                    "location": c.get("location", ""),
                    "status": c.get("status", ""),
                    "node_count": c.get("currentNodeCount", 0),
                    "version": c.get("currentMasterVersion", ""),
                    "endpoint": c.get("endpoint", ""),
                }
                for c in result.get("clusters", [])
            ]
            return {"project_id": target, "total_clusters": len(clusters), "clusters": clusters}

        return await asyncio.to_thread(_list)

    async def list_cloud_functions(self, project_id: str | None = None) -> dict:
        """List Cloud Functions (v2)."""
        import asyncio
        target = project_id or self._project_id

        def _list():
            url = f"https://cloudfunctions.googleapis.com/v2/projects/{target}/locations/-/functions"
            result = self._api_get(url)
            if "error" in result:
                return result
            functions = [
                {
                    "name": f.get("name", "").split("/")[-1],
                    "state": f.get("state", ""),
                    "runtime": f.get("buildConfig", {}).get("runtime", ""),
                    "region": f.get("name", "").split("/")[3] if "/" in f.get("name", "") else "",
                    "update_time": f.get("updateTime", ""),
                }
                for f in result.get("functions", [])
            ]
            return {"project_id": target, "total_functions": len(functions), "functions": functions}

        return await asyncio.to_thread(_list)

    async def list_app_engine_services(self, project_id: str | None = None) -> dict:
        """List App Engine services."""
        import asyncio
        target = project_id or self._project_id

        def _list():
            url = f"https://appengine.googleapis.com/v1/apps/{target}/services"
            result = self._api_get(url)
            if "error" in result:
                return result
            services = [
                {
                    "name": s.get("id", ""),
                    "split": s.get("split", {}),
                }
                for s in result.get("services", [])
            ]
            return {"project_id": target, "total_services": len(services), "services": services}

        return await asyncio.to_thread(_list)

    async def tail_logs(
        self,
        project_id: str | None = None,
        resource_type: str | None = None,
        service_name: str | None = None,
        severity: str = "DEFAULT",
        custom_filter: str | None = None,
    ):
        """Stream live logs from Cloud Logging using the Tail API.

        Yields log entries as they arrive in real-time.
        This is an async generator — use `async for entry in client.tail_logs():`.
        """
        from google.cloud.logging_v2.services.logging_service_v2 import LoggingServiceV2AsyncClient
        from google.cloud.logging_v2.types import TailLogEntriesRequest
        from google.oauth2.credentials import Credentials

        target = project_id or self._project_id

        # Build filter
        filters = []
        if severity and severity != "DEFAULT":
            filters.append(f"severity>={severity}")
        if resource_type:
            filters.append(f'resource.type="{resource_type}"')
        if service_name:
            filters.append(f'(resource.labels.service_name="{service_name}" OR resource.labels.configuration_name="{service_name}" OR textPayload:"{service_name}")')
        if custom_filter:
            filters.append(custom_filter)

        filter_str = " AND ".join(filters) if filters else ""

        # Create gRPC client with user's credentials
        if self._user_token:
            creds = Credentials(token=self._user_token)
            client = LoggingServiceV2AsyncClient(credentials=creds)
        else:
            client = LoggingServiceV2AsyncClient()

        # Build the request generator
        async def request_generator():
            yield TailLogEntriesRequest(
                resource_names=[f"projects/{target}"],
                filter=filter_str,
            )

        try:
            response_stream = await client.tail_log_entries(requests=request_generator())

            async for response in response_stream:
                for entry in response.entries:
                    # Format the log entry
                    payload = ""
                    if entry.text_payload:
                        payload = entry.text_payload
                    elif entry.json_payload:
                        import json
                        payload = json.dumps(dict(entry.json_payload), default=str)[:500]
                    elif entry.proto_payload:
                        payload = str(entry.proto_payload)[:500]

                    yield {
                        "timestamp": entry.timestamp.isoformat() if entry.timestamp else "",
                        "severity": entry.severity.name if entry.severity else "DEFAULT",
                        "message": payload[:500],
                        "resource_type": entry.resource.type if entry.resource else "",
                        "resource_labels": dict(entry.resource.labels) if entry.resource else {},
                        "log_name": entry.log_name.split("/")[-1] if entry.log_name else "",
                        "insert_id": entry.insert_id or "",
                    }

        except Exception as e:
            yield {"error": str(e)}

    async def tail_logs_rest(
        self,
        project_id: str | None = None,
        filter_query: str = "",
        duration_seconds: int = 60,
    ):
        """Poll-based log tailing using REST API (fallback if gRPC doesn't work).

        Polls every 2 seconds for new log entries.
        """
        import asyncio
        from datetime import datetime, timedelta

        import httpx

        target = project_id or self._project_id
        if not self._user_token:
            yield {"error": "User GCP token required"}
            return

        start_time = datetime.now(UTC)
        end_time = start_time + timedelta(seconds=duration_seconds)
        seen_ids = set()
        poll_from = start_time - timedelta(seconds=5)

        while datetime.now(UTC) < end_time:
            try:
                full_filter = f'timestamp>="{poll_from.isoformat()}"'
                if filter_query:
                    full_filter += f" AND {filter_query}"

                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        "https://logging.googleapis.com/v2/entries:list",
                        headers={"Authorization": f"Bearer {self._user_token}"},
                        json={
                            "resourceNames": [f"projects/{target}"],
                            "filter": full_filter,
                            "orderBy": "timestamp desc",
                            "pageSize": 20,
                        },
                    )

                if resp.status_code == 200:
                    entries = resp.json().get("entries", [])
                    # Reverse to get chronological order
                    for entry in reversed(entries):
                        insert_id = entry.get("insertId", "")
                        if insert_id in seen_ids:
                            continue
                        seen_ids.add(insert_id)

                        payload = entry.get("textPayload", "")
                        if not payload and entry.get("jsonPayload"):
                            import json
                            payload = json.dumps(entry["jsonPayload"], default=str)[:500]

                        yield {
                            "timestamp": entry.get("timestamp", ""),
                            "severity": entry.get("severity", "DEFAULT"),
                            "message": payload[:500],
                            "resource_type": entry.get("resource", {}).get("type", ""),
                            "resource_labels": entry.get("resource", {}).get("labels", {}),
                            "log_name": entry.get("logName", "").split("/")[-1],
                            "insert_id": insert_id,
                        }

                        # Move the poll cursor forward
                        ts = entry.get("timestamp", "")
                        if ts:
                            poll_from = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                elif resp.status_code == 403:
                    yield {"error": "Permission denied — ensure Cloud Logging API is enabled"}
                    return
                else:
                    yield {"error": f"API error: {resp.status_code}"}

            except Exception as e:
                yield {"error": f"Poll error: {str(e)}"}

            await asyncio.sleep(2)

        yield {"done": True, "message": "Log stream ended"}

    async def list_projects(self) -> dict:
        """List GCP projects accessible by the user."""
        import asyncio

        def _list():
            try:
                if not self._user_token:
                    return {"error": "User token required to list projects"}

                import httpx
                resp = httpx.get(
                    "https://cloudresourcemanager.googleapis.com/v1/projects",
                    headers={"Authorization": f"Bearer {self._user_token}"},
                    params={"filter": "lifecycleState:ACTIVE"},
                )
                if resp.status_code != 200:
                    return {"error": f"API error: {resp.status_code}"}

                projects = [
                    {"id": p["projectId"], "name": p.get("name", p["projectId"])}
                    for p in resp.json().get("projects", [])
                ]
                return {"projects": projects, "count": len(projects)}
            except Exception as e:
                return {"error": str(e)}

        return await asyncio.to_thread(_list)
