import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useQQOverview } from '@/lib/qq-swr'
import { SystemDashboardPage } from './system-dashboard'
import '@/i18n'
import '@testing-library/jest-dom/vitest'

vi.mock('@/lib/qq-swr', () => ({useQQOverview: vi.fn()}))

beforeEach(() => {
  vi.mocked(useQQOverview).mockReturnValue({data: {
    generated_at: '2026-10-25T12:00:00Z', window_hours: 24, bot_count: 1, active_bot_count: 1,
    gateway_worker_count: 1, api_call_count: 80, api_success_count: 70, api_error_count: 10,
    event_count: 60, delivered_count: 55, pending_count: 3, processing_count: 1, failed_count: 1,
    cancelled_count: 0, channels: [{bot: 6, channel: 7, name: '依卡', channel_name: 'Channel A',
      provider_name: 'Provider A', interface_type: 'qq_official_websocket', enabled: true,
      worker_lease_live: true, session_recorded: true, last_http_status: 200, last_call_at: null}],
  }, mutate: vi.fn().mockResolvedValue(undefined), isLoading: false, isValidating: false} as unknown as ReturnType<typeof useQQOverview>)
})

it('renders an independent system dashboard with channels first and truthful status labels', () => {
  render(<SystemDashboardPage/>);
  expect(screen.getByRole('heading', {name: '系统仪表盘'})).toBeInTheDocument();
  expect(screen.getByText('Channels 状态').compareDocumentPosition(screen.getByText('流量与投递')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByText('Channel A')).toBeInTheDocument();
  expect(screen.getByText('Provider A')).toBeInTheDocument();
  expect(screen.getByText('租约有效')).toBeInTheDocument();
  expect(screen.queryByText('在线')).not.toBeInTheDocument();
  expect(screen.getByText('55')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', {name: '7 天'}));
  expect(useQQOverview).toHaveBeenLastCalledWith(168, {refreshInterval: 15000});
});

it('shows errors without fabricating a healthy snapshot', () => {
  vi.mocked(useQQOverview).mockReturnValue({error: new Error('offline'), mutate: vi.fn()} as unknown as ReturnType<typeof useQQOverview>);
  render(<SystemDashboardPage/>);
  expect(screen.getByRole('alert')).toBeInTheDocument();
  expect(screen.queryByText('已响应')).not.toBeInTheDocument();
});
