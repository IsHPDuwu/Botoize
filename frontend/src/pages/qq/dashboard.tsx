import { Activity, AlertTriangle, Bot, CheckCircle2, Clock3, RefreshCw, Server, XCircle } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { QueryError } from "@/components/ui/query-error";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status";
import { useQQAuth } from "@/hooks/use-qq-auth";
import { useQQBots, useQQDeliveries, useQQEvents, useQQOverview } from "@/lib/qq-swr";
import type { DashboardOverview } from "@/lib/qq-api";

const windows = [
  { label: "24 小时", value: 24 },
  { label: "7 天", value: 168 },
  { label: "30 天", value: 720 },
] as const;

function Metric({ label, value, description, icon: Icon }: { label: string; value: string; description: string; icon: typeof Activity }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 border-b p-4 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0">
      <div className="flex items-center gap-2 text-sm text-muted-foreground"><Icon className="size-4" aria-hidden="true" />{label}</div>
      <strong className="font-mono text-2xl font-semibold tabular-nums">{value}</strong>
      <span className="text-xs text-muted-foreground">{description}</span>
    </div>
  );
}

function Metrics({ data }: { data: DashboardOverview }) {
  const success = data.delivered_count + data.failed_count;
  const rate = success > 0 ? `${Math.round((data.delivered_count / success) * 1000) / 10}%` : "—";
  return (
    <Card>
      <CardContent className="grid gap-0 p-0 sm:grid-cols-3">
        <Metric label="活跃 Bot" value={String(data.active_bot_count)} description={`共 ${data.bot_count} 个 Bot`} icon={Bot} />
        <Metric label="窗口内事件" value={String(data.event_count)} description={`${data.window_hours} 小时窗口`} icon={Activity} />
        <Metric label="投递成功率" value={rate} description={`${data.delivered_count} 次已接受`} icon={CheckCircle2} />
        <Metric label="待处理" value={String(data.pending_count + data.processing_count)} description={`${data.pending_count} 待投递 · ${data.processing_count} 处理中`} icon={Clock3} />
        <Metric label="失败投递" value={String(data.failed_count)} description="达到上限后停止重试" icon={AlertTriangle} />
        <Metric label="已取消" value={String(data.cancelled_count)} description="授权或版本失效" icon={XCircle} />
      </CardContent>
    </Card>
  );
}

function RecentActivity() {
  const { data, error, isLoading, isValidating, mutate } = useQQEvents({ revalidateOnFocus: false });
  if (isLoading && !data) return <Card><CardContent className="space-y-3 p-6"><Skeleton className="h-5 w-40" /><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /></CardContent></Card>;
  if (error && !data) return <QueryError onRetry={mutate} retrying={isValidating} />;
  return (
    <Card>
      <CardHeader><CardTitle>近期事件</CardTitle><CardDescription>最近入库的真实 QQ 事件，不代表已经完成下游投递。</CardDescription></CardHeader>
      <CardContent className="space-y-3">
        {!data?.events.length ? <EmptyState variant="inline" icon={<Activity />} title="暂无事件" description="收到官方 Webhook 事件后会显示在这里。" /> : data.events.slice(0, 5).map((event) => (
          <div key={event.id} className="flex min-w-0 items-start justify-between gap-3 rounded-md border p-3">
            <div className="min-w-0"><p className="truncate text-sm font-medium">{event.event_type}</p><p className="truncate text-xs text-muted-foreground">Bot #{event.bot} · {event.event_id}</p></div>
            <time className="shrink-0 text-xs text-muted-foreground" dateTime={event.received_at}>{new Date(event.received_at).toLocaleString()}</time>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function DeliverySummary() {
  const { data, error, isLoading, isValidating, mutate } = useQQDeliveries({ revalidateOnFocus: false });
  if (isLoading && !data) return <Card><CardContent className="space-y-3 p-6"><Skeleton className="h-5 w-40" /><Skeleton className="h-16 w-full" /><Skeleton className="h-16 w-full" /></CardContent></Card>;
  if (error && !data) return <QueryError onRetry={mutate} retrying={isValidating} />;
  const states = data?.deliveries.reduce<Record<string, number>>((result, row) => { result[row.state] = (result[row.state] ?? 0) + 1; return result; }, {}) ?? {};
  return (
    <Card>
      <CardHeader><CardTitle>投递状态</CardTitle><CardDescription>Outbox 当前快照。</CardDescription></CardHeader>
      <CardContent className="grid grid-cols-2 gap-3">
        {[["delivered", "已接受", "success"], ["pending", "待投递", "warning"], ["processing", "处理中", "info"], ["failed", "失败", "destructive"]].map(([state, label, variant]) => <div key={state} className="flex items-center justify-between gap-2 rounded-md border p-3"><span className="text-sm">{label}</span><StatusBadge variant={variant as "success" | "warning" | "info" | "destructive"}>{String(states[state] ?? 0)}</StatusBadge></div>)}
      </CardContent>
    </Card>
  );
}

export function DashboardPage() {
  const { user } = useQQAuth();
  const [windowHours, setWindowHours] = useState(24);
  const { data, error, isLoading, isValidating, mutate } = useQQOverview(windowHours);
  const bots = useQQBots({ revalidateOnFocus: false });
  return (
    <div className="flex min-h-0 flex-col gap-5 pb-8">
      <PageHeader title={`欢迎回来，${user?.username ?? "用户"}`} description="QQ Bot Proxy 的连接、事件流量与投递健康一览" actions={<div className="flex flex-wrap gap-2">{windows.map((item) => <Button key={item.value} size="sm" variant={windowHours === item.value ? "secondary" : "ghost"} onClick={() => setWindowHours(item.value)}>{item.label}</Button>)}<Button size="sm" variant="outline" onClick={() => void mutate()} disabled={isValidating}><RefreshCw className={isValidating ? "animate-spin" : ""} />刷新</Button></div>} />
      {error && !data ? <QueryError onRetry={mutate} retrying={isValidating} /> : isLoading && !data ? <Card><CardContent className="grid gap-4 p-4 sm:grid-cols-3"><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /></CardContent></Card> : data ? <Metrics data={data} /> : <EmptyState icon={<Server />} title="暂无统计数据" description="后端尚未返回当前窗口的统计快照。" />}
      {bots.data && !bots.data.length && <EmptyState icon={<Bot />} title="暂无可访问 Bot" description="Owner 需要先添加 Bot，Admin 需要等待有效授权。" />}
      <section className="grid min-h-0 gap-5 lg:grid-cols-2"><RecentActivity /><DeliverySummary /></section>
      <Card><CardHeader><CardTitle>接入提示</CardTitle><CardDescription>仪表盘只展示真实服务数据，不使用演示指标。</CardDescription></CardHeader><CardContent className="grid gap-3 text-sm text-muted-foreground sm:grid-cols-3"><p>官方 Webhook 事件先入库，再按照授权快照进入 Outbox。</p><p>投递返回 2xx 只代表下游接受，事件可能因重试而重复。</p><p>Bot 在线状态不由管理端健康检查代替，需结合官方连接结果判断。</p></CardContent></Card>
    </div>
  );
}
