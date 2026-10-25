# Koishi QQ 适配器兼容性核对

核对日期：2026-10-25。只下载 npm 发布包读取源码和编译产物，没有安装、执行插件，没有读取旧 QQ 官方 SDK，没有使用真实凭据运行第三方插件。

## 当前结论

- `@koishijs/plugin-adapter-qq@4.14.0` 转出 `@satorijs/adapter-qq@4.14.0`。
- `koishi-plugin-adapter-qq-crack@1.0.31` 同样不支持仅修改 endpoint 后连接当前 Botoize。
- 两者的 endpoint 用于业务 HTTP；换 token 地址仍硬编码为 `https://bots.qq.com/app/getAppAccessToken`，请求体使用 `appId`、`clientSecret`。
- 两者将业务 HTTP 的 Authorization 设置成 `QQBot <官方 access_token>`；当前 Botoize 使用 `Bearer <平台 API Key>`。
- WebSocket 都使用官方 HELLO、Identify、Resume 与 heartbeat，不是 `/relay/v1/ws/` 的下游协议。`gatewayUrl` 只是覆盖地址，不转换协议。
- crack 未设置 gatewayUrl 时从 endpoint 请求 `/gateway`，并将返回 WSS URL 的 host 替换为 endpoint 的 host，保留原 WSS path。设置 gatewayUrl 则直接使用，但仍会先准备官方 token。
- Webhook 使用官方 Ed25519 验签，不接受本项目的 HMAC 回调。

因此不能把 qqp_ Key 当成官方 AppSecret，不能把原生事件流地址直接填进 gatewayUrl，也不能声称“换个 endpoint 就能用”。已核对版本之外不作推断。

crack 还默认配置第三方 `userInfoApi=https://oiapi.net/api/Openid`，其 getUser 实现会发送 AppID/OpenID；本次没有执行这类请求。

## Botoize 兼容入口应如何补（设计建议，尚未实现）

### 改动更小的配套插件方案

给 Koishi 加一个版本受控的伴生插件，运行时替换 QQBot 的 `_ensureAccessToken`：仅针对明确配置为 Botoize 的实例，把平台 Key 设置为适配器内部 token，禁止该实例发起官方换 token 请求。原适配器继续输出 `QQBot <平台 Key>`，兼容 HTTP 入口只在自己的路径下接受该格式，并复用现有 authorize / scope / 会话 / 配额检查。配置显式 gatewayUrl 指向新的兼容 WS，避免现有 /gateway 路由缺失及 host/path 替换问题。

这样无需新增 token 交换服务，但仍需兼容 WS 的 HELLO/Identify/READY/heartbeat/Resume 和逐批撤权检查；运行时补丁依赖具体插件版本，必须测试并在卸载时恢复，不能宣称零改动或已实测。没有配套插件时，绝不能把平台 Key 填入 secret（否则会发到官方换 token 地址）。当前尚未实施。

### 若希望正式维护可配置 tokenEndpoint 的方案

1. 插件至少需允许配置 tokenEndpoint，或增加明确的 Botoize 模式，因为后端无法让写死的 bots.qq.com 自动请求本地服务。不能用 DNS/TLS 劫持规避这个事实。
2. 新增独立兼容 token 交换入口：校验平台 API Key、绑定 Bot AppID、有效授权和 scope，返回短期平台兼容 token（字段 access_token / expires_in）。不向下游返回官方 token / AppSecret。
3. 兼容 HTTP 入口接受 `QQBot <平台兼容 token>`，内部重新验证当前 Key、用户、Grant revision、scope、会话和配额，再复用现有官方代理。不得将任意官方 token 当作平台身份，也不得以 AppID 代替用户授权。
4. 兼容 `/gateway` 和独立 WebSocket 实现官方协议外观：HELLO / Identify / READY / heartbeat ACK / Resume；底层仍读取已有持久事件流，每批重新鉴权、去重、按授权过滤，会话和序号绑定具体 Key，不创建额外官方上游连接。
5. 首期限定 WebSocket。官方格式下游 Webhook 需要单独的虚拟凭据与 Ed25519 签名设计，不能直接复用当前 HMAC 回调或绕过验签。
6. 验证身份初始化、群聊/私聊、媒体、断线重连、事件去重、修改 scope、撤权断连、跨 Bot/跨用户拒绝后，才可发布可直接填写的兼容配置。

现有 Bearer / relay / OneBot 契约保持不变。当前只完成兼容性调查，尚未实施上述新兼容协议。

来源：

- https://www.npmjs.com/package/@koishijs/plugin-adapter-qq/v/4.14.0
- https://www.npmjs.com/package/@satorijs/adapter-qq/v/4.14.0
- https://www.npmjs.com/package/koishi-plugin-adapter-qq-crack/v/1.0.31
- https://github.com/koishi-shangxue-plugins/koishi-plugin-adapter-qq-crack

定位：crack 发布包 `src/config.ts`（endpoint/gatewayUrl）、`src/bot/index.ts`（_ensureAccessToken / prepareRequestAuthorization / getWebSocketToken）、`src/ws.ts`（prepare / accept）、`src/http.ts`（官方签名）。编译产物 lib/index.js 中同样存在硬编码换 token 地址和 QQBot 认证逻辑。
