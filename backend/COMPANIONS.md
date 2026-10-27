# 主从 Channel 与真实 ID

更新：2026-10-27。

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

已有历史不会重新投递。维护程序每批扫描双方各最多 200 条尚未观察的、已验证持久群消息，逐步重建对应证据并更新绑定；每 60 秒尝试只读刷新群名称及匹配。不能凭 OpenID 解算真实 QQ 号，没有双方证据的绑定需要后续可匹配消息，不声称已全部识别。

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

QQ 是否接受 Markdown 及组合由应用权限和当前接口决定；不保证仅换类型后每种图文都被接受，也不为图片改写用户原文或插入 URL，失败走原类型。官方格式依据 [Markdown 文档](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/type/markdown.html)，未读取旧 SDK。

本地模拟覆盖两版从机、先后顺序/回退/恢复、真实 ID 与旧别名、历史升级、权限隔离、管理回退、主机发送和 Markdown。真实第三方 OneBot 与实际群环境还需联调；本次未向真实 QQ 发送或执行群管理，PostgreSQL 按要求暂缓。
