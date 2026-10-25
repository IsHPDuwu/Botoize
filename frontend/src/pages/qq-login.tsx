import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Languages, Moon, Sun } from "lucide-react";
import { BotoizeLogo } from "@/components/BotoizeLogo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useQQAuth } from "@/hooks/use-qq-auth";
import { useTheme } from "@/hooks/use-theme";
import { toggleLanguage } from "@/i18n";
import { ManagementApiError } from "@/lib/qq-api";

export function LoginPage() {
  const { t } = useTranslation();
  const { resolvedTheme, setTheme } = useTheme();
  const { user, loading, login } = useQQAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (user) navigate("/dashboard", { replace: true });
  }, [navigate, user]);

  if (loading) return <div className="flex min-h-dvh items-center justify-center bg-background text-muted-foreground">{t("common.loading")}</div>;
  if (user) return <Navigate to="/dashboard" replace />;

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await login(username.trim(), password);
      navigate("/dashboard", { replace: true });
    } catch (reason) {
      setError(reason instanceof ManagementApiError && reason.status === 403 ? "用户名或密码不正确。" : reason instanceof Error ? reason.message : "登录失败，请重试");
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <div className="h-dvh overflow-y-auto overscroll-contain p-4">
      <div className="flex min-h-full flex-col gap-4">
        <div className="flex shrink-0 justify-end gap-2">
          <Button variant="ghost" size="icon" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")} title={t("theme.toggle")}>
            {resolvedTheme === "dark" ? <Moon /> : <Sun />}
          </Button>
          <Button variant="ghost" size="icon" onClick={toggleLanguage} title={t("language.switchLanguage")}>
            <Languages />
          </Button>
        </div>
        <div className="my-auto w-full max-w-md shrink-0 self-center">
          <Card className="overflow-hidden">
            <CardHeader className="text-center">
              <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center">
                <BotoizeLogo className="h-full w-full" />
              </div>
              <CardTitle className="text-2xl">Botoize Console</CardTitle>
              <CardDescription>QQ 官方机器人中转控制台</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={submit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="username">用户名</Label>
                  <Input id="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} disabled={busy} required />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password">密码</Label>
                  <Input id="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy} required />
                </div>
                {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
                <Button className="w-full" variant="primary" type="submit" disabled={busy || !username.trim() || !password}>{busy ? "正在登录…" : "登录"}</Button>
              </form>
              <p className="mt-4 text-center text-sm text-muted-foreground">请联系平台 Owner 开通账号，或<a href="/register" className="underline underline-offset-4">使用邀请注册</a>。</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
