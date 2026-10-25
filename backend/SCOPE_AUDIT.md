# 数据面 scope 审计

核对日期：2026-10-25。参考：https://bot.q.qq.com/wiki/develop/api-v2/

这些 scope 是中转平台的本地权限，不是 QQ 官方 OAuth scope，也不是 Gateway intents。
本地允许不能代替 QQ 开放平台授予的能力、事件订阅资格或机器人可见范围。

| 本地 scope | 当前覆盖 |
| --- | --- |
| events:read | 读取、订阅当前有效 BotGrant 对应事件；原生与 OneBot 事件流 |
| query:read | 已接入的 GET /users/@me 和 OneBot get_login_info |
| messages:send | 已登记单聊、群聊、频道、频道私信发送和创建频道私信 |
| messages:delete | 已登记单聊、群聊、频道和频道私信消息撤回 |
| media:upload | 单聊/群聊 files、upload_prepare、upload_part_finish；srv_send_msg=true 另需 messages:send |

## 新增已接入管理路由

路由事实源为 `core/official_routes.py`，逐方法匹配且默认拒绝；请求与响应采用官方格式，不重新定义协议。

- guilds:read：频道详情。
- channels:read / channels:write：子频道列表、详情、创建、修改、删除。
- members:read / members:write：频道成员列表、详情、移除成员。
- roles:read / roles:write：身份组列表、创建、修改、删除、添加/删除身份组成员。
- permissions:read / permissions:write：子频道用户及身份组权限读取、修改。
- schedules:read / schedules:write：日程列表、详情、创建、修改、删除。
- forums:read / forums:write：帖子列表、详情、发表、删除。
- announcements:write：频道/子频道公告创建、删除。
- pins:read / pins:write：精华消息列表、添加、删除。
- audio:control：频道音频控制及上/下麦。
- moderation:write：全员、指定成员及批量成员禁言/解除禁言。
- api-permissions:read / api-permissions:write：官方权限列表及授权链接申请。

新增权限同样受 Key / BotGrant 交集、有效期、共享配额、请求审计约束。Full access 已覆盖新增权限。
旧 Key 不自动升级，需 Owner 授权后由 Admin 重新创建 Key。

登记了 43 个官方管理操作，新增 20 项方法/路径已通过当前官网逐页核实（`scripts/check_official_docs.py`），未读取 SDK。
仍不宣称覆盖官方所有群管理和机器人接口；未核实或未登记的方法/路径保持拒绝。
当前已接入的官方路由有对应权限检查，但不代表覆盖官方全部 API。
官方文档另有机器人、群聊管理、频道管理等能力目录；当前未登记的查询和管理操作仍不支持。
因此存在官方功能覆盖缺口，不能通过增加 scope 名字或 Full access 宣称实现。
后续接入管理类操作时应按实际读写风险新增细粒度 scope，不能统一塞入 query:read。
上游 AccessToken 和 Gateway 建连是服务端内部操作，不向下游暴露凭据权限。

## 会话边界

Provider 为服务提供商，每个 Channel 唯一对应 Bot；Models 是单聊 userid 或群聊 groupid。
Admin 只能在自己的当前授权内转授，子授权绑定父授权 revision，父授权变更或失效后子授权和 Key 失效。
Key 的 scope 和会话取当前授权交集；跨 Bot 会话拒绝。未识别会话的接口对受限 Key 拒绝，身份查询除外。
HTTP/OneBot、媒体、撤回、历史分页、原生/OneBot WS、回调及重放共用会话策略；事件先过滤再分页。
全选当前可见会话与显式“包括未来发现的全部会话”是不同策略，后者不会通过 Full access 自动开启。

## Full access

- Owner 授权界面：选择全部当前已定义数据面 scope。
- Admin 创建 Key：选择当前 BotGrant 内全部 scope，不扩大 Owner 授权。
- 提交和保存仍为显式 scope 数组，不保存 `*` 或自动包含未来新增权限。
- 不授予管理面 Owner 身份，不绕过撤权、有效期、限额或上游权限。
