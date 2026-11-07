"""Opt-in integration checks against only the additive ops_* tables."""

import os
import sys
from pathlib import Path
import pytest
from cloudops import service, store
from cloudops.providers import CloudError

pytestmark = pytest.mark.skipif(
    os.getenv("OPS_TEST_DB") != "1", reason="requires local project MySQL"
)


@pytest.fixture(autouse=True)
def database(monkeypatch):
    monkeypatch.setenv("ALIYUN_REGIONS", "cn-beijing")
    store.initialize()
    from cloudops.providers import seed_demo

    seed_demo()
    # Admit tasks deterministically, then explicitly execute them in each test.
    monkeypatch.setattr(service.executor, "submit", lambda *args: None)
    yield
    # Leave no active test tasks blocking the workbench.
    for row in store.rows(
        "SELECT payload FROM ops_tasks WHERE status='queued' LIMIT 100"
    ):
        t = store.decode(row["payload"])
        t["status"] = "interrupted"
        service.save_task(t)


def test_six_demo_reports_and_evidence():
    task = service.create_task(
        "demo",
        "cn-beijing",
        [
            "demo-idle",
            "demo-normal",
            "demo-busy",
            "demo-spike",
            "demo-missing",
            "demo-stopped",
        ],
        False,
    )
    service.run_task(task["id"], False)
    report = service.get_task(task["id"])
    assert report["status"] == "succeeded"
    results = {r["resource"]["id"]: r for r in report["results"]}
    assert results["demo-idle"]["savings"]["monthly_equivalent_saving"] == 1460
    assert results["demo-spike"]["diagnosis"] == "peak_risk"
    assert results["demo-missing"]["diagnosis"] == "insufficient_data"
    assert results["demo-stopped"]["candidate"] is None
    assert results["demo-normal"]["diagnosis"] == "normal"
    assert results["demo-busy"]["diagnosis"] == "peak_risk"
    assert any(s["tool"] == "get_monitoring" for s in report["steps"])
    assert "示例价格" in service.markdown(report)
    assert (
        len(store.rows("SELECT id FROM ops_snapshots WHERE task_id=%s", (task["id"],)))
        == 6
    )


def test_environment_lock_and_restart_interrupt():
    task = service.create_task("demo", "cn-beijing", ["demo-idle"], False)
    with pytest.raises(CloudError, match="已有"):
        service.create_task("demo", "cn-beijing", ["demo-normal"], False)
    service.initialize(seed=False)
    assert service.get_task(task["id"])["status"] == "interrupted"


def test_model_failure_preserves_rules(monkeypatch):
    def fail(*args):
        raise CloudError("ModelUnavailable", "unavailable")

    monkeypatch.setattr(service, "explain_report", fail)
    task = service.create_task("demo", "cn-beijing", ["demo-idle"], True)
    service.run_task(task["id"], True)
    r = service.get_task(task["id"])
    assert r["status"] == "partial" and r["explanation_status"] == "unavailable"
    assert r["results"][0]["diagnosis"] == "low_utilization"


def test_invalid_instance_does_not_cross_environments():
    task = service.create_task("demo", "cn-beijing", ["real-not-in-demo"], False)
    service.run_task(task["id"], False)
    assert service.get_task(task["id"])["status"] == "failed"


def test_api_contract_download_and_no_cloud_fallback(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
    from fastapi.testclient import TestClient
    from app_main import app

    client = TestClient(app)
    response = client.post(
        "/api/analyses",
        json={"environment": "demo", "instance_ids": ["demo-idle"], "explain": False},
    )
    assert response.status_code == 202
    id = response.json()["id"]
    service.run_task(id, False)
    report = client.get(f"/api/analyses/{id}").json()
    assert report["results"][0]["candidate"]["cpu"] == 8
    assert client.get(f"/api/analyses/{id}/steps").status_code == 200
    download = client.get(f"/api/analyses/{id}/report.md")
    assert download.status_code == 200 and "示例价格" in download.text
    assert "attachment" in download.headers["content-disposition"]
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)
    cloud = client.get("/api/resources?environment=aliyun&region=cn-beijing")
    assert cloud.status_code == 503 and cloud.json()["code"] == "NotConfigured"
    assert client.post("/api/analyses", json={"instance_ids": []}).status_code == 422
    assert client.get("/api/analyses/not-exist").status_code == 404


def test_chat_report_event_and_environment_boundary(monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
    from fastapi.testclient import TestClient
    from app_main import app
    import json

    client = TestClient(app)
    stream = client.post(
        "/api/chat",
        json={
            "query": "帮我做降本分析",
            "environment": "demo",
            "instance_ids": ["demo-idle"],
        },
    )
    events = [
        json.loads(line[6:])
        for line in stream.text.splitlines()
        if line.startswith("data: ")
    ]
    id = next(event["report"]["id"] for event in events if "report" in event)
    task = service.get_task(id)
    assert task["resource_ids"] == ["demo-idle"] and task["environment"] == "demo"
    assert events[-1]["done"] is True
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)
    stream = client.post(
        "/api/chat", json={"query": "查询最近订单", "environment": "aliyun"}
    )
    assert "ORD-1001" not in stream.text
