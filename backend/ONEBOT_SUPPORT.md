# Botoize OneBot 11 / 12

核对日期：2026-10-27。本页描述 QQ 官机的下游 OneBot 映射，不是 QQ 个人号协议，也不宣称拥有 QQ 未开放的权限。Provider 也支持 OneBot 11/12 上游，其配置、事件接收和独立能力范围见 [OneBot 上游](ONEBOT_UPSTREAM.md)。

## 连接

| 通信 | OneBot 11 | OneBot 12 |
| --- | --- | --- |
| HTTP | GET/POST `/onebot/v11/{action}`；兼容旧 `/onebot/{action}` | POST JSON `/onebot/v12/` |
| 通用正向 WS | `/onebot/v11/`；兼容 `/onebot/` | `/onebot/v12/` |
| 分离 API / Event WS | `/onebot/v11/api`、`/onebot/v11/event` | `/onebot/v12/api`、`/onebot/v12/event` |
| HTTP 事件轮询 | 使用原生 relay 或 WS | `get_latest_events` |
| 反向通用 WS / HTTP 上报 | `run_onebot --version 11` | `run_onebot --version 12` |

HTTP 和 WS 使用 **Botoize API Key**，推荐 `Authorization: Bearer <key>`。新版本入口支持规范的 `access_token` query fallback，Authorization 头优先，错误头不会回退；ASGI 在访问日志输出前移除 URL token。但浏览器、网关仍可能记录原始 URL，因此不要用 query 传密钥。拒绝带 Origin 的 WS 和 Cookie 身份，使用服务端客户端。

旧 `/onebot/api`、`/onebot/event` 保留 Origin/额外 query 拒绝和 64 KiB API 帧限制；URL access_token 由 ASGI 提取并脱敏，建议改用版本化入口。新入口 JSON 请求/帧上限 12 MiB，不支持可选 MessagePack。API 动作串行执行，每次重新鉴权、消耗共享限流/配额并记录脱敏审计。空闲 WS 约每 200ms 检查撤权。12 先发送 connect（含版本），然后 status_update，每 30 秒 heartbeat，并在 HTTP 身份探测状态变化时发 status_update。`online` 依据是身份 HTTP 可达，不等于 Gateway 长连接健康。

11 HTTP params 直接放 query / JSON / form；12 HTTP/WS 是：

```json
{"action":"send_message","params":{"detail_type":"group","group_id":"ORIGINAL_GROUP_OPENID","message":[{"type":"text","data":{"text":"hello"}}]},"echo":"request-1"}
```

12 的 echo 必须是字符串，self 若传入必须匹配当前 Key 的机器人。11 echo 原样回传任意 JSON。12 使用标准 10001/10002/10003/10004/10005/10006/10007/10102 以及 33xxx/34xxx/35xxx 错误码。11 保留 1400 参数、1403 权限、1404 不支持、1429 限流、1500 官方拒绝、1502 结果未知。

## ID、上下文和权限

- **12 的 user_id/group_id/message_id 均保留原始字符串**，包括前导零；不 hash、不转整数。QQ 群成员 OpenID、单聊 OpenID、频道用户 ID 仍由 QQ 决定，不能假设可以跨场景互换。
- 11 优先使用已验证的真实数值 ID；官机尚无真实 ID 证据时，按 Bot + 类型持久分配虚拟 ID（用户/群为 1..2^53-1，新消息为 int32 正数）。配置 OneBot 从机后，使用双方同一条已验证消息逐步升级既有绑定并保留旧 ID 别名解析；已知真实 ID 在从机离线后仍可用，不从 OpenID 猜测 QQ 号。通过 `botoize.get_known_conversations` 获取授权内的当前目标 ID，Channel 显示自身 OB11/12 接入 ID。详见 [主从协作](COMPANIONS.md)。
- 当前账号、Key、Bot、授权链/revision、scope、会话范围统一生效；原始字符串 ID 不能绕过会话校验。频道/频道群组操作只允许全会话授权，不把频道 ID 冒充 QQ 群 OpenID。
- 撤回、引用和读取要求存在持久消息上下文。不能只传任意消息 ID 让后端猜目标。发送记录只允许所属账号访问；入站记录还必须存在当前用户、当前授权版本的事件投递记录。不能读其他账号发送记录或旧授权历史。
- `messages:send` 发送，`media:upload` 上传/发送媒体，`messages:delete` 撤回，`events:read` 事件/消息/文件读取，`query:read` 元信息与能力查询。群信息 `groups:read`、成员 `group-members:read`、踢人/禁言 `group-moderation:write`、审批 `group-requests:write`。频道沿用 guilds/channels/members 的独立 scope。新 scope 不自动加入旧 Key。

## 动作覆盖

| 能力 | 11 动作 | 12 动作 |
| --- | --- | --- |
| 身份、状态、版本 | get_login_info / get_status / get_version_info | get_self_info / get_status / get_version |
| 能力发现 | botoize.get_capabilities | get_supported_actions / botoize.get_capabilities |
| 发送 | send_private_msg / send_group_msg / send_msg | send_message（private/group/channel） |
| 撤回 | delete_msg | delete_message |
| 本地已保存消息 | get_msg | 无标准 get_message；不伪造一个标准动作 |
| 媒体检查 | can_send_image / can_send_record | 能力发现 |
| 文件 | CQ/数组的 file 参数支持 file_id、公共 HTTP(S)、base64:// | upload_file / get_file / upload_file_fragmented / get_file_fragmented |
| 群信息 | get_group_info | get_group_info |
| 群成员 | get_group_member_info / get_group_member_list | 同名标准动作 |
| 踢人、禁言、入群审批 | set_group_kick / set_group_ban / set_group_add_request | qq.set_group_kick / qq.set_group_ban / qq.set_group_add_request 扩展 |
| 频道查询 | 无 11 标准频道动作 | get_guild_info / get_channel_info / get_channel_list / get_guild_member_info / get_guild_member_list |
| 频道改名 | 无 11 标准动作 | set_channel_name |
| 已知会话、分页群成员 | botoize.get_known_conversations / botoize.get_group_members_page | 同名扩展 |
| 清理过期文件缓存 | clean_cache（仅当前 Key） | 文件 24 小时到期，新上传时清理 |

群成员列表会真实分页，最多 20 页，达到上限或游标循环返回错误，**不把部分结果当完整列表**。可用分页扩展 `{group_id,cursor}` 返回 `{members,next_cursor}`。QQ群完整好友/已加入群列表没有已核实的全量枚举接口，因此 get_friend_list/get_group_list 不支持；已知会话不是好友名单。未知字段用规范类型的空值并标注 unknown_fields，不伪造群容量/年龄/群名片。群成员新接口为内邀/白名单能力，最终权限由 QQ 判断。

未开放/未实现的标准动作明确不支持：get_stranger_info/get_user_info、get_forward_msg、send_like、set_group_anonymous_ban/set_group_whole_ban/set_group_admin/set_group_anonymous/set_group_card/set_group_name/set_group_leave/set_group_special_title、set_friend_add_request、get_group_honor_info、get_cookies/get_csrf_token/get_credentials、get_record/get_image（不暴露服务器文件路径）、set_restart，以及 12 get_guild_list/set_guild_name/leave_guild/get_channel_member_info/get_channel_member_list/leave_channel/set_group_name/leave_group 等。不会把退出频道映射成删除频道，不暴露 QQ 凭据或重启共享平台。异步后缀不假装已排队。

## 消息与事件

单聊/群支持 text、image、voice（11 record）、video、file（11 botoize.file 扩展）、reply。群聊另支持 OB11 at / CQ at 和 OB12 mention / mention_all，用户 ID 须有主机 OpenID 对应；带 @ 的普通文本自动尝试 Markdown，全局偏好关闭时转义正文以保留普通文本显示。@全部成员仍受 QQ 管理员权限和次数限制。每次最多一个媒体，不静默拆成多次发送或吞掉不支持的段。独立 audio 音乐语义、位置、匿名、合并转发不伪装成普通文本。QQ Markdown/键盘用 `qq.markdown` / `qq.keyboard` 扩展。

12 频道支持 text、mention、mention_all、reply、单图及 qq.face/qq.markdown/qq.keyboard/qq.ark/qq.embed。频道发送额外需要 channels:read 验证 guild/channel 归属。其他组合返回明确错误；不静默解释普通文本中的 `<@...>` 为结构化提及。

引用使用保存的 `message_scene.ext` 中 msg_idx / 发消息响应 ext_info.ref_idx；不把 auth_token 传给下游。`qq.reply_to` 是独立的被动回复扩展，指向同一会话内已授权的真实入站消息，5 分钟内有效，服务端持久递增 msg_seq；不能任意注入 msg_id/msg_seq。QQ 限制每条消息最多被动回复 5 次，最终由 QQ 拒绝超额。网络结果未知不自动重试发送。

主从配对会持久关联官机消息 ID、引用索引与从机消息 ID，引用消息本身也可补充被引用目标的对应。旧 ID 别名继续可查。`get_msg` 可依据当前可读引用，通过匹配从机记录或 OB11 历史查询补齐目标并缓存；必须核对群归属和当前授权，OB12 不虚构历史查询动作。详情及离线/历史修复边界见 [主从协作](COMPANIONS.md)。

接收 C2C、群 @/全量消息，12 还转换频道消息；附件转为可取文件，引用转为 reply，卡片/嵌套消息/提及列表保留为明确的只读 QQ 扩展，不悄悄丢失。群成员增减、机器人进退群、好友增减映射标准 notice；未知操作者留空/0、未知退出原因用空/扩展子类型。11 入群申请产生标准 group/add request，12 用 qq.group_join request 扩展；flag 绑定当前用户事件记录。无法规范化的事件，12 使用 qq.raw_event 扩展，不伪造标准事件类型。

正向 WS 从连接时的事件尾部开始，断线不补发历史；12 HTTP 轮询是每 Key 独立的 1000 条逻辑缓冲区（超出可丢旧事件），与 WS/回调游标互不消费，limit=0 取当前缓冲中的全部；timeout 最大 30 秒。事件 id 稳定，消费者必须去重。反向传输另持久化每目标游标和 fencing 租约，首次配置从当前尾部开始，重启继续游标。WS 发送成功不是业务确认，崩溃边界可能重复，不能承诺 exactly-once。

## 文件安全配置

文件 ID 是当前 Key 独有的不透明 UUID，24 小时有效；入站文件额外绑定会话（频道文件始终要求全会话授权）。数据最大 8 MiB、每 Key 64 MiB / 1000 项；QQ 发送二进制直传最大 5 MiB，超出明确拒绝而非冒充支持大文件传输。分片支持乱序、精确重试、SHA256 校验和冲突/空洞检测。

upload_file 支持 data（JSON Base64）和公共 HTTP(S) URL/安全 headers。每次 DNS 校验全部结果并固定实际连接 IP，验证 TLS，不跟随跳转，不走环境代理，不接受服务器 path、localhost/私网、危险 header。get_file 支持 data；只有来自事件的可用远程 URL 才支持 type=url，本地上传没有凭空生成公开下载地址。path / 不可用 URL 返回 Unsupported Param。

## 反向连接与 HTTP 上报

运行者通过已存 API Key ID 显式配置，不在命令行放 Key 或 QQ Secret：

```powershell
uv run --locked python manage.py run_onebot --key-id 123 --version 12 --transport reverse-ws --url wss://receiver.example/onebot
uv run --locked python manage.py run_onebot --key-id 123 --version 11 --transport http-webhook --url https://receiver.example/event
```

目的端访问令牌从 `BOTOIZE_ONEBOT_REMOTE_TOKEN` 读取，11 HMAC secret 从 `BOTOIZE_ONEBOT_WEBHOOK_SECRET` 读取，可用 `--token-env` / `--secret-env` 指定变量名。**目的端令牌不等于本地 API Key**，默认不会把 Botoize Key 发给接收端。新进程需要 `events:read`；动作仍受该 Key 的具体 scope 限制。

安全配置仅允许公网 HTTPS/WSS 443，固定 IP、TLS 校验、无重定向、无环境代理，不能通过网页配置 SSRF 到本机。`--interval` 1..30 秒，默认 3 秒；反向 WS 断线自动重连，撤权或租约失效停止。12 使用 `Sec-WebSocket-Protocol: 12.botoize`，11 使用 X-Self-ID / X-Client-Role: Universal。每目标只有一个有效 worker。

HTTP 11 上报带 X-Self-ID、可选 sha1 HMAC X-Signature；12 带 X-OneBot-Version/X-Impl，可选远端 Bearer。成功响应 200/204，12 的 JSON 动作列表按顺序鉴权执行；11 快速回复支持 reply/auto_escape，群回复须显式 at_sender=false（QQ 官机群发送没有任意 @ 段，不能假装提及）。不支持的快速管理操作明确计为 rejected，不假装成功。200/204 先持久确认事件，再执行快速动作，避免动作失败触发重复发消息。非法 quick response 只拒绝动作，不重复投递已成功事件。网络失败保留游标重试，可能重复事件。

## 验收与来源

`uv run --locked python manage.py verify_onebot --bot 6` 对正在运行的真实 8000 HTTP/WS 服务验收：临时 Session/CSRF 授权/Key、11 数字身份、12 字符串身份/能力/事件轮询/本地文件、两版通用 WS、运行中撤销与 HTTP 401、批准群只读信息查询。**没有 QQ 发消息或群管理副作用**，临时账号/Key/文件清理。

已真实通过上述链路、群信息查询及大于 1 MiB 的本地合成文件 WS 上传；ASGI 启动需 `--ws-max-size 12582912`（12 MiB）。前端接入页经 computer-use 在桌面和窄屏只读检查，复用现有组件，配置表仅在自身容器滚动。反向公网接收端、真实新入站事件与第三方框架端到端仍未验收，不能以本地模拟替代。PostgreSQL 按用户指示暂缓。

规范来源：[OneBot 11](https://github.com/botuniverse/onebot-11)、[OneBot 12](https://12.onebot.dev/)、[12 规范源码](https://github.com/botuniverse/onebot/tree/main/specs)。QQ 来源为当前官网 autogen/api 的 v2_groups_group_openid_info.get、members.get、members_member_openid.get、batch_remove_members.post、restrict_chat_setting.post、approval_join_request_member_openid.post，以及 messages.post/files.post、autogen/event 群/单聊/成员/好友事件页。没有读取旧 QQ SDK。
