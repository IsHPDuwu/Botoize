import { Activity, CircleHelp, Copy, ExternalLink, Radio, RefreshCw, ShieldCheck, Webhook, Wifi } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBadge } from "@/components/ui/status";
import { checkBackend } from "@/lib/qq-api";
import { Link } from "react-router-dom";

const guideSections = [
  { icon: Webhook, title: "官方 Webhook", state: "支持入站", detail: "官方平台回调写入事件与 Outbox；请为 Bot 配置本平台对应的 Webhook 地址。具体路径由部署入口提供。" },
  { icon: Wifi, title: "原生事件 WebSocket", state: "有限支持", detail: "WebSocket 使用 /relay/v1/ws/，HTTP 历史事件使用 /relay/v1/events/，需要 events:read scope；此功能不是官方 QQ Gateway 长连接。" },
  { icon: Radio, title: "OneBot", state: "部分动作可用", detail: "当前仅实现文档列明的有限动作；未实现的动作返回明确错误，不承诺完整 OneBot 兼容。" },
  { icon: ShieldCheck, title: "管理 API", state: "Session + CSRF", detail: "管理接口使用同源 Session 与 CSRF；数据面接口使用 Bearer Key，并在每次请求校验 BotGrant 与 revision。" },
];

export function SettingsPage() {
  const [backendStatus, setBackendStatus] = useState<"unknown" | "checking" | "connected" | "failed">("unknown");
  const [message, setMessage] = useState("");
  async function check() {
    setBackendStatus("checking"); setMessage("");
    try { await checkBackend(); setBackendStatus("connected"); }
    catch { setBackendStatus("failed"); setMessage("无法连接管理后端，请检查本地开发服务或部署反向代理。"); }
  }
  async function copy(value: string) {
    try { await navigator.clipboard.writeText(value); setMessage("已复制到剪贴板。"); }
    catch { setMessage("复制失败，请手动选择文本。"); }
  }
  const healthPath = `${window.location.origin}/health/`;
  return (
    <div className="flex min-h-0 flex-col gap-5 pb-8">
      <PageHeader title="接入与系统设置" description="部署与协议能力状态。未实现的官方 API 或协议能力会明确标记，不提供空操作。" actions={<Button variant="outline" onClick={() => void check()} disabled={backendStatus === "checking"}><RefreshCw className={backendStatus === "checking" ? "animate-spin" : ""} />检查后端</Button>} />
      {message && <p role="status" className="rounded-md border bg-muted/40 p-3 text-sm text-muted-foreground">{message}</p>}
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><Activity className="size-4" />服务状态</CardTitle><CardDescription>健康检查只表示后端进程响应，不代表 QQ Bot 在线。</CardDescription></CardHeader><CardContent className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-medium">管理后端</p><p className="text-sm text-muted-foreground">{healthPath}</p></div><StatusBadge variant={backendStatus === "connected" ? "success" : backendStatus === "failed" ? "destructive" : "info"}>{backendStatus === "connected" ? "已连接" : backendStatus === "failed" ? "连接失败" : backendStatus === "checking" ? "检查中" : "未检查"}</StatusBadge><Button variant="ghost" size="sm" onClick={() => void copy(healthPath)}><Copy />复制地址</Button></CardContent></Card>
      <section className="grid gap-4 md:grid-cols-2">{guideSections.map(({ icon: Icon, title, state, detail }) => <Card key={title}><CardHeader><div className="flex items-center justify-between gap-3"><CardTitle className="flex items-center gap-2"><Icon className="size-4" />{title}</CardTitle><StatusBadge variant={state === "支持入站" ? "success" : state === "部分动作可用" ? "warning" : "info"}>{state}</StatusBadge></div></CardHeader><CardContent><p className="text-sm text-muted-foreground">{detail}</p></CardContent></Card>)}</section>
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><CircleHelp className="size-4" />后续阅读</CardTitle><CardDescription>当前仓库的协议能力边界和部署说明。</CardDescription></CardHeader><CardContent className="flex flex-wrap gap-3"><Link className="inline-flex items-center gap-1 text-sm underline underline-offset-4" to="/dashboard/api-info">API 接入说明 <ExternalLink className="size-3" /></Link><a className="inline-flex items-center gap-1 text-sm underline underline-offset-4" href="https://bot.q.qq.com/wiki/develop/api-v2/" target="_blank" rel="noreferrer">QQ 官方开发文档 <ExternalLink className="size-3" /></a></CardContent></Card>
    </div>
  );
}
