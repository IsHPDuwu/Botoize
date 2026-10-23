import { useEffect, useState } from 'react';
import {
  Badge, Button, Card, CardHeader, Divider, FluentProvider, Link,
  MessageBar, MessageBarBody, Switch, Tab, TabList, Text, Title1, Title3,
  Toolbar, DataGrid, DataGridHeader, DataGridRow, DataGridHeaderCell,
  DataGridBody, DataGridCell, createTableColumn,
  webDarkTheme, webLightTheme,
  Field, Dropdown, Option, Spinner, makeStyles, makeStaticStyles, tokens,
  Dialog, DialogSurface, DialogBody, DialogTitle, DialogContent, DialogActions,
} from '@fluentui/react-components';
import { CopyRegular, ArrowClockwiseRegular, BotRegular } from '@fluentui/react-icons';
import { demoDashboard, isDemoEnabled, windows, type Window } from './dashboard';
import { checkBackend, management, type SessionUser } from './api';
import { Account } from './Account';
import { Login } from './Login';

const pages = ['总览', '我的 Bot', 'API Key', '订阅端点', '事件与投递', '接入指南'];
const useDocumentLayout = makeStaticStyles({
  body: { margin: 0 },
});
const useStyles = makeStyles({
  shell: { minHeight: '100vh', display: 'grid', gridTemplateColumns: '216px minmax(0, 1fr)', backgroundColor: tokens.colorNeutralBackground2, '@media (max-width: 760px)': { gridTemplateColumns: 'minmax(0, 1fr)' } },
  sidebar: { position: 'sticky', top: 0, height: '100vh', boxSizing: 'border-box', display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL, padding: tokens.spacingHorizontalL, backgroundColor: tokens.colorNeutralBackground1, '@media (max-width: 760px)': { position: 'static', height: 'auto' } },
  workspace: { minWidth: 0, width: '100%', maxWidth: '1280px', boxSizing: 'border-box', marginLeft: 'auto', marginRight: 'auto', display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalL, padding: tokens.spacingHorizontalXXL, '@media (max-width: 760px)': { padding: tokens.spacingHorizontalM } },
  header: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: tokens.spacingHorizontalM },
  metrics: { display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: tokens.spacingHorizontalM, '@media (max-width: 760px)': { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }, '@media (max-width: 480px)': { gridTemplateColumns: 'minmax(0, 1fr)' } },
  columns: { display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) minmax(0, 1fr)', gap: tokens.spacingHorizontalL, '@media (max-width: 1000px)': { gridTemplateColumns: 'minmax(0, 1fr)' } },
  stack: { display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM, minWidth: 0 },
  sidebarFooter: { marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: tokens.spacingVerticalM },
  scroll: { overflowX: 'auto', minWidth: 0 },
});
type Bucket = ReturnType<typeof demoDashboard>['buckets'][number];
const BucketBody = DataGridBody<Bucket>;
const columns = [
  createTableColumn<Bucket>({ columnId: 'label', renderHeaderCell: () => '等宽时间桶（UTC）', renderCell: row => row.label }),
  createTableColumn<Bucket>({ columnId: 'events', renderHeaderCell: () => '唯一事件', renderCell: row => row.events }),
  createTableColumn<Bucket>({ columnId: 'calls', renderHeaderCell: () => 'API 请求', renderCell: row => row.calls }),
];

export function App({ demo = isDemoEnabled(import.meta.env.VITE_DEMO_MODE) || (import.meta.env.DEV && new URLSearchParams(location.search).get('demo') === 'true') }: { demo?: boolean }) {
  useDocumentLayout();
  const [session, setSession] = useState<SessionUser | null>(null);
  const [checking, setChecking] = useState(!demo);
  useEffect(() => {
    if (demo) { setChecking(false); return; }
    let active = true;
    management<SessionUser>('auth/me/').then(user => { if (active) setSession(user); }).catch(() => {}).finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, [demo]);
  if (!demo && checking) return <FluentProvider theme={webDarkTheme}><Spinner label="正在检查登录状态" /></FluentProvider>;
  if (!demo && !session) return <FluentProvider theme={webDarkTheme}><Login onLogin={setSession} /></FluentProvider>;
  return <Workspace demo={demo} user={session} onLogout={() => setSession(null)} />;
}

function Workspace({ demo, user, onLogout }: { demo: boolean; user: SessionUser | null; onLogout: () => void }) {
  useDocumentLayout();
  const styles = useStyles();
  const backend = import.meta.env.VITE_BACKEND_URL?.trim() || (import.meta.env.DEV ? 'http://localhost:8000' : '');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [backendStatus, setBackendStatus] = useState('检查中');
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    setBackendStatus('检查中');
    checkBackend(controller.signal).then(() => {
      if (!controller.signal.aborted) setBackendStatus('已连接');
    }).catch(() => setBackendStatus('连接失败')).finally(() => clearTimeout(timeout));
    return () => { controller.abort(); clearTimeout(timeout); };
  }, [connectionAttempt]);
  const [dark, setDark] = useState(true);
  const [page, setPage] = useState('总览');
  const [window, setWindow] = useState<Window>('24h');
  const [data, setData] = useState<ReturnType<typeof demoDashboard> | null>(null);
  const [scenario, setScenario] = useState('正常数据');
  const [role, setRole] = useState<'Owner' | 'Admin'>('Owner');
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(demo);
  const [error, setError] = useState(false);
  useEffect(() => {
    setData(null);
    setError(false);
    setLoading(demo);
    if (!demo) return;
    // Synthetic latency and failure never run in real mode.
    const timer = setTimeout(() => {
      setLoading(false);
      if (scenario === '加载失败') setError(true);
      else if (scenario === '正常数据') setData(demoDashboard(window, role));
    }, 150);
    return () => clearTimeout(timer);
  }, [demo, window, scenario, revision, role]);
  const [feedback, setFeedback] = useState('');
  const [logoutBusy, setLogoutBusy] = useState(false);
  async function logoutSession() {
    setLogoutBusy(true);
    try { await management('auth/logout/', {}); onLogout(); }
    catch { setFeedback('退出失败，请重试'); }
    finally { setLogoutBusy(false); }
  }
  function changeWindow(value: Window) {
    setWindow(value);
  }
  async function copy() {
    try {
      if (!backend) return;
      await navigator.clipboard.writeText(backend);
      setFeedback('平台地址已复制');
    } catch {
      setFeedback('复制失败，请手动复制平台地址');
    }
  }
  return <FluentProvider theme={dark ? webDarkTheme : webLightTheme}>
    <div className={styles.shell}>
    <aside className={styles.sidebar}>
      <BotRegular /><Text size={500} weight="semibold">Bot Proxy</Text>
      <Text>QQ 官方机器人中转平台</Text>
      <nav aria-label="主导航">
        <TabList vertical selectedValue={page} onTabSelect={(_, value) => setPage(String(value.value))}>
          {[...pages, ...(!demo && user?.role === 'Owner' ? ['Bot 授权'] : [])].map(name => <Tab key={name} value={name}>{name}</Tab>)}
        </TabList>
      </nav>
      <div className={styles.sidebarFooter}>
      <div><Divider /></div><Badge appearance="outline">{demo ? '演示工作区' : `${user?.username} · ${user?.role}`}</Badge>
      {!demo && <Button disabled={logoutBusy} onClick={logoutSession}>退出登录</Button>}
      <Text size={200}>管理端 · Session / CSRF<br />权限由服务端校验</Text>
      </div>
    </aside>
    <main className={styles.workspace}>
    <header className={styles.header}>
      <Title1>{page === '总览' ? '中转概览' : page}</Title1>
      <Toolbar aria-label="外观与状态">
        <Badge appearance="filled" color={demo ? 'warning' : 'informative'}>{demo ? '演示模式 · 全部数据为模拟' : '未接入真实统计'}</Badge>
        <Switch label="深色主题" checked={dark} onChange={(_, value) => setDark(value.checked)} />
      </Toolbar>
    </header>
    <div><Divider /></div>
    {!demo && ['我的 Bot', 'API Key', 'Bot 授权'].includes(page) && <Account key={page} initialUser={user ?? undefined} section={page} />}
      {demo && <Text size={200}>演示工作区 · 当前数据均为模拟，不代表真实服务状态。</Text>}
      {page === '总览' ? <>
        <Text>机器人连接、事件流量与投递健康一览</Text>
        <Toolbar aria-label="统计窗口">
          <TabList aria-label="时间范围" selectedValue={window} onTabSelect={(_, value) => changeWindow(value.value as Window)}>
            {windows.map(value => <Tab key={value} value={value}>{value}</Tab>)}
          </TabList>
          <Button icon={<ArrowClockwiseRegular />} disabled={!demo || loading} onClick={() => setRevision(value => value + 1)}>刷新</Button>
          {demo && <Button appearance="subtle" onClick={() => setSettingsOpen(true)}>演示设置</Button>}
        </Toolbar>
        <Dialog open={settingsOpen} onOpenChange={(_, value) => setSettingsOpen(value.open)}>
        <DialogSurface><DialogBody><DialogTitle>演示设置</DialogTitle><DialogContent>
        {demo && <Field label="角色范围演示（不改变真实权限）"><Dropdown aria-label="角色范围演示" value={role} selectedOptions={[role]} onOptionSelect={(_, value) => setRole(value.optionValue === 'Admin' ? 'Admin' : 'Owner')}>
          <Option value="Owner">Owner</Option><Option value="Admin">Admin</Option>
        </Dropdown></Field>}
        {demo && <p>{role === 'Owner' ? 'Owner 演示：全平台虚构 Bot 与全局活动。' : 'Admin 演示：仅虚构已授权 Bot 与自身活动，不包含其他 Admin 记录。'}角色切换仅演示信息范围，不是登录或服务端权限校验。</p>}
        {demo && <Field label="演示场景（仅合成数据）"><Dropdown value={scenario} selectedOptions={[scenario]} onOptionSelect={(_, value) => setScenario(value.optionValue ?? '正常数据')}>
          {['正常数据', '空数据', '加载失败'].map(value => <Option key={value} value={value}>{value}</Option>)}
        </Dropdown></Field>}
        </DialogContent><DialogActions><Button onClick={() => setSettingsOpen(false)}>完成</Button></DialogActions></DialogBody></DialogSurface>
        </Dialog>
        {loading && <Spinner label="正在加载模拟统计" />}
        {error && <MessageBar intent="error"><MessageBarBody>模拟统计加载失败；未展示过期指标。<Button onClick={() => setRevision(value => value + 1)}>重试</Button></MessageBarBody></MessageBar>}
        {demo && !loading && !error && !data && <MessageBar intent="info"><MessageBarBody>所选窗口暂无模拟统计数据。</MessageBarBody></MessageBar>}
        {!demo && <MessageBar intent="info"><MessageBarBody>真实统计 API 尚未接入，不展示模拟指标。仅显式设置 VITE_DEMO_MODE=true 后启用演示。</MessageBarBody></MessageBar>}
        {demo && data && <>
          <section className={styles.metrics} aria-label="模拟指标">
            {[
              ['在线 Bot（当前快照）', data.online], ['窗口内唯一事件', data.events],
              ['窗口内 API 请求', data.calls], ['终态投递成功率', data.rate],
              ['待重试（当前快照）', data.retry], ['死信（当前快照）', data.dead],
            ].map(([name, value]) => <Card key={name}><CardHeader image={<BotRegular />} header={<Text weight="semibold">{name}</Text>} description={<Text size={600}>{value}</Text>} /></Card>)}
          </section>
          <Card><Title3 as="h3">事件与调用趋势 · 模拟统计表</Title3>
          <Text size={200}>UTC · {window} · 每桶 {data.bucketMinutes} 分钟 · 更新于 {data.generated}</Text>
          <div className={styles.scroll}>
          <DataGrid aria-label="模拟时间分桶统计" items={data.buckets} columns={columns} getRowId={row => row.id}>
            <DataGridHeader><DataGridRow>{({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}</DataGridRow></DataGridHeader>
            <BucketBody>{({ item, rowId }) => <DataGridRow<Bucket> key={rowId}>{({ renderCell }) => <DataGridCell>{renderCell(item)}</DataGridCell>}</DataGridRow>}</BucketBody>
          </DataGrid>
          </div></Card>
        </>}
        {!data && <>
          <section className={styles.metrics} aria-label="统计指标空态">
            {['在线 Bot（当前快照）', '窗口内唯一事件', '窗口内 API 请求', '终态投递成功率', '待重试（当前快照）', '死信（当前快照）'].map(name => <Card key={name}><CardHeader image={<BotRegular />} header={<Text weight="semibold">{name}</Text>} description={<Text size={600}>—</Text>} /><Text>{loading ? '加载中' : error ? '加载失败' : '暂无数据'}</Text></Card>)}
          </section>
          <Card><Title3 as="h3">事件与调用趋势</Title3><Text>窗口 {window} / 等宽时间桶</Text><Text>尚无可展示的时间分桶；接入后将在此显示统计。</Text></Card>
        </>}
      </> : page !== '接入指南' && (demo || !['我的 Bot', 'API Key', 'Bot 授权'].includes(page)) && <Card><Title3 as="h3">{page}工作区</Title3><MessageBar intent="info"><MessageBarBody>此导航为前端预览入口，{page}尚未接入管理 API，不提供伪造管理操作。</MessageBarBody></MessageBar><Text>{({ '我的 Bot': '机器人连接状态、能力与授权摘要将在这里展示。', 'API Key': '单 Bot 密钥、权限范围、到期与撤销记录将在这里展示。', '订阅端点': 'HTTP / WebSocket 订阅及投递健康状态将在这里展示。', '事件与投递': '事件检索、投递记录与重试链路将在这里展示。' } as Record<string, string>)[page]}</Text><Button onClick={() => setPage('接入指南')}>查看接入准备</Button></Card>}
      {(page === '总览' || page === '接入指南') && <div className={styles.columns}>
        <section className={styles.stack} aria-label="近期活动">
          <Title3 as="h3">近期活动{demo ? ' · 模拟' : ''}</Title3>
          {data ? <>
          <Card><CardHeader header="模拟连接异常" description={role === 'Owner' ? '全平台演示 Bot A：官方连接中断，等待重连。' : '已授权演示 Bot：连接中断，等待重连。'} /></Card>
          <Card><CardHeader header="模拟投递失败" description="演示订阅 B：回调超时，等待重试；不代表最终送达。" /></Card>
          <Card><CardHeader header="模拟 Key 到期提醒" description="演示 Key C：将在 3 天后到期。此处不包含真实密钥。" /></Card>
          </> : <Card><CardHeader header="暂无活动记录" description="接入真实服务后显示连接、投递与密钥提醒；当前不生成虚假活动。" /></Card>}
        </section>
        <Card>
        <section className={styles.stack} aria-label="接入信息">
        <Title3 as="h3">接入信息</Title3>
        <Text>后端服务地址：{backend || '未配置 VITE_BACKEND_URL'}</Text>
        <Text>后端健康检查：{backendStatus}（不代表官方机器人在线）</Text>
        <Button disabled={backendStatus === '检查中'} onClick={() => setConnectionAttempt(value => value + 1)}>重新检查连接</Button>
        <Button icon={<CopyRegular />} disabled={!backend} onClick={copy}>复制平台地址</Button>
        <p role="status">{feedback}</p>
        <p><Link href="https://bot.q.qq.com/wiki/develop/api-v2/">QQ 官方开发文档</Link></p>
        <Text>管理 API 使用同源 Session 与 CSRF；前端不保存官方凭据。真实授权范围须由服务端校验。</Text>
      </section></Card></div>}
    </main>
    </div>
  </FluentProvider>;
}