import { useState } from 'react'
import { Plus, RefreshCw, Webhook } from 'lucide-react'
import { mutate } from 'swr'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/ui/page-header'
import { QueryError } from '@/components/ui/query-error'
import { Skeleton } from '@/components/ui/skeleton'
import { StatusBadge } from '@/components/ui/status'
import { management } from '@/lib/qq-api'
import { QQ_SWR_KEYS, useQQMyGrants, useQQSubscriptions } from '@/lib/qq-swr'

export function SubscriptionsPage() {
  const grants = useQQMyGrants()
  const subscriptions = useQQSubscriptions()
  const [draft, setDraft] = useState<{id?: number; bot: string; url: string; secret: string} | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const eligible = grants.data?.filter(grant => grant.scopes.includes('events:read')) ?? []
  const existing = subscriptions.data?.find(row => row.id === draft?.id)
  const reload = async () => { await Promise.all([subscriptions.mutate(), grants.mutate()]) }

  async function save(active: boolean) {
    if (!draft) return
    setBusy(true); setNotice('')
    try {
      await management('subscriptions/', { ...(draft.id ? {id: draft.id} : {}), bot: Number(draft.bot), is_active: active,
        ...(active ? { url: draft.url, ...(draft.secret ? {callback_secret: draft.secret} : {}) } : {}) })
      setDraft(null); await reload(); await mutate(QQ_SWR_KEYS.deliveries)
      setNotice(active ? '订阅已保存；仅投递当前 Grant 允许的会话事件。需后台调度投递 worker。' : '订阅已禁用。')
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '订阅操作失败') }
    finally { setBusy(false) }
  }

  return <div className='flex min-h-0 flex-col gap-5 pb-8'>
    <PageHeader title='订阅端点' description='每个授权 Bot 可配置多个 HTTPS 回调，不限数量。各端点独立签名、投递和重试；授权版本变化后需重新保存。' actions={<><Button variant='outline' disabled={subscriptions.isValidating} onClick={() => void reload()}><RefreshCw />刷新</Button><Button disabled={!grants.data} onClick={() => setDraft({bot: '', url: '', secret: ''})}><Plus />添加订阅</Button></>} />
    {notice && <p role='status' className='rounded-md border bg-muted/40 p-3 text-sm'>{notice}</p>}
    {(subscriptions.error || grants.error) && <QueryError onRetry={reload} retrying={subscriptions.isValidating} />}
    {subscriptions.isLoading ? <Skeleton className='h-40' /> : subscriptions.data?.length ? <Card><CardHeader><CardTitle>已保存订阅</CardTitle><CardDescription>只返回当前账号所属的回调。</CardDescription></CardHeader><CardContent className='space-y-3'>{subscriptions.data.map(row => <div key={row.id} className='flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-md border p-3'><div className='min-w-0'><p className='text-sm font-medium'>{grants.data?.find(grant => grant.bot?.id === row.bot)?.bot?.name ?? `Bot #${row.bot}`}</p><p className='break-all text-xs text-muted-foreground'>{row.url}</p></div><div className='flex items-center gap-2'><StatusBadge variant={row.is_current ? 'success' : row.is_active ? 'warning' : 'info'}>{row.is_current ? '有效' : row.is_active ? '需重存' : '已禁用'}</StatusBadge><Button variant='outline' size='sm' disabled={busy} onClick={() => setDraft({id: row.id, bot: String(row.bot), url: row.url, secret: ''})}>编辑</Button></div></div>)}</CardContent></Card> : <EmptyState icon={<Webhook />} title='尚未配置订阅' description={eligible.length ? '为授权 Bot 配置 HTTPS 回调。' : '需要有效的 events:read 授权才能配置订阅。'} />}
    <Dialog open={draft !== null} onOpenChange={open => { if (!open && !busy) setDraft(null) }}><DialogContent className='max-h-[calc(100dvh-2rem)] overflow-y-auto'><DialogHeader><DialogTitle>HTTP 回调配置</DialogTitle><DialogDescription>仅公网 HTTPS 443；不允许 URL 凭据、fragment、私网解析或重定向。</DialogDescription></DialogHeader>{draft && <form className='space-y-4' onSubmit={event => { event.preventDefault(); void save(true) }}>
      <div className='space-y-2'><Label htmlFor='subscription-bot'>Bot</Label><select id='subscription-bot' value={draft.bot} required disabled={!!draft.id} className='flex h-9 w-full rounded-md border bg-background px-3 text-sm' onChange={event => { setDraft({...draft, bot: event.target.value}) }}><option value=''>选择具有 events:read 的 Bot</option>{eligible.map(grant => <option key={grant.bot?.id} value={grant.bot?.id}>{grant.bot?.name}</option>)}</select></div>
      <div className='space-y-2'><Label htmlFor='callback-url'>HTTPS 回调地址</Label><Input id='callback-url' type='url' required value={draft.url} onChange={event => setDraft({...draft, url: event.target.value})} placeholder='https://example.com/qq/events' /></div>
      <div className='space-y-2'><Label htmlFor='callback-secret'>回调 HMAC 密钥</Label><Input id='callback-secret' type='password' autoComplete='new-password' minLength={32} maxLength={256} required={!existing} value={draft.secret} onChange={event => setDraft({...draft, secret: event.target.value})} placeholder={existing ? '留空保留已有密钥' : '32–256 字符，请自行安全保存'} /></div>
      <DialogFooter><Button type='button' variant='outline' disabled={busy} onClick={() => setDraft(null)}>取消</Button>{existing?.is_active && <Button type='button' variant='outline' disabled={busy} onClick={() => void save(false)}>禁用订阅</Button>}<Button type='submit' disabled={busy || !eligible.some(grant => String(grant.bot?.id) === draft.bot)}>{busy ? '处理中…' : '保存订阅'}</Button></DialogFooter>
    </form>}</DialogContent></Dialog>
  </div>
}
