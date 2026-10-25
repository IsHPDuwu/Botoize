import { useState } from 'react'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

export function RequestId({value}: {value: string}) {
  const [feedback, setFeedback] = useState('')
  if (!value) return <span>—</span>
  async function copy() {
    try { await navigator.clipboard.writeText(value); setFeedback('已复制') }
    catch { setFeedback('复制失败') }
  }
  return <TooltipProvider delayDuration={150}><Tooltip><TooltipTrigger asChild>
    <button type="button" onClick={() => void copy()} aria-label={`复制 Request ID ${value.slice(0, 6)}`} className="font-mono text-xs text-muted-foreground hover:text-foreground">{value.slice(0, 6)}</button>
  </TooltipTrigger><TooltipContent className="max-w-80 break-all font-mono">{value}{feedback && <span className="ml-2 font-sans">{feedback}</span>}</TooltipContent></Tooltip></TooltipProvider>
}
