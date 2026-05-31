"""
Kubernetes Tool - reads and mutates Kubernetes resources through the Python client.

The tool prefers an in-cluster service account, then a local kubeconfig. When no
cluster is reachable, it returns stable demo data and clearly marks writes as
simulated.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

HAS_K8S = False
try:
    from kubernetes import client, config

    HAS_K8S = True
except ImportError:
    client = None
    config = None
    logger.warning(
        "kubernetes python package not installed. Running in mock-only mode."
    )


MOCK_PODS: List[Dict[str, Any]] = [
    {
        "name": "web-frontend-service-6f8d8b9d-a1b2",
        "status": "Running",
        "ip": "10.244.1.15",
        "created_at": "2026-05-30T10:00:00Z",
        "restart_count": 0,
    },
    {
        "name": "payment-api-service-7d88c44f-c3d4",
        "status": "Running",
        "ip": "10.244.1.16",
        "created_at": "2026-05-30T10:05:00Z",
        "restart_count": 1,
    },
    {
        "name": "postgres-db-0",
        "status": "Running",
        "ip": "10.244.2.5",
        "created_at": "2026-05-30T09:00:00Z",
        "restart_count": 0,
    },
    {
        "name": "background-worker-5bc77dfd-x9y0",
        "status": "Pending",
        "ip": None,
        "created_at": "2026-05-31T00:10:00Z",
        "restart_count": 0,
    },
    {
        "name": "auth-gateway-service-84f9b8c2-m4n5",
        "status": "Running",
        "ip": "10.244.1.18",
        "created_at": "2026-05-30T11:20:00Z",
        "restart_count": 4,
    },
]

MOCK_EVENTS: List[Dict[str, Any]] = [
    {
        "reason": "FailedScheduling",
        "message": "0/3 nodes are available: 3 Insufficient memory.",
        "type": "Warning",
        "object": "background-worker-5bc77dfd-x9y0",
        "timestamp": "2026-05-31T00:10:15Z",
    },
    {
        "reason": "BackOff",
        "message": (
            "Back-off restarting failed container auth-gateway in pod "
            "auth-gateway-service-84f9b8c2-m4n5_default"
        ),
        "type": "Warning",
        "object": "auth-gateway-service-84f9b8c2-m4n5",
        "timestamp": "2026-05-31T00:14:05Z",
    },
    {
        "reason": "OOMKilling",
        "message": (
            "System OOM killer invoked for process 4220 (java) - Limit reached "
            "for container payment-api"
        ),
        "type": "Critical",
        "object": "payment-api-service-7d88c44f-c3d4",
        "timestamp": "2026-05-31T00:22:10Z",
    },
]

K8S_RESOURCE_NAME = re.compile(r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$")


class K8sTool:
    """Kubernetes API adapter with explicit real-cluster and demo modes."""

    def __init__(
        self,
        core_api: Optional[Any] = None,
        apps_api: Optional[Any] = None,
    ):
        self.use_real_k8s = False
        self.connection_source = "mock"
        self._core_api = core_api
        self._apps_api = apps_api

        if core_api is not None or apps_api is not None:
            if core_api is None or apps_api is None:
                raise ValueError(
                    "Both core_api and apps_api are required for injected clients"
                )
            self.use_real_k8s = True
            self.connection_source = "injected"
            return

        self._configure_real_client()

    def _configure_real_client(self) -> None:
        """Load Kubernetes credentials and confirm the API server is reachable."""
        if not HAS_K8S:
            return

        loaders = (
            ("in-cluster", config.load_incluster_config),
            ("kubeconfig", config.load_kube_config),
        )
        errors = []
        for source, loader in loaders:
            try:
                loader()
                client.VersionApi().get_code(_request_timeout=3)
                self._core_api = client.CoreV1Api()
                self._apps_api = client.AppsV1Api()
                self.use_real_k8s = True
                self.connection_source = source
                logger.info("Connected to Kubernetes using %s configuration.", source)
                return
            except Exception as exc:
                errors.append(f"{source}: {exc}")

        logger.warning(
            "Could not connect to a Kubernetes cluster. Using mock fallback. Attempts: %s",
            "; ".join(errors),
        )

    def get_pods(self, namespace: str = "default") -> List[Dict[str, Any]]:
        """Get pods with status and restart metrics."""
        self._validate_name(namespace, "namespace")
        if self.use_real_k8s:
            try:
                pods = self._core_api.list_namespaced_pod(namespace)
                return [
                    {
                        "name": pod.metadata.name,
                        "status": pod.status.phase,
                        "ip": pod.status.pod_ip,
                        "created_at": (
                            pod.metadata.creation_timestamp.isoformat()
                            if pod.metadata.creation_timestamp
                            else None
                        ),
                        "restart_count": sum(
                            container.restart_count
                            for container in (pod.status.container_statuses or [])
                        ),
                    }
                    for pod in pods.items
                ]
            except Exception as exc:
                logger.error(
                    "Error fetching real Kubernetes pods: %s. Using mock fallback.", exc
                )

        return [dict(pod) for pod in MOCK_PODS]

    def get_pod_logs(
        self,
        pod_name: str,
        namespace: str = "default",
        tail_lines: int = 50,
    ) -> str:
        """Get logs for a pod."""
        self._validate_name(pod_name, "pod_name")
        self._validate_name(namespace, "namespace")
        if tail_lines < 1:
            raise ValueError("tail_lines must be greater than zero")

        if self.use_real_k8s:
            try:
                return self._core_api.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=tail_lines,
                )
            except Exception as exc:
                logger.error(
                    "Error fetching real logs for %s: %s. Using mock fallback.",
                    pod_name,
                    exc,
                )

        if "payment-api" in pod_name:
            return (
                "[2026-05-31 00:15:02] INFO  Hibernate ORM core version 6.2.7.Final\n"
                "[2026-05-31 00:20:45] WARN  Transaction request took too long (3500ms)\n"
                "[2026-05-31 00:21:10] ERROR Connection pool exhausted\n"
                "java.sql.SQLTransientConnectionException: Connection timed out after 30000ms.\n"
                "*** SYSTEM ALERT: CRITICAL DB_TIMEOUT DETECTED ***"
            )
        if "auth-gateway" in pod_name:
            return (
                "[2026-05-31 00:10:00] INFO  Starting Auth Gateway on port 8001\n"
                "[2026-05-31 00:12:30] WARN  High memory utilization detected: 89%\n"
                "[2026-05-31 00:13:45] ERROR java.lang.OutOfMemoryError: Java heap space\n"
                "[2026-05-31 00:14:02] INFO  Kubelet restarting degraded container auth-gateway"
            )
        return (
            f"[2026-05-31 00:10:00] INFO  Starting container {pod_name} successfully\n"
            "[2026-05-31 00:15:00] INFO  Service health-check endpoint /health returned 200 OK\n"
            "[2026-05-31 00:20:00] INFO  Processing background polling tasks... idle state."
        )

    def get_events(self, namespace: str = "default") -> List[Dict[str, Any]]:
        """Get Kubernetes events in a namespace."""
        self._validate_name(namespace, "namespace")
        if self.use_real_k8s:
            try:
                events = self._core_api.list_namespaced_event(namespace)
                return [
                    {
                        "reason": event.reason,
                        "message": event.message,
                        "type": event.type,
                        "object": (
                            event.involved_object.name
                            if event.involved_object
                            else None
                        ),
                        "timestamp": (
                            event.last_timestamp.isoformat()
                            if event.last_timestamp
                            else None
                        ),
                    }
                    for event in events.items
                ]
            except Exception as exc:
                logger.error(
                    "Error fetching real Kubernetes events: %s. Using mock fallback.",
                    exc,
                )

        return [dict(event) for event in MOCK_EVENTS]

    def describe_pod(self, pod_name: str, namespace: str = "default") -> Dict[str, Any]:
        """Get a read-only pod summary suitable for incident analysis."""
        self._validate_name(pod_name, "pod_name")
        self._validate_name(namespace, "namespace")
        if self.use_real_k8s:
            try:
                pod = self._core_api.read_namespaced_pod(
                    name=pod_name, namespace=namespace
                )
                statuses = {
                    status.name: status
                    for status in (pod.status.container_statuses or [])
                }
                return {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "status": pod.status.phase,
                    "ip": pod.status.pod_ip,
                    "node": pod.spec.node_name,
                    "labels": pod.metadata.labels or {},
                    "containers": [
                        {
                            "name": container.name,
                            "image": container.image,
                            "ready": statuses.get(container.name).ready
                            if statuses.get(container.name)
                            else False,
                            "restart_count": statuses.get(container.name).restart_count
                            if statuses.get(container.name)
                            else 0,
                        }
                        for container in pod.spec.containers
                    ],
                }
            except Exception as exc:
                logger.error(
                    "Error describing real pod %s: %s. Using mock fallback.",
                    pod_name,
                    exc,
                )

        pod = next((item for item in MOCK_PODS if item["name"] == pod_name), None)
        if pod is None:
            raise ValueError(
                f"Pod '{pod_name}' was not found in namespace '{namespace}'"
            )

        container_name = pod_name.split("-", 1)[0]
        return {
            **pod,
            "namespace": namespace,
            "node": "demo-worker-1",
            "labels": {"app": pod_name.split("-service", 1)[0]},
            "containers": [
                {
                    "name": container_name,
                    "image": f"demo/{container_name}:latest",
                    "ready": pod["status"] == "Running",
                    "restart_count": pod["restart_count"],
                }
            ],
        }

    def restart_deployment(
        self,
        deployment_name: str,
        namespace: str = "default",
    ) -> Dict[str, Any]:
        """Trigger a rolling restart by patching the deployment pod template."""
        self._validate_name(deployment_name, "deployment_name")
        self._validate_name(namespace, "namespace")
        restarted_at = datetime.now(timezone.utc).isoformat()
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": restarted_at,
                        }
                    }
                }
            }
        }
        return self._run_write(
            action="restart_deployment",
            target_type="deployment",
            target_name=deployment_name,
            namespace=namespace,
            operation=lambda: self._apps_api.patch_namespaced_deployment(
                name=deployment_name,
                namespace=namespace,
                body=body,
            ),
        )

    def scale_deployment(
        self,
        deployment_name: str,
        replicas: int,
        namespace: str = "default",
    ) -> Dict[str, Any]:
        """Set a deployment replica count."""
        self._validate_name(deployment_name, "deployment_name")
        self._validate_name(namespace, "namespace")
        if isinstance(replicas, bool) or not isinstance(replicas, int) or replicas < 0:
            raise ValueError("replicas must be a non-negative integer")

        return self._run_write(
            action="scale_deployment",
            target_type="deployment",
            target_name=deployment_name,
            namespace=namespace,
            operation=lambda: self._apps_api.patch_namespaced_deployment_scale(
                name=deployment_name,
                namespace=namespace,
                body={"spec": {"replicas": replicas}},
            ),
            details={"replicas": replicas},
        )

    def delete_pod(
        self,
        pod_name: str,
        namespace: str = "default",
    ) -> Dict[str, Any]:
        """Delete a pod and let its controller recreate it when applicable."""
        self._validate_name(pod_name, "pod_name")
        self._validate_name(namespace, "namespace")
        return self._run_write(
            action="delete_pod",
            target_type="pod",
            target_name=pod_name,
            namespace=namespace,
            operation=lambda: self._core_api.delete_namespaced_pod(
                name=pod_name,
                namespace=namespace,
            ),
        )

    def _run_write(
        self,
        action: str,
        target_type: str,
        target_name: str,
        namespace: str,
        operation: Callable[[], Any],
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = {
            "action": action,
            "target_type": target_type,
            "target": target_name,
            "namespace": namespace,
            **(details or {}),
        }
        if self.use_real_k8s:
            try:
                operation()
                return {
                    "success": True,
                    "mode": "real",
                    "applied": True,
                    **result,
                }
            except Exception as exc:
                logger.error(
                    "Real Kubernetes action %s failed for %s/%s: %s.",
                    action,
                    namespace,
                    target_name,
                    exc,
                )
                raise RuntimeError(
                    f"Kubernetes action {action} failed for {namespace}/{target_name}"
                ) from exc

        return {
            "success": True,
            "mode": "mock",
            "applied": False,
            "simulated": True,
            "message": "Kubernetes cluster unavailable; no live change was applied.",
            **result,
        }

    @staticmethod
    def _validate_name(value: str, field_name: str) -> None:
        if len(value) > 253 or not K8S_RESOURCE_NAME.fullmatch(value):
            raise ValueError(f"{field_name} must be a valid Kubernetes resource name")
