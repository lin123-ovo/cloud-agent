# Run CloudAgent locally

CloudAgent runs a local frontend and Python backend with dedicated Docker databases.

```bash
cd /Users/wangzihao/Downloads/cloud_agent/cloud_agent
./scripts/start.sh
```

Open [English workspace](http://127.0.0.1:5173/?lang=en) or [Chinese workspace](http://127.0.0.1:5173/?lang=zh). The language selector remembers your choice. API documentation: [FastAPI docs](http://127.0.0.1:5001/docs).

Docker Desktop must be running. Set a valid `DASHSCOPE_API_KEY` in the server-side `agent/.env`. Keep credentials private. Existing knowledge collections do not need to be initialized again for normal startup.

```bash
./scripts/stop.sh
```

This is a local, single-operator, read-only analysis workspace. Demo prices are examples. Live Alibaba Cloud integration requires your own read-only credentials and has not been verified against a real cloud account in this task.

English mode covers interface labels, assistant responses and Markdown report export. Existing free-form Chinese model explanations are retained as original source text; newly created English reports generate explanations in English. Resource IDs, source filenames, monitoring values and prices remain unchanged.

See [bilingual implementation and validation](docs/english-version.md), [agent optimization](docs/agent-optimization.md) and [operations guide](OPS_WORKBENCH.md).
