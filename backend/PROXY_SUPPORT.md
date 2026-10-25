# 官方代理当前支持范围

产品名称为 Botoize。原版 Koishi QQ 适配器与 adapter-qq-crack 1.0.31 不能只改 endpoint 连接本项目；它们的官方 token / QQBot 认证与 Gateway 协议尚无下游兼容层。真实配置字段、源码核对及建议方案见 `KOISHI_COMPATIBILITY.md`，不将自定义地址等同于协议兼容。

QQ 官方默认上游为 `https://api.bot.qq.com`，Channel 可配置经过公网 HTTPS 校验的 base_url；下游使用 `Authorization: Bearer <API Key>`，平台在服务端替换为上游凭证。
自定义上游会接收 Channel 的 AppID/AppSecret，请仅配置可信服务。其 DNS 固定到经过校验的公网 IP，禁止跳转；token 缓存按 Bot、凭据和完整 base_url 隔离。
官方 HTTPS API 默认读取标准 `HTTPS_PROXY` / `https_proxy` 及 `NO_PROXY`；Gateway 也自动发现环境代理（另支持 WSS_PROXY / ALL_PROXY，遵循 websockets 库优先级）。建议 `HTTPS_PROXY=http://127.0.0.1:7890`、`NO_PROXY=127.0.0.1,localhost`。旧 `QQ_HTTP_PROXY` 非空时为显式覆盖。自定义上游与回调不使用环境代理，保留 DNS pinning。

| 下游接口 | 所需权限 |
| --- | --- |
| `GET /qq/users/@me` | `query:read` |
| `POST /qq/v2/users/{user_openid}/messages` | `messages:send` |
| `POST /qq/v2/groups/{group_openid}/messages` | `messages:send` |
| `DELETE /qq/v2/users/{user_openid}/messages/{message_id}` | `messages:delete` |
| `DELETE /qq/v2/groups/{group_openid}/messages/{message_id}` | `messages:delete` |
| `POST /qq/channels/{channel_id}/messages` | `messages:send`，JSON 或 multipart/form-data |
| `POST /qq/users/@me/dms` | `messages:send`，创建频道私信会话 |
| `POST /qq/dms/{guild_id}/messages` | `messages:send`，JSON |
| `DELETE /qq/channels/{channel_id}/messages/{message_id}` | `messages:delete` |
| `DELETE /qq/dms/{guild_id}/messages/{message_id}` | `messages:delete` |
| `POST /qq/v2/users/{user_openid}/files` | `media:upload`；srv_send_msg=true 另需 messages:send |
| `POST /qq/v2/groups/{group_openid}/files` | `media:upload`；srv_send_msg=true 另需 messages:send |
| `POST /qq/v2/users/{user_openid}/upload_prepare` | `media:upload` |
| `POST /qq/v2/groups/{group_openid}/upload_prepare` | `media:upload` |
| `POST /qq/v2/users/{user_openid}/upload_part_finish` | `media:upload` |
| `POST /qq/v2/groups/{group_openid}/upload_part_finish` | `media:upload` |

消息 JSON 请求仅接受对象；频道发送另支持 multipart/form-data。正文最大 1 MiB（平台上限），原始字节透传，不添加或递增 `msg_seq`。OpenID 当前接受字母、数字、下划线及短横线，长度 1–128。未登记路径返回 501。官方响应正文最大 64 KiB。

媒体 files 请求同样限 JSON 正文 1 MiB（平台保守上限，不是官方 5M 二进制直传上限）。
必须显式传布尔 `srv_send_msg`：false 仅上传，true 具有主动发消息副作用并额外检查 messages:send。
URL 上传由 QQ 官方下载，代理不会下载该 URL；请求原字节及官方 file_info、file_uuid、ttl、raw_url 原样透传，不解析 opaque file_info 或延长其有效期。
单聊/群聊 file_info 的场景范围由官方限制，不能互换。支持 files 的 URL、受正文上限约束的 file_data、upload_id 合并请求。
大文件流程：先调用 upload_prepare 获取 upload_id、block_size 与 parts；客户端自行将分片 PUT 到官方返回的 presigned_url（不要携带平台 Bearer Key），每片成功后调用 upload_part_finish，最后用 files 合并。
代理仅转发官方控制面接口，不获取或代理 presigned_url，不记录响应正文或其中的 URL 签名；若显式使用幂等扩展，响应会加密缓存至 24 小时到期清理。
upload_prepare 的返回 URL 有时效，幂等重放不刷新签名；客户端不得把缓存重放视为新上传任务。
媒体 files POST 同样支持 Idempotency-Key，并在未知结果时不自动重试。

保留官方 HTTP 状态、响应正文以及 Content-Type、X-Tps-trace-ID、Retry-After。201/202 不代表最终消息送达；仍须处理官方异步审核语义。禁止自动重定向，不自动重试消息。平台返回 `official_outcome_unknown` 时无法确定发送结果，调用方不得盲目重发。

权限仍受当前账号、Bot、显式 BotGrant、授权版本及 Key 范围限制。Owner 身份不自动扩大数据面权限。

撤回采用独立 `messages:delete`，现有发送 Key 不会自动获得撤回权。请求不得携带正文，保留官方状态、空正文和错误；不自动重试。官方文档规定超过两分钟不可撤回，由官方判断；群管理员 Bot 可能撤回普通群成员消息，因此该权限是整个 Bot 范围的敏感权限，不限于该 Admin 自己通过代理发送的消息。

频道发送支持 JSON 与 multipart/form-data：保留原始 Content-Type（包括 boundary）、正文和 file_image 字节，不重新序列化对象字段。multipart 暂不扩展至未经核实的其他端点。
频道 ID、私信 guild_id 与 QQ 群 OpenID 不作等价转换。频道发送的官方在线要求、回复时效、消息审核均由 QQ 校验；需单独运行 Gateway 进程，启动 HTTP 服务不表示 Bot 已上线。
频道/私信撤回透传 hidetip 查询；官方文档限制私域机器人可用，不绕过官方权限，也不将单聊/群聊的两分钟规则强加给频道接口。

## 可选发送幂等扩展

官方消息 POST 可附带 `Idempotency-Key`（1–128 个 ASCII 字母、数字或 `._:-`）。
作用域为用户与 Bot，跨 API Key 共享；同一键必须具有完全一致的路径、查询和请求正文原始字节；multipart 还比较完整 Content-Type，避免不同 boundary 错误重放。
首次发送以数据库唯一约束占位，不在网络期间持有事务锁。重复请求在 24 小时内重放已缓存的官方状态、正文和安全响应头，追加 `Idempotency-Replayed: true`；每次仍先检查当前授权。
同键不同参数、正在处理、发送结果未知或已过期均返回平台 409，不自动重发。
进程中断留下的占位不会自动重新领取；应人工核对官方结果，而不是更换幂等键盲目重发。
定期运行 `cleanup_idempotency` 清除过期加密响应正文，摘要墓碑保留至用户或 Bot 删除；过期键不可复用。
本扩展不等于官方消息去重，也不保证恰好一次；未传该请求头时保留原始发送行为。

事件接收已通过验签 Webhook 实现，见 `WEBHOOK_STATUS.md`。下游 WebSocket 地址为
`/relay/v1/ws/?after=0`，必须在握手 Authorization 头传 Bearer API Key，要求 events:read。
不接受 Cookie 或 URL 中的 Key，拒绝携带 Origin 的浏览器连接；请使用服务端 WS 客户端。
每帧为 `{"cursor":"123","payload":{...官方原始事件...}}`，每批最多 50 条，约每秒重新检查授权。
断线后从最后业务处理成功的 cursor 重连，客户端自行去重；发送游标不是业务确认。
须运行支持 WebSocket 的 ASGI 服务器，Django runserver 不提供此功能。
该流是本平台协议，不是官方 Gateway，也不是 OneBot WebSocket。

## OneBot 11 / 12 下游

已扩展为双版本 HTTP、正向通用/分离 WS、反向通用 WS、HTTP 上报及 12 事件轮询。12 保留原始字符串 ID，11 使用持久数值映射（不是 QQ 号）。支持文本/媒体/文件/引用/撤回、群信息/成员/管理以及 12 频道能力；不支持的动作、消息段与参数明确失败，不伪造成功或完整名单。

版本入口为 `/onebot/v11/{action}` 与 `/onebot/v12/`，通用 WS 为 `/onebot/v11/`、`/onebot/v12/`。旧 `/onebot/{action}`、`/onebot/api`、`/onebot/event` 保留。完整动作/事件/错误码/安全限制、反向进程启动和配置见 [ONEBOT_SUPPORT.md](ONEBOT_SUPPORT.md)。

新版 QQ 群信息和成员接口包含白名单/内邀限制，群管理仍需管理员身份和独立 scope。已真实通过双版 HTTP/WS 身份与 Key 撤销验收、批准群只读信息；媒体和破坏性管理映射使用本地模拟，不重复向真实群发消息。反向公网接收端与真实新入站事件仍待验收，不宣称生产就绪。

## 管理 API 与凭据

细粒度官方管理路径由 `core/official_routes.py` 的 49 个操作统一驱动 capabilities 和 OpenAPI，含本次按新版官网增加的 6 个 QQ 群接口，见 SCOPE_AUDIT.md 和 ONEBOT_SUPPORT.md。
Owner 配置 Provider/Channel，Channel 下的 Models 为会话；同步只回填历史事件，未知会话由后续已验证事件发现，不枚举未知群/用户。
Key 创建、原 token 复制、同 token 编辑均要求所属用户和当前有效授权；只有摘要的历史 token 返回不能恢复，不自动轮换。
按当前产品要求，原始 API token 以明文存储在数据库；数据库/备份泄露会直接暴露 Key，不存在加密保护承诺。
所有非登录管理操作不重复索要密码，Session、CSRF、角色、归属及授权子集检查仍保留。

核对来源：
- OneBot HTTP 核实日期：2026-10-25；https://github.com/botuniverse/onebot-11/blob/master/communication/http.md
- OneBot 字段类型及 QQ 号语义：https://github.com/botuniverse/onebot-11/blob/master/api/public.md
- 频道接口核实日期：2026-10-25。
- https://bot.q.qq.com/wiki/develop/api-v2/server-inter/channel/message/send.html
- https://bot.q.qq.com/wiki/develop/api-v2/server-inter/channel/message/recall.html
- https://bot.q.qq.com/wiki/develop/api-v2/server-inter/channel/message/dms.html
- 撤回接口核实日期：2026-10-25。
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages_message_id.delete.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages_message_id.delete.html
- 媒体接口核实日期：2026-10-25；官方页面标注更新于 2026-10-09。
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_files.post.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_files.post.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_id_upload_prepare.post.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_id_upload_prepare.post.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_id_upload_part_finish.post.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_id_upload_part_finish.post.html
- https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html
- https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/api-call-guide.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html
