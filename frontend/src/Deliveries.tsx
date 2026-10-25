import { useEffect, useState } from 'react';
import { Button, Card, MessageBar, MessageBarBody, Spinner, Text, Title3 } from '@fluentui/react-components';
import { management } from './api';

interface Delivery { id: number; event_id: string; bot: number; state: string; attempts: number; available_at: string | null }
interface Page { deliveries: Delivery[]; has_more: boolean; next_before: string | null }
const states: Record<string, string> = { pending: '等待投递', processing: '租约处理中', delivered: '回调已接受', failed: '尝试耗尽', cancelled: '授权失效已取消' };

export function Deliveries() {
  const [page, setPage] = useState<Page | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function load(before?: string) {
    setBusy(true); setError('');
    try { setPage(await management<Page>(`deliveries/${before ? `?before=${encodeURIComponent(before)}` : ''}`)); }
    catch { setError('投递记录加载失败'); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, []);
  return <Card>
    <Title3 as="h3">HTTP 投递记录</Title3>
    <Text>回调返回 2xx 仅表示下游接受，不代表业务处理完成。未配置订阅的快照保持等待状态。</Text>
    <Button disabled={busy} onClick={() => load()}>刷新投递</Button>
    {busy && <Spinner label="加载投递记录" />}
    {error && <MessageBar intent="error"><MessageBarBody>{error}</MessageBarBody></MessageBar>}
    {page?.deliveries.map(row => <Card key={row.id}>
      <Text weight="semibold">#{row.id} · Bot #{row.bot} · {states[row.state] ?? row.state}</Text>
      <Text>事件：{row.event_id} · 已尝试 {row.attempts} 次</Text>
      {row.available_at && <Text>可重试时间：{new Date(row.available_at).toLocaleString()}</Text>}
    </Card>)}
    {!busy && page?.deliveries.length === 0 && <Text>暂无投递记录。</Text>}
    <Button disabled={busy || !page?.has_more} onClick={() => page?.next_before && load(page.next_before)}>更早的投递</Button>
  </Card>;
}