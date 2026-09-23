# 2026-09-22：T13 失败诊断与 AC-17

本轮完成 T13 中的 AC-17 缺口；T13/T14 仍为 in_progress，不能宣布所有自动验收或发布候选通过。已有修改保留；没有部署、推送或联系第三方。

## 已完成

- 新增可空 diagnostics 列及迁移 `20260922_diagnostics`；旧失败记录保持 null，不补造历史信息。
- 交付核心从开始到失败沿用同一 request_id。REST 与官方 A2A 都持久化该请求的同一安全元数据；只有记录所属主体或拥有 audit scope 的管理员可查询。
- 请求引用与已核实快照分开：contract_id/version/view_id 来自经过格式校验的请求；仅通过当前 grant 绑定后记录 digest。未知或未授权资源不能经诊断泄露其摘要。
- 记录实际失败阶段、初始 OPA policy_decision/revision、已完成 processor 和校验结果。policy_decision=allowed 只表示 OPA 的初始决定；receipt 阶段仍可能因撤权拒绝。profile_revision 仅在 processor 完整完成后登记；没有 processor 且处理成功时为 none。未确认的 revision 为 null，未确认的校验为 unknown。
- 成功 receipt 查询补充 policy/profile revision、完成列表和验证结果；状态仍为 ready_to_send，不代表客户端确认收到。
- 字段白名单、有限阶段枚举、标识格式与长度限制；不接受 payload、任意异常文本、匹配片段或凭据。错误响应仅包含稳定错误码、request_id、diagnostic_recorded；诊断通过授权查询获取。
- PG 不可用或诊断不能安全保存时返回 diagnostic_recorded=false，不宣称已记录，也不返回业务数据。认证/请求结构校验尚未进入交付核心的错误不制造快照记录。

## 当前执行证据

| 验证 | 结果 | 证据 |
|---|---|---|
| `.venv/bin/python -m pytest -q` | 125 passed，退出 0；一条故意错误 JWT 密钥警告 | 20260922-diagnostics-final-unit.log |
| 新增诊断回归 | 11 项：绑定/OPA 拒绝及故障/上游/源结构/processor/输出/提交、存储失败、字段隐私、历史记录与管理员 | tests/contracts/test_failure_diagnostics.py |
| `.venv312/bin/python scripts/verify_delivery.py` | 退出 0，真实 PG/Redis/OPA/Presidio/签名提供方/Hub 与官方 SDK | 20260922-diagnostics-final-stack.log |
| 数据库升级 | 真实专用测试库从 20260914_publication 到 20260922_diagnostics | 20260922-diagnostics-stack.log 开头 |
| 真实故障与恢复 | 中途撤权、PG/Redis 停机恢复、Presidio/OPA 停机、断开后重试、无原文日志断言通过 | 20260922-diagnostics-final-stack.log |
| 传输一致性 | 实际 Presidio 停机后 REST 与官方 A2A 查到相同诊断；成功记录仍为 ready_to_send | 同上 |
| 格式检查 | git diff --check 退出 0 | 本轮命令记录 |

首次集成执行退出 1：新增 processing 断言误插入正常 SDK 初始化位置；修复测试位置后重跑成功，保留 20260922-diagnostics-stack.log。随后命名澄清及历史记录回归后的最终日志如上。不将该测试编排失败写为产品通过。

环境：macOS arm64；快速测试 Python 3.9.6、应用 Python 3.12.14；PostgreSQL 17.6、Redis 7.4.5、OPA 1.0.0、Presidio 2.2.360、官方 A2A SDK 0.3.0。沿用固定依赖与独立 Presidio 环境，无模型下载。OPA 原临时文件消失，本轮从官方 v1.0.0 release 恢复 darwin arm64 static 文件并核对官方 SHA256：836cfeaa6713c59ae681e4f1e2f510980ae3df15112adc30dc6cebc5ff636db4。初次非 static 文件名返回 404，随后按官方资产清单改正，未更换版本或关闭 TLS。

专用 PG/Redis 故障测试结束后均健康；脚本创建的临时 Hub/OPA/Presidio 子进程正常停止。测试只操作 compose.test.yaml 的数据库，不连接宿主未知 .env。已有完整演示容器未重建，不能声称它们运行了本轮新代码；下次更新需正常构建并迁移到新 head。

## 尚未验证与下一步

AC-17 更新为 PASS。AC-01/02/03/04/06/13/21/23/24 的完整矩阵与证据缺口仍按 RESUME.md 和 TASKS.json 保留；本轮没有重跑完整 verify_all、干净安装、资源负载测量或远端 CI。发布门槛仍必须拒绝。

下一步继续 T13：补发布/身份接口交叉矩阵、真实 TLS 与 OPA 故障恢复组合、完整入口资源边界、未迁移库就绪拒绝与资源采样。真人试用和安全私密报告责任人与渠道仍需外部输入。Presidio 混淆邮箱漏检没有修复，不扩大内容检测承诺。
