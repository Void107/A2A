# A2A-Contract-Hub

> **AI Agent 数据契约交换枢纽** — 让 AI Agent 之间安全、合规地交换数据。
>
> A secure data exchange hub for AI Agents — enforcing data contracts, access policies, and automatic de-identification between autonomous agents.

---

## 这是什么？ / What is this?

A2A-Contract-Hub 是一个 **AI Agent 间的数据交换中间件**，类似于"AI 世界的数据海关"。每个 Agent 注册时签订数据契约（schemas + policies + transforms），Hub 在转发数据时自动执行策略匹配和脱敏处理。

A2A-Contract-Hub is a **data exchange middleware for AI Agents** — think of it as a "data customs" for the AI world. Each Agent registers with a data contract (schemas + policies + transforms), and the Hub automatically enforces access policies and applies data de-identification when forwarding requests.

### 核心流程 / Core Flow

```
Agent A ──request──▶ Hub ──policy check──▶ Hub ──forward──▶ Agent B
                                                              │
Agent A ◀──masked data── Hub ◀──raw data────────────────────┘
                          │
                          └──async──▶ Audit Log (PostgreSQL)
```

---

## 功能特性 / Features

| 模块 Module | 描述 Description |
|-------------|-----------------|
| **Auth** | JWT + API Key 双重认证 / Dual authentication with JWT & API Key |
| **Schema Registry** | Agent 注册 + 数据契约管理 / Agent registration & data contract management |
| **Query Engine** | 跨 Agent 查询，策略匹配 + 自动脱敏 / Cross-agent queries with policy matching & auto de-identification |
| **Broadcast** | Redis Pub/Sub + SSE 实时广播 / Real-time broadcast via Redis Pub/Sub & SSE |
| **Audit Trail** | 异步审计管道（Redis Stream → PostgreSQL）/ Async audit pipeline |
| **Transform** | 8 种脱敏类型，支持 `[*]` 数组路径 / 8 de-identification types with JSONPath `[*]` array support |

### 脱敏类型 / De-identification Types

| 类型 Type | 效果 Effect | 示例 Example |
|-----------|-------------|-------------|
| `redact` | 删除字段 / Remove field | `salary` → *(deleted)* |
| `mask` | 打码 / Partial mask | `alice@corp.com` → `a************m` |
| `hash` | 哈希 / Hash | `张三` → `a1b2c3d4e5f6` |
| `generalize` | 泛化 / Generalize | `85000` → `"80000-90000"` |
| `truncate` | 截断 / Truncate | Keep first N chars |
| `filter_fields` | 字段过滤 / Whitelist fields | Keep only allowed keys |
| `aggregate` | 聚合 / Aggregate | `[1,2,3]` → `{count: 3}` |
| `custom` | 自定义 / Custom | *(v1.0)* |

---

## 技术栈 / Tech Stack

- **Framework**: FastAPI (async Python)
- **Database**: PostgreSQL + SQLAlchemy (asyncpg)
- **Cache/MQ**: Redis (Pub/Sub + Stream)
- **Migration**: Alembic (async)
- **Auth**: JWT (PyJWT) + bcrypt + HMAC-SHA256
- **Spec**: Agent Data Contract Spec Core v0.2.0

---

## 快速开始 / Quick Start

### 环境要求 / Prerequisites

- Python 3.9+
- PostgreSQL 14+
- Redis 6+

### 安装 / Installation

```bash
# 克隆仓库 / Clone
git clone https://github.com/Void107/a2a-contract-hub.git
cd a2a-contract-hub

# 创建虚拟环境 / Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖 / Install dependencies
pip install -r requirements.txt

# 配置环境变量 / Configure environment
cp .env.example .env
# 编辑 .env，填入你的数据库密码和 JWT 密钥
# Edit .env with your database password and JWT secret
```

### 初始化数据库 / Initialize Database

```bash
# 创建数据库 / Create database
createdb a2a_hub

# 执行迁移 / Run migration
alembic upgrade head
```

### 启动 / Run

```bash
uvicorn app.main:app --reload
```

打开浏览器访问 / Open in browser:
- http://127.0.0.1:8000/health — 健康检查 / Health check
- http://127.0.0.1:8000/docs — 交互式 API 文档 / Interactive API docs

---

## API 接口 / API Endpoints

### 公开接口 / Public

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | 存活探针 / Liveness probe |
| `GET` | `/ready` | 就绪探针 / Readiness probe (checks PG + Redis) |
| `POST` | `/api/v1/agents/register` | 注册 Agent / Register an Agent |
| `POST` | `/api/v1/auth/token` | 换取 JWT / Exchange API Key for JWT |

### 需要认证 / Requires JWT

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/agents/discover` | 发现 Agent / Discover Agents |
| `POST` | `/api/v1/interact/query` | 跨 Agent 查询 / Cross-agent query |
| `POST` | `/api/v1/topics/publish` | 发布广播 / Publish broadcast |
| `GET` | `/api/v1/topics/subscribe` | SSE 订阅 / Subscribe via SSE |
| `GET` | `/api/v1/audit/logs` | 审计日志 / Query audit logs |

---

## 使用示例 / Usage Example

### 1. 注册 Agent / Register

```bash
curl -X POST http://127.0.0.1:8000/api/v1/agents/register \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "weather-bot",
    "display_name": "Weather Bot",
    "callback_url": "http://localhost:9001/api",
    "domain": "acme-corp.com",
    "data_contract": {
      "version": "0.2.0",
      "schemas": [
        {"schema_id": "weather_alert", "name": "Weather Alert", "sensitivity_level": "public"}
      ],
      "policies": [
        {"policy_id": "allow-all", "effect": "allow", "schema_ids": ["weather_alert"], "principal": {"public": true}}
      ],
      "transforms": []
    }
  }'
```

响应会返回 `api_key` 和 `hub_shared_secret`，**只显示一次**。

Response returns `api_key` and `hub_shared_secret` — **shown only once**.

### 2. 获取 Token / Get Token

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "weather-bot", "api_key": "YOUR_API_KEY"}'
```

### 3. 查询数据 / Query Data

```bash
curl -X POST http://127.0.0.1:8000/api/v1/interact/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"target_agent": "weather-bot", "schema_id": "weather_alert"}'
```

---

## 项目结构 / Project Structure

```
a2a-contract-hub/
├── app/
│   ├── main.py                 # 应用入口 / App entrypoint
│   ├── config.py               # 配置管理 / Config (pydantic-settings)
│   ├── database.py             # 异步数据库引擎 / Async DB engine
│   ├── api/
│   │   ├── auth.py             # 认证 / Authentication
│   │   ├── agents.py           # 注册与发现 / Registration & discovery
│   │   ├── query.py            # 查询引擎 / Query engine
│   │   ├── topics.py           # 广播系统 / Broadcast
│   │   └── audit.py            # 审计日志 / Audit logs
│   ├── core/
│   │   ├── security.py         # JWT / API Key / HMAC
│   │   ├── redis_pool.py       # Redis 连接池 / Redis connection pool
│   │   └── interceptor.py      # 策略引擎 / Policy engine
│   ├── models/
│   │   └── schemas.py          # 数据表 / DB models
│   └── services/
│       ├── transform.py        # 脱敏引擎 / De-identification engine
│       └── audit_writer.py     # 异步审计管道 / Async audit pipeline
├── alembic/                    # 数据库迁移 / DB migrations
├── tests/                      # 测试 / Tests
├── .env.example                # 配置模板 / Config template
└── requirements.txt            # 依赖 / Dependencies
```

---

## 数据契约结构 / Data Contract Structure

每个 Agent 的数据契约由三部分组成 / Each Agent's data contract has three parts:

```json
{
  "version": "0.2.0",
  "schemas": [
    {
      "schema_id": "employee_info",
      "name": "Employee Info",
      "fields": [
        {"field_id": "name", "type": "string", "sensitivity": "public"},
        {"field_id": "salary", "type": "number", "sensitivity": "confidential"}
      ]
    }
  ],
  "policies": [
    {
      "policy_id": "allow-internal",
      "effect": "allow",
      "schema_ids": ["employee_info"],
      "principal": {"organizations": ["my-company.com"]},
      "transform_ids": ["mask-salary"]
    }
  ],
  "transforms": [
    {
      "transform_id": "mask-salary",
      "type": "generalize",
      "applies_to_fields": ["salary"],
      "config": {}
    }
  ]
}
```

**策略匹配规则 / Policy Matching Rules:**
- `deny` 优先于 `allow` / `deny` takes precedence over `allow`
- 无匹配策略时默认拒绝（Fail-Closed）/ No matching policy = denied

---

## 安全设计 / Security Design

| 安全点 Security Aspect | 实现 Implementation |
|----------------------|---------------------|
| 认证 / Auth | Agent→Hub: JWT + API Key; Hub→Agent: HMAC-SHA256 |
| 密码存储 / Password Storage | bcrypt (cost factor 12) |
| Token 查找 / Token Lookup | O(1) 索引查询，非遍历 / Indexed lookup, not O(N) scan |
| 错误信息 / Error Messages | 统一返回，防枚举 / Uniform errors to prevent enumeration |
| 上游超时 / Upstream Timeout | connect=5s, read=10s, write=5s, pool=5s |
| 响应限制 / Payload Guard | 流式读取，超 5MB 截断 / Streaming read, truncate at 5MB |
| Redis / Redis | 全局连接池，lifecycle 管理 / Global pool with lifecycle management |
| 审计 / Audit | 异步写入，不阻塞业务 / Async write, non-blocking |

---

## License

MIT

---

*Built with FastAPI, aligned with Agent Data Contract Spec Core v0.2.0.*
