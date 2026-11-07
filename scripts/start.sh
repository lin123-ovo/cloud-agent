#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
export PATH="$ROOT/.venv/bin:$PATH"
if ! docker info >/dev/null 2>&1; then
  echo '请先启动 Docker Desktop，等待引擎就绪后重试。' >&2
  exit 1
fi
docker compose --env-file .env.docker up -d --wait
mkdir -p .local
start_process() {
  local name="$1"
  shift
  if [[ -f ".local/$name.pid" ]]; then
    local pid command
    pid=$(cat ".local/$name.pid")
    command=$(ps -p "$pid" -o command= 2>/dev/null || true)
    case "$name:$command" in
      backend:*uvicorn*app_main:app*|frontend:*vite*) echo "$name 已运行。"; return ;;
    esac
  fi
  # A new session survives the invoking terminal/tool process group exiting.
  .venv/bin/python - "$name" "$@" <<'PYTHON'
import subprocess
import sys
from pathlib import Path

name, *command = sys.argv[1:]
with Path(f".local/{name}.log").open("ab") as log:
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                               stderr=subprocess.STDOUT, start_new_session=True)
Path(f".local/{name}.pid").write_text(str(process.pid))
PYTHON
}
if ! .venv/bin/python -c 'from dotenv import dotenv_values; k=dotenv_values("agent/.env").get("DASHSCOPE_API_KEY", ""); raise SystemExit(not k or "YOUR" in k.upper() or "XXX" in k.upper())'; then
  echo '请在 agent/.env 中填写有效的 DASHSCOPE_API_KEY；数据库已启动。' >&2
  exit 1
fi
start_process backend "$ROOT/.venv/bin/python" -m uvicorn app_main:app --app-dir "$ROOT/app" --host 127.0.0.1 --port 5001
start_process frontend node "$ROOT/front/cloud_agent/node_modules/vite/bin/vite.js" "$ROOT/front/cloud_agent" --config "$ROOT/front/cloud_agent/vite.config.ts"
for attempt in {1..30}; do
  if curl -fsS http://127.0.0.1:5001/openapi.json >/dev/null && curl -fsS http://127.0.0.1:5173/ >/dev/null; then
    echo '前端：http://127.0.0.1:5173  后端：http://127.0.0.1:5001/docs'
    echo '日志：.local/backend.log 和 .local/frontend.log'
    exit 0
  fi
  sleep 1
done
echo '服务启动未就绪，请检查 .local/backend.log 和 .local/frontend.log。' >&2
exit 1
