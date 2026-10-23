# 前端仪表盘

React + TypeScript + Vite，全部控件使用 Fluent UI v9，图标仅使用官方 Fluent 图标。唯一有效规则：禁止手写控件外观、独立 CSS 和其他 UI 库；允许 Fluent makeStyles/Griffel + tokens 做页面布局和语义容器，不覆盖控件内部。侧栏、指标网格、趋势及记录/接入双栏使用响应式布局，760px 以下侧栏转为顶部导航，480px 以下指标单列。

- 安装：使用 `packageManager` 指定的 pnpm 10.28.2，执行 `pnpm install`；生成锁后使用 `pnpm install --frozen-lockfile`。项目 `.npmrc` 同时配置 npmmirror registry 与 HTTP/HTTPS 代理 `http://127.0.0.1:7890`；保持 TLS 校验，不修改全局配置。依赖使用 `pnpm-lock.yaml`，不使用 npm 锁文件。
- 开发：`pnpm dev`。前端统一使用 pnpm；后端统一使用 uv，由后端工作块处理，此处不修改后端。
- 在 `frontend/` 目录运行命令；开发地址以 Vite 输出为准（默认 `http://localhost:5173`）。`pnpm build` 生成 `dist/`；本地预览使用 `pnpm exec vite preview`，预览服务不是生产服务器。生产需自行部署静态文件并配置同源后端，当前未配置 API 代理。
- 已安装依赖无需重复安装。pnpm 的 `Ignored build scripts: esbuild` 提示不等于构建失败；本次 `vite build` 已实际成功，无需开放安装脚本或重建 esbuild，也未配置全量脚本授权。
- 默认不连接统计 API，也不显示伪真实指标，但保留六张指标卡、趋势空态与记录/接入双栏；管理导航显示对应资源说明和接入准备入口，不进行伪造管理操作。后端地址仅取 `VITE_BACKEND_URL`，未配置时复制禁用，绝不使用浏览器 origin 代替后端地址。
- 开发服务可显式打开 `/?demo=true` 查看完整模拟数据，页面始终显著标记演示；此查询开关在生产构建无效。
- 演示：在本地 `.env.local` 中显式设置 `VITE_DEMO_MODE=true` 并重启开发服务。构建时也必须显式启用，生产默认关闭，不因网络失败回退到模拟数据。
- 演示包含 1h/24h/7d/30d、模拟指标/等宽统计分桶、近期活动、刷新、深浅主题、复制成功/失败反馈。统计时区为 UTC；在线数、重试与死信是当前快照。
- 趋势采用 Fluent DataGrid；Owner/Admin 选择器仅切换合成数据的信息范围与活动文案，不代表认证、提权或真实权限隔离。Owner 演示全局范围，Admin 演示一个已授权 Bot 与自身活动。
- 验证：`pnpm check:no-css`、`pnpm test`、`pnpm typecheck`、`pnpm build`。
- no-css 使用 TypeScript AST 检查业务源代码，允许受审计的 makeStyles 布局及 tokens 语义容器；禁止独立样式、内联 style、控件 className、内部选择器、非布局属性、属性展开、非许可 UI 导入和原生替代控件。依赖、构建产物和测试夹具不作为业务源码检查。
- 演示场景选择器支持正常数据、空数据与加载失败；刷新及重试包含合成加载延迟。失败会清除旧指标，切换窗口会取消旧请求，避免将旧数据标为新窗口。演示故障会持续到手动选择正常数据。
- `pnpm lint` 执行 no-CSS 门禁与 TypeScript 检查；`pnpm test` 分别执行 Node 门禁测试及 Vitest 组件测试。
- 后续真实数据必须在服务端验证角色与授权后接入；目前没有真实统计 API 适配器，不宣称已实现真实统计、服务端角色隔离或完整后端上线。真实模式不发起虚构请求，刷新禁用。
- `VITE_*` 在构建时嵌入产物，不可放置秘密；生产构建前应移除本地演示开关。复制地址依赖安全上下文及剪贴板权限，失败时需手动复制。自动化组件测试使用 jsdom 的尺寸观察替身，不替代真实浏览器的布局、窄屏和键盘验收。