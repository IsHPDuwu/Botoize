import { Check, RefreshCw, ShieldCheck, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/ui/page-header";
import { QueryError } from "@/components/ui/query-error";
import { StatusBadge } from "@/components/ui/status";
import { management } from "@/lib/qq-api";
import { useQQBots, useQQGrants, useQQUsers } from "@/lib/qq-swr";

const scopeOptions = ["events:read", "messages:send", "messages:delete", "media:upload", "query:read"];

export function GroupsPage() {
  const bots = useQQBots();
  const grants = useQQGrants();
  const users = useQQUsers();
  const [userId, setUserId] = useState("");
  const [botId, setBotId] = useState("");
  const [scopes, setScopes] = useState<string[]>(["events:read"]);
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function saveGrant(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true); setNotice("");
    try {
      await management("grants/", { user: Number(userId), bot: Number(botId), scopes, is_active: true, password });
      setPassword("");
      await Promise.all([grants.mutate(), users.mutate()]);
      setNotice("Bot 授权已保存，版本号已由服务端递增。");
    } catch (reason) { setNotice(reason instanceof Error ? reason.message : "保存授权失败"); }
    finally { setBusy(false); }
  }

  async function disableGrant(grant: { user_id?: number; bot_id?: number; scopes: string[] }) {
    const confirmation = window.prompt("输入当前密码以停用授权");
    if (!confirmation || !grant.user_id || !grant.bot_id) return;
    setBusy(true); setNotice("");
    try { await management("grants/", { user: grant.user_id, bot: grant.bot_id, scopes: grant.scopes, is_active: false, password: confirmation }); await grants.mutate(); setNotice("授权已停用。"); }
    catch (reason) { setNotice(reason instanceof Error ? reason.message : "停用授权失败"); }
    finally { setBusy(false); }
  }

  const error = bots.error ?? grants.error ?? users.error;
  const reload = async () => { await Promise.all([bots.mutate(), grants.mutate(), users.mutate()]); };
  if (error && !grants.data) return <QueryError onRetry={reload} retrying={bots.isValidating || grants.isValidating || users.isValidating} />;
  return (
    <div className="flex min-h-0 flex-col gap-5 pb-8">
      <PageHeader title="分组管理" description="将 Bot 分配给控制台用户，并通过 scope 控制数据面能力。这里的分组沿用 QQ 授权语义，不是计费分组。" actions={<Button variant="outline" onClick={() => void reload()} disabled={grants.isValidating}><RefreshCw className={grants.isValidating ? "animate-spin" : ""} />刷新</Button>} />
      {notice && <p role="status" className="rounded-md border bg-muted/40 p-3 text-sm text-muted-foreground">{notice}</p>}
      <Card><CardHeader><CardTitle className="flex items-center gap-2"><UserPlus className="size-4" />添加或更新 Bot 授权</CardTitle><CardDescription>更新同一用户与 Bot 的授权会递增 revision，使旧 Key 和订阅快照失效。</CardDescription></CardHeader><CardContent><form onSubmit={saveGrant} className="grid gap-4 md:grid-cols-2"><div className="space-y-2"><Label htmlFor="grant-user">用户</Label><select id="grant-user" className="flex h-9 w-full rounded-md border border-border bg-background px-3 py-2 text-sm" value={userId} onChange={(event) => setUserId(event.target.value)}><option value="">选择用户</option>{(users.data ?? []).filter((user) => user.is_active).map((user) => <option key={user.id} value={user.id}>{user.username} · {user.role}</option>)}</select></div><div className="space-y-2"><Label htmlFor="grant-bot">Bot</Label><select id="grant-bot" className="flex h-9 w-full rounded-md border border-border bg-background px-3 py-2 text-sm" value={botId} onChange={(event) => setBotId(event.target.value)}><option value="">选择 Bot</option>{(bots.data ?? []).map((bot) => <option key={bot.id} value={bot.id}>{bot.name}</option>)}</select></div><fieldset className="space-y-2 md:col-span-2"><legend className="text-sm font-medium">scope</legend>{scopeOptions.map((scope) => <label key={scope} className="mr-4 inline-flex items-center gap-2 text-sm"><input type="checkbox" checked={scopes.includes(scope)} onChange={(event) => setScopes((current) => event.target.checked ? [...current, scope] : current.filter((item) => item !== scope))} />{scope}</label>)}</fieldset><div className="space-y-2"><Label htmlFor="grant-password">确认当前密码</Label><Input id="grant-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></div><div className="flex items-end"><Button variant="primary" type="submit" disabled={busy || !userId || !botId || !scopes.length}>{busy ? "保存中…" : "保存授权"}</Button></div></form></CardContent></Card>
      {grants.data?.length ? <section className="space-y-3" aria-label="授权列表">{grants.data.map((grant) => <Card key={grant.id ?? `${grant.user_id}-${grant.bot_id}`}><CardContent className="flex flex-wrap items-center justify-between gap-4 p-4"><div className="flex min-w-0 items-center gap-3"><span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted"><ShieldCheck className="size-4" /></span><div className="min-w-0"><p className="truncate text-sm font-medium">用户 #{grant.user_id} · Bot #{grant.bot_id}</p><p className="truncate text-xs text-muted-foreground">{grant.scopes.join("、") || "无数据面权限"} · revision {grant.revision}</p></div></div><div className="flex items-center gap-2"><StatusBadge variant={grant.is_active ? "success" : "warning"}>{grant.is_active ? "有效" : "已停用"}</StatusBadge>{grant.is_active && <Button size="sm" variant="outline" disabled={busy} onClick={() => void disableGrant(grant)}><Check />停用</Button>}</div></CardContent></Card>)}</section> : <EmptyState icon={<Users />} title="暂无授权记录" description="为用户分配 Bot 后，授权 revision 和 scope 会显示在这里。" />}
    </div>
  );
}
