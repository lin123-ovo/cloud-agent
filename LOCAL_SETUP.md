# CloudAgent 本机启动

此环境使用 Docker 承载独立数据库，Python 和前端运行在本机。所有对外端口只绑定到本机。

1. 启动 Docker Desktop。
2. 将有效的百炼 API Key 填入 `agent/.env` 的 `DASHSCOPE_API_KEY`。不要将该文件和 `.env.docker` 提交或分享。
3. 启动服务：`./scripts/start.sh`。首次初始化知识库：`./scripts/init-knowledge.sh --initialize`。此操作会调用付费模型，重建本项目 Milvus 中的 `cloud_product_docs` 集合；重复执行会重新生成向量。默认导入项目自带的图谱 JSON 并使用增量 MERGE，其中端点缺失的关系会跳过；若要重新调用模型抽取图谱，可增加 `--extract-graph` 参数，生成文件保存在 `.local/knowledge-init`。
4. 访问 http://127.0.0.1:5173，API 文档为 http://127.0.0.1:5001/docs。
5. 停止服务：`./scripts/stop.sh`。数据卷被保留。日志保存在 `.local/`。

数据库分别使用 Redis 16379、MySQL 13306、Milvus 19531、Neo4j Bolt 17687（浏览器 17474）。MySQL 的模拟数据仅在新建数据卷首次启动时导入；脚本含 TRUNCATE，请勿在现有数据库中运行。项目没有发现 PostgreSQL 调用，因此未启动 PostgreSQL。Docker Compose 项目名为 `cloudagent-local`，不依赖其他项目容器。

依赖恢复：Python 3.11 创建 `.venv` 后执行 `.venv/bin/pip install -r requirements-local-lock.txt`；前端在 `front/cloud_agent` 执行 `npm ci`。若 Docker 镜像下载失败，检查 Docker Desktop 网络与镜像源设置，避免覆盖其他项目设置。

## 运维工作台升级

新版包含资源总览、成本分析、分析记录和智能助手。后端会增量创建 `ops_*` 表并初始化六类独立演示资源。完整操作、阿里云配置、规则边界、测试及排错见 `OPS_WORKBENCH.md`。真实云尚未完成联调；不要将演示估算当作实际节省金额。

## Agent 优化版

路由、混合检索、重排序、工具安全和评测说明见 [docs/agent-optimization.md](docs/agent-optimization.md)。本机已启用 `gte-rerank-v2` 重排序；清空 `agent/.env` 的 `RERANK_MODEL` 可禁用。服务端操作员由 `CLOUDAGENT_OPERATOR_ID` 决定，客户端传入的 `user_id` 不再决定业务数据归属。

## 中英文版本

打开 [英文版](http://127.0.0.1:5173/?lang=en)，或在页面右上角切换 English / 中文。支持英文助手回答及英文报告下载。英文启动说明见 [LOCAL_SETUP.en.md](LOCAL_SETUP.en.md)，实现与验证见 [docs/english-version.md](docs/english-version.md)。
