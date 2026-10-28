# 部署与验收

## 服务与进程

1. 在 backend 使用 `uv sync --locked --no-dev` 安装锁定依赖。生产密钥与 PostgreSQL 环境要求见 API.md。不要使用测试设置或开发 SQLite。
2. 运行 `uv run --locked python manage.py migrate`，再运行 `uv run --locked python manage.py check --deploy`。安全警告必须结合实际 TLS/反代配置解决，不能直接忽略。
3. 使用 `uv run --locked uvicorn config.asgi:application --host 127.0.0.1 --port 8000 --lifespan off --no-proxy-headers --ws-max-size 12582912`。12 MiB 帧用于 OneBot 文件 Base64；原生 QQ HTTP 仍限制 1 MiB，旧 OneBot API WS 仍限制 64 KiB。
4. 前端在 frontend 运行 `pnpm install --frozen-lockfile`、`pnpm build`。反向代理提供 dist 静态文件，并将 `/api/`、`/qq/`、`/onebot/`、`/relay/`、`/webhooks/`、`/health/` 转发到后端；允许 `/relay/v1/ws/` 和 `/onebot/` 的 Upgrade，OneBot JSON 正文上限至少 12 MiB。其他静态路由回落 index.html。
5. 生产必须配置 HTTPS、正确的 ALLOWED_HOSTS、CSRF_TRUSTED_ORIGINS 与安全 Cookie。不要盲目信任客户端转发头；入口仍须限制请求正文大小和连接数。应用内数据库限流按 UTC/数据库时间使用 60 秒固定窗口：登录每来源地址 10 次、管理 API 每用户 120 次、Bearer 每 Key 120 次/每 Admin 300 次/每 Bot 600 次；重复调度 `manage.py cleanup_throttles` 清理过期计数。确认可信反代正确改写 REMOTE_ADDR，否则登录按直连源地址共享额度。
6. 使用服务管理器保持 ASGI 服务运行；为 HTTP 回调单独建立重复调度，执行 `uv run --locked python manage.py deliver_outbox --limit 20`。可多工作进程竞争，但需自行控制全局并发及官方配额。每次命令是有限批次，不会常驻。

调度频率决定重试延迟与吞吐；每分钟一次、每批 20 条的容量至多约 20 条/分钟，网络超时还会降低容量。不要把两秒退避理解成两秒内必定重试。定时任务应使用 backend 为工作目录和该项目环境。

### 控制台连接管理进程

由服务管理器常驻 `uv run --locked python manage.py run_connections`。启动时及运行期间持续监督所有已启用的 QQ WebSocket / OneBot 11 / OneBot 12 Channel，自动启动缺失的 `run_gateway` / `run_onebot_upstream` worker；不依赖是否存在未消费的手动重连请求。已有有效租约时不抢占，进程意外退出或服务器重启后等待旧租约到期，再按 2–60 秒退避恢复。自有子进程超过 75 秒仍无有效租约时终止，10 秒内不退出则强制结束；配置变化或停用会终止旧子进程。数据库暂时不可用时管理循环重试。外部 worker 的活租约仍受保护，跨监督进程竞争由 worker 租约隔离。

官机默认 intents 为 33554432，可用 `--intents` 指定，已有会话优先保留原 intents；验收可加 `--allowed-group OPENID` 限定其启动的官机 worker。默认启动所有启用的 socket Channel，部署前确认 Channel 配置。官机在 Hello 后 20 秒未完成 READY / RESUMED 时重连，不能仅靠心跳 ACK 永久维持未认证连接。

页面每 5 秒读取 `GET /api/v1/channels/status/` 的持久状态；有效租约与已建立事件连接分别判断，过期或配置已变更的连接快照不会显示为已连接。它不是 Bot 实时在线保证。`POST /api/v1/channels/CHANNEL_ID/reconnect/` 只接受 Owner Session + CSRF 和空 JSON，返回 202 表示排队；连续重复请求合并，worker 下一次检查后断开再连接。关停管理进程会终止它启动的子进程，外部服务管理器启动的 worker 独立运行。

Webhook 无常驻连接，其按钮仅排队执行上游 HTTP 身份检查，不声称 WebSocket 在线。首次部署可点击 Channel 的“获取 / 刷新 ID”，直接获取并保存下游 Self ID；该操作不依赖连接管理进程。迁移到新服务器须保留数据库，才能保留 OB11 数字映射。

主从协作另需常驻 `uv run --locked python manage.py run_companions`，维护主机逐条接收回退与群/真实 ID 匹配。详见 [主从协作](COMPANIONS.md)。

`run_connections` 每分钟也执行一次本地历史 ID 修复：刷新双方旧消息指纹，并按数据库游标分批重试已存在的未配对记录；不访问上游或重放历史事件。升级先执行 migrate（包含 `0042`），随后由部署工具重建/重启 connections 以加载代码。该兜底不替代 `run_companions` 的上游群信息刷新和接收回退维护。

### 官方 Gateway worker

由服务管理器为每个 Bot 单独运行 `uv run --locked python manage.py run_gateway --bot BOT_ID --intents BITMASK`，intents 必须按 QQ 已授权事件位显式配置，不默认申请全部权限。
进程通过官方 `/gateway/bot` 发现地址，只接受 api.bot.qq.com / api.sgroup.qq.com 的 WSS websocket 路径。可用 `QQ_GATEWAY_HOST=api.bot.qq.com` 指定当前文档官方域名；覆盖值同样禁止任意主机。使用官方 Identify、Resume、心跳和 ACK，不提供下游 Gateway 登录能力。
当前仅运行完整的单分片 `[0,1]`，不声称支持多分片编排；若官方要求扩分片，进程在相应关闭码终止，不能靠多开同一命令解决。
数据库为每个 Bot 保持 60 秒独占租约，每约 5 秒重新检查 Bot 和凭据；禁用或凭据变化后旧进程退出，由服务管理器重启以获取新配置。
事件与 Outbox 落库成功后才在同一事务更新 sequence；异常时保留旧断点。业务事件必须有官方 event ID，不伪造 ID 或静默跳过失败事件。
断线退避重连，丢 ACK 会重连，Invalid Session 清除断点；致命 intents、分片、封禁错误须人工处理。日志不输出令牌或原始载荷。
Gateway 与 Webhook 同时启用时仅按官方 event ID 去重；不得假设不同来源必有相同 ID，建议单一上游接入方式。
协议来源：QQ 官方 `dev-prepare/interface-framework/event-emit.html` 与 `openapi/wss/shard_url_get.html`，2026-10-25 核对。真实 Bot 已通过 READY、心跳 ACK、worker 中断后 RESUMED；生产容量与 PostgreSQL 恢复验收仍未完成。`--allowed-group OPENID` 可严格限制验收入库范围，`--status` 仅打印脱敏连接状态。

## HTTP 事件回调

### OneBot 上游独立进程

Provider 的 OneBot 11/12 Channel 使用 `uv run --locked python manage.py run_onebot_upstream --bot BOT_ID` 接收正向 WS 事件；也可配置独立 `event_secret` 后使用 `/webhooks/onebot/BOT_ID/` HTTP 上报。与下游 `run_onebot` worker、官方 `run_gateway` 各自独立。生产内网 / 明文 endpoint 需要显式 `ONEBOT_UPSTREAM_ALLOW_PRIVATE=1`；默认仅允许公网 TLS。配置、标准鉴权和断线边界见 [OneBot 上游](ONEBOT_UPSTREAM.md)。

### 下游订阅投递

- 在页面「订阅端点」选择具有 events:read 的 Bot，输入 HTTPS 地址与回调密钥；非登录操作不再次要求密码。也可用 `subscription set GRANT_ID URL` 控制台命令配置。
- URL 配置允许域名，但真正发送时解析所有地址，只允许公共可路由 IP；混合公私地址也拒绝。连接固定到验证过的 IP，TLS 按原域名校验证书，不跟随重定向，也不读取环境代理。
- 回调正文为紧凑 UTF-8 JSON，`X-QQ-Proxy-Delivery-ID` 是稳定 Outbox ID；`X-QQ-Proxy-Timestamp` 为 Unix 秒，`X-QQ-Proxy-Signature` 格式为 `v1=<hex>`，计算规则为 `HMAC-SHA256(secret, timestamp + "." + delivery_id + "." + exact_body_bytes)`。密钥加密保存且不回传；通过 API 的 callback_secret 配置接收端已知的 32–256 字符密钥。普通保存保留旧密钥，只有显式传新密钥才轮换；首次省略则随机生成，但接收端无法取得该随机值，实际验签应显式配置。仅在持久化去重与可靠接受后返回 2xx。此签名为平台协议，不是 OneBot HTTP POST 签名。
- 非 2xx、TLS/DNS/网络错误进入退避。默认最多领取五次；连续崩溃也计入预算。每次尝试有持久历史（HTTP 状态、固定错误分类、时间），`POST /api/v1/deliveries/{id}/replay/` 可让 Owner 或当前授权 Admin 重放 delivered/failed 任务；每次会创建新的 attempt generation、重置当前预算并写审计，可能重复发送，下游必须幂等去重。
- 同一授权版本下创建或更改订阅会影响尚未完成的历史快照，不仅限于新事件。授权版本变化后旧快照不复活，订阅须重新保存；禁用后不再新领取，但无法撤回已经发出的网络请求。
- 队列采用至少一次语义，不能承诺恰好一次。HTTP 拉取和 WS 游标独立于推送状态，不能互相当作业务确认。

## 升级、备份与开发验收

- 当前迁移至 0038：0022–0023 为多回调和名称快照；0024–0028 为 OneBot 消息上下文、Key 文件/分片、轮询游标、反向目标租约和频道归属；0029–0031 为 OneBot 上游接入；0032–0036 为主从协作、群/真实 ID 匹配与接入身份；0037–0038 为实际连接快照和绑定配置版本的持久重连请求。升级仍需先备份数据库和加密密钥，migrate 完成后重启 API、连接管理、主从维护、Gateway、OneBot 与投递 worker，防止旧进程继续使用旧模型。无待迁移时可重复执行。

- 升级前备份数据库与独立保存的 BOT_ENCRYPTION_KEY；先在备份副本演练 migrate。0019 保留旧 Bot ID 和授权，将旧共享 Channel 拆为一 Bot 一 Channel；0020 修复旧创建流程的默认 Channel 隔离；0021 添加 API 审计消息类型和重放标记，历史行保留且重放状态未知。
- 新 Key 按产品要求在数据库明文保存原 token，只有摘要的历史 token 无法恢复。限制数据库、备份与日志访问；备份介质应加密，撤销泄露凭据。不要将 .env、config.txt、SECRET.txt 提交或放入前端资源。
- 官方 HTTP 和 Gateway 默认使用标准 `HTTPS_PROXY=http://127.0.0.1:7890`、`NO_PROXY=127.0.0.1,localhost`。backend/.env 自动加载，已导出的环境变量优先；旧 QQ_HTTP_PROXY 非空为兼容覆盖。自定义上游和回调不读代理，保持公网校验。开发服务使用 --reload；生产不要使用。
- 受限实测：`uv run --locked python manage.py verify_live_qq --listen-seconds 25`；只有明确需要发送时追加 `--send`，最多向批准目标发送一条文本，不进行其他群探测或管理操作。凭据从 config.txt 及其明确引用的 SECRET.txt 读取，输出仅脱敏状态，结束清理临时资源。
- PostgreSQL 并发、跨进程租约和故障恢复验收按当前用户指示暂缓；SQLite 测试不替代这些验收，不宣称生产就绪。

## 本次验证证据

- 测试数据库覆盖官方 Webhook 验签、去重、授权隔离、租约回收、尝试预算、HTTP 回调、订阅管理、OneBot 11/12 动作/文件/事件以及正反向 WS 握手/流/撤权。
- 已经通过运行中的 localhost:8000 真正 HTTP 验证 QQ 身份、批准群文本发送、幂等重放、同 token 复制/编辑、限权与撤销；真实 Gateway READY/ACK/RESUMED 也通过。公网回调仍为模拟测试。
- 前端进行测试、类型检查、Fluent-only 检查与生产构建；构建仍提示主 bundle 超过 500 kB。
- 浏览器在用户已有登录会话中检查真实 Provider/Channel/批准群会话、无授权空态及窄屏弹窗，未使用或重置用户密码；不宣称全路径人工验收完成。

## 不可省略的外部验收

真实 QQ Bot 已从本地配置接入。公网 HTTPS 回调仍需操作人提供接收端与 QQ 平台配置权限。

1. 在 QQ 平台登记 `/webhooks/qq/BOT_ID/`，确认官方地址挑战和真实签名事件通过。
2. 实际发送一条私聊/群消息，检查官方 OpenID、回复 msg_id/msg_seq、审核语义与错误码。
3. 配置可控公网订阅，验证真实 2xx、非 2xx、超时、重复事件去重与重试耗尽。
4. 用服务端 WS 客户端传 Bearer Key 连接，再撤销 Key/授权，确认连接被关闭；从已保存 cursor 恢复。
5. 在 PostgreSQL 多进程部署下执行竞争、进程中断、备份恢复和容量测试。

没有以上证据不能宣布生产就绪。

## 尚未实现与待外部验收（不同阶段）

尚未实现：Gateway 多分片编排、官方异步审核全生命周期跟踪及 QQ 未开放的个人号能力。OneBot 11/12 的 HTTP、通用/分离 WS、反向 WS、HTTP 上报已实现；12 使用原始字符串 ID，11 持久虚拟数字不是真实 QQ 号。覆盖与明确不支持项见 ONEBOT_SUPPORT.md；反向公网接收端仍待外部验收。管理/relay OpenAPI 在 `/api/v1/openapi.json` 提供资源/响应模型。单聊/群聊撤回、频道及频道私信 JSON 消息与撤回、频道 multipart、files、upload_prepare、upload_part_finish 已实现；COS 分片仍由客户端按官方预签名 URL 直传，范围见 PROXY_SUPPORT.md。

已实现并有自动化测试：邀请、Admin 生命周期、Bot/凭据生命周期、Key 轮换、数据库共享限流、可配置平台/Bot/用户/Key 共享请求配额、可选发送幂等、回调签名、DeliveryAttempt、人工 replay 和数据面调用审计。配额管理契约见 API.md；幂等和过期响应清理见 PROXY_SUPPORT.md。

待外部验收：真实官方账号、公网回调、PostgreSQL 多进程竞争及生产容量。自动化测试不能替代这些证据，不能据此声明生产就绪或全量目标完成。
