import asyncio
from types import SimpleNamespace

import httpx
import pytest

import tools.k8s as k8s_module
import tools.prometheus as prometheus_module


class FakeCoreApi:
    def __init__(self):
        self.calls = []

    def delete_namespaced_pod(self, **kwargs):
        self.calls.append(("delete_namespaced_pod", kwargs))


class FakeAppsApi:
    def __init__(self):
        self.calls = []

    def patch_namespaced_deployment(self, **kwargs):
        self.calls.append(("patch_namespaced_deployment", kwargs))

    def patch_namespaced_deployment_scale(self, **kwargs):
        self.calls.append(("patch_namespaced_deployment_scale", kwargs))


def test_k8s_prefers_incluster_config_and_probes_api(monkeypatch):
    calls = []
    core_api = FakeCoreApi()
    apps_api = FakeAppsApi()

    class VersionApi:
        def get_code(self, **kwargs):
            calls.append(("probe", kwargs))

    fake_config = SimpleNamespace(
        load_incluster_config=lambda: calls.append(("in-cluster", {})),
        load_kube_config=lambda: calls.append(("kubeconfig", {})),
    )
    fake_client = SimpleNamespace(
        VersionApi=VersionApi,
        CoreV1Api=lambda: core_api,
        AppsV1Api=lambda: apps_api,
    )
    monkeypatch.setattr(k8s_module, "HAS_K8S", True)
    monkeypatch.setattr(k8s_module, "config", fake_config)
    monkeypatch.setattr(k8s_module, "client", fake_client)

    tool = k8s_module.K8sTool()

    assert tool.use_real_k8s is True
    assert tool.connection_source == "in-cluster"
    assert calls == [("in-cluster", {}), ("probe", {"_request_timeout": 3})]


def test_k8s_uses_kubeconfig_after_incluster_failure(monkeypatch):
    calls = []

    def fail_incluster():
        calls.append("in-cluster")
        raise RuntimeError("not running in cluster")

    class VersionApi:
        def get_code(self, **kwargs):
            calls.append("probe")

    fake_config = SimpleNamespace(
        load_incluster_config=fail_incluster,
        load_kube_config=lambda: calls.append("kubeconfig"),
    )
    fake_client = SimpleNamespace(
        VersionApi=VersionApi,
        CoreV1Api=FakeCoreApi,
        AppsV1Api=FakeAppsApi,
    )
    monkeypatch.setattr(k8s_module, "HAS_K8S", True)
    monkeypatch.setattr(k8s_module, "config", fake_config)
    monkeypatch.setattr(k8s_module, "client", fake_client)

    tool = k8s_module.K8sTool()

    assert tool.use_real_k8s is True
    assert tool.connection_source == "kubeconfig"
    assert calls == ["in-cluster", "kubeconfig", "probe"]


def test_k8s_unavailable_cluster_returns_stable_demo_data(monkeypatch):
    monkeypatch.setattr(k8s_module, "HAS_K8S", False)

    tool = k8s_module.K8sTool()

    assert tool.use_real_k8s is False
    assert tool.get_pods() == tool.get_pods()
    assert tool.get_events() == tool.get_events()
    assert tool.restart_deployment("payment-api") == tool.restart_deployment(
        "payment-api"
    )
    assert tool.restart_deployment("payment-api")["applied"] is False


def test_k8s_write_actions_use_python_client_when_connected():
    core_api = FakeCoreApi()
    apps_api = FakeAppsApi()
    tool = k8s_module.K8sTool(core_api=core_api, apps_api=apps_api)

    restart = tool.restart_deployment("payment-api", namespace="prod")
    _ = tool.scale_deployment("payment-api", replicas=4, namespace="prod")
    delete = tool.delete_pod("payment-api-abc", namespace="prod")

    assert restart["mode"] == "real"
    assert restart["applied"] is True
    assert apps_api.calls[0][1]["body"]["spec"]["template"]["metadata"]["annotations"][
        "kubectl.kubernetes.io/restartedAt"
    ]
    assert apps_api.calls[1] == (
        "patch_namespaced_deployment_scale",
        {
            "name": "payment-api",
            "namespace": "prod",
            "body": {"spec": {"replicas": 4}},
        },
    )
    assert delete["applied"] is True
    assert core_api.calls == [
        (
            "delete_namespaced_pod",
            {"name": "payment-api-abc", "namespace": "prod"},
        )
    ]


def test_k8s_connected_write_failure_is_not_reported_as_mock_success():
    class FailingAppsApi(FakeAppsApi):
        def patch_namespaced_deployment(self, **kwargs):
            raise RuntimeError("forbidden")

    tool = k8s_module.K8sTool(core_api=FakeCoreApi(), apps_api=FailingAppsApi())

    with pytest.raises(
        RuntimeError, match="Kubernetes action restart_deployment failed"
    ):
        tool.restart_deployment("payment-api", namespace="prod")


def test_prometheus_uses_settings_url_and_httpx(monkeypatch):
    calls = []
    payload = {"status": "success", "data": {"resultType": "vector", "result": []}}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class AsyncClient:
        def __init__(self, timeout):
            calls.append(("timeout", timeout))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params):
            calls.append(("get", url, params))
            return Response()

    monkeypatch.setattr(
        prometheus_module,
        "get_settings",
        lambda: SimpleNamespace(prometheus_url="http://metrics.internal:9090/"),
    )
    monkeypatch.setattr(prometheus_module.httpx, "AsyncClient", AsyncClient)

    tool = prometheus_module.PrometheusTool(timeout_seconds=2.5)
    result = asyncio.run(tool.query_metric("up", time="2026-05-31T00:00:00Z"))

    assert result == payload
    assert calls == [
        ("timeout", 2.5),
        (
            "get",
            "http://metrics.internal:9090/api/v1/query",
            {"query": "up", "time": "2026-05-31T00:00:00Z"},
        ),
    ]


def test_prometheus_unavailable_server_returns_stable_mock(monkeypatch):
    class AsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params):
            request = httpx.Request("GET", url, params=params)
            raise httpx.ConnectError("offline", request=request)

    monkeypatch.setattr(prometheus_module.httpx, "AsyncClient", AsyncClient)

    tool = prometheus_module.PrometheusTool(
        prometheus_url="http://offline",
        clock=lambda: 1234.0,
    )
    result = asyncio.run(
        tool.query_metric("container_memory_working_set_bytes{pod='auth-gateway'}")
    )

    assert result["status"] == "success"
    assert result["data"]["result"][0] == {
        "metric": {
            "__name__": "container_memory_working_set_bytes",
            "container": "web-app",
            "pod": "auth-gateway-service-84f9b8c2-m4n5",
        },
        "value": [1234.0, "982736128"],
    }


def test_prometheus_returns_real_promql_error_response(monkeypatch):
    request = httpx.Request("GET", "http://metrics/api/v1/query")
    response = httpx.Response(
        422,
        request=request,
        json={"status": "error", "errorType": "bad_data", "error": "invalid query"},
    )

    class AsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params):
            return response

    monkeypatch.setattr(prometheus_module.httpx, "AsyncClient", AsyncClient)
    tool = prometheus_module.PrometheusTool(prometheus_url="http://metrics")

    result = asyncio.run(tool.query_metric("bad {"))

    assert result == {
        "status": "error",
        "errorType": "bad_data",
        "error": "invalid query",
    }
