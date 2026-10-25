# 管理与授权 API

本文描述授权接口；数据面以 `PROXY_SUPPORT.md`、`WEBHOOK_STATUS.md` 为准，
部署入口见 `DEPLOYMENT.md`。已实现的有限代理能力不等于全量官方 API 兼容。

## 启动与配置

Python 3.13 已验证。后端统一使用 uv：从 backend 工作目录运行
`uv sync --locked`，依赖由 pyproject.toml 声明、uv.lock 锁定，环境独立位于
`backend/.venv`，不要使用系统包或其他项目的虚拟环境，也不要使用 `--active`。
开发依赖默认安装；生产安装使用 `uv sync --locked --no-dev`。
新增/更新依赖使用 `uv add` / `uv lock`，同时提交声明与锁文件。
联网如需代理，可在当前终端为 HTTP_PROXY、HTTPS_PROXY 设置
`http://127.0.0.1:7890`；Python 包使用官方 PyPI，不使用 npm 镜像。
首次本地开发先运行 `uv run --locked python scripts/init_dev.py`：独立随机生成
两项密钥并仅写入被 Git 忽略的 `backend/.env`，不显示密钥，不覆盖已有文件。
然后使用 `uv run --locked python manage.py migrate`，再用
`uv run --locked python manage.py owner init USERNAME` 初始化 Owner；密码通过
终端隐藏输入（至少 12 字符），不放命令行参数。启动 ASGI 入口为
`config.asgi:application`，开发可用 `uv run --locked python manage.py runserver`。

配置自动读取固定路径 `backend/.env`，已导出的环境变量优先（包括空值）。
如果初始化提示文件已存在，在本机编辑器检查配置，不要将内容粘贴到日志或聊天。
`.env.example` 是空密钥模板，不能直接复制后启动；初始化脚本是推荐开发入口。
必须设置随机
DJANGO_SECRET_KEY 和 BOT_ENCRYPTION_KEY（cryptography Fernet.generate_key() 的结果）。
两者独立保存，不能使用 config/test_settings.py 的测试密钥。丢失 Fernet 密钥无法解密
已有凭据；当前不提供自动密钥轮换。显式 DJANGO_DEBUG=1 才允许开发 SQLite。
生产默认关闭 DEBUG、强制 PostgreSQL/HTTPS、安全 Cookie/HSTS，不默认信任转发头。
生产不得部署开发 `.env`，也不得运行开发初始化脚本；由部署环境注入独立密钥，
显式设置 `DJANGO_DEBUG=0` 和 `DB_ENGINE=postgres`，以及 DB_NAME、DB_USER、
DB_PASSWORD、DB_HOST、DB_PORT、DB_SSLMODE=require。
缺失密钥仍拒绝启动，不会生成或回退到默认生产密钥。
部署仍须配置 TLS、入口限流、备份和日志策略。

如果提示根 `.venv` 与项目环境不一致，先在当前 PowerShell 运行 `deactivate`，
再切换到 backend。若没有 deactivate 函数但仍残留 VIRTUAL_ENV，可运行
`Remove-Item Env:VIRTUAL_ENV -ErrorAction SilentlyContinue`；uv 不需要手动激活环境，
不要用 `--active`，不要删除任一已有虚拟环境。VS Code 解释器应选择
`backend/.venv/Scripts/python.exe`。前端继续独立使用 pnpm。

`owner list` 列出 Owner；`owner grant USERNAME` 提升现有有效用户；
`owner revoke USERNAME` 降为 Admin，事务内拒绝撤销最后有效 Owner。
所有命令在数据库单例行上写锁串行化。SQLite 仅用于开发；PostgreSQL 多进程竞争
未在本次测试中验证。没有网页 Owner 用户管理/停用/删除接口，也不挂载 Django admin。
Owner 可通过 `POST /api/v1/invitations/` 创建一次性、72 小时默认有效的 Admin 邀请，明文 token 仅创建响应展示；公开 `POST /api/v1/invitations/accept/` 接受后固定创建 Admin，token 摘要存储且不能重复使用。邀请列表只供 Owner 查看。
直接 SQL/ORM 修改不受命令保护，属于运维应急边界。

## HTTP 契约

所有路径保留尾斜杠。管理接口采用同源 Session，JSON 请求，所有写请求需 CSRF。
先 GET `/api/v1/auth/csrf/`，再在 `X-CSRFToken` 传返回值并携带 Cookie。
登录后 CSRF 轮换，应使用登录响应的新 csrfToken。无跨域/CORS 放行。

- GET `/health/`：进程存活（不是数据库就绪探针）。
- POST `/api/v1/auth/login/`：username,password。
- GET `/api/v1/auth/me/`；POST `/api/v1/auth/logout/`。
- GET `/api/v1/bots/`：Owner 全部，Admin 当前有效 Grant 的有效 Bot。
- POST `/api/v1/bots/`：Owner，name,app_id,secret,password；secret 仅加密写入，不返回。
- PATCH `/api/v1/bots/{id}/`：Owner，password 及可选 name、app_id、secret、is_active。app_id/secret 轮换会递增 Bot 授权 revision 并撤销该 Bot 的现有 Key；停用/启用也递增 revision，secret 永不返回。
- GET `/api/v1/grants/`：Owner 全局分配。
- POST `/api/v1/grants/`：Owner，user,bot,scopes,password，可选 is_active。
  更新同一分配递增 revision，使原 Key 永久失效，即使重新授权也不复活。
- GET `/api/v1/keys/`：仅自己的 Key 元数据。
- POST `/api/v1/keys/`：bot,name,scopes,password，可选 expires_at（ISO 8601）。
  必须有显式有效 BotGrant，包括 Owner；201 响应的 token 仅此一次展示。
- POST `/api/v1/keys/{id}/revoke/`：仅自己，password。
- POST `/api/v1/keys/{id}/rotate/`：仅自己，password，可选 name、scopes、expires_at；旧 Key 立即撤销，新 token 仅响应展示一次且保持原 Bot 绑定。
- POST `/api/v1/owner/keys/{id}/revoke/`：Owner 可撤销他人 Key，password。
- GET `/api/v1/my-grants/`：自己的当前有效 Bot、scopes 与 revision。
- GET `/api/v1/subscriptions/`：自己的 HTTP 订阅及 is_current，不返回其他用户配置。
- POST `/api/v1/subscriptions/`：bot,is_active,password；启用时必须有 url。
  需要自己的显式 Grant，包括 Owner。启用检查 events:read；禁用可清理失效订阅。
- GET `/api/v1/events/?before=CURSOR`：已入库事件，最多 50 条。
- GET `/api/v1/deliveries/?before=CURSOR`：真实投递状态、尝试次数、重试与租约时间，最多 50 条。
  Owner 全局可见，Admin 仅见自身当前版本且具有 events:read 的授权快照。
- GET `/api/v1/deliveries/{id}/attempts/`：该投递的 generation、逐次状态、HTTP status、固定错误分类和时间；按 Owner/Admin 可见性过滤。
- POST `/api/v1/deliveries/{id}/replay/`：password；Owner 或当前仍拥有该 Bot `events:read`、当前 revision、有效订阅的 Admin 可用。返回 202 和重复投递警告，重放会新建 generation。
- GET `/api/v1/api-calls/?before=CURSOR`：数据面调用审计；Owner 全局、Admin 仅自身。记录 request_id、Bot/Key、路由模板、状态和耗时，不记录 body、Authorization 或 secret。

写接口严格拒绝未登记字段。没有修改 Key 的接口，因此不能换绑 Bot/user。
管理 API 未认证为 403（DRF Session 语义），不可见对象为 404。

数据端仅接受 Authorization: Bearer TOKEN，不接受管理 Session 替代：

- GET `/relay/v1/capabilities/`：唯一 bot_id、当前交集 scopes 和可执行的官方 operations；
  websocket_enabled 表示 Key 是否具备原生事件流权限。可选查询 bot_id 必须一致。
- 已登记的 `/qq/*` 和 `/onebot/*` 动作真实调用官方 API，其余官方路径返回 501；
  OneBot 未支持的 POST action 返回 retcode=1404。支持范围见 `PROXY_SUPPORT.md`。

登记 scope：events:read、messages:send、media:upload、query:read。
scope 登记不表示所有同类官方操作均已实现。统一 services.authorize 在每次
调用检查账号/Bot/Key 有效性、期限、Grant revision 与 scope 交集；未来操作必须调用它
并指定 scope 和 bot_id。实际端点/scope 映射见 `PROXY_SUPPORT.md`。

## 验证与边界

在 backend 目录运行 `uv run --locked pytest`，并运行
`uv run --locked python manage.py check --settings=config.test_settings` 和
`uv run --locked python manage.py makemigrations --check --dry-run --settings=config.test_settings`。
pytest.ini 指向独立 test_settings（测试专用 SQLite、
快速密码哈希和固定测试密钥，严禁部署）。初始迁移已提交。

仍未实现：完整 OpenAPI、全量官方 API、官方 Gateway、完整 OneBot、跨进程即时失效通知。
已实现数据库固定窗口限流：登录按来源地址、管理 API 按用户、数据面按 Key/Admin/Bot 共享计数；超限返回平台 429 和 Retry-After。`cleanup_throttles` 用于清理过期计数。
HTTP 查询、队列发送前和 WS 每批次均查询数据库检查授权；不是原子网络撤回，
已经发出的请求不能撤销，WS 撤权存在轮询间隔。
审计覆盖 Owner 命令、Bot/Grant/Key/邀请/订阅/重放写操作及数据面调用、投递尝试，不记录秘密和请求体；仍不是完整不可抵赖审计平台。