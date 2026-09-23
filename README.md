# A2A Contract Hub — 数据契约执行层

当前为本地 alpha 开发版本。使用 OPA 决策、固定 Presidio 英文邮箱识别、严格输入/输出校验与 PostgreSQL 交付记录，为同一份合成会议生成内部和外部两个视图。任务与逐项验收状态见 [STATUS](docs/implementation/STATUS.md) 和 [TASKS](docs/implementation/TASKS.json)；未完成门槛不能视为发布通过。

## 第一次体验，不熟悉编程？

从 [普通用户体验指南](docs/verification/trial/BEGINNER.md) 开始，或把 [AI 安装指令](docs/verification/trial/AI_INSTALL.md) 交给能操作本机的 AI 助手。无需写代码或购买 API；目前结果显示在终端，尚无图形操作界面。开发者可继续阅读下方说明。

## 本地启动

需要 Docker Compose、镜像仓库及 PyPI 下载连接。镜像与 Python 依赖分别固定在 Compose、Dockerfile 和两个 `requirements-*.lock`。首次下载/构建和稳定运行是不同成本，没有五分钟部署承诺。Presidio 使用 EmailRecognizer，不下载 NLP 模型。

在仓库根目录运行：

```sh
docker compose up -d --build --wait
docker compose --profile demo run --rm demo
```

应用绑定本机 `127.0.0.1:58000`。`/health` 检查进程；`/ready` 检查迁移、OPA 固定策略、实际邮箱处理及上游配置。示例运行公共管理/发布/发现/查询接口，精确比较两份结果并输出本地任务。重跑示例使用保存的凭据与不可变契约；不会调用真实任务平台。

只使用专用 `a2a-alpha-local` 数据卷和显式测试网络。首次启动生成并持久保存密钥，日志不打印它们。数据库密码是明确的本地合成环境配置，不用于生产。无需复制现有 `.env`。停止使用 `docker compose stop`，重启使用 `docker compose up -d --wait`；不要为重跑示例删除已有卷。示例不覆盖撤权保护：只有运行 demo 的管理员操作会显式重建示例授权。

## 交付与接口

- `POST /api/v1/auth/token`：管理员预置身份的 API key 换取短期 JWT。当前数据库身份、角色、scope 和授权决定访问权。
- `POST /api/v2/contracts`，`/{id}/{version}/validate`、`/check`、`/activate`、`/default`、`/retire`：保存、验证、检查、显式激活、切换默认、退役。
- `GET /api/v2/contracts/discover`：当前主体可申请的版本与视图；发现不预留权限。
- `POST /api/v2/query`：固定 `target_agent/contract_id/contract_version/view_id/query.meeting_id`。
- `GET /api/v2/receipts/{request_id}`：仅有权主体可查询；`ready_to_send` 表示允许尝试交付，不是接收确认。
- `/a2a/.well-known/agent-card.json`：官方 SDK 0.3.0 的同步 JSON-RPC Message/DataPart 子集，必需扩展为 `urn:uuid:061c06b4-2078-4a1a-95e0-fbd397e27d78`。无流式、推送、取消或官方扩展认证。

轻量调用封装见 [sdk/client.py](sdk/client.py)，完整示例见 [demo.py](examples/meeting_views/demo.py)。契约、输入和预期结果见 [合成样例](docs/implementation/examples/README.md)。新增同类提供方需由管理员批准地址、公钥信任和资源授权，不修改交付核心。

内部视图保留负责人邮箱以分配任务；外部视图移除已知姓名/邮箱字段，将指定文本中的普通英文邮箱替换为 `[EMAIL]`，形成待分配任务。探索样本出现过混淆邮箱漏检；不保证清除自由文本中的人名、中文、电话或商业机密。

## 校验、预览与变更

在安装 `requirements-hub.lock` 的 Python 3.12 环境中：

```sh
python -m app.contracts docs/implementation/examples/contract.meeting.json
python scripts/contract_tools.py compare old.json new.json
python scripts/contract_tools.py preview docs/implementation/examples/contract.meeting.json docs/implementation/examples/raw.meeting.json --presidio-url http://127.0.0.1:58182
python scripts/contract_tools.py migrate legacy.json explicit-new-template.json
```

预览地址应是你显式启动的本地 Presidio 服务；默认完整 Compose 不把检测端口暴露到宿主机。可在容器内运行预览并使用 `http://presidio:8000`。迁移只生成草案，要求明确的新结构模板；未知条件、缺失变换、通配符、多策略歧义会阻止迁移。

`/check` 注册合成输入、预期输出、字段需求和预期任务效果，服务器调用真实处理入口验证。报告区分结构、访问范围和处理行为；仅对已登记样例负责。`review_required` 禁止激活；`breaking` 要求更高主版本、成功消费样例和迁移标识。安全/行为变化及破坏性迁移还需确认 `/check` 返回的具体 `report_digest`；没有通用 force。默认切换应先 `/check?default=true`，所有已登记默认消费者须完成迁移。旧版请求仍受当前撤权约束。

错误使用稳定 code 和安全关联标识，如 `ACCESS_DENIED`、`CONTRACT_INVALID`、`UPSTREAM_SCHEMA_MISMATCH`、`UPSTREAM_RESOURCE_MISMATCH`、`PROCESSING_UNAVAILABLE`、`OUTPUT_CONTRACT_VIOLATION`、`AUDIT_PERSISTENCE_UNAVAILABLE`。具体规则见 [CONTRACT_SPEC](docs/implementation/CONTRACT_SPEC.md)。PG 写入失败不返回数据；Redis 停机不丢失已提交 outbox，但令牌签发的限流依赖 Redis。

## 验证及限制

快速测试：`python -m pytest -q`（测试依赖见 `requirements-test.txt`）。真实集成使用独立 `compose.test.yaml`，详见 [验证说明](docs/verification/RESUME.md)。快速测试采用 SQLite/FakeRedis，不能替代真实 PG、OPA、Presidio 和独立 A2A 进程。

旧公开注册、legacy 查询和任意内容订阅已关闭；旧引擎仅用于离线诊断。公开通知只允许管理员批准的元数据。旧功能测试源文件保存在 `docs/verification/legacy-test-sources/`，替换原因和当前覆盖映射见验证说明。

长期稳定性、真实新人接入和生产部署未验证。当前测试结果不等同于安全审计、合规认证或零泄露保证。

许可证沿用仓库原先声明的 MIT，见 [LICENSE](LICENSE)。贡献与安全报告边界见 [CONTRIBUTING](CONTRIBUTING.md)、[SECURITY](SECURITY.md)。

### 容器下载受限时的安装路径

若 Docker 内的 PyPI 连接反复中断，但本机能正常下载，先用现有 Python 环境安装 `packaging`，再预取相同锁定版本的 Linux CPython 3.12 wheels（正常校验 TLS）：

```sh
python scripts/prepare_wheels.py
docker compose -f compose.yaml -f compose.offline.yaml up -d --build --wait
docker compose -f compose.yaml -f compose.offline.yaml --profile demo run --rm demo
```

脚本默认按本机 CPU 选择 aarch64 或 x86_64；交叉构建请显式传 `--arch`。下载结果与 SHA-256 清单位于忽略提交的 `.local-wheelhouse/`，不是已有虚拟环境复制。干净容器中仍执行完整依赖解析与 `pip check`。在线首次下载、离线安装和实际交付的证据分别记录，不能互相替代。

### 失败记录诊断（2026-09-22）

有 audit scope 的记录所属主体或管理员可通过 `/api/v2/receipts/{request_id}` 查询安全诊断：请求引用、实际失败阶段、已核实快照和已完成处理/校验。未执行阶段为 unknown，未知修订为 null；旧记录 diagnostics 为 null。policy_decision 仅表示初始 OPA 决定，不能覆盖提交时撤权。普通错误响应不含原文或内部异常；diagnostic_recorded=false 表示未成功持久化。升级须运行新增迁移 `20260922_diagnostics`，历史记录保留。当前验证及剩余门槛见 [本轮报告](docs/verification/20260922-DIAGNOSTICS.md)。


### 最新验收与独立试用

最新本地工程结果、明确未验证项及 24 项验收映射见 [四项报告](docs/verification/20260922-FOUR-STEPS.md) 与 [AC 映射](docs/verification/AC-MAP.json)。本地及 [托管 CI](https://github.com/Void107/A2A/actions/runs/35815716142) 已通过；真人试用、长期稳定性和生产部署仍未验证。

如果 pip 下载出现 TLS/索引或摘要问题，保持固定版本并使用官方元数据逐包校验路径：

```sh
python scripts/prepare_wheels.py --downloader curl
```

该命令需要 Python 环境中的 packaging 和系统 curl；默认生成 .local-wheelhouse，仍使用正常 TLS 并核对官方 SHA256。不接受摘要不符文件。之后按上面的 compose.offline.yaml 步骤安装。

完整独立验收：`python scripts/verify_clean_install.py --downloader curl`；已有核实 wheels 时可用 `--reuse-wheels`，但不得把缓存读取时间当作下载耗时。验收使用独立项目名、127.0.0.1:58001 和 172.30.87.0/24；这些测试资源应无冲突。脚本保留专属数据卷和证据，只清理本次容器及网络，不动现有演示栈。

真人试用入口：[任务卡](docs/verification/trial/START_HERE.md) 与 [空白观察表](docs/verification/trial/observation.template.json)。尚无真人结果。私密安全报告渠道和负责人已落实，见 [SECURITY](SECURITY.md)。
