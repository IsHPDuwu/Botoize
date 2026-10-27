import { useState } from 'react'
import { Layers3, Pencil, Plus, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DataList, DataListBody, DataListCell, DataListHead, DataListHeader, DataListRow } from '@/components/ui/data-list'
import { management, type UpstreamChannel, type UpstreamProvider, type ChannelGroupMatch } from '@/lib/qq-api'

// Reuses the ChannelModelEditor Dialog/list pattern and the existing Provider Channels section layout.
export function CompanionSection({ channel, providers, providerId, dirty, onChange }: {
  channel: UpstreamChannel; providers: UpstreamProvider[]; providerId?: number; dirty: boolean;
  onChange: (patch: Partial<UpstreamChannel>) => void
}) {
  const [editor, setEditor] = useState<{index: number; value: ChannelGroupMatch} | null>(null)
  const [loading, setLoading] = useState(false)
  const matches = channel.group_matches ?? []
  const candidates = providers.filter(p => p.id !== providerId).flatMap(p => p.channels.filter(c => c.id !== channel.id && c.interface_type.startsWith('onebot_') && !c.companion_channel).map(c => ({...c, providerName:p.name})))
  const companion = candidates.find(c => c.id === channel.companion_channel)
  async function refresh() {
    if (!channel.id) return
    setLoading(true)
    try {
      const result = await management<{matches:ChannelGroupMatch[];created:number}>(`channels/${channel.id}/companion/refresh/`, {})
      onChange({group_matches:result.matches})
      toast.success(`匹配已刷新，新增 ${result.created} 个群聊`)
    } catch(reason) { toast.error(reason instanceof Error ? reason.message : '匹配刷新失败') }
    finally { setLoading(false) }
  }
  return <section className='flex flex-col gap-4 rounded-xl border bg-card p-4 sm:p-5'>
    <div className='flex items-center gap-2'><Layers3 className='size-4 text-primary'/><h4 className='font-medium'>主从协作 · 群聊匹配</h4></div>
    <div className='space-y-2'><Label htmlFor='channel-companion'>从机 Channel</Label><Select value={channel.companion_channel ? String(channel.companion_channel) : 'none'} onValueChange={value => onChange({companion_channel:value === 'none' ? null : Number(value),group_matches:[]})}><SelectTrigger id='channel-companion'><SelectValue placeholder='不使用从机'/></SelectTrigger><SelectContent><SelectItem value='none'>不使用从机</SelectItem>{candidates.map(c => <SelectItem key={c.id} value={String(c.id)}>{c.providerName} / {c.name} · {c.app_id}</SelectItem>)}</SelectContent></Select><p className='text-xs text-muted-foreground'>选择其他 Provider 的 OneBot Channel。优先接收从机消息；未匹配、离线或漏收时逐条回退主机。发送只走主机，管理动作先主机、失败再尝试从机。</p></div>
    {channel.companion_channel && <>
      <div className='flex flex-wrap items-center justify-between gap-3'><div><h4 className='font-medium'>已匹配群聊</h4><p className='text-xs text-muted-foreground'>唯一同名群自动匹配；重名群通过时间接近且内容一致的消息确认。可以手动新增、纠正或停用。</p></div><div className='flex gap-2'><Button size='sm' variant='outline' disabled={!channel.id || dirty || loading} title={dirty ? '请先保存更改后重新打开' : '读取群名称、匹配历史消息并补齐真实 ID'} onClick={() => void refresh()}><RefreshCw className={loading ? 'animate-spin' : ''}/>刷新匹配</Button><Button size='sm' onClick={() => setEditor({index:-1,value:{primary_group:'',companion_group:'',name:'',enabled:true}})}><Plus/>添加匹配</Button></div></div>
      {matches.length ? <DataList columns='minmax(0,1fr) minmax(0,1fr) 5rem 5rem'><DataListHeader><DataListHead>主机群 / 名称</DataListHead><DataListHead>从机群 ID</DataListHead><DataListHead>来源</DataListHead><DataListHead align='end'>操作</DataListHead></DataListHeader><DataListBody>{matches.map((match,index) => <DataListRow key={match.id ?? `draft-${index}`}><DataListCell primary><span className='block truncate font-medium'>{match.name || '未命名群聊'}</span><span className='block truncate font-mono text-xs text-muted-foreground' title={match.primary_group}>{match.primary_group}</span></DataListCell><DataListCell label='从机群 ID'><span className='block truncate font-mono text-xs' title={match.companion_group}>{match.companion_group}</span>{!match.enabled && <Badge variant='secondary'>已停用</Badge>}</DataListCell><DataListCell label='来源'>{({name:'群名',message:'消息',manual:'手动'}[match.origin ?? 'manual']) ?? match.origin}</DataListCell><DataListCell label='操作' align='end'><Button size='icon' variant='ghost' aria-label={`编辑匹配 ${match.name || match.primary_group}`} onClick={() => setEditor({index,value:{...match}})}><Pencil/></Button></DataListCell></DataListRow>)}</DataListBody></DataList> : <p className='py-6 text-center text-sm text-muted-foreground'>暂无匹配，主机继续接收消息。</p>}
    </>}
    <Dialog open={!!editor} onOpenChange={open => { if(!open) setEditor(null) }}><DialogContent><DialogHeader><DialogTitle>{editor && editor.index < 0 ? '添加群聊匹配' : '编辑群聊匹配'}</DialogTitle><DialogDescription>使用两边的上游原始群 ID。手动修正会使主机旧 Key 失效，需要重新授权。</DialogDescription></DialogHeader>{editor && <form className='space-y-4' onSubmit={event => {event.preventDefault(); const next = [...matches]; if(editor.index < 0) next.push({...editor.value,origin:'manual'}); else next[editor.index] = {...editor.value,origin:'manual'}; onChange({group_matches:next}); setEditor(null)}}>
      <div className='space-y-2'><Label htmlFor='match-name'>群聊名称</Label><Input id='match-name' maxLength={120} value={editor.value.name} onChange={event => setEditor({...editor,value:{...editor.value,name:event.target.value}})}/></div>
      <div className='space-y-2'><Label htmlFor='match-primary'>主机群 ID</Label><Input id='match-primary' required maxLength={256} value={editor.value.primary_group} list='match-primary-groups' onChange={event => setEditor({...editor,value:{...editor.value,primary_group:event.target.value}})}/><datalist id='match-primary-groups'>{channel.models.filter(m => !m.isDirect).map(m => <option key={m.groupid} value={m.groupid}>{m.name}</option>)}</datalist></div>
      <div className='space-y-2'><Label htmlFor='match-companion'>从机群 ID</Label><Input id='match-companion' required maxLength={256} value={editor.value.companion_group} list='match-companion-groups' onChange={event => setEditor({...editor,value:{...editor.value,companion_group:event.target.value}})}/><datalist id='match-companion-groups'>{companion?.models.filter(m => !m.isDirect).map(m => <option key={m.groupid} value={m.groupid}>{m.name}</option>)}</datalist></div>
      <div className='flex items-center justify-between'><Label htmlFor='match-enabled'>启用匹配</Label><Switch id='match-enabled' checked={editor.value.enabled} onCheckedChange={enabled => setEditor({...editor,value:{...editor.value,enabled}})}/></div><DialogFooter><Button type='button' variant='outline' onClick={() => setEditor(null)}>取消</Button><Button type='submit'>确认</Button></DialogFooter>
    </form>}</DialogContent></Dialog>
  </section>
}
