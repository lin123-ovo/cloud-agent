#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose --env-file .env.docker ps
curl -fsS http://127.0.0.1:5001/api/health
curl -fsS http://127.0.0.1:5001/api/environments
