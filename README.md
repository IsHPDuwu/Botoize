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
当前后端仅实现授权底座，前端接入与代理能力边界以各目录文档为准。

验证：在 backend 运行 `uv run --locked pytest`。
