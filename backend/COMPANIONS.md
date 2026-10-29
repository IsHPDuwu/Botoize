# 主从 Channel 与真实 ID

更新：2026-10-28。

在平台管理 → 服务提供商 → Channels 的“主从协作 · 群聊匹配”选择另一个 Provider 的 OneBot 11/12 Channel。每个主机最多一个从机，禁止自身、同 Provider、链式和循环配置。主从各自需要已配置的接收方式：官机 Gateway/Webhook、从机 `run_onebot_upstream --bot ID` 或已鉴权 HTTP 上报。

## 消息与管理

- 匹配群中优先使用从机消息；主机消息先持久化，给从机约 2 秒到达窗口。逐条没有对应从机消息就发布主机消息，不依赖在线标记猜测是否漏收。从机停用时直接发布主机消息。
- 从机先到、主机后到或主机已回退后从机恢复，均不为同一已确认消息再生成主机投递。订阅本身仍是至少一次投递，消费者仍需幂等。
- 所有发送、上传和撤回只走主机。引用必须有当前授权内持久消息上下文；从机独有消息尚无主机官方被动回复 ID 时明确拒绝被动回复，不能拿从机消息 ID 发给 QQ。附件使用从机读取、主机重新上传；不复用两个上游的文件句柄。
- OneBot 的已登记群/用户管理动作先调用主机；明确不支持、官方拒绝或上游不可用后再尝试从机。参数、本地 scope、会话或授权拒绝不会触发回退。群需启用匹配；指定成员需已验证用户 ID。11 特有管理动作不能凭空转换成 12 标准动作。
- 原生 `/qq/` 的群资料、成员资料/列表，以及单成员踢人/禁言有等价回退；未知 cursor、多成员批量操作、频道管理、请求审批和没有等价标准动作的路径保留原错误，不猜测从机审批 flag。原生回退返回 `X-Botoize-Source: companion`。
- 从机仍保有自己的事件流；主机用户只通过主机 Key/账号/授权链/revision/scope/会话获得协作消息和文件，不获得从机凭据或独立访问权。主机调用结束后，执行从机管理前再次检查主机 Key 是否仍有效。

## 群匹配与 ID 升级

群名必须在两边已知群中都唯一且完全一致才自动匹配；重名或未知名称时，使用双方相隔不超过 10 秒、文本内容一致的群消息，要求候选双向唯一。只靠两张无法辨认的图片不匹配，也不根据相似昵称猜用户 QQ 号。已有、手动或停用决定优先，自动证据不会覆盖。

列表展示主机原始群 ID、从机原始群 ID、名称、来源和启用状态；新增和编辑使用现有 Provider Dialog 样式。手动纠正或停用会提升主机授权 revision、撤销旧 Key，防止旧授权继续访问此前映射。改变配对或手动决定后旧桥接事件不再对新配置可见。

OB11 优先使用从机已验证的真实数值 ID，并将数据库 `OpenID → virtual_id` 逐项替换；真实值也独立持久保存。从机断线/停用不会清空它们。断线期间无法确认的新用户先使用持久虚拟 ID，恢复后通过双方同一条已验证消息（发送者和对应提及）升级。OB12 保留主机原始字符串 ID；尚无主机 OpenID 的从机用户先使用明确的 `companion_…` 代理 ID，获得双方证据后归并为真实主机 OpenID。旧虚拟 ID 保留别名解析，已经发给客户端的历史数据不会被远程改写。

同一个数字若原本是另一个对象的虚拟 ID、后来确认是真实 ID，真实 ID 优先；旧虚拟对象重新分配，发生数值歧义时无法同时保持两种含义。非数字 12 ID 无法作为 OB11 数值使用，继续使用映射。不把从机的个人账号 ID 当作官机自身 ID。Channel 显示 `connection_ids.onebot11/onebot12`；官机首次身份查询/连接后缓存自身原始 ID，OneBot Channel 使用其配置 Bot ID。

官机自己的 `self ID → 实际 QQ 号` 也持久写入用户 ID 映射。证据来自已保存的官机发送记录与从机收到的该条消息：优先已验证的消息 ID 对应，否则限定已匹配群、10 秒内相同内容且双向唯一；不使用从机登录账号代替官机 QQ 号。重复、冲突、旧上游来源或停用群匹配不建立绑定。身份刷新、发送落库、读取自身发送记录、成员查询回退和历史维护会补查证据（每次最多扫描最近 200 条已发送群消息），无须重放发送；旧虚拟 self 数字保留为别名。绑定成功后 OB11 自身 ID、发送者 ID 和向从机查询成员所用的账号均使用官机实际 QQ 号；从机离线时仍保留该绑定。

已有历史不会重新投递。维护程序每批扫描双方各最多 200 条尚未观察的、已验证持久群消息，逐步重建对应证据并更新绑定；每 60 秒尝试只读刷新群名称及匹配。不能凭 OpenID 解算真实 QQ 号，没有双方证据的绑定需要后续可匹配消息，不声称已全部识别。

### 引用消息对应

后端持久维护「官机 message ID ↔ 官机 msg_idx / ref_idx ↔ 从机 message ID」。配对的引用消息还会提供「官机 ref_msg_idx ↔ 从机 reply ID」证据，即使原消息未被官机接收，也可补出引用索引。旧虚拟数字 ID、引用索引和 `companion_…` 字符串保留别名，后续收到原消息时归并到官机消息 ID；不会将从机数字 ID 直接传给 QQ。

QQ 有时给同一条被引用消息签发不同于原 msg_idx 的 ref_msg_idx。上游→下游始终保留引用段，未知索引也分配持久 ID，供下游 get_msg；不根据文本快照猜目标。成功配对的引用消息提供从机真实 reply ID，将新索引绑定到已知目标；目标已有不同官机索引也保留原发送索引并登记新别名。下游→官机发送时，无法取得对应官机引用 ID 才静默去掉引用，继续发送正文。从机同时提供相同 Markdown 与纯文本替代内容时只展示一次，避免 Koishi 引用正文重复，也避免破坏消息配对。

`get_msg`、`get_stranger_info`、`get_user_info` 对当前 Channel 的有效 Key 开放，不再额外要求 action scope、会话选择或消息曾投递给该账号。查询前后仍检查凭据撤销、授权有效性和所属 Channel。`get_msg` 优先查本地；缓存未命中时可直接调用该 OneBot 上游或配置的 OB11 从机 `get_msg`，使用已登记真实 ID 或请求中的真实数字，核对返回的消息 ID 后缓存。历史缓存保留群/用户 ID；官机自己的发送记录缺少 sender 时用官机自身身份补齐。OB12 没有标准历史读取动作，使用已接收的记录。

维护程序会逐批修复旧配对的引用关系，并刷新双方旧消息指纹、循环扫描已存在但未配对的记录，将用户和消息虚拟 ID 升级为真实 ID。`run_connections` 每分钟也执行无网络调用的历史修复，避免漏启维护进程导致旧 ID 永久无法升级。缓存可在从机断线后读取；只获得引用索引时可以引用展示，但不会伪造官机被动回复 ID，`qq.reply_to` 仍要求真实官机入站上下文。

```powershell
cd backend
uv run --locked python manage.py migrate
uv run --locked python manage.py run_companions
# 只执行一次刷新和到期回退：追加 --once
```

该 worker 持久处理到期主机消息，名称发现独立于短周期队列，不因慢网络卡住逐条回退。HTTP 事件读取、原生/OneBot WS、轮询和订阅领取任务也会处理到期队列。ASGI 不自动启动 worker。

Owner 可 POST `/api/v1/channels/CHANNEL_ID/companion/refresh/`（Session + CSRF，正文 `{}`）；失败保留现有匹配。Provider 保存支持 `companion_channel`、`group_matches`（id / primary_group / companion_group / name / enabled）及 `prefer_markdown`。

## Markdown 优先

仅官机 Channel 可启用。文本和确认是图片的图文先尝试 Markdown，`markdown.content` 与原始文本完全相同，保留回复/键盘等上下文。失败或超时后尝试原始类型；用户明确接受超时结果未知时可能重复发送。已是 Markdown、视频/语音/文件和未知媒体类型不转换；原生上传记录按 Bot、目标和 opaque file_info 的摘要保存图片类型及有效期，不反推 opaque 内容。

普通群消息包含结构化 @ 时，无需开启全局 Markdown 优先，也会尝试 Markdown。OB11 `at` / CQ at 和 OB12 `mention` / `mention_all` 转为当前官方的 `<qqbot-at-user id="member_openid" />` / `<qqbot-at-everyone />`；真实数字用户 ID 必须已有主机 OpenID 对应。发送时若数据库找不到官机引用索引或该用户 OpenID，移除对应 reply / at / mention 段，继续发送其余内容，不为发送临时查询从机历史。发送历史只保存实际保留的段；无法转换的附加段、无效/跨会话/已删除引用静默跳过，多媒体只保留可转换的首项。全被移除后返回成功且 data=null，不调用 QQ 发送空消息。OB11 图片 cache/proxy/timeout 等兼容选项忽略。发送目标和写权限仍校验。显式 `qq.reply_to` 的被动回复校验保持不变。未开启全局转换时转义正文 Markdown 和 HTML，保留普通文本显示及 @ 标签；开启时保留正文 Markdown 格式。显式 `qq.markdown` 不转义。邮件地址、普通 `@昵称` 不触发转换；原生内容中的官方 @ 标签及旧 `<@…>` 格式也可触发。@全部成员的管理员权限与每日次数由 QQ 限制。失败/超时回退仍保留原请求，可能重复。

QQ 是否接受 Markdown 及组合由应用权限和当前接口决定；不保证仅换类型后每种图文都被接受，也不为图片改写用户原文或插入 URL，失败走原类型。官方格式依据 [Markdown 文档](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html)，未读取旧 SDK。

引用字段依据 [发送群聊消息](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html)，@ 格式依据 [文本交互](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/text-chain.html)（2026-10-26 更新）。

本地模拟覆盖两版从机、先后顺序/回退/恢复、真实 ID 与旧别名、历史升级、权限隔离、管理回退、主机发送和 Markdown。真实第三方 OneBot 与实际群环境还需联调；本次未向真实 QQ 发送或执行群管理，PostgreSQL 按要求暂缓。
