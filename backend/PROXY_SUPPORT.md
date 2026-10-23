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

目前未实现：上传、撤回、频道消息、事件接收、异步审核跟踪、调用持久化审计、共享限流、WebSocket、OneBot。当前测试使用模拟上游，未完成真实官方账号联调；不可据此视为可生产部署。

核对来源：
- https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html
- https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/api-call-guide.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html
- https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html