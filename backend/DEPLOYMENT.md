# 部署与验收

## 服务与进程

1. 在 backend 使用 `uv sync --locked --no-dev` 安装锁定依赖。生产密钥与 PostgreSQL 环境要求见 API.md。不要使用测试设置或开发 SQLite。
2. 运行 `uv run --locked python manage.py migrate`，再运行 `uv run --locked python manage.py check --deploy`。安全警告必须结合实际 TLS/反代配置解决，不能直接忽略。
3. 使用 `uv run --locked uvicorn config.asgi:application --host 127.0.0.1 --port 8000 --lifespan off --no-proxy-headers --ws-max-size 1048576`。
4. 前端在 frontend 运行 `pnpm install --frozen-lockfile`、`pnpm build`。反向代理提供 dist 静态文件，并将 `/api/`、`/qq/`、`/onebot/`、`/relay/`、`/webhooks/`、`/health/` 转发到后端；允许 `/relay/v1/ws/` 的 Upgrade。其他静态路由回落 index.html。
5. 生产必须配置 HTTPS、正确的 ALLOWED_HOSTS、CSRF_TRUSTED_ORIGINS 与安全 Cookie。不要盲目信任客户端转发头；入口须限制请求正文大小、连接数和登录尝试频率。该项目尚未内置跨实例登录限流。
6. 使用服务管理器保持 ASGI 服务运行；为 HTTP 回调单独建立重复调度，执行 `uv run --locked python manage.py deliver_outbox --limit 20`。可多工作进程竞争，但需自行控制全局并发及官方配额。每次命令是有限批次，不会常驻。

调度频率决定重试延迟与吞吐；每分钟一次、每批 20 条的容量至多约 20 条/分钟，网络超时还会降低容量。不要把两秒退避理解成两秒内必定重试。定时任务应使用 backend 为工作目录和该项目环境。

## HTTP 事件回调

- 在页面「订阅端点」选择具有 events:read 的 Bot，输入 HTTPS 地址并确认密码；也可用 `subscription set GRANT_ID URL` 控制台命令配置。
- URL 配置允许域名，但真正发送时解析所有地址，只允许公共可路由 IP；混合公私地址也拒绝。连接固定到验证过的 IP，TLS 按原域名校验证书，不跟随重定向，也不读取环境代理。
- 回调正文为官方原始事件 JSON，`X-QQ-Proxy-Delivery-ID` 是稳定 Outbox ID。下游必须持久化去重，并仅在已可靠接受后返回 2xx。回调没有共享密钥签名，接收端如需可信发送方认证，应在生产入口使用受控出口 IP 白名单；当前不提供签名式 Webhook 认证。
- 非 2xx、TLS/DNS/网络错误进入退避。默认最多领取五次；连续崩溃也计入预算。失败记录不会自动无限重放，投递页面可查看 failed；尚无人工重放 API。
- 同一授权版本下创建或更改订阅会影响尚未完成的历史快照，不仅限于新事件。授权版本变化后旧快照不复活，订阅须重新保存；禁用后不再新领取，但无法撤回已经发出的网络请求。
- 队列采用至少一次语义，不能承诺恰好一次。HTTP 拉取和 WS 游标独立于推送状态，不能互相当作业务确认。

## 本次验证证据

- 测试数据库覆盖官方 Webhook 验签、去重、授权隔离、租约回收、尝试预算、HTTP 回调、订阅管理、OneBot 有限动作以及 WS 握手/流/撤权。
- 网络测试采用模拟官方及回调响应；实际 Uvicorn 冒烟验证 `/health/`=200 和未授权 WS 握手=403。
- 前端进行测试、类型检查、Fluent-only 检查与生产构建；构建仍提示主 bundle 超过 500 kB。
- 当前共享浏览器处于未登录状态，未使用或重置用户密码；新增管理页交互通过组件测试验证，不冒充已完成真实登录浏览器验收。

## 不可省略的外部验收

需要操作人在本机管理页面配置真实 QQ Bot Secret（不要发送到聊天），并提供公网 HTTPS 回调与 QQ 平台配置权限。

1. 在 QQ 平台登记 `/webhooks/qq/BOT_ID/`，确认官方地址挑战和真实签名事件通过。
2. 实际发送一条私聊/群消息，检查官方 OpenID、回复 msg_id/msg_seq、审核语义与错误码。
3. 配置可控公网订阅，验证真实 2xx、非 2xx、超时、重复事件去重与重试耗尽。
4. 用服务端 WS 客户端传 Bearer Key 连接，再撤销 Key/授权，确认连接被关闭；从已保存 cursor 恢复。
5. 在 PostgreSQL 多进程部署下执行竞争、进程中断、备份恢复和容量测试。

没有以上证据不能宣布生产就绪。

## 尚未交付的功能

官方 Gateway 上游 WS、媒体上传/撤回/频道 API、完整 OneBot 事件转换与 WS、共享限流/配额、人工重放、完整调用审计、邀请与密钥轮换尚未实现。它们不是靠填写凭据就会自动完成的功能；当前交付是明确受限的可测试子集，不是最初全部目标的完成声明。