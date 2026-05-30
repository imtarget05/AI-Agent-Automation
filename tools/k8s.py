"""
Kubernetes Tool - interacts with Kubernetes API to retrieve pod lists, logs, and events.
Supports real cluster connection with a robust mock fallback for stable local demos.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Try to import kubernetes client
HAS_K8S = False
try:
    from kubernetes import client, config
    HAS_K8S = True
except ImportError:
    logger.warning("kubernetes python package not installed. Running in mock-only mode.")

class K8sTool:
    """Tool class for Kubernetes cluster operations"""

    def __init__(self):
        self.use_real_k8s = False
        if HAS_K8S:
            try:
                # Try incluster first, then fallback to kube_config
                try:
                    config.load_incluster_config()
                    self.use_real_k8s = True
                    logger.info("Loaded in-cluster Kubernetes config.")
                except Exception:
                    config.load_kube_config()
                    self.use_real_k8s = True
                    logger.info("Loaded local kubeconfig.")
            except Exception as e:
                logger.warning(f"Could not connect to real Kubernetes cluster: {e}. Falling back to simulated K8s environment.")

    def get_pods(self, namespace: str = "default") -> List[Dict[str, Any]]:
        """Get list of pods with status and resource metrics"""
        if self.use_real_k8s:
            try:
                v1 = client.CoreV1Api()
                pods = v1.list_namespaced_pod(namespace)
                return [
                    {
                        "name": pod.metadata.name,
                        "status": pod.status.phase,
                        "ip": pod.status.pod_ip,
                        "created_at": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None,
                        "restart_count": sum(c.restart_count for c in pod.status.container_statuses) if pod.status.container_statuses else 0
                    }
                    for pod in pods.items
                ]
            except Exception as e:
                logger.error(f"Error fetching real K8s pods: {e}. Using mock fallback.")
        
        # Simulated/Mock K8s Pods for stable demo
        return [
            {
                "name": "web-frontend-service-6f8d8b9d-a1b2",
                "status": "Running",
                "ip": "10.244.1.15",
                "created_at": "2026-05-30T10:00:00Z",
                "restart_count": 0
            },
            {
                "name": "payment-api-service-7d88c44f-c3d4",
                "status": "Running",
                "ip": "10.244.1.16",
                "created_at": "2026-05-30T10:05:00Z",
                "restart_count": 1
            },
            {
                "name": "postgres-db-0",
                "status": "Running",
                "ip": "10.244.2.5",
                "created_at": "2026-05-30T09:00:00Z",
                "restart_count": 0
            },
            {
                "name": "background-worker-5bc77dfd-x9y0",
                "status": "Pending",
                "ip": None,
                "created_at": "2026-05-31T00:10:00Z",
                "restart_count": 0
            },
            {
                "name": "auth-gateway-service-84f9b8c2-m4n5",
                "status": "Running",
                "ip": "10.244.1.18",
                "created_at": "2026-05-30T11:20:00Z",
                "restart_count": 4  # Degraded status / restarting
            }
        ]

    def get_pod_logs(self, pod_name: str, namespace: str = "default", tail_lines: int = 50) -> str:
        """Get logs of a specific pod"""
        if self.use_real_k8s:
            try:
                v1 = client.CoreV1Api()
                return v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail_lines=tail_lines)
            except Exception as e:
                logger.error(f"Error fetching real logs for {pod_name}: {e}. Using mock fallback.")

        # High-quality mock logs illustrating AIOps-resolvable issues
        if "payment-api" in pod_name:
            return (
                "[2026-05-31 00:15:02] INFO  [main] org.hibernate.Version: HHH000412: Hibernate ORM core version 6.2.7.Final\n"
                "[2026-05-31 00:15:10] INFO  [main] o.s.b.w.embedded.tomcat.TomcatWebServer: Tomcat initialized with port(s): 8080 (http)\n"
                "[2026-05-31 00:15:12] INFO  [main] c.a.payment.PaymentApplication: Started PaymentApplication in 12.4 seconds\n"
                "[2026-05-31 00:20:45] WARN  [http-nio-8080-exec-3] c.a.payment.web.PaymentController: Transaction request took too long (3500ms)\n"
                "[2026-05-31 00:21:10] ERROR [http-nio-8080-exec-5] c.a.payment.db.ConnectionPool: Connection pool exhausted. Waiting for database connection...\n"
                "[2026-05-31 00:21:25] ERROR [http-nio-8080-exec-5] o.a.c.c.C.[Tomcat].[localhost]: Servlet.service() for servlet [dispatcherServlet] threw exception\n"
                "java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 30000ms.\n"
                "\tat com.zaxxer.hikari.pool.HikariPool.createTimeoutException(HikariPool.java:696)\n"
                "\tat com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:197)\n"
                "\tat com.zaxxer.hikari.pool.HikariProxyConnection.getDelegate(HikariProxyConnection.java:31)\n"
                "*** SYSTEM ALERT: CRITICAL DB_TIMEOUT DETECTED ***"
            )
        elif "auth-gateway" in pod_name:
            return (
                "[2026-05-31 00:10:00] INFO  Starting Auth Gateway on port 8001\n"
                "[2026-05-31 00:12:30] WARN  High memory utilization detected: 89% threshold crossed\n"
                "[2026-05-31 00:13:45] ERROR java.lang.OutOfMemoryError: Java heap space\n"
                "  at java.util.Arrays.copyOf(Arrays.java:3332)\n"
                "  at java.lang.AbstractStringBuilder.ensureCapacityInternal(AbstractStringBuilder.java:124)\n"
                "  at java.lang.AbstractStringBuilder.append(AbstractStringBuilder.java:448)\n"
                "  at java.lang.StringBuilder.append(StringBuilder.java:136)\n"
                "[2026-05-31 00:14:02] INFO  Kubelet restarting degraded container auth-gateway"
            )
        else:
            return (
                f"[2026-05-31 00:10:00] INFO  Starting container {pod_name} successfully\n"
                f"[2026-05-31 00:15:00] INFO  Service health-check endpoint /health returned 200 OK\n"
                f"[2026-05-31 00:20:00] INFO  Processing background polling tasks... idle state."
            )

    def get_events(self, namespace: str = "default") -> List[Dict[str, Any]]:
        """Get Kubernetes events in the namespace"""
        if self.use_real_k8s:
            try:
                v1 = client.CoreV1Api()
                events = v1.list_namespaced_event(namespace)
                return [
                    {
                        "reason": event.reason,
                        "message": event.message,
                        "type": event.type,
                        "object": event.involved_object.name if event.involved_object else None,
                        "timestamp": event.last_timestamp.isoformat() if event.last_timestamp else None
                    }
                    for event in events.items
                ]
            except Exception as e:
                logger.error(f"Error fetching real K8s events: {e}. Using mock fallback.")

        # High-quality mock events to feed into the Prometheus Alert loop
        return [
            {
                "reason": "FailedScheduling",
                "message": "0/3 nodes are available: 3 Insufficient memory.",
                "type": "Warning",
                "object": "background-worker-5bc77dfd-x9y0",
                "timestamp": "2026-05-31T00:10:15Z"
            },
            {
                "reason": "BackOff",
                "message": "Back-off restarting failed container auth-gateway in pod auth-gateway-service-84f9b8c2-m4n5_default",
                "type": "Warning",
                "object": "auth-gateway-service-84f9b8c2-m4n5",
                "timestamp": "2026-05-31T00:14:05Z"
            },
            {
                "reason": "OOMKilling",
                "message": "System OOM killer invoked for process 4220 (java) - Limit reached for container payment-api",
                "type": "Critical",
                "object": "payment-api-service-7d88c44f-c3d4",
                "timestamp": "2026-05-31T00:22:10Z"
            }
        ]
