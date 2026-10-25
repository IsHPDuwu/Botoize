import { Bot, Plus, RefreshCw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/ui/page-header";
import { QueryError } from "@/components/ui/query-error";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status";
import { management } from "@/lib/qq-api";
import { useQQBots, useQQMyGrants } from "@/lib/qq-swr";
import { useQQAuth } from "@/hooks/use-qq-auth";

export function ProvidersPage() {
  const { user } = useQQAuth();
  const { data: bots, error, isLoading, isValidating, mutate: reloadBots } = useQQBots();
  const grants = useQQMyGrants();
  const [name, setName] = useState("");
  const [appId, setAppId] = useState("");
  const [secret, setSecret] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function createBot(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setMessage("");
    try {
      await management("bots/", { name, app_id: appId, secret, password });
      setName(""); setAppId(""); setSecret(""); setPassword("");
      await reloadBots();
      setMessage("Bot 已添加。官方 Secret 不会再次返回。");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "添加 Bot 失败"); }
    finally { setBusy(false); }
  }

  if (error && !bots) return <QueryError onRetry={reloadBots} retrying={isValidating} />;
  return (
    <div className="flex min-h-0 flex-col gap-5 pb-8">
      <PageHeader title="服务提供商" description="管理 QQ 官方机器人。这里的服务提供商代表本项目托管的 Bot，不代表官方 Gateway 长连接。" actions={<Button variant="outline" onClick={() => void reloadBots()} disabled={isValidating}><RefreshCw className={isValidating ? "animate-spin" : ""} />刷新</Button>} />
      {message && <p role="status" className="rounded-md border bg-muted/40 p-3 text-sm text-muted-foreground">{message}</p>}
      {user?.role === "Owner" && <Card><CardHeader><CardTitle className="flex items-center gap-2"><Plus className="size-4" />添加官方 Bot</CardTitle><CardDescription>Secret 仅用于服务端加密保存，不会进入列表或浏览器缓存。</CardDescription></CardHeader><CardContent><form onSubmit={createBot} className="grid gap-4 sm:grid-cols-2"><div className="space-y-2"><Label htmlFor="bot-name">Bot 名称</Label><Input id="bot-name" value={name} onChange={(event) => setName(event.target.value)} required maxLength={120} /></div><div className="space-y-2"><Label htmlFor="bot-app-id">AppID</Label><Input id="bot-app-id" value={appId} onChange={(event) => setAppId(event.target.value)} required maxLength={100} /></div><div className="space-y-2"><Label htmlFor="bot-secret">AppSecret</Label><Input id="bot-secret" type="password" autoComplete="off" value={secret} onChange={(event) => setSecret(event.target.value)} required /></div><div className="space-y-2"><Label htmlFor="bot-password">确认当前密码</Label><Input id="bot-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></div><div className="sm:col-span-2"><Button variant="primary" type="submit" disabled={busy}>{busy ? "添加中…" : "添加 Bot"}</Button></div></form></CardContent></Card>}
      {isLoading && !bots ? <div className="grid gap-4 sm:grid-cols-2"><Skeleton className="h-40" /><Skeleton className="h-40" /></div> : bots?.length ? <div className="grid gap-4 sm:grid-cols-2">{bots.map((bot) => { const grant = grants.data?.find((item) => item.bot?.id === bot.id); return <Card key={bot.id}><CardHeader><div className="flex items-start justify-between gap-3"><div className="flex min-w-0 items-center gap-3"><span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted"><Bot className="size-5" /></span><div className="min-w-0"><CardTitle className="truncate">{bot.name}</CardTitle><CardDescription className="truncate">AppID：{bot.app_id}</CardDescription></div></div><StatusBadge variant={bot.is_active ? "success" : "warning"}>{bot.is_active ? "已启用" : "已停用"}</StatusBadge></div></CardHeader><CardContent className="space-y-2 text-sm text-muted-foreground"><p className="flex items-center gap-2"><ShieldCheck className="size-4" />{grant ? `当前授权版本 ${grant.revision}` : "当前账号暂无显式授权"}</p><p>能力与在线状态以服务端实际返回为准。</p></CardContent></Card>})}</div> : <EmptyState icon={<Bot />} title="暂无可访问 Bot" description={user?.role === "Owner" ? "添加第一个 QQ 官方机器人后，它会出现在这里。" : "等待 Owner 为当前账号分配有效 Bot 授权。"} />}
    </div>
  );
}
