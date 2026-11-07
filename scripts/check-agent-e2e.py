#!/usr/bin/env python3
"""Live local SSE checks; invokes paid models. Results require human answer review."""
from pathlib import Path
import json
import time
import uuid
import httpx

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    ("policy", "五天无理由退款每年有几次？", "demo"),
    ("graph", "ecs.g8a.4xlarge 最多绑定几个弹性网卡？", "demo"),
    ("recommendation", "我做Java加MySQL博客，预算500元，有哪些商品可以选？", "demo"),
    ("orders", "查我的订单", "demo"),
    ("clarify", "帮我处理一下", "demo"),
    ("unknown", "知识库里有没有 ecs.quantum999 的 CPU 规格？没有就明确说没有", "demo"),
    ("real_catalog_guard", "给我推荐一台博客服务器，预算500元", "aliyun"),
]


def main():
    rows = []
    for name, query, environment in CASES:
        start = time.monotonic()
        try:
            response = httpx.post(
                "http://127.0.0.1:5001/api/chat",
                json={
                    "query": query,
                    "user_id": "untrusted-client",
                    "session_id": "optimization-" + name + "-" + uuid.uuid4().hex[:10],
                    "environment": environment,
                },
                timeout=180,
            )
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            rows.append(
                {
                    "case": name,
                    "http": response.status_code,
                    "done": any(e.get("done") for e in events),
                    "error": next((e["error"] for e in events if "error" in e), None),
                    "answer": "".join(e.get("content", "") for e in events),
                    "request_id": next(
                        (e["request_id"] for e in events if "request_id" in e), None
                    ),
                    "elapsed_ms": round((time.monotonic() - start) * 1000),
                    "manual_review": "pending",
                }
            )
            print(name, response.status_code, "error:", rows[-1]["error"], flush=True)
        except httpx.HTTPError as exc:
            rows.append({"case": name, "error": type(exc).__name__})
            print(name, type(exc).__name__, flush=True)
    path = ROOT / "evaluation/e2e.json"
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(path)


if __name__ == "__main__":
    main()
