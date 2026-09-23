# A2A Contract Hub 改造执行包

计划版本：1.0 · 日期：2026-09-13 · 目标：可验证的开源 alpha。

**当前状态：T00–T13 已完成任务范围内的实现及证据核对；T14 正在整理候选交付，T15 等待独立真人试用。** 逐项状态见 TASKS.json；局部或单项通过不等同于所有 AC 通过。

## 产品目标

让开发者通过一份契约获得可预测、可验证的数据交付，围绕三个问题组织工作：

1. 接入是否更省事：无需手动拼接身份、OPA、Presidio、输出校验和审计。
2. 数据是否仍然可用：不同调用方获得有明确结构、能够完成指定任务的视图。
3. 变更与故障是否可发现：发布前检查兼容性，运行时阻止未满足约定的数据交付。

OPA 承担策略决策，Presidio 承担指定范围的内容检测和处理，Hub 承担契约管理、实际执行、输出验证与交付记录。

## 工作位置

主仓库：`/Users/jeremysie/Desktop/A2A项目/a2a-contract-hub`。

历史副本：`/Users/jeremysie/Desktop/A2A项目/A2A/a2a-contract-hub`。不要误改历史副本。

本包使用仓库相对路径，复制整个仓库后仍可阅读执行。顶层 AGENTS.md 是入口，不是自动运行器；在对应 Codex 任务中发起执行请求后才开始工作。[官方 AGENTS.md 说明](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。

## 文件与权威范围

| 文件 | 内容及用途 |
|---|---|
| [PRODUCT.md](PRODUCT.md) | 用户、范围、产品行为、目标指标和延期项 |
| [CONTRACT_SPEC.md](CONTRACT_SPEC.md) | 有限契约语义、执行顺序、版本与失败规则 |
| [examples/README.md](examples/README.md) | 合成输入、契约、身份、预期输出及消费样例 |
| [EXECUTION_PLAN.md](EXECUTION_PLAN.md) | 技术路线、任务交付说明、迁移与操作边界 |
| [ACCEPTANCE.md](ACCEPTANCE.md) | 稳定 AC 编号的验收场景与证据要求 |
| [TASKS.json](TASKS.json) | 机器可读任务、依赖、状态、验收引用与证据 |
| [STATUS.md](STATUS.md) | 当前发现、运行限制、执行日志与交接 |
| [SOURCES.md](SOURCES.md) | 来源、核查日期与实现前需再次确认的外部接口 |
| [DOCUMENT_CHECK.md](DOCUMENT_CHECK.md) | 本次文档/样例一致性检查，不能替代业务运行验收 |

冲突处理：当前用户要求优先；产品范围由 PRODUCT.md 定义，协议行为由 CONTRACT_SPEC.md 定义，任务依赖和状态由 TASKS.json 定义，验收由 ACCEPTANCE.md 定义。发现冲突时先修正文档并记录，不自行选择更宽松的安全解释。

## 给 Codex 的启动任务

下面这段可以直接作为同一项目内的任务请求使用：

> 请在 `/Users/jeremysie/Desktop/A2A项目/a2a-contract-hub` 执行数据契约层改造。先读取 AGENTS.md 和 docs/implementation/README.md，再按规定阅读产品、契约、执行计划、验收、TASKS.json 与 STATUS.md。以 TASKS.json 为任务清单，从第一个未完成且依赖满足的任务开始，持续完成代码实现、必要验证和文档同步。先建立运行基线与严格契约，再修复安全基础，接入 OPA/Presidio，完成双 Agent 会议数据视图、A2A 适配、版本检查和开源 alpha 交付。遵守明确的能力边界；不要为未实现规则回退放行，不要绕过环境权限。遇到缺少外部资源或真人试用时记录具体待办，继续能独立完成的任务。每个任务完成后更新 TASKS.json 的证据及 STATUS.md，最后分别报告已完成、已验证、未验证和需外部输入的事项。不要把本次请求理解为对外部署、推送或联系第三方的授权。

## 续做方式

续做时先核对实际文件和 TASKS.json，不凭上一轮描述假定完成。`done` 必须有相关验收证据；若测试因环境失败则使用 `blocked` 并说明，不填写虚构通过结果。真人试用使用 `awaiting_external_validation`，不阻塞可独立完成的工程工作，也不能被自动标成成功。

技术 alpha 与成熟项目分开评价：自动验收通过可以形成 alpha 候选；真实独立用户试用、长期稳定性与外部安全审查尚未完成时，明确标示缺失证据。
