import { Eye, RefreshCw, ScrollText, Truck } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { QueryError } from "@/components/ui/query-error";
import { StatusBadge } from "@/components/ui/status";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useQQDeliveries, useQQEvents } from "@/lib/qq-swr";
import { qqApi } from "@/lib/qq-api";

const stateLabels: Record<string, string> = { pending: "等待投递", processing: "租约处理中", delivered: "回调已接受", failed: "尝试耗尽", cancelled: "授权失效已取消" };
const stateVariants: Record<string, "success" | "warning" | "info" | "destructive"> = { pending: "warning", processing: "info", delivered: "success", failed: "destructive", cancelled: "destructive" };

export function LogsPage() {
  const [tab, setTab] = useState<"events" | "deliveries">("events");
  const events = useQQEvents({ isPaused: () => tab !== "events" });
  const deliveries = useQQDeliveries();
  const activeError = tab === "events" ? events.error : deliveries.error;
  const activeLoading = tab === "events" ? events.isLoading : deliveries.isLoading;
  const activeValidating = tab === "events" ? events.isValidating : deliveries.isValidating;
  const reload = tab === "events" ? events.mutate : deliveries.mutate;
  const [detail, setDetail] = useState<number | null>(null);

  async function nextPage() {
    if (tab === "events" && events.data?.next_before) await events.mutate(await qqApi.events(events.data.next_before));
    if (tab === "deliveries" && deliveries.data?.next_before) await deliveries.mutate(await qqApi.deliveries(deliveries.data.next_before));
  }

  return (
    <div className="flex min-h-0 flex-col gap-5 pb-8">
      <PageHeader title="日志" description="查看事件入库和下游 HTTP 投递状态。原始载荷只在详情中展开。" actions={<Button variant="outline" onClick={() => void reload()} disabled={activeValidating}><RefreshCw className={activeValidating ? "animate-spin" : ""} />刷新</Button>} />
      <div className="flex flex-wrap gap-2"><Button variant={tab === "events" ? "secondary" : "ghost"} onClick={() => setTab("events")}><ScrollText />事件</Button><Button variant={tab === "deliveries" ? "secondary" : "ghost"} onClick={() => setTab("deliveries")}><Truck />投递</Button></div>
      {activeError && <QueryError onRetry={reload} retrying={activeValidating} />}
      <Card>
        <CardHeader><CardTitle>{tab === "events" ? "已入库事件" : "HTTP 投递记录"}</CardTitle><CardDescription>{tab === "events" ? "入库不代表已经投递。" : "2xx 只代表下游接受，投递可能因重试而重复。"}</CardDescription></CardHeader>
        <CardContent>
          {activeLoading ? <div className="space-y-3"><div className="h-10 animate-pulse rounded-md bg-muted"/><div className="h-10 animate-pulse rounded-md bg-muted"/></div> : tab === "events" ? <EventTable events={events.data?.events ?? []} detail={detail} setDetail={setDetail} /> : <DeliveryTable deliveries={deliveries.data?.deliveries ?? []} />}
          {((tab === "events" && !events.data?.events.length) || (tab === "deliveries" && !deliveries.data?.deliveries.length)) && !activeLoading && <EmptyState variant="inline" icon={tab === "events" ? <ScrollText /> : <Truck />} title={tab === "events" ? "暂无事件" : "暂无投递记录"} description="当前账号没有可展示的记录。" />}
          <div className="mt-4 flex justify-end"><Button variant="outline" size="sm" disabled={activeLoading || !(tab === "events" ? events.data?.has_more : deliveries.data?.has_more)} onClick={() => void nextPage()}>更早记录</Button></div>
        </CardContent>
      </Card>
    </div>
  );
}

function EventTable({ events, detail, setDetail }: { events: { id: number; bot: number; event_id: string; event_type: string; received_at: string; payload: unknown }[]; detail: number | null; setDetail: (id: number | null) => void }) {
  return <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>类型</TableHead><TableHead>Bot</TableHead><TableHead>入库时间</TableHead><TableHead className="text-right">详情</TableHead></TableRow></TableHeader><TableBody>{events.map((event) => <TableRow key={event.id}><TableCell><div className="font-medium">{event.event_type}</div><div className="text-xs text-muted-foreground">{event.event_id}</div>{detail === event.id && <pre className="mt-2 max-w-[min(70vw,640px)] whitespace-pre-wrap break-all rounded-md bg-muted p-3 text-xs">{JSON.stringify(event.payload, null, 2)}</pre>}</TableCell><TableCell>#{event.bot}</TableCell><TableCell>{new Date(event.received_at).toLocaleString()}</TableCell><TableCell className="text-right"><Button variant="ghost" size="sm" onClick={() => setDetail(detail === event.id ? null : event.id)}><Eye />{detail === event.id ? "收起" : "查看"}</Button></TableCell></TableRow>)}</TableBody></Table></div>;
}

function DeliveryTable({ deliveries }: { deliveries: { id: number; event_id: string; bot: number; state: string; attempts: number; available_at: string | null; lease_until: string | null }[] }) {
  return <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>ID</TableHead><TableHead>事件</TableHead><TableHead>状态</TableHead><TableHead>尝试次数</TableHead><TableHead>时间</TableHead></TableRow></TableHeader><TableBody>{deliveries.map((row) => <TableRow key={row.id}><TableCell className="font-mono">#{row.id}</TableCell><TableCell><div>Bot #{row.bot}</div><div className="text-xs text-muted-foreground">{row.event_id}</div></TableCell><TableCell><StatusBadge variant={stateVariants[row.state] ?? "info"}>{stateLabels[row.state] ?? row.state}</StatusBadge></TableCell><TableCell>{row.attempts}</TableCell><TableCell className="text-xs text-muted-foreground">{row.available_at ? `可重试：${new Date(row.available_at).toLocaleString()}` : row.lease_until ? `租约至：${new Date(row.lease_until).toLocaleString()}` : "—"}</TableCell></TableRow>)}</TableBody></Table></div>;
}
