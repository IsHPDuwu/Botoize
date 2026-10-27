# OneBot 11 / 12 上游 Provider

更新：2026-10-27。这是 Botoize 连接外部 OneBot 实现的入口；下游连接 Botoize 仍使用原有 `/onebot/v11/`、`/onebot/v12/` 和 Botoize API Key。

OneBot Channel 也可作为另一 Provider 下主机的从机：优先收消息、逐条回退、主机独占发送和管理失败回退，并逐步用真实 ID 替换 OB11 虚拟绑定。群匹配编辑、ID 显示与维护 worker 见 [主从协作](COMPANIONS.md)。

## 配置

平台管理 → 服务提供商 → Channel 中选择 **OneBot 11** 或 **OneBot 12**，每个 Channel 只对应一个 Bot：

| 字段 | 配置 |
| --- | --- |
| `interface_type` | `onebot_v11` / `onebot_v12` |
| `base_url` | HTTP(S) API 基础地址，或 WS(S) **正向通用**地址；可使用端口及路径前缀 |
| `app_id` / Bot ID | 上游 `user_id`；11 填规范十进制字符串，12 保留原始字符串（最多 256 字符） |
| `secret` / Access Token | 上游鉴权令牌，可留空；编辑时省略或留空保留旧值，`clear_secret: true` 显式清除 |
| `event_secret` | 独立 HTTP 上报密钥，省略保留、非空轮换、空字符串关闭；不返回明文 |
| `models` | 已知单聊 `userid` / 群聊 `groupid`，使用上游原始 ID；也会从已认证事件发现 |

接口示例（在已登录 Owner Session + CSRF 下提交）：

```json
{
  "name": "Local OneBot",
  "channels": [{
    "name": "Bot A",
    "interface_type": "onebot_v12",
    "base_url": "http://127.0.0.1:3000",
    "app_id": "self:001",
    "secret": "UPSTREAM_ACCESS_TOKEN",
    "event_secret": "INDEPENDENT_EVENT_SECRET",
    "is_active": true,
    "models": [{"name": "Known group", "isDirect": false, "groupid": "group:001"}]
  }]
}
```

HTTP 11 向 `{base_url}/{action}` POST params；12 向基础地址 POST action / params / echo / self 信封。WS 请求按 echo 关联；一次调用只尝试一次，不在超时后自动重发消息。12 使用 `get_status` 找到唯一匹配 Bot，再用 `get_self_info` 验证身份；同一上游如存在多个平台使用相同 user_id，会拒绝歧义。11 用 `get_login_info` 核对 Bot ID。

只有 Owner 能配置地址和凭据。开发 DEBUG 默认允许本机/内网与 HTTP/WS；生产默认关闭，确需连接本机/LAN 时设置 **`ONEBOT_UPSTREAM_ALLOW_PRIVATE=1`** 并重启服务及 worker。开启表示信任 Owner 配置的网络目的地。禁止 URL 中的用户名、密码、query 和 fragment；每次连接解析并固定地址，不跟随重定向、不读取环境代理，不将上游 token 发送到下载链接。QQ 官方接口的既有代理设置不受影响。

地址校验会区分缺少协议、非法端口、URL 内含凭据 / query、路径限制以及私网 / 明文未启用。Access Token 填独立字段，不附加 `?access_token=...`。例如本地通用 WS 可填 `ws://127.0.0.1:3001`，HTTP API 可填 `http://127.0.0.1:3000`，端口应使用上游实际监听的值。

Bot ID 在当前数据库仍全局唯一，同一 Bot ID 不能重复建 Channel。跨协议切换必须重新输入凭据或显式清空 OneBot token；已有会话 ID 与新协议不兼容时应创建新 Channel。地址/协议变化和凭据轮换会使旧 Key 失效，需要重新授权并创建 Key。

## 接收事件

### 下游客户端的 Self ID

新部署时无需登录服务器查询数据库。Owner 在「服务提供商」展开 Provider，在 Channel 下点击 **获取 / 刷新 ID**，由后端查询该 Channel 上游身份并保存；点击显示的数字即可复制。OneBot 11 客户端使用 **OB11 ID**；OneBot 12 使用 **OB12 ID**，官机的 platform 填 `qq`。官机 AppID、内部 Bot 编号、从机账号都不是主机的下游 Self ID。官机 OB11 是持久数字映射，OB12 是身份接口返回的字符串 ID。迁移部署应保留数据库，否则无法保留既有数字映射。

对应管理接口为 `POST /api/v1/channels/CHANNEL_ID/identity/`，空 JSON 正文，要求 Owner Session + CSRF；返回 `onebot11` / `onebot12`，不返回凭据。查询失败时保留旧 ID，可检查凭据、网络与 QQ IP 白名单后重试。客户端也能用该 Channel 的 Key 调用 OB11 `get_login_info` / OB12 `get_self_info` 获取身份。

二选一，也可同时启用（相同事件会去重）：

1. **正向 WS worker**：在 backend 运行：

   ```powershell
   uv run --locked python manage.py run_onebot_upstream --bot INTERNAL_BOT_ID
   ```

   WS base URL 直接作为正向通用连接；HTTP 11 自动换成相同地址的 `ws(s)://…/event`，HTTP 12 换成相同地址根路径的 WS。如果实现的 HTTP 和 WS 端口不同，请使用其正向通用 WS 地址作为 base URL，或用 HTTP 上报。每 Bot 只有一个有效 fencing 租约；配置变更/停用停止旧 worker，断线有限退避重连。上游应自行启用事件 WS；仅启动 Botoize ASGI 不会启动此 worker。

2. **HTTP 上报**：配置 `event_secret` 后，将上游事件上报到 **`/webhooks/onebot/INTERNAL_BOT_ID/`**。
   - 11：`X-Signature: sha1=<HMAC-SHA1(event_secret, 原始正文)>`。
   - 12：`Authorization: Bearer <event_secret>`。
   - 必须匹配 Channel Bot 身份；完整 JSON 正文最多 12 MiB；认证和持久化成功后返回 204。不执行 HTTP 快速操作，不接受无密钥上报。

11 无通用 event ID，按配置来源 + 规范事件内容去重；12 按来源 + 原始 event ID 去重。WS 不提供持久 resume/补漏保证，断线期间的事件补发能力取决于上游。事件进入现有日志、会话发现、事件流、轮询和订阅投递，沿用授权链/revision/scope/会话检查。上游 `meta` 不作为用户事件分发；系统仪表盘显示 worker 租约和 WS 连接快照，不能据此保证 Bot 实时在线。

## 动作与版本边界

| 类别 | 11 上游 | 12 上游 |
| --- | --- | --- |
| 身份 / 状态 | `get_login_info`、`get_status` | `get_status`、`get_self_info`，只暴露配置 Bot |
| 发送 / 撤回 / 已保存消息 | 单聊/群聊发送、`delete_msg`、本地 `get_msg` | `send_message`（单聊/群聊/频道）、`delete_message` |
| 用户 / 好友 | 陌生人资料、好友列表、点赞 | 用户资料、好友列表 |
| 群 / 成员 | 列表、群资料、成员资料/列表、荣誉 | 标准列表、群资料、成员资料/列表 |
| 群管理 | 踢人、禁言、全员禁言、管理员、匿名开关、群名片/群名/头衔、退群、好友/群申请审批 | 标准改群名、退群 |
| 频道 | 无标准映射 | 标准 guild/channel 资料、列表、成员、改名、离开 |
| 文件 | Key 独有本地缓存；发送图片/语音/视频使用 Base64；无标准 file 消息段 | Key 独有缓存、标准上传/读取/分片，发送时换成上游 file_id |

这些是桥接实现范围，上游仍可能缺少动作或权限并明确返回错误；不转发任意 action，不暴露 Cookie、CSRF、凭据查询、进程重启、上游服务器路径。好友查询/点赞/好友审批分别要求新 scope `friends:read`、`friends:write`、`friend-requests:write`；旧 Key 不自动增加。

两版下游可连接任一版上游。同版本优先保留语义：11→11 使用原生数值 ID；下游 12 保留字符串；12→11 使用持久数值映射。跨版本仅转换已登记动作/消息段，无法转换的 notice/request 使用明确的 `botoize.onebot11_event` / `botoize.onebot12_event` 扩展，不编造标准事件；频道无法表示为 11 消息。支持 text、mention/all、face、image、voice/record、video、reply，12 另有 file；不认识的发送段拒绝，扩展能否发送仍由上游决定。

列表按完整授权链和 Key 会话范围过滤。频道操作要求全会话授权。引用/读取/撤回只使用当前来源、已保存且当前账号有权访问的消息；撤回仅允许通过本账号发送的消息。11 请求 flag 替换为本地授权事件句柄，不能传原始 flag 绕过检查。文件受现有 8 MiB/文件、64 MiB/Key、24 小时缓存及 URL 下载策略约束；11 附件若上游没有提供可安全读取的内容则明确拒绝，不读取本机或上游文件系统。

## 本地验证

`core/test_onebot_upstream.py` 使用临时 HTTP 和 WS 服务检查两版真实请求、鉴权、身份、发送、媒体、撤回、跨版 ID、上报去重、会话过滤、来源隔离、worker 租约和未知结果不重试。无真实 QQ 消息或群管理副作用。真实第三方 OneBot 实现和公网接收端尚需使用其配置联调；本任务未测试 PostgreSQL。

规范参考：[OneBot 11](https://github.com/botuniverse/onebot-11)、[OneBot 12](https://12.onebot.dev/)。
