# 有限数据契约草案

状态：目标规格；严格静态校验、运行时交付及版本发布检查已实现，完整验收按 TASKS.json 跟踪。`spec_version = 0.3.0-draft.1`；这不是已经发布或实现的规范。示例契约自身为 `contract_version = 1.0.0`，与规范版本、Hub 版本、A2A 协议版本分别管理。

## 1. 第一版边界

- 受控单组织部署，允许管理员登记合作方 Agent；无公开自注册组织身份和跨组织身份联邦。
- 同步、完整 JSON 对象交付；不向调用方流式输出未经处理的内容。
- 一个 `meeting-actions` 契约，两个命名视图：`internal-project`、`external-collaboration`。
- OPA 固定、受维护模板读取经过校验的契约。禁止在注册请求中上传任意 Rego、Python、脚本、远程 schema 引用或自定义处理回调。
- Presidio 基线只承诺英文 `en`、`EMAIL_ADDRESS`、指定文本路径。PERSON、电话、中文、图片、文件和商业机密识别不在基线内。
- 不承诺阻止 Hub 之外的通信、接收后的滥用、识别所有个人信息或自动满足法律合规要求。
- 公开通知仅允许批准的事件类型及元数据字段，例如 `contract.updated`、可公开的 contract_id/contract_version；不支持任意 content、会议文本或用户自填自由文本。通知资源也需当前权限和可公开属性验证。

## 2. 契约对象

完整示例见 [contract.meeting.json](examples/contract.meeting.json)。正式 JSON Schema 与加载器已在 `app/contracts/` 实现；发布/激活 API 已实现，以下字段和样例定义其输入规格。

| 字段 | 约束 |
|---|---|
| `spec_version` | 精确匹配受支持版本；不猜测未来版本语义 |
| `contract_id` | 部署内唯一、稳定的标识；示例 `meeting-actions` |
| `contract_version` | 语义化版本；已激活版本不可原地覆盖 |
| `source_schema` | 受限 JSON Schema Draft 2020-12，描述原始 JSON |
| `views` | 至少一项，每项有唯一 `view_id`、显示名称、字段投影、输出 schema 和有序处理列表 |
| `policies` | 有限授权规则列表，禁止未知键和未知条件 |
| `delivery` | `failure_mode=closed`、`audit_required=true`、响应上限和总超时 |

嵌套对象也拒绝未知属性。schema 子集支持 object/array/string/integer/number/boolean/null、properties、required、additionalProperties、items、enum、const、pattern、format、minimum/maximum、min/maxLength、min/maxItems。第一版不允许 `$ref`、组合 schema、正则属性或网络解析；format 必须实际验证，不能只写注释。pattern 来自受审模板，限制长度与复杂度，不把任意复杂正则送入数据面。

每个对象默认且显式设定 `additionalProperties: false`。每条字段路径必须在 source_schema 中静态解析成功，所有声明的输出路径与 output_schema 一致。

## 3. 视图与字段路径

视图字段：`view_id`、`display_name`、`projection`、`output_schema`、`processors`、`purpose`。

`purpose` 是展示性说明，不产生授权。所有可见原始字段必须经 `projection` 明确列出；对象作为容器隐式创建，不能列出整个对象而放行其全部子字段。

路径只允许对象字段点分隔和对象数组的 `[*]`，如 `action_items[*].task`。第一版禁止递归搜索、通配字段 `*`、负下标、索引筛选、脚本表达式、属性名中的点或括号。数组保持原顺序与项目数量，不能通过字段投影改变项目配对关系。

缺失可选字段允许缺失；缺失 source_schema/output_schema 的必填字段必须失败。处理路径的存在性和类型要求由 schema 与 processor 联合确定：可选字段缺失可跳过，但必需文本字段缺失/类型错误不能跳过。

内部输出保留 `owner_name`、`owner_email` 以支持指派任务。外部输出彻底不包含这两个字段，支持创建待分配行动项；不能声称外部视图仍可按真实人员自动指派。

第一版所有向外暴露的自由文本 `title`、`summary`、`action_items[*].task` 均走外部视图规定的邮箱处理。标识限定格式、日期实际校验，不能用标识字段夹带任意文本。

## 4. 授权规则

规则字段：`policy_id`、`effect`（allow/deny）、`view_ids`、`principal`。不支持条件的旧契约不得静默忽略。

`principal` 可以声明 `agent_ids`、`organization_ids`、`roles`，至少有一个非空列表。**同一维度列表内 OR，不同维度之间 AND**。同时满足 organization 与 role 的例子不能被解释为只满足其中之一。

只计算请求视图适用的规则：任意匹配 deny 则拒绝；否则至少一个匹配 allow 才允许；无匹配拒绝。视图处理规则由视图固定，不因“第一个 allow”而减少处理。多个 allow 不改变结果。

授权上下文由服务端建立：已认证 agent_id、管理员登记的 organization_id、当前有效 roles/scopes/is_active/授权修订号、可信请求资源上下文。JWT 不接受自行声明的组织或角色作为最终事实。每次交付前重验当前授权修订；期间撤权则拒绝。

服务端另存独立于契约版本的当前视图授权记录（access grant），至少包含主体、contract_id、view_id、批准的 meeting_id 集合、active 和 revision。运行时允许范围是当前有效 grant 与所请求不可变契约 policies 的交集；任意一侧拒绝都不能放行。修改契约默认版本不会自动修改 grant；管理员撤销视图或资源授权需要更新 grant/revision，所有旧契约同时受影响。最终许可事务锁定/校验身份及 grant 修订；修订在请求中途改变则拒绝该次交付或以新上下文完整重评，不能只换 revision 继续发送。

发现只展示当前主体可见的视图摘要，不公开完整策略或所有者敏感信息。发现结果不是访问凭证。固定契约旧版本、缓存、回滚都不能越过当前停用/撤权规则；旧契约只能被当前授权进一步收紧，不能恢复失效权限。

OPA 输入只包含决策所需上下文与契约引用/策略数据，不默认发送原始响应。决策格式至少为 `allow: boolean`、`reason_code: string`、`matched_policy_ids: string[]`、`view_id: string`、`contract_digest: string`、`policy_revision: string`。Hub 验证类型、目标视图和版本一致性；HTTP 200 没有 result、结果为 null/空对象、超时和错误都失败关闭。

## 5. 内容处理

第一版 processor 只支持 `presidio_redact`：

```json
{
  "processor_id": "external-email-redaction",
  "type": "presidio_redact",
  "paths": ["title", "summary", "action_items[*].task"],
  "language": "en",
  "entities": ["EMAIL_ADDRESS"],
  "replacement": "[EMAIL]",
  "required": true
}
```

执行契约中规定的顺序。冻结识别器、模型、实体、阈值与替换配置并生成 profile revision；这些属于受控部署配置，不能由调用方选择较宽松版本。替换仅作用于检测到的片段，不改其他字符。对固定、已标注的基准邮箱样例要求处理完成；没有命中不证明原文不存在敏感信息。

不要为相同规则另建“测试专用简化引擎”。确定性字段投影先处理，Presidio 再处理保留文本。已删除字段无需送入识别器。每次执行使用独立数据副本，避免两次视图调用互相污染。

不支持的语言、实体、processor 或未准备好的 profile，在契约激活/就绪检查阶段拒绝；执行期间必需 processor 不可用则拒绝。不得悄悄跳过，也不得自动切换宽松规则。

## 6. 原子版本快照与交付顺序

1. 验证调用方和当前权限，绑定 request_id、contract_id/version/digest、view_id、OPA policy revision、识别器 profile revision。
2. 读取不可变契约快照；版本/策略未就绪时失败，不混用两个版本的输出 schema 与处理规则。
3. OPA 决策并验证其结构；拒绝时记录不含原文的拒绝事件。
4. 使用批准的地址和有签名的请求调用数据提供方；设连接/读写超时、总时限、响应上限、并发限制。
5. 完整读取并解析 JSON，校验 source_schema；未知字段和错误类型在投影之前拒绝。
6. 按视图投影，执行全部必需处理；结果不能先流向调用方。
7. 校验 output_schema 与处理完成清单；准备对当前身份和授权做最终检查。
8. PostgreSQL 同一事务中完成当前停用/撤权检查和 delivery receipt/outbox 持久化。使用共同的授权行锁或等价的并发修订校验，使管理员撤权和交付许可提交存在明确原子顺序；禁止检查后无保护地延迟提交。事务提交成功后才返回响应，不能用仅内存日志或普通 Redis publish 代替。
9. 返回处理后的数据及安全元信息；异步分发/索引审计，可恢复重试、幂等处理。

receipt 表示“校验成功并允许尝试交付”，不能等同于客户端已接收。网络断开可能发生在提交后、接收前；禁止宣称 exactly-once 网络交付。第一版请求重试生成新的 request_id，均需重新授权；审计消费按事件 ID 幂等，不能重复污染最终审计记录。

Redis 可用于 outbox 唤醒和公开通知；数据库中待处理 outbox 是恢复来源，消费者需要轮询补偿。Redis 不可用时，PG 提交成功的查询可以继续，不得导致审计丢失。PG 不可用时，不返回成功数据；仅保留无原文的本地错误诊断并告警，不能声称每条拒绝日志均已持久化。

以最终交付许可事务提交为授权的线性化点：先提交的撤权必须阻止之后的许可；已提交许可甚至已发出的字节无法追溯收回。不可承诺撤权能召回已交付数据。

## 7. 逻辑请求与错误

新逻辑请求明确携带 `target_agent`、`contract_id`、`contract_version`、`view_id`、受限 `query`。会议示例 query 必须恰好包含一个合法格式的 meeting_id，拒绝缺失及多余键；原来任意 query_params 不能直接作为身份或授权事实。

注册中心绑定契约与批准的数据提供方，target_agent 必须匹配该绑定。OPA 必须确认请求 meeting_id 在当前 grant 的批准集合内；示例只批准 `meeting-001`。源结构校验之后、投影之前检查响应 meeting_id 与请求完全一致，结构合法但资源不一致也拒绝。不能依赖上游遵守 query 来实现授权。

逻辑响应：request_id、契约引用/version/digest、view_id、decision=delivered、data。内部 matched_policy_ids、敏感地址和识别片段不默认暴露给外部调用方。

REST 建议使用隔离的新版本路径，如 `/api/v2/...`；正式映射在 T05 协议验证后确定并登记。A2A 使用官方 Message/DataPart/Artifact 等受支持类型和扩展协商承载相同语义，不把任意 REST 接口称为 A2A 兼容。下表为 REST 映射建议，A2A 使用所选协议的合法错误映射。

| code | 建议 HTTP | 含义 |
|---|---|---|
| AUTHENTICATION_REQUIRED | 401 | 缺失或无效身份 |
| ACCESS_DENIED | 403 | 当前身份无权访问 |
| CONTRACT_INVALID | 422 | 契约静态检查不通过 |
| CONTRACT_VERSION_UNAVAILABLE | 409 | 请求的快照未就绪或不可用 |
| UPSTREAM_SCHEMA_MISMATCH | 502 | 原始结构不符合契约 |
| UPSTREAM_RESOURCE_MISMATCH | 502 | 返回的资源标识与获授权请求不一致 |
| UPSTREAM_INVALID_JSON | 502 | 上游不是合法 JSON |
| PROCESSING_UNAVAILABLE | 503 | 必需策略/内容处理依赖不可用 |
| OUTPUT_CONTRACT_VIOLATION | 502 | 处理后输出不符合约定 |
| AUDIT_PERSISTENCE_UNAVAILABLE | 503 | 交付记录不能持久化 |
| PAYLOAD_TOO_LARGE | 413 | 超出契约或系统上限 |
| UPSTREAM_TIMEOUT | 504 | 上游超出时限 |

错误包含稳定 code 与 request_id，路径信息按调用方权限返回；不携带原文值、密钥、栈或内部地址。系统上限始终可以比契约更严格。

## 8. 生命周期、发布与迁移

生命周期：draft → validated → active → retired；失败校验不得进入 active。仅所有者/管理员可发布；服务器重新校验，客户端标记 validated 不可信。

一个逻辑契约可以保留多个不可变版本；激活一个新默认版本不修改正在处理的旧快照。请求必须解析为明确版本，发现可以提供默认版本，但实际响应必须注明版本。

兼容性结果分为 compatible / breaking / review_required。字段删除、类型变化、必填变化与 output projection 变化按已登记消费者需求及 schema 子集检查；授权扩张/收紧、识别器更新属于安全或行为变化单独报告，不伪装成普通 schema 兼容。

草案保存、具体版本激活、默认版本切换是三个不同操作。发布报告同时包含结构结论、已登记消费样例结果、安全/行为变化；没有消费方登记不能被报告成“全部消费者验证通过”。

| 分类 | 保存草案 | 激活具体版本 | 切换默认版本 |
|---|---|---|---|
| compatible | 允许 | 所有静态与消费检查通过后，由授权所有者激活 | 允许所有者显式切换，不能仅因上传而切换 |
| breaking | 允许 | 原地/同主版本替换禁止；新主版本需独立消费样例和明确迁移记录后显式激活 | 不自动切换；所有登记的默认版本消费方迁移验证完成后，所有者才能切换 |
| review_required | 允许 | 第一版阻止激活；缩小到可判定语义或补足所需证据后重新分类 | 阻止切换 |

新主版本并行激活后，未迁移消费方仍可固定旧版，但继续受当前 grant/撤权约束。安全/行为变化需要所有者显式确认具体变化并记录，不能以 compatible 标签自动批准权限扩张。新增代码不得提供绕过这些检查的通用 force 参数。

消费者未登记时只能报告结构差异，不能声称识别全部业务影响。删除 required 的 owner_email 会破坏内部自动分配任务；外部待分配任务不依赖它。

旧 v0.2 契约先离线检查：未知 conditions、错误 effect、缺失 transform、通配符和歧义多策略均列出错误。有限可映射规则才生成新草案，不自动激活。对比结果仅用于诊断，任一引擎允许即允许的双引擎模式禁止。新路径失败不能回退旧接口放行；旧接口若保留也必须经过同一安全核心，否则默认关闭。


## T01 实现边界（2026-09-13）

离线命令 `python -m app.contracts <contract.json>` 只校验，不激活。当前加载器
只接受对象数组、date/email 格式、示例中 meeting/item 的两个审核正则、三段稳定
contract_version（不接受 prerelease/build 标记）。扩展这些范围必须先实现并验证；
拒绝未知能力不是自动兼容。递归 meta-schema 使用内部 `$defs/$ref` 描述契约形状，
用户 source/output schema 仍禁止任何 `$ref`。完整 AC 结果以 TASKS.json 为准。
