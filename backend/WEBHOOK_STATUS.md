# Webhook 实现状态

`core/webhook_crypto.py` 已实现官方 Bot Secret 重复并截取 32 字节的 Ed25519 密钥派生、原始 `timestamp + body` 字节验签，以及回调地址验证签名。

验证证据：官方公钥向量和回调地址挑战签名向量匹配；本地签名往返、正文篡改、错误密钥、签名格式、过期与未来时间戳测试通过。默认正负 300 秒时间窗为本平台策略，不是官方协议保证，也不能替代事件去重。

已知待核对：签名文档提供的事件 body/签名示例未能按展示的原始字节验证，不能声称该事件签名向量已通过。需真实官方回调联调确认。

接收地址为 `POST /webhooks/qq/<Bot数据库ID>/`。部署时需应用全部当前数据库迁移。请求必须携带与该 Bot 一致的 `X-Bot-Appid`。

`op=13` 仅进行官方地址挑战签名，不创建事件；按官方初次验证示例允许不带签名头。其他请求必须通过 `X-Signature-Timestamp`、`X-Signature-Ed25519` 验签，按原始正文验证，正文上限 1 MiB。

普通事件必须提供稳定的顶层 `id` 和事件类型 `t`，仅支持 `op=0`。事件与授权版本快照 Outbox 同事务持久化，按 Bot 与事件 ID 去重；事务完成后返回 `{"op":12}`。重复事件不扩大历史接收者集合。数据库失败不返回成功。

下游可通过 `GET /relay/v1/events/?after=0&limit=50` 主动拉取，使用 Bearer Key 且需要 `events:read`。`after` 为字符串游标，`limit` 为 1–100。返回 `events`（每项含 cursor、原始 payload、received_at）、next_cursor 和 has_more。游标应在业务处理成功后由调用方保存；重用游标会重复返回事件，不自动标记投递完成。

查询仅允许当前用户、Key 绑定 Bot、入库授权快照及同一授权版本的事件。新授权用户不会获得历史快照；授权版本变化后新建的 Key 也不会读取旧版本事件。同版本后来新建的 Key 可以读取该用户该 Bot 的既有快照。客户端须自行保证处理幂等。

控制台 `scan_outbox --after 0 --limit 100` 可有界扫描 pending 快照，重新检查账号、Bot、授权状态、权限和版本；失效项标记 cancelled，不会因重新授权复活。返回 next_cursor、scanned、cancelled、ready（Outbox ID）。有效项仍保留 pending，可重复扫描；ready 仅是扫描时的判断，不是工作租约，也不是发送授权，未来发送前必须再次鉴权。扫描游标到达末尾后应从 0 开始下一轮。

Outbox 现有内部租约原语：`claim_outbox` 使用条件更新领取 pending 或过期 processing 项，生成独立租约令牌；`validate_lease` 在发送前重新校验授权；`finish_outbox` 拒绝过期令牌确认，成功后标记 delivered，失败后指数退避（最多一小时）。领取及失败确认都执行尝试预算，默认最多领取五次；工作进程连续崩溃导致租约过期，也会在下一次领取检查时转为 failed，不会无限回收。网络投递命令已接入这些原语，每次领取创建 `DeliveryAttempt`，保存 generation、尝试序号、状态、HTTP status、固定错误类别和时间。租约不保证网络层 exactly-once；发送中撤权及发送成功但确认前崩溃仍有竞态，下游必须支持事件去重。测试覆盖顺序竞争与过期租约恢复，尚未完成真实多进程数据库压力测试。

订阅配置可通过服务器控制台和 `/api/v1/subscriptions/` 管理。每个授权最多一个订阅，记录当前授权版本并写审计。API 可提交 32–256 字符的 `callback_secret`，将同一随机秘密安全配置到接收端；平台使用 Fernet 加密保存且不回传。省略该字段时保留已有密钥；首次创建时省略则生成内部随机密钥，需另行提交已知秘密后接收端才能验签。授权版本变化后旧订阅不再有效，须明确重新配置。地址只允许 HTTPS 默认端口或 443，拒绝内嵌凭据、片段及空白字符。保存配置不发起网络请求；实际发送会校验解析 IP、阻止私网/保留地址、固定连接目标并禁用重定向。

现已提供 `deliver_outbox --limit 20` 有限批次投递命令；须由外部调度器重复执行。仅领取具有当前有效订阅版本的快照，不消耗未订阅快照的尝试次数。每次发送前校验授权，采用固定公共 IP 的 HTTPS 连接并验证原域名证书，不跟随重定向。回调使用紧凑 UTF-8 JSON、稳定的 `X-QQ-Proxy-Delivery-ID`、`X-QQ-Proxy-Timestamp` 和 `X-QQ-Proxy-Signature: v1=<hex>`；签名计算为 `HMAC-SHA256(secret, timestamp + "." + delivery_id + "." + exact_body_bytes)`。2xx 确认后标记 delivered，其余进入退避。

管理 API `/api/v1/subscriptions/` 已接入订阅页面；`/api/v1/deliveries/` 提供实际投递状态，`/api/v1/deliveries/{id}/attempts/` 查看历史，`/api/v1/deliveries/{id}/replay/` 执行受权重放。下游 WS 事件流见 `PROXY_SUPPORT.md`。详细运行与外部验收见 `DEPLOYMENT.md`。真实官方联调与 PostgreSQL 压测仍未完成。默认时间窗可能拒绝官方长延迟重试，生产策略需联调确定。当前不应视为可生产部署。

来源：
- https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html
- https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/webhook.html