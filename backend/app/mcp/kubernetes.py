"""Kubernetes MCP Client — Pod status, deployments, logs via kubectl."""

import structlog

logger = structlog.get_logger()


class KubernetesMCPClient:
    """MCP-compatible client for Kubernetes operations."""

    def __init__(self):
        try:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()

            self.core_v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self._available = True
        except Exception as e:
            logger.warning("K8s client not available", error=str(e))
            self._available = False

    async def get_pods(
        self, namespace: str = "default", label_selector: str | None = None
    ) -> dict:
        """Get pod status in a namespace."""
        import asyncio

        if not self._available:
            return {"error": "Kubernetes client not configured"}

        def _get():
            kwargs = {"namespace": namespace}
            if label_selector:
                kwargs["label_selector"] = label_selector

            pods = self.core_v1.list_namespaced_pod(**kwargs)
            return {
                "namespace": namespace,
                "total_pods": len(pods.items),
                "pods": [
                    {
                        "name": pod.metadata.name,
                        "status": pod.status.phase,
                        "ready": all(
                            c.ready for c in (pod.status.container_statuses or [])
                        ),
                        "restarts": sum(
                            c.restart_count for c in (pod.status.container_statuses or [])
                        ),
                        "node": pod.spec.node_name,
                        "age": str(pod.metadata.creation_timestamp),
                        "containers": [
                            {
                                "name": c.name,
                                "ready": c.ready,
                                "restart_count": c.restart_count,
                                "state": (
                                    "running" if c.state.running
                                    else "waiting" if c.state.waiting
                                    else "terminated"
                                ),
                            }
                            for c in (pod.status.container_statuses or [])
                        ],
                    }
                    for pod in pods.items[:50]
                ],
            }

        return await asyncio.to_thread(_get)

    async def get_deployments(self, namespace: str = "default") -> dict:
        """Get deployment status."""
        import asyncio

        if not self._available:
            return {"error": "Kubernetes client not configured"}

        def _get():
            deps = self.apps_v1.list_namespaced_deployment(namespace=namespace)
            return {
                "namespace": namespace,
                "deployments": [
                    {
                        "name": d.metadata.name,
                        "replicas": d.spec.replicas,
                        "ready_replicas": d.status.ready_replicas or 0,
                        "available": d.status.available_replicas or 0,
                        "updated": d.status.updated_replicas or 0,
                        "conditions": [
                            {"type": c.type, "status": c.status, "message": c.message}
                            for c in (d.status.conditions or [])
                        ],
                    }
                    for d in deps.items
                ],
            }

        return await asyncio.to_thread(_get)

    async def get_pod_logs(
        self, name: str, namespace: str = "default", tail_lines: int = 100
    ) -> dict:
        """Get pod logs."""
        import asyncio

        if not self._available:
            return {"error": "Kubernetes client not configured"}

        def _get():
            try:
                logs = self.core_v1.read_namespaced_pod_log(
                    name=name, namespace=namespace, tail_lines=tail_lines
                )
                return {"pod": name, "namespace": namespace, "logs": logs}
            except Exception as e:
                return {"error": str(e), "pod": name}

        return await asyncio.to_thread(_get)
