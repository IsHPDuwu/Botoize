import { useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw, Webhook } from "lucide-react";
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
import { QQ_SWR_KEYS, useQQMyGrants, useQQSubscriptions } from "@/lib/qq-swr";
import { mutate } from "swr";

export function SubscriptionsPage() {
  const grants = useQQMyGrants();
  const { data: subscriptions, error, isLoading, isValidating, mutate: reloadSubscriptions } = useQQSubscriptions();
  const [botId, setBotId] = useState("");
  const [urlDraft, setUrl] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [failure, setFailure] = useState("");
  const eligibleGrants = (grants.data ?? []).filter((grant) => grant.scopes.includes("events:read"));
  const selectedGrant = eligibleGrants.find((grant) => String(grant.bot?.id) === botId);
  const selectedSubscription = subscriptions?.find((item) => String(item.bot) === botId);
  const url = urlDraft || selectedSubscription?.url || "";
  const displayedUrl = url;

  async function save(active: boolean) {
    if (!botId) return;
    setBusy(true); setNotice(""); setFailure("");
    try {
      await management("subscriptions/", { bot: Number(botId), ...(active ? { url: displayedUrl } : {}), is_active: active, password });
      setPassword("");
      setNotice(active ? "订阅已保存；请确保服务端已调度投递任务。" : "订阅已禁用。");
      await reloadSubscriptions();
      await mutate(QQ_SWR_KEYS.deliveries);
    } catch (reason) {
      setFailure(reason instanceof Error ? reason.message : "订阅操作失败");
    } finally {
      setBusy(false);
    }
  }

  if (error && !subscriptions) return <QueryError onRetry={reloadSubscriptions} retrying={isValidating} />;
  return (
    <div className="flex min-h-0 flex-col gap-5 pb-8">
      <PageHeader title="订阅端点" description="每个授权 Bot 可配置一个 HTTPS 回调。授权版本变化后需重新保存。" actions={<Button variant="outline" onClick={() => void Promise.all([reloadSubscriptions(), grants.mutate()])} disabled={isValidating}><RefreshCw className={isValidating ? "animate-spin" : ""} />刷新</Button>} />
      {notice && <p role="status" className="rounded-md border border-success-border bg-success-soft p-3 text-sm text-success-foreground">{notice}</p>}
      {failure && <p role="alert" className="rounded-md border border-error-border bg-error-soft p-3 text-sm text-error-foreground">{failure}</p>}
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><Webhook className="size-4" />HTTP 回调配置</CardTitle><CardDescription>仅公网上的 HTTPS 443 地址；不允许 URL 凭据、fragment 或重定向。</CardDescription></CardHeader><CardContent className="space-y-4"><div className="space-y-2"><Label htmlFor="subscription-bot">Bot</Label><select id="subscription-bot" value={botId} onChange={(event) => { setBotId(event.target.value); setUrl(""); setNotice(""); }} className="flex h-9 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"><option value="">选择具有 events:read 的 Bot</option>{eligibleGrants.map((grant) => grant.bot && <option key={grant.bot.id} value={grant.bot.id}>{grant.bot.name}</option>)}</select></div>{selectedGrant && <div className="flex flex-wrap items-center gap-2"><StatusBadge variant={selectedSubscription?.is_current ? "success" : selectedSubscription?.is_active ? "warning" : "info"}>{selectedSubscription?.is_current ? "当前版本有效" : selectedSubscription?.is_active ? "授权版本已变更" : selectedSubscription ? "已禁用" : "尚未配置"}</StatusBadge><span className="text-xs text-muted-foreground">当前 Grant revision：{selectedGrant.revision}</span></div>}<div className="space-y-2"><Label htmlFor="callback-url">HTTPS 回调地址</Label><Input id="callback-url" type="url" value={displayedUrl} onChange={(event) => setUrl(event.target.value)} disabled={busy || !botId} placeholder="https://example.com/qq/events" /></div><div className="space-y-2"><Label htmlFor="subscription-password">确认当前密码</Label><Input id="subscription-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy} /></div><div className="flex flex-wrap gap-2"><Button variant="primary" disabled={busy || !botId || !url || !password} onClick={() => void save(true)}>{busy ? "处理中…" : "保存订阅"}</Button><Button variant="outline" disabled={busy || !selectedSubscription?.is_active || !password} onClick={() => void save(false)}>禁用订阅</Button></div></CardContent></Card>
      {isLoading && !subscriptions ? <Card><CardContent className="space-y-3 p-6"><Skeleton className="h-5 w-40" /><Skeleton className="h-10 w-full" /></CardContent></Card> : subscriptions?.length ? <Card><CardHeader><CardTitle>已保存订阅</CardTitle><CardDescription>只返回当前账号可访问的回调。</CardDescription></CardHeader><CardContent className="space-y-3">{subscriptions.map((subscription) => <div key={subscription.id} className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-md border p-3"><div className="min-w-0"><p className="truncate text-sm font-medium">Bot #{subscription.bot}</p><p className="truncate text-xs text-muted-foreground">{subscription.url}</p></div><div className="flex items-center gap-2"><StatusBadge variant={subscription.is_current && subscription.is_active ? "success" : subscription.is_active ? "warning" : "info"}>{subscription.is_current && subscription.is_active ? "有效" : subscription.is_active ? "需重存" : "已禁用"}</StatusBadge><span className="text-xs text-muted-foreground">revision {subscription.grant_revision}</span></div></div>)}</CardContent></Card> : <EmptyState icon={<Webhook />} title="尚未配置订阅" description={eligibleGrants.length ? "选择一个 Bot 并填写 HTTPS 回调地址。" : "需要有效的 events:read 授权才能配置订阅。"} action={!eligibleGrants.length ? <Link className="text-sm underline underline-offset-4" to="/dashboard/groups">查看 Bot 授权</Link> : undefined} />}
    </div>
  );
}
