"""Live English smoke checks. Calls paid models through the local backend."""

import httpx, json, uuid, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
rows = []
for name, query in [
    ("policy", "How many times per year does the demo policy allow a five-day refund?"),
    (
        "recommendation",
        "Suggest a server for a Java and MySQL blog with a budget of 500",
    ),
    ("clarify", "Please help me with this"),
    ("inventory", "List all my running instances"),
]:
    start = time.monotonic()
    r = httpx.post(
        "http://127.0.0.1:5001/api/chat",
        json={"query": query, "language": "en", "session_id": "en-" + uuid.uuid4().hex},
        timeout=180,
    )
    events = [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: ")]
    rows.append(
        {
            "case": name,
            "status": r.status_code,
            "content": "".join(e.get("content", "") for e in events),
            "done": any(e.get("done") for e in events),
            "error": next((e["error"] for e in events if "error" in e), None),
            "elapsed_ms": round((time.monotonic() - start) * 1000),
        }
    )
    print(name, r.status_code, rows[-1]["error"], flush=True)
# Reuse a completed demo report to verify download presentation without starting another analysis.
tasks = httpx.get("http://127.0.0.1:5001/api/analyses").json()
task = next(
    t
    for t in tasks
    if t.get("environment") == "demo" and t.get("status") == "succeeded"
)
url = f"http://127.0.0.1:5001/api/analyses/{task['id']}/report.md"
en = httpx.get(url, params={"lang": "en"})
zh = httpx.get(url)
Path(ROOT / "evaluation/english/report.en.md").write_text(en.text)
rows.append(
    {
        "case": "report_download",
        "status": en.status_code,
        "english_heading": "# Cloud resource analysis report" in en.text,
        "chinese_unchanged": "# 云资源分析报告" in zh.text,
        "task_id": task["id"],
    }
)
Path(ROOT / "evaluation/english/live.json").write_text(
    json.dumps(rows, ensure_ascii=False, indent=2)
)
print("report", en.status_code, flush=True)
