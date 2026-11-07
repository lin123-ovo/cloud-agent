# CloudAgent 优化与验证

本次修改的实际项目是 `/Users/wangzihao/Downloads/cloud_agent/cloud_agent`。聊天工作区没有源码。修改前 Python 源码备份位于 `.local/optimization-backup-20261107-092111/`；没有备份或导出密钥。现有原始业务表、向量集合和图谱均未重建；集成测试使用并刷新 `ops_*` 演示数据。

## 已落地

| 领域 | 实现 |
|---|---|
| 路由 | 消除产品咨询/选型规则冲突；仅接受五个有效 Agent 的 JSON；保留近期上下文；无效响应与模糊意图先澄清；每轮重置 FinOps 标志 |
| 检索 | 原 Milvus 语义召回扩大到 12 条；项目本地 Markdown 的 BM25 召回；RRF 合并去重；最多 3 条证据；文档名/稳定片段 ID；向量服务失败仍可检索本地资料 |
| 重排序 | 已通过真实 `gte-rerank-v2` 调用，并在本机配置启用；15 秒超时，失败回退到融合顺序；不默认设置未经标定的分数拒答阈值 |
| 无依据回答 | 无候选时明确返回缺少证据；提示词要求逐项核对型号、数字和政策条件；来源冲突时说明差异。候选排名不等于答案可信度 |
| 图谱安全 | 校验有限 Cypher 语法；拒绝写操作、过程、注释、多语句和变长路径；只读事务、10 秒事务超时、最多 20 行；关键词回退使用绑定参数 |
| 身份与业务 | HTTP 聊天身份由服务端操作员配置确定；客户端 `user_id` 为兼容保留但不参与授权；MCP 注入缺身份时拒绝；业务层再次验证身份；SQL 分页限制 1–100；监控资源继续按所有者查询 |
| 环境隔离 | 阿里云模式不调用演示账单、商品或营销 Agent，避免将演示商品当真实数据 |
| 稳定性 | 模型请求超时与有限重试；Agent 节点/整图超时、工具循环上限；业务工具不自动重放；取消向上传播；SSE 错误与结束事件完整；移除人为逐字延时 |
| 诊断 | 请求 ID 关联路由、节点、工具、检索、重排序与耗时；失败记录异常类型，避免暴露供应商错误文本；JSONL 日志按大小轮转 |
| 其他修复 | 推荐 Agent 改为模型仅选择已有商品 ID、代码直接渲染名称和价格，不生成计费周期或新套餐；产品 Agent 来源名单从真实工具返回提取，未取得来源时输出证据不足提示；MCP 推广工具同名覆盖导致 schema 错误；独立导入工具导致循环依赖；禁用缺乏来源版本和上下文隔离的旧问答缓存；启动进程脱离调用终端的进程组 |

## 配置

- `RERANK_MODEL=gte-rerank-v2`：本机已添加；清空此值可禁用模型重排，保留 BM25 + 向量 + RRF。重排会增加一次付费 API 请求和网络耗时。
- `RERANK_MIN_SCORE`：默认 0；仅在独立校准后使用，不能将不同请求的重排分数直接当作统一置信度。资料：[百炼重排序 API](https://www.alibabacloud.com/help/en/model-studio/text-rerank-api)。
- `CLOUDAGENT_OPERATOR_ID`：默认 `user_1001`，由服务端配置本机唯一操作员。
- `NEO4J_READ_USER` / `NEO4J_READ_PASSWORD`：可指定专用只读账户。没有配置时保留原账户，应用仍使用只读事务。没有自动变更数据库用户或角色。
- 新结构化日志：`.local/agent-trace.jsonl`，2 MB 每份，保留三个轮转文件。日志不保存提示词、回答或密钥。
- 本地 Markdown 语料在进程内缓存，修改资料后重启服务。现有向量库的资料更新仍应按原导入流程执行，不会自动重建。

## 可重复验证

```bash
cd /Users/wangzihao/Downloads/cloud_agent/cloud_agent
PYTHONPATH=agent:app:. .venv/bin/python -m pytest tests/agent tests/ops/test_rules.py tests/ops/test_aliyun.py -q
# 需确保当前没有用户分析任务；会写入测试记录和刷新 ops_* 演示数据
PYTHONPATH=agent:app:. OPS_TEST_DB=1 .venv/bin/python -m pytest tests/agent tests/ops -q
# 纯本地检索，不调用模型
.venv/bin/python scripts/evaluate-agent.py --output evaluation/offline.json
# 调用付费模型及现有知识库
.venv/bin/python scripts/evaluate-agent.py --live --rerank --output evaluation/live-new.json
# 后端启动后验证完整 SSE 问答；调用付费模型
.venv/bin/python scripts/check-agent-e2e.py
```

本次 80 项自动测试通过，包含错误路由、上下文、超时、身份覆盖、直接 MCP 越权、无效分页、图谱写语句拒绝、绑定参数、重排序异常及向量库不可用的回退。Black 格式检查及 Ruff F 类静态检查通过；工具安装在临时目录，没有更改项目运行依赖锁。

评测集是本次助手编写的 44 个路由样例及 10 个带来源和短证据的检索样例，属于开发冒烟集，不能作为独立测试集或生产准确率证明。`live.json` 与 `live-final.json` 保留两次真实测量；最后一次 Agent 分类 43/44，连同是否澄清的完整契约匹配 42/44。存在模型波动，不挑选最好结果。检索样例的向量前 3 候选对照与融合重排均命中 10/10，尚无准确率提升证据。

`evaluation/e2e.json` 保存最终完整 HTTP/SSE 检查结果，每例使用新的会话 ID，包含回答供复核；初次发现推荐价格周期和套餐编造的结果保存在 `e2e-before-grounding-fix.json`；HTTP 200 和结束事件仅代表请求完成，不代表回答正确。人工复核应检查：工具是否真的调用、实体/数字是否对应证据、来源是否存在、无答案时是否拒绝编造、跨环境是否混用数据。业务查询需用真实数据库结果核对，不能只看模型措辞。

## 后续仍需外部验证

真实阿里云资源、监控、询价需要可用账号及 RAM 授权，本次没有据演示数据宣称完成真实云联调。当前仍为本机单操作员工具；服务端操作员身份限制不等于企业登录体系。若要上线多人服务，还需接入认证、租户级资源归属和独立会话隔离，再迁移到持久化任务队列和多副本部署。

超时会取消协程，但 Python 无法强制终止已在线程中执行的第三方同步 SDK；因此还设置了数据库/HTTP/事务自身超时，不宣称立即终止所有底层请求。新检索策略需要更大且独立标注的测试集和延迟/成本对照；不能仅凭本次小样本写入提升百分比。项目已有 LangChain/PyMilvus 弃用提示，未在本次批量升级依赖。
