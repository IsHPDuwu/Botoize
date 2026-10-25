import { Check, Copy, KeyRound, Plus, RefreshCw, ShieldAlert, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/ui/page-header";
import { QueryError } from "@/components/ui/query-error";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status";
import { management } from "@/lib/qq-api";
import { useQQKeys, useQQMyGrants } from "@/lib/qq-swr";

const dayOptions = [
  { value: "1", label: "1 天" },
  { value: "7", label: "7 天" },
  { value: "30", label: "30 天" },
  { value: "90", label: "90 天" },
  { value: "0", label: "不过期" },
];

export function TokensPage() {
  const [now] = useState(() => Date.now());
  const { data: keys, error, isLoading, isValidating, mutate: reloadKeys } = useQQKeys();
  const { data: grants } = useQQMyGrants();
  const [botId, setBotId] = useState("");
  const [name, setName] = useState("");
  const [lifetime, setLifetime] = useState("7");
  const [scopes, setScopes] = useState<string[]>([]);
  const [password, setPassword] = useState("");
  const [issuedToken, setIssuedToken] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const activeGrant = grants?.find((grant) => String(grant.bot?.id) === botId);

  async function createKey(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeGrant || !scopes.length) return;
    setBusy(true);
    setNotice("");
    setIssuedToken("");
    try {
      const expiresAt = lifetime === "0" ? null : new Date(Date.now() + Number(lifetime) * 86400000).toISOString();
      const result = await management<{ token: string }>("keys/", {
        bot: Number(botId), name, scopes, expires_at: expiresAt, password,
      });
      setIssuedToken(result.token);
      setName("");
      setPassword("");
      await reloadKeys();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "创建 Key 失败");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: number) {
    const confirmation = window.prompt("输入当前密码以撤销此 Key");
    if (!confirmation) return;
    setBusy(true);
    setNotice("");
    try {
      await management(`keys/${id}/revoke/`, { password: confirmation });
      await reloadKeys();
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "撤销 Key 失败");
    } finally {
      setBusy(false);
    }
  }

  if (error && !keys) return <QueryError onRetry={reloadKeys} retrying={isValidating} />;

  return (
    <div className="flex min-h-0 flex-col gap-5 pb-8">
      <PageHeader
        title="令牌管理"
        description="每个 API Key 固定绑定一个 Bot；权限受当前有效授权限制。"
        actions={<Button variant="outline" onClick={() => void reloadKeys()} disabled={isValidating}><RefreshCw className={isValidating ? "animate-spin" : ""} />刷新</Button>}
      />
      {notice && <p role="status" className="rounded-md border bg-muted/40 p-3 text-sm text-muted-foreground">{notice}</p>}
      {issuedToken && (
        <Card className="border-warning-border bg-warning-soft">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-warning-foreground"><ShieldAlert className="size-5" />新 Key 仅显示一次</CardTitle>
            <CardDescription>请立即复制并安全保存。关闭此提示后无法再次取回。</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            <Input readOnly type="password" value={issuedToken} aria-label="新建 API Key" className="min-w-0 flex-1 font-mono" />
            <Button variant="outline" onClick={() => void navigator.clipboard.writeText(issuedToken).then(() => setNotice("已复制 Key"), () => setNotice("复制失败，请手动选择 Key"))}><Copy />复制</Button>
            <Button variant="ghost" onClick={() => setIssuedToken("")}><Check />已保存，清除明文</Button>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Plus className="size-4" />创建单 Bot Key</CardTitle>
          <CardDescription>创建前需要当前账号对目标 Bot 具有有效授权。</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={createKey} className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="key-bot">绑定 Bot</Label>
              <Select value={botId} onValueChange={(value) => { setBotId(value); setScopes([]); setIssuedToken(""); }}>
                <SelectTrigger id="key-bot"><SelectValue placeholder="选择 Bot" /></SelectTrigger>
                <SelectContent>{(grants ?? []).map((grant) => grant.bot && <SelectItem key={grant.bot.id} value={String(grant.bot.id)}>{grant.bot.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-2"><Label htmlFor="key-name">Key 名称</Label><Input id="key-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required /></div>
            <div className="space-y-2">
              <Label htmlFor="key-lifetime">有效期</Label>
              <Select value={lifetime} onValueChange={setLifetime}>
                <SelectTrigger id="key-lifetime"><SelectValue /></SelectTrigger>
                <SelectContent>{dayOptions.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div className="space-y-2"><Label htmlFor="key-password">确认当前密码</Label><Input id="key-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></div>
            <fieldset className="space-y-2 md:col-span-2">
              <legend className="text-sm font-medium">允许的 scope</legend>
              {activeGrant?.scopes.map((scope) => (
                <label key={scope} className="mr-4 inline-flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={scopes.includes(scope)} onChange={(event) => setScopes((current) => event.target.checked ? [...current, scope] : current.filter((value) => value !== scope))} />{scope}
                </label>
              ))}
              {!activeGrant && <p className="text-sm text-muted-foreground">没有可用于创建 Key 的授权 Bot。</p>}
            </fieldset>
            <div className="md:col-span-2"><Button variant="primary" type="submit" disabled={busy || !activeGrant || !scopes.length}>{busy ? "创建中…" : "创建 API Key"}</Button></div>
          </form>
        </CardContent>
      </Card>
      {isLoading && !keys ? (
        <div className="space-y-3"><Skeleton className="h-28" /><Skeleton className="h-28" /></div>
      ) : keys?.length ? (
        <section className="space-y-3" aria-label="现有 API Key">
          {keys.map((key) => {
            const grant = grants?.find((item) => item.bot?.id === key.bot);
            const revoked = Boolean(key.revoked_at);
            const expired = Boolean(key.expires_at && Date.parse(key.expires_at) <= now);
            const current = Boolean(grant && grant.revision === key.grant_revision);
            const status = revoked ? "已撤销" : expired ? "已过期" : !current ? "授权已变更" : "有效";
            const variant = status === "有效" ? "success" : status === "授权已变更" ? "warning" : "destructive";
            return (
              <Card key={key.id}>
                <CardHeader>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="flex min-w-0 items-center gap-3"><KeyRound className="size-5 shrink-0 text-muted-foreground" /><div className="min-w-0"><CardTitle className="truncate">{key.name}</CardTitle><CardDescription className="truncate">Bot #{key.bot} · {key.prefix}…</CardDescription></div></div>
                    <StatusBadge variant={variant}>{status}</StatusBadge>
                  </div>
                </CardHeader>
                <CardContent className="flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1 text-sm text-muted-foreground"><p>Scopes：{key.scopes.join("、")}</p><p>到期：{key.expires_at ? new Date(key.expires_at).toLocaleString() : "不过期"}</p></div>
                  <Button variant="outline" size="sm" disabled={busy || revoked} onClick={() => void revoke(key.id)}><Trash2 />撤销</Button>
                </CardContent>
              </Card>
            );
          })}
        </section>
      ) : <EmptyState icon={<KeyRound />} title="暂无 API Key" description="创建一个绑定到有效 Bot 授权的 Key。" />}
    </div>
  );
}
