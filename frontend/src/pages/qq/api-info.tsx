import { ArrowRight, Copy, ExternalLink, KeyRound, Radio, ShieldCheck, Webhook, Wifi } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";

const scopes = [
  ["events:read", "读取已授权 Bot 的事件并使用原生事件流。"],
  ["messages:send", "执行当前已登记的消息发送操作。"],
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
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className="size-4" />Bearer 身份验证</CardTitle><CardDescription>令牌只在创建响应中返回一次；不要把它放进 URL 或公开日志。</CardDescription></CardHeader><CardContent className="space-y-3"><pre className="overflow-x-auto rounded-md bg-muted p-4 text-sm"><code>{`Authorization: Bearer <YOUR_API_KEY>`}</code></pre><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => void copy("Authorization: Bearer ")}><Copy />复制头部模板</Button><Link to="/dashboard/tokens"><Button variant="ghost" size="sm">管理令牌 <ArrowRight /></Button></Link></div></CardContent></Card>
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4" />授权 scope</CardTitle><CardDescription>Key 的有效 scope 是 BotGrant scope 的子集。</CardDescription></CardHeader><CardContent className="divide-y">{scopes.map(([scope, detail]) => <div key={scope} className="flex flex-wrap justify-between gap-2 py-3"><code className="text-sm font-medium">{scope}</code><span className="max-w-2xl text-sm text-muted-foreground">{detail}</span></div>)}</CardContent></Card>
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><Radio className="size-4" />能力边界</CardTitle><CardDescription>当前代理并非全量官方 API 或 OneBot 实现。</CardDescription></CardHeader><CardContent className="space-y-2 text-sm text-muted-foreground"><p>未知或尚未实现的官方路径明确返回 501；不要按成功发送处理。</p><p>HTTPS 下游回调仅允许公网上的 HTTPS 443，验证 DNS 和 TLS，不跟随重定向。</p><p>回调可能重复投递，请按投递 ID 做幂等处理。具体范围请查看仓库的 PROXY_SUPPORT.md 和 WEBHOOK_STATUS.md。</p><a className="inline-flex items-center gap-1 text-foreground underline underline-offset-4" href="https://bot.q.qq.com/wiki/develop/api-v2/" target="_blank" rel="noreferrer">QQ 官方开发者文档 <ExternalLink className="size-3" /></a></CardContent></Card>
    </div>
  );
}
