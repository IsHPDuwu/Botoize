import { useState } from 'react'
import { ChevronRight, Layers3, Pencil, Plus, Save, Server, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { management, type UpstreamInterface, type UpstreamProvider, type ConversationModel } from '@/lib/qq-api'
import { cn } from '@/lib/utils'

type ModelRow = ConversationModel
type ChannelRow = { id?: number; bot_id?: number; name: string; base_url: string; interface_type: string; app_id: string; secret?: string; is_active: boolean; models: ModelRow[] }
type Form = { name: string; channels: ChannelRow[] }
const emptyChannel = (): ChannelRow => ({ name: '', base_url: 'https://api.bot.qq.com', interface_type: 'qq_official_websocket', app_id: '', secret: '', is_active: true, models: [] })
const emptyModel = (): ModelRow => ({ name: '', isDirect: false, groupid: '' })

export function ProviderDialog({ current, interfaces, onClose, onSaved }: {
  current: UpstreamProvider | null; interfaces: UpstreamInterface[]; onClose: () => void; onSaved: () => Promise<void>
}) {
  const [form, setForm] = useState<Form>(() => current ? {
    name: current.name, channels: current.channels.map(channel => ({ ...channel, secret: '', models: channel.models.map(model => ({ ...model })) })),
  } : { name: '', channels: [emptyChannel()] })
  const [initial] = useState(() => JSON.stringify(form))
  const [section, setSection] = useState<'provider' | 'channels'>('provider')
  const [selected, setSelected] = useState(0)
  const [saving, setSaving] = useState(false)
  const [discard, setDiscard] = useState(false)
  const [mobileChannelOpen, setMobileChannelOpen] = useState(false)
  const [modelEditor, setModelEditor] = useState<{ index: number; value: ModelRow } | null>(null)
  const active = form.channels[selected]
  const dirty = JSON.stringify(form) !== initial
  const requestClose = () => { if (saving) return; if (dirty) setDiscard(true); else onClose() }
  const updateChannel = (patch: Partial<ChannelRow>) => setForm(previous => ({ ...previous, channels: previous.channels.map((channel, index) => index === selected ? { ...channel, ...patch } : channel) }))

  async function save() {
    if (!form.name.trim() || form.channels.some(channel => !channel.name.trim() || !channel.app_id.trim() || (!channel.id && !channel.secret))) {
      toast.error('请填写名称、AppID 和新渠道的 AppSecret'); return
    }
    setSaving(true)
    try {
      await management(current ? `providers/${current.id}/` : 'providers/', form, undefined, current ? 'PATCH' : 'POST')
      await onSaved()
      toast.success('服务提供商已保存')
      onClose()
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : '保存失败') }
    finally { setSaving(false) }
  }

  const sections = [
    { id: 'provider' as const, icon: Server, label: 'Provider', summary: form.name || '未命名服务提供商' },
    { id: 'channels' as const, icon: Layers3, label: 'Channels', summary: String(form.channels.length) },
  ]
  return <>
    <Dialog open onOpenChange={next => { if (!next) requestClose() }}>
      <DialogContent className='flex h-[calc(100dvh-2rem)] w-screen max-w-none flex-col gap-0 overflow-hidden rounded-none border-0 p-0 sm:h-[94vh] sm:w-[96vw] sm:max-w-[1500px] sm:rounded-xl sm:border [&>button:last-child]:right-2 [&>button:last-child]:top-2 [&>button:last-child]:flex [&>button:last-child]:size-10 [&>button:last-child]:items-center [&>button:last-child]:justify-center [&>div:first-child]:h-full [&>div:first-child]:min-h-0 [&>div:first-child]:flex-1 [&>div:first-child]:gap-0 [&>div:first-child]:overflow-hidden' onPointerDownOutside={event => event.preventDefault()}>
        <DialogHeader className='shrink-0 border-b bg-background py-3 pl-4 pr-16 text-left sm:pl-6 sm:pr-16'>
          <DialogTitle className='truncate text-base sm:text-lg'>{current ? '编辑服务提供商' : '添加服务提供商'}{form.name && <span className='font-normal text-muted-foreground'> · {form.name}</span>}</DialogTitle>
          <DialogDescription className='mt-0.5 hidden sm:block'>Provider 是服务提供商，Channel 是 Bot，Models 是单聊或群聊会话。</DialogDescription>
        </DialogHeader>
        <div className='flex min-h-0 flex-1'>
          <nav className='hidden w-56 shrink-0 flex-col gap-1 border-r bg-muted/20 p-3 lg:flex' aria-label='编辑分区'>
            {sections.map(item => <button key={item.id} type='button' onClick={() => setSection(item.id)} className={cn('flex min-h-14 items-center gap-3 rounded-lg px-3 text-left transition-colors', section === item.id ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted hover:text-foreground')}><item.icon className='size-4 shrink-0' /><span className='min-w-0 flex-1'><span className='block text-sm font-medium'>{item.label}</span><span className='block truncate text-xs opacity-70'>{item.summary}</span></span><ChevronRight className='size-4 shrink-0 opacity-50' /></button>)}
          </nav>
          <div className='flex min-w-0 flex-1 flex-col'>
            <div className='flex shrink-0 gap-1 overflow-x-auto border-b bg-background px-3 py-2 lg:hidden'>{sections.map(item => <Button key={item.id} size='sm' variant={section === item.id ? 'secondary' : 'ghost'} onClick={() => { setSection(item.id); setMobileChannelOpen(false) }}>{item.label}</Button>)}</div>
            <div className={cn('min-h-0 flex-1', section === 'channels' ? 'flex flex-col overflow-hidden' : 'overflow-y-auto')}>
              {section === 'provider' ? <div className='mx-auto flex w-full max-w-3xl flex-col gap-6 p-4 sm:p-6'><div><h3 className='text-lg font-semibold'>基本信息</h3><p className='mt-1 text-sm text-muted-foreground'>服务提供商包含一个或多个上游渠道。</p></div><div className='grid gap-5 rounded-xl border bg-card p-4 sm:p-5'><Label htmlFor='provider-name'>名称</Label><Input id='provider-name' value={form.name} maxLength={120} onChange={event => setForm({ ...form, name: event.target.value })} placeholder='生产环境' /></div></div> :
                <div className='grid h-full min-h-0 flex-1 lg:grid-cols-[300px_minmax(0,1fr)]'>
                  <div className={cn('flex h-full min-h-0 min-w-0 flex-col overflow-hidden border-r bg-muted/10', mobileChannelOpen ? 'hidden lg:flex' : 'flex')}>
                    <div className='flex shrink-0 items-center justify-between border-b px-4 py-3'><div><h3 className='font-semibold'>Channels</h3><p className='text-xs text-muted-foreground'>每个渠道对应一个 Bot</p></div><Button size='icon' variant='outline' aria-label='添加渠道' onClick={() => { setForm({ ...form, channels: [...form.channels, { ...emptyChannel(), name: `Bot ${form.channels.length + 1}` }] }); setSelected(form.channels.length); setMobileChannelOpen(true) }}><Plus /></Button></div>
                    <div className='min-h-0 flex-1 overflow-y-auto pt-2'>{form.channels.map((channel, index) => <div key={channel.id ?? `new-${index}`} className='px-2 pb-1'><button type='button' onClick={() => { setSelected(index); setMobileChannelOpen(true) }} className={cn('flex min-h-16 w-full items-center gap-3 rounded-lg border-l-2 px-3 py-2 text-left transition-colors', selected === index ? 'border-l-primary bg-primary/10' : 'border-l-transparent hover:bg-muted')}><div className='min-w-0 flex-1'><p className='truncate text-sm font-medium'>{channel.name || '未命名渠道'}</p><p className='mt-1 text-xs text-muted-foreground'>{interfaces.find(item => item.interface_type === channel.interface_type)?.label ?? channel.interface_type} · {channel.models.length} 个模型</p></div><ChevronRight className='size-4 shrink-0 text-muted-foreground' /></button></div>)}</div>
                  </div>
                  <div className={cn('min-h-0 min-w-0 overflow-y-auto', mobileChannelOpen ? 'block' : 'hidden lg:block')}>
                    {active && <div className='mx-auto flex w-full max-w-5xl flex-col gap-6 p-4 pb-8 sm:p-6'>
                      <div className='flex items-center justify-between gap-3'><div><Button variant='ghost' size='sm' className='lg:hidden' onClick={() => setMobileChannelOpen(false)}>返回渠道</Button><h3 className='text-lg font-semibold'>{active.name || '未命名渠道'}</h3></div>{!active.id && form.channels.length > 1 && <Button size='icon' variant='ghost' aria-label='删除未保存渠道' onClick={() => { setForm({ ...form, channels: form.channels.filter((_, index) => index !== selected) }); setSelected(0) }}><Trash2 /></Button>}</div>
                      <section className='flex flex-col gap-4 rounded-xl border bg-card p-4 sm:p-5'><div className='flex items-center gap-2'><Server className='size-4 text-primary' /><h4 className='font-medium'>连接配置</h4></div><div className='grid gap-4 sm:grid-cols-2'>
                        <div className='space-y-2'><Label htmlFor='channel-name'>渠道名称</Label><Input id='channel-name' value={active.name} maxLength={120} onChange={event => updateChannel({ name: event.target.value })} /></div>
                        <div className='space-y-2'><Label htmlFor='channel-interface'>接口类型</Label><Select value={active.interface_type} onValueChange={interface_type => updateChannel({ interface_type })}><SelectTrigger id='channel-interface'><SelectValue /></SelectTrigger><SelectContent>{interfaces.map(item => <SelectItem key={item.interface_type} value={item.interface_type} disabled={!item.implemented}>{item.label}</SelectItem>)}</SelectContent></Select></div>
                        <div className='space-y-2 sm:col-span-2'><Label htmlFor='channel-base-url'>Base URL</Label><Input id='channel-base-url' type='url' required value={active.base_url} placeholder='https://api.bot.qq.com' onChange={event => updateChannel({ base_url: event.target.value })} /><p className='text-xs text-muted-foreground'>上游 HTTPS 基础地址，可包含路径前缀。凭据和 API 请求均发送至此地址，仅使用可信上游。</p></div>
                        <div className='space-y-2'><Label htmlFor='channel-app-id'>AppID</Label><Input id='channel-app-id' value={active.app_id} maxLength={100} autoComplete='off' onChange={event => updateChannel({ app_id: event.target.value })} /></div>
                        <div className='space-y-2'><Label htmlFor='channel-secret'>AppSecret</Label><Input id='channel-secret' type='password' autoComplete='new-password' value={active.secret ?? ''} maxLength={4096} placeholder={active.id ? '留空保留已有密钥' : '新 Bot 必填'} onChange={event => updateChannel({ secret: event.target.value })} /></div>
                        <div className='flex items-center justify-between gap-3 sm:col-span-2'><Label htmlFor='channel-enabled'>启用 Bot</Label><Switch id='channel-enabled' checked={active.is_active} onCheckedChange={is_active => updateChannel({ is_active })} /></div>
                      </div></section>
                      <section className='flex flex-col gap-4 rounded-xl border bg-card p-4 sm:p-5'><div className='flex flex-wrap items-center justify-between gap-3'><div><h4 className='font-medium'>Models · 会话</h4><p className='text-xs text-muted-foreground'>历史事件回填、实时事件发现，或显式配置已知 OpenID；无法枚举未知群/用户。</p></div><div className='flex gap-2'><Button variant='outline' size='sm' disabled={!active.id || saving} onClick={() => { const channelId = active.id; setSaving(true); void management<{models: ModelRow[]; created: number}>(`channels/${channelId}/sync/`, {}).then(result => { setForm(previous => ({ ...previous, channels: previous.channels.map(channel => channel.id === channelId ? { ...channel, models: [...channel.models, ...result.models.filter(model => !channel.models.some(existing => existing.isDirect === model.isDirect && (existing.userid ?? existing.groupid) === (model.userid ?? model.groupid)))] } : channel) })); toast.success(`已从历史事件回填 ${result.created} 个会话`) }).catch(reason => toast.error(reason instanceof Error ? reason.message : '回填失败')).finally(() => setSaving(false)) }}>同步历史会话</Button><Button size='sm' onClick={() => setModelEditor({ index: -1, value: emptyModel() })}><Plus />添加会话</Button></div></div>
                        {active.models.length ? active.models.map((model, index) => <div key={model.id ?? `new-${index}`} className='flex items-center justify-between gap-3 rounded-lg border p-3'><div className='min-w-0'><p className='truncate text-sm font-medium'>{model.name || (model.isDirect ? '单聊' : '群聊')}</p><p className='truncate font-mono text-xs text-muted-foreground'>{model.isDirect ? 'userid' : 'groupid'}: {model.userid ?? model.groupid}</p></div><div className='flex items-center gap-2'><Button variant='ghost' size='icon' aria-label={`编辑 ${model.name || '会话'}`} onClick={() => setModelEditor({ index, value: { ...model } })}><Pencil /></Button>{!model.id && <Button variant='ghost' size='icon' aria-label='删除未保存会话' onClick={() => updateChannel({ models: active.models.filter((_, i) => i !== index) })}><Trash2 /></Button>}</div></div>) : <p className='py-6 text-center text-sm text-muted-foreground'>暂无已发现或配置的会话</p>}
                      </section>
                    </div>}
                  </div>
                </div>}
            </div>
          </div>
        </div>
        <DialogFooter className='shrink-0 flex-row flex-wrap items-center justify-between gap-2 border-t bg-background px-4 py-3 sm:px-6'><p className='hidden text-xs text-muted-foreground sm:block'>{dirty ? '有未保存的更改' : '没有未保存的更改'}</p><div className='ml-auto flex flex-wrap items-center gap-2'><Button variant='outline' onClick={requestClose} disabled={saving}>取消</Button><Button onClick={() => void save()} disabled={saving}><Save />{saving ? '保存中…' : '保存'}</Button></div></DialogFooter>
      </DialogContent>
    </Dialog>
    <AlertDialog open={discard} onOpenChange={setDiscard}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>放弃未保存的更改？</AlertDialogTitle><AlertDialogDescription>未保存的配置将会丢失。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>继续编辑</AlertDialogCancel><AlertDialogAction onClick={onClose}>放弃更改</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
    <Dialog open={!!modelEditor} onOpenChange={next => { if (!next) setModelEditor(null) }}><DialogContent><DialogHeader><DialogTitle>{modelEditor?.value.id ? '编辑会话' : '添加已知会话'}</DialogTitle><DialogDescription>使用此 Bot 已知的上游 OpenID，不是 QQ 号或 OneBot 虚拟 ID。</DialogDescription></DialogHeader>{modelEditor && <form onSubmit={event => { event.preventDefault(); if (!active) return; const models = [...active.models]; if (modelEditor.index < 0) models.push(modelEditor.value); else models[modelEditor.index] = modelEditor.value; updateChannel({ models }); setModelEditor(null) }} className='space-y-4'>
      <div className='space-y-2'><Label htmlFor='model-name'>会话名称</Label><Input id='model-name' value={modelEditor.value.name} maxLength={120} onChange={event => setModelEditor({ ...modelEditor, value: { ...modelEditor.value, name: event.target.value } })} /></div>
      <div className='flex items-center justify-between'><Label htmlFor='model-direct'>单聊（isDirect）</Label><Switch id='model-direct' disabled={!!modelEditor.value.id} checked={modelEditor.value.isDirect} onCheckedChange={isDirect => setModelEditor({ ...modelEditor, value: { id: modelEditor.value.id, name: modelEditor.value.name, isDirect, ...(isDirect ? { userid: '' } : { groupid: '' }) } })} /></div>
      <div className='space-y-2'><Label htmlFor='model-target'>{modelEditor.value.isDirect ? 'userid' : 'groupid'}</Label><Input id='model-target' value={modelEditor.value.userid ?? modelEditor.value.groupid ?? ''} maxLength={128} pattern='[A-Za-z0-9_-]+' required disabled={!!modelEditor.value.id} onChange={event => setModelEditor({ ...modelEditor, value: { ...modelEditor.value, [modelEditor.value.isDirect ? 'userid' : 'groupid']: event.target.value } })} /></div><DialogFooter><Button type='button' variant='outline' onClick={() => setModelEditor(null)}>取消</Button><Button type='submit'>确认</Button></DialogFooter>
    </form>}</DialogContent></Dialog>
  </>
}
