import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, Search, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { ApiCallFilters } from '@/lib/qq-api'
import { DateRangePicker } from '@/pages/request-logs/date-range-picker'

export function LogFilters({onApply}: {onApply: (filters: ApiCallFilters) => void}) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(true)
  const [draft, setDraft] = useState<ApiCallFilters>({})
  const [error, setError] = useState('')
  const update = (key: keyof ApiCallFilters, value: string) => setDraft({...draft, [key]:value})
  function apply(event: React.FormEvent) {
    event.preventDefault()
    const value = {...draft}
    for (const key of ['from', 'to'] as const) if (value[key]) value[key] = new Date(value[key]).toISOString()
    if (value.from && value.to && value.from >= value.to) { setError('开始时间必须早于结束时间'); return }
    setError(''); onApply(value)
  }
  return <form onSubmit={apply} className="space-y-2 rounded-lg border bg-card p-3">
    <div className="flex flex-wrap items-center gap-2"><div className="relative w-full sm:w-72"><Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground"/><Input className="pl-9" placeholder="搜索 Request ID、Bot、用户或操作" aria-label="搜索日志" value={draft.search ?? ''} onChange={event => update('search', event.target.value)} /></div>
      <Button variant="outline" type="submit" size="sm">应用筛选</Button><Button variant="ghost" type="button" size="sm" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}><ChevronDown className={expanded ? 'rotate-180' : ''}/>筛选</Button>
      <Button variant="ghost" type="button" size="sm" onClick={() => { setDraft({}); setError(''); onApply({}) }}><X/>清除</Button></div>
    {expanded && <div className="flex flex-wrap items-end gap-2 pt-1">
      {([['username','操作用户'],['path','操作路径'],['bot','Bot ID'],['api_key','Key ID']] as const).map(([key,label]) => <div key={key} className="w-36 space-y-1"><Label htmlFor={`log-${key}`} className="text-xs">{label}</Label><Input id={`log-${key}`} value={draft[key] ?? ''} type={key === 'bot' || key === 'api_key' ? 'number' : 'text'} min="1" onChange={event => update(key,event.target.value)} /></div>)}
      {([['method','方法',['GET','POST','PUT','PATCH','DELETE','WS']],['status','HTTP 状态',['2xx','3xx','4xx','5xx','200','401','403','429','500','502']],['replayed','幂等重放',['true','false']]] as const).map(([key,label,options]) => <div key={key} className="w-32 space-y-1"><Label className="text-xs">{label}</Label><Select value={draft[key] || 'all'} onValueChange={value => update(key,value === 'all' ? '' : value)}><SelectTrigger aria-label={label}><SelectValue/></SelectTrigger><SelectContent><SelectItem value="all">全部</SelectItem>{options.map(value => <SelectItem key={value} value={value}>{value === 'true' ? '仅重放' : value === 'false' ? '非重放' : value}</SelectItem>)}</SelectContent></Select></div>)}
      <div className="space-y-1"><p className="text-xs text-muted-foreground">时间范围（本地，含开始不含结束）</p><DateRangePicker key={`${draft.from ?? ''}/${draft.to ?? ''}`} from={draft.from ? new Date(draft.from) : undefined} to={draft.to ? new Date(draft.to) : undefined} onChange={(from,to) => setDraft({...draft,from:from?.toISOString() ?? '',to:to?.toISOString() ?? ''})} t={t}/></div>
    </div>}{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </form>
}
