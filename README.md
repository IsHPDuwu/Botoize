# Botoize
QQ 官方机器人中转平台

Provider 也支持 OneBot 11 / 12 上游：HTTP / 正向 WS 调用、WS 事件接收和鉴权 HTTP 上报。配置步骤、worker 命令及版本边界见 [OneBot 上游接入](backend/ONEBOT_UPSTREAM.md)。

Channel 支持官机与其他 Provider 的 OneBot 从机协作，逐条接收回退、群匹配、真实 ID 持久升级和 Markdown 优先发送。配置与维护命令见 [主从协作](backend/COMPANIONS.md)。

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
下游原生事件流及 OneBot 11/12 HTTP、通用 WS、反向 WS、HTTP 上报，12 使用字符串 ID。具体能力和 QQ 平台边界见 [OneBot 支持矩阵](backend/ONEBOT_SUPPORT.md)。

需要 WebSocket 时，后端使用 `uv run --locked uvicorn config.asgi:application --host 127.0.0.1 --port 8000 --lifespan off --no-proxy-headers --ws-max-size 12582912`，
而不是 Django runserver。HTTP 推送必须由调度器重复运行
`uv run --locked python manage.py deliver_outbox --limit 20`；仅启动 Web 服务不会处理回调队列。

具体协议与限制见 [代理支持范围](backend/PROXY_SUPPORT.md)、
[Webhook 与事件](backend/WEBHOOK_STATUS.md) 和 [部署与验收](backend/DEPLOYMENT.md)。
已验证真实 QQ 群八类消息及双版 OneBot HTTP/WS 身份、撤权和批准群信息查询；公网反向接收端和真实新入站事件仍待联调，PostgreSQL 暂缓，不宣称生产就绪或全量个人号能力。

验证：在 backend 先运行 `uv run --locked python manage.py migrate`，再运行 `uv run --locked pytest`。
