import { useEffect, useState } from 'react';
import { Button, Field, Input, Dropdown, Option, MessageBar, MessageBarBody, Spinner, Text, makeStyles, tokens } from '@fluentui/react-components';
import { management, type BotInfo } from './api';

interface Grant { bot: BotInfo; scopes: string[]; revision: number }
interface Subscription { id: number; bot: number; url: string; is_active: boolean; is_current: boolean; grant_revision: number }
const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL },
  form: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM, maxWidth: '640px' },
  actions: { display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalS },
});

export function Subscriptions() {
  const styles = useStyles();
  const [grants, setGrants] = useState<Grant[]>([]);
  const [rows, setRows] = useState<Subscription[]>([]);
  const [bot, setBot] = useState('');
  const [url, setUrl] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function refresh() {
    const [g, s] = await Promise.all([management<Grant[]>('my-grants/'), management<Subscription[]>('subscriptions/')]);
    setGrants(g.filter(row => row.scopes.includes('events:read')));
    setRows(s);
  }
  useEffect(() => { refresh().catch(() => setError('加载订阅失败，请刷新重试')).finally(() => setBusy(false)); }, []);
  const selected = rows.find(row => String(row.bot) === bot);
  async function save(active: boolean) {
    setBusy(true); setError(''); setNotice('');
    try {
      await management('subscriptions/', { bot: Number(bot), url, is_active: active, password });
      setPassword('');
      await refresh();
      setNotice(active ? '订阅已保存；请确保服务端已调度投递任务。' : '订阅已禁用。');
    } catch (e) { setError(e instanceof Error ? e.message : '操作失败'); }
    finally { setBusy(false); }
  }
  return <section className={styles.root} aria-label="HTTP 订阅管理">
    <Text>每个授权 Bot 可配置一个 HTTPS 回调。授权变更后需要重新保存；事件可能重复投递，请按投递 ID 去重。</Text>
    {error && <MessageBar intent="error"><MessageBarBody>{error}</MessageBarBody></MessageBar>}
    {notice && <MessageBar intent="success"><MessageBarBody>{notice}</MessageBarBody></MessageBar>}
    {busy && <Spinner label="正在处理订阅" />}
    {!busy && !grants.length && <Text>没有具备 events:read 权限的 Bot。Owner 也需要显式授权。</Text>}
    <div className={styles.form}>
      <Field label="Bot"><Dropdown aria-label="订阅 Bot" disabled={busy} selectedOptions={bot ? [bot] : []} value={grants.find(g => String(g.bot.id) === bot)?.bot.name ?? ''} onOptionSelect={(_, d) => {
        const id = d.optionValue ?? ''; setBot(id); setUrl(rows.find(row => String(row.bot) === id)?.url ?? ''); setNotice('');
      }}>{grants.map(g => <Option key={g.bot.id} value={String(g.bot.id)}>{g.bot.name}</Option>)}</Dropdown></Field>
      {selected && <Text>{selected.is_current ? '当前订阅有效' : selected.is_active ? '授权版本已变化，需重新保存' : '订阅已禁用'}</Text>}
      <Field label="HTTPS 回调地址" hint="仅允许公共网络 HTTPS 443，不跟随重定向。"><Input type="url" value={url} disabled={busy} onChange={(_, d) => setUrl(d.value)} /></Field>
      <Field label="确认当前密码"><Input type="password" value={password} disabled={busy} autoComplete="current-password" onChange={(_, d) => setPassword(d.value)} /></Field>
      <div className={styles.actions}>
        <Button appearance="primary" disabled={busy || !bot || !url || !password} onClick={() => save(true)}>保存订阅</Button>
        <Button disabled={busy || !selected?.is_active || !password} onClick={() => save(false)}>禁用订阅</Button>
        <Button disabled={busy} onClick={() => { setBusy(true); refresh().catch(() => setError('刷新失败')).finally(() => setBusy(false)); }}>刷新</Button>
      </div>
    </div>
  </section>;
}