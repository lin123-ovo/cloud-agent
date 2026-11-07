#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" != "--initialize" ]]; then
  echo '此操作调用 DashScope，可能产生费用，并会重建本项目的 cloud_product_docs 集合。运行时传入 --initialize。' >&2
  exit 1
fi
.venv/bin/python - <<'PY'
from pathlib import Path
from dotenv import dotenv_values
key = dotenv_values('agent/.env').get('DASHSCOPE_API_KEY', '')
if not key or 'YOUR' in key.upper() or 'XXX' in key.upper():
    raise SystemExit('请先在 agent/.env 配置有效的 DASHSCOPE_API_KEY。')
PY
PYTHONPATH="$PWD/agent" .venv/bin/python -c 'from pathlib import Path; from test.milvus_rag import MilvusRAGManager; MilvusRAGManager().ingest_documents(str(Path("mock_data").resolve()))'
if [[ "${2:-}" == "--extract-graph" ]]; then
  mkdir -p .local/knowledge-init
  cp mock_data/ecs_product_info.md .local/knowledge-init/ecs_product_info.md
  PYTHONUNBUFFERED=1 PYTHONPATH="$PWD/agent" .venv/bin/python -c 'from test.build_kg import extract_knowledge_graph, import_to_neo4j; import_to_neo4j(extract_knowledge_graph(".local/knowledge-init/ecs_product_info.md"))'
else
  PYTHONUNBUFFERED=1 PYTHONPATH="$PWD/agent" .venv/bin/python scripts/import-graph.py
fi
