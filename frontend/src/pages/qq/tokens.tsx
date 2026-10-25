import { Check, Copy, KeyRound, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { ConfirmDeleteDialog } from '@/components/ui/confirm-delete-dialog'
import { CopyButton } from '@/components/ui/copy-button'
import { DataList, DataListActions, DataListBody, DataListCell, DataListHead, DataListHeader, DataListRow } from '@/components/ui/data-list'
import { DataTableShell, TableToolbarSearch } from '@/components/ui/data-table-shell'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/ui/page-header'
import { QueryError } from '@/components/ui/query-error'
import { Skeleton } from '@/components/ui/skeleton'
import { StatusBadge } from '@/components/ui/status'
import { management, type ApiKeyInfo } from '@/lib/qq-api'
import { useQQKeys, useQQMyGrants } from '@/lib/qq-swr'
import { ConversationPicker } from './conversation-picker'
import { PermissionBadges } from './permission-badges'

type Draft = { id?: number; bot: string; name: string; scopes: string[]; expiry: string; all: boolean; conversations: number[] }

export function TokensPage() {
  const keys = useQQKeys()
  const grants = useQQMyGrants()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 30000); return () => window.clearInterval(timer) }, [])
  const [draft, setDraft] = useState<Draft | null>(null)
  const [revoking, setRevoking] = useState<ApiKeyInfo | null>(null)
  const [issuedToken, setIssuedToken] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const active = grants.data?.find(grant => String(grant.bot?.id) === draft?.bot)
  const reload = async () => { await Promise.all([keys.mutate(), grants.mutate()]) }
  const openCreate = () => { setNotice(''); setDraft({ bot: '', name: '', scopes: [], expiry: new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 16), all: false, conversations: [] }) }
  const openEdit = (key: ApiKeyInfo) => { setNotice(''); setDraft({ id: key.id, bot: String(key.bot), name: key.name, scopes: [...key.scopes], expiry: key.expires_at?.slice(0, 16) ?? '', all: key.all_conversations ?? true, conversations: [...(key.conversations ?? [])] }) }

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!draft || !active) return
    setBusy(true); setNotice('')
    try {
      const result = await management<ApiKeyInfo & {token?: string}>(draft.id ? `keys/${draft.id}/` : 'keys/', {
        ...(draft.id ? {} : { bot: Number(draft.bot) }), name: draft.name, scopes: draft.scopes,
        expires_at: draft.expiry ? new Date(draft.expiry + 'Z').toISOString() : null,
        all_conversations: draft.all, conversations: draft.conversations,
      }, undefined, draft.id ? 'PATCH' : 'POST')
      if (result.token) setIssuedToken(result.token)
      setNotice(draft.id ? '令牌配置已保存，原始 token 没有改变。' : '令牌已创建。')
      setDraft(null); await reload()
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '保存令牌失败') }
    finally { setBusy(false) }
  }

  async function copy(key: ApiKeyInfo) {
    setBusy(true); setNotice('')
    try {
      const result = await management<{token: string}>(`keys/${key.id}/copy/`, {})
      await navigator.clipboard.writeText(result.token)
      setNotice('已复制同一令牌；没有轮换。')
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '复制失败') }
    finally { setBusy(false) }
  }

  async function revoke() {
    if (!revoking) return
    setBusy(true)
    try { await management(`keys/${revoking.id}/revoke/`, {}); await reload(); setNotice('令牌已撤销。') }
    catch (reason) { setNotice(reason instanceof Error ? reason.message : '撤销失败') }
    finally { setBusy(false) }
  }

  const visible = (keys.data ?? []).filter(key => `${key.name} ${key.prefix} ${key.bot}`.toLowerCase().includes(query.toLowerCase()))
  return <div className='flex min-h-0 flex-col gap-5 pb-8'>
    <PageHeader title='令牌管理' description='每个 Key 固定绑定一个 Bot；scope 和会话范围只能在当前授权内进一步缩小。' actions={<><Button variant='outline' onClick={() => void reload()} disabled={keys.isValidating}><RefreshCw />刷新</Button><Button onClick={openCreate} disabled={!grants.data}><Plus />创建令牌</Button></>} />
    {notice && <p role='status' className='rounded-md border bg-muted/40 p-3 text-sm'>{notice}</p>}
    {(keys.error || grants.error) && <QueryError onRetry={reload} retrying={keys.isValidating || grants.isValidating} />}
    {issuedToken && <Card className='border-warning-border bg-warning-soft'><CardHeader><CardTitle>新令牌</CardTitle><CardDescription>服务端按要求保存明文 token。请安全保存，也可稍后再次复制。</CardDescription></CardHeader><CardContent className='flex flex-wrap items-center gap-2'><Input type='password' readOnly value={issuedToken} aria-label='新建 API Key' className='min-w-0 flex-1 font-mono' /><CopyButton value={issuedToken} label='复制新令牌' /><Button variant='ghost' onClick={() => setIssuedToken('')}><Check />清除显示</Button></CardContent></Card>}
    {keys.isLoading ? <Skeleton className='h-40' /> : keys.data !== undefined && <DataTableShell toolbar={keys.data.length ? <><TableToolbarSearch value={query} onChange={event => setQuery(event.target.value)} placeholder='搜索名称、前缀或 Bot' aria-label='搜索令牌' /><p className='text-sm tabular-nums text-muted-foreground'>{visible.length} 个令牌</p></> : undefined} isEmpty={!keys.data.length} emptyState={<EmptyState icon={<KeyRound />} title='暂无 API Key' description='创建一个绑定有效授权的 Key。' action={<Button onClick={openCreate}><Plus />创建令牌</Button>} />}>
      <DataList columns='minmax(0,1.3fr) minmax(0,1.5fr) 10rem 7rem 8rem'><DataListHeader><DataListHead>名称</DataListHead><DataListHead>权限与会话</DataListHead><DataListHead>到期</DataListHead><DataListHead>状态</DataListHead><DataListHead align='end'>操作</DataListHead></DataListHeader><DataListBody aria-label='现有 API Key'>
        {visible.map(key => {
          const grant = grants.data?.find(item => item.bot?.id === key.bot)
          const expired = !!key.expires_at && Date.parse(key.expires_at) <= now
          const status = key.revoked_at ? '已撤销' : expired ? '已过期' : grants.isLoading || grants.error ? '授权待确认' : grant?.revision !== key.grant_revision ? '授权已变更' : '有效'
          return <DataListRow key={key.id}><DataListCell primary><div className='flex min-w-0 items-start gap-3'><KeyRound className='size-4 shrink-0 text-muted-foreground' /><div className='min-w-0 flex-1'><p className='truncate font-medium'>{key.name}</p><div className='flex min-w-0 items-center gap-1'><code className='truncate text-xs text-muted-foreground'>{key.prefix}…</code><Button variant='ghost' size='icon' className='size-11 shrink-0 touch-manipulation sm:size-7' aria-label={`复制 ${key.name}`} disabled={busy || status !== '有效' || key.can_copy === false} title={key.can_copy === false ? '历史令牌未保存原文，无法恢复；复制不会轮换令牌' : '复制原始令牌'} onClick={() => void copy(key)}><Copy /></Button></div></div></div></DataListCell><DataListCell label='权限与会话'><p className='mb-1 truncate text-xs text-muted-foreground'>{grant?.bot?.name ?? `Bot #${key.bot}`}</p><PermissionBadges scopes={key.scopes} all={key.all_conversations} count={key.conversations?.length ?? 0} />{key.can_copy === false && <p className='text-xs text-muted-foreground'>历史 token 无原文，不能再次复制</p>}</DataListCell><DataListCell label='到期'><span className='text-xs tabular-nums'>{key.expires_at ? new Date(key.expires_at).toLocaleString() : '不过期'}</span></DataListCell><DataListCell label='状态'><StatusBadge variant={status === '有效' ? 'success' : status === '已撤销' || status === '已过期' ? 'destructive' : 'warning'}>{status}</StatusBadge></DataListCell><DataListActions><Button variant='ghost' size='icon' aria-label={`编辑 ${key.name}`} disabled={busy || status !== '有效'} onClick={() => openEdit(key)}><Pencil /></Button><Button variant='ghost' size='icon' aria-label={`撤销 ${key.name}`} disabled={busy || !!key.revoked_at} onClick={() => setRevoking(key)}><Trash2 /></Button></DataListActions></DataListRow>
        })}
      </DataListBody></DataList>{!visible.length && keys.data.length > 0 && <EmptyState title='没有匹配的令牌' description='请尝试其他搜索条件。' />}
    </DataTableShell>}
    <Dialog open={draft !== null} onOpenChange={open => { if (!open && !busy) setDraft(null) }}><DialogContent className='max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl'><DialogHeader><DialogTitle>{draft?.id ? '编辑令牌' : '创建令牌'}</DialogTitle><DialogDescription>编辑或复制不改变原始 token。Full access 仅全选当前授权内的 scope。</DialogDescription></DialogHeader>{draft && <form className='space-y-4' onSubmit={event => void save(event)}>
      <div className='grid gap-4 sm:grid-cols-2'><div className='space-y-2'><Label htmlFor='key-bot'>绑定 Bot</Label><select id='key-bot' required disabled={!!draft.id || busy} className='flex h-9 w-full rounded-md border bg-background px-3 text-sm' value={draft.bot} onChange={event => setDraft({...draft, bot: event.target.value, scopes: [], all: false, conversations: []})}><option value=''>选择已授权 Bot</option>{grants.data?.map(grant => <option key={grant.bot?.id} value={grant.bot?.id}>{grant.bot?.name}</option>)}</select></div><div className='space-y-2'><Label htmlFor='key-name'>名称</Label><Input id='key-name' value={draft.name} maxLength={120} required onChange={event => setDraft({...draft, name: event.target.value})} /></div></div>
      <div className='space-y-2'><Label htmlFor='key-expiry'>到期时间（UTC，留空为不过期）</Label><Input id='key-expiry' type='datetime-local' value={draft.expiry} onChange={event => setDraft({...draft, expiry: event.target.value})} /></div>
      <fieldset className='space-y-3'><legend className='mb-2 text-sm font-medium'>允许的 scope</legend><div className='flex items-center gap-2'><Checkbox id='key-full' checked={!!active?.scopes.length && active.scopes.every(scope => draft.scopes.includes(scope))} disabled={!active} onCheckedChange={checked => setDraft({...draft, scopes: checked ? [...(active?.scopes ?? [])] : []})} /><Label htmlFor='key-full'>Full access（当前授权内全部 scope）</Label></div><div className='grid gap-2 sm:grid-cols-2'>{active?.scopes.map(scope => <div key={scope} className='flex items-center gap-2'><Checkbox id={`key-${scope}`} checked={draft.scopes.includes(scope)} onCheckedChange={checked => setDraft({...draft, scopes: checked ? [...draft.scopes, scope] : draft.scopes.filter(item => item !== scope)})} /><Label htmlFor={`key-${scope}`} className='font-normal'>{scope}</Label></div>)}</div></fieldset>
      <ConversationPicker models={active?.models ?? []} all={draft.all} selected={draft.conversations} allowAll={active?.all_conversations === true} onChange={(all, conversations) => setDraft({...draft, all, conversations})} />
      {!active && <p className='text-sm text-muted-foreground'>没有可用于创建 Key 的授权 Bot，或所选授权已失效。</p>}
      <DialogFooter><Button variant='outline' type='button' disabled={busy} onClick={() => setDraft(null)}>取消</Button><Button type='submit' disabled={busy || !active}>{busy ? '保存中…' : draft.id ? '保存配置' : '创建 API Key'}</Button></DialogFooter>
    </form>}</DialogContent></Dialog>
    <ConfirmDeleteDialog open={revoking !== null} onOpenChange={open => { if (!open) setRevoking(null) }} title='撤销令牌？' description={`“${revoking?.name}” 将立即失效，不能恢复。`} onConfirm={revoke} />
  </div>
}
