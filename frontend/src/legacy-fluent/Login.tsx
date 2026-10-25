import { useState } from 'react';
import { Button, Card, Field, Input, MessageBar, MessageBarBody, Title1, Text, makeStyles, tokens } from '@fluentui/react-components';
import { management, type SessionUser } from './api';

const useStyles = makeStyles({
  page: { minHeight: '100vh', display: 'grid', alignItems: 'center', justifyContent: 'center', padding: tokens.spacingHorizontalL, boxSizing: 'border-box', backgroundColor: tokens.colorNeutralBackground2 },
  panel: { width: '100%', maxWidth: '400px', minWidth: 0 },
  form: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL },
});

export function Login({ onLogin }: { onLogin: (user: SessionUser) => void }) {
  const styles = useStyles();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit() {
    if (busy) return;
    setBusy(true); setError('');
    try { onLogin(await management<SessionUser>('auth/login/', { username, password })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '登录失败，请重试'); }
    finally { setPassword(''); setBusy(false); }
  }
  return <main className={styles.page}>
    <section className={styles.panel} aria-label="登录控制台">
      <Card>
        <Title1 as="h1">登录 Bot Proxy</Title1>
        <Text>QQ 官方机器人中转控制台</Text>
        {error && <MessageBar intent="error"><MessageBarBody>{error}</MessageBarBody></MessageBar>}
        <form onSubmit={event => { event.preventDefault(); void submit(); }}><div className={styles.form}>
          <Field label="用户名" required><Input autoComplete="username" value={username} disabled={busy} onChange={(_, data) => setUsername(data.value)} /></Field>
          <Field label="密码" required><Input type="password" autoComplete="current-password" value={password} disabled={busy} onChange={(_, data) => setPassword(data.value)} /></Field>
          <Button appearance="primary" type="submit" disabled={busy || !username.trim() || !password}>{busy ? '正在登录…' : '登录'}</Button>
        </div></form>
        <Text size={200}>仅限已开通账号。请联系平台 Owner 获取访问权限。</Text>
      </Card>
    </section>
  </main>;
}