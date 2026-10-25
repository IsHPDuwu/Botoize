import { Pencil, Plus, RefreshCw, ShieldCheck, Trash2, Users } from 'lucide-react'
import { useState } from 'react'
import useSWR, { mutate } from 'swr'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { ConfirmDeleteDialog } from '@/components/ui/confirm-delete-dialog'
import { DataList, DataListActions, DataListBody, DataListCell, DataListHead, DataListHeader, DataListRow } from '@/components/ui/data-list'
import { DataTableShell } from '@/components/ui/data-table-shell'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/ui/page-header'
import { QueryError } from '@/components/ui/query-error'
import { Skeleton } from '@/components/ui/skeleton'
import { StatusBadge } from '@/components/ui/status'
import { useQQAuth } from '@/hooks/use-qq-auth'
import { management, type BotGrant, type UpstreamProvider } from '@/lib/qq-api'
import { useQQGrants, useQQMyGrants, useQQUsers } from '@/lib/qq-swr'
import { ConversationPicker } from './conversation-picker'

export function GroupsPage() {
  const { user } = useQQAuth()
  const grants = useQQGrants()
  const mine = useQQMyGrants()
  const users = useQQUsers()
  const providers = useSWR('qq/providers', () => management<UpstreamProvider[]>('providers/'))
  const catalog = useSWR('qq/scopes', () => management<string[]>('scopes/'))
  const [editor, setEditor] = useState<{user: string; bot: string; scopes: string[]; all: boolean; conversations: number[]; editing: boolean} | null>(null)
  const [disable, setDisable] = useState<BotGrant | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const channels = providers.data?.flatMap(provider => provider.channels) ?? []
  const active = channels.find(channel => String(channel.bot_id) === editor?.bot)
  const ownGrant = mine.data?.find(grant => String(grant.bot?.id) === editor?.bot)
  const scopeOptions = user?.role === 'Owner' ? catalog.data ?? [] : ownGrant?.scopes ?? []
  const reload = async () => { await Promise.all([grants.mutate(), mine.mutate(), users.mutate(), providers.mutate()]) }
  const error = grants.error ?? mine.error ?? users.error ?? providers.error ?? catalog.error
  const openCreate = () => setEditor({ user: '', bot: '', scopes: [], all: false, conversations: [], editing: false })

  async function save() {
    if (!editor) return
    setBusy(true); setNotice('')
    try {
      await management('grants/', { user: Number(editor.user), bot: Number(editor.bot), scopes: editor.scopes,
        is_active: true, all_conversations: editor.all, conversations: editor.conversations })
      setEditor(null)
      await mutate(key => typeof key === 'string' && key.startsWith('qq/'))
      setNotice('授权已保存；旧 Key、订阅和下级委派快照已失效。')
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '保存授权失败') }
    finally { setBusy(false) }
  }

  async function disableGrant() {
    if (!disable) return
    setBusy(true)
    try {
      await management('grants/', { user: disable.user_id, bot: disable.bot_id, scopes: disable.scopes,
        is_active: false, all_conversations: disable.all_conversations, conversations: disable.conversations })
      await reload(); setNotice('授权已停用。')
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : '停用失败') }
    finally { setBusy(false) }
  }

  return <div className='flex min-h-0 flex-col gap-5 pb-8'>
    <PageHeader title='分组管理' description='配置用户可访问的 Bot、scope 和单聊/群聊会话。Admin 只能委派自己的权限子集，不能修改自己或 Owner 的授权。' actions={<><Button variant='outline' onClick={() => void reload()} disabled={grants.isValidating}><RefreshCw />刷新</Button><Button onClick={openCreate} disabled={!providers.data || !users.data || !catalog.data}><Plus />添加授权</Button></>} />
    {notice && <p role='status' className='rounded-md border bg-muted/40 p-3 text-sm'>{notice}</p>}
    {error && <QueryError onRetry={reload} retrying={grants.isValidating} />}
    {grants.isLoading ? <Skeleton className='h-40' /> : grants.data !== undefined && <DataTableShell isEmpty={!grants.data.length} emptyState={<EmptyState icon={<Users />} title='暂无授权记录' description='使用添加授权弹窗分配 Bot 和会话。' action={<Button onClick={openCreate}><Plus />添加授权</Button>} />}>
      <DataList columns='minmax(0,1.2fr) minmax(0,1.5fr) 7rem 7rem'><DataListHeader><DataListHead>用户 / Bot</DataListHead><DataListHead>权限与会话</DataListHead><DataListHead>状态</DataListHead><DataListHead align='end'>操作</DataListHead></DataListHeader><DataListBody aria-label='授权列表'>
        {grants.data.map(grant => <DataListRow key={grant.id}><DataListCell primary><div className='flex items-center gap-3'><ShieldCheck className='size-4 shrink-0 text-muted-foreground' /><div className='min-w-0'><p className='truncate font-medium'>{users.data?.find(item => item.id === grant.user_id)?.username ?? `用户 #${grant.user_id}`}</p><p className='truncate text-xs text-muted-foreground'>{grant.bot?.name ?? `Bot #${grant.bot_id}`} · revision {grant.revision}</p></div></div></DataListCell><DataListCell label='权限与会话'><p className='break-all text-xs text-muted-foreground'>{grant.scopes.join('、') || '无 scope'}</p><p className='text-xs'>{grant.all_conversations ? '全部会话（含未来）' : `${grant.conversations?.length ?? 0} 个指定会话`}</p></DataListCell><DataListCell label='状态'><StatusBadge variant={grant.is_active ? 'success' : 'warning'}>{grant.is_active ? '有效' : '已停用'}</StatusBadge></DataListCell><DataListActions><Button variant='ghost' size='icon' aria-label={`编辑授权 ${grant.id}`} disabled={busy} onClick={() => setEditor({user: String(grant.user_id), bot: String(grant.bot_id), scopes: [...grant.scopes], all: grant.all_conversations ?? true, conversations: [...(grant.conversations ?? [])], editing: true})}><Pencil /></Button><Button variant='ghost' size='icon' aria-label={`停用授权 ${grant.id}`} disabled={busy || !grant.is_active} onClick={() => setDisable(grant)}><Trash2 /></Button></DataListActions></DataListRow>)}
      </DataListBody></DataList>
    </DataTableShell>}
    <Dialog open={editor !== null} onOpenChange={open => { if (!open && !busy) setEditor(null) }}><DialogContent className='max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl'><DialogHeader><DialogTitle>{editor?.editing ? '编辑授权' : '添加授权'}</DialogTitle><DialogDescription>Full access 仅显式全选当前允许的 scope，不包含未来新增权限。</DialogDescription></DialogHeader>
      {editor && <form className='space-y-4' onSubmit={event => { event.preventDefault(); void save() }}>
        <div className='grid gap-4 sm:grid-cols-2'><div className='space-y-2'><Label htmlFor='grant-user'>用户</Label><select id='grant-user' className='flex h-9 w-full rounded-md border bg-background px-3 text-sm' value={editor.user} required disabled={editor.editing || busy} onChange={event => setEditor({...editor, user: event.target.value})}><option value=''>选择用户</option>{users.data?.filter(item => item.is_active).map(item => <option key={item.id} value={item.id}>{item.username} · {item.role}</option>)}</select></div><div className='space-y-2'><Label htmlFor='grant-bot'>Bot / Channel</Label><select id='grant-bot' className='flex h-9 w-full rounded-md border bg-background px-3 text-sm' value={editor.bot} required disabled={editor.editing || busy} onChange={event => setEditor({...editor, bot: event.target.value, scopes: [], all: false, conversations: []})}><option value=''>选择 Bot</option>{channels.map(channel => <option key={channel.bot_id} value={channel.bot_id}>{channel.name}</option>)}</select></div></div>
        <fieldset className='space-y-3'><legend className='mb-2 text-sm font-medium'>Scope</legend><div className='flex items-center gap-2'><Checkbox id='grant-full' checked={scopeOptions.length > 0 && scopeOptions.every(scope => editor.scopes.includes(scope))} disabled={!editor.bot} onCheckedChange={checked => setEditor({...editor, scopes: checked ? [...scopeOptions] : []})} /><Label htmlFor='grant-full'>Full access（当前允许的全部 scope）</Label></div><div className='grid gap-2 sm:grid-cols-2'>{scopeOptions.map(scope => <div key={scope} className='flex items-center gap-2'><Checkbox id={`grant-${scope}`} checked={editor.scopes.includes(scope)} onCheckedChange={checked => setEditor({...editor, scopes: checked ? [...editor.scopes, scope] : editor.scopes.filter(item => item !== scope)})} /><Label htmlFor={`grant-${scope}`} className='font-normal'>{scope}</Label></div>)}</div></fieldset>
        <ConversationPicker models={active?.models ?? []} all={editor.all} selected={editor.conversations} allowAll={user?.role === 'Owner' || ownGrant?.all_conversations === true} onChange={(all, conversations) => setEditor({...editor, all, conversations})} />
        <DialogFooter><Button variant='outline' type='button' disabled={busy} onClick={() => setEditor(null)}>取消</Button><Button type='submit' disabled={busy || !editor.bot || !editor.user}>{busy ? '保存中…' : '保存授权'}</Button></DialogFooter>
      </form>}
    </DialogContent></Dialog>
    <ConfirmDeleteDialog open={disable !== null} onOpenChange={open => { if (!open) setDisable(null) }} title='停用授权？' description={`用户 #${disable?.user_id} · Bot #${disable?.bot_id} 的 Key、订阅和下级委派将失效。`} onConfirm={disableGrant} />
  </div>
}
