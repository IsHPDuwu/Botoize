# Botoize 项目状态

日期：2026-10-27（OneBot 上游接入验收更新）

状态：Provider 已实现 OneBot 11/12 上游接入，并通过本地模拟上游及运行中 8000 服务的真实 HTTP/WS、发送与事件回流验收。此前 QQ 八类群消息、Key 生命周期与 Gateway 心跳/Resume 验收保留。真实第三方 OneBot 实现、公网接收端和用户触发的 QQ 新入站事件尚待联调；PostgreSQL 按用户要求暂缓，不宣称生产就绪。

## 资源契约

```text
Provider 服务提供商
└─ Channel = 一个 Bot
   ├─ interface_type / base_url / AppID / AppSecret
   └─ Models = 会话
      ├─ isDirect=true  + userid
      └─ isDirect=false + groupid
```

- Bot 为内部执行与授权实体，不再作为 Model。数据库唯一约束保证一 Channel 一 Bot。
- Django 迁移至 0031；0019 拆分旧共享 Channel，保留旧 Bot ID、事件与授权；0020 为旧 Bot 创建入口分配独立 Channel；0021 添加审计消息类型与幂等重放标记；0022–0023 支持多回调、精确目标/revision 和日志名称快照；0024–0028 添加 OneBot 消息上下文、Key 独立文件/分片、轮询游标、反向目标租约和频道归属；0029–0031 添加上游事件密钥、文件句柄、fencing 租约、消息来源隔离及字符串 Bot/频道 ID。
- Provider 管理、Channel 凭据和接口切换、会话添加与命名已贯通。已保存会话的身份不可修改，编辑器遗漏发现中的会话不会删除数据。
- “同步”仅回填历史事件；未来由已验证事件发现，不枚举或伪造未知群/用户。
- OneBot 11/12 上游支持 HTTP / 正向通用 WS 调用、独立 WS 事件 worker 和鉴权 HTTP 上报；下游 11/12 HTTP、正向通用/分离 WS、反向通用 WS、HTTP 上报及 12 轮询继续复用现有授权和会话隔离。

## 已完成的本地实现

### 授权与隔离

- Owner 管理资源；Admin 只能在当前有效授权内转授，不能修改 Owner 或自己授权，不能接管其他授权来源。
- 子授权绑定父授权 revision，检查授权链、scope 和会话子集；父授权变更、撤销或停用使下游失效。
- Key 创建/编辑会话字段验证、跨 Bot 拒绝、同 token 编辑、所属用户复制、过期与撤销检查。
- Full access 保存当前显式 scope 数组，不获取未来新增权限。“全选当前会话”不等于“未来所有会话”。
- QQ HTTP、OneBot HTTP/API WS、媒体、撤回执行同一会话检查；无法明确识别归属的路径对受限 Key 拒绝（身份查询除外）。
- 历史事件先过滤后分页；原生/OneBot WS、回调、投递历史与 replay 检查当前授权和会话边界。
- 接口类型或 base_url 变化撤销 Key、提升授权版本并清除 Gateway 会话；自定义上游使用公网 DNS pinning，token 缓存按来源与凭据隔离。

### 管理前端

- 项目品牌改为 Botoize；站点标题、侧栏、登录、favicon 使用用户提供的原始透明 PNG，SHA256 与源文件一致，去除外层白色底。真实上游来源路径、版权和第三方声明保留原名。
- 服务提供商、分组管理移动到平台管理。独立 `/dashboard/admin-dashboard` 系统仪表盘复用上游页面布局，Channels 状态优先展示、下方 7/5 分栏；普通仪表盘和系统设置均不放 Channels 卡片。
- 令牌和授权列表复用 DataList、BadgeOverflowList；权限收纳为徽章及溢出弹层，不再直接铺满所有 scope。
- 日志显示 Bot 名、Key 名、操作用户；Request ID 默认只显示前六位，悬浮显示完整值、点击复制，无“点击复制”文案。新增服务端搜索、用户/路径/Bot/Key/方法/状态/重放/时间筛选，先隔离后筛选再分页。
- 普通仪表盘修正“活跃”误导、补充 API 调用统计；投递汇总不再只算第一页，也不再把无回调的事件流游标算作待投递。worker 有效租约不等于在线。
- Owner 用户管理提供创建、编辑用户名/邮箱、密码重置、启停、一次性邀请、邀请撤销和注册页面。只允许管理 Admin，不开放 Owner 网页角色变更或删除历史。
- 每个授权 Bot 可有任意数量 HTTPS 回调，各自密钥、revision、投递任务和重试；修改/禁用精确取消该目标的旧任务，HTTP/WS 事件流仍只出现一次。公网真实投递仍待外部接收端。
- API 接入说明给出 Koishi 的真实配置字段与直连示例；已核对官方适配器 4.14.0 和 adapter-qq-crack 1.0.31，二者目前均不能只改 endpoint 接入。兼容方案调查见 backend/KOISHI_COMPATIBILITY.md；不将设计建议冒充已实现。

- 使用既有上游组件和 Provider/Channels 工作台，新增/编辑均为 Dialog。
- Channel 下编辑 AppID/AppSecret，Models 展示单聊/群聊会话；令牌与授权使用共享会话选择器。
- 令牌列表、显式 scope、会话、有效期、创建/编辑/复制/撤销及错误保留草稿。
- 无原文的历史 token 明确显示不可再次复制，不伪造恢复或偷偷轮换。
- 清除非登录密码确认；保留 Session、CSRF、角色和归属校验。订阅明确配置 HMAC 密钥。
- 浏览器已检查无授权空态、禁用创建和窄屏弹窗；临时视口已恢复，临时标签与合成 QA 账号已清理，未修改用户已有授权。
- 浏览器尚未完成带真实 QQ 会话数据的全路径联调；组件测试不替代该验收。
- 日志默认展示 API 调用，另有入站事件和投递标签。使用现有上游表格/状态组件；调用列表包含时间、Request ID、脱敏操作路径、Bot/Key、类型、重放、HTTP 状态和耗时，支持游标分页和返回最新。
- 新 HTTP 审计只保存白名单路径模板及固定消息类型，不记录正文、目标 ID、任意路径、查询串或密钥；富媒体发送只标记 media，上传可区分图片/视频/语音/文件，不反推 opaque file_info。旧通用路由无法还原，明确标注历史操作未记录。历史重放字段为 null，不伪造。

### 官方接口与文档

- 49 项官方管理操作集中登记，capabilities、scope 与 OpenAPI 共用事实源。
- 补齐日程读改删、论坛读删、公告、精华、上下麦、单成员/批量禁言、权限列表、角色成员列表等已核实路径。
- 此前新增 20 项和本次 6 项 QQ 群方法/路径均通过当前 QQ 官网逐页核对，脚本 `backend/scripts/check_official_docs.py` 返回 26/26 verified=true；没有读取旧 SDK。
- 未核实/未登记接口拒绝，不宣称覆盖 QQ 全部 API。破坏性管理接口只做本地模拟测试，未对真实 QQ 执行。
- 已同步支持矩阵、scope 审计、部署、升级与秘密保护说明；OpenAPI 补充管理资源与响应模型。

### OneBot 11 / 12

- 12 保留原始 user/group/message 字符串 ID（含前导零）；11 为持久数值映射，新消息 ID 限 int32，用户/群 ID 限 JS 安全整数，不冒充真实 QQ 号。
- 两版文本、图片、语音、视频、文件、引用、撤回和已保存消息上下文；12 标准文件上传/读取/分片及频道查询/发送/改名。严格拒绝不支持的段/组合，不静默吞段、拆成多次发送或将未知结果自动重试。
- 按 2026 年 QQ 官网新接口映射群信息、成员分页、踢人、禁言和入群审批；独立 groups/group-members/group-moderation/group-requests scope。部分能力需要内邀/白名单/群管理员身份，不向真实群执行破坏性测试。
- 事件转换含群/单聊/频道消息、附件、引用、成员进退/好友增减和入群申请。12 未知事件用显式 QQ 扩展，递归过滤认证字段；11 不伪造频道消息。尚无新的真实 QQ 入站验收证据。
- 12 connect/status_update/heartbeat、字符串 echo、标准 retcode；11 CQ 解析及任意 JSON echo。所有传输复用授权链/revision、会话隔离、共享限流配额和脱敏审计；空闲 WS 检查撤权，URL token 在 ASGI 访问日志前脱敏。
- Key 独有文件缓存：24 小时、8 MiB/文件、64 MiB/Key、1000 项；QQ 二进制直传最多 5 MiB。分片支持乱序、重试、覆盖冲突/空洞和 SHA256 校验。不读取服务器路径，公共下载 DNS pinning/TLS/无跳转/无环境代理。
- 12 轮询为每 Key 独立的 1000 条逻辑缓冲，与 WS/回调互不消费。反向 worker 持久每目标游标和 fencing 租约，目的端令牌与本地 API Key 分离；公网 HTTPS/WSS 443，至少一次，不承诺 exactly-once。
- API 接入页补充两版 endpoint/token/ID/请求示例，Vite 转发 HTTP/WS。浏览器实查 1440×900、390×844 均无页面横向溢出，窄屏配置表在自身容器滚动；未改变用户登录与授权。
- 完整动作矩阵、明确未支持项和 worker 命令见 `backend/ONEBOT_SUPPORT.md`。MessagePack 可选项、全量未知好友/群名单、个人号能力不宣称支持；公网反向接收端和第三方框架端到端尚待验收。

## 验证证据

### 本次 OneBot 上游

- Provider Channel 可选择 `onebot_v11` / `onebot_v12`；Bot ID / 可选 Access Token / 独立 HTTP 上报密钥均在现有 Dialog 中配置，不返回秘密。
- 上游 HTTP 11 为 action 路径 + params，12 为 action/params/echo/self 信封；正向 WS 按 echo 关联，不自动重试未知发送结果，QQ 官方接口不会接收 OneBot 凭据。
- `run_onebot_upstream --bot ID` 使用单 Bot fencing 租约接收事件；HTTP `/webhooks/onebot/ID/` 使用 11 HMAC-SHA1 / 12 Bearer，未配置独立密钥时关闭。事件进入统一去重、会话发现、日志、轮询和下游投递。
- 原生 11→11 保留数值 ID（含负数消息 ID）；下游 12 保留字符串，12→11 使用持久映射。消息上下文按配置来源隔离，协议切换不会复用旧上游记录；12 状态保留上游平台和离线状态。
- Scope、授权链/revision、会话、Key 文件隔离继续生效；群/好友列表先过滤再输出；审批 flag 绑定当前授权事件。新好友 scope 不自动加入已有 Key。`/qq/` 对 OneBot Channel 返回 501。
- 本地私网与明文上游由 `ONEBOT_UPSTREAM_ALLOW_PRIVATE` 控制（DEBUG 默认允许、生产默认拒绝），使用 DNS pinning / TLS，不跟随跳转、不读取环境代理；公共媒体下载策略保持独立。
- 运行中 localhost:8000 真实 Session+CSRF 创建了两版临时 Provider，均通过 HTTP 身份/模拟消息发送、下游 WS 身份调用、HTTP 上报→WS 事件回流；每版持久化一条发送和一条入站事件。临时账号、Session、Key、审计及 Provider/Channel/Bot 已清理，真实 QQ 操作为 0。
- 实际第三方 OneBot 实现和公网事件接收端尚待配置联调；不将本地模拟验收当作这些证据。详细字段、命令和动作范围见 `backend/ONEBOT_UPSTREAM.md`。

| 验证 | 结果 |
| --- | --- |
| SQLite migrate | 已应用至 0031，makemigrations --check 无变更 |
| 后端完整回归 | 453 passed（95.39 秒）；之后新增来源切换/状态/权限检查并完成相关定向回归，含上游临时 HTTP/WS 服务、事件鉴权、跨版 ID、文件、撤回、授权与 worker fencing |
| 前端组件/契约测试 | 全量 21 passed；随后管理页定向 7 passed（含新增 OneBot 字符串 Bot ID、可选 Access Token、保留未编辑事件密钥契约） |
| 前端 TypeScript / lint | 通过 |
| 前端 production build | 通过，有大 chunk 体积警告 |
| 本次界面目视验收 | computer-use 本地 native pipe 不可用，重试/重建会话后仍失败；未宣称目视通过，组件/类型/lint/构建通过 |
| 官方官网新增路径校验 | 26/26 通过，含新增 6 项 QQ 群接口 |
| OneBot 真实 HTTP/WS | 11 数字身份、12 字符串身份/能力/轮询/本地文件、两版通用 WS、>1 MiB 本地文件 WS 上传、撤销即关闭/HTTP 401 与批准群只读信息查询通过；5173 两版 HTTP/WS 代理鉴权拒绝也通过；无 QQ 发送/管理动作，临时账号/Key/文件清理 |
| 本地 Key 实测 | 临时限权 Key 创建、两次复制同一 token、不可识别目标本地 403 通过 |
| 真实 QQ token | 使用 config.txt 中 AppID 及明确引用的 SECRET.txt 成功取得 token |
| 真实 QQ 身份查询 | 白名单更新后，经 8000 端口真实后端 HTTP 返回 200 |
| 真实发送 | 后端 HTTP 返回 200 和 message ID；幂等重放通过；QQ 接受不等于客户端最终展示 |
| 全类型群消息 | 文本、Markdown、键盘、引用、图片、视频、语音、文件八类均 HTTP 200、返回 message ID、幂等重放通过；四类媒体上传也均 200；用户已确认群里全部收到，详见 backend/LIVE_ACCEPTANCE.md |
| Key HTTP 生命周期 | 创建、两次同 token 复制、编辑不轮换、会话/scope 拒绝、撤销后 401 均通过 |
| Gateway / 心跳 / Resume | READY、ACK 与持久 Bot 的中断后 RESUMED 均真实通过 |
| 事件回流 | 本次两版 OneBot 模拟上游→真实 8000 HTTP→WS 回流通过；尚无用户在批准群 @QQ Bot 的新入站验收证据 |
| 日志实际页面 | 已显示持久 Bot 6 的历史发送记录；新的一次无发送真实 HTTP 检查生成 /qq/users/@me 的 200 脱敏审计，权限 403 和撤销后 401 也可见；未重复发群消息 |
| PostgreSQL 并发/多进程/故障恢复 | 用户要求暂缓，未测试 |

## 真实后端配置与测试方式

保留用户已有 Provider「111」和 Bot「依卡」，补充批准群会话。当前 Provider ID=7、Channel ID=7、Bot ID=6、Conversation ID=10；未覆盖用户已有凭据和授权。前端已确认真实会话可见。

后端 `.env` 使用标准 `HTTPS_PROXY=http://127.0.0.1:7890`、`NO_PROXY=127.0.0.1,localhost`。HTTP 与 Gateway 读取环境变量；自定义上游和回调维持独立公网 DNS pinning。

真实发现接口曾返回旧域名 api.sgroup.qq.com，其 Identify 被 4924 `session ip forbidden` 拒绝；当前文档域名 api.bot.qq.com 验证成功，因此本地配置 `QQ_GATEWAY_HOST=api.bot.qq.com`。覆盖值只接受两个明确官方域名，不支持任意 WSS 目标。

通过正在运行的真实后端 HTTP API 验收：

```powershell
cd backend
uv run --locked python manage.py verify_live_backend --owner hpd
# 明确需要发送时才追加 --send，每次最多一条纯文本。
# 用户已另外授权全类型实测；该命令每类只发一次，不自动重试失败/未知发送。
uv run --with imageio-ffmpeg python -u manage.py verify_live_backend --owner hpd --all-messages
```

`verify_live_backend` 通过 localhost:8000 的真实 Session+CSRF 管理 API 配置资源、签发临时限权 Key，并通过 HTTP 代理接口测试。Provider/Channel/会话与用户授权保留，测试 Key 撤销、合成账号清理。只从 config.txt 及其明确引用的 SECRET.txt 读取凭据，不输出秘密。

`verify_live_qq` 是独立的有界诊断命令，不应将其进程内 APIClient 验证冒充真实 HTTP 链路验收。

## 真实测试强制范围

- 唯一批准群：`36407554EC2084AF78BB2ECFC5820ACE`。
- 不向其他群发送、枚举或探测，不进行禁言、踢人、角色修改或资源删除。
- 正常发送、幂等、心跳与恢复已验证；批准群真实入站事件尚待触发，不能伪造成功。
- 代理不改变系统代理；自定义上游与回调不通过该代理绕过公网地址校验。
- API token 按用户要求在数据库明文存储；数据库/备份泄露会暴露 token。历史摘要不可恢复，数据库、备份与配置须访问控制，备份介质应加密。
- config.txt、SECRET.txt、backend/.env 已忽略，不得提交或进入前端资源。

## 开发服务

- 前端：`http://127.0.0.1:5173/`
- 后端：`http://127.0.0.1:8000/`，健康检查 `/health/`
- OneBot 通用 WS：`ws://127.0.0.1:8000/onebot/v11/`、`ws://127.0.0.1:8000/onebot/v12/`；ASGI `--ws-max-size 12582912`。开发前端也代理 `/onebot` HTTP/WS。
- 本次已在后台启动前端 5173 与后端 8000，健康检查均通过。QQ Gateway 此前验收命令为 `run_gateway --bot 6 --intents 33554432 --allowed-group 36407554EC2084AF78BB2ECFC5820ACE --status`；本次未重连真实 QQ 或重发群消息。
- OneBot 上游事件 worker 为 `run_onebot_upstream --bot ID`；下游主动投递 worker 仍为 `run_onebot`，两者独立。配置 HTTP 上报则无需启动上游 WS worker。

## 后续验收（不能冒充完成）

1. 八类群消息的 QQ 接受和用户群内收件均已确认；音视频播放细节与按钮点击行为未独立验证。ARK、Embed、流式不属于当前群接口列出的类型，未乱发测试。
2. 用户在批准群 @Bot 后，验证真实事件入库、会话发现、HTTP/WS 下游转发。公网回调投递仍需可控公网接收端。
3. 生产部署前恢复 PostgreSQL 并发、租约争抢、重复消费和 worker 故障恢复验收；本次按用户指示不执行。
