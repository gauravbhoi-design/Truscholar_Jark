"""AWS MCP Client — CloudWatch, ECS, S3, Lambda integration via boto3."""

from datetime import UTC, datetime, timedelta

import structlog

logger = structlog.get_logger()


class AWSMCPClient:
    """MCP-compatible client for AWS cloud operations."""

    def __init__(self):
        import boto3

        from app.config import get_settings
        settings = get_settings()
        self.session = boto3.Session(
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
            region_name=settings.aws_region,
        )

    async def query_cloudwatch(
        self, log_group: str, filter_pattern: str = "", hours_back: int = 24
    ) -> dict:
        """Query CloudWatch logs."""
        import asyncio

        def _query():
            client = self.session.client("logs")
            end_time = int(datetime.now(UTC).timestamp() * 1000)
            start_time = int((datetime.now(UTC) - timedelta(hours=hours_back)).timestamp() * 1000)

            params = {
                "logGroupName": log_group,
                "startTime": start_time,
                "endTime": end_time,
                "limit": 100,
            }
            if filter_pattern:
                params["filterPattern"] = filter_pattern

            try:
                response = client.filter_log_events(**params)
                events = response.get("events", [])
                return {
                    "log_group": log_group,
                    "events_found": len(events),
                    "events": [
                        {
                            "timestamp": datetime.fromtimestamp(
                                e["timestamp"] / 1000, tz=UTC
                            ).isoformat(),
                            "message": e["message"][:500],
                            "log_stream": e.get("logStreamName", ""),
                        }
                        for e in events[:50]
                    ],
                }
            except Exception as e:
                return {"error": str(e), "log_group": log_group}

        return await asyncio.to_thread(_query)

    async def check_ecs_service(self, cluster: str, service: str) -> dict:
        """Check ECS service health."""
        import asyncio

        def _check():
            client = self.session.client("ecs")
            try:
                response = client.describe_services(cluster=cluster, services=[service])
                svc = response["services"][0] if response["services"] else {}
                return {
                    "service": service,
                    "cluster": cluster,
                    "status": svc.get("status"),
                    "running_count": svc.get("runningCount"),
                    "desired_count": svc.get("desiredCount"),
                    "pending_count": svc.get("pendingCount"),
                    "events": [
                        {"message": e["message"], "created_at": e["createdAt"].isoformat()}
                        for e in svc.get("events", [])[:10]
                    ],
                }
            except Exception as e:
                return {"error": str(e), "cluster": cluster, "service": service}

        return await asyncio.to_thread(_check)

    async def get_metrics(self, resource_id: str, metric_names: list[str]) -> dict:
        """Get CloudWatch metrics for a resource."""
        import asyncio

        def _get():
            client = self.session.client("cloudwatch")
            results = {}
            end_time = datetime.now(UTC)
            start_time = end_time - timedelta(hours=1)

            for metric in metric_names:
                try:
                    response = client.get_metric_statistics(
                        Namespace="AWS/ECS",
                        MetricName=metric,
                        Dimensions=[{"Name": "ServiceName", "Value": resource_id}],
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=300,
                        Statistics=["Average", "Maximum"],
                    )
                    datapoints = response.get("Datapoints", [])
                    results[metric] = {
                        "datapoints": len(datapoints),
                        "avg": round(sum(d.get("Average", 0) for d in datapoints) / max(len(datapoints), 1), 2),
                        "max": max((d.get("Maximum", 0) for d in datapoints), default=0),
                    }
                except Exception as e:
                    results[metric] = {"error": str(e)}

            return {"resource_id": resource_id, "metrics": results}

        return await asyncio.to_thread(_get)
