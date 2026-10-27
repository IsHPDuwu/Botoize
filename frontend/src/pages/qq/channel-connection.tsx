import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/ui/status'
import { management, type ChannelStatus, type UpstreamChannel } from '@/lib/qq-api'

// Uses the ProviderRuntimeStatus badge and ProviderCard action layout from Monoize.
export function ChannelConnection({channel, status, failed, canReconnect, onRefresh}: {
  channel: UpstreamChannel; status?: ChannelStatus; failed: boolean; canReconnect: boolean; onRefresh: () => Promise<unknown>
}) {
  const [submitting, setSubmitting] = useState(false)
  const [accepted, setAccepted] = useState(false)
  const webhook = channel.interface_type === 'qq_official_webhook'
  const pending = status?.connection_state === 'reconnect_pending'
  const queued = accepted && (!status?.reconnect_processed_at || !status.reconnect_requested_at || status.reconnect_processed_at < status.reconnect_requested_at)
  const state = !channel.is_active ? 'disabled' : failed ? 'unknown' : pending || queued ? 'reconnect_pending' : status?.connection_state ?? 'loading'
  const labels = {disabled:'已停用',unknown:'状态读取失败',reconnect_pending:webhook ? '等待检查' : '等待重连',webhook:'Webhook 接收',connected:'已连接',connecting:'连接中',disconnected:'未连接',loading:'读取状态中'}
  const variant = state === 'connected' ? 'success' : state === 'unknown' ? 'destructive' : ['disconnected','connecting','reconnect_pending'].includes(state) ? 'warning' : 'info'
  async function reconnect() {
    if (!channel.id) return
    setSubmitting(true)
    try {
      await management(`channels/${channel.id}/reconnect/`, {})
      setAccepted(true)
      toast.success(webhook ? '上游检查已排队' : '重连请求已排队')
      await onRefresh().catch(() => undefined)
    } catch(reason) { toast.error(reason instanceof Error ? reason.message : '请求失败') }
    finally { setSubmitting(false) }
  }
  return <div className='flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3'>
    <div className='flex min-w-0 flex-wrap items-center gap-2 text-xs'>
      <span className='text-muted-foreground'>上游连接</span><StatusBadge variant={variant}>{labels[state]}</StatusBadge>
      {webhook ? <span className='text-muted-foreground'>{status?.last_check_at ? `最近 HTTP 检查${status.last_check_ok ? '成功' : '失败'} · ${new Date(status.last_check_at).toLocaleString()}` : 'Webhook 无常驻连接'}</span> :
        state === 'connected' ? <span className='text-muted-foreground'>事件 WS 已建立</span> : state === 'disconnected' ? <span className='text-muted-foreground'>{channel.interface_type.startsWith('onebot_') && channel.event_reporting_enabled ? '事件 WS 未连接，可使用 HTTP 上报' : '尚无有效事件连接'}</span> : null}
      {status?.connection_error && <span className='text-destructive'>上次连接检查失败</span>}
    </div>
    {canReconnect && <Button variant='outline' size='sm' aria-label={`${webhook ? '检查上游' : '重新连接'} ${channel.name}`} disabled={!channel.id || !channel.is_active || submitting || pending || queued} onClick={() => void reconnect()}><RefreshCw className={submitting || pending || queued ? 'animate-spin' : ''}/>{webhook ? '检查上游' : '重新连接'}</Button>}
  </div>
}
