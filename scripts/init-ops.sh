#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python -c 'from cloudops import store; from cloudops.providers import seed_demo; store.initialize(); seed_demo(); print("工作台表和六类演示数据已就绪，原始业务表未修改")'
