import { useEffect, useState } from 'react';
import { Button, Card, Field, Input, MessageBar, MessageBarBody, Text, Title3, Spinner, Dropdown, Option, Checkbox } from '@fluentui/react-components';
import { management, type SessionUser, type BotInfo, type KeyInfo } from './api';

interface Grant { id: number; user_id: number; bot_id: number; scopes: string[]; is_active: boolean; revision: number }
interface MyGrant { bot: BotInfo; scopes: string[]; revision: number }
interface UserSummary { id: number; username: string; role: string; is_active: boolean }
const scopes = ['events:read', 'messages:send', 'media:upload', 'query:read'];

export function Account({ initialUser, section = '全部' }: { initialUser?: SessionUser; section?: string } = {}) {
  const [user, setUser] = useState<SessionUser | null>(initialUser ?? null);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [bots, setBots] = useState<BotInfo[]>([]);
  const [keys, setKeys] = useState<KeyInfo[]>([]);
  const [botName, setBotName] = useState('');
  const [appId, setAppId] = useState('');
  const [secret, setSecret] = useState('');
  const [botId, setBotId] = useState('');
  const [keyName, setKeyName] = useState('');
  const [keyScopes, setKeyScopes] = useState<string[]>([]);
  const [myGrants, setMyGrants] = useState<MyGrant[]>([]);
  const [issuedToken, setIssuedToken] = useState('');
  const [grants, setGrants] = useState<Grant[]>([]);
  const [grantUser, setGrantUser] = useState('');
  const [grantBot, setGrantBot] = useState('');
  const [grantScopes, setGrantScopes] = useState<string[]>([]);
  const [users, setUsers] = useState<UserSummary[]>([]);
  async function mutate(path: string, body: Record<string, unknown>) {
    setBusy(true); setError(''); setIssuedToken('');
    try {
      const result = await management<{ token?: string }>(path, { ...body, password });
      if (result?.token) setIssuedToken(result.token);
      await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败'); }
    finally { setPassword(''); setSecret(''); setBusy(false); }
  }
  async function load() {
    const [botList, keyList, ownGrants] = await Promise.all([management<BotInfo[]>('bots/'), management<KeyInfo[]>('keys/'), management<MyGrant[]>('my-grants/')]);
    setBots(botList); setKeys(keyList);
    setMyGrants(ownGrants);
    setKeyScopes(current => current.filter(scope => ownGrants.find(grant => String(grant.bot.id) === botId)?.scopes.includes(scope)));
    if (user?.role === 'Owner') {
      const [grantList, userList] = await Promise.all([management<Grant[]>('grants/'), management<UserSummary[]>('users/')]);
      setGrants(grantList); setUsers(userList);
    }
  }
  useEffect(() => {
    if (initialUser) { setBusy(false); return; }
    let alive = true;
    management<SessionUser>('auth/me/').then(value => { if (alive) setUser(value); }).catch(() => {}).finally(() => { if (alive) setBusy(false); });
    return () => { alive = false; };
  }, [initialUser]);
  useEffect(() => { if (user) load().catch(() => setError('加载 Bot 或密钥列表失败，请重试')); }, [user]);
  return <Card>
    <Title3 as="h3">{section === '全部' ? '资源管理' : section}</Title3>
    {error && <MessageBar intent="error"><MessageBarBody>{error}</MessageBarBody></MessageBar>}
    {busy && <Spinner label="正在连接管理服务" />}
    {user ? <>
      <Text>{user.username} · {user.role}</Text>
      <Field label="操作确认密码"><Input type="password" autoComplete="current-password" value={password} onChange={(_, data) => setPassword(data.value)} /></Field>
      {user.role === 'Owner' && ['全部', '我的 Bot'].includes(section) && <Card>
        <Title3 as="h3">添加官方 Bot</Title3>
        <Field label="Bot 名称"><Input value={botName} onChange={(_, data) => setBotName(data.value)} /></Field>
        <Field label="AppID"><Input value={appId} onChange={(_, data) => setAppId(data.value)} /></Field>
        <Field label="AppSecret"><Input type="password" autoComplete="off" value={secret} onChange={(_, data) => setSecret(data.value)} /></Field>
        <Button disabled={busy || !password || !botName || !appId || !secret} onClick={() => mutate('bots/', { name: botName, app_id: appId, secret })}>添加 Bot</Button>
      </Card>}
      {user.role === 'Owner' && ['全部', 'Bot 授权'].includes(section) && <Card>
        <Title3 as="h3">Bot 授权管理</Title3>
        <Text>同一 Bot 可授权给多个用户。这里只分配 Bot 权限，不修改用户角色。</Text>
        <Field label="被授权用户"><Dropdown selectedOptions={grantUser ? [grantUser] : []} value={users.find(value => String(value.id) === grantUser)?.username ?? ''} onOptionSelect={(_, data) => setGrantUser(data.optionValue ?? '')}>{users.filter(value => value.is_active).map(value => <Option key={value.id} value={String(value.id)} text={value.username}>{value.username} · {value.role}</Option>)}</Dropdown></Field>
        <Field label="授权 Bot"><Dropdown selectedOptions={grantBot ? [grantBot] : []} value={bots.find(bot => String(bot.id) === grantBot)?.name ?? ''} onOptionSelect={(_, data) => setGrantBot(data.optionValue ?? '')}>{bots.map(bot => <Option key={bot.id} value={String(bot.id)}>{bot.name}</Option>)}</Dropdown></Field>
        {scopes.map(scope => <Checkbox key={scope} label={scope} checked={grantScopes.includes(scope)} onChange={(_, data) => setGrantScopes(current => data.checked ? [...current, scope] : current.filter(value => value !== scope))} />)}
        <Button disabled={busy || !password || !/^[1-9]\d*$/.test(grantUser) || !grantBot} onClick={() => mutate('grants/', { user: Number(grantUser), bot: Number(grantBot), scopes: grantScopes, is_active: true })}>保存用户 Bot 授权</Button>
        {grants.map(grant => <Card key={grant.id}>
          <Text>用户 #{grant.user_id} · Bot #{grant.bot_id} · {grant.is_active ? '有效' : '已停用'} · 版本 {grant.revision}</Text>
          <Text>{grant.scopes.join('、') || '无操作权限'}</Text>
          <Button disabled={busy} onClick={() => { setGrantUser(String(grant.user_id)); setGrantBot(String(grant.bot_id)); setGrantScopes(grant.scopes); }}>编辑此授权</Button>
          <Button disabled={busy || !password || !grant.is_active} onClick={() => mutate('grants/', { user: grant.user_id, bot: grant.bot_id, scopes: grant.scopes, is_active: false })}>停用用户 #{grant.user_id} 的 Bot #{grant.bot_id} 授权</Button>
        </Card>)}
      </Card>}
      <Button disabled={busy} onClick={() => load().catch(() => setError('刷新失败'))}>刷新管理数据</Button>
      {['全部', '我的 Bot'].includes(section) && <>
      <Title3 as="h3">可访问的 Bot</Title3>
      {bots.length ? bots.map(bot => <Card key={bot.id}><Text weight="semibold">{bot.name}</Text><Text>AppID：{bot.app_id} · {bot.is_active ? '已启用' : '已停用'}（不代表官方连接在线）</Text></Card>) : <Text>暂无可访问的 Bot。</Text>}
      </>}
      {['全部', 'API Key'].includes(section) && <>
      <Title3 as="h3">我的 API Key</Title3>
      <Field label="绑定的 Bot"><Dropdown selectedOptions={botId ? [botId] : []} value={myGrants.find(grant => String(grant.bot.id) === botId)?.bot.name ?? ''} onOptionSelect={(_, data) => { setBotId(data.optionValue ?? ''); setKeyScopes([]); }}>{myGrants.map(grant => <Option key={grant.bot.id} value={String(grant.bot.id)}>{grant.bot.name}</Option>)}</Dropdown></Field>
      {!myGrants.length && <Text>暂无可用于创建 Key 的有效 Bot 授权。Owner 也需要显式授权。</Text>}
      <Field label="Key 名称"><Input value={keyName} onChange={(_, data) => setKeyName(data.value)} /></Field>
      <Text>Key 权限（仅显示当前有效授权）</Text>
      {(myGrants.find(grant => String(grant.bot.id) === botId)?.scopes ?? []).map(scope => <Checkbox key={scope} label={`Key 权限 ${scope}`} checked={keyScopes.includes(scope)} onChange={(_, data) => setKeyScopes(current => data.checked ? [...current, scope] : current.filter(value => value !== scope))} />)}
      <Button disabled={busy || !password || !myGrants.some(grant => String(grant.bot.id) === botId) || !keyName || !keyScopes.length} onClick={() => mutate('keys/', { bot: Number(botId), name: keyName, scopes: keyScopes })}>创建单 Bot Key</Button>
      {issuedToken && <MessageBar intent="warning"><MessageBarBody>仅本次展示，请立即安全保存。<Input aria-label="新建密钥" readOnly type="password" value={issuedToken} /><Button onClick={() => navigator.clipboard.writeText(issuedToken).catch(() => setError('复制失败，请手动选择密钥保存'))}>复制新密钥</Button><Button onClick={() => setIssuedToken('')}>我已保存，清除明文</Button></MessageBarBody></MessageBar>}
      {keys.length ? keys.map(key => <Card key={key.id}><Text>{key.name} · Bot #{key.bot}</Text><Text>{key.prefix}… · {key.revoked_at ? '已撤销' : '未撤销'} · {key.scopes.join('、')}</Text><Button disabled={busy || !password || !!key.revoked_at} onClick={() => mutate(`keys/${key.id}/revoke/`, {})}>撤销 {key.name}</Button></Card>) : <Text>暂无密钥。</Text>}
      </>}
    </> : !busy && <Text>会话不可用，请刷新页面重新登录。</Text>}
  </Card>;
}