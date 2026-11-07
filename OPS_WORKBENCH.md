# CloudAgent 云资源分析与成本优化工作台

本版本用于本机 FDE 演示与交付。前端 http://127.0.0.1:5173，API 文档 http://127.0.0.1:5001/docs。它是单操作员工具，不提供企业多租户登录，也不执行云资源变更。

## 安装与启动

1. 启动 Docker Desktop，确认 Docker 引擎就绪。
2. 使用 Python 3.11 创建 `.venv`，运行 `.venv/bin/pip install -r requirements-local-lock.txt`。在 `front/cloud_agent` 执行 `npm ci`。
3. 保留已有 `agent/.env` 和 `.env.docker`。新表均为 `ops_*`，后端启动时以 CREATE IF NOT EXISTS 创建，不清空原始订单、实例或监控表。需要手动刷新演示数据时运行 `./scripts/init-ops.sh`。
4. 运行 `./scripts/start.sh`；停止运行 `./scripts/stop.sh`。已启动旧版进程时先停止再启动，以加载后端升级。启动后执行 `./scripts/check-ops.sh` 检查数据库、后端健康和环境配置。
5. 密钥仅存放在服务端 `.env` 中，不提交、不放入截图或浏览器表单。

现有 Docker 数据卷会保留；不要为更新演示数据执行 `docker compose down -v`，也不要再次在原始数据库运行含 TRUNCATE 的旧初始化 SQL。

## 五分钟演示

1. 选择“演示环境”，资源总览会展示六台实例，分别覆盖低利用率、正常、高负载、低均值高峰值、缺失内存监控和已停止。
2. 勾选资源，点击“分析已选”。任务完成后查看诊断、覆盖率、候选规格、费用边界和执行步骤。
3. 低利用率实例可得到同规格族、CPU/内存均减半的候选。演示价格为 4 元/小时与 2 元/小时，按 730 小时计算差额 1460 元；这是示例计算，不代表实际节省。
4. 高峰值、缺失数据和停止实例不会自动生成降配候选。下载 Markdown，并在“分析记录”重新打开历史结果。
5. 在智能助手中输入“帮我做近7天降本分析”，会创建同一分析服务的报告并打开报告面板。
6. 切换到“阿里云环境”，在未配置凭据时查看独立配置提示，不会加载演示资源。

资源查询和成本分析使用当前环境；旧账单、订单和推广功能仍使用原始示例数据，仅在演示模式下提供。通用知识问答继续使用项目自带知识库，不应作为真实产品政策依据。

## 接入阿里云（真实联调待完成）

本次没有可用云账号，已实现并通过模拟 SDK 响应测试，但尚未对真实云资源、监控和报价完成联调。

参照 `agent/.env.aliyun.example`，将以下字段追加到服务端 `agent/.env` 并重启后端：

```dotenv
ALIBABA_CLOUD_ACCESS_KEY_ID=
ALIBABA_CLOUD_ACCESS_KEY_SECRET=
ALIBABA_CLOUD_SECURITY_TOKEN=
ALIYUN_REGIONS=cn-beijing
```

使用专用 RAM 只读身份，避免提供主账号凭据。按实际资源与地域约束权限。首版调用的 Action 为：

- `ecs:DescribeInstances`：分页列出 ECS 资源。
- `ecs:DescribeInstanceTypes`：读取实例规格。
- `ecs:DescribePrice`：获取普通按量计算规格的原价明细。
- `cms:DescribeMetricList`：读取 CPU、内存监控。

可在 RAM 中按这些 Action 构造自定义策略；不支持资源级约束的查询 Action 需使用 `Resource: "*"`，支持地域或资源限制的部分应按账号资源收紧。部署者需在自己的账号下确认 RAM 策略和目标地域权限；工作台不申请或修改授权。

内存使用率来自 CloudMonitor Agent 的 `memory_usedutilization`。未安装 Agent 时可能没有数据，报告会明确标记缺失。CPU 使用 `acs_ecs_dashboard` 的 `CPUUtilization`。按 300 秒粒度读取最近完整 7 个 UTC 日，界面转换为北京时间；这是 UTC 日窗口，不是北京自然日窗口。

官方资料：[云监控基础和操作系统监控](https://www.alibabacloud.com/help/en/cms/cloudmonitor-1-0/user-guide/overview-of-basic-and-operating-system-monitoring)、[ECS DescribePrice](https://www.alibabacloud.com/help/en/ecs/developer-reference/api-ecs-2014-05-26-describeprice)。

## 诊断与价格边界

规则版本 `2026-10-31.v1`：

- 监控均值及峰值覆盖率至少 90%；缺失或重复桶不以零填充。只接纳窗口内、5 分钟对齐的时间点。
- 平均 CPU<10%、CPU 最大值<40%、平均内存<30%、内存最大值<60%，才进入低利用率筛选。
- CPU 最大值≥80% 或内存最大值≥85%，提示峰值风险。停止实例或监控不充分时不推荐降配。
- 候选必须同规格族且 CPU 和内存恰为当前一半；线性估算峰值达到风险阈值则拒绝候选。这只是筛选，不是容量保证；实际变更前需核对业务、可用区库存和兼容性。
- 真实报价仅支持非抢占式 PostPaid，严格提取 `DescribePrice.DetailInfos` 中 `Resource=instanceType` 的 OriginalPrice，不使用可能包含磁盘的总价。币种、地域、操作系统或小时单位不一致时不估算。
- 报价不包含系统盘、数据盘、网络、镜像、优惠、已有折扣或实际账单；月度金额按 730 小时换算。报价失败则保留利用率建议并展示失败步骤。
- 模型仅生成可折叠的辅助解释；规则结果、指标和金额由代码生成。模型失败时仍保留报告，并标明部分完成。

## 任务、接口和存储

- `GET /api/environments`、`GET /api/environments/{environment}/status?region=...`、`GET /api/resources?environment=...&region=...`。
- `POST /api/analyses`：参数 `environment`、`region`、`instance_ids`（1–20 个不重复实例）、`explain`（默认 true）。返回 202 和任务 ID。
- `GET /api/analyses` 返回最近 100 条；`GET /api/analyses/{id}` 返回报告与步骤；`/steps` 单独读取步骤；`/report.md` 下载报告。
- 任务状态：queued、running、succeeded、partial、failed、interrupted。同一环境最多一个活动任务；繁忙返回 409，未配置或云接口故障返回 503。
- 后台任务使用本机线程池。重启会将未完成任务标记为 interrupted，不自动重放；可在界面手动重跑。这个设计面向本机单进程，不能直接以多副本方式部署。
- MySQL 新增 `ops_demo_resources`、`ops_tasks`、`ops_snapshots`、`ops_steps`。保存规则版本、完整监控快照、报告与脱敏调用记录。原业务数据保持不变。
- `/api/chat` 保留内容 SSE，新增可选 `environment`、`region`、`instance_ids` 字段；分析返回 `report` 事件和内容事件。资源分析不使用问答缓存。
- MCP 新增 `list_cloud_resources`、`create_cloud_analysis`，请求本机持久后端的统一服务。旧 MCP 订单工具继续服务原示例数据。

## 测试与故障定位

离线规则与模拟云接口：`.venv/bin/python -m pytest tests/ops/test_rules.py tests/ops/test_aliyun.py -q`。

完整本地集成：`OPS_TEST_DB=1 .venv/bin/python -m pytest tests/ops -q`。集成测试会写入 `ops_*` 测试记录、刷新六类演示数据并模拟任务重启中断，请在没有用户分析任务执行时运行。

前端：在 `front/cloud_agent` 运行 `npm run build`。当前包含旧 LangChain 弃用提示和前端单包体积提示，不影响本次通过的功能检查。

常见问题：

- 连接失败：先运行检查脚本，确认本项目容器和端口；不要改用另一套 RAG 数据库端口。
- 阿里云空列表：确认允许地域、RAM 权限和该地域是否真的有资源。
- 内存不可用：确认云监控 Agent；不要把缺失监控当成低利用率。
- 任务部分完成：展开执行步骤，查看报价或模型解释是否失败；已生成的结构化结论仍可查看。
- 任务中断：服务重启不会恢复后台线程，重新分析即可；旧报告仍被保留。
