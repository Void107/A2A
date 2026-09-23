# 合成会议场景样例

状态：已通过生产交付入口、真实服务及官方 A2A 客户端执行；详细覆盖与限制见 ../../verification/RESUME.md。所有姓名、邮箱、组织和会议均为合成数据，无凭据。`example.com` 仅用于内容示例，不作为请求目标。

## 文件

| 文件 | 用途 |
|---|---|
| [contract.meeting.json](contract.meeting.json) | 草案契约，含原始与两个输出 JSON Schema |
| [identities.example.json](identities.example.json) | 由管理员预置的三个可信身份上下文示例，禁止把客户端提交的同形 JSON 视为认证 |
| [raw.meeting.json](raw.meeting.json) | 数据提供方的完整合成响应 |
| [expected.internal.json](expected.internal.json) | project-agent 请求 internal-project 的期望 data |
| [expected.external.json](expected.external.json) | partner-agent 请求 external-collaboration 的期望 data |
| [consumer.requirements.json](consumer.requirements.json) | 两个消费方真正需要的字段和业务效果 |
| [cases.json](cases.json) | EX-01..EX-10 请求、突变、依赖故障的描述性样例 |

预期输出只表示逻辑响应中的 `data`，不包含动态 request_id、时间、版本 digest 等元信息。比较 JSON 结构和值，不依赖键顺序。content processor 只替换邮箱片段为 `[EMAIL]`，其他字符和数组顺序不变。

## 消费效果

- 内部：创建两个行动项，按 owner_email 指派负责人，保留 item_id 与截止日期。
- 外部：创建两个待分配行动项，保留 task 与截止日期，不要求知道真实负责人。
- 验证应使用无外部副作用的本地消费样例，不向真实任务系统写入。
- email 藏在摘要和任务文本中，也属于外部检测范围。title 同样纳入扫描，额外用例应覆盖它。
- 外部视图不承诺识别自由文本中的全部姓名、手机号、商业机密或中文个人信息；如业务要求完全清除此类内容，必须另立已验证的内容策略或禁用该文本字段。

## 转为测试的方法

实现时将这些 JSON 作为固定夹具，通过真实服务入口运行。EX 描述并非测试运行器；T01/T08/T13 负责把它们落成测试。不能只手写一段复制预期 JSON 的代码来冒充业务路径验证。

cases.json 的 mutations 使用 JSON Pointer 描述单次测试输入突变；simulate_* 和 server_identity_change 只供测试环境控制，不应加入公开请求模型。所有依赖故障在隔离的本地实例或受控替身中注入。

cases.json 的 default_query 为 `meeting_id=meeting-001`。identities.example.json 的 access_grants 是管理员预置的当前授权，独立于契约版本；未批准的会议在取数前拒绝，返回会议 ID 与请求不一致时也拒绝。

输出结构变化的正反例由兼容检查任务从示例复制生成，不改写已确认的黄金输入输出来迁就实现。
