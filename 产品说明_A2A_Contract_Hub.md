# A2A-Contract-Hub 产品说明

> 写给没有技术背景的你。读完这份文档，你就能理解这个产品是什么、解决什么问题、怎么用起来。

---

## 一、这个产品是什么？

**A2A-Contract-Hub** 是一个 **AI Agent 之间安全交换数据的中间平台**。

你可以把它想象成一个 **"AI 世界的数据海关"**：

- 每个 AI Agent（智能助手）都有自己擅长的数据——天气、金融、医疗、物流……
- 当 Agent A 想要 Agent B 的数据时，不能直接去拿，必须经过这个"海关"
- "海关"会做四件事：**验身份 → 查政策 → 做脱敏 → 记日志**

---

## 二、它解决了什么问题？

### 没有它的时候

| 问题 | 后果 |
|------|------|
| Agent 之间直接通信，没人管 | 敏感数据（手机号、工资、坐标）随便传 |
| 没有统一的身份验证 | 任何人都可以冒充一个 Agent 去偷数据 |
| 没有操作记录 | 出了数据泄露事故，查不到是谁干的 |
| 没有脱敏规则 | 本来只该给你看城市名，结果把精确经纬度都给了 |

### 有了它之后

- 每个 Agent 注册时签好"数据契约"——**什么数据可以给谁看、怎么脱敏**
- 所有数据交换都经过 Hub，**自动执行脱敏规则**
- 每一次操作都有审计日志，**可追溯、可审计**

---

## 三、核心功能一览

### 1. Agent 注册（Schema Registry）

每个 AI Agent 加入平台前，需要"登记户口"：

- **我是谁**：名字、所属组织、联系地址
- **我有什么数据**：天气数据、金融数据、用户画像……
- **谁能看**：所有人都能看 / 只有同组织的能看 / 特定 Agent 才能看
- **怎么脱敏**：坐标要模糊化、工资只给范围、邮箱打星号

注册完成后，Agent 会收到两把"钥匙"：
- **API Key**：用来向平台证明"我是我"
- **Hub Secret**：用来验证平台发来的请求是真的

> 这两把钥匙只会显示一次，请妥善保管。

### 2. 身份认证（Auth）

Agent 每次和平台通信，都要先"刷卡"：

1. Agent 用 API Key 换取一个有时效的通行证（JWT Token）
2. 之后的每个请求都带着这个通行证
3. 通行证过期了就重新换一个

就像你用工牌进公司大楼——工牌有有效期，过期了要去前台续。

### 3. 跨 Agent 数据查询（Query Engine）

这是最核心的功能。当 Agent A 想要 Agent B 的数据时：

```
Agent A → Hub → 检查策略 → 转发给 Agent B → 拿到数据 → 脱敏处理 → 返回给 Agent A
```

**举个具体例子：**

- 金融机器人想要天气机器人的"地点数据"来分析农产品价格
- Hub 检查天气机器人的契约：外部组织可以看地点数据，但坐标要模糊化
- Hub 把请求转给天气机器人，拿到原始数据
- Hub 自动把精确坐标 `31.2304` 变成范围 `"30-40"`
- 金融机器人拿到的是脱敏后的安全数据

**安全保障：**

| 场景 | 处理方式 |
|------|---------|
| 请求的数据不在契约里 | 直接拒绝，返回"未在契约中声明" |
| 没有匹配的访问策略 | 直接拒绝（宁可误拒，不可误放） |
| 目标 Agent 挂了/太慢 | 5 秒连不上或 10 秒没响应就断开，返回明确错误 |
| 响应数据太大（超过 5MB） | 立即截断，防止撑爆平台 |

### 4. 数据脱敏（Transform）

平台支持多种脱敏方式：

| 方式 | 效果 | 适用场景 |
|------|------|---------|
| **删除**（redact） | 字段完全消失 | 绝对不能泄露的数据 |
| **打码**（mask） | `alice@corp.com` → `a************m` | 邮箱、手机号 |
| **哈希**（hash） | `张三` → `a1b2c3d4e5f6` | 需要去重但不能暴露原值 |
| **泛化**（generalize） | `85000` → `"80000-90000"` | 薪资、年龄 |
| **截断**（truncate） | 只保留前 N 个字符 | 超长文本 |
| **字段过滤**（filter_fields） | 只保留白名单字段 | 复杂对象只给看部分 |
| **聚合**（aggregate） | 数组变成 `{count: 5}` | 只给数量不给明细 |

还支持嵌套数据的脱敏——比如一个列表里每个人的工资都要泛化：
```
candidates[*].salary  →  每个人的 salary 都会被脱敏
```

### 5. 广播系统（Broadcast）

Agent 可以向所有人发公告：

- **发布**：天气机器人发布"台风预警"到"天气"频道
- **订阅**：所有关心天气的 Agent 实时收到推送

使用场景：数据更新通知、系统公告、事件触发等。

### 6. 审计日志（Audit Trail）

每一次数据交换都会被记录：

- **谁** 向 **谁** 要了 **什么数据**
- 结果是 **放行 / 拒绝 / 脱敏后放行**
- 命中了 **哪条策略**
- 执行了 **哪些脱敏规则**

支持按 Agent、数据类型、操作结果等条件筛选，支持分页浏览。

审计日志是异步写入的——不会拖慢正常的数据交换，但每一笔都会记录。

---

## 四、系统架构（看图理解）

```
┌─────────────┐         ┌─────────────────────────────────┐         ┌─────────────┐
│  Agent A    │         │       A2A-Contract-Hub           │         │  Agent B    │
│ (金融机器人) │────①───▶│                                 │────③───▶│ (天气机器人) │
│             │◀───⑥────│  ①  验证 Agent A 的 JWT         │◀───④────│             │
└─────────────┘         │  ②  查 Agent B 的契约策略        │         └─────────────┘
                        │  ③  转发请求给 Agent B           │
                        │  ④  流式接收响应（限 5MB）        │
                        │  ⑤  执行脱敏规则                 │
                        │  ⑥  返回脱敏后数据给 Agent A     │
                        │  ⑦  异步记审计日志               │
                        │                                 │
                        │  ┌──────────┐  ┌─────────────┐  │
                        │  │PostgreSQL│  │    Redis     │  │
                        │  │ 数据存储  │  │ 广播+审计缓冲 │  │
                        │  └──────────┘  └─────────────┘  │
                        └─────────────────────────────────┘
```

---

## 五、API 接口速查表

> 基础地址：`http://你的服务器地址:8000`

### 不需要登录的接口

| 接口 | 用途 |
|------|------|
| `GET /health` | 检查服务是否活着 |
| `GET /ready` | 检查数据库和缓存是否正常 |
| `POST /api/v1/agents/register` | 注册新 Agent |
| `POST /api/v1/auth/token` | 用 API Key 换 JWT |

### 需要登录的接口（带 JWT Token）

| 接口 | 用途 |
|------|------|
| `GET /api/v1/agents/discover` | 发现所有可用 Agent |
| `POST /api/v1/interact/query` | 向目标 Agent 查询数据 |
| `POST /api/v1/topics/publish` | 发布广播消息 |
| `GET /api/v1/topics/subscribe` | 订阅广播频道（实时推送） |
| `GET /api/v1/audit/logs` | 查看审计日志 |

### 交互式文档

启动服务后，打开浏览器访问：

```
http://你的服务器地址:8000/docs
```

这是系统自动生成的可视化 API 文档，可以直接在页面上填参数、点按钮测试每个接口。

---

## 六、快速上手（5 分钟体验）

### 前提：服务已启动

```bash
cd a2a-contract-hub
source venv/bin/activate
uvicorn app.main:app --reload
```

### 第 1 步：注册你的 Agent

在终端执行（或在 /docs 页面操作）：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/agents/register \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my-first-agent",
    "display_name": "我的第一个 Agent",
    "callback_url": "http://localhost:9999/api",
    "data_contract": {
      "version": "0.2.0",
      "schemas": [
        {
          "schema_id": "greeting",
          "name": "问候语",
          "sensitivity_level": "public"
        }
      ],
      "policies": [
        {
          "policy_id": "allow-all-greeting",
          "effect": "allow",
          "schema_ids": ["greeting"],
          "principal": {"public": true}
        }
      ],
      "transforms": []
    }
  }'
```

你会收到类似这样的响应：

```json
{
  "agent_id": "my-first-agent",
  "api_key": "xYz123...",
  "hub_shared_secret": "aBc456...",
  "access_token": "eyJhbG...",
  "message": "注册成功！请妥善保存 api_key 和 hub_shared_secret..."
}
```

**把 `api_key` 和 `access_token` 复制下来。**

### 第 2 步：用 API Key 换 Token

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "my-first-agent", "api_key": "你的api_key"}'
```

### 第 3 步：查看有哪些 Agent

```bash
curl http://127.0.0.1:8000/api/v1/agents/discover \
  -H "Authorization: Bearer 你的access_token"
```

### 第 4 步：查看审计日志

```bash
curl "http://127.0.0.1:8000/api/v1/audit/logs" \
  -H "Authorization: Bearer 你的access_token"
```

---

## 七、数据契约怎么写？

数据契约是每个 Agent 的"数据分享政策"，由三部分组成：

### 1. schemas —— 我有什么数据

```json
{
  "schema_id": "employee_info",
  "name": "员工信息",
  "fields": [
    {"field_id": "name", "type": "string", "sensitivity": "public"},
    {"field_id": "salary", "type": "number", "sensitivity": "confidential"},
    {"field_id": "email", "type": "string", "sensitivity": "pii"}
  ],
  "sensitivity_level": "internal"
}
```

### 2. policies —— 谁能看

```json
{
  "policy_id": "allow-internal-employees",
  "effect": "allow",
  "schema_ids": ["employee_info"],
  "principal": {"organizations": ["my-company.com"]},
  "transform_ids": ["mask-salary"]
}
```

**principal 支持四种匹配方式：**

| 方式 | 含义 | 示例 |
|------|------|------|
| `"public": true` | 所有人都能看 | 天气预警 |
| `"organizations": [...]` | 指定组织能看 | 公司内部数据 |
| `"agent_ids": [...]` | 指定 Agent 能看 | 点对点授权 |
| `"roles": [...]` | 指定角色能看 | 有 "audit" 权限的 |

**effect 只有两种：**
- `"allow"` —— 允许访问（可附带脱敏规则）
- `"deny"` —— 拒绝访问（优先级高于 allow）

### 3. transforms —— 怎么脱敏

```json
{
  "transform_id": "mask-salary",
  "type": "generalize",
  "applies_to_fields": ["salary"],
  "config": {}
}
```

### 组合起来就是

> "员工信息这个数据，同公司的 Agent 可以看，但工资字段要泛化成范围。"

---

## 八、常见问题

**Q: 我没有技术背景，能用这个系统吗？**
A: 系统自带可视化 API 文档（访问 `/docs`），可以在网页上直接点击测试。但首次部署建议找有技术背景的朋友协助。

**Q: 查询数据时返回 502 错误？**
A: 这表示目标 Agent 的服务没有运行。你需要确保目标 Agent 在 `callback_url` 地址上提供了可访问的服务。

**Q: 审计日志查询为空？**
A: 审计日志是异步写入的（通过缓冲区批量写入数据库）。做完操作后等几秒再查，日志就会出现。

**Q: API Key 丢了怎么办？**
A: API Key 只在注册时显示一次。如果丢失，需要重新注册一个新的 Agent。

**Q: 数据契约可以修改吗？**
A: 可以。系统会记录每一版契约的历史，支持回溯。

**Q: 支持多少个 Agent 同时使用？**
A: 默认配置支持数百个 Agent 并发使用。如需更大规模，可以调整数据库连接池和服务器配置。

---

## 九、技术规格

| 项目 | 值 |
|------|-----|
| 后端框架 | FastAPI (Python) |
| 数据库 | PostgreSQL |
| 消息队列 | Redis |
| 认证方式 | JWT + API Key |
| 通信协议 | HTTP/REST + SSE |
| 规范版本 | Agent Data Contract Spec v0.2.0 |
| 响应体积上限 | 5MB（可配置） |
| Token 有效期 | 60 分钟（可配置） |

---

*本文档基于 A2A-Contract-Hub v0.2.0 编写。*
