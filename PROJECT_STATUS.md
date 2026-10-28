# Botoize 项目状态

日期：2026-10-28（Channel 启动恢复与连接监督）

状态：Provider 已实现 OneBot 11/12 上游接入，并通过本地模拟上游及运行中 8000 服务的真实 HTTP/WS、发送与事件回流验收。此前 QQ 八类群消息、Key 生命周期与 Gateway 心跳/Resume 验收保留。真实第三方 OneBot 实现、公网接收端和用户触发的 QQ 新入站事件尚待联调；PostgreSQL 按用户要求暂缓，不宣称生产就绪。

本次新增：主从 Channel 配置、优先从机接收与逐条约 2 秒主机回退、主机独占发送、已登记管理操作回退、唯一群名 / 双向唯一同内容消息匹配、Dialog 群匹配新增/编辑/停用、Markdown 优先及失败/超时原类型回退。真实 ID 经证据持久替换 OB11 虚拟绑定，旧数字保留解析别名；从机离线保留真实 ID，恢复后分批扫描历史证据升级未知用户。Channel 显示 OB11/12 接入 ID。配置、命令和具体边界见 `backend/COMPANIONS.md`。

## Channel 自动连接修复

- 根因：旧 `run_connections` 仅扫描未处理的手动重连请求；请求消费后，服务器或 worker 重启不会再次启动该 Channel。
- 现在启动及每轮监督全部启用的 QQ WebSocket / OneBot 11 / OneBot 12 Channel；worker 退出自动退避重启，旧活租约到期前不抢占。停用、切换接口或更换配置会停止旧子进程；无租约的卡死子进程会被终止并替换。数据库暂时不可用时监督循环重试。
- QQ Gateway 在 Hello 后 20 秒未完成 READY / RESUMED 时重连，避免心跳 ACK 持续到达却始终未认证。
- 定向回归 47 项通过，含 OB11/12 真实子进程和本地 WS 服务：已消费请求后的冷启动、断开 socket 后原 worker 重连、杀死 worker 后监督进程替换。仅使用独立临时 SQLite 和合成上游，未发送真实 QQ 消息。
- 同步服务器已存在的两处 PostgreSQL nullable join 加锁修正至本地：主从回退及 outbox 扫描仅锁主表。PostgreSQL 按要求仍未实测。
- 本地 migrate、系统检查、makemigrations --check 通过；后端完整回归 **650 passed**（101.81 秒）；前端 5173 / 后端 8000 健康检查均为 200。未更新或重启远端部署；线上需应用修复后由常驻 `run_connections` 恢复连接。

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
- Django 迁移至 0038；0019 拆分旧共享 Channel，保留旧 Bot ID、事件与授权；0020 为旧 Bot 创建入口分配独立 Channel；0021 添加审计消息类型与幂等重放标记；0022–0023 支持多回调、精确目标/revision 和日志名称快照；0024–0028 添加 OneBot 消息上下文、Key 独立文件/分片、轮询游标、反向目标租约和频道归属；0029–0031 添加上游事件密钥、文件句柄、fencing 租约、消息来源隔离及字符串 Bot/频道 ID；0032–0036 添加主从、群匹配、真实 ID 与旧 ID 别名、附件来源、接入身份缓存、已上传媒体类型摘要和消息到达时授权快照；0037–0038 添加实际连接状态和绑定当前配置的持久重连请求。
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

- 服务提供商展开 Channel 显示上游连接状态，每 5 秒更新；Owner 可手动重连，已有有效 worker 消费持久请求，缺失 worker 由独立 `run_connections` 启动。QQ 仅 READY/RESUMED 后显示已连接，OneBot 仅事件 WS 建立后显示；旧配置或过期租约不会冒充连接。Webhook 显示接收方式并提供 HTTP 身份检查。
- Channel 的“获取 / 刷新 ID”支持新部署首次获取身份并持久显示 OB11/OB12 接入 ID，点击数字复制，失败保留旧值。Owner Session + CSRF、停用检查与脱敏错误已覆盖；官机 AppID / 内部 Bot ID / 从机账号都不是主机 Self ID。
- OneBot endpoint 校验分别说明缺少协议、非法端口、URL 中携带 Token、路径和内网/明文开关问题；支持 HTTP(S) / WS(S)，不回显原始地址或凭据。

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

### 服务器 aqt 无响应排查（2026-10-28 23:49–23:53，香港时间）

- 只读检查服务器部署版本 ea8b46f、管理事件/审计、Koishi 源码及日志；没有更新部署、重启或重发。服务器额外两处 select_for_update(of=('self',)) 调整未覆盖。compose 与运行进程有 run_connections / run_onebot_upstream，没有发现 run_companions。
- 指定 GROUP_MESSAGE_CREATE 事件 3365 在 23:52:01.635 入库，23:52:04.442 出现 get_msg，之后至 23:54 没有 send_group_msg。其引用目标事件 3287 的 get_msg 成功。Koishi 日志在此调用没有 aqt 执行/字体/发送记录。
- 直接原因是官机 msg_elements 被转成额外消息段：用服务器现有 CQCode.parse / h.transform / Argv.parse 和合成内容复现，文本 /aqt 后拼上 qq.msg_elements XML 标签，首个命令 token 不再等于 aqt。日志中 1096794533 / 683454878 两个 1400 对应另两条事件（3309 / 3372）的引用索引，实查均 Message context unavailable，不是指定 aqt 事件的查询。
- 同一元数据也参与主从 fingerprint，使官机/从机相同正文的引用消息不能配对，阻断引用目标 ID 证据；服务器事件 3329/3330、3372/3370 有相同正文和元数据差异。修复将 qq.msg_elements / qq.mentions 移至事件及 get_msg 结果顶层，保留规范历史，不拼正文；配对忽略并在历史扫描刷新旧 fingerprint。
- 本地定向 **102 passed**（34.15 秒），后端完整 **634 passed**（73.62 秒），无新 migration，前后端健康检查均 200。没有真实消息发送；服务器仍待用户自行部署并运行维护 worker 后验收。

### 官机 / OneBot 引用对应与普通 @ 消息（2026-10-28，仅本地）

- 按用户追加规则：发送时只查本地对应，reply 缺少官机消息/引用索引、at / mention 缺少官机 OpenID 时删除该段并发送其余内容；不临时读取从机历史。发送记录同步过滤，避免发送成功后因未知映射落库失败。移除后为空返回空消息错误，格式/权限/跨会话/已删除引用仍拒绝；get_msg 的只读历史查询和显式 qq.reply_to 不变。
- 追加规则验证：migrate 无待应用项；后端全量 **624 passed**（67.60 秒），前端 TypeScript 通过，5173 / 8000 均 HTTP 200。未操作服务器或执行真实发送。

- 后端持久关联官机消息 ID、msg_idx / ref_idx 和从机消息 ID；双方引用消息可补充被引用目标的对应。旧虚拟数字 ID、引用索引和 companion 字符串别名可持续解析，维护程序分批修复旧配对，不重投历史事件。
- `get_msg` 优先查授权内本地记录；仅对当前可读群事件明确引用的目标，可通过匹配从机的记录或 OB11 get_msg 获取并缓存，验证返回消息与群 ID，查询前后检查权限/配置。OB12 没有标准历史查询动作，使用已接收记录。缓存绑定引用事件授权与配对配置，断线保留可读上下文；无真实官机入站 ID 时不伪造被动回复。
- 接受发送响应中的不透明消息 ID，含 `!` 和 `/`，保存历史与引用索引。发送仍只走主机。
- 群聊 OB11 at / CQ at、OB12 mention / mention_all 转为当前官方 qqbot-at 标签，普通带 @ 消息自动尝试 Markdown；全局偏好关闭时转义正文格式，开启时保留 Markdown，显式 qq.markdown 不转义。QQ 号必须已有官机 OpenID 对应，否则按追加规则移除该段；不靠昵称猜测。失败/超时仍按用户选择回退原类型，接受可能重复。
- 官网核对发送群聊引用字段、Markdown 和 2026-10-26 更新的文本交互格式，未读 SDK。SQLite 已应用 Django 生成的 0039–0041；system check / makemigrations --check 通过。后端全量 **608 passed**（79.23 秒），前端管理组件 **9 passed**、TypeScript 通过；5173 与 8000 健康检查均 200。
- 本地实现提交 `57cbd2a`。未登录或修改服务器，未拉更新、重建镜像、重启远端服务，也未重放失败的真实发送；部署后真实 Koishi 引用链路仍需验收。PostgreSQL 继续暂缓。

### QQ 不透明消息 ID 兼容修复（仅本地，未部署服务器）

- 在用户服务器只读复现 Koishi `get_msg` 的 1400，响应为 `Expected a string platform ID`。实际官机消息 ID 含 `!`，引用索引含 `/`；此前读取持久 ID 时误用了用户/群 ID 的字符白名单。
- 消息 ID 按独立的有界不透明字符串解析，支持既有 OB11 数字映射和引用索引查询；用户/群 ID 和上游 URL 路径校验保持原规则，读取仍检查当前账号、会话、授权 revision 与事件快照。
- 相关回归 **109 passed**（53.45 秒），含引用消息读取、真实字符形态、账号隔离与控制字符/长度拒绝。用户明确要求不自动拉更新；服务器没有应用此修复、重建镜像或重启服务。

### 本次连接管理与首次身份获取

- SQLite 应用 Django 生成的 0037–0038；系统检查、makemigrations --check 通过。最终后端全量 **553 passed**（147.97 秒），前端全量 **31 passed**，lint、TypeScript 和 production build 通过；保留既有大 chunk 警告。
- `manage.py verify_connections` 通过运行中的 localhost:8000，以真实登录 Session + CSRF 创建临时 Channel，验证 OB11 / OB12 × HTTP / WS 四种组合的身份查询、首次后台连接、第二次手动重连和持久请求确认。所有上游均为本地合成服务，没有真实 QQ 发送或管理操作；临时账号、Session、Provider/Channel/Bot 已清理。
- 真实官机 Channel 7 的新 identity 管理接口经后端 HTTP 查询成功，取得并缓存两版接入 ID。新增失败分类覆盖 token / 身份阶段、连接拒绝、超时、DNS、TLS、上游数字状态/错误码及迁移解密密钥丢失，不回传异常文本或上游正文。用户另行部署服务器的旧通用报错尚无法确定根因，需更新诊断补丁后取得分类；本机成功不能证明远端网络正常。
- 后台前端 5173 / 后端 8000 健康检查通过；`run_connections` 和 `run_companions` 常驻。QQ 官方 HTTP 继续读取既有代理环境变量；主从真实第三方环境与公网回调尚待联调，PostgreSQL 按要求不测，Computer Use 不可用故本次不声称界面目视通过。

### 本次主从协作

- SQLite 已应用 Django 生成的 0032–0036，makemigrations --check 与系统检查通过。
- 后端完整回归 **525 passed**（121.23 秒），其中主从定向 64 项覆盖两版主机/从机、消息先后顺序、离线/恢复、历史真实 ID 升级、旧别名、主机独占发送/附件上传、管理回退与到达时授权快照。
- 前端完整 **24 passed**，含群匹配 Dialog 新增/编辑/停用、刷新草稿保护、Markdown 偏好保存和接入 ID 展示；TypeScript、lint、构建通过，仍有既有大 chunk 警告。
- 前端 5173 / 后端 8000 健康检查通过，后台新增 `run_companions` 维护进程；没有更改用户真实 Channel 配置，没有真实 QQ 发送或管理副作用。界面目视验证仍被 Computer Use native pipe os error 2 阻断，不声称已目视验收。

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
- 后台常驻 `run_connections --allowed-group 36407554EC2084AF78BB2ECFC5820ACE` 与 `run_companions`。前者持续监督启用的 socket Channel 并处理 Owner 重连请求，后者维护主从逐条接收回退与匹配；前端/API 启动不等于这些 worker 已启动。

## 后续验收（不能冒充完成）

1. 八类群消息的 QQ 接受和用户群内收件均已确认；音视频播放细节与按钮点击行为未独立验证。ARK、Embed、流式不属于当前群接口列出的类型，未乱发测试。
2. 用户在批准群 @Bot 后，验证真实事件入库、会话发现、HTTP/WS 下游转发。公网回调投递仍需可控公网接收端。
3. 生产部署前恢复 PostgreSQL 并发、租约争抢、重复消费和 worker 故障恢复验收；本次按用户指示不执行。
