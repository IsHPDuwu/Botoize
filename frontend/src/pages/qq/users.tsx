import { useEffect, useState } from 'react'
import useSWR from 'swr'
import { Ban, MailPlus, Pencil, Plus, RefreshCw, UserRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CopyButton } from '@/components/ui/copy-button'
import { DataList, DataListActions, DataListBody, DataListCell, DataListHead, DataListHeader, DataListRow } from '@/components/ui/data-list'
import { DataTableShell, TableToolbarSearch } from '@/components/ui/data-table-shell'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PageHeader } from '@/components/ui/page-header'
import { QueryError } from '@/components/ui/query-error'
import { Skeleton } from '@/components/ui/skeleton'
import { StatusBadge } from '@/components/ui/status'
import { management, type UserSummary } from '@/lib/qq-api'
import { useQQUsers } from '@/lib/qq-swr'

type Draft = {id?: number; username: string; email: string; new_password: string}
type Invitation = {id:number; expires_at:string; used_at:string|null; accepted_by:number|null; created_at:string}

export function UsersPage() {
  const users = useQQUsers()
  const invitations = useSWR('qq/invitations', () => management<Invitation[]>('invitations/'))
  const [draft,setDraft] = useState<Draft|null>(null)
  const [target,setTarget] = useState<UserSummary|null>(null)
  const [query,setQuery] = useState('')
  const [notice,setNotice] = useState('')
  const [busy,setBusy] = useState(false)
  const [inviting,setInviting] = useState(false)
  const [hours,setHours] = useState('72')
  const [issued,setIssued] = useState('')
  const [revokeInvite,setRevokeInvite] = useState<number|null>(null)
  const [now,setNow] = useState(() => Date.now())
  useEffect(() => {const timer = window.setInterval(() => setNow(Date.now()), 30000);return () => window.clearInterval(timer)}, [])
  const reload = async () => {await Promise.all([users.mutate(),invitations.mutate()])}
  async function save(event: React.FormEvent) {
    event.preventDefault(); if (!draft) return
    setBusy(true); setNotice('')
    try {
      await management(draft.id ? `users/${draft.id}/` : 'users/', {username:draft.username, email:draft.email,
        ...(draft.new_password ? {new_password:draft.new_password} : {})}, undefined, draft.id ? 'PATCH' : 'POST')
      setDraft(null); setNotice('用户已保存。'); await reload()
    } catch(error) {setNotice(error instanceof Error ? error.message : '保存失败')}
    finally {setBusy(false)}
  }
  async function toggle() {
    if (!target) return
    setBusy(true)
    try {await management(`users/${target.id}/`,{is_active:!target.is_active},undefined,'PATCH');setTarget(null);await reload();setNotice('账号状态已更新；停用会撤销现有 Key，重新启用不会恢复旧 Key。')}
    catch(error) {setNotice(error instanceof Error ? error.message : '更新失败')}
    finally {setBusy(false)}
  }
  async function invite(event: React.FormEvent) {
    event.preventDefault();setBusy(true)
    try {const result = await management<{token:string}>('invitations/',{expires_hours:Number(hours)});setIssued(result.token);setInviting(false);await invitations.mutate()}
    catch(error) {setNotice(error instanceof Error ? error.message : '邀请失败')}
    finally {setBusy(false)}
  }
  async function revokeInvitation() {
    if (revokeInvite === null) return
    setBusy(true)
    try {await management(`invitations/${revokeInvite}/revoke/`, {});setRevokeInvite(null);await invitations.mutate();setNotice('邀请已失效。')}
    catch(error) {setNotice(error instanceof Error ? error.message : '撤销失败')}
    finally {setBusy(false)}
  }
  const visible = (users.data ?? []).filter(user => `${user.username} ${user.email}`.toLowerCase().includes(query.toLowerCase()))
  return <div className="flex min-h-0 flex-col gap-5 pb-8">
    <PageHeader title="用户管理" description="创建、编辑、重置密码和启停 Admin 账号，或签发一次性邀请。Owner 角色不可在网页中修改。" actions={<><Button variant="outline" onClick={() => void reload()} disabled={users.isValidating}><RefreshCw/>刷新</Button><Button variant="outline" onClick={() => setInviting(true)}><MailPlus/>邀请用户</Button><Button onClick={() => setDraft({username:'',email:'',new_password:''})}><Plus/>创建用户</Button></>}/>
    {notice && <p role="status" className="rounded-md border p-3 text-sm">{notice}</p>}
    {(users.error || invitations.error) && <QueryError onRetry={reload}/>}
    {issued && <div className="space-y-2 rounded-lg border p-4 text-sm"><p>一次性邀请凭证（仅此次显示），请通过可信渠道发给新用户。注册入口：{window.location.origin}/register</p><div className="flex gap-2"><Input type="password" readOnly value={issued} aria-label="邀请凭证"/><CopyButton value={issued} label="复制邀请凭证"/><Button variant="ghost" onClick={() => setIssued('')}>清除显示</Button></div></div>}
    {users.isLoading ? <Skeleton className="h-40"/> : <DataTableShell toolbar={<><TableToolbarSearch aria-label="搜索用户" placeholder="搜索用户名或邮箱" value={query} onChange={event => setQuery(event.target.value)}/><span className="text-sm text-muted-foreground">{visible.length} 位用户</span></>}>
      <DataList columns="minmax(0,1.6fr) 5rem 10rem 10rem 5rem 6rem"><DataListHeader><DataListHead>用户</DataListHead><DataListHead>角色</DataListHead><DataListHead>创建时间</DataListHead><DataListHead>最近登录</DataListHead><DataListHead>状态</DataListHead><DataListHead align="end">操作</DataListHead></DataListHeader><DataListBody>{visible.map(user => <DataListRow key={user.id}>
        <DataListCell primary><div className="flex min-w-0 items-center gap-3"><UserRound className="size-4 shrink-0 text-muted-foreground"/><div className="min-w-0 flex-1"><p className="truncate font-medium">{user.username}</p><p className="truncate text-xs text-muted-foreground">{user.email || '未设置邮箱'}</p></div></div></DataListCell><DataListCell label="角色">{user.role}</DataListCell><DataListCell label="创建时间"><span className="text-xs">{user.date_joined ? new Date(user.date_joined).toLocaleString() : '—'}</span></DataListCell><DataListCell label="最近登录"><span className="text-xs">{user.last_login ? new Date(user.last_login).toLocaleString() : '尚未登录'}</span></DataListCell><DataListCell label="状态"><StatusBadge variant={user.is_active ? 'success' : 'warning'}>{user.is_active ? '有效' : '已停用'}</StatusBadge></DataListCell><DataListActions><Button variant="ghost" size="icon" disabled={busy || user.role === 'Owner'} aria-label={`编辑用户 ${user.username}`} onClick={() => setDraft({id:user.id,username:user.username,email:user.email ?? '',new_password:''})}><Pencil/></Button><Button variant="ghost" size="icon" disabled={busy || user.role === 'Owner'} aria-label={`${user.is_active ? '停用' : '启用'}用户 ${user.username}`} onClick={() => setTarget(user)}><Ban/></Button></DataListActions>
      </DataListRow>)}</DataListBody></DataList>
    </DataTableShell>}
    <DataTableShell><div className="border-b px-4 py-3 text-sm font-medium">邀请记录</div><DataList columns="5rem minmax(0,1fr) 7rem 8rem 5rem"><DataListHeader><DataListHead>ID</DataListHead><DataListHead>到期时间</DataListHead><DataListHead>状态</DataListHead><DataListHead>接受用户</DataListHead><DataListHead align="end">操作</DataListHead></DataListHeader><DataListBody>{invitations.data?.map(invitation => <DataListRow key={invitation.id}><DataListCell primary>#{invitation.id}</DataListCell><DataListCell label="到期时间">{new Date(invitation.expires_at).toLocaleString()}</DataListCell><DataListCell label="状态">{invitation.used_at ? '已使用' : Date.parse(invitation.expires_at) <= now ? '已过期' : '待接受'}</DataListCell><DataListCell label="接受用户">{users.data?.find(user => user.id === invitation.accepted_by)?.username ?? '—'}</DataListCell><DataListActions><Button variant="ghost" size="sm" disabled={busy || !!invitation.used_at || Date.parse(invitation.expires_at) <= now} onClick={() => setRevokeInvite(invitation.id)}>撤销</Button></DataListActions></DataListRow>)}</DataListBody></DataList></DataTableShell>
    <Dialog open={!!draft} onOpenChange={open => {if(!open && !busy)setDraft(null)}}><DialogContent><DialogHeader><DialogTitle>{draft?.id ? '编辑用户' : '创建 Admin 用户'}</DialogTitle><DialogDescription>密码至少 12 字符。重置密码会使该账号现有登录会话失效；不修改 Owner 权限。</DialogDescription></DialogHeader>{draft && <form onSubmit={event => void save(event)} className="space-y-4"><div className="space-y-2"><Label htmlFor="user-name">用户名</Label><Input id="user-name" required maxLength={150} value={draft.username} onChange={event => setDraft({...draft,username:event.target.value})}/></div><div className="space-y-2"><Label htmlFor="user-email">邮箱</Label><Input id="user-email" type="email" value={draft.email} onChange={event => setDraft({...draft,email:event.target.value})}/></div><div className="space-y-2"><Label htmlFor="user-password">{draft.id ? '重置密码（留空不修改）' : '初始密码'}</Label><Input id="user-password" type="password" autoComplete="new-password" minLength={12} maxLength={256} required={!draft.id} value={draft.new_password} onChange={event => setDraft({...draft,new_password:event.target.value})}/></div><DialogFooter><Button type="button" variant="outline" onClick={() => setDraft(null)}>取消</Button><Button type="submit" disabled={busy}>保存用户</Button></DialogFooter></form>}</DialogContent></Dialog>
    <Dialog open={!!target} onOpenChange={open => {if(!open && !busy)setTarget(null)}}><DialogContent><DialogHeader><DialogTitle>{target?.is_active ? '停用用户？' : '启用用户？'}</DialogTitle><DialogDescription>{target?.username}：停用会禁止登录、撤销 Key 并使授权及其下级委派失效；不会删除历史记录。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setTarget(null)}>取消</Button><Button disabled={busy} onClick={() => void toggle()}>确认{target?.is_active ? '停用' : '启用'}</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={revokeInvite !== null} onOpenChange={open => {if(!open && !busy)setRevokeInvite(null)}}><DialogContent><DialogHeader><DialogTitle>撤销邀请？</DialogTitle><DialogDescription>邀请 #{revokeInvite} 将立即过期，未使用的凭证将无法再注册。不会删除历史记录。</DialogDescription></DialogHeader><DialogFooter><Button variant="outline" onClick={() => setRevokeInvite(null)}>取消</Button><Button disabled={busy} onClick={() => void revokeInvitation()}>确认撤销</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={inviting} onOpenChange={open => {if(!busy)setInviting(open)}}><DialogContent><DialogHeader><DialogTitle>邀请用户</DialogTitle><DialogDescription>凭证仅可使用一次，新账号固定为 Admin。</DialogDescription></DialogHeader><form onSubmit={event => void invite(event)} className="space-y-4"><Label htmlFor="invite-hours">有效时长（小时）</Label><Input id="invite-hours" type="number" min={1} max={720} value={hours} onChange={event => setHours(event.target.value)}/><DialogFooter><Button variant="outline" type="button" onClick={() => setInviting(false)}>取消</Button><Button disabled={busy} type="submit">生成邀请</Button></DialogFooter></form></DialogContent></Dialog>
  </div>
}
