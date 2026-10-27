import { useState } from 'react'
import useSWR, { mutate } from 'swr'
import { ChevronRight, Layers3, Pencil, Plus, RefreshCw, Server } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/ui/empty-state'
import { PageHeader } from '@/components/ui/page-header'
import { QueryError } from '@/components/ui/query-error'
import { Skeleton } from '@/components/ui/skeleton'
import { useQQAuth } from '@/hooks/use-qq-auth'
import { management, type UpstreamInterface, type UpstreamProvider } from '@/lib/qq-api'
import { ProviderDialog } from './provider-dialog'
import { ChannelIdentity } from './channel-identity'

export function ProvidersPage() {
  const { user } = useQQAuth()
  const { data, error, isLoading, isValidating, mutate: reload } = useSWR('qq/providers', () => management<UpstreamProvider[]>('providers/'))
  const interfaces = useSWR('qq/upstream-interfaces', () => management<UpstreamInterface[]>('upstream-interfaces/'))
  const [editor, setEditor] = useState<{ current: UpstreamProvider | null } | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const label = (type: string) => interfaces.data?.find(item => item.interface_type === type)?.label ?? type
  if (error && !data) return <QueryError onRetry={reload} retrying={isValidating} />
  return <div className='flex min-h-0 flex-col gap-5 pb-8'>
    <PageHeader title='服务提供商' description='Provider 是服务提供商，Channel 是 Bot，Models 是会话。' actions={<>
      <Button variant='outline' disabled={isValidating} onClick={() => void reload()}><RefreshCw className={isValidating ? 'animate-spin' : ''} />刷新</Button>
      {user?.role === 'Owner' && <Button onClick={() => setEditor({ current: null })} disabled={!interfaces.data}><Plus />添加服务提供商</Button>}
    </>} />
    {interfaces.error && <QueryError onRetry={interfaces.mutate} retrying={interfaces.isValidating} />}
    {isLoading && !data ? <Skeleton className='h-40' /> : data?.length ? data.map(provider => {
      const open = expanded.has(provider.id)
      return <Card key={provider.id} className='transition-shadow hover:shadow-md'>
        <CardHeader><div className='flex items-center justify-between gap-3'>
          <button type='button' aria-expanded={open} className='flex min-w-0 flex-1 items-center gap-3 text-left' onClick={() => setExpanded(previous => {
            const next = new Set(previous)
            if (next.has(provider.id)) next.delete(provider.id); else next.add(provider.id)
            return next
          })}>
            <ChevronRight className={`size-4 shrink-0 ${open ? 'rotate-90' : ''}`} /><Server className='size-5 shrink-0 text-muted-foreground' />
            <div className='min-w-0'><CardTitle className='truncate'>{provider.name}</CardTitle><p className='mt-1 text-xs text-muted-foreground'>{provider.channels.length} 个渠道 · {provider.channels.reduce((sum, channel) => sum + channel.models.length, 0)} 个模型</p></div>
          </button>
          {user?.role === 'Owner' && <Button variant='ghost' size='icon' aria-label={`编辑 ${provider.name}`} disabled={!interfaces.data} onClick={() => setEditor({ current: provider })}><Pencil /></Button>}
        </div></CardHeader>
        <CardContent>
          <div className='flex flex-wrap gap-2'>{Array.from(new Set(provider.channels.map(channel => channel.interface_type))).map(type => <Badge key={type} variant='outline'>{label(type)}</Badge>)}</div>
          {open && <div className='mt-4 space-y-3 border-t pt-4'>{provider.channels.map(channel => <div key={channel.id} className='rounded-lg border'>
            <div className='flex flex-wrap items-center justify-between gap-2 border-b bg-muted/10 px-4 py-3'><div className='flex min-w-0 items-center gap-2'><Layers3 className='size-4 shrink-0' /><span className='truncate text-sm font-medium'>{channel.name}</span></div><span className='text-xs text-muted-foreground'>{label(channel.interface_type)}</span></div>
            <ChannelIdentity key={`${channel.id}:${channel.interface_type}:${channel.app_id}:${channel.base_url}`} channel={channel} canRefresh={user?.role === 'Owner'} onRefresh={reload}/>
            {channel.models.length ? channel.models.map(model => <div key={model.id} className='flex items-center justify-between gap-3 border-b px-4 py-3 last:border-b-0'>
              <div className='min-w-0'><p className='truncate text-sm font-medium'>{model.name || (model.isDirect ? '单聊' : '群聊')}</p><p className='truncate font-mono text-xs text-muted-foreground'>{model.userid ?? model.groupid}</p></div>
              <Badge variant='outline'>{model.isDirect ? '单聊' : '群聊'}</Badge>
            </div>) : <p className='p-4 text-sm text-muted-foreground'>暂无模型</p>}
          </div>)}</div>}
        </CardContent>
      </Card>
    }) : <EmptyState icon={<Server />} title='暂无服务提供商' description='添加服务提供商，然后配置渠道和机器人模型。' />}
    {editor && <ProviderDialog current={editor.current} providers={data ?? []} interfaces={interfaces.data ?? []} onClose={() => setEditor(null)} onSaved={async () => {
      await reload()
      await mutate(key => typeof key === 'string' && key.startsWith('qq/') && key !== 'qq/providers' && key !== 'qq/upstream-interfaces')
    }} />}
  </div>
}
