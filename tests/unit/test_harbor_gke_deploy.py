"""Unit tests for Harbor registry push + GKE/Helm deployment.

Hermetic — no Docker, no Helm, no cluster. ``subprocess.run`` is
monkeypatched so we assert on the exact commands Harbor would issue.
"""

import asyncio
import subprocess

import pytest

from agents.harbor.tools import (
    deploy_gke,
    generate_k8s_manifests,
    push_image,
)


class _FakeResult:
    def __init__(self, returncode: int, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr


# ── push_image ────────────────────────────────────────────────────────────────


def test_push_image_no_registry_returns_error():
    ok, msg = asyncio.run(push_image("prometheus-model", ""))
    assert not ok
    assert "REGISTRY_URL" in msg


def test_push_image_issues_tag_then_push(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeResult(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, msg = asyncio.run(push_image("prometheus-model", "gcr.io/nexora"))
    assert ok
    assert "Image pushed: gcr.io/nexora/prometheus-model:latest" in msg
    assert len(calls) == 2
    assert calls[0] == [
        "docker",
        "tag",
        "prometheus-model",
        "gcr.io/nexora/prometheus-model:latest",
    ]
    assert calls[1] == ["docker", "push", "gcr.io/nexora/prometheus-model:latest"]


def test_push_image_uses_explicit_tag(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeResult(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, _ = asyncio.run(push_image("m", "registry.example.com/acme", tag="v1.2"))
    assert ok
    assert calls[0][-1] == "registry.example.com/acme/m:v1.2"


def test_push_image_tag_failure(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _FakeResult(1, stderr="no such image")
    )
    ok, msg = asyncio.run(push_image("prometheus-model", "gcr.io/nexora"))
    assert not ok
    assert "Docker tag failed" in msg
    assert "no such image" in msg


def test_push_image_push_failure(monkeypatch):
    state = {"n": 0}

    def fake_run(cmd, **kwargs):
        state["n"] += 1
        return _FakeResult(0) if state["n"] == 1 else _FakeResult(1, stderr="denied")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, msg = asyncio.run(push_image("prometheus-model", "gcr.io/nexora"))
    assert not ok
    assert "Docker push failed" in msg
    assert "denied" in msg


# ── generate_k8s_manifests ───────────────────────────────────────────────────


def test_generate_k8s_manifests_renders_all_files():
    manifests = generate_k8s_manifests(
        "gcr.io/nexora/prometheus-serving:latest", name="prometheus-serving"
    )
    assert set(manifests) == {"deployment.yaml", "service.yaml"}


def test_generate_k8s_manifests_deployment_content():
    deployment = generate_k8s_manifests(
        "gcr.io/nexora/prometheus-serving:latest",
        name="prometheus-serving",
        namespace="ml",
        replicas=3,
    )["deployment.yaml"]
    assert "kind: Deployment" in deployment
    assert "name: prometheus-serving" in deployment
    assert "namespace: ml" in deployment
    assert "replicas: 3" in deployment
    assert "image: gcr.io/nexora/prometheus-serving:latest" in deployment
    assert "containerPort: 8080" in deployment


def test_generate_k8s_manifests_service_content():
    service = generate_k8s_manifests(
        "gcr.io/nexora/prometheus-serving:latest",
        name="prometheus-serving",
        namespace="ml",
    )["service.yaml"]
    assert "kind: Service" in service
    assert "name: prometheus-serving-service" in service
    assert "type: LoadBalancer" in service
    assert "port: 80" in service
    assert "targetPort: 8080" in service


def test_generate_k8s_manifests_valid_yaml():
    yaml = pytest.importorskip("yaml")
    manifests = generate_k8s_manifests("img:tag", name="ps", replicas=2)
    for text in manifests.values():
        docs = list(yaml.safe_load_all(text))
        assert len(docs) == 1
        assert docs[0]["kind"] in {"Deployment", "Service"}
        assert docs[0]["metadata"]["name"]


# ── deploy_gke ───────────────────────────────────────────────────────────────


def test_deploy_gke_builds_helm_command(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeResult(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, msg = asyncio.run(
        deploy_gke(
            "/chart",
            release_name="prometheus-serving",
            namespace="ml",
            values={"image.repository": "gcr.io/nexora/ps", "image.tag": "latest"},
        )
    )
    assert ok
    assert "prometheus-serving" in msg
    cmd = calls[0]
    assert cmd[:4] == ["helm", "upgrade", "--install", "prometheus-serving"]
    assert "/chart" in cmd
    assert "-n" in cmd and "ml" in cmd
    assert "--set" in cmd
    assert "image.repository=gcr.io/nexora/ps" in cmd
    assert "image.tag=latest" in cmd


def test_deploy_gke_helm_failure(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: _FakeResult(1, stderr="connection refused")
    )
    ok, msg = asyncio.run(deploy_gke("/chart"))
    assert not ok
    assert "Helm deploy failed" in msg
    assert "connection refused" in msg


def test_deploy_gke_no_values_omits_set(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _FakeResult(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, _ = asyncio.run(deploy_gke("/chart"))
    assert ok
    assert "--set" not in calls[0]
