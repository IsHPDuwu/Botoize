import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import type { ConversationModel } from '@/lib/qq-api'

export function ConversationPicker({ models, all, selected, allowAll, onChange }: {
  models: ConversationModel[]; all: boolean; selected: number[]; allowAll: boolean
  onChange: (all: boolean, ids: number[]) => void
}) {
  const ids = models.flatMap(model => model.id === undefined ? [] : [model.id])
  return <fieldset className='space-y-3 rounded-lg border p-4'>
    <legend className='px-1 text-sm font-medium'>Models · 会话范围</legend>
    <div className='flex items-center gap-2'><Checkbox id='conversations-select-current' checked={!all && ids.length > 0 && ids.every(id => selected.includes(id))} disabled={!ids.length} onCheckedChange={checked => onChange(false, checked ? ids : [])} /><Label htmlFor='conversations-select-current' className='font-normal'>全选当前可见会话</Label></div>
    {allowAll && <div className='flex items-center gap-2'><Checkbox id='conversations-all' checked={all} onCheckedChange={checked => onChange(checked === true, [])} /><Label htmlFor='conversations-all' className='font-normal'>全部会话（包括未来发现的会话）</Label></div>}
    <div className='max-h-52 space-y-2 overflow-y-auto'>
      {models.map(model => model.id !== undefined && <div key={model.id} className='flex min-w-0 items-center gap-2'><Checkbox id={`conversation-${model.id}`} checked={all || selected.includes(model.id)} disabled={all} onCheckedChange={checked => onChange(false, checked ? [...selected, model.id!] : selected.filter(id => id !== model.id))} /><Label htmlFor={`conversation-${model.id}`} className='min-w-0 break-all font-normal'>{model.name || (model.isDirect ? '单聊' : '群聊')} · {model.isDirect ? 'userid' : 'groupid'}: {model.userid ?? model.groupid}</Label></div>)}
      {!models.length && <p className='text-sm text-muted-foreground'>暂无授权内可选会话。未选择任何会话时，不能发送消息或读取会话事件。</p>}
    </div>
  </fieldset>
}
