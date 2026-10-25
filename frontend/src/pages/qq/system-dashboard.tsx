import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/ui/page-header'
import { PageWrapper } from '@/components/ui/motion'
import { QueryError } from '@/components/ui/query-error'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useQQOverview } from '@/lib/qq-swr'
import { ChannelHealthCard } from './channel-health'

export function SystemDashboardPage() {
  const [windowHours, setWindowHours] = useState(24)
  const [refreshing, setRefreshing] = useState(false)
  const { data, error, isLoading, isValidating, mutate } = useQQOverview(windowHours, { refreshInterval: 15000 })
  async function refresh() {
    setRefreshing(true)
    try { await mutate() } finally { setRefreshing(false) }
  }
  // Monoize's independent admin-dashboard layout: Channels first, then a 7/5 grid.
  return <PageWrapper className="space-y-6">
    <PageHeader title="系统仪表盘" description="Botoize 服务与 Channels 状态。只显示当前账号可访问的资源。" actions={<>
      <span className="text-sm text-muted-foreground">每 15 秒自动刷新</span>
      <Button variant="outline" disabled={refreshing} onClick={() => void refresh()}><RefreshCw className={refreshing ? 'motion-safe:animate-spin' : ''} aria-hidden="true"/>刷新</Button>
    </>}/>
    {error && <QueryError onRetry={mutate} retrying={isValidating} stale={data !== undefined}/>}
    {isLoading && !data ? <div className="space-y-6" aria-busy="true"><Skeleton className="h-64"/><div className="grid grid-cols-1 gap-6 lg:grid-cols-12"><Skeleton className="h-64 lg:col-span-7"/><Skeleton className="h-64 lg:col-span-5"/></div></div> : data && <>
      <ChannelHealthCard channels={data.channels ?? []} windowHours={windowHours} onWindowChange={setWindowHours} calls={data.api_call_count} pending={data.window_hours !== windowHours}/>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12 lg:items-start">
        <Card className="overflow-clip lg:col-span-7"><CardHeader className="p-5"><CardTitle>流量与投递</CardTitle><CardDescription>{data.window_hours} 小时窗口内全部记录，不是日志首页计数。</CardDescription></CardHeader><CardContent className="border-t p-0">
          <Table aria-label="流量与投递" className="table-fixed"><TableHeader><TableRow className="hover:bg-transparent"><TableHead className="pl-5">类型</TableHead><TableHead className="w-24 pr-5 text-right">数量</TableHead></TableRow></TableHeader><TableBody>
            {Object.entries({'API 调用': data.api_call_count, 'API 2xx': data.api_success_count, 'API 4xx / 5xx': data.api_error_count, '入站事件': data.event_count, '回调已接受': data.delivered_count, '回调待处理': data.pending_count + data.processing_count, '回调失败': data.failed_count, '回调已取消': data.cancelled_count}).map(([label, value]) => <TableRow key={label}><TableCell className="pl-5">{label}</TableCell><TableCell className="pr-5 text-right tabular-nums">{value}</TableCell></TableRow>)}
          </TableBody></Table>
        </CardContent></Card>
        <div className="flex flex-col gap-6 lg:col-span-5">
          <Card className="overflow-clip"><CardHeader className="p-5"><CardTitle>系统状态</CardTitle><CardDescription>本次管理请求返回的真实快照。</CardDescription></CardHeader><CardContent className="border-t p-0"><dl className="divide-y">{[['服务','Botoize'],['管理 API','已响应'],['快照时间',new Date(data.generated_at).toLocaleString()],['Channels',String(data.bot_count)],['已启用 Bot',String(data.active_bot_count)],['有效 Gateway worker 租约',String(data.gateway_worker_count)]].map(([label,value]) => <div key={label} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] items-baseline gap-4 px-5 py-2.5 text-sm"><dt className="text-muted-foreground">{label}</dt><dd className="break-words text-end tabular-nums">{value}</dd></div>)}</dl></CardContent></Card>
          <Card className="overflow-clip"><CardHeader className="p-5"><CardTitle>状态口径</CardTitle><CardDescription>配置、租约与实际流量分别记录。</CardDescription></CardHeader><CardContent className="space-y-2 border-t p-5 text-sm leading-6 text-muted-foreground"><p>租约有效表示 worker 持有运行权，不保证此刻 Gateway 在线。会话快照也不是心跳确认。</p><p>Webhook 没有长连接；最近 HTTP 成功也不能证明事件流正常。未收到真实入站事件时，事件数为 0 是正常结果。</p><p>回调统计只包含 HTTPS 投递任务，不将事件流游标算成待投递。</p></CardContent></Card>
        </div>
      </div>
    </>}
  </PageWrapper>
}
