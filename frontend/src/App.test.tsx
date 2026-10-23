import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { management } from './api';
vi.mock('./api', () => ({ checkBackend: vi.fn().mockResolvedValue(undefined), management: vi.fn() }));
beforeEach(() => { vi.mocked(management).mockImplementation(async path => path === 'auth/me/' ? { id: 1, username: 'test', role: 'Admin' } : []); });
import { App } from './App';
import { demoDashboard, isDemoEnabled, successRate, windows } from './dashboard';

describe('dashboard', () => {
  it('only enables demo explicitly', async () => {
    for (const value of [undefined, '', 'false', '1', 'TRUE', true]) expect(isDemoEnabled(value)).toBe(false);
    expect(isDemoEnabled('true')).toBe(true);
    render(<App demo={false} />);
    expect(screen.queryByRole('grid')).not.toBeInTheDocument();
    expect(await screen.findByText(/真实统计 API 尚未接入/)).toBeInTheDocument();
  });
  it('handles zero denominator and each window', () => {
    expect(successRate(0, 0)).toBe('无数据');
    expect(successRate(3, 1)).toBe('75.0%');
    expect(new Set(windows.map(w => demoDashboard(w).events)).size).toBe(4);
  });
  it('switches windows, theme and navigation', async () => {
    render(<App demo />);
    expect(await screen.findByRole('grid')).toBeInTheDocument();
    for (const value of windows) {
      fireEvent.click(screen.getByRole('tab', { name: value }));
      expect(await screen.findByText(new RegExp(`UTC · ${value} ·`))).toBeInTheDocument();
    }
    const theme = screen.getByRole('switch');
    expect(theme).toBeChecked();
    fireEvent.click(theme);
    expect(theme).not.toBeChecked();
    fireEvent.click(screen.getByRole('tab', { name: '我的 Bot' }));
    expect(screen.getByText(/尚未接入管理 API/)).toBeInTheDocument();
  });
  it('shows loading, empty, error and retry without stale metrics', async () => {
    render(<App demo />);
    expect(screen.getByText('正在加载模拟统计')).toBeInTheDocument();
    await screen.findByRole('grid');
    fireEvent.click(screen.getByRole('button', { name: '刷新' }));
    expect(screen.queryByRole('grid')).not.toBeInTheDocument();
    await screen.findByRole('grid');
    fireEvent.click(screen.getByRole('button', { name: '演示设置' }));
    fireEvent.click(screen.getByRole('combobox', { name: '演示场景（仅合成数据）' }));
    fireEvent.click(screen.getByRole('option', { name: '空数据' }));
    expect(await screen.findByText('所选窗口暂无模拟统计数据。')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('combobox', { name: '演示场景（仅合成数据）' }));
    fireEvent.click(screen.getByRole('option', { name: '加载失败' }));
    expect(await screen.findByText(/模拟统计加载失败/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '完成' }));
    fireEvent.click(await screen.findByRole('button', { name: '重试' }));
    expect(screen.getByText('正在加载模拟统计')).toBeInTheDocument();
    expect(await screen.findByText(/模拟统计加载失败/)).toBeInTheDocument();
    expect(screen.queryByRole('grid')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '演示设置' }));
    fireEvent.click(screen.getByRole('combobox', { name: '演示场景（仅合成数据）' }));
    fireEvent.click(screen.getByRole('option', { name: '正常数据' }));
    fireEvent.click(screen.getByRole('button', { name: '完成' }));
    expect(await screen.findByRole('grid')).toBeInTheDocument();
  }, 45000);
  it('cancels pending demo load when switching to real mode', async () => {
    const { rerender } = render(<App demo />);
    rerender(<App demo={false} />);
    expect(await screen.findByText(/真实统计 API 尚未接入/)).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByRole('grid')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新' })).toBeDisabled();
  });
  it('reports copy success and failure', async () => {
    vi.stubEnv('VITE_BACKEND_URL', 'https://relay.example.test');
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    render(<App demo={false} />);
    fireEvent.click(await screen.findByRole('button', { name: '复制平台地址' }));
    expect(await screen.findByText('平台地址已复制')).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith('https://relay.example.test');
    writeText.mockRejectedValue(new Error('denied'));
    fireEvent.click(screen.getByRole('button', { name: '复制平台地址' }));
    expect(await screen.findByText('复制失败，请手动复制平台地址')).toBeInTheDocument();
    vi.unstubAllEnvs();
  });
  it('keeps real mode structure and shows the configured dev backend', async () => {
    render(<App demo={false} />);
    expect(await screen.findByRole('region', { name: '统计指标空态' })).toBeInTheDocument();
    expect(screen.getByText('事件与调用趋势')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '复制平台地址' })).not.toBeDisabled();
    expect(screen.getByText(/http:\/\/localhost:8000/)).toBeInTheDocument();
  });
  it('shows a standalone login page without workspace content when unauthenticated', async () => {
    vi.mocked(management).mockRejectedValue(new Error('Not authenticated'));
    render(<App demo={false} />);
    expect(await screen.findByRole('heading', { name: '登录 Bot Proxy' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(screen.queryByText('中转概览')).toBeNull();
    expect(screen.queryByText('真实管理会话')).toBeNull();
  });
  it('separates real management pages and returns to login after logout', async () => {
    render(<App demo={false} />);
    await screen.findByText('中转概览');
    expect(screen.queryByLabelText('操作确认密码')).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: '我的 Bot' }));
    await screen.findByText('暂无可访问的 Bot。');
    expect(screen.queryByRole('button', { name: '创建单 Bot Key' })).toBeNull();
    fireEvent.change(screen.getByLabelText('操作确认密码'), { target: { value: 'do-not-retain' } });
    fireEvent.click(screen.getByRole('tab', { name: 'API Key' }));
    await screen.findByRole('button', { name: '创建单 Bot Key' });
    expect(screen.getByLabelText('操作确认密码')).toHaveValue('');
    expect(screen.queryByText('可访问的 Bot')).toBeNull();
    expect(screen.queryByRole('tab', { name: 'Bot 授权' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '退出登录' }));
    await screen.findByRole('heading', { name: '登录 Bot Proxy' });
    expect(management).toHaveBeenCalledWith('auth/logout/', {});
    expect(screen.queryByRole('navigation')).toBeNull();
  });
  it('switches synthetic role scope without claiming authorization', async () => {
    render(<App demo />);
    await screen.findByRole('grid');
    fireEvent.click(screen.getByRole('button', { name: '演示设置' }));
    fireEvent.click(screen.getByRole('combobox', { name: '角色范围演示' }));
    fireEvent.click(screen.getByRole('option', { name: 'Admin' }));
    expect(await screen.findByText(/Admin 演示：仅虚构已授权/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '完成' }));
    await screen.findByRole('grid');
    expect(screen.queryByText(/全平台演示 Bot A/)).not.toBeInTheDocument();
    expect(demoDashboard('24h', 'Admin').events).toBeLessThan(demoDashboard('24h', 'Owner').events);
    for (const window of windows) {
      const data = demoDashboard(window);
      expect(data.buckets).toHaveLength(6);
      expect(data.events).toBe(data.buckets.reduce((sum, row) => sum + row.events, 0));
      expect(Date.parse(data.generated) - Date.parse(data.start)).toBe(data.bucketMinutes * 6 * 60000);
    }
  });
});