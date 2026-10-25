import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { DataList, DataListBody, DataListCell, DataListHead, DataListHeader, DataListRow } from '@/components/ui/data-list'
import { SegmentedControl } from '@/components/ui/segmented-control'
import { StatusBadge } from '@/components/ui/status'
import { EmptyState } from '@/components/ui/empty-state'
import type { ChannelStatus } from '@/lib/qq-api'

// Adapted from upstream admin-dashboard/dashboard-sections ChannelHealthCard.
export function ChannelHealthCard({channels, windowHours, onWindowChange, calls, pending}: {channels: ChannelStatus[]; windowHours: number; onWindowChange: (value: number) => void; calls: number; pending: boolean}) {
  return <Card className="overflow-clip"><CardHeader className="gap-3 space-y-0 p-5">
    <div className="flex flex-wrap items-start justify-between gap-3"><div className="flex min-w-0 flex-col gap-1.5"><CardTitle>Channels 状态</CardTitle><CardDescription className="tabular-nums">共 {channels.length} 个 Channel · {channels.filter(c => c.worker_lease_live).length} 个有效 worker 租约</CardDescription></div>
      <SegmentedControl value={String(windowHours)} options={['24', '168', '720']} label={v => ({'24':'24 小时','168':'7 天','720':'30 天'}[v] ?? v)} onChange={v => onWindowChange(Number(v))} ariaLabel="统计窗口"/>
    </div>
    <p className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm text-muted-foreground"><span>API 调用 <span className="font-medium tabular-nums text-foreground">{calls}</span></span><span>租约不等于实时在线；Webhook 没有长连接。</span></p>
  </CardHeader><CardContent className={`border-t p-0 transition-opacity ${pending ? 'opacity-60' : ''}`}>
    {channels.length ? <DataList columns="minmax(0,1fr) 7rem 8rem 9rem 11rem"><DataListHeader><DataListHead>Channel / 服务商</DataListHead><DataListHead>Bot</DataListHead><DataListHead>配置</DataListHead><DataListHead>Gateway worker</DataListHead><DataListHead align="end">最近 API 调用</DataListHead></DataListHeader><DataListBody>{channels.map(channel => <DataListRow key={channel.channel}>
      <DataListCell primary><span className="block truncate font-medium" title={channel.channel_name}>{channel.channel_name}</span><span className="block truncate text-muted-foreground" title={channel.provider_name}>{channel.provider_name}</span></DataListCell>
      <DataListCell label="Bot"><span className="block truncate" title={channel.name}>{channel.name}</span></DataListCell>
      <DataListCell label="配置"><StatusBadge variant={channel.enabled ? 'success' : 'info'}>{channel.enabled ? '已启用' : '已停用'}</StatusBadge><span className="mt-1 block text-xs text-muted-foreground">{channel.interface_type === 'qq_official_websocket' ? 'QQ WebSocket' : channel.interface_type === 'qq_official_webhook' ? 'QQ Webhook' : channel.interface_type}</span></DataListCell>
      <DataListCell label="Gateway worker">{channel.interface_type !== 'qq_official_websocket' ? <span className="text-muted-foreground">不适用</span> : <><StatusBadge variant={channel.worker_lease_live ? 'success' : 'warning'}>{channel.worker_lease_live ? '租约有效' : '无有效租约'}</StatusBadge><span className="mt-1 block text-xs text-muted-foreground">{channel.session_recorded ? '已有会话快照' : '尚无会话快照'}</span></>}</DataListCell>
      <DataListCell label="最近 API 调用" align="end"><span className="block tabular-nums">{channel.last_http_status ?? '—'}</span><span className="mt-1 block text-xs tabular-nums text-muted-foreground">{channel.last_call_at ? new Date(channel.last_call_at).toLocaleString() : '暂无调用'}</span></DataListCell>
    </DataListRow>)}</DataListBody></DataList> : <EmptyState variant="inline" title="暂无可访问 Channel" description="添加服务提供商或联系管理员授权。" className="py-8"/>}
  </CardContent></Card>
}
