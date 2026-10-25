# QQ-Official-Bot-Proxy
QQ 官方机器人中转平台

## 本地启动（Windows PowerShell）

后端使用 Python 3.13 + uv，前端使用 pnpm。若已激活仓库根 `.venv`，先运行
`deactivate`；uv 会管理独立的 `backend/.venv`，不需要手动激活，不使用 `--active`。

1. 从仓库根运行 `cd backend`，然后 `uv sync --locked`。
2. 首次运行 `uv run --locked python scripts/init_dev.py`，生成本地开发 `.env`。
	密钥仅写文件、不输出；已有 `.env` 不会被覆盖，请在本机编辑器检查。
3. 运行 `uv run --locked python manage.py migrate` 和
	`uv run --locked python manage.py check`。
4. 运行 `uv run --locked python manage.py owner init USERNAME`，按隐藏提示设置密码。
5. 运行 `uv run --locked python manage.py runserver`。

后端自动读取 `backend/.env`，环境变量优先。开发配置显式启用 DEBUG 和 SQLite，
不能用于生产；不要提交或分享 `.env`，不要更换已有数据库的加密密钥。
生产默认仍要求独立密钥、PostgreSQL 和 HTTPS；详见 [后端配置与 API](backend/API.md)。

网络需要代理时，在当前 PowerShell 设置
`$env:HTTP_PROXY='http://127.0.0.1:7890'` 和
`$env:HTTPS_PROXY='http://127.0.0.1:7890'`。Python 依赖使用官方 PyPI，不用 npm 镜像。

前端在独立终端进入 `frontend`，依次运行 `pnpm install`、`pnpm dev`。
当前已接入真实登录、Bot/授权/API Key 管理、事件查询、HTTP 订阅和投递状态页。
数据面支持官方用户查询、私聊/群消息代理、验签 Webhook、事件拉取、HTTPS 回调推送、
下游原生 WebSocket 事件流及受限 OneBot 11 HTTP 动作。

需要 WebSocket 时，后端使用 `uv run --locked uvicorn config.asgi:application --host 127.0.0.1 --port 8000 --lifespan off --no-proxy-headers --ws-max-size 1048576`，
而不是 Django runserver。HTTP 推送必须由调度器重复运行
`uv run --locked python manage.py deliver_outbox --limit 20`；仅启动 Web 服务不会处理回调队列。

具体协议与限制见 [代理支持范围](backend/PROXY_SUPPORT.md)、
[Webhook 与事件](backend/WEBHOOK_STATUS.md) 和 [部署与验收](backend/DEPLOYMENT.md)。
目前没有真实 QQ 账号及公网回调联调证据，不宣称生产就绪或全量官方 API/OneBot 兼容。

验证：在 backend 运行 `uv run --locked pytest`。
