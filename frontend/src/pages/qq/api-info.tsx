import { ArrowRight, Copy, ExternalLink, KeyRound, Radio, ShieldCheck, Webhook, Wifi } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";

const scopes = [
  ["events:read", "读取已授权 Bot 的事件并使用原生事件流。"],
  ["messages:send", "执行当前已登记的消息发送操作。"],
  ["messages:delete", "撤回消息的独立敏感权限；群管理员 Bot 可能撤回普通群成员消息。"],
  ["query:read", "执行当前已登记的官方查询操作。"],
  ["media:upload", "仅对已实现的媒体动作生效；scope 不代表所有媒体接口均可用。"],
];

export function ApiInfoPage() {
  const base = window.location.origin;
  async function copy(value: string) { await navigator.clipboard.writeText(value); }
  return (
    <div className="flex min-h-0 flex-col gap-5 pb-8">
      <PageHeader title="API 接入说明" description="QQ 官方机器人中转的数据面入口和授权要求。" />
      <Card><CardHeader><CardTitle>接入流程</CardTitle><CardDescription>从管理端创建单 Bot Key，再把 Key 配置到你的下游服务。</CardDescription></CardHeader><CardContent className="grid gap-3 md:grid-cols-4">{[["01", "创建授权", "/dashboard/groups"], ["02", "生成令牌", "/dashboard/tokens"], ["03", "配置下游", "/dashboard/admin-settings"], ["04", "检查事件", "/dashboard/logs"]].map(([number, title, href]) => <Link key={number} to={href} className="flex items-center gap-3 rounded-md border p-3 transition-colors hover:bg-accent"><span className="font-mono text-sm text-muted-foreground">{number}</span><span className="min-w-0 flex-1 text-sm font-medium">{title}</span><ArrowRight className="size-4 text-muted-foreground" /></Link>)}</CardContent></Card>
      <section className="grid gap-4 md:grid-cols-2"><Card><CardHeader><CardTitle className="flex items-center gap-2"><Webhook className="size-4" />官方 Webhook</CardTitle><CardDescription>QQ 官方平台向部署入口发送机器人事件。</CardDescription></CardHeader><CardContent className="space-y-3 text-sm text-muted-foreground"><p>Webhooks 按 Bot 绑定，接收到的有效事件先持久化，再生成当前授权快照对应的投递任务。</p><p>本地健康检查和 Webhook 响应都不能证明机器人已建立 Gateway 长连接。</p></CardContent></Card><Card><CardHeader><CardTitle className="flex items-center gap-2"><Wifi className="size-4" />原生事件 WebSocket</CardTitle><CardDescription>有限的下游事件流，不是 QQ 官方 Gateway。</CardDescription></CardHeader><CardContent className="space-y-3 text-sm text-muted-foreground"><p>HTTP 事件读取：<code className="rounded bg-muted px-1">{base}/relay/v1/events/</code></p><p>WebSocket 事件流：<code className="rounded bg-muted px-1">{base.replace(/^http/, "ws")}/relay/v1/ws/</code></p><p>要求有效 Bearer Key 和 events:read scope；撤权会终止后续批次发送。</p></CardContent></Card></section>
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className="size-4" />Bearer 身份验证</CardTitle><CardDescription>令牌可由所属账号在令牌管理中复制；不要放进 URL 或公开日志。</CardDescription></CardHeader><CardContent className="space-y-3"><pre className="overflow-x-auto rounded-md bg-muted p-4 text-sm"><code>{`Authorization: Bearer <YOUR_API_KEY>`}</code></pre><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => void copy("Authorization: Bearer ")}><Copy />复制头部模板</Button><Link to="/dashboard/tokens"><Button variant="ghost" size="sm">管理令牌 <ArrowRight /></Button></Link></div></CardContent></Card>
      <Card><CardHeader><CardTitle>Koishi QQ 适配器配置</CardTitle><CardDescription>以 @koishijs/plugin-adapter-qq 4.14.0（@satorijs/adapter-qq 4.14.0）为例。原版不是 Botoize 下游适配器。</CardDescription></CardHeader><CardContent className="space-y-4 text-sm">
        <p className="text-muted-foreground">你说的 koishi-plugin-adapter-qq 对应官方包 @koishijs/plugin-adapter-qq。以下是直连 QQ 的字段说明，不是将代理 Key 填入 AppSecret 的接入方案。</p>
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b"><th className="py-2 pr-4">config 字段</th><th>如何填写</th></tr></thead><tbody>{[
          ['id', 'QQ 开放平台的 AppID；不是 Channel ID / Bot 数据库 ID。'],
          ['secret', '官方 AppSecret；不能填 qqp_ 开头的 Botoize API Key。'],
          ['type', 'public 或 private，按 QQ 平台的公域 / 私域应用类型填写，不是群聊 / 私聊。'],
          ['sandbox', '正式环境 false；沙箱应用 true。'],
          ['endpoint', '正式官方 HTTP 地址 https://api.bot.qq.com/。修改它只影响 HTTP，不会适配认证和事件协议。'],
          ['protocol', 'websocket 或 webhook，按原版适配器对接官方 Gateway / Webhook。'],
          ['intents', '所需事件的位掩码；群 @消息为 33554432，仍需 QQ 平台权限。'],
          ['gatewayUrl', '可选，官方 Gateway WSS 地址覆盖；不要填 /relay/v1/ws/。'],
        ].map(([field,detail]) => <tr key={field} className="border-b last:border-0"><td className="py-2 pr-4 align-top font-mono">{field}</td><td className="py-2 text-muted-foreground">{detail}</td></tr>)}</tbody></table></div>
        <pre className="overflow-x-auto rounded-md bg-muted p-4 text-xs"><code>{`# Koishi koishi.yml：仅示例直连官方 QQ，不经过 Botoize
plugins:
  adapter-qq:
    id: 'YOUR_QQ_APP_ID'
    secret: 'YOUR_OFFICIAL_APP_SECRET'
    type: public
    sandbox: false
    endpoint: https://api.bot.qq.com/
    protocol: websocket
    intents: 33554432`}</code></pre>
        <p className="text-muted-foreground">为什么不能只改 endpoint：原版会向固定的 bots.qq.com 换取官方 token，并设置 QQBot Authorization；Botoize 要求 Bearer API Key。其 WebSocket 使用官方 HELLO / Identify / Resume，Botoize 原生下游使用事件流协议；原版 Webhook 的 Ed25519 验签也不兼容本项目的 HMAC 回调。三者不能混填。</p>
        <p className="text-muted-foreground">接 Botoize 时，需要支持 Bearer 认证和本项目事件协议的桥接插件，或使用文档所列的 OneBot 有限子集。本项目目前没有发布可直接替换该原版插件的 Koishi 桥接包，不能靠配置实现完整兼容。</p>
        <p className="text-muted-foreground">也已核对 koishi-plugin-adapter-qq-crack 1.0.31：endpoint 用于业务 HTTP 和 Gateway 发现，但换 token 地址仍固定为 bots.qq.com；HTTP 仍用 QQBot 认证，WS 仍用官方协议，不能仅修改 endpoint / gatewayUrl 接入当前 Botoize。该版本还默认向第三方 userInfoApi 查询 AppID/OpenID，请评估数据流向。</p>
        <pre className="overflow-x-auto rounded-md bg-muted p-4 text-xs"><code>{`// 可用的 Botoize HTTP 示例（不是 Koishi adapter-qq 配置）
const response = await fetch('${base}/qq/users/@me', {
  headers: { Authorization: 'Bearer YOUR_BOTOIZE_API_KEY' },
});
if (!response.ok) throw new Error('HTTP ' + response.status);
console.log(await response.json());
// Key 需要 query:read；事件读取另需 events:read。`}</code></pre>
      </CardContent></Card>
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4" />授权 scope</CardTitle><CardDescription>Key 的有效 scope 是 BotGrant scope 的子集。</CardDescription></CardHeader><CardContent className="divide-y">{scopes.map(([scope, detail]) => <div key={scope} className="flex flex-wrap justify-between gap-2 py-3"><code className="text-sm font-medium">{scope}</code><span className="max-w-2xl text-sm text-muted-foreground">{detail}</span></div>)}</CardContent></Card>
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><Radio className="size-4" />能力边界</CardTitle><CardDescription>当前代理并非全量官方 API 或 OneBot 实现。</CardDescription></CardHeader><CardContent className="space-y-2 text-sm text-muted-foreground"><p>未知或尚未实现的官方路径明确返回 501；不要按成功发送处理。</p><p>HTTPS 下游回调仅允许公网上的 HTTPS 443，验证 DNS 和 TLS，不跟随重定向。</p><p>回调可能重复投递，请按投递 ID 做幂等处理。具体范围请查看仓库的 PROXY_SUPPORT.md 和 WEBHOOK_STATUS.md。</p><a className="inline-flex items-center gap-1 text-foreground underline underline-offset-4" href="https://bot.q.qq.com/wiki/develop/api-v2/" target="_blank" rel="noreferrer">QQ 官方开发者文档 <ExternalLink className="size-3" /></a></CardContent></Card>
    </div>
  );
}
