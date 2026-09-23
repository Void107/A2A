# 2026-09-14 中断续做核验

> 最新 2026-09-22 四项推进结果：[20260922-FOUR-STEPS.md](20260922-FOUR-STEPS.md)。其余本地自动门槛均已补齐；AC-24 等待托管 CI，AC-22 等待真人。旧缺口说明保留为历史。

> 2026-09-22 更新：AC-17 失败诊断已补齐；最新默认测试 125 项通过，真实交付栈通过，迁移 head 为 20260922_diagnostics。见 [本轮报告](20260922-DIAGNOSTICS.md)。下文 2026-09-14 的 AC-17 缺口与测试数量属于历史记录；其余未完成门槛仍以 TASKS.json 为准。

本报告区分旧证据、当前执行、尚未覆盖的完整门槛。主仓库 HEAD 与工作树摘要记录在 `resume-source-manifest.json`；本轮未提交、推送、对外部署或联系第三方。全部服务与数据为本地合成测试用途。

## 当前完成的工作

T08/T10：同一个交付核心跑通 REST 与官方 A2A SDK 0.3.0 内外部双视图；实际消费者生成两项正确分配/待分配任务。新增逆序请求、原始结构漂移、受限 query、无 grant 的真实身份、真实 OPA 空决定、依赖停止、交付中途撤权及固定版本请求中途切换默认版检查。

T11：有限递归差异、安全变化单列、已登记合成消费样例的生产处理验证、版本级持久化证据、明确迁移标识及报告摘要确认。compatible、breaking、review_required 分别控制激活和默认切换。未知语义或失败样例不可被确认摘要绕过。旧 0.2 迁移仅生成草案，拒绝未知条件/变换/歧义。

T12 已完成干净离线安装和重启验证；T13–T14：已实现本地启动包、独立签名提供方、轻量客户端、合成消费者、健康探针修复、CI 与发布门槛、负载测量及维护文档；任务 done 与完整 AC 必须继续以 TASKS.json 为准。

## 当前执行证据

| 检查 | 当前结果 | 证据 |
|---|---|---|
| 默认 Python 测试 | 114 passed；1 条故意错误 JWT 短密钥警告 | `resume-final-suite.log` |
| 顺序本地 CI 命令 | 所有子命令退出 0；unit 当时为 108，之后新增 2 项也通过 | `ci-results.json`、`resume-ci-local.log` |
| 真实 PG 迁移/两次 lifespan | 至 `20260914_publication`；未配置交付依赖时 `/ready` 正确 503 | `ci-verify_real_baseline.log` |
| 当前身份/授权/公开元数据 | 真实 API + PG/Redis 执行通过 | `ci-verify_security.log` |
| 上游签名、地址、资源限制 | 实际 HTTP/Redis 及可控故障通过 | `ci-verify_upstream.log` |
| receipt/outbox、失败保留、恢复与双消费者 | 真实 PG，Redis 停机及独立进程恢复通过 | `ci-verify_receipts.log` |
| OPA 明确决定、错误/超时关闭 | 真实 OPA 成功/拒绝，异常适配检查通过 | `ci-verify_opa.log` |
| 固定 Presidio/结构/消费样例 | 实际独立识别服务通过 | `ci-verify_processing.log` |
| 完整交付/版本/官方 A2A/故障 | 真实独立服务链路通过 | `ci-verify_delivery.log` |
| 登记消费反例 | 缺邮箱与错误任务效果失败，日期配对改变可见 | `resume-consumer-negative.log` |
| 语法编译 | `python -m compileall -q app scripts sdk examples` 退出 0 | 本轮命令记录 |

运行环境：主应用 Python 3.12.14；快速测试 Python 3.9.6；Presidio 独立 Python 环境；PG 17.6、Redis 7.4.5、OPA 1.0.0、官方 A2A SDK 0.3.0、Presidio 2.2.360、spaCy 3.7.5、tldextract 5.3.0。没有 NLP 模型下载。精确环境锁与依赖元数据分别在 requirements-*.lock 和 resume-*-dependency-metadata.json；元数据不是第三方许可法律审查。

当前命令：

```sh
docker compose -f compose.test.yaml up -d --wait
UNIT_PYTHON=.venv/bin/python .venv312/bin/python scripts/verify_all.py
MEASURE_DELIVERY=1 .venv312/bin/python scripts/verify_delivery.py
.venv/bin/python -m pytest -q
python scripts/verify_release.py
```

`OPA_BINARY` 与 `PRESIDIO_PYTHON` 可显式指定本地独立可执行文件。默认 OPA 路径是本次已验证的 `/private/tmp/a2a-opa-1.0.0`；其他机器必须按 CI/README 准备自己的固定依赖，不依赖这个个人临时文件。验证入口不会使用宿主 `.env` 连接未知数据库。

## 负载结果及限制

预热后每种视图分别在并发 1、5、10 运行 100 次，共 600 次；另保留 30 次预热。600/600 成功，错误/超时均为 0。客户端 p95（毫秒）：内部约 84 / 329 / 787，外部约 89 / 370 / 769；这是本机实测，没有生产容量承诺。

原始数据：`resume-performance.json`。阶段记录：`resume-core-metrics.jsonl`、`resume-performance-phases.json`。授权阶段度量 OPA，不包括最初身份读取；完整客户端耗时包含该开销。阶段汇总包括预热及初始校验请求，未按并发分组。冷启动数字包括本地服务启动、管理员预置和首个视图，不包含首次联网下载；未设置容器 CPU/内存配额，没有完整运行期资源采样。这些限制使 AC-23 完整门槛仍待补齐，不能仅凭 600 次成功标为全通过。

测量结束时 outbox 待处理 41 条；后续真实验证启动消费者后已恢复到 0，见 `resume-outbox-recovery.json`。这说明本次积压后来被处理，不等于已建立积压 SLA。

## 旧证据核对与测试迁移

原 `t08-fault-stack.log` 确实含成功总结，与旧任务描述一致；但只覆盖 A2A 外部成功视图，未完成新版本变更流程，不能单独代表 T10/T11 完成。当前证据已重新运行，旧日志保留。

旧默认测试实际出现 23 failed、73 passed、10 errors，原因包括旧 API 预期与已关闭功能冲突以及 8 项 legacy 安全回归。迁移前源码保存在 `legacy-test-sources/*.txt`，未把它们的过时开放注册/任意内容发布预期算作新能力。有效场景对应如下：

- 身份、过期、伪造、停用、当前 scope：默认 `test_auth.py`、`hacker_agent.py` 与真实 `verify_security.py`。
- 任意广播内容：改为必须拒绝；允许的公开元数据、非所有者/非公开资源拒绝均有实际接口测试。
- 旧查询：有效身份也必须 410，不重开旧路径；超时/连接/非法 JSON 转到实际 upstream adapter 与真实 HTTP 验证。
- 旧 transform 与审计安全反例：仍默认收集，修复异常吞并和未知语义放行。旧诊断代码不成为第二个运行时授权引擎。

EX-09 停用身份的当前实现返回 401 `AUTHENTICATION_REQUIRED`，而旧描述写 `ACCESS_DENIED`。状态码语义差异明确保留；已验证旧 JWT 被拒绝且没有业务数据。未为测试放宽黄金输出。

## 检测质量边界

重新执行 `presidio_quality.py`：固定回归 4 个样本，TP=3、FP=0、FN=0；探索 5 个样本，TP=2、FP=0、FN=1。混淆邮箱 `alice @ example . com` 仍漏检。见 `t07-quality.json`，分母是实体片段，不能把样本数当邮箱数。PERSON、中文与电话不属于支持实体；没有零泄露或全面匿名化结论。

## 尚未完成的完整 AC

TASKS.json 中没有 PASS 的自动 AC 都不是通过。已有局部证据不替代下列剩余矩阵：

- AC-01/02/03/04/06：部分已由静态、适配器和真实路径覆盖，仍需逐条汇总/补足所有发布负例、身份/接口交叉矩阵、完整 TLS 与 OPA 错误状态/非法 JSON/恢复组合。
- AC-13：仍需把所有必需服务超时与资源/并发边界组合逐项核对到完整交付入口。AC-11 的四种受控输出/完成清单故障现已通过，见 resume-output-faults.log。
- AC-15/16 的真实进程退出补充已通过；客户端断开、重试、失败记录隔离和普通日志检查也已通过。AC-17 仍需核对所有失败阶段应有的契约/策略/profile 元数据：当前失败记录仅保存 request_id、主体和错误码，不伪造尚未执行步骤的信息。
- AC-21：干净离线安装、重启保留及缺 Presidio 状态均已有证据；尚未单独用全新未迁移库执行完整就绪拒绝矩阵，首次下载耗时也未完整计量。
- AC-23：补齐前述阶段/资源采样和冷启动定义。
- AC-24：CI 定义已写，远端 CI 未触发；完整 AC 映射和发布证据仍有缺口。`verify_release.py` 必须对这些缺口返回非零。
- AC-22：无独立真人参与者，保持 NOT_RUN / awaiting_external_validation。

需要外部输入：未参与开发的真实试用者，以及所有者确认的私密安全报告渠道/责任人。当前请求不授权远端部署、推送或联系人员。

## 完整本地安装结果

首次容器内联网下载遇到 TLS EOF/索引失败；Python 3.9 与 3.12 的 click 条件依赖冲突已修正。通过本机预取同版 Linux aarch64 wheels 后，干净镜像内离线安装与 pip check 通过，见 resume-offline-repaired-build.log、resume-wheel-manifest.json。没有复制旧虚拟环境或关闭 TLS 校验。

首次启动暴露 Presidio 镜像未带共享 profile 模块，已修复为无 Hub 运行依赖的 app/profile.py；重新构建并达到完整健康状态。新建卷/网络、迁移、启动见 resume-clean-offline-build.log 与 resume-offline-repaired-start.log。首次双视图见 resume-clean-demo-retry.log。

重启 PG/Hub/提供方后已有 receipt 数量保持 2 → 2；再运行演示成功，见 resume-clean-*-restart.log。停止 Presidio 时就绪为 503 PROFILE_NOT_READY，恢复后 200，见 resume-clean-readiness.json。在线直接构建仍未重新验证成功，README 保留经验证的离线安装路径和在线失败边界。

新增当前证据：resume-output-faults.log（4 项）、resume-process-failures.log（真实进程退出）、resume-disconnect-stack.log（真实客户端断开/重试/记录隔离/日志）。默认测试最新总数 114。仍未宣布所有自动 AC 或发布候选通过。
