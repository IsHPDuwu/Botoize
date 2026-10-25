import { Activity, Eye, RefreshCw, ScrollText, Truck } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { QueryError } from "@/components/ui/query-error";
import { StatusBadge } from "@/components/ui/status";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useQQApiCalls, useQQDeliveries, useQQEvents } from "@/lib/qq-swr";
import { qqApi, type ApiCallRecord, type ApiCallFilters, type EventRecord, type DeliveryRecord } from "@/lib/qq-api";
import { RequestId } from './request-id';
import { LogFilters } from './log-filters';

const stateLabels: Record<string, string> = { pending: "等待投递", processing: "租约处理中", delivered: "回调已接受", failed: "尝试耗尽", cancelled: "授权失效已取消" };
const stateVariants: Record<string, "success" | "warning" | "info" | "destructive"> = { pending: "warning", processing: "info", delivered: "success", failed: "destructive", cancelled: "destructive" };

export function LogsPage() {
  const [tab, setTab] = useState<"calls" | "events" | "deliveries">("calls");
  const [before, setBefore] = useState<string>();
  const [filters, setFilters] = useState<ApiCallFilters>();
  const calls = useQQApiCalls(undefined, before, tab === "calls", filters);
  const events = useQQEvents(undefined, tab === "events");
  const deliveries = useQQDeliveries(undefined, tab === "deliveries");
  const active = tab === "calls" ? calls : tab === "events" ? events : deliveries;
  const activeError = active.error;
  const activeLoading = active.isLoading;
  const activeValidating = active.isValidating;
  const reload = async () => { await active.mutate(); };
  const hasMore = active.data?.has_more;
  const empty = tab === "calls" ? !calls.data?.calls.length : tab === "events" ? !events.data?.events.length : !deliveries.data?.deliveries.length;
  const [detail, setDetail] = useState<number | null>(null);

  async function nextPage() {
    if (tab === "calls" && calls.data?.next_before) setBefore(calls.data.next_before);
    if (tab === "events" && events.data?.next_before) await events.mutate(await qqApi.events(events.data.next_before), false);
    if (tab === "deliveries" && deliveries.data?.next_before) await deliveries.mutate(await qqApi.deliveries(deliveries.data.next_before), false);
  }

  return (
    <div className="flex min-h-0 flex-col gap-5 pb-8">
      <PageHeader title="日志" description="API 调用、入站事件与下游投递分别记录。机器人发出的消息不属于入站事件。" actions={<Button variant="outline" onClick={() => void reload()} disabled={activeValidating}><RefreshCw className={activeValidating ? "animate-spin" : ""} />刷新</Button>} />
      <div className="flex flex-wrap gap-2"><Button variant={tab === "calls" ? "secondary" : "ghost"} onClick={() => setTab("calls")}><Activity />API 调用</Button><Button variant={tab === "events" ? "secondary" : "ghost"} onClick={() => setTab("events")}><ScrollText />事件</Button><Button variant={tab === "deliveries" ? "secondary" : "ghost"} onClick={() => setTab("deliveries")}><Truck />投递</Button></div>
      {activeError && <QueryError onRetry={reload} retrying={activeValidating} />}
      {tab === 'calls' && <LogFilters onApply={value => { setBefore(undefined); setFilters(value) }} />}
      <Card>
        <CardHeader><CardTitle>{tab === "calls" ? "API 调用记录" : tab === "events" ? "已入库事件" : "HTTP 投递记录"}</CardTitle><CardDescription>{tab === "calls" ? "仅记录 HTTP 调用元数据，不保存密钥、正文或目标 ID。2xx 不代表客户端已展示；历史记录无法还原具体操作。" : tab === "events" ? "入库不代表已经投递。" : "2xx 只代表下游接受，投递可能因重试而重复。"}</CardDescription></CardHeader>
        <CardContent>
          {activeLoading ? <div className="space-y-3"><div className="h-10 animate-pulse rounded-md bg-muted"/><div className="h-10 animate-pulse rounded-md bg-muted"/></div> : tab === "calls" ? <ApiCallTable calls={calls.data?.calls ?? []} /> : tab === "events" ? <EventTable events={events.data?.events ?? []} detail={detail} setDetail={setDetail} /> : <DeliveryTable deliveries={deliveries.data?.deliveries ?? []} />}
          {empty && !activeLoading && !activeError && <EmptyState variant="inline" icon={tab === "calls" ? <Activity /> : tab === "events" ? <ScrollText /> : <Truck />} title={tab === "calls" ? "暂无 API 调用" : tab === "events" ? "暂无事件" : "暂无投递记录"} description="当前账号没有可展示的记录。" />}
          <div className="mt-4 flex justify-end gap-2">{tab === "calls" && before && <Button variant="outline" size="sm" onClick={() => setBefore(undefined)}>最新记录</Button>}<Button variant="outline" size="sm" disabled={activeValidating || !hasMore} onClick={() => void nextPage()}>更早记录</Button></div>
        </CardContent>
      </Card>
    </div>
  );
}

const messageLabels: Record<string, string> = { text: "文本", mixed: "图文", markdown: "Markdown", ark: "ARK", embed: "Embed", media: "富媒体", image: "图片", video: "视频", audio: "语音", file: "文件", keyboard: "键盘", reference: "引用" };

function ApiCallTable({ calls }: { calls: ApiCallRecord[] }) {
  return <Table className="min-w-[760px] text-xs [&_th]:whitespace-nowrap [&_td]:px-3 [&_td]:py-2"><TableHeader><TableRow><TableHead>时间 / Request ID</TableHead><TableHead>方法 / 操作</TableHead><TableHead>Bot / Key</TableHead><TableHead>操作用户</TableHead><TableHead>类型 / 重放</TableHead><TableHead>HTTP 状态</TableHead><TableHead className="text-right">耗时</TableHead></TableRow></TableHeader><TableBody>{calls.map((call) => <TableRow key={call.id}>
    <TableCell><div className="whitespace-nowrap">{new Date(call.created_at).toLocaleString()}</div><div className="mt-1"><RequestId value={call.request_id}/></div></TableCell>
    <TableCell><span className="font-medium">{call.method}</span><div className="mt-1 break-all font-mono text-muted-foreground">{call.path.includes("(?P<") ? "历史通用路由（操作未记录）" : call.path}</div></TableCell>
    <TableCell><div className="max-w-36 truncate" title={call.bot_name}>{call.bot_name || (call.bot === null ? 'Bot —' : `Bot #${call.bot}`)}</div><div className="mt-1 max-w-36 truncate text-muted-foreground" title={call.key_name}>{call.key_name || (call.api_key === null ? "Key 未关联或已删除" : `Key #${call.api_key}`)}</div></TableCell>
    <TableCell><span className="block max-w-32 truncate" title={call.username || '未认证 / 历史用户已删除'}>{call.username || '未认证 / 历史用户已删除'}</span></TableCell>
    <TableCell><div>{call.message_type ? call.message_type.split("+").map((part) => messageLabels[part] ?? part).join(" + ") : "—"}</div>{call.replayed === true && <div className="mt-1 text-muted-foreground">幂等重放（未重复发送）</div>}</TableCell>
    <TableCell><StatusBadge variant={call.status_code >= 500 ? "destructive" : call.status_code >= 400 ? "warning" : call.status_code >= 300 ? "info" : "success"}>{call.status_code}</StatusBadge></TableCell>
    <TableCell className="text-right tabular-nums">{call.duration_ms} ms</TableCell>
  </TableRow>)}</TableBody></Table>;
}

function EventTable({ events, detail, setDetail }: { events: EventRecord[]; detail: number | null; setDetail: (id: number | null) => void }) {
  return <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>类型</TableHead><TableHead>Bot</TableHead><TableHead>入库时间</TableHead><TableHead className="text-right">详情</TableHead></TableRow></TableHeader><TableBody>{events.map((event) => <TableRow key={event.id}><TableCell><div className="font-medium">{event.event_type}</div><div className="text-xs text-muted-foreground">{event.event_id}</div>{detail === event.id && <pre className="mt-2 max-w-[min(70vw,640px)] whitespace-pre-wrap break-all rounded-md bg-muted p-3 text-xs">{JSON.stringify(event.payload, null, 2)}</pre>}</TableCell><TableCell>{event.bot_name || `Bot #${event.bot}`}</TableCell><TableCell>{new Date(event.received_at).toLocaleString()}</TableCell><TableCell className="text-right"><Button variant="ghost" size="sm" onClick={() => setDetail(detail === event.id ? null : event.id)}><Eye />{detail === event.id ? "收起" : "查看"}</Button></TableCell></TableRow>)}</TableBody></Table></div>;
}

function DeliveryTable({ deliveries }: { deliveries: DeliveryRecord[] }) {
  return <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>ID</TableHead><TableHead>事件</TableHead><TableHead>状态</TableHead><TableHead>尝试次数</TableHead><TableHead>时间</TableHead></TableRow></TableHeader><TableBody>{deliveries.map((row) => <TableRow key={row.id}><TableCell className="font-mono">#{row.id}</TableCell><TableCell><div>{row.bot_name || `Bot #${row.bot}`}</div><div className="text-xs text-muted-foreground">{row.username} · 回调 #{row.subscription}</div><div className="text-xs text-muted-foreground">{row.event_id}</div></TableCell><TableCell><StatusBadge variant={stateVariants[row.state] ?? "info"}>{stateLabels[row.state] ?? row.state}</StatusBadge></TableCell><TableCell>{row.attempts}</TableCell><TableCell className="text-xs text-muted-foreground">{row.available_at ? `可重试：${new Date(row.available_at).toLocaleString()}` : row.lease_until ? `租约至：${new Date(row.lease_until).toLocaleString()}` : "—"}</TableCell></TableRow>)}</TableBody></Table></div>;
}
