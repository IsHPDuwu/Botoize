import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { management, type UpstreamChannel } from '@/lib/qq-api'

type ConnectionIDs = NonNullable<UpstreamChannel['connection_ids']>

export function ChannelIdentity({ channel, canRefresh, onRefresh }: {
  channel: UpstreamChannel; canRefresh: boolean; onRefresh: () => Promise<unknown>
}) {
  const [loading, setLoading] = useState(false)
  const [resolved, setResolved] = useState<ConnectionIDs>()
  const ids = resolved ?? channel.connection_ids
  const ob11 = ids?.onebot11 ?? (channel.interface_type === 'onebot_v11' ? channel.app_id : null)
  const ob12 = ids?.onebot12 ?? (channel.interface_type.startsWith('onebot_') ? channel.app_id : null)
  async function refresh() {
    setLoading(true)
    try {
      setResolved(await management<ConnectionIDs>(`channels/${channel.id}/identity/`, {}))
      toast.success('接入 ID 已更新')
      await onRefresh().catch(() => undefined)
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : '获取身份失败') }
    finally { setLoading(false) }
  }
  async function copy(value: string | number) {
    try { await navigator.clipboard.writeText(String(value)); toast.success('已复制') }
    catch { toast.error('复制失败') }
  }
  return <div className='flex flex-wrap items-center justify-between gap-3 border-b px-4 py-2'>
    <div className='flex min-w-0 flex-wrap gap-x-5 gap-y-1 font-mono text-xs text-muted-foreground'>
      {([['OB11 ID', ob11], ['OB12 ID', ob12]] as const).map(([label, value]) => <span key={label}>{label}: {value == null ? '待获取' : <button type='button' className='break-all text-left hover:text-foreground' aria-label={`复制 ${label}`} onClick={() => void copy(value)}>{value}</button>}</span>)}
    </div>
    {canRefresh && <Button variant='outline' size='sm' disabled={!channel.id || !channel.is_active || loading} aria-label={`获取 / 刷新 ID ${channel.name}`} onClick={() => void refresh()}><RefreshCw className={loading ? 'animate-spin' : ''}/>获取 / 刷新 ID</Button>}
  </div>
}
