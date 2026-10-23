# 授权底座（未实现官方代理）

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
Admin 账号暂由可信控制台通过 ORM 创建，默认 role=Admin；邀请流程未实现。
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
- GET `/api/v1/grants/`：Owner 全局分配。
- POST `/api/v1/grants/`：Owner，user,bot,scopes,password，可选 is_active。
  更新同一分配递增 revision，使原 Key 永久失效，即使重新授权也不复活。
- GET `/api/v1/keys/`：仅自己的 Key 元数据。
- POST `/api/v1/keys/`：bot,name,scopes,password，可选 expires_at（ISO 8601）。
  必须有显式有效 BotGrant，包括 Owner；201 响应的 token 仅此一次展示。
- POST `/api/v1/keys/{id}/revoke/`：仅自己，password。
- POST `/api/v1/owner/keys/{id}/revoke/`：Owner 可撤销他人 Key，password。

写接口严格拒绝未登记字段。没有修改 Key 的接口，因此不能换绑 Bot/user。
管理 API 未认证为 403（DRF Session 语义），不可见对象为 404。

数据端仅接受 Authorization: Bearer TOKEN，不接受管理 Session 替代：

- GET `/relay/v1/capabilities/`：唯一 bot_id、当前交集 scopes，operations 为空，
  proxy_enabled/websocket_enabled 均为 false。可选查询 bot_id 必须一致。
- `/qq/*`、`/onebot/*`：有效鉴权后返回 501、code=proxy_not_available、source=platform。
  请求 JSON 中 bot_id 如存在也必须一致。没有实际发往官方的请求。

登记 scope：events:read、messages:send、media:upload、query:read。
scope 仅为授权底座登记，不表示相应官方操作已经实现。统一 services.authorize 在每次
调用检查账号/Bot/Key 有效性、期限、Grant revision 与 scope 交集；未来操作必须调用它
并指定 scope 和 bot_id。当前无任何可执行代理操作，故不虚构端点/scope 映射。

## 验证与边界

在 backend 目录运行 `uv run --locked pytest`，并运行
`uv run --locked python manage.py check --settings=config.test_settings` 和
`uv run --locked python manage.py makemigrations --check --dry-run --settings=config.test_settings`。
pytest.ini 指向独立 test_settings（测试专用 SQLite、
快速密码哈希和固定测试密钥，严禁部署）。初始迁移已提交。

未实现：邀请、配额、登录防爆破、统一 request_id/错误包装、分页/OpenAPI、
官方 Token/Webhook/HTTP 代理、WS、OneBot、事件/任务/跨进程失效通知、密钥轮换。
没有长连接或待执行队列，当前撤销通过每次 HTTP 查询数据库生效。
审计覆盖 Owner 命令及 Bot/Grant/Key 写操作，不是完整审计平台。