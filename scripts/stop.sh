#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
for name in backend frontend; do
  pidfile=".local/$name.pid"
  if [[ -f "$pidfile" ]]; then
    pid=$(cat "$pidfile")
    command=$(ps -p "$pid" -o command= || true)
    case "$name:$command" in
      backend:*uvicorn*app_main:app*|frontend:*vite*) kill "$pid" 2>/dev/null || true ;;
      *) echo "跳过 $name：进程不存在或已不匹配。" ;;
    esac
    rm -f "$pidfile"
  fi
done
docker compose --env-file .env.docker stop
