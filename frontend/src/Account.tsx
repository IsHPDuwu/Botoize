import { useEffect, useState } from 'react';
import { Button, Card, Field, Input, MessageBar, MessageBarBody, Text, Title3, Spinner } from '@fluentui/react-components';
import { management, type SessionUser, type BotInfo, type KeyInfo } from './api';

export function Account() {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [bots, setBots] = useState<BotInfo[]>([]);
  const [keys, setKeys] = useState<KeyInfo[]>([]);
  async function load() {
    const [botList, keyList] = await Promise.all([management<BotInfo[]>('bots/'), management<KeyInfo[]>('keys/')]);
    setBots(botList); setKeys(keyList);
  }
  useEffect(() => {
    let alive = true;
    management<SessionUser>('auth/me/').then(value => { if (alive) setUser(value); }).catch(() => {}).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, []);
  useEffect(() => { if (user) load().catch(() => setError('加载 Bot 或密钥列表失败，请重试')); }, [user]);
  async function signIn() {
    setBusy(true); setError('');
    try { setUser(await management<SessionUser>('auth/login/', { username, password })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '登录失败'); }
    finally { setPassword(''); setBusy(false); }
  }
  async function signOut() {
    setBusy(true); setError('');
    try { await management('auth/logout/', {}); setUser(null); setBots([]); setKeys([]); }
    catch { setError('退出失败，请重试'); }
    finally { setBusy(false); }
  }
  return <Card>
    <Title3 as="h3">真实管理会话</Title3>
    {error && <MessageBar intent="error"><MessageBarBody>{error}</MessageBarBody></MessageBar>}
    {busy && <Spinner label="正在连接管理服务" />}
    {user ? <>
      <Text>{user.username} · {user.role}</Text>
      <Button disabled={busy} onClick={() => load().catch(() => setError('刷新失败'))}>刷新管理数据</Button>
      <Title3 as="h3">可访问的 Bot</Title3>
      {bots.length ? bots.map(bot => <Card key={bot.id}><Text weight="semibold">{bot.name}</Text><Text>AppID：{bot.app_id} · {bot.is_active ? '已启用' : '已停用'}（不代表官方连接在线）</Text></Card>) : <Text>暂无可访问的 Bot。</Text>}
      <Title3 as="h3">我的 API Key</Title3>
      {keys.length ? keys.map(key => <Card key={key.id}><Text>{key.name} · Bot #{key.bot}</Text><Text>{key.prefix}… · {key.revoked_at ? '已撤销' : '未撤销'} · {key.scopes.join('、')}</Text></Card>) : <Text>暂无密钥。</Text>}
      <Button disabled={busy} onClick={signOut}>退出登录</Button>
    </> : <form onSubmit={event => { event.preventDefault(); void signIn(); }}>
      <Field label="用户名" required><Input autoComplete="username" value={username} onChange={(_, data) => setUsername(data.value)} /></Field>
      <Field label="密码" required><Input type="password" autoComplete="current-password" value={password} onChange={(_, data) => setPassword(data.value)} /></Field>
      <Button type="submit" appearance="primary" disabled={busy || !username || !password}>登录后端</Button>
    </form>}
  </Card>;
}