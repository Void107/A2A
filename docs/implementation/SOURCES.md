# 来源与核查边界

核查日期：2026-09-13。链接支持能力与接入方式；本包中的字段、任务和接口建议是本项目设计，不是官方 A2A 标准。

| 来源 | 用途 |
|---|---|
| [OPA 核心文档](https://www.openpolicyagent.org/docs) | 策略决策与实际执行分离，决策可输出结构化数据 |
| [OPA 集成](https://www.openpolicyagent.org/docs/integration) | REST 接入、HTTP 200 无 result 的未定义语义、管理接口 |
| [OPA 数据过滤](https://www.openpolicyagent.org/docs/filtering) | 明确现有生态已有细粒度数据控制，修正“无人实现”的市场假设 |
| [Presidio](https://presidio.dataprivacystack.org/) | 检测范围、自动识别局限 |
| [Presidio Anonymizer](https://presidio.dataprivacystack.org/anonymizer/) | 检测结果的替换和去标识化 |
| [Presidio Structured](https://presidio.dataprivacystack.org/structured/) | 结构化内容处理参考；不等同于本项目的输出契约校验 |
| [A2A 规范](https://a2a-protocol.org/latest/specification/) | Agent Card、消息、任务与协议绑定 |
| [A2A 扩展](https://a2a-protocol.org/latest/topics/extensions/) | 扩展声明、标识和协商；不擅用官方扩展命名空间 |
| [Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) | 项目阅读入口的组织方式 |

## 实现前再确认

T00/T05/T06/T07 必须锁定实际 Python、依赖、OPA、Presidio 识别器配置、官方 A2A SDK 与协议版本，并记录来源和验证结果。不要把 `/latest/` 当可复现版本锁定。

Presidio 官方页面目前使用新站点，历史微软文档可能重定向；下载模型、镜像与组件时以实际官方发布位置为准，不猜测镜像名和包版本。

官方能力不能替代本项目验证：OPA 不能验证不可信的注册事实；Presidio 不保证发现所有敏感信息；A2A SDK 导入成功不证明协议互通；AGENTS.md 的存在不会自动启动后台任务。

## 本地审阅基线

- 当前主实现 `../../app/`、`../../tests/`、`../../alembic/`。
- 旧产品说明 `../../产品说明_A2A_Contract_Hub.md` 和 `../../README.md` 含待核实声明；本包是目标更新方案。
- 历史市场设计与搭建指南位于项目父目录的 `A2A/Documents/`。它们可帮助追溯动机，不作为当前已实现功能的证据。
- 前次审阅曾复现未知 effect 放行、缺失 transform、错误配置/不支持聚合保留原文，以及审计写库失败后删除队列消息。实现时需重现并转成实际业务路径测试。
- 全套测试曾受 macOS 原生扩展代码签名/加载问题阻止，没有获得完整通过结果；详见 STATUS.md，不能据此推断业务测试通过或失败。
