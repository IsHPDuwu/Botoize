import { RefreshCw, UserRound, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { QueryError } from "@/components/ui/query-error";
import { StatusBadge } from "@/components/ui/status";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useQQUsers } from "@/lib/qq-swr";

export function UsersPage() {
  const { data, error, isLoading, isValidating, mutate } = useQQUsers();
  if (error && !data) return <QueryError onRetry={mutate} retrying={isValidating} />;
  return (
    <div className="flex min-h-0 flex-col gap-5 pb-8">
      <PageHeader title="Owner 用户管理" description="当前后端只提供 Owner 可见的用户列表；邀请、停用和角色修改尚未开放。" actions={<Button variant="outline" onClick={() => void mutate()} disabled={isValidating}><RefreshCw className={isValidating ? "animate-spin" : ""} />刷新</Button>} />
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Users className="size-4" />控制台用户</CardTitle><CardDescription>不会通过此页面修改 Owner 角色或账号状态。</CardDescription></CardHeader>
        <CardContent>
          {isLoading && !data ? <div className="space-y-3"><div className="h-8 animate-pulse rounded bg-muted"/><div className="h-8 animate-pulse rounded bg-muted"/></div> : data?.length ? <div className="overflow-x-auto"><Table><TableHeader><TableRow><TableHead>用户</TableHead><TableHead>角色</TableHead><TableHead>状态</TableHead></TableRow></TableHeader><TableBody>{data.map((user) => <TableRow key={user.id}><TableCell><div className="flex items-center gap-2"><UserRound className="size-4 text-muted-foreground"/><span className="font-medium">{user.username}</span></div></TableCell><TableCell>{user.role}</TableCell><TableCell><StatusBadge variant={user.is_active ? "success" : "warning"}>{user.is_active ? "有效" : "已停用"}</StatusBadge></TableCell></TableRow>)}</TableBody></Table></div> : <EmptyState variant="inline" icon={<Users />} title="暂无用户" description="没有可展示的控制台账号。" />}
        </CardContent>
      </Card>
    </div>
  );
}
