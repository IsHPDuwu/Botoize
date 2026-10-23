# Webhook 实现状态

`core/webhook_crypto.py` 已实现官方 Bot Secret 重复并截取 32 字节的 Ed25519 密钥派生、原始 `timestamp + body` 字节验签，以及回调地址验证签名。

验证证据：官方公钥向量和回调地址挑战签名向量匹配；本地签名往返、正文篡改、错误密钥、签名格式、过期与未来时间戳测试通过。默认正负 300 秒时间窗为本平台策略，不是官方协议保证，也不能替代事件去重。

已知待核对：签名文档提供的事件 body/签名示例未能按展示的原始字节验证，不能声称该事件签名向量已通过。需真实官方回调联调确认。

目前仅密码学基础模块，尚未开放 Webhook HTTP 接收地址；事件持久化、事务 Outbox、去重、投递及成功确认都未实现，不应配置为生产回调地址。

来源：
- https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html
- https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/webhook.html