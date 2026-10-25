import { BadgeOverflowList } from '@/components/BadgeOverflowList'
import { Badge } from '@/components/ui/badge'

// Same compact restriction badges and overflow popover as the upstream key list.
export function PermissionBadges({scopes, all, count}: {scopes: string[]; all?: boolean; count: number}) {
  return <div className="flex min-w-0 flex-wrap items-center justify-end gap-1.5 [@container(min-width:56rem)]:justify-start">
    <BadgeOverflowList visibleCount={1} popoverOnSingle ariaLabel={`${scopes.length} 项权限`} items={scopes.map(scope => ({key:scope,
      collapsed: <Badge variant="outline" className="max-w-36 px-1.5 text-xs"><span className="truncate">{scope}</span></Badge>,
      full: <Badge variant="outline" className="max-w-none text-xs">{scope}</Badge>}))} />
    {!scopes.length && <Badge variant="outline">无权限</Badge>}
    <Badge variant="secondary" className="whitespace-nowrap text-xs">{all ? '全部会话（含未来）' : `${count} 个会话`}</Badge>
  </div>
}
