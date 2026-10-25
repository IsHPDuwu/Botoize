# 官方代理当前支持范围

上游固定为 `https://api.bot.qq.com`，下游使用 `Authorization: Bearer <API Key>`；平台在服务端替换为官方凭证。

| 下游接口 | 所需权限 |
| --- | --- |
| `GET /qq/users/@me` | `query:read` |
| `POST /qq/v2/users/{user_openid}/messages` | `messages:send` |
| `POST /qq/v2/groups/{group_openid}/messages` | `messages:send` |

消息请求仅接受 JSON 对象，正文最大 1 MiB，原始字节透传，不添加或递增 `msg_seq`。OpenID 当前接受字母、数字、下划线及短横线，长度 1–128。未登记路径返回 501。官方响应正文最大 64 KiB。

保留官方 HTTP 状态、响应正文以及 Content-Type、X-Tps-trace-ID、Retry-After。201/202 不代表最终消息送达；仍须处理官方异步审核语义。禁止自动重定向，不自动重试消息。平台返回 `official_outcome_unknown` 时无法确定发送结果，调用方不得盲目重发。

权限仍受当前账号、Bot、显式 BotGrant、授权版本及 Key 范围限制。Owner 身份不自动扩大数据面权限。

## 可选发送幂等扩展

官方消息 POST 可附带 `Idempotency-Key`（1–128 个 ASCII 字母、数字或 `._:-`）。
作用域为用户与 Bot，跨 API Key 共享；同一键必须具有完全一致的路径、查询和请求正文原始字节。
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

## OneBot 11 HTTP 子集

使用相同 Bearer Key，可 POST `/onebot/`，JSON 为 action、params、可选 echo；
也可 POST `/onebot/{action}`，JSON 直接是 params。响应为 status、retcode、data、message、echo。

| action | 权限 | params / 结果 |
| --- | --- | --- |
| get_login_info | query:read | 空 params；结果 user_id（官方 ID 字符串）、nickname |
| send_private_msg | messages:send | user_id（官方 OpenID 字符串）、message（纯文本） |
| send_group_msg | messages:send | group_id（官方 OpenID 字符串）、message（纯文本） |

发送支持显式 msg_id、msg_seq 官方扩展，不自动产生回复上下文；可传 auto_escape=true。
不接受 QQ 数字号、CQ 码或消息段数组，不提供数字 ID 映射，因此不是完整 OneBot 兼容实现。
成功发送的 data.message_id 为官方返回 ID；缺少 ID、网络失败或结果无法解析返回 1502，
不能盲目重发。1400 表示参数错误，1403 为缺权限，1404 为动作不支持，1500 为官方非 2xx。
官方接受响应也不保证业务消息最终送达。

目前未实现：上传、撤回、频道消息、官方 Gateway 上游 WS、OneBot 事件转换/WS、
异步审核跟踪。数据面调用已持久化 request_id、路由模板、状态和耗时，应用已提供按 Key/Admin/Bot 共享的数据库限流；
下游回调另提供 HMAC 签名、投递历史和受权人工重放。当前官方请求测试使用模拟上游，
未完成真实官方账号联调；不可据此视为可生产部署。

核对来源：
- https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html
- https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/api-call-guide.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html