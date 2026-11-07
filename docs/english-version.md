# CloudAgent 中英文版本

入口：[英文版](http://127.0.0.1:5173/?lang=en) / [中文版](http://127.0.0.1:5173/?lang=zh)。页面右上方可随时选择 English 或中文，URL 和浏览器会保存所选语言。

已覆盖：资源总览、成本分析、历史记录、报告字段与风险提示、Element Plus 控件、助手欢迎页、快捷提问、英文回答及英文 Markdown 下载。切换界面语言不会自动翻译历史聊天内容。未知的用户自定义资源名、型号、来源文件名和原始数据保留原文。

语言文案统一维护在 `front/cloud_agent/src/locales/en.json`。Vue 前端和 Python 的确定性提示复用同一份文案。模型根据每个请求的语言指令回答，不增加一次整段翻译模型调用。使用 ContextVar 隔离并发请求语言，默认值保持中文。

API 兼容：

- `POST /api/chat` 新增可选 `language: "zh" | "en"`，默认 `zh`。
- `POST /api/analyses` 新增可选 `language: "zh" | "en"`，默认 `zh`；仅作为 JSON 任务元数据保存，没有表结构迁移。
- `GET /api/analyses/{id}/report.md?lang=en` 下载英文版，省略 `lang` 仍下载中文版。
- 新任务按创建时的语言生成模型解释。旧报告已有解释保留原文，并注明原文语言；指标、数值、金额和规则结果不会重新生成或翻译。

验证：前端 TypeScript 检查与生产构建通过；后端含新增语言测试共 90 项通过。真实模型调用检查了英文政策问答、商品推荐和意图澄清；资源查询与英文 Markdown 导出通过，新建英文演示报告及英文模型解释生成成功。浏览器中验证中英文切换、页面控件语言与刷新后保留选择。

- 自动测试：`PYTHONPATH=agent:app:. .venv/bin/python -m pytest tests/agent tests/ops/test_rules.py tests/ops/test_aliyun.py -q`
- 本地数据库集成：`PYTHONPATH=agent:app:. OPS_TEST_DB=1 .venv/bin/python -m pytest tests/agent tests/ops -q`（刷新 ops_* 演示数据，勿在有用户任务时运行）。
- 实际英文接口冒烟：`.venv/bin/python scripts/check-english-e2e.py`（调用付费模型）。
- 结果与预览：`evaluation/english/`。

修改前源码备份：`.local/english-backup-20261107-095118/`。未重建知识库、图谱或原始业务数据。前端仍有原有的 bundle 体积提示，Python 仍有 LangChain 弃用提示。
