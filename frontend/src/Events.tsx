import { useEffect, useState } from 'react';
import { Button, Card, MessageBar, MessageBarBody, Spinner, Text, Title3 } from '@fluentui/react-components';
import { management } from './api';

interface EventRecord { id: number; bot: number; event_id: string; event_type: string; received_at: string; payload: unknown }
interface EventPage { events: EventRecord[]; next_before: string | null; has_more: boolean }

export function Events() {
  const [page, setPage] = useState<EventPage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function load(before?: string) {
    setBusy(true); setError('');
    try { setPage(await management<EventPage>(`events/${before ? `?before=${encodeURIComponent(before)}` : ''}`)); }
    catch { setError('事件加载失败，请重试'); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, []);
  return <Card>
    <Title3 as="h3">已入库事件</Title3>
    <Text>仅展示服务端允许访问的事件。入库不代表已向下游投递。</Text>
    <Button disabled={busy} onClick={() => load()}>刷新事件</Button>
    {busy && <Spinner label="正在加载事件" />}
    {error && <MessageBar intent="error"><MessageBarBody>{error}</MessageBarBody></MessageBar>}
    {!busy && page?.events.length === 0 && <Text>暂无可访问的事件。</Text>}
    {page?.events.map(event => <Card key={event.id}>
      <Text weight="semibold">{event.event_type} · Bot #{event.bot}</Text>
      <Text>事件 ID：{event.event_id}</Text>
      <Text>入库时间：{new Date(event.received_at).toLocaleString()}</Text>
      <details><summary>查看原始事件</summary><Text>{JSON.stringify(event.payload)}</Text></details>
    </Card>)}
    <Button disabled={busy || !page?.has_more || !page.next_before} onClick={() => page?.next_before && load(page.next_before)}>更早的事件</Button>
  </Card>;
}